#!/usr/bin/env python3
"""
step3b2_flood_check.py — step 3B2a, the go / no-go check.

QUESTION THIS ANSWERS
---------------------
After the exposure filter, 7 cells (1.75 ha) survive on Sherkin's south coast
and at the mouth of Baltimore Harbour. Before building any receptor pipeline,
one question decides whether there is anything to value at all:

    Does the OPW coastal flood extent reach the shoreline behind those cells?

If no mapped coastal floodplain lies behind them, the avoided-damage value via
the flood pathway is zero. That is a legitimate result and it costs 15 minutes
to establish, instead of hours spent building a receptor pipeline for an empty
floodplain.

WHAT IT DOES
------------
1. Downloads (or reads) the OPW National Coastal Flood Extents 2021, Current
   Scenario. National coverage, EPSG:2157 (ITM), SHP.
2. Selects the surviving cells from cluster_fetch_check_cells.csv.
3. Reprojects them to EPSG:2157 and buffers by a search radius.
4. Reads only the flood polygons inside that box (bbox filter — the national
   file is large; never read it whole).
5. Reports, per return period: polygon count, area in hectares, and the
   distance from the kelp cells to the nearest floodplain.
6. Writes a GeoPackage for inspection in QGIS.

WHAT THIS RESULT DOES AND DOES NOT MEAN
---------------------------------------
The OPW National Coastal Flood Hazard Maps model still water level from tide
and storm surge. Per OPW's own metadata they do NOT include wave overtopping,
and flood defences are not taken into account, so the extents are a worst case
in that respect. Our valuation mechanism is wave overtopping.

Therefore this layer is used ONLY as a screen: it tells us which stretches of
coast have any low-lying land at all behind them. It must NOT be presented as
"the area our kelp bed protects", and we must never claim our attenuation
figure changes an OPW extent line. Say this on the slide.

LICENCE — UNRESOLVED, READ BEFORE PUBLISHING
--------------------------------------------
data.gov.ie labels this dataset CC BY-NC-ND 4.0: non-commercial, no
derivatives. It is simultaneously tagged a High Value Dataset under EU
Implementing Regulation 2023/138, which requires open terms. Those two look to
be in tension. This script does not resolve it. Before any of this appears in a
published prototype, ask flood_data@opw.ie in writing. Same open-item class as
the Burrows fetch licence.

Usage:
    python src/step3b2_flood_check.py --download
    python src/step3b2_flood_check.py --zip data/opw/ncfhm_itm_ext_c_c_1000yr_200yr_10yr.zip
    python src/step3b2_flood_check.py --download --radius-m 3000
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

# Verified 2026-08-10 from
# https://data.gov.ie/dataset/national-coastal-flood-extents-2021-current-scenario
OPW_URLS = {
    "long": (
        "https://s3.eu-west-1.amazonaws.com/catalogue.floodinfo.opw/"
        "ncfhm_itm_ext_c_c_1000yr_200yr_10yr.zip"
    ),
    "short": (
        "https://s3.eu-west-1.amazonaws.com/catalogue.floodinfo.opw/"
        "ncfhm_itm_ext_c_c_2yr_5yr_20yr_50yr_100yr.zip"
    ),
}

ITM = "EPSG:2157"
WGS84 = "EPSG:4326"
CELL_HA = 0.25

BANNER = """
------------------------------------------------------------------------------
OPW National Coastal Flood Extents 2021 — Current Scenario
  Licence   CC BY-NC-ND 4.0  (non-commercial, NO DERIVATIVES — unresolved)
  Excludes  wave overtopping, fluvial, pluvial, sewers
  Excludes  flood defences (extents are a worst case in that respect)
  Scale     strategic only; not valid for individual properties
  Erratum   2024-10-10: 2-year and 100-year shapefiles had been swapped.
            If your download predates that, re-download.
------------------------------------------------------------------------------
"""


def need(module: str, pip_name: str | None = None):
    try:
        return __import__(module)
    except ImportError:
        sys.exit(
            f"ERROR: {module} is not installed.\n"
            f"  pip install {pip_name or module}\n"
            f"  Then add it to DEPENDENCIES.md with version and licence."
        )


def download(url: str, dest: Path) -> Path:
    requests = need("requests")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  already present: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest
    print(f"  downloading {url}")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        got = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"\r    {got / 1e6:6.1f} / {total / 1e6:.1f} MB", end="")
    print(f"\n  saved {dest}")
    return dest


def unzip(zip_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    shps = sorted(out_dir.rglob("*.shp"))
    if not shps:
        sys.exit(f"ERROR: no .shp inside {zip_path}")
    return shps


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cells", default="outputs/model/cluster_fetch_check_cells.csv")
    ap.add_argument("--groups", default="C02,C04",
                    help="cluster labels that survived the exposure filter")
    ap.add_argument("--zip", default=None, help="already-downloaded OPW zip")
    ap.add_argument("--download", action="store_true", help="fetch the OPW zip")
    ap.add_argument("--which", default="long", choices=["long", "short"],
                    help="long = 10/200/1000 yr, short = 2/5/20/50/100 yr")
    ap.add_argument("--data-dir", default="data/opw")
    ap.add_argument("--radius-m", type=float, default=2000.0,
                    help="search radius around the kelp cells, metres")
    ap.add_argument("--out", default="outputs/valuation/step3b2_flood_check")
    args = ap.parse_args()

    gpd = need("geopandas")
    from shapely.geometry import Point

    print(BANNER)

    # ---------------- cells ------------------------------------------------
    cells_path = Path(args.cells)
    if not cells_path.exists():
        sys.exit(f"ERROR: {cells_path} not found. Run cluster_fetch_check.py first.")

    df = pd.read_csv(cells_path)
    if "group" not in df.columns:
        sys.exit(f"ERROR: no 'group' column in {cells_path}.")

    groups = [g.strip() for g in args.groups.split(",")]
    sel = df[(df["group"].isin(groups)) & (df["in_valid_depth"] == 1)]
    if sel.empty:
        sys.exit(
            f"ERROR: no cells matched groups={groups}.\n"
            f"  groups present: {sorted(df['group'].unique())}"
        )

    print("SURVIVING CELLS")
    print(f"  groups            {groups}")
    print(f"  cells             {len(sel)}      (expected 7)")
    print(f"  area              {len(sel) * CELL_HA:.2f} ha   (expected 1.75 ha)")
    print(f"  depth             {sel['depth_m'].min():.2f} – {sel['depth_m'].max():.2f} m")
    print(f"  H_red NE-SW med   {sel['H_red_NE-SW'].median() * 100:.2f} %")
    if len(sel) != 7:
        print("  >> not 7 cells. Check --groups against your clustering run.")
    print()

    pts = gpd.GeoDataFrame(
        sel.copy(),
        geometry=[Point(xy) for xy in zip(sel["lon"], sel["lat"])],
        crs=WGS84,
    ).to_crs(ITM)

    buf = pts.buffer(args.radius_m)
    # union_all() is geopandas >= 1.0; unary_union is the older name.
    search = buf.union_all() if hasattr(buf, "union_all") else buf.unary_union
    minx, miny, maxx, maxy = search.bounds
    print(f"SEARCH AREA  {args.radius_m:.0f} m around the cells")
    print(f"  ITM bbox          {minx:.0f} {miny:.0f} {maxx:.0f} {maxy:.0f}")
    print()

    # ---------------- OPW data --------------------------------------------
    data_dir = Path(args.data_dir)
    if args.zip:
        zip_path = Path(args.zip)
        if not zip_path.exists():
            sys.exit(f"ERROR: {zip_path} not found.")
    elif args.download:
        url = OPW_URLS[args.which]
        zip_path = download(url, data_dir / url.rsplit("/", 1)[-1])
    else:
        sys.exit("ERROR: pass --download or --zip PATH.")

    shps = unzip(zip_path, data_dir / zip_path.stem)
    print(f"\nOPW SHAPEFILES  {len(shps)} found")
    for s in shps:
        print(f"  {s.name}")
    print()

    # ---------------- intersect -------------------------------------------
    print("=" * 78)
    print("RESULT")
    print("=" * 78)
    rows, keep = [], []
    for shp in shps:
        # bbox filter: never read the national file whole
        try:
            g = gpd.read_file(shp, bbox=(minx, miny, maxx, maxy))
        except Exception as e:  # noqa: BLE001
            print(f"  {shp.stem:<24} READ FAILED: {e}")
            continue

        if g.crs is None:
            print(f"  {shp.stem:<24} WARNING: no CRS on file; assuming {ITM}")
            g = g.set_crs(ITM)
        g = g.to_crs(ITM)

        if g.empty:
            print(f"  {shp.stem:<24} 0 polygons in the search box  -> NO FLOODPLAIN")
            rows.append({"layer": shp.stem, "n_polygons": 0, "area_ha": 0.0,
                         "min_dist_m": None})
            continue

        clipped = gpd.clip(g, search)
        area_ha = float(clipped.area.sum()) / 10_000.0
        dmin = float(pts.geometry.apply(lambda p: g.distance(p).min()).min())
        print(f"  {shp.stem:<24} {len(clipped):4d} polygons | {area_ha:8.2f} ha "
              f"| nearest {dmin:7.0f} m from a kelp cell")
        rows.append({"layer": shp.stem, "n_polygons": len(clipped),
                     "area_ha": round(area_ha, 2), "min_dist_m": round(dmin, 1)})
        if not clipped.empty:
            clipped = clipped.copy()
            clipped["layer"] = shp.stem
            keep.append(clipped)

    # ---------------- verdict ---------------------------------------------
    total = sum(r["area_ha"] for r in rows)
    print()
    print("-" * 78)
    if total == 0:
        print("VERDICT: no OPW coastal floodplain within "
              f"{args.radius_m:.0f} m of the surviving cells.")
        print("  The flood/overtopping value for this patch is ZERO, not 'not assessed'.")
        print("  Zero is a real, defensible answer. Report it as zero and say why.")
        print("  Optional check: widen --radius-m, or try --which short (2-100 yr).")
    else:
        print(f"VERDICT: {total:.2f} ha of mapped coastal floodplain found.")
        print("  Proceed to step 3B2b: count receptors inside it (OSM / Microsoft")
        print("  building footprints, CSO Small Area dwellings). GeoHive will not")
        print("  supply building footprints — Prime2 is not open.")
    print("-" * 78)

    # ---------------- write ------------------------------------------------
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out.with_suffix(".csv"), index=False)
    print(f"\nWrote {out.with_suffix('.csv')}")

    if keep:
        import pandas as _pd
        allpoly = gpd.GeoDataFrame(_pd.concat(keep, ignore_index=True), crs=ITM)
        allpoly.to_file(out.with_suffix(".gpkg"), layer="flood_extent", driver="GPKG")
        pts.to_file(out.with_suffix(".gpkg"), layer="kelp_cells", driver="GPKG")
        gpd.GeoDataFrame(geometry=[search], crs=ITM).to_file(
            out.with_suffix(".gpkg"), layer="search_area", driver="GPKG")
        print(f"Wrote {out.with_suffix('.gpkg')}  (open in QGIS)")
    else:
        pts.to_file(out.with_suffix(".gpkg"), layer="kelp_cells", driver="GPKG")
        gpd.GeoDataFrame(geometry=[search], crs=ITM).to_file(
            out.with_suffix(".gpkg"), layer="search_area", driver="GPKG")
        print(f"Wrote {out.with_suffix('.gpkg')}  (cells and search area only)")

    print(f"\nCommand: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()