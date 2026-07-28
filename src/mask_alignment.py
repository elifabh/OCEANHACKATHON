#!/usr/bin/env python3
"""
mask_alignment.py - is the wave-fetch raster actually where we think it is?

WHY THIS SCRIPT EXISTS
fetch_probe.py returned plausible numbers: inner_roaringwater came out about
6x more sheltered than the exposed AOIs, and nothing exceeded the method's
documented 200 km cap. But plausible is not correct. The raster is EPSG:27700
(OSGB36 British National Grid) and West Cork sits far outside the area that
grid was built for, so the OSGB36 -> WGS84 datum shift there is an
extrapolation rather than an interpolation of the official grid-shift model.
A systematic offset of one or two kilometres would move every sample point
inland or offshore and STILL produce numbers that look entirely reasonable.
That is the failure mode this script exists to rule out.

HOW IT WORKS
Take an independent land/water mask. At each AOI grid point, ask two
questions: does the fetch raster have a value here (fetch is only defined over
water), and does the mask say this is water? Those two answers should agree.
Then repeat the comparison with the sample points shifted by a range of
offsets in the raster's own metric CRS, and find the offset at which agreement
is highest. If that is zero, the georeferencing is right. If agreement peaks
at, say, 1000 m east, we have measured the error, in metres, with a direction.

TOLERANCE, STATED UP FRONT
Perfect agreement is not expected and its absence is not a failure:

  - The fetch layer is 200 m. A coastline can only be located to about half a
    pixel, so a residual of one pixel is not evidence of anything.
  - The two products draw the coastline at different tide states. Ours is a
    satellite water mask; the fetch layer's coastline came from a mapped
    shoreline. In Roaringwater Bay the intertidal zone is tens to a couple of
    hundred metres wide, which is sub-pixel to one pixel here.
  - Small islands and rock outcrops below 200 m across exist in the mask and
    not in the fetch grid.

So the test is for a GROSS offset, not for sub-pixel accuracy. Verdict
thresholds: best offset of 0 m is a pass; up to one pixel (200 m) is a pass
within tolerance; more than that is a fail with a measured correction vector.

THE REFERENCE MASK
Default route builds one in Google Earth Engine from a Sentinel-2 median
composite and NDWI. Note this does NOT contradict the locked atmospheric
correction decision: L2A/Sen2Cor is unsuitable for WATER-COLUMN work, which is
why the kelp pipeline uses L1C + ACOLITE. Drawing a land/water boundary is a
LAND application and is exactly what Sen2Cor is designed for. NDWI here is a
geometric reference, not a radiometric measurement.

If Earth Engine is uncooperative, --landmask takes any local single-band
raster where non-zero means water.

Dependencies: rasterio, numpy; earthengine-api only for the default route.

Usage:
    python src/mask_alignment.py --selftest
    python src/mask_alignment.py --raster data/fetch/log10_eu200m1a.tif
    python src/mask_alignment.py --raster data/fetch/log10_eu200m1a.tif \
        --landmask data/masks/water_10m.tif
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform

from common import AOIS, EE_PROJECT, USABLE_MONTHS, grid_points

OUT_DIR = Path("outputs/exposure")
WGS84 = CRS.from_epsg(4326)

MAX_SHIFT_M = 1000.0     # search +/- 1 km
SHIFT_STEP_M = 200.0     # one fetch pixel


# ---------------------------------------------------------------------------
# 1. Reference water mask
# ---------------------------------------------------------------------------

def water_from_gee(points: list[tuple[float, float]]) -> list[bool | None]:
    """Sentinel-2 NDWI water mask sampled at lon/lat points, via Earth Engine.

    NOT RUNTIME-TESTED in the session that wrote this file - there was no
    Earth Engine access there. If it raises, fall back to --landmask and say
    so rather than editing it blind.
    """
    import ee

    ee.Initialize(project=EE_PROJECT)

    months = list(USABLE_MONTHS)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterDate("2019-01-01", "2024-12-31")
           .filter(ee.Filter.calendarRange(months[0], months[-1], "month"))
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40)))

    # Median composite: one scene's cloud shadow or sun glint must not decide
    # where the coastline is.
    med = col.median()
    ndwi = med.normalizedDifference(["B3", "B8"]).rename("ndwi")
    water = ndwi.gt(0).rename("water")

    indexed = [[i, lon, lat] for i, (lon, lat) in enumerate(points)]

    def _mk(triple):
        t = ee.List(triple)
        return ee.Feature(
            ee.Geometry.Point([ee.Number(t.get(1)), ee.Number(t.get(2))]),
            {"idx": ee.Number(t.get(0))},
        )

    out: list[bool | None] = [None] * len(points)
    CHUNK = 500                       # keep getInfo payloads comfortable
    for start in range(0, len(indexed), CHUNK):
        fc = ee.FeatureCollection(ee.List(indexed[start:start + CHUNK]).map(_mk))
        sampled = water.sampleRegions(collection=fc, scale=10,
                                      geometries=False).getInfo()
        for feat in sampled.get("features", []):
            p = feat.get("properties", {})
            if "idx" in p and p.get("water") is not None:
                out[int(p["idx"])] = bool(p["water"])
    return out


def water_from_raster(path: Path,
                      points: list[tuple[float, float]]) -> list[bool | None]:
    """Read water/land from a local raster. Non-zero, non-nodata means water."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    out: list[bool | None] = []
    with rasterio.open(path) as src:
        xs, ys = ((lons, lats) if src.crs == WGS84
                  else warp_transform(WGS84, src.crs, lons, lats))
        b = src.bounds
        for x, y in zip(xs, ys):
            if not (b.left <= x <= b.right and b.bottom <= y <= b.top):
                out.append(None)
                continue
            v = float(next(src.sample([(x, y)], indexes=1))[0])
            if v != v or (src.nodata is not None and v == src.nodata):
                out.append(None)
            else:
                out.append(v != 0)
    return out


# ---------------------------------------------------------------------------
# 2. Fetch presence under a shift
# ---------------------------------------------------------------------------

class FetchWindow:
    """The fetch raster read once into memory, so 121 shifts stay cheap."""

    def __init__(self, path: Path, xs: list[float], ys: list[float],
                 pad_m: float):
        self.src = rasterio.open(path)
        self.res_x, self.res_y = self.src.res
        pad_px = int(pad_m / min(self.res_x, self.res_y)) + 2

        rows, cols = zip(*[self.src.index(x, y) for x, y in zip(xs, ys)])
        self.r0 = max(min(rows) - pad_px, 0)
        self.c0 = max(min(cols) - pad_px, 0)
        r1 = min(max(rows) + pad_px + 1, self.src.height)
        c1 = min(max(cols) + pad_px + 1, self.src.width)

        win = rasterio.windows.Window(self.c0, self.r0, c1 - self.c0, r1 - self.r0)
        self.arr = self.src.read(1, window=win, masked=True)
        self.nodata = self.src.nodata
        self.crs = self.src.crs
        self.bounds = self.src.bounds
        self.src.close()

    def has_value(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """True where the fetch raster carries a real value at (x, y)."""
        # Affine inverse via rasterio's own index maths, vectorised by hand:
        # the window read means we must subtract the window origin.
        rows = np.floor((self._top - ys) / self.res_y).astype(int) - self.r0
        cols = np.floor((xs - self._left) / self.res_x).astype(int) - self.c0
        ok = ((rows >= 0) & (rows < self.arr.shape[0]) &
              (cols >= 0) & (cols < self.arr.shape[1]))
        out = np.zeros(len(xs), dtype=bool)
        if ok.any():
            vals = self.arr[rows[ok], cols[ok]]
            good = ~np.ma.getmaskarray(vals)
            data = np.ma.getdata(vals)
            good &= np.isfinite(data)
            if self.nodata is not None:
                good &= (data != self.nodata)
            out[np.where(ok)[0]] = good
        return out

    # set after construction by the caller (kept simple and explicit)
    _left: float = 0.0
    _top: float = 0.0



def edge_points(water: np.ndarray, valid: np.ndarray,
                n_aoi: int, grid: int) -> np.ndarray:
    """Points that sit on a land/water transition in the reference mask.

    WHY THIS EXISTS - found by the self-test, not by reasoning. The first
    version scored agreement over every sample point and a 720 m injected
    error moved the score by 0.4 percentage points, because points far inland
    or far offshore agree under ANY shift and swamp the ones that carry
    information. A test that cannot fail is not a test. Only points adjacent
    to a coastline can distinguish one alignment from another, so the verdict
    is computed on those and the all-points number is kept as context.
    """
    per = grid * grid
    edge = np.zeros(len(water), dtype=bool)
    for a in range(n_aoi):
        s = a * per
        w = water[s:s + per].reshape(grid, grid)
        v = valid[s:s + per].reshape(grid, grid)
        e = np.zeros((grid, grid), dtype=bool)
        dh = v[:, :-1] & v[:, 1:] & (w[:, :-1] != w[:, 1:])
        e[:, :-1] |= dh
        e[:, 1:] |= dh
        dv = v[:-1, :] & v[1:, :] & (w[:-1, :] != w[1:, :])
        e[:-1, :] |= dv
        e[1:, :] |= dv
        edge[s:s + per] = e.ravel()
    return edge


# ---------------------------------------------------------------------------
# 3. The shift search
# ---------------------------------------------------------------------------

def shift_search(fw: FetchWindow, xs: np.ndarray, ys: np.ndarray,
                 is_water: np.ndarray, valid: np.ndarray,
                 edge: np.ndarray) -> list[dict]:
    """Agreement between 'fetch has a value' and 'mask says water', per shift.

    The reported dx/dy is the shift APPLIED TO OUR SAMPLE COORDINATES that
    maximises agreement. It therefore points in the same direction as the
    layer's own displacement: a result of (+600, -400) means the fetch grid
    sits 600 m east and 400 m south of where its georeferencing claims.
    """
    sel = valid & edge
    ctx = valid
    results = []
    steps = np.arange(-MAX_SHIFT_M, MAX_SHIFT_M + 1e-9, SHIFT_STEP_M)
    for dy in steps:
        for dx in steps:
            has_e = fw.has_value(xs[sel] + dx, ys[sel] + dy)
            has_c = fw.has_value(xs[ctx] + dx, ys[ctx] + dy)
            agree_e = (has_e == is_water[sel])
            results.append({
                "dx_m": float(dx), "dy_m": float(dy),
                "n_edge": int(sel.sum()), "n_all": int(ctx.sum()),
                "edge_agree_pct": round(100.0 * agree_e.mean(), 2),
                "all_agree_pct": round(
                    100.0 * (has_c == is_water[ctx]).mean(), 2),
                "fetch_over_land_pct": round(
                    100.0 * (has_e & ~is_water[sel]).mean(), 2),
                "no_fetch_over_water_pct": round(
                    100.0 * (~has_e & is_water[sel]).mean(), 2),
            })
    return results


MIN_GAIN_PP = 3.0   # below this the optimum is flat and means nothing


def verdict(results: list[dict]) -> tuple[bool, dict, dict]:
    """Pass unless a shift both beats zero MATERIALLY and lands outside a pixel.

    BUG FIXED 2026-07-28, found by a real run. The first version keyed the
    verdict on the offset alone, so a best shift that beat zero by 0.96 of a
    percentage point - i.e. noise across 121 candidates - was reported as a
    FAIL, in the same breath as the code printing "treat as a pass". A shift
    search over a flat surface returns whichever cell won the coin toss. The
    gain has to clear MIN_GAIN_PP before the argmax means anything, and the
    self-test measured what a genuine error looks like: 20.3 pp.
    """
    best = max(results, key=lambda r: r["edge_agree_pct"])
    zero = next(r for r in results if r["dx_m"] == 0.0 and r["dy_m"] == 0.0)
    offset = (best["dx_m"] ** 2 + best["dy_m"] ** 2) ** 0.5
    gain = best["edge_agree_pct"] - zero["edge_agree_pct"]
    displaced = (offset > SHIFT_STEP_M) and (gain >= MIN_GAIN_PP)
    return (not displaced), best, zero



# ---------------------------------------------------------------------------
# 3b. Why do they disagree? Generalisation and displacement look different.
# ---------------------------------------------------------------------------

def diagnose(is_water: np.ndarray, valid: np.ndarray, has_fetch: np.ndarray,
             n_aoi: int, grid: int, step_m: float) -> None:
    """Separate a coarse coastline from a displaced one.

    A DISPLACEMENT moves everything one way, so the errors pile up on one side
    of the land and are balanced overall: points that fall off the water gain
    what points that fall onto it lose. A COARSE COASTLINE is a dilation: the
    fetch grid calls water everything within a pixel or so of water, errors
    are one-sided, and their direction is uniform around every shore.

    Two readouts, both from the sample grid already in hand:
      1. how far into the land, in grid steps, fetch still claims water;
      2. which way the nearest water lies from each of those points.
    """
    per = grid * grid
    depth_hist: dict[int, list[int]] = {}
    dir_counts = {"N": 0, "E": 0, "S": 0, "W": 0}

    for a in range(n_aoi):
        s = a * per
        w = is_water[s:s + per].reshape(grid, grid)
        f = has_fetch[s:s + per].reshape(grid, grid)

        # multi-source BFS: distance from every cell to the nearest water cell
        dist = np.full((grid, grid), -1, dtype=int)
        dist[w] = 0
        frontier = w.copy()
        for d in range(1, 8):
            nxt = np.zeros_like(frontier)
            nxt[1:, :] |= frontier[:-1, :]
            nxt[:-1, :] |= frontier[1:, :]
            nxt[:, 1:] |= frontier[:, :-1]
            nxt[:, :-1] |= frontier[:, 1:]
            nxt &= (dist < 0)
            if not nxt.any():
                break
            dist[nxt] = d
            frontier = nxt

        for d in range(1, 8):
            sel = (dist == d)
            if sel.any():
                depth_hist.setdefault(d, [0, 0])
                depth_hist[d][0] += int(sel.sum())
                depth_hist[d][1] += int((sel & f).sum())

        # direction from each wrongly-wet land point toward the nearest water
        rr, cc = np.where(f & ~w & (dist > 0))
        for r, c in zip(rr, cc):
            d = dist[r, c]
            if r > 0 and dist[r - 1, c] == d - 1:
                dir_counts["N"] += 1
            elif r < grid - 1 and dist[r + 1, c] == d - 1:
                dir_counts["S"] += 1
            elif c > 0 and dist[r, c - 1] == d - 1:
                dir_counts["W"] += 1
            elif c < grid - 1 and dist[r, c + 1] == d - 1:
                dir_counts["E"] += 1

    print("\n  land points claimed as water by the fetch grid, by depth inland")
    print(f"    {'steps from water':<20}{'~metres':>9}{'n land':>9}"
          f"{'fetch says water':>19}")
    for d in sorted(depth_hist):
        n, k = depth_hist[d]
        print(f"    {d:<20}{d * step_m:>9.0f}{n:>9}{100.0 * k / n:>18.1f}%")
    print("    A coarse coastline decays fast: high at 1 step, near zero by 3.")
    print("    A displacement stays high for 2-3 steps on one side only.")

    tot = sum(dir_counts.values()) or 1
    print("\n  direction of the nearest water from those points")
    print("    " + "   ".join(f"{k} {100.0 * v / tot:4.1f}%"
                              for k, v in dir_counts.items()))
    spread = max(dir_counts.values()) / tot
    if spread > 0.45:
        print("    >>> CONCENTRATED in one direction. That is a displacement.")
    else:
        print("    >>> Spread across all four. That is dilation of the")
        print("    >>> coastline, not a shift of the grid.")


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def _synthetic_pair(tmp: Path, offset_m: tuple[float, float]) -> tuple[Path, Path]:
    """A land/water truth raster, and a 'fetch' raster shifted by a known error.

    Both in EPSG:27700 so the test exercises the real reprojection path.
    """
    from rasterio.transform import from_origin

    res, left, top = 200.0, -100000.0, 6000000.0
    w = h = 300
    truth = np.zeros((h, w), dtype="float32")
    # A ragged coast with bays and offshore islands, so the reference mask has
    # plenty of land/water transitions - a straight coastline would let a
    # north-south error pass undetected.
    yy, xx = np.mgrid[0:h, 0:w]
    coast = (w // 2) + (18 * np.sin(yy / 11.0) + 9 * np.sin(yy / 3.7)).astype(int)
    truth[xx < coast] = 1.0
    for cy, cx, r in [(60, 190, 7), (140, 205, 5), (215, 185, 9), (95, 225, 4)]:
        truth[(yy - cy) ** 2 + (xx - cx) ** 2 <= r * r] = 0.0   # islands
    for cy, cx, r in [(110, 120, 8), (200, 100, 6)]:
        truth[(yy - cy) ** 2 + (xx - cx) ** 2 <= r * r] = 1.0   # inland lakes

    land_p = tmp / "truth.tif"
    with rasterio.open(land_p, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs=CRS.from_epsg(27700),
                       transform=from_origin(left, top, res, res),
                       nodata=-999.0) as dst:
        dst.write(truth, 1)

    # "fetch": defined (value 4.0) over water, nodata over land, then the whole
    # grid origin displaced by offset_m to simulate a georeferencing error.
    fetch = np.where(truth > 0, 4.0, -999.0).astype("float32")
    fetch_p = tmp / "fetch.tif"
    with rasterio.open(fetch_p, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="float32", crs=CRS.from_epsg(27700),
                       transform=from_origin(left + offset_m[0],
                                             top + offset_m[1], res, res),
                       nodata=-999.0) as dst:
        dst.write(fetch, 1)
    return land_p, fetch_p


def _run_pair(land_p: Path, fetch_p: Path, grid: int = 45):
    with rasterio.open(land_p) as t:
        b = t.bounds
        xs_p = np.linspace(b.left + 3000, b.right - 3000, grid)
        ys_p = np.linspace(b.top - 3000, b.bottom + 3000, grid)
        gx, gy = np.meshgrid(xs_p, ys_p)
        gx, gy = gx.ravel(), gy.ravel()
        lon, lat = warp_transform(t.crs, WGS84, list(gx), list(gy))

    water = water_from_raster(land_p, list(zip(lon, lat)))
    valid = np.array([w is not None for w in water])
    is_water = np.array([bool(w) if w is not None else False for w in water])
    edge = edge_points(is_water, valid, 1, grid)

    fw = FetchWindow(fetch_p, list(gx), list(gy), MAX_SHIFT_M)
    with rasterio.open(fetch_p) as f:
        fw._left, fw._top = f.bounds.left, f.bounds.top
    res = shift_search(fw, gx, gy, is_water, valid, edge)
    ok, best, zero = verdict(res)
    return ok, best, zero, int(edge.sum())


def selftest() -> int:
    import tempfile
    print("SELFTEST (no network)\n")
    tmp = Path(tempfile.mkdtemp())

    land_p, fetch_p = _synthetic_pair(tmp, (0.0, 0.0))
    ok, best, zero, n_edge = _run_pair(land_p, fetch_p)
    print(f"  case A  no injected error    -> best ({best['dx_m']:+.0f},"
          f" {best['dy_m']:+.0f}) m   coastline agreement"
          f" {best['edge_agree_pct']:.1f}%   n_edge={n_edge}")
    assert ok and best["dx_m"] == 0 and best["dy_m"] == 0, best

    land_p, fetch_p = _synthetic_pair(tmp, (600.0, -400.0))
    ok, best, zero, n_edge = _run_pair(land_p, fetch_p)
    drop = zero["edge_agree_pct"]
    print(f"  case B  injected (+600,-400) -> best ({best['dx_m']:+.0f},"
          f" {best['dy_m']:+.0f}) m   coastline agreement"
          f" {best['edge_agree_pct']:.1f}%  (at zero shift: {drop:.1f}%)")
    # Sign convention, established by this run and not assumed: the recovered
    # vector matches the injected displacement.
    assert (best["dx_m"], best["dy_m"]) == (600.0, -400.0), best
    assert not ok, "a 720 m offset must not be reported as a pass"
    assert best["edge_agree_pct"] - drop > 10.0, (
        f"only {best['edge_agree_pct'] - drop:.1f} pp separates a 720 m error "
        "from a clean layer - the test still lacks power")
    print(f"  discriminating power         -> "
          f"{best['edge_agree_pct'] - drop:.1f} pp between right and wrong")

    print("\nSELFTEST PASSED. The shift search recovers a known georeferencing")
    print("error in metres and in direction, and reports a clean raster as")
    print("clean. It says nothing about the Burrows layer until you run it.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check the fetch raster's georeferencing against a water mask.")
    ap.add_argument("--raster", type=Path, help="the wave-fetch GeoTIFF")
    ap.add_argument("--landmask", type=Path,
                    help="local water raster (non-zero = water); "
                         "omit to build one in Earth Engine")
    ap.add_argument("--grid", type=int, default=40,
                    help="grid side per AOI. 40 gives ~175 m spacing, which is\n"
                         "what it takes to resolve a one-pixel offset.")
    ap.add_argument("--diagnose", action="store_true",
                    help="explain the disagreement: coarse coastline or shift")
    ap.add_argument("--cache", action="store_true",
                    help="reuse the saved mask samples instead of calling GEE")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.raster or not args.raster.exists():
        ap.error("--raster is required and must exist (or use --selftest)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pts: list[tuple[float, float]] = []
    labels: list[str] = []
    for name, bbox in AOIS.items():
        for lon, lat in grid_points(bbox, args.grid, args.grid):
            pts.append((lon, lat))
            labels.append(name)
    print(f"sample points: {len(pts)} across {len(AOIS)} AOIs\n")

    cache_p = OUT_DIR / "mask_samples.csv"
    if args.cache and cache_p.exists():
        print(f"reference mask: cached from {cache_p}")
        with cache_p.open(encoding="utf-8") as fh:
            water = [None if r["water"] == "" else r["water"] == "True"
                     for r in csv.DictReader(fh)]
    elif args.landmask:
        print(f"reference mask: {args.landmask}")
        water = water_from_raster(args.landmask, pts)
    else:
        print("reference mask: Sentinel-2 NDWI median composite via Earth Engine")
        try:
            water = water_from_gee(pts)
        except Exception as exc:
            print(f"  Earth Engine route failed: {exc}")
            print("  Re-run with --landmask pointing at a local water raster.")
            return 2

    if not (args.cache and cache_p.exists()):
        with cache_p.open("w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            wr.writerow(["aoi", "lon", "lat", "water"])
            for lab, (lon, lat), wv in zip(labels, pts, water):
                wr.writerow([lab, lon, lat, "" if wv is None else wv])

    valid = np.array([w is not None for w in water])
    is_water = np.array([bool(w) if w is not None else False for w in water])
    print(f"  mask returned a value at {valid.sum()} / {len(pts)} points")
    print(f"  of those, water: {is_water[valid].sum()}  "
          f"land: {(~is_water[valid]).sum()}")
    if valid.sum() < 100:
        print("  >>> too few reference points to conclude anything. Stop.")
        return 2
    if is_water[valid].mean() < 0.05 or is_water[valid].mean() > 0.95:
        print("  >>> the mask is almost all one class, so agreement would be")
        print("  >>> high for trivial reasons. Check the mask before trusting")
        print("  >>> the verdict below.")

    with rasterio.open(args.raster) as src:
        xs_l, ys_l = warp_transform(WGS84, src.crs,
                                    [p[0] for p in pts], [p[1] for p in pts])
        left, top = src.bounds.left, src.bounds.top
    xs = np.array(xs_l)
    ys = np.array(ys_l)

    fw = FetchWindow(args.raster, xs_l, ys_l, MAX_SHIFT_M)
    fw._left, fw._top = left, top

    edge = edge_points(is_water, valid, len(AOIS), args.grid)
    print(f"  coastline (edge) points : {int((valid & edge).sum())}")
    if int((valid & edge).sum()) < 60:
        print("  >>> too few coastline points for the verdict to mean much.")
        print("  >>> Raise --grid and re-run.")

    results = shift_search(fw, xs, ys, is_water, valid, edge)
    ok, best, zero = verdict(results)

    print("\n" + "=" * 74)
    print("ALIGNMENT RESULT   (verdict is on coastline points only)")
    print("=" * 74)
    print(f"  at zero shift : coastline {zero['edge_agree_pct']:.2f}%"
          f"   all points {zero['all_agree_pct']:.2f}%")
    print(f"    fetch present over land : {zero['fetch_over_land_pct']:.2f}%")
    print(f"    no fetch over water     : {zero['no_fetch_over_water_pct']:.2f}%")
    print(f"  best          : coastline {best['edge_agree_pct']:.2f}%"
          f"   at ({best['dx_m']:+.0f}, {best['dy_m']:+.0f}) m")
    gain = best["edge_agree_pct"] - zero["edge_agree_pct"]
    print(f"  gain from shifting      : {gain:+.2f} percentage points")
    if gain < 3.0 and not ok:
        print("  >>> The best shift barely beats zero. That is not evidence of")
        print("  >>> a displacement, it is a flat optimum - treat as a pass and")
        print("  >>> say the test was inconclusive at this sample density.")

    if ok:
        print("\n  PASS. Best agreement is at or within one pixel of zero shift,")
        print("  so the OSGB36 extrapolation has not displaced the layer over")
        print("  West Cork. The fetch values sampled in fetch_probe.py refer to")
        print("  the places we think they do. Wave exposure is now closed as a")
        print("  data question.")
    else:
        print("\n  FAIL. The layer is displaced. The fetch grid sits about")
        print(f"  ({best['dx_m']:+.0f}, {best['dy_m']:+.0f}) m from where its")
        print("  georeferencing claims, in EPSG:27700. Add that vector to the")
        print("  sample coordinates. Before doing so, check the alternative")
        print("  explanation: that the reference mask is wrong. A clean offset")
        print("  of a round number of pixels in one direction points at the")
        print("  datum; a diffuse or diagonal result points at the mask.")

    if args.diagnose:
        step_m = (AOIS["sherkin_baltimore"][2] - AOIS["sherkin_baltimore"][0]) \
            / args.grid * 111320.0 * 0.622
        diagnose(is_water, valid, fw.has_value(xs, ys),
                 len(AOIS), args.grid, step_m)

    path = OUT_DIR / "mask_alignment_shifts.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    print(f"\n  written: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())