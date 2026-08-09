"""
bed_width.py -- build step 3.

The gate depth_gate.py could not close: Dubi & Torum's k is a decay rate per
metre. Attenuation depends on how far the wave actually travels through kelp.
A 9.8 ha patch scattered as singletons delivers almost nothing; the same area
as one continuous band delivers a lot.

Method (48-hour prototype, stated as such):
  - "kelp" = assessed AND suitability >= operating threshold, at any depth.
    Deeper cells are included because waves do travel through them, just with
    a small k.
  - Through every cell, measure the contiguous run of kelp cells along each of
    the four grid axes (E-W, N-S, and both diagonals), in both directions.
  - For each run, integrate the decay using each traversed cell's OWN depth:
        H_out / H_in = exp( -sum_i k(D_i) * step_i )
    with k(D) = 0.0658 * exp(-0.5 * D) and step = 50 m (70.7 m on diagonals).
  - Report the BEST of the four axes per cell. That is an upper bound on what
    any wave direction could achieve, so if it is small the conclusion is
    robust to not knowing the wave direction.

Simplifications to declare:
  - No wave transformation between the bed and the shoreline.
  - Stem density assumed at the Dubi & Torum reference of 12 plants/m2.
  - k extrapolated outside their tested 4-10 m range; flagged in the output.

Run:  python src/bed_width.py
Read-only.
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
CELL_HA = (CELL_M * CELL_M) / 10_000.0
D_VALID = (4.0, 10.0)
WRONG_SPECIES = {"inner_roaringwater"}

# four axes as (dx, dy); diagonals travel sqrt(2) further per step
AXES = [((1, 0), "E-W"), ((0, 1), "N-S"), ((1, 1), "NE-SW"), ((1, -1), "NW-SE")]


def k_dubi_torum(depth_m):
    """Wave height decay rate, m^-1. Dubi & Torum (1996) fitted curve."""
    return 0.0658 * math.exp(-0.5 * depth_m)


def grid_index(sub):
    """Map lon/lat onto integer grid indices for one AOI."""
    lon, lat = sub.lon.to_numpy(), sub.lat.to_numpy()
    dlat = CELL_M / 111_320.0
    dlon = dlat / math.cos(math.radians(float(np.median(lat))))
    ix = np.rint((lon - lon.min()) / dlon).astype(int)
    iy = np.rint((lat - lat.min()) / dlat).astype(int)
    return ix, iy


def main():
    d = pd.read_csv(PRED)
    thr = json.loads((MODEL / "model_multisite_report.json").read_text())["operating_threshold"]
    print(f"operating threshold: {thr}\n")

    kelp = d[(d.assessed == 1) & (d.suitability >= thr)].copy()
    print(f"kelp cells (any depth): {len(kelp):,}  ({len(kelp)*CELL_HA:.1f} ha)\n")

    out = []
    for aoi, sub in kelp.groupby("aoi"):
        sub = sub.reset_index(drop=True)
        ix, iy = grid_index(sub)
        depth = sub.depth_m.to_numpy()

        # cell lookup -> row position
        pos = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(ix, iy))}

        # sanity: duplicate grid cells would silently break the walk
        if len(pos) != len(sub):
            print(f"  ! {aoi}: {len(sub)-len(pos)} cells collided on the grid index")

        for i in range(len(sub)):
            best = None
            for (dx, dy), label in AXES:
                step = CELL_M * math.hypot(dx, dy)
                run_cells = [i]
                for sign in (1, -1):
                    x, y = int(ix[i]), int(iy[i])
                    while True:
                        x, y = x + sign * dx, y + sign * dy
                        j = pos.get((x, y))
                        if j is None:
                            break
                        run_cells.append(j)
                # integrate decay over every cell in the run
                total = sum(k_dubi_torum(depth[j]) * step for j in run_cells)
                red = 1.0 - math.exp(-total)          # wave HEIGHT reduction
                if best is None or red > best[0]:
                    best = (red, len(run_cells), len(run_cells) * step, label)
            red, ncell, width_m, label = best
            out.append({
                "aoi": aoi, "lon": sub.lon[i], "lat": sub.lat[i],
                "depth_m": round(float(depth[i]), 2),
                "run_cells": ncell,
                "bed_width_m": round(width_m, 1),
                "best_axis": label,
                "H_reduction": round(red, 4),
                "E_reduction": round(1 - (1 - red) ** 2, 4),
                "depth_in_valid_range": int(D_VALID[0] <= depth[i] <= D_VALID[1]),
            })

    res = pd.DataFrame(out)
    p = MODEL / "bed_width_attenuation.csv"
    res.to_csv(p, index=False)
    print(f"written: {p}\n")

    print("=== bed width, all kelp cells ===")
    for aoi, g in res.groupby("aoi"):
        print(f"  {aoi}: n={len(g)}  width median {g.bed_width_m.median():,.0f} m "
              f"(max {g.bed_width_m.max():,.0f} m)   "
              f"H reduction median {g.H_reduction.median():.1%}")

    print("\n=== the cells that passed the depth gate ===")
    g = res[(res.depth_in_valid_range == 1) & (~res.aoi.isin(WRONG_SPECIES))]
    if g.empty:
        print("  none")
        return
    print(f"  {len(g)} cells = {len(g)*CELL_HA:.1f} ha, all in {sorted(g.aoi.unique())}")
    print(f"  bed width      median {g.bed_width_m.median():,.0f} m  "
          f"(range {g.bed_width_m.min():,.0f}-{g.bed_width_m.max():,.0f})")
    print(f"  wave HEIGHT reduction  median {g.H_reduction.median():.1%}  "
          f"(range {g.H_reduction.min():.1%}-{g.H_reduction.max():.1%})")
    print(f"  wave ENERGY reduction  median {g.E_reduction.median():.1%}")
    print("\n  >>> Compare against the headline '50%' often quoted from")
    print("  >>> Dubi & Torum. If this is far below 50%, that is the honest")
    print("  >>> number and the 50% must never appear as our result.")


if __name__ == "__main__":
    main()