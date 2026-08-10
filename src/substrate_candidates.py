#!/usr/bin/env python3
"""
substrate_candidates.py — step C, check 3. Closes an open item in common.py.

WHY
---
NPWS layer 21 does not reach shallow water at mizen_outer: 94.8 ha of 4-10 m
seabed, 0.0 ha of overlap, against 24.5 % overlap at sherkin. The shallow cells
were never candidates. Bathymetry was never the blocker.

So candidate generation has to stop depending on reef polygons. The replacement
named in common.py is the INFOMAR Seabed Substrate (Folk) layer, target
definition Substrate = Rock AND Biozone = Infralittoral, i.e. EUNIS A3.

But common.py also says, in as many words:

    BIOZONE_VALUES_SEEN: tuple[str, ...] = ()
    "Biozone values are NOT yet known. Pulling the distinct list is an open
     task for step 2, and it is a gating one. Do not hard-code a guessed
     string here."

That warning is why this script reads the values instead of assuming them.
The project has already been bitten once by a guessed field name: an early
probe assumed an INF_Class field that does not exist and printed a confident
"no rock found".

WHAT IT DOES
------------
1. Reads the distinct Biozone and Substrate values actually published, with no
   guessing, and prints them.
2. Pulls the polygons over each AOI and reports area by Biozone x Substrate,
   in EPSG:2157. Never Shape_Area: that field is Web Mercator and overstates
   area by about 2.6x at this latitude.
3. Intersects Rock polygons with the 4-10 m depth strip and reports how many
   candidate hectares this route would produce at mizen, with sherkin as a
   control.

WHAT IT DOES NOT SETTLE
-----------------------
Whether kelp is present. This produces candidate cells; the suitability model
still has to run, and NPWS stays the label source. If Biozone turns out to
carry no infralittoral class, the depth band has to come from light attenuation
instead, which needs a local Kd estimate — a much bigger job, and one to decide
on deliberately rather than drift into.

Usage:
    python src/substrate_candidates.py --aoi mizen_outer
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

FOLK = ("https://maps.marine.ie/arcgis/rest/services/Infomar/"
        "INFOMAR_Seabed_Folk/MapServer")
LAYER = 0
BATHY = "https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer"
ITM = 2157


def need(mod, pip_name=None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"ERROR: {mod} not installed.  pip install {pip_name or mod}")


def load_common():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path.cwd()))
    try:
        import common
        return common
    except Exception:
        try:
            from src import common
            return common
        except Exception:
            return None


def q(requests, url, params):
    """MapServer query. A 4xx is deterministic and is not retried."""
    p = dict(params); p.setdefault("f", "json")
    r = requests.get(url, params=p, timeout=120)
    if r.status_code >= 400:
        print(f"    HTTP {r.status_code}: {r.text[:200]}")
        return None
    try:
        j = r.json()
    except ValueError:
        print(f"    non-JSON body: {r.text[:200]}")
        return None
    if isinstance(j, dict) and "error" in j:
        print(f"    ArcGIS error: {str(j['error'])[:200]}")
        return None
    return j


def distinct(requests, field):
    j = q(requests, f"{FOLK}/{LAYER}/query",
          {"where": "1=1", "outFields": field, "returnDistinctValues": "true",
           "returnGeometry": "false"})
    if not j:
        return []
    vals = []
    for f in j.get("features", []):
        v = (f.get("attributes") or {}).get(field)
        if v not in (None, "") and v not in vals:
            vals.append(v)
    return sorted(vals, key=str)


def polygons(requests, gpd, bbox, page=1000):
    """All Folk polygons intersecting the bbox, paginated, as GeoDataFrame."""
    w, s, e, n = bbox
    feats, offset = [], 0
    while True:
        j = q(requests, f"{FOLK}/{LAYER}/query", {
            "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*", "returnGeometry": "true", "outSR": 4326,
            "resultOffset": offset, "resultRecordCount": page, "f": "geojson"})
        if not j:
            return None
        got = j.get("features", [])
        feats.extend(got)
        if len(got) < page:
            break
        offset += page
        if offset > 20000:
            print("    stopping at 20k polygons")
            break
    if not feats:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    g = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    g = g[g.geometry.notna() & ~g.geometry.is_empty]
    # CLIP. esriSpatialRelIntersects returns whole polygons, so a single large
    # offshore Sand polygon touching the box was being counted in full: an
    # 8x9 km AOI reported 592,350 ha. Areas are only meaningful after clipping.
    from shapely.geometry import box as shbox
    g = gpd.clip(g, gpd.GeoDataFrame(geometry=[shbox(w, s, e, n)], crs="EPSG:4326"))
    return g[~g.geometry.is_empty].to_crs(epsg=ITM)


def depth_strip(requests, rasterio, gpd, bbox, dmin, dmax, size=1000):
    from rasterio import features
    from shapely.geometry import shape
    w, s, e, n = bbox
    r = requests.get(BATHY + "/exportImage", timeout=180, params={
        "bbox": f"{w},{s},{e},{n}", "bboxSR": 4326, "imageSR": 4326,
        "size": f"{size},{size}", "format": "tiff", "pixelType": "F32",
        "noData": "-3.4028235e+38", "interpolation": "RSP_NearestNeighbor",
        "f": "image"})
    if r.status_code != 200 or r.content[:2] not in (b"II", b"MM"):
        return None
    with rasterio.io.MemoryFile(r.content) as mf, mf.open() as src:
        z = np.asarray(src.read(1), dtype="float64")
        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        z[z < -1e30] = np.nan
        tr = src.transform
    depth = -z                      # negative below LAT; land is positive
    depth[~np.isfinite(depth)] = np.nan
    depth[depth <= 0] = np.nan
    mask = ((depth >= dmin) & (depth < dmax)).astype("uint8")
    if not mask.any():
        return None
    polys = [shape(g) for g, v in
             features.shapes(mask, mask=mask.astype(bool), transform=tr) if v == 1]
    return gpd.GeoDataFrame(geometry=polys, crs="EPSG:4326").to_crs(epsg=ITM)


def diagnose_zero(requests, rasterio, gpd, np_, bbox, rock_gdf, strip_gdf, size=1000):
    """A zero intersection between 500 ha of rock and 240 ha of shallow water in
    one box is either a geometry bug or a real coverage limit. Tell them apart
    instead of picking one."""
    print("    --- zero-overlap diagnostic ---")

    # 1. geometry validity. ArcGIS GeoJSON frequently exports self-intersecting
    #    rings, and gpd.overlay returns empty rather than raising on those.
    bad_r = int((~rock_gdf.geometry.is_valid).sum())
    bad_s = int((~strip_gdf.geometry.is_valid).sum())
    print(f"    invalid geometries: rock {bad_r}/{len(rock_gdf)}, "
          f"strip {bad_s}/{len(strip_gdf)}")
    if bad_r or bad_s:
        r2 = rock_gdf.copy(); r2["geometry"] = r2.geometry.buffer(0)
        s2 = strip_gdf.copy(); s2["geometry"] = s2.geometry.buffer(0)
        try:
            i2 = gpd.overlay(r2[r2.is_valid], s2[s2.is_valid], how="intersection")
            ha2 = float(i2.area.sum()) / 1e4 if not i2.empty else 0.0
            print(f"    after buffer(0) repair: {ha2:.2f} ha")
            if ha2 > 0:
                print("    -> it was a GEOMETRY BUG. Use the repaired result.")
                return i2, ha2
        except Exception as ex:  # noqa: BLE001
            print(f"    repair attempt failed: {ex}")

    # 2. how far apart are they, really
    try:
        d = float(strip_gdf.geometry.apply(
            lambda g: rock_gdf.distance(g).min()).min())
        print(f"    nearest rock polygon to the depth strip: {d:.0f} m")
    except Exception:  # noqa: BLE001
        pass

    # 3. the decisive one: what depth do the rock polygons actually sit at?
    w, s_, e, n = bbox
    r = requests.get(BATHY + "/exportImage", timeout=180, params={
        "bbox": f"{w},{s_},{e},{n}", "bboxSR": 4326, "imageSR": 4326,
        "size": f"{size},{size}", "format": "tiff", "pixelType": "F32",
        "noData": "-3.4028235e+38", "interpolation": "RSP_NearestNeighbor",
        "f": "image"})
    if r.status_code != 200 or r.content[:2] not in (b"II", b"MM"):
        print("    could not re-fetch bathymetry for the depth-of-rock check")
        return None, 0.0
    from rasterio.mask import mask as rmask
    with rasterio.io.MemoryFile(r.content) as mf, mf.open() as src:
        geoms = list(rock_gdf.to_crs(src.crs).geometry)
        try:
            arr, _ = rmask(src, geoms, crop=True, filled=True, nodata=np_.nan)
        except Exception as ex:  # noqa: BLE001
            print(f"    masking failed: {ex}")
            return None, 0.0
        z = np_.asarray(arr[0], dtype="float64")
        if src.nodata is not None:
            z[z == src.nodata] = np_.nan
    z[z < -1e30] = np_.nan
    dep = -z
    dep[~np_.isfinite(dep)] = np_.nan
    dep[dep <= 0] = np_.nan
    ok = int(np_.sum(np_.isfinite(dep)))
    if ok == 0:
        print("    no bathymetry inside the rock polygons at all")
        return None, 0.0
    qs = np_.nanpercentile(dep, [0, 1, 5, 50, 95, 100])
    print(f"    depth INSIDE rock polygons: min {qs[0]:.1f} | p1 {qs[1]:.1f} | "
          f"p5 {qs[2]:.1f} | median {qs[3]:.1f} | p95 {qs[4]:.1f} | max {qs[5]:.1f} m")
    shal = int(np_.nansum((dep >= 4) & (dep < 10)))
    print(f"    rock pixels in 4-10 m: {shal} of {ok} ({100.0*shal/ok:.2f} %)")
    if shal == 0:
        print("    -> REAL LIMIT. Folk mapping does not reach 4-10 m here.")
        print("       Expected: Folk rock is traced from backscatter, and step 1")
        print("       already found near-zero acoustic data at 0-20 m.")
    else:
        print("    -> rock DOES reach 4-10 m; the overlay is at fault, not the data.")
    return None, 0.0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", default="mizen_outer")
    ap.add_argument("--compare", default="sherkin_baltimore")
    ap.add_argument("--dmin", type=float, default=4.0)
    ap.add_argument("--dmax", type=float, default=10.0)
    ap.add_argument("--out", default="outputs/model/substrate_candidates")
    args = ap.parse_args()

    requests = need("requests"); rasterio = need("rasterio"); gpd = need("geopandas")
    import pandas as pd

    common = load_common()
    aois = getattr(common, "AOIS", {}) if common else {}
    if args.aoi not in aois:
        sys.exit(f"ERROR: '{args.aoi}' not in common.AOIS")

    print("=" * 78)
    print("INFOMAR SEABED FOLK — the actual published values")
    print("=" * 78)
    bio = distinct(requests, "Biozone")
    sub = distinct(requests, "Substrate")
    print(f"\n  Biozone   ({len(bio)} values)")
    for v in bio:
        print(f"    {v}")
    print(f"\n  Substrate ({len(sub)} values)")
    for v in sub:
        print(f"    {v}")

    infra = [v for v in bio if "infralit" in str(v).lower()]
    rock = [v for v in sub if str(v).strip().lower() == "rock"]
    print(f"\n  infralittoral-like Biozone values : {infra or 'NONE FOUND'}")
    print(f"  rock Substrate values             : {rock or 'NONE FOUND'}")
    if len(infra) > 1:
        print(f"\n  DATA QUALITY: {len(infra)} spellings of the same class, e.g. "
              f"trailing whitespace. Strip before any matching.")
    print("\n  Biozone is read and reported but NOT used as a filter — see the")
    print("  note in main(). The 4-10 m band comes from INFOMAR bathymetry.")

    print("\n" + "=" * 78)
    print(f"CANDIDATE AREA IN THE {args.dmin:.0f}-{args.dmax:.0f} m BAND")
    print("=" * 78)
    rows = {}
    keep_layers = {}
    for name in [args.aoi] + ([args.compare] if args.compare in aois else []):
        bbox = tuple(float(x) for x in aois[name])
        print(f"\n  {name}")
        g = polygons(requests, gpd, bbox)
        if g is None:
            print("    Folk query failed")
            continue
        if g.empty:
            print("    no Folk polygons in this box")
            rows[name] = {"folk_ha": 0, "rock_ha": 0, "strip_ha": 0, "candidate_ha": 0}
            continue
        g["ha"] = g.area / 1e4          # EPSG:2157, never Shape_Area
        print(f"    {len(g)} polygons, {g['ha'].sum():.1f} ha (ITM area, not Shape_Area)")
        if "Biozone" in g.columns and "Substrate" in g.columns:
            t = g.groupby(["Biozone", "Substrate"], dropna=False)["ha"].sum()
            for (b, s_), v in t.sort_values(ascending=False).head(8).items():
                print(f"      {str(b)[:28]:<28} {str(s_)[:24]:<24} {v:8.1f} ha")

        # BIOZONE IS NOT USED AS A FILTER.
        # common.py proposed Substrate=Rock AND Biozone=Infralittoral (EUNIS A3).
        # Read against the live layer that filter yields 4.8 ha at mizen and
        # 1.5 ha at sherkin, and zero candidates at BOTH — including the control
        # AOI where the pipeline demonstrably works. A filter that returns zero
        # on a known-good control is broken, not informative.
        # The reason: INFOMAR classifies the shallow rock here as "Shallow
        # circalittoral", not "Infralittoral" (mizen 1485 ha, sherkin 605 ha).
        # So the depth band comes from the bathymetry we already trust, and
        # Biozone is reported for information only.
        sel = g
        if rock and "Substrate" in g.columns:
            sel = sel[sel["Substrate"].isin(rock)]
        if "Biozone" in sel.columns and len(sel):
            bz = sel.groupby("Biozone", dropna=False)["ha"].sum().sort_values(
                ascending=False)
            print("    rock by Biozone (reported, NOT filtered on):")
            for k, v in bz.items():
                print(f"      {str(k)[:34]:<34} {v:8.1f} ha")
        print(f"    rock (any biozone): {len(sel)} polygons, "
              f"{sel['ha'].sum() if len(sel) else 0:.1f} ha")

        strip = depth_strip(requests, rasterio, gpd, bbox, args.dmin, args.dmax)
        strip_ha = float(strip.area.sum()) / 1e4 if strip is not None else 0.0
        cand_ha = 0.0
        inter = None
        if strip is not None and len(sel):
            inter = gpd.overlay(sel, strip, how="intersection")
            cand_ha = float(inter.area.sum()) / 1e4 if not inter.empty else 0.0
        print(f"    depth strip {strip_ha:.1f} ha  ->  CANDIDATES {cand_ha:.1f} ha")
        if cand_ha == 0.0 and strip is not None and len(sel):
            fixed, fixed_ha = diagnose_zero(requests, rasterio, gpd, np,
                                            bbox, sel, strip)
            if fixed is not None and fixed_ha > 0:
                inter, cand_ha = fixed, fixed_ha
        rows[name] = {"folk_ha": round(float(g['ha'].sum()), 1),
                      "rock_ha": round(float(sel['ha'].sum()) if len(sel) else 0.0, 1),
                      "strip_ha": round(strip_ha, 1),
                      "candidate_ha": round(cand_ha, 1)}
        keep_layers[name] = (sel, strip, inter)

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).T.to_csv(out.with_suffix(".csv"))
    for name, (sel, strip, inter) in keep_layers.items():
        if len(sel):
            sel.to_file(out.with_suffix(".gpkg"), layer=f"{name}_rock", driver="GPKG")
        if strip is not None:
            strip.to_file(out.with_suffix(".gpkg"), layer=f"{name}_strip", driver="GPKG")
        if inter is not None and not inter.empty:
            inter.to_file(out.with_suffix(".gpkg"), layer=f"{name}_candidates",
                          driver="GPKG")
    print(f"\nWrote {out.with_suffix('.csv')}")
    print(f"Wrote {out.with_suffix('.gpkg')}")

    tgt = rows.get(args.aoi, {})
    print("\n" + "-" * 78)
    if tgt.get("candidate_ha", 0) >= 1.0:
        print(f"VERDICT: {tgt['candidate_ha']:.1f} ha of candidates at {args.aoi}.")
        print("  This route works. Next: patch step 2 to build candidates from")
        print("  depth + substrate, keep NPWS as labels only, re-run, and check")
        print("  whether mizen's extrapolation rate falls once shallow cells exist.")
    elif tgt.get("rock_ha", 0) == 0:
        print(f"VERDICT: no rock substrate mapped at {args.aoi} at all.")
        print("  Folk coverage is another survey gap. Report it as unsurveyed.")
    else:
        print(f"VERDICT: rock exists ({tgt.get('rock_ha', 0):.1f} ha) but almost")
        print(f"  none of it sits in {args.dmin:.0f}-{args.dmax:.0f} m.")
        print("  Record the numbers and stop; do not widen the depth band to get")
        print("  a result. The band comes from Dubi & Torum, not from convenience.")
    print("\n  Reminder: Folk polygons are an INTERPRETATION, not a measurement,")
    print("  and unmapped is unsurveyed, never absent.")
    print("-" * 78)
    print(f"\nCommand: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()