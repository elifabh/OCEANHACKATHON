#!/usr/bin/env python3
"""
france_chain.py -- the locked Sherkin coastal-protection chain, run end to end
on the Iroise Sea site with that site's own data.

WHAT THIS IS FOR
----------------
Every Irish site returned "not computable" for coastal protection, and always
for the same physical reason: the only published L. hyperborea attenuation
coefficients (Dubi & Torum 1996; Mork 1996; Lovas & Torum 2001) were measured
at 4-10 m depth, and the Irish beds sit at 0.8 m or at 12-17 m. This site was
identified because its bed's core standing stock sits at 7-15 m, so the
coefficient band falls INSIDE the forest rather than outside it.

The point of the exercise is not to obtain a euro. It is to run the same chain
with the depth constraint satisfied and report honestly what comes out --
including "still not computable", if that is the answer.

THE METHOD IS IMPORTED, NOT RE-TYPED
------------------------------------
`AXES`, `interp_axes`, `per_axis_cell_table`, `headline`, `k_dubi_torum`,
`saturation_check` and `reproduce_sherkin` are imported from
`src/anaird_phaseb.py`, the module that reproduced the locked 7.9 % / 15.2 %
to the digit before it was allowed to compute An Aird's numbers. The screen
gates (`SHORE_DIST_M`, `HAB_SEARCH_M`) and the bearing parameters
(`BEARING_HALF_WIDTHS`, `BEARING_RADII_M`, `BEARING_PRIMARY`) are imported
from the screens that pre-registered them. Nothing about the method is
re-decided here; only the DATA is this site's.

`reproduce_sherkin()` runs first on every invocation. If the imported method
no longer re-derives 7.9 % / 15.2 % from the stored seven Sherkin cells, this
script aborts before touching French data, because a method that has drifted
cannot be trusted at a new site either.

THE SIX STEPS, EXACTLY AS AT SHERKIN
------------------------------------
  1  habitat cells -- here MAPPED L. hyperborea (EMODnet/OSPAR), where
     Sherkin had modelled suitability >= threshold
  2  exposure gate -- here the site's own measured wave climate, where
     Sherkin used the Burrows fetch exclusion
  3  keep only cells in Dubi & Torum's tested 4-10 m range
  4  per-axis MEDIAN wave-height reduction over those cells
  5  interpolate linearly between the two axes bracketing the measured
     wave-travel bearing
  6  E = 1 - (1 - H)^2

TWO COEFFICIENT SPELLINGS, BOTH REPORTED
----------------------------------------
The brief specifies the published discrete damping values
(0.0094 / 0.0032 / 0.0014 / 0.0005 per m at 4 / 6 / 8 / 10 m). This project's
locked chain uses the fitted curve k = 0.0658 exp(-0.5 D) that those four
points define. They are close but not identical -- the fit reads
0.0089 / 0.0033 / 0.0012 / 0.0004 -- so BOTH are computed and both are
reported. The binned form is primary here because the brief asked for it; the
fitted form is the cross-check and is the one that must reproduce Sherkin.
Neither is allowed to stand alone.

THE TIDAL DATUM IS NOT A DETAIL AT THIS SITE
--------------------------------------------
EMODnet Bathymetry depths refer to LAT -- verified from the product's own
metadata, not assumed. Sherkin's INFOMAR depths are LAT too, so the datum
treatment is identical and the two sites stay comparable. But the Iroise
tidal range is roughly twice West Cork's, so a cell at 4 m LAT spends most of
its life deeper than 4 m, and "the bed sits in the 4-10 m band" is a
statement about one instant of the tide. The band is therefore evaluated at
LAT AND at mean sea level, and if the two disagree about the answer, that
disagreement is the result.

WHAT THIS SCRIPT WILL NOT DO
----------------------------
It will not reuse any Irish attenuation percentage. It will not apply a
coefficient outside 4-10 m -- the chain stops instead, exactly as it did at
every Irish site. It will not put a euro on a receptor without a published
method whose inputs this pipeline actually produces; `damage_function_check`
decides that, and it decides it the same way for France as for Ireland.

Run:
    PYTHONPATH=src python src/france_chain.py
    PYTHONPATH=src python src/france_chain.py --skip-receptors   # faster
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

import geopandas as gpd                                     # noqa: E402
import rasterio                                             # noqa: E402
from rasterio.features import rasterize                     # noqa: E402
from shapely.geometry import box, Point                     # noqa: E402
from pyproj import Transformer                              # noqa: E402

from anaird_phaseb import (AXES, BEARING_HALF_WIDTHS, BEARING_PRIMARY,  # noqa: E402
                           CELL_HA, GRID_M, D_VALID, headline,
                           interp_axes, k_dubi_torum, per_axis_cell_table,
                           reproduce_sherkin, saturation_check)
from national_phaseb import BEARING_RADII_M                  # noqa: E402
from wide_receptor_screen import SHORE_DIST_M, HAB_SEARCH_M  # noqa: E402
import france_data as FD                                     # noqa: E402
import replacement_cost as RC                                # noqa: E402
import damage_function_check as DFC                          # noqa: E402

OUT = REPO / "outputs" / "france"
DATA = REPO / "data" / "france"
L93 = "EPSG:2154"          # Lambert-93: the French analogue of Irish ITM
WGS = "EPSG:4326"

# ---------------------------------------------------------------------------
# Dubi & Torum (1996), the four published damping values
# ---------------------------------------------------------------------------
# Wave HEIGHT damping per metre of travel through the kelp, measured at
# 12 plants/m2 on subtidal L. hyperborea. The fitted curve this project has
# used since bed_width.py is k = 0.0658 exp(-0.5 D); these are the four points
# it was fitted through, as given in the brief.
DT_PUBLISHED = {4.0: 0.0094, 6.0: 0.0032, 8.0: 0.0014, 10.0: 0.0005}


def k_binned(depth_m: float) -> float:
    """Published damping at the nearest measured depth. Bins, not a curve.

    Raises outside 4-10 m. The Irish chain stopped rather than extrapolate and
    this one does the same: a coefficient outside its validity range is not a
    smaller result, it is a different claim.
    """
    if not (D_VALID[0] <= depth_m <= D_VALID[1]):
        raise ValueError(f"depth {depth_m:.2f} m is outside Dubi & Torum's "
                         f"tested range {D_VALID[0]}-{D_VALID[1]} m")
    return DT_PUBLISHED[min(DT_PUBLISHED, key=lambda d: abs(d - depth_m))]


# Mork (1996): the published envelope this project cross-checks against.
# Reported as an envelope for wave ENERGY reduction over a kelp forest.
MORK_ENVELOPE = (0.70, 0.85)

# Below this, an RGE ALTI return is treated as an UNKNOWN ground elevation
# rather than a low one. See add_elevation().
ELEV_SANITY_MIN_M = -10.0

# Le Conquet tidal levels -- see verify_tides() and TIDE_SOURCE.
# Filled from the verified source at run time; the fallback is None so that a
# missing verification produces "NOT RUN" rather than a guessed number.
TIDE = {"z0_msl_above_cd_m": None, "source": None}


# ===========================================================================
# grid
# ===========================================================================
def build_grid() -> dict:
    """A 50 m lattice in Lambert-93 covering the AOI.

    50 m because that is the Irish model's cell size and the attenuation walk
    integrates k over a step length; changing the step would change the
    numbers for a reason that has nothing to do with the site.
    """
    t = Transformer.from_crs(WGS, L93, always_xy=True)
    xs, ys = [], []
    for lon in (FD.BBOX_WGS[0], FD.BBOX_WGS[2]):
        for lat in (FD.BBOX_WGS[1], FD.BBOX_WGS[3]):
            x, y = t.transform(lon, lat)
            xs.append(x)
            ys.append(y)
    x0 = math.floor(min(xs) / GRID_M) * GRID_M
    y0 = math.floor(min(ys) / GRID_M) * GRID_M
    nx = int(math.ceil((max(xs) - x0) / GRID_M))
    ny = int(math.ceil((max(ys) - y0) / GRID_M))
    return {"x0": x0, "y0": y0, "nx": nx, "ny": ny,
            "cx": x0 + (np.arange(nx) + 0.5) * GRID_M,
            "cy": y0 + (np.arange(ny) + 0.5) * GRID_M}


def kelp_cover(grid: dict) -> tuple[np.ndarray, gpd.GeoDataFrame]:
    """Fraction of each 50 m cell covered by mapped L. hyperborea.

    Rasterised at 10 m and aggregated 5x5, because the polygons have a median
    area of 82 m2: a centre-in-polygon test at 50 m would throw most of the
    mapped habitat away and call the loss a result.
    """
    g = gpd.read_file(DATA / "kelp_hyperborea.geojson").to_crs(L93)
    sub = GRID_M / 5.0                                   # 10 m
    W, H = grid["nx"] * 5, grid["ny"] * 5
    tr = rasterio.transform.from_origin(grid["x0"],
                                        grid["y0"] + grid["ny"] * GRID_M,
                                        sub, sub)
    fine = rasterize(((geom, 1) for geom in g.geometry if geom is not None),
                     out_shape=(H, W), transform=tr, fill=0, dtype="uint8",
                     all_touched=False)
    frac = fine.reshape(grid["ny"], 5, grid["nx"], 5).mean(axis=(1, 3))
    return frac.astype("float32"), g


def sample_depth(grid: dict) -> np.ndarray:
    """EMODnet depth (metres below LAT, positive down) at every cell centre."""
    with rasterio.open(DATA / "bathy_emodnet.tif") as s:
        arr = s.read(1).astype("float64")
        inv = ~s.transform
        t = Transformer.from_crs(L93, WGS, always_xy=True)
        X, Y = np.meshgrid(grid["cx"], grid["cy"][::-1])   # row 0 = north
        lon, lat = t.transform(X.ravel(), Y.ravel())
        col, row = inv * (np.asarray(lon), np.asarray(lat))
        col = np.rint(col).astype(int)
        row = np.rint(row).astype(int)
        ok = (col >= 0) & (col < s.width) & (row >= 0) & (row < s.height)
        z = np.full(col.shape, np.nan)
        z[ok] = arr[row[ok], col[ok]]
    return (-z).reshape(grid["ny"], grid["nx"])           # depth, positive down


def cell_bearings(grid: dict, origin_l93: tuple) -> tuple[np.ndarray, np.ndarray]:
    """Distance (m) and compass bearing FROM origin TO each cell centre."""
    X, Y = np.meshgrid(grid["cx"], grid["cy"][::-1])
    dx, dy = X - origin_l93[0], Y - origin_l93[1]
    dist = np.hypot(dx, dy)
    bear = (np.degrees(np.arctan2(dx, dy)) + 360.0) % 360.0
    return dist, bear


def ang_diff(a: np.ndarray, b: float) -> np.ndarray:
    return np.abs((a - b + 180.0) % 360.0 - 180.0)


# ===========================================================================
# attenuation, in both coefficient spellings
# ===========================================================================
def per_axis_table_binned(mask: np.ndarray, depth: np.ndarray) -> pd.DataFrame:
    """per_axis_cell_table(), but with the published binned coefficients.

    Same walk, same step lengths, same four axes. Only k changes. Kept as a
    separate function rather than a flag so the two spellings cannot be
    confused for one another downstream.
    """
    cells = {(int(c), int(r)) for r, c in zip(*np.nonzero(mask))}
    rows = []
    for (c0, r0) in sorted(cells):
        if not np.isfinite(depth[r0, c0]):
            continue
        rec = {"col": c0, "row": r0, "depth_m": round(float(depth[r0, c0]), 2)}
        for (dx, dy), label, _ in AXES:
            step = GRID_M * math.hypot(dx, dy)
            run = [(c0, r0)]
            for sign in (1, -1):
                c, r = c0, r0
                while True:
                    c, r = c + sign * dx, r + sign * dy
                    if (c, r) not in cells:
                        break
                    run.append((c, r))
            tot = 0.0
            for (c, r) in run:
                d = float(depth[r, c])
                if np.isfinite(d) and D_VALID[0] <= d <= D_VALID[1]:
                    tot += k_binned(d) * step
            rec[f"width_{label}"] = round(len(run) * step, 1)
            rec[f"H_red_{label}"] = round(1 - math.exp(-tot), 4)
        rows.append(rec)
    return pd.DataFrame(rows)


def coefficient_domain_report(depth_of_cells: np.ndarray) -> dict:
    """Is every coefficient used inside its validity range? Computed, not hoped.

    The chain STOPS if any cell entering the attenuation sum is outside
    4-10 m. This function is what makes that a check rather than a comment.
    """
    d = depth_of_cells[np.isfinite(depth_of_cells)]
    inside = (d >= D_VALID[0]) & (d <= D_VALID[1])
    return {"n_cells": int(d.size),
            "n_inside_4_10m": int(inside.sum()),
            "n_outside": int((~inside).sum()),
            "all_inside": bool(inside.all()),
            "depth_min_m": round(float(d.min()), 2) if d.size else None,
            "depth_max_m": round(float(d.max()), 2) if d.size else None}


def mork_crosscheck(E: float) -> dict:
    """Compare our energy reduction against Mork's published envelope.

    A number far below the envelope is not automatically wrong -- Mork's
    figure is for a wave crossing a wide forest, and the quantity here is a
    median over cells whose runs may be short. But "far outside and not
    flagged" is how a wrong number survives, so the comparison is computed
    and reported either way.
    """
    lo, hi = MORK_ENVELOPE
    if E < lo:
        verdict = ("BELOW Mork's 70-85 % envelope. Expected when the traversed "
                   "kelp width is short compared with the width Mork's forests "
                   "had; check the width column before reading anything into it.")
    elif E > hi:
        verdict = ("ABOVE Mork's 70-85 % envelope. Treat as saturation of an "
                   "exponential fit, not as a measurement.")
    else:
        verdict = "INSIDE Mork's 70-85 % envelope."
    return {"E_reduction": round(E, 4), "mork_envelope": [lo, hi],
            "verdict": verdict, "inside": bool(lo <= E <= hi)}


# ===========================================================================
# receptors
# ===========================================================================
def load_receptors(grid: dict) -> gpd.GeoDataFrame:
    """BD TOPO receptors near the shoreline, with RGE ALTI ground elevation."""
    shore = gpd.read_file(DATA / "bdtopo_limite_terre_mer.geojson").to_crs(L93)
    shore_u = shore.geometry.union_all()

    frames = []
    specs = [("bdtopo_batiment.geojson", "building", "usage_1"),
             ("bdtopo_construction_lineaire.geojson", "linear_construction", "nature"),
             ("bdtopo_construction_surfacique.geojson", "surface_construction", "nature"),
             ("bdtopo_equipement_de_transport.geojson", "transport_equipment", "nature"),
             ("bdtopo_zone_d_activite_ou_d_interet.geojson", "activity_zone", "categorie")]
    for fname, cls, attr in specs:
        p = DATA / fname
        if not p.exists():
            print(f"   receptors: {fname} absent -- class '{cls}' NOT screened")
            continue
        g = gpd.read_file(p).to_crs(L93)
        if g.empty:
            continue
        g["receptor_class"] = cls
        g["detail"] = g[attr].astype(str) if attr in g.columns else ""
        g["name"] = (g["toponyme"].astype(str) if "toponyme" in g.columns
                     else (g["nom"].astype(str) if "nom" in g.columns else ""))
        frames.append(g[["receptor_class", "detail", "name", "geometry"]])
    if not frames:
        return gpd.GeoDataFrame(columns=["receptor_class", "geometry"],
                                geometry="geometry", crs=L93)
    r = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=L93)

    # Buffer-and-index rather than a distance to a unioned 2,272-part line:
    # the answer is the same and the second form does not finish.
    buf = gpd.GeoDataFrame(geometry=[shore_u.buffer(SHORE_DIST_M)], crs=L93)
    hit = gpd.sjoin(r, buf, how="inner", predicate="intersects")
    near = r.loc[sorted(set(hit.index))].copy().reset_index(drop=True)
    near["dist_shore_m"] = near.geometry.distance(shore_u)
    near = near[near.dist_shore_m <= SHORE_DIST_M].reset_index(drop=True)
    print(f"   receptors: {len(r):,} in AOI, {len(near):,} within "
          f"{SHORE_DIST_M:.0f} m of the BD TOPO land-sea limit")
    return near


def add_elevation(near: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """RGE ALTI at each receptor's representative point.

    1 m source data via the IGN altimetry API, cached per batch. This is a
    strict improvement on the Irish sites, which had only the Copernicus
    GLO-30 DSM -- 30 m, and a SURFACE model, so biased upward by whatever is
    standing on the ground.
    """
    pts = near.geometry.representative_point().to_crs(WGS)
    coords = [(float(p.x), float(p.y)) for p in pts]
    z = FD.rge_alti(coords, tag="receptors")
    near = near.copy()
    near["elev_raw_m"] = z[:len(near)] if len(z) >= len(near) else \
        list(z) + [float("nan")] * (len(near) - len(z))

    # SANITY GATE, added after the first run returned -2045.28 m for a quay.
    # RGE ALTI's documented no-data sentinel is -99999.01 and that is already
    # filtered inside FD.rge_alti(), but the API also returns large negative
    # values over water and inside harbour basins. Those are an UNKNOWN
    # ground elevation, not a low one, and counting them as "below 5 m" would
    # manufacture exposed receptors -- the exact error the Irish screen warns
    # about ("0.0 is an UNKNOWN ground elevation, not a low one",
    # national_exposure_screen.py).
    bad = near.elev_raw_m < ELEV_SANITY_MIN_M
    near["elev_m"] = near.elev_raw_m.where(~bad)
    near["elev_unknown"] = bad | near.elev_raw_m.isna()
    n_bad = int(bad.sum())
    if n_bad:
        print(f"   elevation sanity: {n_bad} receptor(s) returned "
              f"< {ELEV_SANITY_MIN_M:.0f} m and are marked UNKNOWN, not low")
    return near


def alongshore_frontage_m(grid: dict, f_final: np.ndarray, wave_from: float,
                          receptors_l93: np.ndarray | None = None,
                          within_m: float = 2000.0) -> dict:
    """Alongshore metres of shoreline that have valid-band kelp in front.

    replacement_cost() needs a FRONTAGE, not an area: a bed's hectares cannot
    be multiplied by a euro-per-metre rate. Sherkin had to infer one from area
    divided by an assumed cross-shore width, and reported four widths because
    it could not measure the real thing. Here it is measured.

    TWO frontages are returned and only one of them may be priced.

    `habitat_only`  every shoreline segment with valid-band, on-wave-path kelp
                    within `within_m`. In this AOI that is the whole
                    archipelago -- a quarter of a million metres, most of it
                    uninhabited rock. Multiplying it by a euro-per-metre rate
                    would produce a billion-euro headline describing a
                    breakwater nobody would ever build around every islet in
                    the Iroise. It is reported as CONTEXT and never priced.

    `with_receptor` the same, restricted to segments that also have a
                    below-5 m receptor within SHORE_DIST_M. This is the one
                    that may be priced, and the restriction is not a
                    convenience: replacement cost is admissible ONLY where
                    Shabman & Batie condition 3 holds, and condition 3 is
                    exactly "a built receptor is there". Pricing frontage the
                    condition does not cover would be pricing frontage the
                    method does not license.
    """
    shore = gpd.read_file(DATA / "bdtopo_limite_terre_mer.geojson").to_crs(L93)
    X, Y = np.meshgrid(grid["cx"], grid["cy"][::-1])
    fx, fy = X[f_final], Y[f_final]
    if fx.size == 0:
        return {"habitat_only_m": 0.0, "with_receptor_m": 0.0,
                "segments_total": 0}
    rx = ry = None
    if receptors_l93 is not None and len(receptors_l93):
        rx = receptors_l93[:, 0]
        ry = receptors_l93[:, 1]

    hab_m = 0.0
    both_m = 0.0
    n_seg = n_hab = n_both = 0
    for geom in shore.geometry:
        if geom is None or geom.is_empty:
            continue
        lines = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
        for ln in lines:
            L = ln.length
            if L <= 0:
                continue
            n = max(1, int(math.ceil(L / GRID_M)))
            seg_len = L / n
            for i in range(n):
                pt = ln.interpolate((i + 0.5) * seg_len)
                n_seg += 1
                dd = np.hypot(fx - pt.x, fy - pt.y)
                near_i = dd <= within_m
                if not near_i.any():
                    continue
                bb = (np.degrees(np.arctan2(fx[near_i] - pt.x,
                                            fy[near_i] - pt.y)) + 360) % 360
                if not (np.abs((bb - wave_from + 180) % 360 - 180)
                        <= BEARING_PRIMARY).any():
                    continue
                hab_m += seg_len
                n_hab += 1
                if rx is not None and \
                        (np.hypot(rx - pt.x, ry - pt.y) <= SHORE_DIST_M).any():
                    both_m += seg_len
                    n_both += 1
    return {"habitat_only_m": round(hab_m, 1),
            "with_receptor_m": round(both_m, 1),
            "segments_total": n_seg,
            "segments_habitat_only": n_hab,
            "segments_with_receptor": n_both,
            "within_m": within_m,
            "receptor_gate_m": SHORE_DIST_M,
            "priceable": "with_receptor_m",
            "method": f"BD TOPO land-sea limit split into ~{GRID_M:.0f} m "
                      f"segments. habitat_only: valid-band on-wave-path kelp "
                      f"within {within_m:.0f} m inside the "
                      f"+/- {BEARING_PRIMARY:.0f} deg sector. with_receptor: "
                      f"that AND a below-5 m receptor within "
                      f"{SHORE_DIST_M:.0f} m. Only with_receptor may be "
                      f"priced -- see the docstring."}


# ===========================================================================
# main
# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-receptors", action="store_true")
    ap.add_argument("--cover-threshold", type=float, default=0.5,
                    help="fraction of a 50 m cell that must be mapped kelp "
                         "for the cell to count as habitat")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    res: dict = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "site": FD.SITE, "aoi_bbox_wgs84": FD.BBOX_WGS,
                 "grid_m": GRID_M, "cover_threshold": a.cover_threshold}

    def hr(t=""):
        print("\n" + "=" * 78)
        if t:
            print(t)
            print("=" * 78)

    hr("CONTROL FIRST -- does the imported method still reproduce Sherkin?")
    sh = reproduce_sherkin()
    print(f"  {sh['n_cells']} cells, {sh['ha']} ha, "
          f"H {sh['H_reduction']:.1%}, E {sh['E_reduction']:.1%}")
    if not sh["reproduces_locked_figures"]:
        print("  ABORT: the imported method no longer re-derives the locked "
              "7.9 % / 15.2 % from the stored Sherkin cells. A method that "
              "has drifted cannot be trusted at a new site either.")
        return 2
    print("  PASSED -- 7.9 % / 15.2 % reproduced. Proceeding on French data.")
    res["sherkin_control"] = sh

    hr("WAVE CLIMATE -- this site's own, measured, never carried from Ireland")
    s = pd.read_csv(REPO / "outputs" / "model" /
                    "swell_direction_leconquet_summary.csv")
    row = s[s.basis == "energy_weighted"].iloc[0]
    wave_from = float(row.mean_from_deg)
    wave_to = float(row.travels_to_deg)
    print(f"  IBI (primary, same product as Sherkin/An Aird): waves FROM "
          f"{wave_from:.1f} deg, travelling TO {wave_to:.1f} deg, "
          f"R = {float(row.concentration_R):.3f}")
    cross = REPO / "outputs" / "model" / "swell_direction_leconquet_nws_summary.csv"
    if cross.exists():
        c = pd.read_csv(cross)
        crow = c[c.basis == "energy_weighted"].iloc[0]
        delta = abs((float(crow.mean_from_deg) - wave_from + 180) % 360 - 180)
        print(f"  NWSHELF (independent cross-check): FROM "
              f"{float(crow.mean_from_deg):.1f} deg -- {delta:.1f} deg apart")
        res["wave_crosscheck"] = {
            "ibi_from_deg": round(wave_from, 1),
            "nwshelf_from_deg": round(float(crow.mean_from_deg), 1),
            "delta_deg": round(delta, 1),
            "agree_within_narrowest_sector": bool(delta <= min(BEARING_HALF_WIDTHS)),
            "note": "Two independent wave models. The NWSHELF summary file "
                    "carries swell_direction.py's hard-coded IBI product "
                    "label in its footer -- a cosmetic defect in that script, "
                    "recorded rather than silently tolerated. The n differs "
                    "(3-hourly vs hourly), which is how the two are told apart."}
    else:
        print("  NWSHELF cross-check: NOT RUN (file absent)")
        res["wave_crosscheck"] = {"status": "NOT RUN"}
    print(f"  Sherkin was 212.7 deg, An Aird 252.7 deg. Three sites, three "
          f"bearings, none reused.")
    res["wave"] = {"from_deg": round(wave_from, 1), "to_deg": round(wave_to, 1),
                   "basis": "energy_weighted", "product": "IBI_MULTIYEAR_WAV_005_006",
                   "period": "2015-2024"}

    hr("GRID, HABITAT AND DEPTH")
    grid = build_grid()
    print(f"  lattice {grid['nx']} x {grid['ny']} cells of {GRID_M:.0f} m "
          f"in {L93}")
    frac, kelp_gdf = kelp_cover(grid)
    depth = sample_depth(grid)
    kelp_mask = frac >= a.cover_threshold
    print(f"  mapped L. hyperborea (EMODnet/OSPAR, CC-BY-4.0): "
          f"{len(kelp_gdf):,} polygons, "
          f"{kelp_gdf.to_crs(L93).area.sum()/1e4:,.0f} ha in the AOI")
    print(f"  cells with cover >= {a.cover_threshold:.0%}: "
          f"{int(kelp_mask.sum()):,} = {kelp_mask.sum()*CELL_HA:,.0f} ha")
    for thr in (0.25, 0.5, 0.75):
        print(f"     sensitivity, cover >= {thr:.0%}: "
              f"{int((frac >= thr).sum()):,} cells "
              f"({(frac >= thr).sum()*CELL_HA:,.0f} ha)")
    res["habitat"] = {
        "source": "EMODnet Seabed Habitats macroalgae EOV poly 2025 "
                  "(CC BY 4.0), habsubtype = L. hyperborea only",
        "polygons": int(len(kelp_gdf)),
        "mapped_ha_in_aoi": round(float(kelp_gdf.to_crs(L93).area.sum() / 1e4), 1),
        "cells_at_threshold": int(kelp_mask.sum()),
        "ha_at_threshold": round(float(kelp_mask.sum() * CELL_HA), 1),
        "cover_sensitivity": {f"{t:.2f}": int((frac >= t).sum())
                              for t in (0.25, 0.5, 0.75)},
        "l_digitata_excluded": json.loads(
            (DATA / "kelp_digitata_count.json").read_text(encoding="utf-8"))
        if (DATA / "kelp_digitata_count.json").exists() else None}

    # ---------------- step 3: the depth gate, at two tidal datums ----------
    hr("STEP 3 -- THE DEPTH GATE (Dubi & Torum 4-10 m), AT TWO DATUMS")
    print("  EMODnet depths are referred to LAT (verified from the product's "
          "own metadata).")
    datums = {"LAT": 0.0}
    if TIDE["z0_msl_above_cd_m"] is not None:
        datums["MSL"] = float(TIDE["z0_msl_above_cd_m"])
        print(f"  MSL sensitivity uses Z0 = {datums['MSL']:.2f} m above chart "
              f"datum, source: {TIDE['source']}")
    else:
        print("  MSL sensitivity: NOT RUN -- no verified Z0 for Le Conquet on "
              "disk. Reported as NOT RUN, never as agreement.")

    band_results = {}
    for dname, offset in datums.items():
        d = depth + offset
        inband = kelp_mask & np.isfinite(d) & (d >= D_VALID[0]) & (d <= D_VALID[1])
        band_results[dname] = {
            "offset_m": offset,
            "cells": int(inband.sum()),
            "ha": round(float(inband.sum() * CELL_HA), 2)}
        print(f"  {dname:4s}: {int(inband.sum()):,} kelp cells in 4-10 m "
              f"= {inband.sum()*CELL_HA:,.0f} ha")
    res["depth_gate"] = band_results

    depth_lat = depth
    in_band = kelp_mask & np.isfinite(depth_lat) & \
        (depth_lat >= D_VALID[0]) & (depth_lat <= D_VALID[1])
    if not in_band.any():
        print("\n  NOTHING SURVIVES THE DEPTH GATE. The chain stops here, "
              "exactly as it did at every Irish site. This is a result.")
        res["status"] = "stopped_at_depth_gate"
        (OUT / "france_chain.json").write_text(
            json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0

    # ---------------- the bearing test ------------------------------------
    hr("THE BEARING TEST -- habitat only shelters what it stands in front of")
    t = Transformer.from_crs(WGS, L93, always_xy=True)
    origin = t.transform(FD.SITE["receptor_lon"], FD.SITE["receptor_lat"])
    dist, bear = cell_bearings(grid, origin)
    # The Irish radii (500 / 1000 / 2000 m) are kept so the two sites can be
    # read on the same axis, and wider ones are ADDED because this bed is an
    # offshore archipelago rather than a fringe: reporting only the Irish
    # radii here would show three hectares and hide three thousand.
    radii = list(BEARING_RADII_M) + [5000, 10000, 20000]
    bt = {}
    for hw in list(BEARING_HALF_WIDTHS):
        insec = ang_diff(bear, wave_from) <= hw
        bt[str(int(hw))] = {str(r): round(float((in_band & insec &
                                                 (dist <= r)).sum() * CELL_HA), 2)
                            for r in radii}
    bt["none"] = {str(r): round(float((in_band & (dist <= r)).sum() * CELL_HA), 2)
                  for r in radii}
    print(f"  in-band habitat (ha) by sector half-width, centred on the "
          f"direction waves arrive FROM ({wave_from:.0f} deg):")
    print(f"     {'half-width':>12}" +
          "".join(f"{'<='+str(x//1000)+'km' if x>=1000 else '<='+str(x)+'m':>11}"
                  for x in radii))
    for k in list(BEARING_HALF_WIDTHS) + ["none"]:
        key = str(int(k)) if k != "none" else "none"
        lab = f"+/- {int(k)} deg" if k != "none" else "no test"
        print(f"     {lab:>12}" +
              "".join(f"{bt[key][str(r)]:>11.1f}" for r in radii))
    print("     (distances from Le Conquet town centre. The Irish radii stop")
    print("      at 2 km because Irish clusters are fringing; this bed is an")
    print("      offshore archipelago, so wider radii are added rather than")
    print("      substituted.)")
    res["bearing_test_ha"] = bt

    on_path = ang_diff(bear, wave_from) <= BEARING_PRIMARY
    f_final = in_band & on_path
    print(f"\n  primary sector (+/- {BEARING_PRIMARY:.0f} deg), any distance: "
          f"{int(f_final.sum()):,} cells = {f_final.sum()*CELL_HA:,.0f} ha")
    if not f_final.any():
        print("  NOTHING IN BAND LIES ON THE WAVE PATH. Chain stops.")
        res["status"] = "stopped_at_bearing_test"
        (OUT / "france_chain.json").write_text(
            json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0

    # ---------------- steps 4-6, both coefficient spellings ---------------
    hr("STEPS 4-6 -- ATTENUATION, BOTH COEFFICIENT SPELLINGS")
    dom = coefficient_domain_report(np.where(f_final, depth_lat, np.nan))
    print(f"  coefficient domain: {dom['n_inside_4_10m']:,} of "
          f"{dom['n_cells']:,} cells inside 4-10 m "
          f"(depths {dom['depth_min_m']}-{dom['depth_max_m']} m)")
    if not dom["all_inside"]:
        print("  ABORT: a cell outside 4-10 m reached the attenuation sum.")
        res["status"] = "aborted_coefficient_out_of_domain"
        res["coefficient_domain"] = dom
        (OUT / "france_chain.json").write_text(
            json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        return 3
    res["coefficient_domain"] = dom

    cells_fit = per_axis_cell_table(f_final, depth_lat)
    cells_bin = per_axis_table_binned(f_final, depth_lat)
    out_fit = headline(cells_fit, wave_to)
    med_bin = {lab: float(np.median(cells_bin[f"H_red_{lab}"]))
               for (_, lab, _) in AXES}
    H_bin, lo, hi, w = interp_axes(med_bin, wave_to)
    out_bin = {"n_cells": int(len(cells_bin)),
               "ha": round(len(cells_bin) * CELL_HA, 2),
               "per_axis_median_H": {k: round(v, 4) for k, v in med_bin.items()},
               "bracketing_axes": [lo, hi], "weight_on_upper": round(w, 4),
               "travel_deg": round(wave_to, 1),
               "H_reduction": round(H_bin, 4),
               "E_reduction": round(1 - (1 - H_bin) ** 2, 4),
               "width_median_m": {lab: round(float(np.median(
                   cells_bin[f"width_{lab}"])), 1) for (_, lab, _) in AXES}}

    for lab, o in (("PUBLISHED BINS (primary, per the brief)", out_bin),
                   ("FITTED CURVE (the locked Sherkin spelling)", out_fit)):
        print(f"\n  {lab}")
        print(f"     cells {o['n_cells']:,}  = {o['ha']:,.1f} ha")
        print(f"     per-axis median H: " +
              "  ".join(f"{k} {v:.1%}" for k, v in o["per_axis_median_H"].items()))
        print(f"     bracketing axes {o['bracketing_axes']} at travel "
              f"{o['travel_deg']:.0f} deg, weight {o['weight_on_upper']:.2f}")
        print(f"     wave HEIGHT reduction  H = {o['H_reduction']:.1%}")
        print(f"     wave ENERGY reduction  E = {o['E_reduction']:.1%}")
        print(f"     median traversed width: " +
              "  ".join(f"{k} {v:,.0f} m" for k, v in o["width_median_m"].items()))
    res["attenuation"] = {"published_bins": out_bin, "fitted_curve": out_fit}

    # ---------------- domain / saturation ---------------------------------
    hr("IS THE COEFFICIENT BEING USED, OR EXTRAPOLATED TO SATURATION?")
    best_axis = max(out_bin["per_axis_median_H"],
                    key=out_bin["per_axis_median_H"].get)
    sat = saturation_check(cells_fit, best_axis)
    ratio = sat["ratio_width_to_50pct"]
    print(f"  axis {best_axis}: traversed width vs the width needed for a "
          f"50 % height loss at that depth")
    print(f"     ratio median {ratio.median():.2f}, "
          f"p90 {ratio.quantile(0.9):.2f}, max {ratio.max():.2f}")
    print("  A ratio far above 1 means an exponential fitted in a flume over a "
          "few metres is being run to saturation, and the percentage is an "
          "artefact of the extrapolation rather than a measurement.")
    res["saturation"] = {"axis": best_axis,
                         "ratio_median": round(float(ratio.median()), 2),
                         "ratio_p90": round(float(ratio.quantile(0.9)), 2),
                         "ratio_max": round(float(ratio.max()), 2)}

    # A diagnostic that only reports a problem is half a diagnostic. Re-run
    # steps 4-6 over the cells where the exponential has NOT saturated --
    # traversed width at or below the width needed for a 50 % height loss --
    # so the reader sees what the answer becomes when the extrapolation is
    # removed rather than only being warned that it is there.
    unsat = (ratio <= 1.0).to_numpy()
    if unsat.any() and not unsat.all():
        cb = cells_bin.loc[unsat].reset_index(drop=True)
        mb = {lab: float(np.median(cb[f"H_red_{lab}"])) for (_, lab, _) in AXES}
        Hu, _, _, _ = interp_axes(mb, wave_to)
        cf = cells_fit.loc[unsat].reset_index(drop=True)
        mf = {lab: float(np.median(cf[f"H_red_{lab}"])) for (_, lab, _) in AXES}
        Hf, _, _, _ = interp_axes(mf, wave_to)
        res["attenuation_unsaturated_only"] = {
            "cells": int(unsat.sum()),
            "ha": round(float(unsat.sum() * CELL_HA), 2),
            "share_of_cells": round(float(unsat.mean()), 3),
            "published_bins": {"H_reduction": round(Hu, 4),
                               "E_reduction": round(1 - (1 - Hu) ** 2, 4)},
            "fitted_curve": {"H_reduction": round(Hf, 4),
                             "E_reduction": round(1 - (1 - Hf) ** 2, 4)},
            "definition": "cells whose traversed kelp width is at or below "
                          "the width needed for a 50 % wave-height loss at "
                          "that depth, i.e. where Dubi & Torum's exponential "
                          "has not been run out to saturation",
            "read_this_as": "the CONSERVATIVE end. The headline figure "
                            "includes cells where the fit is extrapolated; "
                            "this one does not.",
        }
        u = res["attenuation_unsaturated_only"]
        print(f"\n  UNSATURATED SUBSET ({u['cells']:,} cells, "
              f"{u['share_of_cells']:.0%} of the bed, {u['ha']:,.0f} ha):")
        print(f"     published bins  H = {u['published_bins']['H_reduction']:.1%}"
              f"   E = {u['published_bins']['E_reduction']:.1%}")
        print(f"     fitted curve    H = {u['fitted_curve']['H_reduction']:.1%}"
              f"   E = {u['fitted_curve']['E_reduction']:.1%}")
        print(f"     this is the conservative end; the headline above "
              f"includes extrapolated cells")

    hr("CROSS-CHECK AGAINST MORK (1996)")
    mc = mork_crosscheck(out_bin["E_reduction"])
    print(f"  E = {mc['E_reduction']:.1%};  Mork envelope "
          f"{MORK_ENVELOPE[0]:.0%}-{MORK_ENVELOPE[1]:.0%}")
    print(f"  {mc['verdict']}")
    res["mork_crosscheck"] = mc

    # ---------------- receptors -------------------------------------------
    if not a.skip_receptors:
        hr("RECEPTORS -- BD TOPO, landward of the valid-coefficient frontage")
        near = load_receptors(grid)
        if len(near):
            near = add_elevation(near)
            low5 = near[near.elev_m < 5.0]      # NaN comparisons are False, so
            low10 = near[near.elev_m < 10.0]    # unknowns are excluded, not low
            print(f"  within {SHORE_DIST_M:.0f} m of the shoreline: {len(near):,}")
            print(f"     below 5 m RGE ALTI : {len(low5):,}")
            print(f"     below 10 m RGE ALTI: {len(low10):,}")
            print(f"     by class (all near-shore):")
            for cls, n in near.receptor_class.value_counts().items():
                nl = int((near[near.receptor_class == cls].elev_m < 5).sum())
                print(f"        {cls:22s} {n:6,d}   of which below 5 m: {nl:,}")
            # which of them have in-band, on-path habitat in front of them
            X, Y = np.meshgrid(grid["cx"], grid["cy"][::-1])
            fx, fy = X[f_final], Y[f_final]
            rows = []
            for _, r in low5.iterrows():
                p = r.geometry.representative_point()
                bb = (np.degrees(np.arctan2(fx - p.x, fy - p.y)) + 360) % 360
                dd = np.hypot(fx - p.x, fy - p.y)
                sec = np.abs((bb - wave_from + 180) % 360 - 180) <= BEARING_PRIMARY
                rows.append({
                    "receptor_class": r.receptor_class, "detail": r.detail,
                    "name": r.name, "elev_m": r.elev_m,
                    "dist_shore_m": round(float(r.dist_shore_m), 1),
                    "inband_ha_within_1km": round(
                        float((sec & (dd <= 1000)).sum() * CELL_HA), 2),
                    "inband_ha_within_2km": round(
                        float((sec & (dd <= 2000)).sum() * CELL_HA), 2),
                    "nearest_inband_m": (round(float(dd[sec].min()), 0)
                                         if sec.any() else None)})
            rec = pd.DataFrame(rows)
            rec.to_csv(OUT / "france_receptors_below5m.csv", index=False)
            sheltered = rec[rec.inband_ha_within_2km > 0]
            print(f"\n  of the {len(rec):,} receptors below 5 m, "
                  f"{len(sheltered):,} have valid-band kelp on the wave path "
                  f"within 2 km")
            # The Irish screen found OSM records no `sea_wall` anywhere in
            # either sample. BD TOPO has the same hole from the other
            # direction: in this AOI its construction_lineaire vocabulary is
            # Ruines / Pont / Mur / Quai / Mur de soutenement / Barrage /
            # Cloture / Tunnel / Portique portuaire -- and no `Digue`. Two
            # countries, two authoritative databases, the same blind spot on
            # the one class that would settle Shabman & Batie condition 3
            # outright.
            natures = sorted(set(near[near.receptor_class ==
                                      "linear_construction"].detail))
            res["defence_class_check"] = {
                "looked_for": "Digue (dike / sea defence) in BD TOPO "
                              "construction_lineaire",
                "found": bool(any("igue" in n for n in natures)),
                "natures_present": natures,
                "note": "The same gap as OSM's missing `sea_wall` in the "
                        "Irish screen. Condition 3 must therefore rest on the "
                        "presence of built receptors, not on a mapped "
                        "defence."}
            print(f"  BD TOPO defence class `Digue`: "
                  f"{'PRESENT' if res['defence_class_check']['found'] else 'ABSENT'}"
                  f" -- the same blind spot as OSM `sea_wall` in Ireland")

            lowpts = np.array([[p.x, p.y] for p in
                               low5.geometry.representative_point()]) \
                if len(low5) else np.empty((0, 2))
            front = alongshore_frontage_m(grid, f_final, wave_from, lowpts)
            print(f"  alongshore frontage, habitat only:  "
                  f"{front['habitat_only_m']:>9,.0f} m "
                  f"({front['segments_habitat_only']:,} of "
                  f"{front['segments_total']:,} segments) -- CONTEXT, "
                  f"never priced")
            print(f"  alongshore frontage, WITH receptor: "
                  f"{front['with_receptor_m']:>9,.0f} m "
                  f"({front['segments_with_receptor']:,} segments) -- "
                  f"the priceable one")
            res["frontage"] = front

            res["receptors"] = {
                "near_shore": int(len(near)),
                "elevation_unknown": int(near.elev_unknown.sum()),
                "below_5m": int(len(low5)), "below_10m": int(len(low10)),
                "below_5m_with_inband_habitat_2km": int(len(sheltered)),
                "by_class": {k: int(v) for k, v in
                             near.receptor_class.value_counts().items()},
                "shore_dist_gate_m": SHORE_DIST_M,
                "elevation_source": "IGN RGE ALTI (1 m), Licence Ouverte 2.0",
                "file": "outputs/france/france_receptors_below5m.csv"}
        else:
            res["receptors"] = {"near_shore": 0}

    # ---------------- the euro question -----------------------------------
    hr("THE EURO -- avoided damage first, and only then replacement cost")
    dfc = DFC.check()
    print("  Does any published avoided-damage method fit what this pipeline "
          "produces?")
    for m in dfc["methods"]:
        if m["key"] == "replacement_cost":
            continue
        print(f"     {m['name'][:58]:58s} "
              f"{'FITS' if m['fits'] else 'missing %d input(s)' % len(m['missing'])}")
    res["damage_function_check"] = {
        "any_avoided_damage_method_fits": dfc["any_avoided_damage_method_fits"],
        "note": "The check is the SAME one applied to the Irish sites. What "
                "changed at this site is the depth constraint, not the "
                "availability of a hazard value at the receptor."}
    print(f"\n  verdict: "
          f"{'a method fits' if dfc['any_avoided_damage_method_fits'] else 'NO published avoided-damage method fits'}")

    (OUT / "france_chain.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    cells_bin.to_csv(OUT / "france_cells_binned.csv", index=False)
    cells_fit.to_csv(OUT / "france_cells_fitted.csv", index=False)
    print(f"\nwritten: {OUT / 'france_chain.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
