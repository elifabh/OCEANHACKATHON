#!/usr/bin/env python3
"""
cluster_fetch_check.py — step 3B2 prerequisite.

QUESTION THIS ANSWERS
---------------------
The 39 depth-gated sherkin_baltimore cells ("9.8 ha") are not one bed. They sit
in spatially separate groups, and group-level wave attenuation differs by
roughly a factor of eight (~9% vs ~73% wave-height reduction).

The hypothesis is that the high-attenuation groups are the ones sheltered from
Atlantic swell by Sherkin Island itself. If true, the headline 42.7% figure is
driven by cells the swell cannot reach, and the "Atlantic shield" framing does
not apply to them.

This script tests that hypothesis against the model's own `log10_fetch` feature
rather than against a visual reading of a map.

WHAT IT DOES
------------
1. Loads bed_width_by_axis.csv. This file holds every cell above the step-2
   operating threshold (599 rows; 126 in sherkin_baltimore), i.e. the whole
   predicted bed, not only the depth-gated subset.
2. Clusters the WHOLE predicted bed for the AOI by physical contiguity
   (single-linkage union-find, default 100 m link = touching incl. diagonals).
   Clustering only the 39 gated cells would invent fragmentation that is an
   artefact of the depth gate, not of the bed.
3. Joins log10_fetch from the step-2 prediction CSV on rounded lon/lat.
4. Reports per cluster: size, depth, log10_fetch, and wave-height reduction on
   all four axes, for the whole cluster and for its depth-valid subset.
5. Reports reference fetch distributions so cluster values can be read on a
   scale.

INTERPRETATION
--------------
log10_fetch is a relative exposure index, not metres of open water. It only
carries meaning by comparison. Low fetch = sheltered = local wind sea rather
than Atlantic swell. If the highest-attenuation cluster also has the lowest
fetch, the hypothesis is confirmed and the defensible headline becomes the
exposed cluster's number.

This script performs no modelling and produces no euro figure.

Usage:
    python src/cluster_fetch_check.py
    python src/cluster_fetch_check.py --link-m 150
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CELL_HA = 0.25  # 50 m x 50 m grid cell
AXES = ["E-W", "N-S", "NE-SW", "NW-SE"]

# Candidate coordinate column names in the prediction CSV. The prediction
# writer was patched after the fact, so exact names are not assumed.
LON_CANDIDATES = ["lon", "longitude", "x", "lon_deg", "cx", "centroid_lon"]
LAT_CANDIDATES = ["lat", "latitude", "y", "lat_deg", "cy", "centroid_lat"]


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def to_local_metres(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Local equirectangular projection, adequate for <10 km clustering.

    NOT for area or distance reporting — EPSG:2157 is the project rule there.
    Used only to decide which cells touch which.
    """
    lat0 = float(np.mean(lat))
    x = (lon - float(np.mean(lon))) * 111_320.0 * math.cos(math.radians(lat0))
    y = (lat - lat0) * 111_132.0
    return np.column_stack([x, y])


def single_linkage_clusters(xy: np.ndarray, link_m: float) -> np.ndarray:
    """Union-find connected components. Two cells join if within link_m."""
    n = len(xy)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        d = np.hypot(xy[i + 1 :, 0] - xy[i, 0], xy[i + 1 :, 1] - xy[i, 1])
        for off in np.nonzero(d <= link_m)[0]:
            union(i, i + 1 + int(off))

    roots = np.array([find(i) for i in range(n)])
    # Relabel 1..k, ordered south to north by cluster mean y.
    order = sorted(set(roots.tolist()), key=lambda r: float(np.mean(xy[roots == r, 1])))
    remap = {r: i + 1 for i, r in enumerate(order)}
    return np.array([remap[r] for r in roots])


# ---------------------------------------------------------------------------
# fetch join
# ---------------------------------------------------------------------------
def pick_col(df: pd.DataFrame, candidates: list, what: str) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    sys.exit(
        f"ERROR: no {what} column found in the prediction CSV.\n"
        f"  tried: {candidates}\n"
        f"  found: {list(df.columns)}"
    )


def attach_fetch(cells: pd.DataFrame, pred_path: Path, dp: int):
    """Join log10_fetch onto the cells. Fails loudly, never silently."""
    cells = cells.copy()
    if not pred_path.exists():
        print(f"WARNING: {pred_path} not found. Running without fetch — the "
              f"main question cannot be answered.\n")
        cells["log10_fetch"] = np.nan
        return cells, None

    pred = pd.read_csv(pred_path)
    if "log10_fetch" not in pred.columns:
        sys.exit(
            "ERROR: log10_fetch is not in the prediction CSV. The step-2 feature "
            "persistence patch has not been applied to this file.\n"
            f"  columns: {list(pred.columns)}"
        )

    lon_c = pick_col(pred, LON_CANDIDATES, "longitude")
    lat_c = pick_col(pred, LAT_CANDIDATES, "latitude")

    p = pred[[lon_c, lat_c, "log10_fetch"]].copy()
    p["_k"] = list(zip(p[lon_c].round(dp), p[lat_c].round(dp)))
    p = p.drop_duplicates("_k")

    cells["_k"] = list(zip(cells["lon"].round(dp), cells["lat"].round(dp)))
    merged = cells.merge(p[["_k", "log10_fetch"]], on="_k", how="left")

    missing = int(merged["log10_fetch"].isna().sum())
    if missing:
        print(f"WARNING: {missing}/{len(merged)} cells got no fetch value at "
              f"{dp} dp. Retry with --join-dp {dp - 1}. Do not interpret "
              f"partial results.\n")
    return merged.drop(columns="_k"), pred


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def describe(s: pd.Series) -> str:
    s = s.dropna()
    if s.empty:
        return "         n/a"
    return f"{s.median():6.2f} [{s.min():6.2f} – {s.max():6.2f}]"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--bed", default="outputs/model/bed_width_by_axis.csv")
    ap.add_argument("--pred", default="outputs/model/suitability_multisite_predictions.csv")
    ap.add_argument("--out", default="outputs/model/cluster_fetch_check.csv")
    ap.add_argument("--aoi", default="sherkin_baltimore")
    ap.add_argument("--link-m", type=float, default=100.0,
                    help="max gap still counted as one bed, m (100 = touching incl. diagonal)")
    ap.add_argument("--join-dp", type=int, default=6, help="decimal places for lon/lat matching")
    ap.add_argument("--min-cells", type=int, default=2,
                    help="clusters smaller than this are pooled into a 'scattered' row")
    args = ap.parse_args()

    bed_path = Path(args.bed)
    if not bed_path.exists():
        sys.exit(f"ERROR: {bed_path} not found.")

    bed = pd.read_csv(bed_path)
    cells = bed[bed["aoi"] == args.aoi].reset_index(drop=True)
    if cells.empty:
        sys.exit(f"ERROR: no cells for aoi={args.aoi}.")

    valid = cells[cells["in_valid_depth"] == 1]

    # --- self-check against the handover note -----------------------------
    print("=" * 78)
    print("INPUT CHECK")
    print("=" * 78)
    print(f"  predicted bed cells    {len(cells):4d}     ({len(cells) * CELL_HA:.2f} ha)")
    print(f"  depth-valid cells      {len(valid):4d}     ({len(valid) * CELL_HA:.2f} ha)"
          f"   handover note: 39 / 9.8 ha")
    h_med = float(valid["H_red_NE-SW"].median())
    print(f"  median H_red NE-SW    {h_med:.4f}     handover note: 0.4269")
    if len(valid) != 39 or abs(h_med - 0.4269) > 0.001:
        print("  >> MISMATCH — this is not the file the note describes. Stop and check.")
    print()

    # --- cluster the WHOLE predicted bed ----------------------------------
    xy = to_local_metres(cells["lon"].to_numpy(), cells["lat"].to_numpy())
    cells["cluster"] = single_linkage_clusters(xy, args.link_m)
    cells, pred = attach_fetch(cells, Path(args.pred), args.join_dp)

    sizes = cells["cluster"].value_counts()
    big = sorted([c for c in sizes.index if sizes[c] >= args.min_cells])
    small = [c for c in sizes.index if sizes[c] < args.min_cells]
    cells["group"] = cells["cluster"].apply(lambda c: f"C{c:02d}" if c in big else "scattered")

    print("=" * 78)
    print(f"CLUSTERS OF THE PREDICTED BED  (single linkage, {args.link_m:.0f} m link)")
    print(f"  {len(big)} clusters of >={args.min_cells} cells, "
          f"{len(small)} isolated cells pooled as 'scattered'")
    print("=" * 78)

    rows = []
    for gname, d in cells.groupby("group"):
        dv = d[d["in_valid_depth"] == 1]
        print(f"\n  {gname}   bed {len(d):3d} cells / {len(d)*CELL_HA:6.2f} ha"
              f"   |   depth-valid {len(dv):2d} cells / {len(dv)*CELL_HA:5.2f} ha")
        print(f"    centroid              {d['lat'].mean():.4f} N, {abs(d['lon'].mean()):.4f} W")
        print(f"    depth m  (bed)        {describe(d['depth_m'])}")
        print(f"    log10_fetch (bed)     {describe(d['log10_fetch'])}   <-- EXPOSURE")
        if len(dv):
            for ax in AXES:
                mark = "   <-- swell axis" if ax == "NE-SW" else ""
                print(f"    H_red {ax:<6} (valid) {describe(dv[f'H_red_{ax}'] * 100)} %{mark}")
        else:
            print("    H_red                 no depth-valid cells — not assessed")

        rec = {
            "group": gname,
            "bed_cells": len(d),
            "bed_area_ha": round(len(d) * CELL_HA, 2),
            "valid_cells": len(dv),
            "valid_area_ha": round(len(dv) * CELL_HA, 2),
            "centroid_lat": round(float(d["lat"].mean()), 5),
            "centroid_lon": round(float(d["lon"].mean()), 5),
            "depth_m_median": round(float(d["depth_m"].median()), 2),
        }
        if d["log10_fetch"].notna().any():
            rec["log10_fetch_median"] = round(float(d["log10_fetch"].median()), 3)
            rec["log10_fetch_min"] = round(float(d["log10_fetch"].min()), 3)
            rec["log10_fetch_max"] = round(float(d["log10_fetch"].max()), 3)
        if len(dv):
            for ax in AXES:
                rec[f"H_red_{ax}_median"] = round(float(dv[f"H_red_{ax}"].median()), 4)
            m = float(dv["H_red_NE-SW"].median())
            rec["energy_red_NESW_median"] = round(1 - (1 - m) ** 2, 4)
        rows.append(rec)

    # --- reference scale ---------------------------------------------------
    if pred is not None and cells["log10_fetch"].notna().any():
        print("\n" + "=" * 78)
        print("REFERENCE SCALE  (log10_fetch is relative — meaningless in isolation)")
        print("=" * 78)
        if "aoi" in pred.columns:
            for aoi, d in pred.groupby("aoi"):
                print(f"  all predicted cells, {aoi:<22} {describe(d['log10_fetch'])}")
        print(f"  all predicted cells, every AOI       {describe(pred['log10_fetch'])}")
        print()
        print("  How to read it: the LOWEST-fetch cluster is the most sheltered.")
        print("  If that cluster also shows the HIGHEST attenuation, then the 42.7%")
        print("  headline comes from cells Atlantic swell cannot reach, and the")
        print("  defensible headline is the exposed cluster's number instead.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    cells_out = out.with_name(out.stem + "_cells.csv")
    cells.to_csv(cells_out, index=False)
    print(f"\nWrote {out}")
    print(f"Wrote {cells_out}")
    print(f"\nCommand: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()