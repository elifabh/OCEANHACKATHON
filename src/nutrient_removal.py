#!/usr/bin/env python3
"""
nutrient_removal.py -- the nitrogen-removal row, as OUR OWN synthesis.

WHY THIS ROW WAS OMITTED BEFORE, AND WHAT CHANGED
--------------------------------------------------
CLAUDE.md section 6 offered a nutrient-cycling row on one condition: verify a
genus-specific NITROGEN-ONLY value in Eger et al. 2023 and prefer it, because
the carbon component is contested in this project. The 2026-08-17 session
checked the full text and all 14 supplementary datasets and found none. The
paper publishes a combined C+N+P figure for Laminaria/Saccharina
($113,681/ha/yr) and an all-genera nitrogen mean ($73,831/ha/yr), and neither
is a genus-specific nitrogen euro. The row was omitted, correctly.

What changed is the question. There is still no genus-specific nitrogen EURO
to transfer -- and this module does not invent one. What Eger et al. do
publish, genus-specifically, is a nitrogen MASS, and a mass multiplied by an
independently sourced European price is a transparent synthesis whose two
halves a reviewer can check separately. That is a different and weaker claim
than a benefit transfer, and it is labelled as such everywhere it appears.

    THIS IS NOT A BENEFIT TRANSFER OF A PUBLISHED EURO FIGURE.
    It is our own replacement-cost synthesis: Eger's published nitrogen mass
    x an external, separately verified European nitrogen price.

THE TWO HALVES, EACH VERIFIED AT ITS OWN PRIMARY SOURCE
--------------------------------------------------------
MASS  Eger, A. M., Marzinelli, E. M., Beas-Luna, R. et al. (2023). The value
      of ecosystem services in global marine kelp forests. Nature
      Communications 14:1894. https://doi.org/10.1038/s41467-023-37385-0
      Verified 2026-08-28 in the full text (PMC10113392), Results:
          "The average grams of nitrogen removed per m2 per year were
           41 (Ecklonia), 124 (Laminaria/Saccharina), 88 (Lessonia),
           81 (Macrocystis), and 86 (Nereocystis)."
      124 g N/m2/yr = 1,240 kg N/ha/yr for Laminaria/Saccharina.
      Their method: "average elemental composition of each genus as reported
      in the literature to convert region specific NPP into the average
      amount of carbon, nitrogen, and phosphorus absorbed from the water each
      year." So the mass is NPP x tissue N content, not a measured flux.

PRICE (floor)  US EPA (2007). Wastewater Technology Fact Sheet: Side Stream
      Nutrient Removal. EPA 832-F-07-017, Office of Water, September 2007.
      Verified 2026-08-28 on page 5, section COSTS, verbatim:
          "The SHARON process has been compared with other techniques for
           nitrogen removal from reject water and was found to be the least
           expensive under Dutch circumstances. A cost estimate of
           1.5 Euro/kg N_removed (approximately $2/kg N_removed) was given."
      Cited there to STOWA (Dutch Foundation for Applied Water Research),
      2006, SHARON and SHARON/ANAMOX Process Sheets.

PRICE (ceiling)  Brink, C., van Grinsven, H. et al. (2011). Costs and
      benefits of nitrogen in the environment. Chapter 22 in The European
      Nitrogen Assessment, Cambridge University Press.
      Verified 2026-08-28 on page 513, Executive summary, Key findings:
          "Health costs from secondary ammonium particles (2-20 euro/kg N),
           from GHG balance effects of N2O (5-15 euro/kg N), from ecosystem
           impacts via N-runoff (5-20 euro/kg N) and by N-deposition
           (2-10 euro/kg N) are intermediate."
      The N-runoff band, 5-20 euro/kg N, is the one used.

A BAND, NOT A POINT ESTIMATE
----------------------------
The brief asked for a band and the sources make that the only honest form.
The floor and the ceiling answer different questions -- what it costs an
engineer to strip a kilo of nitrogen out of a concentrated reject stream,
versus what a kilo of nitrogen running off into an ecosystem costs society --
and they are three to thirteen times apart. Collapsing them to a mean would
manufacture a precision neither source supports.

THE CROSS-CHECK THAT JUSTIFIES NOT USING EGER'S OWN EURO
---------------------------------------------------------
Eger et al.'s global nitrogen figure pairs $73,831/ha/yr with 620 kg N/ha/yr.
Dividing gives an implicit price of about $119/kg N -- roughly six times our
societal ceiling and eighty times the engineering floor. That is computed in
`eger_implicit_price()` and reported, because it is the strongest available
evidence that transferring their dollar figure into a European context would
have imported a price no European source supports.

THE LIMITATION THAT WEAKENS THIS ROW MOST
------------------------------------------
Replacement cost requires the man-made alternative to be a LEAST-COST
SUBSTITUTE for the same service (Shabman & Batie 1978, condition 2). A
wastewater plant removes nitrogen from the system permanently, as N2 gas. A
kelp forest mostly does not: it assimilates nitrogen into tissue, and the
great majority of that tissue is EXPORTED as detritus to adjacent and deep
habitats, where much of it is remineralised and the nitrogen returns to the
water. Only the buried or genuinely exported-beyond-the-boundary fraction is
"removed" in the sense a treatment plant means. So the two services are not
equivalent, condition 2 is only partly met, and the figures here are an upper
bound on an upper bound. This is stated on the map, not only here.

Run:  python src/nutrient_removal.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "valuation"

# --------------------------------------------------------------- the inputs
# Eger et al. 2023, Nat Commun 14:1894 -- genus-specific nitrogen MASS.
EGER_N_G_PER_M2_YR = {
    "Ecklonia": 41.0,
    "Laminaria/Saccharina": 124.0,
    "Lessonia": 88.0,
    "Macrocystis": 81.0,
    "Nereocystis": 86.0,
}
GENUS = "Laminaria/Saccharina"        # the Sherkin bed is L. hyperborea
N_KG_PER_HA_YR = EGER_N_G_PER_M2_YR[GENUS] * 10.0   # 124 g/m2 -> 1240 kg/ha

# Eger et al.'s own global (all-genera) pairing, used ONLY for the
# implicit-price cross-check, never as a value.
EGER_GLOBAL_N_USD_PER_HA_YR = 73_831.0
EGER_GLOBAL_N_KG_PER_HA_YR = 620.0

# European nitrogen prices, each verified at its own primary source.
N_PRICE_EUR_PER_KG = {
    "engineering_floor": {
        "value": 1.5,
        "label": "SHARON/ANAMMOX side-stream treatment, least-cost under "
                 "Dutch circumstances",
        "source": "US EPA (2007) Wastewater Technology Fact Sheet: Side "
                  "Stream Nutrient Removal, EPA 832-F-07-017, p.5, COSTS; "
                  "citing STOWA 2006",
        "price_base": "2006/2007 euro, not indexed",
        "what_it_answers": "what it costs an engineer to strip a kilo of "
                           "nitrogen out of a CONCENTRATED reject stream -- "
                           "the cheapest place in the whole system to do it",
    },
    "societal_low": {
        "value": 5.0,
        "label": "ecosystem impacts via N-runoff, lower bound",
        "source": "Brink & van Grinsven et al. (2011), European Nitrogen "
                  "Assessment ch.22, p.513, Executive summary",
        "price_base": "2011 publication, price base not stated in the "
                      "summary; not indexed",
        "what_it_answers": "what a kilo of nitrogen running off into an "
                           "ecosystem costs society",
    },
    "societal_high": {
        "value": 20.0,
        "label": "ecosystem impacts via N-runoff, upper bound",
        "source": "Brink & van Grinsven et al. (2011), European Nitrogen "
                  "Assessment ch.22, p.513, Executive summary",
        "price_base": "2011 publication, price base not stated in the "
                      "summary; not indexed",
        "what_it_answers": "as above, upper end of the published range",
    },
}

# The locked Sherkin bed. Never recomputed here.
SHERKIN_BED_HA = 1.75

LABEL = ("OUR OWN TRANSPARENT REPLACEMENT-COST SYNTHESIS -- Eger et al. "
         "(2023) published nitrogen MASS x an external European nitrogen "
         "price. NOT a benefit transfer of a published euro figure.")

CAVEATS = (
    "NOT a benefit transfer. Eger et al. publish no genus-specific "
    "nitrogen-only euro value; this row multiplies their published MASS by a "
    "separately sourced European PRICE, and both halves are checkable "
    "independently.",
    "Replacement cost OVERESTIMATES value (Barbier 2016). Secondary method "
    "only, and this project's primary method is expected avoided damage.",
    "Shabman & Batie (1978) condition 2 (least-cost substitute) is only "
    "PARTLY met: a treatment plant removes nitrogen permanently as N2 gas, "
    "whereas kelp assimilates it into tissue that is largely EXPORTED as "
    "detritus and substantially remineralised. The two services are not "
    "equivalent and this is the row's largest weakness.",
    "Shabman & Batie condition 3 (demonstrated demand) is NOT asserted here. "
    "No evidence has been gathered that Ireland would build nitrogen-removal "
    "capacity if this 1.75 ha bed were lost.",
    "The mass is NPP x literature tissue composition (Eger et al.'s own "
    "method), a modelled global genus mean, not a flux measured at Sherkin.",
    "The floor and the ceiling answer different questions and are 3-13x "
    "apart. The band is the result; a mean of it would be a fabrication.",
    "No price is inflation-indexed. The floor is a 2006/2007 euro and the "
    "ceiling a 2011 publication. Indexing without a stated deflator would "
    "manufacture false precision, so it is not done.",
    "NEVER sum this row with the fisheries rows or with any other service: "
    "different methods, different questions, uncorrected overlap.",
)


@dataclass
class NutrientRow:
    bed_ha: float
    genus: str
    n_kg_per_ha_yr: float
    n_kg_total_yr: float
    band_eur_per_yr: dict
    price_eur_per_kg: dict
    label: str
    demand_condition_met: bool
    caveats: tuple


def eger_implicit_price() -> dict:
    """What price per kg N is implied by Eger et al.'s own dollar figure?

    Their global nitrogen row pairs $73,831/ha/yr with 620 kg N/ha/yr. The
    quotient is the price their valuation rests on, and comparing it with the
    European anchors is the clearest evidence that transferring their dollar
    figure would import a price no European source supports.
    """
    implied = EGER_GLOBAL_N_USD_PER_HA_YR / EGER_GLOBAL_N_KG_PER_HA_YR
    return {
        "eger_global_n_usd_per_ha_yr": EGER_GLOBAL_N_USD_PER_HA_YR,
        "eger_global_n_kg_per_ha_yr": EGER_GLOBAL_N_KG_PER_HA_YR,
        "implied_usd_per_kg_n": round(implied, 1),
        "vs_engineering_floor_x": round(implied / N_PRICE_EUR_PER_KG
                                        ["engineering_floor"]["value"], 1),
        "vs_societal_high_x": round(implied / N_PRICE_EUR_PER_KG
                                    ["societal_high"]["value"], 1),
        "note": "USD and EUR are NOT converted -- the point is the order of "
                "magnitude, and a conversion would imply a precision the "
                "comparison does not have. Eger et al.'s implicit price is "
                "roughly 80x the engineering floor and 6x the societal "
                "ceiling. That gap is why their euro figure is not "
                "transferred.",
    }


def nutrient_row(bed_ha: float = SHERKIN_BED_HA,
                 demand_condition_met: bool = False) -> NutrientRow:
    n_total = N_KG_PER_HA_YR * bed_ha
    band = {k: round(n_total * v["value"]) for k, v in N_PRICE_EUR_PER_KG.items()}
    return NutrientRow(
        bed_ha=bed_ha,
        genus=GENUS,
        n_kg_per_ha_yr=N_KG_PER_HA_YR,
        n_kg_total_yr=round(n_total, 1),
        band_eur_per_yr=band,
        price_eur_per_kg={k: v["value"] for k, v in N_PRICE_EUR_PER_KG.items()},
        label=LABEL,
        demand_condition_met=demand_condition_met,
        caveats=CAVEATS,
    )


def verify() -> dict:
    """Assert every number this module publishes against its stated source.

    A figure that cannot fail a check is not a verified figure.
    """
    checks = []

    def chk(name: str, ok: bool, detail: str):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    chk("eger genus mass is 124 g N/m2/yr",
        EGER_N_G_PER_M2_YR[GENUS] == 124.0,
        "Eger et al. 2023, Results, verbatim: '124 (Laminaria/Saccharina)'")
    chk("124 g/m2/yr converts to 1240 kg/ha/yr",
        abs(N_KG_PER_HA_YR - 1240.0) < 1e-9,
        "124 g/m2 x 10,000 m2/ha / 1,000 g/kg = 1,240 kg/ha")
    chk("engineering floor is 1.5 EUR/kg N",
        N_PRICE_EUR_PER_KG["engineering_floor"]["value"] == 1.5,
        "EPA 832-F-07-017 p.5: '1.5 Euro/kg N_removed'")
    chk("societal band is 5-20 EUR/kg N",
        (N_PRICE_EUR_PER_KG["societal_low"]["value"] == 5.0
         and N_PRICE_EUR_PER_KG["societal_high"]["value"] == 20.0),
        "ENA ch.22 p.513: 'ecosystem impacts via N-runoff (5-20 euro/kg N)'")
    chk("bed area is the locked 1.75 ha",
        SHERKIN_BED_HA == 1.75, "CLAUDE.md section 4")
    row = nutrient_row()
    chk("band is ordered floor < low < high",
        row.band_eur_per_yr["engineering_floor"]
        < row.band_eur_per_yr["societal_low"]
        < row.band_eur_per_yr["societal_high"],
        str(row.band_eur_per_yr))
    chk("no retired figure appears",
        all(str(x) not in json.dumps(asdict(row))
            for x in ("9.8", "42.7", "67.2", "82%")),
        "CLAUDE.md section 4 retired figures")
    chk("row is labelled as a synthesis, not a benefit transfer",
        "NOT a benefit transfer" in row.label,
        row.label[:60])
    chk("demand condition is not asserted",
        row.demand_condition_met is False,
        "Shabman & Batie condition 3 is not claimed for this row")
    return {"checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "all_passed": all(c["passed"] for c in checks),
            "checks": checks}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    row = nutrient_row()
    ver = verify()
    imp = eger_implicit_price()

    print("=" * 78)
    print("NITROGEN REMOVAL -- our own synthesis, not a benefit transfer")
    print("=" * 78)
    print(f"bed                 {row.bed_ha} ha (locked, CLAUDE.md section 4)")
    print(f"genus               {row.genus}")
    print(f"nitrogen mass       {row.n_kg_per_ha_yr:,.0f} kg N/ha/yr "
          f"(Eger et al. 2023: 124 g N/m2/yr)")
    print(f"total nitrogen      {row.n_kg_total_yr:,.1f} kg N/yr over the bed")
    print()
    print("BAND -- each end answers a different question, and that is why it "
          "is a band")
    for k, v in N_PRICE_EUR_PER_KG.items():
        print(f"  {k:20s} EUR {v['value']:>5.1f}/kg N  ->  "
              f"EUR {row.band_eur_per_yr[k]:>9,.0f}/yr")
        print(f"  {'':20s} {v['what_it_answers']}")
        print(f"  {'':20s} source: {v['source'][:70]}")
    print()
    print(f"  headline band: EUR {row.band_eur_per_yr['engineering_floor']:,.0f}"
          f" - {row.band_eur_per_yr['societal_high']:,.0f} / yr")
    print()
    print("CROSS-CHECK -- what price does Eger et al.'s own dollar figure imply?")
    print(f"  ${imp['eger_global_n_usd_per_ha_yr']:,.0f}/ha/yr over "
          f"{imp['eger_global_n_kg_per_ha_yr']:,.0f} kg N/ha/yr "
          f"= ${imp['implied_usd_per_kg_n']:,.1f}/kg N")
    print(f"  that is {imp['vs_engineering_floor_x']:,.0f}x the engineering "
          f"floor and {imp['vs_societal_high_x']:,.0f}x the societal ceiling")
    print(f"  -> transferring their euro would import a price no European "
          f"source supports")
    print()
    print("CAVEATS -- all of them travel with the row")
    for c in row.caveats:
        print(f"  * {c}")
    print()
    print("VERIFICATION")
    for c in ver["checks"]:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['check']}")
    print(f"  ALL PASSED: {ver['all_passed']}")

    payload = {"row": asdict(row), "verification": ver,
               "eger_implicit_price": imp,
               "sources": {"mass": "Eger et al. 2023, Nat Commun 14:1894, "
                                   "doi 10.1038/s41467-023-37385-0",
                           "price_floor": N_PRICE_EUR_PER_KG
                           ["engineering_floor"]["source"],
                           "price_ceiling": N_PRICE_EUR_PER_KG
                           ["societal_high"]["source"]}}
    p = OUT / "nutrient_removal.json"
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    print(f"\nwritten: {p}")
    return 0 if ver["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
