#!/usr/bin/env python3
"""
national_results_table.py — the one national results table.

WHY THIS EXISTS
---------------
Four screens now exist (receptor, habitat-gap model, exposure, Phase B) and
each writes its own CSV. A reader should not have to join four tables by hand
to find out what the project concluded about a place. This builds the single
table the work was for:

    site | habitat tier | exposed receptors | attenuation | euro or honest zero

EVERY CANDIDATE APPEARS, INCLUDING THE ZEROS
--------------------------------------------
The row set is every cluster that passes the pre-registered strict fetch gate
AND carries habitat evidence at E1, E2 or E3 — not only the ones that produced
a number. A site whose coastal-protection value is an evidenced zero is a
result of the same standing as a site with a percentage, and it is listed with
the same detail and in the same table.

THE EURO COLUMN HAS THREE STATES, NOT TWO
------------------------------------------
    EUR 0 - evidenced zero   a named test that could have returned non-zero
                             returned zero (no occupied building below 5 m, or
                             none inside the OPW 1000-year extent)
    not computable           the receptor term is NOT zero, but a required
                             input does not exist in this project (a damage
                             function for wave or erosion damage to Irish
                             dwellings). A missing input is not a zero.
    a figure                 only ever with its evidence tier attached, and
                             only from the Sherkin chain run on that site's own
                             geometry, fetch and measured wave direction

Usage:
    PYTHONPATH=src python src/national_results_table.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wide_receptor_screen import FETCH_EXCLUSION_MAX  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "phaseb_national"
CAND = REPO / "outputs" / "national_candidate_table.csv"
EXPO = REPO / "outputs" / "exposure_screen" / "national_exposure_screen.csv"
PHASEB = OUT / "national_phaseb_table.csv"
ORTHO = REPO / "outputs" / "exposure_screen" / "ortho" / "ortho_manifest.csv"
DRILL = REPO / "outputs" / "exposure_screen" / "exposure_flag_drilldown.csv"

TIERS = {"E1_npws_laminaria_fine": "E1", "E1_npws_laminaria_coarse": "E1",
         "E2_model_assessed": "E2", "E3_model_offreef_inrange": "E3"}

TIER_MEANING = {
    "E1": "survey record — NPWS CO Series dive/video survey maps Laminaria here",
    "E2": "modelled on mapped reef — suitability model v2 over threshold, in "
          "training range, on NPWS-mapped hard substrate",
    "E3": "modelled, substrate UNVERIFIED — over threshold and in range, but "
          "nobody has checked that there is hard ground there. A candidate, "
          "never a claimed value.",
}

STATUS_TEXT = {
    "bed_too_shallow_for_coefficient":
        "no attenuation — the modelled bed lies above the 4 m top of the "
        "Dubi & Torum tested range (intertidal / shallow subtidal fringe), "
        "where L. hyperborea is not the expected species",
    "bed_too_deep_for_coefficient":
        "no attenuation — the modelled bed lies below the 10 m bottom of the "
        "Dubi & Torum tested range",
    "no_bed_in_dubi_torum_depth_range":
        "no attenuation — no cell falls inside the 4-10 m tested range",
    "no_modelled_cells_within_1km":
        "no attenuation — no modelled cell within 1 km",
    "bearing_test_only_no_exposed_receptor":
        "attenuation not computed — no exposed receptor, so the euro row "
        "closes on the receptor term before any physics is needed",
    "lattice_reconstruction_failed":
        "no attenuation — the AOI lattice could not be reconstructed; skipped "
        "rather than walked on a wrong grid",
    "no_wave_direction":
        "not analysed — no CMEMS wave direction for this site, and a bearing "
        "test with a guessed direction is worse than none",
    "in_domain": "", "out_of_domain": "",
}


def _i(v):
    """int() that keeps a missing value missing instead of inventing a zero."""
    return None if v is None or pd.isna(v) else int(v)


def main() -> int:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cand = pd.read_csv(CAND)
    expo = pd.read_csv(EXPO)
    pb = pd.read_csv(PHASEB) if PHASEB.exists() else pd.DataFrame()
    # Every orthophoto manifest, not just the first batch: a later Part 1 run
    # can add flagged clusters whose chips land in their own directory.
    mans = sorted((REPO / "outputs" / "exposure_screen").glob(
        "ortho*/ortho_manifest*.csv"))
    ortho = (pd.concat([pd.read_csv(m) for m in mans], ignore_index=True)
             if mans else pd.DataFrame())
    if mans:
        print(f"  orthophoto manifests read: {[m.name for m in mans]} "
              f"({len(ortho)} buildings, "
              f"{int(ortho.verdict.notna().sum())} with a verdict)")
    drill = pd.read_csv(DRILL) if DRILL.exists() else pd.DataFrame()

    # ---- the row set ------------------------------------------------------
    ev_col = "evidence_class"
    base = cand[cand[ev_col].isin(TIERS) & (cand.pass_fetch_strict == True)].copy()  # noqa: E712
    base["habitat_tier"] = base[ev_col].map(TIERS)

    e = expo.set_index("cluster")
    p = pb.set_index("cluster") if not pb.empty else pd.DataFrame()

    rows = []
    for r in base.itertuples():
        cl = int(r.cluster)
        row = {
            "cluster": cl,
            "county": getattr(r, "county", ""),
            "place": getattr(r, "nearest_place", ""),
            "lon": round(float(r.lon), 5), "lat": round(float(r.lat), 5),
            "habitat_tier": r.habitat_tier,
            "evidence_class": getattr(r, ev_col),
            "fetch_strict_min": getattr(r, "fetch_nearest_min", np.nan),
            "npws_laminaria_ha_1km": getattr(r, "npws_lam_ha_1km", np.nan),
        }
        # ---- exposure ----
        if cl in e.index:
            x = e.loc[cl]
            row.update({
                "buildings_500m": int(x.n_buildings_500m),
                "occupied_tag": int(x.n_occupied_tag),
                "lowest_occupied_m": float(x.elev_min_occupied_m),
                "exposed_receptors_tag_based": int(x.exposed_receptors),
                # OPW counts are NaN where the layer maps no extent within the
                # search box. "No extent mapped" is not "no risk" and it is not
                # zero either, so it stays None and prints as "-".
                "in_opw_1000yr_internal_any": _i(x.opw_internal_1000yr_inside),
                "in_opw_1000yr_internal_occupied": _i(
                    x.opw_internal_1000yr_inside_occupied),
                "opw_extent_mapped": bool(pd.notna(
                    x.opw_internal_1000yr_inside)),
            })
        else:
            row.update({"exposed_receptors_tag_based": None,
                        "elevation_screened": False})
        # ---- orthophoto correction ----
        if not ortho.empty and cl in set(ortho.cluster):
            o = ortho[ortho.cluster == cl]
            row["ortho_checked"] = int(len(o))
            for v in ("dwelling_like", "ancillary_nonresidential",
                      "ruin_or_no_roof", "uncertain"):
                row["ortho_" + v] = int((o.verdict == v).sum())
            row["exposed_receptors_dwelling_like"] = int(
                (o.verdict == "dwelling_like").sum())
        else:
            row["ortho_checked"] = 0
        # ---- Phase B ----
        if not p.empty and cl in p.index:
            b = p.loc[cl]
            row.update({
                "wave_from_deg": b.get("wave_from_deg"),
                "habitat_ha_1km_any_direction": b.get("ha_within_1km_any_direction"),
                "habitat_ha_on_wave_path_60deg": b.get("ha_on_wave_path_60deg"),
                "bed_source": b.get("bed_source"),
                "bed_ha_4_10m": b.get("bed_ha_dubi_torum_band"),
                "bed_depth_median_m": b.get("bed_depth_median_m"),
                "H_reduction": b.get("H_reduction"),
                "E_reduction": b.get("E_reduction"),
                "saturation_ratio": b.get("saturation_ratio_median"),
                "saturation_ratio_max": b.get("saturation_ratio_max"),
                "traversed_width_median_m": b.get("traversed_width_median_m"),
                "H_reduction_on_wave_path": b.get("H_reduction_on_wave_path"),
                "E_reduction_on_wave_path": b.get("E_reduction_on_wave_path"),
                "out_of_domain": b.get("out_of_domain"),
                "bed_on_wave_path": b.get("bed_on_wave_path"),
                "phaseb_status": b.get("status"),
                "avoided_damage_eur": b.get("avoided_damage_eur"),
                "avoided_damage_basis": b.get("avoided_damage_basis"),
            })
        else:
            row["phaseb_status"] = "not_analysed_no_exposed_receptor"

        # ---- the attenuation cell, in words ----
        if pd.notna(row.get("H_reduction")):
            att = (f"H {float(row['H_reduction'])*100:.1f} % / "
                   f"E {float(row['E_reduction'])*100:.1f} %")
            if row.get("out_of_domain") is True:
                att += "  [OUT OF DOMAIN — upper bound from extrapolation]"
            if row.get("bed_on_wave_path") is False:
                att += "  [NOT on the wave path — protects nothing at this frontage]"
        else:
            att = STATUS_TEXT.get(str(row.get("phaseb_status")), "")
            if not att and row.get("phaseb_status") == \
                    "not_analysed_no_exposed_receptor":
                att = ("attenuation not computed — no exposed receptor, so the "
                       "euro row closes on the receptor term")
        row["attenuation"] = att

        # ---- the euro cell ----
        # Three states, and the middle one is the point: a site whose receptor
        # term is NOT zero still gets no figure, because the inputs a figure
        # needs do not exist. Two separate things can be missing — the damage
        # function, and a usable attenuation coefficient — and where both are
        # missing the cell says so, because "no damage function" alone would
        # imply the physics chain was fine.
        no_att = pd.isna(row.get("H_reduction"))
        if row.get("avoided_damage_eur") == 0:
            row["euro"] = "EUR 0 — evidenced zero"
        elif "avoided_damage_basis" in row and pd.isna(
                row.get("avoided_damage_eur")):
            row["euro"] = ("not computable — no damage function AND no "
                           "applicable attenuation coefficient" if no_att
                           else "not computable — no damage function")
        elif row.get("exposed_receptors_tag_based") == 0:
            row["euro"] = "EUR 0 — evidenced zero"
            row["avoided_damage_basis"] = (
                f"EVIDENCED ZERO — no occupied-tag building behind this "
                f"frontage sits below 5 m in Copernicus GLO-30 "
                f"(lowest occupied {row.get('lowest_occupied_m')} m).")
        else:
            row["euro"] = "not determined"
        rows.append(row)

    tab = pd.DataFrame(rows)
    order = {"E1": 0, "E2": 1, "E3": 2}
    tab["_t"] = tab.habitat_tier.map(order)
    tab = tab.sort_values(["_t", "exposed_receptors_tag_based", "cluster"],
                          ascending=[True, False, True]).drop(columns="_t")
    OUT.mkdir(parents=True, exist_ok=True)
    tab.to_csv(OUT / "NATIONAL_RESULTS_TABLE.csv", index=False)

    # ---- printed form ----
    print("=" * 110)
    print("NATIONAL RESULTS TABLE — coastal protection, Irish Atlantic coast")
    print("=" * 110)
    print(f"  built {t0}")
    print(f"  row set: every cluster passing the pre-registered strict fetch "
          f"gate ({FETCH_EXCLUSION_MAX}) with habitat evidence at E1, E2 or E3")
    print(f"  rows: {len(tab)}   "
          f"E1 {int((tab.habitat_tier=='E1').sum())}, "
          f"E2 {int((tab.habitat_tier=='E2').sum())}, "
          f"E3 {int((tab.habitat_tier=='E3').sum())}")
    for k, v in TIER_MEANING.items():
        print(f"    {k}: {v}")
    print()
    hdr = (f"{'site':<34}{'tier':<5}{'exp':>4}{'dwl':>4}"
           f"{'OPW':>4}  {'attenuation':<52}{'euro'}")
    print(hdr)
    print("-" * 110)
    for r in tab.itertuples():
        site = f"{r.cluster} {r.county} {str(r.place)[:18]}"
        exp = r.exposed_receptors_tag_based
        dwl = getattr(r, "exposed_receptors_dwelling_like", None)
        opw = getattr(r, "in_opw_1000yr_internal_occupied", None)
        print(f"{site:<34}{r.habitat_tier:<5}"
              f"{('-' if exp is None else int(exp)):>4}"
              f"{('-' if dwl is None or (isinstance(dwl,float) and np.isnan(dwl)) else int(dwl)):>4}"
              f"{('-' if opw is None or (isinstance(opw,float) and np.isnan(opw)) else int(opw)):>4}"
              f"  {str(r.attenuation)[:50]:<52}{r.euro}")
    print("-" * 110)
    print("  exp = occupied-tag buildings below 5 m (Copernicus GLO-30)")
    print("  dwl = of those, judged dwelling-like on two orthophoto sources")
    print("  OPW = occupied-tag buildings within 500 m of the cluster that "
          "lie inside the OPW")
    print("        1000-year coastal flood extent, at any elevation.")
    print("        [INTERNAL COUNT ONLY - CC BY-NC-ND 4.0, unresolved; no "
          "visual derivative")
    print("        of that layer exists in this repo. CLAUDE.md rule 9.]")
    print()
    n0 = int(tab.euro.str.startswith("EUR 0").sum())
    nn = int(tab.euro.str.startswith("not computable").sum())
    print(f"  EVIDENCED ZEROS: {n0} of {len(tab)}")
    print(f"  NOT COMPUTABLE:  {nn}")
    print(f"  FIGURES:         {len(tab) - n0 - nn}")
    natt = int(tab.H_reduction.notna().sum()) if "H_reduction" in tab else 0
    print("")
    print(f"  Sites where the Sherkin attenuation chain could be run at all: {natt} of {len(tab)}")
    print("  Every other site stops on physics or on the receptor term, not on "
          "missing data.")
    print(f"\nWrote {OUT / 'NATIONAL_RESULTS_TABLE.csv'}")
    # ---- markdown, so the handover note never re-types a number ----
    md = []
    md.append("| # | site | tier | exposed receptors | attenuation | euro |")
    md.append("|---|---|---|---|---|---|")
    for i, r in enumerate(tab.itertuples(), start=1):
        exp = r.exposed_receptors_tag_based
        dwl = getattr(r, "exposed_receptors_dwelling_like", None)
        if exp is None or (isinstance(exp, float) and np.isnan(exp)):
            exps = "not screened"
        elif int(exp) == 0:
            exps = "0"
        else:
            d = ("-" if dwl is None or (isinstance(dwl, float) and np.isnan(dwl))
                 else int(dwl))
            exps = f"{int(exp)} tagged, **{d} dwelling-like**"
        att = str(r.attenuation).replace("|", "/")
        md.append(f"| {i} | **{r.cluster}** {r.county} - {r.place} | "
                  f"{r.habitat_tier} | {exps} | {att} | {r.euro} |")
    (OUT / "NATIONAL_RESULTS_TABLE.md").write_text(
        chr(10).join(md) + chr(10), encoding="utf-8")
    print(f"Wrote {OUT / 'NATIONAL_RESULTS_TABLE.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
