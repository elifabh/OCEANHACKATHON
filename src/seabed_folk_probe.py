#!/usr/bin/env python3
"""
seabed_folk_probe.py - the four checks that must happen before the subtidal
suitability model is written.

WHY THIS SCRIPT EXISTS
Step 1 demoted the rendered backscatter to an optional texture covariate and
promoted the INFOMAR Seabed Substrate layer to the primary substrate source,
because that layer discriminated the AOIs where the greyscale render did not.
The target habitat definition for step 2 is Substrate = Rock AND Biozone =
infralittoral, i.e. EUNIS A3, which EUNIS bounds above by the top of the kelp
zone and below by the lower limit of kelp growth. The habitat class is, by
definition, the kelp class.

Four things have to be established before any of that can be trusted, and none
of them can be assumed.

  CHECK 1 - IS Shape_Area IN REAL METRES? HIGHEST PRIORITY.
      The MapServer reports SR 102100/3857 (Web Mercator), which inflates area
      by 1/cos^2(latitude), about 2.58x at 51.5 N. But Shape_Area is normally
      computed in the SOURCE geodatabase's CRS, which may or may not be the
      one the service advertises. Guessing either way is a 2.6x error in the
      habitat area and therefore a 2.6x error in the euro figure - the single
      largest numerical risk in the project.
      This script does not read the answer off the metadata. It downloads the
      geometry, projects it to Irish Transverse Mercator, computes the area
      itself, and divides. A ratio near 1.0 means Shape_Area is already true
      metres. A ratio near 2.58 means it is Web Mercator. Measured, not read.

  CHECK 2 - DO 'INFRALITTORAL' AND AN A3 CODE ACTUALLY EXIST?
      If Biozone carries no infralittoral class, the depth band cannot come
      from this layer and has to be derived from light attenuation instead,
      which needs a local Kd estimate and is a much bigger job. That changes
      the plan, so it is better known now than in October.

  CHECK 3 - AREA BY SUBSTRATE x BIOZONE, IN km2, NOT POLYGON COUNTS.
      Step 1 reported 16 Rock polygons of 50 at sherkin. That is not a
      quantity: one polygon may be 5 km2 and another 0.01 km2. And polygons
      that merely INTERSECT the AOI box extend outside it, so their full area
      overstates what is actually in the box. Everything here is clipped to
      the AOI before being summed.

  CHECK 4 - PROVENANCE PER POLYGON.
      Resolution and Source support a per-polygon confidence weight and give
      the pitch an answer to "how do you know?".

WHAT THIS SCRIPT DOES NOT DO
It does not choose a threshold, build a model, or compute a habitat area for
the pitch. It establishes what the data is. The model is the next script.

Dependencies beyond the standard library: shapely (BSD-3), pyproj (MIT),
requests. Add all three to DEPENDENCIES.md with versions.

Data: INFOMAR (Geological Survey Ireland & Marine Institute), CC BY 4.0.

Usage:
    python src/seabed_folk_probe.py --selftest
    python src/seabed_folk_probe.py
    python src/seabed_folk_probe.py --aoi sherkin_baltimore
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from common import (
    AOIS,
    INFOMAR_BATHY,
    ATTRIBUTION,
    CRS_ITM,
    INFOMAR_SEDIMENT,
    INFOMAR_SEDIMENT_LAYER,
    ArcGISError,
    arcgis_request,
    mercator_area_inflation,
)

OUT_DIR = Path("outputs/folk")
LAYER_URL = f"{INFOMAR_SEDIMENT}/{INFOMAR_SEDIMENT_LAYER}"

TO_ITM = Transformer.from_crs(4326, CRS_ITM, always_xy=True)

# CORRECTED after the live run. Three findings, all of which would have caused
# silent undercounts:
#   - the layer publishes BOTH "Rock" and "Rock or other hard substrata".
#     common.SUBSTRATE_HARD = "Rock" alone misses the second.
#   - "Infralittoral" and "Infralittoral " (trailing space) are two distinct
#     values in the domain. Any exact-match filter drops one of them.
#   - "Biogenic reef" is hard substrate and is Annex I reef, but it is built by
#     animals (Sabellaria, Modiolus) and is not equivalent to bedrock for a
#     Laminaria hyperborea holdfast. It is counted separately, never merged.
HARD_SUBSTRATE = {"rock", "rock or other hard substrata"}
BIOGENIC = {"biogenic reef"}


def norm(v) -> str:
    """Trim and collapse whitespace before any category is compared."""
    return " ".join(str(v).split()) if v not in (None, "") else "(null)"

# What "the same" and "clearly Mercator" mean, so the verdict is not eyeballed.
RATIO_TRUE_METRES = (0.97, 1.03)
RATIO_MERCATOR_TOL = 0.05


# ---------------------------------------------------------------------------
# Geometry: ArcGIS rings -> shapely, in Irish Transverse Mercator
# ---------------------------------------------------------------------------

def _ring_area(ring: list) -> float:
    """Signed shoelace area. Used only to tell an outer ring from a hole."""
    a = 0.0
    for i in range(len(ring) - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def rings_to_polygon(rings: list) -> Polygon | None:
    """Build a shapely geometry in ITM metres from an ArcGIS 4326 ring list.

    ArcGIS draws outer rings clockwise and holes counter-clockwise. Rather
    than trusting that, the rings are classified by the sign of their own
    area, and the largest-magnitude ring is taken as the outer one. Then the
    result is projected to ITM so that shapely's area is in real square
    metres rather than square degrees, which are meaningless.
    """
    proj = []
    for ring in rings:
        if len(ring) < 4:
            continue
        xs, ys = TO_ITM.transform([p[0] for p in ring], [p[1] for p in ring])
        proj.append(list(zip(xs, ys)))
    if not proj:
        return None

    proj.sort(key=lambda r: abs(_ring_area(r)), reverse=True)
    outer, holes = proj[0], proj[1:]
    try:
        poly = Polygon(outer, holes)
    except Exception:
        return None
    if not poly.is_valid:
        poly = poly.buffer(0)            # self-intersections are common in
    return poly if not poly.is_empty else None    # digitised coastal polygons


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def layer_schema() -> dict:
    """Field names, types and the layer's declared spatial reference."""
    meta = arcgis_request(LAYER_URL, {"f": "json"}, method="GET")
    fields = [(f.get("name"), f.get("type")) for f in meta.get("fields", []) or []]
    ext = meta.get("extent", {}) or {}
    sr = ext.get("spatialReference", {}) or {}
    print(f"  layer            : {meta.get('name')}")
    print(f"  geometry type    : {meta.get('geometryType')}")
    print(f"  declared SR      : wkid={sr.get('wkid')} "
          f"latestWkid={sr.get('latestWkid')}")
    print(f"  maxRecordCount   : {meta.get('maxRecordCount')}")
    print("  fields           : " + ", ".join(n for n, _ in fields))
    return {"fields": [n for n, _ in fields], "sr": sr,
            "max_records": meta.get("maxRecordCount"),
            "name": meta.get("name")}


def distinct_values(field: str) -> list | None:
    """Ask the server for the domain of a field. National, not AOI-scoped."""
    try:
        payload = arcgis_request(f"{LAYER_URL}/query", {
            "where": "1=1", "outFields": field,
            "returnDistinctValues": "true", "returnGeometry": "false",
            "f": "json",
        })
    except ArcGISError as exc:
        print(f"    distinct query on {field} failed: {exc.message}")
        return None
    vals = sorted({f.get("attributes", {}).get(field)
                   for f in payload.get("features", [])},
                  key=lambda v: (v is None, str(v)))
    return vals


def query_aoi(bbox: list[float]) -> tuple[list[dict], bool]:
    """All substrate polygons intersecting an AOI, with geometry in 4326."""
    xmin, ymin, xmax, ymax = bbox
    payload = arcgis_request(f"{LAYER_URL}/query", {
        "geometry": json.dumps({
            "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
            "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*", "returnGeometry": "true",
        "f": "json",
    })
    return payload.get("features", []), bool(payload.get("exceededTransferLimit"))


# ---------------------------------------------------------------------------
# CHECK 1 - measure what Shape_Area actually is
# ---------------------------------------------------------------------------

def area_units_verdict(pairs: list[tuple[float, float]], lat: float) -> dict:
    """pairs = (Shape_Area as delivered, our own ITM area in m2)."""
    usable = [(s, o) for s, o in pairs if s and o and o > 0]
    print(f"\n  polygons usable for the ratio test: {len(usable)}")
    if len(usable) < 5:
        print("  >>> too few to conclude. Do NOT use Shape_Area; compute area")
        print("  >>> from geometry, which this script already does.")
        return {"verdict": "inconclusive", "n": len(usable)}

    ratios = sorted(s / o for s, o in usable)
    med = ratios[len(ratios) // 2]
    expected = mercator_area_inflation(lat)
    print(f"  Shape_Area / our ITM area : median {med:.3f}"
          f"   (min {ratios[0]:.3f}, max {ratios[-1]:.3f})")
    print(f"  Web Mercator would predict : {expected:.3f} at {lat:.1f} N")

    if RATIO_TRUE_METRES[0] <= med <= RATIO_TRUE_METRES[1]:
        verdict = "true_metres"
        print("  >>> Shape_Area IS ALREADY TRUE SQUARE METRES. Usable as is.")
    elif abs(med - expected) / expected <= RATIO_MERCATOR_TOL:
        verdict = "web_mercator"
        print(f"  >>> Shape_Area IS WEB MERCATOR, inflated ~{med:.2f}x. Using")
        print("  >>> it unchanged would overstate the habitat area and the")
        print("  >>> euro figure by that factor. This script ignores it and")
        print("  >>> reports geometry-derived ITM area instead.")
    else:
        verdict = "unknown"
        print("  >>> Shape_Area matches NEITHER true metres NOR Web Mercator.")
        print("  >>> Something else is going on - a third CRS, or areas stored")
        print("  >>> in hectares or km2. Do not use it. Investigate before the")
        print("  >>> valuation engine consumes any area at all.")
    print("  Either way, every number below is computed from geometry in")
    print(f"  EPSG:{CRS_ITM}, not read from Shape_Area.")
    return {"verdict": verdict, "median_ratio": round(med, 4),
            "expected_mercator": round(expected, 4), "n": len(usable)}


# ---------------------------------------------------------------------------
# CHECK 3 - clipped area by Substrate x Biozone
# ---------------------------------------------------------------------------

def tabulate(name: str, feats: list[dict], bbox: list[float]) -> list[dict]:
    """Clip every polygon to the AOI and sum true area by class pair."""

    x0, x1 = TO_ITM.transform([bbox[0], bbox[2]], [bbox[1], bbox[3]])[0]
    y0, y1 = TO_ITM.transform([bbox[0], bbox[2]], [bbox[1], bbox[3]])[1]
    clip = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    by_class: dict[tuple, float] = defaultdict(float)
    geoms_by_class: dict[tuple, list] = defaultdict(list)
    ratio_pairs: list[tuple[float, float]] = []
    prov: dict[tuple, int] = defaultdict(int)
    clipped_off = 0.0
    full_total = 0.0
    dropped = [0]
    no_geom = [0]

    for f in feats:
        attrs = f.get("attributes", {}) or {}
        rings = (f.get("geometry", {}) or {}).get("rings")
        if not rings:
            no_geom[0] += 1
            continue
        poly = rings_to_polygon(rings)
        if poly is None:
            dropped[0] += 1        # invalid geometry that buffer(0) could not
            continue               # repair - counted, never silent
        full_total += poly.area
        ratio_pairs.append((attrs.get("Shape_Area"), poly.area))

        inside = poly.intersection(clip)
        if inside.is_empty:
            continue
        clipped_off += poly.area - inside.area

        key = (norm(attrs.get("Substrate")), norm(attrs.get("Biozone")))
        by_class[key] += inside.area
        geoms_by_class[key].append(inside)
        prov[(norm(attrs.get("Source")), norm(attrs.get("Resolution")))] += 1

    box_km2 = clip.area / 1e6
    print(f"\n  polygons returned : {len(feats)}")
    if dropped[0] or no_geom[0]:
        print(f"  >>> {dropped[0]} DROPPED for unrepairable geometry, "
              f"{no_geom[0]} had no rings. Their area is missing from every")
        print("  >>> figure below. The first version of this script dropped")
        print("  >>> them without saying so.")
    print(f"  AOI box in ITM    : {box_km2:.1f} km2")
    print(f"  area outside the box, discarded : "
          f"{clipped_off / 1e6:.1f} km2 of {full_total / 1e6:.1f} km2 "
          f"({100.0 * clipped_off / full_total if full_total else 0:.0f}%)")
    print("  >>> That discarded share is why polygon counts are not areas.")

    rows = []
    print(f"\n  {'Substrate':<26}{'Biozone':<22}{'km2':>9}{'% of box':>10}")
    for (sub, bio), a in sorted(by_class.items(), key=lambda kv: -kv[1]):
        km2 = a / 1e6
        mark = ("  <- hard" if sub.lower() in HARD_SUBSTRATE
                else "  <- biogenic" if sub.lower() in BIOGENIC else "")
        print(f"  {sub:<26}{bio:<22}{km2:>9.2f}{100 * km2 / box_km2:>9.1f}%{mark}")
        rows.append({"aoi": name, "substrate": sub, "biozone": bio,
                     "km2_clipped": round(km2, 3),
                     "pct_of_box": round(100 * km2 / box_km2, 2)})

    # Overlap guard: the classes should partition the seabed, not double-count.
    all_g = [g for gs in geoms_by_class.values() for g in gs]
    if all_g:
        union = unary_union(all_g).area
        summed = sum(by_class.values())
        if summed > 0 and (summed - union) / summed > 0.02:
            print(f"\n  >>> POLYGONS OVERLAP: classes sum to {summed / 1e6:.2f} km2"
                  f" but their union is {union / 1e6:.2f} km2.")
            print("  >>> Summing them double-counts. Dissolve before any area")
            print("  >>> figure goes into the valuation.")

    print(f"\n  provenance (Source / Resolution), polygon counts:")
    for (srcv, resv), n in sorted(prov.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {srcv[:44]:<46}{resv[:16]:<18}{n:>4}")

    return rows, ratio_pairs




# ---------------------------------------------------------------------------
# DEPTH-BAND MODE - the question the Biozone field could not answer
# ---------------------------------------------------------------------------

DEPTH_BINS = [("0-5 m", 0.0, 5.0), ("5-10 m", 5.0, 10.0),
              ("10-20 m", 10.0, 20.0), ("20-30 m", 20.0, 30.0),
              (">30 m", 30.0, float("inf"))]
GRID_M = 100.0          # sample spacing; each point stands for 0.01 km2
BATCH = 400


def depth_band_area(name: str, bbox: list[float], feats: list[dict]) -> list[dict]:
    """How much hard substrate sits in the kelp depth band, by measurement.

    The Biozone field says almost nothing is infralittoral in these AOIs - 5
    hectares across all three - because vessel-mounted multibeam cannot work
    safely in very shallow water, so the interpreters had nothing to classify
    there. That is a survey gap, not an absence of habitat.

    Bedrock, however, is continuous: an outcrop mapped at 25 m does not stop
    existing at 12 m. So instead of trusting the depth LABEL, this joins the
    substrate POLYGONS to INFOMAR's own depth MEASUREMENTS on a regular grid,
    and counts area by real depth. Each grid point stands for one cell, so
    area is a count times the cell size - a raster estimate, stated as such,
    with a resolution equal to the grid spacing.

    HONEST LIMIT, and it must go on the slide: a grid point only gets a depth
    if INFOMAR surveyed it. Where the shallow survey is missing, this returns
    'no depth', NOT 'no habitat'. The two must never be conflated.
    """
    import math
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    polys, classes = [], []
    for f in feats:
        rings = (f.get("geometry", {}) or {}).get("rings")
        if not rings:
            continue
        p = rings_to_polygon(rings)
        if p is None:
            continue
        polys.append(p)
        classes.append(norm((f.get("attributes", {}) or {}).get("Substrate")))
    if not polys:
        print("  no usable substrate polygons here")
        return []
    tree = STRtree(polys)

    lat_mid = (bbox[1] + bbox[3]) / 2.0
    dlon = GRID_M / (111320.0 * math.cos(math.radians(lat_mid)))
    dlat = GRID_M / 110574.0
    pts = []
    y = bbox[1] + dlat / 2
    while y < bbox[3]:
        x = bbox[0] + dlon / 2
        while x < bbox[2]:
            pts.append([x, y])
            x += dlon
        y += dlat
    print(f"  grid: {len(pts)} points at {GRID_M:.0f} m "
          f"({GRID_M * GRID_M / 1e6:.4f} km2 each)")

    depths: dict[int, float] = {}
    failed_batches = 0
    for start in range(0, len(pts), BATCH):
        chunk = pts[start:start + BATCH]
        try:
            payload = arcgis_request(f"{INFOMAR_BATHY}/getSamples", {
                "geometry": json.dumps({"points": chunk,
                                        "spatialReference": {"wkid": 4326}}),
                "geometryType": "esriGeometryMultipoint",
                "returnFirstValueOnly": "true",
                "interpolation": "RSP_NearestNeighbor", "f": "json"})
        except ArcGISError:
            # Proven 2026-07-27: a batch entirely outside INFOMAR coverage
            # returns HTTP 400 rather than an empty list. Zero samples, not an
            # error - see the empty-batch rule in common.arcgis_request.
            failed_batches += 1
            continue
        for s in payload.get("samples", []):
            loc = s.get("locationId")
            raw = s.get("value")
            if loc is None or raw in (None, "", "NaN"):
                continue
            try:
                depths[start + int(loc)] = -float(str(raw).split()[0])
            except ValueError:
                continue
    print(f"  points with a depth : {len(depths)} / {len(pts)}"
          f"   ({100.0 * len(depths) / len(pts):.1f}%)"
          f"   empty batches: {failed_batches}")

    cell_km2 = (GRID_M * GRID_M) / 1e6
    tally: dict[tuple, int] = defaultdict(int)
    no_depth_hard = 0
    for i, (lon, lat) in enumerate(pts):
        x, y = TO_ITM.transform(lon, lat)
        pt = Point(x, y)
        sub = None
        for j in tree.query(pt):
            if polys[j].contains(pt):
                sub = classes[j]
                break
        if sub is None:
            continue
        hard = sub.lower() in HARD_SUBSTRATE
        d = depths.get(i)
        if d is None:
            if hard:
                no_depth_hard += 1
            continue
        if d <= 0:
            continue
        for label, lo, hi in DEPTH_BINS:
            if lo <= d < hi:
                tally[(sub, label)] += 1
                break

    rows = []
    print(f"\n  {'Substrate':<30}{'depth':<10}{'km2':>8}")
    for (sub, band), n in sorted(tally.items(), key=lambda kv: -kv[1]):
        km2 = n * cell_km2
        mark = "  <- hard" if sub.lower() in HARD_SUBSTRATE else ""
        print(f"  {sub:<30}{band:<10}{km2:>8.2f}{mark}")
        rows.append({"aoi": name, "substrate": sub, "depth_band": band,
                     "km2": round(km2, 3), "n_points": n})

    kelp = sum(n for (sub, band), n in tally.items()
               if sub.lower() in HARD_SUBSTRATE and band in
               ("0-5 m", "5-10 m", "10-20 m"))
    print(f"\n  HARD SUBSTRATE IN 0-20 m : {kelp * cell_km2:.2f} km2"
          f"  ({kelp * cell_km2 * 100:.0f} ha)")
    print(f"  hard substrate with NO depth measurement: "
          f"{no_depth_hard * cell_km2:.2f} km2")
    print("  >>> The second number is unsurveyed, not unsuitable. Report both")
    print("  >>> or the habitat is understated by the size of the survey gap.")
    return rows


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    print("SELFTEST (no network)\n")

    # A 0.02 x 0.02 degree square near Sherkin, with a known true area.
    lon0, lat0 = -9.40, 51.48
    d = 0.02
    ring = [[lon0, lat0], [lon0 + d, lat0], [lon0 + d, lat0 + d],
            [lon0, lat0 + d], [lon0, lat0]]
    poly = rings_to_polygon([ring])
    assert poly is not None
    km2 = poly.area / 1e6
    # Sanity-check against the spherical approximation, independent of pyproj.
    import math
    approx = (d * 111.320 * math.cos(math.radians(lat0 + d / 2))) * (d * 110.574)
    assert abs(km2 - approx) / approx < 0.01, (km2, approx)
    print(f"  ring -> ITM area                  {km2:.4f} km2 "
          f"(spherical check {approx:.4f})  ok")

    # A hole must be subtracted, not added.
    inner = [[lon0 + 0.005, lat0 + 0.005], [lon0 + 0.005, lat0 + 0.015],
             [lon0 + 0.015, lat0 + 0.015], [lon0 + 0.015, lat0 + 0.005],
             [lon0 + 0.005, lat0 + 0.005]]
    holed = rings_to_polygon([ring, inner])
    assert holed.area < poly.area * 0.8, (holed.area, poly.area)
    print("  hole subtracted, not added        ok")

    # Clipping: half the polygon outside the AOI must contribute half.
    feats = [{"attributes": {"Substrate": "Rock", "Biozone": "Infralittoral",
                             "Shape_Area": poly.area, "Source": "t",
                             "Resolution": "5 m"},
              "geometry": {"rings": [ring]}}]
    half = [lon0 + d / 2, lat0, lon0 + d, lat0 + d]
    rows, _ = tabulate("half_box", feats, half)
    frac = rows[0]["km2_clipped"] / km2
    assert 0.45 < frac < 0.55, frac
    print(f"  clipped to half the box           {frac:.2f} of full  ok")

    # The Shape_Area verdict must name all three states correctly.
    true_m = [(poly.area, poly.area)] * 6
    assert area_units_verdict(true_m, 51.5)["verdict"] == "true_metres"
    merc = [(poly.area * mercator_area_inflation(51.5), poly.area)] * 6
    assert area_units_verdict(merc, 51.5)["verdict"] == "web_mercator"
    weird = [(poly.area * 7.3, poly.area)] * 6
    assert area_units_verdict(weird, 51.5)["verdict"] == "unknown"
    print("\n  Shape_Area verdict: metres / mercator / unknown all detected ok")

    print("\nSELFTEST PASSED. Geometry, holes, clipping and the area-units")
    print("verdict are correct. Nothing here has touched INFOMAR yet.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Pre-model checks on the INFOMAR Seabed Substrate layer.")
    ap.add_argument("--aoi", choices=sorted(AOIS))
    ap.add_argument("--depth-band", action="store_true",
                    help="join substrate polygons to INFOMAR depth "
                         "and report hard-substrate area by real depth")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(ATTRIBUTION["INFOMAR"])
    print("\n" + "=" * 74)
    print("CHECK 0  layer schema")
    print("=" * 74)
    try:
        schema = layer_schema()
    except ArcGISError as exc:
        print(f"  schema request failed: {exc}")
        return 2

    print("\n" + "=" * 74)
    print("CHECK 2  do 'infralittoral' and an A3 code exist?")
    print("=" * 74)
    domains = {}
    for field in ("Biozone", "EUNIS", "Substrate", "Folk_5"):
        if field not in schema["fields"]:
            print(f"  {field}: NOT PUBLISHED by this layer")
            continue
        vals = distinct_values(field)
        domains[field] = vals
        if vals is None:
            continue
        print(f"  {field} ({len(vals)} values):")
        for v in vals[:25]:
            print(f"    - {v}")
        if len(vals) > 25:
            print(f"    ... and {len(vals) - 25} more")

    bio = [v for v in (domains.get("Biozone") or []) if v
           and "infralittoral" in str(v).lower()]
    a3 = [v for v in (domains.get("EUNIS") or []) if v
          and str(v).upper().startswith("A3")]
    print(f"\n  infralittoral Biozone values : {bio or 'NONE FOUND'}")
    print(f"  EUNIS A3 codes               : {a3 or 'NONE FOUND'}")
    if not bio and not a3:
        print("  >>> PLAN CHANGE. Neither an infralittoral Biozone nor an A3")
        print("  >>> code is available, so the depth band cannot come from")
        print("  >>> this layer. It must be derived from INFOMAR bathymetry")
        print("  >>> plus a local light-attenuation (Kd) estimate. That is a")
        print("  >>> bigger job than the plan assumed - decide now, not in")
        print("  >>> October.")

    targets = {args.aoi: AOIS[args.aoi]} if args.aoi else AOIS
    all_rows, all_pairs, depth_rows = [], [], []
    for name, bbox in targets.items():
        print("\n" + "=" * 74)
        print(f"CHECK 3 & 4  {name}")
        print("=" * 74)
        try:
            feats, exceeded = query_aoi(bbox)
        except ArcGISError as exc:
            print(f"  query failed: {exc}")
            continue
        if exceeded:
            print("  >>> exceededTransferLimit IS TRUE. Polygons are MISSING")
            print("  >>> and every area below is an undercount. Page the query")
            print("  >>> with resultOffset before using these numbers.")
        rows, pairs = tabulate(name, feats, bbox)
        all_rows.extend(rows)
        all_pairs.extend(pairs)
        if args.depth_band:
            print(f"\n  --- depth-band join, {name} ---")
            depth_rows.extend(depth_band_area(name, bbox, feats))

    print("\n" + "=" * 74)
    print("CHECK 1  what is Shape_Area actually in?")
    print("=" * 74)
    lat = sum((b[1] + b[3]) / 2 for b in targets.values()) / len(targets)
    verdict = area_units_verdict(all_pairs, lat)

    if all_rows:
        p = OUT_DIR / "substrate_area_by_class.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(all_rows[0]))
            w.writeheader()
            w.writerows(all_rows)
        print(f"\n  written: {p}")
    if depth_rows:
        p2 = OUT_DIR / "hard_substrate_by_depth.csv"
        with p2.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(depth_rows[0]))
            w.writeheader()
            w.writerows(depth_rows)
        print(f"  written: {p2}")
    (OUT_DIR / "shape_area_verdict.json").write_text(
        json.dumps(verdict, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())