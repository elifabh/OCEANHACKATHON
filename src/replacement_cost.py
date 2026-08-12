"""
replacement_cost.py — illustrative upper-bound replacement-cost row.

STATUS OF THIS METHOD
---------------------
Replacement cost is the project's SECONDARY valuation method. The primary
method is expected avoided damage. Barbier (2016) and the wider literature
find that replacement cost tends to OVERESTIMATE the value of the service.
Every figure produced here must be labelled "illustrative upper bound".

Shabman & Batie (1978), as restated in NRC (2005, 2012), give three
conditions under which replacement cost is a valid proxy for value:

    C1  an engineered solution provides an EQUIVALENT service;
    C2  that solution is the LEAST-COST alternative;
    C3  there is substantial evidence the service WOULD BE DEMANDED by
        society if supplied by that alternative.

This module REFUSES to label its output a "value" unless the caller asserts
C3 explicitly. At sherkin_baltimore C3 fails: the avoided-damage row closed
at an evidenced EUR 0 because there are no built receptors behind the
frontage. The same fact cannot close row 1 at zero and license row 2 as a
value. Output there is a COUNTERFACTUAL ILLUSTRATION, not a valuation.

C1 also warrants care. Kelp attenuates wave energy in the nearshore, before
the wave reaches the shore. That is the stated function of a nearshore /
low-crested breakwater. A revetment armours the shoreline itself. Both unit
rates are therefore carried; `structure` selects which.

The pro-rata scaling by energy_reduction is OUR SIMPLIFICATION, not a
published method. You cannot build 15.2% of a breakwater; marine structures
have minimum viable dimensions and high fixed mobilisation costs. Linear
pro-rata is reported alongside the full-structure cost so the reader can see
both bounds.

Unit-cost provenance: outputs/replacement_cost_unit_rates.csv
Discount rate: 4% real, Ireland's official test discount rate
(DPENDR, Infrastructure Guidelines: Central Technical References and
Economic Appraisal Parameters, which superseded the Public Spending Code).
"""

from dataclasses import dataclass, asdict
from typing import Optional

# ---------------------------------------------------------------- constants

# Pooled Irish rate: three OPW tranches at Seaview (Bastardstown), Co. Wexford,
# 2024-2026. EUR 1,826,794 over 325 m. SINGLE SITE. Soft eroding Celtic Sea
# coast, not exposed Atlantic hard rock. See CSV for the individual tranches.
IE_ROCK_ARMOUR_EUR_PER_M = {"low": 4315.6, "central": 5620.9, "high": 7150.5}

# OPW funds "up to 90%" of scheme cost, so approved funding is a LOWER BOUND
# on the true cost. Applying this factor gives the implied full scheme cost
# if the 90% ceiling was reached.
OPW_FUNDING_CEILING = 0.90

# Environment Agency (2015) SC080039/R7, Table 1.2, 2007 GBP price base.
# Carried for the functionally-correct structure. NOT inflation-adjusted and
# NOT currency-converted here: doing either without an explicit, stated index
# would manufacture false precision. Convert deliberately or not at all.
UK_NEARSHORE_BREAKWATER_GBP_PER_M_2007 = {"low": 1750.0, "high": 4300.0}

IE_DISCOUNT_RATE = 0.04  # real, DPENDR Infrastructure Guidelines
DESIGN_LIFE_YEARS = {"low": 30, "central": 50}  # EA (2015) s.1.8.2 / s.1.8.3


def capital_recovery_factor(rate: float, years: int) -> float:
    """Annual equivalent of one unit of capital over `years` at `rate`."""
    return rate / (1.0 - (1.0 + rate) ** -years)


@dataclass
class ReplacementCostResult:
    frontage_m: float
    energy_reduction: float
    unit_cost_eur_per_m: float
    full_structure_eur: float
    pro_rata_eur: float
    annualised_eur_per_yr: float
    design_life_years: int
    discount_rate: float
    label: str
    demand_condition_met: bool
    caveats: tuple


def replacement_cost(
    frontage_m: float,
    energy_reduction: float,
    unit_cost_eur_per_m: float = IE_ROCK_ARMOUR_EUR_PER_M["central"],
    design_life_years: int = DESIGN_LIFE_YEARS["central"],
    discount_rate: float = IE_DISCOUNT_RATE,
    demand_condition_met: bool = False,
    apply_opw_funding_ceiling: bool = False,
    site: Optional[str] = None,
) -> ReplacementCostResult:
    """
    Parameters
    ----------
    frontage_m
        ALONGSHORE length of coast the bed fronts, in metres. This is NOT the
        bed area. Derive it from src/bed_width_axes.py. Area alone cannot
        produce a EUR/m figure.
    energy_reduction
        Fractional wave-energy reduction attributable to the bed, e.g. 0.152.
        Subtidal L. hyperborea only (Dubi & Torum 1996; Mork 1996;
        Lovas & Torum 2001). Never apply to the intertidal layer.
    demand_condition_met
        Assert True ONLY where there is evidence the protection service would
        actually be demanded, i.e. a built receptor exists behind the
        frontage. False -> output is labelled a counterfactual illustration.
    apply_opw_funding_ceiling
        Divide the unit rate by 0.90 to recover the implied full scheme cost
        from an OPW approved-funding figure.
    """
    if not 0.0 <= energy_reduction <= 1.0:
        raise ValueError("energy_reduction must be a fraction in [0, 1]")
    if frontage_m <= 0:
        raise ValueError("frontage_m must be > 0 (alongshore metres, not area)")

    rate = unit_cost_eur_per_m
    if apply_opw_funding_ceiling:
        rate = rate / OPW_FUNDING_CEILING

    full = frontage_m * rate
    pro_rata = full * energy_reduction
    annual = pro_rata * capital_recovery_factor(discount_rate, design_life_years)

    if demand_condition_met:
        label = "ILLUSTRATIVE UPPER BOUND (replacement cost; Barbier 2016)"
    else:
        label = (
            "COUNTERFACTUAL ILLUSTRATION - NOT A VALUE. "
            "Shabman & Batie (1978) condition 3 (demonstrated demand) not met."
        )

    caveats = (
        "Replacement cost overestimates value (Barbier 2016). Secondary method only.",
        "Unit rate from a SINGLE Irish site (Seaview, Co. Wexford), soft eroding "
        "Celtic Sea coast. West Cork is exposed Atlantic hard rock: larger design "
        "wave, larger armour, so this rate probably UNDERSTATES local cost.",
        "Unit rate is OPW APPROVED FUNDING, not tendered or out-turn cost.",
        "Pro-rata scaling by energy_reduction is our simplification, not a "
        "published method. Structures cannot be built at fractional scale.",
        "A revetment armours the shoreline; kelp attenuates energy in the "
        "nearshore. The functionally equivalent structure is a nearshore / "
        "low-crested breakwater. Shabman & Batie condition 1 is only partly met.",
        "Capital EUR and annualised EUR/yr are different quantities. Never place "
        "a one-off capital figure beside the annual fisheries rows as if comparable.",
        "NEVER sum this row with the fisheries rows: different methods, different "
        "questions, uncorrected overlap.",
    )

    return ReplacementCostResult(
        frontage_m=frontage_m,
        energy_reduction=energy_reduction,
        unit_cost_eur_per_m=round(rate, 1),
        full_structure_eur=round(full),
        pro_rata_eur=round(pro_rata),
        annualised_eur_per_yr=round(annual),
        design_life_years=design_life_years,
        discount_rate=discount_rate,
        label=label,
        demand_condition_met=demand_condition_met,
        caveats=caveats,
    )


def sherkin_sensitivity(bed_area_ha: float = 1.75, energy_reduction: float = 0.152):
    """
    Sherkin frontage is NOT YET MEASURED. Until src/bed_width_axes.py supplies
    the alongshore length, frontage is inferred from area / cross-shore width.
    Every row below is a counterfactual illustration, not a value.
    """
    area_m2 = bed_area_ha * 10_000
    rows = []
    for cross_shore_w in (50, 100, 150, 200):
        L = area_m2 / cross_shore_w
        for band, rate in IE_ROCK_ARMOUR_EUR_PER_M.items():
            r = replacement_cost(
                frontage_m=L,
                energy_reduction=energy_reduction,
                unit_cost_eur_per_m=rate,
                demand_condition_met=False,
                site="sherkin_baltimore",
            )
            rows.append({"cross_shore_w_m": cross_shore_w, "band": band, **asdict(r)})
    return rows


if __name__ == "__main__":
    import csv
    import sys

    rows = sherkin_sensitivity()
    w = csv.DictWriter(
        sys.stdout,
        fieldnames=[
            "cross_shore_w_m", "band", "frontage_m", "unit_cost_eur_per_m",
            "full_structure_eur", "pro_rata_eur", "annualised_eur_per_yr",
        ],
        extrasaction="ignore",
    )
    w.writeheader()
    for row in rows:
        row["frontage_m"] = round(row["frontage_m"], 1)
        w.writerow(row)
    print(
        "\nCOUNTERFACTUAL ILLUSTRATION ONLY - Shabman & Batie condition 3 "
        "is not met at sherkin_baltimore.",
        file=sys.stderr,
    )
