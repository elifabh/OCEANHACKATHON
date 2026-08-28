#!/usr/bin/env python3
"""
national_exposure_screen.py -- the receptor-EXPOSURE test, run at every
remaining strict-fetch-passing cluster that has habitat evidence.

WHY THIS EXISTS
---------------
Two locked rules from the handover notes collide:

  * 2026-08-27 (wide screen, section 6): "A screen without elevation cannot
    produce a POSITIVE receptor finding, only a negative one."
  * 2026-08-28 (An Aird Phase B, section 11): "An evidenced zero requires a
    named test that could have returned non-zero. 'No data' is not a zero."

The elevation test has been run at exactly ONE site -- An Aird, cluster 531.
Everywhere else the receptor term is still shore proximity, which does not
distinguish a house on a saltmarsh from a house on a 30 m cliff. So the
project cannot presently say "zero" at the other candidates. It has not
looked. This script looks.

WHAT IT DOES
------------
  1  selects, from outputs/national_candidate_table.csv, every cluster that
     passes the STRICT fetch gate and carries habitat evidence at E1, E2 or
     E3 -- i.e. a survey record, a modelled presence on mapped reef, or a
     modelled presence off reef. (The 27 Aug deliverable table used E1+E2
     only, 19 clusters; adding E3 widens it to 38. E3 is included here
     because the question being asked is about the RECEPTOR term, and it is
     cheaper to screen a site than to argue about whether it qualifies.)
  2  pulls OSM buildings at FULL TAG DETAIL around each cluster, so a
     `ruins` can be told from a `house` (at An Aird six of nine "buildings"
     were ruins);
  3  samples Copernicus GLO-30 ground elevation at every one of them --
     the PRIMARY screen, because its licence is read and clean;
  4  cross-checks internally against the OPW coastal flood extents, which
     may not leave this repo (CLAUDE.md rule 9);
  5  ranks by exposed-receptor count and stops. NO EURO IS COMPUTED HERE.

PRE-REGISTERED DEFINITIONS -- fixed before any cluster was screened
-------------------------------------------------------------------
  receptor set     OSM buildings within 500 m of the cluster centroid.
                   Identical to the An Aird Phase B rule, not re-chosen.
  occupied tag     building tag NOT in {ruins, garage, shed, farm_auxiliary,
                   greenhouse}. Identical to An Aird's `habitable` subset.
  low bands        GLO-30 elevation < 5 m and < 10 m, as specified for this
                   run. Both reported for every cluster.
  EXPOSED RECEPTOR the ranking key: an occupied-tag building below 5 m.
                   Ties broken by (all buildings < 5 m), then
                   (occupied-tag < 10 m), then lowest occupied elevation.

  What "exposed" does and does not mean. Below 5 m is LOW-LYING, which is a
  necessary condition for still-water or overtopping exposure and not a
  sufficient one. A non-zero count here is a FLAG FOR REVIEW, never a
  finding, and never a euro. A zero count is a genuine negative, because the
  test could have returned non-zero and did not.

CONTROL
-------
  Cluster 531 (An Aird) is screened again by this generalised code and its
  numbers must reproduce the hand-built Phase B result: 9 buildings, lowest
  4.2 m (a ruin), two houses at 9.1 m and 12.1 m. The script prints PASS or
  FAIL on that comparison before the national table is read.

PROVENANCE
----------
  OSM buildings / coastline    (c) OpenStreetMap contributors, ODbL 1.0
  Copernicus WorldDEM-30 (GLO-30), open COG on AWS -- licence read
      2026-08-28, data/reference/License-COPDEM-30.pdf. Free of charge,
      worldwide, unlimited in time; reproduction, distribution,
      communication and adaptation granted. Required notice (Article 6b):
      "produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and
      (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS
      by the European Union and ESA; all rights reserved"
  OPW National Coastal Flood Hazard Maps 2022, Current Scenario --
      CC BY-NC-ND 4.0, UNRESOLVED. INTERNAL CROSS-CHECK ONLY. Counts and
      distances stay in this repo; no visual derivative exists anywhere.

Run:  PYTHONPATH=src python src/national_exposure_screen.py
Read-only with respect to every locked artefact. Writes only under
outputs/exposure_screen/.
"""

from __future__ import annotations

import json
import math
import os
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

# rasterio's boundless window read trips a NumPy 2.5 deprecation inside
# rasterio itself. It is noise, it fires once per building, and it would
# otherwise be most of this script's run log.
warnings.filterwarnings("ignore", category=DeprecationWarning,
                        message=".*shape on a NumPy array.*")

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Screen parameters are IMPORTED, never re-declared (locked rule, national
# screen note section 9). Nothing here can silently re-type a threshold.
from wide_receptor_screen import (  # noqa: E402
    FETCH_EXCLUSION_MAX,
    ITM,
    SHORE_DIST_M,
    WGS,
    overpass,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "exposure_screen"
CANDIDATE_TABLE = REPO / "outputs" / "national_candidate_table.csv"
ANAIRD_RECEPTORS = REPO / "outputs" / "anaird" / "anaird_receptors.csv"

# ---------------------------------------------------- pre-registered values
RECEPTOR_RADIUS_M = 500.0          # An Aird Phase B rule, unchanged
NON_OCCUPIED_TAGS = {"ruins", "garage", "shed", "farm_auxiliary", "greenhouse"}
LOW_BANDS_M = (5.0, 10.0)
EVIDENCE_WANTED = {
    "E1_npws_laminaria_fine",
    "E1_npws_laminaria_coarse",
    "E2_model_assessed",
    "E3_model_offreef_inrange",
}
CONTROL_CLUSTER = 531              # An Aird

# Overpass box half-width. The receptor radius is 500 m; 800 m of box gives
# the coastline enough margin that a shore distance is never truncated by
# the query window.
BOX_HALF_M = 800.0
BOXES_PER_QUERY = 10               # keep each Overpass union query small

GLO30_NOTICE = ("produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 "
                "and (c) Airbus Defence and Space GmbH 2014-2018 provided under "
                "COPERNICUS by the European Union and ESA; all rights reserved")
GLO30_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"

OPW_ZIP = REPO / "data" / "opw" / "ncfhm_itm_ext_c_c_1000yr_200yr_10yr.zip"
OPW_LAYERS = [("10 yr", "0010"), ("200 yr", "0200"), ("1000 yr", "1000")]
OPW_INNER = "NCFHM_2022_Current_Scenario_1000yr_200yr_10ry"


def hr(title: str = "") -> None:
    print("\n" + "=" * 78)
    if title:
        print(title)
        print("=" * 78)


# ======================================================================
# Copernicus GLO-30, multi-tile
# ======================================================================

def _glo30_tile_url(lat_sw: int, lon_sw: int) -> str:
    ns = f"N{lat_sw:02d}" if lat_sw >= 0 else f"S{abs(lat_sw):02d}"
    ew = f"W{abs(lon_sw):03d}" if lon_sw < 0 else f"E{lon_sw:03d}"
    name = f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"
    return f"{GLO30_BASE}/{name}/{name}.tif"


_TILE_BOUNDS: dict[tuple[int, int], tuple] = {}


def _glo30_bounds(la: int, lo: int):
    if (la, lo) not in _TILE_BOUNDS:
        with rasterio.open(f"/vsicurl/{_glo30_tile_url(la, lo)}") as s:
            _TILE_BOUNDS[(la, lo)] = tuple(s.bounds)
    return _TILE_BOUNDS[(la, lo)]


def _glo30_tile_for(lon: float, lat: float) -> tuple[int, int] | None:
    """Which GLO-30 tile actually CONTAINS this point.

    BUG FIXED HERE, 2026-08-28. The obvious rule -- tile = (floor(lat),
    floor(lon)) -- is WRONG at a tile edge, and wrong silently. Copernicus
    tiles are pixel-CENTRE registered, so the tile named W010 has bounds
    lon [-10.000208, -9.000208]: it starts half a pixel WEST of the whole
    degree. A building at lon -10.00013 (cluster 593, Malivey) therefore
    floors to tile W011, lies 7 m outside it, and -- because these COGs
    declare no nodata value -- rasterio's sample() returns 0.0 rather than
    raising. That produced a "house at 0.0 m" in the first run of this
    screen whose true elevation, read from the correct tile, is 18.7 m.

    So the tile is chosen by testing the real bounds of the candidates, and
    a point in none of them returns None (-> NaN) instead of a fake zero.
    """
    la0, lo0 = math.floor(lat), math.floor(lon)
    for la in (la0, la0 - 1, la0 + 1):
        for lo in (lo0, lo0 + 1, lo0 - 1):
            try:
                left, bottom, right, top = _glo30_bounds(la, lo)
            except Exception:                                 # noqa: BLE001
                continue
            if left <= lon <= right and bottom <= lat <= top:
                return (la, lo)
    return None


def sample_glo30(pts_wgs: list[tuple[float, float]]) -> np.ndarray:
    """Ground elevation in metres above the EGM2008 geoid, GLO-30, multi-tile.

    GLO-30 is a Digital SURFACE Model: it includes buildings and vegetation,
    so over a footprint it returns a roof/terrain mixture. At 30 m posting a
    small dwelling is a fraction of a pixel and the terrain dominates, but
    the direction of the bias is UPWARD. Stated, not corrected -- which
    means this screen errs towards under-reporting low-lying buildings
    rather than inventing them.

    A returned value of exactly 0.0 is NOT a ground elevation: GLO-30
    flattens water surfaces to zero and declares no nodata value, so a
    coastal pixel that the product classes as water reads 0.0. Callers must
    treat exact zeros as unknown -- see WATER_FLAT_VALUE below.
    """
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    out = np.full(len(pts_wgs), np.nan, dtype=float)
    if not pts_wgs:
        return out
    groups: dict[tuple[int, int], list[int]] = {}
    for i, (lon, lat) in enumerate(pts_wgs):
        tile = _glo30_tile_for(lon, lat)
        if tile is None:
            continue                       # stays NaN, never a fake zero
        groups.setdefault(tile, []).append(i)
    for (la, lo), idx in sorted(groups.items()):
        with rasterio.open(f"/vsicurl/{_glo30_tile_url(la, lo)}") as s:
            nodata = s.nodata
            vals = np.array([v[0] for v in s.sample(
                [pts_wgs[i] for i in idx])], dtype=float)
        if nodata is not None:
            vals = np.where(vals == nodata, np.nan, vals)
        out[list(idx)] = vals
    return out


# GLO-30 water flattening. The product sets water surfaces to exactly 0 and
# declares no nodata, so a building whose 30 m pixel is classed as water
# reads 0.0 m. That is an UNKNOWN ground elevation, not a low one. Counting
# it as "below 5 m" would manufacture exposure; counting it as high would
# manufacture safety. It is excluded from the bands and reported separately,
# with the land-neighbourhood median beside it as a labelled estimate.
WATER_FLAT_VALUE = 0.0
NB_HALF_PX = 2                      # +/- 2 pixels ~ +/- 60 m


def glo30_neighbourhood(pts_wgs: list[tuple[float, float]]
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Land-neighbourhood statistics around each point.

    Returns (median of non-water pixels, min, fraction of water pixels) over
    a (2*NB_HALF_PX+1)^2 window. Used to bracket a water-flattened building
    and to show, for every low reading, whether the surrounding terrain
    agrees. Read per point from the tile that contains it.
    """
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    n = len(pts_wgs)
    med = np.full(n, np.nan)
    lo_ = np.full(n, np.nan)
    wfrac = np.full(n, np.nan)
    groups: dict[tuple[int, int], list[int]] = {}
    for i, (lon, lat) in enumerate(pts_wgs):
        tile = _glo30_tile_for(lon, lat)
        if tile is not None:
            groups.setdefault(tile, []).append(i)
    k = 2 * NB_HALF_PX + 1
    for (la, lo), idx in sorted(groups.items()):
        with rasterio.open(f"/vsicurl/{_glo30_tile_url(la, lo)}") as s:
            for i in idx:
                lon, lat = pts_wgs[i]
                row, col = s.index(lon, lat)
                win = rasterio.windows.Window(col - NB_HALF_PX,
                                              row - NB_HALF_PX, k, k)
                a = s.read(1, window=win, boundless=True,
                           fill_value=np.nan).astype(float).ravel()
                a = a[np.isfinite(a)]
                if a.size == 0:
                    continue
                wfrac[i] = float((a == WATER_FLAT_VALUE).mean())
                land = a[a != WATER_FLAT_VALUE]
                if land.size:
                    med[i] = float(np.median(land))
                    lo_[i] = float(land.min())
    return med, lo_, wfrac


# ======================================================================
# OSM
# ======================================================================

def fetch_osm_for_boxes(boxes: list[tuple]) -> tuple[gpd.GeoDataFrame,
                                                     gpd.GeoDataFrame]:
    """Buildings (full tags) and coastline for a list of WGS bboxes.

    The boxes are unioned into a handful of Overpass queries rather than one
    per cluster: 38 clusters would otherwise be 76 round trips against a
    public endpoint that was already rate-limiting this project on 27 Aug.
    Every response is cached by query hash, so a re-run is free and
    reproduces against the same OSM snapshot.
    """
    brows: list[dict] = []
    clines: list[LineString] = []
    for i in range(0, len(boxes), BOXES_PER_QUERY):
        chunk = boxes[i:i + BOXES_PER_QUERY]
        bbs = [f"{b[1]:.6f},{b[0]:.6f},{b[3]:.6f},{b[2]:.6f}" for b in chunk]

        parts = "".join('way["building"](%s);relation["building"](%s);'
                        'node["building"](%s);' % (bb, bb, bb) for bb in bbs)
        q_b = "[out:json][timeout:300];(%s);out center tags;" % parts
        for el in overpass(q_b).get("elements", []):
            c = el.get("center") or {"lon": el.get("lon"), "lat": el.get("lat")}
            if c.get("lon") is None:
                continue
            t = el.get("tags") or {}
            brows.append({"osm_id": "%s/%s" % (el["type"], el["id"]),
                          "building": t.get("building", "yes"),
                          "name": t.get("name"),
                          "tags": json.dumps(t, ensure_ascii=False),
                          "lon": c["lon"], "lat": c["lat"]})

        parts = "".join('way["natural"="coastline"](%s);' % bb for bb in bbs)
        q_c = "[out:json][timeout:300];(%s);out geom;" % parts
        for el in overpass(q_c).get("elements", []):
            pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
            if len(pts) >= 2:
                clines.append(LineString(pts))
        print("   boxes %d-%d: %d buildings, %d coastline ways so far"
              % (i + 1, i + len(chunk), len(brows), len(clines)))

    bld = gpd.GeoDataFrame(
        brows, geometry=gpd.points_from_xy([r["lon"] for r in brows],
                                           [r["lat"] for r in brows]), crs=WGS)
    bld = bld[~bld.osm_id.duplicated()].reset_index(drop=True)
    coast = gpd.GeoDataFrame(geometry=clines, crs=WGS)
    coast = coast[~coast.geometry.duplicated()].reset_index(drop=True)
    return bld, coast


# ======================================================================
# OPW -- INTERNAL CROSS-CHECK ONLY (CLAUDE.md rule 9)
# ======================================================================
# The licence is CC BY-NC-ND 4.0 and unresolved. A COUNT of buildings inside
# an extent, and a DISTANCE to that extent, are not visual derivatives; they
# are the same internal use the 11 Aug Sherkin screen and the 28 Aug An Aird
# screen made of the layer. Nothing OPW-derived is written to any publishable
# artefact by this script, and every column it does write is prefixed
# `opw_internal_` so it cannot be exported by accident.
#
# What the layer is: OPW-modelled STILL WATER from tide and storm surge. It
# excludes wave overtopping -- which is this project's mechanism -- and
# ignores defences. It screens for low-lying land. It never says "the kelp
# protects this".
# ======================================================================

def opw_union(cx: float, cy: float, half_m: float, code: str):
    """OPW extent near a point. NOTE the bbox is in ITM (EPSG:2157).

    The shapefile is EPSG:2157. A WGS84 bbox returns ZERO features SILENTLY
    -- the CRS trap CLAUDE.md section 3 records. Verified during this run:
    the An Aird point returns 0 features with a 4326 bbox and 58 with the
    ITM one.
    """
    try:
        g = gpd.read_file(
            "zip://%s!%s/ncfhm_itm_ext_c_c_%s.shp" % (OPW_ZIP, OPW_INNER, code),
            bbox=(cx - half_m, cy - half_m, cx + half_m, cy + half_m))
    except Exception as exc:                                  # noqa: BLE001
        print("      OPW read failed (%s)" % exc, file=sys.stderr)
        return None, 0
    if len(g) == 0:
        return None, 0
    return unary_union(g.to_crs(ITM).geometry.values), len(g)


def opw_check(near: gpd.GeoDataFrame, cx: float, cy: float) -> dict:
    out: dict = {}
    for label, code in OPW_LAYERS:
        u, n = opw_union(cx, cy, 2000.0, code)
        if u is None:
            out[label] = {"polygons_2km": 0, "extent_mapped_in_box": False,
                          "inside": 0, "inside_occupied": 0,
                          "inside_osm_ids": [],
                          "min_dist_m": None, "min_dist_occupied_m": None}
            continue
        inside = near.geometry.apply(u.contains)
        occ = near[near.occupied_tag]
        d = near.geometry.distance(u)
        out[label] = {
            "polygons_2km": int(n),
            "extent_mapped_in_box": True,
            "inside": int(inside.sum()),
            "inside_occupied": int((inside & near.occupied_tag).sum()),
            "inside_osm_ids": list(near.loc[inside, "osm_id"]),
            "min_dist_m": round(float(d.min()), 1) if len(d) else None,
            "min_dist_occupied_m": (round(float(occ.geometry.distance(u).min()), 1)
                                    if len(occ) else None),
        }
    return out


def opw_elevation_calibration(cx: float, cy: float, to_wgs) -> dict | None:
    """What GLO-30 elevation does the OPW 1000-yr extent actually reach here?

    INTERNAL. The 5 m and 10 m bands are reporting bands, not a physical
    threshold, and I am not going to invent a tide-plus-surge figure. This
    measures instead, at each site where OPW has mapped an extent, the
    elevation the modelled extreme still-water extent climbs to -- the
    empirical answer to "what does below-5-m mean here". Sampled on a 50 m
    lattice inside the extent within 1 km of the cluster.
    """
    u, _ = opw_union(cx, cy, 1200.0, "1000")
    if u is None:
        return None
    xs = np.arange(cx - 1000, cx + 1000 + 1, 50.0)
    ys = np.arange(cy - 1000, cy + 1000 + 1, 50.0)
    gx, gy = np.meshgrid(xs, ys)
    inside = [Point(x, y) for x, y in zip(gx.ravel(), gy.ravel())
              if u.contains(Point(x, y))]
    if len(inside) < 5:
        return None
    lonlat = [to_wgs.transform(p.x, p.y) for p in inside]
    el = sample_glo30(lonlat)
    el = el[np.isfinite(el)]
    if el.size < 5:
        return None
    return {"n_points": int(el.size),
            "p50_m": round(float(np.percentile(el, 50)), 1),
            "p90_m": round(float(np.percentile(el, 90)), 1),
            "p99_m": round(float(np.percentile(el, 99)), 1),
            "max_m": round(float(el.max()), 1)}


# ======================================================================
# the screen
# ======================================================================

def select_clusters() -> pd.DataFrame:
    d = pd.read_csv(CANDIDATE_TABLE)
    sel = d[(d["pass_fetch_strict"]) &
            (d["evidence_class"].isin(EVIDENCE_WANTED))].copy()
    return sel.reset_index(drop=True)


def screen_cluster(row, bld_itm: gpd.GeoDataFrame, bld_wgs: gpd.GeoDataFrame,
                   coast_u, to_itm, to_wgs) -> tuple[dict, pd.DataFrame]:
    cx, cy = to_itm.transform(row.lon, row.lat)
    centre = Point(cx, cy)

    d_centre = bld_itm.geometry.distance(centre)
    near = bld_itm[d_centre <= RECEPTOR_RADIUS_M].copy()
    near["dist_cluster_m"] = d_centre[d_centre <= RECEPTOR_RADIUS_M]
    near["dist_shore_m"] = (near.geometry.distance(coast_u)
                            if coast_u is not None else np.nan)
    near["lon"] = bld_wgs.loc[near.index, "lon"].values
    near["lat"] = bld_wgs.loc[near.index, "lat"].values
    near["occupied_tag"] = ~near.building.isin(NON_OCCUPIED_TAGS)
    near["cluster"] = int(row.cluster)

    if len(near):
        pts = list(zip(near.lon, near.lat))
        near["elev_m"] = sample_glo30(pts)
        med, lo_, wf = glo30_neighbourhood(pts)
        near["elev_land_nb_median_m"] = med
        near["elev_land_nb_min_m"] = lo_
        near["nb_water_fraction"] = wf
        # exactly 0.0 is GLO-30's water class, not a ground elevation
        near["elev_is_water_pixel"] = near.elev_m == WATER_FLAT_VALUE
        near["elev_used_m"] = near.elev_m.where(~near.elev_is_water_pixel)
    else:
        for c in ("elev_m", "elev_land_nb_median_m", "elev_land_nb_min_m",
                  "nb_water_fraction", "elev_used_m"):
            near[c] = pd.Series(dtype=float)
        near["elev_is_water_pixel"] = pd.Series(dtype=bool)
    near = near.sort_values("dist_shore_m")

    occ = near[near.occupied_tag]
    have_el = near[np.isfinite(near.elev_used_m)]
    occ_el = occ[np.isfinite(occ.elev_used_m)]

    def n_below(df, band):
        return int((df.elev_used_m < band).sum())

    rec = {
        "cluster": int(row.cluster),
        "county": row.county,
        "nearest_place": row.nearest_place,
        "lon": float(row.lon), "lat": float(row.lat),
        "evidence_class": row.evidence_class,
        "evidence_is_survey_record": bool(row.evidence_is_survey_record),
        "phaseB_eligible_27aug": bool(row.phaseB_eligible),
        "fetch_nearest_min": float(row.fetch_nearest_min),
        "fetch_nearest_max": float(row.fetch_nearest_max),
        "npws_lam_ha_1km": float(row.npws_lam_ha_1km),
        "gap_pos_in_range": (None if pd.isna(row.gap_pos_in_range)
                             else int(row.gap_pos_in_range)),
        "gap_pos_in_range_on_reef": (None if pd.isna(row.gap_pos_in_range_on_reef)
                                     else int(row.gap_pos_in_range_on_reef)),
        "n_buildings_500m": int(len(near)),
        "n_occupied_tag": int(len(occ)),
        "n_with_elevation": int(len(have_el)),
        "n_water_pixel": (int(near.elev_is_water_pixel.sum())
                          if len(near) else 0),
        "n_occupied_water_pixel": (int((near.elev_is_water_pixel
                                        & near.occupied_tag).sum())
                                   if len(near) else 0),
        "tag_counts": near.building.value_counts().to_dict() if len(near) else {},
        "elev_min_m": (round(float(have_el.elev_used_m.min()), 1)
                       if len(have_el) else None),
        "elev_median_m": (round(float(have_el.elev_used_m.median()), 1)
                          if len(have_el) else None),
        "elev_max_m": (round(float(have_el.elev_used_m.max()), 1)
                       if len(have_el) else None),
        "elev_min_occupied_m": (round(float(occ_el.elev_used_m.min()), 1)
                                if len(occ_el) else None),
        "n_below_5m": n_below(have_el, 5.0) if len(have_el) else 0,
        "n_below_10m": n_below(have_el, 10.0) if len(have_el) else 0,
        "n_occupied_below_5m": n_below(occ_el, 5.0) if len(occ_el) else 0,
        "n_occupied_below_10m": n_below(occ_el, 10.0) if len(occ_el) else 0,
        "min_dist_shore_m": (round(float(near.dist_shore_m.min()), 1)
                             if len(near) else None),
    }
    rec["exposed_receptors"] = rec["n_occupied_below_5m"]
    # Sensitivity: if a water-flattened building is given its land-neighbourhood
    # median instead of being dropped, how many more fall below 5 m? Reported,
    # never substituted for the primary count.
    if len(near):
        wf_occ = near[near.elev_is_water_pixel & near.occupied_tag]
        rec["exposed_receptors_if_water_pixels_use_land_neighbourhood"] = (
            rec["exposed_receptors"]
            + int((wf_occ.elev_land_nb_median_m < 5.0).sum()))
    else:
        rec["exposed_receptors_if_water_pixels_use_land_neighbourhood"] = 0

    opw = opw_check(near, cx, cy) if len(near) else {}
    rec["opw_internal"] = opw
    if opw:
        k = opw.get("1000 yr", {})
        rec["opw_internal_1000yr_polygons_2km"] = k.get("polygons_2km")
        rec["opw_internal_1000yr_inside"] = k.get("inside")
        rec["opw_internal_1000yr_inside_occupied"] = k.get("inside_occupied")
        rec["opw_internal_1000yr_min_dist_m"] = k.get("min_dist_m")
        rec["opw_internal_1000yr_min_dist_occupied_m"] = \
            k.get("min_dist_occupied_m")
    rec["opw_internal_calibration"] = opw_elevation_calibration(cx, cy, to_wgs)
    return rec, near


def control_check(near: pd.DataFrame) -> dict:
    """Reproduce the hand-built An Aird Phase B receptor result, or fail."""
    want = pd.read_csv(ANAIRD_RECEPTORS)
    got = near.drop(columns=["geometry"], errors="ignore")
    ok_n = len(got) == len(want)
    merged = want[["osm_id", "building", "elev_m"]].merge(
        got[["osm_id", "building", "elev_m"]], on="osm_id",
        how="outer", suffixes=("_want", "_got"), indicator=True)
    ok_ids = bool((merged["_merge"] == "both").all())
    dmax = (float(np.nanmax(np.abs(merged.elev_m_want - merged.elev_m_got)))
            if ok_ids else float("nan"))
    ok_el = ok_ids and dmax < 0.05
    res = {"n_expected": int(len(want)), "n_got": int(len(got)),
           "ids_match": ok_ids, "max_abs_elev_diff_m": dmax,
           "passed": bool(ok_n and ok_ids and ok_el)}
    print("   expected %d buildings, got %d" % (res["n_expected"], res["n_got"]))
    print("   osm_id sets identical: %s" % ok_ids)
    print("   max |elevation difference|: %.4f m" % dmax)
    if not res["passed"]:
        print("   >>> CONTROL FAILED. The generalised code does not reproduce "
              "the hand-built An Aird receptor result. Nothing below this "
              "line should be believed.", file=sys.stderr)
    else:
        print("   CONTROL PASSED -- generalised code reproduces An Aird "
              "Phase B section 6a exactly.")
    return res


def main() -> int:
    t0 = datetime.now(timezone.utc)
    OUT.mkdir(parents=True, exist_ok=True)

    hr("NATIONAL RECEPTOR-EXPOSURE SCREEN")
    print("run %s" % t0.isoformat(timespec="seconds"))
    print("imported gate FETCH_EXCLUSION_MAX = %s (the same Python object the "
          "Mizen screen\npre-registered on 11 Aug; this script does not use it "
          "to re-gate, only to record\nwhich gate produced the input set)"
          % FETCH_EXCLUSION_MAX)
    print("\nPRE-REGISTERED, fixed before any cluster was screened:")
    print("   receptor set      OSM buildings within %.0f m of the cluster "
          "centroid" % RECEPTOR_RADIUS_M)
    print("   occupied tag      building NOT in %s" % sorted(NON_OCCUPIED_TAGS))
    print("   low bands         GLO-30 elevation < 5 m and < 10 m")
    print("   EXPOSED RECEPTOR  an occupied-tag building below 5 m  <-- ranking key")
    print("   below 5 m is LOW-LYING, not proven exposed. A non-zero count is a")
    print("   flag for review, never a finding and never a euro.")

    sel = select_clusters()
    hr("1. SELECTION")
    print("   source: %s" % CANDIDATE_TABLE.relative_to(REPO))
    print("   rule:   pass_fetch_strict AND evidence_class in E1/E2/E3")
    print("   -> %d clusters" % len(sel))
    print(sel.evidence_class.value_counts().to_string())
    print("\n   by county:")
    print(sel.county.value_counts().to_string())
    if CONTROL_CLUSTER not in set(sel.cluster):
        print("   >>> control cluster %d is not in the selection" %
              CONTROL_CLUSTER, file=sys.stderr)
        return 2

    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)

    hr("2. OSM -- buildings at full tag detail, plus coastline")
    boxes = []
    for _, r in sel.iterrows():
        cx, cy = to_itm.transform(r.lon, r.lat)
        x0, y0 = to_wgs.transform(cx - BOX_HALF_M, cy - BOX_HALF_M)
        x1, y1 = to_wgs.transform(cx + BOX_HALF_M, cy + BOX_HALF_M)
        boxes.append((x0, y0, x1, y1))
    bld_wgs, coast_wgs = fetch_osm_for_boxes(boxes)
    print("   total: %d distinct buildings, %d coastline ways"
          % (len(bld_wgs), len(coast_wgs)))
    bld_itm = bld_wgs.to_crs(ITM)
    coast_u = (unary_union(coast_wgs.to_crs(ITM).geometry.values)
               if len(coast_wgs) else None)
    if coast_u is None:
        print("   >>> no coastline returned; shore distances will be NaN",
              file=sys.stderr)

    hr("3. CONTROL -- reproduce An Aird (cluster %d)" % CONTROL_CLUSTER)
    crow = sel[sel.cluster == CONTROL_CLUSTER].iloc[0]
    _, cnear = screen_cluster(crow, bld_itm, bld_wgs, coast_u, to_itm, to_wgs)
    control = control_check(cnear)

    hr("4. SCREEN -- every selected cluster")
    recs, all_near = [], []
    for i, r in sel.iterrows():
        rec, near = screen_cluster(r, bld_itm, bld_wgs, coast_u, to_itm, to_wgs)
        recs.append(rec)
        if len(near):
            all_near.append(near.drop(columns=["geometry"]))
        print("   [%2d/%2d] cluster %-5d %-9s %-34s  n=%-3d  min %5s m  "
              "<5m %d  <10m %d  EXPOSED %d"
              % (i + 1, len(sel), rec["cluster"], rec["county"],
                 str(rec["nearest_place"])[:34], rec["n_buildings_500m"],
                 "n/a" if rec["elev_min_m"] is None else "%.1f" % rec["elev_min_m"],
                 rec["n_below_5m"], rec["n_below_10m"], rec["exposed_receptors"]))

    res = pd.DataFrame(recs)
    res = res.sort_values(
        ["exposed_receptors", "n_below_5m", "n_occupied_below_10m",
         "elev_min_occupied_m"],
        ascending=[False, False, False, True]).reset_index(drop=True)
    res.insert(0, "rank", np.arange(1, len(res) + 1))

    hr("5. RANKED RESULT -- by exposed-receptor count")
    show = ["rank", "cluster", "county", "nearest_place", "evidence_class",
            "n_buildings_500m", "n_occupied_tag", "elev_min_m",
            "elev_min_occupied_m", "n_below_5m", "n_below_10m",
            "n_occupied_below_5m", "n_occupied_below_10m", "exposed_receptors"]
    with pd.option_context("display.width", 250, "display.max_rows", 200,
                           "display.max_colwidth", 30):
        print(res[show].to_string(index=False))

    tot_exposed = int(res.exposed_receptors.sum())
    hr("6. VERDICT")
    print("   clusters screened                     %d" % len(res))
    print("   buildings examined (with overlaps)    %d"
          % int(res.n_buildings_500m.sum()))
    if all_near:
        allb = pd.concat(all_near, ignore_index=True)
        print("   distinct buildings                    %d"
              % allb.osm_id.nunique())
    print("   buildings with a usable GLO-30 value  %d"
          % int(res.n_with_elevation.sum()))
    print("   buildings on a GLO-30 water pixel     %d  (elevation unknown, "
          "excluded from the bands)" % int(res.n_water_pixel.sum()))
    print("   buildings below 5 m                   %d" % int(res.n_below_5m.sum()))
    print("   buildings below 10 m                  %d" % int(res.n_below_10m.sum()))
    print("   EXPOSED RECEPTORS (occupied < 5 m)    %d" % tot_exposed)
    print("   clusters with >0 exposed receptors    %d"
          % int((res.exposed_receptors > 0).sum()))
    alt = int(res["exposed_receptors_if_water_pixels_use_land_neighbourhood"].sum())
    if alt != tot_exposed:
        print("   sensitivity: %d if water-pixel buildings are given their "
              "land-neighbourhood median" % alt)
    if tot_exposed == 0:
        print("\n   Every cluster is UNEXPOSED on this test. Under the rule "
              "locked on\n   27 Aug this is a genuine negative: the test could "
              "have returned\n   non-zero and did not.")
    else:
        print("\n   >>> AT LEAST ONE CLUSTER HAS LOW-LYING OCCUPIED BUILDINGS.")
        print("   >>> STOPPING BEFORE ANY EURO, as instructed. Habitat "
              "evidence at the\n   >>> E2/E3 sites is MODELLED, not surveyed; "
              "any value carries that label.")

    # ------------------------------------------------------------- outputs
    res_out = res.copy()
    res_out["opw_internal"] = res_out["opw_internal"].apply(json.dumps)
    res_out["opw_internal_calibration"] = \
        res_out["opw_internal_calibration"].apply(json.dumps)
    res_out["tag_counts"] = res_out["tag_counts"].apply(json.dumps)
    res_out.to_csv(OUT / "national_exposure_screen.csv", index=False)
    if all_near:
        pd.concat(all_near, ignore_index=True).to_csv(
            OUT / "national_exposure_receptors.csv", index=False)

    summary = {
        "run_utc": t0.isoformat(timespec="seconds"),
        "source_table": str(CANDIDATE_TABLE.relative_to(REPO)),
        "selection_rule": "pass_fetch_strict AND evidence_class in E1/E2/E3",
        "n_clusters": int(len(res)),
        "pre_registered": {
            "receptor_radius_m": RECEPTOR_RADIUS_M,
            "non_occupied_tags": sorted(NON_OCCUPIED_TAGS),
            "low_bands_m": list(LOW_BANDS_M),
            "exposed_receptor": "occupied-tag building with GLO-30 < 5 m",
            "fetch_gate_that_produced_the_input": FETCH_EXCLUSION_MAX,
            "shore_dist_m_used_by_the_input_screen": SHORE_DIST_M,
        },
        "control_an_aird": control,
        "elevation_source": "Copernicus WorldDEM-30 (GLO-30), DSM, 30 m",
        "elevation_notice": GLO30_NOTICE,
        "opw_use": ("INTERNAL CROSS-CHECK ONLY -- CC BY-NC-ND 4.0 unresolved, "
                    "CLAUDE.md rule 9. Counts and distances only; no visual "
                    "derivative exists."),
        "totals": {
            "buildings_examined_with_overlaps": int(res.n_buildings_500m.sum()),
            "buildings_with_elevation": int(res.n_with_elevation.sum()),
            "buildings_on_glo30_water_pixel": int(res.n_water_pixel.sum()),
            "buildings_below_5m": int(res.n_below_5m.sum()),
            "buildings_below_10m": int(res.n_below_10m.sum()),
            "exposed_receptors": tot_exposed,
            "exposed_receptors_water_pixel_sensitivity": alt,
            "clusters_with_exposed_receptors":
                int((res.exposed_receptors > 0).sum()),
        },
        "glo30_water_flattening": (
            "GLO-30 sets water surfaces to exactly 0.0 m and declares no "
            "nodata. A building whose 30 m pixel is classed as water reads "
            "0.0, which is an UNKNOWN ground elevation, not a low one. Such "
            "buildings are excluded from the < 5 m and < 10 m bands and "
            "counted in n_water_pixel."),
        "glo30_tile_edge_bug_fixed": (
            "Copernicus tiles are pixel-centre registered, so tile W010 "
            "spans lon [-10.000208, -9.000208]. Selecting a tile with "
            "floor(lon) puts a point at lon -10.00013 in the wrong tile, "
            "where rasterio.sample() returns 0.0 rather than raising "
            "because these COGs declare no nodata. The tile is now chosen "
            "by testing real bounds. This changed cluster 593 way/265358612 "
            "from 0.0 m to 18.7 m."),
        "clusters": recs,
    }
    (OUT / "national_exposure_screen_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("\n   wrote %s" % (OUT / "national_exposure_screen.csv")
          .relative_to(REPO))
    print("   wrote %s" % (OUT / "national_exposure_receptors.csv")
          .relative_to(REPO))
    print("   wrote %s" % (OUT / "national_exposure_screen_summary.json")
          .relative_to(REPO))
    return 0 if control["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
