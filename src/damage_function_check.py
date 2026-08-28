#!/usr/bin/env python3
"""
damage_function_check.py -- does any published avoided-damage method fit the
non-building receptors this screen found?

WHY THIS IS A SCRIPT AND NOT A SENTENCE
---------------------------------------
The instruction for this work was explicit: where a receptor is exposed,
state what is exposed and stop before inventing a euro figure UNLESS a
published avoided-damage method fits. "It doesn't fit" is easy to assert and
easy to assert wrongly, in either direction -- and the project's own history
is of numbers that survived because nobody wrote down what they required.

So the requirement is written down. Each candidate method declares the
inputs it needs. The project declares what it actually has. The verdict is
the set difference, computed, not judged.

THE CANDIDATES, AND WHY THESE ONES
----------------------------------
1  JRC global depth-damage functions (Huizinga, de Moel & Szewczyk 2017) --
   the standard continental-scale curve set, includes an infrastructure
   class. This is what a reviewer would reach for first.
2  European road network flood damage functions (van Ginkel et al. 2021) --
   the road-specific refinement of (1), six road classes, the closest thing
   in the literature to a damage function for the receptors this screen
   actually found.
3  Expected Damage Function (EDF) approach for coastal habitat protection
   services -- the method the ecosystem-service literature uses to turn a
   habitat's wave effect into avoided damage.
4  Replacement cost (Shabman & Batie 1978 conditions) -- already
   implemented in this project at `replacement_cost.py`; included so the
   one method that CAN be evaluated here is evaluated by the same machinery
   rather than treated as a special case.

WHAT THE PROJECT HAS
--------------------
Declared once, in PROJECT_HAS, from the pipeline as it actually stands on
2026-08-28. Anything not in that set is not available, and a method needing
it does not fit. Adding an entry to PROJECT_HAS is a claim that the
pipeline produces that quantity, and should be as hard to do casually as
adding a locked figure.

REFERENCES -- verified 2026-08-28, not recalled
-----------------------------------------------
  Huizinga, J., de Moel, H., Szewczyk, W. (2017). Global flood depth-damage
      functions: Methodology and the database with guidelines. EUR 28552
      EN, JRC105688, Publications Office of the European Union.
      https://publications.jrc.ec.europa.eu/repository/bitstream/JRC105688/
      global_flood_depth-damage_functions__10042017.pdf
  van Ginkel, K. C. H., Dottori, F., Alfieri, L., Feyen, L., Koks, E. E.
      (2021). Flood risk assessment of the European road network. Natural
      Hazards and Earth System Sciences, 21, 1011-1027.
      https://doi.org/10.5194/nhess-21-1011-2021
      Checked on the article page 2026-08-28: the curves take INUNDATION
      DEPTH as the primary input; the hazard data "do not include the
      effect of pluvial and coastal flooding"; the authors "urge
      researchers to always evaluate the local situation ... and strive for
      consistency with the hazard data when choosing the most applicable
      curve"; junctions, viaducts, bridges and tunnels are omitted.
  Shabman, L. A., Batie, S. S. (1978). Economic value of natural coastal
      wetlands: a critique. Coastal Zone Management Journal 4(3), 231-247.
      -- the three conditions, already used by replacement_cost.py.
  Barbier, E. B. (2016). The protective service of mangrove ecosystems: a
      review of valuation methods. Marine Pollution Bulletin 109(2),
      676-681. -- the EDF/replacement-cost distinction this project uses.

Run:  PYTHONPATH=src python src/damage_function_check.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "asset_screen"


# ----------------------------------------------------------------------
# what the pipeline actually produces, as of 2026-08-28
# ----------------------------------------------------------------------
PROJECT_HAS = {
    "receptor_inventory":
        "OSM assets by class within 500 m of each cluster centroid",
    "receptor_ground_elevation":
        "Copernicus GLO-30 minimum along the clipped geometry (a DSM, 30 m, "
        "biased upward)",
    "offshore_wave_direction":
        "CMEMS IBI_MULTIYEAR_WAV_005_006 energy-weighted mean direction",
    "offshore_wave_height_reduction_over_bed":
        "Dubi & Torum coefficient applied over the modelled bed, 4-10 m only",
    "fetch_exposure_index":
        "Burrows log10 fetch, 200 m raster, EPSG:27700",
    "modelled_still_water_extent_internal":
        "OPW NCFHM 10/200/1000 yr, tide+surge, no waves, licence unresolved, "
        "counts only",
    "unit_replacement_rate":
        "Irish rock armour EUR 5,621/m (range 4,316-7,150), OPW-sourced",
    "coastline_geometry":
        "OSM natural=coastline",
}

# what each candidate method needs before it can produce a euro
METHODS = [
    {
        "key": "jrc_depth_damage",
        "name": "JRC global depth-damage functions (Huizinga et al. 2017)",
        "produces": "direct damage per asset for a given flood depth",
        "requires": {
            "inundation_depth_at_receptor":
                "water depth over each asset, per event or per return period",
            "asset_value_or_reconstruction_cost":
                "maximum damage value per asset class, per country",
            "with_and_without_habitat_hazard":
                "the SAME depth computed twice, with and without the habitat, "
                "because an avoided damage is a difference not a level",
        },
    },
    {
        "key": "european_road_curves",
        "name": "European road network flood damage functions "
                "(van Ginkel et al. 2021)",
        "produces": "direct damage per road segment for a given flood depth",
        "requires": {
            "inundation_depth_at_receptor":
                "water depth over each road segment",
            "asset_value_or_reconstruction_cost":
                "road reconstruction cost per km by class and country",
            "with_and_without_habitat_hazard":
                "avoided damage is a difference of two hazard states",
            "fluvial_hazard_context":
                "the published curves are calibrated on RIVER flood hazard "
                "data that explicitly exclude coastal flooding",
        },
    },
    {
        "key": "expected_damage_function",
        "name": "Expected Damage Function for coastal habitat protection",
        "produces": "annual expected avoided damage attributable to the habitat",
        "requires": {
            "hazard_at_receptor_per_return_period":
                "overtopping discharge or inundation depth at the asset, "
                "across a set of return periods",
            "with_and_without_habitat_hazard":
                "the habitat's effect expressed AT THE RECEPTOR, not offshore",
            "damage_function_per_asset_class":
                "a curve mapping that hazard to damage for each asset class",
            "asset_value_or_reconstruction_cost":
                "what the asset is worth or costs to reinstate",
        },
    },
    {
        "key": "replacement_cost",
        "name": "Replacement cost (Shabman & Batie 1978 conditions; "
                "Barbier 2016 framing)",
        "produces": "cost of the man-made structure that would deliver the "
                    "same service -- an upper bound, and only where demand "
                    "is demonstrated",
        "requires": {
            "unit_replacement_rate": "cost per metre of equivalent structure",
            "coastline_geometry": "a frontage length to multiply it by",
            "offshore_wave_height_reduction_over_bed":
                "the effect being replaced",
        },
        # Shabman & Batie's conditions are not data inputs; they are
        # admissibility tests, evaluated per site by replacement_cost.py.
        "conditions": {
            "sb1_equivalent_service":
                "the man-made alternative provides the same service",
            "sb2_least_cost":
                "it is the least-cost alternative",
            "sb3_demonstrated_demand":
                "it would in fact be demanded if the habitat were lost",
        },
    },
]


def check() -> dict:
    have = set(PROJECT_HAS)
    results = []
    for m in METHODS:
        missing = {k: v for k, v in m["requires"].items() if k not in have}
        results.append({
            "key": m["key"], "name": m["name"], "produces": m["produces"],
            "requires": list(m["requires"]),
            "missing": missing,
            "fits": len(missing) == 0,
            "conditions": m.get("conditions"),
        })
    return {
        "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_has": PROJECT_HAS,
        "methods": results,
        "any_avoided_damage_method_fits": any(
            r["fits"] and r["key"] != "replacement_cost" for r in results),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    res = check()
    lines: list = []

    def log(m: str = "") -> None:
        print(m)
        lines.append(m)

    log("=" * 78)
    log("DAMAGE-FUNCTION APPLICABILITY CHECK")
    log("=" * 78)
    log("Does any published avoided-damage method fit the non-building")
    log("receptors this screen found? Computed from declared requirements,")
    log("not asserted.")
    log("")
    log("WHAT THE PIPELINE HAS (%d quantities):" % len(PROJECT_HAS))
    for k, v in PROJECT_HAS.items():
        log("   %-42s %s" % (k, v))

    for r in res["methods"]:
        log("")
        log("-" * 78)
        log("%s" % r["name"])
        log("   produces: %s" % r["produces"])
        if r["fits"]:
            log("   VERDICT: INPUTS AVAILABLE")
        else:
            log("   VERDICT: DOES NOT FIT -- %d required input(s) missing"
                % len(r["missing"]))
            for k, v in r["missing"].items():
                log("      MISSING  %-38s %s" % (k, v))
        if r["conditions"]:
            log("   plus admissibility conditions, tested per site:")
            for k, v in r["conditions"].items():
                log("      %-12s %s" % (k, v))

    log("")
    log("=" * 78)
    log("CONCLUSION")
    log("=" * 78)
    if res["any_avoided_damage_method_fits"]:
        log("An avoided-damage method fits. Proceed -- and say which.")
    else:
        log("NO published avoided-damage method fits this pipeline's outputs.")
        log("")
        log("The blocking input is the same one in all three: a HAZARD VALUE")
        log("AT THE RECEPTOR -- an inundation depth or an overtopping")
        log("discharge over the road, the pier, the car park -- computed twice,")
        log("with and without the habitat. This project produces a wave-height")
        log("reduction OFFSHORE, over the bed. Those are different quantities")
        log("and no published curve converts one into the other.")
        log("")
        log("The road curves are additionally out of context: van Ginkel et al.")
        log("(2021) are calibrated on river flood hazard that explicitly")
        log("excludes coastal flooding, and the authors ask readers to keep")
        log("the curve consistent with the hazard data. Overtopping on an")
        log("exposed Atlantic frontage is not that hazard.")
        log("")
        log("So the honest output for an exposed non-building receptor is a")
        log("STATEMENT OF WHAT IS EXPOSED, and a stop. Not a zero -- a zero")
        log("would claim the damage is nil. 'Not computable' is the third")
        log("euro state the 28 August note locked in, and it is the right one.")

    (OUT / "damage_function_check.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "damage_function_check.log").write_text("\n".join(lines),
                                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
