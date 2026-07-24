"""
diagnose_mask.py -- Ocean Hackathon Cork 2026, "Seeing the Invisible Shield"
Step 4 of the feasibility test: is the water mask real, and is the visible
structure coming from the seabed or from the surface?

WHY
---
The band panels showed near-identical spatial structure in B8 (NIR) and B2
(blue). Water absorbs NIR within centimetres, so structure present in B8 cannot
originate at the seabed. Two explanations remain, needing different fixes:

  (a) It is real water and the structure is SURFACE roughness / sun glint.
      -> correctable; see Hedley et al. (2005) NIR-based deglinting.
  (b) The NDWI mask is calling bare rock or shadowed slopes "water",
      so we have been looking at land.
      -> fix the mask first; the scene shortlist stays valid.

NDWI = (green - NIR)/(green + NIR) separates water from VEGETATION reliably
because vegetation is bright in NIR. It is weaker against bare rock, dry soil
and terrain shadow, which are also dark in NIR. West Cork headlands are bare
rock, so (b) was a real possibility rather than a theoretical one.

THE TEST
--------
Top-of-atmosphere reflectance in B8 needs no interpretation:

    open water        ~0.01 - 0.05
    bare rock / soil  ~0.15 - 0.30
    vegetation        ~0.25 - 0.40

MNDWI (green vs SWIR B11) is computed as a cross-check: water absorbs SWIR even
more strongly than NIR, so disagreement between the two masks localises trouble.

Values are TOA (L1C) and include atmospheric path reflectance. That inflates
blue substantially but leaves NIR and SWIR over water low, which is why the
thresholds above still work before atmospheric correction.

FIXED AFTER THE FIRST RUN
-------------------------
The first version took the top-ranked CSV row per AOI without checking data
coverage. An AOI can straddle two MGRS tiles, and the scene from the barely
overlapping tile covers a sliver of the box. For sherkin_baltimore that sliver
was entirely sea, which produced a meaningless "100% water, no land pixels"
result. Scenes are now required to cover the AOI, and the scene actually used is
printed so this cannot happen silently again.

OUTPUT
------
A printed table, plus outputs/mask_diagnostics.csv
"""

from __future__ import annotations

import sys

import ee
import pandas as pd

EE_PROJECT = "gen-lang-client-0871366385"

IN_CSV = "outputs/candidate_scenes.csv"
OUT_CSV = "outputs/mask_diagnostics.csv"
SCALE = 20
MIN_DATA_COVERAGE = 0.95

AOIS = {
    "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
    "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
    "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
}

BANDS = ["B2", "B3", "B4", "B8", "B11"]


def data_coverage(img: ee.Image, geom: ee.Geometry) -> float:
    return img.select("B3").mask().rename("d").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=SCALE,
        maxPixels=1e9, bestEffort=True,
    ).get("d").getInfo()


def pick_scene(sel: pd.DataFrame, geom: ee.Geometry):
    """Highest-ranked scene that actually covers the AOI."""
    for _, row in sel.iterrows():
        img = ee.Image(f"COPERNICUS/S2_HARMONIZED/{row['scene_id']}")
        cov = data_coverage(img, geom)
        if cov >= MIN_DATA_COVERAGE:
            return row, img, cov
    return None, None, None


def stats_for(img: ee.Image, geom: ee.Geometry, mask: ee.Image, tag: str) -> dict:
    """Median and stdev of TOA reflectance for the masked pixels."""
    refl = img.select(BANDS).divide(10000).updateMask(mask)
    red = ee.Reducer.median().combine(ee.Reducer.stdDev(), sharedInputs=True)
    d = refl.reduceRegion(
        reducer=red, geometry=geom, scale=SCALE, maxPixels=1e9, bestEffort=True
    ).getInfo()
    return {f"{tag}_{k}": (round(v, 4) if isinstance(v, (int, float)) else v)
            for k, v in d.items()}


def main() -> None:
    ee.Initialize(project=EE_PROJECT)
    df = pd.read_csv(IN_CSV)
    rows = []

    for aoi, bbox in AOIS.items():
        sel = df[df["aoi"] == aoi]
        if sel.empty:
            print(f"{aoi}: no scenes in {IN_CSV} -- skipped", file=sys.stderr)
            continue

        geom = ee.Geometry.Rectangle(bbox)
        row, img, cov = pick_scene(sel, geom)
        if row is None:
            print(f"{aoi}: no scene covers >= {MIN_DATA_COVERAGE:.0%} of the AOI "
                  f"-- skipped", file=sys.stderr)
            continue

        ndwi = img.normalizedDifference(["B3", "B8"])          # what we used
        mndwi = img.normalizedDifference(["B3", "B11"])        # SWIR cross-check
        w_ndwi, w_mndwi = ndwi.gt(0), mndwi.gt(0)

        frac = ee.Image.cat(
            w_ndwi.rename("ndwi_w"),
            w_mndwi.rename("mndwi_w"),
            w_ndwi.And(w_mndwi.Not()).rename("ndwi_only"),
        ).reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geom, scale=SCALE,
            maxPixels=1e9, bestEffort=True,
        ).getInfo()

        rec = {
            "aoi": aoi,
            "date": str(row["datetime_utc"])[:10],
            "scene_id": row["scene_id"],
            "data_coverage": round(cov, 3),
            "ndwi_water_frac": round(frac["ndwi_w"], 3),
            "mndwi_water_frac": round(frac["mndwi_w"], 3),
            "ndwi_only_frac": round(frac["ndwi_only"], 3),   # suspected bad pixels
        }
        rec.update(stats_for(img, geom, w_ndwi, "water"))
        rec.update(stats_for(img, geom, w_ndwi.Not(), "land"))
        rows.append(rec)

        b8, b11 = rec.get("water_B8_median"), rec.get("water_B11_median")
        sd2, sd8 = rec.get("water_B2_stdDev"), rec.get("water_B8_stdDev")
        land_b8 = rec.get("land_B8_median")

        if b8 is None:
            verdict = "no data"
        elif b8 > 0.10:
            verdict = "MASK BROKEN -- these are land pixels"
        elif b8 > 0.06:
            verdict = "SUSPECT -- land contamination or heavy glint"
        elif b8 > 0.025:
            verdict = "water, but bright NIR -> surface roughness / glint"
        else:
            verdict = "clean water surface"

        print(f"\n=== {aoi}  {rec['date']}  [{rec['scene_id'][-6:]}] ===")
        print(f"  AOI data coverage {cov:.0%}")
        if land_b8 is None:
            print("  WARNING: no land pixels found -- check the AOI box")
        elif land_b8 < 0.15:
            print(f"  WARNING: land B8 {land_b8} is low for vegetation/rock; "
                  f"the land sample may be edge pixels only")
        print(f"  water fraction   NDWI {rec['ndwi_water_frac']:.0%}   "
              f"MNDWI {rec['mndwi_water_frac']:.0%}   "
              f"NDWI-only (suspect) {rec['ndwi_only_frac']:.0%}")
        print(f"  median TOA over water:  B2 {rec.get('water_B2_median')}  "
              f"B3 {rec.get('water_B3_median')}  B4 {rec.get('water_B4_median')}  "
              f"B8 {b8}  B11 {b11}")
        print(f"  median TOA over land :  B8 {land_b8}")
        print(f"  stdev over water:  B2 {sd2}  B8 {sd8}"
              + ("   <- NIR varies MORE than blue: structure is surface-driven"
                 if (sd2 and sd8 and sd8 >= sd2) else ""))
        print(f"  --> {verdict}")

    if rows:
        pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
        print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()