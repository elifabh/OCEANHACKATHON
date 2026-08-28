#!/usr/bin/env python3
"""
habitat_gap_model.py
====================
Part 2 of the national Phase A screen (2026-08-27): close the
habitat-evidence gap left by src/national_receptor_screen.py.

THE GAP
    The national screen classifies each cluster's habitat evidence three
    ways:
        laminaria_present       NPWS maps Laminaria-dominated reef within 1 km
        surveyed_not_laminaria  NPWS mapped reef within 1 km, other community
        unmapped                no NPWS layer-21 polygon within 1 km at all
    Only the third is a genuine blank. On Dingle and outer Iveragh every
    fetch-passing cluster fell in it, so the West Cork run could not say
    whether those frontages have kelp in front of them or not - the honest
    entry was "no habitat data", which is not an answer.

WHAT THIS SCRIPT DOES
    Applies the existing step-2 suitability model v2 (AUC 0.830 leave-one-
    site-out) to those unmapped areas, on the same 50 m grid, from the same
    four covariates (INFOMAR depth, slope, curvature, Burrows log10 fetch),
    so that "no habitat map" becomes a stated presence/absence answer with
    an explicit evidence class.

HOW THE MODEL IS OBTAINED, AND WHY THIS IS SAFE
    The model is NOT refitted; it is RECONSTRUCTED and then verified.

    (Correction, same day: an earlier version of this docstring said a refit
    was impossible because the training depth caches were gone. That was
    wrong - I looked for `depth_*.npy` and missed that build_site caches
    under a different name. `outputs/labels/depth_cache/site_*.npz` holds all
    five training SACs, so a full refit IS feasible offline. It is not done
    here for a different and better reason: re-running
    suitability_multisite.py writes to outputs/model/, which would overwrite
    the LOCKED step-2 report and predictions. A refit as an independent check
    is worth doing, but only with its output redirected. Logged as an open
    item.)

    The fitted model is reconstructed from outputs/model/model_multisite_report.json
    (coefficients, standardisation means/sds, per-site intercepts, operating
    threshold, training ranges) and then VERIFIED against the 28 856 stored
    step-2 predictions, which carry both their covariates and their
    suitability. The verification runs on every invocation and the script
    aborts if it fails. Measured on 2026-08-27:
        median |reconstructed - stored| = 3.7e-05
        threshold-side disagreements    = 3 of 28 856 cells (0.01%)
    The residual traces to the 4-dp rounding of the `curvature` column in
    the stored CSV (curvature sd is 0.0022, so 4 dp is +/-0.023 sd), not to
    the reconstruction; cells recomputed here from the depth grid do not
    carry that rounding.

    The report records features_fitted as the four covariates only, so the
    run that produced v2 was made with --no-interaction. The reconstruction
    reproduces that, which the verification confirms.

THE EVIDENCE LADDER - the point of the whole exercise
    E1  npws_laminaria             NPWS CO Series survey maps Laminaria
                                   within 1 km. A RECORD, not a model.
    E1n surveyed_not_laminaria     NPWS CO Series maps faunal turf reef and
                                   no Laminaria -> recorded absence. Handled
                                   in Part 1; such clusters never reach here.
    E2  model_assessed             model >= threshold, covariates in training
                                   range, ON MAPPED REEF. The step-2 assessed
                                   standard. Modelled presence on known
                                   hard substrate.
    E3  model_offreef_inrange      model >= threshold, in range, NOT on mapped
                                   reef -> SUBSTRATE UNVERIFIED.
    E0  model_absence_on_reef      no in-range cell on mapped reef reaches the
                                   threshold -> modelled absence on known reef.
    E0  model_absence_offreef      same, but off reef: the weakest negative.
    E4  extrapolation_only         every modelled cell has a covariate outside
                                   the training range.
    E5  no_bathymetry              no cell had all four covariates -> still
                                   unassessed, which is not absence.

    E2, E3, E0 and E4 are what this script adds, and all four are REAL
    answers where Part 1 could only write a blank.

    Why E3 and E0-offreef are weaker, in the words of
    suitability_multisite.reef_mask: NPWS layer 21 is a REEF inventory, so
    every training cell was hard substrate. The model never saw sand or mud
    and cannot recognise them. Off mapped reef it can say "these conditions
    look like kelp ground", but NOT "there is rock here".

    Why E2 is reachable at all in a "gap" area: the gap set includes clusters
    whose only nearby NPWS polygons are "geogenic reef" - substrate coverage
    with NO community determination. That is mapped reef (so the model is in
    its substrate domain and step-2's `assessed` test can be met) while still
    leaving the biological question open (so the cluster is genuinely a gap).
    Those two facts are not in conflict; keeping them apart is the point.

HARD RULES CARRIED INTO THIS SCRIPT
    - No euro value is computed. Phase A only.
    - Cells with in_training_range = 0 are EXTRAPOLATION. They are labelled,
      reported, and never used for an area or a euro figure (step-2 caveat 4).
    - E3 cells are never used for an area or a euro figure either: substrate
      is unverified. Area is only defensible on E1/E2.
    - The fetch gate is not touched. This script never re-evaluates exposure.

OUTPUT
    outputs/habitat_gap_model_input.csv    snapshot of the clusters handed in
    outputs/habitat_gap_model_cells.csv    per-cell predictions (all AOIs)
    outputs/habitat_gap_model_clusters.csv per-cluster verdict + evidence
    outputs/habitat_gap_model_summary.json parameters, coverage, verification
    outputs/national_candidate_table.csv   THE DELIVERABLE: national ranked
                                           table, Part 1 + Part 2 merged
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from sklearn.cluster import DBSCAN

sys.path.insert(0, str(Path(__file__).resolve().parent))

from circularity_check import (BATCH, CACHE_DIR, grid_axes,  # noqa: E402
                               sample_depth_grid, sample_fetch_grid, terrain)
from common import INFOMAR_BATHY, ArcGISError, arcgis_request  # noqa: E402
from wide_receptor_screen import (FETCH_EXCLUSION_MAX, FETCH_RASTER,  # noqa: E402
                                  HAB_SEARCH_M, ITM, MODEL_PRED,
                                  MODEL_REPORT, NPWS_SHP, WGS)

OUT_DIR = Path("outputs")
IN_GAP = OUT_DIR / "national_receptor_screen_gap.csv"
IN_ALL = OUT_DIR / "national_receptor_screen.csv"
OUT_INPUT = OUT_DIR / "habitat_gap_model_input.csv"
OUT_CELLS = OUT_DIR / "habitat_gap_model_cells.csv"
OUT_CLUST = OUT_DIR / "habitat_gap_model_clusters.csv"
OUT_SUMMARY = OUT_DIR / "habitat_gap_model_summary.json"
OUT_TABLE = OUT_DIR / "national_candidate_table.csv"

GRID_M = 50.0            # the step-2 grid; changing it invalidates the model
AOI_MARGIN_M = 1300.0    # >= HAB_SEARCH_M plus one cell for the terrain edge
AOI_GROUP_EPS_M = 2000.0 # clusters closer than this share one AOI grid
FEATURES = ("depth_m", "slope_deg", "curvature", "log10_fetch")

# Verification tolerances for the model reconstruction (see module docstring).
VERIFY_MEDIAN_MAX = 1e-3
VERIFY_THRESHOLD_DISAGREE_MAX = 10


# ----------------------------------------------------------------------
# 1. The model
# ----------------------------------------------------------------------

class ModelV2:
    """Step-2 suitability model v2, reconstructed from its saved report."""

    def __init__(self, report_path: Path = Path(MODEL_REPORT)):
        rep = json.loads(Path(report_path).read_text())
        self.report = rep
        if list(rep["features_fitted"]) != list(FEATURES):
            raise SystemExit(
                f"features_fitted {rep['features_fitted']} != {list(FEATURES)}. "
                "The saved model is not the 4-covariate v2 this script "
                "reconstructs; refusing to guess.")
        self.mu = np.array([rep["standardisation"][f]["mean"] for f in FEATURES])
        self.sd = np.array([rep["standardisation"][f]["sd"] for f in FEATURES])
        self.beta = np.array([rep["coefficients_standardised_within_site"][f]
                              for f in FEATURES])
        self.intercepts = list(rep["site_intercepts"].values())
        # A site outside the training set has no intercept of its own, so it
        # is scored with the mean of the training intercepts - exactly what
        # suitability_multisite.py does for the Roaringwater application.
        self.intercept = float(np.mean(self.intercepts))
        self.threshold = float(rep["operating_threshold"])
        self.ranges = {f: tuple(rep["training_ranges"][f]) for f in FEATURES}

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.mu) / self.sd
        return 1.0 / (1.0 + np.exp(-np.clip(self.intercept + Z @ self.beta,
                                            -30, 30)))

    def in_range(self, X: np.ndarray) -> np.ndarray:
        ok = np.ones(X.shape[0], dtype=bool)
        for i, f in enumerate(FEATURES):
            lo, hi = self.ranges[f]
            ok &= (X[:, i] >= lo) & (X[:, i] <= hi)
        return ok

    def verify(self) -> dict:
        """Reproduce the 28 856 stored step-2 predictions. Abort if it fails."""
        d = pd.read_csv(MODEL_PRED)
        X = d[list(FEATURES)].to_numpy(float)
        p = self.predict(X)
        stored = d["suitability"].to_numpy(float)
        diff = np.abs(p - stored)
        disagree = int(((p >= self.threshold) != (stored >= self.threshold)).sum())
        res = {"n_cells": int(len(d)),
               "median_abs_diff": float(np.median(diff)),
               "max_abs_diff": float(diff.max()),
               "threshold_disagreements": disagree,
               "threshold_disagreement_share": round(disagree / len(d), 6)}
        ok = (res["median_abs_diff"] <= VERIFY_MEDIAN_MAX
              and disagree <= VERIFY_THRESHOLD_DISAGREE_MAX)
        res["pass"] = bool(ok)
        print("  model reconstruction check against the stored step-2 "
              f"predictions ({len(d)} cells):")
        print(f"    median |diff| {res['median_abs_diff']:.2e}   "
              f"max {res['max_abs_diff']:.2e}   "
              f"threshold disagreements {disagree}")
        if not ok:
            raise SystemExit("  >>> reconstruction FAILED. Refusing to apply a "
                             "model that does not reproduce step 2.")
        print("    PASS - this is model v2, not a re-fit.\n")
        return res


# ----------------------------------------------------------------------
# 2. AOIs from the gap clusters
# ----------------------------------------------------------------------

def slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(s).lower())[:36]


# Halo beyond HAB_SEARCH_M that must also be sampled. terrain() takes central
# differences, so a cell needs its four orthogonal neighbours to get a slope
# and a curvature at all. Three cells of margin is more than enough.
DISC_HALO_M = 150.0

# Attempts per batch before giving up and leaving those cells for a later run.
# Deliberately small: the sampler is resumable, so waiting out an outage
# in-process buys nothing that re-running does not.
SERVER_RETRIES = 2

# Minutes of INFOMAR sampling before the run stops starting new AOIs and goes
# on to write its outputs. Override with GAP_BUDGET_MIN (0 = unlimited).
DEFAULT_BUDGET_MIN = 45.0


def disc_mask(bbox, grid_m: float, pts_lonlat, to_itm) -> np.ndarray:
    """Cells within HAB_SEARCH_M + DISC_HALO_M of any cluster centroid.

    WHY THIS EXISTS
    An AOI is the bounding box of its cluster group plus a margin, but the
    per-cluster verdict only ever reads cells within HAB_SEARCH_M (1 km) of
    a cluster centroid. On a group of four clusters spread over 5 km the
    rectangle is ~33 km2 while the union of the 1 km discs is under 13 km2,
    so about 60% of the INFOMAR sampling was being thrown away unread.

    That waste was not free: INFOMAR's getSamples starts returning HTTP 504
    under sustained load and common.arcgis_request retries a 5xx three times
    at a 60 s timeout, so one unlucky request costs three minutes. Measured
    2026-08-27: 11 s per healthy 400-point request, but ~40 s/request
    averaged over a long run.

    Masking cannot change any reported number: every cell the verdict reads
    is inside the mask, and cells outside it were only ever going to be
    dropped. It changes how many cells land in the per-cell CSV, nothing
    else.
    """
    lons, lats, _, _ = grid_axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)
    LON, LAT = np.meshgrid(lons, lats)
    gx, gy = to_itm.transform(LON.ravel(), LAT.ravel())
    gx = np.asarray(gx); gy = np.asarray(gy)
    r = HAB_SEARCH_M + DISC_HALO_M
    keep = np.zeros(gx.size, dtype=bool)
    for lon, lat in pts_lonlat:
        px, py = to_itm.transform(lon, lat)
        keep |= ((gx - px) ** 2 + (gy - py) ** 2) <= r * r
    return keep.reshape(ny, nx)


def sample_depth_masked(name: str, bbox, grid_m: float,
                        mask: np.ndarray) -> np.ndarray:
    """INFOMAR depth on the AOI grid, querying ONLY the masked cells.

    Same sign convention as circularity_check.sample_depth_grid: positive
    down, metres below LAT, NaN where not surveyed.

    Caching. A full-grid cache written by an earlier unmasked run is a
    strict superset of what the mask needs, so it is used as-is when
    present; that is why the AOIs sampled before this optimisation existed
    are not re-downloaded. Otherwise the masked grid gets its own cache file
    so the two can never be confused.

    The empty-batch rule from common.arcgis_request applies: a batch whose
    points all fall outside INFOMAR coverage returns HTTP 400, not an empty
    list, so ArcGISError is caught and counted as zero samples.
    """
    lons, lats, _, _ = grid_axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)
    grid = np.full((ny, nx), np.nan, dtype=float)

    full_cache = CACHE_DIR / f"depth_{name}_{int(grid_m)}m.npy"
    mask_cache = CACHE_DIR / f"depth_{name}_{int(grid_m)}m_disc.npy"
    # Only the FULL-grid cache may short-circuit: it was written by an earlier
    # unmasked run and is a strict superset of what the mask needs. The disc
    # cache is written incrementally and may be partial, so it is handled by
    # the resumable block below, never returned blind.
    if full_cache.exists():
        cached = np.load(full_cache)
        if cached.shape == grid.shape:
            print(f"    depth from full grid cache "
                  f"({np.isfinite(cached).mean():.0%} surveyed)")
            return cached, 0

    # RESUMABLE STATE. `done` marks cells for which the server has given a
    # definitive answer - either a depth value, or membership of a batch that
    # came back 400 (the empty-batch rule, i.e. confirmed outside coverage).
    # Cells the server never answered stay not-done, and both arrays are
    # flushed after every batch, so an INFOMAR outage costs only the batches
    # that were actually in flight. INFOMAR went to a hard 504 on every
    # request on 2026-08-27 around 22:50 UTC; without this, each outage threw
    # away a whole AOI's worth of successful requests.
    done_cache = CACHE_DIR / f"depth_{name}_{int(grid_m)}m_disc_done.npy"
    done = np.zeros((ny, nx), dtype=bool)
    if mask_cache.exists() and done_cache.exists():
        prev, prev_done = np.load(mask_cache), np.load(done_cache)
        if prev.shape == grid.shape and prev_done.shape == grid.shape:
            grid, done = prev, prev_done
            print(f"    resuming: {int(done.sum())} of {int(mask.sum())} "
                  "masked cells already answered")

    todo = mask & ~done
    idx = np.flatnonzero(todo.ravel())
    if idx.size == 0:
        print(f"    depth complete from resumable cache "
              f"({np.isfinite(grid[mask]).mean():.0%} surveyed inside discs)")
        return grid, 0

    pts = [[float(lons[i % nx]), float(lats[i // nx])] for i in idx]
    n_req = int(np.ceil(len(pts) / BATCH))
    print(f"    sampling {len(pts)} INFOMAR points inside the 1 km discs "
          f"({n_req} requests; {mask.mean():.0%} of the {mask.size}-cell grid)")
    got, empty, unqueried = {}, 0, 0

    def flush():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(mask_cache, grid)
        np.save(done_cache, done)

    for start in range(0, len(pts), BATCH):
        chunk = pts[start:start + BATCH]
        cells = idx[start:start + BATCH]
        payload = None
        # A 400 is the documented empty-batch rule: every point of this batch
        # is outside INFOMAR coverage. That IS coverage information.
        # A 5xx or a transport failure is the server being unwell, which is
        # NOT coverage information - INFOMAR started returning 504 under
        # sustained load on 2026-08-27. Treating the two the same would turn
        # "the server was busy" into "there is no bathymetry here", i.e. it
        # would manufacture E5 verdicts. They are kept apart.
        # retries=1: arcgis_request's own 3x retry at a 60 s timeout turns a
        # dead server into three minutes per batch. One attempt here, and the
        # outer loop below decides whether to wait and try again.
        for extra in range(SERVER_RETRIES):
            try:
                payload = arcgis_request(f"{INFOMAR_BATHY}/getSamples", {
                    "geometry": json.dumps(
                        {"points": chunk, "spatialReference": {"wkid": 4326}}),
                    "geometryType": "esriGeometryMultipoint",
                    "returnFirstValueOnly": "true",
                    "interpolation": "RSP_NearestNeighbor", "f": "json"},
                    retries=1)
                break
            except ArcGISError as exc:
                st = getattr(exc, "status", None)
                if st is not None and 400 <= int(st) < 500:
                    # Empty-batch rule: every point is outside coverage. That
                    # is a real answer, so these cells are done, as NaN.
                    empty += 1
                    done.ravel()[cells] = True
                    payload = None
                    break
                if extra == SERVER_RETRIES - 1:
                    unqueried += len(chunk)   # left not-done, retried next run
                    payload = None
                    break
                time.sleep(15 * (extra + 1))
        if payload is None:
            flush()
            continue
        for s in payload.get("samples", []):
            loc, raw = s.get("locationId"), s.get("value")
            if loc is None or raw in (None, "", "NaN"):
                continue
            try:
                got[start + int(loc)] = -float(str(raw).split()[0])
            except ValueError:
                continue
        # The whole batch got an answer; points with no value are genuinely
        # unsurveyed at that location, which is also an answer.
        done.ravel()[cells] = True
        for k, v in got.items():
            cell = idx[k]
            grid[cell // nx, cell % nx] = v
        got.clear()
        flush()

    if empty:
        print(f"    ({empty} batches entirely outside INFOMAR coverage)")
    print(f"    answered {int((mask & done).sum())} / {int(mask.sum())} masked "
          f"cells; surveyed {int(np.isfinite(grid[mask]).sum())}")
    if unqueried:
        print(f"    >>> {unqueried} points NEVER GOT AN ANSWER (5xx/transport). "
              "Progress IS cached; re-run to fill them in.")
    return grid, unqueried


def group_aois(gap: pd.DataFrame) -> list[dict]:
    """One 50 m grid per group of clusters, so neighbours share a download."""
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    xy = np.array([to_itm.transform(r.lon, r.lat) for r in gap.itertuples()])
    lab = DBSCAN(eps=AOI_GROUP_EPS_M, min_samples=1).fit_predict(xy)
    gap = gap.assign(_aoi=lab)
    aois = []
    for g, sub in gap.groupby("_aoi"):
        lat_mid = float(sub["lat"].mean())
        dlon = AOI_MARGIN_M / (111320.0 * np.cos(np.radians(lat_mid)))
        dlat = AOI_MARGIN_M / 110574.0
        bbox = [float(sub["lon"].min() - dlon), float(sub["lat"].min() - dlat),
                float(sub["lon"].max() + dlon), float(sub["lat"].max() + dlat)]
        name = f"gap_{slug(sub.iloc[0]['box'])}_{int(g):02d}"
        aois.append({"name": name, "bbox": bbox,
                     "clusters": sub["cluster"].tolist(),
                     "pts": list(zip(sub["lon"].tolist(), sub["lat"].tolist())),
                     "box": sub.iloc[0]["box"], "county": sub.iloc[0]["county"],
                     "places": sorted(set(sub["nearest_place"]))})
    return aois


# ----------------------------------------------------------------------
# 3. Predict one AOI
# ----------------------------------------------------------------------

def run_aoi(aoi: dict, model: ModelV2, npws_itm, to_itm) -> pd.DataFrame:
    """Per-cell predictions for one AOI. Empty frame if nothing is predictable."""
    name, bbox = aoi["name"], aoi["bbox"]
    print(f"\n  --- {name}  {aoi['county']}  {[round(v, 4) for v in bbox]}")
    print(f"      clusters {aoi['clusters']}  near {aoi['places'][:2]}")
    mask = disc_mask(bbox, GRID_M, aoi["pts"], to_itm)
    depth, unqueried = sample_depth_masked(name, bbox, GRID_M, mask)
    aoi["points_never_answered"] = int(unqueried)
    if not np.isfinite(depth).any():
        if unqueried:
            print("      no depth returned AND the server never answered "
                  f"{unqueried} points -> this AOI is UNRESOLVED, not empty")
        else:
            print("      no INFOMAR depth anywhere in this AOI "
                  "-> E5 no_bathymetry")
        return pd.DataFrame()
    slope, curv = terrain(depth, GRID_M)
    fetch = sample_fetch_grid(Path(FETCH_RASTER), bbox, GRID_M)
    if fetch is None:
        fetch = np.full_like(depth, np.nan)

    lons, lats, _, _ = grid_axes(bbox, GRID_M)
    LON, LAT = np.meshgrid(lons, lats)
    stack = {"depth_m": depth, "slope_deg": slope, "curvature": curv,
             "log10_fetch": fetch}
    ok = np.ones(depth.shape, dtype=bool)
    for f in FEATURES:
        ok &= np.isfinite(stack[f])
    n_grid = depth.size
    print(f"      grid {depth.shape} = {n_grid} cells; depth "
          f"{np.isfinite(depth).mean():.0%}, all four covariates "
          f"{ok.mean():.0%}")
    if not ok.any():
        return pd.DataFrame()

    X = np.column_stack([stack[f][ok] for f in FEATURES])
    p = model.predict(X)
    inside = model.in_range(X)

    # Mapped reef of ANY community. By construction of the gap set there is
    # none within 1 km of the cluster, but the AOI is 1.3 km, so this is
    # measured rather than assumed.
    on_reef = np.zeros(X.shape[0], dtype=bool)
    if len(npws_itm):
        from shapely.geometry import Point
        from shapely.strtree import STRtree
        polys = list(npws_itm.geometry.values)
        tree = STRtree(polys)
        px, py = to_itm.transform(LON[ok], LAT[ok])
        for i, (x, y) in enumerate(zip(px, py)):
            pt = Point(x, y)
            hit = tree.query(pt)
            if len(hit) and any(polys[j].covers(pt) for j in hit):
                on_reef[i] = True

    df = pd.DataFrame({
        "aoi": name, "lon": np.round(LON[ok], 6), "lat": np.round(LAT[ok], 6),
        "suitability": np.round(p, 4),
        "on_mapped_reef": on_reef.astype(int),
        "in_training_range": inside.astype(int),
        # The step-2 definition: assessed = on mapped reef AND in range. Off
        # reef there is no substrate evidence, so assessed stays 0 here. That
        # is deliberate: it keeps these cells out of every area and euro sum
        # and out of the screen's pass_habitat term.
        "assessed": (on_reef & inside).astype(int),
        "npws_label": 0,
        **{f: np.round(X[:, i], 6) for i, f in enumerate(FEATURES)},
    })
    pos_in = int(((p >= model.threshold) & inside).sum())
    print(f"      modelled {len(df)} cells; in training range "
          f"{inside.mean():.0%}; >= {model.threshold:.4f} and in range "
          f"{pos_in}; on mapped reef {int(on_reef.sum())}")
    return df


# ----------------------------------------------------------------------
# 4. Per-cluster verdict
# ----------------------------------------------------------------------

def cluster_verdict(row, cells: pd.DataFrame, model: ModelV2,
                    to_itm) -> dict:
    """Summarise the modelled cells within HAB_SEARCH_M of one cluster."""
    cx, cy = to_itm.transform(row.lon, row.lat)
    if cells.empty:
        d = np.array([])
    else:
        mx, my = to_itm.transform(cells["lon"].to_numpy(),
                                  cells["lat"].to_numpy())
        d = np.hypot(mx - cx, my - cy)
    near = cells[d <= HAB_SEARCH_M] if len(d) else cells.iloc[0:0]

    # How much of the 1 km disc was even gridded, and how much had depth.
    n_mod = int(len(near))
    if n_mod == 0:
        return {"gap_cells_1km": 0, "gap_cells_in_range": 0,
                "gap_cells_extrap": 0, "gap_cells_on_reef": 0,
                "gap_cells_in_range_on_reef": 0, "gap_pos_in_range": 0,
                "gap_pos_extrap": 0, "gap_pos_in_range_on_reef": 0,
                "gap_max_suit_in_range": np.nan,
                "gap_max_suit_any": np.nan, "gap_on_mapped_reef": 0,
                "gap_evidence": "E5_no_bathymetry",
                "gap_answer": "no cell in the 1 km disc had all four "
                              "covariates (INFOMAR depth is the binding one) - "
                              "still UNASSESSED, which is not absence"}
    inr = near["in_training_range"].to_numpy(bool)
    reef = near["on_mapped_reef"].to_numpy(bool)
    s = near["suitability"].to_numpy(float)
    hot = s >= model.threshold
    pos_in = int((hot & inr).sum())
    pos_ex = int((hot & ~inr).sum())
    pos_in_reef = int((hot & inr & reef).sum())
    pos_in_off = int((hot & inr & ~reef).sum())
    n_in = int(inr.sum())
    n_in_reef = int((inr & reef).sum())

    # The rung reached depends on BOTH tests the step-2 application applies:
    # in the training range, and on mapped reef. "assessed" in step 2 means
    # both. Geogenic reef counts as mapped reef - it is hard substrate, which
    # is the model's entire training domain - but it carries no community
    # determination, which is exactly why these clusters are in the gap set.
    if n_in == 0:
        ev = "E4_extrapolation_only"
        ans = (f"all {n_mod} modelled cells sit outside the model's training "
               "range - labelled extrapolation, no defensible answer")
    elif pos_in_reef > 0:
        ev = "E2_model_assessed"
        ans = (f"{pos_in_reef} of {n_in_reef} in-range cells ON MAPPED REEF "
               f"score >= {model.threshold:.4f}. This is the step-2 assessed "
               "standard: substrate is mapped reef and the covariates are in "
               "range. It is a modelled presence, not a survey record")
    elif pos_in_off > 0:
        ev = "E3_model_offreef_inrange"
        ans = (f"{pos_in_off} of {n_in} in-range cells score >= "
               f"{model.threshold:.4f}, but none of them is on mapped reef: "
               "conditions resemble Laminaria ground while SUBSTRATE IS "
               "UNVERIFIED - never usable for an area or a euro figure")
    elif n_in_reef > 0:
        ev = "E0_model_absence_on_reef"
        ans = (f"0 of {n_in_reef} in-range cells on mapped reef reach "
               f"{model.threshold:.4f}: on ground that IS reef, conditions "
               "resemble the faunal-turf end of the training data rather "
               "than the Laminaria end")
    else:
        ev = "E0_model_absence_offreef"
        ans = (f"0 of {n_in} in-range cells reach {model.threshold:.4f}, and "
               "none is on mapped reef: modelled absence on unverified "
               "substrate, the weakest negative on the ladder")
    return {"gap_cells_1km": n_mod,
            "gap_cells_in_range": n_in,
            "gap_cells_extrap": int((~inr).sum()),
            "gap_cells_on_reef": int(reef.sum()),
            "gap_cells_in_range_on_reef": n_in_reef,
            "gap_pos_in_range": pos_in, "gap_pos_extrap": pos_ex,
            "gap_pos_in_range_on_reef": pos_in_reef,
            "gap_max_suit_in_range": round(float(s[inr].max()), 4)
                if n_in else np.nan,
            "gap_max_suit_any": round(float(s.max()), 4),
            "gap_on_mapped_reef": int(reef.sum()),
            "gap_evidence": ev, "gap_answer": ans}


# ----------------------------------------------------------------------
# 5. Main
# ----------------------------------------------------------------------

def main() -> int:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not IN_GAP.exists() or not IN_ALL.exists():
        print(f"Run src/national_receptor_screen.py first "
              f"({IN_GAP} / {IN_ALL} missing).")
        return 2
    print("Habitat-gap model - Part 2 of the national Phase A screen.")
    print("NO EURO VALUE IS COMPUTED HERE.\n")

    model = ModelV2()
    verification = model.verify()

    gap = pd.read_csv(IN_GAP)
    allc = pd.read_csv(IN_ALL)
    gap.to_csv(OUT_INPUT, index=False)
    print(f"  fetch-passing clusters with no NPWS mapping: {len(gap)}")
    if gap.empty:
        print("  nothing to model. Writing the merged table unchanged.")
        cells = pd.DataFrame()
        aois = []
    else:
        print(gap[["box", "county", "nearest_place", "lon", "lat",
                   "fetch_nearest_min", "fetch_nearest_max"]].to_string(index=False))
        aois = group_aois(gap)
        print(f"\n  grouped into {len(aois)} AOI grid(s) at {GRID_M:.0f} m")

        import geopandas as gpd
        npws = gpd.read_file(NPWS_SHP)
        keep = np.zeros(len(npws), dtype=bool)
        nb = npws.geometry.bounds
        for a in aois:
            x0, y0, x1, y1 = a["bbox"]
            keep |= ((nb["maxx"] >= x0) & (nb["minx"] <= x1)
                     & (nb["maxy"] >= y0) & (nb["miny"] <= y1)).to_numpy()
        # SUBTIDAL only, to match suitability_multisite.py exactly: its main()
        # filters layer 21 to Extent == Subtidal before reef_mask sees it. The
        # mask deliberately includes "geogenic reef" as well as the two
        # community-determined classes, because every one of them is hard
        # substrate and hard substrate is the model's whole training domain.
        npws_sub = npws[keep].copy()
        npws_sub = npws_sub[npws_sub["Extent"].astype(str).str.strip()
                            .str.lower() == "subtidal"]
        npws_itm = npws_sub.to_crs(ITM)
        print(f"  subtidal NPWS layer-21 polygons intersecting a gap AOI: "
              f"{len(npws_itm)}  (communities: "
              f"{sorted(set(npws_itm['Community'].astype(str).str.strip().str.lower()))})")

        to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
        # TIME BUDGET. INFOMAR's getSamples went to a hard HTTP 504 on
        # 2026-08-27 around 22:50 UTC, mid-run. Without a budget the script
        # would grind against a dead server and write NOTHING, so a service
        # outage would cost the whole deliverable. Instead: stop starting new
        # AOIs once the budget is spent, mark the untouched ones
        # `not_attempted`, and go on to write the outputs. Sampling is
        # resumable per batch, so re-running picks up exactly where this
        # stopped. Set GAP_BUDGET_MIN=0 for no budget.
        budget_min = float(os.environ.get("GAP_BUDGET_MIN", DEFAULT_BUDGET_MIN))
        t_start = time.monotonic()
        parts, attempted = [], 0
        for a in aois:
            spent = (time.monotonic() - t_start) / 60.0
            if budget_min and spent > budget_min:
                a["not_attempted"] = True
                continue
            a["not_attempted"] = False
            attempted += 1
            parts.append(run_aoi(a, model, npws_itm, to_itm))
        n_skipped = sum(1 for a in aois if a.get("not_attempted"))
        if n_skipped:
            print(f"\n  >>> TIME BUDGET ({budget_min:.0f} min) SPENT. "
                  f"{attempted} AOIs attempted, {n_skipped} NOT ATTEMPTED.")
            print("  >>> Those clusters are reported as E8_not_yet_modelled, "
                  "which is NOT a habitat finding. Re-run to continue.")
        parts = [p for p in parts if not p.empty]
        cells = (pd.concat(parts, ignore_index=True) if parts
                 else pd.DataFrame())

    if not cells.empty:
        cells.to_csv(OUT_CELLS, index=False)
        print(f"\n  written: {OUT_CELLS}  ({len(cells)} cells)")
    else:
        print("\n  no cell was predictable in any gap AOI.")

    # ---- per-cluster verdicts ----
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    verdicts = []
    skipped_names = {a["name"] for a in aois if a.get("not_attempted")}
    for r in gap.itertuples():
        my_aois = [a["name"] for a in aois if r.cluster in a["clusters"]]
        if my_aois and set(my_aois) <= skipped_names:
            # The AOI was never sampled because the time budget ran out, not
            # because anything was found. This must never read as absence.
            v = {"gap_cells_1km": 0, "gap_cells_in_range": 0,
                 "gap_cells_extrap": 0, "gap_cells_on_reef": 0,
                 "gap_cells_in_range_on_reef": 0, "gap_pos_in_range": 0,
                 "gap_pos_extrap": 0, "gap_pos_in_range_on_reef": 0,
                 "gap_max_suit_in_range": np.nan, "gap_max_suit_any": np.nan,
                 "gap_on_mapped_reef": 0,
                 "gap_evidence": "E8_not_yet_modelled",
                 "gap_answer": "NOT ATTEMPTED - the INFOMAR sampling budget "
                               "was spent before this AOI was reached. This is "
                               "a run-status flag, not a habitat finding. "
                               "Re-run src/habitat_gap_model.py to resolve it"}
        else:
            sub = cells[cells["aoi"].isin(my_aois)] \
                if not cells.empty else pd.DataFrame()
            v = cluster_verdict(r, sub, model, to_itm)
        v.update({"cluster": r.cluster, "box": r.box, "county": r.county,
                  "nearest_place": r.nearest_place, "lon": r.lon, "lat": r.lat,
                  "n_buildings_200m": r.n_buildings_200m,
                  "fetch_nearest_min": r.fetch_nearest_min,
                  "fetch_nearest_max": r.fetch_nearest_max,
                  "pass_fetch_strict": r.pass_fetch_strict})
        verdicts.append(v)
    vdf = pd.DataFrame(verdicts)
    if not vdf.empty:
        cols = ["box", "county", "nearest_place", "cluster", "lon", "lat",
                "n_buildings_200m", "fetch_nearest_min", "fetch_nearest_max",
                "pass_fetch_strict", "gap_cells_1km", "gap_cells_in_range",
                "gap_cells_extrap", "gap_cells_on_reef",
                "gap_cells_in_range_on_reef", "gap_pos_in_range",
                "gap_pos_in_range_on_reef", "gap_pos_extrap",
                "gap_max_suit_in_range", "gap_max_suit_any",
                "gap_on_mapped_reef", "gap_evidence", "gap_answer"]
        vdf = vdf[cols]
        vdf.to_csv(OUT_CLUST, index=False)
        print(f"  written: {OUT_CLUST}")
        pd.set_option("display.width", 250)
        print("\n" + "=" * 110)
        print(vdf[["box", "nearest_place", "lon", "lat", "gap_cells_1km",
                   "gap_cells_in_range", "gap_pos_in_range",
                   "gap_max_suit_in_range", "gap_evidence"]].to_string(index=False))
        print("=" * 110)

    # ---- the deliverable: merged national ranked table ----
    merged = allc.merge(
        vdf.drop(columns=[c for c in ("box", "county", "nearest_place", "lon",
                                      "lat", "n_buildings_200m",
                                      "fetch_nearest_min", "fetch_nearest_max",
                                      "pass_fetch_strict")
                          if c in vdf.columns]),
        on="cluster", how="left") if not vdf.empty else allc.copy()

    # Part 1 states that were never modelled, because only fetch-passing
    # clusters were handed to Part 2. The label says so rather than implying
    # an answer that was never computed.
    UNMODELLED = {
        "surveyed_not_laminaria": "E1n_surveyed_not_laminaria",
        "reef_mapped_community_undetermined":
            "E6_reef_mapped_community_undetermined_not_modelled",
        "modelled_no_laminaria": "E0_model_absence_westcork_aoi",
        "unmapped": "E7_unmapped_not_modelled",
    }

    def evidence_class(r) -> str:
        # Part 2's answer wins wherever it exists: it is strictly more
        # informative than the blank it replaces.
        ge = r.get("gap_evidence")
        if isinstance(ge, str) and ge:
            return ge
        if r.get("habitat_evidence") == "laminaria_present":
            if r.get("npws_lam_ha_1km", 0) and r["npws_lam_ha_1km"] > 0:
                q = r.get("npws_mapping_quality", "")
                return f"E1_npws_laminaria_{q}" if q else "E1_npws_laminaria"
            return "E2_model_assessed"       # step-2 West Cork tier-2 cells
        return UNMODELLED.get(r.get("habitat_evidence"), "E9_unclassified")

    merged["evidence_class"] = merged.apply(evidence_class, axis=1)
    # A SURVEY RECORD, as opposed to a model output. Only the NPWS CO Series
    # classes qualify. Kept separate so the two are never conflated on a slide.
    merged["evidence_is_survey_record"] = merged["evidence_class"].str.startswith(
        ("E1_npws", "E1n_"))
    # Good enough to carry an area into a Phase B valuation. E2 is a MODELLED
    # presence on mapped reef - the same standard the locked 1.75 ha Sherkin
    # bed was built on - so it qualifies, but it needs survey confirmation
    # before any euro is attached to it.
    merged["habitat_for_valuation"] = merged["evidence_class"].str.startswith(
        ("E1_npws", "E2_"))
    merged["phaseB_eligible"] = (merged["habitat_for_valuation"]
                                 & merged["pass_fetch_strict"])
    merged = merged.sort_values(
        ["phaseB_eligible", "candidate", "pass_fetch_strict", "pass_fetch",
         "fetch_nearest_max", "npws_lam_ha_1km"],
        ascending=[False, False, False, False, False, False]).reset_index(drop=True)
    merged.insert(0, "rank", np.arange(1, len(merged) + 1))
    merged.to_csv(OUT_TABLE, index=False)
    print(f"\n  written: {OUT_TABLE}  ({len(merged)} clusters ranked)")

    summary = {
        "run_utc": t0,
        "note": "Phase A Part 2. No euro value computed. E3/E4/E5 cells are "
                "never usable for an area or a euro figure.",
        "model": {
            "source": str(MODEL_REPORT),
            "reconstructed_not_refitted": True,
            "verification_against_stored_step2_predictions": verification,
            "operating_threshold": model.threshold,
            "training_ranges": {f: list(model.ranges[f]) for f in FEATURES},
            "intercept_used": model.intercept,
            "intercept_rule": "mean of the five training-site intercepts, as "
                              "suitability_multisite.py does for an unseen site; "
                              "probabilities are therefore uncalibrated and only "
                              "the ranking transfers",
        },
        "parameters": {"GRID_M": GRID_M, "AOI_MARGIN_M": AOI_MARGIN_M,
                       "AOI_GROUP_EPS_M": AOI_GROUP_EPS_M,
                       "HAB_SEARCH_M": HAB_SEARCH_M,
                       "FETCH_EXCLUSION_MAX": FETCH_EXCLUSION_MAX,
                       "fetch_gate_untouched": True},
        "aois": [{"name": a["name"], "bbox": [round(v, 5) for v in a["bbox"]],
                  "county": a["county"], "box": a["box"],
                  "clusters": a["clusters"], "places": a["places"],
                  "points_never_answered": a.get("points_never_answered", 0)}
                 for a in aois],
        "aois_with_unanswered_points": [
            a["name"] for a in aois if a.get("points_never_answered", 0)],
        "aois_not_attempted": [a["name"] for a in aois
                               if a.get("not_attempted")],
        "run_complete": not any(a.get("not_attempted")
                                or a.get("points_never_answered", 0)
                                for a in aois),
        "results": {
            "gap_clusters_in": int(len(gap)),
            "aois": len(aois),
            "cells_modelled": int(len(cells)) if not cells.empty else 0,
            "cells_in_training_range": int(cells["in_training_range"].sum())
                if not cells.empty else 0,
            "cells_positive_in_range": int(
                ((cells["suitability"] >= model.threshold)
                 & (cells["in_training_range"] == 1)).sum())
                if not cells.empty else 0,
            "cells_on_mapped_reef": int(cells["on_mapped_reef"].sum())
                if not cells.empty else 0,
            "gap_evidence_counts": (vdf["gap_evidence"].value_counts().to_dict()
                                    if not vdf.empty else {}),
            "national_evidence_class_counts":
                merged["evidence_class"].value_counts().to_dict(),
            "clusters_with_a_survey_record":
                int(merged["evidence_is_survey_record"].sum()),
            "habitat_for_valuation": int(merged["habitat_for_valuation"].sum()),
            "phaseB_eligible": int(merged["phaseB_eligible"].sum()),
            "phaseB_eligible_sites": merged[merged["phaseB_eligible"]][
                ["box", "county", "nearest_place", "lon", "lat",
                 "evidence_class", "fetch_nearest_min", "npws_lam_ha_1km"]
            ].to_dict("records"),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary["results"], indent=2))
    print(f"\nVERDICT: {int(merged['phaseB_eligible'].sum())} cluster(s) on the "
          "whole searched Irish Atlantic coast have Laminaria evidence good "
          "enough for valuation AND pass the strict fetch gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
