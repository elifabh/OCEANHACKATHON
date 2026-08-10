#!/usr/bin/env python3
"""
npws_shallow_overlap.py — step C, check 2.

QUESTION
--------
INFOMAR has 58.9 ha of real 4-10 m seabed at mizen_outer. The pipeline reported
no assessed cell shallower than 20 m there. Where did the shallow band go?

Two candidate explanations have already been ruled out:

  - Wrong endpoint. common.py has INFOMAR_BATHY pointing at .../AllSurvey/,
    which is correct. The pipeline was reading the right service.
  - Extrapolation. The step-2 training range is depth -0.44 to 54.97 m, so
    4-10 m sits well INSIDE it. Mizen's "53% outside range" comes from its
    deep water: median depth 56.6 m, 73% deeper than 50 m. Extrapolation
    cannot have dropped the shallow band.

That leaves candidate generation. Step 2 builds its candidate cells from NPWS
Article 17 layer 21 reef polygons. If those polygons do not reach into shallow
water at Mizen, the shallow cells were never candidates at all, and no amount
of bathymetry fixes it.

THE TEST
--------
Take the 4-10 m pixels from the INFOMAR service, dissolve them into a strip,
and intersect with NPWS layer 21.

  overlap        -> cells existed as candidates and were dropped later.
                    Next place to look is the depth cache / sampling step.
  no overlap     -> NPWS never mapped shallow reef here. Candidate generation
                    is the blocker, and the fix is to stop deriving candidates
                    from reef polygons alone.

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It does not decide whether kelp is there. NPWS layer 21 coverage is patchy, and
the project rule stands: unlabelled is unknown, never absent. A no-overlap
result means "not mapped", not "no reef".

Usage:
    python src/npws_shallow_overlap.py --aoi mizen_outer
    python src/npws_shallow_overlap.py --aoi mizen_outer --compare sherkin_baltimore
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

DEFAULT_SHP = "data/npws/gis_files/21 NPWSArticle17Habitat.shp"
BATHY = "https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer"
ITM = 2157


def need(mod, pip_name=None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"ERROR: {mod} not installed.  pip install {pip_name or mod}")


def get_bbox(name):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path.cwd()))
    try:
        import common
    except Exception:
        try:
            from src import common
        except Exception:
            return None
    d = getattr(common, "AOIS", None)
    if isinstance(d, dict) and name in d:
        return tuple(float(x) for x in d[name])
    return None


def depth_strip(requests, rasterio, gpd, bbox, dmin, dmax, size):
    """Fetch bathymetry, keep dmin..dmax, vectorise to polygons in ITM."""
    from rasterio import features
    from shapely.geometry import shape

    w, s, e, n = bbox
    r = requests.get(BATHY + "/exportImage", timeout=180, params={
        "bbox": f"{w},{s},{e},{n}", "bboxSR": 4326, "imageSR": 4326,
        "size": f"{size},{size}", "format": "tiff", "pixelType": "F32",
        "noData": "-3.4028235e+38", "interpolation": "RSP_NearestNeighbor",
        "f": "image"})
    if r.status_code != 200 or r.content[:2] not in (b"II", b"MM"):
        sys.exit(f"ERROR: bathymetry request failed, HTTP {r.status_code}")

    with rasterio.io.MemoryFile(r.content) as mf, mf.open() as src:
        z = np.asarray(src.read(1), dtype="float64")
        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        z[z < -1e30] = np.nan
        tr = src.transform
    # Negative below LAT, positive on land. Land is excluded, never abs()'d.
    depth = -z
    depth[~np.isfinite(depth)] = np.nan
    depth[depth <= 0] = np.nan

    mask = ((depth >= dmin) & (depth < dmax)).astype("uint8")
    npix = int(mask.sum())
    if npix == 0:
        return None, 0, 0.0

    shapes = features.shapes(mask, mask=mask.astype(bool), transform=tr)
    polys = [shape(g) for g, v in shapes if v == 1]
    g = gpd.GeoDataFrame(geometry=polys, crs="EPSG:4326").to_crs(epsg=ITM)
    ha = float(g.area.sum()) / 10_000.0
    return g, npix, ha


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", default="mizen_outer")
    ap.add_argument("--compare", default="sherkin_baltimore",
                    help="AOI known to produce assessed shallow cells (control)")
    ap.add_argument("--shp", default=DEFAULT_SHP)
    ap.add_argument("--dmin", type=float, default=4.0)
    ap.add_argument("--dmax", type=float, default=10.0)
    ap.add_argument("--size", type=int, default=1000)
    ap.add_argument("--out", default="outputs/model/npws_shallow_overlap")
    args = ap.parse_args()

    requests = need("requests"); rasterio = need("rasterio"); gpd = need("geopandas")
    import pandas as pd

    shp = Path(args.shp)
    if not shp.exists():
        sys.exit(f"ERROR: {shp} not found. Pass --shp.")

    print("=" * 78)
    print(f"NPWS LAYER 21 vs THE {args.dmin:.0f}-{args.dmax:.0f} m BAND")
    print("=" * 78)

    names = [args.aoi] + ([args.compare] if args.compare else [])
    results, layers = {}, {}

    for name in names:
        bbox = get_bbox(name)
        if bbox is None:
            print(f"  {name}: not in common.py AOIS — skipped")
            continue
        w, s, e, n = bbox
        print(f"\n  {name}  bbox {w:.4f} {s:.4f} {e:.4f} {n:.4f}")

        strip, npix, ha = depth_strip(requests, rasterio, gpd, bbox,
                                      args.dmin, args.dmax, args.size)
        if strip is None:
            print(f"    no {args.dmin:.0f}-{args.dmax:.0f} m pixels here")
            continue
        print(f"    depth strip: {npix} px, {ha:.1f} ha, {len(strip)} polygons")

        npws = gpd.read_file(shp, bbox=(w, s, e, n))
        if npws.empty:
            print("    NPWS layer 21: no polygons in this box at all")
            results[name] = {"strip_ha": ha, "npws_ha": 0.0, "overlap_ha": 0.0}
            layers[name] = (strip, None, None)
            continue
        npws = npws.to_crs(epsg=ITM)
        print(f"    NPWS layer 21: {len(npws)} polygons, "
              f"{npws.area.sum()/1e4:.1f} ha in box")

        # What habitat classes are present, so the answer names them.
        cls_col = next((c for c in npws.columns
                        if c.lower() in ("habitatcod", "habitat", "hab_type",
                                         "habitat_ty", "name", "habcode")), None)
        if cls_col:
            top = (npws.assign(ha=npws.area / 1e4)
                   .groupby(cls_col)["ha"].sum().sort_values(ascending=False))
            print("    classes present:")
            for k, v in top.head(6).items():
                print(f"      {str(k)[:52]:<52} {v:8.1f} ha")

        inter = gpd.overlay(strip, npws, how="intersection")
        oha = float(inter.area.sum()) / 1e4 if not inter.empty else 0.0
        pct = 100.0 * oha / ha if ha else 0.0
        print(f"    OVERLAP: {oha:.1f} ha  ({pct:.1f} % of the depth strip)")
        if cls_col and not inter.empty:
            t = (inter.assign(ha=inter.area / 1e4)
                 .groupby(cls_col)["ha"].sum().sort_values(ascending=False))
            for k, v in t.head(6).items():
                print(f"      overlapping class: {str(k)[:44]:<44} {v:7.2f} ha")

        results[name] = {"strip_ha": ha, "npws_ha": float(npws.area.sum()/1e4),
                         "overlap_ha": oha, "overlap_pct": pct}
        layers[name] = (strip, npws, inter)

    if not results:
        sys.exit("\nNothing to compare.")

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).T.round(2).to_csv(out.with_suffix(".csv"))
    for name, (strip, npws, inter) in layers.items():
        strip.to_file(out.with_suffix(".gpkg"), layer=f"{name}_strip", driver="GPKG")
        if npws is not None and not npws.empty:
            npws.to_file(out.with_suffix(".gpkg"), layer=f"{name}_npws", driver="GPKG")
        if inter is not None and not inter.empty:
            inter.to_file(out.with_suffix(".gpkg"), layer=f"{name}_overlap", driver="GPKG")
    print(f"\nWrote {out.with_suffix('.csv')}")
    print(f"Wrote {out.with_suffix('.gpkg')}")

    tgt = results.get(args.aoi, {})
    ctl = results.get(args.compare, {})
    print("\n" + "-" * 78)
    if not tgt:
        print("VERDICT: no result for the target AOI.")
    elif tgt.get("overlap_ha", 0) < 0.5:
        print("VERDICT: NPWS layer 21 does NOT reach the shallow band at "
              f"{args.aoi}.")
        print("  The shallow cells were never candidates. Bathymetry was never")
        print("  the blocker — candidate generation is.")
        print("  Fix: generate candidates from depth + substrate (INFOMAR Seabed")
        print("  Folk: Substrate=Rock AND Biozone=Infralittoral) instead of from")
        print("  reef polygons alone, and keep NPWS strictly for labels.")
        print("  Remember: not mapped is NOT absent. Say 'unsurveyed', not 'no reef'.")
    else:
        print(f"VERDICT: {tgt['overlap_ha']:.1f} ha overlap "
              f"({tgt.get('overlap_pct', 0):.0f} % of the strip).")
        print("  Candidates did exist. The loss happened later — check the depth")
        print("  cache sampling and the 'assessed' mask next.")
    if ctl:
        print(f"\n  control {args.compare}: strip {ctl['strip_ha']:.1f} ha, "
              f"overlap {ctl['overlap_ha']:.1f} ha "
              f"({ctl.get('overlap_pct', 0):.0f} %)")
        print("  If the control overlaps and the target does not, the difference")
        print("  is NPWS survey effort, not our code.")
    print("-" * 78)
    print(f"\nCommand: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()