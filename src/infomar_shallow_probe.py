#!/usr/bin/env python3
"""
infomar_shallow_probe.py — step C, check B.

QUESTION
--------
EMODnet reports 103 ha of 4-10 m water at mizen_outer, 91% of it traced to
INFOMAR surveys (EDMO 366, GSI). Our own pipeline reported no assessed cell
shallower than 20 m at mizen. Both cannot be right about the same seabed.

Two possibilities:
  A  INFOMAR bathymetry really has no shallow band there.
  B  It has one, and our pipeline dropped it somewhere.

B is much cheaper to fix and gives 4.2 m data instead of EMODnet's 7 m HR DTM,
so B gets tested first. This script asks the INFOMAR bathymetry service
directly, with no mask, no model, no depth cache.

Note: the step-1 finding that mizen has near-zero acoustic data at 0-20 m was
about BACKSCATTER. Bathymetry is a different service. The two may have been
conflated, which is exactly what this script settles.

Usage:
    python src/infomar_shallow_probe.py --aoi mizen_outer
    python src/infomar_shallow_probe.py --aoi mizen_outer --compare sherkin_baltimore
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np

# Verified 2026-08-10 by listing the folder: the INFOMAR folder publishes
# exactly two ImageServers, "AllSurvey_Backscatter" and "AllSurvey".
# "AllSurvey_Bathymetry" does not exist; the bathymetry is "AllSurvey".
DEFAULT_URL = "https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer"
BANDS = [(0, 4, "< 4 m"), (4, 10, "4-10 m  VALID"), (10, 20, "10-20 m"),
         (20, 50, "20-50 m"), (50, 1e6, "> 50 m")]


def need(mod, pip_name=None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"ERROR: {mod} not installed.  pip install {pip_name or mod}")


def get_bbox(name):
    sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path.cwd()))
    try:
        import common
    except Exception:
        try:
            from src import common
        except Exception:
            return None
    for attr in ("AOIS", "AOI", "AOI_BBOX", "AOIS_BBOX"):
        d = getattr(common, attr, None)
        if isinstance(d, dict) and name in d:
            v = d[name]
            if isinstance(v, dict):
                for k in ("bbox", "BBOX", "extent"):
                    if k in v: v = v[k]; break
            if isinstance(v, (list, tuple)) and len(v) == 4:
                return tuple(float(x) for x in v)
    return None


def list_services(requests, folder="https://image.marine.ie/arcgis/rest/services/INFOMAR"):
    """Ask the server what it publishes instead of guessing a service name."""
    try:
        r = requests.get(folder, params={"f": "json"}, timeout=60)
        j = r.json()
    except Exception as ex:  # noqa: BLE001
        print(f"  could not list services: {ex}")
        return []
    names = [d.get("name", "") for d in j.get("services", [])
             if d.get("type") == "ImageServer"]
    return names


def service_info(requests, url):
    """ImageServer metadata: pixel type, band count, extent. A rendered 8-bit
    mosaic cannot serve F32, which is one way exportImage returns HTTP 500."""
    try:
        j = requests.get(url, params={"f": "json"}, timeout=60).json()
    except Exception as ex:  # noqa: BLE001
        print(f"    metadata read failed: {ex}")
        return None
    if "error" in j:
        print(f"    metadata error: {str(j['error'])[:160]}")
        return None
    print(f"    pixelType={j.get('pixelType')}  bands={j.get('bandCount')}  "
          f"serviceDataType={j.get('serviceDataType')}")
    print(f"    min/max px size = {j.get('minPixelSize')} / {j.get('maxPixelSize')}")
    ext = j.get("extent") or {}
    sr = (ext.get("spatialReference") or {}).get("latestWkid") or (ext.get("spatialReference") or {}).get("wkid")
    if ext:
        print(f"    extent SR={sr}  x {ext.get('xmin')}..{ext.get('xmax')}  "
              f"y {ext.get('ymin')}..{ext.get('ymax')}")
    return j


# Progressively simpler exportImage parameter sets. The first that returns a
# TIFF wins; the rest exist because ArcGIS returns a bare HTTP 500 for several
# different unsupported-parameter cases without saying which.
PARAM_SETS = [
    ("F32 + noData + nearest", {"pixelType": "F32", "noData": "-3.4028235e+38",
                                "interpolation": "RSP_NearestNeighbor"}),
    ("F32 + nearest",          {"pixelType": "F32",
                                "interpolation": "RSP_NearestNeighbor"}),
    ("F32 only",               {"pixelType": "F32"}),
    ("server default",         {}),
]


def probe(requests, url, bbox, size, label):
    """exportImage as TIFF. Pixel size pinned so the histogram is reproducible."""
    w, s_, e, n = bbox
    for name, extra in PARAM_SETS:
        for sz in (size, 512):
            p = {"bbox": f"{w},{s_},{e},{n}", "bboxSR": 4326, "imageSR": 4326,
                 "size": f"{sz},{sz}", "format": "tiff", "f": "image", **extra}
            try:
                r = requests.get(url + "/exportImage", params=p, timeout=180)
            except Exception as ex:  # noqa: BLE001
                print(f"    [{name} @{sz}] request failed: {ex}")
                continue
            if r.status_code == 200 and r.content[:2] in (b"II", b"MM"):
                print(f"    [{name} @{sz}] OK  ({len(r.content)/1e6:.2f} MB)")
                return r.content, name, sz
            print(f"    [{name} @{sz}] HTTP {r.status_code}")
            if sz == 512:
                break
    return None, None, None


def report(rasterio, blob, label, cell_m):
    import io
    with rasterio.io.MemoryFile(blob) as mf, mf.open() as src:
        z = np.asarray(src.read(1), dtype="float64")
        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        z[z < -1e30] = np.nan
    # SIGN MATTERS. common.py records this service as a real elevation surface,
    # min -4904.0 m, max +62.2 m: negative below LAT, positive on land. An
    # earlier version of this script took abs(), which folded coastal land
    # elevation into the "4-10 m" depth band and inflated the result. Depth is
    # the negative side only.
    land = int(np.sum(np.isfinite(z) & (z > 0)))
    sea = int(np.sum(np.isfinite(z) & (z < 0)))
    print(f"    raw z: {sea} sea px (z<0), {land} land px (z>0)")
    if land and sea:
        print(f"    land elevation range +0 .. +{np.nanmax(z[z > 0]):.1f} m "
              f"— excluded, not folded into depth")
    depth = -z
    depth[~np.isfinite(depth)] = np.nan
    depth[depth <= 0] = np.nan             # drop land and the 0 m line
    ha = cell_m * cell_m / 1e4
    tot = int(np.sum(np.isfinite(depth)))
    print(f"\n  {label}   SEA pixels: {tot}   (~{cell_m:.0f} m cells, {tot*ha:.0f} ha)")
    if tot == 0:
        print("    NO BATHYMETRY DATA RETURNED AT ALL for this box.")
        return {}
    print(f"    depth min {np.nanmin(depth):.1f} m  max {np.nanmax(depth):.1f} m  "
          f"median {np.nanmedian(depth):.1f} m")
    out = {}
    for lo, hi, name in BANDS:
        k = int(np.nansum((depth >= lo) & (depth < hi)))
        out[name] = k
        pct = 100.0 * k / tot
        print(f"    {name:<16} {k:8d} px  {k*ha:9.1f} ha  {pct:5.1f} %")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", default="mizen_outer")
    ap.add_argument("--compare", default="sherkin_baltimore",
                    help="AOI known to have shallow data, as a positive control")
    ap.add_argument("--bbox", nargs=4, type=float)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--size", type=int, default=1000, help="pinned raster size")
    args = ap.parse_args()

    requests = need("requests"); rasterio = need("rasterio")

    boxes = {}
    boxes[args.aoi] = tuple(args.bbox) if args.bbox else get_bbox(args.aoi)
    if boxes[args.aoi] is None:
        sys.exit(f"ERROR: AOI '{args.aoi}' not in src/common.py. Use --bbox.")
    if args.compare and not args.bbox:
        cb = get_bbox(args.compare)
        if cb: boxes[args.compare] = cb

    print("=" * 78)
    print("INFOMAR BATHYMETRY — RAW PROBE, NO MASK")
    print("=" * 78)
    print(f"  service {args.url}")
    print("  The compare AOI is a positive control: if it also returns nothing,")
    print("  the problem is the request, not the seabed.")

    print("\n  ImageServer services published under /INFOMAR:")
    for nm in list_services(requests) or ["  (none listed)"]:
        print(f"    {nm}")
    print("\n  Metadata for the service being used:")
    service_info(requests, args.url)

    results = {}
    for name, bbox in boxes.items():
        w, s, e, n = bbox
        # crude metres-per-pixel for area reporting
        import math
        wm = (e - w) * 111320 * math.cos(math.radians((s + n) / 2))
        cell_m = wm / args.size
        print(f"\n  {name}: bbox {w:.4f} {s:.4f} {e:.4f} {n:.4f}")
        blob, how, sz = probe(requests, args.url, bbox, args.size, name)
        if blob is None:
            print("    every parameter set failed. Pick a service from the list")
            print("    above and pass it with --url.")
            continue
        cell_m = wm / sz
        results[name] = report(rasterio, blob, f"{name} [{how}]", cell_m)

    print("\n" + "-" * 78)
    tgt = results.get(args.aoi, {})
    ctl = results.get(args.compare, {})
    shallow = tgt.get("4-10 m  VALID", 0)
    if not tgt:
        print("VERDICT: no data returned for the target AOI.")
        if ctl:
            print("  The control AOI did return data, so the service and request are")
            print("  fine and INFOMAR genuinely lacks coverage at mizen.")
            print("  -> Case A. Download 366_7mNorthAtlanticOceanWestCork.emo.zip")
        else:
            print("  The control returned nothing either. Fix the request first;")
            print("  this says nothing about mizen yet.")
    elif shallow == 0:
        print("VERDICT: Case A — INFOMAR has data at mizen but none in 4-10 m.")
        print("  Our pipeline was right. Go to the EMODnet 7 m HR DTM.")
    else:
        print(f"VERDICT: Case B — INFOMAR DOES have {shallow} pixels at 4-10 m.")
        print("  The pipeline dropped them. Next, in this order:")
        print("    1. depth cache under outputs/labels/depth_cache/ — is the band there?")
        print("    2. the 'assessed' mask in suitability_multisite.py")
        print("    3. NPWS layer-21 label coverage at mizen")
        print("    4. the extrapolation flag / training-range check")
    print("-" * 78)
    print(f"\nCommand: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()