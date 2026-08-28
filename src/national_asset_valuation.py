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
from anaird_phaseb import D_VALID, reproduce_sherkin  # noqa: E402
from damage_function_check import check as damage_check  # noqa: E402
from national_phaseb import (BEARING_PRIMARY, SATURATION_STOP,  # noqa: E402
                             analyse_site, analyse_site_e1,
                             frontage_definitions)
from replacement_cost import (IE_ROCK_ARMOUR_EUR_PER_M,  # noqa: E402
                              replacement_cost)
from wide_receptor_screen import FETCH_EXCLUSION_MAX, ITM, WGS  # noqa: E402

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
    ex = rec[rec.exposed]
    if not len(ex):
        return {"n": 0, "classes": [], "text": "nothing below 5 m facing "
                                               "gate-passing water"}
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
    return {"n": int(len(ex)), "classes": rows, "text": text}


def demand_evidence(rec: pd.DataFrame) -> dict:
    """R5 -- is Shabman & Batie condition 3 satisfied at this frontage?

    An existing coastal PROTECTION structure is evidence that protection was
    demanded and built here. A pier or a marina is not: it is demand for a
    berth. The distinction is the whole point of keeping the two sets apart.
    """
    if not len(rec):
        return {"protection_structures": {}, "marine_works": {},
                "sb3_demonstrated_demand": False, "basis": "no receptors"}
    def counts(keys):
        out = {}
        for k in keys:
            m = rec.classes.astype(str).str.split(";").apply(
                lambda ks, kk=k: kk in ks)
            if int(m.sum()):
                out[k] = int(m.sum())
        return out
    prot = counts(PROTECTION_STRUCTURE_CLASSES)
    marine = counts(MARINE_WORKS_CLASSES)
    return {
        "protection_structures": prot,
        "marine_works": marine,
        "sb3_demonstrated_demand": bool(prot),
        "basis": ("an existing coastal protection structure is mapped at this "
                  "frontage (%s)" % ", ".join(prot) if prot else
                  "no coastal protection structure mapped at this frontage; "
                  "marine works present (%s) are demand for a berth, not for "
                  "shore protection" % (", ".join(marine) or "none")),
    }


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
                    hab = analyse_site_e1(c, wf, wt)
                else:
                    hab = analyse_site(c, cells_all, wf, wt)
            except Exception as exc:                          # noqa: BLE001
                hab = {"status": "chain_failed: %s" % exc}
            row["wave_from_deg"] = wf
            row["wave_to_deg"] = wt
        else:
            hab = {"status": "no_wave_direction"}
            print("   NO measured wave direction -- the bearing test is not "
                  "run. A guessed bearing is worse than none.")

        row["habitat_status"] = hab.get("status")
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
        row["marine_works"] = json.dumps(dem["marine_works"])
        if dem["protection_structures"] or dem["marine_works"]:
            print("   coastal works present: protection %s | berth %s"
                  % (dem["protection_structures"] or "-",
                     dem["marine_works"] or "-"))

        # ---- THE EURO CELL, by the pre-registered rules ----
        if exp["n"] == 0:
            row["coastal_protection_eur"] = "EUR 0 - evidenced zero"
            row["euro_reason"] = (
                "R1: no receptor of any of the %d screened classes is below "
                "5 m facing gate-passing water. The test covered roads, "
                "railways, coastal works, utilities, public assets and land "
                "parcels, not buildings alone, and could have returned "
                "non-zero." % len(ac.CLASSES))
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
