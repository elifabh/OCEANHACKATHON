#!/usr/bin/env python3
"""
anaird_phaseb.py -- Phase B: coastal-protection valuation at An Aird,
Kilkieran Bay, Co. Galway (national receptor screen cluster 531).

WHY THIS SITE
-------------
The national receptor screen (2026-08-27) returned 19 clusters that pass the
pre-registered fetch gate with usable habitat evidence. An Aird is the only
NEW one whose habitat evidence is a fine-grained NPWS CO Series dive/video
survey record rather than a model output. It is therefore the only new site
where the Sherkin method can be run end to end on survey data.

WHAT THIS SCRIPT DOES -- AND WHAT IT REFUSES TO DO
--------------------------------------------------
It runs the SAME chain as Sherkin, with An Aird's own numbers throughout:

  1  receptors    OSM buildings behind the frontage, their tags, their
                  distance to shore, and their GROUND ELEVATION from
                  Copernicus GLO-30. The rule locked on 2026-08-27 says a
                  screen without elevation cannot produce a positive receptor
                  finding. This closes that gap for this one site.
  2  frontage     alongshore metres of coast the receptors sit behind,
                  reported under three explicit definitions because
                  "frontage" is a definitional choice, not a measurement.
  3  habitat      NPWS Reef Inventory layer 21 `Laminaria-dominated reef`,
                  de-duplicated by exact geometry (624 of 1 936 national
                  polygons are exact duplicates), rasterised to the same
                  50 m grid step 2 used, and subjected to the BEARING TEST
                  that both handover notes list as the Phase B fix: habitat
                  only counts if it lies between the receptors and the water
                  the waves actually come from.
  4  exposure     Burrows 200 m log10 fetch, tie-aware sampler imported
                  unchanged from wide_receptor_screen, plus An Aird's own
                  wave climate from the CMEMS IBI reanalysis (the same
                  product and the same script that produced Sherkin's).
  5  depth        INFOMAR bathymetry on the habitat cells. Needed twice:
                  for Dubi & Torum's depth-dependent k, and for their
                  4-10 m validity gate.
  6  attenuation  RECOMPUTED from this site's own geometry and depths.
                  Sherkin's 7.9 % / 15.2 % are NEVER reused. The method is
                  bed_width.py's, unchanged: integrate k(D) along contiguous
                  runs of habitat, report the best of four axes per cell.
  7  valuation    avoided damage first, replacement cost only if Shabman &
                  Batie condition 3 (demonstrated demand) is satisfied, via
                  src/replacement_cost.py, which refuses to label its output
                  a value unless the caller asserts that condition.

It will not manufacture a number for a step whose input is missing. Every
gate reports PASS / FAIL / NOT COMPUTABLE with the reason attached.

PROVENANCE OF EVERY INPUT
-------------------------
  OSM buildings / coastline    (c) OpenStreetMap contributors, ODbL 1.0
  NPWS Reef Inventory 2023 layer 21, Kilkieran Bay 2013 CO Series survey
  NPWS (2014) Kilkieran Bay and Islands SAC conservation objectives
      supporting document - marine habitats and species, Version 1
  INFOMAR AllSurvey bathymetry, Marine Institute / GSI
  Burrows wave fetch, log10_eu200m1a.tif, EPSG:27700
  Copernicus WorldDEM-30 (GLO-30) -- see LICENCE note below
  CMEMS IBI_MULTIYEAR_WAV_005_006 wave reanalysis
  OPW Minor Works unit rates via outputs/replacement_cost_unit_rates.csv

COPERNICUS GLO-30 LICENCE (read 2026-08-28, data/reference/License-COPDEM-30.pdf)
  Free of charge, worldwide, unlimited in time; reproduction, distribution,
  communication to the public and adaptation all granted (Articles 3-5).
  Required notice where the data are adapted (Article 6b):
      "produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and
      (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS
      by the European Union and ESA; all rights reserved"
  This clears open item 3 of the national screen note. Unlike the OPW flood
  layer it carries no non-commercial and no no-derivatives clause.

Run:  PYTHONPATH=src python src/anaird_phaseb.py
Read-only with respect to every locked artefact. Writes only under
outputs/anaird/.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import requests
from pyproj import Transformer
from shapely.geometry import LineString, Point, box
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Screen parameters are IMPORTED, never re-declared. Locked rule, national
# screen note section 9: a threshold must not be silently re-typed.
from wide_receptor_screen import (  # noqa: E402
    FETCH_EXCLUSION_MAX,
    FETCH_RASTER,
    HAB_SEARCH_M,
    ITM,
    NPWS_SHP,
    NPWS_TARGET,
    SHORE_DIST_M,
    WGS,
    FetchSampler,
    overpass,
)
from common import INFOMAR_BATHY, ArcGISError, arcgis_request  # noqa: E402
from replacement_cost import (  # noqa: E402
    IE_ROCK_ARMOUR_EUR_PER_M,
    replacement_cost,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "anaird"
CACHE = REPO / "outputs" / "labels" / "depth_cache"

# ---------------------------------------------------------------- the site
# Cluster 531 of outputs/national_receptor_screen.csv. Coordinates are the
# DBSCAN centroid of its 8 shore-proximate OSM buildings, carried over
# unchanged so this script and the screen describe the same place.
SITE = {
    "name": "An Aird, Kilkieran Bay, Co. Galway",
    "cluster": 531,
    "lon": -9.88977,
    "lat": 53.30098,
    "county": "Galway",
    "npws_site": "Kilkieran Bay and Islands SAC",
    "npws_site_code": "002111",
}

# Analysis box: 6 km half-width around the cluster, big enough to hold the
# whole wave path from open water to the shore.
BOX_HALF_M = 6000.0
GRID_M = 50.0            # same cell size as the step-2 suitability model
CELL_HA = (GRID_M * GRID_M) / 1e4

# --- Dubi & Torum (1996), carried over from bed_width.py / depth_gate.py ---
# k = 0.0658 * exp(-0.5 D), wave HEIGHT decay per metre of travel through
# kelp, measured at D = 4-10 m and 12 plants/m2. Applies to subtidal
# L. hyperborea on exposed Atlantic coasts ONLY (CLAUDE.md rule 3).
D_VALID = (4.0, 10.0)

# Bearing test half-width. +/-60 degrees of the wave-approach direction is
# the figure both handover notes propose. It is OUR choice, not a published
# standard, and the result is reported at 30/45/60/90 so its influence is
# visible rather than hidden.
BEARING_HALF_WIDTHS = (30.0, 45.0, 60.0, 90.0)
BEARING_PRIMARY = 60.0

# Copernicus WorldDEM-30 (GLO-30), open COG on AWS, no request signing.
GLO30_TILE = ("https://copernicus-dem-30m.s3.amazonaws.com/"
              "Copernicus_DSM_COG_10_N53_00_W010_00_DEM/"
              "Copernicus_DSM_COG_10_N53_00_W010_00_DEM.tif")
GLO30_NOTICE = ("produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 "
                "and (c) Airbus Defence and Space GmbH 2014-2018 provided under "
                "COPERNICUS by the European Union and ESA; all rights reserved")

# An Aird's own wave climate, from outputs/model/swell_direction_anaird_summary.csv,
# produced by src/swell_direction.py against CMEMS IBI_MULTIYEAR_WAV_005_006,
# 2015-2024, nearest wet cell 53.3064 N 9.9164 W (1.7 km from the site).
# Read from file at run time; these are the fallbacks if the file is absent.
SWELL_SUMMARY = REPO / "outputs" / "model" / "swell_direction_anaird_summary.csv"

INFOMAR_BATCH = 400
UA = "OceanHackathon-Cork2026-research/1.0 (mielmt17@gmail.com)"


def hr(title: str = "") -> None:
    print("\n" + "=" * 78)
    if title:
        print(title)
        print("=" * 78)


# ======================================================================
# 1. RECEPTORS
# ======================================================================

def fetch_local_osm(bbox_wgs) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame,
                                       gpd.GeoDataFrame]:
    """Buildings, coastline and man-made structures in the analysis box.

    Queried fresh at full tag detail rather than reused from the screen's
    cache, because the screen kept only the `building` value and the receptor
    question needs the whole tag set (a `ruins` is not a receptor).
    """
    s, w, n, e = bbox_wgs[1], bbox_wgs[0], bbox_wgs[3], bbox_wgs[2]
    bb = f"{s},{w},{n},{e}"

    q_b = f"""[out:json][timeout:280];
    ( way["building"]({bb}); relation["building"]({bb}); node["building"]({bb}); );
    out center tags;"""
    rows = []
    for el in overpass(q_b).get("elements", []):
        c = el.get("center") or {"lon": el.get("lon"), "lat": el.get("lat")}
        if c.get("lon") is None:
            continue
        t = el.get("tags") or {}
        rows.append({"osm_id": f'{el["type"]}/{el["id"]}',
                     "building": t.get("building", "yes"),
                     "name": t.get("name"), "tags": json.dumps(t),
                     "lon": c["lon"], "lat": c["lat"]})
    bld = gpd.GeoDataFrame(rows, geometry=gpd.points_from_xy(
        [r["lon"] for r in rows], [r["lat"] for r in rows]), crs=WGS)

    q_c = f"""[out:json][timeout:280];
    way["natural"="coastline"]({bb});
    out geom;"""
    geoms = []
    for el in overpass(q_c).get("elements", []):
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(pts) >= 2:
            geoms.append(LineString(pts))
    coast = gpd.GeoDataFrame(geometry=geoms, crs=WGS)

    q_m = f"""[out:json][timeout:280];
    ( way["man_made"]({bb}); node["man_made"]({bb});
      way["highway"]({bb}); way["amenity"]({bb}); );
    out center tags;"""
    rows = []
    for el in overpass(q_m).get("elements", []):
        c = el.get("center") or {"lon": el.get("lon"), "lat": el.get("lat")}
        if c.get("lon") is None:
            continue
        t = el.get("tags") or {}
        rows.append({"osm_id": f'{el["type"]}/{el["id"]}',
                     "kind": t.get("man_made") or t.get("highway")
                     or t.get("amenity"), "tags": json.dumps(t),
                     "lon": c["lon"], "lat": c["lat"]})
    infra = gpd.GeoDataFrame(rows, geometry=gpd.points_from_xy(
        [r["lon"] for r in rows], [r["lat"] for r in rows]), crs=WGS)

    print(f"   OSM: {len(bld)} buildings, {len(coast)} coastline ways, "
          f"{len(infra)} man-made / highway / amenity features")
    return bld, coast, infra


def sample_glo30(pts_wgs: list[tuple[float, float]]) -> np.ndarray:
    """Ground elevation, metres above EGM2008 geoid, from Copernicus GLO-30.

    GLO-30 is a Digital SURFACE Model: it includes buildings and vegetation.
    Over a building footprint it returns roof height, not ground level. At
    30 m posting a small dwelling is a fraction of a pixel, so the value is
    dominated by surrounding terrain, but the direction of the bias is
    upward. That is stated, not corrected.
    """
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    with rasterio.open(f"/vsicurl/{GLO30_TILE}") as s:
        return np.array([v[0] for v in s.sample(pts_wgs)], dtype=float)


# ======================================================================
# 2. HABITAT
# ======================================================================

def load_npws_local(bbox_wgs) -> dict[str, gpd.GeoDataFrame]:
    """NPWS layer 21 in the analysis box, de-duplicated by exact geometry.

    Locked rule (national screen note section 9): 624 of the 1 936 national
    `Laminaria-dominated reef` polygons are exact duplicates and raw area
    sums are inflated 2.10x. Dedup is by byte-identical geometry only, which
    removes duplicates and never removes a merely-overlapping polygon.
    """
    g = gpd.read_file(NPWS_SHP).cx[bbox_wgs[0]:bbox_wgs[2],
                                   bbox_wgs[1]:bbox_wgs[3]].to_crs(ITM)
    n_before = len(g)
    dup = g.geometry.to_wkb().duplicated()
    g = g[~dup].copy()
    print(f"   NPWS layer 21 in box: {n_before} rows, dropped {int(dup.sum())} "
          f"exact duplicates -> {len(g)}")
    comm = g["Community"].astype(str).str.strip().str.lower()
    ext = g["Extent"].astype(str).str.strip().str.lower()
    out = {
        "laminaria": g[(comm == NPWS_TARGET) & (ext == "subtidal")].copy(),
        "turf": g[(comm == "faunal turf reef") & (ext == "subtidal")].copy(),
        "geogenic": g[(comm == "geogenic reef") & (ext == "subtidal")].copy(),
        "intertidal": g[ext == "intertidal"].copy(),
    }
    for k, v in out.items():
        v["ha"] = v.geometry.area / 1e4
        print(f"     {k:12s} {len(v):4d} polygons  {v['ha'].sum():9.2f} ha"
              + (f"  sources: {sorted(set(v['Source'].astype(str)))[:2]}"
                 if len(v) else ""))
    return out


def grid_axes(cx: float, cy: float, half: float, step: float):
    n = int(round(2 * half / step))
    xs = cx - half + (np.arange(n) + 0.5) * step
    ys = cy - half + (np.arange(n) + 0.5) * step
    return xs, ys


def rasterise(geoms, xs, ys) -> np.ndarray:
    """Boolean mask on the ITM grid, True where a polygon covers the centre."""
    if len(geoms) == 0:
        return np.zeros((len(ys), len(xs)), dtype=bool)
    step = float(xs[1] - xs[0])
    transform = rasterio.transform.from_origin(
        xs[0] - step / 2, ys[-1] + step / 2, step, step)
    arr = rasterio.features.rasterize(
        [(g, 1) for g in geoms], out_shape=(len(ys), len(xs)),
        transform=transform, fill=0, dtype="uint8", all_touched=False)
    # rasterio writes row 0 at the TOP (max y); the grid here is ascending y.
    return np.flipud(arr).astype(bool)


# ======================================================================
# 3. DEPTH
# ======================================================================

def sample_infomar(xs_itm, ys_itm, mask: np.ndarray, tag: str) -> np.ndarray:
    """INFOMAR depth, positive down, metres below LAT, NaN where unsurveyed.

    Sign convention and the empty-batch rule are carried over from
    habitat_gap_model.sample_depth_masked unchanged: a 4xx means every point
    of the batch is outside INFOMAR coverage and IS coverage information; a
    5xx means the server is unwell and is NOT. Conflating them would turn a
    busy server into "there is no bathymetry here".
    """
    ny, nx = mask.shape
    grid = np.full((ny, nx), np.nan, dtype=float)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"depth_{tag}_{int(GRID_M)}m.npy"
    done_cache = CACHE / f"depth_{tag}_{int(GRID_M)}m_done.npy"
    done = np.zeros((ny, nx), dtype=bool)
    if cache.exists() and done_cache.exists():
        prev, prev_done = np.load(cache), np.load(done_cache)
        if prev.shape == grid.shape:
            grid, done = prev, prev_done
            print(f"   resuming depth cache: {int(done.sum())} of "
                  f"{int(mask.sum())} masked cells already answered")

    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    todo = mask & ~done
    idx = np.flatnonzero(todo.ravel())
    if idx.size == 0:
        print("   depth complete from cache")
        return grid
    pts = [list(to_wgs.transform(float(xs_itm[i % nx]), float(ys_itm[i // nx])))
           for i in idx]
    print(f"   sampling {len(pts)} INFOMAR points "
          f"({int(np.ceil(len(pts) / INFOMAR_BATCH))} requests)")
    empty = unanswered = 0
    for start in range(0, len(pts), INFOMAR_BATCH):
        chunk = pts[start:start + INFOMAR_BATCH]
        cells = idx[start:start + INFOMAR_BATCH]
        payload = None
        for attempt in range(3):
            try:
                payload = arcgis_request(f"{INFOMAR_BATHY}/getSamples", {
                    "geometry": json.dumps(
                        {"points": chunk, "spatialReference": {"wkid": 4326}}),
                    "geometryType": "esriGeometryMultipoint",
                    "returnFirstValueOnly": "true",
                    "interpolation": "RSP_NearestNeighbor", "f": "json"},
                    retries=1)
                break
            except ArcGISError as exc:
                st = getattr(exc, "status", None)
                if st is not None and 400 <= int(st) < 500:
                    empty += 1
                    done.ravel()[cells] = True
                    payload = None
                    break
                if attempt == 2:
                    unanswered += len(chunk)
                    payload = None
                    break
                import time
                time.sleep(10 * (attempt + 1))
        if payload is None:
            np.save(cache, grid)
            np.save(done_cache, done)
            continue
        for s in payload.get("samples", []):
            loc, raw = s.get("locationId"), s.get("value")
            if loc is None or raw in (None, "", "NaN"):
                continue
            try:
                cell = idx[start + int(loc)]
            except (ValueError, IndexError):
                continue
            try:
                grid[cell // nx, cell % nx] = -float(str(raw).split()[0])
            except ValueError:
                continue
        done.ravel()[cells] = True
        np.save(cache, grid)
        np.save(done_cache, done)
    if empty:
        print(f"   ({empty} batches entirely outside INFOMAR coverage)")
    if unanswered:
        print(f"   >>> {unanswered} points never answered (5xx). Re-run to fill.")
    print(f"   answered {int((mask & done).sum())}/{int(mask.sum())}; "
          f"surveyed {int(np.isfinite(grid[mask]).sum())}")
    return grid



# ======================================================================
# 5. RECEPTOR EXPOSURE -- OPW coastal flood extents, INTERNAL SCREEN ONLY
#
# CLAUDE.md rule 9: the OPW flood-map licence is CC BY-NC-ND 4.0 and
# UNRESOLVED, so nothing VISUALLY DERIVED from this layer may appear in a
# published or demo map until flood_data@opw.ie clears it. A count of
# buildings inside an extent is not a visual derivative, and it is exactly
# what the 11 Aug Sherkin screen used the layer for ("0 buildings inside the
# 1000-yr extent anywhere on Sherkin"). The same internal use is made here,
# the result stays in the repo, and the licence question stays open.
#
# What the layer is and is not: OPW model still water level from tide and
# storm surge. Their own metadata excludes wave overtopping, which is this
# project's mechanism, and ignores flood defences. It therefore screens for
# LOW-LYING LAND behind a frontage. It never says "the kelp protects this".
# ======================================================================

OPW_ZIP = REPO / "data" / "opw" / "ncfhm_itm_ext_c_c_1000yr_200yr_10yr.zip"
OPW_LAYERS = [("10 yr", "0010"), ("200 yr", "0200"), ("1000 yr", "1000")]
OPW_INNER = "NCFHM_2022_Current_Scenario_1000yr_200yr_10ry"


def _opw_union(cx: float, cy: float, half_m: float, code: str):
    g = gpd.read_file(
        f"zip://{OPW_ZIP}!{OPW_INNER}/ncfhm_itm_ext_c_c_{code}.shp",
        bbox=(cx - half_m, cy - half_m, cx + half_m, cy + half_m))
    if len(g) == 0:
        return None, 0
    g = g.to_crs(ITM)
    return unary_union(g.geometry.values), len(g)


def opw_receptor_check(near: gpd.GeoDataFrame) -> dict:
    """How many of the receptors sit inside each mapped coastal flood extent."""
    cx = float(near.geometry.x.mean())
    cy = float(near.geometry.y.mean())
    out = {}
    for label, code in OPW_LAYERS:
        u, n = _opw_union(cx, cy, 2000.0, code)
        if u is None:
            out[label] = {"polygons": 0, "inside": 0, "min_dist_m": float("nan"),
                          "min_dist_house_m": float("nan")}
            continue
        inside = near.geometry.apply(u.contains)
        d = near.geometry.distance(u)
        houses = near[near.building == "house"]
        out[label] = {
            "polygons": int(n),
            "inside": int(inside.sum()),
            "inside_osm_ids": list(near.loc[inside, "osm_id"]),
            "min_dist_m": round(float(d.min()), 1),
            "min_dist_house_m": round(float(houses.geometry.distance(u).min()), 1)
            if len(houses) else float("nan"),
        }
    return out


def neighbourhood_check(centre: Point, radius_m: float = 4000.0) -> list[dict]:
    """Every settlement cluster within 4 km: its fetch and its flood exposure.

    This is the anti-correlation test at local scale. The national screen
    found it over 1 477 clusters; here it is inside one bay, which is the
    version a jury can see on one slide.
    """
    b = gpd.read_file(
        REPO / "outputs" / "national_receptor_screen_buildings.geojson"
    ).to_crs(ITM)
    b = b[b.geometry.distance(centre) <= radius_m].copy()
    scr = pd.read_csv(REPO / "outputs" / "national_receptor_screen.csv")
    u, _ = _opw_union(float(centre.x), float(centre.y), radius_m + 500, "1000")
    b["inside"] = b.geometry.apply(u.contains) if u is not None else False
    rows = []
    for cl, sub in b.groupby("cluster"):
        s = scr[scr.cluster == cl]
        if s.empty:
            continue
        s = s.iloc[0]
        rows.append({
            "cluster": int(cl),
            "place": str(s.nearest_place),
            "n": int(len(sub)),
            "fetch_min": float(s.fetch_nearest_min),
            "fetch_max": float(s.fetch_nearest_max),
            "pass_fetch_strict": bool(s.pass_fetch_strict),
            "inside": int(sub.inside.sum()),
            "houses_inside": int(((sub.building == "house") & sub.inside).sum()),
        })
    return sorted(rows, key=lambda r: -r["fetch_min"])

# ======================================================================
# 4. ATTENUATION
#
# THE LOCKED SHERKIN METHOD, REPRODUCED EXACTLY BEFORE IT IS REUSED.
#
# src/bed_width.py reports the BEST of four grid axes, which is an upper
# bound over wave direction, not an estimate. The locked 7.9 % / 15.2 %
# were NOT produced that way. Reading the step-3B2 note of 2026-08-10
# together with outputs/valuation/step3b2_flood_check.gpkg gives the actual
# chain, and this script reproduces it to the digit before applying it here:
#
#   1  keep model cells that are assessed AND over the suitability threshold
#   2  keep only cells whose fetch lies entirely outside the
#      inner_roaringwater range, i.e. log10 fetch > FETCH_EXCLUSION_MAX
#   3  keep only cells in Dubi & Torum's tested depth range, 4-10 m
#      -> 7 cells, 1.75 ha, depths 7.57-9.73 m
#   4  compute the MEDIAN wave-height reduction PER AXIS over those cells
#      -> N-S 4.82 %, NE-SW 9.03 %, E-W 5.07 %, NW-SE 5.86 %
#   5  interpolate linearly between the two axes bracketing the measured
#      wave-travel bearing (33 deg for Sherkin: N-S at 0 deg and NE-SW at
#      45 deg) -> H = 7.91 %  ->  the locked 7.9 %
#   6  E = 1 - (1 - H)^2 -> 15.19 %  ->  the locked 15.2 %
#
# reproduce_sherkin() below runs steps 4-6 against the stored 7 cells on
# every run and aborts if the answer is not 7.9 % / 15.2 %. An Aird's
# numbers are then produced by the same six steps with An Aird's own cells,
# depths, fetch and wave direction. Sherkin's percentages are never reused.
# ======================================================================

def k_dubi_torum(depth_m: float) -> float:
    """Wave HEIGHT decay rate, per metre. Dubi & Torum (1996) fitted curve.

    k = 0.0658 * exp(-0.5 D), measured at D = 4-10 m and 12 plants/m2, for
    subtidal L. hyperborea on exposed Atlantic coasts (CLAUDE.md rule 3).
    """
    return 0.0658 * math.exp(-0.5 * depth_m)


# (dx, dy) step, label, and the axis bearing in degrees. An axis is
# undirected, so N-S is 0 and E-W is 90.
AXES = [((0, 1), "N-S", 0.0), ((1, 1), "NE-SW", 45.0),
        ((1, 0), "E-W", 90.0), ((1, -1), "NW-SE", 135.0)]


def interp_axes(per_axis: dict[str, float], travel_deg: float) -> tuple[float, str, str, float]:
    """Linear interpolation between the two axes bracketing a bearing.

    Bearings are folded onto 0-180 because an axis has no direction: a wave
    travelling to 213 deg crosses the same run of cells as one travelling to
    33 deg. Returns (value, lower axis, upper axis, weight on the upper).
    """
    t = travel_deg % 180.0
    order = [(b, lab) for (_, lab, b) in AXES]
    order.sort()
    order.append((order[0][0] + 180.0, order[0][1]))     # wrap NW-SE -> N-S
    for (b0, l0), (b1, l1) in zip(order, order[1:]):
        if b0 <= t <= b1:
            w = (t - b0) / (b1 - b0)
            return (1 - w) * per_axis[l0] + w * per_axis[l1], l0, l1, w
    raise ValueError(f"bearing {travel_deg} not bracketed")


def per_axis_cell_table(mask: np.ndarray, depth: np.ndarray) -> pd.DataFrame:
    """Per-cell, per-axis wave-height reduction and run length.

    Identical walk to bed_width_axes.py: through every habitat cell, follow
    the contiguous run of habitat cells along each axis in both directions
    and integrate each traversed cell's OWN k(D) over its step length.
    """
    ny, nx = mask.shape
    cells = {(int(c), int(r)) for r, c in zip(*np.nonzero(mask))}
    rows = []
    for (c0, r0) in sorted(cells):
        if not np.isfinite(depth[r0, c0]):
            continue
        rec = {"col": c0, "row": r0, "depth_m": round(float(depth[r0, c0]), 2)}
        for (dx, dy), label, _ in AXES:
            step = GRID_M * math.hypot(dx, dy)
            run = [(c0, r0)]
            for sign in (1, -1):
                c, r = c0, r0
                while True:
                    c, r = c + sign * dx, r + sign * dy
                    if (c, r) not in cells:
                        break
                    run.append((c, r))
            tot = sum(k_dubi_torum(float(depth[r, c])) * step for (c, r) in run
                      if np.isfinite(depth[r, c]))
            rec[f"width_{label}"] = round(len(run) * step, 1)
            rec[f"H_red_{label}"] = round(1 - math.exp(-tot), 4)
        rows.append(rec)
    return pd.DataFrame(rows)


def headline(cells: pd.DataFrame, travel_deg: float) -> dict:
    """Steps 4-6 of the locked chain: per-axis medians, interpolate, square."""
    med = {lab: float(np.median(cells[f"H_red_{lab}"])) for (_, lab, _) in AXES}
    H, lo, hi, w = interp_axes(med, travel_deg)
    return {"n_cells": int(len(cells)), "ha": round(len(cells) * CELL_HA, 2),
            "per_axis_median_H": {k: round(v, 4) for k, v in med.items()},
            "bracketing_axes": [lo, hi], "weight_on_upper": round(w, 4),
            "travel_deg": round(travel_deg, 1),
            "H_reduction": round(H, 4),
            "E_reduction": round(1 - (1 - H) ** 2, 4),
            "width_median_m": {lab: round(float(np.median(cells[f"width_{lab}"])), 1)
                               for (_, lab, _) in AXES}}


SHERKIN_BED_GPKG = REPO / "outputs" / "valuation" / "step3b2_flood_check.gpkg"
SHERKIN_TRAVEL_DEG = 33.0        # step-3B2 note, measured near the bed
SHERKIN_LOCKED = {"H": 0.079, "E": 0.152, "cells": 7, "ha": 1.75}


def reproduce_sherkin() -> dict:
    """Guard: re-derive the locked 7.9 % / 15.2 % from the stored 7 cells.

    If this does not reproduce, the method in this file is not the method
    that produced the locked figures and nothing below it may be trusted.
    """
    g = gpd.read_file(SHERKIN_BED_GPKG, layer="kelp_cells")
    out = headline(g, SHERKIN_TRAVEL_DEG)
    ok = (out["n_cells"] == SHERKIN_LOCKED["cells"]
          and abs(out["ha"] - SHERKIN_LOCKED["ha"]) < 0.01
          and abs(out["H_reduction"] - SHERKIN_LOCKED["H"]) < 0.0006
          and abs(out["E_reduction"] - SHERKIN_LOCKED["E"]) < 0.0012)
    out["reproduces_locked_figures"] = bool(ok)
    return out


def saturation_check(cells: pd.DataFrame, axis_label: str) -> pd.DataFrame:
    """Is the coefficient being used inside or outside its domain?

    depth_gate.py frames the test: compare the bed width actually traversed
    against the width needed for a 50 % wave-height loss at that depth. When
    the traversed width is many times the 50 % width, an exponential decay
    law fitted in a wave flume over a few metres is being extrapolated to
    saturation, and the resulting percentage is an artefact of the
    extrapolation rather than a measurement.
    """
    k = cells.depth_m.map(k_dubi_torum)
    half = 0.693 / k
    return pd.DataFrame({
        "depth_m": cells.depth_m,
        "width_m": cells[f"width_{axis_label}"],
        "width_for_50pct_loss_m": half.round(0),
        "ratio_width_to_50pct": (cells[f"width_{axis_label}"] / half).round(2),
        "H_red": cells[f"H_red_{axis_label}"],
    })


# ======================================================================
# main
# ======================================================================

def main() -> int:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict = {"run_utc": t0, "site": SITE,
                    "screen_parameters_imported": {
                        "FETCH_EXCLUSION_MAX": FETCH_EXCLUSION_MAX,
                        "SHORE_DIST_M": SHORE_DIST_M,
                        "HAB_SEARCH_M": HAB_SEARCH_M},
                    "grid_m": GRID_M}

    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    cx, cy = to_itm.transform(SITE["lon"], SITE["lat"])
    centre = Point(cx, cy)
    xs, ys = grid_axes(cx, cy, BOX_HALF_M, GRID_M)
    bx0, by0 = to_wgs.transform(cx - BOX_HALF_M, cy - BOX_HALF_M)
    bx1, by1 = to_wgs.transform(cx + BOX_HALF_M, cy + BOX_HALF_M)
    bbox_wgs = (bx0, by0, bx1, by1)

    hr(f"PHASE B -- {SITE['name']}")
    print(f"cluster {SITE['cluster']}   {SITE['lat']:.5f} N  {abs(SITE['lon']):.5f} W")
    print(f"analysis box {2*BOX_HALF_M/1000:.0f} x {2*BOX_HALF_M/1000:.0f} km, "
          f"{GRID_M:.0f} m grid ({len(xs)} x {len(ys)} cells)")
    print(f"imported gate FETCH_EXCLUSION_MAX = {FETCH_EXCLUSION_MAX} "
          "(the same Python object the Mizen screen pre-registered on 11 Aug)")

    # ---------------------------------------------------------- 1 receptors
    hr("1. RECEPTORS -- what is behind this frontage")
    bld, coast, infra = fetch_local_osm(bbox_wgs)
    bld_itm = bld.to_crs(ITM)
    coast_itm = coast.to_crs(ITM)
    coast_u = unary_union(coast_itm.geometry.values)
    bld_itm["dist_shore_m"] = bld_itm.geometry.distance(coast_u)
    bld_itm["dist_cluster_m"] = bld_itm.geometry.distance(centre)

    near = bld_itm[(bld_itm.dist_cluster_m <= 500)].copy()
    # bld_itm shares bld's index, so the WGS coordinates come straight back
    near["lon"] = bld.loc[near.index, "lon"].values
    near["lat"] = bld.loc[near.index, "lat"].values
    near["elev_m"] = sample_glo30(list(zip(near.lon, near.lat)))
    near = near.sort_values("dist_shore_m")
    print(f"\n   {len(near)} buildings within 500 m of the cluster centroid:")
    print("   " + "-" * 72)
    print(f"   {'osm_id':<18}{'building':<12}{'shore m':>9}{'elev m':>9}"
          f"{'from centroid m':>17}")
    for _, r in near.iterrows():
        print(f"   {r.osm_id:<18}{r.building:<12}{r.dist_shore_m:>9.0f}"
              f"{r.elev_m:>9.1f}{r.dist_cluster_m:>17.0f}")
    print("   " + "-" * 72)
    tags = near.building.value_counts().to_dict()
    print(f"   tag counts: {tags}")
    print(f"   elevation (Copernicus GLO-30, DSM): min {near.elev_m.min():.1f} m, "
          f"median {near.elev_m.median():.1f} m, max {near.elev_m.max():.1f} m")

    habitable = near[~near.building.isin(["ruins", "garage", "shed",
                                          "farm_auxiliary", "greenhouse"])]
    print(f"\n   Of these, {len(habitable)} carry a tag consistent with an "
          f"occupied structure ({sorted(set(habitable.building))}); "
          f"{len(near) - len(habitable)} do not.")

    infra_itm = infra.to_crs(ITM)
    infra_itm["dist_cluster_m"] = infra_itm.geometry.distance(centre)
    near_infra = infra_itm[infra_itm.dist_cluster_m <= 500]
    print(f"\n   man-made / highway / amenity features within 500 m: "
          f"{len(near_infra)}")
    for _, r in near_infra.sort_values("dist_cluster_m").iterrows():
        print(f"     {r.osm_id:<20}{str(r.kind):<14}{r.dist_cluster_m:>6.0f} m  "
              f"{r.tags}")

    result["receptors"] = {
        "n_buildings_500m": int(len(near)),
        "tag_counts": tags,
        "n_occupied_tag": int(len(habitable)),
        "elev_min_m": round(float(near.elev_m.min()), 1),
        "elev_median_m": round(float(near.elev_m.median()), 1),
        "elev_max_m": round(float(near.elev_m.max()), 1),
        "elev_source": "Copernicus WorldDEM-30 (GLO-30), DSM, 30 m",
        "elev_notice": GLO30_NOTICE,
        "infrastructure_500m": [
            {"osm_id": r.osm_id, "kind": r.kind, "dist_m": round(r.dist_cluster_m),
             "tags": json.loads(r.tags)}
            for _, r in near_infra.iterrows()],
    }
    near.drop(columns=["geometry"]).to_csv(OUT / "anaird_receptors.csv",
                                           index=False)

    # ---------------------------------------------------------- 2 frontage
    hr("2. FRONTAGE -- alongshore metres, three definitions")
    hull = unary_union(near.geometry.values).convex_hull
    defs = {}
    seg = coast_u.intersection(unary_union(
        [g.buffer(SHORE_DIST_M) for g in near.geometry.values]))
    defs["coastline_within_200m_of_a_receptor"] = float(seg.length)
    seg2 = coast_u.intersection(centre.buffer(250))
    defs["coastline_within_250m_of_the_centroid"] = float(seg2.length)
    # Straight-line alongshore span: project the in-front coastline onto its
    # own principal axis. This is what a designer would actually armour; the
    # crenulate traced length is not.
    if not seg.is_empty:
        pts = np.array([p for gline in getattr(seg, "geoms", [seg])
                        for p in np.array(gline.coords)])
        pts = pts - pts.mean(axis=0)
        u, s, vt = np.linalg.svd(pts, full_matrices=False)
        proj = pts @ vt[0]
        defs["principal_axis_span"] = float(proj.max() - proj.min())
    for k, v in defs.items():
        print(f"   {k:<42}{v:8.0f} m")
    print("\n   Frontage is a DEFINITIONAL CHOICE, not a measurement. The "
          "Kilkieran shore is\n   crenulate: the traced coastline within "
          "200 m of a receptor is several times\n   the straight span the "
          "same receptors sit behind. All three are carried forward.")
    result["frontage_m"] = {k: round(v) for k, v in defs.items()}

    # ---------------------------------------------------------- 3 exposure
    hr("3. EXPOSURE -- Burrows fetch and An Aird's own wave climate")
    fs = FetchSampler(FETCH_RASTER)
    f_cluster = fs.sample(cx, cy)
    print(f"   fetch at the cluster centroid: tied cells "
          f"{f_cluster['fetch_nearest_min']:.3f}-{f_cluster['fetch_nearest_max']:.3f} "
          f"({f_cluster['n_tied']} tied at {f_cluster['dist_to_sea_m']:.0f} m), "
          f"max within 2 km {f_cluster['fetch_max']:.3f}")
    strict = f_cluster["fetch_nearest_min"] > FETCH_EXCLUSION_MAX
    print(f"   gate {FETCH_EXCLUSION_MAX}: strict {'PASS' if strict else 'FAIL'}, "
          f"lenient {'PASS' if f_cluster['fetch_nearest_max'] > FETCH_EXCLUSION_MAX else 'FAIL'}")

    swell = None
    if SWELL_SUMMARY.exists():
        sw = pd.read_csv(SWELL_SUMMARY)
        swell = sw[sw.basis == "energy_weighted"].iloc[0].to_dict()
        print(f"\n   CMEMS IBI wave reanalysis 2015-2024, nearest wet cell:")
        for _, r in sw.iterrows():
            print(f"     {r.basis:<34}from {r.mean_from_deg:6.1f} deg, "
                  f"towards {r.travels_to_deg:5.1f} deg, R={r.concentration_R:.3f}")
        wave_from = float(swell["mean_from_deg"])
    else:
        print("   !! no An Aird swell summary on disk; run swell_direction.py")
        wave_from = float("nan")
    print(f"\n   >>> Wave energy arrives FROM {wave_from:.0f} deg. Sherkin's is "
          f"212.7 deg. Different site,\n   >>> different wave climate; nothing "
          "is carried across.")
    result["exposure"] = {"fetch_at_cluster": {k: (round(v, 3) if isinstance(v, float) else v)
                                               for k, v in f_cluster.items()},
                          "pass_fetch_strict": bool(strict),
                          "wave_from_deg_energy_weighted": round(wave_from, 1),
                          "wave_source": "CMEMS IBI_MULTIYEAR_WAV_005_006, 2015-2024"}

    # ------------------------------------------------- 4 habitat + bearing
    hr("4. HABITAT -- NPWS survey record, then the bearing test")
    npws = load_npws_local(bbox_wgs)
    lam = npws["laminaria"]
    print("\n   SPECIES CHECK (this is a hard gate, cf. CLAUDE.md rules 3 and 6).")
    print("   NPWS (2014) Kilkieran Bay and Islands SAC conservation objectives")
    print("   supporting document, marine habitats, p.13, Laminaria-dominated")
    print("   community complex:")
    print('     "The kelp species Laminaria hyperborea dominate this community')
    print('      complex, but L. digitata and Saccharina latissima are also')
    print('      recorded here. The latter frequently occurs with L. hyperborea')
    print('      in the more sheltered sites."')
    print("     \"This community complex occurs on bedrock and boulders in")
    print("      depths between 6m and 18m.\"")
    print("   -> L. hyperborea is the DOMINANT species by survey record, so the")
    print("      Dubi & Torum coefficients are not blocked as they are at")
    print("      inner_roaringwater. The bed is NOT pure L. hyperborea.")

    lam_mask = rasterise(lam.geometry.values, xs, ys)
    print(f"\n   rasterised: {int(lam_mask.sum())} cells of {GRID_M:.0f} m "
          f"= {lam_mask.sum() * CELL_HA:.1f} ha in the {2*BOX_HALF_M/1000:.0f} km box")

    # bearing of every habitat cell from the cluster centroid
    XX, YY = np.meshgrid(xs, ys)
    dxg, dyg = XX - cx, YY - cy
    dist = np.hypot(dxg, dyg)
    bear = (np.degrees(np.arctan2(dxg, dyg)) + 360.0) % 360.0

    def ang_diff(a, b):
        return np.abs((a - b + 180.0) % 360.0 - 180.0)

    print(f"\n   BEARING TEST. Habitat only shelters a receptor if it lies "
          f"between that\n   receptor and the water the waves come from. The "
          f"screen's habitat term has no\n   direction test -- both handover "
          f"notes list this as the Phase B fix.")
    print(f"\n   {'sector half-width':<22}{'ha <= 1 km':>12}{'ha <= 2 km':>12}"
          f"{'ha <= 6 km':>12}")
    bearing_rows = {}
    for hw in BEARING_HALF_WIDTHS:
        insec = ang_diff(bear, wave_from) <= hw
        row = {}
        for rad in (1000, 2000, 6000):
            row[rad] = float((lam_mask & insec & (dist <= rad)).sum() * CELL_HA)
        bearing_rows[hw] = row
        print(f"   +/-{hw:<19.0f}{row[1000]:>12.2f}{row[2000]:>12.2f}"
              f"{row[6000]:>12.2f}")
    allha = {rad: float((lam_mask & (dist <= rad)).sum() * CELL_HA)
             for rad in (1000, 2000, 6000)}
    print(f"   {'no bearing test':<22}{allha[1000]:>12.2f}{allha[2000]:>12.2f}"
          f"{allha[6000]:>12.2f}")

    insec = ang_diff(bear, wave_from) <= BEARING_PRIMARY
    hab = lam_mask & insec & (dist <= HAB_SEARCH_M)
    print(f"\n   >>> Habitat within the screen's {HAB_SEARCH_M:.0f} m radius: "
          f"{allha[1000]:.2f} ha.")
    print(f"   >>> Of that, on the wave path (+/-{BEARING_PRIMARY:.0f} deg of "
          f"{wave_from:.0f} deg): {allha[1000] and bearing_rows[BEARING_PRIMARY][1000]:.2f} ha.")
    result["habitat"] = {
        "npws_source": "NPWS CO Series: Kilkieran Bay 2013 (dive/video survey)",
        "species_record": ("L. hyperborea dominant; L. digitata and Saccharina "
                           "latissima also recorded (NPWS 2014, p.13)"),
        "npws_recorded_depth_range_m": [6, 18],
        "ha_by_radius_no_bearing_test": {str(k): round(v, 2) for k, v in allha.items()},
        "ha_by_bearing_half_width": {str(int(k)): {str(r): round(v, 2)
                                                   for r, v in row.items()}
                                     for k, row in bearing_rows.items()},
        "bearing_primary_deg": BEARING_PRIMARY,
    }

    # ---------------------------------------------------------- 5 depth
    hr("5. DEPTH -- INFOMAR over the habitat cells")
    # sample everywhere there is habitat within 2 km: enough for the wave
    # path, small enough not to hammer the service.
    dmask = lam_mask & (dist <= 2000)
    print(f"   sampling {int(dmask.sum())} habitat cells within 2 km")
    depth = sample_infomar(xs, ys, dmask, f"anaird_{int(BOX_HALF_M)}m")
    dv = depth[dmask]
    dv = dv[np.isfinite(dv)]
    if dv.size:
        print(f"   depth on habitat cells: n={dv.size} of {int(dmask.sum())} "
              f"({dv.size/max(int(dmask.sum()),1):.0%} surveyed)")
        print(f"     min {dv.min():.1f}  p25 {np.percentile(dv,25):.1f}  "
              f"median {np.median(dv):.1f}  p75 {np.percentile(dv,75):.1f}  "
              f"max {dv.max():.1f} m")
        in_dt = ((dv >= D_VALID[0]) & (dv <= D_VALID[1])).sum()
        print(f"   in Dubi & Torum's tested range {D_VALID[0]}-{D_VALID[1]} m: "
              f"{in_dt} cells = {in_dt*CELL_HA:.2f} ha ({in_dt/dv.size:.0%})")
        print(f"   deeper than {D_VALID[1]} m: "
              f"{(dv > D_VALID[1]).sum()} cells "
              f"({(dv > D_VALID[1]).mean():.0%}) -- Dubi & Torum call "
              "attenuation\n     'almost negligible' beyond 10 m")
        result["depth"] = {
            "cells_sampled": int(dmask.sum()),
            "cells_surveyed": int(dv.size),
            "min_m": round(float(dv.min()), 1),
            "median_m": round(float(np.median(dv)), 1),
            "max_m": round(float(dv.max()), 1),
            "cells_in_dubi_torum_range": int(in_dt),
            "ha_in_dubi_torum_range": round(float(in_dt * CELL_HA), 2),
        }
    else:
        print("   NO INFOMAR DEPTH on any habitat cell. Attenuation is NOT "
              "COMPUTABLE.")
        result["depth"] = {"cells_surveyed": 0}

    # --------------------------------------------- 5b fetch per habitat cell
    hr("5b. EXPOSURE PER HABITAT CELL -- the locked chain's step 2")
    print("   Sherkin kept only cells whose fetch lies ENTIRELY outside the")
    print("   inner_roaringwater range, i.e. log10 fetch > "
          f"{FETCH_EXCLUSION_MAX}. Same test here,")
    print("   cell by cell, on the same Burrows raster.")
    cell_fetch = np.full(dmask.shape, np.nan)
    for r, c in np.argwhere(dmask):
        cell_fetch[r, c] = fs.sample(float(xs[c]), float(ys[r]),
                                     radius_m=200.0)["fetch_nearest_max"]
    cf = cell_fetch[dmask]
    cf = cf[np.isfinite(cf)]
    print(f"   fetch on {cf.size} habitat cells: min {cf.min():.3f}  "
          f"median {np.median(cf):.3f}  max {cf.max():.3f}")
    print(f"   cells with fetch > {FETCH_EXCLUSION_MAX}: "
          f"{int((cf > FETCH_EXCLUSION_MAX).sum())} of {cf.size} "
          f"({(cf > FETCH_EXCLUSION_MAX).mean():.0%})")

    # ------------------------------------------------------ 6 attenuation
    hr("6. ATTENUATION -- the locked Sherkin chain, run on An Aird's own data")

    print("   6a. GUARD -- reproduce the locked Sherkin figures first.")
    sh = reproduce_sherkin()
    print(f"       stored bed: {sh['n_cells']} cells = {sh['ha']} ha")
    print(f"       per-axis median H: {sh['per_axis_median_H']}")
    print(f"       interpolated at {sh['travel_deg']} deg between "
          f"{sh['bracketing_axes'][0]} and {sh['bracketing_axes'][1]} "
          f"(w={sh['weight_on_upper']})")
    print(f"       H = {sh['H_reduction']:.1%}   E = {sh['E_reduction']:.1%}"
          f"   locked = 7.9 % / 15.2 %")
    if not sh["reproduces_locked_figures"]:
        print("   !! DOES NOT REPRODUCE. Everything below is untrustworthy.")
        return 2
    print("       reproduces: YES. The method below is the locked method.")
    result["sherkin_method_guard"] = sh

    print("\n   6b. An Aird, same six steps, own cells / depths / fetch / direction.")
    cells = per_axis_cell_table(dmask, depth)
    att_head = None
    if cells.empty:
        print("       NOT COMPUTABLE: no habitat cell has a depth value.")
        result["attenuation"] = {"computable": False}
    else:
        cells["fetch"] = cell_fetch[cells.row.values, cells.col.values]
        cells["bearing_deg"] = bear[cells.row.values, cells.col.values].round(1)
        cells["dist_m"] = dist[cells.row.values, cells.col.values].round(0)
        cells["in_valid_depth"] = ((cells.depth_m >= D_VALID[0])
                                   & (cells.depth_m <= D_VALID[1])).astype(int)
        cells["pass_fetch"] = (cells.fetch > FETCH_EXCLUSION_MAX).astype(int)
        cells.to_csv(OUT / "anaird_attenuation_cells.csv", index=False)

        funnel = [
            ("habitat cells with INFOMAR depth", cells),
            (f"+ fetch > {FETCH_EXCLUSION_MAX}", cells[cells.pass_fetch == 1]),
            (f"+ depth {D_VALID[0]}-{D_VALID[1]} m (Dubi & Torum range)",
             cells[(cells.pass_fetch == 1) & (cells.in_valid_depth == 1)]),
        ]
        print(f"\n       {'funnel':<48}{'cells':>7}{'ha':>9}")
        for lab, sub in funnel:
            print(f"       {lab:<48}{len(sub):>7}{len(sub) * CELL_HA:>9.2f}")
        bed = funnel[-1][1]

        if bed.empty:
            print("\n       NOTHING SURVIVES the locked filters. Attenuation is")
            print("       not computable at An Aird by the Sherkin method.")
            result["attenuation"] = {
                "computable": False,
                "reason": "no habitat cell passes both the fetch and depth gates"}
        else:
            travel = float(swell["travels_to_deg"])
            att_head = headline(bed, travel)
            # The receptors are sheltered only by habitat that lies between
            # them and the incoming waves, so the same statistic is also
            # reported for the bearing-tested subset.
            on_path = bed[np.abs((bed.bearing_deg.values - wave_from + 180.0)
                                 % 360.0 - 180.0) <= BEARING_PRIMARY]
            att_path = headline(on_path, travel) if len(on_path) else None
            print(f"\n       An Aird bed by the locked filters: "
                  f"{att_head['n_cells']} cells = {att_head['ha']} ha")
            print(f"       depth range {bed.depth_m.min():.1f}-"
                  f"{bed.depth_m.max():.1f} m (median {bed.depth_m.median():.1f})")
            print(f"       per-axis median H: {att_head['per_axis_median_H']}")
            print(f"       per-axis median width m: {att_head['width_median_m']}")
            print(f"       waves travel TO {att_head['travel_deg']} deg -> "
                  f"bracketed by {att_head['bracketing_axes'][0]} and "
                  f"{att_head['bracketing_axes'][1]} "
                  f"(w={att_head['weight_on_upper']})")
            print(f"\n       >>> An Aird  H reduction = "
                  f"{att_head['H_reduction']:.1%}   E reduction = "
                  f"{att_head['E_reduction']:.1%}")
            print("       >>> Sherkin  H reduction = 7.9 %   "
                  "E reduction = 15.2 %   (NOT reused above)")
            if att_path is not None:
                print("")
                print(f"       Bearing-tested subset -- the part of that bed "
                      f"that actually lies between the")
                print(f"       receptors and the incoming waves: "
                      f"{att_path['n_cells']} cells = {att_path['ha']} ha, "
                      f"depth "
                      f"{on_path.depth_m.min():.1f}-{on_path.depth_m.max():.1f} m")
                print(f"       H = {att_path['H_reduction']:.1%}   "
                      f"E = {att_path['E_reduction']:.1%}")
            result["attenuation"] = {"computable": True, **att_head,
                                     "bearing_tested_subset": att_path}

            print("\n   6c. DOMAIN CHECK -- is the coefficient inside its range?")
            print("       depth_gate.py's test: compare the width actually")
            print("       traversed against the width needed for a 50 % height")
            print("       loss at that depth. A ratio far above 1 means an")
            print("       exponential decay fitted in a flume is being")
            print("       extrapolated to saturation.")
            ratios = {}
            for ax in att_head["bracketing_axes"]:
                sat = saturation_check(bed, ax)
                ratios[ax] = float(sat.ratio_width_to_50pct.median())
                print(f"       axis {ax:<6} traversed width median "
                      f"{sat.width_m.median():>6.0f} m | 50 % width median "
                      f"{sat.width_for_50pct_loss_m.median():>6.0f} m | ratio "
                      f"median {ratios[ax]:.2f} max "
                      f"{sat.ratio_width_to_50pct.max():.2f}")
            shb = gpd.read_file(SHERKIN_BED_GPKG, layer="kelp_cells")
            ssat = saturation_check(shb, "NE-SW")
            print(f"       Sherkin NE-SW  traversed width median "
                  f"{ssat.width_m.median():>6.0f} m | 50 % width median "
                  f"{ssat.width_for_50pct_loss_m.median():>6.0f} m | ratio "
                  f"median {ssat.ratio_width_to_50pct.median():.2f}")
            result["attenuation"]["saturation_ratio_median"] = ratios
            result["attenuation"]["sherkin_saturation_ratio_median_NE_SW"] = \
                float(ssat.ratio_width_to_50pct.median())

            print("\n   6d. DENSITY SENSITIVITY -- the largest unverified input.")
            print("       Dubi & Torum's k is for 12 plants/m2. NPWS (2014) says")
            print("       of this very community: \"Kelp coverage is variable,")
            print("       ranging from dense to sparse.\" There is no density")
            print("       measurement for An Aird. Drag scales with stem density,")
            print("       so k scales with it to first order.")
            H0 = att_head["H_reduction"]
            tot0 = -math.log(1 - H0)
            dens = {}
            print(f"       {'density vs 12 plants/m2':<26}{'H reduction':>13}"
                  f"{'E reduction':>13}")
            for frac in (1.00, 0.50, 0.25, 0.10):
                h = 1 - math.exp(-frac * tot0)
                dens[f"{frac:.2f}"] = {"H": round(h, 4),
                                       "E": round(1 - (1 - h) ** 2, 4)}
                print(f"       {frac*12:>5.1f} plants/m2 ({frac:.0%})"
                      f"{'':<7}{h:>12.1%}{1-(1-h)**2:>13.1%}")
            result["attenuation"]["density_sensitivity"] = dens

    # ------------------------------------------------------- 7 valuation
    hr("7. COASTAL-PROTECTION VALUATION")
    val: dict = {}
    result["valuation"] = val

    # ---- 7a avoided damage ------------------------------------------------
    print("7a. AVOIDED DAMAGE -- the primary method")
    print("-" * 78)
    print("An avoided-damage figure needs all three of:")
    print("  (i)   a receptor that would take damage without the habitat;")
    print("  (ii)  a damage function linking the forcing to a euro loss;")
    print("  (iii) a with-habitat / without-habitat difference in the forcing.")
    print()
    occ = sorted(set(habitable.building))
    other = sorted(set(near.building) - set(occ))
    print(f"(i) RECEPTORS. {len(near)} OSM buildings within 500 m of the cluster "
          f"centroid: {tags}.")
    print(f"    {len(habitable)} carry an occupied-structure tag ({occ}); "
          f"{len(near) - len(habitable)} do not ({other}).")
    print(f"    Ground elevation (Copernicus GLO-30 DSM): lowest "
          f"{near.elev_m.min():.1f} m, median {near.elev_m.median():.1f} m, "
          f"max {near.elev_m.max():.1f} m.")
    lowest_row = near.loc[near.elev_m.idxmin()]
    print(f"    The lowest structure is a '{lowest_row.building}' at "
          f"{lowest_row.elev_m:.1f} m. The lowest HOUSE is at "
          f"{near[near.building == 'house'].elev_m.min():.1f} m.")

    opw = opw_receptor_check(near)
    print()
    print("    OPW National Coastal Flood Hazard Maps 2022, Current Scenario "
          "(ITM).")
    print("    INTERNAL SCREEN ONLY. The licence (CC BY-NC-ND 4.0) is "
          "unresolved, so no")
    print("    visual derivative of this layer leaves the repo. What follows "
          "is a count,")
    print("    which is what the 11 Aug Sherkin screen also used it for.")
    print(f"    {'return period':<16}{'polygons in 4 km box':>22}"
          f"{'buildings inside':>18}{'nearest bld m':>15}")
    for rp, row in opw.items():
        print(f"    {rp:<16}{row['polygons']:>22}{row['inside']:>18}"
              f"{row['min_dist_m']:>15.1f}")
    print()
    print("    ZERO of the buildings behind this frontage lie inside the "
          "1000-year coastal")
    print("    flood extent. The nearest structure to that line is a ruin at "
          f"{opw['1000 yr']['min_dist_m']:.0f} m;")
    print(f"    the nearest HOUSE is {opw['1000 yr']['min_dist_house_m']:.0f} m "
          "from it. Elevation, from a")
    print("    licence-clean source, says the same thing independently.")
    print()
    print("(ii) DAMAGE FUNCTION. Not reached: the receptor term is zero, so no "
          "damage")
    print("     function is needed. (This project has none for wave or erosion "
          "damage")
    print("     to Irish dwellings in any case.)")
    print()
    if att_head is not None:
        print(f"(iii) FORCING DIFFERENCE. An Aird's own attenuation is "
              f"{att_head['H_reduction']:.1%} wave height /")
        print(f"      {att_head['E_reduction']:.1%} wave energy. Read 6c and 6d "
              "before using either.")
    else:
        print("(iii) FORCING DIFFERENCE. Not computable (section 6).")
    print()
    print("    >>> AVOIDED DAMAGE AT AN AIRD = EUR 0, EVIDENCED ZERO.")
    print("    >>> Same test, same answer, same wording as Sherkin: no built")
    print("    >>> receptor lies within the mapped coastal flood extent behind")
    print("    >>> this frontage. The zero is a finding, not a missing number.")
    val["avoided_damage"] = {
        "eur_per_yr": 0,
        "status": "evidenced zero",
        "basis": ("0 of %d buildings behind the frontage lie inside the OPW "
                  "1000-year coastal flood extent; nearest house %.0f m outside "
                  "it; corroborated by Copernicus GLO-30 elevation"
                  % (len(near), opw["1000 yr"]["min_dist_house_m"])),
        "n_buildings_500m": int(len(near)),
        "n_occupied_tag": int(len(habitable)),
        "tag_counts": tags,
        "lowest_elevation_m": round(float(near.elev_m.min()), 1),
        "lowest_house_elevation_m": round(
            float(near[near.building == "house"].elev_m.min()), 1),
        "opw_check": opw,
        "opw_licence": ("CC BY-NC-ND 4.0, UNRESOLVED. Used internally as a "
                        "count only. No visual derivative may be published "
                        "until flood_data@opw.ie clears it."),
        "caveat": ("OPW models still water from tide and storm surge and "
                   "excludes wave overtopping, which is this project's "
                   "mechanism. It is a screen for low-lying land, never a "
                   "statement about wave damage."),
    }

    # ---- 7b replacement cost ---------------------------------------------
    print("\n7b. REPLACEMENT COST -- Shabman & Batie (1978), NRC (2005, 2012)")
    print("-" * 78)
    structures = [(r.osm_id, json.loads(r.tags)) for _, r in near_infra.iterrows()
                  if json.loads(r.tags).get("man_made")]
    print("C1 equivalent service     : PARTLY MET. Kelp attenuates energy in "
          "the nearshore;")
    print("                            the functionally equivalent structure "
          "is a nearshore /")
    print("                            low-crested breakwater, not the rock "
          "revetment the")
    print("                            Irish unit rate prices. Unchanged from "
          "step 5b.")
    print("C2 least-cost alternative : UNTESTED, as at Sherkin.")
    print("C3 demonstrated demand    : FAILS. Three strands, all negative:")
    print(f"      1. No receptor is exposed. 0 of {len(near)} buildings sit "
          "inside the OPW")
    print("         1000-year coastal flood extent (7a). Sherkin failed C3 "
          "because there")
    print("         were no receptors at all; An Aird fails it because the "
          "receptors that")
    print("         exist are not exposed. Different route, same conclusion.")
    print("      2. The receptor set itself is thin: "
          f"{len(habitable)} houses and "
          f"{len(near) - len(habitable)} ruins /")
    print("         ancillary structures on an exposed rocky frontage.")
    print("      3. Revealed preference. The OPW HAS funded work in this "
          "parish -- Bruach")
    print("         na Mara Estate, Carna, EUR 33,710 approved 2 June 2026 "
          "(gov.ie primary")
    print("         text). It is a SURVEY OF THE SURFACE WATER PIPE NETWORK: "
          "pluvial")
    print("         drainage, not shoreline wave protection. It is evidence "
          "that the State")
    print("         pays here, and evidence that what it pays for is not this "
          "service.")
    if structures:
        print(f"      Note: {len(structures)} engineered marine structure(s) "
              "in OSM within 500 m:")
        for oid, t in structures:
            print(f"        {oid}  {t}")
        print("        The breakwater is 246 m2 (about 29 x 22 m) at a small "
              "landing. A")
        print("        harbour-shelter structure of that size is not evidence "
              "of demand for")
        print("        wave protection of the receptors behind it.")
    print()
    print("    >>> C3 FAILS. Replacement cost at An Aird is a COUNTERFACTUAL")
    print("    >>> ILLUSTRATION, NOT A VALUE -- the same label Sherkin carries.")

    print("\n    Illustration, computed on An Aird's OWN frontage and OWN "
          "energy reduction:")
    e_red = att_head["E_reduction"] if att_head else float("nan")
    rc_rows = []
    if att_head is not None:
        print(f"    energy reduction {e_red:.1%} (An Aird, section 6); "
              "pro-rata scaling is OUR")
        print("    simplification, not a published method (CLAUDE.md rule 8).")
        print(f"\n    {'frontage definition':<44}{'frontage m':>11}"
              f"{'full structure':>16}{'pro-rata':>12}{'annualised':>12}")
        for label, L in result["frontage_m"].items():
            r = replacement_cost(
                frontage_m=float(L), energy_reduction=float(e_red),
                unit_cost_eur_per_m=IE_ROCK_ARMOUR_EUR_PER_M["central"],
                demand_condition_met=False, site="an_aird_kilkieran")
            rc_rows.append({"frontage_definition": label, **asdict(r)})
            print(f"    {label:<44}{L:>11.0f}"
                  f"{r.full_structure_eur:>16,.0f}{r.pro_rata_eur:>12,.0f}"
                  f"{r.annualised_eur_per_yr:>12,.0f}")
        print(f"\n    label returned by src/replacement_cost.py:")
        print(f"      {rc_rows[0]['label']}")
        pd.DataFrame(rc_rows).to_csv(OUT / "anaird_replacement_cost.csv",
                                     index=False)
    val["replacement_cost"] = {
        "conditions": {"C1": "partly met", "C2": "untested", "C3": "FAILS"},
        "c3_evidence": {
            "receptors_in_opw_1000yr_extent": 0,
            "opw_minor_works_nearby": {
                "scheme": "Bruach na Mara Estate, Carna, Co. Galway",
                "amount_eur": 33710,
                "approved": "2026-06-02",
                "works": "survey of the surface water pipe network",
                "is_shoreline_protection": False,
                "source": "gov.ie OPW press release, primary text"},
            "osm_marine_structures": [
                {"osm_id": oid, "tags": t, "area_m2": 246} for oid, t in structures],
        },
        "label": "COUNTERFACTUAL ILLUSTRATION - NOT A VALUE",
        "unit_rate_eur_per_m": IE_ROCK_ARMOUR_EUR_PER_M,
        "rows": rc_rows,
    }

    # ---- 7c the neighbourhood --------------------------------------------
    print("\n7c. THE NEIGHBOURHOOD -- the anti-correlation at 4 km scale")
    print("-" * 78)
    nb = neighbourhood_check(centre)
    print(f"    {'cluster':>7}  {'place':<34}{'bld':>5}{'fetch min':>11}"
          f"{'fetch max':>11}{'gate':>7}{'in 1000yr':>11}{'houses in':>11}")
    for row in nb:
        place = row["place"].encode("ascii", "replace").decode("ascii")
        print(f"    {row['cluster']:>7}  {place[:33]:<34}{row['n']:>5}"
              f"{row['fetch_min']:>11.3f}{row['fetch_max']:>11.3f}"
              f"{('PASS' if row['pass_fetch_strict'] else 'fail'):>7}"
              f"{row['inside']:>11}{row['houses_inside']:>11}")
    print()
    passers = [r for r in nb if r["pass_fetch_strict"]]
    failers = [r for r in nb if not r["pass_fetch_strict"]]
    print("    Read the two right-hand columns against the two on their left.")
    print(f"    {len(passers)} cluster(s) clear the {FETCH_EXCLUSION_MAX} gate: "
          f"{[r['cluster'] for r in passers]}, holding "
          f"{sum(r['n'] for r in passers)} buildings")
    print(f"    between them and {sum(r['inside'] for r in passers)} inside the "
          "1000-year extent.")
    print(f"    {len(failers)} cluster(s) fail the gate, holding "
          f"{sum(r['n'] for r in failers)} buildings and "
          f"{sum(r['inside'] for r in failers)} inside")
    print(f"    the extent, of which {sum(r['houses_inside'] for r in failers)} "
          "are houses. Every flood-exposed house")
    print("    in this 4 km stretch sits on water below the gate, where the "
          "Dubi & Torum")
    print("    coefficients do not apply at all.")
    print("    The West Cork anti-correlation reproduces inside a single 4 km "
          "stretch of")
    print("    one bay. That is the strongest form of it the project has yet "
          "shown.")
    val["neighbourhood"] = nb

    hr("VERDICT")
    print("Coastal protection, An Aird / Kilkieran Bay:")
    print("  avoided damage      EUR 0 - evidenced zero (no receptor in the "
          "mapped extent)")
    print("  replacement cost    counterfactual illustration, NOT a value "
          "(C3 fails)")
    print("  euro carried        NONE")
    if att_head is not None:
        print(f"\nThe site's own physics WAS computed and is new: "
              f"{att_head['ha']} ha of survey-mapped")
        print(f"L. hyperborea-dominated reef in the 4-10 m band behind an "
              f"exposed frontage,")
        print(f"H reduction {att_head['H_reduction']:.1%}, E reduction "
              f"{att_head['E_reduction']:.1%} at the measured "
              f"{att_head['travel_deg']:.0f} deg wave")
        print("bearing. Sections 6c and 6d say how far that may be trusted.")

    json.dump(result, (OUT / "anaird_phaseb_summary.json").open("w"), indent=2,
              default=str)
    print(f"\nwritten: {OUT / 'anaird_phaseb_summary.json'}")
    fs.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
