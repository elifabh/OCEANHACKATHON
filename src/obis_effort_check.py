#!/usr/bin/env python3
"""
Step 4, follow-up probe: unbiased effort breakdown.

Why this exists: obis_gbif_probe.py paginates /occurrence and got cut off at
50,000 records. API pages are not a random sample, so the "top 3 datasets = 62%"
figure from that run is contaminated by pagination order and must not be quoted.

This script uses two aggregate endpoints instead. No pagination, no truncation,
totals computed server-side over the whole AOI.

  /v3/dataset?geometry=...    -> every dataset contributing records, with titles
  /v3/checklist?geometry=...  -> every taxon, with record counts

The dataset TITLES are the point. They tell you what was actually surveyed.

Usage:
    python src/obis_effort_check.py
    python src/obis_effort_check.py --wkt "POLYGON((...))"

NOT TESTED against the live API. Response field names are guessed defensively;
if a field is missing the script prints the raw keys so you can tell me.
"""

import argparse
from collections import Counter

import requests

DEFAULT_WKT = (
    "POLYGON((-9.65359 51.39842, -9.65359 51.54624, "
    "-9.36648 51.54624, -9.36648 51.39842, -9.65359 51.39842))"
)


def get(path, wkt, extra=None):
    url = f"https://api.obis.org/v3/{path}"
    params = {"geometry": wkt}
    if extra:
        params.update(extra)
    r = requests.get(url, params=params, timeout=180)
    if r.status_code != 200:
        print(f"!! {path}: HTTP {r.status_code}")
        print(f"!! {r.text[:500]}")
        return None
    return r.json()


def pick(d, *names, default=None):
    """Tolerant field lookup across possible API field names."""
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wkt", default=DEFAULT_WKT)
    args = ap.parse_args()

    print("AOI:", args.wkt)

    # ---------- datasets ----------
    print("\n=== DATASETS CONTRIBUTING RECORDS ===")
    js = get("dataset", args.wkt)
    if js is None:
        return
    rows = js.get("results", [])
    if rows and not any(k in rows[0] for k in ("records", "n_records", "count")):
        print("field names differ; raw keys of first row:")
        print(sorted(rows[0].keys()))

    ds = []
    for d in rows:
        ds.append(
            (
                pick(d, "records", "n_records", "count", default=0),
                pick(d, "title", "name", default="(no title)"),
                pick(d, "id", "dataset_id", default=""),
            )
        )
    ds.sort(reverse=True)
    total = sum(n for n, _, _ in ds)

    print(f"datasets                {len(ds)}")
    print(f"total records in AOI    {total}   <-- the untruncated number")
    if total:
        for k in (1, 3, 5, 10):
            share = sum(n for n, _, _ in ds[:k]) / total
            print(f"top {k:<2} = {100 * share:5.1f}% of records")

    print("\nall datasets, largest first:")
    for n, title, did in ds:
        pct = 100 * n / total if total else 0
        print(f"  {n:7d}  {pct:5.1f}%  {title[:90]}")

    # ---------- taxa ----------
    print("\n=== CHECKLIST ===")
    js = get("checklist", args.wkt)
    if js is None:
        return
    rows = js.get("results", [])
    print(f"taxa returned           {len(rows)}")

    ranks = Counter(pick(t, "taxonRank", "rank", default="?") for t in rows)
    print("\nby rank:")
    for rank, c in ranks.most_common():
        print(f"  {c:6d}  {rank}")

    phyla = Counter(pick(t, "phylum", default="?") for t in rows)
    print("\nby phylum (species-level habitat check):")
    for ph, c in phyla.most_common(15):
        print(f"  {c:6d}  {ph}")

    # Species that would actually matter for a kelp biodiversity score.
    # Presence of these tells you whether ANY benthic reef survey exists here.
    print("\n=== KELP-RELEVANT TAXA PRESENT? ===")
    targets = [
        "Laminaria hyperborea", "Laminaria digitata", "Saccharina latissima",
        "Saccorhiza polyschides", "Alaria esculenta",
        "Echinus esculentus", "Alcyonium digitatum", "Cliona celata",
        "Homarus gammarus", "Necora puber", "Cancer pagurus",
        "Maja brachydactyla", "Labrus bergylta", "Ctenolabrus rupestris",
        "Patella pellucida", "Halidrys siliquosa",
    ]
    by_name = {}
    for t in rows:
        nm = pick(t, "scientificName", "species", "acceptedNameUsage")
        if nm:
            by_name[nm] = pick(t, "records", "n_records", "count", default=0)
    for name in targets:
        n = by_name.get(name)
        print(f"  {name:28s} {'-- absent' if n is None else f'{n} records'}")


if __name__ == "__main__":
    main()