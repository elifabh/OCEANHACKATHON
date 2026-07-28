#!/usr/bin/env python3
"""
fetch_probe.py - inspect a downloaded wave-fetch raster before trusting it.

WHY THIS SCRIPT EXISTS
Step 1 proved that substrate alone cannot discriminate our negative control:
inner_roaringwater (Saccharina / Saccorhiza per MERC 2007, NOT L. hyperborea)
looks the same as sherkin's shallow bands on INFOMAR backscatter. So WAVE
EXPOSURE has to be a primary term in the step 2 suitability model, not an
optional third factor.

The cheapest credible exposure layer is wave fetch: for each 11.25 degree
sector, the open-water distance to the nearest land, summed over 32 sectors.
That is the method of Burrows et al. (2008) Marine Ecology Progress Series
353:1-12 and Burrows (2012), and the same family of index (fetch x wind) that
Isaeus (2004) and Bekkby et al. (2009, ICES JMS 66:2106-2115) used to model
Laminaria hyperborea in Norway. We are not inventing a covariate.

Michael Burrows has published ready-made fetch rasters on figshare. This script
does NOT download them - it checks one after you have. Three things have to be
true before the layer goes anywhere near the model, and none of them can be
assumed:

  1. THE PROJECTION IS WHAT THE RECORD CLAIMS. The 200 m record says
     "Ordnance Survey projection" but the file is named log10_eu200m1a.tif,
     which reads like a European extent. Those are different things. If it is
     EPSG:27700, West Cork at 9.4 W is far outside the zone the grid was
     designed for; the maths still works but it must be checked, not assumed.
  2. OUR AOIs ARE ACTUALLY INSIDE THE RASTER. A layer that stops at the Irish
     Sea is useless to us and would return nodata that is easy to misread as
     "sheltered".
  3. THE VALUES RANK THE AOIs CORRECTLY. This is the real test.
     mizen_outer faces the open Atlantic; sherkin_baltimore is partly screened
     by Sherkin and Cape Clear; inner_roaringwater sits behind the island
     chain. Predicted order, from coastal geometry alone:

         mizen_outer  >  sherkin_baltimore  >  inner_roaringwater

     If the raster does not reproduce that, the raster is wrong for us, or it
     is misprojected, or we are sampling the wrong place. Do not proceed on a
     layer that fails this - a silently misprojected exposure layer would
     invert the negative control and the model would look like it works.

WHAT THIS SCRIPT DOES NOT DO
It does not turn fetch into wave height, and neither should anything
downstream without saying so. Fetch is an INDEX of geometric shelter. It is
not a measurement of wave energy and it must never be fed to the Dubi & Torum
(1996) or Mork (1996) wave-attenuation coefficients as if it were a significant
wave height. Those need real Hs and Tp - a separate job, in step 3.

Dependency: rasterio (bundles GDAL, so no separate GDAL install on Windows).
    pip install rasterio

Usage:
    python src/fetch_probe.py --selftest
    python src/fetch_probe.py --raster data/fetch/log10_eu200m1a.tif
    python src/fetch_probe.py --raster data/fetch/log10_eu200m1a.tif --grid 40
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

try:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import transform as warp_transform
except ImportError:                                    # pragma: no cover
    print("rasterio is required:  pip install rasterio")
    raise

from common import AOIS, EXPECTED_EXPOSURE_ORDER, grid_points

OUT_DIR = Path("outputs/exposure")
WGS84 = CRS.from_epsg(4326)


# ---------------------------------------------------------------------------
# 1. What is this file?
# ---------------------------------------------------------------------------

def describe_raster(src) -> dict:
    """Print the properties that decide whether the layer is usable at all."""
    b = src.bounds
    info = {
        "driver": src.driver,
        "crs": str(src.crs),
        "epsg": src.crs.to_epsg() if src.crs else None,
        "width": src.width,
        "height": src.height,
        "bands": src.count,
        "dtype": src.dtypes[0],
        "nodata": src.nodata,
        "res_x": src.res[0],
        "res_y": src.res[1],
    }
    print("  driver / bands   :", info["driver"], "/", info["bands"])
    print("  CRS              :", info["crs"])
    print("  EPSG             :", info["epsg"] if info["epsg"] else "NOT AN EPSG CODE")
    print(f"  size             : {src.width} x {src.height} px")
    print(f"  pixel size       : {src.res[0]:g} x {src.res[1]:g}"
          f"  ({'degrees' if src.crs and src.crs.is_geographic else 'CRS units'})")
    print(f"  bounds           : {b.left:.1f} {b.bottom:.1f} {b.right:.1f} {b.top:.1f}")
    print("  dtype            :", info["dtype"])
    print("  nodata           :", info["nodata"])

    if src.crs is None:
        print("  >>> NO CRS. The file carries no georeferencing, so nothing can")
        print("  >>> be sampled from it reliably. Stop here.")
    elif info["epsg"] == 27700:
        print("  >>> EPSG:27700 (OSGB36 British National Grid). West Cork is far")
        print("  >>> outside the area this grid was defined for, so eastings")
        print("  >>> will be negative and the datum shift is an extrapolation.")
        print("  >>> At 200 m pixels the error is not material, but say so on")
        print("  >>> the slide rather than being asked.")
    if src.nodata is None:
        print("  >>> NODATA IS UNDEFINED. Land and unmapped sea will come back")
        print("  >>> as a real number - probably 0 - which is indistinguishable")
        print("  >>> from 'completely enclosed water'. Treat 0 with suspicion.")
    return info


def guess_value_convention(values: list[float]) -> str:
    """Burrows publishes both log10 and raw summed-cell-count versions."""
    if not values:
        return "unknown (no valid samples)"
    hi = max(values)
    if hi <= 12:
        return f"looks like LOG10 of summed fetch (max {hi:.2f})"
    return f"looks like RAW summed cell counts (max {hi:.0f})"


# ---------------------------------------------------------------------------
# 2. Sample the AOIs
# ---------------------------------------------------------------------------

def sample_aoi(src, bbox: list[float], grid: int) -> tuple[list[float], int]:
    """Sample a lon/lat grid over one AOI, returning valid values and n asked."""
    pts = grid_points(bbox, grid, grid)
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]

    if src.crs != WGS84:
        xs, ys = warp_transform(WGS84, src.crs, lons, lats)
    else:
        xs, ys = lons, lats

    # Drop points outside the raster before sampling, so "outside the layer"
    # and "nodata inside the layer" stay separable.
    b = src.bounds
    inside = [(x, y) for x, y in zip(xs, ys)
              if b.left <= x <= b.right and b.bottom <= y <= b.top]
    if not inside:
        return [], len(pts)

    vals: list[float] = []
    for arr in src.sample(inside, indexes=1, masked=True):
        v = arr[0]
        if v is None or (hasattr(v, "mask") and v.mask):
            continue
        fv = float(v)
        if fv != fv:                                   # NaN
            continue
        if src.nodata is not None and fv == src.nodata:
            continue
        vals.append(fv)
    return vals, len(pts)


def summarise(name: str, vals: list[float], requested: int) -> dict:
    print(f"\n  {name}")
    print(f"    points requested : {requested}")
    print(f"    points with data : {len(vals)}"
          f"   ({100.0 * len(vals) / requested:.1f}%)")
    if not vals:
        print("    >>> NO DATA AT ANY POINT. Either the AOI is outside the")
        print("    >>> raster, or the layer is land-masked here. Check the")
        print("    >>> bounds printed above before concluding 'sheltered'.")
        return {"aoi": name, "requested": requested, "n_valid": 0}
    s = sorted(vals)
    q = statistics.quantiles(s, n=4) if len(s) >= 4 else [s[0], s[len(s) // 2], s[-1]]
    print(f"    min / p25 / med / p75 / max :"
          f" {s[0]:.3f} / {q[0]:.3f} / {statistics.median(s):.3f}"
          f" / {q[2]:.3f} / {s[-1]:.3f}")
    return {
        "aoi": name, "requested": requested, "n_valid": len(s),
        "coverage_pct": round(100.0 * len(s) / requested, 1),
        "min": round(s[0], 4), "p25": round(q[0], 4),
        "median": round(statistics.median(s), 4), "p75": round(q[2], 4),
        "max": round(s[-1], 4),
    }


# ---------------------------------------------------------------------------
# 3. The test that decides whether we keep the layer
# ---------------------------------------------------------------------------

def ranking_test(rows: list[dict]) -> bool:
    """Does the layer reproduce the exposure order predicted from geometry?"""
    print("\n" + "=" * 74)
    print("RANKING TEST   expected: " + "  >  ".join(EXPECTED_EXPOSURE_ORDER))
    print("=" * 74)

    med = {r["aoi"]: r.get("median") for r in rows}
    if any(med.get(a) is None for a in EXPECTED_EXPOSURE_ORDER):
        print("  INCONCLUSIVE: at least one AOI returned no data.")
        return False

    order = sorted(EXPECTED_EXPOSURE_ORDER, key=lambda a: -med[a])
    for a in order:
        print(f"    {a:<22} median {med[a]:.3f}")
    ok = tuple(order) == tuple(EXPECTED_EXPOSURE_ORDER)
    print("\n  observed: " + "  >  ".join(order))
    if ok:
        print("  PASS. The layer separates exposed from sheltered in the")
        print("  direction the coastline predicts. It is usable as the")
        print("  exposure term, still as an INDEX and not as wave energy.")
    else:
        print("  FAIL. Do NOT build the suitability model on this layer yet.")
        print("  Rule out, in this order: (1) wrong CRS or a datum shift that")
        print("  silently moved the sample points; (2) the AOI boxes include")
        print("  land or estuary pixels that drag the median; (3) the layer is")
        print("  a different quantity than assumed (log10 vs raw counts does")
        print("  not change rank, so this would be a real problem).")
    return ok


# ---------------------------------------------------------------------------
# Offline self-test - builds synthetic rasters, no download needed
# ---------------------------------------------------------------------------

def _write_synthetic(path: Path, aoi_values: dict[str, float]) -> None:
    """A 4326 raster over West Cork with a chosen value inside each AOI box."""
    import numpy as np
    from rasterio.transform import from_origin

    left, top, res = -10.0, 51.8, 0.002
    w, h = int((-9.0 - left) / res), int((top - 51.2) / res)
    nodata = -9999.0
    arr = np.full((h, w), nodata, dtype="float32")

    for name, val in aoi_values.items():
        x0, y0, x1, y1 = AOIS[name]
        c0, c1 = int((x0 - left) / res), int((x1 - left) / res)
        r0, r1 = int((top - y1) / res), int((top - y0) / res)
        arr[r0:r1, c0:c1] = val

    with rasterio.open(
        path, "w", driver="GTiff", height=h, width=w, count=1,
        dtype="float32", crs=CRS.from_epsg(4326),
        transform=from_origin(left, top, res, res), nodata=nodata,
    ) as dst:
        dst.write(arr, 1)


def selftest() -> int:
    import tempfile
    print("SELFTEST (no network, no download)\n")
    tmp = Path(tempfile.mkdtemp())

    # Case A: a layer that ranks the AOIs the way the coastline predicts.
    good = tmp / "good.tif"
    _write_synthetic(good, {"mizen_outer": 5.4,
                            "sherkin_baltimore": 4.6,
                            "inner_roaringwater": 3.1})
    with rasterio.open(good) as src:
        rows = [summarise(n, *sample_aoi(src, b, 8)) for n, b in AOIS.items()]
    assert ranking_test(rows) is True, "PASS case did not pass"
    print("\n  case A (correct ordering)            -> PASS as expected")

    # Case B: the same code on a layer that ranks them wrongly. This proves the
    # test can actually fail; a check that cannot fail is not a check.
    bad = tmp / "bad.tif"
    _write_synthetic(bad, {"mizen_outer": 3.1,
                           "sherkin_baltimore": 4.6,
                           "inner_roaringwater": 5.4})
    with rasterio.open(bad) as src:
        rows_b = [summarise(n, *sample_aoi(src, b, 8)) for n, b in AOIS.items()]
    assert ranking_test(rows_b) is False, "FAIL case was not caught"
    print("\n  case B (inverted ordering)           -> FAIL as expected")

    # Case C: AOIs outside the raster must not be reported as 'sheltered'.
    far = tmp / "far.tif"
    _write_synthetic(far, {})
    with rasterio.open(far) as src:
        vals, req = sample_aoi(src, AOIS["mizen_outer"], 8)
    assert vals == [] and req == 64, (len(vals), req)
    print("  case C (all nodata)                  -> reported as no data, not 0")

    assert "LOG10" in guess_value_convention([2.0, 5.4])
    assert "RAW" in guess_value_convention([12000.0])
    print("  guess_value_convention               -> ok")

    print("\nSELFTEST PASSED. This proves the sampling, masking and ranking")
    print("logic are correct. It proves nothing about the Burrows raster -")
    print("run without --selftest once you have downloaded it.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Inspect a wave-fetch raster and test it against the AOIs.")
    ap.add_argument("--raster", type=Path, help="path to the downloaded GeoTIFF")
    ap.add_argument("--grid", type=int, default=25,
                    help="grid side per AOI, default 25 (=625 points)")
    ap.add_argument("--selftest", action="store_true",
                    help="run offline logic checks on synthetic rasters and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.raster:
        ap.error("--raster is required (or use --selftest)")
    if not args.raster.exists():
        print(f"file not found: {args.raster}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 74)
    print(f"WAVE FETCH PROBE   {args.raster}")
    print("=" * 74)

    with rasterio.open(args.raster) as src:
        describe_raster(src)
        print("\n  sampling AOIs")
        rows, all_vals = [], []
        for name, bbox in AOIS.items():
            vals, req = sample_aoi(src, bbox, args.grid)
            rows.append(summarise(name, vals, req))
            all_vals.extend(vals)

    print("\n  value convention :", guess_value_convention(all_vals))
    print("  >>> Whichever it is, this is an INDEX of geometric shelter, not a")
    print("  >>> wave height. Do not pass it to a wave-attenuation coefficient.")

    ok = ranking_test(rows)

    path = OUT_DIR / "fetch_probe_summary.csv"
    keys = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  written: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())