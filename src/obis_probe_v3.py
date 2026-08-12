#!/usr/bin/env python3
"""
Step 4, probe v3. Fixes three faults in the previous two scripts.

FAULT 1 - /v3/checklist was called without a size parameter and returned only
          10 taxa (the API default). Every "-- absent" line in the v2 output was
          an artefact of that, NOT a finding. Fixed by paging explicitly.

FAULT 2 - v1 reported 50,000 occurrence records; v2's /dataset endpoint reports
          26,404 total. Those cannot both be right. This script counts UNIQUE
          occurrence ids so we find out whether deep paging was returning
          duplicates.

FAULT 3 - v2 printed dataset titles but threw away the dataset ids, so nothing
          could be followed up. Ids are kept and printed here.

The real question this answers: the AOI's biggest dataset is phytoplankton
monitoring at mussel farms, which is irrelevant to kelp. But roughly a quarter of
records come from benthic/rocky-shore survey datasets (Marine Recorder, SeaSearch,
WFD benthos, Porcupine, EcoServe). Those ARE relevant. How many species do they
hold, and do they include kelp and kelp-associated fauna?

Usage:
    python src/obis_probe_v3.py

NOT TESTED against the live API.
"""

import argparse
from collections import Counter, defaultdict

import requests

BASE = "https://api.obis.org/v3"

DEFAULT_WKT = (
    "POLYGON((-9.65359 51.39842, -9.65359 51.54624, "
    "-9.36648 51.54624, -9.36648 51.39842, -9.65359 51.39842))"
)

# Datasets whose title suggests they survey the seabed / shore rather than
# plankton, seabirds, megafauna or offshore trawl. Edit this list if the
# flagging below looks wrong -- it is a keyword guess, not authoritative.
RELEVANT_KEYWORDS = [
    "benthos", "benthic", "marine recorder", "seasearch", "rocky shore",
    "macroalgae", "porcupine", "ecoserve", "crab atlas", "invertebrate",
    "shore thing", "explore your shore", "ophiuroid",
]

KELP_TAXA = [
    "Laminaria hyperborea", "Laminaria digitata", "Laminaria",
    "Saccharina latissima", "Saccorhiza polyschides", "Alaria esculenta",
    "Echinus esculentus", "Alcyonium digitatum", "Cliona celata",
    "Homarus gammarus", "Necora puber", "Cancer pagurus",
    "Maja brachydactyla", "Labrus bergylta", "Ctenolabrus rupestris",
    "Patella pellucida", "Halidrys siliquosa",
]


def get(path, params):
    r = requests.get(f"{BASE}/{path}", params=params, timeout=180)
    if r.status_code != 200:
        print(f"!! {path}: HTTP {r.status_code}\n!! {r.text[:400]}")
        return None
    return r.json()


def page_occurrences(wkt, datasetid=None, size=5000, max_pages=20):
    """Page /occurrence, tracking unique ids so duplicates are visible."""
    out, seen, offset = [], set(), 0
    for i in range(max_pages):
        p = {"geometry": wkt, "size": size, "offset": offset}
        if datasetid:
            p["datasetid"] = datasetid
        js = get("occurrence", p)
        if js is None:
            break
        batch = js.get("results", [])
        new = 0
        for rec in batch:
            rid = rec.get("id")
            if rid is not None and rid in seen:
                continue
            if rid is not None:
                seen.add(rid)
            out.append(rec)
            new += 1
        if new < len(batch):
            print(f"    page {i+1}: {len(batch)} returned, {new} new "
                  f"-> {len(batch)-new} DUPLICATES")
        if len(batch) < size:
            break
        offset += size
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wkt", default=DEFAULT_WKT)
    args = ap.parse_args()

    # ---------- 1. datasets, with ids kept ----------
    print("=== DATASETS (ids kept this time) ===")
    js = get("dataset", {"geometry": args.wkt})
    if js is None:
        return
    rows = js.get("results", [])
    ds = []
    for d in rows:
        n = d.get("records") or d.get("n_records") or d.get("count") or 0
        ds.append((n, d.get("title") or "", d.get("id") or ""))
    ds.sort(reverse=True)
    total = sum(n for n, _, _ in ds) or 1

    relevant = []
    for n, title, did in ds:
        hit = any(k in title.lower() for k in RELEVANT_KEYWORDS)
        if hit:
            relevant.append((n, title, did))
        if n >= 50:
            print(f"  {'BENTHIC' if hit else '       '} {n:7d} "
                  f"{100*n/total:5.1f}%  {did}  {title[:60]}")

    rel_n = sum(n for n, _, _ in relevant)
    print(f"\nflagged as seabed/shore survey: {len(relevant)} datasets, "
          f"{rel_n} records = {100*rel_n/total:.1f}% of AOI total")

    # ---------- 2. checklist, properly paged ----------
    print("\n=== CHECKLIST (size fixed) ===")
    js = get("checklist", {"geometry": args.wkt, "size": 10000})
    if js is not None:
        taxa = js.get("results", [])
        print(f"taxa returned  {len(taxa)}   (v2 said 10 -- that was the bug)")
        names = {t.get("scientificName") or t.get("species") for t in taxa}
        names.discard(None)
        print("\nkelp-relevant taxa in the WHOLE AOI:")
        for t in KELP_TAXA:
            print(f"  {t:26s} {'present' if t in names else '-- absent'}")

    # ---------- 3. species held by the benthic datasets only ----------
    print("\n=== SPECIES IN THE SEABED/SHORE DATASETS ONLY ===")
    per_ds = {}
    all_species = Counter()
    sites_by_species = defaultdict(set)
    for n, title, did in relevant:
        if not did:
            continue
        print(f"\n  {title[:70]}  ({n} records)")
        recs = page_occurrences(args.wkt, datasetid=did)
        sp = Counter(r["species"] for r in recs if r.get("species"))
        per_ds[title] = (len(recs), len(sp))
        all_species.update(sp)
        for r in recs:
            s = r.get("species")
            if s and r.get("decimalLongitude") is not None:
                sites_by_species[s].add(
                    (round(r["decimalLongitude"], 4), round(r["decimalLatitude"], 4))
                )
        print(f"    fetched {len(recs)} unique records, {len(sp)} species")

    print(f"\ncombined: {sum(v[0] for v in per_ds.values())} records, "
          f"{len(all_species)} species across {len(per_ds)} datasets")

    print("\nkelp-relevant taxa IN THESE DATASETS:")
    for t in KELP_TAXA:
        c = all_species.get(t)
        sites = len(sites_by_species.get(t, ()))
        print(f"  {t:26s} "
              f"{'-- absent' if not c else f'{c} records at {sites} sites'}")

    print("\ntop 25 species in the seabed/shore datasets:")
    for name, c in all_species.most_common(25):
        print(f"  {c:5d}  at {len(sites_by_species[name]):3d} sites   {name}")


if __name__ == "__main__":
    main()