#!/usr/bin/env python3
"""
Step 4 - separate dive surveys from shore/algal surveys.

WHY
---
Site 51.497817_-9.619775 recorded 38 taxa and zero of the 17 faunal indicators.
Inspection showed all 38 were algae, including high-shore fucoids (Pelvetia
canaliculata, Fucus spiralis). That is an intertidal shore transect, not a dive.

A survey that never records animals cannot score on a faunal indicator list.
Including such sites makes the score look like habitat variation when it is
survey method. They must be identified and excluded before anything is mapped.

Kingdom comes from the OBIS records already on disk - no new API calls.

USAGE
  python src/survey_type_split.py
  python src/survey_type_split.py --min-animal-pct 20 --write
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

RAW = Path("outputs/obis_raw_occurrences.json")
LONG = Path("outputs/kelp_sites_long.csv")
OUT = Path("outputs/kelp_sites_long_faunal.csv")
KELP = "laminaria hyperborea"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-animal-pct", type=float, default=20.0,
                    help="a site is a dive survey if at least this %% of its "
                         "taxa are animals")
    ap.add_argument("--round", type=int, default=6)
    ap.add_argument("--write", action="store_true",
                    help="write the filtered long table")
    args = ap.parse_args()

    if not RAW.exists():
        raise SystemExit(f"{RAW} not found. Run build_site_long.py --fetch first.")

    rec = json.loads(RAW.read_text(encoding="utf-8"))
    df = pd.DataFrame([{
        "lat": r.get("decimalLatitude"),
        "lon": r.get("decimalLongitude"),
        "species": r.get("species"),
        "kingdom": r.get("kingdom"),
        "phylum": r.get("phylum"),
    } for r in rec]).dropna(subset=["lat", "lon", "species"])

    df["site_id"] = (df["lat"].round(args.round).astype(str) + "_" +
                     df["lon"].round(args.round).astype(str))
    kelp_sites = set(df.loc[df["species"].str.lower() == KELP, "site_id"])
    df = df[df["site_id"].isin(kelp_sites)]

    rows = []
    for site, g in df.groupby("site_id"):
        n = g["species"].nunique()
        animal = g.loc[g["kingdom"] == "Animalia", "species"].nunique()
        rows.append({
            "site_id": site,
            "taxa": n,
            "animal_taxa": animal,
            "pct_animal": round(100 * animal / n, 1) if n else 0.0,
        })

    t = pd.DataFrame(rows).sort_values("pct_animal")
    t["survey_type"] = ["shore_or_algal" if p < args.min_animal_pct
                        else "faunal_dive" for p in t["pct_animal"]]
    print(t.to_string(index=False))

    bad = t[t.survey_type == "shore_or_algal"]
    print(f"\n  {len(bad)} of {len(t)} kelp sites record almost no animals.")
    print("  These cannot be scored on a faunal indicator list. The threshold "
          f"({args.min_animal_pct}%) is a judgement, not a published cut-off - "
          "state it as ours.")

    if args.write:
        if not LONG.exists():
            raise SystemExit(f"{LONG} not found.")
        keep = set(t.loc[t.survey_type == "faunal_dive", "site_id"])
        long = pd.read_csv(LONG)
        out = long[long["site_id"].isin(keep)]
        out.to_csv(OUT, index=False)
        print(f"\n  {out.site_id.nunique()} sites kept -> {OUT}")
        print(f"  Next: python src/indicator_score.py --sites {OUT}")


if __name__ == "__main__":
    main()