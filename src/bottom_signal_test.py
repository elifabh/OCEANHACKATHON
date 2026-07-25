#!/usr/bin/env python3
"""
bottom_signal_test.py - is a seabed signal reaching Sentinel-2 at this site?

CHANGES IN THIS VERSION
  1. INFOMAR requests now retry on ArcGIS-level errors (HTTP 400/500 with an
     "error" body) as well as transport errors, with exponential backoff and a
     short delay between batches. A transient 400 from rate limiting used to
     kill the whole run.
  2. Batches that still fail are SKIPPED and counted, and the run prints a loud
     warning that coverage is then a lower bound rather than a measurement.
     A partially sampled AOI must never be read as a coverage result.
  3. The band table now reports the DIRECTION of the sign consistency
     (brighter or darker than deep water), because kelp is a dark bottom and
     the direction changes the interpretation.
  4. Pure-water absorption per band is printed next to the retrieved Kd, so the
     physics check is legible in the output rather than buried in a threshold.
  5. On a negative result the script states what would still have to be ruled
     out before the finding is locked.

WHY THIS TEST EXISTS
An earlier script compared shallow-water standard deviation against deep water
and reported ratios of 7-11x. That test was invalid: no water mask, so land and
surf pixels entered the shallow stratum; the red band showed the same excess as
blue although red light is extinguished within about 2 m of water; removing a
depth trend changed the result by 0.06%, whereas a seabed signal must be
organised by depth; and the exposed site scored higher than the sheltered one.

THE MODEL
Radiative transfer in optically shallow water (Lyzenga 1978, Applied Optics
17:379-383; Lyzenga 1981):

    R(z) = R_inf + (R_bottom - R_inf) * exp(-g * Kd * z)

R_inf   deep-water asymptote, no bottom contribution
Kd      diffuse attenuation coefficient, per metre, per band
z       depth below the instantaneous water surface
g       two-way in-water path factor, 1/cos(theta_water) + 1/cos(theta_view),
        with in-water angles from Snell refraction at n = 1.33

Linearised:  ln|R - R_inf| = ln|R_bottom - R_inf| - g*Kd*z

FIVE CHECKS, ANY OF WHICH CAN FAIL
  A  Sign consistency. A real bottom makes shallow water systematically
     brighter OR systematically darker than R_inf. A coin flip is noise.
     Kelp is a DARK bottom, unlike sand or coral, so a consistently negative
     sign is a pass, not a failure. Hence the absolute value in the transform.
  B  Log-linear fit quality, r-squared of ln|R - R_inf| against depth.
  C  Physics of the retrieved Kd. Pure-water absorption alone sets a floor:
     roughly 0.015 per metre at 490 nm, 0.065 at 560 nm, 0.43 at 665 nm. Red
     always attenuates fastest of B2/B3/B4 in any water type, so Kd(B4) must be
     the largest and must clear its floor. Blue-versus-green ordering is water
     type dependent (CDOM and sediment raise blue) and is NOT used as a test.
  D  Red-edge negative control. Water absorption at 705, 740 and 783 nm is
     roughly 0.7, 2.5 and 2.7 per metre, so B5/B6/B7 cannot return a seabed
     signal from 5-12 m. If they fit as well as the visible bands, the fitted
     relationship is an artefact and the whole test fails.
  E  Out-of-sample skill. Shallow pixels are split in half, the model fitted on
     one half and used to predict the other, and scored against a null model
     that predicts the training mean. Skill at or below zero means no signal.

ESTABLISHED METHOD VERSUS OURS
  Established: Hedley, Harborne & Mumby (2005) IJRS 26:2107-2112 deglinting;
  Lyzenga (1978, 1981) water-column model; Wilson, Wong & Devred (2020)
  Front. Environ. Sci. 8:579856 as the closest published workflow for fully
  submerged kelp in optically complex temperate water.
  Ours: point-wise application on a sampling grid rather than a full raster;
  TOA (L1C) reflectance with no water-specific atmospheric correction; the
  specific pass/fail thresholds, which are engineering choices and are printed
  at run time so they can be argued with.

WHAT THIS CANNOT SHOW
  That the signal is kelp. It tests for a bottom-influenced signal only.
  Species attribution is not achievable from 10 m multispectral data
  (Wilson et al. 2020).

INPUTS
  Sentinel-2 L1C, 2021-05-28, tile 29UMT, tide 0.27 m LAT, sun elevation 59 deg.
  INFOMAR bathymetry, LAT datum confirmed in survey report ROS_GEO19_04_FINAL
  (UKHO VORF model, GNSS tides), ~4.2 m ground resolution, CC BY 4.0.
  Both INFOMAR and the ERDDAP tide gauge are on LAT, so no datum offset.

Usage
  python bottom_signal_test.py
  python bottom_signal_test.py --shallow-max 5
  python bottom_signal_test.py --aoi inner_roaringwater
  python bottom_signal_test.py --aoi mizen_outer --grid 60
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import ee
import numpy as np
import pandas as pd
import requests

from common import (
    AOIS,
    ATTRIBUTION,
    CATEGORY_PRIMARY,
    EE_PROJECT,
    INFOMAR_BATHY,
    PRIMARY_AOI,
    chunked,
    grid_points,
)

# ---------------------------------------------------------------------------
# Scene constants - locked in earlier sessions, see the handover note
# ---------------------------------------------------------------------------
SCENE_DATE = "2021-05-28"
MGRS_TILE = "29UMT"
SCENE_TIDE_M_LAT = 0.27       # tide height at overpass, Union Hall Harbor gauge

VIS_BANDS = ["B2", "B3", "B4"]          # 490, 560, 665 nm
NIR_BAND = "B8"                          # 842 nm, used for deglinting
CONTROL_BANDS = ["B5", "B6", "B7"]      # 705, 740, 783 nm - negative control
SWIR_BAND = "B11"                        # 1610 nm, used for MNDWI

# Pure-water absorption, per metre, approximate, for the physics check.
# These are floors: real Kd is always higher because of CDOM, chlorophyll and
# suspended sediment. A retrieved Kd below the floor is unphysical.
PURE_WATER_KD_FLOOR = {
    "B2": 0.015, "B3": 0.065, "B4": 0.43,
    "B5": 0.70, "B6": 2.50, "B7": 2.70,
}

# ---------------------------------------------------------------------------
# Water mask. Land B8 TOA is about 0.31 here and open water about 0.031
# (established by diagnose_mask.py). The ceiling is deliberately tight so that
# whitecaps and surf are removed as well as land.
# ---------------------------------------------------------------------------
NIR_MAX = 0.055
COAST_BUFFER_PX = 3           # erode the water mask by 3 pixels = 30 m
CS_THRESHOLD = 0.60           # Cloud Score+ 'cs', higher is clearer

SHALLOW_MAX_DEFAULT = 12.0
DEEP_MIN = 40.0               # glint fit and R_inf are drawn from here
REFRACTIVE_INDEX = 1.33

SIGN_CONSISTENCY_MIN = 0.70
R2_MIN = 0.20
KD_MAX = 3.00
SKILL_MIN = 0.05
RANDOM_SEED = 42

# INFOMAR request behaviour
MAX_ATTEMPTS = 5
BATCH_DELAY_S = 0.4           # politeness delay between successful batches

OUT_DIR = Path("outputs/bottom_signal")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OceanHackathonCork2026/kelp-prototype"})


# ===========================================================================
# Statistics helpers - no sklearn or scipy needed
# ===========================================================================

def linreg(x: pd.Series, y: pd.Series) -> dict | None:
    """Ordinary least squares on two series. Returns slope, intercept, r2, n."""
    d = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) < 10:
        return None
    var_x = d["x"].var()
    if not var_x or var_x == 0:
        return None
    slope = d[["x", "y"]].cov().loc["x", "y"] / var_x
    intercept = d["y"].mean() - slope * d["x"].mean()
    pred = slope * d["x"] + intercept
    ss_res = float(((d["y"] - pred) ** 2).sum())
    ss_tot = float(((d["y"] - d["y"].mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {"slope": float(slope), "intercept": float(intercept),
            "r2": float(r2), "n": int(len(d))}


def geometric_path_factor(solar_zenith_deg: float, view_zenith_deg: float) -> float:
    """Two-way in-water path factor g = 1/cos(theta_w) + 1/cos(theta_v)."""
    def refract(theta_air_deg: float) -> float:
        s = math.sin(math.radians(theta_air_deg)) / REFRACTIVE_INDEX
        return math.asin(max(-1.0, min(1.0, s)))

    return 1.0 / math.cos(refract(solar_zenith_deg)) + \
           1.0 / math.cos(refract(view_zenith_deg))


# ===========================================================================
# 1. INFOMAR bathymetry, with retry, backoff and skipped-batch accounting
# ===========================================================================

def sample_bathymetry(points: list[list[float]]) -> tuple[pd.DataFrame, list[int]]:
    """Sample INFOMAR bathymetry, restricted to Primary (survey) rasters.

    Returns (dataframe, list_of_skipped_batch_numbers). A non-empty skip list
    means the coverage seen here is a LOWER BOUND, not a measurement.
    """
    mosaic_rule = json.dumps(
        {"mosaicMethod": "esriMosaicNorthwest",
         "where": f"Category = {CATEGORY_PRIMARY}"}
    )
    rows: list[dict] = []
    skipped: list[int] = []
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

        payload = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = SESSION.post(f"{INFOMAR_BATHY}/getSamples",
                                    data=params, timeout=90)
                resp.raise_for_status()
                body = resp.json()
                # An ArcGIS "error" body arrives with HTTP 200 or 400 and is
                # often transient under rate limiting, so it is retried too.
                if isinstance(body, dict) and "error" in body:
                    raise RuntimeError(body["error"])
                payload = body
                break
            except Exception as exc:                       # noqa: BLE001
                wait = 2 ** attempt
                print(f"    bathy batch {k}/{n_batches} attempt "
                      f"{attempt + 1}/{MAX_ATTEMPTS} failed: {exc}")
                print(f"      waiting {wait}s")
                time.sleep(wait)

        if payload is None:
            skipped.append(k)
            print(f"    bathy batch {k}/{n_batches} SKIPPED after "
                  f"{MAX_ATTEMPTS} attempts")
            continue

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

        if k % 5 == 0 or k == n_batches:
            print(f"    bathy batch {k}/{n_batches} ({len(rows)} samples)")
        time.sleep(BATCH_DELAY_S)

    if skipped:
        print(f"\n  WARNING: {len(skipped)} of {n_batches} bathymetry batches "
              f"were skipped: {skipped}")
        print("  Point counts below are a LOWER BOUND, not a measurement of")
        print("  coverage. Re-run before quoting any coverage figure. If the")
        print("  test result is negative, do not lock it until a clean run.")

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No INFOMAR bathymetry returned for this AOI.")

    # INFOMAR convention: negative below datum. Positive values are land or
    # intertidal and are removed later by the depth filter.
    df["depth_lat_m"] = -df["elev_lat_m"]
    df["depth_inst_m"] = df["depth_lat_m"] + SCENE_TIDE_M_LAT
    return df, skipped


# ===========================================================================
# 2. Sentinel-2, water mask built server-side
# ===========================================================================

def build_scene(bbox: list[float]):
    """Return (masked 10 m stack, 20 m stack, metadata)."""
    ee.Initialize(project=EE_PROJECT)
    aoi = ee.Geometry.Rectangle(bbox)
    end = (pd.Timestamp(SCENE_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    col = (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")     # L1C, TOA
        .filterBounds(aoi)
        .filterDate(SCENE_DATE, end)
        .filter(ee.Filter.eq("MGRS_TILE", MGRS_TILE))
    )
    if col.size().getInfo() == 0:
        raise RuntimeError(f"No L1C scene for {SCENE_DATE}, tile {MGRS_TILE}.")

    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    img = ee.Image(col.linkCollection(cs_plus, ["cs"]).first())

    props = img.toDictionary([
        "system:index",
        "MEAN_SOLAR_ZENITH_ANGLE",
        "MEAN_INCIDENCE_ZENITH_ANGLE_B2",
    ]).getInfo()

    refl = img.select(
        VIS_BANDS + [NIR_BAND] + CONTROL_BANDS + [SWIR_BAND]
    ).divide(10000)

    # Water mask: three independent criteria, all must pass
    ndwi = refl.normalizedDifference(["B3", NIR_BAND])
    mndwi = refl.normalizedDifference(["B3", SWIR_BAND])
    dark_nir = refl.select(NIR_BAND).lt(NIR_MAX)
    water = ndwi.gt(0).And(mndwi.gt(0)).And(dark_nir)

    # Erode so no sample sits within COAST_BUFFER_PX of a rejected pixel.
    # This is what removes the mixed land-water pixels that invalidated the
    # earlier variance-ratio test.
    proj10 = img.select("B2").projection()
    water_clean = (water.reproject(proj10)
                   .focal_min(radius=COAST_BUFFER_PX, units="pixels"))

    stack10 = (refl.select(VIS_BANDS + [NIR_BAND])
               .addBands(img.select("cs"))
               .addBands(water_clean.rename("water"))
               .addBands(ndwi.rename("ndwi"))
               .addBands(mndwi.rename("mndwi")))
    stack20 = refl.select(CONTROL_BANDS + [SWIR_BAND])
    return stack10, stack20, props


def sample_stack(stack, points: list[list[float]], scale: int,
                 label: str) -> pd.DataFrame:
    rows: list[dict] = []
    n_batches = (len(points) + 499) // 500
    for k, batch in enumerate(chunked(points, 500), 1):
        fc = ee.FeatureCollection(
            [ee.Feature(ee.Geometry.Point(p), {"s_lon": p[0], "s_lat": p[1]})
             for p in batch]
        )
        sampled = stack.sampleRegions(collection=fc, scale=scale,
                                      geometries=False)
        rows.extend(f["properties"] for f in sampled.getInfo()["features"])
        print(f"    {label} batch {k}/{n_batches} ({len(rows)} samples)")
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(f"Sentinel-2 {label} sampling returned nothing.")
    return df


def grid_key(lon: float, lat: float, bbox: list[float], nx: int, ny: int) -> str:
    """Map any coordinate back to the grid cell it came from.

    Cell spacing is of order 100 m, far larger than any pixel-centre snapping,
    so this join cannot mismatch. A rounded lon/lat join can, and did.
    """
    xmin, ymin, xmax, ymax = bbox
    i = int(round((lon - xmin) / ((xmax - xmin) / nx) - 0.5))
    j = int(round((lat - ymin) / ((ymax - ymin) / ny) - 0.5))
    return f"{i}_{j}"


# ===========================================================================
# 3. Hedley et al. (2005) deglint, fitted on half the deep pixels
# ===========================================================================

def fit_glint(fit_set: pd.DataFrame, bands: list[str]) -> tuple[dict, float, dict]:
    nir_min = float(fit_set[NIR_BAND].min())
    slopes, diag = {}, {}
    print(f"\n  Hedley deglint, fitted on {len(fit_set)} held-in deep pixels")
    for band in bands:
        cov = fit_set[[band, NIR_BAND]].cov()
        slope = cov.loc[band, NIR_BAND] / cov.loc[NIR_BAND, NIR_BAND]
        r = fit_set[[band, NIR_BAND]].corr().loc[band, NIR_BAND]
        slopes[band] = float(slope)
        diag[band] = {"slope": float(slope), "r2": float(r * r)}
        print(f"    {band}: slope={slope:+.4f}  r2={r * r:.3f}")
        if r * r < 0.20:
            print(f"      weak NIR correlation: little glint in {band}. The "
                  f"correction barely changes it. Report, do not fix.")
    print(f"    min deep NIR = {nir_min:.5f}")
    return slopes, nir_min, diag


def apply_deglint(df: pd.DataFrame, slopes: dict, nir_min: float) -> pd.DataFrame:
    out = df.copy()
    for band, slope in slopes.items():
        out[f"{band}_dg"] = out[band] - slope * (out[NIR_BAND] - nir_min)
    return out


# ===========================================================================
# 4. The Lyzenga test, per band
# ===========================================================================

def test_band(shallow: pd.DataFrame, band_col: str, r_inf: float,
              g: float, rng: np.random.Generator) -> dict:
    res: dict = {"band": band_col, "r_inf": r_inf}

    delta = shallow[band_col] - r_inf
    valid = delta.notna() & (delta != 0)
    if valid.sum() < 20:
        res["status"] = "too_few"
        return res

    d = shallow.loc[valid].copy()
    d["delta"] = delta[valid]

    # A - sign consistency and its direction
    frac_pos = float((d["delta"] > 0).mean())
    res["frac_brighter_than_deep"] = round(frac_pos, 3)
    res["sign_consistency"] = round(max(frac_pos, 1.0 - frac_pos), 3)
    res["direction"] = "brighter" if frac_pos >= 0.5 else "darker"
    dominant_sign = 1.0 if frac_pos >= 0.5 else -1.0

    # B - log-linear fit
    d["ln_abs_delta"] = np.log(d["delta"].abs())
    fit = linreg(d["depth_inst_m"], d["ln_abs_delta"])
    if fit is None:
        res["status"] = "fit_failed"
        return res
    res["slope"] = round(fit["slope"], 5)
    res["r2"] = round(fit["r2"], 3)
    res["n_shallow"] = fit["n"]

    # C - retrieved Kd against the pure-water floor
    kd = -fit["slope"] / g
    base = band_col.split("_")[0]
    res["kd_per_m"] = round(kd, 4)
    res["kd_floor"] = PURE_WATER_KD_FLOOR.get(base)
    res["kd_over_floor"] = (round(kd / res["kd_floor"], 3)
                            if res["kd_floor"] else None)

    # E - out-of-sample skill against a null model
    idx = np.array(d.index)
    rng.shuffle(idx)
    half = len(idx) // 2
    train, test = d.loc[idx[:half]], d.loc[idx[half:]]
    tr_fit = linreg(train["depth_inst_m"], train["ln_abs_delta"])
    if tr_fit is None or len(test) < 10:
        res["oos_skill"] = float("nan")
    else:
        pred = r_inf + dominant_sign * np.exp(
            tr_fit["intercept"] + tr_fit["slope"] * test["depth_inst_m"])
        rmse_model = float(np.sqrt(((test[band_col] - pred) ** 2).mean()))
        null_pred = float(train[band_col].mean())
        rmse_null = float(np.sqrt(((test[band_col] - null_pred) ** 2).mean()))
        res["rmse_model"] = round(rmse_model, 6)
        res["rmse_null"] = round(rmse_null, 6)
        res["oos_skill"] = (round(1.0 - rmse_model / rmse_null, 3)
                            if rmse_null > 0 else float("nan"))

    res["status"] = "ok"
    return res


def print_band_table(results: list[dict], title: str) -> None:
    print(f"\n  {title}")
    print(f"  {'band':<8}{'R_inf':>9}{'sign':>6}{'dir':>10}{'r2':>7}"
          f"{'Kd':>8}{'floor':>7}{'Kd/floor':>10}{'OOS':>8}{'n':>6}")
    for r in results:
        if r.get("status") != "ok":
            print(f"  {r['band']:<8}  [{r.get('status')}]")
            continue
        skill = r.get("oos_skill")
        skill_s = f"{skill:+.3f}" if skill == skill else "n/a"
        over = r.get("kd_over_floor")
        over_s = f"{over:.2f}" if over is not None else "n/a"
        print(f"  {r['band']:<8}{r['r_inf']:>9.5f}{r['sign_consistency']:>6.2f}"
              f"{r['direction']:>10}{r['r2']:>7.3f}{r['kd_per_m']:>8.3f}"
              f"{r['kd_floor']:>7.3f}{over_s:>10}{skill_s:>8}"
              f"{r['n_shallow']:>6}")
    print("  Kd/floor below 1.0 is physically impossible: the retrieval is")
    print("  claiming water clearer than pure water.")


# ===========================================================================
# 5. Verdict
# ===========================================================================

def verdict(vis_results: list[dict], ctl_results: list[dict],
            shallow_max: float, n_very_shallow: int, skipped: list[int]) -> str:
    ok = {r["band"]: r for r in vis_results if r.get("status") == "ok"}
    if not ok:
        print("\n  INCONCLUSIVE: no visible band produced a usable fit.")
        return "inconclusive"

    reasons: list[str] = []

    passers = [
        b for b, r in ok.items()
        if r["sign_consistency"] >= SIGN_CONSISTENCY_MIN
        and r["r2"] >= R2_MIN
        and (r.get("oos_skill") == r.get("oos_skill")
             and r.get("oos_skill", -1) >= SKILL_MIN)
    ]
    if not passers:
        for b, r in ok.items():
            bits = []
            if r["sign_consistency"] < SIGN_CONSISTENCY_MIN:
                bits.append(f"sign {r['sign_consistency']:.2f} "
                            f"< {SIGN_CONSISTENCY_MIN}")
            if r["r2"] < R2_MIN:
                bits.append(f"r2 {r['r2']:.2f} < {R2_MIN}")
            s = r.get("oos_skill")
            if not (s == s) or s < SKILL_MIN:
                bits.append(f"skill {s} < {SKILL_MIN}")
            reasons.append(f"{b}: " + ", ".join(bits))

    # C - Kd physics
    physics_ok = True
    kd = {b: r["kd_per_m"] for b, r in ok.items()}
    for b, r in ok.items():
        over = r.get("kd_over_floor")
        if over is not None and over < 1.0:
            physics_ok = False
            reasons.append(
                f"{b}: Kd {r['kd_per_m']:.3f} is {over:.2f}x the pure-water "
                f"floor {r['kd_floor']:.3f}. Water cannot be clearer than pure "
                f"water, so this is not light attenuating through water.")
    if "B4_dg" in kd and any(kd["B4_dg"] < v for b, v in kd.items()
                             if b != "B4_dg"):
        physics_ok = False
        reasons.append(
            "Kd(B4) is not the largest. Red attenuates fastest in every water "
            "type, so the fit is not describing light through water.")
    if any(v > KD_MAX or v <= 0 for v in kd.values()):
        physics_ok = False
        reasons.append(f"a Kd falls outside (0, {KD_MAX}]")

    # D - red-edge negative control
    control_ok = True
    best_vis_r2 = max((ok[b]["r2"] for b in ok), default=0.0)
    for r in (x for x in ctl_results if x.get("status") == "ok"):
        if r["r2"] >= best_vis_r2 and \
                r["sign_consistency"] >= SIGN_CONSISTENCY_MIN:
            control_ok = False
            reasons.append(
                f"{r['band']} (red-edge) fits at least as well as the best "
                f"visible band (r2 {r['r2']:.2f} vs {best_vis_r2:.2f}). Water "
                f"absorbs these wavelengths within about a metre, so the "
                f"fitted relationship is an artefact common to all bands.")

    print("\n  " + "-" * 70)
    if passers and physics_ok and control_ok:
        print("  BOTTOM SIGNAL PRESENT.")
        print(f"  Bands passing every criterion: {', '.join(sorted(passers))}")
        print("  Depth dependence, retrieved attenuation coefficients and the")
        print("  red-edge control are all consistent with light reaching the")
        print("  seabed and returning.")
        print("\n  NEXT: install ACOLITE, move to L1C plus dark spectrum")
        print("  fitting, and report the retrieved Kd as the site water-clarity")
        print("  estimate, replacing the illustrative values in the notes.")
        print("  Still not demonstrated: that the signal is kelp.")
        out = "present"
    elif passers and (not physics_ok or not control_ok):
        print("  ARTEFACT, NOT BOTTOM SIGNAL.")
        print("  A depth relationship was fitted, but it fails the physics")
        print("  checks, so it is not light travelling through water.")
        out = "artefact"
    else:
        print("  NO BOTTOM SIGNAL DETECTED at this site with Sentinel-2.")
        out = "absent"

    if reasons:
        print("\n  Why:")
        for r in reasons:
            print(f"    - {r}")

    if out in ("absent", "artefact"):
        print("\n  BEFORE LOCKING THIS FINDING, rule out three things:")
        if skipped:
            print(f"    1. {len(skipped)} bathymetry batches were skipped. The")
            print("       shallow stratum is incomplete. Re-run first.")
        else:
            print("    1. Bathymetry sampling was complete, so this is not a")
            print("       data-coverage artefact.")
        if shallow_max > 6.0:
            print(f"    2. The shallow stratum is 0-{shallow_max:.0f} m. Kelp is a")
            print("       DARK bottom, so for these waters detection is only")
            print("       plausible in roughly 0-5 m; deeper pixels add noise")
            print(f"       that can bury it. There are {n_very_shallow} pixels")
            print("       shallower than 5 m here. Re-run with")
            print("       --shallow-max 5 before concluding.")
        else:
            print(f"    2. Already restricted to 0-{shallow_max:.0f} m, so this is")
            print("       not a depth-range artefact.")
        print("    3. This is TOA (L1C) reflectance. R_inf above is mostly")
        print("       atmosphere, and it is one to two orders of magnitude")
        print("       larger than the water-leaving signal a dark bottom can")
        print("       produce at these depths. A water-specific atmospheric")
        print("       correction (ACOLITE, dark spectrum fitting) is the only")
        print("       remaining way to raise the signal-to-background ratio.")
        print("\n  If all three are ruled out, the finding is solid: optical")
        print("  detection is closed at this site. Switch to the")
        print("  habitat-suitability path (INFOMAR bathymetry and backscatter")
        print("  plus wave exposure, validated against the NPWS Annex I reef")
        print("  polygon). Valuation and biodiversity are unaffected, so five")
        print("  of the six jury criteria are untouched. A negative result with")
        print("  a falsifiable test behind it is a finding, and it should be")
        print("  presented as one.")
    print("  " + "-" * 70)
    return out


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", choices=sorted(AOIS), default=PRIMARY_AOI)
    ap.add_argument("--grid", type=int, default=50)
    ap.add_argument("--shallow-max", type=float, default=SHALLOW_MAX_DEFAULT)
    ap.add_argument("--nir-max", type=float, default=NIR_MAX)
    ap.add_argument("--buffer-px", type=int, default=COAST_BUFFER_PX)
    args = ap.parse_args()

    if "PASTE" in EE_PROJECT:
        print("EE_PROJECT is still a placeholder in common.py.")
        return 1

    globals()["NIR_MAX"] = args.nir_max
    globals()["COAST_BUFFER_PX"] = args.buffer_px

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bbox = AOIS[args.aoi]
    nx = ny = args.grid
    pts = grid_points(bbox, nx, ny)
    rng = np.random.default_rng(RANDOM_SEED)

    print(ATTRIBUTION["INFOMAR"])
    print(ATTRIBUTION["SENTINEL2"])
    print(f"\n{'=' * 72}\n{args.aoi}   {len(pts)} grid points   "
          f"shallow 0-{args.shallow_max:.0f} m   deep >{DEEP_MIN:.0f} m\n"
          f"{'=' * 72}")
    print(f"  thresholds: NIR_MAX={args.nir_max}  buffer={args.buffer_px}px  "
          f"cs>={CS_THRESHOLD}")
    print(f"              sign>={SIGN_CONSISTENCY_MIN}  r2>={R2_MIN}  "
          f"skill>={SKILL_MIN}  Kd must clear its pure-water floor")

    print("\n  INFOMAR bathymetry")
    bathy, skipped = sample_bathymetry(pts)
    print(f"  {len(bathy)} points with depth")

    print("\n  Sentinel-2 L1C")
    stack10, stack20, props = build_scene(bbox)
    print(f"  scene: {props.get('system:index')}")
    solar_z = float(props["MEAN_SOLAR_ZENITH_ANGLE"])
    view_z = float(props["MEAN_INCIDENCE_ZENITH_ANGLE_B2"])
    g = geometric_path_factor(solar_z, view_z)
    print(f"  solar zenith {solar_z:.2f} deg, view zenith {view_z:.2f} deg")
    print(f"  two-way in-water path factor g = {g:.3f}  "
          f"(Snell, n={REFRACTIVE_INDEX})")

    s10 = sample_stack(stack10, pts, 10, "vis/nir 10m")
    s20 = sample_stack(stack20, pts, 20, "red-edge/swir 20m")

    for frame, xc, yc in ((bathy, "b_lon", "b_lat"),
                          (s10, "s_lon", "s_lat"),
                          (s20, "s_lon", "s_lat")):
        frame["_k"] = [grid_key(x, y, bbox, nx, ny)
                       for x, y in zip(frame[xc], frame[yc])]

    df = (bathy.merge(s10, on="_k", how="inner", suffixes=("", "_s10"))
                .merge(s20.drop(columns=["s_lon", "s_lat"]), on="_k",
                       how="inner", suffixes=("", "_s20"))
                .drop_duplicates("_k"))
    print(f"\n  joined on grid cell: {len(df)} points")

    n0 = len(df)
    df = df[df["cs"] >= CS_THRESHOLD]
    print(f"  cloud-free (cs >= {CS_THRESHOLD}):      {len(df):>6}  "
          f"(-{n0 - len(df)})")
    n1 = len(df)
    df = df[df["water"] == 1]
    print(f"  clean water, {args.buffer_px}px from land:  {len(df):>6}  "
          f"(-{n1 - len(df)})")
    n2 = len(df)
    df = df[df["depth_inst_m"] > 0]
    print(f"  below the water surface:      {len(df):>6}  (-{n2 - len(df)})")

    if len(df) < 100:
        print("\n  Too few clean pixels to test. Raise --grid, or relax "
              "--buffer-px / --nir-max and record the change.")
        return 1

    shallow = df[df["depth_inst_m"] <= args.shallow_max]
    deep_pool = df[df["depth_inst_m"] >= DEEP_MIN]
    n_very_shallow = int((df["depth_inst_m"] <= 5.0).sum())
    print(f"\n  shallow stratum: {len(shallow)}   of which <=5 m: "
          f"{n_very_shallow}   deep pool: {len(deep_pool)}")

    if len(shallow) < 30:
        print("  Shallow stratum too thin to test this AOI.")
        return 1
    if len(deep_pool) < 60:
        print(f"  Fewer than 60 pixels deeper than {DEEP_MIN:.0f} m. Lower "
              "DEEP_MIN or extend the AOI seaward, and record the change.")
        return 1

    fit_set = deep_pool.sample(frac=0.5, random_state=RANDOM_SEED)

    all_bands = VIS_BANDS + CONTROL_BANDS
    slopes, nir_min, glint_diag = fit_glint(fit_set, all_bands)
    df_dg = apply_deglint(df, slopes, nir_min)
    fit_dg = apply_deglint(fit_set, slopes, nir_min)
    shallow_dg = df_dg[df_dg["depth_inst_m"] <= args.shallow_max]

    # R_inf per band: median over the deglinted fit half. Median, not mean, so
    # residual glint or a stray cloud edge cannot drag it.
    r_inf = {f"{b}_dg": float(fit_dg[f"{b}_dg"].median()) for b in all_bands}

    print("\n  Surface-contamination check (should be close to 1.0):")
    s_nir = float(shallow[NIR_BAND].mean())
    d_nir = float(deep_pool[NIR_BAND].mean())
    print(f"    mean B8 shallow {s_nir:.5f} / deep {d_nir:.5f} "
          f"= {s_nir / d_nir:.2f}")
    if s_nir / d_nir > 1.30:
        print("    Still elevated after masking: residual surf. Tighten "
              "--nir-max or raise --buffer-px and re-run.")

    vis_results = [test_band(shallow_dg, f"{b}_dg", r_inf[f"{b}_dg"], g, rng)
                   for b in VIS_BANDS]
    ctl_results = [test_band(shallow_dg, f"{b}_dg", r_inf[f"{b}_dg"], g, rng)
                   for b in CONTROL_BANDS]

    print_band_table(vis_results, "VISIBLE BANDS - the test")
    print_band_table(ctl_results,
                     "RED-EDGE BANDS - negative control, these must FAIL")

    outcome = verdict(vis_results, ctl_results, args.shallow_max,
                      n_very_shallow, skipped)

    csv_path = OUT_DIR / f"pixels_{args.aoi}_sm{int(args.shallow_max)}.csv"
    df_dg.drop(columns=["_k"]).to_csv(csv_path, index=False)

    report = {
        "aoi": args.aoi,
        "scene": props.get("system:index"),
        "scene_date": SCENE_DATE,
        "tide_m_lat": SCENE_TIDE_M_LAT,
        "solar_zenith_deg": solar_z,
        "view_zenith_deg": view_z,
        "path_factor_g": g,
        "grid": args.grid,
        "skipped_bathy_batches": skipped,
        "thresholds": {
            "nir_max": args.nir_max, "coast_buffer_px": args.buffer_px,
            "cs": CS_THRESHOLD, "shallow_max_m": args.shallow_max,
            "deep_min_m": DEEP_MIN, "sign_min": SIGN_CONSISTENCY_MIN,
            "r2_min": R2_MIN, "kd_max": KD_MAX, "skill_min": SKILL_MIN,
            "pure_water_kd_floor": PURE_WATER_KD_FLOOR,
        },
        "counts": {"clean_pixels": len(df), "shallow": len(shallow),
                   "shallow_le_5m": n_very_shallow,
                   "deep_pool": len(deep_pool), "glint_fit": len(fit_set)},
        "glint": glint_diag,
        "r_inf": r_inf,
        "visible": vis_results,
        "red_edge_control": ctl_results,
        "outcome": outcome,
        "attribution": ATTRIBUTION,
    }
    json_path = OUT_DIR / f"report_{args.aoi}_sm{int(args.shallow_max)}.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n  written: {csv_path}")
    print(f"  written: {json_path}   <- cite this in the write-up")
    return 0


if __name__ == "__main__":
    sys.exit(main())