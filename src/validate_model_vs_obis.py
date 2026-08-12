#!/usr/bin/env python3
"""
Step 2 validation, using the OBIS diver records found in step 4.

WHY THIS MATTERS
Roaringwater Bay was the held-out site in the multi-site model. LOSO AUC 0.830
was computed on the training sites. This is the first time the model meets
independent field observations inside the demo area.

WHAT IT CAN AND CANNOT SHOW
The 35 Marine Recorder sites are PRESENCE ONLY. A dive site without
L. hyperborea is not an absence -- the diver may not have looked, or recorded
only conspicuous taxa. So:
  - AUC / accuracy CANNOT be computed. Do not report one.
  - What CAN be measured: the suitability the model assigns at known-present
    locations, against the distribution of suitability across the whole AOI.
    If the model is informative, presence sites sit high in that distribution.
The comparison used here is the percentile rank of each presence site within
the AOI's suitability values. A median percentile near 50 means the model is
no better than random; near 90+ means it is picking out real kelp ground.

The 45 "any kelp" sites and 37 "no kelp" sites are also scored, as a weak
secondary check -- weak because "no kelp recorded" is not "no kelp present".

Usage:
    python src/validate_model_vs_obis.py

Requires: pandas, requests, numpy
NOT TESTED. Grid matching uses nearest-cell within a tolerance; if the model
grid is 50 m, a dive coordinate should always find a cell.
"""

import math
from collections import defaultdict

import numpy as np
import pandas as pd
import requests

BASE = "https://api.obis.org/v3"
WKT = (
    "POLYGON((-9.65359 51.39842, -9.65359 51.54624, "
    "-9.36648 51.54624, -9.36648 51.39842, -9.65359 51.39842))"
)
PRED = "outputs/model/v1_20260727/suitability_multisite_predictions.csv"

DIVE_DATASETS = [
    "6d7b384f-090b-4c15-b68d-4c1192c0f8a6",  # Marine Recorder / JNCC
    "953e0d26-24e8-4797-b944-8aa7fe2ea937",  # Marine Recorder / NMNI
    "3e981ea4-29b3-4df5-8529-38d798262eb1",  # Marine Recorder / SeaSearch
]
TARGET = "Laminaria hyperborea"
ANY_KELP = {
    "Laminaria hyperborea", "Laminaria digitata", "Saccharina latissima",
    "Saccorhiza polyschides", "Alaria esculenta",
}
MATCH_TOL_M = 75.0   # a dive coord must fall within this of a grid cell centre


def page(datasetid, size=5000, max_pages=10):
    out, seen, offset = [], set(), 0
    for _ in range(max_pages):
        r = requests.get(
            f"{BASE}/occurrence",
            params={"geometry": WKT, "datasetid": datasetid,
                    "size": size, "offset": offset}, timeout=180)
        if r.status_code != 200:
            print(f"!! HTTP {r.status_code} {r.text[:200]}")
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
    # ---------- model grid ----------
    df = pd.read_csv(PRED)
    print(f"predictions: {len(df)} cells, AOIs: {sorted(df.aoi.unique())}")

    aois = [a for a in df.aoi.unique() if "roaring" in a.lower()]
    if not aois:
        print("!! no AOI name contains 'roaring'. Available:",
              sorted(df.aoi.unique()))
        print("!! edit the filter below before trusting anything.")
        return
    print(f"using AOIs: {aois}")
    g = df[df.aoi.isin(aois)].reset_index(drop=True)
    print(f"cells in those AOIs: {len(g)}")
    print(f"suitability: min={g.suitability.min():.4f} "
          f"median={g.suitability.median():.4f} max={g.suitability.max():.4f}")

    lat0 = float(g.lat.mean())
    mlon = 111320.0 * math.cos(math.radians(lat0))
    mlat = 110540.0
    gx = g.lon.values * mlon
    gy = g.lat.values * mlat
    vals = g.suitability.values

    # ---------- dive sites ----------
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
        "L. hyperborea present": [k for k, v in sites.items() if TARGET in v],
        "any kelp present": [k for k, v in sites.items() if v & ANY_KELP],
        "no kelp recorded": [k for k, v in sites.items() if not (v & ANY_KELP)],
    }

    print("\n=== MODEL SUITABILITY AT DIVE SITES ===")
    print("percentile = rank of that site's suitability within all AOI cells\n")

    for label, pts in groups.items():
        s_vals, pcts, unmatched = [], [], 0
        for lon, lat in pts:
            d2 = (gx - lon * mlon) ** 2 + (gy - lat * mlat) ** 2
            i = int(np.argmin(d2))
            if math.sqrt(d2[i]) > MATCH_TOL_M:
                unmatched += 1
                continue
            s = float(vals[i])
            s_vals.append(s)
            pcts.append(100.0 * (vals < s).mean())
        if not s_vals:
            print(f"{label:24s} no sites matched a grid cell")
            continue
        print(f"{label:24s} n={len(s_vals):3d}  (unmatched {unmatched})")
        print(f"{'':24s}   suitability median={np.median(s_vals):.4f}")
        print(f"{'':24s}   percentile   median={np.median(pcts):5.1f}  "
              f"q1={np.percentile(pcts,25):5.1f}  q3={np.percentile(pcts,75):5.1f}")
        print(f"{'':24s}   share above 90th pct: "
              f"{100*np.mean(np.array(pcts)>90):.0f}%")
        print(f"{'':24s}   share below 50th pct: "
              f"{100*np.mean(np.array(pcts)<50):.0f}%\n")

    print("READ IT LIKE THIS:")
    print("  presence median percentile >= 85  -> model validated on held-out site")
    print("  presence median around 50         -> model is not informative here")
    print("  many presences below 50th pct     -> model misses real kelp ground;")
    print("                                       inspect those sites on a map")


if __name__ == "__main__":
    main()