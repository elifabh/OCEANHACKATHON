#!/usr/bin/env python3
"""
wide_receptor_screen.py
=======================
Phase A of the widened coastal-protection receptor screen (2026-08-27).

QUESTION
    Anywhere along the wider West Cork / Kerry Atlantic coast (Mizen,
    Sheep's Head, Beara, Iveragh/Kenmare River, Dingle), is there a stretch
    where ALL of these hold?
      (a) Laminaria habitat sits in front of the frontage:
            tier 1  NPWS Reef Inventory 2023, layer 21, Community =
                    "Laminaria-dominated reef" (subtidal), within HAB_SEARCH_M
            tier 2  our own step-2 suitability model (v2, threshold 0.7104),
                    where the model was actually run (four AOIs only)
      (b) built receptors sit behind it:
            OSM building centroids within SHORE_DIST_M of the OSM coastline,
            clustered with DBSCAN (>= CLUSTER_MIN_N buildings, eps
            CLUSTER_EPS_M) - the same settlement-scale rule as
            mizen_receptor_screen.py
      (c) the sea in front is exposed enough for the Dubi & Torum / Mork
          coefficients to be in domain:
            Burrows log10 fetch of the nearest sea cell > FETCH_EXCLUSION_MAX
            (3.73, the pre-registered gate carried over unchanged from
            src/mizen_receptor_screen.py).

WHAT CHANGED VERSUS mizen_receptor_screen.py, AND WHY
    - The OPW 1000-yr coastal flood extent is NOT used. Its licence
      (CC BY-NC-ND 4.0) is unresolved (CLAUDE.md rule 9). The "receptor"
      test is therefore SHORE PROXIMITY, not FLOOD EXPOSURE. That is a
      weaker test: a house 150 m from the shore on a 30 m cliff passes it.
      Elevation could not be added (Copernicus DEM via Earth Engine needs
      an interactive login that was not available). Every candidate in the
      output must be read with that in mind; Phase B is where elevation
      and flood exposure would be re-introduced once the OPW licence is
      cleared or an open DEM is on disk.
    - A habitat term is added. The Mizen screen only asked "receptors AND
      exposure"; this one also asks "AND mapped/modelled Laminaria".
    - The extent is ~150 km of coast in five regions plus the Baltimore
      control, instead of three boxes.

WHAT THIS IS NOT
    Not a valuation. No euro is computed here. It is a ranked candidate
    table for human review (Phase A). Phase B (valuation) is a separate
    decision.

OUTPUT
    outputs/wide_receptor_screen.csv             all clusters, ranked
    outputs/wide_receptor_screen_candidates.csv  clusters passing (a)+(b)+(c)
    outputs/wide_receptor_screen_summary.json    searched extent, counts,
                                                 parameters, data timestamps
    outputs/wide_receptor_screen_laminaria.geojson  the NPWS Laminaria
                                                 polygons in the extent
                                                 (for the review map)

CONTROL
    The Baltimore cluster from the 11 Aug screen (-9.374, 51.484) must
    reappear and must still FAIL the fetch gate. If it does not reappear,
    the building/coastline step is broken. If it passes the gate, the
    fetch sampling is broken.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.windows
import requests
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from sklearn.cluster import DBSCAN

from common import AOIS

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

# Searched extent, WGS84 (lon_min, lat_min, lon_max, lat_max). One box,
# fetched from Overpass in latitude bands. Covers Mizen Head to the north
# side of the Dingle peninsula (Brandon Bay). The eastern edge (-9.30)
# deliberately includes the sherkin_baltimore control box.
EXTENT = (-10.60, 51.42, -9.30, 52.30)
OVERPASS_LAT_BANDS = ((51.42, 51.62), (51.62, 51.82), (51.82, 52.02), (52.02, 52.30))

# Region labels for the review table: nearest anchor wins. Anchors are
# hand-placed on the peninsula spines / bay shores. They are LABELS ONLY;
# nothing is computed from them.
REGION_ANCHORS = {
    "roaringwater_control": [(-9.40, 51.48), (-9.48, 51.52), (-9.35, 51.50)],
    "mizen":               [(-9.82, 51.47), (-9.70, 51.49), (-9.60, 51.52), (-9.55, 51.53)],
    "sheeps_head":         [(-9.87, 51.58), (-9.75, 51.61), (-9.62, 51.64), (-9.55, 51.66)],
    "beara":               [(-10.18, 51.60), (-10.05, 51.64), (-9.90, 51.68), (-9.78, 51.73),
                            (-9.95, 51.75), (-10.10, 51.72), (-9.70, 51.78)],
    "iveragh_kenmare_n":   [(-10.05, 51.80), (-9.85, 51.86), (-10.25, 51.86), (-10.40, 51.92),
                            (-10.30, 51.98), (-10.10, 52.02), (-9.90, 52.05)],
    "dingle":              [(-10.50, 52.10), (-10.35, 52.14), (-10.20, 52.12), (-10.05, 52.15),
                            (-9.90, 52.18), (-9.75, 52.22), (-10.45, 52.05)],
}

NPWS_SHP = Path("data/npws/gis_files/21 NPWSArticle17Habitat.shp")
NPWS_TARGET = "laminaria-dominated reef"
MODEL_PRED = Path("outputs/model/suitability_multisite_predictions.csv")
MODEL_REPORT = Path("outputs/model/model_multisite_report.json")
FETCH_RASTER = Path("data/fetch/log10_eu200m1a.tif")

OUT_DIR = Path("outputs")
OUT_ALL = OUT_DIR / "wide_receptor_screen.csv"
OUT_CAND = OUT_DIR / "wide_receptor_screen_candidates.csv"
OUT_SUMMARY = OUT_DIR / "wide_receptor_screen_summary.json"
OUT_LAM = OUT_DIR / "wide_receptor_screen_laminaria.geojson"
OUT_BLD = OUT_DIR / "wide_receptor_screen_buildings.geojson"
BED_GPKG = Path("outputs/valuation/step3b2_flood_check.gpkg")  # layer kelp_cells = the locked 1.75 ha bed

# --- screen parameters ------------------------------------------------
SHORE_DIST_M = 200.0     # building counts as shore-proximate if <= this
SHORE_DIST_STRICT_M = 100.0  # reported per cluster, not used as a gate
CLUSTER_EPS_M = 300.0    # unchanged from mizen_receptor_screen.py
CLUSTER_MIN_N = 3        # unchanged
FETCH_SEARCH_M = 2000.0  # unchanged
TIE_TOL_M = 10.0         # sea cells within this of the minimum distance count as tied
HAB_SEARCH_M = 1000.0    # habitat must be within this of the cluster centroid

# --- the pre-registered decision rule, carried over UNCHANGED ----------
FETCH_EXCLUSION_MAX = 3.73   # inner_roaringwater maximum (mizen screen)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Mirrors, tried in order when the primary returns 429/504. Added
# 2026-08-27 for the national run: the primary was returning gateway
# timeouts and 93 queries against one degraded instance is not viable.
# Every mirror serves the same OSM database, and every response is
# cached by query hash, so which mirror answered cannot change a result.
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
# overpass.private.coffee was tried on 2026-08-27 and returned HTTP 500 to
# every request, including queries the primary answered in 2 s. Dropped: a
# mirror that always fails only burns retry attempts.
UA = "OceanHackathonCork2026/kelp-prototype (elif, MTU)"
ITM = "EPSG:2157"
BNG = "EPSG:27700"
WGS = "EPSG:4326"

# Baltimore control from outputs/mizen_receptor_screen.csv (11 Aug run)
CONTROL_LONLAT = (-9.37434, 51.48362)
CONTROL_MATCH_M = 400.0


# ----------------------------------------------------------------------
# 1. Overpass
# ----------------------------------------------------------------------

OSM_CACHE = Path("data/osm")


def overpass(query: str, retries: int = 12) -> dict:
    """POST to Overpass; cache the raw JSON under data/osm/ keyed by query hash
    so a re-run (e.g. after a parameter change) does not re-download ~90k
    buildings and can be reproduced against the same OSM snapshot."""
    import hashlib
    OSM_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(query.encode()).hexdigest()[:12]
    cached = OSM_CACHE / f"overpass_{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    for attempt in range(1, retries + 1):
        url = OVERPASS_MIRRORS[(attempt - 1) % len(OVERPASS_MIRRORS)]
        try:
            r = requests.post(url, data={"data": query},
                              headers={"User-Agent": UA}, timeout=300)
            r.raise_for_status()
            payload = r.json()
            if "elements" not in payload:
                raise RuntimeError(f"no 'elements' key from {url}")
            cached.write_text(json.dumps(payload), encoding="utf-8")
            return payload
        except Exception as exc:                        # noqa: BLE001
            if attempt == retries:
                raise RuntimeError(f"Overpass failed after {retries} attempts: {exc}") from exc
            # 429 = the public instance is rate-limiting us. That needs a much
            # longer wait than a transient error. Added 2026-08-27 for the
            # national run, which issues ~60 queries instead of ~9. Backoff
            # only; it cannot change any cached or returned result.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            wait = 30 * attempt if status in (429, 504) else 15 * attempt
            print(f"   Overpass attempt {attempt} on {url} failed ({exc}); "
                  f"retry in {wait}s on the next mirror",
                  file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


def fetch_buildings(bands) -> gpd.GeoDataFrame:
    lons, lats, kinds = [], [], []
    for (s, n) in bands:
        bb = f"{s},{EXTENT[0]},{n},{EXTENT[2]}"
        q = f"""[out:json][timeout:280];
        ( way["building"]({bb}); relation["building"]({bb}); );
        out center tags;"""
        payload = overpass(q)
        k = 0
        for el in payload.get("elements", []):
            c = el.get("center")
            if not c:
                continue
            lons.append(c["lon"]); lats.append(c["lat"])
            kinds.append((el.get("tags") or {}).get("building", "yes"))
            k += 1
        print(f"   buildings band {s}-{n}: {k}")
    gdf = gpd.GeoDataFrame({"building": kinds},
                           geometry=gpd.points_from_xy(lons, lats), crs=WGS)
    # de-duplicate anything sitting exactly on a band edge
    gdf = gdf[~gdf.geometry.duplicated()].reset_index(drop=True)
    return gdf


def fetch_coastline(bands) -> gpd.GeoDataFrame:
    geoms = []
    for (s, n) in bands:
        bb = f"{s},{EXTENT[0]},{n},{EXTENT[2]}"
        q = f"""[out:json][timeout:280];
        way["natural"="coastline"]({bb});
        out geom;"""
        payload = overpass(q)
        k = 0
        for el in payload.get("elements", []):
            pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
            if len(pts) >= 2:
                geoms.append(LineString(pts)); k += 1
        print(f"   coastline ways band {s}-{n}: {k}")
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=WGS)
    return gdf


def fetch_places() -> gpd.GeoDataFrame:
    bb = f"{EXTENT[1]},{EXTENT[0]},{EXTENT[3]},{EXTENT[2]}"
    q = f"""[out:json][timeout:180];
    node["place"~"^(city|town|village|hamlet|locality|island)$"]({bb});
    out;"""
    payload = overpass(q)
    rows = []
    for el in payload.get("elements", []):
        t = el.get("tags") or {}
        if "name" in t and el.get("lat") is not None:
            rows.append({"name": t["name"], "place": t.get("place"),
                         "lon": el["lon"], "lat": el["lat"]})
    df = pd.DataFrame(rows)
    print(f"   named places: {len(df)}")
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=WGS)


# ----------------------------------------------------------------------
# 2. habitat layers
# ----------------------------------------------------------------------

def load_npws_laminaria() -> gpd.GeoDataFrame:
    g = gpd.read_file(NPWS_SHP)
    g = g.cx[EXTENT[0]:EXTENT[2], EXTENT[1]:EXTENT[3]]
    lam = g[g["Community"].str.strip().str.lower() == NPWS_TARGET].copy()
    lam = lam.to_crs(ITM)
    lam["ha"] = lam.geometry.area / 1e4
    print(f"   NPWS Laminaria-dominated reef in extent: {len(lam)} polygons, "
          f"{lam['ha'].sum():.1f} ha, sites: "
          f"{lam.groupby('Site_name')['ha'].sum().round(1).to_dict()}")
    return lam


def load_model_cells() -> tuple[gpd.GeoDataFrame, float]:
    rep = json.loads(MODEL_REPORT.read_text())
    thr = float(rep["operating_threshold"])
    df = pd.read_csv(MODEL_PRED)
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat), crs=WGS).to_crs(ITM)
    print(f"   model cells: {len(g)} in AOIs {sorted(df.aoi.unique())}, threshold {thr}")
    return g, thr


# ----------------------------------------------------------------------
# 3. exposure (identical logic to mizen_receptor_screen.FetchSampler)
# ----------------------------------------------------------------------

class FetchSampler:
    def __init__(self, path: Path):
        self.src = rasterio.open(path)
        self.nodata = self.src.nodata
        self.to_bng = Transformer.from_crs(ITM, BNG, always_xy=True)

    def close(self):
        self.src.close()

    def sample(self, x_itm: float, y_itm: float, radius_m: float = FETCH_SEARCH_M) -> dict:
        x, y = self.to_bng.transform(x_itm, y_itm)
        win = rasterio.windows.from_bounds(x - radius_m, y - radius_m,
                                           x + radius_m, y + radius_m,
                                           transform=self.src.transform)
        arr = self.src.read(1, window=win, boundless=True, fill_value=np.nan).astype("float64")
        if arr.size == 0:
            return self._empty()
        valid = np.isfinite(arr)
        if self.nodata is not None:
            valid &= arr != self.nodata
        valid &= arr > 0
        if not valid.any():
            return self._empty()
        wt = rasterio.windows.transform(win, self.src.transform)
        rows, cols = np.nonzero(valid)
        xs = wt.c + (cols + 0.5) * wt.a + (rows + 0.5) * wt.b
        ys = wt.f + (cols + 0.5) * wt.d + (rows + 0.5) * wt.e
        d = np.hypot(xs - x, ys - y)
        inside = d <= radius_m
        if not inside.any():
            return self._empty()
        d = d[inside]; vals = arr[valid][inside]
        dmin = float(d.min())
        # TIE HANDLING (added 27 Aug). On a 200 m raster a cluster sitting on
        # a neck of land can have several sea cells at the SAME distance on
        # different sides. np.argmin would then pick one by floating-point
        # noise, and the 11 Aug screen's "fetch_nearest" would be an
        # accident of array order. All cells within TIE_TOL_M of the minimum
        # distance are reported: the gate is evaluated on the LEAST exposed
        # of them (strict) and on the MOST exposed (lenient), and a cluster
        # is flagged when the two disagree.
        tied = d <= dmin + TIE_TOL_M
        tv = vals[tied]
        return {"fetch_nearest_min": float(tv.min()), "fetch_nearest_max": float(tv.max()),
                "n_tied": int(tied.sum()),
                "fetch_max": float(np.nanmax(vals)),
                "dist_to_sea_m": dmin, "n_sea_cells": int(inside.sum())}

    @staticmethod
    def _empty() -> dict:
        return {"fetch_nearest_min": np.nan, "fetch_nearest_max": np.nan, "n_tied": 0,
                "fetch_max": np.nan, "dist_to_sea_m": np.nan, "n_sea_cells": 0}


# ----------------------------------------------------------------------
# 4. helpers
# ----------------------------------------------------------------------

def region_of(lon: float, lat: float) -> str:
    best, bestd = None, 1e9
    for name, pts in REGION_ANCHORS.items():
        for (alon, alat) in pts:
            d = np.hypot((lon - alon) * np.cos(np.radians(lat)), lat - alat)
            if d < bestd:
                best, bestd = name, d
    return best


def main() -> int:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("== habitat layers ==")
    lam = load_npws_laminaria()
    lam[["Site_name", "Extent", "Source", "ha", "geometry"]].to_crs(WGS).to_file(OUT_LAM, driver="GeoJSON")
    cells, thr = load_model_cells()
    bed = gpd.read_file(BED_GPKG, layer="kelp_cells").to_crs(ITM)
    bed_union = bed.geometry.buffer(25, cap_style="square").union_all()
    print(f"   locked Sherkin bed: {len(bed)} cells, {bed_union.area/1e4:.2f} ha")
    cells_pos = cells[cells["suitability"] >= thr]
    cells_pos_assessed = cells_pos[cells_pos["assessed"] == 1]

    print("== OSM ==")
    bld = fetch_buildings(OVERPASS_LAT_BANDS)
    print(f"   buildings total (deduplicated): {len(bld)}")
    coast = fetch_coastline(OVERPASS_LAT_BANDS)
    places = fetch_places()
    if bld.empty or coast.empty:
        print("OSM returned nothing for buildings or coastline. Zero here is a bug.")
        return 1

    bld = bld.to_crs(ITM)
    coast = coast.to_crs(ITM)
    places = places.to_crs(ITM)

    print("== shore proximity ==")
    tree = STRtree(coast.geometry.values)
    near_idx = tree.nearest(bld.geometry.values)
    bld["dist_shore_m"] = [
        bld.geometry.values[i].distance(coast.geometry.values[j]) for i, j in enumerate(near_idx)
    ]
    shore = bld[bld["dist_shore_m"] <= SHORE_DIST_M].copy()
    print(f"   buildings within {SHORE_DIST_M:.0f} m of coastline: {len(shore)} of {len(bld)}")

    print("== clustering ==")
    xy = np.c_[shore.geometry.x.values, shore.geometry.y.values]
    labels = DBSCAN(eps=CLUSTER_EPS_M, min_samples=CLUSTER_MIN_N).fit_predict(xy)
    shore["cluster"] = labels
    n_noise = int((labels == -1).sum())
    print(f"   clusters: {len(set(labels)) - (1 if -1 in labels else 0)} "
          f"(+{n_noise} isolated shore buildings dropped)")

    print("== per-cluster evidence ==")
    sampler = FetchSampler(FETCH_RASTER)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    lam_tree = STRtree(lam.geometry.values)
    place_tree = STRtree(places.geometry.values)
    rows = []
    try:
        for cid in sorted(set(labels)):
            if cid == -1:
                continue
            sub = shore[shore["cluster"] == cid]
            cx, cy = float(sub.geometry.x.mean()), float(sub.geometry.y.mean())
            cp = Point(cx, cy)
            lon, lat = to_wgs.transform(cx, cy)

            f = sampler.sample(cx, cy)

            # tier 1: NPWS Laminaria
            hits = lam_tree.query(cp.buffer(HAB_SEARCH_M), predicate="intersects")
            if len(hits):
                lam_sub = lam.iloc[hits]
                lam_dist = float(min(g.distance(cp) for g in lam_sub.geometry))
                lam_ha = float(lam_sub.geometry.intersection(cp.buffer(HAB_SEARCH_M)).area.sum() / 1e4)
                lam_site = "; ".join(sorted(set(lam_sub["Site_name"])))
            else:
                lam_dist, lam_ha, lam_site = np.nan, 0.0, ""

            # tier 2: model cells (only meaningful inside the four AOIs)
            d_cells = cells.geometry.distance(cp)
            in_r = d_cells <= HAB_SEARCH_M
            n_cells = int(in_r.sum())
            n_pos = int((in_r & (cells["suitability"] >= thr)).sum())
            n_pos_assessed = int((in_r & (cells["suitability"] >= thr) & (cells["assessed"] == 1)).sum())
            model_max = float(cells.loc[in_r, "suitability"].max()) if n_cells else np.nan

            # nearest named place
            pj = place_tree.nearest(cp)
            place = places.iloc[pj]
            place_d = float(place.geometry.distance(cp))

            bed_dist = float(bed_union.distance(cp))

            has_hab = bool(len(hits) > 0 or n_pos_assessed > 0)
            fetch_strict = bool(np.isfinite(f["fetch_nearest_min"]) and f["fetch_nearest_min"] > FETCH_EXCLUSION_MAX)
            fetch_lenient = bool(np.isfinite(f["fetch_nearest_max"]) and f["fetch_nearest_max"] > FETCH_EXCLUSION_MAX)
            fetch_ok = fetch_lenient
            rows.append({
                "region": region_of(lon, lat),
                "nearest_place": f"{place['name']} ({place['place']}, {place_d/1000:.1f} km)",
                "cluster": int(cid),
                "n_buildings_200m": int(len(sub)),
                "n_buildings_100m": int((sub["dist_shore_m"] <= SHORE_DIST_STRICT_M).sum()),
                "min_dist_shore_m": round(float(sub["dist_shore_m"].min()), 1),
                "lon": round(lon, 5), "lat": round(lat, 5),
                "fetch_nearest_min": round(f["fetch_nearest_min"], 3) if np.isfinite(f["fetch_nearest_min"]) else np.nan,
                "fetch_nearest_max": round(f["fetch_nearest_max"], 3) if np.isfinite(f["fetch_nearest_max"]) else np.nan,
                "n_tied_sea_cells": f["n_tied"],
                "fetch_max_2km": round(f["fetch_max"], 3) if np.isfinite(f["fetch_max"]) else np.nan,
                "dist_to_sea_cell_m": round(f["dist_to_sea_m"], 0) if np.isfinite(f["dist_to_sea_m"]) else np.nan,
                "npws_lam_dist_m": round(lam_dist, 0) if np.isfinite(lam_dist) else np.nan,
                "npws_lam_ha_1km": round(lam_ha, 2),
                "npws_site": lam_site,
                "model_cells_1km": n_cells,
                "model_pos_1km": n_pos,
                "model_pos_assessed_1km": n_pos_assessed,
                "model_max_suit_1km": round(model_max, 3) if np.isfinite(model_max) else np.nan,
                "locked_bed_dist_m": round(bed_dist, 0),
                "pass_fetch_strict": fetch_strict,
                "pass_fetch": fetch_ok,
                "fetch_tie_ambiguous": bool(fetch_lenient and not fetch_strict),
                "pass_habitat": has_hab,
                "candidate": bool(fetch_ok and has_hab),
            })
    finally:
        sampler.close()

    df = pd.DataFrame(rows)
    if df.empty:
        print("No shore-proximate building clusters anywhere in the extent. "
              "That is a bug (Baltimore alone should appear), not a finding.")
        return 1

    shore[shore["cluster"] >= 0].assign(dist_shore_m=lambda d: d.dist_shore_m.round(1)).to_crs(WGS).to_file(OUT_BLD, driver="GeoJSON")
    df = df.sort_values(["candidate", "pass_fetch", "fetch_nearest_max", "npws_lam_ha_1km"],
                        ascending=[False, False, False, False]).reset_index(drop=True)
    df.to_csv(OUT_ALL, index=False)
    cand = df[df["candidate"]]
    cand.to_csv(OUT_CAND, index=False)

    # control
    ctrl_xy = Transformer.from_crs(WGS, ITM, always_xy=True).transform(*CONTROL_LONLAT)
    cxy = np.array([Transformer.from_crs(WGS, ITM, always_xy=True).transform(r.lon, r.lat) for r in df.itertuples()])
    cd = np.hypot(cxy[:, 0] - ctrl_xy[0], cxy[:, 1] - ctrl_xy[1])
    ctrl_found = bool((cd <= CONTROL_MATCH_M).any())
    ctrl_row = df.iloc[int(np.argmin(cd))] if ctrl_found else None

    summary = {
        "run_utc": t0,
        "extent_wgs84": EXTENT,
        "parameters": {
            "SHORE_DIST_M": SHORE_DIST_M, "CLUSTER_EPS_M": CLUSTER_EPS_M,
            "CLUSTER_MIN_N": CLUSTER_MIN_N, "FETCH_SEARCH_M": FETCH_SEARCH_M,
            "HAB_SEARCH_M": HAB_SEARCH_M, "FETCH_EXCLUSION_MAX": FETCH_EXCLUSION_MAX,
            "model_threshold": thr,
        },
        "inputs": {
            "osm_buildings_total": int(len(bld)),
            "osm_buildings_within_shore_dist": int(len(shore)),
            "osm_coastline_ways": int(len(coast)),
            "npws_laminaria_polygons": int(len(lam)),
            "npws_laminaria_ha": round(float(lam["ha"].sum()), 1),
            "npws_laminaria_by_site_ha": {k: round(v, 1) for k, v in lam.groupby("Site_name")["ha"].sum().items()},
            "model_cells_total": int(len(cells)),
            "model_cells_positive": int(len(cells_pos)),
            "model_cells_positive_assessed": int(len(cells_pos_assessed)),
            "opw_flood_layer_used": False,
            "elevation_used": False,
        },
        "results": {
            "clusters": int(len(df)),
            "clusters_pass_fetch_lenient": int(df["pass_fetch"].sum()),
            "clusters_pass_fetch_strict": int(df["pass_fetch_strict"].sum()),
            "clusters_fetch_tie_ambiguous": int(df["fetch_tie_ambiguous"].sum()),
            "candidates_strict": int((df["candidate"] & df["pass_fetch_strict"]).sum()),
            "clusters_pass_habitat": int(df["pass_habitat"].sum()),
            "candidates": int(len(cand)),
            "clusters_by_region": df.groupby("region").size().to_dict(),
            "pass_fetch_by_region": df.groupby("region")["pass_fetch"].sum().astype(int).to_dict(),
            "pass_habitat_by_region": df.groupby("region")["pass_habitat"].sum().astype(int).to_dict(),
        },
        "control": {
            "baltimore_found": ctrl_found,
            "baltimore_row": (ctrl_row.to_dict() if ctrl_row is not None else None),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))

    pd.set_option("display.width", 250)
    print("\n" + "=" * 100)
    print(df.head(40).to_string(index=False))
    print("=" * 100)
    print(json.dumps(summary["results"], indent=2))
    print("control:", "Baltimore FOUND" if ctrl_found else "Baltimore NOT FOUND - screen broken",
          "" if ctrl_row is None else f"(pass_fetch={ctrl_row['pass_fetch']}, fetch_nearest_min/max={ctrl_row['fetch_nearest_min']}/{ctrl_row['fetch_nearest_max']})")
    print(f"\nVERDICT (extent {EXTENT}, shore-proximity receptor test, no flood/elevation term): "
          f"{len(cand)} cluster(s) pass habitat AND fetch gate (lenient tie rule); "
          f"{int((cand['pass_fetch_strict']).sum())} under the strict tie rule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
