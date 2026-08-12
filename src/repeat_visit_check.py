#!/usr/bin/env python3
"""
repeat_visit_check.py  --  Step 5 pre-check.

Question: does any West Cork kelp dive site appear in MORE THAN ONE YEAR?
If yes -> a local time series may exist and Step 5 is buildable from our own data.
If no  -> the decline row closes at "insufficient basis" and we stop.

Reads:  outputs/obis_raw_occurrences.json   (the corrected `after`-cursor extract)
Writes: outputs/repeat_visits.csv           (site x year matrix, long form)

Run:    python src/repeat_visit_check.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

RAW = Path("outputs/obis_raw_occurrences.json")
OUT = Path("outputs/repeat_visits.csv")
TARGET = "Laminaria hyperborea"
ROUND = 2  # decimal places for site key; note 4 was shown insensitive in step 4


def load(path):
    if not path.exists():
        sys.exit(f"NOT FOUND: {path} -- run from the project root.")
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    # tolerate {"results": [...]} or a bare list
    recs = obj.get("results", obj) if isinstance(obj, dict) else obj
    print(f"loaded {len(recs)} records")
    return recs


def get(rec, *keys):
    for k in keys:
        v = rec.get(k)
        if v not in (None, ""):
            return v
    return None


def year_of(rec):
    y = get(rec, "date_year", "year")
    if y is not None:
        try:
            return int(y)
        except (TypeError, ValueError):
            pass
    d = get(rec, "eventDate", "date", "eventDate_start")
    if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return None


def main():
    recs = load(RAW)

    rows = []
    for r in recs:
        lat = get(r, "decimalLatitude", "latitude")
        lon = get(r, "decimalLongitude", "longitude")
        if lat is None or lon is None:
            continue
        rows.append({
            "site": f"{round(float(lat), ROUND)}_{round(float(lon), ROUND)}",
            "year": year_of(r),
            "taxon": get(r, "species", "scientificName", "originalScientificName"),
            "dataset": get(r, "dataset_id", "datasetName", "institutionCode"),
        })

    df = pd.DataFrame(rows)
    print(f"{len(df)} records with coordinates")

    undated = df["year"].isna().sum()
    print(f"undated records: {undated} ({undated / max(len(df), 1):.1%})")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)

    # sites where L. hyperborea was recorded at least once
    kelp_sites = set(df.loc[df["taxon"] == TARGET, "site"])
    print(f"\nsites with {TARGET}: {len(kelp_sites)}")
    if not kelp_sites:
        sys.exit("No target sites -- check the taxon string against the file.")

    sub = df[df["site"].isin(kelp_sites)]

    # site x year
    per_site = (sub.groupby("site")
                   .agg(n_years=("year", "nunique"),
                        years=("year", lambda s: sorted(set(s))),
                        n_records=("year", "size"))
                   .sort_values("n_years", ascending=False))

    repeats = per_site[per_site["n_years"] > 1]

    print("\n" + "=" * 60)
    print(f"SITES VISITED IN >1 YEAR: {len(repeats)} of {len(per_site)}")
    print("=" * 60)
    if len(repeats):
        print(repeats.head(20).to_string())
        span = sub[sub["site"].isin(repeats.index)]
        print(f"\nyear range across repeat sites: "
              f"{span['year'].min()}-{span['year'].max()}")
        # does the target itself recur, or only the associated fauna?
        kelp_only = sub[sub["taxon"] == TARGET]
        kr = kelp_only.groupby("site")["year"].nunique()
        print(f"sites where {TARGET} ITSELF is recorded in >1 year: "
              f"{(kr > 1).sum()}")
    else:
        print("None. No repeat-visit structure in this extract.")

    print("\nrecords per year (all kelp-site taxa):")
    print(sub.groupby("year").size().to_string())

    per_site.assign(years=per_site["years"].astype(str)).to_csv(OUT)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()