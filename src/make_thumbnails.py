"""
make_thumbnails.py -- Ocean Hackathon Cork 2026, "Seeing the Invisible Shield"
Step 2 of the kelp detection feasibility test: VISUAL SCREENING.

WHY THIS EXISTS
---------------
scene_selection.py ranks scenes on season, tide and cloud. It cannot judge the
three things that actually decide whether the seabed is visible: sun glint,
surface roughness (waves) and water turbidity. Wilson et al. (2020, Front.
Environ. Sci. 8:579856) screened for exactly these by eye before processing.
Cloud Score+ was trained mainly over land, so a clear fraction of 1.00 over
water is not evidence of a usable scene -- the first run of this script found
thin haze in scenes reported as 100% clear.

FIXES APPLIED AFTER EARLIER RUNS
--------------------------------
1. Land is masked to flat grey. Bright saturated land dominates the eye and
   hides the subtle in-water structure these previews exist to show.
   Implemented with where() rather than mosaic(): visualize() names its bands
   vis-red/vis-green/vis-blue while ee.Image.constant() names them
   constant/constant_1/constant_2, and mosaicking mismatched band names makes
   the thumbnail request fail with HTTP 400.
2. AOI water-fraction check runs before any download. An earlier inner-bay box
   was placed mostly over farmland and produced useless previews.
3. Tile-edge scenes are rejected. An AOI can straddle two MGRS tiles; the scene
   from the tile that barely overlaps renders as a mostly blank image.
4. A failed scene is skipped, not fatal. One bad request should not discard the
   whole run.

OUTPUT
------
outputs/thumbnails/<aoi>__<date>__<tile>.png
"""

from __future__ import annotations

import os
import sys

import ee
import pandas as pd
import requests

EE_PROJECT = "gen-lang-client-0871366385"   # same ID as in scene_selection.py

IN_CSV = "outputs/candidate_scenes.csv"
OUT_DIR = "outputs/thumbnails"
TOP_N = 4               # previews to KEEP per AOI, after rejections
IMG_WIDTH = 900         # pixels
MIN_WATER_FRAC = 0.35   # below this, the AOI box is badly placed
MIN_DATA_COVERAGE = 0.95  # below this, the scene clips the AOI at a tile edge

# NOTE: this dict must stay identical to AOIS in scene_selection.py. If you add
# or move a box here, rerun scene_selection.py first or its CSV will not contain
# the matching scenes.
AOIS = {
    # Primary: outer Roaringwater Bay, Baltimore / Sherkin approaches.
    # The 2021-05-28 preview showed the whole turbidity gradient in one frame
    # (tannic Ilen water, clear shallow water with visible bottom, deep water),
    # so this box is confirmed good and is left unchanged.
    "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
    # Exposed Atlantic comparison. Previews showed persistent surface roughness,
    # which is expected: the wave exposure that suits L. hyperborea is the same
    # exposure that degrades optical bottom detection. Kept, but demoted.
    "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
    # Turbid negative control, RELOCATED from the earlier farmland box.
    "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
}


# --------------------------------------------------------------------------
# Per-scene checks
# --------------------------------------------------------------------------
def water_fraction(img: ee.Image, geom: ee.Geometry) -> float:
    """Fraction of the AOI that is water, from NDWI = (green - NIR)/(green + NIR)."""
    ndwi = img.normalizedDifference(["B3", "B8"])
    return ndwi.gt(0).rename("w").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=20,
        maxPixels=1e9, bestEffort=True,
    ).get("w").getInfo()


def data_coverage(img: ee.Image, geom: ee.Geometry) -> float:
    """Fraction of the AOI with actual data. Near tile edges this drops sharply."""
    return img.select("B3").mask().rename("d").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=20,
        maxPixels=1e9, bestEffort=True,
    ).get("d").getInfo()


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def water_stretch(img: ee.Image, geom: ee.Geometry) -> dict:
    """2nd-98th percentile of B4/B3/B2 over water pixels only."""
    ndwi = img.normalizedDifference(["B3", "B8"])
    water = img.select(["B4", "B3", "B2"]).updateMask(ndwi.gt(0))
    pct = water.reduceRegion(
        reducer=ee.Reducer.percentile([2, 98]), geometry=geom, scale=20,
        maxPixels=1e9, bestEffort=True,
    ).getInfo()

    mins, maxs = [], []
    for band in ("B4", "B3", "B2"):
        lo, hi = pct.get(f"{band}_p2"), pct.get(f"{band}_p98")
        if lo is None or hi is None or hi <= lo:
            lo, hi = 200, 1400            # conservative water fallback
        mins.append(lo)
        maxs.append(hi)
    return {"bands": ["B4", "B3", "B2"], "min": mins, "max": maxs, "gamma": 1.1}


def render(img: ee.Image, vis: dict) -> ee.Image:
    """Water with the water stretch; land replaced by flat grey."""
    water_mask = img.normalizedDifference(["B3", "B8"]).gt(0)
    water_rgb = img.visualize(**vis)                     # uint8, 3 bands
    grey = ee.Image.constant([110, 110, 110]).toUint8().rename(water_rgb.bandNames())
    return water_rgb.where(water_mask.Not(), grey)


# --------------------------------------------------------------------------
def main() -> None:
    ee.Initialize(project=EE_PROJECT)
    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_csv(IN_CSV)

    # ---- AOI sanity check before downloading anything --------------------
    print("Checking AOI placement:", file=sys.stderr)
    usable = {}
    for aoi, bbox in AOIS.items():
        rows = df[df["aoi"] == aoi]
        if rows.empty:
            print(f"  {aoi}: no scenes in {IN_CSV} -- add this AOI to "
                  f"scene_selection.py and rerun it", file=sys.stderr)
            continue
        geom = ee.Geometry.Rectangle(bbox)
        ref = ee.Image(f"COPERNICUS/S2_HARMONIZED/{rows.iloc[0]['scene_id']}")
        frac = water_fraction(ref, geom)
        ok = frac >= MIN_WATER_FRAC
        print(f"  {aoi}: {frac:.0%} water  "
              f"[{'OK' if ok else 'TOO MUCH LAND -- move this box'}]", file=sys.stderr)
        if ok:
            usable[aoi] = (bbox, rows)

    if not usable:
        print("\nNo usable AOI. Fix the boxes and rerun.", file=sys.stderr)
        return

    # ---- Download previews -----------------------------------------------
    print("\nDownloading previews:", file=sys.stderr)
    saved = 0
    for aoi, (bbox, rows) in usable.items():
        geom = ee.Geometry.Rectangle(bbox)
        kept = 0
        for _, row in rows.iterrows():
            if kept >= TOP_N:
                break

            scene_id = row["scene_id"]
            date = str(row["datetime_utc"])[:10]
            tile = scene_id.split("_")[-1]
            name = f"{aoi}__{date}__{tile}.png"
            img = ee.Image(f"COPERNICUS/S2_HARMONIZED/{scene_id}")

            try:
                cov = data_coverage(img, geom)
                if cov < MIN_DATA_COVERAGE:
                    print(f"  SKIP {name}  only {cov:.0%} data coverage (tile edge)",
                          file=sys.stderr)
                    continue

                vis = water_stretch(img, geom)
                url = render(img, vis).getThumbURL(
                    {"region": geom, "dimensions": IMG_WIDTH, "format": "png"}
                )
                r = requests.get(url, timeout=300)
                r.raise_for_status()
                with open(os.path.join(OUT_DIR, name), "wb") as f:
                    f.write(r.content)

            except (ee.EEException, requests.RequestException) as exc:
                print(f"  FAIL {name}  {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

            kept += 1
            saved += 1
            print(f"  {name}  tide={row.get('wl_union_hall_harbor')} m  "
                  f"sun={row.get('sun_elev_deg'):.0f} deg  "
                  f"stretch={[int(v) for v in vis['max']]}", file=sys.stderr)

    print(f"\n{saved} previews written to {OUT_DIR}/")


if __name__ == "__main__":
    main()