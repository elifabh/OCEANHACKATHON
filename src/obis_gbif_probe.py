#!/usr/bin/env python3
"""
Step 4 probe: how much occurrence data actually exists in our AOI?

Run this BEFORE designing any biodiversity score. It answers one question:
is there enough, and evenly-enough-collected, data to measure biodiversity —
or only enough to measure where divers went?

Outputs three diagnostics:
  1. n_records, n_species          -> is there anything at all?
  2. effort concentration          -> what share of records come from the
                                      top few datasets / top few coordinates?
  3. depth coverage                -> can we filter to the 0-20 m kelp zone?

If (2) is high, per-cell species counts are a map of sampling effort, not of
biodiversity, and the score must be habitat-based instead.

Usage:
    python obis_gbif_probe.py                      # default AOI = Roaringwater Bay SAC bbox
    python obis_gbif_probe.py --wkt "POLYGON((...))"
    python obis_gbif_probe.py --max-pages 20

NOT TESTED against the live APIs (no outbound network where this was written).
Expect to fix at least one thing. Failure modes are printed loudly, not swallowed.

Sources for endpoints:
  OBIS  https://api.obis.org/v3/occurrence   params: geometry(WKT), size, offset,
        startdepth, enddepth, scientificname, fields   (iobis/pyobis docs)
  GBIF  https://api.gbif.org/v1/occurrence/search  params: geometry(WKT), limit, offset
        NB: GBIF treats a CLOCKWISE outer ring as a hole. Must be counter-clockwise.
"""

import argparse
import json
import sys
from collections import Counter

import requests

# Roaringwater Bay SAC bounding box.
# Source: data.gov.ie "Roaringwater Bay Marine Habitats" dataset geographic coverage.
DEFAULT_WKT = (
    "POLYGON((-9.65359 51.39842, -9.65359 51.54624, "
    "-9.36648 51.54624, -9.36648 51.39842, -9.65359 51.39842))"
)


def ring_from_wkt(wkt):
    """Crude POLYGON((...)) parser -> list of (lon, lat). Single ring only."""
    inner = wkt[wkt.index("((") + 2: wkt.index("))")]
    pts = []
    for pair in inner.split(","):
        lon, lat = pair.strip().split()
        pts.append((float(lon), float(lat)))
    return pts


def is_ccw(ring):
    """Shoelace. Positive signed area = counter-clockwise."""
    a = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        a += (x2 - x1) * (y2 + y1)
    return a < 0


def to_ccw_wkt(wkt):
    """GBIF needs a counter-clockwise outer ring; reverse it if needed."""
    ring = ring_from_wkt(wkt)
    if is_ccw(ring):
        return wkt, False
    ring = ring[::-1]
    body = ", ".join(f"{lon} {lat}" for lon, lat in ring)
    return f"POLYGON(({body}))", True


def fetch_obis(wkt, max_pages, page=5000):
    url = "https://api.obis.org/v3/occurrence"
    recs, offset = [], 0
    for i in range(max_pages):
        params = {"geometry": wkt, "size": page, "offset": offset}
        r = requests.get(url, params=params, timeout=120)
        if r.status_code != 200:
            print(f"  !! OBIS HTTP {r.status_code} at offset {offset}")
            print(f"  !! {r.text[:400]}")
            break
        batch = r.json().get("results", [])
        recs.extend(batch)
        print(f"  page {i + 1}: +{len(batch)}  (total {len(recs)})")
        if len(batch) < page:
            break
        offset += page
    else:
        print(f"  !! hit --max-pages ({max_pages}); result is TRUNCATED")
    return recs


def fetch_gbif_count(wkt):
    """Just the count + species facet. Cheap sanity cross-check on OBIS."""
    url = "https://api.gbif.org/v1/occurrence/search"
    params = {"geometry": wkt, "limit": 0, "facet": "speciesKey", "facetLimit": 1}
    r = requests.get(url, params=params, timeout=120)
    if r.status_code != 200:
        print(f"  !! GBIF HTTP {r.status_code}")
        print(f"  !! {r.text[:400]}")
        return None
    return r.json().get("count")


def share_of_top(counter, k):
    total = sum(counter.values())
    if total == 0:
        return 0.0
    return sum(c for _, c in counter.most_common(k)) / total


def report(recs):
    n = len(recs)
    print(f"\nrecords                 {n}")
    if n == 0:
        print("nothing to report. Widen the AOI or check the WKT.")
        return

    species = Counter(
        r.get("species") for r in recs if r.get("species")
    )
    datasets = Counter(r.get("dataset_id") for r in recs if r.get("dataset_id"))
    # round coords to ~11 m so repeat visits to one dive site collapse together
    sites = Counter(
        (round(r["decimalLongitude"], 4), round(r["decimalLatitude"], 4))
        for r in recs
        if r.get("decimalLongitude") is not None
        and r.get("decimalLatitude") is not None
    )
    with_depth = sum(1 for r in recs if r.get("depth") is not None)
    years = Counter(r.get("date_year") for r in recs if r.get("date_year"))

    print(f"species (named)         {len(species)}")
    print(f"datasets                {len(datasets)}")
    print(f"distinct sites (4dp)    {len(sites)}")
    print(f"records with depth      {with_depth}  ({100 * with_depth / n:.0f}%)")
    if years:
        print(f"year range              {min(years)} - {max(years)}")

    print("\n--- EFFORT CONCENTRATION (the thing that decides the design) ---")
    print(f"top 1 dataset  = {100 * share_of_top(datasets, 1):.0f}% of records")
    print(f"top 3 datasets = {100 * share_of_top(datasets, 3):.0f}% of records")
    print(f"top 10 sites   = {100 * share_of_top(sites, 10):.0f}% of records")

    print("\ntop 10 species")
    for name, c in species.most_common(10):
        print(f"  {c:6d}  {name}")

    print("\ntop 5 datasets")
    for did, c in datasets.most_common(5):
        print(f"  {c:6d}  {did}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wkt", default=DEFAULT_WKT)
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--out", default="outputs/obis_probe_records.json")
    args = ap.parse_args()

    print("AOI (OBIS):", args.wkt)
    print("\n=== OBIS ===")
    recs = fetch_obis(args.wkt, args.max_pages)
    report(recs)

    gbif_wkt, flipped = to_ccw_wkt(args.wkt)
    print("\n=== GBIF (count only, cross-check) ===")
    if flipped:
        print("  ring was clockwise; reversed for GBIF")
    c = fetch_gbif_count(gbif_wkt)
    print(f"records                 {c}")
    if c is not None and len(recs) > 0:
        print(f"GBIF / OBIS ratio       {c / len(recs):.2f}")
        print("  (GBIF is a superset incl. terrestrial + birds; expect > 1)")

    try:
        with open(args.out, "w") as f:
            json.dump(recs, f)
        print(f"\nraw OBIS records -> {args.out}")
    except OSError as e:
        print(f"\n!! could not write {args.out}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()