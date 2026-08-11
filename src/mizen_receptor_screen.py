#!/usr/bin/env python3
"""
mizen_receptor_screen.py
========================
One joint screen instead of three separate site checks.

QUESTION
    Is there any stretch of the Mizen coast where BOTH conditions hold?
      (a) the adjacent sea is exposed  -> high Burrows log10 fetch, so the
          Dubi & Torum (1996) / Mork (1996) coefficients are inside their
          stated domain (L. hyperborea, exposed coast);
      (b) there are built receptors behind it -> OSM building centroids
          falling inside the OPW 1000-yr coastal flood extent.

    Step 3B2 at Sherkin answered (b) alone and got ~0.4 ha of raster
    artefacts. Answering (a) and (b) in the SAME table is what tells us
    whether "exposed" and "inhabited" are anti-correlated on this coast,
    which is the real hypothesis under test.

WHAT THIS IS NOT
    Not a valuation. Not a kelp map. It is a site-selection screen whose
    only job is to decide where (if anywhere) the valuation engine has a
    legitimate input.

OUTPUT
    outputs/mizen_receptor_screen.csv  - one row per receptor cluster,
    ranked by the fetch of the nearest sea cell.

FIXES CARRIED IN FROM THE 10 AUG NOTE
    - Uses the 1000-yr extent ONLY. Never sums return periods.
    - Drops flood polygons < MIN_POLY_M2 (Sherkin median polygon was
      75 m2; minimum 25 m2 = one 5 m DTM pixel).
    - Clips to the AOI before reporting any area.
    - Runs sherkin_baltimore as a control. A screen that finds no
      buildings at Baltimore is broken, not informative.

LICENCE WARNING (unresolved, see note section 8)
    OPW flood data is labelled CC BY-NC-ND 4.0 on data.gov.ie. Do not
    publish anything derived from it before flood_data@opw.ie replies.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from shapely.geometry import box
from sklearn.cluster import DBSCAN

# ----------------------------------------------------------------------
# CONFIG  -- CHECK THESE THREE THINGS BEFORE THE FIRST RUN
# ----------------------------------------------------------------------

# 1. AOI boxes. These are APPROXIMATE, written without sight of common.py.
#    Replace with the exact boxes from src/common.py. Do not trust mine.
from common import AOIS
AOI_BBOX = {k: tuple(AOIS[k]) for k in ("mizen_outer", "sherkin_baltimore")}
# Screening-only box. NOT an AOI — common.py'ye dokunmuyor, step 1/2
# provenance'ı bozmuyor. mizen_outer -9.74'te bitiyor; Crookhaven ve
# Goleen daha doğuda.
AOI_BBOX["mizen_east_screen"] = (-9.74, 51.44, -9.66, 51.52)

# 2. Path to the OPW 1000-yr coastal extent shapefile, unzipped.
#    Inside ncfhm_itm_ext_c_c_1000yr_200yr_10yr.zip. Pick the 1000-yr one.
#    Erratum 2024-10-10 swapped the 2-yr and 100-yr files - neither is used
#    here, but confirm the filename says 1000.
OPW_1000YR = Path(
    "data/opw/ncfhm_itm_ext_c_c_1000yr_200yr_10yr/"
    "NCFHM_2022_Current_Scenario_1000yr_200yr_10ry/"
    "ncfhm_itm_ext_c_c_1000.shp"
)

# 3. Burrows 200 m log10 fetch raster, EPSG:27700. Already locked.
FETCH_RASTER = Path("data/fetch/log10_eu200m1a.tif")

OUT_CSV = Path("outputs/mizen_receptor_screen.csv")

# --- screen parameters ------------------------------------------------
MIN_POLY_M2 = 500.0     # discard flood polygons below this (artefact filter)
CLUSTER_EPS_M = 300.0   # DBSCAN neighbourhood: settlement-scale
CLUSTER_MIN_N = 3       # fewer than 3 buildings is not a receptor
FETCH_SEARCH_M = 2000.0 # radius to look seaward for a valid fetch cell

# --- the pre-registered decision rule ---------------------------------
# Locked in the 07 Aug / 10 Aug notes: inner_roaringwater was excluded on
# species grounds (MERC 2007: Saccharina / Saccorhiza, not L. hyperborea)
# and its cells top out at log10_fetch 3.73. Applying the project's own
# exclusion logic consistently, a receptor cluster only qualifies if the
# sea in front of it is MORE exposed than the most exposed cell of an AOI
# we already threw out.
FETCH_EXCLUSION_MAX = 3.73   # inner_roaringwater maximum
FETCH_MIZEN_MEDIAN = 4.07    # mizen_outer median, for context only

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ITM = "EPSG:2157"   # Irish Transverse Mercator
BNG = "EPSG:27700"  # Burrows raster CRS


# ----------------------------------------------------------------------
# 1. buildings
# ----------------------------------------------------------------------

def fetch_osm_buildings(bbox: tuple[float, float, float, float],
                        retries: int = 3) -> gpd.GeoDataFrame:
    """Building centroids from OSM Overpass.

    `out center` returns one point per way/relation instead of the full
    polygon ring. For counting receptors a centroid is sufficient and the
    payload is roughly an order of magnitude smaller.

    OSM coverage in rural West Cork is incomplete. If a village you can
    see on the OSI orthophoto comes back with a handful of buildings,
    that is an OSM gap, not an absence of houses -- fall back to the
    Microsoft Global ML Building Footprints (CDLA-Permissive-2.0).
    GeoHive Prime2 is NOT an option: restricted to public-sector bodies
    under the National Mapping Agreement.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    # Overpass bbox order is (south, west, north, east).
    bb = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    query = f"""
    [out:json][timeout:180];
    (
      way["building"]({bb});
      relation["building"]({bb});
    );
    out center tags;
    """

    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": "OceanHackathonCork2026/kelp-prototype (elif, MTU)"},
                timeout=200,
            )
            r.raise_for_status()
            payload = r.json()
            break
        except Exception as exc:                       # noqa: BLE001
            if attempt == retries:
                raise RuntimeError(
                    f"Overpass failed after {retries} attempts: {exc}"
                ) from exc
            wait = 10 * attempt
            print(f"   Overpass attempt {attempt} failed ({exc}); "
                  f"retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)

    lons, lats, kinds = [], [], []
    for el in payload.get("elements", []):
        c = el.get("center") or (
            {"lat": el.get("lat"), "lon": el.get("lon")}
            if el.get("lat") is not None else None
        )
        if not c or c.get("lat") is None:
            continue
        lons.append(c["lon"])
        lats.append(c["lat"])
        kinds.append((el.get("tags") or {}).get("building", "yes"))

    if not lons:
        return gpd.GeoDataFrame(
            {"building": []}, geometry=[], crs="EPSG:4326"
        )

    gdf = gpd.GeoDataFrame(
        {"building": kinds},
        geometry=gpd.points_from_xy(lons, lats),
        crs="EPSG:4326",
    )
    return gdf


# ----------------------------------------------------------------------
# 2. flood extent
# ----------------------------------------------------------------------

def load_flood_extent(path: Path,
                      bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """OPW 1000-yr coastal extent, clipped to the AOI, artefacts removed.

    Reads with a bbox filter so the 118 MB national file is never fully
    materialised. The bbox is given in WGS84 and reprojected to the
    file's own CRS first, because gpd.read_file(bbox=...) interprets the
    bbox in the CRS of the file unless a GeoSeries is passed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"OPW 1000-yr shapefile not found at {path}. "
            "Unzip ncfhm_itm_ext_c_c_1000yr_200yr_10yr.zip and set OPW_1000YR."
        )

    aoi_wgs = gpd.GeoSeries([box(*bbox)], crs="EPSG:4326")
    gdf = gpd.read_file(path, bbox=aoi_wgs)
    if gdf.empty:
        return gdf.to_crs(ITM)

    gdf = gdf.to_crs(ITM)
    aoi_itm = aoi_wgs.to_crs(ITM).iloc[0]

    # Clip, not intersect. esriSpatialRelIntersects-style selection returns
    # whole polygons and inflates every area figure downstream.
    gdf = gpd.clip(gdf, aoi_itm)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)

    gdf["area_m2"] = gdf.geometry.area
    kept = gdf[gdf["area_m2"] >= MIN_POLY_M2].copy()
    return kept


# ----------------------------------------------------------------------
# 3. exposure
# ----------------------------------------------------------------------

class FetchSampler:
    """Nearest-sea-cell fetch lookup against the Burrows raster.

    No coastline vector is needed. The Burrows surface is defined over
    water only, so any valid cell IS sea. For a receptor cluster we take
    the nearest valid cell within FETCH_SEARCH_M and also the maximum
    within that radius -- nearest answers "what is immediately in front",
    maximum answers "is open water reachable at all".
    """

    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"Burrows fetch raster not found at {path}")
        self.src = rasterio.open(path)
        self.nodata = self.src.nodata
        self.to_bng = Transformer.from_crs(ITM, BNG, always_xy=True)

    def close(self):
        self.src.close()

    def sample(self, x_itm: float, y_itm: float,
               radius_m: float = FETCH_SEARCH_M) -> dict:
        x, y = self.to_bng.transform(x_itm, y_itm)

        win = rasterio.windows.from_bounds(
            x - radius_m, y - radius_m, x + radius_m, y + radius_m,
            transform=self.src.transform,
        )
        try:
            arr = self.src.read(1, window=win, boundless=True,
                                fill_value=np.nan).astype("float64")
        except Exception:                               # noqa: BLE001
            return self._empty()

        if arr.size == 0:
            return self._empty()

        valid = np.isfinite(arr)
        if self.nodata is not None:
            valid &= arr != self.nodata
        # Burrows log10 fetch is strictly positive over water; land and
        # fill come through as <= 0 in some builds of this raster.
        valid &= arr > 0
        if not valid.any():
            return self._empty()

        wt = rasterio.windows.transform(win, self.src.transform)
        rows, cols = np.nonzero(valid)
        # cell centres
        xs = wt.c + (cols + 0.5) * wt.a + (rows + 0.5) * wt.b
        ys = wt.f + (cols + 0.5) * wt.d + (rows + 0.5) * wt.e

        d = np.hypot(xs - x, ys - y)
        inside = d <= radius_m
        if not inside.any():
            return self._empty()

        d = d[inside]
        vals = arr[valid][inside]
        i = int(np.argmin(d))
        return {
            "fetch_nearest": float(vals[i]),
            "fetch_max": float(np.nanmax(vals)),
            "dist_to_sea_m": float(d[i]),
            "n_sea_cells": int(inside.sum()),
        }

    @staticmethod
    def _empty() -> dict:
        return {"fetch_nearest": np.nan, "fetch_max": np.nan,
                "dist_to_sea_m": np.nan, "n_sea_cells": 0}


# ----------------------------------------------------------------------
# 4. screen one AOI
# ----------------------------------------------------------------------

def screen_aoi(name: str, bbox, sampler: FetchSampler) -> pd.DataFrame:
    print(f"\n=== {name} ===")

    flood = load_flood_extent(OPW_1000YR, bbox)
    print(f"  OPW 1000-yr, clipped, >={MIN_POLY_M2:.0f} m2: "
          f"{len(flood)} polygons, {flood['area_m2'].sum()/1e4:.2f} ha")
    if flood.empty:
        print("  no flood extent in this AOI -> no receptors possible")
        return pd.DataFrame()

    bld = fetch_osm_buildings(bbox)
    print(f"  OSM buildings in box: {len(bld)}")
    if bld.empty:
        print("  OSM returned nothing. Check the bbox before believing this.")
        return pd.DataFrame()

    bld = bld.to_crs(ITM)
    hit = gpd.sjoin(bld, flood[["geometry"]], how="inner",
                    predicate="within").drop(columns=["index_right"])
    hit = hit[~hit.index.duplicated(keep="first")]
    print(f"  buildings inside the 1000-yr extent: {len(hit)}")
    if hit.empty:
        return pd.DataFrame()

    xy = np.c_[hit.geometry.x.values, hit.geometry.y.values]
    labels = DBSCAN(eps=CLUSTER_EPS_M,
                    min_samples=CLUSTER_MIN_N).fit_predict(xy)
    hit = hit.assign(cluster=labels)

    rows = []
    for cid in sorted(set(labels)):
        if cid == -1:      # DBSCAN noise: isolated buildings
            continue
        sub = hit[hit["cluster"] == cid]
        cx, cy = float(sub.geometry.x.mean()), float(sub.geometry.y.mean())
        f = sampler.sample(cx, cy)
        lon, lat = Transformer.from_crs(
            ITM, "EPSG:4326", always_xy=True).transform(cx, cy)
        rows.append({
            "aoi": name,
            "cluster": int(cid),
            "n_buildings": int(len(sub)),
            "lon": round(lon, 5),
            "lat": round(lat, 5),
            **f,
            "qualifies": bool(
                np.isfinite(f["fetch_nearest"])
                and f["fetch_nearest"] > FETCH_EXCLUSION_MAX
            ),
        })

    n_noise = int((labels == -1).sum())
    print(f"  clusters: {len(rows)} (+{n_noise} isolated buildings dropped)")
    return pd.DataFrame(rows)


def main() -> int:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    sampler = FetchSampler(FETCH_RASTER)
    try:
        parts = [screen_aoi(n, bb, sampler) for n, bb in AOI_BBOX.items()]
    finally:
        sampler.close()

    df = pd.concat([p for p in parts if not p.empty], ignore_index=True) \
        if any(not p.empty for p in parts) else pd.DataFrame()

    if df.empty:
        print("\nNo receptor clusters found in any AOI.")
        print("Before reporting zero: confirm the AOI boxes and that OSM "
              "returned buildings. A zero that comes from a wrong bbox is "
              "a bug, not a finding.")
        return 1

    df = df.sort_values(["qualifies", "fetch_nearest", "n_buildings"],
                        ascending=[False, False, False]).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False)

    print("\n" + "=" * 72)
    print(df.to_string(index=False))
    print("=" * 72)
    print(f"\nthreshold: fetch_nearest > {FETCH_EXCLUSION_MAX} "
          f"(inner_roaringwater max, already-excluded AOI)")
    print(f"context:   mizen_outer median fetch = {FETCH_MIZEN_MEDIAN}")

    q = df[df["qualifies"]]
    if q.empty:
        print("\nVERDICT: no receptor cluster on the Mizen coast sits behind "
              "water more exposed than an AOI we already excluded.")
        print("Exposed and inhabited are anti-correlated here. Report that "
              "as the finding and move to steps 4-6.")
    else:
        print(f"\nVERDICT: {len(q)} candidate cluster(s). "
              "Next: confirm substrate in the 4-10 m band in front of the "
              "top one. National Folk polygons will not have it "
              "(0 px shallower than 11 m across all four AOIs) -- this is "
              "where the Sentinel-2 substrate proxy has to carry the load.")

    print("\nControl check: sherkin_baltimore must return Baltimore village. "
          "If it does not, the screen is broken, not the coast.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())