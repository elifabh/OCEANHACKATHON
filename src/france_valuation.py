#!/usr/bin/env python3
"""
france_valuation.py -- the euro question at Le Conquet, asked in the project's
own method hierarchy and answered honestly.

THE HIERARCHY IS NOT NEGOTIABLE
-------------------------------
  1  AVOIDED DAMAGE is the primary method. If it can be computed, it is the
     answer and replacement cost is not shown as a value beside it.
  2  REPLACEMENT COST is secondary, an illustrative upper bound, and only
     where Shabman & Batie (1978) condition 3 -- demonstrated demand -- holds.
     Barbier (2016) finds it tends to OVERESTIMATE. Where condition 3 fails
     it is a counterfactual illustration and not a value at all.

That hierarchy is what closed the Sherkin coastal-protection row at
"EUR 0 -- evidenced zero" and refused to let the EUR 5,621/m rate stand as a
value beside it. It is applied here unchanged.

WHAT THIS SITE ACTUALLY CHANGED, AND WHAT IT DID NOT
-----------------------------------------------------
The site was chosen because the Irish chain stopped at a depth constraint.
That constraint is now satisfied: 12,544 of 12,544 cells entering the
attenuation sum are inside Dubi & Torum's 4-10 m range, for the first time
anywhere in this project, and the resulting energy reduction lands inside
Mork's published 70-85 % envelope.

It did not change the euro. `damage_function_check` runs the same test here
as in Ireland and returns the same verdict, because the missing input is not
a property of Ireland: it is a HAZARD VALUE AT THE RECEPTOR, computed twice,
with and without the habitat. This pipeline produces a wave-height reduction
OFFSHORE, over the bed. No published curve converts one into the other.

    The depth constraint was the FIRST blocker at the Irish sites. Removing
    it revealed that it was never the ONLY one.

That is the honest headline and it is worth more than a euro would have been,
because it identifies exactly what a follow-on project must build: a
nearshore wave-transformation model between the bed and the shoreline.

CONDITION 3 IS MET HERE, AND THAT IS GENUINELY NEW
---------------------------------------------------
At Sherkin, condition 3 failed on a fact: there are no built receptors behind
the frontage, which is also why the avoided-damage row is an evidenced zero
rather than a blank. The same fact cannot close row 1 at zero and license
row 2 as a value.

Le Conquet is the opposite case, and the receptor screen measured it rather
than asserting it: buildings, quays, a working port and a ferry terminal sit
below 5 m within 200 m of the BD TOPO land-sea limit, and a subset of them
have valid-band kelp on the measured wave path within 2 km. So condition 3 is
met by this project's own stated test.

Conditions 1 and 2 are still only PARTLY met, and that does not change:
  C1  a revetment armours the shoreline; kelp attenuates energy in the
      nearshore. The functionally equivalent structure is a nearshore or
      low-crested breakwater, which is why both unit rates are carried.
  C2  least-cost is not demonstrated. No alternatives appraisal exists.

THE UNIT RATE PROBLEM, STATED RATHER THAN SOLVED
-------------------------------------------------
This project has verified exactly two unit rates and neither is French:

  * EUR 5,621/m (range 4,316-7,150), Irish rock armour, OPW approved funding,
    three tranches at ONE site (Seaview, Co. Wexford), soft eroding Celtic
    Sea coast.
  * GBP 1,750-4,300/m at a 2007 price base, UK nearshore breakwater,
    Environment Agency (2015) SC080039/R7 Table 1.2. Functionally the closer
    structure. NOT currency-converted and NOT indexed, because doing either
    without a stated index would manufacture false precision.

Applying an Irish rate on a French coast is a cross-country transfer and it
is labelled as one on every figure. A French rate exists -- CEREMA, "Cout des
protections contre les aleas littoraux", which covers perres, murs, epis,
brise-lames and butees -- but its unit costs are inside the publication and
were not reachable from the CEREMA website in this session. Inventing a
French number, or half-sourcing one from a builders' price aggregator, would
be worse than transferring a rate whose provenance is fully documented. So
the transfer is made, flagged, and the CEREMA guide is left as a named
one-step task rather than a vague "find French costs".

Run:  PYTHONPATH=src python src/france_valuation.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import replacement_cost as RC                       # noqa: E402
import damage_function_check as DFC                 # noqa: E402

OUT = REPO / "outputs" / "france"
CHAIN = OUT / "france_chain.json"

# The CEREMA guide, named so the task is one step rather than a search.
CEREMA = {
    "title": "Cout des protections contre les aleas littoraux",
    "publisher": "Cerema",
    "covers": "perres, murs et ouvrages de soutenement, epis, brise-lames, "
              "butees -- investment, maintenance and management costs",
    "page": "https://www.cerema.fr/fr/centre-ressources/boutique/"
            "cout-protections-contre-aleas-littoraux",
    "status": "unit costs are inside the publication; not reachable from the "
              "public page in this session",
    "why_it_matters": "it would replace the cross-country transfer of the "
                      "Irish OPW rate with a French rate for French "
                      "structures, which is the single largest remaining "
                      "weakness in the replacement-cost row at this site",
}


def load_chain() -> dict:
    if not CHAIN.exists():
        raise SystemExit(f"{CHAIN} not found -- run src/france_chain.py first")
    return json.loads(CHAIN.read_text(encoding="utf-8"))


def condition3(chain: dict) -> dict:
    """Shabman & Batie condition 3, decided from the receptor screen.

    The project's own test, from replacement_cost.py: assert True ONLY where
    there is evidence the protection service would actually be demanded, i.e.
    a built receptor exists behind the frontage.
    """
    r = chain.get("receptors") or {}
    n_low = int(r.get("below_5m", 0))
    n_shelt = int(r.get("below_5m_with_inband_habitat_2km", 0))
    met = n_shelt > 0
    return {
        "condition": "Shabman & Batie (1978) C3 -- demonstrated demand",
        "test": "a built receptor exists behind the frontage, below 5 m, with "
                "valid-coefficient habitat on the measured wave path",
        "receptors_below_5m": n_low,
        "of_those_with_inband_habitat_on_wave_path_within_2km": n_shelt,
        "met": bool(met),
        "contrast_with_sherkin":
            "At Sherkin this test returns zero -- no built receptors behind "
            "the frontage at all -- which is why the avoided-damage row is an "
            "evidenced zero AND why the EUR 5,621/m rate is labelled a "
            "counterfactual illustration there. Here the same test returns "
            f"{n_shelt}, so the label changes. The TEST did not change.",
        "still_only_partly_met": {
            "C1_equivalent_service": "PARTLY. A revetment armours the "
                                     "shoreline; kelp attenuates energy in "
                                     "the nearshore. The equivalent structure "
                                     "is a nearshore / low-crested breakwater.",
            "C2_least_cost": "NOT DEMONSTRATED. No alternatives appraisal "
                             "exists for this frontage.",
        },
    }


def main() -> int:
    chain = load_chain()
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "site": chain["site"]["name"]}

    def hr(t):
        print("\n" + "=" * 78)
        print(t)
        print("=" * 78)

    hr("STEP 1 (PRIMARY) -- AVOIDED DAMAGE")
    dfc = DFC.check()
    for m in dfc["methods"]:
        if m["key"] == "replacement_cost":
            continue
        print(f"  {m['name']}")
        if m["fits"]:
            print("     VERDICT: INPUTS AVAILABLE")
        else:
            print(f"     VERDICT: DOES NOT FIT -- {len(m['missing'])} missing")
            for k in m["missing"]:
                print(f"        MISSING  {k}")
    fits = dfc["any_avoided_damage_method_fits"]
    print()
    if fits:
        print("  An avoided-damage method fits. It is the answer, and "
              "replacement cost is NOT shown as a value beside it.")
    else:
        print("  NO published avoided-damage method fits -- the SAME verdict")
        print("  as at every Irish site, and for the same missing quantity:")
        print("  a hazard value AT THE RECEPTOR, with and without the")
        print("  habitat. This pipeline produces a wave-height reduction")
        print("  OFFSHORE, over the bed. Satisfying the depth constraint did")
        print("  not supply a damage function, and could not have.")
    res["avoided_damage"] = {
        "any_method_fits": bool(fits),
        "euro": None,
        "verdict": ("computable" if fits else
                    "NOT COMPUTABLE -- no published method's inputs are "
                    "produced by this pipeline"),
        "blocking_input": "hazard value at the receptor (inundation depth or "
                          "overtopping discharge), computed with and without "
                          "the habitat",
        "what_would_unblock_it": "a nearshore wave-transformation model "
                                 "between the bed and the shoreline, plus a "
                                 "damage curve for the receptor classes found",
    }

    hr("STEP 2 (SECONDARY) -- REPLACEMENT COST, ADMISSIBILITY FIRST")
    c3 = condition3(chain)
    print(f"  test: {c3['test']}")
    print(f"  receptors below 5 m: {c3['receptors_below_5m']:,}")
    print(f"  of those with valid-band habitat on the wave path within 2 km: "
          f"{c3['of_those_with_inband_habitat_on_wave_path_within_2km']:,}")
    print(f"  C3 (demonstrated demand): "
          f"{'MET' if c3['met'] else 'NOT MET'}")
    for k, v in c3["still_only_partly_met"].items():
        print(f"  {k}: {v}")
    res["shabman_batie"] = c3

    front = chain.get("frontage") or {}
    # Only the receptor-restricted frontage may be priced. The habitat-only
    # figure is the whole archipelago and is carried as context.
    L = float(front.get("with_receptor_m") or 0.0)
    L_context = float(front.get("habitat_only_m") or 0.0)
    E_bin = float(chain["attenuation"]["published_bins"]["E_reduction"])
    E_fit = float(chain["attenuation"]["fitted_curve"]["E_reduction"])
    print("\n  measured alongshore frontage")
    print(f"     habitat only  {L_context:>9,.0f} m  -- the whole "
          f"archipelago.")
    print("        CONTEXT ONLY, never priced. Nobody would armour every "
          "islet in the")
    print("        Iroise, and pricing this length would produce a "
          "billion-euro headline")
    print("        for a structure that exists as no one's proposal.")
    print(f"     WITH receptor {L:>9,.0f} m  -- the priced one.")
    print("        Shabman & Batie condition 3 licenses replacement cost "
          "exactly where a")
    print("        built receptor is. Pricing more than that prices frontage "
          "the method")
    print("        does not license.")
    print(f"  energy reduction: {E_bin:.1%} (published bins) / "
          f"{E_fit:.1%} (fitted curve)")

    if L <= 0:
        print("\n  No frontage measured -- replacement cost is not computed.")
        res["replacement_cost"] = {"status": "no frontage measured"}
    else:
        rows = []
        for band, rate in RC.IE_ROCK_ARMOUR_EUR_PER_M.items():
            for ename, E in (("published_bins", E_bin), ("fitted_curve", E_fit)):
                r = RC.replacement_cost(
                    frontage_m=L, energy_reduction=E,
                    unit_cost_eur_per_m=rate,
                    demand_condition_met=c3["met"],
                    site="le_conquet_iroise")
                rows.append({"rate_band": band, "coefficient_spelling": ename,
                             **asdict(r)})
        print("\n  Irish OPW rock-armour rate, TRANSFERRED ACROSS BORDERS "
              "(flagged, not hidden):")
        print(f"     {'band':8s} {'spelling':16s} {'EUR/m':>8s} "
              f"{'full structure':>16s} {'pro-rata':>14s} {'annualised':>14s}")
        for r in rows:
            print(f"     {r['rate_band']:8s} {r['coefficient_spelling']:16s} "
                  f"{r['unit_cost_eur_per_m']:>8,.0f} "
                  f"{r['full_structure_eur']:>16,.0f} "
                  f"{r['pro_rata_eur']:>14,.0f} "
                  f"{r['annualised_eur_per_yr']:>14,.0f}")
        print(f"\n     label on every row above:")
        print(f"     {rows[0]['label']}")
        res["replacement_cost"] = {
            "frontage_m_priced": L,
            "frontage_m_habitat_only_context": L_context,
            "frontage_method": front.get("method"),
            "why_the_shorter_one_is_priced":
                "The habitat-only frontage is the whole archipelago's "
                "shoreline. Replacement cost is admissible only where "
                "Shabman & Batie condition 3 holds, and condition 3 IS the "
                "presence of a built receptor. Pricing frontage the condition "
                "does not cover would be pricing frontage the method does not "
                "license -- and would produce a headline an order of "
                "magnitude too large.",
            "rows": rows,
            "unit_rate_provenance": "Irish OPW approved funding, three "
                                    "tranches at ONE site (Seaview, Co. "
                                    "Wexford), soft eroding Celtic Sea coast",
            "cross_country_transfer": True,
            "cross_country_warning":
                "This is an IRISH rate applied on a FRENCH coast. The Iroise "
                "is exposed Atlantic hard rock with a larger design wave than "
                "Seaview, so the rate probably UNDERSTATES local cost. It is "
                "used because it is the only unit rate this project has "
                "verified at source; see cerema_task.",
            "functionally_closer_structure": {
                "rate": RC.UK_NEARSHORE_BREAKWATER_GBP_PER_M_2007,
                "source": "Environment Agency (2015) SC080039/R7, Table 1.2",
                "currency": "GBP, 2007 price base",
                "not_converted": "deliberately. Converting or indexing "
                                 "without a stated index would manufacture "
                                 "false precision.",
            },
            "pro_rata_is_our_simplification":
                "Scaling structure cost by the energy reduction is OUR "
                "simplification, not a published method (CLAUDE.md rule 8). "
                "Marine structures have minimum viable dimensions and high "
                "fixed mobilisation costs; you cannot build 76 % of a "
                "breakwater. Full-structure cost is reported beside it so "
                "both bounds are visible.",
            "capital_vs_annual":
                "full_structure_eur and pro_rata_eur are ONE-OFF CAPITAL. "
                "annualised_eur_per_yr is an annual equivalent at 4 % over "
                "50 years. Never place a capital figure beside the annual "
                "fisheries rows as if comparable.",
            "cerema_task": CEREMA,
        }

    hr("WHAT THIS SITE SETTLED, AND WHAT IT DID NOT")
    dom = chain.get("coefficient_domain", {})
    att = chain["attenuation"]["published_bins"]
    mork = chain.get("mork_crosscheck", {})
    print(f"  SETTLED: the coefficient domain. {dom.get('n_inside_4_10m',0):,} "
          f"of {dom.get('n_cells',0):,} cells inside 4-10 m -- the first time "
          f"anywhere in this project.")
    print(f"  SETTLED: an attenuation figure that survives its own "
          f"cross-check. E = {att['E_reduction']:.1%}, and Mork's published "
          f"envelope is {mork.get('mork_envelope')}: "
          f"{'INSIDE' if mork.get('inside') else 'OUTSIDE'}.")
    print(f"  NOT SETTLED: the euro. Avoided damage is still not computable, "
          f"for a reason that has nothing to do with depth.")
    print(f"  NOT SETTLED: whether the percentage is a measurement. The "
          f"saturation ratio's p90 is "
          f"{chain.get('saturation',{}).get('ratio_p90')}, so the upper decile "
          f"of cells is running an exponential fitted over a few flume metres "
          f"out to saturation.")
    res["what_this_settled"] = {
        "coefficient_domain_satisfied": bool(dom.get("all_inside")),
        "mork_crosscheck_inside": bool(mork.get("inside")),
        "euro_obtained": False,
        "saturation_p90": chain.get("saturation", {}).get("ratio_p90"),
    }

    p = OUT / "france_valuation.json"
    p.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")
    print(f"\nwritten: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
