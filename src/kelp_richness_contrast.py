#!/usr/bin/env python3
"""
Step 4, analysis 1: does the presence of kelp raise observed species richness
at a site, in West Cork, in data we actually hold?

This is the raw material for the biodiversity score. If it works, the score is
grounded in local observation rather than transferred from Norwegian literature.

METHOD CONTROL - the whole point of this script.
The AOI's benthic records come from two incompatible methods:
  - diver survey (Marine Recorder: JNCC, NMNI, SeaSearch) -> long species lists,
    on reef, and the only method that can record kelp at all
  - grab / core sampling (WFD benthos)                    -> infauna in sediment,
    can never record kelp
Comparing richness across the two measures the method, not the habitat. Worse,
"kelp present" is perfectly confounded with "was a dive": a grab sample cannot
record Laminaria even if it lands in a kelp bed. So the comparison is restricted
to the three Marine Recorder datasets only. Everything else is reported
separately, for context, never pooled into the test.

EFFORT CONTROL.
Richness rises with survey effort. A site with 40 records will show more species
than one with 5, whatever lives there. So the script reports richness against
records-per-site, and repeats the comparison inside bins of similar effort. If
the kelp signal only exists before binning, it is an effort artefact and must be
reported as such.

Usage:
    python src/kelp_richness_contrast.py

NOT TESTED against the live API.
"""

import csv
from collections import Counter, defaultdict
from statistics import median

import requests

BASE = "https://api.obis.org/v3"

WKT = (
    "POLYGON((-9.65359 51.39842, -9.65359 51.54624, "
    "-9.36648 51.54624, -9.36648 51.39842, -9.65359 51.39842))"
)

# The comparable set: one method, diver survey, Marine Recorder schema.
DIVE_DATASETS = {
    "6d7b384f-090b-4c15-b68d-4c1192c0f8a6": "Marine Recorder / JNCC",
    "953e0d26-24e8-4797-b944-8aa7fe2ea937": "Marine Recorder / NMNI",
    "3e981ea4-29b3-4df5-8529-38d798262eb1": "Marine Recorder / SeaSearch",
}
# Reported for context only. NOT pooled into the contrast.
CONTEXT_DATASETS = {
    "275ca552-98ad-403f-a2ab-f76b8391b442": "Porcupine MNHS",
    "5132b63a-4d7a-41e7-87eb-b5a9d6edc05f": "WFD benthos (grab)",
}

TARGET = "Laminaria hyperborea"
ANY_KELP = {
    "Laminaria hyperborea", "Laminaria digitata", "Saccharina latissima",
    "Saccorhiza polyschides", "Alaria esculenta",
}


def page(datasetid, size=5000, max_pages=10):
    out, seen, offset = [], set(), 0
    for _ in range(max_pages):
        r = requests.get(
            f"{BASE}/occurrence",
            params={"geometry": WKT, "datasetid": datasetid,
                    "size": size, "offset": offset},
            timeout=180,
        )
        if r.status_code != 200:
            print(f"!! HTTP {r.status_code} {r.text[:300]}")
            break
        batch = r.json().get("results", [])
        for rec in batch:
            rid = rec.get("id")
            if rid is not None and rid in seen:
                continue
            if rid is not None:
                seen.add(rid)
            out.append(rec)
        if len(batch) < size:
            break
        offset += size
    return out


def build_sites(recs):
    """site key = coords rounded to 4dp (~11 m). Returns dict of site -> info."""
    sites = defaultdict(lambda: {"species": set(), "n": 0, "depths": []})
    for r in recs:
        lon, lat = r.get("decimalLongitude"), r.get("decimalLatitude")
        if lon is None or lat is None:
            continue
        key = (round(lon, 4), round(lat, 4))
        s = sites[key]
        s["n"] += 1
        if r.get("species"):
            s["species"].add(r["species"])
        if r.get("depth") is not None:
            s["depths"].append(r["depth"])
    return sites


def describe(label, values):
    if not values:
        print(f"  {label:28s} n=0")
        return
    print(f"  {label:28s} n={len(values):4d}  median={median(values):5.1f}  "
          f"min={min(values):3.0f}  max={max(values):3.0f}")


def main():
    print("=== FETCH (diver survey datasets only) ===")
    recs = []
    for did, name in DIVE_DATASETS.items():
        got = page(did)
        print(f"  {name:32s} {len(got)} records")
        recs.extend(got)
    print(f"  pooled: {len(recs)} records")

    sites = build_sites(recs)
    print(f"  sites (coords to 4dp): {len(sites)}")

    kelp_sites = {k: v for k, v in sites.items() if TARGET in v["species"]}
    anykelp_sites = {k: v for k, v in sites.items()
                     if v["species"] & ANY_KELP}
    other_sites = {k: v for k, v in sites.items()
                   if not (v["species"] & ANY_KELP)}

    print(f"\n  sites with {TARGET}: {len(kelp_sites)}")
    print(f"  sites with any kelp      : {len(anykelp_sites)}")
    print(f"  sites with no kelp       : {len(other_sites)}")

    if len(kelp_sites) < 5:
        print("\n!! fewer than 5 kelp sites in the comparable set.")
        print("!! the contrast below is descriptive only; do not put a")
        print("!! significance claim on it.")

    print("\n=== RICHNESS (species per site) ===")
    describe(f"{TARGET} present", [len(v["species"]) for v in kelp_sites.values()])
    describe("any kelp present", [len(v["species"]) for v in anykelp_sites.values()])
    describe("no kelp", [len(v["species"]) for v in other_sites.values()])

    print("\n=== EFFORT (records per site) -- read this before believing above ===")
    describe(f"{TARGET} present", [v["n"] for v in kelp_sites.values()])
    describe("any kelp present", [v["n"] for v in anykelp_sites.values()])
    describe("no kelp", [v["n"] for v in other_sites.values()])

    print("\n=== RICHNESS WITHIN EFFORT BINS ===")
    print("  if the gap disappears here, it was an effort artefact")
    bins = [(1, 5), (6, 15), (16, 40), (41, 10**6)]
    for lo, hi in bins:
        k = [len(v["species"]) for v in anykelp_sites.values() if lo <= v["n"] <= hi]
        o = [len(v["species"]) for v in other_sites.values() if lo <= v["n"] <= hi]
        km = f"{median(k):.1f}" if k else "-"
        om = f"{median(o):.1f}" if o else "-"
        print(f"  {lo:3d}-{hi if hi < 10**6 else '+':>4} records/site   "
              f"kelp median={km:>5} (n={len(k):3d})   "
              f"no-kelp median={om:>5} (n={len(o):3d})")

    print("\n=== DEPTH AT KELP SITES ===")
    d = [x for v in kelp_sites.values() for x in v["depths"]]
    describe("depth, m", d)
    if not d:
        print("  no depth values -> cannot check these sit in the 0-20 m band")

    # ---- the assemblage: what actually lives at L. hyperborea sites ----
    print(f"\n=== ASSEMBLAGE AT {TARGET} SITES ===")
    assemblage = Counter()
    for v in kelp_sites.values():
        assemblage.update(v["species"])
    assemblage.pop(TARGET, None)
    print(f"  {len(assemblage)} co-occurring species across "
          f"{len(kelp_sites)} sites")
    print("\n  top 30 (n = number of kelp sites the species appears at):")
    for name, c in assemblage.most_common(30):
        print(f"   {c:4d}/{len(kelp_sites):<4d}  {name}")

    out = "outputs/kelp_site_assemblage.csv"
    try:
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["species", "n_kelp_sites", "n_kelp_sites_total"])
            for name, c in assemblage.most_common():
                w.writerow([name, c, len(kelp_sites)])
        print(f"\n  full list -> {out}")
    except OSError as e:
        print(f"\n!! could not write {out}: {e}")

    # ---- context only ----
    print("\n=== CONTEXT (different methods -- NOT comparable, do not pool) ===")
    for did, name in CONTEXT_DATASETS.items():
        got = page(did)
        s = build_sites(got)
        rich = [len(v["species"]) for v in s.values()]
        print(f"  {name:24s} {len(got):5d} records, {len(s):4d} sites, "
              f"median richness {median(rich) if rich else 0:.1f}")


if __name__ == "__main__":
    main()