#!/usr/bin/env python3
"""
national_asset_screen.py -- the receptor screen, widened from BUILDINGS to
every mapped built asset.

THE GAP THIS CLOSES
-------------------
Every receptor screen this project has run -- Mizen (11 Aug), wide (27 Aug),
national exposure (28 Aug) -- counted OSM buildings and nothing else. The
28 August note then reports the result as

    "47 sites -- no occupied-tag building below 5 m at all. The receptor
     term is zero before the flood test is reached."

That sentence is true and it is not the sentence the valuation needs. A road,
a pier, a substation, a water main, a caravan park and a national monument are
all damage receptors. "No buildings" is not "no receptors", and the screen has
never looked. This script looks, at all 50 classes in `asset_classes.py`,
across the same 53 strict-fetch-passing clusters with habitat evidence.

WHAT IT DOES, PER CLUSTER
-------------------------
  1  pulls every OSM element in five family queries (transport,
     coastal_marine, utilities, public_community, land_parcels) with FULL
     GEOMETRY, not centroids -- see WHY GEOMETRY below;
  2  classifies each element locally against `asset_classes.CLASSES`, so an
     element may count in several classes and nothing is hidden by the
     choice of a single tag;
  3  clips each element to the pre-registered 500 m receptor disc;
  4  samples Copernicus GLO-30 ALONG the clipped geometry, not at a
     centroid, and takes the MINIMUM non-water elevation;
  5  samples the imported, unmodified FetchSampler at the receptor's
     seaward-most point, so "does this thing face water that passes the
     gate" is asked of the receptor, not of the cluster centroid;
  6  cross-checks internally against the OPW extents (counts only,
     CLAUDE.md rule 9);
  7  writes one cache file per cluster and stops. NO EURO IS COMPUTED HERE.

WHY GEOMETRY, NOT CENTROIDS
---------------------------
A building's centroid is a fair summary of a building. A road's centroid is
not a fair summary of a road: the coast road at Kilcummin runs from the pier
at 3 m to the top of the hill at 40 m, and its centroid is neither. A linear
or areal asset is damaged where it is LOWEST, so the elevation of an extended
receptor is the minimum along the part of it inside the receptor disc.

    PRE-REGISTERED, fixed before any cluster was screened:
      receptor set    every element of any class in asset_classes.CLASSES
                      whose geometry comes within RECEPTOR_RADIUS_M (500 m,
                      IMPORTED from national_exposure_screen, not re-chosen)
                      of the cluster centroid
      elevation       point element  -> GLO-30 at the point
                      extended       -> minimum of the non-water GLO-30
                                        samples taken every SAMPLE_STEP_M
                                        (20 m) along the clipped geometry,
                                        plus its vertices
      low bands       < 5 m and < 10 m, unchanged from the building screen
      gate            per-receptor strict fetch pass at its seaward-most
                      point, FETCH_EXCLUSION_MAX imported unchanged
      EXPOSED         low (< 5 m) AND facing gate-passing water

    THIS IS NOT THE SAME QUANTITY AS THE BUILDING SCREEN'S COUNT, and the
    difference is in the honest direction. Minimum-along-geometry finds low
    ground a centroid misses, so an extended asset flags more readily than a
    point one. Both `n_low_5m` (elevation only, comparable to the 28 Aug
    building count) and `n_exposed` (elevation AND gate) are reported for
    every class, and neither is ever presented as the other.

WHAT "EXPOSED" STILL DOES NOT MEAN
----------------------------------
Unchanged from 28 August, limitation 1: below 5 m is LOW-LYING, which is
necessary for overtopping exposure and not sufficient. There is no damage
function here, no with/without forcing difference and no overtopping model.
A non-zero count is a FLAG FOR REVIEW, never a finding and never a euro.

AND WHAT A ZERO MEANS DEPENDS ON THE CLASS
------------------------------------------
`asset_classes` labels every class high / medium / low for OSM completeness
in rural Ireland. A zero in a "low" class -- manholes, culverts, pipelines,
street cabinets, sewerage, telecom, minor power -- is NOT evidence that the
asset is absent. It is evidence that OSM does not record one. Every table
this script writes carries the level beside the count, and the summary
refuses to total a "low" class into any absence claim.

RESUMABILITY AND THE 28 AUGUST DOWNGRADE HAZARD
-----------------------------------------------
Overpass and INFOMAR have both gone down mid-run in this project. Design for
it, not around it:
  * every Overpass response is cached by query hash (imported `overpass()`,
    12 retries with backoff over 4 mirrors);
  * every CLUSTER writes a complete cache file, atomically, only when it
    finished; a re-run reads it and does no network at all;
  * the locked rule of 28 August is enforced in code here: a re-run may
    never replace a COMPLETE cached cluster with an incomplete one. See
    `_load_cache`. A time budget can stop the run; it cannot make the
    answer worse.

PROVENANCE
----------
  OSM assets / coastline    (c) OpenStreetMap contributors, ODbL 1.0
  Copernicus WorldDEM-30 (GLO-30)  -- notice reproduced from
      national_exposure_screen.GLO30_NOTICE
  Burrows fetch raster, EPSG:27700, imported sampler, unmodified
  OPW National Coastal Flood Hazard Maps 2022 -- CC BY-NC-ND 4.0,
      UNRESOLVED. INTERNAL COUNTS ONLY. No visual derivative. CLAUDE.md
      rule 9.

Run:
    PYTHONPATH=src python src/national_asset_screen.py
    PYTHONPATH=src python src/national_asset_screen.py --clusters 596,1043
    PYTHONPATH=src python src/national_asset_screen.py --budget-min 90
Read-only with respect to every locked artefact. Writes only under
outputs/asset_screen/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning,
                        message=".*shape on a NumPy array.*")

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely.geometry import (LineString, MultiLineString, MultiPoint,
                              MultiPolygon, Point, Polygon)
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_classes as ac  # noqa: E402
from national_exposure_screen import (  # noqa: E402
    GLO30_NOTICE,
    LOW_BANDS_M,
    OPW_LAYERS,
    RECEPTOR_RADIUS_M,
    WATER_FLAT_VALUE,
    _glo30_tile_for,
    _glo30_tile_url,
    opw_union,
    sample_glo30,
    select_clusters,
)
from wide_receptor_screen import (  # noqa: E402
    FETCH_EXCLUSION_MAX,
    FETCH_RASTER,
    ITM,
    WGS,
    FetchSampler,
    overpass,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "asset_screen"
CACHE = OUT / "cache"

# ---------------------------------------------------- pre-registered values
# RECEPTOR_RADIUS_M, LOW_BANDS_M, FETCH_EXCLUSION_MAX are all IMPORTED above.
# The only new parameter this screen introduces is the sampling step, and it
# is a sampling density, not a threshold: 20 m on a 30 m raster guarantees no
# pixel along a clipped way is skipped.
SAMPLE_STEP_M = 20.0
MAX_SAMPLES_PER_FEATURE = 400      # a clipped 500 m disc cannot need more
BOX_HALF_M = 800.0                 # unchanged from the building screen
BOXES_PER_QUERY = 5                # smaller than the building screen's 10:
                                   # `out geom` payloads are far larger than
                                   # `out center` ones
CACHE_VERSION = 5

GLO30_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


def hr(title: str = "") -> None:
    print("\n" + "=" * 78)
    if title:
        print(title)
        print("=" * 78)


# ======================================================================
# GLO-30, read once per window instead of once per point
# ======================================================================
# `national_exposure_screen.sample_glo30` opens the COG over /vsicurl and
# calls rasterio's sample() per point. That is fine for 1 096 buildings and
# hopeless for the ~200 000 samples this screen takes along clipped
# geometries. This reads ONE window per cluster per tile into memory and
# indexes it directly.
#
# It must return exactly what sample_glo30 returns, or it is a different
# screen wearing the same name. `control_glo30_patch()` asserts that on the
# real building set before the national run starts, and main() refuses to
# continue if it fails.
# ======================================================================

MAX_PATCH_DEG = 0.5     # a patch is a CLUSTER-sized window, never a national one


class Glo30Patch:
    """In-memory GLO-30 window covering a small bbox, sampled by nearest pixel.

    Deliberately refuses a large bbox. The first version of this class took
    the bbox of every point handed to it, which for a national point set is
    ~5 degrees across; it then read a boundless window of that size out of
    each 1-degree tile and returned mostly NaN. The control below caught it.
    A patch is a per-cluster object and the guard makes that structural
    rather than a convention.
    """

    def __init__(self, lon_min, lat_min, lon_max, lat_max, pad_deg=0.01):
        os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
        os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
        lon_min -= pad_deg; lat_min -= pad_deg
        lon_max += pad_deg; lat_max += pad_deg
        if (lon_max - lon_min) > MAX_PATCH_DEG or (lat_max - lat_min) > MAX_PATCH_DEG:
            raise ValueError(
                "Glo30Patch bbox %.3f x %.3f deg exceeds MAX_PATCH_DEG=%.2f. "
                "A patch is a per-cluster window; build one per cluster."
                % (lon_max - lon_min, lat_max - lat_min, MAX_PATCH_DEG))
        self.parts = []
        # every integer tile that could overlap, tested against its REAL
        # bounds (Copernicus tiles are pixel-centre registered and start half
        # a pixel outside the whole degree -- the 28 Aug tile-edge bug)
        for la in range(math.floor(lat_min) - 1, math.floor(lat_max) + 2):
            for lo in range(math.floor(lon_min) - 1, math.floor(lon_max) + 2):
                try:
                    with rasterio.open("/vsicurl/%s" % _glo30_tile_url(la, lo)) as s:
                        left, bottom, right, top = s.bounds
                        if (right < lon_min or left > lon_max
                                or top < lat_min or bottom > lat_max):
                            continue
                        w_l, w_b = max(left, lon_min), max(bottom, lat_min)
                        w_r, w_t = min(right, lon_max), min(top, lat_max)
                        # INTEGER offsets computed here rather than via
                        # round_offsets/round_shape, for two reasons the
                        # control found in successive runs:
                        #  * a float window makes the read and the window
                        #    transform disagree by up to half a pixel, and
                        #    the sampler then silently returns a neighbour
                        #    (max |diff| 18.4 m in steep ground);
                        #  * round_offsets floors the origin without growing
                        #    the width, so the window can fall one pixel
                        #    short at the far edge -- which lost exactly one
                        #    point, at lon -10.00046, half a pixel inside the
                        #    W011 tile edge. A one-pixel margin removes it.
                        w0 = rasterio.windows.from_bounds(
                            w_l, w_b, w_r, w_t, transform=s.transform)
                        c0 = int(math.floor(w0.col_off)) - 1
                        r0 = int(math.floor(w0.row_off)) - 1
                        cw = int(math.ceil(w0.col_off + w0.width)) - c0 + 1
                        ch = int(math.ceil(w0.row_off + w0.height)) - r0 + 1
                        win = rasterio.windows.Window(c0, r0, cw, ch)
                        arr = s.read(1, window=win, boundless=True,
                                     fill_value=np.nan).astype(float)
                        tr = rasterio.windows.transform(win, s.transform)
                        nodata = s.nodata
                        bounds = (left, bottom, right, top)
                except Exception:                             # noqa: BLE001
                    continue
                if nodata is not None:
                    arr = np.where(arr == nodata, np.nan, arr)
                self.parts.append({"arr": arr, "inv": ~tr, "shape": arr.shape,
                                   "bounds": bounds})

    def sample(self, pts_wgs) -> np.ndarray:
        out = np.full(len(pts_wgs), np.nan, dtype=float)
        if not pts_wgs or not self.parts:
            return out
        lons = np.array([p[0] for p in pts_wgs], dtype=float)
        lats = np.array([p[1] for p in pts_wgs], dtype=float)
        for part in self.parts:
            left, bottom, right, top = part["bounds"]
            # only points genuinely inside this tile's real bounds -- the same
            # containment test _glo30_tile_for uses, so a point at a tile edge
            # is read from the tile that actually holds it
            ok = (lons >= left) & (lons <= right) & (lats >= bottom) & (lats <= top)
            ok &= ~np.isfinite(out)
            if not ok.any():
                continue
            cols, rows = part["inv"] * (lons[ok], lats[ok])
            cols = np.floor(np.asarray(cols)).astype(int)
            rows = np.floor(np.asarray(rows)).astype(int)
            ny, nx = part["shape"]
            good = (rows >= 0) & (rows < ny) & (cols >= 0) & (cols < nx)
            idx = np.nonzero(ok)[0]
            vals = np.full(idx.size, np.nan)
            vals[good] = part["arr"][rows[good], cols[good]]
            out[idx] = vals
        return out


def control_glo30_patch(max_clusters: int = 12) -> dict:
    """Does the window sampler reproduce sample_glo30 on the real receptors?

    Run on the 28 August building receptor file -- the actual points behind
    the published elevations, not synthetic coordinates -- and run it the way
    the screen uses it: ONE patch per cluster. A control that exercised the
    class differently from the caller would prove nothing about the caller.
    """
    f = REPO / "outputs" / "exposure_screen" / "national_exposure_receptors.csv"
    if not f.exists():
        return {"ran": False, "reason": "no building receptor file to test against"}
    d = pd.read_csv(f)
    d = d[np.isfinite(d.lon) & np.isfinite(d.lat)]
    if not len(d):
        return {"ran": False, "reason": "building receptor file has no coordinates"}
    clusters = sorted(d.cluster.unique())
    rng = np.random.default_rng(0)
    if len(clusters) > max_clusters:
        clusters = sorted(rng.choice(clusters, max_clusters, replace=False).tolist())
    n_pts = n_cmp = nan_mismatch = 0
    dmax = 0.0
    for cl in clusters:
        sub = d[d.cluster == cl]
        pts = list(zip(sub.lon.astype(float), sub.lat.astype(float)))
        if not pts:
            continue
        ref = sample_glo30(pts)
        patch = Glo30Patch(min(p[0] for p in pts), min(p[1] for p in pts),
                           max(p[0] for p in pts), max(p[1] for p in pts))
        got = patch.sample(pts)
        both = np.isfinite(ref) & np.isfinite(got)
        n_pts += len(pts)
        n_cmp += int(both.sum())
        nan_mismatch += int((np.isfinite(ref) != np.isfinite(got)).sum())
        if both.any():
            dmax = max(dmax, float(np.max(np.abs(ref[both] - got[both]))))
    res = {"ran": True, "n_clusters": len(clusters), "n": n_pts,
           "n_compared": n_cmp, "max_abs_diff_m": dmax,
           "nan_mismatch": nan_mismatch,
           "passed": bool(n_cmp > 0 and dmax == 0.0 and nan_mismatch == 0)}
    print("   %d clusters, %d points, %d comparable, max |diff| = %s m, "
          "NaN mismatches %d" % (len(clusters), n_pts, n_cmp, dmax, nan_mismatch))
    if res["passed"]:
        print("   CONTROL PASSED -- the window sampler is bit-identical to "
              "sample_glo30 on the real receptor set.")
    else:
        print("   >>> CONTROL FAILED. The fast sampler is not the same "
              "sampler. Nothing below this line should be believed.",
              file=sys.stderr)
    return res


# ======================================================================
# OSM -- five family queries, full geometry
# ======================================================================
# Selectors are deliberately BROADER than asset_classes: pull the key, then
# classify locally. A regex in an Overpass query that does not match is
# silent, and silence is exactly the failure mode this whole session exists
# to remove. Pulling `way["man_made"]` and filtering in Python means a
# man_made value we did not anticipate shows up in the unclassified log
# rather than vanishing.

FAMILY_SELECTORS = {
    "transport": [
        'way["highway"]', 'node["highway"]', 'relation["highway"]',
        'way["railway"]', 'node["railway"]', 'relation["railway"]',
        'way["aeroway"]', 'node["aeroway"]',
        'way["bridge"]', 'way["tunnel"]',
        'way["ford"]', 'node["ford"]',
        'node["amenity"="ferry_terminal"]', 'way["amenity"="ferry_terminal"]',
        'way["amenity"~"^parking"]', 'node["amenity"~"^parking"]',
        'relation["route"="ferry"]', 'way["route"="ferry"]',
    ],
    "coastal_marine": [
        'way["man_made"]', 'node["man_made"]', 'relation["man_made"]',
        'way["harbour"]', 'node["harbour"]',
        'way["leisure"="marina"]', 'node["leisure"="marina"]',
        'way["leisure"="slipway"]', 'node["leisure"="slipway"]',
        'way["waterway"="dock"]', 'node["waterway"="dock"]',
        'way["barrier"]', 'node["barrier"]',
        'node["seamark:type"]', 'way["seamark:type"]',
        'way["industrial"]', 'node["industrial"]', 'way["craft"]',
    ],
    "utilities": [
        'way["power"]', 'node["power"]', 'relation["power"]',
        'way["pipeline"]', 'node["pipeline"]',
        'way["substance"]', 'node["substance"]',
        'node["telecom"]', 'way["telecom"]',
        'way["waterway"~"^(culvert|sewer)$"]',
        'way["utility"]', 'node["utility"]',
    ],
    "public_community": [
        'way["amenity"]', 'node["amenity"]', 'relation["amenity"]',
        'way["emergency"]', 'node["emergency"]',
        'way["tourism"]', 'node["tourism"]', 'relation["tourism"]',
        'way["leisure"]', 'node["leisure"]', 'relation["leisure"]',
        'way["historic"]', 'node["historic"]', 'relation["historic"]',
        'way["heritage"]', 'node["heritage"]',
        'relation["boundary"="protected_area"]',
    ],
    "land_parcels": [
        'way["landuse"]', 'relation["landuse"]',
    ],
}


def _geom_from_element(el: dict):
    """Shapely geometry from an Overpass element carrying `out geom`."""
    t = el.get("type")
    if t == "node":
        if el.get("lon") is None:
            return None
        return Point(el["lon"], el["lat"])
    if t == "way":
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry") or []
               if p and p.get("lon") is not None]
        if len(pts) < 2:
            return Point(pts[0]) if pts else None
        if len(pts) >= 4 and pts[0] == pts[-1]:
            try:
                g = Polygon(pts)
                if g.is_valid and g.area > 0:
                    return g
            except Exception:                                 # noqa: BLE001
                pass
        return LineString(pts)
    if t == "relation":
        parts = []
        for m in el.get("members") or []:
            g = m.get("geometry")
            if not g:
                continue
            pts = [(p["lon"], p["lat"]) for p in g if p and p.get("lon") is not None]
            if len(pts) >= 2:
                parts.append(LineString(pts))
        if parts:
            return unary_union(parts)
        c = el.get("center")
        if c:
            return Point(c["lon"], c["lat"])
    return None


def fetch_assets_for_boxes(boxes: list, log) -> tuple:
    """All five families plus coastline over a list of WGS bboxes.

    Returns (elements dataframe with shapely WGS geometry, coastline union).
    """
    rows: list = []
    clines: list = []
    seen: set = set()
    unclassified: dict = {}

    for i in range(0, len(boxes), BOXES_PER_QUERY):
        chunk = boxes[i:i + BOXES_PER_QUERY]
        bbs = ["%.6f,%.6f,%.6f,%.6f" % (b[1], b[0], b[3], b[2]) for b in chunk]

        for fam, sels in FAMILY_SELECTORS.items():
            parts = "".join("%s(%s);" % (s, bb) for bb in bbs for s in sels)
            q = "[out:json][timeout:300];(%s);out geom tags;" % parts
            payload = overpass(q)
            n_new = 0
            for el in payload.get("elements", []):
                oid = "%s/%s" % (el.get("type"), el.get("id"))
                if oid in seen:
                    continue
                tags = el.get("tags") or {}
                keys = ac.classify(tags)
                if not keys:
                    # record what we pulled and did not classify, so a tag
                    # value nobody anticipated is visible rather than silent
                    for k, v in tags.items():
                        if k in ("man_made", "amenity", "leisure", "barrier",
                                 "landuse", "power", "railway", "highway",
                                 "seamark:type", "waterway", "industrial"):
                            unclassified["%s=%s" % (k, v)] = \
                                unclassified.get("%s=%s" % (k, v), 0) + 1
                    continue
                g = _geom_from_element(el)
                if g is None or g.is_empty:
                    continue
                seen.add(oid)
                rows.append({"osm_id": oid, "family_query": fam,
                             "classes": keys,
                             "primary_class": ac.primary_class(keys),
                             "name": tags.get("name"),
                             "tags": json.dumps(tags, ensure_ascii=False),
                             "geometry": g})
                n_new += 1
            log("   boxes %d-%d %-16s +%d elements (%d total)"
                % (i + 1, i + len(chunk), fam, n_new, len(rows)))

        parts = "".join('way["natural"="coastline"](%s);' % bb for bb in bbs)
        q_c = "[out:json][timeout:300];(%s);out geom;" % parts
        for el in overpass(q_c).get("elements", []):
            pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
            if len(pts) >= 2:
                clines.append(LineString(pts))

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS) if rows else \
        gpd.GeoDataFrame({"osm_id": [], "family_query": [], "classes": [],
                          "primary_class": [], "name": [], "tags": []},
                         geometry=[], crs=WGS)
    coast = gpd.GeoDataFrame(geometry=clines, crs=WGS)
    if len(coast):
        coast = coast[~coast.geometry.duplicated()].reset_index(drop=True)
    return gdf, coast, unclassified


# ======================================================================
# geometry helpers
# ======================================================================

def sample_points_along(geom, step: float = SAMPLE_STEP_M) -> list:
    """Points at which to read elevation for one clipped receptor.

    A point feature gives one point. An extended feature gives its vertices
    plus a `step`-spaced walk along it, because the elevation that matters
    for a road or a pier is the lowest one anywhere along it, and a vertex
    walk alone can stride over a dip on a long straight segment.
    """
    if geom is None or geom.is_empty:
        return []
    gt = geom.geom_type
    if gt == "Point":
        return [(geom.x, geom.y)]
    if gt in ("MultiPoint", "GeometryCollection", "MultiPolygon",
              "MultiLineString"):
        pts: list = []
        for g in geom.geoms:
            pts.extend(sample_points_along(g, step))
            if len(pts) > MAX_SAMPLES_PER_FEATURE:
                break
        return pts[:MAX_SAMPLES_PER_FEATURE]
    if gt == "Polygon":
        pts = sample_points_along(geom.exterior, step)
        try:
            rp = geom.representative_point()
            pts.append((rp.x, rp.y))
        except Exception:                                     # noqa: BLE001
            pass
        return pts[:MAX_SAMPLES_PER_FEATURE]
    # LineString / LinearRing
    pts = list(geom.coords)
    L = geom.length
    if L > 0:
        n = min(int(L / step) + 1, MAX_SAMPLES_PER_FEATURE)
        for k in range(n + 1):
            p = geom.interpolate(min(k * step, L))
            pts.append((p.x, p.y))
    return pts[:MAX_SAMPLES_PER_FEATURE]


N_SEAWARD_CANDIDATES = 6


def seaward_fetch(geom, fs: FetchSampler):
    """Where along this receptor is the water, and what is its fetch?

    A 900 m coast road has one end at the water and one end inland; asking
    "what water does this face" at its midpoint answers a question about the
    middle of a road. So the fetch is sampled at the receptor's SEAWARD-MOST
    point.

    "Seaward-most" is defined by the FETCH RASTER, not by the OSM coastline.
    That is deliberate. The first version used `natural=coastline` and it was
    absent from 3 of the first 4 cluster boxes -- partly genuine (OSM maps
    some Irish inlets as water bodies rather than coastline) and partly the
    poisoned-mirror bug (see overpass_audit.py). A gate test that silently
    degrades to "the middle of the feature" whenever a tag is missing is not
    a test. The Burrows raster's sea cells are present everywhere on this
    coast by construction, and `FetchSampler.sample` already reports the
    distance to the nearest one.

    Up to N_SEAWARD_CANDIDATES points are tried -- both ends, the
    lowest-elevation sample, and an even spread -- and the one nearest a sea
    cell wins. Bounded on purpose: sampling every 20 m point would be ~200k
    raster window reads.
    """
    if geom is None or geom.is_empty:
        return None, FetchSampler._empty()
    pts = sample_points_along(geom, step=max(SAMPLE_STEP_M, 50.0))
    if not pts:
        rp = geom.representative_point()
        return rp, fs.sample(rp.x, rp.y)
    if len(pts) > N_SEAWARD_CANDIDATES:
        idx = np.linspace(0, len(pts) - 1, N_SEAWARD_CANDIDATES).astype(int)
        pts = [pts[i] for i in dict.fromkeys(idx.tolist())]
    best_p, best_f, best_d = None, None, np.inf
    for (x, y) in pts:
        f = fs.sample(x, y)
        d = f["dist_to_sea_m"]
        if not np.isfinite(d):
            continue
        if d < best_d:
            best_p, best_f, best_d = Point(x, y), f, d
    if best_p is None:
        rp = geom.representative_point()
        return rp, fs.sample(rp.x, rp.y)
    return best_p, best_f


# ======================================================================
# per-cluster cache -- and the 28 August no-downgrade rule
# ======================================================================

def _cache_path(cluster: int) -> Path:
    return CACHE / ("cluster_%d.json" % cluster)


def _load_cache(cluster: int) -> dict | None:
    """Return a COMPLETE cached cluster result, or None.

    LOCKED RULE, 2026-08-28: 'A resumable job may never write a verdict
    weaker than the one already on disk.' The enforcement is here and in
    `_save_cache`: only a result marked complete is ever loaded, and only a
    complete result is ever written. A run that dies mid-cluster leaves no
    file, so the next run redoes that cluster from scratch rather than
    inheriting half of it.
    """
    p = _cache_path(cluster)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                         # noqa: BLE001
        return None
    if not d.get("complete") or d.get("cache_version") != CACHE_VERSION:
        return None
    return d


def _save_cache(cluster: int, payload: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["complete"] = True
    payload["cache_version"] = CACHE_VERSION
    payload["written_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = _cache_path(cluster).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_cache_path(cluster))          # atomic on Windows and POSIX


# ======================================================================
# the screen, one cluster
# ======================================================================

def screen_cluster(row, assets: gpd.GeoDataFrame, coast_u, fs: FetchSampler,
                   to_itm, to_wgs, log) -> tuple:
    cl = int(row.cluster)
    cx, cy = to_itm.transform(float(row.lon), float(row.lat))
    centre = Point(cx, cy)
    disc = centre.buffer(RECEPTOR_RADIUS_M)

    if len(assets):
        a_itm = assets.to_crs(ITM)
        hit = a_itm.geometry.intersects(disc)
        near = a_itm[hit].copy()
    else:
        near = assets.copy()

    # ONE coastline union for the whole cluster. Computing it inside the
    # per-receptor loop made shore distance O(n) unions per cluster.
    coast_itm = (coast_u.to_crs(ITM).union_all()
                 if coast_u is not None and len(coast_u) else None)

    recs: list = []
    if len(near):
        clipped = near.geometry.intersection(disc)
        # elevation: one GLO-30 window for the whole cluster
        allpts_wgs: list = []
        spans: list = []
        for g in clipped:
            pts = sample_points_along(g)
            wgs_pts = [to_wgs.transform(x, y) for (x, y) in pts]
            spans.append((len(allpts_wgs), len(wgs_pts)))
            allpts_wgs.extend(wgs_pts)
        if allpts_wgs:
            lons = [p[0] for p in allpts_wgs]
            lats = [p[1] for p in allpts_wgs]
            patch = Glo30Patch(min(lons), min(lats), max(lons), max(lats))
            elev = patch.sample(allpts_wgs)
        else:
            elev = np.array([])

        for k, (idx, (oid, cls, pcls, nm, tg)) in enumerate(zip(
                near.index, zip(near.osm_id, near.classes, near.primary_class,
                                near.name, near.tags))):
            g_full = near.geometry.loc[idx]
            g = clipped.loc[idx]
            s0, sn = spans[k]
            e = elev[s0:s0 + sn] if sn else np.array([])
            e = e[np.isfinite(e)]
            water = e == WATER_FLAT_VALUE
            land = e[~water]
            sp, f = seaward_fetch(g, fs)
            gate = (np.isfinite(f["fetch_nearest_min"])
                    and f["fetch_nearest_min"] > FETCH_EXCLUSION_MAX)
            gate_lenient = (np.isfinite(f["fetch_nearest_max"])
                            and f["fetch_nearest_max"] > FETCH_EXCLUSION_MAX)
            sp_wgs = to_wgs.transform(sp.x, sp.y) if sp is not None else (None, None)
            emin = float(land.min()) if land.size else float("nan")
            recs.append({
                "cluster": cl,
                "osm_id": oid,
                "classes": ";".join(cls),
                "primary_class": pcls,
                "family": ac.BY_KEY[pcls]["family"] if pcls else None,
                "completeness": ac.BY_KEY[pcls]["completeness"] if pcls else None,
                "name": nm,
                "geom_type": g.geom_type,
                "geom_type_full": g_full.geom_type,
                "n_elev_samples": int(e.size),
                "n_water_pixel_samples": int(water.sum()),
                "len_in_disc_m": (round(float(g.length), 1)
                                  if g.geom_type in ("LineString", "MultiLineString",
                                                     "LinearRing") else None),
                "area_in_disc_m2": (round(float(g.area), 1)
                                    if g.geom_type in ("Polygon", "MultiPolygon")
                                    else None),
                "dist_cluster_m": round(float(g.distance(centre)), 1),
                "dist_shore_m": (round(float(g.distance(coast_itm)), 1)
                                 if coast_itm is not None else None),
                "elev_min_m": None if not np.isfinite(emin) else round(emin, 2),
                "elev_p50_m": (round(float(np.median(land)), 2)
                               if land.size else None),
                "elev_max_m": (round(float(land.max()), 2) if land.size else None),
                "all_samples_water": bool(e.size > 0 and land.size == 0),
                "seaward_lon": sp_wgs[0], "seaward_lat": sp_wgs[1],
                "fetch_min": (None if not np.isfinite(f["fetch_nearest_min"])
                              else round(float(f["fetch_nearest_min"]), 3)),
                "fetch_max": (None if not np.isfinite(f["fetch_nearest_max"])
                              else round(float(f["fetch_nearest_max"]), 3)),
                "fetch_n_tied": int(f["n_tied"]),
                "dist_to_sea_m": (None if not np.isfinite(f["dist_to_sea_m"])
                                  else round(float(f["dist_to_sea_m"]))),
                "gate_pass_strict": bool(gate),
                "gate_pass_lenient": bool(gate_lenient),
                "low_5m": bool(land.size and land.min() < LOW_BANDS_M[0]),
                "low_10m": bool(land.size and land.min() < LOW_BANDS_M[1]),
                "exposed": bool(land.size and land.min() < LOW_BANDS_M[0] and gate),
                "tags": tg,
            })

    rdf = pd.DataFrame(recs)

    # ---- OPW internal cross-check (counts only, CLAUDE.md rule 9) ----
    opw: dict = {}
    if len(rdf):
        sub = near.copy()
        subclip = near.geometry.intersection(disc)
        for label, code in OPW_LAYERS:
            u, n = opw_union(cx, cy, 2000.0, code)
            if u is None:
                opw[label] = {"polygons_2km": 0, "extent_mapped_in_box": False,
                              "intersecting": 0, "contained": 0,
                              "intersecting_osm_ids": []}
                continue
            inter = subclip.apply(lambda g, u=u: bool(g.intersects(u)))
            cont = subclip.apply(lambda g, u=u: bool(u.contains(g)))
            opw[label] = {
                "polygons_2km": int(n), "extent_mapped_in_box": True,
                "intersecting": int(inter.sum()), "contained": int(cont.sum()),
                "intersecting_osm_ids": list(sub.loc[inter[inter].index, "osm_id"]),
            }

    # ---- per-class summary ----
    per_class: dict = {}
    for key in ac.KEYS:
        if len(rdf):
            m = rdf.classes.str.split(";").apply(lambda ks, k=key: k in ks)
            s = rdf[m]
        else:
            s = rdf
        if not len(s):
            per_class[key] = {"n": 0, "n_low_5m": 0, "n_low_10m": 0,
                              "n_gate_pass": 0, "n_exposed": 0,
                              "elev_min_m": None,
                              "completeness": ac.BY_KEY[key]["completeness"]}
            continue
        el = s.elev_min_m.dropna()
        per_class[key] = {
            "n": int(len(s)),
            "n_low_5m": int(s.low_5m.sum()),
            "n_low_10m": int(s.low_10m.sum()),
            "n_gate_pass": int(s.gate_pass_strict.sum()),
            "n_exposed": int(s.exposed.sum()),
            "elev_min_m": (round(float(el.min()), 2) if len(el) else None),
            "completeness": ac.BY_KEY[key]["completeness"],
        }

    summary = {
        "cluster": cl, "county": row.county, "nearest_place": row.nearest_place,
        "lon": float(row.lon), "lat": float(row.lat),
        "evidence_class": row.evidence_class,
        "fetch_nearest_min": float(row.fetch_nearest_min),
        "fetch_nearest_max": float(row.fetch_nearest_max),
        "n_assets": int(len(rdf)),
        "n_low_5m": int(rdf.low_5m.sum()) if len(rdf) else 0,
        "n_low_10m": int(rdf.low_10m.sum()) if len(rdf) else 0,
        "n_gate_pass": int(rdf.gate_pass_strict.sum()) if len(rdf) else 0,
        "n_exposed": int(rdf.exposed.sum()) if len(rdf) else 0,
        "n_exposed_high_completeness": (
            int(rdf[(rdf.exposed) & (rdf.completeness == "high")].shape[0])
            if len(rdf) else 0),
        "elev_min_m": (round(float(rdf.elev_min_m.min()), 2)
                       if len(rdf) and rdf.elev_min_m.notna().any() else None),
        "per_class": per_class,
        "opw_internal": opw,
        "families_present": (sorted(set(rdf.family.dropna())) if len(rdf) else []),
    }
    return summary, rdf


# ======================================================================
# main
# ======================================================================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clusters", default=None,
                    help="comma-separated cluster ids; default = all 53")
    ap.add_argument("--budget-min", type=float, default=None,
                    help="stop starting new clusters after this many minutes. "
                         "Cannot downgrade a completed cluster (28 Aug rule).")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the per-cluster cache and re-screen")
    args = ap.parse_args()

    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    logf = OUT / "national_asset_screen_run.log"
    lines: list = []

    def log(msg: str = "") -> None:
        print(msg)
        lines.append(msg)
        if len(lines) % 25 == 0:
            logf.write_text("\n".join(lines), encoding="utf-8")

    hr("NATIONAL ASSET SCREEN -- every mapped built receptor, not just buildings")
    log("run %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log("")
    log("IMPORTED, not re-declared:")
    log("   RECEPTOR_RADIUS_M   = %.0f m   (national_exposure_screen)" % RECEPTOR_RADIUS_M)
    log("   LOW_BANDS_M         = %s      (national_exposure_screen)" % (LOW_BANDS_M,))
    log("   FETCH_EXCLUSION_MAX = %s      (wide_receptor_screen, Mizen 11 Aug)"
        % FETCH_EXCLUSION_MAX)
    log("NEW here, and it is a sampling density rather than a threshold:")
    log("   SAMPLE_STEP_M       = %.0f m   along every extended receptor" % SAMPLE_STEP_M)
    log("")
    log("%d receptor classes in %d families" % (len(ac.CLASSES), len(ac.FAMILIES)))
    for lvl in ("high", "medium", "low"):
        ks = [c["key"] for c in ac.CLASSES if c["completeness"] == lvl]
        log("   completeness %-6s %2d classes: %s" % (lvl, len(ks), ", ".join(ks)))
    log("")
    log("GLO-30 notice: %s" % GLO30_NOTICE)
    log("OSM: (c) OpenStreetMap contributors, ODbL 1.0")

    hr("CONTROL -- fast GLO-30 window sampler vs sample_glo30")
    ctrl = control_glo30_patch()
    if ctrl.get("ran") and not ctrl.get("passed"):
        log("CONTROL FAILED -- aborting.")
        logf.write_text("\n".join(lines), encoding="utf-8")
        return 2
    log("GLO-30 sampler control: %s" % json.dumps(ctrl))

    sel = select_clusters()
    if args.clusters:
        want = {int(x) for x in args.clusters.split(",")}
        sel = sel[sel.cluster.isin(want)].reset_index(drop=True)
    log("\n%d clusters selected (strict fetch gate + habitat evidence E1/E2/E3)"
        % len(sel))

    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    fs = FetchSampler(FETCH_RASTER)

    summaries: list = []
    all_recs: list = []
    unclassified_all: dict = {}
    done_cached = 0
    stopped_on_budget = False

    try:
        for n, (_, row) in enumerate(sel.iterrows(), start=1):
            cl = int(row.cluster)
            cached = None if args.refresh else _load_cache(cl)
            if cached is not None:
                summaries.append(cached["summary"])
                all_recs.append(pd.DataFrame(cached["receptors"]))
                done_cached += 1
                log("[%2d/%2d] cluster %-5d %-9s CACHED  (%d assets, %d exposed)"
                    % (n, len(sel), cl, row.county,
                       cached["summary"]["n_assets"],
                       cached["summary"]["n_exposed"]))
                continue

            if args.budget_min is not None and \
                    (time.time() - t0) / 60.0 > args.budget_min:
                # The 28 August hazard, avoided by construction: a budget stop
                # NEVER writes a weaker verdict. Unreached clusters simply have
                # no cache file and no row; they are reported as not attempted,
                # which is a run-status flag and not a result.
                stopped_on_budget = True
                log("\nBUDGET REACHED after %.1f min -- stopping BEFORE starting "
                    "cluster %d. Completed clusters on disk are untouched."
                    % ((time.time() - t0) / 60.0, cl))
                break

            log("\n[%2d/%2d] cluster %-5d %-9s %s"
                % (n, len(sel), cl, row.county, row.nearest_place))
            cxb, cyb = to_itm.transform(float(row.lon), float(row.lat))
            corners = [to_wgs.transform(cxb + dx * BOX_HALF_M, cyb + dy * BOX_HALF_M)
                       for dx, dy in ((-1, -1), (1, 1))]
            box = (corners[0][0], corners[0][1], corners[1][0], corners[1][1])
            assets, coast, unc = fetch_assets_for_boxes([box], log)
            for k, v in unc.items():
                unclassified_all[k] = unclassified_all.get(k, 0) + v
            log("   %d classified elements, %d coastline ways"
                % (len(assets), len(coast)))

            summary, rdf = screen_cluster(row, assets, coast, fs, to_itm,
                                          to_wgs, log)
            log("   -> %d receptors in 500 m | %d below 5 m | %d pass gate "
                "| %d EXPOSED (%d in high-completeness classes)"
                % (summary["n_assets"], summary["n_low_5m"],
                   summary["n_gate_pass"], summary["n_exposed"],
                   summary["n_exposed_high_completeness"]))

            _save_cache(cl, {"summary": summary,
                             "receptors": rdf.to_dict(orient="records")})
            summaries.append(summary)
            all_recs.append(rdf)
    finally:
        fs.close()

    if not summaries:
        log("nothing screened")
        logf.write_text("\n".join(lines), encoding="utf-8")
        return 1

    sdf = pd.DataFrame([{k: v for k, v in s.items()
                         if k not in ("per_class", "opw_internal")}
                        for s in summaries])
    rdf_all = pd.concat([r for r in all_recs if len(r)], ignore_index=True) \
        if any(len(r) for r in all_recs) else pd.DataFrame()

    sdf.to_csv(OUT / "national_asset_screen.csv", index=False)
    if len(rdf_all):
        rdf_all.to_csv(OUT / "national_asset_receptors.csv", index=False)

    # ---- national per-class rollup ----
    rows = []
    for key in ac.KEYS:
        c = ac.BY_KEY[key]
        tot = {"n": 0, "n_low_5m": 0, "n_low_10m": 0, "n_gate_pass": 0,
               "n_exposed": 0}
        mins = []
        clusters_with = 0
        for s in summaries:
            pc = s["per_class"][key]
            for k in tot:
                tot[k] += pc[k]
            if pc["n"]:
                clusters_with += 1
            if pc["elev_min_m"] is not None:
                mins.append(pc["elev_min_m"])
        rows.append({"class": key, "family": c["family"], "label": c["label"],
                     "completeness": c["completeness"],
                     "clusters_with_any": clusters_with,
                     "n_total": tot["n"], "n_low_5m": tot["n_low_5m"],
                     "n_low_10m": tot["n_low_10m"],
                     "n_gate_pass": tot["n_gate_pass"],
                     "n_exposed": tot["n_exposed"],
                     "elev_min_m": min(mins) if mins else None})
    cls_df = pd.DataFrame(rows)
    cls_df.to_csv(OUT / "national_asset_by_class.csv", index=False)

    hr("PER-CLASS COVERAGE ACROSS %d CLUSTERS" % len(summaries))
    log("%-24s %-16s %-6s %6s %7s %8s %8s %8s"
        % ("class", "family", "compl", "clust", "n", "<5 m", "gate", "EXPOSED"))
    log("-" * 92)
    for _, r in cls_df.iterrows():
        log("%-24s %-16s %-6s %6d %7d %8d %8d %8d"
            % (r["class"], r["family"], r["completeness"],
               r["clusters_with_any"], r["n_total"], r["n_low_5m"],
               r["n_gate_pass"], r["n_exposed"]))

    hr("CLUSTERS WITH >0 EXPOSED NON-BUILDING RECEPTORS")
    fl = sdf[sdf.n_exposed > 0].sort_values("n_exposed", ascending=False)
    if len(fl):
        for _, r in fl.iterrows():
            log("cluster %-5d %-9s %-42s  %3d exposed / %3d receptors  min %s m"
                % (r.cluster, r.county, str(r.nearest_place)[:42],
                   r.n_exposed, r.n_assets, r.elev_min_m))
    else:
        log("none")
    fl.to_csv(OUT / "asset_flagged_clusters.csv", index=False)

    summ = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_min": round((time.time() - t0) / 60.0, 1),
        "clusters_selected": int(len(sel)),
        "clusters_screened": int(len(summaries)),
        "clusters_from_cache": done_cached,
        "stopped_on_budget": stopped_on_budget,
        "glo30_sampler_control": ctrl,
        "imported_parameters": {
            "RECEPTOR_RADIUS_M": RECEPTOR_RADIUS_M,
            "LOW_BANDS_M": list(LOW_BANDS_M),
            "FETCH_EXCLUSION_MAX": FETCH_EXCLUSION_MAX,
            "SAMPLE_STEP_M": SAMPLE_STEP_M},
        "n_receptors_total": int(len(rdf_all)),
        "n_low_5m_total": int(rdf_all.low_5m.sum()) if len(rdf_all) else 0,
        "n_exposed_total": int(rdf_all.exposed.sum()) if len(rdf_all) else 0,
        "completeness_meaning": ac.COMPLETENESS_MEANING,
        "unclassified_tag_values": dict(sorted(unclassified_all.items(),
                                               key=lambda kv: -kv[1])[:120]),
        "per_cluster": {str(s["cluster"]): s for s in summaries},
    }
    (OUT / "national_asset_screen_summary.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")

    hr("TOTALS")
    log("clusters screened      %d of %d (%d from cache)"
        % (len(summaries), len(sel), done_cached))
    log("receptors within 500 m %d" % len(rdf_all))
    log("   below 5 m           %d" % summ["n_low_5m_total"])
    log("   EXPOSED (low+gate)  %d" % summ["n_exposed_total"])
    log("elapsed                %.1f min" % summ["elapsed_min"])
    logf.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
