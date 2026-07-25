#!/usr/bin/env python3
"""
intertidal_test.py - can Sentinel-2 detect intertidal macroalgae in West Cork?

CHANGES IN v3
  1. NO CONSTANT TIDE BAND. v2 attached tide as a constant image band and used
     ee.Reducer.linearFit. Earth Engine types a constant band by its value, so
     each scene produced Float<0.27,0.27>, Float<0.81,0.81> and so on, and the
     collection was rejected as heterogeneous. The regression is now computed
     from plain image arithmetic with the tide weights held on the Python side.
     Identical mathematics, no type problem, and no collection reducers at all.
  2. SINGLE YEAR PREFERRED. v2 selected scenes from 2021, 2024 and 2025. Algal
     biomass varies between years, which is a confound the land control can only
     partly absorb. The selector now looks for one year that supports the test
     on its own and falls back to multiple years with a warning only if no
     single year does. --multi-year forces the old behaviour.
  3. PROPER SIGNIFICANCE TEST. v2 compared a p-value against 0.05 while also
     accepting any correlation below -0.70. Those disagree: with six scenes,
     p < 0.05 requires |r| >= 0.811. The criterion is now the two-tailed
     critical value of Pearson r at df = n - 2, looked up from the scene count,
     so the threshold tightens automatically when there are fewer scenes.
  4. ALL-SCENE PIXELS ONLY. A pixel must be cloud-free in every scene to enter
     the regression. This keeps the tide mean and Sxx identical for every pixel,
     which is what makes the Python-side weights valid.

WHY THIS TEST, AFTER THE SUBTIDAL ONE FAILED
bottom_signal_test.py established that no seabed signal reaches Sentinel-2 at
these sites (two AOIs, restricted to 0-5 m, physics-constrained, negative).
That closes SUBTIDAL detection: Laminaria hyperborea never leaves the water, so
its signal has to travel through metres of it.

Intertidal macroalgae is a different physical problem. At low tide it is OUT of
the water. Exposed algae behaves like terrestrial vegetation: strong reflectance
in the near infrared, weak in the red. Water absorbs NIR almost completely, so
the water column that defeated the subtidal test is simply absent.

THE DESIGN: TIDE DOSE-RESPONSE
Watch the same pixels across several scenes spanning a range of tide heights.

  A genuinely intertidal pixel   NDVI falls as tide rises (progressive
                                 submergence)
  Permanent land                 NDVI does not change with tide  -> CONTROL
  Permanent deep water           NDVI does not change with tide  -> CONTROL

Per pixel, from image arithmetic across the stack, with tide as the predictor:

  xbar = mean(tide),  w_i = tide_i - xbar,  Sxx = sum(w_i^2)
  Sxy  = sum(w_i * ndvi_i)
  Syy  = sum(ndvi_i^2) - n * mean(ndvi)^2
  slope = Sxy / Sxx
  r     = Sxy / sqrt(Sxx * Syy)

Using several tide levels rather than a low/high pair matters. A two-scene
difference can be produced by any two-date change: cloud haze, a different sun
angle, seasonal algal growth. A monotonic dose-response across five or six tide
levels, absent in the land and water controls, cannot.

FALSIFIABILITY - the test can come back negative
  1. LAND CONTROL must be flat. If permanent land also tracks tide, the
     relationship is a date artefact and the whole result is void. This is the
     single most important check.
  2. WATER CONTROL must be flat, for the same reason.
  3. The intertidal class must reach the critical value of r for the number of
     scenes used, in the negative direction.
  4. Tide range must be wide enough to constitute a dose. A 0.4 m spread proves
     nothing regardless of the statistics.
  5. Scenes are restricted to one season, and preferably one year.

WHAT THIS PRODUCES IF IT PASSES
  - An intertidal macroalgae extent map, in hectares, from free satellite data
  - A repeatable measurement, so CHANGE over years becomes possible. The
    challenge deliverable asks the tool to assess decline, and nothing in the
    project addresses that yet. This is the route to it.
  - The lower edge of the intertidal band marks the upper edge of the subtidal
    kelp zone, which constrains the subtidal habitat-suitability model.

WHAT IT CANNOT SHOW - READ THIS BEFORE WRITING ANY SLIDE
  NDVI cannot distinguish species. West Cork intertidal shores carry fucoids
  (Fucus vesiculosus, F. serratus, Ascophyllum nodosum) as well as Laminaria
  digitata, which sits in the lowest intertidal on exposed shores. The product
  is INTERTIDAL MACROALGAE EXTENT, not a Laminaria digitata map.

  Consequence for the valuation chain: the wave-attenuation coefficients
  (Dubi & Tørum 1996; Mork 1996) are measured on L. hyperborea, a subtidal
  species. They must NOT be applied to this intertidal layer. The valuation
  chain continues to run off the subtidal habitat-suitability model.

ESTABLISHED METHOD VERSUS OURS
  Established: NDVI for emergent macroalgae is long-standing practice; the
  Marine Institute / EMFF "Development of Methodologies for Assessment of
  Ireland's Seaweed Resource" project used free Sentinel-2 data for
  county-scale seaweed mapping and a National Seaweed Atlas. NOT YET VERIFIED
  by us: whether that work specifically demonstrated intertidal kelp, and at
  what accuracy. Check the source before citing it as precedent.
  Ours: the tide dose-response design, the control classes, the specific
  thresholds. All printed at run time so they can be argued with.

  Red-edge indices are reported to detect submerged vegetation deeper than NIR
  ones. Not used here, deliberately: for FULLY EXPOSED algae the water column is
  absent, so NIR is unimpaired and standard NDVI at native 10 m is the simpler,
  better-established choice. Red-edge belongs to the submerged problem, which is
  closed.

INPUTS
  Sentinel-2 L1C via Earth Engine, tile 29UMT.
  Tide from outputs/candidate_scenes.csv (scene_selection.py, from the Marine
  Institute Irish National Tide Gauge Network via ERDDAP, measured not
  predicted, LAT datum, CC BY 4.0). Primary gauge: Union Hall Harbor.

Usage
  python intertidal_test.py
  python intertidal_test.py --aoi mizen_outer
  python intertidal_test.py --multi-year
  python intertidal_test.py --tide-col wl_castletownbere_port
  python intertidal_test.py --scenes 2021-05-28:0.27 2021-06-15:2.10
  python intertidal_test.py --list-columns
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import ee
import numpy as np
import pandas as pd

from common import AOIS, ATTRIBUTION, EE_PROJECT, PRIMARY_AOI

MGRS_TILE = "29UMT"
OUT_DIR = Path("outputs/intertidal")
CSV_CANDIDATES = (
    Path("../outputs/candidate_scenes.csv"),
    Path("outputs/candidate_scenes.csv"),
)

# Tide gauge preference, most local first. Union Hall Harbor is 15-20 km from
# Baltimore; Castletownbere is about 50 km away with a tidal phase difference,
# so it is a comparison gauge, not the primary one.
TIDE_COL_PREFERENCE = ("wl_union_hall_harbor", "wl_castletownbere_port")

MONTHS = (5, 6, 7, 8)
N_SCENES = 6
MIN_SCENES = 4
MIN_TIDE_RANGE_M = 1.5
CLEAR_STEPS = (0.90, 0.80, 0.70, 0.60)
CS_THRESHOLD = 0.60
MIN_VALID_OBS = 4

# Two-tailed critical values of Pearson r at alpha = 0.05, df = n - 2.
R_CRIT_05 = {3: 0.997, 4: 0.950, 5: 0.878, 6: 0.811, 7: 0.754, 8: 0.707,
             9: 0.666, 10: 0.632, 11: 0.602, 12: 0.576, 13: 0.553,
             14: 0.532, 15: 0.514}

# Classification. Engineering choices, printed at run time. NDVI for exposed
# brown algae is lower than for terrestrial vegetation because fucoxanthin
# darkens the red edge, so the vegetation threshold sits below the usual
# terrestrial value.
NDVI_VEG = 0.20
NDVI_WATER = 0.00
LAND_MIN_NDVI = 0.25
DEEP_WATER_MAX_NDVI = -0.10

CONTROL_CORR_ABS_MAX = 0.40
CONTROL_SLOPE_ABS_MAX = 0.02      # NDVI units per metre of tide
MIN_INTERTIDAL_HA = 0.5

SAMPLE_PER_CLASS = 300
RANDOM_SEED = 42


def r_critical(n: int) -> float:
    """Critical |r| for significance at alpha = 0.05 with n observations."""
    if n in R_CRIT_05:
        return R_CRIT_05[n]
    if n < min(R_CRIT_05):
        return 0.999
    return R_CRIT_05[max(R_CRIT_05)]


# ===========================================================================
# Candidate list
# ===========================================================================

def load_candidates() -> pd.DataFrame | None:
    for path in CSV_CANDIDATES:
        if path.exists():
            print(f"  reading {path}")
            return pd.read_csv(path)
    print("  candidate_scenes.csv not found. Run from src/, or pass scenes by "
          "hand with --scenes DATE:TIDE ...")
    return None


def detect_columns(df: pd.DataFrame, tide_override: str | None) -> dict:
    cols = {c.lower(): c for c in df.columns}

    def first_containing(*tokens: str) -> str | None:
        for low, orig in cols.items():
            if any(t in low for t in tokens):
                return orig
        return None

    if tide_override:
        if tide_override not in df.columns:
            raise SystemExit(f"--tide-col '{tide_override}' is not in the CSV. "
                             f"Columns: {', '.join(df.columns)}")
        tide = tide_override
    else:
        tide = next((c for c in TIDE_COL_PREFERENCE if c in df.columns), None)
        if tide is None:
            tide = first_containing("tide", "water_level", "wl_", "sea_level")

    return {
        "date": first_containing("datetime", "date", "time", "acquired"),
        "tide": tide,
        "clear": first_containing("clear_frac", "aoi_clear"),
        "aoi": cols.get("aoi"),
        "scene_id": first_containing("scene_id", "system_index", "granule_id"),
        "sun": first_containing("sun_elev"),
        "other_tides": [c for c in df.columns
                        if c.lower().startswith("wl_") and c != tide],
    }


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
            values = sorted(df[cols["aoi"]].astype(str).unique())
            raise SystemExit(f"  No rows for AOI '{aoi_name}'. Values present: "
                             f"{', '.join(values)}")
    else:
        print("  NO 'aoi' column found. Rows for all AOIs may be mixed; treat "
              "the result with suspicion.")

    d["_date"] = pd.to_datetime(d[cols["date"]], errors="coerce", utc=True)
    d["_tide"] = pd.to_numeric(d[cols["tide"]], errors="coerce")
    d = d.dropna(subset=["_date", "_tide"])
    before = len(d)
    d = d[d["_date"].dt.month.isin(MONTHS)]
    print(f"  months {MONTHS}: {before} -> {len(d)} rows")
    if d.empty:
        raise SystemExit("  Nothing left after the seasonal filter.")

    d = d.drop_duplicates(subset=[cols["scene_id"]]) if cols["scene_id"] \
        else d.drop_duplicates(subset=["_date"])

    # Relax the clear-fraction threshold only as far as necessary.
    if cols["clear"]:
        d["_clear"] = pd.to_numeric(d[cols["clear"]], errors="coerce")
        pool, used_clear = None, None
        for step in CLEAR_STEPS:
            sub = d[d["_clear"] >= step]
            ok, spread = _supports_test(sub)
            status = "using this" if ok else "insufficient"
            print(f"  aoi_clear_frac >= {step:.2f}: {len(sub)} scenes, tide "
                  f"spread {spread:.2f} m  <- {status}")
            if ok:
                pool, used_clear = sub, step
                break
        if pool is None:
            raise SystemExit(
                f"  No threshold down to {CLEAR_STEPS[-1]} gives {MIN_SCENES} "
                f"scenes with a {MIN_TIDE_RANGE_M} m tide spread. Widen MONTHS "
                f"or try another AOI.")
    else:
        print("  No clear-fraction column; using all scenes in the window.")
        pool, used_clear = d, None
    meta["clear_frac_threshold_used"] = used_clear

    # Prefer a single year: removes the interannual biomass confound entirely.
    chosen_year = None
    if not allow_multi_year:
        best = None
        print("\n  Looking for a single year that supports the test on its own:")
        for year, sub in pool.groupby(pool["_date"].dt.year):
            ok, spread = _supports_test(sub)
            print(f"    {year}: {len(sub)} scenes, tide spread {spread:.2f} m"
                  f"{'  eligible' if ok else ''}")
            if ok and (best is None or (spread, len(sub)) > best[0]):
                best = ((spread, len(sub)), int(year), sub)
        if best is not None:
            _, chosen_year, pool = best
            print(f"  Using {chosen_year} only. No interannual confound.")
        else:
            print("  No single year qualifies. Falling back to multiple years;")
            print("  the land control is then the guard against date effects.")
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
    """One cloud-masked NDVI image per scene. No constant bands anywhere."""
    aoi = ee.Geometry.Rectangle(bbox)
    base = (ee.ImageCollection("COPERNICUS/S2_HARMONIZED")     # L1C, TOA
            .filterBounds(aoi)
            .filter(ee.Filter.eq("MGRS_TILE", MGRS_TILE)))
    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    base = base.linkCollection(cs_plus, ["cs"])

    images, used = [], []
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
        refl = img.select(["B4", "B8"]).divide(10000)
        ndvi = (refl.normalizedDifference(["B8", "B4"])
                .updateMask(img.select("cs").gte(CS_THRESHOLD))
                .rename("ndvi").toFloat())
        images.append(ndvi)
        used.append(sc)
        print(f"    {sc['date']}  tide {sc['tide']:+.2f} m  matched by {how}")

    if len(used) < MIN_SCENES:
        raise SystemExit(
            f"  Only {len(used)} usable scenes; {MIN_SCENES} are needed for a "
            "correlation to mean anything.")

    tides = [s["tide"] for s in used]
    spread = max(tides) - min(tides)
    print(f"\n  tide range in the stack: {min(tides):+.2f} to {max(tides):+.2f} "
          f"m LAT  (spread {spread:.2f} m)")
    if spread < MIN_TIDE_RANGE_M:
        raise SystemExit(
            f"  Tide spread {spread:.2f} m is below {MIN_TIDE_RANGE_M} m. "
            "Without a dose there is no dose-response and no test.")

    years = sorted({s["date"][:4] for s in used})
    if len(years) > 1:
        print(f"  NOTE: scenes span {len(years)} years ({', '.join(years)}). "
              "Part of any signal could be interannual growth. The land")
        print("  control is the guard: if land is flat, date effects are small.")

    return images, used, aoi


def regression_images(ndvi_imgs: list, tides: list[float]) -> ee.Image:
    """Slope and Pearson r of NDVI against tide, per pixel.

    The tide weights are Python floats, so no constant image band is created and
    no ImageCollection reducer is used. Both were the source of the Earth Engine
    heterogeneous-collection error in v2.

    Masks propagate through the arithmetic, so a pixel survives only if it is
    cloud-free in EVERY scene. That is what keeps the tide mean and Sxx the same
    for every pixel, which the Python-side weights assume.
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
    ndvi_min = ndvi_imgs[0]
    ndvi_max = ndvi_imgs[0]
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

    slope = sxy.divide(sxx).rename("slope")
    corr = sxy.divide(syy.multiply(sxx).sqrt()).rename("corr")

    stats = (slope
             .addBands(corr)
             .addBands(count.rename("n_obs"))
             .addBands(ndvi_min.rename("ndvi_min"))
             .addBands(ndvi_max.rename("ndvi_max"))
             .addBands(ybar.rename("ndvi_mean")))
    # syy <= 0 means NDVI was constant: r is undefined, so drop those pixels.
    return stats.updateMask(syy.gt(0)).updateMask(count.gte(MIN_VALID_OBS))


def classify(stats: ee.Image) -> ee.Image:
    """1 = permanent land, 2 = permanent deep water, 3 = intertidal candidate."""
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
            .updateMask(stats.select("n_obs").gte(MIN_VALID_OBS))
            .toByte())


def sample_classes(stats: ee.Image, cls: ee.Image, aoi) -> pd.DataFrame:
    fc = cls.addBands(stats).stratifiedSample(
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
    res = (ee.Image.pixelArea()
           .updateMask(cls.eq(value))
           .reduceRegion(reducer=ee.Reducer.sum(), geometry=aoi,
                         scale=10, maxPixels=int(1e9))
           .getInfo())
    return float(res.get("area") or 0.0) / 10000.0


# ===========================================================================
# Verdict
# ===========================================================================

CLASS_NAMES = {1: "permanent land (CONTROL)",
               2: "permanent deep water (CONTROL)",
               3: "intertidal candidate (TEST)"}


def summarise(df: pd.DataFrame, r_crit: float) -> dict:
    out = {}
    print(f"\n  {'class':<32}{'n':>6}{'med r':>9}{'|r|>=crit':>11}"
          f"{'med slope':>11}{'NDVI min':>10}{'NDVI max':>10}")
    for value, name in CLASS_NAMES.items():
        sub = df[df["cls"] == value] if "cls" in df else df.iloc[0:0]
        if sub.empty:
            print(f"  {name:<32}{0:>6}   (no pixels in this class)")
            out[value] = {"n": 0}
            continue
        frac_sig = float((sub["corr"].abs() >= r_crit).mean())
        rec = {
            "n": int(len(sub)),
            "median_corr": float(sub["corr"].median()),
            "frac_significant": frac_sig,
            "median_slope": float(sub["slope"].median()),
            "median_ndvi_min": float(sub["ndvi_min"].median()),
            "median_ndvi_max": float(sub["ndvi_max"].median()),
        }
        out[value] = rec
        print(f"  {name:<32}{rec['n']:>6}{rec['median_corr']:>9.3f}"
              f"{frac_sig:>11.2f}{rec['median_slope']:>11.4f}"
              f"{rec['median_ndvi_min']:>10.3f}{rec['median_ndvi_max']:>10.3f}")
    print(f"  Significance uses the two-tailed critical Pearson r at "
          f"alpha=0.05: |r| >= {r_crit:.3f}")
    return out


def verdict(stats: dict, area_ha: float, r_crit: float) -> tuple[str, list[str]]:
    reasons: list[str] = []
    land, water, inter = stats.get(1, {}), stats.get(2, {}), stats.get(3, {})

    controls_ok = True
    for label, s in (("land", land), ("deep water", water)):
        if not s.get("n"):
            controls_ok = False
            reasons.append(f"{label} control has no pixels, so the test has no "
                           f"baseline")
            continue
        if abs(s["median_corr"]) > CONTROL_CORR_ABS_MAX:
            controls_ok = False
            reasons.append(
                f"{label} control tracks tide (median r = "
                f"{s['median_corr']:+.2f}, limit {CONTROL_CORR_ABS_MAX}). "
                f"Something other than tide differs between these dates, so "
                f"any intertidal result is void.")
        if abs(s["median_slope"]) > CONTROL_SLOPE_ABS_MAX:
            controls_ok = False
            reasons.append(
                f"{label} control NDVI shifts {s['median_slope']:+.4f} per "
                f"metre of tide (limit {CONTROL_SLOPE_ABS_MAX})")

    test_ok = True
    if not inter.get("n"):
        test_ok = False
        reasons.append("no intertidal candidate pixels were found at all")
    else:
        if inter["median_corr"] > -r_crit:
            test_ok = False
            reasons.append(
                f"intertidal median r = {inter['median_corr']:+.3f}, not below "
                f"-{r_crit:.3f}, the critical value for this many scenes")
        if inter["frac_significant"] < 0.5:
            test_ok = False
            reasons.append(
                f"only {inter['frac_significant']:.0%} of intertidal pixels "
                f"reach significance; a majority is needed")
        if area_ha < MIN_INTERTIDAL_HA:
            test_ok = False
            reasons.append(
                f"intertidal extent {area_ha:.2f} ha is below "
                f"{MIN_INTERTIDAL_HA} ha: too little to build a product on")

    print("\n  " + "-" * 70)
    if controls_ok and test_ok:
        print("  INTERTIDAL MACROALGAE DETECTED.")
        print(f"  Extent in this AOI: {area_ha:.1f} ha")
        print("  NDVI falls monotonically as tide rises, both controls are")
        print("  flat, and the correlation clears the critical value. The")
        print("  relationship is submergence, not a date artefact.")
        print("\n  WHAT THIS IS: intertidal macroalgae extent. NOT a Laminaria")
        print("  digitata map. NDVI cannot separate it from Fucus or")
        print("  Ascophyllum. Do NOT apply the L. hyperborea wave-attenuation")
        print("  coefficients to this layer.")
        print("\n  WHAT IT UNLOCKS")
        print("    - a working Sentinel-2 product, so 'open satellite data' is")
        print("      honest and the demonstrator criterion is addressable")
        print("    - repeat low-tide scenes across years, the route to the")
        print("      decline assessment the challenge asks for and nothing in")
        print("      the project currently addresses")
        print("    - the lower edge of this band is the upper edge of the")
        print("      subtidal zone, constraining the suitability model")
        print("\n  NEXT: validate against ground truth before claiming any")
        print("  accuracy. NPWS Annex I polygon, MERC 2007 dive stations,")
        print("  Seasearch. An unvalidated extent figure is not a result.")
        out = "detected"
    elif not controls_ok:
        print("  TEST VOID - CONTROLS FAILED.")
        print("  Permanent land or permanent water also tracks tide, so the")
        print("  scenes differ in something other than tide. Do not read the")
        print("  intertidal row. Narrow the season, restrict to one year, or")
        print("  raise the clear-fraction threshold, then re-run.")
        out = "void"
    else:
        print("  NO INTERTIDAL SIGNAL DETECTED.")
        print("  The controls are clean, so this is a real negative rather than")
        print("  an artefact. Before locking it, check that the tide range")
        print("  spans the intertidal zone here and that the AOI contains")
        print("  enough rocky shore.")
        out = "absent"

    if reasons:
        print("\n  Why:")
        for r in reasons:
            print(f"    - {r}")
    print("  " + "-" * 70)
    return out, reasons


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", choices=sorted(AOIS), default=PRIMARY_AOI)
    ap.add_argument("--tide-col", default=None)
    ap.add_argument("--scenes", nargs="*", default=None, metavar="DATE:TIDE")
    ap.add_argument("--n-scenes", type=int, default=N_SCENES)
    ap.add_argument("--multi-year", action="store_true",
                    help="do not prefer a single year")
    ap.add_argument("--list-columns", action="store_true")
    args = ap.parse_args()

    if "PASTE" in EE_PROJECT:
        print("EE_PROJECT is still a placeholder in common.py.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bbox = AOIS[args.aoi]

    print(ATTRIBUTION["SENTINEL2"])
    print(ATTRIBUTION["TIDE_GAUGE"])
    print(f"\n{'=' * 72}\n{args.aoi}   intertidal macroalgae feasibility\n"
          f"{'=' * 72}")
    print(f"  thresholds: NDVI_VEG={NDVI_VEG}  NDVI_WATER={NDVI_WATER}  "
          f"cs>={CS_THRESHOLD}  min obs={MIN_VALID_OBS}")
    print(f"              controls |r| <= {CONTROL_CORR_ABS_MAX}, "
          f"|slope| <= {CONTROL_SLOPE_ABS_MAX}")

    print("\n  Scene selection")
    meta: dict = {}
    if args.scenes:
        scenes = []
        for item in args.scenes:
            try:
                day, tide = item.split(":")
                scenes.append({"date": day.strip(), "tide": float(tide),
                               "scene_id": None})
            except ValueError:
                print(f"  cannot parse '{item}'; expected DATE:TIDE")
                return 1
        scenes.sort(key=lambda s: s["tide"])
        print(f"  {len(scenes)} scenes supplied on the command line")
    else:
        df = load_candidates()
        if df is None:
            return 1
        cols = detect_columns(df, args.tide_col)
        print(f"  columns: date='{cols['date']}'  tide='{cols['tide']}'  "
              f"clear='{cols['clear']}'  aoi='{cols['aoi']}'  "
              f"scene_id='{cols['scene_id']}'")
        if args.list_columns:
            print("\n  all columns:")
            for c in df.columns:
                print(f"    {c}")
            return 0
        if not cols["date"] or not cols["tide"]:
            print("\n  Could not identify the date and tide columns. Use "
                  "--list-columns, then --tide-col or --scenes.")
            return 1
        scenes, meta = pick_scenes(df, cols, args.aoi, args.n_scenes,
                                   args.multi_year)

    ee.Initialize(project=EE_PROJECT)
    print("\n  Building the NDVI stack")
    ndvi_imgs, used, aoi = build_ndvi_images(bbox, scenes)
    tides = [s["tide"] for s in used]
    r_crit = r_critical(len(tides))
    print(f"  {len(tides)} scenes -> critical |r| at alpha=0.05 is {r_crit:.3f}")

    print("\n  Per-pixel regression of NDVI against tide")
    stats = regression_images(ndvi_imgs, tides)
    cls = classify(stats)

    print("  Sampling the three classes")
    df_s = sample_classes(stats, cls, aoi)
    if df_s.empty:
        print("  Sampling returned nothing. Check that the AOI contains "
              "coastline and that the scenes overlap it.")
        return 1
    print(f"  {len(df_s)} sampled pixels")

    print("  Measuring extent")
    land_ha = class_area_ha(cls, 1, aoi)
    water_ha = class_area_ha(cls, 2, aoi)
    area_ha = class_area_ha(cls, 3, aoi)
    print(f"    land {land_ha:.1f} ha   deep water {water_ha:.1f} ha   "
          f"intertidal {area_ha:.1f} ha")

    summary = summarise(df_s, r_crit)
    outcome, reasons = verdict(summary, area_ha, r_crit)

    tag = f"{args.aoi}_{len(used)}scenes"
    csv_path = OUT_DIR / f"pixels_{tag}.csv"
    df_s.to_csv(csv_path, index=False)

    report = {
        "aoi": args.aoi,
        "tide_gauge_column": args.tide_col or TIDE_COL_PREFERENCE[0],
        "scenes": used,
        "n_scenes": len(used),
        "tide_range_m": max(tides) - min(tides),
        "r_critical_alpha05": r_crit,
        "months_filter": list(MONTHS),
        "selection_meta": meta,
        "thresholds": {
            "cs": CS_THRESHOLD, "min_valid_obs": MIN_VALID_OBS,
            "ndvi_veg": NDVI_VEG, "ndvi_water": NDVI_WATER,
            "land_min_ndvi": LAND_MIN_NDVI,
            "deep_water_max_ndvi": DEEP_WATER_MAX_NDVI,
            "control_corr_abs_max": CONTROL_CORR_ABS_MAX,
            "control_slope_abs_max": CONTROL_SLOPE_ABS_MAX,
        },
        "area_ha": {"land": land_ha, "deep_water": water_ha,
                    "intertidal": area_ha},
        "class_stats": {CLASS_NAMES[k]: v for k, v in summary.items()},
        "outcome": outcome,
        "reasons": reasons,
        "caveats": [
            "Intertidal macroalgae extent, NOT a Laminaria digitata map. NDVI "
            "cannot separate L. digitata from Fucus or Ascophyllum.",
            "L. hyperborea wave-attenuation coefficients (Dubi & Torum 1996; "
            "Mork 1996) must NOT be applied to this layer.",
            "No ground-truth validation. The extent figure is unvalidated.",
            "TOA (L1C) reflectance. NDVI is a ratio, so it is far less "
            "sensitive to atmospheric offset than absolute reflectance, but it "
            "is not immune.",
        ],
        "attribution": ATTRIBUTION,
    }
    (OUT_DIR / f"report_{tag}.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n  written: {csv_path}")
    print(f"  written: {OUT_DIR / f'report_{tag}.json'}   <- cite this")
    return 0


if __name__ == "__main__":
    sys.exit(main())