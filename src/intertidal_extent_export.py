#!/usr/bin/env python3
"""
intertidal_extent_export.py - vectorize the detected intertidal class to GeoJSON.

intertidal_test.py answers "is there a detectable intertidal signal?" and writes
a stratified 300-pixel SAMPLE plus a verdict report - deliberately not a map
layer. This script produces the missing spatial product for the step 6 map: the
class-3 (intertidal candidate) mask as polygons.

It does NOT re-decide anything. It rebuilds the identical per-pixel regression
and classification (same candidate CSV, same selection rules, same thresholds,
imported from intertidal_test, so the scene set is deterministic), REQUIRES that
a matching report_*.json with outcome "detected" already exists on disk, and
refuses to write if its own recomputed extent disagrees with that report.

The output is intertidal macroalgae extent, SPECIES-AGNOSTIC (NDVI cannot
separate Fucus/Ascophyllum from Laminaria digitata), UNVALIDATED against ground
truth, and must never be merged with, or styled like, the subtidal suitability
model (CLAUDE.md section 4, prohibitions 3 and 5).

Run from the repo root:  python src/intertidal_extent_export.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, timezone, datetime
from pathlib import Path

import ee

sys.path.insert(0, str(Path(__file__).parent))
from common import AOIS, ATTRIBUTION, EE_PROJECT, PRIMARY_AOI  # noqa: E402
from intertidal_test import (  # noqa: E402
    N_SCENES, OUT_DIR,
    load_candidates, detect_columns, pick_scenes,
    build_ndvi_images, regression_images, classify,
)

AREA_TOLERANCE_HA = 0.1     # vectorization at native scale should be near-exact


def main() -> int:
    aoi_name = PRIMARY_AOI

    report_path = None
    for p in sorted(OUT_DIR.glob(f"report_{aoi_name}_*scenes.json")):
        report_path = p
    if report_path is None:
        raise SystemExit(f"No report_{aoi_name}_*.json in {OUT_DIR}. "
                         f"Run intertidal_test.py first; this script only "
                         f"exports an already-verified detection.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["outcome"] != "detected":
        raise SystemExit(f"{report_path.name} outcome is "
                         f"'{report['outcome']}', not 'detected'. "
                         f"Nothing defensible to export.")
    reported_ha = report["area_ha"]["intertidal"]
    print(f"  report: {report_path.name}  outcome=detected  "
          f"intertidal {reported_ha:.1f} ha")

    df = load_candidates()
    if df is None:
        return 1
    cols = detect_columns(df, None)
    scenes, _ = pick_scenes(df, cols, aoi_name, N_SCENES,
                            allow_multi_year=False)

    ee.Initialize(project=EE_PROJECT)
    ndvi_imgs, used, aoi, proj = build_ndvi_images(AOIS[aoi_name], scenes)
    if [s["date"] for s in used] != [s["date"] for s in report["scenes"]]:
        raise SystemExit("Scene set differs from the report's - the candidate "
                         "CSV must have changed since the test ran. Re-run "
                         "intertidal_test.py first.")

    tides = [s["tide"] for s in used]
    stats = regression_images(ndvi_imgs, tides)
    cls = classify(stats, len(tides))

    print("  vectorizing class 3 (intertidal candidate) at native 10 m")
    fc = (cls.eq(3).selfMask().reduceToVectors(
        geometry=aoi, crs=proj, scale=10, geometryType="polygon",
        eightConnected=True, labelProperty="cls", maxPixels=int(1e9),
    ))
    area_m2 = float(ee.Number(
        fc.geometry().area(maxError=1)).getInfo())
    vect_ha = area_m2 / 10_000.0
    print(f"  vectorized area {vect_ha:.2f} ha  vs report {reported_ha:.1f} ha")
    if abs(vect_ha - reported_ha) > max(AREA_TOLERANCE_HA, 0.02 * reported_ha):
        raise SystemExit("EXPORT REFUSED: vectorized area disagrees with the "
                         "verified report beyond tolerance.")

    gj = fc.getInfo()
    n_polys = len(gj["features"])
    for f in gj["features"]:
        f["properties"] = {}          # per-polygon props carry nothing useful
    gj["properties"] = {
        "product": "intertidal macroalgae extent (species-agnostic)",
        "aoi": aoi_name,
        "area_ha": round(vect_ha, 2),
        "report_area_ha": reported_ha,
        "source_report": report_path.name,
        "scenes": [s["date"] for s in used],
        "tide_range_m": report["tide_range_m"],
        "method": ("Sentinel-2 L1C NDVI tide dose-response "
                   "(per-pixel regression of NDVI against measured tide; "
                   "class = NDVI vegetated when exposed, water-like when "
                   "submerged, negative slope)"),
        "caveats": report["caveats"],
        "exported": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "attribution": [ATTRIBUTION["SENTINEL2"], ATTRIBUTION["TIDE_GAUGE"]],
    }
    out = OUT_DIR / f"extent_{aoi_name}_{len(used)}scenes.geojson"
    out.write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
    print(f"  written: {out}  ({n_polys} polygons, "
          f"{out.stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
