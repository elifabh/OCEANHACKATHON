#!/usr/bin/env python3
"""
infomar_coverage.py - does INFOMAR bathymetry actually exist where kelp grows?

WHAT THE PREVIOUS PROBE GOT WRONG
The first script called the ImageServer /query operation. That queries mosaic
FOOTPRINTS, not pixels. All three AOIs returned the identical five items
("Inshore", "Offshore" and three overviews), which only proves the national
mosaic overlaps the AOIs. It says nothing about whether a single real
measurement exists at Sherkin.

WHAT THIS SCRIPT DOES INSTEAD
  1. Samples real pixel values on a regular grid inside each AOI, restricted to
     Category = 1 (Primary) so a 15 km overview pixel can never be mistaken for
     survey data.
  2. Reports the DEPTH DISTRIBUTION, not just a coverage percentage. The
     question that matters is not "is there data in the box" but "is there data
     in the 0-15 m strip where Laminaria hyperborea grows". Vessel-mounted MBES
     cannot safely work in very shallow water, so a coverage hole there is the
     expected failure mode.
  3. Pulls the survey coverage polygons, which carry survey names, dates and
     - critically - links to the survey reports where the VERTICAL DATUM is
     stated. The tide-leverage calculation is invalid until that datum is known.

NOT YET VALIDATED: this script was written from the published ArcGIS REST
service metadata and has not been executed against the live service by its
author. Every request prints a diagnosable error rather than failing silently.

Data: INFOMAR (Geological Survey Ireland & Marine Institute), CC BY 4.0.

Usage:
    python src/infomar_coverage.py
    python src/infomar_coverage.py --aoi sherkin_baltimore --grid 30
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

import requests

from common import (
    AOIS,
    ATTRIBUTION,
    CATEGORY_PRIMARY,
    INFOMAR_BATHY,
    INFOMAR_COVERAGE,
    chunked,
    grid_points,
    webmercator_px_to_ground_m,
)

OUT_DIR = Path("outputs/infomar")
TIMEOUT = 90
BATCH = 100          # points per getSamples request
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OceanHackathonCork2026/kelp-prototype"})


# ---------------------------------------------------------------------------
# Low-level request helper
# ---------------------------------------------------------------------------

def arcgis_post(url: str, params: dict) -> dict:
    """POST to an ArcGIS REST endpoint and return parsed JSON.

    POST rather than GET because multipoint geometries exceed URL length limits.
    Raises with the server's own message on an ArcGIS-level error, so a failure
    is diagnosable instead of silent.
    """
    last = None
    for attempt in range(3):
        try:
            resp = SESSION.post(url, data=params, timeout=TIMEOUT)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            last = exc
            print(f"    retry {attempt + 1}/3 after: {exc}")
    else:
        raise RuntimeError(f"{url} failed after 3 attempts: {last}")
    try:
        payload = resp.json()
    except ValueError:
        raise RuntimeError(
            f"Non-JSON response from {url}\nFirst 500 chars:\n{resp.text[:500]}"
        )
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"ArcGIS error from {url}: {payload['error']}")
    return payload


# ---------------------------------------------------------------------------
# 1. Pixel sampling
# ---------------------------------------------------------------------------

def sample_bathymetry(points: list[list[float]], restrict_primary: bool = True):
    """Sample the INFOMAR bathymetry ImageServer at lon/lat points.

    Points falling on NoData are normally omitted from the response, so the
    number of samples returned versus requested is the coverage measure.
    """
    mosaic_rule = {
        "mosaicMethod": "esriMosaicNorthwest",
        "where": f"Category = {CATEGORY_PRIMARY}",
    }

    samples = []
    for batch in chunked(points, BATCH):
        params = {
            "geometry": json.dumps(
                {"points": batch, "spatialReference": {"wkid": 4326}}
            ),
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            "f": "json",
        }
        if restrict_primary:
            params["mosaicRule"] = json.dumps(mosaic_rule)

        payload = arcgis_post(f"{INFOMAR_BATHY}/getSamples", params)
        samples.extend(payload.get("samples", []))

    return samples


def parse_samples(samples: list[dict]) -> list[dict]:
    """Normalise raw getSamples output into flat records with numeric values."""
    rows = []
    for s in samples:
        raw = s.get("value")
        if raw in (None, "", "NaN"):
            continue
        try:
            value = float(str(raw).split()[0])
        except ValueError:
            continue
        loc = s.get("location", {})
        rows.append(
            {
                "lon": loc.get("x"),
                "lat": loc.get("y"),
                "value": value,
                "resolution": s.get("resolution"),
                "raster_id": s.get("rasterId"),
            }
        )
    return rows


def summarise(name: str, requested: int, rows: list[dict]) -> dict:
    """Print and return the diagnostic that actually answers the question."""
    print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
    print(f"  points requested : {requested}")
    print(f"  points with data : {len(rows)}")

    if not rows:
        print("  >>> NO BATHYMETRY DATA IN THIS AOI.")
        print("  >>> Depth-based habitat suitability cannot be built here from")
        print("  >>> INFOMAR. Fall back to EMODnet, or request data from")
        print("  >>> data@infomar.ie.")
        return {"aoi": name, "requested": requested, "with_data": 0}

    pct = 100.0 * len(rows) / requested
    values = [r["value"] for r in rows]
    # INFOMAR elevation convention: negative below datum, positive above.
    depths = [-v for v in values if v < 0]
    above = [v for v in values if v >= 0]

    print(f"  coverage         : {pct:.1f}%")
    if above:
        print(f"  samples at/above datum (land or intertidal): {len(above)}")

    # Resolution check - a coarse value here means an overview leaked through
    resolutions = sorted({round(r["resolution"], 2)
                          for r in rows if r.get("resolution")})
    if resolutions:
        print(f"  native resolutions returned: {resolutions}")
        finest = min(resolutions)
        ground = webmercator_px_to_ground_m(finest, 51.5)
        print(f"  finest ~= {finest} service units ({ground:.1f} m ground at 51.5N)")
        if finest > 50:
            print("  >>> WARNING: coarsest-only data. This is not survey-grade")
            print("  >>> bathymetry for a 10 m Sentinel-2 kelp fringe.")

    if not depths:
        print("  >>> All samples at or above datum. No subtidal depths returned.")
        return {"aoi": name, "requested": requested, "with_data": len(rows)}

    bins = {
        "0-5 m   (kelp core)": 0,
        "5-10 m  (kelp lower limit)": 0,
        "10-20 m": 0,
        "20-50 m": 0,
        ">50 m": 0,
    }
    for d in depths:
        if d < 5:
            bins["0-5 m   (kelp core)"] += 1
        elif d < 10:
            bins["5-10 m  (kelp lower limit)"] += 1
        elif d < 20:
            bins["10-20 m"] += 1
        elif d < 50:
            bins["20-50 m"] += 1
        else:
            bins[">50 m"] += 1

    print(f"  depth range      : {min(depths):.1f} m to {max(depths):.1f} m")
    print(f"  median depth     : {statistics.median(depths):.1f} m")
    print("  depth distribution:")
    for label, count in bins.items():
        share = 100.0 * count / len(depths)
        bar = "#" * int(share / 2)
        print(f"    {label:<28} {count:>4}  {share:5.1f}%  {bar}")

    shallow = bins["0-5 m   (kelp core)"] + bins["5-10 m  (kelp lower limit)"]
    if shallow == 0:
        print("\n  >>> SHALLOW COVERAGE HOLE CONFIRMED: no samples shallower")
        print("  >>> than 10 m. This is the expected MBES limitation and it")
        print("  >>> constrains the habitat-suitability fallback, which needs")
        print("  >>> depth exactly in the strip that is missing.")
    else:
        print(f"\n  >>> {shallow} samples shallower than 10 m: the kelp depth band")
        print("  >>> IS covered. Habitat-suitability fallback is viable here.")

    return {
        "aoi": name,
        "requested": requested,
        "with_data": len(rows),
        "coverage_pct": round(pct, 1),
        "min_depth_m": round(min(depths), 1),
        "max_depth_m": round(max(depths), 1),
        "median_depth_m": round(statistics.median(depths), 1),
        "n_shallower_than_10m": shallow,
    }


# ---------------------------------------------------------------------------
# 2. Survey coverage polygons - provenance and the vertical datum trail
# ---------------------------------------------------------------------------

def survey_coverage(bbox: list[float]) -> list[dict]:
    """Query every queryable layer of the survey coverage service for the AOI."""
    meta = SESSION.get(f"{INFOMAR_COVERAGE}?f=json", timeout=TIMEOUT).json()
    layers = meta.get("layers", [])
    if not layers:
        print("  (no layers listed on the coverage service)")
        return []

    found = []
    xmin, ymin, xmax, ymax = bbox
    for layer in layers:
        lid, lname = layer.get("id"), layer.get("name")
        params = {
            "geometry": json.dumps(
                {
                    "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
                    "spatialReference": {"wkid": 4326},
                }
            ),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            payload = arcgis_post(f"{INFOMAR_COVERAGE}/{lid}/query", params)
        except Exception as exc:                      # noqa: BLE001
            print(f"  layer {lid} ({lname}): not queryable - {exc}")
            continue

        feats = payload.get("features", [])
        if feats:
            print(f"  layer {lid} ({lname}): {len(feats)} feature(s)")
            for f in feats:
                attrs = f.get("attributes", {})
                found.append({"layer_id": lid, "layer_name": lname, **attrs})
    return found


def report_datum_trail(records: list[dict]) -> None:
    """Surface anything that looks like a survey report link or a datum field."""
    if not records:
        print("\n  No polygons returned. If a QUERY FAILED line appears above,")
        print("  this is a request failure, NOT a coverage result. Re-run.")
        print("  That is a stronger negative signal than an empty pixel sample:")
        print("  it suggests the area was never surveyed.")
        return

    interesting = ("report", "url", "link", "datum", "vertical", "year",
                   "date", "survey", "vessel", "order", "name")
    print("\n  Fields worth opening by hand:")
    for rec in records[:8]:
        for key, val in rec.items():
            if val in (None, "", " "):
                continue
            if any(tok in key.lower() for tok in interesting):
                print(f"    {key}: {val}")
        print("    ---")
    print("  ACTION: open any survey report URL above and find the VERTICAL")
    print("  DATUM. If it is not LAT, your tide-gauge sum needs a constant")
    print("  offset before the shallow/deep split can be trusted.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aoi", choices=sorted(AOIS), help="single AOI (default: all)")
    ap.add_argument("--grid", type=int, default=20, help="grid side, default 20")
    ap.add_argument("--skip-coverage", action="store_true",
                    help="skip the survey coverage polygon query")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = {args.aoi: AOIS[args.aoi]} if args.aoi else AOIS

    print(ATTRIBUTION["INFOMAR"])

    summaries = []
    for name, bbox in targets.items():
        pts = grid_points(bbox, args.grid, args.grid)
        try:
            raw = sample_bathymetry(pts)
        except Exception as exc:                      # noqa: BLE001
            print(f"\n{name}: sampling FAILED - {exc}")
            continue

        rows = parse_samples(raw)
        summaries.append(summarise(name, len(pts), rows))

        if rows:
            csv_path = OUT_DIR / f"samples_{name}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=["lon", "lat", "value", "resolution", "raster_id"]
                )
                writer.writeheader()
                writer.writerows(rows)
            print(f"  written: {csv_path}")

        if not args.skip_coverage:
            print("\n  survey coverage polygons:")
            try:
                recs = survey_coverage(bbox)
            except Exception as exc:                  # noqa: BLE001
                print(f"  coverage query FAILED - {exc}")
                recs = []
            report_datum_trail(recs)
            if recs:
                json_path = OUT_DIR / f"coverage_{name}.json"
                json_path.write_text(json.dumps(recs, indent=2), encoding="utf-8")
                print(f"  written: {json_path}")

    if summaries:
        summary_path = OUT_DIR / "coverage_summary.csv"
        keys = sorted({k for s in summaries for k in s})
        with summary_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(summaries)
        print(f"\nSummary written: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())