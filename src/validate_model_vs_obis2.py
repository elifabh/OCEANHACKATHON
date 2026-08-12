#!/usr/bin/env python3
"""
Step 2 validation v2. Fixes two faults in validate_model_vs_obis.py.

FAULT 1 - AOIs were selected by name matching "roaring". That picked only
          inner_roaringwater (the AOI locked OUT of positive labelling because
          MERC 2007 records Saccharina/Saccorhiza there, not L. hyperborea) and
          dropped sherkin_baltimore, which is geographically inside Roaringwater
          Bay. Fixed: match against every AOI, report which one each site hits.

FAULT 2 - 33 of 35 sites failed to match any cell at 75 m tolerance, so the
          reported percentiles came from n=2 and mean nothing. This version
          reports the DISTANCE from each dive site to the nearest model cell
          before doing any scoring, so we can see whether the problem is
          tolerance (fixable) or coverage (the AOI boxes simply do not extend to
          where the divers went -- a real finding, and a slide).

Usage:
    python src/validate_model_vs_obis2.py

NOT TESTED.
"""

import math
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import requests

BASE = "https://api.obis.org/v3"
WKT = ("POLYGON((-9.65359 51.39842, -9.65359 51.54624, "
       "-9.36648 51.54624, -9.36648 51.39842, -9.65359 51.39842))")
PRED = "outputs/model/v1_20260727/suitability_multisite_predictions.csv"

DIVE_DATASETS = [
    "6d7b384f-090b-4c15-b68d-4c1192c0f8a6",
    "953e0d26-24e8-4797-b944-8aa7fe2ea937",
    "3e981ea4-29b3-4df5-8529-38d798262eb1",
]
TARGET = "Laminaria hyperborea"
ANY_KELP = {"Laminaria hyperborea", "Laminaria digitata",
            "Saccharina latissima", "Saccorhiza polyschides",
            "Alaria esculenta"}


def page(datasetid, size=5000, max_pages=10):
    out, seen, offset = [], set(), 0
    for _ in range(max_pages):
        r = requests.get(f"{BASE}/occurrence",
                         params={"geometry": WKT, "datasetid": datasetid,
                                 "size": size, "offset": offset}, timeout=180)
        if r.status_code != 200:
            print(f"!! HTTP {r.status_code}")
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


def main():
    df = pd.read_csv(PRED)
    print(f"model cells: {len(df)}")
    for a in sorted(df.aoi.unique()):
        s = df[df.aoi == a]
        print(f"  {a:22s} {len(s):6d} cells   "
              f"lon {s.lon.min():.4f}..{s.lon.max():.4f}   "
              f"lat {s.lat.min():.4f}..{s.lat.max():.4f}   "
              f"suit median {s.suitability.median():.3f}")

    lat0 = float(df.lat.mean())
    mlon = 111320.0 * math.cos(math.radians(lat0))
    mlat = 110540.0
    gx, gy = df.lon.values * mlon, df.lat.values * mlat
    aoi_arr = df.aoi.values
    suit = df.suitability.values

    # per-AOI value arrays, for percentile within the matched AOI
    per_aoi = {a: df[df.aoi == a].suitability.values for a in df.aoi.unique()}

    recs = []
    for d in DIVE_DATASETS:
        recs.extend(page(d))
    sites = defaultdict(set)
    for r in recs:
        lon, lat = r.get("decimalLongitude"), r.get("decimalLatitude")
        if lon is None or lat is None or not r.get("species"):
            continue
        sites[(round(lon, 4), round(lat, 4))].add(r["species"])

    groups = {
        "L. hyperborea": [k for k, v in sites.items() if TARGET in v],
        "any kelp": [k for k, v in sites.items() if v & ANY_KELP],
        "no kelp recorded": [k for k, v in sites.items() if not (v & ANY_KELP)],
    }

    # ---------- step 1: coverage diagnosis, before any scoring ----------
    print("\n=== DISTANCE FROM DIVE SITE TO NEAREST MODEL CELL ===")
    for label, pts in groups.items():
        dists, hit_aoi = [], []
        for lon, lat in pts:
            d2 = (gx - lon * mlon) ** 2 + (gy - lat * mlat) ** 2
            i = int(np.argmin(d2))
            dists.append(math.sqrt(d2[i]))
            hit_aoi.append(aoi_arr[i])
        d = np.array(dists)
        print(f"\n{label}  (n={len(d)})")
        print(f"  median {np.median(d):8.0f} m   "
              f"min {d.min():6.0f}   max {d.max():8.0f}")
        for t in (75, 250, 1000, 5000):
            print(f"  within {t:5d} m: {int((d <= t).sum()):3d} sites")
        print("  nearest AOI: " + ", ".join(
            f"{a}={c}" for a, c in Counter(hit_aoi).most_common()))

    # ---------- step 2: score only what genuinely falls inside ----------
    print("\n=== SUITABILITY, SITES WITHIN 250 m OF A CELL ===")
    print("percentile is computed within the AOI the site matched\n")
    for label, pts in groups.items():
        rows = []
        for lon, lat in pts:
            d2 = (gx - lon * mlon) ** 2 + (gy - lat * mlat) ** 2
            i = int(np.argmin(d2))
            if math.sqrt(d2[i]) > 250:
                continue
            a = aoi_arr[i]
            s = float(suit[i])
            rows.append((a, s, 100.0 * (per_aoi[a] < s).mean()))
        if len(rows) < 5:
            print(f"{label:20s} n={len(rows)} -- too few to interpret. "
                  f"Do NOT report a percentile.")
            for a, s, p in rows:
                print(f"{'':20s}   {a} suit={s:.3f} pct={p:.0f}")
            continue
        p = np.array([r[2] for r in rows])
        s = np.array([r[1] for r in rows])
        print(f"{label:20s} n={len(rows)}")
        print(f"{'':20s}   suit median {np.median(s):.3f}")
        print(f"{'':20s}   pct  median {np.median(p):5.1f}  "
              f"q1 {np.percentile(p,25):5.1f}  q3 {np.percentile(p,75):5.1f}")
        print("{:20s}   by AOI: {}".format(
            "", ", ".join(f"{a}={c}" for a, c in
                          Counter(r[0] for r in rows).most_common())))

    print("\nIf most sites are still >1000 m from any cell, the finding is")
    print("that the AOI boxes do not cover the surveyed ground. That is a")
    print("scoping result, not a model failure. Next step would be to extend")
    print("an AOI over the dive sites and re-run steps 1-2.")


if __name__ == "__main__":
    main()