#!/usr/bin/env python3
"""
national_asset_valuation.py -- the exposure and valuation chain re-run over
the WIDENED receptor set.

WHAT CHANGED, AND WHY IT MATTERS
--------------------------------
`national_phaseb.py` ran the chain with a receptor set of OSM buildings. This
runs the same chain, with the same imported coefficients and the same
pre-registered gates, over the receptor set produced by
`national_asset_screen.py` -- 50 classes of built asset, not one.

Everything here is imported from the scripts that already produced the
published figures. Nothing is re-implemented:

    reproduce_sherkin, analyse_site, analyse_site_e1, frontage_definitions
        from national_phaseb / anaird_phaseb -- the same objects that
        produced the 7.9 % / 15.2 % and the 28 August national table
    FETCH_EXCLUSION_MAX, D_VALID, SATURATION_STOP, BEARING_PRIMARY
        pre-registered, imported, never re-typed
    replacement_cost, IE_ROCK_ARMOUR_EUR_PER_M
        from replacement_cost.py, unchanged
    damage_function_check.check()
        the computed verdict on whether any published avoided-damage method
        fits -- not a sentence in this file's prose

THE EURO DECISION RULES -- PRE-REGISTERED, written before the national asset
screen had finished running
---------------------------------------------------------------------------
R1  If NO receptor of any of the 50 classes is below 5 m facing gate-passing
    water, the coastal-protection row closes at **EUR 0 -- evidenced zero**.
    The zero is stronger than the 28 August one, because the test that could
    have returned non-zero now covers roads, piers, utilities, public assets
    and land parcels rather than buildings alone.

R1b A receptor whose every GLO-30 sample falls on the product's
    water-flattened 0.0 has NO ground elevation. It cannot enter the < 5 m
    band, so it cannot be "exposed" -- and a pier, quay or slipway standing
    in the sea is exactly such a receptor in a 30 m surface model. R1 is
    therefore NOT available at a cluster that has one on gate-passing water:
    an unknown elevation is not a low one and it is not a high one, and
    resting a zero on the DSM's inability to measure the assets that stand
    in the water would manufacture safety. Those clusters go to R2.

R2  If any receptor IS exposed, the row closes at **not computable**, and
    the cell states WHAT is exposed. It does not state a euro, because
    `damage_function_check` finds no published avoided-damage method whose
    inputs this pipeline has. A missing damage function is not a zero.

R3  A EUR 0 may NOT be justified by the receptor lying outside the OPW
    still-water extent when the receptor is a coastal work at the waterline.
    OPW models tide and surge without wave overtopping, and overtopping is
    this project's mechanism; for a slipway or a pier apron the still-water
    extent is the wrong test, not a passed one. The OPW cross-check is
    reported and is not permitted to produce a zero on its own.

R4  The depth band and the wave-path test are unchanged and still stop the
    chain. A widened receptor set cannot licence a coefficient outside
    4-10 m, and cannot make a bed that is not on the wave path protective.

R5  Replacement cost stays barred where Shabman & Batie condition 3 fails.
    The widened screen supplies a NEW and better input to that condition:
    an existing COASTAL PROTECTION STRUCTURE at the frontage (sea wall,
    breakwater, groyne, embankment/dyke) is direct evidence that protection
    was demanded and built there. A pier, quay, slipway or marina is NOT --
    those are demand for a berth, not for shore protection. The two sets are
    kept separate in `PROTECTION_STRUCTURE_CLASSES` and `MARINE_WORKS_CLASSES`
    and only the first is allowed to satisfy condition 3.

R6  Zeros are results. A cluster with nothing exposed is reported with the
    same weight as one with something exposed, and the count of each is in
    the headline.

WHAT THIS SCRIPT DOES NOT DO
---------------------------
It does not invent a damage function, it does not scale one asset class's
damage from another's, and it does not convert an offshore wave-height
reduction into a hazard at a receptor. Those are the three ways a euro could
have appeared here, and all three are barred.

Run:
    PYTHONPATH=src python src/national_asset_valuation.py
    PYTHONPATH=src python src/national_asset_valuation.py --skip-waves
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_classes as ac  # noqa: E402
from anaird_phaseb import (CELL_HA, D_VALID, GRID_M,  # noqa: E402
                           grid_axes as itm_grid_axes, headline,
                           load_npws_local, per_axis_cell_table,
                           rasterise, reproduce_sherkin,
                           sample_infomar, saturation_check)
from damage_function_check import check as damage_check  # noqa: E402
from national_phaseb import (BEARING_PRIMARY, SATURATION_STOP,  # noqa: E402
                             analyse_site, analyse_site_e1,
                             frontage_definitions)
from replacement_cost import (IE_ROCK_ARMOUR_EUR_PER_M,  # noqa: E402
                              replacement_cost)
from wide_receptor_screen import (FETCH_EXCLUSION_MAX,  # noqa: E402
                                  FETCH_RASTER, ITM, WGS,
                                  FetchSampler)

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
ASSET = REPO / "outputs" / "asset_screen"
EXPO = REPO / "outputs" / "exposure_screen"
OUT = REPO / "outputs" / "asset_valuation"

GAP_CELLS = REPO / "outputs" / "habitat_gap_model_cells.csv"

# R5: which classes are evidence of demonstrated demand for PROTECTION
PROTECTION_STRUCTURE_CLASSES = {"sea_wall", "breakwater_groyne",
                                "retaining_wall", "embankment_dyke"}
# ... and which are demand for a berth, which is a different thing
MARINE_WORKS_CLASSES = {"pier_jetty", "quay", "slipway", "harbour", "marina",
                        "dock", "boatyard", "ferry_terminal"}

PY = sys.executable


def hr(t: str = "") -> None:
    print("\n" + "=" * 78)
    if t:
        print(t)
        print("=" * 78)


# ======================================================================
# wave directions for every newly flagged cluster
# ======================================================================

def load_wave_table() -> pd.DataFrame:
    """Every measured wave direction on disk, merged. Globbed, not named, so
    a later batch cannot be silently left out (national_phaseb does the
    same)."""
    files = sorted(EXPO.glob("site_wave_climate*.csv"))
    files = [f for f in files if not f.name.endswith("_run.log")]
    frames = []
    for f in files:
        try:
            d = pd.read_csv(f)
            if "cluster" in d.columns and "wave_from_deg" in d.columns:
                frames.append(d)
        except Exception:                                     # noqa: BLE001
            continue
    if not frames:
        return pd.DataFrame(columns=["cluster", "status", "wave_from_deg",
                                     "wave_to_deg", "concentration_R"])
    w = pd.concat(frames, ignore_index=True)
    w = w[w.cluster.notna()]
    w["cluster"] = w.cluster.astype(int)
    # keep an 'ok' row in preference to an 'unavailable' one for the same site
    w["_rank"] = (w.status.astype(str) != "ok").astype(int)
    w = w.sort_values("_rank").drop_duplicates(subset=["cluster"], keep="first")
    return w.drop(columns=["_rank"])


def ensure_wave_directions(need: pd.DataFrame, wave: pd.DataFrame) -> pd.DataFrame:
    """Measure the wave direction at every flagged cluster that lacks one.

    Each direction is measured AT THAT SITE. There is no default and no
    fallback (locked rule, 28 Aug): a site CMEMS cannot answer is skipped,
    because a guessed bearing silently decides how much habitat counts as
    being in front of a receptor. Downloads are cached under data/cmems/, so
    an outage costs wall clock and never work.
    """
    have = set(wave.loc[wave.status.astype(str) == "ok", "cluster"].astype(int))
    missing = need[~need.cluster.astype(int).isin(have)]
    if missing.empty:
        print("   every flagged cluster already has a measured wave direction")
        return wave
    print("   %d flagged clusters have no measured wave direction yet"
          % len(missing))
    sites = OUT / "wave_sites_assets.csv"
    OUT.mkdir(parents=True, exist_ok=True)
    missing[["cluster", "county", "nearest_place", "lon", "lat",
             "evidence_class"]].to_csv(sites, index=False)
    out_csv = EXPO / "site_wave_climate_assets.csv"
    env = dict(os.environ, PYTHONPATH=str(SRC))
    print("   running site_wave_climate.py on %d sites (cached, resumable)"
          % len(missing))
    p = subprocess.run([PY, "-u", str(SRC / "site_wave_climate.py"),
                        "--sites", str(sites), "--out", str(out_csv)],
                       cwd=str(REPO), env=env, capture_output=True, text=True)
    (OUT / "site_wave_climate_assets_run.log").write_text(
        (p.stdout or "") + "\n" + (p.stderr or ""), encoding="utf-8")
    if p.returncode != 0:
        print("   !! site_wave_climate exited %d -- continuing with whatever "
              "directions it did measure (a failed step is reported, not "
              "fatal)" % p.returncode)
    return load_wave_table()


# ======================================================================
# what is exposed, per cluster
# ======================================================================

def analyse_site_e1_full(row, wave_from: float, wave_to: float,
                         radius_m: float = 2000.0,
                         lattice_half_m: float | None = None,
                         depth_tag: str | None = None) -> dict:
    """The FULL Sherkin chain at an E1 survey-record site.

    `national_phaseb.analyse_site_e1` deliberately stops at the bearing test,
    on a premise that the widened screen has falsified: "All three E1 sites
    came back with zero exposed receptors". They did -- as BUILDINGS. Once
    roads, tracks and coastal works are counted, E1 sites do flag, and the
    28 August note's own limitation 10 says what happens then: "If an E1 site
    ever flags as exposed it takes the full anaird_phaseb.py chain instead."

    This is that chain, assembled from the imported pieces that produced the
    An Aird result -- NPWS survey polygons rasterised on the same lattice,
    INFOMAR depths sampled per cell, the same per-axis run-length walk, the
    same interpolation at the site's own wave bearing, the same saturation
    domain check. Nothing is re-implemented.

    It is EXPENSIVE (INFOMAR sampling, which has gone down mid-run twice in
    this project) and it is cached per site by `sample_infomar` itself, so an
    outage costs wall clock and not work.
    """
    from pyproj import Transformer
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    cl = int(row.cluster)
    res = {"cluster": cl, "bed_source": "npws_survey_polygon",
           "chain": "full_anaird_phaseb", "wave_from_deg": wave_from,
           "wave_to_deg": wave_to}
    cx, cy = to_itm.transform(float(row.lon), float(row.lat))
    half = radius_m + 200.0
    dlat = (half + 600.0) / 111000.0
    dlon = dlat / math.cos(math.radians(float(row.lat)))
    bbox = (float(row.lon) - dlon, float(row.lat) - dlat,
            float(row.lon) + dlon, float(row.lat) + dlat)
    lam = load_npws_local(bbox)["laminaria"]
    if lam is None or not len(lam):
        res["status"] = "no_npws_laminaria_polygon"
        return res
    if lattice_half_m is not None:
        half = float(lattice_half_m)
    xs, ys = itm_grid_axes(cx, cy, half, GRID_M)
    mask = rasterise(lam.geometry.values, xs, ys)
    XX, YY = np.meshgrid(xs, ys)
    dist = np.hypot(XX - cx, YY - cy)
    mask = mask & (dist <= radius_m)
    res["cells_in_polygon"] = int(mask.sum())
    if not mask.sum():
        res["status"] = "no_survey_cells_within_radius"
        return res

    depth = sample_infomar(xs, ys, mask, depth_tag or ("e1full_c%d" % cl))
    d = depth[mask & np.isfinite(depth)]
    res["cells_with_depth"] = int(d.size)
    if d.size:
        res["bed_depth_m"] = {"n": int(d.size), "min": round(float(d.min()), 1),
                              "median": round(float(np.median(d)), 1),
                              "max": round(float(d.max()), 1),
                              "note": "INFOMAR, metres below LAT, positive down"}

    # ---- fetch per lattice cell, exactly as anaird_phaseb does it ----
    # 200 m sampling radius and `fetch_nearest_max`, both carried over
    # unchanged. This is the cell-level fetch gate; the cluster-level gate is
    # a different, coarser thing.
    fs = FetchSampler(FETCH_RASTER)
    try:
        cell_fetch = np.full(mask.shape, np.nan)
        for r_, c_ in np.argwhere(mask):
            cell_fetch[r_, c_] = fs.sample(
                float(xs[c_]), float(ys[r_]),
                radius_m=200.0)["fetch_nearest_max"]
    finally:
        fs.close()

    bear = (np.degrees(np.arctan2(XX - cx, YY - cy)) + 360.0) % 360.0

    # ---- THE WALK IS UNFILTERED; THE SELECTION IS FILTERED ----
    #
    # This is the one place the reassembly got wrong, three times, and the
    # An Aird control caught it every time. `per_axis_cell_table` follows contiguous runs
    # of habitat and integrates each traversed cell's OWN k(D), so the walk
    # must see the WHOLE habitat mask -- filtering the mask first breaks the
    # runs and shortened An Aird's answer from 46.7 % to 21.9 %. The fetch
    # and depth gates are then applied to the ROWS of the resulting table,
    # which is what anaird_phaseb.py does at its line 947 onward.
    cells = per_axis_cell_table(mask, depth)
    if cells.empty:
        res["status"] = "no_cell_with_depth_in_bed"
        return res
    cells["fetch"] = cell_fetch[cells.row.values, cells.col.values]
    cells["bearing_deg"] = bear[cells.row.values, cells.col.values].round(1)
    cells["in_valid_depth"] = ((cells.depth_m >= D_VALID[0])
                               & (cells.depth_m <= D_VALID[1])).astype(int)
    cells["pass_fetch"] = (cells.fetch > FETCH_EXCLUSION_MAX).astype(int)
    res["funnel"] = {
        "habitat_cells_with_depth": int(len(cells)),
        "and_fetch_over_gate": int((cells.pass_fetch == 1).sum()),
        "and_depth_4_10m": int(((cells.pass_fetch == 1)
                                & (cells.in_valid_depth == 1)).sum())}
    res["funnel"]["ha_final"] = round(
        res["funnel"]["and_depth_4_10m"] * CELL_HA, 2)

    bed = cells[(cells.pass_fetch == 1) & (cells.in_valid_depth == 1)]
    res["cells_selected"] = int(len(bed))
    if bed.empty:
        dd = cells.loc[cells.pass_fetch == 1, "depth_m"]
        if len(dd) and float(dd.median()) < D_VALID[0]:
            res["status"] = "bed_too_shallow_for_coefficient"
        elif len(dd) and float(dd.median()) > D_VALID[1]:
            res["status"] = "bed_too_deep_for_coefficient"
        else:
            res["status"] = "no_bed_in_dubi_torum_depth_range"
        return res

    head = headline(bed, wave_to)
    res["attenuation"] = head
    axis = head["bracketing_axes"][1] if head["weight_on_upper"] >= 0.5         else head["bracketing_axes"][0]
    sat = saturation_check(bed, axis)
    res["saturation"] = {
        "axis_checked": axis,
        "traversed_width_median_m": round(float(sat.width_m.median()), 1),
        "width_for_50pct_loss_median_m": round(
            float(sat.width_for_50pct_loss_m.median()), 1),
        "ratio_median": round(float(sat.ratio_width_to_50pct.median()), 3),
        "sherkin_reference_ratio": 0.23,
        "stop_threshold": SATURATION_STOP}
    res["out_of_domain"] = bool(sat.ratio_width_to_50pct.median() > SATURATION_STOP)
    res["status"] = "out_of_domain" if res["out_of_domain"] else "in_domain"

    on_path = bed[_ang_diff(bed.bearing_deg.values, wave_from) <= BEARING_PRIMARY]
    res["bed_on_wave_path"] = bool(len(on_path) > 0)
    res["ha_on_wave_path"] = round(len(on_path) * CELL_HA, 2)
    if len(on_path):
        res["attenuation_on_wave_path"] = headline(on_path, wave_to)
    return res


def _ang_diff(a, b):
    """Smallest absolute angle between two compass bearings, in degrees."""
    d = np.abs((np.asarray(a, dtype=float) - float(b) + 180.0) % 360.0 - 180.0)
    return d


def add_wave_facing(rec: pd.DataFrame, wave_from: float) -> pd.DataFrame:
    """Does each receptor FACE the incoming waves?

    The per-receptor fetch bearing (`sea_bearing_deg`, the true azimuth from
    the receptor to the nearest sea cell) tested against the site's own
    measured wave direction. This is the An Aird bearing test applied to the
    RECEPTOR rather than to the habitat: a road whose water lies to the east
    on a coast whose waves arrive from the west is behind the headland, not
    behind the kelp.

    +/- BEARING_PRIMARY (60 deg) is the same half-width the habitat test
    uses, imported, not re-chosen. It is OUR choice, not a published
    standard -- carried unchanged from the An Aird note.
    """
    rec = rec.copy()
    if "sea_bearing_deg" not in rec.columns or wave_from is None:
        rec["faces_wave_sector"] = np.nan
        return rec
    b = pd.to_numeric(rec.sea_bearing_deg, errors="coerce")
    rec["sea_bearing_deg"] = b
    rec["wave_facing_offset_deg"] = _ang_diff(b.values, wave_from)
    rec["faces_wave_sector"] = rec.wave_facing_offset_deg <= BEARING_PRIMARY
    return rec


def coastline_for_cluster(lon: float, lat: float) -> gpd.GeoDataFrame:
    """The cluster's coastline, from the SAME cached Overpass query the screen
    issued.

    The query string is reproduced byte-for-byte from
    `national_asset_screen.fetch_assets_for_boxes`, so `overpass()` finds it
    in the cache and this costs no network at all. Rebuilding it here rather
    than re-querying means the frontage is measured against exactly the
    coastline the screen measured shore distances against.
    """
    from pyproj import Transformer
    from shapely.geometry import LineString

    from national_asset_screen import BOX_HALF_M
    from wide_receptor_screen import overpass as _ovp

    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    cx, cy = to_itm.transform(lon, lat)
    sw = to_wgs.transform(cx - BOX_HALF_M, cy - BOX_HALF_M)
    ne = to_wgs.transform(cx + BOX_HALF_M, cy + BOX_HALF_M)
    b = (sw[0], sw[1], ne[0], ne[1])
    bb = "%.6f,%.6f,%.6f,%.6f" % (b[1], b[0], b[3], b[2])
    q = ("[out:json][timeout:300];(%s);out geom;"
         % ('way["natural"="coastline"](%s);' % bb))
    try:
        payload = _ovp(q)
    except Exception:                                         # noqa: BLE001
        return gpd.GeoDataFrame(geometry=[], crs=WGS)
    geoms = []
    for el in payload.get("elements", []):
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(pts) >= 2:
            geoms.append(LineString(pts))
    return gpd.GeoDataFrame(geometry=geoms, crs=WGS)


def exposure_statement(rec: pd.DataFrame) -> dict:
    """WHAT is exposed at this cluster -- the sentence that replaces a euro.

    Reported by class, with the count, the minimum elevation and the fetch
    at the seaward-most point, exactly as asked for. Completeness travels
    with every line, because a zero in a low-completeness class is not an
    absence.
    """
    # Receptors with NO ground elevation because GLO-30 flattened every
    # sample to water. They cannot be `exposed` by the band test, and for a
    # pier or slipway standing in the sea that is a limitation of the DSM,
    # not a finding of safety. Reported beside the count, never inside it.
    water = rec[rec.all_samples_water & rec.gate_pass_strict] if len(rec) \
        else rec
    water_classes = sorted({k for ks in water.classes.astype(str)
                            for k in ks.split(";")}) if len(water) else []

    ex = rec[rec.exposed]
    if not len(ex):
        return {"n": 0, "classes": [],
                "n_water_flattened_on_gate_water": int(len(water)),
                "water_flattened_classes": water_classes,
                "text": ("nothing below 5 m facing gate-passing water"
                         + ("; but %d receptor(s) on gate-passing water have "
                            "NO GLO-30 ground elevation at all (every sample "
                            "water-flattened): %s"
                            % (len(water), ", ".join(water_classes))
                            if len(water) else ""))}
    rows = []
    for key in ac.KEYS:
        m = ex.classes.astype(str).str.split(";").apply(lambda ks, k=key: k in ks)
        s = ex[m]
        if not len(s):
            continue
        rows.append({
            "class": key,
            "label": ac.BY_KEY[key]["label"],
            "family": ac.BY_KEY[key]["family"],
            "completeness": ac.BY_KEY[key]["completeness"],
            "n": int(len(s)),
            "elev_min_m": (round(float(s.elev_min_m.min()), 2)
                           if s.elev_min_m.notna().any() else None),
            "fetch_min": (round(float(s.fetch_min.max()), 3)
                          if s.fetch_min.notna().any() else None),
            "named": sorted({str(x) for x in s.name.dropna()})[:6],
        })
    rows.sort(key=lambda r: (-r["n"], r["class"]))
    text = "; ".join("%d %s (min %s m)" % (r["n"], r["class"], r["elev_min_m"])
                     for r in rows[:6])
    if len(water):
        text += ("; plus %d with no GLO-30 ground elevation (all samples "
                 "water-flattened): %s" % (len(water), ", ".join(water_classes)))
    return {"n": int(len(ex)), "classes": rows, "text": text,
            "n_water_flattened_on_gate_water": int(len(water)),
            "water_flattened_classes": water_classes}


def demand_evidence(rec: pd.DataFrame) -> dict:
    """R5 -- is Shabman & Batie condition 3 satisfied at this frontage?

    An existing coastal PROTECTION structure is evidence that protection was
    demanded and built here. A pier or a marina is not: it is demand for a
    berth. The distinction is the whole point of keeping the two sets apart.
    """
    if not len(rec):
        return {"protection_structures": {}, "marine_works": {},
                "sb3_demonstrated_demand": False, "basis": "no receptors"}

    def counts(keys, frame):
        out = {}
        for k in keys:
            m = frame.classes.astype(str).str.split(";").apply(
                lambda ks, kk=k: kk in ks)
            if int(m.sum()):
                out[k] = int(m.sum())
        return out

    # A protection structure only counts as evidence of demand for COASTAL
    # protection if it is plausibly a COASTAL defence -- that is, if it is
    # itself low-lying and facing gate-passing water. The screen's own
    # `exposed` flag is exactly that test, so no new threshold is introduced.
    #
    # This tightening was forced by the first national run, which reported
    # Shabman & Batie condition 3 satisfied at four clusters. Two were false
    # positives that elevation alone exposes: seven `barrier=retaining_wall`
    # at cluster 88 sit between 15 m and 79 m on a hillside, and two
    # `man_made=embankment` at cluster 231 sit at 18.7 m and 36.2 m. A wall at
    # 79 m is not protecting anything from the sea. Counting them would have
    # satisfied, for the first time in this project, the very condition that
    # unlocks a replacement-cost VALUE rather than a counterfactual
    # illustration -- on two road walls and a field bank.
    prot_all = counts(PROTECTION_STRUCTURE_CLASSES, rec)
    exposed_only = rec[rec.exposed] if "exposed" in rec.columns else rec.iloc[0:0]
    prot = counts(PROTECTION_STRUCTURE_CLASSES, exposed_only)
    marine = counts(MARINE_WORKS_CLASSES, rec)
    if prot:
        basis = ("a coastal protection structure is mapped at this frontage, "
                 "low-lying and facing gate-passing water (%s)"
                 % ", ".join("%s x%d" % (k, v) for k, v in prot.items()))
    elif prot_all:
        basis = ("protection-class structures are mapped here (%s) but NONE is "
                 "low-lying and facing gate-passing water, so none is evidence "
                 "of demand for COASTAL protection -- a retaining wall or "
                 "embankment well above the shore is a road or field structure"
                 % ", ".join("%s x%d" % (k, v) for k, v in prot_all.items()))
    else:
        basis = ("no coastal protection structure mapped at this frontage; "
                 "marine works present (%s) are demand for a berth, not for "
                 "shore protection" % (", ".join(marine) or "none"))
    return {
        "protection_structures": prot,
        "protection_structures_any_elevation": prot_all,
        "marine_works": marine,
        "sb3_demonstrated_demand": bool(prot),
        "basis": basis,
    }


def write_markdown_table(df: pd.DataFrame, results: list) -> None:
    """The deliverable table, generated rather than typed.

    Columns are the ones asked for on 2026-08-28: receptor type, count,
    minimum elevation, whether it faces gate-passing water, and the euro
    cell. Ordered so the sites that carry a finding are at the top and the
    zeros are visible below them rather than buried -- a zero is a result.
    """
    lines = [
        "# National asset screen -- coastal-protection row, per cluster",
        "",
        "Generated by `src/national_asset_valuation.py`. Do not hand-edit.",
        "",
        "> (c) OpenStreetMap contributors, ODbL 1.0. Every receptor count, "
        "class, geometry and length here derives from OSM via the Overpass "
        "API and is an ODbL derivative database.",
        "> Elevations: Copernicus WorldDEM-30 (GLO-30), a Digital SURFACE "
        "model at 30 m, biased upward.",
        "> **No euro leaves this table.** Where a receptor is exposed the "
        "cell states what is exposed and stops: no published avoided-damage "
        "method has the inputs this pipeline produces "
        "(`src/damage_function_check.py`).",
        "",
        "| # | cluster | county / place | tier | receptors | <5 m | gate | "
        "EXPOSED | min elev | what is exposed | coastal protection |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    d = df.sort_values(["n_exposed", "n_low_5m"], ascending=[False, False])
    for i, (_, r) in enumerate(d.iterrows(), start=1):
        tier = str(r.evidence_class).split("_")[0]
        what = str(r.exposed_summary) if r.n_exposed else "nothing"
        lines.append(
            "| %d | **%d** | %s - %s | %s | %d | %d | %d | **%d** | %s | %s | %s |"
            % (i, r.cluster, r.county, str(r.nearest_place)[:38], tier,
               r.n_receptors, r.n_low_5m, r.n_gate_pass, r.n_exposed,
               "-" if pd.isna(r.elev_min_m) else "%.2f m" % float(r.elev_min_m),
               what, r.coastal_protection_eur))
    lines += ["", "## Why each euro cell reads as it does", ""]
    for r in results:
        lines.append("**%d %s -- %s**  \n%s\n"
                     % (r["cluster"], r["county"], r["coastal_protection_eur"],
                        r["euro_reason"]))
    (OUT / "NATIONAL_ASSET_TABLE.md").write_text("\n".join(lines),
                                                 encoding="utf-8")


def control_e1_full_chain() -> dict:
    """Does the reassembled E1 chain reproduce the published An Aird result?

    `analyse_site_e1_full` is new code assembled from imported pieces, and new
    code that produces a percentage must be shown to reproduce one that is
    already published before it is used anywhere else. An Aird (cluster 531)
    is the only E1 site whose full chain has been run and written up
    (NOTE_2026-08-28_anaird_phaseB.md): H 46.7 %, E 71.6 %, saturation ratio
    1.26-1.43, OUT OF DOMAIN.

    Run on An Aird's own lattice (half-width 6 000 m) and its own INFOMAR
    depth cache tag, so it costs no network and compares like with like. It
    uses the SAME code path a real site gets -- no special-casing -- so a pass
    means the production path is the published method.
    """
    expected = {"H_pct": 46.7, "E_pct": 71.6, "out_of_domain": True}
    try:
        expo = pd.read_csv(EXPO / "national_exposure_screen.csv")
        r = expo[expo.cluster == 531]
        if r.empty:
            return {"ran": False, "reason": "cluster 531 not in the screen"}
        r = r.iloc[0]
        w = load_wave_table()
        w = w[(w.cluster == 531) & (w.status.astype(str) == "ok")]
        if w.empty:
            return {"ran": False, "reason": "no measured wave direction for 531"}
        w = w.iloc[0]
        got = analyse_site_e1_full(r, float(w.wave_from_deg),
                                   float(w.wave_to_deg),
                                   lattice_half_m=6000.0,
                                   depth_tag="anaird_6000m")
    except Exception as exc:                                  # noqa: BLE001
        return {"ran": False, "reason": "chain raised: %s" % exc}
    att = got.get("attenuation")
    if not att:
        return {"ran": True, "passed": False, "expected": expected,
                "got_status": got.get("status"),
                "reason": "no attenuation produced"}
    gh = round(att["H_reduction"] * 100, 1)
    ge = round(att["E_reduction"] * 100, 1)
    ratio = (got.get("saturation") or {}).get("ratio_median")
    ok = (abs(gh - expected["H_pct"]) <= 0.15
          and abs(ge - expected["E_pct"]) <= 0.15
          and bool(got.get("out_of_domain")) == expected["out_of_domain"])
    return {"ran": True, "passed": bool(ok), "expected": expected,
            "got": {"H_pct": gh, "E_pct": ge,
                    "out_of_domain": bool(got.get("out_of_domain")),
                    "saturation_ratio_median": ratio}}


# ======================================================================
# main
# ======================================================================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-waves", action="store_true",
                    help="do not call site_wave_climate for missing sites")
    ap.add_argument("--clusters", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now(timezone.utc)

    hr("NATIONAL ASSET VALUATION -- the chain over the widened receptor set")
    print("run %s" % t0.isoformat(timespec="seconds"))
    print("fetch gate (imported)      %s" % FETCH_EXCLUSION_MAX)
    print("Dubi & Torum depth band    %.1f-%.1f m" % D_VALID)
    print("saturation stop            ratio > %.1f" % SATURATION_STOP)
    print("bearing half-width         +/- %.0f deg" % BEARING_PRIMARY)

    # ---- guard: the method must still re-derive the locked Sherkin figures
    hr("GUARD -- re-derive the locked Sherkin 7.9 % / 15.2 %")
    sh = reproduce_sherkin()
    print("   %d cells, %s ha, H = %.1f %%, E = %.1f %%"
          % (sh["n_cells"], sh["ha"], sh["H_reduction"] * 100,
             sh["E_reduction"] * 100))
    if not sh["reproduces_locked_figures"]:
        print("   !! DOES NOT REPRODUCE -- aborting.")
        return 3
    print("   PASSED.")

    # ---- guard: the reassembled E1 chain must reproduce An Aird ----
    hr("GUARD -- reassembled E1 chain vs the published An Aird result")
    e1c = control_e1_full_chain()
    if not e1c.get("ran"):
        print("   NOT RUN: %s" % e1c.get("reason"))
        print("   analyse_site_e1_full() is therefore UNVALIDATED. It is "
              "only invoked at an E1 site that both flags and has a mapped "
              "coastal protection structure; if that happens, its output "
              "must be treated as unverified.")
    elif e1c["passed"]:
        print("   PASSED  expected %s, got %s" % (e1c["expected"], e1c["got"]))
    else:
        print("   >>> FAILED  expected %s, got %s"
              % (e1c["expected"], e1c.get("got", e1c.get("got_status"))))
        print("   The reassembled chain does not reproduce the published "
              "An Aird figures. Any E1 full-chain output below is not to be "
              "believed.")

    # ---- guard: no avoided-damage method may have quietly become available
    hr("GUARD -- damage-function applicability")
    dfc = damage_check()
    print("   any published avoided-damage method fits: %s"
          % dfc["any_avoided_damage_method_fits"])
    for m in dfc["methods"]:
        if m["key"] == "replacement_cost":
            continue
        print("      %-58s %s" % (m["name"][:58],
                                  "FITS" if m["fits"] else
                                  "missing %d input(s)" % len(m["missing"])))

    # ---- inputs ----
    scr_f = ASSET / "national_asset_screen.csv"
    rec_f = ASSET / "national_asset_receptors.csv"
    if not scr_f.exists():
        print("\nNo asset screen output. Run national_asset_screen.py first.")
        return 1
    scr = pd.read_csv(scr_f)
    rec = pd.read_csv(rec_f) if rec_f.exists() else pd.DataFrame()
    if args.clusters:
        want = {int(x) for x in args.clusters.split(",") if x.strip()}
        scr = scr[scr.cluster.isin(want)]
    print("\n%d clusters screened for assets" % len(scr))

    flagged = scr[scr.n_exposed > 0].copy()
    clean = scr[scr.n_exposed == 0].copy()
    print("   %d with >0 exposed receptors" % len(flagged))
    print("   %d with none exposed  <- these are the evidenced zeros"
          % len(clean))

    # ---- wave directions ----
    hr("WAVE DIRECTION -- measured at each flagged site, never carried")
    wave = load_wave_table()
    if not args.skip_waves and len(flagged):
        wave = ensure_wave_directions(flagged, wave)
    ok_w = set(wave.loc[wave.status.astype(str) == "ok", "cluster"].astype(int))
    print("   %d clusters have a measured direction" % len(ok_w))

    cells_all = pd.read_csv(GAP_CELLS) if GAP_CELLS.exists() else pd.DataFrame()

    # ---- per cluster ----
    results: list = []
    for _, c in scr.sort_values("n_exposed", ascending=False).iterrows():
        cl = int(c.cluster)
        sub = rec[rec.cluster == cl] if len(rec) else pd.DataFrame()
        hr("CLUSTER %d -- %s -- %s" % (cl, c.county, c.nearest_place))
        print("   %.5f, %.5f   evidence %s" % (c.lon, c.lat, c.evidence_class))
        print("   %d receptors in 500 m | %d below 5 m | %d pass fetch gate "
              "| %d EXPOSED" % (c.n_assets, c.n_low_5m, c.n_gate_pass,
                                c.n_exposed))

        exp = exposure_statement(sub) if len(sub) else {"n": 0, "classes": [],
                                                        "text": "no receptors"}
        if exp["n"]:
            print("   WHAT IS EXPOSED:")
            for r in exp["classes"]:
                print("      %-22s %-16s n=%-4d min %-7s fetch %-7s  [%s]"
                      % (r["class"], r["family"], r["n"],
                         r["elev_min_m"], r["fetch_min"], r["completeness"]))
        else:
            print("   WHAT IS EXPOSED: nothing")

        row = {"cluster": cl, "county": c.county,
               "nearest_place": c.nearest_place,
               "evidence_class": c.evidence_class,
               "lon": float(c.lon), "lat": float(c.lat),
               "n_receptors": int(c.n_assets),
               "n_low_5m": int(c.n_low_5m),
               "n_gate_pass": int(c.n_gate_pass),
               "n_exposed": int(c.n_exposed),
               "n_exposed_high_completeness": int(c.n_exposed_high_completeness),
               "elev_min_m": c.elev_min_m,
               "exposed_summary": exp["text"],
               "exposed_classes": ";".join(r["class"] for r in exp["classes"]),
               }

        # ---- the habitat side: bearing test + Sherkin chain ----
        hab: dict = {}
        if cl in ok_w and len(cells_all):
            w = wave[wave.cluster == cl].iloc[0]
            wf, wt = float(w.wave_from_deg), float(w.wave_to_deg)
            print("   waves FROM %.1f deg -> TO %.1f deg (R %.3f, measured here)"
                  % (wf, wt, float(w.concentration_R)))
            try:
                if str(c.evidence_class).startswith("E1"):
                    # The 28 Aug limitation 10 rule: an E1 site that flags as
                    # exposed takes the FULL chain, not the bearing test only.
                    # That premise ("all three E1 sites came back with zero
                    # exposed receptors") held for buildings and does not hold
                    # for roads, tracks and coastal works.
                    #
                    # The full chain is run where it can change a cell. Its
                    # only output is an attenuation percentage, and that feeds
                    # ONLY the replacement-cost row: the avoided-damage row is
                    # already "not computable" under R2 wherever a receptor is
                    # exposed, whatever the percentage. Replacement cost in
                    # turn needs Shabman & Batie condition 3. So the chain is
                    # run when the site flags AND a coastal PROTECTION
                    # structure is mapped at the frontage; otherwise the
                    # bearing test is reported and the reason is stated, not
                    # left as a silence.
                    dem_pre = demand_evidence(sub) if len(sub) else {
                        "sb3_demonstrated_demand": False}
                    flagged_here = int(c.n_exposed) > 0
                    if flagged_here and dem_pre["sb3_demonstrated_demand"]:
                        print("   E1 site with exposed receptors AND a mapped "
                              "coastal protection structure -> running the "
                              "FULL anaird_phaseb chain (28 Aug limitation 10)")
                        hab = analyse_site_e1_full(c, wf, wt)
                    else:
                        hab = analyse_site_e1(c, wf, wt)
                        if flagged_here:
                            hab["status"] = (
                                "e1_bearing_test_only_full_chain_not_needed")
                            hab["full_chain_skipped_because"] = (
                                "This E1 site DOES have exposed receptors, so "
                                "the 28 Aug premise for stopping at the "
                                "bearing test no longer holds. The full chain "
                                "was still not run, for a different and "
                                "stated reason: its only output is an "
                                "attenuation percentage, which feeds only the "
                                "replacement-cost row, and that row is barred "
                                "here by Shabman & Batie condition 3 (no "
                                "coastal protection structure is mapped at "
                                "this frontage). The avoided-damage row is "
                                "'not computable' under R2 regardless of the "
                                "percentage.")
                else:
                    hab = analyse_site(c, cells_all, wf, wt)
            except Exception as exc:                          # noqa: BLE001
                hab = {"status": "chain_failed: %s" % exc}
            row["wave_from_deg"] = wf
            row["wave_to_deg"] = wt
            if len(sub):
                sub = add_wave_facing(sub, wf)
                exf = sub[sub.exposed]
                n_face = int(exf.faces_wave_sector.sum()) if len(exf) else 0
                row["n_exposed_facing_waves"] = n_face
                row["n_exposed_not_facing_waves"] = int(len(exf) - n_face)
                print("   per-receptor fetch bearing: %d of %d exposed "
                      "receptors face the incoming waves (+/-%.0f deg); "
                      "%d face water off the wave path"
                      % (n_face, len(exf), BEARING_PRIMARY, len(exf) - n_face))
        else:
            hab = {"status": "no_wave_direction"}
            print("   NO measured wave direction -- the bearing test is not "
                  "run. A guessed bearing is worse than none.")

        row["habitat_status"] = hab.get("status")
        if hab.get("full_chain_skipped_because"):
            row["full_chain_skipped_because"] = hab["full_chain_skipped_because"]
        if "bearing_ha" in hab:
            row["habitat_ha_1km_any_direction"] = hab.get("bearing_ha_no_test_1km")
            row["habitat_ha_1km_on_wave_path"] = hab.get("bearing_ha_primary_1km")
            print("   habitat within 1 km: %.2f ha any direction -> %.2f ha "
                  "on the wave path (+/-%.0f deg)"
                  % (hab.get("bearing_ha_no_test_1km") or 0.0,
                     hab.get("bearing_ha_primary_1km") or 0.0, BEARING_PRIMARY))
        if "bed_depth_m" in hab:
            d = hab["bed_depth_m"]
            row["bed_depth_median_m"] = d["median"]
            print("   bed depth (m below LAT): %.1f .. %.1f, median %.1f"
                  % (d["min"], d["max"], d["median"]))
        att = hab.get("attenuation")
        if att:
            row["H_reduction_pct"] = round(att["H_reduction"] * 100, 1)
            row["E_reduction_pct"] = round(att["E_reduction"] * 100, 1)
            row["bed_on_wave_path"] = bool(hab.get("bed_on_wave_path"))
            row["out_of_domain"] = bool(hab.get("out_of_domain"))
            print("   attenuation H %.1f %% / E %.1f %%   bed on wave path: %s"
                  "   out of domain: %s"
                  % (row["H_reduction_pct"], row["E_reduction_pct"],
                     row["bed_on_wave_path"], row["out_of_domain"]))
        else:
            print("   attenuation: not computed (%s)" % hab.get("status"))

        # ---- R5: demonstrated demand ----
        dem = demand_evidence(sub) if len(sub) else {
            "sb3_demonstrated_demand": False, "basis": "no receptors",
            "protection_structures": {}, "marine_works": {}}
        row["sb3_demonstrated_demand"] = dem["sb3_demonstrated_demand"]
        row["sb3_basis"] = dem["basis"]
        row["protection_structures"] = json.dumps(dem["protection_structures"])
        row["protection_structures_any_elevation"] = json.dumps(
            dem.get("protection_structures_any_elevation", {}))
        row["marine_works"] = json.dumps(dem["marine_works"])
        if dem["protection_structures"] or dem["marine_works"]:
            print("   coastal works present: protection %s | berth %s"
                  % (dem["protection_structures"] or "-",
                     dem["marine_works"] or "-"))

        # ---- THE EURO CELL, by the pre-registered rules ----
        n_wf = exp.get("n_water_flattened_on_gate_water", 0)
        if exp["n"] == 0 and n_wf == 0:
            row["coastal_protection_eur"] = "EUR 0 - evidenced zero"
            row["euro_reason"] = (
                "R1: no receptor of any of the %d screened classes is below "
                "5 m facing gate-passing water. The test covered roads, "
                "railways, coastal works, utilities, public assets and land "
                "parcels, not buildings alone, and could have returned "
                "non-zero." % len(ac.CLASSES))
        elif exp["n"] == 0 and n_wf:
            # An unknown elevation is not a low one -- and it is not a high
            # one either. Calling this an evidenced zero would rest the zero
            # on the DSM's inability to measure the very assets that stand in
            # the water.
            row["coastal_protection_eur"] = "not computable"
            row["euro_reason"] = (
                "R1 does not apply: no receptor is measurably below 5 m, but "
                "%d receptor(s) on gate-passing water (%s) have NO GLO-30 "
                "ground elevation at all -- every sample falls on the "
                "product's water-flattened 0.0. An unknown elevation is not a "
                "low one and not a high one, so the receptor term cannot be "
                "closed at zero here."
                % (n_wf, ", ".join(exp.get("water_flattened_classes", []))))
        else:
            row["coastal_protection_eur"] = "not computable"
            row["euro_reason"] = (
                "R2: %d receptors are exposed (%s). No published "
                "avoided-damage method fits -- all three candidates need a "
                "hazard value AT THE RECEPTOR computed with and without the "
                "habitat, and this pipeline produces a wave-height reduction "
                "OFFSHORE. A missing damage function is not a zero."
                % (exp["n"], exp["text"]))
            if hab.get("status") in ("bed_too_shallow_for_coefficient",
                                     "bed_too_deep_for_coefficient",
                                     "no_bed_in_dubi_torum_depth_range"):
                row["euro_reason"] += (" Independently, the attenuation "
                                       "coefficient cannot be applied here "
                                       "(%s)." % hab["status"])
        print("   EURO: %s" % row["coastal_protection_eur"])

        # ---- replacement cost, only where every gate allows it ----
        rc_allowed = bool(att and hab.get("bed_on_wave_path")
                          and not hab.get("out_of_domain"))
        row["replacement_cost_computed"] = False
        if rc_allowed:
            fr = {}
            if len(sub):
                pts = gpd.GeoDataFrame(
                    geometry=[Point(x, y) for x, y in
                              zip(sub.seaward_lon.astype(float),
                                  sub.seaward_lat.astype(float))
                              if np.isfinite(x) and np.isfinite(y)], crs=WGS)
                coast = coastline_for_cluster(float(c.lon), float(c.lat))
                fr = frontage_definitions((float(c.lon), float(c.lat)),
                                          pts, coast)
            row["frontage_m"] = json.dumps({k: round(v, 1)
                                            for k, v in fr.items()})
            if fr:
                e = att["E_reduction"]
                rcs = {}
                for k, m_ in fr.items():
                    r = replacement_cost(
                        frontage_m=float(m_), energy_reduction=float(e),
                        demand_condition_met=dem["sb3_demonstrated_demand"],
                        site="cluster %d" % cl)
                    rcs[k] = {"frontage_m": round(float(m_), 1),
                              "full_structure_eur": round(r.full_structure_eur),
                              "pro_rata_eur": round(r.pro_rata_eur),
                              "annualised_eur_per_yr": round(r.annualised_eur_per_yr),
                              "label": r.label}
                row["replacement_cost"] = json.dumps(rcs)
                row["replacement_cost_computed"] = True
                print("   REPLACEMENT COST (label from replacement_cost.py):")
                for k, v in rcs.items():
                    print("      %-42s %6.0f m  EUR %s/yr  [%s]"
                          % (k, v["frontage_m"], f"{v['annualised_eur_per_yr']:,}",
                             v["label"][:44]))
                print("   NOTE the pro-rata scaling by energy reduction is OUR "
                      "simplification,\n        not a published method "
                      "(CLAUDE.md rule 8).")
        else:
            reason = ("no attenuation figure" if not att else
                      "bed not on the wave path" if not hab.get("bed_on_wave_path")
                      else "out of domain")
            row["replacement_cost"] = json.dumps({"not_computed": reason})
            print("   replacement cost: not computed (%s)" % reason)

        row["opw_internal_note"] = (
            "R3: the OPW still-water extent is reported by the screen and is "
            "NOT permitted to produce a zero here. It models tide and surge "
            "without wave overtopping, and overtopping is this project's "
            "mechanism; for a coastal work at the waterline it is the wrong "
            "test, not a passed one.")
        results.append(row)

    df = pd.DataFrame(results)
    df.to_csv(OUT / "national_asset_valuation.csv", index=False)
    write_markdown_table(df, results)

    # ---------------- headline ----------------
    hr("HEADLINE")
    n_zero = int((df.coastal_protection_eur == "EUR 0 - evidenced zero").sum())
    n_nc = int((df.coastal_protection_eur == "not computable").sum())
    print("clusters analysed                     %d" % len(df))
    print("   EUR 0 -- evidenced zero            %d" % n_zero)
    print("   not computable (receptors exposed) %d" % n_nc)
    print("   a euro figure                      0")
    print("")
    print("total exposed receptors               %d" % int(df.n_exposed.sum()))
    print("   in high-completeness classes       %d"
          % int(df.n_exposed_high_completeness.sum()))
    print("")
    print("No euro leaves this run. Where a receptor is exposed the cell says")
    print("what is exposed and stops, because no published avoided-damage")
    print("method has the inputs this pipeline produces.")

    summ = {
        "run_utc": t0.isoformat(timespec="seconds"),
        "sherkin_guard": sh,
        "e1_full_chain_control": e1c,
        "damage_function_check": dfc,
        "rules": {
            "R1": "no exposed receptor of any class -> EUR 0 evidenced zero",
            "R2": "any exposed receptor -> not computable, state what is exposed",
            "R3": "OPW still-water extent may not produce a zero for a coastal "
                  "work at the waterline",
            "R4": "depth band and wave-path test unchanged and still stop the chain",
            "R5": "Shabman & Batie 3 may be satisfied by an existing coastal "
                  "PROTECTION structure, never by a pier/quay/marina",
            "R6": "zeros are results and are reported with the same weight",
        },
        "protection_structure_classes": sorted(PROTECTION_STRUCTURE_CLASSES),
        "marine_works_classes": sorted(MARINE_WORKS_CLASSES),
        "n_clusters": int(len(df)),
        "n_evidenced_zero": n_zero,
        "n_not_computable": n_nc,
        "n_with_euro_figure": 0,
        "n_exposed_receptors": int(df.n_exposed.sum()),
        "per_cluster": results,
    }
    (OUT / "national_asset_valuation_summary.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print("\nwritten: %s" % (OUT / "national_asset_valuation.csv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
