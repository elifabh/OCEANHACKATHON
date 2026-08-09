"""
find_depth.py  -- build step 3, pre-flight check.

Question this answers: did step 2 save the per-cell feature table (depth_m),
or was it computed in memory and discarded?

Run from the repo root:
    python src/find_depth.py

Read-only. Writes nothing, changes nothing.
"""

from pathlib import Path
import sys

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUTPUTS = REPO / "outputs"
PRED = OUTPUTS / "model" / "suitability_multisite_predictions.csv"

WANTED = "depth_m"
COORDS = ("lon", "lat")


def read_head(path, n=5):
    """Read a few rows of any tabular file we might have written."""
    suf = path.suffix.lower()
    try:
        if suf == ".csv":
            return pd.read_csv(path, nrows=n)
        if suf in (".parquet", ".pq"):
            return pd.read_parquet(path).head(n)
        if suf in (".gpkg", ".geojson", ".shp"):
            import geopandas as gpd
            return gpd.read_file(path, rows=n)
    except Exception as exc:
        print(f"    ! could not read: {type(exc).__name__}: {exc}")
    return None


def main():
    if not OUTPUTS.exists():
        sys.exit(f"outputs/ not found at {OUTPUTS} -- run this from the repo root.")

    print(f"repo: {REPO}\n")
    print("=== 1. every tabular file under outputs/ ===")

    candidates = []
    exts = {".csv", ".parquet", ".pq", ".gpkg", ".geojson", ".shp"}
    for p in sorted(OUTPUTS.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in exts):
            continue
        mb = p.stat().st_size / 1e6
        print(f"\n  {p.relative_to(REPO)}  ({mb:.1f} MB)")
        head = read_head(p)
        if head is None:
            continue
        cols = list(head.columns)
        print(f"    columns: {cols}")
        if WANTED in cols:
            has_xy = all(c in cols for c in COORDS)
            print(f"    >>> HAS {WANTED}. lon/lat present: {has_xy}")
            candidates.append((p, has_xy))

    print("\n=== 2. verdict ===")
    if not candidates:
        print(f"  No file contains '{WANTED}'.")
        print("  => step 2 did not persist the feature table.")
        print("     Fix: re-run step 2 with an extra to_csv of the feature grid.")
        return

    print(f"  Found {len(candidates)} file(s) with '{WANTED}':")
    for p, has_xy in candidates:
        print(f"    - {p.relative_to(REPO)}  (joinable on lon/lat: {has_xy})")

    # If we have a joinable candidate, test the join for real.
    joinable = [p for p, ok in candidates if ok]
    if not joinable or not PRED.exists():
        return

    print("\n=== 3. join test against the prediction CSV ===")
    pred = pd.read_csv(PRED)
    src = joinable[0]
    feat = pd.read_parquet(src) if src.suffix.lower() in (".parquet", ".pq") else pd.read_csv(src)
    print(f"  source: {src.relative_to(REPO)}  rows={len(feat):,}   predictions rows={len(pred):,}")

    # Coordinate precision decides whether an exact key match is safe.
    def decimals(s):
        return (s.astype(str).str.split(".").str[-1].str.len()).max()

    print(f"  lon decimals -- predictions: {decimals(pred.lon)}, source: {decimals(feat.lon)}")

    keys = ["lon", "lat"] + (["aoi"] if "aoi" in feat.columns and "aoi" in pred.columns else [])
    print(f"  join keys: {keys}")

    for nd in (6, 5, 4):
        left = pred.assign(lon=pred.lon.round(nd), lat=pred.lat.round(nd))
        right = feat.assign(lon=feat.lon.round(nd), lat=feat.lat.round(nd))
        right = right[keys + [WANTED]].drop_duplicates(subset=keys)
        merged = left.merge(right, on=keys, how="left")
        matched = merged[WANTED].notna().sum()
        assessed_matched = merged.loc[merged.assessed == 1, WANTED].notna().sum()
        n_assessed = int((pred.assessed == 1).sum())
        print(
            f"    round to {nd} dp -> matched {matched:,}/{len(pred):,} "
            f"({100 * matched / len(pred):.1f}%)   "
            f"assessed cells matched {assessed_matched:,}/{n_assessed:,}"
        )

    print("\n  Need 100% of assessed cells matched before any euro figure is computed.")


if __name__ == "__main__":
    main()