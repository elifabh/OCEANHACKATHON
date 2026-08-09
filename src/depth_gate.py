"""
depth_gate.py -- build step 3.

How much of the assessed area survives the physical constraint on the only
wave-attenuation coefficient we have?

Dubi & Torum (1996): k = 0.0658*exp(-0.5*D), measured at D = 4-10 m,
12 plants/m2. They state attenuation is "almost negligible" beyond 10 m.

Run:  python src/depth_gate.py
Read-only.
"""

from pathlib import Path
import math

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PRED = REPO / "outputs" / "model" / "suitability_multisite_predictions.csv"

CELL_HA = 0.25          # 50 m grid
D_MAX = 10.0            # Dubi & Torum validity limit
D_MIN = 4.0             # shallow end of their tested range

# Species constraint (locked): MERC 2007 records Saccharina / Saccorhiza at
# inner Roaringwater, not L. hyperborea. Their coefficients cannot be applied.
WRONG_SPECIES = {"inner_roaringwater"}


def main():
    d = pd.read_csv(PRED)
    if "depth_m" not in d.columns:
        raise SystemExit("no depth_m column -- re-run step 2 with the feature patch")

    a = d[d.assessed == 1].copy()
    print(f"assessed cells: {len(a):,}  ({len(a)*CELL_HA:,.1f} ha)\n")

    # The threshold is chosen per run, so read it rather than hard-coding.
    import json
    rep = json.loads((PRED.parent / "model_multisite_report.json").read_text())
    thr = rep["operating_threshold"]
    print(f"operating threshold this run: {thr}\n")

    print("=== depth bands, assessed cells (ha) ===")
    bands = [(-99, 4, "< 4 m  (below tested range)"),
             (4, 10, "4-10 m (VALID)"),
             (10, 20, "10-20 m"),
             (20, 999, "> 20 m")]
    rowsum = []
    for lo, hi, lab in bands:
        sel = a[(a.depth_m > lo) & (a.depth_m <= hi)]
        by = sel.groupby("aoi").size() * CELL_HA
        rowsum.append((lab, len(sel) * CELL_HA, dict(by)))
        print(f"  {lab:30s} {len(sel)*CELL_HA:8.1f} ha   {dict(by.round(1))}")

    print("\n=== the funnel ===")
    steps = [
        ("assessed", a),
        (f"+ suitability >= {thr}", a[a.suitability >= thr]),
        (f"+ depth <= {D_MAX} m", a[(a.suitability >= thr) & (a.depth_m <= D_MAX)]),
        (f"+ depth >= {D_MIN} m", a[(a.suitability >= thr) & (a.depth_m <= D_MAX)
                                    & (a.depth_m >= D_MIN)]),
        ("+ correct species (drop inner_roaringwater)",
         a[(a.suitability >= thr) & (a.depth_m <= D_MAX) & (a.depth_m >= D_MIN)
           & (~a.aoi.isin(WRONG_SPECIES))]),
    ]
    for lab, sel in steps:
        print(f"  {lab:46s} {len(sel):6,d} cells  {len(sel)*CELL_HA:8.1f} ha")

    final = steps[-1][1]
    print("\n=== what survives, by AOI ===")
    if final.empty:
        print("  NOTHING. The physically valid, species-valid area is empty.")
        print("  This is a result, not a bug. Report it.")
    else:
        for aoi, g in final.groupby("aoi"):
            k = 0.0658 * (g.depth_m.map(lambda D: math.exp(-0.5 * D)))
            half = 0.693 / k          # metres of kelp for 50% wave height loss
            print(f"  {aoi}: {len(g)} cells = {len(g)*CELL_HA:.1f} ha")
            print(f"    depth  median {g.depth_m.median():.1f} m "
                  f"(range {g.depth_m.min():.1f}-{g.depth_m.max():.1f})")
            print(f"    bed width needed for 50% wave height loss: "
                  f"median {half.median():,.0f} m "
                  f"(range {half.min():,.0f}-{half.max():,.0f})")
            print("    >>> compare against the ACTUAL bed width. If the bed is "
                  "narrower,\n        the real attenuation is far below 50%.")


if __name__ == "__main__":
    main()