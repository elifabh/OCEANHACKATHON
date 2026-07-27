#!/usr/bin/env python3
"""
infomar_backscatter.py - step 1 of the subtidal track.

WHY THIS SCRIPT EXISTS
Subtidal Laminaria hyperborea cannot be seen optically here: the Lyzenga
radiative-transfer test closed that route, with nearshore suspended sediment
fingerprinted as the cause. The remaining route is a habitat-suitability model
built on acoustics. L. hyperborea is an obligate hard-substrate species - it
attaches by a holdfast to bedrock, boulders or cobble and cannot grow on sand
or mud. Acoustic backscatter is the open, national proxy for seabed hardness.
So the first question to answer, before any model is written, is blunt:

    does INFOMAR backscatter exist, at usable resolution, in the three AOIs,
    and specifically in the depth strip where kelp can grow?

WHAT THIS SCRIPT CHECKS, IN ORDER
  1. WHICH ENDPOINT IS REAL. The URL previously held in common.py
     ("INFOMAR/AllSurvey_Backscatter") could not be confirmed to exist. Two
     alternatives were confirmed from published service metadata. This script
     walks the candidate list and reports what each one actually is, rather
     than assuming.
  2. WHAT THE PIXEL VALUES MEAN. The published services are RENDERED 8-bit
     greyscale images (3 or 4 bands, U8, min 0 max 255), NOT calibrated
     decibels. The GSI service description states the polarity: darker = hard
     (rock, gravel), lighter = soft (sand, silt, mud). This script verifies
     that the bands really are equal (i.e. genuinely greyscale) instead of
     taking the metadata's word for it.
  3. AOI-WIDE VALUE DISTRIBUTION via computeHistograms. One request returns the
     digital-number histogram over the whole AOI, which is a far better answer
     to "coverage and value range" than a few hundred sampled points.
  4. POINT COVERAGE via getSamples on a regular grid, with per-point failure
     isolation (see the HTTP 400 section below).
  5. DEPTH JOIN. The same grid is sampled against the INFOMAR bathymetry
     service so the hardness distribution can be reported INSIDE the candidate
     infralittoral band, not just over the whole box. Hard ground at 60 m is
     irrelevant to kelp.
  6. SUBSTRATE CROSS-CHECK against INFOMAR Seabed Folk, the official
     interpreted substrate product.

THE KNOWN HTTP 400
infomar_coverage.py hit a persistent HTTP 400 on the northern strip of
inner_roaringwater, roughly 12% of points, cause recorded as unknown. Two
things in the old helper made that undiagnosable, and both are fixed in
common.arcgis_request:
  - resp.raise_for_status() was called before resp.text was read, so the ArcGIS
    error message and details in the 400 body were discarded;
  - the 400 was retried three times, which cannot help and obscured the trace.
This script additionally does two things the old one did not:
  - it BISECTS a failing batch down to the individual offending points, so a
    bad point costs those points and not the whole AOI;
  - with --diagnose it re-sends a failing group under progressively simpler
    parameters to identify which parameter triggers the 400.
A standing hypothesis worth testing: the old call sent
mosaicRule={"mosaicMethod":"esriMosaicNorthwest","where":"Category = 1"}. The
GSI backscatter service publishes NO fields at all and an empty allowed-mosaic-
methods list, so any where-clause or non-default mosaic method should be
expected to 400 there. Whether the same explains the bathymetry failure is
exactly what --diagnose is for. Do not write the cause into the report until
the diagnostic prints it.

NOT YET RUN AGAINST THE LIVE SERVICES BY ITS AUTHOR. The logic is exercised
offline by `--selftest`; the network path is not. Every request prints a
diagnosable error rather than failing silently.

Data: INFOMAR (Geological Survey Ireland & Marine Institute), CC BY 4.0.

Usage:
    python src/infomar_backscatter.py --selftest
    python src/infomar_backscatter.py
    python src/infomar_backscatter.py --aoi sherkin_baltimore --grid 30
    python src/infomar_backscatter.py --aoi inner_roaringwater --diagnose
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

from common import (
    AOIS,
    ATTRIBUTION,
    BACKSCATTER_CANDIDATES,
    CATEGORY_PRIMARY,
    INFOMAR_BATHY,
    INFOMAR_SEDIMENT,
    INFOMAR_SEDIMENT_LAYER,
    ArcGISError,
    aoi_area_km2,
    arcgis_request,
    grid_points,
    service_metadata,
)

OUT_DIR = Path("outputs/infomar")
BATCH = 100                 # points per getSamples request
REQUEST_PAUSE = 0.2         # be polite to a public service
MAX_REQUESTS_PER_AOI = 400  # guard against pathological bisection

# Candidate infralittoral band for West Cork. The true lower limit of
# L. hyperborea is set by light, not by a constant: EUNIS notes kelp depth
# varies with water clarity and reaches ~45 m only in exceptionally clear
# water such as St Kilda. West Cork is not that. 20 m is used here as a
# working upper bound for the PROBE ONLY; the operational limit must later be
# derived from local light attenuation, not asserted.
KELP_BAND_M = (0.0, 20.0)
DEPTH_BINS = [
    ("0-5 m    (kelp core)", 0.0, 5.0),
    ("5-10 m   (kelp forest)", 5.0, 10.0),
    ("10-20 m  (kelp park, light-limited)", 10.0, 20.0),
    ("20-50 m  (below kelp)", 20.0, 50.0),
    (">50 m", 50.0, float("inf")),
]


# ---------------------------------------------------------------------------
# 1. Which backscatter endpoint is real, and what is it?
# ---------------------------------------------------------------------------

def describe_service(label: str, url: str) -> dict | None:
    """Fetch and print the properties that decide whether a service is usable."""
    print(f"\n  [{label}]\n  {url}")
    try:
        meta = service_metadata(url)
    except ArcGISError as exc:
        print(f"    UNREACHABLE: {exc}")
        return None

    sr = meta.get("spatialReference", {})
    info = {
        "label": label,
        "url": url,
        "name": meta.get("name"),
        "band_count": meta.get("bandCount"),
        "pixel_type": meta.get("pixelType"),
        "service_data_type": meta.get("serviceDataType"),
        "pixel_size_x": meta.get("pixelSizeX"),
        "pixel_size_y": meta.get("pixelSizeY"),
        "wkid": sr.get("latestWkid") or sr.get("wkid"),
        "vcs_wkid": sr.get("latestVcsWkid") or sr.get("vcsWkid"),
        "min_values": meta.get("minValues"),
        "max_values": meta.get("maxValues"),
        "mean_values": meta.get("meanValues"),
        "fields": [f.get("name") for f in meta.get("fields", []) or []],
        "capabilities": meta.get("capabilities"),
        "allowed_mosaic_methods": meta.get("allowedMosaicMethods"),
        "default_mosaic_method": meta.get("defaultMosaicMethod"),
        "has_histograms": meta.get("hasHistograms"),
    }

    print(f"    name           : {info['name']}")
    print(f"    bands / type   : {info['band_count']} x {info['pixel_type']}"
          f"  ({info['service_data_type']})")
    print(f"    pixel size     : {info['pixel_size_x']} x {info['pixel_size_y']}"
          f"  in wkid {info['wkid']}")
    if info["vcs_wkid"]:
        print(f"    vertical CRS   : {info['vcs_wkid']}"
              "   (5861 = LAT height in the EPSG registry)")
    print(f"    value range    : min {info['min_values']} "
          f"max {info['max_values']} mean {info['mean_values']}")
    print(f"    fields         : {info['fields'] or 'NONE'}")
    print(f"    mosaic methods : default={info['default_mosaic_method']} "
          f"allowed={info['allowed_mosaic_methods']}")

    # The interpretation guard. This is the thing that would silently invert
    # the whole habitat model if it went unnoticed.
    if info["pixel_type"] == "U8" and (info["band_count"] or 0) >= 3:
        print("    >>> RENDERED IMAGE, NOT DECIBELS. Values are 0-255 grey")
        print("    >>> levels. Per the GSI service description: DARK = HARD")
        print("    >>> seabed (rock/gravel), LIGHT = SOFT (sand/silt/mud).")
        print("    >>> So LOW digital number = candidate kelp substrate.")
        print("    >>> Any claim of calibrated backscatter in dB is false and")
        print("    >>> must not appear in the pitch.")
    elif info["pixel_type"] in ("F32", "F64", "S16"):
        print("    >>> Continuous-valued service. Check the units before")
        print("    >>> assuming decibels.")

    if not info["fields"]:
        print("    >>> NO FIELDS PUBLISHED: do not send a mosaicRule where-")
        print("    >>> clause to this service. 'Category = 1' would 400 here.")
    return info


def pick_backscatter_service() -> dict | None:
    """Walk the candidate list; return the first service that answers."""
    print("=" * 74)
    print("STEP 1  which backscatter endpoint actually exists")
    print("=" * 74)
    chosen = None
    for label, url in BACKSCATTER_CANDIDATES:
        info = describe_service(label, url)
        if info and chosen is None:
            chosen = info
    if chosen:
        print(f"\n  SELECTED: {chosen['label']}")
    else:
        print("\n  >>> NO BACKSCATTER ENDPOINT RESPONDED. The subtidal track")
        print("  >>> cannot proceed on web services. Fall back to the INFOMAR")
        print("  >>> data download portal or email data@infomar.ie, and record")
        print("  >>> the outage with today's date.")
    return chosen


# ---------------------------------------------------------------------------
# 2. AOI-wide histogram - the real answer to "coverage and value range"
# ---------------------------------------------------------------------------

def aoi_histogram(url: str, bbox: list[float]) -> dict | None:
    """computeHistograms over the AOI envelope: full DN distribution, 1 request.

    A histogram counts VALID pixels only, so sum(counts) divided by the number
    of pixels the envelope should contain is a coverage fraction that does not
    depend on where a sampling grid happened to land.
    """
    xmin, ymin, xmax, ymax = bbox
    params = {
        "geometry": json.dumps({
            "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
            "spatialReference": {"wkid": 4326},
        }),
        "geometryType": "esriGeometryEnvelope",
        "f": "json",
    }
    try:
        payload = arcgis_request(f"{url}/computeHistograms", params)
    except ArcGISError as exc:
        print(f"  computeHistograms FAILED: {exc}")
        return None

    hists = payload.get("histograms") or []
    if not hists:
        print("  computeHistograms returned no histogram: no valid pixels in"
              " this AOI, or the operation is unsupported here.")
        return None

    h = hists[0]
    counts = h.get("counts", [])
    total = sum(counts)
    if total == 0:
        print("  histogram total is zero: NO BACKSCATTER PIXELS IN THIS AOI.")
        return {"valid_pixels": 0}

    lo, hi, size = h.get("min", 0), h.get("max", 255), h.get("size", len(counts))
    width = (hi - lo) / size if size else 1.0

    def bin_value(i: int) -> float:
        return lo + (i + 0.5) * width

    # Distribution summary straight off the histogram.
    cum, pct_targets = 0, {0.05: None, 0.25: None, 0.5: None,
                           0.75: None, 0.95: None}
    for i, c in enumerate(counts):
        cum += c
        frac = cum / total
        for p in pct_targets:
            if pct_targets[p] is None and frac >= p:
                pct_targets[p] = bin_value(i)
    mean = sum(bin_value(i) * c for i, c in enumerate(counts)) / total

    print(f"  valid pixels     : {total:,}")
    print(f"  DN range in AOI  : {lo:g} to {hi:g} in {size} bins")
    print(f"  DN mean          : {mean:.1f}")
    print("  DN percentiles   : " + "  ".join(
        f"p{int(p*100)}={pct_targets[p]:.0f}" for p in sorted(pct_targets)))

    zero_share = 100.0 * counts[0] / total if counts else 0.0
    top_share = 100.0 * counts[-1] / total if counts else 0.0
    print(f"  DN==min share    : {zero_share:.1f}%    DN==max share: {top_share:.1f}%")
    if zero_share > 20:
        print("  >>> WARNING: a large spike at the darkest value. On a rendered")
        print("  >>> product NoData is often written as black, and black also")
        print("  >>> means 'hardest'. Do NOT read this as rock until it is")
        print("  >>> cross-checked against bathymetry coverage at the same")
        print("  >>> points (the --skip-depth flag turns that check off).")

    return {
        "valid_pixels": total,
        "dn_min": lo,
        "dn_max": hi,
        "dn_mean": round(mean, 1),
        "dn_p05": pct_targets[0.05],
        "dn_p25": pct_targets[0.25],
        "dn_p50": pct_targets[0.5],
        "dn_p75": pct_targets[0.75],
        "dn_p95": pct_targets[0.95],
        "dn_min_share_pct": round(zero_share, 1),
        "dn_max_share_pct": round(top_share, 1),
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# 3. Point sampling with per-point failure isolation
# ---------------------------------------------------------------------------

class SampleRun:
    """Bookkeeping for one AOI's sampling: results, failures, request budget."""

    def __init__(self, url: str, mosaic_rule: dict | None = None):
        self.url = url
        self.mosaic_rule = mosaic_rule
        self.rows: dict[int, dict] = {}
        self.failures: list[dict] = []
        self.requests = 0

    def _params(self, points: list[list[float]]) -> dict:
        params = {
            "geometry": json.dumps({
                "points": points,
                "spatialReference": {"wkid": 4326},
            }),
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            # Nearest neighbour, not the service default of bilinear: bilinear
            # across the edge of a survey block invents intermediate grey
            # values that look like a real intermediate hardness.
            "interpolation": "RSP_NearestNeighbor",
            "f": "json",
        }
        if self.mosaic_rule:
            params["mosaicRule"] = json.dumps(self.mosaic_rule)
        return params

    def sample(self, indexed: list[tuple[int, list[float]]]) -> None:
        """Sample a group; on a 4xx, bisect until the bad points are isolated."""
        if not indexed:
            return
        if self.requests >= MAX_REQUESTS_PER_AOI:
            for idx, pt in indexed:
                self.failures.append({"index": idx, "lon": pt[0], "lat": pt[1],
                                      "error": "request budget exhausted"})
            return

        points = [pt for _, pt in indexed]
        self.requests += 1
        time.sleep(REQUEST_PAUSE)
        try:
            payload = arcgis_request(f"{self.url}/getSamples", self._params(points))
        except ArcGISError as exc:
            if len(indexed) == 1:
                idx, pt = indexed[0]
                self.failures.append({"index": idx, "lon": pt[0], "lat": pt[1],
                                      "error": exc.message,
                                      "details": "; ".join(map(str, exc.details))})
                return
            mid = len(indexed) // 2
            self.sample(indexed[:mid])
            self.sample(indexed[mid:])
            return

        for s in payload.get("samples", []):
            loc_id = s.get("locationId")
            if loc_id is None or not (0 <= loc_id < len(indexed)):
                continue                       # cannot be joined: drop, silently
            global_idx, pt = indexed[loc_id]
            parsed = parse_value(s.get("value"))
            if parsed is None:
                continue
            self.rows[global_idx] = {
                "index": global_idx,
                "lon": pt[0],
                "lat": pt[1],
                "band1": parsed[0],
                "bands": " ".join(f"{v:g}" for v in parsed),
                "n_bands": len(parsed),
                "greyscale": len(set(parsed[:3])) == 1,
                "resolution": s.get("resolution"),
                "raster_id": s.get("rasterId"),
            }


def parse_value(raw) -> list[float] | None:
    """getSamples returns multi-band values as a space-separated string."""
    if raw in (None, "", "NaN"):
        return None
    parts = str(raw).split()
    out = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            return None
    return out or None


def summarise_backscatter(name: str, requested: int, run: SampleRun) -> dict:
    """Report point coverage and the DN distribution, with the traps flagged."""
    rows = [run.rows[k] for k in sorted(run.rows)]
    print(f"\n  points requested : {requested}")
    print(f"  points with data : {len(rows)}   "
          f"({100.0 * len(rows) / requested:.1f}%)")
    print(f"  points failed 4xx: {len(run.failures)}")
    print(f"  requests issued  : {run.requests}")

    if not rows:
        print("  >>> NO BACKSCATTER AT ANY SAMPLED POINT IN THIS AOI.")
        return {"aoi": name, "requested": requested, "with_data": 0,
                "failed": len(run.failures)}

    non_grey = [r for r in rows if not r["greyscale"]]
    if non_grey:
        print(f"  >>> {len(non_grey)} points have unequal RGB bands. The service")
        print("  >>> is NOT a plain greyscale render there; a colour ramp means")
        print("  >>> band 1 alone is not a hardness proxy. Inspect before use.")
    else:
        print("  band check       : all sampled points are true greyscale"
              " (R=G=B), consistent with a hardness render")

    dns = [r["band1"] for r in rows]
    resolutions = sorted({round(r["resolution"], 3)
                          for r in rows if r.get("resolution")})
    print(f"  DN min/median/max: {min(dns):.0f} / "
          f"{statistics.median(dns):.0f} / {max(dns):.0f}")
    print(f"  native resolution: {resolutions or 'not reported'}")
    print(f"  distinct DN values: {len(set(dns))}"
          "   (a small number means heavy quantisation)")
    return {
        "aoi": name,
        "requested": requested,
        "with_data": len(rows),
        "failed": len(run.failures),
        "coverage_pct": round(100.0 * len(rows) / requested, 1),
        "dn_min": min(dns),
        "dn_median": statistics.median(dns),
        "dn_max": max(dns),
        "n_nongreyscale": len(non_grey),
    }


# ---------------------------------------------------------------------------
# 4. Depth join - hardness only matters inside the light-limited band
# ---------------------------------------------------------------------------

def sample_depth(points: list[list[float]], use_category: bool) -> SampleRun:
    """Sample INFOMAR bathymetry at the same grid. Optionally restrict to
    Category = 1 (primary rasters) so a coarse overview cannot masquerade as
    survey data. That where-clause is the prime suspect for the old HTTP 400,
    so it is a flag, not a default."""
    rule = ({"mosaicMethod": "esriMosaicNorthwest",
             "where": f"Category = {CATEGORY_PRIMARY}"} if use_category else None)
    run = SampleRun(INFOMAR_BATHY, rule)
    run.sample(list(enumerate(points)))
    return run


def report_depth_join(bs: SampleRun, depth: SampleRun) -> dict:
    """Cross-tabulate hardness against depth, and use depth as a NoData test."""
    joined = []
    for idx, brow in bs.rows.items():
        drow = depth.rows.get(idx)
        if not drow:
            continue
        # INFOMAR elevation convention: negative below datum (LAT).
        elev = drow["band1"]
        joined.append({**brow, "elev_m": elev, "depth_m": -elev})

    print(f"\n  points with BOTH backscatter and depth: {len(joined)}")
    if not joined:
        print("  >>> NO OVERLAP. Backscatter and bathymetry do not co-occur at")
        print("  >>> the sampled points, so a depth-conditioned hardness layer")
        print("  >>> cannot be built here from these two services.")
        return {"joined": 0}

    # NoData masquerade test: are the darkest pixels real seabed?
    dark = [j for j in joined if j["band1"] <= 5]
    bs_only = len(bs.rows) - len(joined)
    if bs_only:
        print(f"  points with backscatter but NO depth: {bs_only}"
              "   (candidate NoData or out-of-survey)")
    if dark:
        print(f"  very dark points (DN<=5) that DO have a depth: {len(dark)}"
              "   -> real hard ground, not NoData")

    subtidal = [j for j in joined if j["depth_m"] > 0]
    if not subtidal:
        print("  >>> All joined points are at or above datum. Nothing subtidal.")
        return {"joined": len(joined), "subtidal": 0}

    print("\n  hardness by depth band (DN: low = hard = candidate kelp rock):")
    print(f"    {'band':<38} {'n':>5}  {'DN p25':>7} {'DN med':>7} {'DN p75':>7}")
    out = {"joined": len(joined), "subtidal": len(subtidal)}
    for label, lo, hi in DEPTH_BINS:
        sel = [j["band1"] for j in subtidal if lo <= j["depth_m"] < hi]
        if not sel:
            print(f"    {label:<38} {0:>5}  {'-':>7} {'-':>7} {'-':>7}")
            continue
        sel.sort()
        q = statistics.quantiles(sel, n=4) if len(sel) >= 4 else [sel[0], statistics.median(sel), sel[-1]]
        print(f"    {label:<38} {len(sel):>5}  {q[0]:>7.0f} {q[1]:>7.0f} {q[2]:>7.0f}")

    in_band = [j for j in subtidal
               if KELP_BAND_M[0] <= j["depth_m"] <= KELP_BAND_M[1]]
    print(f"\n  points in the {KELP_BAND_M[0]:.0f}-{KELP_BAND_M[1]:.0f} m "
          f"candidate infralittoral band: {len(in_band)}")
    out["in_kelp_band"] = len(in_band)
    if not in_band:
        print("  >>> THE KELP DEPTH STRIP IS EMPTY. Vessel-mounted MBES cannot")
        print("  >>> safely work in very shallow water, so a hole here is the")
        print("  >>> expected failure mode rather than a surprise. If this is")
        print("  >>> the result, the suitability model needs a different depth")
        print("  >>> source (EMODnet, Admiralty charts, or S2-derived SDB in")
        print("  >>> the clear-water AOI only) and the limitation belongs on a")
        print("  >>> slide, not buried in a footnote.")
    else:
        dn = sorted(j["band1"] for j in in_band)
        print(f"  DN in that band: min {dn[0]:.0f}  median "
              f"{statistics.median(dn):.0f}  max {dn[-1]:.0f}")
        print("  >>> This is the distribution the suitability model will")
        print("  >>> threshold. Do NOT pick the threshold here - pick it in")
        print("  >>> step 2 against the Seabed Folk rock polygons, so it is")
        print("  >>> anchored to an external classification.")
        out["kelp_band_dn_median"] = statistics.median(dn)
    return out


# ---------------------------------------------------------------------------
# 5. Substrate cross-check
# ---------------------------------------------------------------------------

ROCK_TOKENS = ("rock", "boulder", "cobble", "reef", "bedrock", "gravel")


def seabed_folk(bbox: list[float]) -> list[dict]:
    """Query the interpreted substrate polygons intersecting the AOI."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "geometry": json.dumps({
            "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
            "spatialReference": {"wkid": 4326},
        }),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{INFOMAR_SEDIMENT}/{INFOMAR_SEDIMENT_LAYER}/query"
    try:
        payload = arcgis_request(url, params)
    except ArcGISError as exc:
        print(f"  Seabed Folk query FAILED: {exc}")
        return []
    feats = payload.get("features", [])
    return [f.get("attributes", {}) for f in feats]


def report_substrate(records: list[dict]) -> dict:
    if not records:
        print("  no substrate polygons intersect this AOI")
        return {"substrate_polygons": 0, "rock_classes": 0}

    classes: dict[str, int] = {}
    for rec in records:
        label = next((str(v) for k, v in rec.items()
                      if "class" in k.lower() and v not in (None, "")), "UNCLASSED")
        classes[label] = classes.get(label, 0) + 1

    print(f"  substrate polygons intersecting AOI: {len(records)}")
    for label, n in sorted(classes.items(), key=lambda kv: -kv[1]):
        hard = any(t in label.lower() for t in ROCK_TOKENS)
        print(f"    {label:<45} {n:>4}{'   <- hard substrate' if hard else ''}")
    n_rock = sum(n for label, n in classes.items()
                 if any(t in label.lower() for t in ROCK_TOKENS))
    if n_rock:
        print("  >>> Rock/boulder classes present. In step 2 these polygons are")
        print("  >>> the external anchor for the backscatter threshold, and the")
        print("  >>> honest framing for the jury: the hard-substrate call comes")
        print("  >>> from an official INFOMAR interpretation, not from a cutoff")
        print("  >>> we invented on a greyscale image.")
    else:
        print("  >>> No rock class returned. Either the AOI is genuinely soft")
        print("  >>> ground, or this product does not cover it. Check coverage")
        print("  >>> before concluding anything about substrate.")
    return {"substrate_polygons": len(records), "rock_classes": n_rock}


# ---------------------------------------------------------------------------
# 6. The 400 diagnostic ladder
# ---------------------------------------------------------------------------

def diagnose_400(url: str, point: list[float]) -> None:
    """Re-send one failing point under progressively simpler parameters.

    Whichever rung first succeeds names the parameter that caused the 400.
    """
    base_geom = json.dumps({"points": [point],
                            "spatialReference": {"wkid": 4326}})
    ladder = [
        ("full request as used by infomar_coverage.py", {
            "geometry": base_geom,
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicNorthwest",
                                      "where": f"Category = {CATEGORY_PRIMARY}"}),
        }),
        ("mosaic method only, no where-clause", {
            "geometry": base_geom,
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicNorthwest"}),
        }),
        ("no mosaicRule at all", {
            "geometry": base_geom,
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
        }),
        ("single esriGeometryPoint instead of multipoint", {
            "geometry": json.dumps({"x": point[0], "y": point[1],
                                    "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
        }),
    ]
    print(f"\n  400 DIAGNOSTIC at lon={point[0]:.4f} lat={point[1]:.4f}")
    for label, params in ladder:
        params["f"] = "json"
        time.sleep(REQUEST_PAUSE)
        try:
            payload = arcgis_request(f"{url}/getSamples", params)
        except ArcGISError as exc:
            print(f"    FAIL  {label}")
            print(f"          -> {exc.message}")
            if exc.details:
                print(f"          -> {'; '.join(map(str, exc.details))}")
            continue
        n = len(payload.get("samples", []))
        print(f"    OK    {label}  ({n} sample(s) returned)")
        print("    >>> The rung above this one is what triggers the 400.")
        return
    print("    >>> Every rung failed. The 400 is not caused by mosaicRule or")
    print("    >>> geometry type. Next suspects: the point is outside the")
    print("    >>> service's declared full extent, or it falls in a mosaic")
    print("    >>> item with broken metadata. Report both possibilities to")
    print("    >>> data@infomar.ie with these coordinates.")


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    """Exercise the parsing and summary logic with synthetic data, no network."""
    print("SELFTEST (no network)")
    assert parse_value("77 77 77") == [77.0, 77.0, 77.0]
    assert parse_value("-12.5") == [-12.5]
    assert parse_value("NaN") is None
    assert parse_value(None) is None
    assert parse_value("") is None
    print("  parse_value                            ok")

    bs = SampleRun("http://example.invalid")
    depth = SampleRun("http://example.invalid")
    for i in range(10):
        bs.rows[i] = {"index": i, "lon": -9.4, "lat": 51.5,
                      "band1": 10.0 * i, "bands": "", "n_bands": 3,
                      "greyscale": True, "resolution": 10.0, "raster_id": 1}
    for i in range(8):                       # two points deliberately depthless
        depth.rows[i] = {"index": i, "lon": -9.4, "lat": 51.5,
                         "band1": -(2.0 + 3.0 * i), "bands": "", "n_bands": 1,
                         "greyscale": True, "resolution": 6.0, "raster_id": 1}

    summary = summarise_backscatter("synthetic", 12, bs)
    assert summary["with_data"] == 10, summary
    assert summary["dn_min"] == 0.0 and summary["dn_max"] == 90.0, summary
    print("  summarise_backscatter                  ok")

    joined = report_depth_join(bs, depth)
    assert joined["joined"] == 8, joined
    assert joined["subtidal"] == 8, joined
    print("  report_depth_join                      ok")

    sub = report_substrate([{"INF_Class": "Rock and boulders"},
                            {"INF_Class": "Rock and boulders"},
                            {"INF_Class": "Muddy sand"}])
    assert sub["substrate_polygons"] == 3 and sub["rock_classes"] == 2, sub
    print("  report_substrate                       ok")

    print("\nSELFTEST PASSED. This proves the logic runs; it proves nothing")
    print("about the live INFOMAR services. Run without --selftest for that.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Probe INFOMAR acoustic backscatter over the kelp AOIs.")
    ap.add_argument("--aoi", choices=sorted(AOIS), help="single AOI (default: all)")
    ap.add_argument("--grid", type=int, default=25, help="grid side, default 25")
    ap.add_argument("--skip-depth", action="store_true",
                    help="skip the co-located bathymetry sampling")
    ap.add_argument("--skip-substrate", action="store_true",
                    help="skip the Seabed Folk substrate query")
    ap.add_argument("--depth-category-filter", action="store_true",
                    help="restrict bathymetry to Category = 1 (the suspected "
                         "cause of the old HTTP 400; off by default)")
    ap.add_argument("--diagnose", action="store_true",
                    help="run the 400 diagnostic ladder on the first failure")
    ap.add_argument("--selftest", action="store_true",
                    help="run offline logic checks and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(ATTRIBUTION["INFOMAR"])

    chosen = pick_backscatter_service()
    if not chosen:
        return 2
    bs_url = chosen["url"]

    targets = {args.aoi: AOIS[args.aoi]} if args.aoi else AOIS
    summaries, all_failures = [], []

    for name, bbox in targets.items():
        print(f"\n{'=' * 74}\n{name}   ({aoi_area_km2(bbox):.1f} km2 box)\n{'=' * 74}")

        print("\nSTEP 2  AOI-wide value distribution")
        hist = aoi_histogram(bs_url, bbox)

        print("\nSTEP 3  point sampling")
        pts = grid_points(bbox, args.grid, args.grid)
        run = SampleRun(bs_url)               # no mosaicRule: service has no fields
        run.sample(list(enumerate(pts)))
        summary = summarise_backscatter(name, len(pts), run)

        if run.failures:
            print(f"\n  first failing point: lon={run.failures[0]['lon']:.4f} "
                  f"lat={run.failures[0]['lat']:.4f}")
            print(f"  server said: {run.failures[0]['error']}")
            for f in run.failures:
                all_failures.append({"aoi": name, "service": "backscatter", **f})
            if args.diagnose:
                diagnose_400(bs_url,
                             [run.failures[0]["lon"], run.failures[0]["lat"]])

        depth_run = None
        if not args.skip_depth:
            print("\nSTEP 4  co-located depth")
            depth_run = sample_depth(pts, args.depth_category_filter)
            print(f"  depth points with data: {len(depth_run.rows)} / {len(pts)}"
                  f"   failures: {len(depth_run.failures)}")
            for f in depth_run.failures:
                all_failures.append({"aoi": name, "service": "bathymetry", **f})
            if depth_run.failures and args.diagnose:
                diagnose_400(INFOMAR_BATHY,
                             [depth_run.failures[0]["lon"],
                              depth_run.failures[0]["lat"]])
            summary.update(report_depth_join(run, depth_run))

        if not args.skip_substrate:
            print("\nSTEP 5  interpreted substrate (INFOMAR Seabed Folk)")
            summary.update(report_substrate(seabed_folk(bbox)))

        if hist:
            summary.update({k: v for k, v in hist.items() if k != "counts"})
            (OUT_DIR / f"histogram_{name}.json").write_text(
                json.dumps(hist, indent=2), encoding="utf-8")

        if run.rows:
            path = OUT_DIR / f"backscatter_{name}.csv"
            fields = ["index", "lon", "lat", "band1", "bands", "n_bands",
                      "greyscale", "resolution", "raster_id", "depth_m"]
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for idx in sorted(run.rows):
                    row = dict(run.rows[idx])
                    if depth_run and idx in depth_run.rows:
                        row["depth_m"] = -depth_run.rows[idx]["band1"]
                    w.writerow(row)
            print(f"\n  written: {path}")

        summaries.append(summary)

    if all_failures:
        path = OUT_DIR / "sample_failures.csv"
        keys = sorted({k for f in all_failures for k in f})
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(all_failures)
        print(f"\nFailures written: {path}  ({len(all_failures)} points)")
        print("This file is the reproducible description of the HTTP 400 to")
        print("send to data@infomar.ie. It is worth an email: a named bug in a")
        print("public service, reported with coordinates, is also a contact.")

    if summaries:
        path = OUT_DIR / "backscatter_summary.csv"
        keys = sorted({k for s in summaries for k in s})
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(summaries)
        print(f"Summary written: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())