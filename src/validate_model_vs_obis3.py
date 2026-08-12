#!/usr/bin/env python3
"""
Step 2 validation v3. One fix, and it matters.

FAULT - v2 pooled percentiles across inner_roaringwater and sherkin_baltimore.
        Those AOIs behave completely differently:
          inner_roaringwater  median suitability 0.886  -> saturated, the model
                              calls nearly the whole AOI suitable, so a
                              percentile there carries almost no information.
                              It is also the AOI locked out of positive
                              labelling (MERC 2007: Saccharina/Saccorhiza).
          sherkin_baltimore   median suitability 0.003  -> the model is
                              discriminating here. A presence landing high in
                              THIS AOI is real evidence.
        Pooling the two averages a meaningful test with a meaningless one.

This script reports each AOI separately and prints every individual site, so
nothing hides behind a median computed from n=6.

Usage:
    python src/validate_model_vs_obis3.py
"""

import math
from collections import defaultdict

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
TOL_M = 250.0


def page(datasetid, size=5000, max_pages=10):
    out, seen, offset = [], set(), 0
    for _ in range(max_pages):
        r = requests.get(f"{BASE}/occurrence",
                         params={"geometry": WKT, "datasetid": datasetid,
                                 "size": size, "offset": offset}, timeout=180)
        if r.status_code != 200:
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
    lat0 = float(df.lat.mean())
    mlon, mlat = 111320.0 * math.cos(math.radians(lat0)), 110540.0

    recs = []
    for d in DIVE_DATASETS:
        recs.extend(page(d))
    sites = defaultdict(set)
    for r in recs:
        lon, lat = r.get("decimalLongitude"), r.get("decimalLatitude")
        if lon is None or lat is None or not r.get("species"):
            continue
        sites[(round(lon, 4), round(lat, 4))].add(r["species"])

    for aoi in sorted(df.aoi.unique()):
        g = df[df.aoi == aoi]
        vals = g.suitability.values
        gx, gy = g.lon.values * mlon, g.lat.values * mlat

        print(f"\n{'='*66}\n{aoi}")
        print(f"  {len(g)} cells   suitability: median {np.median(vals):.4f}   "
              f"90th pct {np.percentile(vals, 90):.4f}   max {vals.max():.4f}")
        frac_hi = float((vals > 0.5).mean())
        print(f"  share of AOI above 0.5: {100*frac_hi:.1f}%")
        if frac_hi > 0.6:
            print("  !! SATURATED -- model calls most of this AOI suitable.")
            print("  !! Percentiles here are weak evidence. Read raw values.")

        for label, want in (("L. hyperborea", "target"),
                            ("any kelp", "any"),
                            ("no kelp recorded", "none")):
            rows = []
            for (lon, lat), sp in sites.items():
                if want == "target" and TARGET not in sp:
                    continue
                if want == "any" and not (sp & ANY_KELP):
                    continue
                if want == "none" and (sp & ANY_KELP):
                    continue
                d2 = (gx - lon * mlon) ** 2 + (gy - lat * mlat) ** 2
                i = int(np.argmin(d2))
                dist = math.sqrt(d2[i])
                if dist > TOL_M:
                    continue
                s = float(vals[i])
                rows.append((lon, lat, dist, s, 100.0 * (vals < s).mean()))

            print(f"\n  {label}: {len(rows)} site(s) within {TOL_M:.0f} m")
            if not rows:
                continue
            for lon, lat, dist, s, p in sorted(rows, key=lambda r: -r[3]):
                print(f"    {lat:.4f},{lon:.4f}  {dist:5.0f} m  "
                      f"suit {s:.4f}  pct {p:5.1f}")
            s_arr = np.array([r[3] for r in rows])
            print(f"    median suit {np.median(s_arr):.4f}")
            if len(rows) < 5:
                print("    (n<5 -- descriptive only, no claim)")

    print(f"\n{'='*66}")
    print("HOW TO READ:")
    print("  sherkin_baltimore is the informative AOI (model median ~0.003).")
    print("  If L. hyperborea sites there sit at 0.8+, the model is finding")
    print("  real kelp ground on a site it never trained on.")
    print("  inner_roaringwater is saturated -- treat as no test.")
    print("  'no kelp recorded' is NOT absence. It cannot falsify the model,")
    print("  only fail to support it.")


if __name__ == "__main__":
    main()