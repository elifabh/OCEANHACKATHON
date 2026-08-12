#!/usr/bin/env python3
"""
Step 4 - rarefaction control on the indicator score.

THE PROBLEM
-----------
indicators_found correlates with animal richness (Spearman 0.637), and the
indicator share falls as richness rises (-0.671). That pattern is what a
saturating count looks like: only 14 indicators exist regionally, so a
well-surveyed site runs out of indicators to find while its total species count
keeps climbing. It does NOT by itself prove the score is an effort artefact.

THE CONTROL
-----------
Rarefaction. Draw the same number of animal taxa from every site, count how many
are indicators, repeat many times, average. Every site is then scored at equal
sampling, so any remaining spread is not sampling.

READ THE RESULT LIKE THIS
-------------------------
  correlation collapses AND spread stays  -> real between-site signal.
                                             The score can be mapped.
  correlation collapses AND spread shrinks -> sites are indistinguishable.
                                             Report as a habitat attribute, not
                                             a map layer.
  correlation survives                     -> something else is confounded.
                                             Do not map anything yet.

The draw is from taxa recorded, not individuals, so this is sample-based
rarefaction on presence data. It controls for how much was written down. It
cannot control for what a diver chose to look for.

USAGE
  python src/rarefy_indicator.py
  python src/rarefy_indicator.py --n 15 --iters 2000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("outputs/obis_raw_occurrences.json")
LONG = Path("outputs/kelp_sites_long_faunal.csv")
MATCH = Path("outputs/indicator_match.csv")
OUT = Path("outputs/indicator_rarefied.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, help="taxa drawn per site (default: the "
                                          "smallest site's animal richness)")
    ap.add_argument("--iters", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    for p in (RAW, LONG, MATCH):
        if not p.exists():
            raise SystemExit(f"{p} not found.")

    # animal taxa only - the indicator list is faunal
    rec = json.loads(RAW.read_text(encoding="utf-8"))
    animal = {r.get("species") for r in rec if r.get("kingdom") == "Animalia"}

    long = pd.read_csv(LONG)
    long = long[long["species"].isin(animal)]

    # the observed names that count as indicators, taken straight from the
    # match file so the two scripts cannot drift apart
    m = pd.read_csv(MATCH)
    ind = set()
    for s in m.loc[m["present_in_west_cork"] == True, "matched_as"].dropna():
        ind.update(x.strip() for x in str(s).split(";"))
    print(f"{len(ind)} observed names count as indicators")

    sites = {s: g["species"].unique().tolist() for s, g in long.groupby("site_id")}
    rich = {s: len(v) for s, v in sites.items()}
    n = args.n or min(rich.values())
    print(f"{len(sites)} sites, animal richness {min(rich.values())}-"
          f"{max(rich.values())}, drawing n={n}, {args.iters} iterations")

    rng = np.random.default_rng(args.seed)
    rows = []
    for s, sp in sites.items():
        flags = np.array([x in ind for x in sp])
        draws = [flags[rng.choice(len(sp), n, replace=False)].sum()
                 for _ in range(args.iters)]
        rows.append({
            "site_id": s,
            "animal_taxa": len(sp),
            "indicators_observed": int(flags.sum()),
            "indicators_rarefied": round(float(np.mean(draws)), 2),
            "sd": round(float(np.std(draws)), 2),
        })

    t = pd.DataFrame(rows).sort_values("indicators_rarefied", ascending=False)
    t.to_csv(OUT, index=False)
    print("\n" + t.to_string(index=False))

    from scipy.stats import spearmanr
    r_raw, p_raw = spearmanr(t["animal_taxa"], t["indicators_observed"])
    r_rar, p_rar = spearmanr(t["animal_taxa"], t["indicators_rarefied"])
    v = t["indicators_rarefied"]
    print(f"\n  Spearman(richness, observed)  = {r_raw:.3f}  p = {p_raw:.3g}")
    print(f"  Spearman(richness, rarefied)  = {r_rar:.3f}  p = {p_rar:.3g}")
    print(f"  rarefied spread: {v.min():.2f} to {v.max():.2f} of {n}, "
          f"sd across sites {v.std():.2f}")
    print(f"  mean within-site sd from the draw itself: {t['sd'].mean():.2f}")
    print("\n  Between-site spread must be clearly larger than the within-site "
          "draw sd, or the differences are noise.")
    print(f"\n  written to {OUT}\n")


if __name__ == "__main__":
    main()