#!/usr/bin/env python3
"""
build_map.py - Step 6: build the interactive demonstrator map.

Reads evidence from outputs/, reprojects everything to EPSG:4326, embeds it
as JS constants into src/map_template.html and writes the self-contained
outputs/map/index.html (plus a local copy of the vendored Leaflet library,
so the map opens from disk with no network and no server).

Every displayed number is defined ONCE in LOCKED below, verbatim from
CLAUDE.md section 4. Where a locked number can be recomputed from files on
disk (bed area, 14 of 17, EPA statuses), this script recomputes it and
REFUSES TO BUILD on any mismatch - a silent drift between the map and the
locked facts is the worst failure mode this file can have.

Layers embedded:
  1. Modelled subtidal suitability (assessed cells only) + the 1.75 ha bed
  2. Intertidal macroalgae extent (Sentinel-2 tide dose-response,
     outputs/intertidal/extent_*.geojson) - species-agnostic, unvalidated,
     visually and verbally distinct from layer 1, never merged with it
     (CLAUDE.md section 4, prohibitions 3 and 5).
  3. Biodiversity dive-site points (panel carries the 14-of-17 headline)
  4. EPA WFD coastal waterbody status, clipped to the map area
  5. OPW flood layer - EXCLUDED by licence (CC BY-NC-ND, unresolved);
     the map shows a disabled toggle, nothing OPW-derived is embedded.

Run:  python src/build_map.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box as shapely_box

sys.path.insert(0, str(Path(__file__).parent))
from common import AOIS, CRS_ITM, PRIMARY_AOI  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "map"
TEMPLATE = ROOT / "src" / "map_template.html"
VENDOR_SRC = ROOT / "src" / "vendor"

CRS_WGS84 = 4326
CRS_IRISH_GRID = 29902          # EPA WFD files (TM65). See CLAUDE.md CRS traps.
GRID_M = 50.0                   # model grid; verified against model report
EPA_SIMPLIFY_M = 30.0           # simplification tolerance, applied in metres
MAX_HTML_MB = 15.0

# ---------------------------------------------------------------------------
# LOCKED facts - verbatim from CLAUDE.md section 4. Do not edit here without
# editing CLAUDE.md first. Everything the map displays comes from this dict.
# ---------------------------------------------------------------------------
LOCKED = {
    "bed_ha": 1.75,
    "wave_height_attenuation_pct": 7.9,
    "wave_energy_reduction_pct": 15.2,
    "crab_eur_yr": 290947,
    "crab_sd_low": 250349,
    "crab_sd_high": 331544,
    "lobster_eur_yr": 1051907,
    "fisheries_subtotal_label": "≈ €1.34M/yr, fisheries only",
    "avoided_damage": "€0 — evidenced zero",
    "avoided_damage_reason": "no built receptors behind this frontage",
    "replacement_rate_eur_m": 5621,
    "replacement_range": [4316, 7150],
    "biodiversity": "14 of 17",
    "indicator_total": 17,
    "indicator_present": 14,
    "model_auc": 0.830,
    "decline_sentence": (
        "No decline detected in the only official repeated assessment "
        "covering the AOI (EPA WFD, Roaring Water Bay IE_SW_140_0000; "
        "macroalgae element High in both reported cycles)."
    ),
    # The four limitations that must travel with the decline sentence
    # (docs/DEVIR_NOTU_2026-08-12_step5_decline_closed.md section 3.2).
    "decline_limitations": [
        "The macroalgae element is only reported up to the 2010–2015 "
        "cycle — two independent assessments, not a trend.",
        "It is a water-quality element (assessed in Irish coastal waters "
        "with the RSL intertidal rocky-shore species tool and/or the "
        "opportunistic green algae tool), a quality ratio — not kelp "
        "extent or biomass.",
        "The 2007–09 → 2010–12 improvement may be methodological "
        "reclassification, not genuine change.",
        "A coastal waterbody spans tens of km²; the modelled bed is "
        "1.75 ha. The assessment did not measure our bed.",
    ],
}

WATERBODY_CODE = "IE_SW_140_0000"   # Roaring Water Bay

# EPA status files: (cycle label, filename, code column, overall column,
# macroalgae column or None where the element is not published).
EPA_CYCLES = [
    ("2007–2009", "WFD_CWBStatus_20072009.geojson",
     "EU_CD", "EcoStatus_Pot", "MacroalgaeStatus_Pot"),
    ("2010–2012", "WFD_CWBStatus_20102012.geojson",
     "EU_CD", "EcoStatus_Pot", "MacroalgaeStatus_Pot"),
    ("2010–2015", "WFD_CWBStatus_20102015.geojson",
     "European_Code", "Status", "Macroalgae_Status"),
    ("2013–2018", "WFD_CWBStatus_20132018.geojson",
     "European_Code", "Status", None),
    ("2016–2021", "WFD_CWBStatus_20162021.geojson",
     "European_Code", "Status", None),
    ("2019–2024", "WFD_CWBStatus_20192024.geojson",
     "European_Code", "Status", None),
]


def fail(msg: str) -> None:
    sys.exit(f"BUILD REFUSED: {msg}")


def round_geojson_coords(obj, ndigits=5):
    """Round every coordinate in a GeoJSON-like structure. ~1 m at 5 dp."""
    if isinstance(obj, dict):
        return {k: round_geojson_coords(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_geojson_coords(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits)
    return obj


def gdf_to_geojson(gdf: gpd.GeoDataFrame, ndigits=5) -> dict:
    gj = json.loads(gdf.to_json(drop_id=True))
    return round_geojson_coords(gj, ndigits)


# ---------------------------------------------------------------------------
# Layer 1a - the 1.75 ha bed: 7 x 50 m model cells (points in EPSG:2157,
# squared up in ITM so each cell is exactly 50 m x 50 m on the ground).
# ---------------------------------------------------------------------------
def build_bed() -> dict:
    kc = gpd.read_file(
        ROOT / "outputs" / "valuation" / "step3b2_flood_check.gpkg",
        layer="kelp_cells",
    )
    if len(kc) != 7:
        fail(f"kelp_cells: expected 7 cells, found {len(kc)}")
    if kc.crs.to_epsg() != CRS_ITM:
        fail(f"kelp_cells CRS is {kc.crs}, expected EPSG:{CRS_ITM}")
    squares = kc.geometry.buffer(GRID_M / 2, cap_style="square")
    area_ha = float(squares.area.sum()) / 10_000.0
    if abs(area_ha - LOCKED["bed_ha"]) > 1e-6:
        fail(f"bed area recomputed {area_ha} ha != locked {LOCKED['bed_ha']} ha")
    bed = gpd.GeoDataFrame(
        {
            "depth_m": kc["depth_m"].round(1),
            "cluster": kc["group"],
        },
        geometry=squares,
        crs=kc.crs,
    ).to_crs(CRS_WGS84)
    print(f"  bed: 7 cells, {area_ha:.4f} ha (matches locked {LOCKED['bed_ha']})")
    return gdf_to_geojson(bed, ndigits=6)


# ---------------------------------------------------------------------------
# Layer 1b - suitability grid, assessed cells only. Cells with
# in_training_range = 0 are extrapolation and are excluded (model report
# caveat: they must not enter any area or euro figure - and the map shows
# only what the model can defend).
# ---------------------------------------------------------------------------
def build_suitability() -> dict:
    sp = pd.read_csv(ROOT / "outputs" / "model" / "suitability_multisite_predictions.csv")
    rep = json.loads((ROOT / "outputs" / "model" / "model_multisite_report.json").read_text())
    if rep["grid_m"] != GRID_M:
        fail(f"model grid {rep['grid_m']} != {GRID_M}")
    auc = round(rep["auc"]["leave_one_site_out"], 3)
    if abs(auc - LOCKED["model_auc"]) > 1e-9:
        fail(f"LOSO AUC {auc} != locked {LOCKED['model_auc']}")
    sub = sp[(sp["aoi"] == PRIMARY_AOI) & (sp["assessed"] == 1)]
    if not ((sub["suitability"] >= 0) & (sub["suitability"] <= 1)).all():
        fail("suitability outside [0,1]")
    cells = [
        [round(r.lon, 5), round(r.lat, 5), round(r.suitability, 3)]
        for r in sub.itertuples()
    ]
    print(f"  suitability: {len(cells)} assessed cells (of {len(sp[sp.aoi == PRIMARY_AOI])} in AOI)")
    return {
        "grid_m": GRID_M,
        "auc_loso": auc,
        "threshold": rep["acceptance"]["extras"]["operating_threshold"],
        "n_total_in_aoi": int(len(sp[sp.aoi == PRIMARY_AOI])),
        "cells": cells,
    }


# ---------------------------------------------------------------------------
# Layer 2 - intertidal macroalgae extent (Sentinel-2). Read from the export
# produced by src/intertidal_extent_export.py, which itself refuses to write
# unless the intertidal_test.py verdict was "detected" and areas agree. This
# function re-verifies both on every build: the map must not outlive its
# evidence. The displayed area is UNVALIDATED and is labelled so in the
# template; it is not a locked fact and is never used in any valuation.
# ---------------------------------------------------------------------------
def build_intertidal() -> dict:
    inter_dir = ROOT / "outputs" / "intertidal"
    extent_path = inter_dir / f"extent_{PRIMARY_AOI}_7scenes.geojson"
    if not extent_path.exists():
        fail(f"{extent_path} missing - run src/intertidal_test.py then "
             f"src/intertidal_extent_export.py (no placeholder data)")
    gj = json.loads(extent_path.read_text(encoding="utf-8"))
    meta = gj["properties"]

    report = json.loads((inter_dir / meta["source_report"])
                        .read_text(encoding="utf-8"))
    if report["outcome"] != "detected":
        fail(f"intertidal report outcome '{report['outcome']}' != 'detected'")
    if abs(meta["area_ha"] - report["area_ha"]["intertidal"]) > 0.5:
        fail("intertidal extent area disagrees with its source report")

    feats = gpd.GeoDataFrame.from_features(gj["features"], crs=CRS_WGS84)
    area_ha = float(feats.to_crs(CRS_ITM).area.sum()) / 10_000.0
    if abs(area_ha - meta["area_ha"]) > 0.02 * meta["area_ha"]:
        fail(f"intertidal geometry recomputes to {area_ha:.2f} ha, "
             f"metadata says {meta['area_ha']} ha")

    years = sorted({s[:4] for s in meta["scenes"]})
    if len(years) != 1:
        fail(f"intertidal scenes span years {years}; caption assumes one")
    print(f"  intertidal: {len(gj['features'])} polygons, "
          f"{area_ha:.2f} ha re-verified vs report "
          f"{report['area_ha']['intertidal']:.1f} ha; year {years[0]}")
    return {
        "extent": {"type": "FeatureCollection",
                   "features": round_geojson_coords(gj["features"], 6)},
        "area_ha": round(area_ha, 1),
        "n_scenes": len(meta["scenes"]),
        "year": years[0],
        "tide_range_m": round(meta["tide_range_m"], 2),
    }


# ---------------------------------------------------------------------------
# Layer 4 - EPA WFD waterbodies around the map area, with per-cycle status.
# Source CRS EPSG:29902 (TM65) - the CRS trap in CLAUDE.md. Geometry is
# simplified in the projected CRS (metres), then reprojected.
# ---------------------------------------------------------------------------
def build_epa() -> dict:
    epa_dir = ROOT / "outputs" / "epa_cwb"
    wb = gpd.read_file(epa_dir / "WFD_COASTALWATERBODIES_CYCLE3.geojson")
    if wb.crs.to_epsg() != CRS_IRISH_GRID:
        fail(f"EPA waterbodies CRS {wb.crs} != EPSG:{CRS_IRISH_GRID}")

    lon_min, lat_min, lon_max, lat_max = AOIS[PRIMARY_AOI]
    pad = 0.25  # degrees of context around the AOI
    box = gpd.GeoSeries(
        [shapely_box(lon_min - pad, lat_min - pad, lon_max + pad, lat_max + pad)],
        crs=CRS_WGS84,
    ).to_crs(wb.crs).iloc[0]
    sel = wb[wb.geometry.intersects(box)].copy()
    if WATERBODY_CODE not in set(sel["EU_CD"]):
        fail(f"{WATERBODY_CODE} not in selected EPA waterbodies")

    status: dict[str, dict] = {code: {} for code in sel["EU_CD"]}
    for label, fname, codecol, overallcol, macrocol in EPA_CYCLES:
        g = gpd.read_file(epa_dir / fname, ignore_geometry=True)
        for _, row in g.iterrows():
            code = str(row[codecol])
            if code in status:
                entry = {"overall": row[overallcol]}
                if macrocol is not None and pd.notna(row.get(macrocol)):
                    entry["macroalgae"] = row[macrocol]
                status[code][label] = entry

    # Refuse to build if the files contradict the locked decline sentence.
    rw = status[WATERBODY_CODE]
    macro = [c["macroalgae"] for c in rw.values() if "macroalgae" in c]
    if not macro or set(macro) != {"High"}:
        fail(f"Roaring Water Bay macroalgae element not uniformly High: {macro}")
    if rw["2007–2009"]["overall"] != "Moderate":
        fail("2007-2009 overall status expected Moderate")
    later = [rw[lab]["overall"] for lab, *_ in
             [c for c in EPA_CYCLES if c[0] != "2007–2009"]]
    if set(later) != {"Good"}:
        fail(f"2010-2024 overall statuses expected all Good, got {later}")

    sel["geometry"] = sel.geometry.simplify(EPA_SIMPLIFY_M)
    sel = sel.to_crs(CRS_WGS84)
    out = gpd.GeoDataFrame(
        {"code": sel["EU_CD"], "name": sel["NAME"]},
        geometry=sel.geometry, crs=CRS_WGS84,
    )
    gj = gdf_to_geojson(out, ndigits=5)
    for feat in gj["features"]:
        feat["properties"]["status"] = status[feat["properties"]["code"]]
    print(f"  epa: {len(gj['features'])} waterbodies; Roaring Water Bay statuses verified")
    return gj


# ---------------------------------------------------------------------------
# Layer 3 - biodiversity dive-site points (context for the 14-of-17 panel).
# The 14-of-17 headline itself is recomputed from indicator_match.csv and
# checked against LOCKED; per-site counts come from indicator_site_scores.csv.
# ---------------------------------------------------------------------------
def build_biodiversity() -> dict:
    m = pd.read_csv(ROOT / "outputs" / "indicator_match.csv")
    n_total = len(m)
    n_present = int(m["present_in_west_cork"].sum())
    if (n_total, n_present) != (LOCKED["indicator_total"], LOCKED["indicator_present"]):
        fail(f"indicator recount {n_present} of {n_total} != locked "
             f"{LOCKED['biodiversity']}")

    s = pd.read_csv(ROOT / "outputs" / "indicator_site_scores.csv")
    sites = []
    for r in s.itertuples():
        lat_s, lon_s = str(r.site).split("_")
        sites.append({
            "lat": round(float(lat_s), 5),
            "lon": round(float(lon_s), 5),
            "records": int(r.records_at_site),
            "species": int(r.species_at_site),
            "indicators": int(r.indicators_found),
        })
    print(f"  biodiversity: locked {LOCKED['biodiversity']} re-verified; "
          f"{len(sites)} dive sites")
    return {"present": n_present, "total": n_total, "sites": sites}


# ---------------------------------------------------------------------------
# Layer 6 - RESTORATION PRIORITY (2026-08-28). Built by
# src/restoration_priority.py. Only class R1 is rendered here: R2 lies in the
# national gap AOIs, hundreds of kilometres off this map, and drawing nothing
# for it is more honest than drawing it somewhere it is not.
#
# The layer's external false-positive rate travels with it. A restoration
# layer whose FPR is not on its face is a recommendation pretending to be a
# map, so the build REFUSES if that number stops being a failure.
# ---------------------------------------------------------------------------
def build_restoration() -> dict:
    d = ROOT / "outputs" / "restoration"
    gj_path = d / "restoration_candidates.geojson"
    sm_path = d / "restoration_summary.json"
    if not gj_path.exists() or not sm_path.exists():
        fail(f"{gj_path.name} / {sm_path.name} missing - run "
             f"src/restoration_priority.py (no placeholder data)")
    summary = json.loads(sm_path.read_text(encoding="utf-8"))
    g = gpd.read_file(gj_path)

    bbox = shapely_box(*AOIS[PRIMARY_AOI])
    r1 = g[(g.restoration_class == "R1") & g.geometry.intersects(bbox)].copy()
    area_ha = float(r1.to_crs(CRS_ITM).area.sum()) / 10_000.0
    expect = len(r1) * (GRID_M * GRID_M) / 1e4
    if abs(area_ha - expect) > 0.01:
        fail(f"restoration R1 area {area_ha:.3f} ha != {expect:.3f} ha "
             f"expected from {len(r1)} cells of {GRID_M:.0f} m")

    fpr = summary["external_false_positive_rate"]
    if fpr["passes"]:
        fail("the model's external FPR now PASSES its acceptance criterion; "
             "the restoration caption says it fails. Re-read the model report "
             "before shipping either.")
    if not summary["euro"].startswith("NONE"):
        fail("restoration layer has acquired a euro value; it must not have one")

    print(f"  restoration: R1 {len(r1)} cells = {area_ha:.2f} ha on this map; "
          f"R2 {summary['classes']['R2']['cells']} cells off-map; "
          f"external FPR {fpr['value']:.1%} (criterion "
          f"{fpr['threshold_max']:.0%}, FAILED)")
    return {
        "r1": gdf_to_geojson(r1[["restoration_class", "rank_in_class",
                                 "suitability", "geometry"]]),
        "r1_cells": int(len(r1)),
        "r1_ha": round(area_ha, 2),
        "r2_cells": int(summary["classes"]["R2"]["cells"]),
        "r2_ha": summary["classes"]["R2"]["ha"],
        "label": summary["layer_label"],
        "fpr_pct": round(fpr["value"] * 100, 1),
        "fpr_criterion_pct": round(fpr["threshold_max"] * 100, 0),
        "fpr_n": fpr["n"],
    }


# ---------------------------------------------------------------------------
# Layer 7 - QUALITATIVE COASTAL EXPOSURE INDEX (2026-08-28). Built by
# src/coastal_exposure_index.py: InVEST's documented method, implemented
# directly. ORDINAL. It is rendered on the map and kept away from every euro
# frame, and the build refuses if it has acquired a monetary interpretation.
# ---------------------------------------------------------------------------
def build_exposure() -> dict:
    d = ROOT / "outputs" / "exposure_index"
    gj_path = d / f"exposure_index_{PRIMARY_AOI}.geojson"
    sm_path = d / f"exposure_index_{PRIMARY_AOI}_summary.json"
    if not gj_path.exists() or not sm_path.exists():
        fail("exposure index missing - run src/coastal_exposure_index.py")
    s = json.loads(sm_path.read_text(encoding="utf-8"))
    if s.get("monetary") is not False or not s["euro"].startswith("NONE"):
        fail("exposure index has acquired a monetary interpretation")
    g = gpd.read_file(gj_path)
    keep = ["EI", "EI_no_habitat", "EI_habitat_reduction",
            "exposure_quintile", "kelp_within_2km", "geometry"]
    g = g[[c for c in keep if c in g.columns]].copy()
    for c in ("EI", "EI_no_habitat", "EI_habitat_reduction"):
        if c in g.columns:
            g[c] = g[c].round(3)
    print(f"  exposure index: {len(g)} shore points, EI "
          f"{s['EI']['min']}-{s['EI']['max']}, "
          f"{len(s['variables_used'])} variables, habitat lowers EI by "
          f"median {s['habitat']['median_EI_reduction']}")
    return {
        "points": gdf_to_geojson(g, ndigits=5),
        "label": s["layer_label"],
        "n_points": int(len(g)),
        "ei_min": s["EI"]["min"], "ei_median": s["EI"]["median"],
        "ei_max": s["EI"]["max"],
        "variables_used": s["variables_used"],
        "variables_omitted": list(s["variables_omitted"]),
        "habitat_median_reduction": s["habitat"]["median_EI_reduction"],
        "habitat_points": s["habitat"]["points_with_kelp"],
        "invest_ran": s["invest"]["ran_invest_itself"],
        "invest_licence": s["invest"]["licence"],
        "invest_install": s["invest"]["install"],
        "wind_note": s["wind"], "wave_note": s["wave"],
    }


# ---------------------------------------------------------------------------
# FRAME 4 - NUTRIENT REMOVAL (2026-08-28). Built by src/nutrient_removal.py,
# which verifies its own inputs against their primary sources and returns a
# BAND. The band is RE-DERIVED here from the mass and the prices rather than
# read as a headline: a headline nobody recomputes is a headline nobody is
# checking.
# ---------------------------------------------------------------------------
def build_nutrient() -> dict:
    p = ROOT / "outputs" / "valuation" / "nutrient_removal.json"
    if not p.exists():
        fail("nutrient_removal.json missing - run src/nutrient_removal.py")
    d = json.loads(p.read_text(encoding="utf-8"))
    if not d["verification"]["all_passed"]:
        fail("nutrient_removal.py's own verification did not pass")
    row = d["row"]
    if abs(row["bed_ha"] - LOCKED["bed_ha"]) > 1e-9:
        fail(f"nutrient row uses {row['bed_ha']} ha, locked bed is "
             f"{LOCKED['bed_ha']} ha")
    for k, price in row["price_eur_per_kg"].items():
        want = round(row["n_kg_total_yr"] * price)
        if abs(row["band_eur_per_yr"][k] - want) > 1:
            fail(f"nutrient band {k}: stored {row['band_eur_per_yr'][k]} != "
                 f"recomputed {want}")
    if row["demand_condition_met"]:
        fail("nutrient row asserts demonstrated demand; it must not")
    if "NOT a benefit transfer" not in row["label"]:
        fail("nutrient row has lost its 'NOT a benefit transfer' label")
    print(f"  nutrient: {row['n_kg_total_yr']:,.0f} kg N/yr over "
          f"{row['bed_ha']} ha -> EUR "
          f"{row['band_eur_per_yr']['engineering_floor']:,}-"
          f"{row['band_eur_per_yr']['societal_high']:,}/yr (band re-derived)")
    return {
        "n_kg_per_ha_yr": row["n_kg_per_ha_yr"],
        "n_kg_total_yr": row["n_kg_total_yr"],
        "band": row["band_eur_per_yr"],
        "prices": row["price_eur_per_kg"],
        "label": row["label"],
        "caveats": list(row["caveats"]),
        "eger_implied_usd_per_kg": d["eger_implicit_price"]["implied_usd_per_kg_n"],
        "eger_vs_floor_x": d["eger_implicit_price"]["vs_engineering_floor_x"],
        "eger_vs_ceiling_x": d["eger_implicit_price"]["vs_societal_high_x"],
    }


# ---------------------------------------------------------------------------
# TRANSFER TEST - the Iroise Sea run (2026-08-28). NOT a layer on the Irish
# map and NOT an Irish euro. It is the evidence that the engine transfers,
# which is the challenge's own requirement, and it is presented in its own
# section with its own site name attached to every figure.
# ---------------------------------------------------------------------------
def build_france() -> dict:
    cp = ROOT / "outputs" / "france" / "france_chain.json"
    vp = ROOT / "outputs" / "france" / "france_valuation.json"
    if not cp.exists() or not vp.exists():
        fail("France chain/valuation JSON missing - run src/france_chain.py "
             "then src/france_valuation.py")
    c = json.loads(cp.read_text(encoding="utf-8"))
    v = json.loads(vp.read_text(encoding="utf-8"))

    if not c["sherkin_control"]["reproduces_locked_figures"]:
        fail("the France run's Sherkin control did not reproduce 7.9/15.2")
    dom = c["coefficient_domain"]
    if not dom["all_inside"]:
        fail("France run used a coefficient outside 4-10 m")
    if v["avoided_damage"]["euro"] is not None:
        fail("France avoided-damage row has acquired a euro; the "
             "damage-function check says no published method fits")

    rc = v.get("replacement_cost", {})
    central = [r for r in rc.get("rows", [])
               if r["rate_band"] == "central"
               and r["coefficient_spelling"] == "published_bins"]
    if not central:
        fail("no central replacement-cost row in the France valuation")
    central = central[0]
    if "ILLUSTRATIVE UPPER BOUND" not in central["label"]:
        fail("France replacement-cost row is not labelled an illustrative "
             "upper bound")

    unsat = c.get("attenuation_unsaturated_only")
    if not unsat:
        fail("France run has no unsaturated-subset figure; the headline "
             "attenuation must not travel without its conservative end")
    print(f"  France: {dom['n_inside_4_10m']:,}/{dom['n_cells']:,} cells in "
          f"4-10 m; E {c['attenuation']['published_bins']['E_reduction']:.1%} "
          f"(unsaturated subset "
          f"{unsat['published_bins']['E_reduction']:.1%}); "
          f"frontage {rc['frontage_m_priced']:,.0f} m; "
          f"annualised EUR {central['annualised_eur_per_yr']:,}/yr")
    return {
        "site": c["site"]["name"],
        "town": c["site"]["receptor_town"],
        "lon": c["site"]["receptor_lon"], "lat": c["site"]["receptor_lat"],
        "habitat_ha": c["habitat"]["ha_at_threshold"],
        "inband_ha": c["depth_gate"]["LAT"]["ha"],
        "cells_in_band": dom["n_cells"],
        "cells_inside_domain": dom["n_inside_4_10m"],
        "wave_from_deg": c["wave"]["from_deg"],
        "wave_crosscheck": c.get("wave_crosscheck", {}),
        "H_bins": c["attenuation"]["published_bins"]["H_reduction"],
        "E_bins": c["attenuation"]["published_bins"]["E_reduction"],
        "H_fit": c["attenuation"]["fitted_curve"]["H_reduction"],
        "E_fit": c["attenuation"]["fitted_curve"]["E_reduction"],
        "unsaturated": unsat,
        "mork": c["mork_crosscheck"],
        "saturation": c["saturation"],
        "receptors": c["receptors"],
        "defence_class": c.get("defence_class_check", {}),
        "frontage_priced_m": rc.get("frontage_m_priced"),
        "frontage_context_m": rc.get("frontage_m_habitat_only_context"),
        "c3_met": v["shabman_batie"]["met"],
        "avoided_damage_verdict": v["avoided_damage"]["verdict"],
        "rc_central": central,
        "rc_rows": rc.get("rows", []),
        "cross_country": rc.get("cross_country_warning"),
        "settled": v["what_this_settled"],
        "licence_note": "Kelp layer: EMODnet Seabed Habitats macroalgae EOV "
                        "2025, CC BY 4.0. The Ifremer/Sextant Molene dataset "
                        "the brief named is CC BY-NC-ND and is NOT used.",
    }


# ---------------------------------------------------------------------------
# Assemble, inject, self-check, write.
# ---------------------------------------------------------------------------
def main() -> None:
    print("build_map.py")
    payload = {
        "build_date": date.today().isoformat(),
        "aoi": {"name": "Roaringwater Bay / Sherkin Island",
                "bbox": AOIS[PRIMARY_AOI]},
        "locked": LOCKED,
        "bed": build_bed(),
        "suitability": build_suitability(),
        "epa": build_epa(),
        "biodiversity": build_biodiversity(),
        "intertidal": build_intertidal(),
        "restoration": build_restoration(),
        "exposure": build_exposure(),
        "nutrient": build_nutrient(),
        "france": build_france(),
        "opw_note": (
            "OPW national coastal flood extents: licence CC BY-NC-ND 4.0, "
            "clearance pending — layer withheld."
        ),
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    token = "/*__MAP_DATA__*/null"
    if token not in template:
        fail(f"template token {token} missing from {TEMPLATE}")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = template.replace(token, data_js)

    # Self-checks on the final artefact: retired/forbidden figures must not
    # appear anywhere in what a juror could see (CLAUDE.md section 4).
    for forbidden in ("9.8 ha", "42.7", "67.2", "82%"):
        if forbidden in html:
            fail(f"forbidden figure {forbidden!r} found in output HTML")
    for required in ("14 of 17", "a tool, not a prediction",
                     "counterfactual illustration", "species-agnostic",
                     "unvalidated",
                     # added 2026-08-28 with the four new deliverables. Each
                     # phrase is the one thing that stops its own layer or row
                     # from being read as something stronger than it is.
                     "not a management recommendation",
                     "qualitative relative exposure index",
                     "not a monetary value",
                     "NOT a benefit transfer",
                     # Case matters: the ALL-CAPS form travels inside the
                     # embedded JSON whether or not the panel renders it, so
                     # a case-insensitive check would pass on data the reader
                     # never sees. This is the visible label.
                     "Illustrative upper bound"):
        if required not in html:
            fail(f"required phrase {required!r} missing from output HTML")

    # A grand total across service types is the one thing the three-frame
    # layout exists to prevent, and a fourth frame is a fourth chance to add
    # one by accident. The check is on the artefact, not on intent.
    for banned in ("Grand total", "GRAND TOTAL", "Total value",
                   "grand total"):
        if banned in html:
            fail(f"{banned!r} appears in the output HTML; rows are never "
                 f"summed across service types")

    # The France euro must never be able to read as an Irish one.
    if "France" not in html or "Le Conquet" not in html:
        fail("the transfer-test section has lost its site name; a French "
             "euro with no site name beside it is an Irish euro to a reader")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "index.html"
    out_file.write_text(html, encoding="utf-8")

    vendor_dst = OUT_DIR / "vendor"
    shutil.copytree(VENDOR_SRC, vendor_dst, dirs_exist_ok=True)

    size_mb = out_file.stat().st_size / 1e6
    if size_mb > MAX_HTML_MB:
        fail(f"index.html is {size_mb:.1f} MB > {MAX_HTML_MB} MB budget")
    print(f"  wrote {out_file} ({size_mb:.2f} MB) + vendor/")
    print("OK")


if __name__ == "__main__":
    main()
