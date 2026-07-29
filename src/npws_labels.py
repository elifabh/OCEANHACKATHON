#!/usr/bin/env python3
"""
npws_labels.py - the three measurements that decide the step 2 model form.

WHY THIS SCRIPT EXISTS
NPWS Article 17 layer 21 gives us labelled kelp for the first time. Before a
single line of model code is written, three things have to be measured, because
each one changes what kind of model is legitimate.

  MEASUREMENT 1 - WHAT ARE THE LABELS, EXACTLY?
      Distinct Community and Extent values, polygon counts and DISSOLVED area
      in real metres, per AOI. Three specific things are being looked for:
        - is there Intertidal Laminaria in the training box? It must be split
          out, because the Dubi & Torum / Mork wave-attenuation coefficients
          apply to subtidal L. hyperborea only.
        - do Community / Extent carry trailing-whitespace duplicates? The
          sibling INFOMAR layer published both "Infralittoral" and
          "Infralittoral " and an exact-match filter silently dropped one.
        - is "Faunal turf reef" present in useful quantity? It is the proposed
          HARD NEGATIVE: seabed a diver reached, on hard substrate, with no
          kelp. Without it the training set is presence-only.

  MEASUREMENT 2 - IS "Geogenic Reef" A PARENT CLASS?
      Nationally it is 767,435 ha against 54,913 ha of Laminaria-dominated
      reef. If Geogenic polygons sit ON TOP OF Laminaria polygons, the field is
      a nested classification and Geogenic CANNOT be used as a negative - doing
      so would label true kelp as absence and teach the model the opposite of
      the truth. Measured as the share of Laminaria area that is also covered
      by Geogenic.

  MEASUREMENT 3 - IS THE MAPPING WALL-TO-WALL OR PATCHY?
      This is the one that decides rule-based vs supervised. If NPWS classified
      every square metre of the surveyed area into some Community, then "no
      Laminaria polygon" inside that area means a surveyor looked and saw
      something else - a real absence, and a GAM is legitimate.
      If the mapping is isolated survey patches, "no polygon" means "nobody
      looked", the negatives are contaminated, and fitting to them would teach
      the model the SURVEY FOOTPRINT rather than the ecology.

      That distinction is not academic here. The Roaringwater pitch is exactly
      "absence of map, not absence of kelp". We cannot claim that for
      Roaringwater and simultaneously treat Kenmare's blanks as true zeros.

WHAT THIS SCRIPT DOES NOT DO
It does not fit a model, choose a threshold, or produce a habitat area for the
pitch. It establishes what the labels are. The model is the next script.

HONEST LIMIT ON MEASUREMENT 3
Without a land mask the denominator for "% of the box that is mapped" includes
land, so that percentage is a HARD LOWER BOUND on marine coverage, not an
estimate. Pass --land <coastline.shp> to get a real denominator. The coverage
curve and the component count do not depend on the land mask and are the
figures to lean on until one is supplied.

Dependencies: geopandas (BSD-3), shapely (BSD-3), pyproj (MIT).
All to DEPENDENCIES.md with versions.

Data: NPWS Reef Inventory 2023, layer 21 NPWSArticle17Habitat.shp.

Usage:
    python src/npws_labels.py --selftest
    python src/npws_labels.py --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp"
    python src/npws_labels.py --shp "<path>" --aoi kenmare_river
    python src/npws_labels.py --shp "<path>" --site Kenmare
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path("outputs/labels")

# ---------------------------------------------------------------------------
# Fallbacks so --selftest runs even if common.py is not importable. The real
# values always win; these exist only so the offline test cannot be blocked by
# an import problem.
# ---------------------------------------------------------------------------
try:
    from common import AOIS, CRS_FOR_AREA
except ImportError:                                       # pragma: no cover
    CRS_FOR_AREA = 2157
    AOIS = {
        "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
        "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
        "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
        "kenmare_river": [-9.93, 51.75, -9.78, 51.81],
    }

# The label we are trying to model.
TARGET = "laminaria-dominated reef"
# The proposed hard negative: surveyed, hard substrate, no kelp.
HARD_NEGATIVE = "faunal turf reef"
# The suspected parent/container class.
SUSPECT_PARENT = "geogenic reef"

# Closing radii for the survey-footprint curve, in metres. Reported for
# interpretation only - the verdict uses the adaptive merge radius below.
CLOSING_RADII_M = (50.0, 100.0, 250.0, 500.0, 1000.0)
# The adaptive test grows the closing radius from START, doubling, until the
# mapped area becomes one connected region or CAP is reached. CAP is 8 km
# because our AOI boxes are about 10 km across: beyond that the "region" would
# be the whole box and the reading would be meaningless.
MERGE_RADIUS_START_M = 50.0
MERGE_RADIUS_CAP_M = 8000.0
# Grid spacing for the box-coverage estimate, in metres.
COVERAGE_GRID_M = 50.0

# A parent class is declared if it covers this share of the target's area.
PARENT_OVERLAP_THRESHOLD = 0.50
# Mapping is called wall-to-wall if coverage stays this high out to the
# largest closing radius.
WALL_TO_WALL_THRESHOLD = 0.90


def norm(v) -> str:
    """Trim and collapse whitespace before any category is compared.

    Copied deliberately from seabed_folk_probe.py rather than imported,
    because that file is a probe and this one must not depend on it. The
    sibling INFOMAR layer published "Infralittoral" and "Infralittoral " as
    two distinct values; assume this layer can do the same until measured.
    """
    if v is None:
        return "(null)"
    s = " ".join(str(v).split())
    return s if s else "(null)"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def densified_box(bbox: list[float], n: int = 25):
    """AOI box as a lon/lat polygon with densified edges.

    Transforming only the four corners and rebuilding a rectangle in the target
    CRS is wrong: a line of constant latitude is not straight in Irish
    Transverse Mercator. Over a 10 km box the error is small, but it is free to
    avoid, and every area figure downstream inherits it.
    """
    from shapely.geometry import Polygon

    x0, y0, x1, y1 = bbox
    pts = []
    for i in range(n):                      # south edge, west -> east
        pts.append((x0 + (x1 - x0) * i / n, y0))
    for i in range(n):                      # east edge, south -> north
        pts.append((x1, y0 + (y1 - y0) * i / n))
    for i in range(n):                      # north edge, east -> west
        pts.append((x1 - (x1 - x0) * i / n, y1))
    for i in range(n):                      # west edge, north -> south
        pts.append((x0, y1 - (y1 - y0) * i / n))
    pts.append((x0, y0))
    return Polygon(pts)


def load_layer21(path: Path):
    """Read layer 21, repair geometry, reproject to CRS_FOR_AREA. Count losses."""
    import geopandas as gpd

    gdf = gpd.read_file(path)
    print(f"  features read : {len(gdf)}")
    if gdf.crs is None:
        print("  >>> NO CRS on this layer. It cannot be placed on the earth.")
        print("  >>> Find the CRS in the NPWS metadata and set it explicitly.")
        print("  >>> Do NOT assume WGS84 - layer 28 in this same download is")
        print("  >>> EPSG:29902, so the archive mixes projections.")
        return None
    print(f"  source CRS    : {gdf.crs}")
    print(f"  fields        : {', '.join(map(str, gdf.columns))}")

    for required in ("Community", "Extent"):
        if required not in gdf.columns:
            print(f"  >>> field '{required}' is NOT in this layer. This is not")
            print("  >>> layer 21, or the schema changed. Stopping.")
            return None

    gdf = gdf.to_crs(epsg=CRS_FOR_AREA)

    n0 = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    n_empty = n0 - len(gdf)

    bad = ~gdf.geometry.is_valid
    n_bad = int(bad.sum())
    if n_bad:
        gdf.loc[bad, "geometry"] = gdf.loc[bad].geometry.buffer(0)
    n1 = len(gdf)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty
              & gdf.geometry.is_valid].copy()
    n_unrepairable = n1 - len(gdf)

    if n_empty or n_bad or n_unrepairable:
        print(f"  geometry      : {n_empty} empty dropped, {n_bad} invalid "
              f"repaired, {n_unrepairable} UNREPAIRABLE and dropped")
    if n_unrepairable:
        print("  >>> The unrepairable polygons' area is missing from every")
        print("  >>> figure below. Counted, not silent.")

    gdf["_community"] = gdf["Community"].map(norm)
    gdf["_extent"] = gdf["Extent"].map(norm)
    return gdf


def clip_to(gdf, geom):
    """Clip a GeoDataFrame to a geometry, keeping attributes."""
    import geopandas as gpd

    hit = gdf[gdf.geometry.intersects(geom)].copy()
    if len(hit) == 0:
        return hit
    hit["geometry"] = hit.geometry.intersection(geom)
    hit = hit[hit.geometry.notna() & ~hit.geometry.is_empty].copy()
    return gpd.GeoDataFrame(hit, geometry="geometry", crs=gdf.crs)


def dissolved_km2(geoms) -> float:
    """Union then area, so overlapping polygons are not double-counted."""
    from shapely.ops import unary_union

    gl = [g for g in geoms if g is not None and not g.is_empty]
    if not gl:
        return 0.0
    return unary_union(gl).area / 1e6


# ---------------------------------------------------------------------------
# MEASUREMENT 0 - is Area_km trustworthy? (cheap, and we were burned before)
# ---------------------------------------------------------------------------

def area_field_check(gdf) -> dict:
    """Compare the published Area_km against area recomputed from geometry.

    Shape_Area on the INFOMAR substrate layer turned out to be Web Mercator,
    inflated 2.58x, which would have overstated the euro figure by that factor.
    Same class of trap, same one-line test, so it is run here too.
    """
    if "Area_km" not in gdf.columns:
        print("  Area_km not published by this layer - nothing to check.")
        return {"verdict": "field_absent"}

    ratios = []
    for published, geom in zip(gdf["Area_km"], gdf.geometry):
        try:
            p = float(published)
        except (TypeError, ValueError):
            continue
        own = geom.area / 1e6
        if p > 0 and own > 0:
            ratios.append(p / own)
    if len(ratios) < 5:
        print("  too few usable rows to judge Area_km. Ignoring it.")
        return {"verdict": "inconclusive", "n": len(ratios)}

    ratios.sort()
    med = ratios[len(ratios) // 2]
    print(f"  Area_km / our EPSG:{CRS_FOR_AREA} area : median {med:.3f} "
          f"(n={len(ratios)}, min {ratios[0]:.3f}, max {ratios[-1]:.3f})")
    if 0.97 <= med <= 1.03:
        verdict = "agrees"
        print("  >>> Area_km agrees with geometry. Still not used below -")
        print("  >>> every figure here is recomputed from geometry.")
    else:
        verdict = "disagrees"
        print(f"  >>> Area_km DISAGREES with geometry by {med:.2f}x. Do not")
        print("  >>> use it anywhere. Recompute, never rescale.")
    return {"verdict": verdict, "median_ratio": round(med, 4), "n": len(ratios)}


# ---------------------------------------------------------------------------
# MEASUREMENT 1 - what are the labels?
# ---------------------------------------------------------------------------

def whitespace_trap_check(gdf) -> list[str]:
    """Do Community / Extent carry values that differ only by whitespace?"""
    warnings = []
    for field in ("Community", "Extent"):
        raw = {str(v) for v in gdf[field].dropna().unique()}
        by_norm: dict[str, set] = defaultdict(set)
        for r in raw:
            by_norm[norm(r)].add(r)
        for cleaned, variants in by_norm.items():
            if len(variants) > 1:
                msg = (f"{field}: {sorted(repr(v) for v in variants)} differ "
                       f"only by whitespace -> '{cleaned}'")
                warnings.append(msg)
    if warnings:
        print("  >>> WHITESPACE TRAP PRESENT. Any exact-match filter on the")
        print("  >>> raw value silently drops one variant:")
        for w in warnings:
            print(f"        {w}")
        print("  >>> This script normalises. Make sure the model script does.")
    else:
        print("  no whitespace-duplicate values in Community or Extent  ok")
    return warnings


def describe(name: str, gdf) -> list[dict]:
    """Polygon count and DISSOLVED area per Community x Extent, in km2."""
    rows = []
    groups: dict[tuple, list] = defaultdict(list)
    for comm, ext, geom in zip(gdf["_community"], gdf["_extent"], gdf.geometry):
        groups[(comm, ext)].append(geom)

    print(f"\n  {'Community':<32}{'Extent':<14}{'n':>6}{'km2':>10}")
    for (comm, ext), geoms in sorted(groups.items(),
                                     key=lambda kv: -dissolved_km2(kv[1])):
        km2 = dissolved_km2(geoms)
        mark = ""
        if comm.lower() == TARGET:
            mark = "  <- TARGET"
        elif comm.lower() == HARD_NEGATIVE:
            mark = "  <- hard negative"
        elif comm.lower() == SUSPECT_PARENT:
            mark = "  <- suspected parent"
        print(f"  {comm[:31]:<32}{ext[:13]:<14}{len(geoms):>6}{km2:>10.3f}{mark}")
        rows.append({"aoi": name, "community": comm, "extent": ext,
                     "n_polygons": len(geoms), "km2": round(km2, 4)})

    tgt = [r for r in rows if r["community"].lower() == TARGET]
    tgt_sub = sum(r["km2"] for r in tgt if r["extent"].lower() == "subtidal")
    tgt_int = sum(r["km2"] for r in tgt if r["extent"].lower() == "intertidal")
    tgt_other = sum(r["km2"] for r in tgt) - tgt_sub - tgt_int
    neg = sum(r["km2"] for r in rows if r["community"].lower() == HARD_NEGATIVE)

    print(f"\n  TARGET subtidal      : {tgt_sub:.3f} km2 ({tgt_sub * 100:.0f} ha)")
    print(f"  TARGET intertidal    : {tgt_int:.3f} km2 ({tgt_int * 100:.0f} ha)")
    if tgt_other > 0:
        print(f"  TARGET other/unknown : {tgt_other:.3f} km2  <- check Extent")
    print(f"  HARD NEGATIVE        : {neg:.3f} km2 ({neg * 100:.0f} ha)")

    if tgt_int > 0:
        print("  >>> INTERTIDAL Laminaria is present. It must be excluded from")
        print("  >>> the subtidal model AND from the valuation: Dubi & Torum")
        print("  >>> (1996) and Mork (1996) are subtidal L. hyperborea only.")
    if tgt_sub > 0 and neg <= 0:
        print("  >>> NO HARD NEGATIVE HERE. The training set would be")
        print("  >>> presence-only and a fitted model would learn the survey")
        print("  >>> footprint. See measurement 3 before choosing a model.")
    return rows


# ---------------------------------------------------------------------------
# MEASUREMENT 2 - is the suspected parent class actually a parent?
# ---------------------------------------------------------------------------

def parent_class_test(gdf, child: str = TARGET,
                      parent: str = SUSPECT_PARENT) -> dict:
    """Share of the child class's area that is also covered by the parent."""
    from shapely.ops import unary_union

    ch = [g for c, g in zip(gdf["_community"], gdf.geometry)
          if c.lower() == child]
    pa = [g for c, g in zip(gdf["_community"], gdf.geometry)
          if c.lower() == parent]

    print(f"  '{child}' polygons  : {len(ch)}")
    print(f"  '{parent}' polygons : {len(pa)}")

    if not ch:
        print("  >>> No target polygons here, so the test cannot run. This is")
        print("  >>> NOT evidence that the classes are disjoint.")
        return {"verdict": "no_target_here", "n_child": 0, "n_parent": len(pa)}
    if not pa:
        print("  >>> No parent-class polygons here. Test inconclusive at this")
        print("  >>> extent - rerun with --site over the whole SAC.")
        return {"verdict": "no_parent_here", "n_child": len(ch),
                "n_parent": 0}

    cu, pu = unary_union(ch), unary_union(pa)
    child_km2 = cu.area / 1e6
    inter_km2 = cu.intersection(pu).area / 1e6
    frac = inter_km2 / child_km2 if child_km2 > 0 else 0.0

    print(f"  child area                 : {child_km2:.3f} km2")
    print(f"  child area also in parent  : {inter_km2:.3f} km2")
    print(f"  OVERLAP FRACTION           : {frac:.3f}")

    if frac >= PARENT_OVERLAP_THRESHOLD:
        verdict = "nested"
        print(f"  >>> '{parent}' IS A PARENT/CONTAINER CLASS. It must NEVER be")
        print("  >>> used as a negative: it sits on top of true kelp, so")
        print("  >>> labelling it absence would teach the model the opposite")
        print("  >>> of the truth.")
    elif frac <= 0.05:
        verdict = "disjoint"
        print(f"  >>> '{parent}' is DISJOINT from the target. It is usable as")
        print("  >>> an additional hard negative, alongside faunal turf reef.")
    else:
        verdict = "partial"
        print(f"  >>> PARTIAL overlap ({frac:.1%}). Neither safely a negative")
        print("  >>> nor safely independent. Exclude it and say so, rather")
        print("  >>> than picking whichever reading suits the result.")
    return {"verdict": verdict, "n_child": len(ch), "n_parent": len(pa),
            "child_km2": round(child_km2, 4),
            "overlap_km2": round(inter_km2, 4),
            "overlap_fraction": round(frac, 4)}


# ---------------------------------------------------------------------------
# MEASUREMENT 3 - wall-to-wall or patchy?
# ---------------------------------------------------------------------------

def survey_footprint(name: str, gdf, box_geom, land_geom=None) -> dict:
    """Three independent readings of how completely the box is mapped.

    (a) BOX COVERAGE. Share of the AOI box covered by any polygon. Without a
        land mask the denominator includes land, so this is a hard LOWER BOUND
        on marine coverage, never an estimate.

    (b) COVERAGE CURVE. Coverage measured against a morphological closing of
        the mapped area at increasing radii. Closing at radius R fills gaps
        narrower than about 2R. The SHAPE of the curve is the diagnostic:
          - stays high at every R  -> the mapped area is genuinely gap-free,
                                      i.e. wall-to-wall. Blanks are absences.
          - falls sharply at some R -> there are holes about that wide inside
                                      the surveyed area, i.e. patchy sampling.
                                      Blanks are unknowns, not absences.
        A single radius cannot tell these apart, which is why the curve is
        reported instead of one number.

    (c) COMPONENTS. How many separate pieces the mapped area breaks into, and
        what share sits in the largest. Many tiny scattered pieces is the
        signature of survey transects rather than area mapping.
    """
    from shapely.ops import unary_union

    geoms = [g for g in gdf.geometry if g is not None and not g.is_empty]
    if not geoms:
        print("  nothing mapped in this box.")
        return {"aoi": name, "verdict": "empty"}

    mapped = unary_union(geoms)
    mapped_km2 = mapped.area / 1e6

    denom_geom = box_geom
    denom_label = "whole box (INCLUDES LAND)"
    if land_geom is not None:
        denom_geom = box_geom.difference(land_geom)
        denom_label = "box minus supplied land mask"
    denom_km2 = denom_geom.area / 1e6

    box_cov = mapped_km2 / denom_km2 if denom_km2 > 0 else 0.0
    print(f"  mapped area          : {mapped_km2:.3f} km2")
    print(f"  denominator          : {denom_km2:.3f} km2  [{denom_label}]")
    print(f"  (a) BOX COVERAGE     : {box_cov:.1%}")
    if land_geom is None:
        print("  >>> No land mask supplied, so the denominator includes land.")
        print("  >>> Treat (a) as a LOWER BOUND on marine coverage. Pass")
        print("  >>> --land <coastline.shp> for a real figure.")

    print(f"\n  (b) coverage against a closing at radius R:")
    curve = {}
    for r in CLOSING_RADII_M:
        env = mapped.buffer(r).buffer(-r)
        env_km2 = env.area / 1e6
        cov = min(mapped_km2 / env_km2, 1.0) if env_km2 > 0 else 0.0
        curve[int(r)] = round(cov, 4)
        print(f"      R = {int(r):>5} m   envelope {env_km2:>9.3f} km2   "
              f"coverage {cov:>7.1%}")

    parts = list(getattr(mapped, "geoms", [mapped]))
    areas = sorted((p.area for p in parts), reverse=True)
    largest_share = areas[0] / sum(areas) if areas else 0.0
    print(f"\n  (c) components       : {len(parts)}, largest holds "
          f"{largest_share:.1%} of the mapped area")

    # ---- (d) the reading the verdict is actually based on -----------------
    # A FIXED radius list is not enough, and this was caught by a synthetic
    # case rather than by reasoning. Survey patches that sit FAR apart - the
    # transect pattern, which is the worst case for us - are not bridged by a
    # 1 km closing at all, so the envelope stays equal to the mapped area,
    # coverage reads ~100%, and the most patchy dataset imaginable is reported
    # as wall-to-wall. Exactly backwards.
    #
    # So the radius is not fixed: it is grown until the mapped area becomes a
    # single connected region, and coverage is read THERE. The question that
    # answers is the one we actually care about - "once I fill in enough to
    # join up everything that was mapped, how much of that region did anyone
    # actually classify?" Wall-to-wall mapping is already joined up, so the
    # radius stays small and coverage stays high. Scattered patches need a
    # huge radius and coverage collapses.
    #
    # An island archipelago will be called patchy by this test, because the
    # water between the islands is unmapped. That is the correct answer for
    # our purpose: that water is potential habitat and nobody classified it.
    merge_r, cov_at_merge, merged = None, None, False
    r = MERGE_RADIUS_START_M
    while r <= MERGE_RADIUS_CAP_M:
        env = mapped.buffer(r).buffer(-r)
        n_parts = len(list(getattr(env, "geoms", [env])))
        env_km2 = env.area / 1e6
        cov = min(mapped_km2 / env_km2, 1.0) if env_km2 > 0 else 0.0
        if n_parts <= 1:
            merge_r, cov_at_merge, merged = r, cov, True
            break
        merge_r, cov_at_merge = r, cov
        r *= 2

    if merged:
        print(f"\n  (d) mapped area becomes ONE region at R = {int(merge_r)} m;"
              f" coverage there {cov_at_merge:.1%}")
    else:
        print(f"\n  (d) still {len(parts)} separate regions at the "
              f"{int(MERGE_RADIUS_CAP_M)} m cap; coverage there "
              f"{cov_at_merge:.1%}")
        print("  >>> Not merging even at the cap means the mapped patches are")
        print("  >>> kilometres apart. That is survey sampling, not area")
        print("  >>> mapping, whatever reading (b) gives.")

    # ---- the verdict needs BOTH readings, and this too was found by a
    # synthetic case rather than by thinking. Each reading is blind to one
    # failure shape:
    #   - a fixed radius is fooled by patches that sit KILOMETRES apart,
    #     because it never bridges them at all (the scattered case).
    #   - the merge radius is fooled by a checkerboard whose tiles touch at
    #     the corners: it is technically "one region" at a 50 m closing while
    #     still being half holes.
    # So take the WORSE of the two. Wall-to-wall has to survive both.
    cov_fixed = curve[int(max(CLOSING_RADII_M))]
    cov_worst = min(cov_fixed, cov_at_merge if cov_at_merge is not None else 0.0)
    merge_txt = f"{cov_at_merge:.1%}" if cov_at_merge is not None else "n/a"
    print(f"      fixed {int(max(CLOSING_RADII_M))} m reading: {cov_fixed:.1%}"
          f"   |   merge reading: {merge_txt}")
    print(f"      the verdict uses the WORSE of the two: {cov_worst:.1%}")

    if merged and cov_worst >= WALL_TO_WALL_THRESHOLD:
        verdict = "wall_to_wall"
        print(f"\n  >>> WALL-TO-WALL. The mapped area is joined up and "
              f"{cov_worst:.0%}")
        print("  >>> of it is classified, so there are no unmapped holes")
        print("  >>> inside the surveyed area. A blank cell here means a")
        print("  >>> surveyor classified it as something else.")
        print("  >>> NEGATIVES ARE INFORMATIVE -> a fitted GAM is legitimate,")
        print("  >>> with spatially blocked folds (Roberts et al. 2017).")
    else:
        verdict = "patchy"
        print(f"\n  >>> PATCHY. Coverage is {cov_worst:.0%} once the mapped")
        print("  >>> patches are joined up, so most of the region between them")
        print("  >>> was never classified. A blank cell means nobody looked,")
        print("  >>> not that there is no kelp.")
        print("  >>> NEGATIVES ARE CONTAMINATED -> do NOT fit to blanks. Use")
        print("  >>> only Community-labelled polygons as negatives (faunal")
        print("  >>> turf reef), and draw background with the same spatial")
        print("  >>> bias as the presences (Phillips et al. 2009).")

    return {"aoi": name, "verdict": verdict,
            "mapped_km2": round(mapped_km2, 4),
            "denominator_km2": round(denom_km2, 4),
            "box_coverage": round(box_cov, 4),
            "land_mask_used": land_geom is not None,
            "coverage_curve": curve,
            "n_components": len(parts),
            "largest_component_share": round(largest_share, 4),
            "merge_radius_m": int(merge_r) if merge_r else None,
            "merged_at_cap": merged,
            "coverage_at_merge": round(cov_at_merge, 4)
            if cov_at_merge is not None else None,
            "coverage_worst_case": round(cov_worst, 4)}


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    """Every assertion below is paired with a case that MUST fail.

    Three metrics in this project looked sensible and measured the wrong thing
    until a synthetic case proved otherwise, so a test that can only pass is
    not a test.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon, box as sbox
    from shapely.ops import unary_union

    print("SELFTEST (no network, no files)\n")

    # --- densified box: area must match the spherical approximation ---
    import math
    b = AOIS["kenmare_river"]
    poly4326 = densified_box(b)
    g = gpd.GeoSeries([poly4326], crs=4326).to_crs(epsg=CRS_FOR_AREA)
    km2 = g.iloc[0].area / 1e6
    lat_mid = (b[1] + b[3]) / 2
    approx = ((b[2] - b[0]) * 111.320 * math.cos(math.radians(lat_mid))) * \
             ((b[3] - b[1]) * 110.574)
    assert abs(km2 - approx) / approx < 0.02, (km2, approx)
    print(f"  densified box -> ITM area   {km2:.2f} km2 "
          f"(spherical check {approx:.2f})  ok")

    # --- norm(): the whitespace trap must be caught, and only when present ---
    assert norm("Infralittoral ") == norm("Infralittoral") == "Infralittoral"
    assert norm("Faunal turf reef") != norm("Geogenic Reef")
    print("  norm() collapses whitespace, does not merge real classes  ok")

    # --- build a synthetic layer in ITM ---
    def mk(rows):
        geoms = [r.pop("geometry") for r in rows]
        gg = gpd.GeoDataFrame(rows, geometry=geoms, crs=CRS_FOR_AREA)
        gg["_community"] = gg["Community"].map(norm)
        gg["_extent"] = gg["Extent"].map(norm)
        return gg

    # NESTED case: a Geogenic polygon covering the Laminaria polygon entirely.
    kelp = sbox(0, 0, 1000, 1000)                       # 1 km2
    nested = mk([
        {"Community": "Laminaria-dominated reef", "Extent": "Subtidal",
         "geometry": kelp},
        {"Community": "Geogenic Reef", "Extent": "Subtidal",
         "geometry": sbox(-500, -500, 1500, 1500)},
    ])
    r_nested = parent_class_test(nested)
    assert r_nested["verdict"] == "nested", r_nested

    # DISJOINT case: Geogenic well away from the kelp. MUST give the other
    # answer, or the test above proves nothing.
    disjoint = mk([
        {"Community": "Laminaria-dominated reef", "Extent": "Subtidal",
         "geometry": kelp},
        {"Community": "Geogenic Reef", "Extent": "Subtidal",
         "geometry": sbox(9000, 9000, 10000, 10000)},
    ])
    r_disjoint = parent_class_test(disjoint)
    assert r_disjoint["verdict"] == "disjoint", r_disjoint
    print("\n  parent test: nested detected AND disjoint detected  ok")

    # --- MEASUREMENT 3: wall-to-wall vs patchy must give OPPOSITE answers ---
    box_geom = sbox(0, 0, 5000, 5000)

    # Wall-to-wall: 25 tiles that completely tile the box, no gaps.
    tiles = [sbox(i * 1000, j * 1000, (i + 1) * 1000, (j + 1) * 1000)
             for i in range(5) for j in range(5)]
    ww = mk([{"Community": "Faunal turf reef", "Extent": "Subtidal",
              "geometry": t} for t in tiles])
    r_ww = survey_footprint("synthetic_wall_to_wall", ww, box_geom)
    assert r_ww["verdict"] == "wall_to_wall", r_ww

    # Patchy: same tiles but every other one removed -> 500 m holes throughout.
    holed = [t for k, t in enumerate(tiles) if k % 2 == 0]
    pa = mk([{"Community": "Faunal turf reef", "Extent": "Subtidal",
              "geometry": t} for t in holed])
    r_pa = survey_footprint("synthetic_patchy", pa, box_geom)
    assert r_pa["verdict"] == "patchy", r_pa

    # SCATTERED PATCHES - the worst case, and the one the first version of
    # this function got exactly backwards. Three small survey blobs 5 km
    # apart. A fixed 1 km closing cannot bridge them, so the envelope equals
    # the mapped area and coverage reads ~100%: the most presence-only dataset
    # imaginable reported as wall-to-wall. It must come back PATCHY.
    big_box = sbox(0, 0, 20000, 20000)
    blobs = [sbox(x, 5000, x + 400, 5400) for x in (1000, 8000, 15000)]
    sc = mk([{"Community": "Faunal turf reef", "Extent": "Subtidal",
              "geometry": t} for t in blobs])
    r_sc = survey_footprint("synthetic_scattered", sc, big_box)
    assert r_sc["verdict"] == "patchy", r_sc
    # and prove the naive fixed-radius reading really would have been fooled,
    # so this test is guarding something real rather than restating the code
    assert r_sc["coverage_curve"][1000] > 0.95, r_sc["coverage_curve"]
    print("\n  footprint test: wall-to-wall, holed AND scattered all correct")
    print("  (scattered case reads "
          f"{r_sc['coverage_curve'][1000]:.0%} at a fixed 1 km radius - the")
    print("   naive test would have called it wall-to-wall)  ok")

    # --- dissolve must not double-count overlapping polygons ---
    a, bb = sbox(0, 0, 1000, 1000), sbox(500, 0, 1500, 1000)
    naive = (a.area + bb.area) / 1e6
    dis = dissolved_km2([a, bb])
    assert abs(dis - 1.5) < 1e-6, dis
    assert naive == 2.0
    print(f"\n  dissolve: overlapping 1+1 km2 -> {dis:.2f} km2, "
          f"not {naive:.2f}  ok")

    # --- describe() must split Extent, not merge it ---
    mixed = mk([
        {"Community": "Laminaria-dominated reef", "Extent": "Subtidal",
         "geometry": sbox(0, 0, 1000, 1000)},
        {"Community": "Laminaria-dominated reef", "Extent": "Intertidal",
         "geometry": sbox(2000, 0, 2500, 1000)},
        {"Community": "Faunal turf reef", "Extent": "Subtidal",
         "geometry": sbox(4000, 0, 5000, 1000)},
    ])
    rows = describe("synthetic_mixed", mixed)
    sub = [r for r in rows if r["community"].lower() == TARGET
           and r["extent"] == "Subtidal"][0]
    inter = [r for r in rows if r["community"].lower() == TARGET
             and r["extent"] == "Intertidal"][0]
    assert abs(sub["km2"] - 1.0) < 1e-6 and abs(inter["km2"] - 0.5) < 1e-6
    print("\n  describe(): subtidal and intertidal kept separate  ok")

    # --- Area_km check must catch a wrong field, not just pass everything ---
    good = mk([{"Community": "Laminaria-dominated reef", "Extent": "Subtidal",
                "geometry": sbox(i * 2000, 0, i * 2000 + 1000, 1000)}
               for i in range(6)])
    good["Area_km"] = [g.area / 1e6 for g in good.geometry]
    assert area_field_check(good)["verdict"] == "agrees"
    bad = good.copy()
    bad["Area_km"] = [g.area / 1e6 * 2.58 for g in good.geometry]
    assert area_field_check(bad)["verdict"] == "disagrees"
    print("\n  Area_km check: agreement AND disagreement both detected  ok")

    print("\nSELFTEST PASSED. Geometry, dissolve, the parent-class test, the")
    print("wall-to-wall/patchy test and the Area_km check are all shown to be")
    print("capable of returning BOTH answers. Nothing here touched a file.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Three measurements that decide the step 2 model form.")
    ap.add_argument("--shp", type=Path,
                    help='path to "21 NPWSArticle17Habitat.shp" (quote it: '
                         'the filename contains a space)')
    ap.add_argument("--aoi", choices=sorted(AOIS),
                    help="restrict to one AOI (default: all)")
    ap.add_argument("--site",
                    help="also run over every polygon whose Site_name contains "
                         "this string, e.g. Kenmare - a wider extent than the "
                         "AOI box, which makes measurement 2 far more reliable")
    ap.add_argument("--land", type=Path,
                    help="optional land/coastline polygons, to give "
                         "measurement 3 a real marine denominator")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.shp:
        ap.error("--shp is required (or --selftest)")
    if not args.shp.exists():
        print(f"not found: {args.shp}")
        print('Quote the path - the filename contains a space:')
        print('  --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp"')
        return 2

    import geopandas as gpd
    from shapely.ops import unary_union

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("NPWS Reef Inventory 2023, layer 21 NPWSArticle17Habitat.")
    print(f"All areas computed from geometry in EPSG:{CRS_FOR_AREA}. "
          "Area_km is never used.\n")

    print("=" * 74)
    print("LOAD")
    print("=" * 74)
    gdf = load_layer21(args.shp)
    if gdf is None:
        return 2

    land_geom = None
    if args.land:
        if not args.land.exists():
            print(f"  land mask not found: {args.land}")
            return 2
        land = gpd.read_file(args.land).to_crs(epsg=CRS_FOR_AREA)
        land_geom = unary_union([g for g in land.geometry
                                 if g is not None and not g.is_empty])
        print(f"  land mask loaded: {len(land)} features")

    print("\n" + "=" * 74)
    print("MEASUREMENT 0  is Area_km trustworthy?")
    print("=" * 74)
    area_verdict = area_field_check(gdf)

    print("\n" + "=" * 74)
    print("MEASUREMENT 1a  whitespace trap")
    print("=" * 74)
    ws = whitespace_trap_check(gdf)

    print("\n  Community values published nationally:")
    for v in sorted(gdf["_community"].unique()):
        print(f"    - {v}")
    print("\n  Extent values published nationally:")
    for v in sorted(gdf["_extent"].unique()):
        print(f"    - {v}")

    targets = {args.aoi: AOIS[args.aoi]} if args.aoi else AOIS
    class_rows, foot_rows, parent_rows = [], [], []

    for name, bbox in targets.items():
        print("\n" + "=" * 74)
        print(f"AOI  {name}")
        print("=" * 74)
        box_geom = gpd.GeoSeries([densified_box(bbox)],
                                 crs=4326).to_crs(epsg=CRS_FOR_AREA).iloc[0]
        sub = clip_to(gdf, box_geom)
        if len(sub) == 0:
            print("  NO layer-21 polygons in this box.")
            print("  >>> Layer 21 is clipped to SAC boundaries, so an AOI")
            print("  >>> outside any SAC is empty BY CONSTRUCTION. That is a")
            print("  >>> coverage limit, not evidence of no habitat.")
            continue

        print("\n  --- MEASUREMENT 1  what are the labels? ---")
        class_rows.extend(describe(name, sub))

        print("\n  --- MEASUREMENT 2  is Geogenic Reef a parent class? ---")
        pr = parent_class_test(sub)
        pr["extent_of_test"] = f"aoi:{name}"
        parent_rows.append(pr)

        print("\n  --- MEASUREMENT 3  wall-to-wall or patchy? ---")
        land_clip = (land_geom.intersection(box_geom)
                     if land_geom is not None else None)
        foot_rows.append(survey_footprint(name, sub, box_geom, land_clip))

    if args.site:
        print("\n" + "=" * 74)
        print(f"SITE-WIDE  Site_name contains '{args.site}'")
        print("=" * 74)
        if "Site_name" not in gdf.columns:
            print("  >>> no Site_name field in this layer; skipping.")
        else:
            mask = gdf["Site_name"].astype(str).str.contains(
                args.site, case=False, na=False)
            site = gdf[mask].copy()
            print(f"  polygons: {len(site)}")
            if len(site) == 0:
                print("  >>> no match. Check the spelling against the")
                print("  >>> Site_name values before concluding anything.")
            else:
                names = sorted(site["Site_name"].astype(str).unique())
                print(f"  matched sites: {names}")
                class_rows.extend(describe(f"site:{args.site}", site))
                print("\n  --- MEASUREMENT 2 over the whole site ---")
                pr = parent_class_test(site)
                pr["extent_of_test"] = f"site:{args.site}"
                parent_rows.append(pr)

    # ---------------- outputs ----------------
    if class_rows:
        p = OUT_DIR / "label_classes.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(class_rows[0]))
            w.writeheader()
            w.writerows(class_rows)
        print(f"\n  written: {p}")
    (OUT_DIR / "label_verdicts.json").write_text(json.dumps({
        "area_field": area_verdict,
        "whitespace_warnings": ws,
        "parent_class_test": parent_rows,
        "survey_footprint": foot_rows,
    }, indent=2), encoding="utf-8")
    print(f"  written: {OUT_DIR / 'label_verdicts.json'}")

    # ---------------- the decision ----------------
    print("\n" + "=" * 74)
    print("WHAT THESE THREE ANSWERS MEAN FOR THE MODEL")
    print("=" * 74)
    ken = next((f for f in foot_rows if f["aoi"] == "kenmare_river"), None)
    if ken and ken.get("verdict") == "wall_to_wall":
        print("  Kenmare mapping is wall-to-wall -> blanks are real absences")
        print("  -> fit a logistic GAM on depth, curvature, fetch, log(slope),")
        print("     validated with SPATIALLY BLOCKED folds (blocks >= 1 km,")
        print("     because the fetch layer is 200 m native).")
    elif ken and ken.get("verdict") == "patchy":
        print("  Kenmare mapping is patchy -> blanks are unknowns")
        print("  -> train ONLY on labelled polygons: Laminaria-dominated reef")
        print("     (subtidal) as presence, faunal turf reef as absence.")
        print("     Never feed unlabelled cells in as zeros.")
    else:
        print("  kenmare_river was not measured in this run. Rerun without")
        print("  --aoi, or with --aoi kenmare_river, before deciding.")
    print("\n  In BOTH cases these still hold:")
    print("   - intertidal Laminaria is excluded from the subtidal model")
    print("   - a class named 'Laminaria-dominated reef' is a COMMUNITY, not")
    print("     the species L. hyperborea. Say so on the slide.")
    print("   - report a depth-only null model alongside the fitted one, or")
    print("     you cannot show the extra covariates earn their place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())