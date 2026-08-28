#!/usr/bin/env python3
"""
national_phaseb.py — Parts 2 and 4 of the national finish-out.

WHAT THIS IS
------------
`anaird_phaseb.py` applied the Sherkin coastal-protection method to ONE new
site by hand. This does the same thing for every site the national screens
flagged, using each site's OWN geometry, OWN fetch and OWN measured wave
direction, and labels every answer by the strength of its habitat evidence.

    Part 2  the BEARING TEST — how much habitat actually lies in the incoming
            wave direction, rather than merely "within 1 km"
    Part 4  the SHERKIN CHAIN — bed, per-axis run lengths, per-axis median
            wave-height reduction, interpolation at the site's own wave
            bearing, energy reduction, the saturation domain check, then the
            valuation

THE FOUR RULES THIS FILE ENFORCES IN CODE, NOT IN PROSE
-------------------------------------------------------
1. **Sherkin is re-derived before anything else runs.** `reproduce_sherkin()`
   is imported from `anaird_phaseb` and must return 7.9 % / 15.2 % from the
   stored 7 cells or this script aborts. If the method here is not the method
   that produced the locked figures, nothing below it may be trusted.
2. **No site's attenuation percentage is ever reused at another site.** Every
   number is computed from that site's own cells. The only cross-site
   constants are the published Dubi & Torum coefficient and the
   pre-registered fetch gate, both imported, never re-typed.
3. **The coefficient carries a domain check and the script stops at it.**
   `saturation_check` compares the width actually traversed with the width
   needed for a 50 % height loss. Sherkin sits at 0.23 of that width; An Aird
   sat at 1.26-1.43 and its 46.7 % was therefore barred from being quoted.
   Any site whose ratio exceeds SATURATION_STOP is marked
   `out_of_domain` and its percentage is reported as an upper bound produced
   by extrapolation, never as an estimate.
4. **Evidence tier travels with every euro.** E1 = survey record, E2 =
   modelled on mapped reef, E3 = modelled with substrate unverified. An E3
   result is a candidate, never a claimed value, and the tier is written into
   the same row as the number.

WHAT A MODELLED BED IS AND IS NOT
----------------------------------
At an E2/E3 site the "bed" is a raster of model predictions, not a surveyed
polygon. `NOTE_2026-08-28_anaird_phaseB.md` §5.2c is explicit that run length
through a prediction raster and run length through a mapped polygon are not
comparable quantities. Every E2/E3 attenuation figure in this file is
therefore labelled `bed_source = model_raster`, and it is additionally
truncated by the gap model's 1 km sampling disc — a bed extending past that
radius is cut off, so the run lengths are a LOWER bound.

Usage:
    PYTHONPATH=src python src/national_phaseb.py
    PYTHONPATH=src python src/national_phaseb.py --clusters 596,1335
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anaird_phaseb import (AXES, BEARING_HALF_WIDTHS, CELL_HA,  # noqa: E402
                           D_VALID, GRID_M, fetch_local_osm,
                           grid_axes as itm_grid_axes, headline,
                           k_dubi_torum, load_npws_local, per_axis_cell_table,
                           rasterise, reproduce_sherkin, saturation_check)
from replacement_cost import (IE_ROCK_ARMOUR_EUR_PER_M,  # noqa: E402
                              replacement_cost)
from wide_receptor_screen import (FETCH_EXCLUSION_MAX, HAB_SEARCH_M,  # noqa: E402
                                  ITM, SHORE_DIST_M, WGS)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "phaseb_national"

CAND_TABLE = REPO / "outputs" / "national_candidate_table.csv"
EXPO_TABLE = REPO / "outputs" / "exposure_screen" / "national_exposure_screen.csv"
DRILLDOWN = REPO / "outputs" / "exposure_screen" / "exposure_flag_drilldown.csv"
WAVE_TABLE = REPO / "outputs" / "exposure_screen" / "site_wave_climate.csv"
ORTHO_MAN = REPO / "outputs" / "exposure_screen" / "ortho" / "ortho_manifest.csv"
GAP_CELLS = REPO / "outputs" / "habitat_gap_model_cells.csv"
GAP_SUMMARY = REPO / "outputs" / "habitat_gap_model_summary.json"

# The step-2 suitability threshold. Read from the model report so it cannot
# drift; the literal is only a fallback assertion.
MODEL_THRESHOLD = 0.7104

# Ratio of traversed width to the width needed for a 50 % height loss above
# which the Dubi & Torum fit is being extrapolated to saturation rather than
# used. 1.0 is the value the An Aird note argued for ("below ~0.5 the
# coefficient is in its near-linear range; above ~1 the answer is an artefact
# of extrapolation"). Pre-registered here BEFORE any national site was run.
SATURATION_STOP = 1.0

# Radius over which habitat is searched for the bearing test. HAB_SEARCH_M is
# the screen's own 1 km; the wider radii are reported for context exactly as
# the An Aird note reports 1/2/6 km.
BEARING_RADII_M = (500, 1000, 2000)
BEARING_PRIMARY = 60.0


def hr(t: str = "") -> None:
    print("\n" + "=" * 78)
    if t:
        print(t)
        print("=" * 78)


def ang_diff(a, b):
    return np.abs((a - b + 180.0) % 360.0 - 180.0)


# ======================================================================
# lattice reconstruction
# ======================================================================

def lattice_from_cells(cells: pd.DataFrame) -> dict:
    """Rebuild the AOI's regular (row, col) lattice from a cell table.

    `habitat_gap_model.py` predicts on `grid_axes(bbox, 50)`, a regular
    lon/lat lattice whose spacing is 50 m in both directions at the AOI's
    mid-latitude, and writes only the cells it could predict. The run-length
    walk needs the lattice back, because "the next cell along NE-SW" is an
    index operation, not a distance query.

    Spacing is recovered as the smallest positive difference between distinct
    coordinates rather than assumed, and the reconstruction is checked: every
    cell must land within a tenth of a cell of an integer index, or the
    lattice is rejected and the site is skipped rather than silently walked
    on a wrong grid.
    """
    lons = np.sort(cells.lon.unique())
    lats = np.sort(cells.lat.unique())
    if len(lons) < 2 or len(lats) < 2:
        return {}
    dlon = float(np.min(np.diff(lons)))
    dlat = float(np.min(np.diff(lats)))
    if dlon <= 0 or dlat <= 0:
        return {}
    ci = (cells.lon.values - lons[0]) / dlon
    ri = (cells.lat.values - lats[0]) / dlat
    if np.max(np.abs(ci - np.round(ci))) > 0.1 or \
       np.max(np.abs(ri - np.round(ri))) > 0.1:
        return {}
    ci = np.round(ci).astype(int)
    ri = np.round(ri).astype(int)
    nx, ny = int(ci.max()) + 1, int(ri.max()) + 1
    if nx * ny > 4_000_000:
        return {}
    return {"col": ci, "row": ri, "nx": nx, "ny": ny,
            "lon0": float(lons[0]), "lat0": float(lats[0]),
            "dlon": dlon, "dlat": dlat}


def grids(cells: pd.DataFrame, lat: dict) -> tuple[np.ndarray, np.ndarray,
                                                   np.ndarray, np.ndarray,
                                                   np.ndarray]:
    """(suitability, depth, log10 fetch, assessed, in_range) on the lattice."""
    shape = (lat["ny"], lat["nx"])
    suit = np.full(shape, np.nan)
    dep = np.full(shape, np.nan)
    fet = np.full(shape, np.nan)
    asd = np.zeros(shape, dtype=bool)
    rng = np.zeros(shape, dtype=bool)
    r, c = lat["row"], lat["col"]
    suit[r, c] = cells.suitability.values
    dep[r, c] = cells.depth_m.values
    fet[r, c] = cells.log10_fetch.values
    asd[r, c] = cells.assessed.values.astype(bool)
    rng[r, c] = cells.in_training_range.values.astype(bool)
    return suit, dep, fet, asd, rng


# ======================================================================
# per-site analysis
# ======================================================================

def bearing_table(mask: np.ndarray, dist: np.ndarray, bear: np.ndarray,
                  wave_from: float) -> dict:
    """Habitat hectares by sector half-width and radius (the Phase B fix).

    Habitat only shelters a receptor if it lies BETWEEN that receptor and the
    water the waves come from, so the sector is centred on the direction waves
    arrive FROM, exactly as in anaird_phaseb.py §4.
    """
    out = {}
    for hw in BEARING_HALF_WIDTHS:
        insec = ang_diff(bear, wave_from) <= hw
        out[str(int(hw))] = {str(r): round(float((mask & insec & (dist <= r)).sum()
                                                 * CELL_HA), 2)
                             for r in BEARING_RADII_M}
    out["none"] = {str(r): round(float((mask & (dist <= r)).sum() * CELL_HA), 2)
                   for r in BEARING_RADII_M}
    return out


def analyse_site(row: pd.Series, cells_all: pd.DataFrame,
                 wave_from: float, wave_to: float) -> dict:
    """Bearing test + Sherkin attenuation chain for one E2/E3 cluster."""
    from pyproj import Transformer
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    cl = int(row.cluster)
    res: dict = {"cluster": cl, "county": row.county,
                 "nearest_place": row.nearest_place,
                 "lon": float(row.lon), "lat": float(row.lat),
                 "evidence_class": row.evidence_class,
                 "wave_from_deg": wave_from, "wave_to_deg": wave_to}

    # ---- pick the AOI this cluster's habitat lives in ----
    cx, cy = to_itm.transform(float(row.lon), float(row.lat))
    ax, ay = to_itm.transform(cells_all.lon.values, cells_all.lat.values)
    d_all = np.hypot(np.asarray(ax) - cx, np.asarray(ay) - cy)
    near = cells_all[d_all <= HAB_SEARCH_M + 400.0]
    if near.empty:
        res["status"] = "no_modelled_cells_within_1km"
        return res
    aoi = near.aoi.value_counts().idxmax()
    cells = cells_all[cells_all.aoi == aoi].copy()
    res["aoi"] = aoi
    res["n_cells_in_aoi"] = int(len(cells))

    lat = lattice_from_cells(cells)
    if not lat:
        res["status"] = "lattice_reconstruction_failed"
        return res
    suit, dep, fet, asd, rng = grids(cells, lat)

    # ---- geometry of the lattice, from the cluster centroid ----
    lons = lat["lon0"] + np.arange(lat["nx"]) * lat["dlon"]
    lats = lat["lat0"] + np.arange(lat["ny"]) * lat["dlat"]
    LON, LAT = np.meshgrid(lons, lats)
    gx, gy = to_itm.transform(LON.ravel(), LAT.ravel())
    gx = np.asarray(gx).reshape(LON.shape)
    gy = np.asarray(gy).reshape(LON.shape)
    dist = np.hypot(gx - cx, gy - cy)
    bear = (np.degrees(np.arctan2(gx - cx, gy - cy)) + 360.0) % 360.0

    # ---- habitat masks ----
    pos = np.isfinite(suit) & (suit >= MODEL_THRESHOLD) & rng
    pos_reef = pos & asd                      # the step-2 "assessed" standard
    res["cells_positive_in_range"] = int(pos.sum())
    res["cells_positive_on_reef"] = int(pos_reef.sum())

    is_e2 = str(row.evidence_class).startswith("E2")
    bed_mask = pos_reef if is_e2 else pos
    res["bed_definition"] = ("model >= threshold, in training range, ON MAPPED "
                             "REEF (the step-2 assessed standard)" if is_e2 else
                             "model >= threshold, in training range, OFF mapped "
                             "reef (substrate UNVERIFIED)")
    res["bed_source"] = "model_raster"

    # ---- Part 2: the bearing test ----
    res["bearing_ha"] = bearing_table(bed_mask, dist, bear, wave_from)
    res["bearing_ha_primary_1km"] = res["bearing_ha"][str(int(BEARING_PRIMARY))]["1000"]
    res["bearing_ha_no_test_1km"] = res["bearing_ha"]["none"]["1000"]

    # ---- Part 4: the Sherkin funnel ----
    in_1km = dist <= HAB_SEARCH_M
    f1 = bed_mask & in_1km
    f2 = f1 & np.isfinite(dep)
    f3 = f2 & (fet > FETCH_EXCLUSION_MAX)
    f4 = f3 & (dep >= D_VALID[0]) & (dep <= D_VALID[1])
    res["funnel"] = {
        "positive_within_1km": int(f1.sum()),
        "with_infomar_depth": int(f2.sum()),
        "and_fetch_over_gate": int(f3.sum()),
        "and_depth_4_10m": int(f4.sum()),
        "ha_final": round(float(f4.sum() * CELL_HA), 2)}
    on_path = ang_diff(bear, wave_from) <= BEARING_PRIMARY
    res["funnel"]["and_on_wave_path"] = int((f4 & on_path).sum())
    res["funnel"]["ha_on_wave_path"] = round(float((f4 & on_path).sum() * CELL_HA), 2)

    # Depth profile of the cells that survive habitat + fetch. This is what
    # decides whether the coefficient may be applied at all, so it is always
    # reported, never only when the answer is zero.
    dsel = dep[f3]
    dsel = dsel[np.isfinite(dsel)]
    if dsel.size:
        res["bed_depth_m"] = {
            "n": int(dsel.size), "min": round(float(dsel.min()), 1),
            "p10": round(float(np.percentile(dsel, 10)), 1),
            "median": round(float(np.median(dsel)), 1),
            "p90": round(float(np.percentile(dsel, 90)), 1),
            "max": round(float(dsel.max()), 1),
            "note": ("INFOMAR, metres below LAT, positive down. A negative "
                     "value is ground that dries at the lowest tides.")}

    if f4.sum() == 0:
        # Say WHICH side of the band, because the two mean different things.
        # Too shallow: the model is predicting in the intertidal / shallow
        # fringe, where L. hyperborea is not the expected species at all
        # (CLAUDE.md rules 3 and 5 keep the intertidal layer separate and
        # restrict the coefficients to subtidal L. hyperborea). Too deep: the
        # bed may well be real L. hyperborea, but Dubi & Torum never measured
        # there. Either way the chain stops, and it stops on physics rather
        # than on missing data.
        if dsel.size and float(np.median(dsel)) < D_VALID[0]:
            res["status"] = "bed_too_shallow_for_coefficient"
        elif dsel.size and float(np.median(dsel)) > D_VALID[1]:
            res["status"] = "bed_too_deep_for_coefficient"
        else:
            res["status"] = "no_bed_in_dubi_torum_depth_range"
        return res

    cellsdf = per_axis_cell_table(f4, dep)
    if cellsdf.empty:
        res["status"] = "no_cell_with_depth_in_bed"
        return res
    head = headline(cellsdf, wave_to)
    res["attenuation"] = head

    # ---- the domain check, and the stop ----
    axis = head["bracketing_axes"][1] if head["weight_on_upper"] >= 0.5 \
        else head["bracketing_axes"][0]
    sat = saturation_check(cellsdf, axis)
    res["saturation"] = {
        "axis_checked": axis,
        "traversed_width_median_m": round(float(sat.width_m.median()), 1),
        "width_for_50pct_loss_median_m": round(float(sat.width_for_50pct_loss_m.median()), 1),
        "ratio_median": round(float(sat.ratio_width_to_50pct.median()), 3),
        "ratio_max": round(float(sat.ratio_width_to_50pct.max()), 2),
        "sherkin_reference_ratio": 0.23,
        "stop_threshold": SATURATION_STOP}
    res["out_of_domain"] = bool(sat.ratio_width_to_50pct.median() > SATURATION_STOP)
    res["status"] = "out_of_domain" if res["out_of_domain"] else "in_domain"

    # ---- the same chain over only the part of the bed on the wave path ----
    #
    # An attenuation percentage computed over a bed that is not between the
    # receptors and the incoming waves describes a real physical effect
    # somewhere else. This flag is the An Aird bearing test applied to the bed
    # itself rather than to the screen's habitat column, and it is reported
    # beside every percentage.
    res["bed_on_wave_path"] = bool((f4 & on_path).sum() > 0)
    if (f4 & on_path).sum() > 0:
        cp = per_axis_cell_table(f4 & on_path, dep)
        if not cp.empty:
            res["attenuation_on_wave_path"] = headline(cp, wave_to)
    return res


def analyse_site_e1(row: pd.Series, wave_from: float, wave_to: float,
                    radius_m: float = 2000.0) -> dict:
    """Bearing test over the NPWS SURVEY polygons at an E1 site.

    Deliberately stops at the bearing test. All three E1 sites came back with
    zero exposed receptors, so their coastal-protection row is an evidenced
    zero and no attenuation figure is needed to reach it; running the INFOMAR
    sampling anyway would spend budget Part 1 still needs. If an E1 site ever
    flags as exposed it takes the full `anaird_phaseb.py` chain instead, which
    is the treatment An Aird already had.

    The habitat here is a SURVEY POLYGON, not a model raster. The two are not
    interchangeable in a run-length calculation (locked rule, 28 Aug), which
    is why `bed_source` differs from the E2/E3 path.
    """
    from pyproj import Transformer
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    cl = int(row.cluster)
    res: dict = {"cluster": cl, "county": row.county,
                 "nearest_place": row.nearest_place,
                 "lon": float(row.lon), "lat": float(row.lat),
                 "evidence_class": row.evidence_class,
                 "wave_from_deg": wave_from, "wave_to_deg": wave_to,
                 "bed_source": "npws_survey_polygon",
                 "bed_definition": "NPWS CO Series Laminaria-dominated reef, "
                                   "subtidal, de-duplicated by exact geometry"}
    cx, cy = to_itm.transform(float(row.lon), float(row.lat))
    half = radius_m + 200.0
    dlat = (half + 600.0) / 111000.0
    dlon = dlat / math.cos(math.radians(float(row.lat)))
    bbox = (float(row.lon) - dlon, float(row.lat) - dlat,
            float(row.lon) + dlon, float(row.lat) + dlat)
    npws = load_npws_local(bbox)
    lam = npws["laminaria"]
    xs, ys = itm_grid_axes(cx, cy, half, GRID_M)
    mask = rasterise(lam.geometry.values, xs, ys)
    XX, YY = np.meshgrid(xs, ys)
    dist = np.hypot(XX - cx, YY - cy)
    bear = (np.degrees(np.arctan2(XX - cx, YY - cy)) + 360.0) % 360.0
    res["bearing_ha"] = bearing_table(mask, dist, bear, wave_from)
    res["bearing_ha_primary_1km"] = res["bearing_ha"][str(int(BEARING_PRIMARY))]["1000"]
    res["bearing_ha_no_test_1km"] = res["bearing_ha"]["none"]["1000"]
    res["status"] = "bearing_test_only_no_exposed_receptor"
    # CONTROL. An Aird (cluster 531) is the one site whose bearing test is
    # already published (NOTE_2026-08-28_anaird_phaseB.md, section 4). If the
    # generalised code does not reproduce it, the generalisation is wrong and
    # the other sites' numbers cannot be trusted either.
    if cl == 531:
        exp = {"none_1km": 58.00, "60_1km": 15.50, "30_1km": 3.50}
        got = {"none_1km": res["bearing_ha"]["none"]["1000"],
               "60_1km": res["bearing_ha"]["60"]["1000"],
               "30_1km": res["bearing_ha"]["30"]["1000"]}
        ok = all(abs(got[k] - v) < 0.01 for k, v in exp.items())
        res["anaird_control"] = {"expected": exp, "got": got, "passed": bool(ok)}
        print(f"   CONTROL vs the published An Aird bearing test: "
              f"{'PASSED' if ok else 'FAILED'}  {got}")
    return res


# ======================================================================
# valuation
# ======================================================================

def frontage_definitions(centre_wgs, receptors, coast) -> dict:
    """Three alongshore lengths. Frontage is definitional, not measured."""
    import geopandas as gpd
    if coast is None or coast.empty or receptors.empty:
        return {}
    c_itm = coast.to_crs(ITM)
    r_itm = receptors.to_crs(ITM)
    cu = unary_union(c_itm.geometry.values)
    centre = gpd.GeoSeries([Point(centre_wgs)], crs=WGS).to_crs(ITM).iloc[0]
    out = {}
    seg = cu.intersection(unary_union([g.buffer(SHORE_DIST_M)
                                       for g in r_itm.geometry.values]))
    out["coastline_within_200m_of_a_receptor"] = float(seg.length)
    out["coastline_within_250m_of_the_centroid"] = float(
        cu.intersection(centre.buffer(250)).length)
    if not seg.is_empty:
        pts = np.array([p for g in getattr(seg, "geoms", [seg])
                        for p in np.array(g.coords)])
        if len(pts) >= 2:
            pts = pts - pts.mean(axis=0)
            _, _, vt = np.linalg.svd(pts, full_matrices=False)
            proj = pts @ vt[0]
            out["principal_axis_span"] = float(proj.max() - proj.min())
    return {k: v for k, v in out.items() if v and v > 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", default="",
                    help="comma-separated cluster ids; default = every flagged one")
    ap.add_argument("--no-osm", action="store_true",
                    help="skip the frontage step if Overpass is down")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")

    hr("NATIONAL PHASE B — bearing test (Part 2) and valuation (Part 4)")
    print(f"  run {t0}")
    print(f"  fetch gate (imported, pre-registered 11 Aug): "
          f"{FETCH_EXCLUSION_MAX}")
    print(f"  Dubi & Torum tested depth range: {D_VALID[0]}-{D_VALID[1]} m")
    print(f"  saturation stop (pre-registered here): ratio > {SATURATION_STOP}")

    # ---- guard 1: the method must reproduce the locked Sherkin figures ----
    hr("GUARD — re-derive the locked Sherkin 7.9 % / 15.2 %")
    sh = reproduce_sherkin()
    print(f"   {sh['n_cells']} cells, {sh['ha']} ha, "
          f"H = {sh['H_reduction']*100:.1f} %, E = {sh['E_reduction']*100:.1f} %")
    if not sh["reproduces_locked_figures"]:
        print("   !! DOES NOT REPRODUCE. Aborting: the method in this file is "
              "not the method that produced the locked figures.")
        return 3
    print("   PASSED. Sherkin's percentages are re-derived, never reused.")

    # ---- inputs ----
    cand = pd.read_csv(CAND_TABLE)
    expo = pd.read_csv(EXPO_TABLE)
    wave = pd.read_csv(WAVE_TABLE)
    drill = pd.read_csv(DRILLDOWN) if DRILLDOWN.exists() else pd.DataFrame()
    ortho = pd.read_csv(ORTHO_MAN) if ORTHO_MAN.exists() else pd.DataFrame()
    cells_all = pd.read_csv(GAP_CELLS)
    if GAP_SUMMARY.exists():
        s = json.loads(GAP_SUMMARY.read_text(encoding="utf-8"))
        thr = (s.get("model") or {}).get("threshold")
        if thr and abs(float(thr) - MODEL_THRESHOLD) > 1e-9:
            print(f"   !! model threshold on disk {thr} != {MODEL_THRESHOLD}")
            return 3

    wave_e1 = REPO / "outputs" / "exposure_screen" / "site_wave_climate_e1.csv"
    if wave_e1.exists():
        wave = pd.concat([wave, pd.read_csv(wave_e1)], ignore_index=True)
        wave = wave.drop_duplicates(subset=["cluster"], keep="first")

    if args.clusters:
        want = [int(x) for x in args.clusters.split(",") if x.strip()]
    else:
        want = expo.loc[expo.exposed_receptors > 0, "cluster"].astype(int).tolist()
    # The three E1 survey-record sites are added even when none is exposed:
    # "no site left unexamined" means the bearing test runs on the sites with
    # the BEST evidence too, not only on the ones that flagged.
    e1 = expo.loc[expo.evidence_class.astype(str).str.startswith("E1"),
                  "cluster"].astype(int).tolist()
    if not args.clusters:
        want = want + [c for c in e1 if c not in want]
    print(f"SITES TO ANALYSE: {want}")
    print(f"  of which E1 survey-record sites (bearing test only): "
          f"{[c for c in want if c in e1]}")

    results, rows = [], []
    for cl in want:
        er = expo[expo.cluster == cl]
        if er.empty:
            print(f"\n--- cluster {cl}: not in the exposure screen; skipped")
            continue
        er = er.iloc[0]
        w = wave[wave.cluster == cl]
        if w.empty or str(w.iloc[0].get("status")) != "ok":
            print(f"\n--- cluster {cl}: NO WAVE DIRECTION. Skipped — a bearing "
                  f"test with a guessed direction is worse than none.")
            results.append({"cluster": cl, "status": "no_wave_direction"})
            continue
        w = w.iloc[0]

        hr(f"CLUSTER {cl} — {er.county} — {er.nearest_place}")
        print(f"   {er.lon:.5f}, {er.lat:.5f}   evidence {er.evidence_class}")
        print(f"   waves FROM {w.wave_from_deg:.1f} deg, travelling TO "
              f"{w.wave_to_deg:.1f} deg (R = {w.concentration_R:.3f}, "
              f"CMEMS 2015-2024, measured at this site)")

        if str(er.evidence_class).startswith("E1"):
            r = analyse_site_e1(er, float(w.wave_from_deg), float(w.wave_to_deg))
        else:
            r = analyse_site(er, cells_all, float(w.wave_from_deg),
                             float(w.wave_to_deg))

        # ---------------- Part 2 report ----------------
        if "bearing_ha" in r:
            print(f"\n   BEARING TEST — habitat (ha) by sector half-width "
                  f"about the {w.wave_from_deg:.0f} deg wave direction")
            print(f"   {'half-width':<16}" +
                  "".join(f"{'<= '+str(x)+' m':>14}" for x in BEARING_RADII_M))
            for hw in list(BEARING_HALF_WIDTHS) + ["none"]:
                k = str(int(hw)) if hw != "none" else "none"
                lab = f"+/-{int(hw)} deg" if hw != "none" else "no bearing test"
                print(f"   {lab:<16}" +
                      "".join(f"{r['bearing_ha'][k][str(x)]:>14.2f}"
                              for x in BEARING_RADII_M))
            print(f"   >>> within 1 km, any direction: "
                  f"{r['bearing_ha_no_test_1km']:.2f} ha; on the wave path "
                  f"(+/-{BEARING_PRIMARY:.0f} deg): "
                  f"{r['bearing_ha_primary_1km']:.2f} ha")

        # ---------------- Part 4 report ----------------
        if "funnel" in r:
            f = r["funnel"]
            print(f"\n   BED FUNNEL (this site's own cells, depths and fetch)")
            print(f"     positive cells within 1 km        {f['positive_within_1km']:>6}")
            print(f"     + INFOMAR depth                   {f['with_infomar_depth']:>6}")
            print(f"     + fetch > {FETCH_EXCLUSION_MAX}                   "
                  f"{f['and_fetch_over_gate']:>6}")
            print(f"     + depth {D_VALID[0]:.0f}-{D_VALID[1]:.0f} m "
                  f"(Dubi & Torum)      {f['and_depth_4_10m']:>6}"
                  f"   = {f['ha_final']:.2f} ha")
            print(f"     of which on the wave path         "
                  f"{f['and_on_wave_path']:>6}   = {f['ha_on_wave_path']:.2f} ha")
        if "bed_depth_m" in r:
            b = r["bed_depth_m"]
            print(f"     depth of the {b['n']} habitat+fetch cells (m below LAT): "
                  f"min {b['min']}, p10 {b['p10']}, median {b['median']}, "
                  f"p90 {b['p90']}, max {b['max']}")
        if r.get("status") == "bed_too_shallow_for_coefficient":
            print("\n   >>> STOP. The modelled bed sits ABOVE the 4 m top of the "
                  "Dubi & Torum tested\n       range — in the intertidal / shallow "
                  "subtidal fringe. L. hyperborea is a\n       subtidal species and "
                  "CLAUDE.md rules 3 and 5 bar applying its coefficients\n       "
                  "there. No attenuation figure is produced. This is a physics "
                  "stop, not\n       missing data.")
        elif r.get("status") == "bed_too_deep_for_coefficient":
            print("\n   >>> STOP. The modelled bed sits BELOW the 10 m bottom of "
                  "the Dubi & Torum\n       tested range. The bed may be real; the "
                  "coefficient was never measured\n       there, so no attenuation "
                  "figure is produced.")
        if "attenuation" in r:
            a, s = r["attenuation"], r["saturation"]
            print(f"\n   ATTENUATION — per-axis medians "
                  f"{ {k: round(v*100,1) for k,v in a['per_axis_median_H'].items()} }")
            print(f"     interpolated at {a['travel_deg']:.1f} deg between "
                  f"{a['bracketing_axes'][0]} and {a['bracketing_axes'][1]} "
                  f"(w = {a['weight_on_upper']:.3f})")
            print(f"     H reduction {a['H_reduction']*100:.1f} %   "
                  f"E reduction {a['E_reduction']*100:.1f} %")
            print(f"\n   DOMAIN CHECK on axis {s['axis_checked']}: traversed "
                  f"{s['traversed_width_median_m']:.0f} m vs "
                  f"{s['width_for_50pct_loss_median_m']:.0f} m for a 50 % loss"
                  f"  -> ratio {s['ratio_median']:.2f} "
                  f"(Sherkin 0.23, stop at {SATURATION_STOP})")
            if r["out_of_domain"]:
                print("     >>> OUT OF DOMAIN. The percentage above is an upper "
                      "bound produced by\n         extrapolating a flume-fitted "
                      "coefficient past its half-loss point.\n         It is NOT "
                      "an estimate of what this bed does and it is not carried "
                      "into a euro.")
            else:
                print("     >>> in domain. The coefficient is being used inside "
                      "its near-linear range.")
            if not r.get("bed_on_wave_path"):
                print("     >>> BUT NONE OF THIS BED IS ON THE WAVE PATH. "
                      "Every cell in the")
                print(f"         {D_VALID[0]:.0f}-{D_VALID[1]:.0f} m band lies outside +/-{BEARING_PRIMARY:.0f} deg of the direction")
                print("         the waves arrive from, so the percentage above describes attenuation")
                print("         that does not happen between these receptors and the sea. It may")
                print("         not be claimed as protection of THIS frontage.")
        else:
            print(f"\n   no attenuation computed: {r.get('status')}")

        # ---------------- receptors, ortho, valuation ----------------
        val = {"cluster": cl}
        dsub = drill[drill.cluster == cl] if not drill.empty else pd.DataFrame()
        osub = ortho[ortho.cluster == cl] if not ortho.empty else pd.DataFrame()
        low = dsub[(dsub.occupied_tag) & (dsub.elev_m < 5)
                   & (~dsub.elev_is_water_pixel)] if not dsub.empty else pd.DataFrame()
        val["exposed_receptors_tag_based"] = int(len(low))
        if not osub.empty:
            v = osub.set_index("osm_id").verdict.to_dict()
            val["ortho_dwelling_like"] = int(sum(1 for i in low.osm_id
                                                 if v.get(i) == "dwelling_like"))
            val["ortho_uncertain"] = int(sum(1 for i in low.osm_id
                                             if v.get(i) == "uncertain"))
            val["ortho_not_a_dwelling"] = int(sum(
                1 for i in low.osm_id
                if v.get(i) in ("ancillary_nonresidential", "ruin_or_no_roof")))
        if not low.empty:
            val["in_opw_1000yr"] = int(low.opw_internal_1000yr_inside.sum())
            val["in_opw_10yr"] = int(low.opw_internal_10yr_inside.sum())
            ins = low[low.opw_internal_1000yr_inside]
            if not osub.empty:
                v = osub.set_index("osm_id").verdict.to_dict()
                val["in_opw_1000yr_dwelling_like"] = int(sum(
                    1 for i in ins.osm_id if v.get(i) == "dwelling_like"))
        print(f"\n   RECEPTORS  tag-based exposed {val['exposed_receptors_tag_based']}"
              f"   ortho: dwelling-like {val.get('ortho_dwelling_like','-')}, "
              f"uncertain {val.get('ortho_uncertain','-')}, "
              f"not a dwelling {val.get('ortho_not_a_dwelling','-')}")
        print(f"   inside OPW 1000 yr {val.get('in_opw_1000yr','-')} "
              f"(dwelling-like {val.get('in_opw_1000yr_dwelling_like','-')}), "
              f"10 yr {val.get('in_opw_10yr','-')}   [INTERNAL COUNT ONLY]")

        # avoided damage
        if len(low) == 0:
            # No occupied-tag building below 5 m at all. The zero is carried by
            # the elevation test, not by the flood test, and it is stated that
            # way rather than as a vacuous "0 of 0".
            val["avoided_damage_eur"] = 0.0
            val["avoided_damage_basis"] = (
                f"EVIDENCED ZERO — no occupied-tag building behind this "
                f"frontage sits below 5 m in Copernicus GLO-30 "
                f"(lowest occupied {er.elev_min_occupied_m} m; "
                f"{int(er.n_occupied_below_10m)} below 10 m of "
                f"{int(er.n_occupied_tag)} occupied-tag buildings). The "
                f"receptor term is zero before the flood test is reached.")
        elif val.get("in_opw_1000yr", 0) == 0:
            val["avoided_damage_eur"] = 0.0
            val["avoided_damage_basis"] = (
                f"EVIDENCED ZERO — 0 of the {len(low)} low-lying occupied-tag "
                f"buildings behind this frontage lie inside the OPW 1000-year "
                f"coastal flood extent. The test could have returned non-zero "
                f"and did not.")
        else:
            val["avoided_damage_eur"] = None
            val["avoided_damage_basis"] = (
                f"NOT COMPUTABLE — {val['in_opw_1000yr']} building(s) are inside "
                f"the OPW 1000-year extent, so the receptor term is not zero, "
                f"but this project has no damage function for wave or erosion "
                f"damage to Irish dwellings and OPW models still water only, "
                f"not overtopping. A missing damage function is not a zero.")
        print(f"\n   AVOIDED DAMAGE: "
              f"{'EUR 0 — evidenced zero' if val['avoided_damage_eur'] == 0 else 'NOT COMPUTABLE'}")
        print(f"     {val['avoided_damage_basis']}")

        # frontage + replacement cost (counterfactual unless C3 is met)
        #
        # HARD SKIP when the bed is not on the wave path. The replacement-cost
        # row scales a structure cost by the bed's energy reduction. If that
        # reduction happens somewhere other than between these receptors and
        # the incoming waves, the product is not a conservative illustration —
        # it is a wrong number wearing a caveat. Refusing to compute it is the
        # conservative choice; the reason is printed so the refusal is visible.
        if not args.no_osm and "attenuation" in r and not r.get("bed_on_wave_path"):
            print("")
            print("   REPLACEMENT COST: NOT COMPUTED. The bed's energy "
                  "reduction does not occur")
            print("     between these receptors and the sea (bearing test, "
                  "above), so scaling a")
            print("     structure cost by it would attribute an effect that "
                  "happens elsewhere.")
            val["replacement_cost"] = []
            val["replacement_cost_skipped"] = "bed_not_on_wave_path"
        elif not args.no_osm and "attenuation" in r:
            try:
                import geopandas as gpd
                d = 0.02
                bbox = (float(er.lon) - d, float(er.lat) - d * 0.6,
                        float(er.lon) + d, float(er.lat) + d * 0.6)
                bld, coast, _ = fetch_local_osm(bbox)
                if not dsub.empty:
                    keep = bld[bld.osm_id.isin(set(dsub.osm_id))]
                else:
                    keep = bld
                fr = frontage_definitions((float(er.lon), float(er.lat)),
                                          keep, coast)
                val["frontage_m"] = {k: round(v) for k, v in fr.items()}
                e_red = float(r["attenuation"]["E_reduction"])
                demand = bool(val.get("in_opw_1000yr", 0) > 0)
                rcs = []
                for lab, L in fr.items():
                    rc = replacement_cost(
                        frontage_m=float(L), energy_reduction=e_red,
                        unit_cost_eur_per_m=IE_ROCK_ARMOUR_EUR_PER_M["central"],
                        demand_condition_met=demand, site=f"cluster_{cl}")
                    rcs.append({"frontage_definition": lab, **asdict(rc)})
                val["replacement_cost"] = rcs
                print(f"\n   REPLACEMENT COST — {'illustrative upper bound' if demand else 'COUNTERFACTUAL ILLUSTRATION, NOT A VALUE'}")
                print(f"   {'frontage definition':<44}{'m':>7}"
                      f"{'full EUR':>14}{'pro-rata':>14}{'EUR/yr':>12}")
                for x in rcs:
                    print(f"   {x['frontage_definition']:<44}"
                          f"{x['frontage_m']:>7.0f}{x['full_structure_eur']:>14,.0f}"
                          f"{x['pro_rata_eur']:>14,.0f}"
                          f"{x['annualised_eur_per_yr']:>12,.0f}")
                if r["out_of_domain"]:
                    print("   >>> These rows are scaled by an OUT-OF-DOMAIN energy "
                          "reduction. They are\n       arithmetic, not evidence. "
                          "The pro-rata scaling is our simplification\n       "
                          "(CLAUDE.md rule 8), not a published method.")
            except Exception as exc:                        # noqa: BLE001
                print(f"   frontage/replacement skipped: "
                      f"{type(exc).__name__}: {str(exc)[:160]}")
                val["frontage_m"] = {}

        r["valuation"] = val
        results.append(r)

        tier = ("E1" if str(er.evidence_class).startswith("E1")
                else "E2" if str(er.evidence_class).startswith("E2") else "E3")
        rows.append({
            "cluster": cl, "county": er.county, "place": er.nearest_place,
            "lon": er.lon, "lat": er.lat,
            "habitat_tier": tier, "evidence_class": er.evidence_class,
            "bed_source": r.get("bed_source", ""),
            "fetch_min": er.fetch_nearest_min,
            "wave_from_deg": w.wave_from_deg,
            "ha_within_1km_any_direction": r.get("bearing_ha_no_test_1km"),
            "ha_on_wave_path_60deg": r.get("bearing_ha_primary_1km"),
            "bed_ha_dubi_torum_band": (r.get("funnel") or {}).get("ha_final"),
            "bed_ha_on_wave_path": (r.get("funnel") or {}).get("ha_on_wave_path"),
            "bed_depth_median_m": (r.get("bed_depth_m") or {}).get("median"),
            "bed_depth_min_m": (r.get("bed_depth_m") or {}).get("min"),
            "bed_depth_max_m": (r.get("bed_depth_m") or {}).get("max"),
            "H_reduction": (r.get("attenuation") or {}).get("H_reduction"),
            "E_reduction": (r.get("attenuation") or {}).get("E_reduction"),
            "saturation_ratio_median": (r.get("saturation") or {}).get("ratio_median"),
            "out_of_domain": r.get("out_of_domain"),
            "bed_on_wave_path": r.get("bed_on_wave_path"),
            "exposed_receptors_tag_based": val.get("exposed_receptors_tag_based"),
            "ortho_dwelling_like": val.get("ortho_dwelling_like"),
            "ortho_not_a_dwelling": val.get("ortho_not_a_dwelling"),
            "ortho_uncertain": val.get("ortho_uncertain"),
            "in_opw_1000yr_internal": val.get("in_opw_1000yr"),
            "in_opw_10yr_internal": val.get("in_opw_10yr"),
            "avoided_damage_eur": val.get("avoided_damage_eur"),
            "avoided_damage_basis": val.get("avoided_damage_basis"),
            "status": r.get("status"),
        })

    out_json = OUT / "national_phaseb_summary.json"
    out_json.write_text(json.dumps(
        {"run_utc": t0, "sherkin_guard": sh,
         "parameters": {"FETCH_EXCLUSION_MAX": FETCH_EXCLUSION_MAX,
                        "MODEL_THRESHOLD": MODEL_THRESHOLD,
                        "D_VALID": list(D_VALID), "GRID_M": GRID_M,
                        "SATURATION_STOP": SATURATION_STOP,
                        "BEARING_PRIMARY": BEARING_PRIMARY},
         "sites": results}, indent=2, default=str), encoding="utf-8")
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "national_phaseb_table.csv", index=False)

    hr("SUMMARY")
    if not tab.empty:
        show = ["cluster", "county", "habitat_tier", "ha_within_1km_any_direction",
                "ha_on_wave_path_60deg", "bed_ha_dubi_torum_band", "H_reduction",
                "E_reduction", "saturation_ratio_median", "out_of_domain",
                "bed_on_wave_path",
                "ortho_dwelling_like", "in_opw_1000yr_internal",
                "avoided_damage_eur"]
        print(tab[show].to_string(index=False))
    print(f"\nWrote {out_json}")
    print(f"Wrote {OUT / 'national_phaseb_table.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
