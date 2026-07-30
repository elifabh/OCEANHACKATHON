#!/usr/bin/env python3
"""
suitability_model.py - the subtidal kelp suitability model. Build step 2 of 7.

Everything here follows from the diagnostics, and none of it is a free choice.

  LABELS. npws_labels.py established that NPWS layer 21 mapping is PATCHY, so
  an unlabelled cell is an unknown, not an absence. Training therefore uses
  ONLY labelled polygons:
      presence  = Community "Laminaria-dominated reef", Extent Subtidal
      negative  = Community "Faunal turf reef",         Extent Subtidal
  Unlabelled cells never enter the fit, in either class. Geogenic Reef is
  excluded: it is an origin word, not a community word, and mizen_outer carries
  it with no community label at all, so treating it as "no kelp" would be the
  exact mistake this whole analysis exists to avoid.

  PREDICTORS. covariate_check.py measured slope and curvature to be
  uncorrelated (Spearman -0.085) with each retaining separating power after the
  other's contribution is removed, so both stay. Kenmare's internal exposure
  range (11x) is comparable to the between-AOI range (8.7x), so fetch is
  testable at the training site and stays. Depth stays, with the caveat below.
      depth (m below LAT)  ·  slope (deg)  ·  curvature  ·  log10 fetch

  THE DEPTH CAVEAT, WHICH MUST TRAVEL WITH EVERY NUMBER THIS SCRIPT PRINTS.
  circularity_check.py found the kelp/faunal-turf boundary is PARTLY drawn on
  the 20 m contour: 41% of the shared boundary sits within 3 m of 20 m against
  7% of a control boundary. So depth's predictive power is partly a recovery of
  the surveyors' own delineation rule rather than an ecological discovery. The
  model still needs depth - kelp really is light-limited - but the result must
  never be presented as "we predict kelp from depth". Run with --no-depth to
  see what the other three covariates achieve alone; both are reported.

  VALIDATION. Roberts et al. (2017) Ecography 40:913-929: with spatially
  autocorrelated data, random k-fold cross-validation severely underestimates
  prediction error, and blocks must be at least as large as the autocorrelation
  range. Our coarsest predictor is the Burrows fetch layer at 200 m native, so
  blocks are 1 km by default - five times that. Random k-fold is computed too,
  and printed beside the blocked figure, because the gap between them is the
  thing a jury should be shown rather than the flattering number alone.

  EXTRAPOLATION. Kenmare's most exposed labelled cell is about 15.6 km/sector
  of fetch. The medians at sherkin_baltimore and mizen_outer are about 67 -
  four times higher. Predicting there is extrapolation, which is where models
  fail most confidently. Every predicted cell therefore carries an
  in_training_range flag, cells outside it are reported separately, and they
  must be excluded from any area or euro figure downstream.

  EXTERNAL TEST. Roaringwater has essentially no mapped Laminaria but does have
  234 Faunal turf polygons across sherkin_baltimore and inner_roaringwater.
  Those are real negatives the model never saw. There are no external
  positives, so the external test is one-sided: it can measure a false-positive
  rate and nothing else. Stated as such.

  PRE-REGISTERED ACCEPTANCE CRITERIA. Written before the model was run so the
  verdict cannot be tuned to the result. See ACCEPTANCE below. A failure is
  reported as a failure.

The model is a logistic regression fitted by iteratively reweighted least
squares with a small ridge penalty. Implemented here in numpy rather than
imported, for three reasons: it adds no dependency, the coefficients on
standardised predictors are directly readable as effect sizes for a
non-technical audience, and a 40-line fit that can be checked line by line is
worth more to a jury than a call into a library.

Dependencies: numpy (BSD-3), geopandas (BSD-3), shapely (BSD-3), pyproj (MIT),
rasterio (BSD-3). All to DEPENDENCIES.md with versions.

Data: NPWS Reef Inventory 2023 layer 21; INFOMAR bathymetry (GSI & Marine
Institute) CC BY 4.0; Burrows wave fetch (LICENCE STILL UNREAD - this script
writes that warning into its own output).

Usage:
    python src/suitability_model.py --selftest
    python src/suitability_model.py \
        --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp" \
        --fetch data/fetch/log10_eu200m1a.tif
    python src/suitability_model.py --shp "<path>" --fetch "<tif>" --no-depth
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

OUT_DIR = Path("outputs/model")

try:
    from common import AOIS, CRS_FOR_AREA
    HAVE_COMMON = True
except ImportError:                                       # pragma: no cover
    HAVE_COMMON = False
    CRS_FOR_AREA = 2157
    AOIS = {
        "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
        "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
        "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
        "kenmare_river": [-9.93, 51.75, -9.78, 51.81],
    }

from circularity_check import (auc_separation, class_mask, grid_axes, norm,
                               sample_depth_grid, sample_fetch_grid, terrain)

TRAIN_AOI = "kenmare_river"
APPLY_AOIS = ("sherkin_baltimore", "inner_roaringwater", "mizen_outer")
GRID_M_DEFAULT = 50.0
BLOCK_M_DEFAULT = 1000.0        # 5x the 200 m fetch layer
N_FOLDS = 5
SEED = 20261016                 # the first day of the hackathon; arbitrary but fixed
RIDGE = 1e-3
MAX_IRLS = 50

# Range within which a prediction is called interpolation rather than
# extrapolation: the 1st to 99th percentile of each training predictor.
RANGE_PCT = (1.0, 99.0)
DECISION_THRESHOLD = 0.5

ACCEPTANCE = {
    "blocked_auc_min": 0.70,
    "external_false_positive_max": 0.30,
    "inner_roaringwater_must_score_below_kenmare_kelp": True,
    "random_minus_blocked_auc_warn_above": 0.05,
}


# ---------------------------------------------------------------------------
# Logistic regression, IRLS with ridge
# ---------------------------------------------------------------------------

def fit_logistic(X: np.ndarray, y: np.ndarray, ridge: float = RIDGE):
    """Newton / IRLS fit. X has no intercept column; one is added here.

    The ridge term is small and exists for one reason: with a predictor that
    separates the classes almost perfectly the unpenalised likelihood has no
    finite maximum and the coefficients run away to infinity. That is exactly
    our situation - depth alone reaches AUC 0.95 - so an unpenalised fit would
    either fail to converge or return meaningless magnitudes.
    """
    n, k = X.shape
    Xd = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = ridge * np.eye(k + 1)
    pen[0, 0] = 0.0                      # never penalise the intercept

    for _ in range(MAX_IRLS):
        eta = Xd @ beta
        p = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        w = np.clip(p * (1.0 - p), 1e-8, None)
        z = eta + (y - p) / w
        WX = Xd * w[:, None]
        H = Xd.T @ WX + pen
        # Newton step for the PENALISED likelihood reduces exactly to this:
        #   (X'WX + P) b_new = X'Wz    with   z = eta + (y - p)/w
        # so no separate penalty term appears on the right-hand side.
        g = Xd.T @ (w * z)
        try:
            new = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(new)):
            break
        step = np.max(np.abs(new - beta))
        beta = new
        if step < 1e-8:
            break
    return beta


def predict_proba(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    eta = beta[0] + X @ beta[1:]
    return 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """AUC as P(score of a positive > score of a negative), ties at one half."""
    pos = p[y == 1].tolist()
    neg = p[y == 0].tolist()
    if not pos or not neg:
        return float("nan")
    # auc_separation folds direction; here direction is known and meaningful,
    # so compute it unfolded and keep the sign.
    from circularity_check import _auc_lower
    return 1.0 - _auc_lower(pos, neg)


# ---------------------------------------------------------------------------
# Spatial blocks
# ---------------------------------------------------------------------------

def block_ids(lon, lat, transformer, block_m: float) -> np.ndarray:
    """Assign each point to a square block of side block_m, in projected metres."""
    x, y = transformer.transform(list(lon), list(lat))
    x = np.asarray(x)
    y = np.asarray(y)
    bx = np.floor(x / block_m).astype(np.int64)
    by = np.floor(y / block_m).astype(np.int64)
    return bx * 1_000_000 + by


def assign_folds(blocks: np.ndarray, n_folds: int, seed: int) -> np.ndarray:
    """Whole blocks to folds, so no fold shares a block with another."""
    uniq = np.unique(blocks)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(uniq.size)
    fold_of_block = {int(uniq[perm[i]]): i % n_folds for i in range(uniq.size)}
    return np.array([fold_of_block[int(b)] for b in blocks])


def cv_auc(X, y, folds, n_folds: int) -> tuple[float, list]:
    """Out-of-fold AUC. Each fold is predicted by a model that never saw it."""
    oof = np.full(y.size, np.nan)
    per_fold = []
    for f in range(n_folds):
        tr, te = folds != f, folds == f
        if te.sum() == 0 or tr.sum() < 10:
            per_fold.append(None)
            continue
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            per_fold.append(None)      # a fold with one class cannot be scored
            continue
        b = fit_logistic(X[tr], y[tr])
        oof[te] = predict_proba(b, X[te])
        per_fold.append(round(auc(y[te], predict_proba(b, X[te])), 4))
    ok = np.isfinite(oof)
    return (auc(y[ok], oof[ok]) if ok.sum() else float("nan")), per_fold


# ---------------------------------------------------------------------------
# Feature assembly
# ---------------------------------------------------------------------------

FEATURES_ALL = ("depth_m", "slope_deg", "curvature", "log10_fetch")


def build_grid(name, bbox, grid_m, gdf, to_itm, fetch_path, use_cache=True,
               depth_fn=None):
    """Per-cell predictors, class label and coordinates for one AOI."""
    depth = sample_depth_grid(name, bbox, grid_m, use_cache=use_cache,
                              depth_fn=depth_fn)
    slope, curv = terrain(depth, grid_m)
    fetch = (sample_fetch_grid(fetch_path, bbox, grid_m)
             if fetch_path is not None else np.full_like(depth, np.nan))
    mask, conflicts = class_mask(bbox, grid_m, gdf, to_itm)

    lons, lats, _, _ = grid_axes(bbox, grid_m)
    LON, LAT = np.meshgrid(lons, lats)
    return {"name": name, "depth_m": depth, "slope_deg": slope,
            "curvature": curv, "log10_fetch": fetch, "mask": mask,
            "lon": LON, "lat": LAT, "conflicts": conflicts,
            "grid_m": grid_m}


def flatten(g, features, labelled_only: bool):
    """Flatten a grid dict to rows with every feature present."""
    ok = np.ones(g["depth_m"].shape, dtype=bool)
    for f in features:
        ok &= np.isfinite(g[f])
    if labelled_only:
        ok &= (g["mask"] == 1) | (g["mask"] == 2)
    X = np.column_stack([g[f][ok] for f in features])
    y = (g["mask"][ok] == 1).astype(float)
    return X, y, g["lon"][ok], g["lat"][ok], g["mask"][ok], ok


# ---------------------------------------------------------------------------
# Extrapolation
# ---------------------------------------------------------------------------

def training_ranges(X, features):
    lo = np.percentile(X, RANGE_PCT[0], axis=0)
    hi = np.percentile(X, RANGE_PCT[1], axis=0)
    return {f: (float(lo[i]), float(hi[i])) for i, f in enumerate(features)}


def in_range(X, ranges, features):
    """Boolean per row, plus the per-feature share of rows outside the range."""
    inside = np.ones(X.shape[0], dtype=bool)
    detail = {}
    for i, f in enumerate(features):
        lo, hi = ranges[f]
        okf = (X[:, i] >= lo) & (X[:, i] <= hi)
        detail[f] = round(1.0 - float(okf.mean()), 4)
        inside &= okf
    return inside, detail


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    print("SELFTEST (no network, no files)\n")
    rng = np.random.default_rng(1)

    # --- IRLS must recover known coefficients -----------------------------
    n = 4000
    Xs = rng.normal(size=(n, 2))
    true = np.array([-0.4, 1.5, -0.8])
    p = 1.0 / (1.0 + np.exp(-(true[0] + Xs @ true[1:])))
    ys = (rng.random(n) < p).astype(float)
    b = fit_logistic(Xs, ys)
    assert np.max(np.abs(b - true)) < 0.15, (b, true)
    print(f"  IRLS recovers coefficients: got "
          f"[{b[0]:+.2f} {b[1]:+.2f} {b[2]:+.2f}] "
          f"vs true [{true[0]:+.2f} {true[1]:+.2f} {true[2]:+.2f}]  ok")

    # Perfectly separable data must not blow up. Without the ridge the
    # likelihood has no finite maximum, which is our real situation.
    Xsep = np.linspace(-3, 3, 400).reshape(-1, 1)
    ysep = (Xsep[:, 0] > 0).astype(float)
    bsep = fit_logistic(Xsep, ysep)
    assert np.all(np.isfinite(bsep)), bsep
    assert auc(ysep, predict_proba(bsep, Xsep)) > 0.99
    print(f"  separable data: finite coefficients ({bsep[1]:.1f}), AUC "
          f"{auc(ysep, predict_proba(bsep, Xsep)):.3f}  ok")

    # --- AUC direction ----------------------------------------------------
    yy = np.array([1, 1, 0, 0], dtype=float)
    assert auc(yy, np.array([0.9, 0.8, 0.2, 0.1])) == 1.0
    assert auc(yy, np.array([0.1, 0.2, 0.8, 0.9])) == 0.0
    assert auc(yy, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5
    print("  auc: correct=1.0, inverted=0.0, all-tied=0.5  ok")

    # --- blocks and folds -------------------------------------------------
    from pyproj import Transformer
    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)
    lon = np.repeat(np.linspace(-9.93, -9.78, 40), 40)
    lat = np.tile(np.linspace(51.75, 51.81, 40), 40)
    bl = block_ids(lon, lat, to_itm, 1000.0)
    fo = assign_folds(bl, N_FOLDS, SEED)
    # no block may be split across folds - that is the entire point
    for bb in np.unique(bl):
        assert len(np.unique(fo[bl == bb])) == 1, bb
    assert len(np.unique(fo)) == N_FOLDS
    print(f"  spatial blocks: {np.unique(bl).size} blocks, "
          f"{N_FOLDS} folds, no block split across folds  ok")
    # a 1 km block must be coarser than the 50 m grid by the expected factor
    assert np.unique(bl).size < lon.size / 4
    print("  block size is coarser than the sample spacing  ok")

    # --- THE test that justifies blocking -----------------------------
    # Spatially autocorrelated label, and a model given enough spatial terms
    # to memorise position. Random k-fold then interleaves training cells among
    # the test cells and the memorisation pays off; blocked k-fold holds whole
    # regions out and it does not. If the two agreed, the blocking machinery
    # would be doing nothing and the whole validation design would be theatre.
    #
    # NOTE FOR THE REAL MODEL, and it must not be misread: our actual model has
    # four linear terms and no spatial terms, so it has very little capacity to
    # memorise position, and its random-vs-blocked gap will be much smaller
    # than this fixture's - measured at about 0.025 with a single global
    # predictor. A small gap is therefore EXPECTED and is not evidence that
    # blocking was unnecessary; the blocked figure is still the honest one,
    # because the reason to block is that the samples are not independent, not
    # that the gap happens to be large.
    side = 60
    yy_, xx_ = np.mgrid[0:side, 0:side].astype(float)
    patch = np.sin(xx_ / 7.0) + np.sin(yy_ / 7.0)
    label = (patch + rng.normal(0, 0.4, (side, side)) > 0).astype(float).ravel()
    smooth = (patch + rng.normal(0, 0.9, (side, side))).ravel()
    lon_g = -9.93 + xx_.ravel() * 0.0007
    lat_g = 51.75 + yy_.ravel() * 0.00045

    xs = (xx_.ravel() - xx_.mean()) / xx_.std()
    ys = (yy_.ravel() - yy_.mean()) / yy_.std()
    feat = np.column_stack([smooth, xs, ys, xs ** 2, ys ** 2, xs * ys,
                            xs ** 3, ys ** 3])

    bl2 = block_ids(lon_g, lat_g, to_itm, 1500.0)
    fo_block = assign_folds(bl2, N_FOLDS, SEED)
    fo_random = np.random.default_rng(SEED).integers(0, N_FOLDS, label.size)
    a_block, _ = cv_auc(feat, label, fo_block, N_FOLDS)
    a_random, _ = cv_auc(feat, label, fo_random, N_FOLDS)
    print(f"  autocorrelated fixture: random k-fold AUC {a_random:.3f}, "
          f"blocked {a_block:.3f}")
    assert a_random - a_block > 0.05, (a_random, a_block)
    print(f"  random k-fold is optimistic by {a_random - a_block:.3f} - "
          f"blocking is doing work  ok")

    # And the gap must NOT appear when there is nothing spatial to leak. Without
    # this control the assertion above could be satisfied by any difference
    # between the two fold schemes rather than by autocorrelation.
    flat_feat = rng.normal(size=(side * side, 8))
    flat_lab = (rng.random(side * side) < 0.5).astype(float)
    fb_, _ = cv_auc(flat_feat, flat_lab, fo_block, N_FOLDS)
    fr_, _ = cv_auc(flat_feat, flat_lab, fo_random, N_FOLDS)
    assert abs(fr_ - fb_) < 0.05, (fr_, fb_)
    print(f"  with no spatial structure the two agree ({fr_:.3f} vs {fb_:.3f})"
          f" - the gap above is autocorrelation, not an artefact  ok")

    # --- extrapolation flag ----------------------------------------------
    Xtr = rng.normal(size=(500, 2))
    rngs = training_ranges(Xtr, ("a", "b"))
    Xte = np.array([[0.0, 0.0], [99.0, 0.0], [0.0, -99.0]])
    inside, detail = in_range(Xte, rngs, ("a", "b"))
    assert inside.tolist() == [True, False, False], inside
    assert detail["a"] > 0 and detail["b"] > 0, detail
    # and a point set entirely inside must flag nothing, or the test above only
    # shows the function can say "outside"
    inside2, detail2 = in_range(Xtr, rngs, ("a", "b"))
    assert inside2.mean() > 0.9, inside2.mean()
    print(f"  extrapolation flag: out-of-range caught, in-range not flagged "
          f"({inside2.mean():.0%} inside)  ok")

    # --- cv_auc must refuse a fold with only one class --------------------
    y1 = np.concatenate([np.ones(50), np.zeros(50)])
    f1 = np.concatenate([np.zeros(50), np.ones(50)]).astype(int)  # fold=class
    a1, per1 = cv_auc(rng.normal(size=(100, 1)), y1, f1, 2)
    assert all(v is None for v in per1), per1
    assert a1 != a1, a1          # NaN, not a fabricated number
    print("  cv_auc: a fold containing one class is skipped, not scored  ok")

    print("\nSELFTEST PASSED. IRLS recovers known coefficients and survives")
    print("separable data, AUC has the right sign, spatial blocks are never")
    print("split across folds, blocked CV is measurably stricter than random")
    print("CV on autocorrelated data, the extrapolation flag works in both")
    print("directions, and a single-class fold is refused rather than scored.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Subtidal kelp suitability model, trained at Kenmare and "
                    "applied at Roaringwater.")
    ap.add_argument("--shp", type=Path)
    ap.add_argument("--fetch", type=Path)
    ap.add_argument("--grid", type=float, default=GRID_M_DEFAULT)
    ap.add_argument("--block", type=float, default=BLOCK_M_DEFAULT,
                    help=f"spatial block side in metres (default "
                         f"{BLOCK_M_DEFAULT:.0f}; must exceed the 200 m fetch "
                         f"layer's own resolution)")
    ap.add_argument("--no-depth", action="store_true",
                    help="drop depth, to see what the other covariates achieve "
                         "without the partly-circular term")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not HAVE_COMMON:
        print("cannot import common.py - run from the repo root.")
        return 2
    if not args.shp or not args.shp.exists():
        print("--shp is required and must exist (quote it, it has a space)")
        return 2
    if not args.fetch or not args.fetch.exists():
        print("--fetch is required: log10 fetch is one of the four predictors.")
        return 2
    if args.block <= 200.0:
        print(f"--block {args.block:.0f} m is not larger than the 200 m fetch")
        print("layer. Blocks that small share fetch values across folds and")
        print("the validation would be optimistic. Refusing.")
        return 2

    import geopandas as gpd
    from pyproj import Transformer

    features = tuple(f for f in FEATURES_ALL
                     if not (args.no_depth and f == "depth_m"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)

    print("Subtidal kelp suitability model - build step 2 of 7.")
    print("NPWS layer 21 x INFOMAR bathymetry (GSI & Marine Institute, "
          "CC BY 4.0).")
    print("Wave fetch: Burrows, figshare. LICENCE STILL UNREAD - nothing from "
          "this run may be published until it is.")
    print(f"Predictors: {', '.join(features)}")
    if args.no_depth:
        print("  (--no-depth: the partly-circular depth term is EXCLUDED)")
    print(f"Grid {args.grid:.0f} m, spatial blocks {args.block:.0f} m, "
          f"{N_FOLDS} folds, seed {SEED}.\n")

    gdf = gpd.read_file(args.shp)
    if gdf.crs is None:
        print("  >>> no CRS on the layer. Stopping.")
        return 2
    gdf = gdf.to_crs(epsg=CRS_FOR_AREA)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    bad = ~gdf.geometry.is_valid
    if int(bad.sum()):
        gdf.loc[bad, "geometry"] = gdf.loc[bad].geometry.buffer(0)
    if "Extent" in gdf.columns:
        gdf = gdf[gdf["Extent"].map(norm).str.lower() == "subtidal"].copy()

    # ---------------- training ----------------
    print("=" * 74)
    print(f"TRAINING SET  {TRAIN_AOI}")
    print("=" * 74)
    gtr = build_grid(TRAIN_AOI, AOIS[TRAIN_AOI], args.grid, gdf, to_itm,
                     args.fetch)
    X, y, lon, lat, _, _ = flatten(gtr, features, labelled_only=True)
    print(f"  cells with every predictor and a label: {y.size}"
          f"   kelp {int(y.sum())}, faunal turf {int((1 - y).sum())}")
    if gtr["conflicts"]:
        print(f"  >>> {gtr['conflicts']} cells were claimed by both classes "
              f"and dropped")
    if y.size < 200 or y.sum() < 50 or (1 - y).sum() < 50:
        print("  >>> training set too small to fit anything trustworthy.")
        return 2

    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Xz = (X - mu) / sd

    beta = fit_logistic(Xz, y)
    print(f"\n  standardised coefficients (per 1 SD of the predictor):")
    print(f"    {'intercept':<16}{beta[0]:>+9.3f}")
    for i, f in enumerate(features):
        print(f"    {f:<16}{beta[i + 1]:>+9.3f}")
    big = [f for i, f in enumerate(features) if abs(beta[i + 1]) > 8.0]
    if big:
        print(f"\n  >>> LARGE COEFFICIENTS on {big}. That is the signature of")
        print("  >>> near-perfect separation: the likelihood has almost no")
        print("  >>> finite maximum and only the small ridge penalty is")
        print("  >>> keeping the numbers bounded. The ranking is still valid,")
        print("  >>> so AUC and the map are fine, but the magnitudes must NOT")
        print("  >>> be read as effect sizes and must not go on a slide as a")
        print("  >>> bar chart of importance.")
    print("  >>> Sign convention: positive means MORE kelp-like. Depth is")
    print("  >>> metres below LAT, so a negative depth coefficient means")
    print("  >>> shallower is more kelp-like, which is the expected direction.")

    # ---------------- validation ----------------
    print("\n" + "=" * 74)
    print("VALIDATION")
    print("=" * 74)
    blocks = block_ids(lon, lat, to_itm, args.block)
    folds_b = assign_folds(blocks, N_FOLDS, SEED)
    folds_r = np.random.default_rng(SEED).integers(0, N_FOLDS, y.size)

    a_block, per_b = cv_auc(Xz, y, folds_b, N_FOLDS)
    a_rand, _ = cv_auc(Xz, y, folds_r, N_FOLDS)
    a_insample = auc(y, predict_proba(beta, Xz))

    print(f"  spatial blocks: {np.unique(blocks).size} of "
          f"{args.block:.0f} m, cells per block "
          f"{y.size / max(np.unique(blocks).size, 1):.0f}")
    print(f"\n  in-sample AUC                 {a_insample:.3f}   "
          "(not a performance figure - the model has seen these cells)")
    print(f"  random {N_FOLDS}-fold AUC             {a_rand:.3f}   "
          "(OPTIMISTIC - folds share spatial neighbours)")
    print(f"  BLOCKED {N_FOLDS}-fold AUC            {a_block:.3f}   "
          "<-- the honest number")
    print(f"  per-fold blocked AUC          {per_b}")

    gap = (a_rand - a_block) if (a_rand == a_rand and a_block == a_block) else 0
    if gap > ACCEPTANCE["random_minus_blocked_auc_warn_above"]:
        print(f"\n  >>> random CV is {gap:.3f} higher than blocked CV. That gap")
        print("  >>> IS spatial autocorrelation (Roberts et al. 2017). Quote")
        print("  >>> the blocked figure only; the random one is not a")
        print("  >>> performance estimate.")

    # depth-only baseline on the same folds, for comparison
    base = {}
    if "depth_m" in features:
        di = features.index("depth_m")
        a_depth, _ = cv_auc(Xz[:, [di]], y, folds_b, N_FOLDS)
        base["depth_only_blocked_auc"] = round(a_depth, 4)
        print(f"\n  depth-only baseline, same blocks   {a_depth:.3f}")
        print(f"  full model                        {a_block:.3f}   "
              f"gain {a_block - a_depth:+.3f}")
        if a_block - a_depth < 0.02:
            print("  >>> The extra covariates add almost nothing over depth")
            print("  >>> alone. Report the depth-only model as the product and")
            print("  >>> say so - a multi-term model whose terms do no work is")
            print("  >>> worse than a one-term model that is labelled as one.")
        print("  >>> AND REMEMBER: the depth term is partly the surveyors' own")
        print("  >>> 20 m delineation rule (41% of the class boundary sits")
        print("  >>> within 3 m of 20 m). Do not present it as a discovery.")

    # ---------------- apply ----------------
    print("\n" + "=" * 74)
    print("APPLICATION  Roaringwater")
    print("=" * 74)
    ranges = training_ranges(X, features)
    print("  training range of each predictor "
          f"(p{RANGE_PCT[0]:.0f}-p{RANGE_PCT[1]:.0f}):")
    for f in features:
        print(f"    {f:<16}{ranges[f][0]:>10.3f}  to {ranges[f][1]:>10.3f}")

    rows, summaries, ext_pos, ext_n = [], [], 0, 0
    for name in APPLY_AOIS:
        print(f"\n  --- {name} ---")
        g = build_grid(name, AOIS[name], args.grid, gdf, to_itm, args.fetch)
        Xa, ya, lo_a, la_a, mk, _ = flatten(g, features, labelled_only=False)
        if Xa.shape[0] == 0:
            print("    no cell has every predictor here. Nothing predicted.")
            summaries.append({"aoi": name, "cells": 0})
            continue
        inside, detail = in_range(Xa, ranges, features)
        pr = predict_proba(beta, (Xa - mu) / sd)

        cell_ha = (args.grid ** 2) / 1e4
        print(f"    cells predicted            {Xa.shape[0]}"
              f"  ({Xa.shape[0] * cell_ha:.0f} ha)")
        print(f"    inside the training range  {int(inside.sum())}"
              f"  ({inside.mean():.0%})")
        for f, share in detail.items():
            if share > 0.10:
                print(f"      {f}: {share:.0%} of cells outside the range")
        if inside.mean() < 0.25:
            print("    >>> MOSTLY EXTRAPOLATION. Predictions here are not")
            print("    >>> supported by the training data. They may be shown")
            print("    >>> greyed out but must NOT enter any area or euro")
            print("    >>> figure.")
        if inside.sum():
            print(f"    suitability inside range   median "
                  f"{np.median(pr[inside]):.3f}, "
                  f"p90 {np.percentile(pr[inside], 90):.3f}")

        # external negatives: cells NPWS labelled Faunal turf, never trained on
        neg = mk == 2
        if neg.sum() >= 30:
            usable = neg & inside
            if usable.sum() >= 30:
                fp = float((pr[usable] > DECISION_THRESHOLD).mean())
                ext_pos += int((pr[usable] > DECISION_THRESHOLD).sum())
                ext_n += int(usable.sum())
                print(f"    EXTERNAL NEGATIVES (Faunal turf, in range): "
                      f"{int(usable.sum())} cells, "
                      f"{fp:.1%} scored above {DECISION_THRESHOLD}")
            else:
                print(f"    external negatives present ({int(neg.sum())}) but "
                      f"only {int(usable.sum())} inside the training range - "
                      f"too few to score")

        for k in range(Xa.shape[0]):
            rows.append({"aoi": name, "lon": round(float(lo_a[k]), 6),
                         "lat": round(float(la_a[k]), 6),
                         "suitability": round(float(pr[k]), 4),
                         "in_training_range": int(inside[k]),
                         "npws_label": int(mk[k])})
        summaries.append({
            "aoi": name, "cells": int(Xa.shape[0]),
            "ha": round(Xa.shape[0] * cell_ha, 1),
            "share_in_training_range": round(float(inside.mean()), 4),
            "out_of_range_by_feature": detail,
            "median_suitability_in_range": (round(float(np.median(pr[inside])), 4)
                                            if inside.sum() else None)})

    # ---------------- acceptance ----------------
    print("\n" + "=" * 74)
    print("PRE-REGISTERED ACCEPTANCE CRITERIA")
    print("=" * 74)
    results = {}

    ok1 = a_block == a_block and a_block >= ACCEPTANCE["blocked_auc_min"]
    print(f"  1. blocked AUC >= {ACCEPTANCE['blocked_auc_min']:.2f}"
          f"                 {a_block:.3f}   {'PASS' if ok1 else 'FAIL'}")
    results["blocked_auc"] = {"value": round(a_block, 4), "pass": bool(ok1)}

    if ext_n >= 30:
        fpr = ext_pos / ext_n
        ok2 = fpr <= ACCEPTANCE["external_false_positive_max"]
        print(f"  2. external false-positive rate <= "
              f"{ACCEPTANCE['external_false_positive_max']:.0%}"
              f"   {fpr:.1%}   {'PASS' if ok2 else 'FAIL'}")
        print(f"     ({ext_n} Roaringwater Faunal turf cells inside range. "
              f"One-sided: there are no external positives, so this measures")
        print("      false positives only and cannot measure sensitivity.)")
        results["external_fpr"] = {"value": round(fpr, 4), "n": ext_n,
                                   "pass": bool(ok2)}
    else:
        ok2 = None
        print(f"  2. external false-positive rate      only {ext_n} usable "
              f"cells   NOT TESTED")
        results["external_fpr"] = {"value": None, "n": ext_n, "pass": None}

    ken_kelp = float(np.median(predict_proba(beta, Xz)[y == 1]))
    inner = next((s for s in summaries if s["aoi"] == "inner_roaringwater"),
                 None)
    if inner and inner.get("median_suitability_in_range") is not None:
        ok3 = inner["median_suitability_in_range"] < ken_kelp
        print(f"  3. inner_roaringwater below Kenmare kelp   "
              f"{inner['median_suitability_in_range']:.3f} vs {ken_kelp:.3f}"
              f"   {'PASS' if ok3 else 'FAIL'}")
        print("     (three independent sources - MERC 2007, Norton 1978, NPWS")
        print("      Article 17 - record no L. hyperborea there.)")
        results["negative_control"] = {
            "inner": inner["median_suitability_in_range"],
            "kenmare_kelp": round(ken_kelp, 4), "pass": bool(ok3)}
    else:
        ok3 = None
        print("  3. negative control                  not evaluable")
        results["negative_control"] = {"pass": None}

    fails = [k for k, v in results.items() if v.get("pass") is False]
    print("")
    if fails:
        print(f"  >>> FAILED: {fails}. The model is NOT accepted. These")
        print("  >>> thresholds were fixed before the run, so the correct")
        print("  >>> response is to fix the model, not the thresholds.")
    elif any(v.get("pass") is None for v in results.values()):
        print("  >>> PASSED what could be tested; some criteria were not")
        print("  >>> evaluable. Say which on the slide.")
    else:
        print("  >>> ALL PRE-REGISTERED CRITERIA PASSED.")

    # ---------------- outputs ----------------
    if rows:
        p = OUT_DIR / "suitability_predictions.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  written: {p}   ({len(rows)} cells)")
    (OUT_DIR / "model_report.json").write_text(json.dumps({
        "features": list(features), "grid_m": args.grid,
        "block_m": args.block, "n_folds": N_FOLDS, "seed": SEED,
        "training": {"aoi": TRAIN_AOI, "n": int(y.size),
                     "n_kelp": int(y.sum()), "n_turf": int((1 - y).sum())},
        "coefficients_standardised": {
            "intercept": round(float(beta[0]), 4),
            **{f: round(float(beta[i + 1]), 4)
               for i, f in enumerate(features)}},
        "standardisation": {f: {"mean": round(float(mu[i]), 4),
                                "sd": round(float(sd[i]), 4)}
                            for i, f in enumerate(features)},
        "auc": {"in_sample": round(a_insample, 4),
                "random_kfold_OPTIMISTIC": round(a_rand, 4),
                "blocked_kfold_AUTHORITATIVE": round(a_block, 4),
                "per_fold_blocked": per_b, **base},
        "training_ranges": ranges, "application": summaries,
        "acceptance": {"thresholds": ACCEPTANCE, "results": results},
        "caveats": [
            "The depth term partly reproduces the NPWS 20 m delineation rule "
            "(41% of the shared class boundary lies within 3 m of 20 m against "
            "7% of a control boundary). It must not be presented as an "
            "ecological discovery.",
            "Covariate contributions were demonstrated only where the two "
            "surveyed classes co-occur in depth (16-20 m, n=638 cells). Half "
            "the mapped kelp lies shallower than 10 m, where the survey "
            "recorded almost no Faunal turf reef to compare against.",
            "The external test is one-sided: Roaringwater has Faunal turf "
            "negatives but essentially no mapped Laminaria, so sensitivity "
            "cannot be measured outside the training site.",
            "Cells with in_training_range = 0 are extrapolation and must be "
            "excluded from any area or euro figure.",
            "The Burrows wave-fetch licence has not been read. Nothing from "
            "this run may be published until it has.",
        ],
    }, indent=2, default=str), encoding="utf-8")
    print(f"  written: {OUT_DIR / 'model_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())