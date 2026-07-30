#!/usr/bin/env python3
"""
label_depths.py - two questions that must be answered before the model is
written, both of them about depth.

Run npws_labels.py first. This script assumes its findings:
  - layer 21 mapping is PATCHY, so blanks are unknowns, not absences
  - training labels are Laminaria-dominated reef (presence) vs Faunal turf
    reef (negative), both Subtidal
  - Geogenic Reef is NOT nested inside the target, but is still excluded here
    because it may be an uncharacterised class rather than a community

QUESTION 1 - DOES THE ROARINGWATER PITCH SURVIVE?
    The pitch is "absence of map, not absence of kelp". But NPWS DID map
    Roaringwater: 100 Faunal turf polygons at sherkin, 134 at inner
    Roaringwater. So a surveyor looked and did not call it kelp, which is not
    the same as nobody looking.

    The only thing that can rescue the pitch is depth. NPWS's own Roaringwater
    documentation records Laminaria communities down to about 20 m, with the
    community changing to echinoderm/sponge/hydroid/anemone fauna below 20 m.
    So:
      - if the Faunal turf polygons sit mostly BELOW 20 m, they are correctly
        labelled deep habitat, the shallow kelp band is genuinely unmapped,
        and the pitch stands.
      - if they spread across 0-20 m, then the kelp band WAS surveyed and was
        not called kelp, and the pitch has to be rewritten.

    This script does not decide which is more convenient. It measures.

QUESTION 2 - IS THE SIGNAL THE MODEL NEEDS ACTUALLY THERE?
    At Kenmare, is Laminaria-dominated reef measurably shallower than Faunal
    turf reef? If not, depth cannot separate the classes and the whole model
    design is built on an assumption that is not in the data. Better to find
    that out now than after building it.

    Reported as the probability that a randomly chosen Laminaria cell is
    shallower than a randomly chosen Faunal turf cell. That number IS the
    depth-only null model (M0) - it is exactly the AUC of a classifier that
    uses nothing but depth - so it also becomes the baseline every later model
    has to beat to justify its extra covariates.

HONEST LIMITS, BOTH GO ON THE SLIDE
  1. A grid cell only gets a depth if INFOMAR surveyed it. Cells with no depth
     are counted and reported separately, never dropped silently.
  2. INFOMAR's shallow coverage is the weakest part of its coverage (mizen_outer
     has zero samples at 0-5 m). That means shallow cells are the ones most
     likely to be missing, so the sampled depths for a SHALLOW class are biased
     towards the deeper part of its true range. This biases question 2 towards
     UNDERSTATING the separation, i.e. against our own hypothesis. Good
     direction, but it must be stated.
  3. Depths are metres below LAT, positive down. A value <= 0 is at or above
     LAT, i.e. intertidal, and is binned separately rather than lumped into
     the shallowest subtidal band.

Dependencies: geopandas (BSD-3), shapely (BSD-3), pyproj (MIT), requests
(Apache-2.0). All to DEPENDENCIES.md with versions.

Data: NPWS Reef Inventory 2023 layer 21; INFOMAR bathymetry (Geological Survey
Ireland & Marine Institute), CC BY 4.0.

Usage:
    python src/label_depths.py --selftest
    python src/label_depths.py --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp"
    python src/label_depths.py --shp "<path>" --grid 100
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path("outputs/labels")

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
# Classes sampled. Geogenic Reef is deliberately absent: npws_labels.py showed
# it does not overlap the target, but it is an origin word, not a community
# word, and mizen_outer carries it with no community label at all. Treating an
# uncharacterised class as "no kelp" is the exact mistake this whole analysis
# exists to avoid.
SAMPLED = (TARGET, HARD_NEGATIVE)

# The kelp band, from NPWS's own Roaringwater documentation.
KELP_BAND_MAX_M = 20.0
DEPTH_BINS = [("intertidal (<=0)", -math.inf, 0.0), ("0-5 m", 0.0, 5.0),
              ("5-10 m", 5.0, 10.0), ("10-20 m", 10.0, 20.0),
              ("20-30 m", 20.0, 30.0), (">30 m", 30.0, math.inf)]

GRID_M_DEFAULT = 50.0
BATCH = 400

# Pre-registered thresholds. Written before the numbers were seen so the
# verdict cannot be tuned to whatever the data happens to say.
PITCH_BROKEN_ABOVE = 0.50      # share of negative class inside the kelp band
PITCH_SURVIVES_BELOW = 0.25
AUC_USABLE = 0.70
AUC_WEAK = 0.55
MIN_N_PER_CLASS = 30           # below this, report but draw no conclusion


def norm(v) -> str:
    if v is None:
        return "(null)"
    s = " ".join(str(v).split())
    return s if s else "(null)"


# ---------------------------------------------------------------------------
# P(a shallower than b) - the depth-only null model
# ---------------------------------------------------------------------------

def auc_shallower(pos: list[float], neg: list[float]) -> float:
    """P(random pos is shallower than random neg), ties counted as one half.

    Rank-based (Mann-Whitney U) so it is O(n log n) rather than O(n^2). The
    self-test checks it against a brute-force double loop, because an
    off-by-one or a reversed sign here would silently invert the single most
    important number in this script.
    """
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
        avg = (i + j + 2) / 2.0                # ranks are 1-based
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1

    r_pos = sum(r for r, (_, g) in zip(ranks, combined) if g == 0)
    u_pos = r_pos - n1 * (n1 + 1) / 2.0        # P(pos deeper) + 0.5 P(tie)
    return 1.0 - u_pos / (n1 * n2)             # -> P(pos shallower) + 0.5 P(tie)


def quantiles(vals: list[float]) -> tuple[float, float, float]:
    """p25, median, p75 by nearest-rank. No numpy dependency."""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return (float("nan"),) * 3
    return (s[int(0.25 * (n - 1))], s[int(0.50 * (n - 1))],
            s[int(0.75 * (n - 1))])


# ---------------------------------------------------------------------------
# Grid, polygons, depth
# ---------------------------------------------------------------------------

def aoi_grid(bbox: list[float], grid_m: float) -> list[tuple[float, float]]:
    """Cell-centred regular lon/lat grid. Regular, so point share = area share."""
    lat_mid = (bbox[1] + bbox[3]) / 2.0
    dlon = grid_m / (111320.0 * math.cos(math.radians(lat_mid)))
    dlat = grid_m / 110574.0
    pts, y = [], bbox[1] + dlat / 2
    while y < bbox[3]:
        x = bbox[0] + dlon / 2
        while x < bbox[2]:
            pts.append((x, y))
            x += dlon
        y += dlat
    return pts


def classify_points(pts, gdf, transformer):
    """Which sampled Community class contains each grid point.

    Returns {point_index: community}. Points in no sampled class are absent.
    Overlap between the two sampled classes would be a data problem, so it is
    counted and reported rather than resolved by whichever polygon is hit first.
    """
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    keep = [(norm(c), g) for c, g in zip(gdf["Community"], gdf.geometry)
            if norm(c).lower() in SAMPLED and g is not None and not g.is_empty]
    if not keep:
        return {}, 0
    classes = [c for c, _ in keep]
    polys = [g for _, g in keep]
    tree = STRtree(polys)

    xs, ys = transformer.transform([p[0] for p in pts], [p[1] for p in pts])
    out, n_conflict = {}, 0
    for i, (x, y) in enumerate(zip(xs, ys)):
        pt = Point(x, y)
        hits = {classes[j] for j in tree.query(pt) if polys[j].covers(pt)}
        if not hits:
            continue
        if len(hits) > 1:
            n_conflict += 1        # a cell claimed by both classes: unusable
            continue
        out[i] = hits.pop()
    return out, n_conflict


def sample_depths(pts, idxs, depth_fn=None) -> dict[int, float]:
    """Depth below LAT, positive down, for the given point indices.

    THE EMPTY-BATCH RULE, proven 2026-07-27: an INFOMAR getSamples request
    whose points ALL fall outside raster coverage returns HTTP 400 rather than
    an empty list. So a 400 here means zero samples, not a bug.
    """
    if depth_fn is not None:
        return depth_fn(pts, idxs)

    idxs = list(idxs)
    depths, empty = {}, 0
    for start in range(0, len(idxs), BATCH):
        chunk_idx = idxs[start:start + BATCH]
        chunk = [[pts[i][0], pts[i][1]] for i in chunk_idx]
        try:
            payload = arcgis_request(f"{INFOMAR_BATHY}/getSamples", {
                "geometry": json.dumps({"points": chunk,
                                        "spatialReference": {"wkid": 4326}}),
                "geometryType": "esriGeometryMultipoint",
                "returnFirstValueOnly": "true",
                "interpolation": "RSP_NearestNeighbor", "f": "json"})
        except ArcGISError:
            empty += 1
            continue
        for s in payload.get("samples", []):
            loc, raw = s.get("locationId"), s.get("value")
            if loc is None or raw in (None, "", "NaN"):
                continue
            try:
                depths[chunk_idx[int(loc)]] = -float(str(raw).split()[0])
            except (ValueError, IndexError):
                continue
    if empty:
        print(f"    ({empty} batches entirely outside INFOMAR coverage "
              f"-> zero samples, not an error)")
    return depths


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report_aoi(name: str, bbox: list[float], gdf, grid_m: float,
               transformer, depth_fn=None) -> dict:
    cell_ha = (grid_m * grid_m) / 1e4
    pts = aoi_grid(bbox, grid_m)
    cls, n_conflict = classify_points(pts, gdf, transformer)
    if not cls:
        print("  neither sampled class is present in this box.")
        print("  >>> Layer 21 is clipped to SAC boundaries, so this may be a")
        print("  >>> coverage limit rather than an absence of habitat.")
        return {"aoi": name, "status": "no_sampled_class", "classes": {}}, []
    if n_conflict:
        print(f"  >>> {n_conflict} cells fall inside BOTH sampled classes and")
        print("  >>> were dropped. Overlapping labels are a data problem; if")
        print("  >>> this number is large the label set is not clean.")

    print(f"  grid {grid_m:.0f} m ({cell_ha:.2f} ha/cell), "
          f"{len(pts)} cells, {len(cls)} inside a sampled class")
    print("  sampling INFOMAR depth ...")
    depths = sample_depths(pts, sorted(cls), depth_fn)

    per_class: dict[str, list[float]] = defaultdict(list)
    nodepth: dict[str, int] = defaultdict(int)
    for i, c in cls.items():
        if i in depths:
            per_class[c].append(depths[i])
        else:
            nodepth[c] += 1

    rows, out = [], {"aoi": name, "grid_m": grid_m, "cell_ha": cell_ha,
                     "cells_conflicting": n_conflict, "classes": {}}

    for c in sorted(per_class, key=lambda k: -len(per_class[k])):
        vals = per_class[c]
        n_tot = len(vals) + nodepth[c]
        cov = len(vals) / n_tot if n_tot else 0.0
        p25, med, p75 = quantiles(vals)
        in_band = sum(1 for v in vals if 0.0 < v <= KELP_BAND_MAX_M)
        below = sum(1 for v in vals if v > KELP_BAND_MAX_M)
        inter = sum(1 for v in vals if v <= 0.0)
        band_share = in_band / len(vals) if vals else float("nan")

        print(f"\n  {c}")
        print(f"    cells in class          : {n_tot}  "
              f"({n_tot * cell_ha:.0f} ha)")
        print(f"    with an INFOMAR depth   : {len(vals)}  ({cov:.0%})"
              f"   no depth: {nodepth[c]}")
        if cov < 0.5:
            print("    >>> under half of this class has a depth measurement.")
            print("    >>> Every depth figure below describes the surveyed")
            print("    >>> subset only, not the class.")
        print(f"    depth p25 / med / p75   : {p25:.1f} / {med:.1f} / "
              f"{p75:.1f} m below LAT")
        print(f"    intertidal (<=0)        : {inter}  "
              f"({inter / len(vals):.0%})")
        print(f"    inside 0-{KELP_BAND_MAX_M:.0f} m kelp band : {in_band}  "
              f"({band_share:.0%})")
        print(f"    below {KELP_BAND_MAX_M:.0f} m             : {below}  "
              f"({below / len(vals):.0%})")

        hist = {}
        for label, lo, hi in DEPTH_BINS:
            k = sum(1 for v in vals if lo < v <= hi) if lo != -math.inf \
                else sum(1 for v in vals if v <= hi)
            hist[label] = k
        bar = "  ".join(f"{lbl}:{n}" for lbl, n in hist.items() if n)
        print(f"    by band                 : {bar}")

        out["classes"][c] = {
            "cells": n_tot, "ha": round(n_tot * cell_ha, 1),
            "with_depth": len(vals), "depth_coverage": round(cov, 4),
            "no_depth": nodepth[c],
            "p25": round(p25, 2), "median": round(med, 2), "p75": round(p75, 2),
            "n_intertidal": inter, "n_in_kelp_band": in_band,
            "n_below_band": below,
            "share_in_kelp_band": (round(band_share, 4)
                                   if band_share == band_share else None),
            "histogram": hist,
        }
        rows.append({"aoi": name, "community": c, "cells": n_tot,
                     "ha": round(n_tot * cell_ha, 1),
                     "with_depth": len(vals),
                     "depth_coverage": round(cov, 4),
                     "p25_m": round(p25, 2), "median_m": round(med, 2),
                     "p75_m": round(p75, 2),
                     "share_in_kelp_band": (round(band_share, 4)
                                            if band_share == band_share
                                            else "")})

    # ---- question 2, wherever both classes are present ----
    pos = per_class.get(
        next((c for c in per_class if c.lower() == TARGET), ""), [])
    neg = per_class.get(
        next((c for c in per_class if c.lower() == HARD_NEGATIVE), ""), [])
    if pos and neg:
        auc = auc_shallower(pos, neg)
        out["depth_only_auc"] = round(auc, 4)
        out["n_pos"], out["n_neg"] = len(pos), len(neg)
        print(f"\n  DEPTH-ONLY NULL MODEL (M0)")
        print(f"    P(a random kelp cell is shallower than a random faunal")
        print(f"    turf cell) = {auc:.3f}   [n_pos={len(pos)}, "
              f"n_neg={len(neg)}]")
        if min(len(pos), len(neg)) < MIN_N_PER_CLASS:
            out["depth_signal"] = "too_few"
            print(f"    >>> fewer than {MIN_N_PER_CLASS} cells in one class.")
            print("    >>> Reported, but no conclusion drawn from it.")
        elif auc < 0.45:
            out["depth_signal"] = "reversed"
            print("    >>> REVERSED: kelp is measurably DEEPER than faunal")
            print("    >>> turf. That contradicts NPWS's own description, so")
            print("    >>> something is wrong - check the depth sign, the LAT")
            print("    >>> datum, and the class filter before going further.")
        elif auc < AUC_WEAK:
            out["depth_signal"] = "absent"
            print("    >>> NO SIGNAL. Depth cannot separate the classes, so a")
            print("    >>> depth-led suitability model is not supported by the")
            print("    >>> data. STOP and rethink before building it.")
        elif auc < AUC_USABLE:
            out["depth_signal"] = "weak"
            print("    >>> WEAK. Depth alone is close to a coin toss. The")
            print("    >>> model will live or die on the other covariates, so")
            print("    >>> do not present depth as the main mechanism.")
        else:
            out["depth_signal"] = "present"
            print("    >>> SIGNAL PRESENT. Depth separates the classes. This")
            print("    >>> number is now the baseline: any fitted model must")
            print("    >>> beat it on spatially blocked folds, or its extra")
            print("    >>> covariates have not earned their place.")
    return out, rows


def pitch_verdict(results: list[dict]) -> dict:
    """Question 1: is the shallow kelp band at Roaringwater actually unmapped?"""
    boxes = ("sherkin_baltimore", "inner_roaringwater")
    tot_band, tot_with_depth, detail = 0, 0, {}
    for r in results:
        if r.get("aoi") not in boxes:
            continue
        for c, d in r.get("classes", {}).items():
            if c.lower() != HARD_NEGATIVE:
                continue
            tot_band += d["n_in_kelp_band"]
            tot_with_depth += d["with_depth"]
            detail[r["aoi"]] = {
                "share_in_kelp_band": d["share_in_kelp_band"],
                "median_m": d["median"], "with_depth": d["with_depth"],
                "depth_coverage": d["depth_coverage"]}

    print("\n" + "=" * 74)
    print("QUESTION 1  DOES THE ROARINGWATER PITCH SURVIVE?")
    print("=" * 74)
    if tot_with_depth == 0:
        print("  No Faunal turf cells with a depth in either Roaringwater box.")
        print("  >>> Cannot answer. Do NOT claim the pitch is safe.")
        return {"verdict": "unanswerable", "detail": detail}

    share = tot_band / tot_with_depth
    for aoi, d in detail.items():
        print(f"  {aoi}: {d['share_in_kelp_band']:.0%} of surveyed Faunal turf"
              f" inside 0-{KELP_BAND_MAX_M:.0f} m, median {d['median_m']:.1f} m"
              f" (depth coverage {d['depth_coverage']:.0%})")
    print(f"\n  combined: {tot_band} of {tot_with_depth} cells "
          f"({share:.1%}) inside the kelp band")

    if share > PITCH_BROKEN_ABOVE:
        verdict = "rewrite_required"
        print(f"\n  >>> PITCH MUST BE REWRITTEN. {share:.0%} of the mapped")
        print("  >>> Faunal turf sits INSIDE the kelp band, so NPWS surveyed")
        print("  >>> the shallow zone at Roaringwater and did not call it")
        print("  >>> kelp. 'Absence of map, not absence of kelp' is not")
        print("  >>> supportable as written. Honest replacement:")
        print('  >>>   "Roaringwater reefs are mapped only as community')
        print('  >>>    classes at coarse resolution; no Laminaria extent was')
        print('  >>>    delineated. We produce the first spatial estimate."')
        print("  >>> That is still a strong claim and it is true.")
    elif share < PITCH_SURVIVES_BELOW:
        verdict = "stands"
        print(f"\n  >>> PITCH STANDS. Only {share:.0%} of the mapped Faunal")
        print("  >>> turf is inside the kelp band, so the shallow zone is")
        print("  >>> genuinely unmapped and the Faunal turf polygons are")
        print("  >>> correctly labelled deeper habitat - consistent with")
        print("  >>> NPWS's own account of the community changing below 20 m.")
    else:
        verdict = "ambiguous"
        print(f"\n  >>> AMBIGUOUS at {share:.0%}. Between the pre-registered")
        print(f"  >>> {PITCH_SURVIVES_BELOW:.0%} and {PITCH_BROKEN_ABOVE:.0%}"
              " thresholds. Use the weaker,")
        print("  >>> defensible wording, not the stronger one.")
    return {"verdict": verdict, "share_in_kelp_band": round(share, 4),
            "detail": detail}


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    import geopandas as gpd
    from pyproj import Transformer
    from shapely.geometry import box as sbox

    print("SELFTEST (no network, no files)\n")

    # --- auc_shallower against a brute-force double loop -------------------
    def brute(pos, neg):
        tot = 0.0
        for a in pos:
            for b in neg:
                tot += 1.0 if a < b else (0.5 if a == b else 0.0)
        return tot / (len(pos) * len(neg))

    import random
    random.seed(7)
    for trial in range(200):
        p = [random.choice([1, 2, 3, 4, 5]) for _ in range(random.randint(2, 12))]
        q = [random.choice([1, 2, 3, 4, 5]) for _ in range(random.randint(2, 12))]
        fast, slow = auc_shallower(p, q), brute(p, q)
        assert abs(fast - slow) < 1e-9, (p, q, fast, slow)
    print("  auc_shallower == brute force on 200 random tie-heavy cases  ok")

    # Direction and the degenerate case must both be right.
    assert auc_shallower([1, 2], [10, 20]) == 1.0
    assert auc_shallower([10, 20], [1, 2]) == 0.0
    assert abs(auc_shallower([1, 2, 3], [1, 2, 3]) - 0.5) < 1e-12
    print("  auc direction: shallow->1.0, deep->0.0, identical->0.5  ok")

    # --- quantiles ---------------------------------------------------------
    assert quantiles([1, 2, 3, 4, 5])[1] == 3
    print("  quantiles median correct  ok")

    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)
    b = AOIS["kenmare_river"]

    def mk(rows):
        geoms = [r.pop("geometry") for r in rows]
        return gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS_FOR_AREA)

    # Two side-by-side strips inside the AOI, in ITM.
    x0, y0 = to_itm.transform(b[0] + 0.01, b[1] + 0.01)
    kelp = sbox(x0, y0, x0 + 1500, y0 + 1500)
    turf = sbox(x0 + 2000, y0, x0 + 3500, y0 + 1500)
    gdf = mk([
        {"Community": "Laminaria-dominated reef", "geometry": kelp},
        {"Community": "Faunal turf reef", "geometry": turf},
    ])

    # Depth functions keyed on which strip the point is in, so the synthetic
    # answer is known exactly.
    def make_depth(kelp_d, turf_d, drop_every_other=False):
        def fn(pts, idxs):
            out = {}
            for i in sorted(idxs):
                # Drop on the parity of the GLOBAL grid index. The grid is
                # regular and each class is a contiguous strip, so parity
                # alternates along every row and lands at ~50% within BOTH
                # classes. An earlier version keyed the drop on position in the
                # sorted index list, which gave 64% in one class and 37% in the
                # other - the test then failed for a reason that had nothing
                # to do with the code under test.
                if drop_every_other and (i % 2 == 0):
                    continue
                x, y = to_itm.transform(pts[i][0], pts[i][1])
                from shapely.geometry import Point
                out[i] = kelp_d if kelp.covers(Point(x, y)) else turf_d
            return out
        return fn

    # CASE A: strong separation. Must say "present".
    print("\n  --- case A: kelp at 8 m, turf at 35 m ---")
    resA, _ = report_aoi("kenmare_river", b, gdf, 100.0, to_itm,
                         make_depth(8.0, 35.0))
    assert resA["depth_signal"] == "present", resA
    assert resA["depth_only_auc"] == 1.0, resA

    # CASE B: no separation. Must say "absent", or case A proves nothing.
    print("\n  --- case B: both classes at 15 m ---")
    resB, _ = report_aoi("kenmare_river", b, gdf, 100.0, to_itm,
                         make_depth(15.0, 15.0))
    assert resB["depth_signal"] == "absent", resB

    # CASE C: reversed. Must be flagged, not quietly reported as good.
    print("\n  --- case C: kelp DEEPER than turf ---")
    resC, _ = report_aoi("kenmare_river", b, gdf, 100.0, to_itm,
                         make_depth(35.0, 8.0))
    assert resC["depth_signal"] == "reversed", resC
    print("\n  depth signal: present / absent / reversed all detected  ok")

    # --- no-depth cells must be counted, not silently dropped -------------
    print("\n  --- case D: only 50% of cells have a depth ---")
    resD, _ = report_aoi("kenmare_river", b, gdf, 100.0, to_itm,
                         make_depth(8.0, 35.0, drop_every_other=True))
    for c, d in resD["classes"].items():
        assert d["no_depth"] > 0, (c, d)
        # the invariant that actually matters: nothing vanishes
        assert d["with_depth"] + d["no_depth"] == d["cells"], (c, d)
        assert 0.45 <= d["depth_coverage"] <= 0.55, (c, d)
    print("  no-depth cells counted and coverage reported  ok")

    # --- QUESTION 1 verdict must be able to go both ways ------------------
    def fake_result(aoi, band_share, n=200):
        in_band = int(round(band_share * n))
        return {"aoi": aoi, "classes": {"Faunal turf reef": {
            "n_in_kelp_band": in_band, "with_depth": n, "median": 25.0,
            "share_in_kelp_band": band_share, "depth_coverage": 0.8}}}

    v_deep = pitch_verdict([fake_result("sherkin_baltimore", 0.05),
                            fake_result("inner_roaringwater", 0.10)])
    assert v_deep["verdict"] == "stands", v_deep
    v_shallow = pitch_verdict([fake_result("sherkin_baltimore", 0.80),
                               fake_result("inner_roaringwater", 0.75)])
    assert v_shallow["verdict"] == "rewrite_required", v_shallow
    v_mid = pitch_verdict([fake_result("sherkin_baltimore", 0.35),
                           fake_result("inner_roaringwater", 0.35)])
    assert v_mid["verdict"] == "ambiguous", v_mid
    v_none = pitch_verdict([])
    assert v_none["verdict"] == "unanswerable", v_none
    print("\n  pitch verdict: stands / rewrite / ambiguous / unanswerable"
          " all reachable  ok")

    # --- overlapping labels must be dropped and counted ------------------
    overlap = mk([
        {"Community": "Laminaria-dominated reef", "geometry": kelp},
        {"Community": "Faunal turf reef", "geometry": kelp},
    ])
    _, n_conf = classify_points(aoi_grid(b, 100.0), overlap, to_itm)
    assert n_conf > 0, n_conf
    print(f"  overlapping labels: {n_conf} conflicting cells dropped, not"
          " assigned to whichever came first  ok")

    print("\nSELFTEST PASSED. The AUC matches brute force including ties, all")
    print("three depth-signal verdicts and all four pitch verdicts are")
    print("reachable, no-depth cells are counted, and conflicting labels are")
    print("dropped. Nothing here touched INFOMAR.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Depth test for the NPWS labels: does the pitch survive, "
                    "and is the depth signal real?")
    ap.add_argument("--shp", type=Path,
                    help='path to "21 NPWSArticle17Habitat.shp" (quote it)')
    ap.add_argument("--grid", type=float, default=GRID_M_DEFAULT,
                    help=f"grid spacing in metres (default {GRID_M_DEFAULT:.0f})")
    ap.add_argument("--aoi", choices=sorted(AOIS))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not HAVE_COMMON:
        print("cannot import common.py - run this from the repo root:")
        print("  python src/label_depths.py --shp ...")
        return 2
    if not args.shp:
        ap.error("--shp is required (or --selftest)")
    if not args.shp.exists():
        print(f"not found: {args.shp}")
        print('Quote the path - the filename contains a space.')
        return 2

    import geopandas as gpd
    from pyproj import Transformer

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)

    print("NPWS layer 21 x INFOMAR bathymetry (GSI & Marine Institute, "
          "CC BY 4.0).")
    print("Depths are metres below LAT, positive down.\n")

    gdf = gpd.read_file(args.shp)
    if gdf.crs is None:
        print("  >>> no CRS on the layer. Stopping.")
        return 2
    gdf = gdf.to_crs(epsg=CRS_FOR_AREA)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    bad = ~gdf.geometry.is_valid
    if int(bad.sum()):
        gdf.loc[bad, "geometry"] = gdf.loc[bad].geometry.buffer(0)
    # Subtidal only: an intertidal polygon has no meaningful subtidal depth and
    # must not enter a subtidal model.
    if "Extent" in gdf.columns:
        before = len(gdf)
        gdf = gdf[gdf["Extent"].map(norm).str.lower() == "subtidal"].copy()
        print(f"  Subtidal filter: {before} -> {len(gdf)} polygons")

    targets = {args.aoi: AOIS[args.aoi]} if args.aoi else AOIS
    results, rows = [], []
    for name, bbox in targets.items():
        print("\n" + "=" * 74)
        print(f"AOI  {name}")
        print("=" * 74)
        res, rws = report_aoi(name, bbox, gdf, args.grid, to_itm)
        results.append(res)
        rows.extend(rws)

    pv = pitch_verdict(results)

    ken = next((r for r in results if r.get("aoi") == "kenmare_river"), None)
    print("\n" + "=" * 74)
    print("QUESTION 2  IS THE DEPTH SIGNAL REAL AT KENMARE?")
    print("=" * 74)
    if not ken or "depth_only_auc" not in ken:
        print("  kenmare_river was not measured, or one class was missing")
        print("  there. Rerun without --aoi before deciding anything.")
    else:
        print(f"  depth-only AUC = {ken['depth_only_auc']:.3f}  "
              f"({ken['depth_signal']})")
        print(f"  n_pos = {ken['n_pos']}, n_neg = {ken['n_neg']}")
        print("  >>> This is the number every later model must beat on")
        print("  >>> spatially blocked folds (blocks >= 1 km, because the")
        print("  >>> Burrows fetch layer is 200 m native).")

    if rows:
        p = OUT_DIR / "label_depths.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  written: {p}")
    (OUT_DIR / "label_depth_verdicts.json").write_text(json.dumps(
        {"pitch": pv, "per_aoi": results, "grid_m": args.grid,
         "kelp_band_max_m": KELP_BAND_MAX_M,
         "thresholds": {"pitch_broken_above": PITCH_BROKEN_ABOVE,
                        "pitch_survives_below": PITCH_SURVIVES_BELOW,
                        "auc_usable": AUC_USABLE, "auc_weak": AUC_WEAK}},
        indent=2), encoding="utf-8")
    print(f"  written: {OUT_DIR / 'label_depth_verdicts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())