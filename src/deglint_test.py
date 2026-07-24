#!/usr/bin/env python3
"""
deglint_test.py - THE FEASIBILITY DECISION.

QUESTION
After sun-glint removal, does the shallow strip retain more structure than
optically deep water? If yes, a bottom-influenced signal reaches the sensor and
the optical detection path stays open. If no, the architecture falls back to a
habitat-suitability model.

ESTABLISHED METHOD
Sun-glint removal follows Hedley, Harborne & Mumby (2005), Int. J. Remote
Sensing 26(10):2107-2112. Over an optically deep, homogeneous sample, regress
each visible band on NIR and subtract the NIR-correlated component:

    R_i' = R_i - b_i * (R_NIR - min(R_NIR)_deep)

Wilson et al. (2020), Front. Environ. Sci. 8:579856 apply the same correction
to submerged kelp in optically complex temperate water.

OURS, AND SIMPLIFIED - NOT PUBLISHED METHOD
  - Applied POINT-WISE on a sampling grid, not on the full raster. Enough for a
    statistical test; not a mapping product.
  - TOA reflectance (L1C). No water-specific atmospheric correction yet.
    ACOLITE would sit before this step in the real pipeline.
  - "Structure" here is the standard deviation across scattered sample points,
    which is not the same thing as spatial texture.

THREE CORRECTIONS OVER THE FIRST DRAFT OF THIS SCRIPT
  1. HELD-OUT GLINT FIT. Fitting the correction on deep water necessarily
     suppresses variance in that same deep water. Comparing shallow against the
     fitting sample would bias the test toward a positive result. The deep
     points are therefore split 50/50: half fit the correction, half are held
     out for the comparison.
  2. GRID-INDEX JOIN. INFOMAR may return pixel-centre coordinates rather than
     the requested ones, so a rounded lon/lat join can silently drop rows. Both
     sources are mapped back to their originating grid cell instead.
  3. SURFACE CONTAMINATION CHECK. Breaking waves and whitecaps are brightest in
     shallow water and are broadband, so they can masquerade as bottom signal.
     Mean NIR by stratum is reported as a guard.

WHAT THIS CAN AND CANNOT SHOW
  CAN: whether variance survives in shallow water that does not survive in
       deep water - i.e. whether ANY bottom-influenced signal exists.
  CANNOT: that the signal is kelp. Bathymetric relief alone produces variance,
       which is why variance remaining after a depth trend is removed is also
       reported. Species attribution is not achievable from 10 m multispectral
       data (Wilson et al. 2020).

INPUTS
  Sentinel-2 L1C, 2021-05-28, tile 29UMT, tide 0.27 m LAT, sun elevation 59 deg.
  INFOMAR bathymetry, LAT datum (confirmed in report ROS_GEO19_04_FINAL),
  ~4.2 m ground resolution, CC BY 4.0.

Usage:
    python deglint_test.py
    python deglint_test.py --aoi mizen_outer --grid 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ee
import pandas as pd
import requests

from common import (
    AOIS,
    ATTRIBUTION,
    BEST_SCENE_DATE,
    CATEGORY_PRIMARY,
    EE_PROJECT,
    INFOMAR_BATHY,
    PRIMARY_AOI,
    chunked,
    grid_points,
)

OUT_DIR = Path("outputs/deglint")
VIS_BANDS = ["B2", "B3", "B4"]
NIR_BAND = "B8"

MGRS_TILE = "29UMT"
SCENE_TIDE_M_LAT = 0.27      # tide height at overpass, Union Hall Harbor gauge

SHALLOW_MAX = 12.0           # kelp band plus margin, metres below the surface
DEEP_MIN = 30.0              # optically deep for these waters
GLINT_SAMPLE_MIN = 40.0      # depth from which glint-fit candidates are drawn

CS_THRESHOLD = 0.60          # Cloud Score+ 'cs'; higher is clearer
RANDOM_SEED = 42

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OceanHackathonCork2026/kelp-prototype"})


# ---------------------------------------------------------------------------
# Grid bookkeeping - the robust join key
# ---------------------------------------------------------------------------

def grid_key(lon: float, lat: float, bbox: list[float], nx: int, ny: int) -> str:
    """Map any coordinate back to the grid cell it came from.

    Cell spacing at grid=50 over a 0.10 degree box is about 130 m, far larger
    than the 4.2 m bathymetry pixel, so pixel-centre snapping cannot move a
    sample into the wrong cell.
    """
    xmin, ymin, xmax, ymax = bbox
    dx = (xmax - xmin) / nx
    dy = (ymax - ymin) / ny
    i = int(round((lon - xmin) / dx - 0.5))
    j = int(round((lat - ymin) / dy - 0.5))
    return f"{i}_{j}"


# ---------------------------------------------------------------------------
# 1. Bathymetry (INFOMAR, LAT datum)
# ---------------------------------------------------------------------------

def sample_bathymetry(points: list[list[float]]) -> pd.DataFrame:
    mosaic_rule = json.dumps(
        {"mosaicMethod": "esriMosaicNorthwest",
         "where": f"Category = {CATEGORY_PRIMARY}"}
    )
    rows = []
    n_batches = (len(points) + 99) // 100
    for k, batch in enumerate(chunked(points, 100), 1):
        params = {
            "geometry": json.dumps(
                {"points": batch, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            "mosaicRule": mosaic_rule,
            "f": "json",
        }
        for attempt in range(3):
            try:
                resp = SESSION.post(f"{INFOMAR_BATHY}/getSamples",
                                    data=params, timeout=90)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                print(f"    batch {k}/{n_batches} retry {attempt + 1}/3: {exc}")
        else:
            raise RuntimeError(
                f"INFOMAR batch {k} failed 3 times. This is a REQUEST failure, "
                "not a coverage result. Re-run.")

        payload = resp.json()
        if "error" in payload:
            raise RuntimeError(f"ArcGIS error: {payload['error']}")
        for s in payload.get("samples", []):
            raw = s.get("value")
            if raw in (None, "", "NaN"):
                continue
            try:
                elev = float(str(raw).split()[0])
            except ValueError:
                continue
            loc = s.get("location", {})
            rows.append({"b_lon": loc.get("x"), "b_lat": loc.get("y"),
                         "elev_lat_m": elev})
        print(f"    batch {k}/{n_batches} done ({len(rows)} samples so far)")

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No bathymetry returned for this AOI.")

    # INFOMAR convention: negative below datum. Convert to depth below LAT, then
    # to depth below the instantaneous water surface at the overpass moment.
    # Both INFOMAR and the ERDDAP tide gauge are on LAT, so no datum offset.
    df["depth_lat_m"] = -df["elev_lat_m"]
    df["depth_inst_m"] = df["depth_lat_m"] + SCENE_TIDE_M_LAT
    return df


# ---------------------------------------------------------------------------
# 2. Sentinel-2 reflectance
# ---------------------------------------------------------------------------

def sample_sentinel2(points: list[list[float]], bbox: list[float]) -> pd.DataFrame:
    ee.Initialize(project=EE_PROJECT)
    aoi = ee.Geometry.Rectangle(bbox)

    end = (pd.Timestamp(BEST_SCENE_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    col = (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")      # L1C, TOA
        .filterBounds(aoi)
        .filterDate(BEST_SCENE_DATE, end)
        .filter(ee.Filter.eq("MGRS_TILE", MGRS_TILE))
    )
    if col.size().getInfo() == 0:
        raise RuntimeError(f"No L1C scene for {BEST_SCENE_DATE}, tile {MGRS_TILE}.")

    # linkCollection matches on system:index - the documented way to attach
    # Cloud Score+ to its parent scene.
    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    img = ee.Image(col.linkCollection(cs_plus, ["cs"]).first())
    print(f"  scene: {img.get('system:index').getInfo()}")

    stack = (img.select(VIS_BANDS + [NIR_BAND]).divide(10000)
             .addBands(img.select("cs")))

    rows = []
    n_batches = (len(points) + 499) // 500
    for k, batch in enumerate(chunked(points, 500), 1):
        fc = ee.FeatureCollection(
            [ee.Feature(ee.Geometry.Point(p), {"s_lon": p[0], "s_lat": p[1]})
             for p in batch]
        )
        sampled = stack.sampleRegions(collection=fc, scale=10, geometries=False)
        rows.extend(f["properties"] for f in sampled.getInfo()["features"])
        print(f"    batch {k}/{n_batches} done ({len(rows)} samples so far)")

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("Sentinel-2 sampling returned nothing.")
    return df


# ---------------------------------------------------------------------------
# 3. Hedley et al. (2005) deglint, fitted on half the deep points
# ---------------------------------------------------------------------------

def fit_glint(fit_set: pd.DataFrame) -> tuple[dict, float]:
    print(f"\n  glint regression sample: {len(fit_set)} held-in deep points")
    nir_min = fit_set[NIR_BAND].min()
    slopes = {}
    for band in VIS_BANDS:
        cov = fit_set[[band, NIR_BAND]].cov()
        slope = cov.loc[band, NIR_BAND] / cov.loc[NIR_BAND, NIR_BAND]
        r = fit_set[[band, NIR_BAND]].corr().loc[band, NIR_BAND]
        slopes[band] = slope
        print(f"    {band}: slope={slope:+.4f}  r={r:+.3f}  r2={r * r:.3f}")
        if r * r < 0.20:
            print(f"      NOTE: weak NIR correlation - little glint to remove "
                  f"in {band}. The correction barely changes this band, which "
                  f"is a result worth reporting, not a bug.")
    print(f"    min deep NIR = {nir_min:.5f}")
    return slopes, nir_min


def apply_deglint(df: pd.DataFrame, slopes: dict, nir_min: float) -> pd.DataFrame:
    out = df.copy()
    for band, slope in slopes.items():
        out[f"{band}_dg"] = out[band] - slope * (out[NIR_BAND] - nir_min)
    return out


# ---------------------------------------------------------------------------
# 4. The test
# ---------------------------------------------------------------------------

def depth_detrended_std(sub: pd.DataFrame, col: str) -> float:
    """Std of reflectance after removing a linear depth trend."""
    if len(sub) < 10:
        return float("nan")
    cov = sub[[col, "depth_inst_m"]].cov()
    denom = cov.loc["depth_inst_m", "depth_inst_m"]
    if denom == 0:
        return float("nan")
    slope = cov.loc[col, "depth_inst_m"] / denom
    intercept = sub[col].mean() - slope * sub["depth_inst_m"].mean()
    return (sub[col] - (slope * sub["depth_inst_m"] + intercept)).std()


def run_test(shallow: pd.DataFrame, deep: pd.DataFrame) -> None:
    print(f"\n  shallow (0-{SHALLOW_MAX:.0f} m) : {len(shallow)} points")
    print(f"  deep, held out (>{DEEP_MIN:.0f} m) : {len(deep)} points")

    if len(shallow) < 20 or len(deep) < 20:
        print("\n  >>> INCONCLUSIVE: a stratum is too thin. Raise --grid or move")
        print("  >>> the AOI. Do not read a decision out of this run.")
        return

    # Surface contamination guard
    s_nir, d_nir = shallow[NIR_BAND].mean(), deep[NIR_BAND].mean()
    print(f"\n  mean NIR  shallow={s_nir:.5f}  deep={d_nir:.5f}  "
          f"ratio={s_nir / d_nir if d_nir else float('nan'):.2f}")
    if d_nir and s_nir / d_nir > 1.5:
        print("  >>> WARNING: shallow water is much brighter in NIR. Breaking")
        print("  >>> waves or whitecaps are likely. Any excess visible-band")
        print("  >>> variance below may be surface, not bottom. Expected at an")
        print("  >>> exposed site such as mizen_outer.")

    print(f"\n  {'band':<7}{'shallow sd':>12}{'deep sd':>11}{'ratio':>8}"
          f"{'shallow sd, depth removed':>28}")
    ratios = []
    for band in VIS_BANDS:
        col = f"{band}_dg"
        s_sd, d_sd = shallow[col].std(), deep[col].std()
        ratio = s_sd / d_sd if d_sd > 0 else float("nan")
        ratios.append(ratio)
        print(f"  {band:<7}{s_sd:>12.5f}{d_sd:>11.5f}{ratio:>8.2f}"
              f"{depth_detrended_std(shallow, col):>28.5f}")

    valid = [r for r in ratios if r == r]
    if not valid:
        print("\n  >>> INCONCLUSIVE: deep-water variance is zero. Check inputs.")
        return
    best = max(valid)

    print("\n  " + "-" * 68)
    if best >= 2.0:
        print("  >>> BOTTOM SIGNAL PRESENT. Shallow water carries clearly more")
        print("  >>> structure than held-out deep water after glint removal.")
        print("  >>> DECISION: install ACOLITE, keep the optical path.")
    elif best >= 1.3:
        print("  >>> MARGINAL. Some excess shallow structure, not decisive.")
        print("  >>> Read the depth-removed column: if it collapses toward the")
        print("  >>> deep sd, the excess is bathymetric relief, not substrate.")
        print("  >>> DECISION: habitat-suitability model becomes the primary")
        print("  >>> path; optical detection ships as an experimental layer.")
    else:
        print("  >>> NO BOTTOM SIGNAL. Shallow water is statistically")
        print("  >>> indistinguishable from deep water after glint removal.")
        print("  >>> DECISION: optical detection is closed at this site with")
        print("  >>> Sentinel-2. Switch to the habitat-suitability model.")
        print("  >>> Valuation and biodiversity are unaffected: 5 of the 6 jury")
        print("  >>> criteria are untouched. This is a finding, not a failure,")
        print("  >>> and it should be presented as one.")
    print("  " + "-" * 68)


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", choices=sorted(AOIS), default=PRIMARY_AOI)
    ap.add_argument("--grid", type=int, default=50, help="grid side, default 50")
    args = ap.parse_args()

    if "PASTE" in EE_PROJECT:
        print("EE_PROJECT is still a placeholder in common.py. Put your Earth "
              "Engine Cloud project id there first.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bbox = AOIS[args.aoi]
    nx = ny = args.grid
    pts = grid_points(bbox, nx, ny)

    print(ATTRIBUTION["INFOMAR"])
    print(ATTRIBUTION["SENTINEL2"])
    print(f"\n{'=' * 70}\n{args.aoi}  ({len(pts)} grid points)\n{'=' * 70}")

    print("\n  sampling INFOMAR bathymetry...")
    bathy = sample_bathymetry(pts)
    print(f"  {len(bathy)} points with depth")

    print("\n  sampling Sentinel-2 L1C...")
    s2 = sample_sentinel2(pts, bbox)
    print(f"  {len(s2)} points with reflectance")

    bathy["_k"] = [grid_key(x, y, bbox, nx, ny)
                   for x, y in zip(bathy["b_lon"], bathy["b_lat"])]
    s2["_k"] = [grid_key(x, y, bbox, nx, ny)
                for x, y in zip(s2["s_lon"], s2["s_lat"])]

    df = bathy.merge(s2, on="_k", how="inner").drop_duplicates("_k")
    print(f"\n  joined: {len(df)} points with BOTH depth and reflectance")
    if len(df) < 0.5 * min(len(bathy), len(s2)):
        print("  >>> WARNING: join lost more than half of one source. Inspect")
        print("  >>> b_lon/b_lat against s_lon/s_lat in the CSV before trusting")
        print("  >>> the result.")

    clear = df[df["cs"] >= CS_THRESHOLD]
    print(f"  cloud-free (cs >= {CS_THRESHOLD}): {len(clear)}")

    # Split deep points: half fit the glint correction, half are held out.
    deep_pool = clear[clear["depth_inst_m"] >= GLINT_SAMPLE_MIN]
    if len(deep_pool) < 60:
        print(f"\n  Only {len(deep_pool)} points deeper than {GLINT_SAMPLE_MIN:.0f} m.")
        print("  Too few to split. Lower GLINT_SAMPLE_MIN or extend the AOI")
        print("  seaward, and record the change in the write-up.")
        return 1
    fit_set = deep_pool.sample(frac=0.5, random_state=RANDOM_SEED)

    slopes, nir_min = fit_glint(fit_set)
    corrected = apply_deglint(clear, slopes, nir_min)

    shallow = corrected[(corrected["depth_inst_m"] > 0)
                        & (corrected["depth_inst_m"] <= SHALLOW_MAX)]
    deep_heldout = corrected[
        (corrected["depth_inst_m"] >= DEEP_MIN)
        & (~corrected["_k"].isin(fit_set["_k"]))
    ]
    run_test(shallow, deep_heldout)

    csv_path = OUT_DIR / f"deglint_{args.aoi}.csv"
    corrected.drop(columns=["_k"]).to_csv(csv_path, index=False)
    print(f"\n  written: {csv_path}")
    print("\n  Caveat for the write-up: this tests for bottom-influenced signal,")
    print("  not for kelp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())