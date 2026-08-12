#!/usr/bin/env python3
"""
Step 4 - build the site x species long table.

WHY THIS EXISTS
---------------
indicator_score.py --sites needs one row per (site, species). The assemblage
CSV is already aggregated (species -> number of sites), so the per-site detail
is gone. This rebuilds it.

WHAT COUNTS AS A SITE
---------------------
A site is a distinct coordinate pair, rounded to a fixed number of decimals.
That choice is not neutral: round too coarsely and separate dives merge, round
too finely and one dive splits into several. So this script does NOT pick for
you. It tries several roundings, prints how many Laminaria hyperborea sites
each produces, and refuses to write a file unless the count matches the 35
sites already established - or unless you override it deliberately.

This is the same discipline as the earlier probe failures: a number that looks
plausible is not the same as a number that is right.

USAGE
-----
  # normal case - raw records already on disk
  python src/build_site_long.py

  # if the JSON has no per-record coordinates, re-query OBIS.
  # Use the SAME bbox as src/obis_probe_v3.py or the site count will not match.
  python src/build_site_long.py --fetch --bbox -9.75,51.40,-9.30,51.60

  # override the site-count check once you have decided a rounding is correct
  python src/build_site_long.py --round 4 --expect 0

Requires: requests, pandas
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

try:
    import requests
except ImportError:
    requests = None

RECORDS_JSON = Path("outputs/obis_probe_records.json")
ASSEMBLAGE_CSV = Path("outputs/kelp_site_assemblage.csv")
OUT_LONG = Path("outputs/kelp_sites_long.csv")
RAW_CACHE = Path("outputs/obis_raw_occurrences.json")

KELP = "laminaria hyperborea"
OBIS_OCC = "https://api.obis.org/v3/occurrence"

LAT_KEYS = ("decimallatitude", "latitude", "lat")
LON_KEYS = ("decimallongitude", "longitude", "lon", "lng")
SP_KEYS = ("species", "scientificname", "acceptedname", "taxon")


def die(msg: str) -> None:
    print(f"\nFATAL: {msg}\n", file=sys.stderr)
    sys.exit(1)


def pick_key(sample: dict, wanted: tuple) -> str | None:
    lowered = {k.lower(): k for k in sample}
    for w in wanted:
        if w in lowered:
            return lowered[w]
    return None


def find_records(obj):
    """Walk a JSON blob and return the first list of dicts that has coordinates."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if pick_key(obj[0], LAT_KEYS) and pick_key(obj[0], LON_KEYS):
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            found = find_records(v)
            if found:
                return found
    return None


def fetch_obis(bbox: str) -> list:
    """Deep-page OBIS with the documented 'after' cursor.

    The earlier probe hit 50,000 records from /occurrence against 26,404 from
    /dataset. Offset paging past 10,000 is not reliable and repeats rows; the
    'after' cursor does not. If the two totals still disagree after this, the
    difference is real and worth reporting, not a paging bug.
    """
    if requests is None:
        die("pip install requests")
    lo_x, lo_y, hi_x, hi_y = [float(v) for v in bbox.split(",")]
    wkt = (f"POLYGON(({lo_x} {lo_y},{hi_x} {lo_y},{hi_x} {hi_y},"
           f"{lo_x} {hi_y},{lo_x} {lo_y}))")

    out, after, page = [], None, 0
    while True:
        params = {"geometry": wkt, "size": 5000}
        if after:
            params["after"] = after
        r = requests.get(OBIS_OCC, params=params, timeout=120)
        if r.status_code != 200:
            die(f"OBIS returned HTTP {r.status_code}. Nothing written.")
        results = r.json().get("results", [])
        if not results:
            break
        out.extend(results)
        after = results[-1].get("id")
        page += 1
        print(f"  page {page}: +{len(results)} (total {len(out)})")
        if not after:
            break
    ids = [r.get("id") for r in out]
    dupes = len(ids) - len(set(ids))
    print(f"  {len(out)} records, {dupes} duplicate ids")
    if dupes:
        print("  de-duplicating on id")
        seen, uniq = set(), []
        for r in out:
            if r.get("id") not in seen:
                seen.add(r.get("id"))
                uniq.append(r)
        out = uniq
    RAW_CACHE.parent.mkdir(parents=True, exist_ok=True)
    RAW_CACHE.write_text(json.dumps(out), encoding="utf-8")
    print(f"  cached to {RAW_CACHE}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="re-query OBIS")
    ap.add_argument("--bbox", help="minlon,minlat,maxlon,maxlat (with --fetch)")
    ap.add_argument("--round", type=int, help="coordinate decimals to use")
    ap.add_argument("--expect", type=int, default=35,
                    help="expected kelp-site count; 0 disables the check")
    args = ap.parse_args()

    # ------------------------------------------------------------- load
    if args.fetch:
        if not args.bbox:
            die("--fetch needs --bbox. Copy the same bounding box used in "
                "src/obis_probe_v3.py, or the site count will not match.")
        print("Fetching from OBIS...")
        records = fetch_obis(args.bbox)
    elif RAW_CACHE.exists():
        print(f"Using cached raw records: {RAW_CACHE}")
        records = json.loads(RAW_CACHE.read_text(encoding="utf-8"))
    elif RECORDS_JSON.exists():
        records = find_records(json.loads(RECORDS_JSON.read_text(encoding="utf-8")))
        if not records:
            die(f"{RECORDS_JSON} has no per-record coordinates in it - it is "
                f"probably a dataset summary, not raw occurrences. Re-run "
                f"with:  python src/build_site_long.py --fetch --bbox ...")
        print(f"Using {RECORDS_JSON}: {len(records)} records")
    else:
        die(f"Neither {RAW_CACHE} nor {RECORDS_JSON} found. Use --fetch --bbox.")

    lat_k = pick_key(records[0], LAT_KEYS)
    lon_k = pick_key(records[0], LON_KEYS)
    sp_k = pick_key(records[0], SP_KEYS)
    if not (lat_k and lon_k and sp_k):
        die(f"Missing fields. Found keys: {sorted(records[0])[:25]}")
    print(f"  fields -> lat '{lat_k}', lon '{lon_k}', species '{sp_k}'")

    df = pd.DataFrame([{"lat": r.get(lat_k), "lon": r.get(lon_k),
                        "species": r.get(sp_k)} for r in records])
    df = df.dropna(subset=["lat", "lon", "species"])
    print(f"  {len(df)} records with coordinates and a name")

    # -------------------------------------------- choose the site rounding
    print("\nSites containing Laminaria hyperborea, by coordinate rounding:")
    counts = {}
    for d in (6, 5, 4, 3):
        sid = (df["lat"].round(d).astype(str) + "_" + df["lon"].round(d).astype(str))
        kelp_sites = sid[df["species"].str.lower() == KELP].nunique()
        counts[d] = kelp_sites
        flag = "  <-- matches expected" if kelp_sites == args.expect else ""
        print(f"  {d} decimals: {kelp_sites} kelp sites, "
              f"{sid.nunique()} sites total{flag}")

    if args.round:
        use = args.round
    else:
        matching = [d for d, c in counts.items() if c == args.expect]
        if not matching:
            die(f"No rounding reproduces {args.expect} kelp sites. The site "
                f"definition here differs from the one used to build "
                f"{ASSEMBLAGE_CSV}. Do not proceed on a mismatched definition - "
                f"either pass --round explicitly with --expect 0, or check how "
                f"sites were defined in src/obis_probe_v3.py.")
        use = max(matching)
    print(f"\nUsing {use} decimals.")

    # ---------------------------------------------------------- build table
    df["site_id"] = (df["lat"].round(use).astype(str) + "_" +
                     df["lon"].round(use).astype(str))
    kelp_sites = set(df.loc[df["species"].str.lower() == KELP, "site_id"])
    # Survey effort = number of raw OBIS records at the site. This MUST be
    # counted before de-duplication. After de-duplication the row count is
    # species richness, which is itself the effort artefact we are trying to
    # control for - using it as the effort flag would be circular.
    effort = df.groupby("site_id").size().rename("records_at_site")
    out = (df[df["site_id"].isin(kelp_sites)]
           [["site_id", "species", "lat", "lon"]]
           .drop_duplicates()
           .sort_values(["site_id", "species"])
           .merge(effort, left_on="site_id", right_index=True))

    # ------------------------------------------------- independent check
    n_sites, n_species = out["site_id"].nunique(), out["species"].nunique()
    print(f"\n  {n_sites} kelp sites, {n_species} unique species, {len(out)} rows")
    if ASSEMBLAGE_CSV.exists():
        ref_n = pd.read_csv(ASSEMBLAGE_CSV).shape[0]
        verdict = "matches" if n_species == ref_n else "DOES NOT MATCH"
        print(f"  {ASSEMBLAGE_CSV} has {ref_n} species - {verdict}")
        if n_species != ref_n:
            print("  A mismatch means this table was built from a different "
                  "record set or a different filter than the assemblage. Find "
                  "out why before scoring anything with it.")

    OUT_LONG.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_LONG, index=False)
    print(f"\n  written to {OUT_LONG}")
    print("\nNext:  python src/indicator_score.py --sites outputs/kelp_sites_long.csv\n")


if __name__ == "__main__":
    main()