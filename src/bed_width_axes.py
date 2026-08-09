"""
bed_width_axes.py -- build step 3, sensitivity check.

bed_width.py reported the BEST of four grid axes. That is an upper bound, not
an estimate: it silently picks whichever direction happens to have the longest
run of kelp. West Cork's dominant swell is from the southwest, so the NE-SW
axis is the one that matters physically.

This reports every axis separately so the spread is visible.

Run:  python src/bed_width_axes.py
Read-only apart from one CSV.
"""

from pathlib import Path
import json
import math

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
MODEL = REPO / "outputs" / "model"
PRED = MODEL / "suitability_multisite_predictions.csv"

CELL_M = 50.0
CELL_HA = 0.25
D_VALID = (4.0, 10.0)
WRONG_SPECIES = {"inner_roaringwater"}
AXES = [((1, 0), "E-W"), ((0, 1), "N-S"),
        ((1, 1), "NE-SW"), ((1, -1), "NW-SE")]
SWELL_AXIS = "NE-SW"        # Atlantic swell approaches from the SW


def k_dt(depth_m):
    return 0.0658 * math.exp(-0.5 * depth_m)


def main():
    d = pd.read_csv(PRED)
    thr = json.loads((MODEL / "model_multisite_report.json").read_text())["operating_threshold"]
    kelp = d[(d.assessed == 1) & (d.suitability >= thr)].copy()

    rows = []
    for aoi, sub in kelp.groupby("aoi"):
        sub = sub.reset_index(drop=True)
        lon, lat = sub.lon.to_numpy(), sub.lat.to_numpy()
        dlat = CELL_M / 111_320.0
        dlon = dlat / math.cos(math.radians(float(np.median(lat))))
        ix = np.rint((lon - lon.min()) / dlon).astype(int)
        iy = np.rint((lat - lat.min()) / dlat).astype(int)
        depth = sub.depth_m.to_numpy()
        pos = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(ix, iy))}

        for i in range(len(sub)):
            rec = {"aoi": aoi, "lon": lon[i], "lat": lat[i],
                   "depth_m": round(float(depth[i]), 2),
                   "in_valid_depth": int(D_VALID[0] <= depth[i] <= D_VALID[1])}
            for (dx, dy), label in AXES:
                step = CELL_M * math.hypot(dx, dy)
                run = [i]
                for sign in (1, -1):
                    x, y = int(ix[i]), int(iy[i])
                    while True:
                        x, y = x + sign * dx, y + sign * dy
                        j = pos.get((x, y))
                        if j is None:
                            break
                        run.append(j)
                tot = sum(k_dt(depth[j]) * step for j in run)
                rec[f"width_{label}"] = round(len(run) * step, 1)
                rec[f"H_red_{label}"] = round(1 - math.exp(-tot), 4)
            rows.append(rec)

    res = pd.DataFrame(rows)
    p = MODEL / "bed_width_by_axis.csv"
    res.to_csv(p, index=False)
    print(f"written: {p}\n")

    g = res[(res.in_valid_depth == 1) & (~res.aoi.isin(WRONG_SPECIES))]
    print(f"=== the {len(g)} cells that passed the depth gate "
          f"({len(g)*CELL_HA:.1f} ha) ===\n")
    print(f"  {'axis':8s} {'width median':>14s} {'H reduction median':>20s} {'range':>18s}")
    for _, label in AXES:
        w = g[f"width_{label}"]
        h = g[f"H_red_{label}"]
        star = "  <-- SWELL" if label == SWELL_AXIS else ""
        print(f"  {label:8s} {w.median():11,.0f} m {h.median():19.1%} "
              f"{h.min():7.1%}-{h.max():.1%}{star}")

    best = g[[f"H_red_{l}" for _, l in AXES]].max(axis=1)
    swell = g[f"H_red_{SWELL_AXIS}"]
    print(f"\n  best-of-four median : {best.median():.1%}   <- what bed_width.py reported")
    print(f"  swell axis median   : {swell.median():.1%}   <- the defensible number")
    print(f"  inflation from picking the best axis: "
          f"{(best.median() - swell.median()):.1f} percentage points")

    print("\n  Caveats that still apply to the swell-axis number:")
    print("   - assumes 12 plants/m2 (Dubi & Torum reference); we have no density data")
    print("   - assumes every cell above threshold really is kelp; sherkin external FPR 31.3%")
    print("   - this is the reduction across the bed, NOT at the shoreline:")
    print("     shoaling and breaking between the bed and the coast are not modelled")


if __name__ == "__main__":
    main()