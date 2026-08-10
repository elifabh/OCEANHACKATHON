#!/usr/bin/env python3
"""
emodnet_provenance.py — step C, v3. Replaces emodnet_shallow_check.py.

WHAT WENT WRONG IN v1 AND v2, SO IT IS NOT REPEATED
---------------------------------------------------
v1 read dataset names that did not exist, defaulted every patch to "UNKNOWN",
and then counted UNKNOWN as real because it contained no GEBCO-like keyword.
Absence of evidence was reported as evidence.

v2 fixed the keyword logic but sent the WFS request WITHOUT a bbox, so it
returned the first 2000 source patches from anywhere in Europe and analysed
those. The Mizen answer was never actually about Mizen.

Both failures share one cause: asking a keyword question when the real question
is spatial. This version asks the spatial one.

THE ACTUAL TEST
---------------
EMODnet's source-reference layer is a non-overlapping patchwork of the real
datasets that went into the DTM. Areas with no observations are completed from
GEBCO 2024. Those completed areas are therefore expected to fall in the HOLES
of the patchwork, not inside a patch.

So: take the centre of every 4-10 m DTM cell at Mizen and ask whether it lies
inside a source patch.

    inside a patch  -> depth traces to a logged survey or composite DTM
    in a hole       -> depth is interpolated fill, and unusable for us

The v2 attribute dump showed the schema carries no dataset name at all:
colour, date_start, date_end, device, edmo_id, identifier, metadata_url,
release, type. `type` is the useful one — CDI means a SeaDataNet Common Data
Index survey entry. `metadata_url` resolves each patch to its own record, which
is how a claim about provenance gets checked by hand rather than asserted.

ALSO CHECKED
------------
emodnet:hr_bathymetry_area — the high-resolution coastal DTMs. If Mizen falls
inside one, the 115 m product is not the best available and we should go for the
HR DTM instead.

WFS AXIS ORDER
--------------
WFS 1.1.0 and 2.0.0 with EPSG:4326 are widely inconsistent about whether a bbox
is lon,lat or lat,lon. Rather than assume, this script sends the request, checks
whether what came back actually intersects the requested box, and retries with
the axes swapped if it does not.

Usage:
    python src/emodnet_provenance.py --aoi mizen_outer
    python src/emodnet_provenance.py --bbox -9.86 51.44 -9.74 51.52
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

WCS = "https://ows.emodnet-bathymetry.eu/wcs"
WFS = "https://ows.emodnet-bathymetry.eu/wfs"
COVERAGE = "emodnet:mean"
SOURCE_LAYER = "emodnet:source_references"
HR_LAYER = "emodnet:hr_bathymetry_area"
DEG_PER_CELL = 1.0 / 16.0 / 60.0
CELL_HA = 115.0 * 115.0 / 10_000.0


def need(mod: str, pip_name: str | None = None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"ERROR: {mod} not installed.  pip install {pip_name or mod}\n"
                 f"  Record it in DEPENDENCIES.md with version and licence.")


def get_aoi_bbox(name: str):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path.cwd()))
    try:
        import common  # type: ignore
    except Exception:
        try:
            from src import common  # type: ignore
        except Exception:
            return None
    for attr in ("AOIS", "AOI", "AOI_BBOX", "AOIS_BBOX"):
        d = getattr(common, attr, None)
        if isinstance(d, dict) and name in d:
            v = d[name]
            if isinstance(v, dict):
                for k in ("bbox", "BBOX", "extent"):
                    if k in v:
                        v = v[k]
                        break
            if isinstance(v, (list, tuple)) and len(v) == 4:
                return tuple(float(x) for x in v)
    return None


# ---------------------------------------------------------------------------
def fetch_depth(requests, bbox, out: Path) -> Path:
    w, s, e, n = bbox
    r = requests.get(WCS, timeout=180, params={
        "service": "WCS", "version": "1.0.0", "request": "GetCoverage",
        "coverage": COVERAGE, "crs": "EPSG:4326", "bbox": f"{w},{s},{e},{n}",
        "resx": DEG_PER_CELL, "resy": DEG_PER_CELL, "format": "GeoTIFF"})
    if r.status_code != 200 or r.content[:2] not in (b"II", b"MM"):
        sys.exit(f"ERROR: WCS returned {r.status_code}: {r.content[:200]!r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    print(f"  depth grid: {out}  ({len(r.content)/1e6:.1f} MB)")
    return out


def wfs_geojson(requests, gpd, layer: str, bbox, page: int = 5000):
    """Fetch a layer for the bbox, verifying axis order against the result."""
    w, s, e, n = bbox
    orders = [("lon,lat", f"{w},{s},{e},{n},EPSG:4326"),
              ("lat,lon", f"{s},{w},{n},{e},EPSG:4326")]
    for label, bstr in orders:
        feats, start = [], 0
        while True:
            p = {"service": "WFS", "version": "1.1.0", "request": "GetFeature",
                 "typename": layer, "outputFormat": "application/json",
                 "srsname": "EPSG:4326", "bbox": bstr,
                 "maxFeatures": page, "startIndex": start}
            try:
                r = requests.get(WFS, params=p, timeout=240)
            except Exception as ex:  # noqa: BLE001
                print(f"    {layer} [{label}]: request failed ({ex})")
                break
            body = r.text.lstrip()
            if r.status_code != 200 or not body.startswith("{"):
                print(f"    {layer} [{label}]: HTTP {r.status_code} -> {body[:160]}")
                break
            got = r.json().get("features", [])
            feats.extend(got)
            if len(got) < page:
                break
            start += page
            if start > 50_000:
                print("    stopping at 50k features")
                break
        if not feats:
            continue
        g = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
        g = g[g.geometry.notna() & ~g.geometry.is_empty]
        from shapely.geometry import box as shbox
        hit = int(g.intersects(shbox(w, s, e, n)).sum())
        print(f"    {layer} [{label}]: {len(g)} features, {hit} intersect the AOI")
        if hit > 0:
            return g[g.intersects(shbox(w, s, e, n))].copy()
        print(f"    -> nothing intersects; the server used the other axis order")
    return None


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", default="mizen_outer")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--dmin", type=float, default=4.0)
    ap.add_argument("--dmax", type=float, default=10.0)
    ap.add_argument("--out-dir", default="data/emodnet")
    ap.add_argument("--out", default="outputs/model/emodnet_provenance")
    args = ap.parse_args()

    requests = need("requests")
    rasterio = need("rasterio")
    gpd = need("geopandas")
    import pandas as pd
    from shapely.geometry import Point

    bbox = tuple(args.bbox) if args.bbox else get_aoi_bbox(args.aoi)
    if bbox is None:
        sys.exit(f"ERROR: AOI '{args.aoi}' not found in src/common.py. Use --bbox.")
    w, s, e, n = bbox
    print("=" * 78)
    print(f"EMODnet PROVENANCE — {args.aoi}")
    print("=" * 78)
    print(f"  bbox  {w:.4f} {s:.4f} {e:.4f} {n:.4f}   depth band "
          f"{args.dmin:.0f}-{args.dmax:.0f} m\n")

    tif = fetch_depth(requests, bbox, Path(args.out_dir) / f"{args.aoi}_mean.tif")

    with rasterio.open(tif) as src:
        z = np.asarray(src.read(1), dtype="float64")
        if src.nodata is not None:
            z[z == src.nodata] = np.nan
        tr = src.transform
    depth = -z
    depth[depth <= 0] = np.nan

    rows, cols = np.where((depth >= args.dmin) & (depth < args.dmax))
    if len(rows) == 0:
        sys.exit(f"\nNo {args.dmin:.0f}-{args.dmax:.0f} m cells here. C closes for EMODnet.")
    xs, ys = rasterio.transform.xy(tr, rows, cols)
    cells = gpd.GeoDataFrame(
        {"depth_m": depth[rows, cols].round(2)},
        geometry=[Point(a, b) for a, b in zip(xs, ys)], crs="EPSG:4326")
    print(f"\n  {len(cells)} cells in the {args.dmin:.0f}-{args.dmax:.0f} m band "
          f"({len(cells) * CELL_HA:.1f} ha)")

    print("\n" + "=" * 78)
    print("SOURCE PATCHWORK  (does each shallow cell sit inside a real patch?)")
    print("=" * 78)
    srcs = wfs_geojson(requests, gpd, SOURCE_LAYER, bbox)
    if srcs is None or srcs.empty:
        print("\n  No source patches over this AOI at all.")
        print("  Every shallow depth here is interpolated fill. Do not use it.")
        sys.exit(0)

    joined = gpd.sjoin(cells, srcs, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    inside = joined["index_right"].notna()
    n_in, n_out = int(inside.sum()), int((~inside).sum())
    print(f"\n  inside a source patch : {n_in:5d} cells  {n_in * CELL_HA:8.1f} ha")
    print(f"  in a hole (fill)      : {n_out:5d} cells  {n_out * CELL_HA:8.1f} ha")

    if n_in:
        cols_keep = [c for c in ("type", "device", "edmo_id", "date_start",
                                 "release", "metadata_url") if c in joined.columns]
        grp = (joined[inside].groupby(cols_keep[:-1] if "metadata_url" in cols_keep
                                      else cols_keep, dropna=False)
               .agg(cells=("depth_m", "size"),
                    example_url=("metadata_url", "first") if "metadata_url" in joined else ("depth_m", "size"))
               .reset_index().sort_values("cells", ascending=False))
        print("\n  Patches actually under the shallow cells:")
        print(grp.head(12).to_string(index=False))
        print("\n  Open one metadata_url by hand before trusting any of this.")

    print("\n" + "=" * 78)
    print("HIGH-RESOLUTION COVERAGE  (is something better than 115 m available?)")
    print("=" * 78)
    hr = wfs_geojson(requests, gpd, HR_LAYER, bbox)
    if hr is None or hr.empty:
        print("  No HR DTM covers this AOI. 115 m is the best EMODnet offers here.")
    else:
        print(f"  {len(hr)} HR area(s) overlap the AOI:")
        show = [c for c in hr.columns if c != "geometry"][:6]
        print(hr[show].head(10).to_string(index=False))
        print("  Get the HR DTM instead of the 115 m product.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joined.assign(has_source=inside).to_file(out.with_suffix(".gpkg"),
                                             layer="shallow_cells", driver="GPKG")
    srcs.to_file(out.with_suffix(".gpkg"), layer="source_patches", driver="GPKG")
    print(f"\nWrote {out.with_suffix('.gpkg')}")

    frac = n_in / max(len(cells), 1)
    print("\n" + "-" * 78)
    if frac >= 0.9:
        print(f"VERDICT: {frac:.0%} of the shallow band traces to real source patches.")
        print("  C is alive. Next: check whether an HR DTM exists, decide 115 m vs")
        print("  Sentinel-2 SDB, then re-run the depth gate at mizen.")
    elif frac >= 0.3:
        print(f"VERDICT: MIXED — only {frac:.0%} traces to real patches.")
        print("  Usable, but only the covered cells. Carry has_source through the")
        print("  pipeline and mark the rest 'not assessed', never zero.")
    else:
        print(f"VERDICT: only {frac:.0%} traces to real data. The shallow band at")
        print("  Mizen is mostly interpolation. EMODnet does not solve this.")
        print("  Go to Sentinel-2 SDB (Casal et al. 2020) or close C.")
    print("-" * 78)
    print(f"\nCommand: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()