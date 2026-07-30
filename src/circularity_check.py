#!/usr/bin/env python3
"""
circularity_check.py - the last thing before the model. Three tests, all of
which can kill the model design, which is why they are run first.

WHY THIS SCRIPT EXISTS
label_depths.py measured a depth-only AUC of 0.954 at Kenmare: kelp cells
median 9.9 m, faunal turf cells median 27.2 m. Taken at face value that is an
excellent result. Taken sceptically it is two separate problems.

  PROBLEM A - CIRCULARITY.
      NPWS's own Roaringwater documentation says Laminaria communities occur to
      about 20 m and the community changes to echinoderm/sponge/hydroid fauna
      below 20 m. If the surveyors used that as a MAPPING RULE - draw the class
      boundary along the 20 m contour - then an AUC of 0.954 is not an
      ecological finding, it is us rediscovering the cartographer's own rule
      and presenting it as a model. A jury that opens the metadata finds this.
      It is not fully circular: 8% of kelp cells are deeper than 20 m and 19%
      of faunal turf cells are shallower, and a pure contour would give zero
      overlap. But 0.954 is high enough for field mapping that the question has
      to be answered rather than assumed.

  PROBLEM B - NOTHING LEFT FOR THE OTHER COVARIATES.
      If depth alone reaches 0.954, then wave exposure, slope and curvature
      have 0.046 of headroom between them. The step 1 conclusion - that wave
      exposure must be a primary model term - was reached when substrate was
      the only alternative. It has to be re-tested now, because a covariate
      that adds nothing must be dropped and said to have been dropped.

THE THREE TESTS

  TEST 1 - PROVENANCE. What do Rational / Source / Notes / Reference actually
      say for the Kenmare Laminaria polygons? A field that says "inferred from
      depth" settles Problem A immediately. This is reading, not inference.

  TEST 2 - IS THE CLASS BOUNDARY A DEPTH CONTOUR?
      Depth is sampled along the boundary SHARED between the kelp polygons and
      the faunal turf polygons. If that boundary was drawn on the 20 m contour,
      those depths cluster tightly at 20 m. If it was drawn from observation,
      they scatter.
      A control is required or the test means nothing: the same measurement is
      taken along the kelp class's OTHER boundary - the part not shared with
      faunal turf, i.e. the landward and open edges. If the shared boundary is
      tight at 20 m AND the control boundary is not, that is contour-following.
      If both are equally scattered, the tightness meant nothing.

  TEST 3 - CONDITIONAL CONTRIBUTION. Within a FIXED depth band, do fetch,
      slope and curvature still separate the classes?
      Holding depth constant removes the part of each covariate's apparent
      skill that is really just depth wearing a different hat. Whatever
      separation survives is the covariate's own contribution. Reported as the
      same AUC statistic, so it is directly comparable to the 0.954.
      A covariate at 0.50 here adds nothing and must be dropped from the model
      and named on the slide as dropped.

Slope and curvature are computed from the sampled depth GRID by finite
differences, not from a downloaded raster, because the grid is already a
regular array. Sign convention: depth is positive down, so
curvature = Laplacian(depth) is POSITIVE over a local high (a shoal, more
likely rock) and NEGATIVE over a local basin (more likely soft sediment).
That is the substrate proxy Bekkby et al. (2009) found to be their second most
important predictor, and it is our replacement for the dead INFOMAR substrate
route.

CACHING. The full grid has to be sampled, not just the cells inside polygons,
because slope and curvature need neighbours. At 50 m over the Kenmare box that
is ~27,500 INFOMAR samples. They are cached to disk on the first run, so every
later run is instant. Delete the cache file to force a refetch.

Dependencies: geopandas (BSD-3), shapely (BSD-3), pyproj (MIT), numpy (BSD-3),
rasterio (BSD-3), requests (Apache-2.0). All to DEPENDENCIES.md with versions.

Data: NPWS Reef Inventory 2023 layer 21; INFOMAR bathymetry (GSI & Marine
Institute) CC BY 4.0; Burrows wave fetch (licence still unread - do not publish
until it is).

Usage:
    python src/circularity_check.py --selftest
    python src/circularity_check.py \
        --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp" \
        --fetch data/fetch/log10_eu200m1a.tif
    python src/circularity_check.py --shp "<path>" --no-cache
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

OUT_DIR = Path("outputs/labels")
CACHE_DIR = OUT_DIR / "depth_cache"

try:
    from common import (AOIS, CRS_FOR_AREA, INFOMAR_BATHY, ArcGISError,
                        arcgis_request)
    HAVE_COMMON = True
except ImportError:                                       # pragma: no cover
    HAVE_COMMON = False
    CRS_FOR_AREA = 2157
    INFOMAR_BATHY = None
    AOIS = {
        "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
        "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
        "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
        "kenmare_river": [-9.93, 51.75, -9.78, 51.81],
    }

    class ArcGISError(RuntimeError):
        pass

    def arcgis_request(*a, **k):
        raise ArcGISError("common.py not importable")

TARGET = "laminaria-dominated reef"
HARD_NEGATIVE = "faunal turf reef"
GRID_M_DEFAULT = 50.0
BATCH = 400

# The contour the NPWS text names. Test 2 asks whether the class boundary
# follows it.
SUSPECT_CONTOUR_M = 20.0
# Depths within this of the suspect contour count as "on" it.
CONTOUR_TOLERANCE_M = 3.0
# The shared boundary is called contour-following if this share of its samples
# lie on the contour AND the control boundary is at least this much looser.
CONTOUR_SHARE_HIGH = 0.60
CONTOUR_CONTROL_MARGIN = 0.25

# Test 3 holds depth inside this band. Chosen because it is where the two
# classes actually overlap (382 faunal turf cells and 1353 kelp cells sit in
# 10-20 m at Kenmare), so there is something to separate.
COND_BAND = (10.0, 20.0)
# AUC distance from 0.5 below which a covariate is judged to add nothing.
COND_NULL_TOL = 0.05
COND_USEFUL = 0.60
MIN_N_PER_CLASS = 30


def norm(v) -> str:
    if v is None:
        return "(null)"
    s = " ".join(str(v).split())
    return s if s else "(null)"


# ---------------------------------------------------------------------------
# AUC - same statistic as label_depths.py, imported if possible so there is
# only one implementation to be wrong.
# ---------------------------------------------------------------------------
try:
    from label_depths import auc_shallower as _auc_lower, quantiles
except ImportError:                                       # pragma: no cover
    def _auc_lower(pos, neg):
        n1, n2 = len(pos), len(neg)
        if n1 == 0 or n2 == 0:
            return float("nan")
        combined = sorted([(v, 0) for v in pos] + [(v, 1) for v in neg])
        ranks = [0.0] * len(combined)
        i = 0
        while i < len(combined):
            j = i
            while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
                j += 1
            avg = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[k] = avg
            i = j + 1
        r_pos = sum(r for r, (_, g) in zip(ranks, combined) if g == 0)
        u_pos = r_pos - n1 * (n1 + 1) / 2.0
        return 1.0 - u_pos / (n1 * n2)

    def quantiles(vals):
        s = sorted(vals)
        n = len(s)
        if n == 0:
            return (float("nan"),) * 3
        return (s[int(0.25 * (n - 1))], s[int(0.50 * (n - 1))],
                s[int(0.75 * (n - 1))])


def auc_separation(pos: list[float], neg: list[float]) -> float:
    """Separation of two samples, direction-free: 0.5 = none, 1.0 = perfect.

    _auc_lower gives P(pos < neg). For a covariate whose useful direction is
    unknown in advance - fetch could plausibly go either way - the SIZE of the
    departure from 0.5 is what matters, not its sign. Folding to
    max(a, 1-a) keeps the number comparable to the 0.954 depth figure while
    not silently assuming a direction we have not established.
    """
    a = _auc_lower(pos, neg)
    if a != a:
        return a
    return max(a, 1.0 - a)


# ---------------------------------------------------------------------------
# Grid and depth, with a cache
# ---------------------------------------------------------------------------

def grid_axes(bbox: list[float], grid_m: float):
    """Regular lon/lat axes for the AOI, plus the cell size in degrees."""
    lat_mid = (bbox[1] + bbox[3]) / 2.0
    dlon = grid_m / (111320.0 * math.cos(math.radians(lat_mid)))
    dlat = grid_m / 110574.0
    lons = np.arange(bbox[0] + dlon / 2, bbox[2], dlon)
    lats = np.arange(bbox[1] + dlat / 2, bbox[3], dlat)
    return lons, lats, dlon, dlat


def sample_depth_grid(name: str, bbox: list[float], grid_m: float,
                      use_cache: bool = True, depth_fn=None) -> np.ndarray:
    """Depth (m below LAT, positive down) on the full grid. NaN = not surveyed.

    Returns a 2-D array shaped (n_lat, n_lon), row 0 = southernmost.
    """
    lons, lats, _, _ = grid_axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)
    grid = np.full((ny, nx), np.nan, dtype=float)

    cache = CACHE_DIR / f"depth_{name}_{int(grid_m)}m.npy"
    if depth_fn is None and use_cache and cache.exists():
        cached = np.load(cache)
        if cached.shape == grid.shape:
            print(f"    depth grid from cache: {cache} "
                  f"({np.isfinite(cached).mean():.0%} surveyed)")
            return cached
        print(f"    cache shape {cached.shape} != {grid.shape}; refetching")

    pts = [(float(lo), float(la)) for la in lats for lo in lons]

    if depth_fn is not None:
        got = depth_fn(pts)
    else:
        print(f"    sampling {len(pts)} INFOMAR points "
              f"({math.ceil(len(pts) / BATCH)} requests) ...")
        got, empty = {}, 0
        for start in range(0, len(pts), BATCH):
            chunk = [[p[0], p[1]] for p in pts[start:start + BATCH]]
            try:
                payload = arcgis_request(f"{INFOMAR_BATHY}/getSamples", {
                    "geometry": json.dumps(
                        {"points": chunk,
                         "spatialReference": {"wkid": 4326}}),
                    "geometryType": "esriGeometryMultipoint",
                    "returnFirstValueOnly": "true",
                    "interpolation": "RSP_NearestNeighbor", "f": "json"})
            except ArcGISError:
                # Empty-batch rule, proven 2026-07-27: a batch entirely outside
                # coverage returns HTTP 400, not an empty list.
                empty += 1
                continue
            for s in payload.get("samples", []):
                loc, raw = s.get("locationId"), s.get("value")
                if loc is None or raw in (None, "", "NaN"):
                    continue
                try:
                    got[start + int(loc)] = -float(str(raw).split()[0])
                except ValueError:
                    continue
        if empty:
            print(f"    ({empty} batches entirely outside INFOMAR coverage)")

    for i, v in got.items():
        grid[i // nx, i % nx] = v
    print(f"    surveyed cells: {np.isfinite(grid).mean():.0%}")

    if depth_fn is None and use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(cache, grid)
        print(f"    cached to {cache}")
    return grid


def terrain(depth: np.ndarray, grid_m: float):
    """Slope (degrees) and curvature (Laplacian of depth) by finite differences.

    Central differences, so any cell missing an orthogonal neighbour yields
    NaN rather than a value computed against a fabricated edge. Depth is
    positive down, so curvature > 0 is a local HIGH (shoal) and < 0 is a local
    LOW (basin).
    """
    ny, nx = depth.shape
    slope = np.full_like(depth, np.nan)
    curv = np.full_like(depth, np.nan)
    if ny < 3 or nx < 3:
        return slope, curv

    c = depth[1:-1, 1:-1]
    n = depth[2:, 1:-1]
    s = depth[:-2, 1:-1]
    e = depth[1:-1, 2:]
    w = depth[1:-1, :-2]

    dzdx = (e - w) / (2.0 * grid_m)
    dzdy = (n - s) / (2.0 * grid_m)
    slope[1:-1, 1:-1] = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    curv[1:-1, 1:-1] = ((e - 2.0 * c + w) + (n - 2.0 * c + s)) / (grid_m ** 2)
    return slope, curv


def sample_fetch_grid(path: Path, bbox: list[float],
                      grid_m: float) -> np.ndarray | None:
    """log10 summed wave fetch on the same grid. NaN outside coverage."""
    import rasterio
    from rasterio.crs import CRS as RCRS
    from rasterio.warp import transform as warp_transform

    lons, lats, _, _ = grid_axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)
    out = np.full((ny, nx), np.nan, dtype=float)
    pts = [(float(lo), float(la)) for la in lats for lo in lons]

    with rasterio.open(path) as src:
        xs, ys = warp_transform(RCRS.from_epsg(4326), src.crs,
                                [p[0] for p in pts], [p[1] for p in pts])
        b = src.bounds
        idx = [i for i, (x, y) in enumerate(zip(xs, ys))
               if b.left <= x <= b.right and b.bottom <= y <= b.top]
        if not idx:
            print("    >>> no grid point falls inside the fetch raster.")
            return None
        coords = [(xs[i], ys[i]) for i in idx]
        for i, arr in zip(idx, src.sample(coords, indexes=1, masked=True)):
            v = arr[0]
            if hasattr(v, "mask") and v.mask:
                continue
            fv = float(v)
            if fv == fv and (src.nodata is None or fv != src.nodata):
                out[i // nx, i % nx] = fv
    print(f"    fetch cells with a value: {np.isfinite(out).mean():.0%}")
    return out


def class_mask(bbox, grid_m, gdf, transformer):
    """Per-cell class label: 1 = target, 2 = hard negative, 0 = neither."""
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    keep = [(norm(c).lower(), g) for c, g in zip(gdf["Community"], gdf.geometry)
            if norm(c).lower() in (TARGET, HARD_NEGATIVE)
            and g is not None and not g.is_empty]
    lons, lats, _, _ = grid_axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)
    mask = np.zeros((ny, nx), dtype=int)
    if not keep:
        return mask, 0

    classes = [1 if c == TARGET else 2 for c, _ in keep]
    polys = [g for _, g in keep]
    tree = STRtree(polys)
    pts = [(float(lo), float(la)) for la in lats for lo in lons]
    xs, ys = transformer.transform([p[0] for p in pts], [p[1] for p in pts])

    conflicts = 0
    for i, (x, y) in enumerate(zip(xs, ys)):
        pt = Point(x, y)
        hits = {classes[j] for j in tree.query(pt) if polys[j].covers(pt)}
        if not hits:
            continue
        if len(hits) > 1:
            conflicts += 1
            continue
        mask[i // nx, i % nx] = hits.pop()
    return mask, conflicts


# ---------------------------------------------------------------------------
# TEST 1 - provenance
# ---------------------------------------------------------------------------

PROVENANCE_FIELDS = ("Source", "Rational", "Notes", "Reference", "Art17_2007",
                     "Designatio", "HAB_TYPE")
# Words that would mean the class was DERIVED rather than observed.
INFERENCE_WORDS = ("depth", "modelled", "modeled", "inferred", "predicted",
                   "assumed", "extrapolat", "bathymetr", "contour", "expert",
                   "desk", "interpret")


def test_provenance(gdf) -> dict:
    """Read what the layer says about where each Laminaria polygon came from."""
    sub = gdf[gdf["Community"].map(norm).str.lower() == TARGET]
    print(f"  Laminaria-dominated reef polygons examined: {len(sub)}")
    if len(sub) == 0:
        print("  >>> none here; run over a wider extent.")
        return {"verdict": "no_polygons"}

    found, flagged = {}, []
    for f in PROVENANCE_FIELDS:
        if f not in sub.columns:
            continue
        vals = {}
        for v in sub[f]:
            vals[norm(v)] = vals.get(norm(v), 0) + 1
        found[f] = vals
        print(f"\n  {f}:")
        for v, n in sorted(vals.items(), key=lambda kv: -kv[1])[:8]:
            hit = [w for w in INFERENCE_WORDS if w in v.lower()]
            tag = f"   <-- INFERENCE WORD: {hit}" if hit else ""
            print(f"    {n:>6}x  {v[:90]}{tag}")
            if hit:
                flagged.append({"field": f, "value": v, "n": n, "words": hit})
        if len(vals) > 8:
            print(f"    ... and {len(vals) - 8} more distinct values")

    if flagged:
        print("\n  >>> AT LEAST ONE PROVENANCE FIELD NAMES DEPTH, BATHYMETRY OR")
        print("  >>> INFERENCE. If the class was delineated from depth then a")
        print("  >>> depth-based model reproduces the mapping rule, not the")
        print("  >>> ecology. Read the full text of the flagged values before")
        print("  >>> going further, and quote it on the slide either way.")
        verdict = "inference_words_present"
    else:
        print("\n  >>> No inference words in any provenance field. That is")
        print("  >>> reassuring but NOT proof of independence - the fields may")
        print("  >>> simply be terse. Tests 2 and 3 still decide.")
        verdict = "no_inference_words"
    return {"verdict": verdict, "fields": found, "flagged": flagged}


# ---------------------------------------------------------------------------
# TEST 2 - is the class boundary a depth contour?
# ---------------------------------------------------------------------------

def depth_at(depth: np.ndarray, bbox, grid_m, lonlat) -> list[float]:
    """Nearest-cell depth lookup for a list of (lon, lat)."""
    lons, lats, _, _ = grid_axes(bbox, grid_m)
    if len(lons) == 0 or len(lats) == 0:
        return []
    out = []
    for lo, la in lonlat:
        j = int(np.abs(lons - lo).argmin())
        i = int(np.abs(lats - la).argmin())
        v = depth[i, j]
        if np.isfinite(v):
            out.append(float(v))
    return out


def _line_points(geom, spacing_m: float, to_wgs) -> list[tuple[float, float]]:
    """Points every `spacing_m` along a (multi)line, returned as lon/lat."""
    from shapely.geometry import LineString, MultiLineString

    lines = []
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, (LineString,)):
        lines = [geom]
    elif isinstance(geom, MultiLineString):
        lines = list(geom.geoms)
    else:
        lines = [g for g in getattr(geom, "geoms", []) 
                 if isinstance(g, LineString)]
        if not lines and hasattr(geom, "exterior"):
            lines = [geom.exterior]

    pts = []
    for ln in lines:
        if ln.length <= 0:
            continue
        n = max(1, int(ln.length // spacing_m))
        for k in range(n + 1):
            p = ln.interpolate(min(k * spacing_m, ln.length))
            lon, lat = to_wgs.transform(p.x, p.y)
            pts.append((lon, lat))
    return pts


def test_contour(gdf, bbox, grid_m, depth, to_wgs) -> dict:
    """Depth along the shared class boundary, against a control boundary."""
    from shapely.ops import unary_union

    tg = [g for c, g in zip(gdf["Community"], gdf.geometry)
          if norm(c).lower() == TARGET and g is not None and not g.is_empty]
    ng = [g for c, g in zip(gdf["Community"], gdf.geometry)
          if norm(c).lower() == HARD_NEGATIVE and g is not None
          and not g.is_empty]
    if not tg or not ng:
        print("  both classes are needed; one is missing here.")
        return {"verdict": "missing_class"}

    tu, nu = unary_union(tg), unary_union(ng)
    # Shared boundary: where the kelp edge runs against the faunal turf body.
    shared = tu.boundary.intersection(nu.buffer(grid_m))
    control = tu.boundary.difference(nu.buffer(grid_m))

    sp = _line_points(shared, grid_m, to_wgs)
    cp = _line_points(control, grid_m, to_wgs)
    sd = depth_at(depth, bbox, grid_m, sp)
    cd = depth_at(depth, bbox, grid_m, cp)

    print(f"  shared boundary  : {len(sp)} points, {len(sd)} with a depth")
    print(f"  control boundary : {len(cp)} points, {len(cd)} with a depth")
    if len(sd) < MIN_N_PER_CLASS or len(cd) < MIN_N_PER_CLASS:
        print(f"  >>> fewer than {MIN_N_PER_CLASS} samples on one boundary.")
        print("  >>> Reported, but no conclusion drawn.")
        return {"verdict": "too_few", "n_shared": len(sd), "n_control": len(cd)}

    lo, hi = (SUSPECT_CONTOUR_M - CONTOUR_TOLERANCE_M,
              SUSPECT_CONTOUR_M + CONTOUR_TOLERANCE_M)
    s_on = sum(1 for v in sd if lo <= v <= hi) / len(sd)
    c_on = sum(1 for v in cd if lo <= v <= hi) / len(cd)
    sq, cq = quantiles(sd), quantiles(cd)

    print(f"\n  shared  p25/med/p75 : {sq[0]:.1f} / {sq[1]:.1f} / {sq[2]:.1f} m"
          f"   on {SUSPECT_CONTOUR_M:.0f}+-{CONTOUR_TOLERANCE_M:.0f} m: "
          f"{s_on:.0%}")
    print(f"  control p25/med/p75 : {cq[0]:.1f} / {cq[1]:.1f} / {cq[2]:.1f} m"
          f"   on {SUSPECT_CONTOUR_M:.0f}+-{CONTOUR_TOLERANCE_M:.0f} m: "
          f"{c_on:.0%}")

    if s_on >= CONTOUR_SHARE_HIGH and (s_on - c_on) >= CONTOUR_CONTROL_MARGIN:
        verdict = "contour_following"
        print(f"\n  >>> THE CLASS BOUNDARY FOLLOWS THE {SUSPECT_CONTOUR_M:.0f} m"
              " CONTOUR.")
        print("  >>> The depth-only AUC is then largely circular: it recovers")
        print("  >>> the rule the surveyors drew with. The model must NOT be")
        print("  >>> presented as predicting kelp from depth. Honest framing:")
        print('  >>>   "NPWS delineate the kelp community by depth, so we take')
        print('  >>>    the depth band as given and test what our other')
        print('  >>>    covariates add within it."')
    elif s_on < CONTOUR_SHARE_HIGH and abs(s_on - c_on) < CONTOUR_CONTROL_MARGIN:
        verdict = "independent"
        print("\n  >>> NOT A CONTOUR. The shared boundary is no more clustered")
        print(f"  >>> at {SUSPECT_CONTOUR_M:.0f} m than the control boundary,")
        print("  >>> so the depth separation is an observed pattern rather")
        print("  >>> than a mapping rule. The AUC stands.")
    else:
        verdict = "partial"
        print("\n  >>> PARTIAL. Some depth-guided delineation, not a clean")
        print("  >>> contour. Report both numbers and use the cautious")
        print("  >>> wording; do not claim the separation is purely observed.")
    return {"verdict": verdict, "n_shared": len(sd), "n_control": len(cd),
            "shared_share_on_contour": round(s_on, 4),
            "control_share_on_contour": round(c_on, 4),
            "shared_quartiles": [round(v, 2) for v in sq],
            "control_quartiles": [round(v, 2) for v in cq]}


# ---------------------------------------------------------------------------
# TEST 3 - conditional contribution
# ---------------------------------------------------------------------------

def test_conditional(mask, depth, covars: dict, band=COND_BAND) -> dict:
    """Does each covariate separate the classes with depth held constant?"""
    lo, hi = band
    in_band = np.isfinite(depth) & (depth > lo) & (depth <= hi)
    pos = in_band & (mask == 1)
    neg = in_band & (mask == 2)
    n_pos, n_neg = int(pos.sum()), int(neg.sum())
    print(f"  cells in the {lo:.0f}-{hi:.0f} m band: "
          f"kelp {n_pos}, faunal turf {n_neg}")

    out = {"band": [lo, hi], "n_pos": n_pos, "n_neg": n_neg, "covariates": {}}
    if min(n_pos, n_neg) < MIN_N_PER_CLASS:
        print(f"  >>> fewer than {MIN_N_PER_CLASS} cells in one class inside")
        print("  >>> the band. The classes barely overlap in depth, which is")
        print("  >>> itself a finding: there is almost no depth-independent")
        print("  >>> evidence available, so the other covariates cannot be")
        print("  >>> tested and must not be claimed to contribute.")
        out["verdict"] = "no_overlap"
        return out

    # Depth inside the band is the sanity check: it should now be near 0.5,
    # because that is what "holding depth constant" is supposed to achieve. If
    # it is not, the band is too wide and the whole test is contaminated.
    covars = {"depth (control)": depth, **covars}

    print(f"\n  {'covariate':<22}{'n_pos':>7}{'n_neg':>7}{'AUC':>8}   verdict")
    for cname, arr in covars.items():
        if arr is None:
            print(f"  {cname:<22}{'-':>7}{'-':>7}{'-':>8}   not available")
            out["covariates"][cname] = {"auc": None, "verdict": "unavailable"}
            continue
        ok = np.isfinite(arr)
        p = arr[pos & ok].tolist()
        q = arr[neg & ok].tolist()
        if min(len(p), len(q)) < MIN_N_PER_CLASS:
            print(f"  {cname:<22}{len(p):>7}{len(q):>7}{'-':>8}   too few")
            out["covariates"][cname] = {"auc": None, "verdict": "too_few",
                                        "n_pos": len(p), "n_neg": len(q)}
            continue
        a = auc_separation(p, q)
        if abs(a - 0.5) < COND_NULL_TOL:
            v = "adds nothing"
        elif a < COND_USEFUL:
            v = "marginal"
        else:
            v = "CONTRIBUTES"
        print(f"  {cname:<22}{len(p):>7}{len(q):>7}{a:>8.3f}   {v}")
        out["covariates"][cname] = {"auc": round(a, 4), "verdict": v,
                                    "n_pos": len(p), "n_neg": len(q)}

    ctrl = out["covariates"].get("depth (control)", {}).get("auc")
    if ctrl is not None and ctrl > 0.65:
        print(f"\n  >>> WARNING: depth still separates at {ctrl:.3f} INSIDE the")
        print("  >>> band, so depth is not actually held constant and every")
        print("  >>> other number above is partly depth again. Narrow the")
        print("  >>> band before believing them.")
        out["control_ok"] = False
    else:
        out["control_ok"] = True

    useful = [c for c, d in out["covariates"].items()
              if c != "depth (control)" and d.get("verdict") == "CONTRIBUTES"]
    dead = [c for c, d in out["covariates"].items()
            if c != "depth (control)" and d.get("verdict") == "adds nothing"]
    print(f"\n  contributes : {useful or 'NONE'}")
    print(f"  adds nothing: {dead or 'none'}")
    if not useful:
        print("  >>> NO COVARIATE ADDS ANYTHING once depth is held constant.")
        print("  >>> The honest product is then a DEPTH-BAND model, and it")
        print("  >>> must be described as one. A multi-term model whose extra")
        print("  >>> terms do no work is worse than a one-term model that is")
        print("  >>> labelled as such - the jury can check.")
    out["useful"], out["dead"] = useful, dead
    return out


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    import geopandas as gpd
    from pyproj import Transformer
    from shapely.geometry import box as sbox

    print("SELFTEST (no network, no files)\n")

    # --- terrain() against analytic surfaces ------------------------------
    g = 50.0
    yy, xx = np.mgrid[0:9, 0:9].astype(float)
    plane = 3.0 * (xx * g) / 100.0                       # slope 3% in x
    sl, cv = terrain(plane, g)
    assert abs(np.nanmean(sl) - math.degrees(math.atan(0.03))) < 1e-6
    assert abs(np.nanmax(np.abs(cv))) < 1e-9
    print(f"  terrain(): plane -> slope {np.nanmean(sl):.4f} deg, "
          f"curvature 0  ok")

    para = ((xx * g) ** 2 + (yy * g) ** 2) * 1e-4         # Laplacian = 4e-4
    _, cv2 = terrain(para, g)
    assert abs(np.nanmean(cv2) - 4e-4) < 1e-12, np.nanmean(cv2)
    print(f"  terrain(): paraboloid -> curvature {np.nanmean(cv2):.2e} "
          f"(analytic 4.00e-04)  ok")

    # A shoal must give POSITIVE curvature with depth positive down.
    shoal = np.full((5, 5), 20.0)
    shoal[2, 2] = 10.0
    _, cvs = terrain(shoal, g)
    assert cvs[2, 2] > 0, cvs[2, 2]
    print(f"  terrain(): shoal -> positive curvature  ok")

    # NaN must propagate, not be invented.
    holed = plane.copy()
    holed[4, 4] = np.nan
    sl3, _ = terrain(holed, g)
    assert not np.isfinite(sl3[4, 3]) and not np.isfinite(sl3[3, 4])
    print("  terrain(): a missing depth yields NaN, never a fabricated value"
          "  ok")

    # --- auc_separation is direction-free ---------------------------------
    assert abs(auc_separation([1, 2], [10, 20]) - 1.0) < 1e-12
    assert abs(auc_separation([10, 20], [1, 2]) - 1.0) < 1e-12
    assert abs(auc_separation([1, 2, 3], [1, 2, 3]) - 0.5) < 1e-12
    print("  auc_separation: folds both directions, 0.5 when identical  ok")

    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)
    to_wgs = Transformer.from_crs(CRS_FOR_AREA, 4326, always_xy=True)
    # A synthetic bbox, deliberately larger than a real AOI. An earlier
    # version used the real kenmare_river box and produced only 29 boundary
    # samples, so test 2 aborted on "too few" and proved nothing. The geometry
    # a test runs on has to be big enough for the test to be able to conclude.
    bbox = [-9.93, 51.70, -9.63, 51.90]        # about 21 x 22 km
    grid_m = 200.0
    lons, lats, _, _ = grid_axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)

    # Two adjacent strips: kelp west, faunal turf east.
    assert ny > 60 and nx > 60, (ny, nx)   # enough cells for test 2 to decide
    # The shared boundary must sit at the MIDDLE of the bbox, because the
    # synthetic depth ramp below runs 2 -> 40 m across the full width and
    # therefore passes through ~20 m exactly there. An earlier version placed
    # the strips off-centre, so the boundary sat at 13 m, the contour test
    # correctly found no clustering at 20 m, and the assertion failed for a
    # reason that had nothing to do with the code under test.
    jmid = nx // 2
    xw, yw = to_itm.transform(lons[3], lats[3])
    xm, _ = to_itm.transform(lons[jmid], lats[3])
    xe, ye = to_itm.transform(lons[nx - 4], lats[-4])
    kelp = sbox(xw, yw, xm, ye)
    turf = sbox(xm, yw, xe, ye)
    gdf = gpd.GeoDataFrame(
        {"Community": ["Laminaria-dominated reef", "Faunal turf reef"],
         "Source": ["NPWS CO Series: dive and video survey", "ditto"],
         "Rational": ["observed community composition", "observed"]},
        geometry=[kelp, turf], crs=CRS_FOR_AREA)

    mask, conf = class_mask(bbox, grid_m, gdf, to_itm)
    assert (mask == 1).sum() > MIN_N_PER_CLASS, (mask == 1).sum()
    assert (mask == 2).sum() > MIN_N_PER_CLASS, (mask == 2).sum()
    assert conf == 0
    print(f"\n  class_mask: {int((mask == 1).sum())} kelp cells, "
          f"{int((mask == 2).sum())} turf cells, 0 conflicts  ok")

    # --- TEST 1: must flag an inference word, and must NOT flag clean text --
    print("\n  --- test 1, clean provenance ---")
    assert test_provenance(gdf)["verdict"] == "no_inference_words"
    dirty = gdf.copy()
    dirty.loc[dirty["Community"] == "Laminaria-dominated reef", "Rational"] = \
        "extent inferred from bathymetry, 20 m contour"
    print("\n  --- test 1, provenance naming depth ---")
    r1 = test_provenance(dirty)
    assert r1["verdict"] == "inference_words_present", r1
    assert any("bathymetr" in f["words"] or "depth" in f["words"]
               or "contour" in f["words"] for f in r1["flagged"]), r1
    print("\n  provenance: clean passes, depth-derived is flagged  ok")

    # --- TEST 2: a depth field that IS a contour, and one that is not ------
    # Depth increasing west->east, so the kelp/turf join sits on one contour.
    ramp = np.tile(np.linspace(2.0, 40.0, nx), (ny, 1))
    # sanity-check the fixture itself before trusting the test that uses it
    assert abs(ramp[0, jmid] - SUSPECT_CONTOUR_M) < CONTOUR_TOLERANCE_M, \
        ("fixture is wrong: boundary column is at "
         f"{ramp[0, jmid]:.1f} m, not near {SUSPECT_CONTOUR_M:.0f} m")
    print("\n  --- test 2, boundary lies on a contour ---")
    r2a = test_contour(gdf, bbox, grid_m, ramp, to_wgs)
    assert r2a["verdict"] == "contour_following", r2a

    # Depth varying north-south instead, so the west-east join crosses all
    # depths and cannot be a contour. MUST give the other answer.
    ramp_ns = np.tile(np.linspace(2.0, 40.0, ny).reshape(-1, 1), (1, nx))
    print("\n  --- test 2, boundary crosses all depths ---")
    r2b = test_contour(gdf, bbox, grid_m, ramp_ns, to_wgs)
    assert r2b["verdict"] == "independent", r2b
    print("\n  contour test: contour-following AND independent both detected"
          "  ok")

    # --- TEST 3: a covariate that contributes, and one that does not -------
    # Depth constant so the band holds everything and the control reads 0.5.
    flat = np.full((ny, nx), 15.0)
    useful = np.where(mask == 1, 4.0, 3.0).astype(float)   # tracks the class
    useless = np.tile(np.linspace(0, 1, nx), (ny, 1))      # unrelated ramp
    noise = np.full((ny, nx), 7.0)                         # constant
    print("\n  --- test 3, one useful and two useless covariates ---")
    r3 = test_conditional(mask, flat, {"useful": useful, "ns_ramp": useless,
                                       "constant": noise},
                          band=(10.0, 20.0))
    assert r3["covariates"]["useful"]["verdict"] == "CONTRIBUTES", r3
    assert r3["covariates"]["constant"]["verdict"] == "adds nothing", r3
    assert r3["control_ok"] is True, r3
    assert "useful" in r3["useful"] and "constant" in r3["dead"], r3

    # And the all-useless case must report NO useful covariate, or the test
    # above only proves the function can say yes.
    print("\n  --- test 3, nothing useful at all ---")
    r3b = test_conditional(mask, flat, {"constant": noise}, band=(10.0, 20.0))
    assert r3b["useful"] == [], r3b

    # The contaminated-band guard must fire when depth is NOT held constant.
    print("\n  --- test 3, band too wide (guard must fire) ---")
    steep = np.where(mask == 1, 11.0, 19.0).astype(float)
    r3c = test_conditional(mask, steep, {"constant": noise}, band=(10.0, 20.0))
    assert r3c["control_ok"] is False, r3c
    print("\n  conditional test: contributes / adds nothing / contaminated"
          " band all detected  ok")

    # --- depth grid + cache round-trip ------------------------------------
    def fake(pts):
        return {i: 12.0 for i in range(0, len(pts), 2)}
    dg = sample_depth_grid("selftest", bbox, grid_m, use_cache=False,
                           depth_fn=fake)
    assert dg.shape == (ny, nx)
    assert 0.4 < np.isfinite(dg).mean() < 0.6, np.isfinite(dg).mean()
    print(f"\n  depth grid: shape {dg.shape}, "
          f"{np.isfinite(dg).mean():.0%} surveyed, holes preserved  ok")

    print("\nSELFTEST PASSED. terrain() matches analytic slope and curvature")
    print("and propagates NaN; provenance flags depth-derived text and not")
    print("clean text; the contour test returns both verdicts; the conditional")
    print("test finds a real covariate, rejects a useless one, and catches a")
    print("contaminated band. Nothing here touched INFOMAR.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Is the depth separation circular, and do the other "
                    "covariates contribute anything?")
    ap.add_argument("--shp", type=Path,
                    help='path to "21 NPWSArticle17Habitat.shp" (quote it)')
    ap.add_argument("--fetch", type=Path,
                    help="Burrows log10 wave-fetch GeoTIFF")
    ap.add_argument("--aoi", default="kenmare_river", choices=sorted(AOIS),
                    help="AOI to test (default kenmare_river - the only one "
                         "with both classes)")
    ap.add_argument("--grid", type=float, default=GRID_M_DEFAULT)
    ap.add_argument("--band", type=float, nargs=2, default=list(COND_BAND),
                    metavar=("MIN_M", "MAX_M"),
                    help="depth band for test 3")
    ap.add_argument("--no-cache", action="store_true",
                    help="refetch INFOMAR depth instead of using the cache")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not HAVE_COMMON:
        print("cannot import common.py - run from the repo root.")
        return 2
    if not args.shp:
        ap.error("--shp is required (or --selftest)")
    if not args.shp.exists():
        print(f"not found: {args.shp}  (quote the path, it has a space)")
        return 2
    if args.fetch and not args.fetch.exists():
        print(f"fetch raster not found: {args.fetch}")
        return 2

    import geopandas as gpd
    from pyproj import Transformer

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)
    to_wgs = Transformer.from_crs(CRS_FOR_AREA, 4326, always_xy=True)
    name, bbox = args.aoi, AOIS[args.aoi]

    print("NPWS layer 21 x INFOMAR bathymetry (GSI & Marine Institute, "
          "CC BY 4.0).")
    if args.fetch:
        print("Wave fetch: Burrows, figshare. LICENCE STILL UNREAD - do not "
              "publish from this until it is.")
    print(f"AOI {name}, grid {args.grid:.0f} m. Depth is metres below LAT, "
          "positive down.\n")

    gdf = gpd.read_file(args.shp)
    if gdf.crs is None:
        print("  >>> no CRS on the layer. Stopping.")
        return 2
    gdf = gdf.to_crs(epsg=CRS_FOR_AREA)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    bad = ~gdf.geometry.is_valid
    if int(bad.sum()):
        gdf.loc[bad, "geometry"] = gdf.loc[bad].geometry.buffer(0)
    if "Extent" in gdf.columns:
        before = len(gdf)
        gdf = gdf[gdf["Extent"].map(norm).str.lower() == "subtidal"].copy()
        print(f"  Subtidal filter: {before} -> {len(gdf)} polygons")

    # Clip to the AOI so the boundary geometry is local, not national.
    from shapely.geometry import box as sbox
    x0, y0 = to_itm.transform(bbox[0], bbox[1])
    x1, y1 = to_itm.transform(bbox[2], bbox[3])
    clip = sbox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    local = gdf[gdf.geometry.intersects(clip)].copy()
    local["geometry"] = local.geometry.intersection(clip)
    local = local[local.geometry.notna() & ~local.geometry.is_empty].copy()
    print(f"  polygons in the AOI: {len(local)}")

    print("\n" + "=" * 74)
    print("TEST 1  PROVENANCE - what does the layer say about its own source?")
    print("=" * 74)
    r1 = test_provenance(local)

    print("\n" + "=" * 74)
    print("SAMPLING DEPTH GRID")
    print("=" * 74)
    depth = sample_depth_grid(name, bbox, args.grid,
                              use_cache=not args.no_cache)
    slope, curv = terrain(depth, args.grid)
    fetch = sample_fetch_grid(args.fetch, bbox, args.grid) if args.fetch \
        else None
    mask, conf = class_mask(bbox, args.grid, local, to_itm)
    print(f"  labelled cells: kelp {int((mask == 1).sum())}, "
          f"faunal turf {int((mask == 2).sum())}, conflicts {conf}")

    print("\n" + "=" * 74)
    print(f"TEST 2  IS THE CLASS BOUNDARY THE {SUSPECT_CONTOUR_M:.0f} m "
          "CONTOUR?")
    print("=" * 74)
    r2 = test_contour(local, bbox, args.grid, depth, to_wgs)

    print("\n" + "=" * 74)
    print("TEST 3  WITH DEPTH HELD CONSTANT, WHAT STILL SEPARATES THE CLASSES?")
    print("=" * 74)
    r3 = test_conditional(mask, depth,
                          {"slope (deg)": slope, "curvature": curv,
                           "log10 fetch": fetch},
                          band=(args.band[0], args.band[1]))

    print("\n" + "=" * 74)
    print("WHAT THIS MEANS FOR THE MODEL")
    print("=" * 74)
    circ = r2.get("verdict")
    if circ == "contour_following":
        print("  The depth separation is largely the surveyors' own rule.")
        print("  -> do NOT present depth as a predictor. Take the depth band")
        print("     as given and report only what the other covariates add.")
    elif circ == "independent":
        print("  The depth separation is an observed pattern, not a mapping")
        print("  rule. The 0.954 baseline stands and can be presented.")
    else:
        print(f"  Contour test: {circ}. Use cautious wording.")
    if r3.get("useful"):
        print(f"  Covariates that survive holding depth constant: "
              f"{r3['useful']}")
        print("  -> those, plus depth, are the model. Drop the rest and say so.")
    else:
        print("  No covariate survives holding depth constant.")
        print("  -> the honest deliverable is a depth-band model. Say that")
        print("     plainly; a jury can check a model with dead terms in it.")

    (OUT_DIR / "circularity_verdicts.json").write_text(json.dumps(
        {"aoi": name, "grid_m": args.grid, "provenance": r1, "contour": r2,
         "conditional": r3}, indent=2, default=str), encoding="utf-8")
    print(f"\n  written: {OUT_DIR / 'circularity_verdicts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())