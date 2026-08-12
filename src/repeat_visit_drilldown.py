#!/usr/bin/env python3
"""
repeat_visit_drilldown.py -- who and what is behind the numbers.

Two questions:
  A) The 3 sites where L. hyperborea ITSELF recurs -- which sites, which years,
     which dataset? This is the only remaining time-series candidate.
  B) What produces the 2012-2020 record block? If it is one recorder/programme,
     the rise in record counts is effort, not abundance.

Run: python src/repeat_visit_drilldown.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

RAW = Path("outputs/obis_raw_occurrences.json")
TARGET = "Laminaria hyperborea"
ROUND = 2

pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 60)


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
    d = get(rec, "eventDate", "date")
    if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
        return int(d[:4])
    return None


def main():
    if not RAW.exists():
        sys.exit(f"NOT FOUND: {RAW}")
    obj = json.loads(RAW.read_text(encoding="utf-8"))
    recs = obj.get("results", obj) if isinstance(obj, dict) else obj

    rows = []
    for r in recs:
        lat, lon = get(r, "decimalLatitude"), get(r, "decimalLongitude")
        if lat is None or lon is None:
            continue
        rows.append({
            "site": f"{round(float(lat), ROUND)}_{round(float(lon), ROUND)}",
            "lat": float(lat), "lon": float(lon),
            "year": year_of(r),
            "taxon": get(r, "species", "scientificName"),
            "dataset": get(r, "datasetName", "dataset_id"),
            "institution": get(r, "institutionCode", "collectionCode"),
            "basis": get(r, "basisOfRecord"),
            "recorder": get(r, "recordedBy"),
        })
    df = pd.DataFrame(rows).dropna(subset=["year"])
    df["year"] = df["year"].astype(int)

    # ---- A: the target species' own repeat sites -------------------------
    kelp = df[df["taxon"] == TARGET]
    per = kelp.groupby("site")["year"].nunique()
    repeat_sites = per[per > 1].index.tolist()

    print("=" * 70)
    print(f"A) {TARGET} recorded in >1 year at {len(repeat_sites)} site(s)")
    print("=" * 70)
    for s in repeat_sites:
        block = kelp[kelp["site"] == s]
        print(f"\nSITE {s}   ({block['lat'].mean():.4f}, {block['lon'].mean():.4f})")
        print(block[["year", "dataset", "institution", "basis"]]
              .sort_values("year").to_string(index=False))

    # ---- B: what drives the modern record block --------------------------
    print("\n" + "=" * 70)
    print("B) records per year x dataset (all taxa, 2005 onward)")
    print("=" * 70)
    modern = df[df["year"] >= 2005]
    print(pd.crosstab(modern["year"], modern["dataset"].fillna("?")).to_string())

    print("\ntop datasets overall:")
    print(df["dataset"].fillna("?").value_counts().head(15).to_string())

    print("\nbasisOfRecord by era (pre-1950 = herbarium/literature risk):")
    df["era"] = pd.cut(df["year"], [0, 1950, 2000, 2100],
                       labels=["<1950", "1950-1999", "2000+"])
    print(pd.crosstab(df["era"], df["basis"].fillna("?")).to_string())


if __name__ == "__main__":
    main()