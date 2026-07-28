#!/usr/bin/env python3
"""
reef_intersect.py - candidate Laminaria hyperborea habitat from reef x depth x
exposure.

WHY THIS SCRIPT EXISTS
The INFOMAR Seabed Substrate layer cannot deliver the habitat. Measured on
2026-07-28 across the three AOIs: 0.10 km2 of seabed is labelled Rock inside
the 0-20 m kelp band, against 12.29 km2 labelled "Unclassified substrate" in
the same band. The shallow zone has DEPTH - inner_roaringwater alone has
9.6 km2 of measured depth shallower than 20 m - but no substrate class. The
acoustic survey reached the shallows; the interpretation did not.

That absence is not geological. Sherkin and Baltimore are bedrock coasts, and
84% of the rock INFOMAR does map at sherkin sits deeper than 30 m. Bedrock
does not stop at 30 m and resume at the shoreline. The gap is in the map.

NPWS Annex I Reef [1170] fills exactly this gap, because it comes from a
different instrument: diving and video survey of SACs, which works precisely
where vessel-mounted multibeam interpretation does not. Roaringwater Bay and
Islands SAC (000101) is designated for Reefs [1170], so sherkin_baltimore sits
inside a legally recognised reef designation.

WHAT REEF IS AND IS NOT - SAY THIS ON THE SLIDE
Annex I "Reef" is a container, not our habitat. It includes bedrock, stony and
biogenic reef, at any depth, intertidal as well as subtidal. It is not kelp and
it is not evidence of kelp. It becomes a kelp-habitat candidate only after two
further filters, both of which we have:

    reef  AND  0-20 m depth (INFOMAR, measured, LAT)
          AND  wave exposure (Burrows fetch, georeferencing verified)

The output of this script is therefore CANDIDATE habitat: hard substrate in the
photic zone on an exposed coast. Calling it a kelp map would be an overclaim.
Ground truth for West Cork exists and is the next step, not a substitute for
one: Norton, Hiscock & Kitching (1977), Journal of Ecology 65:919-941, mapped
an L. hyperborea forest at Carrigathorna beside Lough Hyne, next to this AOI.

TWO-STAGE USE. Run --inspect first. The NPWS download's internal structure -
layer names, the field carrying the habitat code, the CRS - is not known to
this script in advance and is not guessed. Inspect, then run.

Dependencies: geopandas (BSD-3), shapely (BSD-3), pyproj (MIT), rasterio
(BSD-3), requests (Apache-2.0). All to DEPENDENCIES.md with versions.

Data: NPWS (Annex I Reefs), INFOMAR / GSI & Marine Institute CC BY 4.0,
Burrows wave fetch (licence to be confirmed from the figshare record).

Usage:
    python src/reef_intersect.py --selftest
    python src/reef_intersect.py --inspect data/npws/ReefInventory2023.gdb
    python src/reef_intersect.py --reef data/npws/ReefInventory2023.gdb \
        --layer CO_1170_Reefs --fetch data/fetch/log10_eu200m1a.tif
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point
from shapely.strtree import STRtree

from common import AOIS, CRS_ITM, INFOMAR_BATHY, ArcGISError, arcgis_request

OUT_DIR = Path("outputs/habitat")
TO_ITM = Transformer.from_crs(4326, CRS_ITM, always_xy=True)

GRID_M = 100.0
CELL_KM2 = (GRID_M * GRID_M) / 1e6
BATCH = 400
KELP_BAND = (0.0, 20.0)

# Words that mark a layer or a field value as Annex I reef. Matched
# case-insensitively on substrings, because NPWS spells it several ways
# ("Reefs", "1170", "CO_1170_Reefs", "Annex I Reef").
REEF_TOKENS = ("reef", "1170")


# ---------------------------------------------------------------------------
# Stage 1 - what did she actually download?
# ---------------------------------------------------------------------------

def inspect(path: Path) -> int:
    """List every layer, its CRS, size and fields. Guess nothing."""
    import geopandas as gpd
    from pyogrio import list_layers

    print(f"inspecting {path}\n")
    try:
        layers = list_layers(path)
    except Exception as exc:
        print(f"  cannot open: {exc}")
        print("  If this is a .gdb directory, pass the DIRECTORY itself, not a")
        print("  file inside it. If it is a zip, unzip it first.")
        return 2

    for name, geomtype in layers:
        print(f"  layer: {name}   ({geomtype})")
        try:
            gdf = gpd.read_file(path, layer=name, rows=5)
        except Exception as exc:
            print(f"    unreadable: {exc}\n")
            continue
        print(f"    CRS    : {gdf.crs}")
        print(f"    fields : {', '.join(gdf.columns[:14])}"
              f"{' ...' if len(gdf.columns) > 14 else ''}")
        hit = any(t in str(name).lower() for t in REEF_TOKENS)
        # Also look for a habitat-code field carrying 1170 in the sample rows.
        for col in gdf.columns:
            vals = {str(v).lower() for v in gdf[col].head(5).tolist()}
            if any(t in v for v in vals for t in REEF_TOKENS):
                print(f"    >>> field '{col}' carries reef/1170 values: "
                      f"{sorted(vals)[:3]}")
                hit = True
        if hit:
            print("    >>> CANDIDATE REEF LAYER. Pass it with --layer.")
        print()
    print("Next: rerun with --reef <path> --layer <name> --fetch <fetch.tif>")
    return 0


# ---------------------------------------------------------------------------
# Stage 2 - reef polygons in ITM, filtered and clipped
# ---------------------------------------------------------------------------

def load_reef(path: Path, layer: str | None, code_field: str | None,
              code_value: str | None):
    """Read the reef layer, keep only reef features, project to ITM."""
    import geopandas as gpd

    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    print(f"  features read : {len(gdf)}")
    if gdf.crs is None:
        print("  >>> NO CRS on this layer. Cannot place it on the earth.")
        print("  >>> Find the CRS in the NPWS metadata and set it explicitly")
        print("  >>> before using any of this. Do not assume WGS84.")
        return None
    print(f"  source CRS    : {gdf.crs}")

    if code_field:
        if code_field not in gdf.columns:
            print(f"  >>> field '{code_field}' is not in this layer. Fields: "
                  f"{list(gdf.columns)}")
            return None
        before = len(gdf)
        if code_value:
            gdf = gdf[gdf[code_field].astype(str).str.lower()
                      .str.contains(code_value.lower(), na=False)]
        else:
            gdf = gdf[gdf[code_field].astype(str).str.lower()
                      .str.contains("|".join(REEF_TOKENS), na=False)]
        print(f"  filtered on {code_field}: {before} -> {len(gdf)} features")
        if len(gdf) == 0:
            print("  >>> FILTER REMOVED EVERYTHING. Check the value with")
            print("  >>> --inspect before assuming there is no reef here.")
            return None
    else:
        print("  >>> NO --code-field given, so EVERY feature in this layer is")
        print("  >>> treated as reef. If the layer mixes habitat types, the")
        print("  >>> area below is an overcount. Check with --inspect.")

    gdf = gdf.to_crs(epsg=CRS_ITM)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    invalid = (~gdf.geometry.is_valid).sum()
    if invalid:
        print(f"  repairing {invalid} invalid geometries with buffer(0)")
        gdf.loc[~gdf.geometry.is_valid, "geometry"] = \
            gdf.loc[~gdf.geometry.is_valid].geometry.buffer(0)
    print(f"  total reef area (whole layer): "
          f"{gdf.geometry.area.sum() / 1e6:.1f} km2")
    return gdf


# ---------------------------------------------------------------------------
# Depth, from INFOMAR, on the AOI grid
# ---------------------------------------------------------------------------

def aoi_grid(bbox: list[float]) -> list[list[float]]:
    lat_mid = (bbox[1] + bbox[3]) / 2.0
    dlon = GRID_M / (111320.0 * math.cos(math.radians(lat_mid)))
    dlat = GRID_M / 110574.0
    pts, y = [], bbox[1] + dlat / 2
    while y < bbox[3]:
        x = bbox[0] + dlon / 2
        while x < bbox[2]:
            pts.append([x, y])
            x += dlon
        y += dlat
    return pts


def sample_depths(pts: list[list[float]]) -> dict[int, float]:
    """Depth below LAT at each point, positive down. Missing = not surveyed.

    NOTE: duplicated from seabed_folk_probe.py. Both copies encode the
    empty-batch rule proven on 2026-07-27 - an INFOMAR getSamples request whose
    points all fall outside coverage returns HTTP 400 rather than an empty
    list, so a 400 here means zero samples, not a bug. Move this into
    common.py at the next refactor; two copies of a rule is one too many.
    """
    depths: dict[int, float] = {}
    empty = 0
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
            empty += 1
            continue
        for s in payload.get("samples", []):
            loc, raw = s.get("locationId"), s.get("value")
            if loc is None or raw in (None, "", "NaN"):
                continue
            try:
                depths[start + int(loc)] = -float(str(raw).split()[0])
            except ValueError:
                continue
    if empty:
        print(f"    ({empty} batches entirely outside INFOMAR coverage)")
    return depths


def sample_fetch(path: Path, pts: list[list[float]]) -> dict[int, float]:
    """log10 summed wave fetch at each point, from the Burrows raster."""
    import rasterio
    from rasterio.crs import CRS as RCRS
    from rasterio.warp import transform as warp_transform

    out: dict[int, float] = {}
    with rasterio.open(path) as src:
        xs, ys = warp_transform(RCRS.from_epsg(4326), src.crs,
                                [p[0] for p in pts], [p[1] for p in pts])
        b = src.bounds
        idx = [i for i, (x, y) in enumerate(zip(xs, ys))
               if b.left <= x <= b.right and b.bottom <= y <= b.top]
        if not idx:
            return out
        coords = [(xs[i], ys[i]) for i in idx]
        for i, arr in zip(idx, src.sample(coords, indexes=1, masked=True)):
            v = arr[0]
            if hasattr(v, "mask") and v.mask:
                continue
            fv = float(v)
            if fv == fv and (src.nodata is None or fv != src.nodata):
                out[i] = fv
    return out


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------

def run_aoi(name: str, bbox: list[float], reef_gdf, fetch_path: Path | None,
            depth_fn=None) -> tuple[dict, list[dict]]:
    print(f"\n{'=' * 74}\n{name}\n{'=' * 74}")

    x0, x1 = TO_ITM.transform([bbox[0], bbox[2]], [bbox[1], bbox[3]])[0]
    y0, y1 = TO_ITM.transform([bbox[0], bbox[2]], [bbox[1], bbox[3]])[1]
    from shapely.geometry import box as sbox
    clip = sbox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    sub = reef_gdf[reef_gdf.geometry.intersects(clip)]
    if len(sub) == 0:
        print("  NO REEF POLYGONS HERE.")
        print("  >>> If this AOI lies outside any SAC, a dataset clipped to")
        print("  >>> SAC boundaries will be empty by construction. That is a")
        print("  >>> coverage limit, NOT evidence of no reef. Check whether")
        print("  >>> this AOI is inside a designated site before concluding.")
        return {"aoi": name, "reef_km2": 0.0, "candidate_ha": 0.0}, []

    reef_clipped = sub.geometry.intersection(clip)
    reef_km2 = reef_clipped.area.sum() / 1e6
    print(f"  reef polygons intersecting : {len(sub)}")
    print(f"  reef area inside the AOI   : {reef_km2:.2f} km2")

    geoms = [g for g in reef_clipped if g is not None and not g.is_empty]
    tree = STRtree(geoms)

    pts = aoi_grid(bbox)
    itm = [TO_ITM.transform(p[0], p[1]) for p in pts]
    in_reef = set()
    for i, (x, y) in enumerate(itm):
        p = Point(x, y)
        for j in tree.query(p):
            if geoms[j].contains(p):
                in_reef.add(i)
                break
    print(f"  grid points in reef        : {len(in_reef)} of {len(pts)}"
          f"   ({len(in_reef) * CELL_KM2:.2f} km2 by grid count)")

    print("  sampling INFOMAR depth ...")
    depths = (depth_fn or sample_depths)(pts)
    fetches = sample_fetch(fetch_path, pts) if fetch_path else {}

    bands = defaultdict(int)
    rows = []
    no_depth = 0
    for i in sorted(in_reef):
        d = depths.get(i)
        if d is None:
            no_depth += 1
            continue
        if d <= 0:
            bands["intertidal / above LAT"] += 1
            continue
        band = ("0-5 m" if d < 5 else "5-10 m" if d < 10 else
                "10-20 m" if d < 20 else "20-30 m" if d < 30 else ">30 m")
        bands[band] += 1
        if KELP_BAND[0] < d <= KELP_BAND[1]:
            rows.append({"aoi": name, "lon": round(pts[i][0], 6),
                         "lat": round(pts[i][1], 6), "depth_m": round(d, 2),
                         "log10_fetch": (round(fetches[i], 3)
                                         if i in fetches else "")})

    print(f"\n  reef area by measured depth")
    for band in ("intertidal / above LAT", "0-5 m", "5-10 m", "10-20 m",
                 "20-30 m", ">30 m"):
        if bands.get(band):
            print(f"    {band:<24}{bands[band] * CELL_KM2:>8.2f} km2")
    cand_ha = len(rows) * CELL_KM2 * 100
    print(f"\n  CANDIDATE HABITAT (reef AND 0-20 m) : {cand_ha:.0f} ha"
          f"  ({len(rows) * CELL_KM2:.2f} km2)")
    print(f"  reef with NO depth measurement      : "
          f"{no_depth * CELL_KM2 * 100:.0f} ha")
    print("  >>> The second number is unsurveyed depth, not unsuitable")
    print("  >>> habitat. Both go on the slide, or the estimate is dishonest")
    print("  >>> in whichever direction suits us.")

    fv = sorted(r["log10_fetch"] for r in rows if r["log10_fetch"] != "")
    if fv:
        print(f"  exposure within the candidate: median log10 fetch "
              f"{fv[len(fv) // 2]:.2f}  (n={len(fv)})")
    elif fetch_path:
        print("  >>> NO FETCH VALUES in the candidate area. Check the raster.")

    return ({"aoi": name, "reef_km2": round(reef_km2, 3),
             "grid_reef_km2": round(len(in_reef) * CELL_KM2, 3),
             "candidate_ha": round(cand_ha, 1),
             "reef_no_depth_ha": round(no_depth * CELL_KM2 * 100, 1),
             "median_log10_fetch": (round(fv[len(fv) // 2], 3) if fv else "")},
            rows)


# ---------------------------------------------------------------------------
# Offline self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    import geopandas as gpd
    import tempfile
    from shapely.geometry import box as sbox

    print("SELFTEST (no network)\n")
    tmp = Path(tempfile.mkdtemp())

    # A reef covering the western half of sherkin_baltimore.
    b = AOIS["sherkin_baltimore"]
    poly = sbox(b[0], b[1], (b[0] + b[2]) / 2, b[3])
    gdf = gpd.GeoDataFrame({"HABCODE": ["1170"]}, geometry=[poly], crs=4326)
    p = tmp / "reef.gpkg"
    gdf.to_file(p, layer="CO_1170_Reefs", driver="GPKG")

    loaded = load_reef(p, "CO_1170_Reefs", "HABCODE", "1170")
    assert loaded is not None and len(loaded) == 1
    print("  load + filter + reproject           ok")

    # Fake depths: everything 12 m except a deep strip, so the band filter
    # has something to reject.
    pts_seen = {}

    def fake_depth(pts):
        pts_seen["n"] = len(pts)
        return {i: (12.0 if i % 3 else 45.0) for i in range(len(pts))}

    summary, rows = run_aoi("sherkin_baltimore", b, loaded, None, fake_depth)
    # Two thirds of reef points are at 12 m, one third at 45 m.
    frac = summary["candidate_ha"] / (summary["grid_reef_km2"] * 100)
    assert 0.6 < frac < 0.72, frac
    print(f"\n  depth band kept {frac:.2f} of reef points (expected 0.67)  ok")
    assert summary["reef_no_depth_ha"] == 0.0

    # An AOI with no reef must say so, not report zero habitat silently.
    empty, _ = run_aoi("mizen_outer", AOIS["mizen_outer"], loaded, None,
                       fake_depth)
    assert empty["candidate_ha"] == 0.0
    print("\n  empty AOI reported as coverage limit, not as absence   ok")

    print("\nSELFTEST PASSED. Loading, filtering, reprojection, the reef/grid")
    print("join and the depth-band filter are correct. Nothing has touched")
    print("NPWS or INFOMAR yet.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Candidate kelp habitat = NPWS reef x depth x exposure.")
    ap.add_argument("--inspect", type=Path, help="list layers and fields, then stop")
    ap.add_argument("--reef", type=Path, help="NPWS reef dataset")
    ap.add_argument("--layer", help="layer name inside it")
    ap.add_argument("--code-field", help="field carrying the habitat code")
    ap.add_argument("--code-value", default="1170", help="value to keep")
    ap.add_argument("--fetch", type=Path, help="Burrows wave-fetch GeoTIFF")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.inspect:
        return inspect(args.inspect)
    if not args.reef or not args.reef.exists():
        ap.error("--reef is required (or --inspect / --selftest)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("NPWS Annex I Reefs [1170]. INFOMAR (GSI & Marine Institute), "
          "CC BY 4.0. Burrows wave fetch.\n")
    reef = load_reef(args.reef, args.layer, args.code_field, args.code_value)
    if reef is None:
        return 2
    if args.fetch and not args.fetch.exists():
        print(f"  fetch raster not found: {args.fetch}")
        return 2

    summaries, all_rows = [], []
    for name, bbox in AOIS.items():
        s, rows = run_aoi(name, bbox, reef, args.fetch)
        summaries.append(s)
        all_rows.extend(rows)

    total = sum(s["candidate_ha"] for s in summaries)
    print(f"\n{'=' * 74}\nCANDIDATE HABITAT, ALL AOIs : {total:.0f} ha")
    print("Candidate means hard substrate in the photic zone. It is not a kelp")
    print("map and must not be presented as one until ground truth is added.")
    print("=" * 74)

    if all_rows:
        p = OUT_DIR / "candidate_habitat_points.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(all_rows[0]))
            w.writeheader()
            w.writerows(all_rows)
        print(f"\n  written: {p}   ({len(all_rows)} cells of "
              f"{CELL_KM2 * 100:.0f} ha each)")
    p2 = OUT_DIR / "habitat_summary.csv"
    with p2.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summaries[0]))
        w.writeheader()
        w.writerows(summaries)
    print(f"  written: {p2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())