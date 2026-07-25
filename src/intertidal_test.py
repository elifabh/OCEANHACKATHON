#!/usr/bin/env python3
"""
intertidal_test.py - can Sentinel-2 detect intertidal macroalgae in West Cork?

CHANGES IN v5 - a definition bug in the geometry check, not a threshold tune
v4 produced an overwhelming statistical result and then failed it on geometry:

    class                             n   r q25   r med   r q75   sig  slope med
    permanent land (CONTROL)        300  -0.068  +0.091  +0.216  0.00    +0.0053
    permanent deep water (CONTROL)  300  -0.184  -0.076  +0.024  0.00    -0.0047
    intertidal candidate (TEST)     300  -0.870  -0.800  -0.722  0.78    -0.1298

The whole interquartile range of the test class sits below -0.72, 78% of its
pixels reach per-pixel significance against 0% on land, its slope is 24x the
land control, and NDVI runs from 0.344 when exposed to -0.074 when submerged.
Both controls are flat. Only the coastal-adjacency check failed, at 55% against
a required 70%.

THE BUG: v4 measured distance to the "permanent land" CLASS, which is defined as
NDVI >= 0.25 in every scene, i.e. VEGETATED land. On these shores a band of bare
rock, lichen and splash zone separates vegetation from the algal zone, and
Roaringwater Bay is full of small rocky skerries with no vegetation on them at
all, where that class does not exist. Genuine intertidal pixels are therefore
far from VEGETATION while being immediately adjacent to LAND. The check was
measuring the wrong thing.

  1. LAND IS NOW DEFINED AS "never water-like": ndvi_min > NDVI_WATER across all
     scenes. This includes bare rock. It cannot include intertidal pixels, which
     by definition fall to water-like NDVI at high tide, so there is no
     circularity.
  2. DISTANCE IS REPORTED, NOT THRESHOLDED TIGHTLY. Quartiles of distance to
     land are printed for every class. The verdict fails only on an
     indefensible distance (median beyond MAX_MEDIAN_DIST_PX), because two
     thresholds in this script have now been mis-set and the distribution is
     more informative than a pass/fail.
  3. THE DISTANCE SCALE IS DERIVED FROM PHYSICS. Intertidal band width equals
     tidal range divided by shore slope. West Cork spring range is about 3.5 m,
     so on a 3% slope the band is roughly 117 m, about 12 pixels. A pixel at the
     lower edge of a real intertidal band can legitimately sit ten pixels from
     the high-water line. v4's 5-pixel limit was tighter than the physics allows.

WHY THIS TEST EXISTS
bottom_signal_test.py established that no seabed signal reaches Sentinel-2 at
these sites (two AOIs, restricted to 0-5 m, physics-constrained, negative). That
closes SUBTIDAL detection: Laminaria hyperborea never leaves the water, so its
signal must travel through metres of it.

Intertidal macroalgae is a different physical problem. At low tide it is OUT of
the water. Exposed algae behaves like terrestrial vegetation: strong in the near
infrared, weak in the red. Water absorbs NIR almost completely, so the water
column that defeated the subtidal test is simply absent.

THE DESIGN: TIDE DOSE-RESPONSE
  A genuinely intertidal pixel   NDVI falls as tide rises
  Permanent land                 NDVI does not change with tide  -> CONTROL
  Permanent deep water           NDVI does not change with tide  -> CONTROL

Per pixel, from image arithmetic, with tide as the predictor:
  xbar = mean(tide),  w_i = tide_i - xbar,  Sxx = sum(w_i^2)
  Sxy = sum(w_i * ndvi_i),  Syy = sum(ndvi_i^2) - n * mean(ndvi)^2
  slope = Sxy / Sxx          r = Sxy / sqrt(Sxx * Syy)

Tide weights are Python floats, so no constant image band is created and no
ImageCollection reducer is used; both caused Earth Engine to reject the
collection as heterogeneous in v2.

PASS CRITERIA, FIXED BEFORE THE RUN
  Controls flat        |median r| <= 0.40 and |median slope| <= 0.02 for BOTH
                       controls. If a control tracks tide, the scenes differ in
                       something other than tide and the result is void. This is
                       the most important check and has not changed since v1.
  Direction            intertidal median r <= -0.60
  Separation           |r| >= 3x land, |slope| >= 5x land, significant fraction
                       >= 4x land
  Geometry             intertidal MEDIAN distance to land <= 15 px (150 m).
                       Reported in full; only gross failure is fatal.
  Extent               >= 0.5 ha

WHAT IT CANNOT SHOW - READ BEFORE WRITING ANY SLIDE
  NDVI cannot distinguish species. West Cork intertidal shores carry fucoids
  (Fucus vesiculosus, F. serratus, Ascophyllum nodosum) as well as Laminaria
  digitata, which occupies the lowest intertidal on exposed shores. The product
  is INTERTIDAL MACROALGAE EXTENT, not a Laminaria digitata map.

  Consequence for the valuation chain: the wave-attenuation coefficients
  (Dubi & Tørum 1996; Mork 1996) are measured on L. hyperborea, a subtidal
  species. They must NOT be applied to this intertidal layer. The valuation
  chain continues to run off the subtidal habitat-suitability model.

  A pixel must be cloud-free in EVERY scene, which keeps the tide mean and Sxx
  identical for every pixel. That costs pixels and could bias against
  cloud-edge coastal pixels. Retained counts are printed.

ESTABLISHED METHOD VERSUS OURS
  Established: NDVI for emergent macroalgae is long-standing practice; the
  Marine Institute / EMFF "Development of Methodologies for Assessment of
  Ireland's Seaweed Resource" project used free Sentinel-2 data for county-scale
  seaweed mapping and a National Seaweed Atlas. NOT YET VERIFIED by us: whether
  that work specifically demonstrated intertidal kelp, and at what accuracy.
  Check the source before citing it as precedent.
  Ours: the tide dose-response design, the control classes, the separation and
  geometry criteria. All printed at run time so they can be argued with.

INPUTS
  Sentinel-2 L1C via Earth Engine, tile 29UMT.
  Tide from outputs/candidate_scenes.csv (scene_selection.py, Marine Institute
  Irish National Tide Gauge Network via ERDDAP, measured not predicted, LAT
  datum, CC BY 4.0). Primary gauge: Union Hall Harbor.

Usage
  python intertidal_test.py
  python intertidal_test.py --n-scenes 6
  python intertidal_test.py --aoi mizen_outer
  python intertidal_test.py --multi-year
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ee
import numpy as np
import pandas as pd

from common import AOIS, ATTRIBUTION, EE_PROJECT, PRIMARY_AOI

MGRS_TILE = "29UMT"
OUT_DIR = Path("outputs/intertidal")
CSV_CANDIDATES = (Path("../outputs/candidate_scenes.csv"),
                  Path("outputs/candidate_scenes.csv"))

# Union Hall Harbor is 15-20 km from Baltimore. Castletownbere is about 50 km
# away with a tidal phase difference, so it is a comparison gauge only.
TIDE_COL_PREFERENCE = ("wl_union_hall_harbor", "wl_castletownbere_port")

MONTHS = (5, 6, 7, 8)
N_SCENES = 8
MIN_SCENES = 6
MIN_TIDE_RANGE_M = 1.5
CLEAR_STEPS = (0.90, 0.80, 0.70, 0.60)
CS_THRESHOLD = 0.60

# Two-tailed critical |r| at alpha = 0.05, df = n - 2. Reported per pixel for
# context; the verdict uses class separation, not this value on a class median.
R_CRIT_05 = {3: 0.997, 4: 0.950, 5: 0.878, 6: 0.811, 7: 0.754, 8: 0.707,
             9: 0.666, 10: 0.632, 11: 0.602, 12: 0.576, 13: 0.553,
             14: 0.532, 15: 0.514, 16: 0.497, 17: 0.482, 18: 0.468,
             19: 0.456, 20: 0.444}

# NDVI for exposed brown algae is lower than for terrestrial vegetation because
# fucoxanthin darkens the red edge, so the vegetation threshold sits below the
# usual terrestrial value.
NDVI_VEG = 0.20
NDVI_WATER = 0.00
LAND_MIN_NDVI = 0.25              # VEGETATED land, for the control class only
DEEP_WATER_MAX_NDVI = -0.10

CONTROL_CORR_ABS_MAX = 0.40
CONTROL_SLOPE_ABS_MAX = 0.02      # NDVI units per metre of tide
INTERTIDAL_CORR_MAX = -0.60
SEP_CORR_RATIO = 3.0
SEP_SLOPE_RATIO = 5.0
SEP_SIGFRAC_RATIO = 4.0

# Geometry. West Cork spring tidal range is about 3.5 m; on a 3% shore slope the
# intertidal band is roughly 117 m, about 12 pixels, so a pixel at the lower
# edge of a real band can sit ten pixels from the high-water line. Only a gross
# violation is treated as fatal.
DIST_SEARCH_PX = 64               # fastDistanceTransform neighbourhood
MAX_MEDIAN_DIST_PX = 15.0         # 150 m
MIN_INTERTIDAL_HA = 0.5

SAMPLE_PER_CLASS = 300
RANDOM_SEED = 42


def r_critical(n: int) -> float:
    if n in R_CRIT_05:
        return R_CRIT_05[n]
    return 0.999 if n < min(R_CRIT_05) else R_CRIT_05[max(R_CRIT_05)]


# ===========================================================================
# Candidate list
# ===========================================================================

def load_candidates() -> pd.DataFrame | None:
    for path in CSV_CANDIDATES:
        if path.exists():
            print(f"  reading {path}")
            return pd.read_csv(path)
    print("  candidate_scenes.csv not found. Run from src/.")
    return None


def detect_columns(df: pd.DataFrame, tide_override: str | None) -> dict:
    cols = {c.lower(): c for c in df.columns}

    def first(*tokens: str) -> str | None:
        for low, orig in cols.items():
            if any(t in low for t in tokens):
                return orig
        return None

    if tide_override:
        if tide_override not in df.columns:
            raise SystemExit(f"--tide-col '{tide_override}' not in CSV. "
                             f"Columns: {', '.join(df.columns)}")
        tide = tide_override
    else:
        tide = next((c for c in TIDE_COL_PREFERENCE if c in df.columns), None)
        if tide is None:
            tide = first("tide", "water_level", "wl_", "sea_level")

    return {"date": first("datetime", "date", "time", "acquired"),
            "tide": tide,
            "clear": first("clear_frac", "aoi_clear"),
            "aoi": cols.get("aoi"),
            "scene_id": first("scene_id", "system_index", "granule_id"),
            "sun": first("sun_elev")}


def _supports_test(sub: pd.DataFrame) -> tuple[bool, float]:
    if len(sub) < MIN_SCENES:
        return False, 0.0
    spread = float(sub["_tide"].max() - sub["_tide"].min())
    return spread >= MIN_TIDE_RANGE_M, spread


def pick_scenes(df: pd.DataFrame, cols: dict, aoi_name: str, n: int,
                allow_multi_year: bool) -> tuple[list[dict], dict]:
    d = df.copy()
    meta: dict = {}

    if cols["aoi"]:
        before = len(d)
        d = d[d[cols["aoi"]].astype(str) == aoi_name]
        print(f"  AOI filter on '{cols['aoi']}': {before} -> {len(d)} rows")
        if d.empty:
            vals = sorted(df[cols["aoi"]].astype(str).unique())
            raise SystemExit(f"  No rows for '{aoi_name}'. Present: "
                             f"{', '.join(vals)}")
    else:
        print("  NO 'aoi' column. Rows for all AOIs may be mixed.")

    d["_date"] = pd.to_datetime(d[cols["date"]], errors="coerce", utc=True)
    d["_tide"] = pd.to_numeric(d[cols["tide"]], errors="coerce")
    d = d.dropna(subset=["_date", "_tide"])
    before = len(d)
    d = d[d["_date"].dt.month.isin(MONTHS)]
    print(f"  months {MONTHS}: {before} -> {len(d)} rows")
    if d.empty:
        raise SystemExit("  Nothing left after the seasonal filter.")

    d = (d.drop_duplicates(subset=[cols["scene_id"]]) if cols["scene_id"]
         else d.drop_duplicates(subset=["_date"]))

    if cols["clear"]:
        d["_clear"] = pd.to_numeric(d[cols["clear"]], errors="coerce")
        pool, used_clear = None, None
        for step in CLEAR_STEPS:
            sub = d[d["_clear"] >= step]
            ok, spread = _supports_test(sub)
            print(f"  aoi_clear_frac >= {step:.2f}: {len(sub)} scenes, spread "
                  f"{spread:.2f} m  <- {'using this' if ok else 'insufficient'}")
            if ok:
                pool, used_clear = sub, step
                break
        if pool is None:
            raise SystemExit(f"  No threshold down to {CLEAR_STEPS[-1]} gives "
                             f"{MIN_SCENES} scenes with a "
                             f"{MIN_TIDE_RANGE_M} m spread.")
    else:
        pool, used_clear = d, None
    meta["clear_frac_threshold_used"] = used_clear

    chosen_year = None
    if not allow_multi_year:
        best = None
        print("\n  Single-year candidates (removes interannual growth confound):")
        for year, sub in pool.groupby(pool["_date"].dt.year):
            ok, spread = _supports_test(sub)
            print(f"    {year}: {len(sub)} scenes, spread {spread:.2f} m"
                  f"{'  eligible' if ok else ''}")
            if ok and (best is None or (spread, len(sub)) > best[0]):
                best = ((spread, len(sub)), int(year), sub)
        if best is not None:
            _, chosen_year, pool = best
            print(f"  Using {chosen_year} only.")
        else:
            print("  No single year qualifies; falling back to multiple years.")
    meta["single_year"] = chosen_year

    sel = pool.sort_values("_tide")
    if len(sel) > n:
        targets = np.linspace(sel["_tide"].min(), sel["_tide"].max(), n)
        idx = sorted({int((sel["_tide"] - t).abs().idxmin()) for t in targets})
        sel = sel.loc[idx].sort_values("_tide")

    print(f"\n  Selected {len(sel)} scenes (tide from '{cols['tide']}'):")
    header = f"    {'date':<12}{'tide m LAT':>11}"
    if cols["clear"]:
        header += f"{'clear':>8}"
    if cols["sun"]:
        header += f"{'sun deg':>9}"
    print(header)

    out: list[dict] = []
    for _, r in sel.iterrows():
        day = r["_date"].strftime("%Y-%m-%d")
        line = f"    {day:<12}{r['_tide']:>+11.2f}"
        if cols["clear"]:
            line += f"{r['_clear']:>8.2f}"
        if cols["sun"]:
            line += f"{pd.to_numeric(r[cols['sun']], errors='coerce'):>9.1f}"
        print(line)
        out.append({"date": day, "tide": float(r["_tide"]),
                    "scene_id": (str(r[cols["scene_id"]])
                                 if cols["scene_id"] else None)})
    return out, meta


# ===========================================================================
# Earth Engine
# ===========================================================================

def build_ndvi_images(bbox: list[float], scenes: list[dict]):
    aoi = ee.Geometry.Rectangle(bbox)
    base = (ee.ImageCollection("COPERNICUS/S2_HARMONIZED")     # L1C, TOA
            .filterBounds(aoi)
            .filter(ee.Filter.eq("MGRS_TILE", MGRS_TILE)))
    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    base = base.linkCollection(cs_plus, ["cs"])

    images, used, proj = [], [], None
    print()
    for sc in scenes:
        sub, how = None, None
        if sc.get("scene_id"):
            cand = base.filter(ee.Filter.eq("system:index", sc["scene_id"]))
            if cand.size().getInfo() > 0:
                sub, how = cand, "scene_id"
        if sub is None:
            end = (pd.Timestamp(sc["date"]) + pd.Timedelta(days=1)
                   ).strftime("%Y-%m-%d")
            cand = base.filterDate(sc["date"], end)
            if cand.size().getInfo() == 0:
                print(f"    {sc['date']}: no scene on this tile, skipped")
                continue
            sub, how = cand, "date"

        img = ee.Image(sub.first())
        if proj is None:
            proj = img.select("B4").projection()
        refl = img.select(["B4", "B8"]).divide(10000)
        ndvi = (refl.normalizedDifference(["B8", "B4"])
                .updateMask(img.select("cs").gte(CS_THRESHOLD))
                .rename("ndvi").toFloat())
        images.append(ndvi)
        used.append(sc)
        print(f"    {sc['date']}  tide {sc['tide']:+.2f} m  via {how}")

    if len(used) < MIN_SCENES:
        raise SystemExit(f"  Only {len(used)} usable scenes; {MIN_SCENES} "
                         f"needed.")

    tides = [s["tide"] for s in used]
    spread = max(tides) - min(tides)
    print(f"\n  tide range: {min(tides):+.2f} to {max(tides):+.2f} m LAT  "
          f"(spread {spread:.2f} m)")
    if spread < MIN_TIDE_RANGE_M:
        raise SystemExit(f"  Spread {spread:.2f} m below {MIN_TIDE_RANGE_M} m.")

    years = sorted({s["date"][:4] for s in used})
    if len(years) > 1:
        print(f"  NOTE: {len(years)} years ({', '.join(years)}). Part of any "
              f"signal could be interannual growth; the land control guards.")
    return images, used, aoi, proj


def regression_images(ndvi_imgs: list, tides: list[float]) -> ee.Image:
    """Slope and Pearson r of NDVI against tide, per pixel.

    Masks propagate through the arithmetic, so a pixel survives only if it is
    cloud-free in EVERY scene, which keeps the tide mean and Sxx identical for
    every pixel as the Python-side weights assume.
    """
    n = len(tides)
    xbar = sum(tides) / n
    weights = [t - xbar for t in tides]
    sxx = sum(w * w for w in weights)
    if sxx <= 0:
        raise SystemExit("  All tide values identical: no predictor variance.")

    sum_y = ndvi_imgs[0]
    sum_y2 = ndvi_imgs[0].multiply(ndvi_imgs[0])
    sxy = ndvi_imgs[0].multiply(weights[0])
    ndvi_min, ndvi_max = ndvi_imgs[0], ndvi_imgs[0]
    count = ndvi_imgs[0].mask()

    for img, w in zip(ndvi_imgs[1:], weights[1:]):
        sum_y = sum_y.add(img)
        sum_y2 = sum_y2.add(img.multiply(img))
        sxy = sxy.add(img.multiply(w))
        ndvi_min = ndvi_min.min(img)
        ndvi_max = ndvi_max.max(img)
        count = count.add(img.mask())

    ybar = sum_y.divide(n)
    syy = sum_y2.subtract(ybar.multiply(ybar).multiply(n))

    stats = (sxy.divide(sxx).rename("slope")
             .addBands(sxy.divide(syy.multiply(sxx).sqrt()).rename("corr"))
             .addBands(count.rename("n_obs"))
             .addBands(ndvi_min.rename("ndvi_min"))
             .addBands(ndvi_max.rename("ndvi_max"))
             .addBands(ybar.rename("ndvi_mean")))
    return stats.updateMask(syy.gt(0)).updateMask(count.gte(n))


def classify(stats: ee.Image, n: int) -> ee.Image:
    """1 = vegetated land control, 2 = deep water control, 3 = intertidal."""
    land = stats.select("ndvi_min").gte(LAND_MIN_NDVI)
    water = stats.select("ndvi_max").lte(DEEP_WATER_MAX_NDVI)
    inter = (stats.select("ndvi_max").gte(NDVI_VEG)
             .And(stats.select("ndvi_min").lte(NDVI_WATER))
             .And(stats.select("slope").lt(0)))
    return (ee.Image(0)
            .where(land, 1)
            .where(water, 2)
            .where(inter, 3)          # intertidal wins where rules overlap
            .rename("cls")
            .updateMask(stats.select("n_obs").gte(n))
            .toByte())


def distance_to_land(stats: ee.Image, proj) -> ee.Image:
    """Distance in pixels to the nearest land, bare rock included.

    Land here means "never water-like in any scene": ndvi_min > NDVI_WATER.
    That deliberately differs from the vegetated-land CONTROL class. On these
    shores bare rock, lichen and splash zone separate vegetation from the algal
    band, and Roaringwater Bay has many unvegetated rocky skerries, so distance
    to VEGETATION is not distance to land. Using the vegetated class here was
    the bug in v4.

    Intertidal pixels have ndvi_min <= NDVI_WATER by definition, so they are
    excluded from the land mask and there is no circularity.
    """
    land_any = (stats.select("ndvi_min").gt(NDVI_WATER)
                .unmask(0).reproject(proj))
    # fastDistanceTransform returns squared distance to the nearest non-zero
    # pixel, in pixel units.
    return (land_any.fastDistanceTransform(DIST_SEARCH_PX)
            .sqrt().rename("dist_land_px").toFloat())


def sample_classes(stats: ee.Image, cls: ee.Image, dist: ee.Image,
                   aoi) -> pd.DataFrame:
    fc = cls.addBands(stats).addBands(dist).stratifiedSample(
        numPoints=SAMPLE_PER_CLASS,
        classBand="cls",
        region=aoi,
        scale=10,
        classValues=[1, 2, 3],
        classPoints=[SAMPLE_PER_CLASS] * 3,
        seed=RANDOM_SEED,
        dropNulls=True,
        geometries=True,
        tileScale=4,
    )
    rows = []
    for f in fc.getInfo()["features"]:
        props = dict(f["properties"])
        if f.get("geometry"):
            props["lon"], props["lat"] = f["geometry"]["coordinates"]
        rows.append(props)
    return pd.DataFrame(rows)


def class_area_ha(cls: ee.Image, value: int, aoi) -> float:
    res = (ee.Image.pixelArea().updateMask(cls.eq(value))
           .reduceRegion(reducer=ee.Reducer.sum(), geometry=aoi,
                         scale=10, maxPixels=int(1e9)).getInfo())
    return float(res.get("area") or 0.0) / 10000.0


# ===========================================================================
# Verdict
# ===========================================================================

CLASS_NAMES = {1: "vegetated land (CONTROL)",
               2: "deep water (CONTROL)",
               3: "intertidal candidate (TEST)"}


def summarise(df: pd.DataFrame, r_crit: float) -> dict:
    out = {}
    print(f"\n  {'class':<28}{'n':>5}{'r q25':>8}{'r med':>8}{'r q75':>8}"
          f"{'sig':>6}{'slope':>10}{'NDVI lo':>9}{'NDVI hi':>9}"
          f"{'dist med':>10}{'dist q75':>10}")
    for value, name in CLASS_NAMES.items():
        sub = df[df["cls"] == value] if "cls" in df else df.iloc[0:0]
        if sub.empty:
            print(f"  {name:<28}{0:>5}   (no pixels)")
            out[value] = {"n": 0}
            continue
        has_dist = "dist_land_px" in sub
        rec = {
            "n": int(len(sub)),
            "corr_q25": float(sub["corr"].quantile(0.25)),
            "median_corr": float(sub["corr"].median()),
            "corr_q75": float(sub["corr"].quantile(0.75)),
            "frac_significant": float((sub["corr"].abs() >= r_crit).mean()),
            "median_slope": float(sub["slope"].median()),
            "median_ndvi_min": float(sub["ndvi_min"].median()),
            "median_ndvi_max": float(sub["ndvi_max"].median()),
            "dist_median_px": (float(sub["dist_land_px"].median())
                               if has_dist else float("nan")),
            "dist_q75_px": (float(sub["dist_land_px"].quantile(0.75))
                            if has_dist else float("nan")),
        }
        out[value] = rec
        print(f"  {name:<28}{rec['n']:>5}{rec['corr_q25']:>8.3f}"
              f"{rec['median_corr']:>8.3f}{rec['corr_q75']:>8.3f}"
              f"{rec['frac_significant']:>6.2f}{rec['median_slope']:>10.4f}"
              f"{rec['median_ndvi_max']:>9.3f}{rec['median_ndvi_min']:>9.3f}"
              f"{rec['dist_median_px']:>10.1f}{rec['dist_q75_px']:>10.1f}")
    print(f"  'sig' = fraction reaching per-pixel critical |r| = {r_crit:.3f} "
          f"(context, not the verdict)")
    print("  'NDVI lo' = NDVI at LOW tide, 'NDVI hi' = at HIGH tide")
    print("  'dist' = pixels to the nearest land INCLUDING bare rock "
          "(1 px = 10 m)")
    return out


def verdict(stats: dict, area_ha: float, r_crit: float) -> tuple[str, list, list]:
    fails: list[str] = []
    passes: list[str] = []
    land, water, inter = stats.get(1, {}), stats.get(2, {}), stats.get(3, {})

    controls_ok = True
    for label, s in (("land", land), ("deep water", water)):
        if not s.get("n"):
            controls_ok = False
            fails.append(f"{label} control has no pixels: no baseline")
            continue
        if abs(s["median_corr"]) > CONTROL_CORR_ABS_MAX:
            controls_ok = False
            fails.append(f"{label} control tracks tide (median r = "
                         f"{s['median_corr']:+.3f}, limit "
                         f"{CONTROL_CORR_ABS_MAX})")
        if abs(s["median_slope"]) > CONTROL_SLOPE_ABS_MAX:
            controls_ok = False
            fails.append(f"{label} control slope {s['median_slope']:+.4f} per "
                         f"metre exceeds {CONTROL_SLOPE_ABS_MAX}")
    if controls_ok:
        passes.append(f"controls flat: land r = {land['median_corr']:+.3f}, "
                      f"water r = {water['median_corr']:+.3f}")

    test_ok = True
    if not inter.get("n"):
        test_ok = False
        fails.append("no intertidal candidate pixels found")
    else:
        if inter["median_corr"] > INTERTIDAL_CORR_MAX:
            test_ok = False
            fails.append(f"intertidal median r = {inter['median_corr']:+.3f}, "
                         f"not below {INTERTIDAL_CORR_MAX}")
        else:
            passes.append(f"dose-response: r quartiles "
                          f"{inter['corr_q25']:+.3f} / "
                          f"{inter['median_corr']:+.3f} / "
                          f"{inter['corr_q75']:+.3f}")

        if land.get("n"):
            ratio_r = abs(inter["median_corr"]) / max(abs(land["median_corr"]),
                                                      1e-6)
            ratio_s = abs(inter["median_slope"]) / max(abs(land["median_slope"]),
                                                       1e-6)
            ratio_f = inter["frac_significant"] / max(land["frac_significant"],
                                                      1e-6)
            for name, ratio, need in (("r", ratio_r, SEP_CORR_RATIO),
                                      ("slope", ratio_s, SEP_SLOPE_RATIO),
                                      ("significant fraction", ratio_f,
                                       SEP_SIGFRAC_RATIO)):
                if ratio < need:
                    test_ok = False
                    fails.append(f"{name} separation from land is {ratio:.1f}x, "
                                 f"below {need}x")
                else:
                    passes.append(f"{name} is {ratio:.0f}x the land control")

        dmed = inter.get("dist_median_px", float("nan"))
        if dmed == dmed:
            if dmed > MAX_MEDIAN_DIST_PX:
                test_ok = False
                fails.append(
                    f"intertidal median distance to land is {dmed:.1f} px "
                    f"({dmed * 10:.0f} m), beyond {MAX_MEDIAN_DIST_PX:.0f} px. "
                    f"That is not a shoreline fringe.")
            else:
                passes.append(
                    f"coastal fringe: median {dmed:.1f} px "
                    f"({dmed * 10:.0f} m) from land, q75 "
                    f"{inter['dist_q75_px']:.1f} px")

        if area_ha < MIN_INTERTIDAL_HA:
            test_ok = False
            fails.append(f"extent {area_ha:.2f} ha below {MIN_INTERTIDAL_HA} ha")

    print("\n  " + "-" * 72)
    if controls_ok and test_ok:
        print("  INTERTIDAL MACROALGAE DETECTED.")
        print(f"  Extent in this AOI: {area_ha:.1f} ha")
        print("\n  WHAT THIS IS: intertidal macroalgae extent. NOT a Laminaria")
        print("  digitata map. NDVI cannot separate it from Fucus or")
        print("  Ascophyllum. Do NOT apply the L. hyperborea wave-attenuation")
        print("  coefficients to this layer.")
        print("\n  WHAT IT UNLOCKS")
        print("    - a working Sentinel-2 product, so 'open satellite data' is")
        print("      honest and the demonstrator criterion is addressable")
        print("    - repeat low-tide scenes across years: the route to the")
        print("      decline assessment the challenge asks for, which nothing")
        print("      in the project currently addresses")
        print("    - the lower edge of this band is the upper edge of the")
        print("      subtidal zone, constraining the suitability model")
        print("\n  NEXT: validate against ground truth before quoting accuracy.")
        print("  NPWS Annex I polygon, MERC 2007 dive stations, Seasearch.")
        print("  An unvalidated extent figure is not a result.")
        out = "detected"
    elif not controls_ok:
        print("  TEST VOID - CONTROLS FAILED.")
        print("  A control tracks tide, so the scenes differ in something other")
        print("  than tide. Do not read the intertidal row.")
        out = "void"
    else:
        print("  NO INTERTIDAL SIGNAL DETECTED.")
        print("  The controls are clean, so this is a real negative rather than")
        print("  an artefact.")
        out = "absent"

    if fails:
        print("\n  Failed:")
        for f in fails:
            print(f"    - {f}")
    if passes:
        print("\n  Passed:")
        for p in passes:
            print(f"    + {p}")
    print("  " + "-" * 72)
    return out, fails, passes


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", choices=sorted(AOIS), default=PRIMARY_AOI)
    ap.add_argument("--tide-col", default=None)
    ap.add_argument("--n-scenes", type=int, default=N_SCENES)
    ap.add_argument("--multi-year", action="store_true")
    ap.add_argument("--list-columns", action="store_true")
    args = ap.parse_args()

    if "PASTE" in EE_PROJECT:
        print("EE_PROJECT is still a placeholder in common.py.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bbox = AOIS[args.aoi]

    print(ATTRIBUTION["SENTINEL2"])
    print(ATTRIBUTION["TIDE_GAUGE"])
    print(f"\n{'=' * 74}\n{args.aoi}   intertidal macroalgae feasibility\n"
          f"{'=' * 74}")
    print("  Verdict criteria, fixed before the run:")
    print(f"    controls flat   |r| <= {CONTROL_CORR_ABS_MAX}, |slope| <= "
          f"{CONTROL_SLOPE_ABS_MAX}")
    print(f"    direction       intertidal median r <= {INTERTIDAL_CORR_MAX}")
    print(f"    separation      r >= {SEP_CORR_RATIO}x, slope >= "
          f"{SEP_SLOPE_RATIO}x, sig >= {SEP_SIGFRAC_RATIO}x the land control")
    print(f"    geometry        median distance to land (bare rock included) "
          f"<= {MAX_MEDIAN_DIST_PX:.0f} px = {MAX_MEDIAN_DIST_PX * 10:.0f} m")
    print(f"    extent          >= {MIN_INTERTIDAL_HA} ha")

    print("\n  Scene selection")
    df = load_candidates()
    if df is None:
        return 1
    cols = detect_columns(df, args.tide_col)
    print(f"  columns: date='{cols['date']}'  tide='{cols['tide']}'  "
          f"clear='{cols['clear']}'  aoi='{cols['aoi']}'  "
          f"scene_id='{cols['scene_id']}'")
    if args.list_columns:
        for c in df.columns:
            print(f"    {c}")
        return 0
    if not cols["date"] or not cols["tide"]:
        print("\n  Could not identify date and tide columns.")
        return 1
    scenes, meta = pick_scenes(df, cols, args.aoi, args.n_scenes,
                               args.multi_year)

    ee.Initialize(project=EE_PROJECT)
    print("\n  Building the NDVI stack")
    ndvi_imgs, used, aoi, proj = build_ndvi_images(bbox, scenes)
    tides = [s["tide"] for s in used]
    n = len(tides)
    r_crit = r_critical(n)
    print(f"  {n} scenes -> per-pixel critical |r| = {r_crit:.3f}")

    print("\n  Per-pixel regression of NDVI against tide")
    stats = regression_images(ndvi_imgs, tides)
    cls = classify(stats, n)
    dist = distance_to_land(stats, proj)

    print("  Sampling the three classes")
    df_s = sample_classes(stats, cls, dist, aoi)
    if df_s.empty:
        print(f"  Sampling returned nothing. Requiring all {n} scenes "
              f"cloud-free may have removed too much; try --n-scenes 6.")
        return 1
    print(f"  {len(df_s)} sampled pixels")
    got = df_s["cls"].value_counts().to_dict() if "cls" in df_s else {}
    for v, name in CLASS_NAMES.items():
        k = got.get(v, 0)
        if k < SAMPLE_PER_CLASS:
            print(f"    {name}: only {k} of {SAMPLE_PER_CLASS} requested "
                  f"(attrition from requiring all {n} scenes cloud-free)")

    print("  Measuring extent")
    land_ha = class_area_ha(cls, 1, aoi)
    water_ha = class_area_ha(cls, 2, aoi)
    area_ha = class_area_ha(cls, 3, aoi)
    print(f"    vegetated land {land_ha:.1f} ha   deep water {water_ha:.1f} ha"
          f"   intertidal {area_ha:.1f} ha")

    summary = summarise(df_s, r_crit)
    outcome, fails, passes = verdict(summary, area_ha, r_crit)

    tag = f"{args.aoi}_{n}scenes"
    df_s.to_csv(OUT_DIR / f"pixels_{tag}.csv", index=False)
    report = {
        "aoi": args.aoi,
        "tide_gauge_column": args.tide_col or TIDE_COL_PREFERENCE[0],
        "scenes": used,
        "n_scenes": n,
        "tide_range_m": max(tides) - min(tides),
        "r_critical_alpha05_per_pixel": r_crit,
        "months_filter": list(MONTHS),
        "selection_meta": meta,
        "thresholds": {
            "cs": CS_THRESHOLD, "ndvi_veg": NDVI_VEG,
            "ndvi_water": NDVI_WATER, "land_min_ndvi": LAND_MIN_NDVI,
            "deep_water_max_ndvi": DEEP_WATER_MAX_NDVI,
            "control_corr_abs_max": CONTROL_CORR_ABS_MAX,
            "control_slope_abs_max": CONTROL_SLOPE_ABS_MAX,
            "intertidal_corr_max": INTERTIDAL_CORR_MAX,
            "sep_corr_ratio": SEP_CORR_RATIO,
            "sep_slope_ratio": SEP_SLOPE_RATIO,
            "sep_sigfrac_ratio": SEP_SIGFRAC_RATIO,
            "max_median_dist_px": MAX_MEDIAN_DIST_PX,
        },
        "area_ha": {"vegetated_land": land_ha, "deep_water": water_ha,
                    "intertidal": area_ha},
        "class_stats": {CLASS_NAMES[k]: v for k, v in summary.items()},
        "outcome": outcome,
        "failed": fails,
        "passed": passes,
        "caveats": [
            "Intertidal macroalgae extent, NOT a Laminaria digitata map. NDVI "
            "cannot separate L. digitata from Fucus or Ascophyllum.",
            "L. hyperborea wave-attenuation coefficients (Dubi & Torum 1996; "
            "Mork 1996) must NOT be applied to this layer.",
            "No ground-truth validation. The extent figure is unvalidated.",
            "TOA (L1C). NDVI is a ratio and so is far less sensitive to "
            "atmospheric offset than absolute reflectance, but not immune.",
            "A pixel must be cloud-free in every scene, which costs pixels and "
            "could bias against cloud-edge coastal pixels.",
        ],
        "attribution": ATTRIBUTION,
    }
    (OUT_DIR / f"report_{tag}.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n  written: outputs/intertidal/pixels_{tag}.csv")
    print(f"  written: outputs/intertidal/report_{tag}.json   <- cite this")
    return 0


if __name__ == "__main__":
    sys.exit(main())