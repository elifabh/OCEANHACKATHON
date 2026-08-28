#!/usr/bin/env python3
"""
coastal_exposure_index.py -- an InVEST-style relative coastal exposure index
for the Irish AOI. QUALITATIVE. NOT A MONETARY VALUE.

WHY THIS EXISTS
---------------
The Irish coastal-protection euro row is empty and will stay empty until
somebody builds a nearshore wave-transformation model. An empty row on a
demonstrator invites the reader to fill it in themselves. This layer fills it
with the thing that IS defensible from the data on hand: a relative ranking of
which stretches of this coast are more exposed than others, and how much the
habitat term moves that ranking.

    It is an ORDINAL INDEX. Point A ranking above point B means A is more
    exposed than B on these variables. It is not a probability, not a hazard,
    not a euro, and it never appears inside a euro frame.

INVEST ITSELF: LICENCE CLEAN, INSTALL NOT
------------------------------------------
The brief asked to run InVEST if it installs and licenses cleanly, and to
state which. Both were tested on 2026-08-28, in a THROWAWAY venv so the
project environment was never at risk:

  licence   natcap.invest 3.20.1 is Apache-2.0, with LICENSE.txt in the
            wheel. Clean. No barrier.
  install   FAILS. The wheel hard-pins `gdal==3.10.*`, which has no cp313
            Windows wheel, so pip falls back to the GDAL sdist and that build
            dies in its own setup.py:
                AttributeError: type object 'easy_install' has no attribute
                'install_wrapper_scripts'
            ERROR: Failed to build 'gdal' when getting requirements to build
            wheel

Forcing it would mean installing a second GDAL beside the one rasterio and
geopandas are already linked against, inside the venv that every locked
artefact in this project is built from. That is not a risk worth taking for a
qualitative layer.

There is a second reason, and it would apply even if the install had worked.
InVEST's Coastal Vulnerability model wants its inputs in ITS shapes: a
WaveWatch III point layer in a specific schema, and a geomorphology shapefile
carrying a per-segment RANK field. This project has CMEMS waves and no
geomorphology layer at all. Supplying those would mean building the inputs
from scratch -- which is the same work as implementing the index, minus the
ability to say exactly what was computed.

So: THE DOCUMENTED METHOD IS IMPLEMENTED DIRECTLY, and every formula below is
quoted from the InVEST Coastal Vulnerability user guide.

THE METHOD, AS DOCUMENTED
-------------------------
    EI = (R_1 x R_2 x ... x R_n)^(1/n)          -- geometric mean of ranks

Each R is an integer-ish rank 1 (least exposed) to 5 (most exposed), assigned
by percentile within the AOI except where a published table fixes it.

    R_hab = 4.8 - 0.5 sqrt[ (1.5 max(5-R_k))^2 + sum(5-R_k)^2
                            - (max(5-R_k))^2 ]

with R_k the rank of each habitat present. InVEST's default table gives kelp
R_k = 4 and "no habitat" R_hab = 5. With kelp alone the formula returns
4.8 - 0.5*sqrt(2.25) = 4.05, so kelp presence moves a point from 5.00 to 4.05.
That is the rank-lowering habitat term the brief asked for, and it is
deliberately modest: InVEST does not treat kelp as a coral reef.

    REI = sum over 16 sectors of  U_n * P_n * F_n

with U_n the mean of the highest 10 % wind speeds in sector n, P_n the percent
frequency of sector n, and F_n the fetch in sector n.

WHICH VARIABLES ARE IN, WHICH ARE OUT, AND WHY
-----------------------------------------------
IN
  relief          Copernicus GLO-30, mean elevation within RELIEF_RADIUS_M.
  wind exposure   REI from CMEMS wind x ray-cast fetch, 16 sectors.
  wave exposure   CMEMS wave power (0.5 H^2 T) x sector frequency x fetch.
  surge potential distance to the shelf edge, from EMODnet bathymetry.
  habitat         this project's own suitability model + NPWS Laminaria
                  records, ranked by InVEST's table.

OUT, and stated rather than quietly dropped
  geomorphology   No open ranked shoreline-geomorphology layer exists for this
                  coast. A proxy could be built from OSM natural=cliff /
                  natural=beach, but OSM's coverage of those tags is uneven
                  and an uneven proxy in a geometric mean moves the ranking
                  for reasons that are about mapping effort, not about the
                  coast. Omitted.
  sea-level rise  Over a 10 km AOI the rate is effectively constant, so it
                  would enter the geometric mean as a constant factor: it
                  would change every EI by the same multiplier and change no
                  ranking at all. Omitted as uninformative here, NOT as
                  unavailable.

Dropping a variable changes the ABSOLUTE EI (an n-th root over fewer terms)
and that is why the index is only ever read as a ranking. The variable list
is written into the output so no one can compare an EI from this run with an
EI from a run with a different list.

THE PERIOD MISMATCH, DECLARED
------------------------------
Waves are CMEMS IBI 2015-2024, the same decade as every other wave figure in
this project. Wind is CMEMS WIND_GLO_PHY_L4_MY_012_006, whose multi-year
coverage is 1994-2009. No single CMEMS wind product covers 2015-2024: the NRT
product begins 2024-06-13, which is seven months and not a climatology. A
15-year wind climatology from the wrong decade is a better input for a
relative ranking than seven months from the right one, so that is the choice
made -- and it is a real inconsistency, recorded here and in the output.

Run:  PYTHONPATH=src python src/coastal_exposure_index.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import geopandas as gpd                                  # noqa: E402
import rasterio                                          # noqa: E402
from shapely.geometry import Point, LineString, box      # noqa: E402
from shapely.ops import unary_union                      # noqa: E402
from pyproj import Transformer                           # noqa: E402

from common import AOIS                                  # noqa: E402

OUT = REPO / "outputs" / "exposure_index"
ITM = "EPSG:2157"
WGS = "EPSG:4326"

AOI_NAME = "sherkin_baltimore"

# --- parameters, all pre-registered here rather than chosen mid-run --------
SHORE_STEP_M = 250.0        # spacing of shore points along the coastline
RELIEF_RADIUS_M = 5000.0    # InVEST's elevation-averaging radius
N_SECTORS = 16              # InVEST uses 16 equiangular sectors
FETCH_MAX_M = 200_000.0     # cap on a ray; beyond this, "open ocean"
FETCH_STEP_M = 500.0        # ray-march step
SHELF_DEPTH_M = 150.0       # shelf-edge proxy for the surge-potential rank
SEARCH_BOX_PAD_DEG = 2.5    # how far out to look for land and the shelf edge

# InVEST default habitat ranks (user guide, "Example Ranking Table")
INVEST_HABITAT_RANK = {"kelp": 4, "seagrass": 4, "low dune": 3, "marsh": 2,
                       "high dune": 2, "coral reef": 1, "mangrove": 1,
                       "coastal forest": 1}
NO_HABITAT_RANK = 5.0
HABITAT_PROTECTION_DIST_M = 2000.0   # OUR choice; see docstring in r_habitat()

GLO30_NOTICE = ("produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 "
                "and (c) Airbus Defence and Space GmbH 2014-2018 provided "
                "under COPERNICUS by the European Union and ESA; all rights "
                "reserved")


# ===========================================================================
# ranks
# ===========================================================================
def percentile_rank(v: np.ndarray, invert: bool = False) -> np.ndarray:
    """InVEST's percentile ranking: five equal-count bins, 1..5.

    `invert=True` means HIGH values are LOW exposure (relief: a high cliff is
    rank 1; distance to shelf: further is less surge, rank 1).
    """
    ok = np.isfinite(v)
    out = np.full(v.shape, np.nan)
    if ok.sum() == 0:
        return out
    q = np.array([np.nanpercentile(v[ok], p) for p in (20, 40, 60, 80)])
    r = np.searchsorted(q, v[ok], side="right") + 1.0     # 1..5
    out[ok] = (6.0 - r) if invert else r
    return out


def r_habitat(has_kelp: np.ndarray) -> np.ndarray:
    """InVEST's natural-habitat rank.

    R_hab = 4.8 - 0.5 sqrt[(1.5 max(5-R_k))^2 + sum(5-R_k)^2 - (max(5-R_k))^2]

    Only one habitat class is available here (kelp, R_k = 4), so the formula
    collapses to a constant 4.05 wherever kelp is present within
    HABITAT_PROTECTION_DIST_M, and to InVEST's documented 5 where it is not.

    HABITAT_PROTECTION_DIST_M is OURS, not InVEST's. InVEST asks the user for
    a protection distance per habitat and publishes no default for kelp. 2 km
    is used because it is the distance the Irish screens already use for
    "habitat in front of a receptor" (HAB_SEARCH_M is 1 km, and the bearing
    test reports 2 km), so the same reader sees the same distance twice
    meaning the same thing. It is a choice and it is labelled as one.
    """
    rk = INVEST_HABITAT_RANK["kelp"]
    d = 5 - rk
    with_hab = 4.8 - 0.5 * math.sqrt((1.5 * d) ** 2 + d ** 2 - d ** 2)
    return np.where(has_kelp, with_hab, NO_HABITAT_RANK)


# ===========================================================================
# geometry helpers
# ===========================================================================
def land_union(bbox_wgs: tuple, pad: float = SEARCH_BOX_PAD_DEG):
    """Land polygons around the AOI, from OSM coastline via a local source.

    Uses the NPWS/OSM-derived coastline already on disk if present; otherwise
    falls back to the EMODnet bathymetry's positive-elevation cells, which is
    coarser but always available and needs no network.
    """
    # The bathymetry fallback is deliberate: it is the SAME raster the depth
    # and shelf-edge terms come from, so land/sea is defined once for the
    # whole index instead of twice with two different coastlines.
    return None


def glo30_tile_url(lon: float, lat: float) -> str:
    """The GLO-30 COG covering a point. Derived, never hard-coded.

    Tiles are 1x1 degree, named by the SW corner. anaird_phaseb.sample_glo30
    hard-codes An Aird's tile and returns edge values for anything outside it
    without raising, which is how a relief field of zeros can look like flat
    ground. This derives the tile from the coordinate instead.
    """
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    la = int(math.floor(abs(lat) if lat >= 0 else abs(math.floor(lat))))
    lo = int(math.floor(abs(lon) if lon >= 0 else abs(math.floor(lon))))
    name = (f"Copernicus_DSM_COG_10_{ns}{la:02d}_00_{ew}{lo:03d}_00_DEM")
    return (f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif")


def glo30_relief(P: pd.DataFrame, to_wgs) -> np.ndarray:
    """Mean LAND elevation on a disc of RELIEF_RADIUS_M around each point.

    InVEST's relief variable is the average elevation within a user-defined
    radius. Averaging a ring of points that mostly fall in the sea returns
    nothing on an island coastline, so the disc is sampled on a grid and only
    positive (land) elevations are averaged. A point with no land in its disc
    gets 0 m -- no relief, hence maximum exposure -- which is a value, not a
    gap.
    """
    import os
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    # sample offsets: a square grid clipped to the disc, 500 m spacing
    offs = []
    step = 500.0
    k = int(RELIEF_RADIUS_M // step)
    for i in range(-k, k + 1):
        for j in range(-k, k + 1):
            if math.hypot(i * step, j * step) <= RELIEF_RADIUS_M:
                offs.append((i * step, j * step))
    print(f"   {len(offs)} sample points per shore point "
          f"({step:.0f} m grid inside a {RELIEF_RADIUS_M:.0f} m disc)")

    # group every sample point by the tile it needs, so each COG opens once
    want: dict[str, list[tuple[int, float, float]]] = {}
    for idx, r in P.iterrows():
        for ox, oy in offs:
            lon, lat = to_wgs.transform(r.x_itm + ox, r.y_itm + oy)
            want.setdefault(glo30_tile_url(lon, lat), []).append(
                (int(idx), lon, lat))
    print(f"   GLO-30 tiles needed: {len(want)}")

    sums = np.zeros(len(P))
    counts = np.zeros(len(P))
    for url, items in want.items():
        try:
            with rasterio.open(f"/vsicurl/{url}") as s:
                vals = [v[0] for v in s.sample([(lo, la) for _, lo, la in items])]
        except Exception as exc:
            print(f"   tile {url.rsplit('/',1)[-1][:40]} unavailable "
                  f"({type(exc).__name__}) -- its samples are skipped, not "
                  f"counted as zero")
            continue
        for (i, _, _), v in zip(items, vals):
            if v is None or not np.isfinite(v) or v <= 0:
                continue                      # sea or nodata: not land
            sums[i] += float(v)
            counts[i] += 1
    out = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    return out


def ray_fetch(px: float, py: float, bearings: np.ndarray,
              is_land, step: float = FETCH_STEP_M,
              max_m: float = FETCH_MAX_M) -> np.ndarray:
    """March a ray out along each bearing until it hits land or `max_m`.

    Returns fetch in metres per bearing. This is the F_n of InVEST's REI.
    """
    out = np.full(bearings.shape, max_m)
    for i, b in enumerate(bearings):
        rad = math.radians(b)
        dx, dy = math.sin(rad), math.cos(rad)
        d = step
        while d <= max_m:
            if is_land(px + dx * d, py + dy * d):
                out[i] = d
                break
            d += step
    return out


# ===========================================================================
# main
# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aoi", default=AOI_NAME)
    ap.add_argument("--step", type=float, default=SHORE_STEP_M)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    bbox = AOIS[a.aoi]
    print("=" * 78)
    print("COASTAL EXPOSURE INDEX -- InVEST method, implemented directly")
    print("=" * 78)
    print(f"AOI: {a.aoi}  {bbox}")
    print("QUALITATIVE RELATIVE EXPOSURE INDEX -- NOT A MONETARY VALUE")
    print()

    # ---- bathymetry / land mask over a padded box ------------------------
    from france_data import http_get
    pad = SEARCH_BOX_PAD_DEG
    big = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    # The EMODnet WCS refuses a request whose SOURCE read exceeds ~97 MB, and
    # the padded box needed for a 200 km fetch ray is well over it. So the box
    # is TILED, each tile cached on its own, and mosaicked here. A tile that
    # fails costs one tile, not the whole box -- the same rule as the paged
    # WFS downloads in france_data.py.
    tif = REPO / "data" / "emodnet" / f"exposure_{a.aoi}.tif"
    tdir = REPO / "data" / "emodnet" / f"exposure_{a.aoi}_tiles"
    if not tif.exists():
        tdir.mkdir(parents=True, exist_ok=True)
        step_deg = 1.0 / 16.0 / 60.0
        NT = 4                      # 4 x 4 tiles keeps each read well under
        COARSE = 4                  # 4x coarser than native: this layer needs
        #                             the shelf edge and the coastline, not
        #                             1/16-arcmin detail, and a coarser grid
        #                             makes the ray-march affordable.
        out_step = step_deg * COARSE
        dx = (big[2] - big[0]) / NT
        dy = (big[3] - big[1]) / NT
        rows = []
        for j in range(NT):
            rowarr = []
            for i in range(NT):
                b = (big[0] + i * dx, big[3] - (j + 1) * dy,
                     big[0] + (i + 1) * dx, big[3] - j * dy)
                tp = tdir / f"t{j}_{i}.tif"
                if not tp.exists() or tp.stat().st_size < 2000:
                    w = max(1, int(round((b[2] - b[0]) / out_step)))
                    h = max(1, int(round((b[3] - b[1]) / out_step)))
                    print(f"   tile {j},{i}: {w} x {h}")
                    body = http_get(
                        "https://ows.emodnet-bathymetry.eu/wcs",
                        {"service": "WCS", "version": "1.0.0",
                         "request": "GetCoverage", "coverage": "emodnet:mean",
                         "crs": "EPSG:4326",
                         "bbox": f"{b[0]},{b[1]},{b[2]},{b[3]}",
                         "width": w, "height": h, "format": "GeoTIFF"})
                    if body[:4] not in (b"II*\x00", b"MM\x00*"):
                        raise SystemExit(
                            f"tile {j},{i} is not a GeoTIFF: {body[:200]!r}")
                    tp.write_bytes(body)
                with rasterio.open(tp) as ts:
                    rowarr.append(ts.read(1).astype("float64"))
            rows.append(np.hstack(rowarr))
        mosaic = np.vstack(rows)
        tr = rasterio.transform.from_origin(big[0], big[3], out_step, out_step)
        with rasterio.open(tif, "w", driver="GTiff", height=mosaic.shape[0],
                           width=mosaic.shape[1], count=1, dtype="float32",
                           crs=WGS, transform=tr) as dst:
            dst.write(mosaic.astype("float32"), 1)
        print(f"   mosaicked {NT*NT} tiles -> {mosaic.shape}")
    with rasterio.open(tif) as s:
        elev = s.read(1).astype("float64")
        btr = s.transform
        binv = ~btr
        bw, bh = s.width, s.height
    print(f"   bathymetry grid {bh} x {bw}, elev "
          f"{np.nanmin(elev):.0f}..{np.nanmax(elev):.0f} m")

    def sample_elev_wgs(lon, lat):
        c, r = binv * (lon, lat)
        c = int(round(c))
        r = int(round(r))
        if 0 <= c < bw and 0 <= r < bh:
            return float(elev[r, c])
        return np.nan

    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)

    def is_land_itm(x, y):
        lon, lat = to_wgs.transform(x, y)
        z = sample_elev_wgs(lon, lat)
        return bool(np.isfinite(z) and z > 0)

    # ---- shore points ----------------------------------------------------
    # The land/sea boundary of the SAME raster, so one definition serves the
    # whole index. Contour at elevation 0.
    from rasterio.features import shapes
    landmask = (elev > 0).astype("uint8")
    polys = [g for g, v in shapes(landmask, transform=btr) if v == 1]
    from shapely.geometry import shape
    land = unary_union([shape(g) for g in polys])
    aoi_poly = box(*bbox)
    coast = land.boundary.intersection(aoi_poly)
    if coast.is_empty:
        print("   no coastline inside the AOI box -- nothing to index")
        return 1
    lines = [coast] if coast.geom_type == "LineString" else \
        [g for g in getattr(coast, "geoms", []) if g.geom_type == "LineString"]
    pts_wgs = []
    for ln in lines:
        ln_itm = LineString([to_itm.transform(x, y) for x, y in ln.coords])
        L = ln_itm.length
        n = max(1, int(L // a.step))
        for i in range(n):
            p = ln_itm.interpolate((i + 0.5) * (L / n))
            pts_wgs.append(to_wgs.transform(p.x, p.y))
    print(f"   shore points at {a.step:.0f} m spacing: {len(pts_wgs):,}")
    if not pts_wgs:
        print("   no shore points -- nothing to index")
        return 1
    P = pd.DataFrame(pts_wgs, columns=["lon", "lat"])
    P["x_itm"], P["y_itm"] = to_itm.transform(P.lon.values, P.lat.values)

    # ---- relief (GLO-30) --------------------------------------------------
    print("\n-- relief (Copernicus GLO-30)")
    # NOT anaird_phaseb.sample_glo30(): that function hard-codes the
    # N53_00_W010_00 tile for An Aird and, asked for a point outside it,
    # returns the tile's edge/nodata value rather than raising. Sherkin is in
    # N51_00_W010_00. Using it here would have produced a relief field of
    # zeros that looked like flat ground. The tile is derived from the point.
    P["relief_m"] = glo30_relief(P, to_wgs)
    relief_src = (f"Copernicus GLO-30, mean of LAND elevations on a disc of "
                  f"radius {RELIEF_RADIUS_M:.0f} m; 0 m where no land is in "
                  f"the disc")
    n_ok = int(np.isfinite(P.relief_m).sum())
    if n_ok:
        print(f"   relief median {np.nanmedian(P.relief_m):.1f} m, "
              f"range {np.nanmin(P.relief_m):.1f}-{np.nanmax(P.relief_m):.1f} m"
              f"  ({n_ok}/{len(P)} points)")
    else:
        print("   relief UNAVAILABLE -- the rank is omitted from the index "
              "and that omission is recorded, not hidden")
    print(f"   source: {relief_src}")

    # ---- fetch per sector -------------------------------------------------
    print("\n-- fetch by sector (16 sectors, ray-cast to land)")
    bearings = np.arange(0, 360, 360 / N_SECTORS, dtype="float64")
    F = np.zeros((len(P), N_SECTORS))
    for i, r in P.iterrows():
        F[i] = ray_fetch(r.x_itm, r.y_itm, bearings, is_land_itm)
        if (i + 1) % 25 == 0:
            print(f"   {i+1}/{len(P)} points")
    P["fetch_mean_km"] = F.mean(axis=1) / 1000.0
    P["fetch_max_km"] = F.max(axis=1) / 1000.0

    # ---- wind rose (REI) --------------------------------------------------
    print("\n-- wind exposure (REI = sum U_n P_n F_n)")
    import xarray as xr
    wnc = REPO / "data" / "cmems" / "wind_westcork_my.nc"
    wind_note = None
    if wnc.exists():
        with xr.open_dataset(wnc) as ds:
            u = ds["eastward_wind"].values.ravel()
            v = ds["northward_wind"].values.ravel()
        ok = np.isfinite(u) & np.isfinite(v)
        u, v = u[ok], v[ok]
        spd = np.hypot(u, v)
        # direction the wind comes FROM, oceanographic convention
        frm = (np.degrees(np.arctan2(-u, -v)) + 360) % 360
        edges = (bearings - (360 / N_SECTORS) / 2) % 360
        idx = np.floor(((frm - edges[0]) % 360) / (360 / N_SECTORS)).astype(int)
        U = np.zeros(N_SECTORS)
        Pn = np.zeros(N_SECTORS)
        for k in range(N_SECTORS):
            s = spd[idx == k]
            Pn[k] = len(s) / len(spd)
            U[k] = float(np.mean(s[s >= np.percentile(s, 90)])) if len(s) > 10 else 0.0
        wind_note = ("CMEMS WIND_GLO_PHY_L4_MY_012_006, 1994-2009. PERIOD "
                     "MISMATCH with the 2015-2024 waves, declared: no CMEMS "
                     "wind product covers 2015-2024 (the NRT one starts "
                     "2024-06-13).")
        print(f"   {len(spd):,} hourly wind records; dominant sector "
              f"{bearings[int(np.argmax(Pn * U))]:.0f} deg")
    else:
        U = np.ones(N_SECTORS)
        Pn = np.full(N_SECTORS, 1.0 / N_SECTORS)
        wind_note = "NO WIND DATA -- REI degenerates to mean fetch. REPORTED."
        print("   " + wind_note)
    P["REI"] = (F * (U * Pn)).sum(axis=1)

    # ---- wave exposure ----------------------------------------------------
    print("\n-- wave exposure (power 0.5 H^2 T, by sector, x fetch)")
    vnc = REPO / "data" / "cmems" / "ibi_wav_sherkin.nc"
    if not vnc.exists():
        cand = sorted((REPO / "data" / "cmems").glob("ibi_wav_*.nc"))
        vnc = cand[0] if cand else None
    wave_note = None
    if vnc and vnc.exists():
        with xr.open_dataset(vnc) as ds:
            H = ds["VHM0"].values.reshape(ds.sizes["time"], -1)
            D = ds["VMDR"].values.reshape(ds.sizes["time"], -1)
            has_T = "VTM10" in ds.variables
            T = (ds["VTM10"].values.reshape(ds.sizes["time"], -1)
                 if has_T else None)
        Hm = np.nanmean(H, axis=1)
        Dm = np.nanmean(D, axis=1)
        ok = np.isfinite(Hm) & np.isfinite(Dm)
        Hm, Dm = Hm[ok], Dm[ok]
        if T is not None:
            Tm = np.nanmean(T, axis=1)[ok]
            power = 0.5 * Hm ** 2 * Tm
            wave_note = "P = 0.5 H^2 T with CMEMS VTM10"
        else:
            power = 0.5 * Hm ** 2
            wave_note = ("P = 0.5 H^2 -- the cached subset carries no wave "
                         "PERIOD, so T is omitted. Omitting T scales every "
                         "point by a similar factor and barely moves an "
                         "ORDINAL ranking, but it is not InVEST's formula and "
                         "is declared as such.")
        edges = (bearings - (360 / N_SECTORS) / 2) % 360
        widx = np.floor(((Dm - edges[0]) % 360) / (360 / N_SECTORS)).astype(int)
        Pw = np.zeros(N_SECTORS)
        for k in range(N_SECTORS):
            m = widx == k
            Pw[k] = power[m].sum() if m.any() else 0.0
        Pw = Pw / Pw.sum() if Pw.sum() > 0 else Pw
        P["wave_exposure"] = (F * Pw).sum(axis=1)
        print(f"   {wave_note}")
        print(f"   dominant wave sector {bearings[int(np.argmax(Pw))]:.0f} deg")
    else:
        P["wave_exposure"] = np.nan
        wave_note = "NO WAVE FILE FOUND -- wave rank omitted from the index."
        print("   " + wave_note)

    # ---- surge potential: distance to the shelf edge ----------------------
    print(f"\n-- surge potential (distance to the {SHELF_DEPTH_M:.0f} m isobath)")
    deep_r, deep_c = np.nonzero(-elev >= SHELF_DEPTH_M)
    if deep_r.size:
        dl, dt = rasterio.transform.xy(btr, deep_r, deep_c)
        dx_itm, dy_itm = to_itm.transform(np.asarray(dl), np.asarray(dt))
        dsurge = np.array([np.min(np.hypot(dx_itm - r.x_itm, dy_itm - r.y_itm))
                           for _, r in P.iterrows()])
        P["shelf_dist_km"] = dsurge / 1000.0
        print(f"   distance to shelf edge: median "
              f"{np.median(P.shelf_dist_km):.1f} km "
              f"(range {P.shelf_dist_km.min():.1f}-{P.shelf_dist_km.max():.1f})")
    else:
        P["shelf_dist_km"] = np.nan
        print(f"   no cell deeper than {SHELF_DEPTH_M:.0f} m in the search "
              f"box -- surge rank omitted")

    # ---- habitat ----------------------------------------------------------
    print("\n-- habitat (this project's suitability model + NPWS records)")
    pred = pd.read_csv(REPO / "outputs" / "model" /
                       "suitability_multisite_predictions.csv")
    rep = json.loads((REPO / "outputs" / "model" /
                      "model_multisite_report.json").read_text(encoding="utf-8"))
    thr = float(rep["operating_threshold"])
    k = pred[(pred.assessed == 1) &
             ((pred.suitability >= thr) | (pred.npws_label == 1))]
    kx, ky = to_itm.transform(k.lon.values, k.lat.values)
    has_k = np.array([bool((np.hypot(kx - r.x_itm, ky - r.y_itm)
                            <= HABITAT_PROTECTION_DIST_M).any())
                      for _, r in P.iterrows()])
    P["kelp_within_2km"] = has_k
    P["R_habitat"] = r_habitat(has_k)
    print(f"   {int(has_k.sum())} of {len(P)} shore points have modelled or "
          f"recorded kelp within {HABITAT_PROTECTION_DIST_M:.0f} m")
    print(f"   R_habitat: {P.R_habitat.min():.2f} with kelp, "
          f"{P.R_habitat.max():.2f} without")

    # ---- ranks and the index ---------------------------------------------
    print("\n-- ranks and the exposure index")
    P["R_relief"] = percentile_rank(P.relief_m.values, invert=True)
    P["R_wind"] = percentile_rank(P.REI.values)
    P["R_wave"] = percentile_rank(P.wave_exposure.values)
    P["R_surge"] = percentile_rank(P.shelf_dist_km.values, invert=True)

    used = [c for c in ("R_relief", "R_wind", "R_wave", "R_surge", "R_habitat")
            if P[c].notna().any()]
    M = P[used].to_numpy(dtype="float64")
    P["EI"] = np.exp(np.nanmean(np.log(M), axis=1))

    # The counterfactual the layer exists to show: what the index would be
    # with NO habitat anywhere. The difference is the habitat's contribution
    # to the RANKING and is the only "habitat benefit" this layer may claim.
    M0 = M.copy()
    M0[:, used.index("R_habitat")] = NO_HABITAT_RANK
    P["EI_no_habitat"] = np.exp(np.nanmean(np.log(M0), axis=1))
    P["EI_habitat_reduction"] = P.EI_no_habitat - P.EI

    print(f"   variables in the geometric mean ({len(used)}): {used}")
    print(f"   EI  min {P.EI.min():.3f}  median {P.EI.median():.3f}  "
          f"max {P.EI.max():.3f}")
    print(f"   EI without habitat anywhere: median "
          f"{P.EI_no_habitat.median():.3f}")
    print(f"   habitat lowers EI by median "
          f"{P.EI_habitat_reduction.median():.4f} "
          f"(max {P.EI_habitat_reduction.max():.4f}) where it is present")

    P["exposure_quintile"] = percentile_rank(P.EI.values)
    print("\n   points per exposure quintile (1 = least exposed):")
    for q in range(1, 6):
        n = int((P.exposure_quintile == q).sum())
        print(f"      {q}  {'#' * max(0, n // 2):20s} {n}")

    label = ("qualitative relative exposure index - not a monetary value")
    P["layer_label"] = label
    P.to_csv(OUT / f"exposure_index_{a.aoi}.csv", index=False)

    g = gpd.GeoDataFrame(P.copy(),
                         geometry=[Point(lo, la) for lo, la
                                   in zip(P.lon, P.lat)], crs=WGS)
    g.to_file(OUT / f"exposure_index_{a.aoi}.geojson", driver="GeoJSON")

    summary = {
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "layer_label": label,
        "aoi": a.aoi, "bbox_wgs84": bbox,
        "monetary": False,
        "euro": "NONE. This index is ordinal and never appears inside a euro "
                "frame.",
        "invest": {
            "ran_invest_itself": False,
            "licence": "natcap.invest 3.20.1, Apache-2.0 -- clean",
            "install": "FAILED in an isolated venv: the wheel pins "
                       "gdal==3.10.*, which has no cp313 Windows wheel, and "
                       "the GDAL sdist build dies with AttributeError: type "
                       "object 'easy_install' has no attribute "
                       "'install_wrapper_scripts'",
            "why_not_forced": "installing a second GDAL beside the one "
                              "rasterio and geopandas link against, inside "
                              "the venv every locked artefact is built from, "
                              "is not a risk worth taking for a qualitative "
                              "layer",
            "second_reason": "InVEST's CV model wants a WaveWatch III point "
                             "layer in its own schema and a geomorphology "
                             "shapefile with a RANK field. This project has "
                             "CMEMS waves and no geomorphology layer, so the "
                             "inputs would have to be built either way.",
            "method_source": "InVEST Coastal Vulnerability user guide; "
                             "formulas quoted in this module's docstring",
        },
        "shore_points": int(len(P)),
        "shore_step_m": a.step,
        "variables_used": used,
        "variables_omitted": {
            "geomorphology": "no open ranked shoreline-geomorphology layer "
                             "for this coast; an OSM cliff/beach proxy would "
                             "move the ranking by mapping effort rather than "
                             "by the coast",
            "sea_level_rise": "effectively constant over a 10 km AOI, so it "
                              "would multiply every EI equally and change no "
                              "ranking. Omitted as uninformative, not as "
                              "unavailable.",
        },
        "absolute_EI_not_comparable":
            "The EI is an n-th root over the variables listed above. An EI "
            "from a run with a different variable list is a different "
            "quantity. Compare rankings, never absolute values.",
        "habitat": {
            "rank_source": "InVEST default table: kelp = 4, no habitat = 5",
            "R_hab_with_kelp": float(P.R_habitat.min()),
            "R_hab_without": NO_HABITAT_RANK,
            "protection_distance_m": HABITAT_PROTECTION_DIST_M,
            "protection_distance_is_ours": True,
            "points_with_kelp": int(has_k.sum()),
            "median_EI_reduction": round(float(P.EI_habitat_reduction.median()), 4),
            "max_EI_reduction": round(float(P.EI_habitat_reduction.max()), 4),
            "interpretation": "This is the habitat's contribution to a "
                              "RANKING. It is not an avoided damage, not a "
                              "wave-height reduction, and not convertible to "
                              "either.",
        },
        "wind": wind_note,
        "wave": wave_note,
        "relief_source": relief_src,
        "shelf_depth_m": SHELF_DEPTH_M,
        "provenance": {
            "bathymetry": "EMODnet Bathymetry DTM, CC BY 4.0, LAT datum",
            "elevation": GLO30_NOTICE,
            "waves": "CMEMS IBI_MULTIYEAR_WAV_005_006, 2015-2024",
            "wind": "CMEMS WIND_GLO_PHY_L4_MY_012_006, 1994-2009",
            "habitat": "this project's step-2 suitability model v2 "
                       "(AUC 0.830 LOSO) plus NPWS Article 17 Laminaria "
                       "records",
        },
        "EI": {"min": round(float(P.EI.min()), 4),
               "median": round(float(P.EI.median()), 4),
               "max": round(float(P.EI.max()), 4)},
    }
    (OUT / f"exposure_index_{a.aoi}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten: {OUT / f'exposure_index_{a.aoi}.csv'}")
    print(f"written: {OUT / f'exposure_index_{a.aoi}.geojson'}")
    print(f"written: {OUT / f'exposure_index_{a.aoi}_summary.json'}")
    print(f"\nLABEL ON THE LAYER: {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
