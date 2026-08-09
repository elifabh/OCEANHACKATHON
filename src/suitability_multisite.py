#!/usr/bin/env python3
"""
suitability_multisite.py - the suitability model, trained across several SACs.
Build step 2 of 7, second attempt.

WHY THE FIRST ATTEMPT WAS REJECTED
suitability_model.py trained at Kenmare River alone and was refused by its own
pre-registered criteria:

    blocked 5-fold AUC at Kenmare       0.955   PASS
    external false positives            100.0%  FAIL   (234 Faunal turf cells)
    inner_roaringwater vs Kenmare kelp  0.982 vs 0.956  FAIL

The diagnosis is not a coding error and is not fixed by a different algorithm.
The fitted coefficients were depth -3.976 against slope +0.542, curvature
-0.777 and fetch -0.278, and the depth-only baseline reached 0.945 of the
model's 0.955. The model learned one rule - shallow means kelp - which is true
at Kenmare, where kelp sits at a median 9.9 m and faunal turf at 27.2 m, and
false at inner Roaringwater, where the faunal turf itself sits at a median
7.2 m. Applied there, it called everything kelp.

Two of the four coefficients also came out with the sign opposite to the
published ecology: L. hyperborea favours EXPOSED coast, so fetch should be
positive, and rock outcrops are local highs, so curvature should be positive.
A model that contradicts the literature on two of four terms has not learned
ecology; it has learned the geometry of one bay.

The cause was measured, not guessed: Kenmare's labelled cells span 1.4 to
15.6 km/sector of fetch - a single sheltered inlet - while sherkin_baltimore
and mizen_outer sit at about 67. Exposure barely varies in the training set, so
it could not be learned, and an artefact was fitted in its place and then
extrapolated onto exactly the exposed coast where L. hyperborea is most likely.

WHY A DIFFERENT MODEL WOULD NOT HELP
The failure is in the training data, not the estimator. Any learner - a GAM, a
random forest, a network - fitted to a single sheltered bay will learn that
bay. A more flexible one learns it harder. The fix has to widen the data.

WHAT CHANGED HERE
  1. TRAINING SPANS SEVERAL SACs, discovered from the layer rather than
     hard-coded: every site carrying both Laminaria-dominated reef and Faunal
     turf reef, subtidal, ranked by mapped kelp area. Kilkieran Bay, Hook Head,
     Clew Bay, Kenmare River and Galway Bay together cover sheltered to
     exposed, which is the range Kenmare alone did not.
  2. LEAVE-ONE-SITE-OUT VALIDATION replaces block cross-validation. Each site
     is predicted by a model that never saw it. That is the direct measurement
     of the claim "the engine transfers to other Atlantic locations", and the
     number goes on a slide. Blocked CV within a site cannot measure transfer
     between sites.
  3. ROARINGWATER IS HELD OUT ENTIRELY, including its 234 Faunal turf
     polygons. It stays a genuine external test. Folding it into training would
     have improved the numbers by destroying the only independent check we
     have.
  4. COEFFICIENT SIGNS ARE CHECKED AGAINST PUBLISHED ECOLOGY and a mismatch is
     reported as a failure, not a curiosity. That check is what caught the
     first model, and it is now part of the run rather than something a human
     has to notice.
  5. SAMPLING IS RESTRICTED to cells on or near a labelled polygon. Gridding
     whole SAC bounding boxes at 50 m would need hundreds of thousands of
     INFOMAR samples for water nobody labelled.

WHAT THIS STILL CANNOT DO
There are no external POSITIVES anywhere outside the training sites, because
Roaringwater has essentially no mapped Laminaria. Sensitivity outside the
training sites is therefore unmeasurable, and the external test can only ever
report a false-positive rate. Leave-one-site-out sensitivity is the closest
substitute and must be described as such.

Dependencies: numpy (BSD-3), geopandas (BSD-3), shapely (BSD-3), pyproj (MIT),
rasterio (BSD-3). All to DEPENDENCIES.md with versions.

Data: NPWS Reef Inventory 2023 layer 21; INFOMAR bathymetry (GSI & Marine
Institute) CC BY 4.0; Burrows wave fetch (LICENCE STILL UNREAD).

Usage:
    python src/suitability_multisite.py --selftest
    python src/suitability_multisite.py \
        --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp" \
        --fetch data/fetch/log10_eu200m1a.tif
    python src/suitability_multisite.py --shp "<path>" --fetch "<tif>" \
        --list-sites
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

OUT_DIR = Path("outputs/model")
CACHE_DIR = Path("outputs/labels/depth_cache")

try:
    from common import AOIS, CRS_FOR_AREA, INFOMAR_BATHY, ArcGISError, \
        arcgis_request
    HAVE_COMMON = True
except ImportError:                                       # pragma: no cover
    HAVE_COMMON = False
    CRS_FOR_AREA = 2157
    INFOMAR_BATHY = None
    AOIS = {
        "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
        "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
        "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
        "kenmare_river": [-9.93, 51.75, -9.78, 51.81],
    }

    class ArcGISError(RuntimeError):
        pass

    def arcgis_request(*a, **k):
        raise ArcGISError("common.py not importable")

from circularity_check import terrain, sample_fetch_grid, norm
from suitability_model import (fit_logistic, predict_proba, auc,
                               training_ranges, in_range, FEATURES_ALL,
                               RANGE_PCT, DECISION_THRESHOLD)

TARGET = "laminaria-dominated reef"
NEGATIVE = "faunal turf reef"
GRID_M_DEFAULT = 50.0
BATCH = 400
PAD_M = 300.0            # padding around the labelled polygons of a site
DILATE_CELLS = 3         # sample this far beyond a labelled cell, for neighbours
MAX_SITES = 6
MIN_PER_CLASS = 100      # a site needs this many cells of each class to be used
# Coarsely-mapped sites are excluded: Lower River Shannon is 26,175 ha in 27
# polygons, a median of ~970 ha, which is a different kind of map from the
# 0.27 ha median at Kenmare and would dominate the fit with one brushstroke.
MAX_MEDIAN_POLY_HA = 50.0

# Sites held out entirely. Roaringwater is our application area and its Faunal
# turf polygons are the only external negatives that exist.
HOLDOUT_TOKENS = ("roaringwater",)

# Expected coefficient signs, from published work, with how firmly each is
# established. Depth is metres below LAT, positive down.
# The interaction term. Its name is checked for explicitly wherever features
# are assembled, so adding it cannot silently change the meaning of the four
# base terms.
INTERACTION = "depth_x_fetch"

EXPECTED_SIGNS = {
    INTERACTION: (+1, "moderate: the kelp depth limit tracks water clarity, "
                      "and exposed water is clearer, so on an exposed coast "
                      "kelp extends deeper. With a negative depth coefficient "
                      "that means the depth penalty must WEAKEN as fetch "
                      "rises, i.e. a positive interaction"),
    "depth_m": (-1, "firm: kelp is light-limited; NPWS record Laminaria "
                    "communities to ~20 m at Roaringwater, Bekkby et al. 2009 "
                    "find depth the strongest predictor"),
    "log10_fetch": (+1, "firm: L. hyperborea favours exposed coast; wave "
                        "exposure is a primary term in Bekkby et al. 2009"),
    "curvature": (+1, "moderate: curvature is a substrate proxy, positive over "
                      "local highs where bedrock outcrops rather than in "
                      "basins where sediment collects"),
    "slope_deg": (+1, "weak: steeper ground tends to be scoured to rock, but "
                      "this is our inference, not a cited result"),
}

SEED = 20261016

# A standardised coefficient below this is not "the wrong sign", it is no
# detectable effect. The first version of check_signs had no magnitude floor,
# so it reported log10_fetch at -0.028 - numerically indistinguishable from
# zero - with the same FAIL it gave -0.278, which was a genuinely wrong-signed
# effect. Those are different diagnoses and must not share a verdict.
SIGN_MIN_MAGNITUDE = 0.10

# Operating point for the external test. A fixed 0.5 cut is meaningless across
# sites whose kelp prevalence among labelled cells runs from 5.6% (Saltee) to
# 77% (Kilkieran), so the threshold is taken from out-of-site predictions at a
# stated specificity instead. Fixed in advance, like every other threshold.
TARGET_SPECIFICITY = 0.90

ACCEPTANCE = {
    "loso_auc_min": 0.70,
    "worst_site_auc_min": 0.60,
    "external_false_positive_max": 0.30,
    "sign_mismatches_max_firm": 0,
    "target_specificity_for_threshold": TARGET_SPECIFICITY,
}


# ---------------------------------------------------------------------------
# Site discovery
# ---------------------------------------------------------------------------

def discover_sites(gdf, max_sites: int, list_only: bool = False):
    """Sites carrying both classes, ranked by mapped kelp area."""
    rows = []
    for site in sorted(set(gdf["Site_name"].map(norm))):
        if site == "(null)":
            continue
        sub = gdf[gdf["Site_name"].map(norm) == site]
        kelp = sub[sub["Community"].map(norm).str.lower() == TARGET]
        turf = sub[sub["Community"].map(norm).str.lower() == NEGATIVE]
        if len(kelp) == 0 or len(turf) == 0:
            continue
        kelp_ha = float(kelp.geometry.area.sum()) / 1e4
        med_ha = float(np.median(kelp.geometry.area.values)) / 1e4
        rows.append({"site": site, "n_kelp": len(kelp), "n_turf": len(turf),
                     "kelp_ha": round(kelp_ha, 1),
                     "turf_ha": round(float(turf.geometry.area.sum()) / 1e4, 1),
                     "median_kelp_poly_ha": round(med_ha, 3)})
    rows.sort(key=lambda r: -r["kelp_ha"])

    print(f"  {'site':<42}{'kelp ha':>10}{'turf ha':>10}"
          f"{'med poly ha':>13}   status")
    chosen = []
    for r in rows:
        low = r["site"].lower()
        if any(t in low for t in HOLDOUT_TOKENS):
            status = "HELD OUT (application area)"
        elif r["median_kelp_poly_ha"] > MAX_MEDIAN_POLY_HA:
            status = f"excluded: coarse mapping (>{MAX_MEDIAN_POLY_HA:.0f} ha)"
        elif len(chosen) >= max_sites:
            status = "not used (site cap reached)"
        else:
            status = "TRAIN"
            chosen.append(r["site"])
        print(f"  {r['site'][:41]:<42}{r['kelp_ha']:>10.1f}{r['turf_ha']:>10.1f}"
              f"{r['median_kelp_poly_ha']:>13.3f}   {status}")
        r["status"] = status
    if list_only:
        return chosen, rows
    if not chosen:
        print("  >>> no usable training site found.")
    return chosen, rows


# ---------------------------------------------------------------------------
# Gridding, restricted to the neighbourhood of labelled polygons
# ---------------------------------------------------------------------------

def dilate(m: np.ndarray, k: int) -> np.ndarray:
    """Grow a boolean mask by k cells in each direction. No scipy needed."""
    out = m.copy()
    for _ in range(k):
        g = out.copy()
        g[1:, :] |= out[:-1, :]
        g[:-1, :] |= out[1:, :]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def site_bbox(sub_gdf, to_wgs, pad_m=PAD_M):
    """WGS84 bbox of a site's labelled polygons, padded."""
    minx, miny, maxx, maxy = sub_gdf.total_bounds        # projected metres
    minx, miny = minx - pad_m, miny - pad_m
    maxx, maxy = maxx + pad_m, maxy + pad_m
    lo0, la0 = to_wgs.transform(minx, miny)
    lo1, la1 = to_wgs.transform(maxx, maxy)
    return [min(lo0, lo1), min(la0, la1), max(lo0, lo1), max(la0, la1)]


def axes(bbox, grid_m):
    lat_mid = (bbox[1] + bbox[3]) / 2.0
    dlon = grid_m / (111320.0 * math.cos(math.radians(lat_mid)))
    dlat = grid_m / 110574.0
    return (np.arange(bbox[0] + dlon / 2, bbox[2], dlon),
            np.arange(bbox[1] + dlat / 2, bbox[3], dlat))


def label_mask(bbox, grid_m, sub_gdf, to_itm):
    """1 = kelp, 2 = faunal turf, 0 = unlabelled. Conflicts dropped, counted."""
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    keep = [(1 if norm(c).lower() == TARGET else 2, g)
            for c, g in zip(sub_gdf["Community"], sub_gdf.geometry)
            if norm(c).lower() in (TARGET, NEGATIVE)
            and g is not None and not g.is_empty]
    lons, lats = axes(bbox, grid_m)
    m = np.zeros((len(lats), len(lons)), dtype=int)
    if not keep:
        return m, 0
    cls = [c for c, _ in keep]
    polys = [g for _, g in keep]
    tree = STRtree(polys)
    pts = [(float(lo), float(la)) for la in lats for lo in lons]
    xs, ys = to_itm.transform([p[0] for p in pts], [p[1] for p in pts])
    nx = len(lons)
    conflicts = 0
    for i, (x, y) in enumerate(zip(xs, ys)):
        pt = Point(x, y)
        hits = {cls[j] for j in tree.query(pt) if polys[j].covers(pt)}
        if not hits:
            continue
        if len(hits) > 1:
            conflicts += 1
            continue
        m[i // nx, i % nx] = hits.pop()
    return m, conflicts


def sample_depth_subset(key, bbox, grid_m, want: np.ndarray, depth_fn=None):
    """Depth for the cells in `want` only, cached to disk."""
    lons, lats = axes(bbox, grid_m)
    ny, nx = len(lats), len(lons)
    grid = np.full((ny, nx), np.nan)
    cache = CACHE_DIR / f"site_{key}_{int(grid_m)}m.npz"

    if depth_fn is None and cache.exists():
        z = np.load(cache)
        if z["depth"].shape == grid.shape and \
                np.allclose(z["bbox"], np.array(bbox), atol=1e-9):
            # Report over the SAMPLED cells, not the whole grid. The fresh path
            # below reports the former; an earlier version reported the latter
            # here, so a cached run showed 5% where the run that wrote the
            # cache had shown 78% - the same data, described two ways.
            print(f"    depth from cache "
                  f"({np.isfinite(z['depth'][want]).mean():.0%} of sampled "
                  f"cells surveyed)")
            return z["depth"]
        print("    cache does not match this bbox; refetching")

    idx = np.flatnonzero(want.ravel())
    pts = [(float(lons[i % nx]), float(lats[i // nx])) for i in idx]
    if depth_fn is not None:
        got = depth_fn(pts)
    else:
        print(f"    sampling {len(pts)} INFOMAR points "
              f"({math.ceil(len(pts) / BATCH)} requests) ...")
        got, empty = {}, 0
        for start in range(0, len(pts), BATCH):
            chunk = [[p[0], p[1]] for p in pts[start:start + BATCH]]
            try:
                payload = arcgis_request(f"{INFOMAR_BATHY}/getSamples", {
                    "geometry": json.dumps(
                        {"points": chunk,
                         "spatialReference": {"wkid": 4326}}),
                    "geometryType": "esriGeometryMultipoint",
                    "returnFirstValueOnly": "true",
                    "interpolation": "RSP_NearestNeighbor", "f": "json"})
            except ArcGISError:
                empty += 1          # empty-batch rule, proven 2026-07-27
                continue
            for s in payload.get("samples", []):
                loc, raw = s.get("locationId"), s.get("value")
                if loc is None or raw in (None, "", "NaN"):
                    continue
                try:
                    got[start + int(loc)] = -float(str(raw).split()[0])
                except ValueError:
                    continue
        if empty:
            print(f"    ({empty} batches entirely outside INFOMAR coverage)")

    flat = grid.ravel()
    for k, v in got.items():
        flat[idx[k]] = v
    grid = flat.reshape(ny, nx)
    print(f"    surveyed: {np.isfinite(grid[want]).mean():.0%} of sampled cells")
    if depth_fn is None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(cache, depth=grid, bbox=np.array(bbox))
    return grid


def build_site(key, sub_gdf, grid_m, to_itm, to_wgs, fetch_path, depth_fn=None):
    """Feature rows for one site."""
    bbox = site_bbox(sub_gdf, to_wgs)
    mask, conflicts = label_mask(bbox, grid_m, sub_gdf, to_itm)
    want = dilate(mask > 0, DILATE_CELLS)
    print(f"    grid {mask.shape}, labelled cells {int((mask > 0).sum())}, "
          f"sampled {int(want.sum())}")
    if conflicts:
        print(f"    {conflicts} cells claimed by both classes, dropped")

    depth = sample_depth_subset(key, bbox, grid_m, want, depth_fn)
    slope, curv = terrain(depth, grid_m)
    fetch = (sample_fetch_grid(fetch_path, bbox, grid_m)
             if fetch_path is not None else np.full_like(depth, np.nan))
    if fetch is None:
        fetch = np.full_like(depth, np.nan)

    lons, lats = axes(bbox, grid_m)
    LON, LAT = np.meshgrid(lons, lats)
    feats = {"depth_m": depth, "slope_deg": slope, "curvature": curv,
             "log10_fetch": fetch}
    ok = (mask > 0)
    for f in FEATURES_ALL:
        ok &= np.isfinite(feats[f])
    X = np.column_stack([feats[f][ok] for f in FEATURES_ALL])
    y = (mask[ok] == 1).astype(float)
    print(f"    usable rows {y.size}: kelp {int(y.sum())}, "
          f"turf {int((1 - y).sum())}")
    return {"X": X, "y": y, "lon": LON[ok], "lat": LAT[ok], "bbox": bbox,
            "grid": {"mask": mask, **feats}}


# ---------------------------------------------------------------------------
# Leave-one-site-out
# ---------------------------------------------------------------------------

def loso(Z, y, site_idx, sites, weights=None):
    """Each site predicted by a model fitted on all the others.

    The fit carries one intercept per TRAINING site. A held-out site has none,
    so it is scored with the mean of the training intercepts. That is exactly
    the situation at Roaringwater, which makes this the honest simulation of
    what the deployed model faces: the ranking is transferable, the absolute
    probability is not.
    """
    oof = np.full(y.size, np.nan)
    per_site, slopes = {}, {}
    for k, name in enumerate(sites):
        te = site_idx == k
        tr = ~te
        if te.sum() == 0 or len(np.unique(y[tr])) < 2:
            per_site[name] = None
            continue
        tr_sites = [i for i in range(len(sites)) if i != k]
        remap = {old: new for new, old in enumerate(tr_sites)}
        idx_tr = np.array([remap[i] for i in site_idx[tr]])
        Dz = design(Z[tr], idx_tr, len(tr_sites))
        w = (site_weights(idx_tr, len(tr_sites)) if weights is not None
             else None)
        b = fit_logistic(Dz, y[tr], sample_weight=w, add_intercept=False,
                         unpenalised=tuple(range(len(tr_sites))))
        inter = b[:len(tr_sites)]
        beta_z = b[len(tr_sites):]
        slopes[name] = [round(float(v), 4) for v in beta_z]
        eta = float(np.mean(inter)) + Z[te] @ beta_z
        oof[te] = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        per_site[name] = (round(auc(y[te], oof[te]), 4)
                          if len(np.unique(y[te])) == 2 else None)
    ok = np.isfinite(oof)
    return (auc(y[ok], oof[ok]) if ok.sum() else float("nan")), per_site, oof, \
        slopes


def check_signs(coefs, features):
    """Compare fitted signs against the published direction.

    Three outcomes, not two. A coefficient can agree, disagree, or be too small
    to say anything about - and the third is a different finding from the
    second. "Wrong sign" means the model learned a relationship backwards; "no
    effect detected" means it learned nothing there, which points at the
    training data rather than at the fit. The first version of this function
    had no magnitude floor and gave both the same FAIL.

    `coefs` is the covariate coefficients only, without any intercept.
    """
    out, firm_bad, silent = {}, [], []
    print(f"\n  {'term':<14}{'coef':>9}{'expected':>10}   {'basis':<10}verdict")
    for i, f in enumerate(features):
        c = float(coefs[i])
        exp, why = EXPECTED_SIGNS.get(f, (0, "no expectation"))
        if abs(c) < SIGN_MIN_MAGNITUDE:
            state, tag = "no_effect", "no effect detected"
            silent.append(f)
        elif exp == 0 or c * exp > 0:
            state, tag = "agrees", "ok"
        else:
            state, tag = "opposite", "<-- OPPOSITE"
            if why.startswith("firm"):
                firm_bad.append(f)
        print(f"  {f:<14}{c:>+9.3f}{('+' if exp > 0 else '-'):>10}   "
              f"{why.split(':')[0]:<10}{tag}")
        out[f] = {"coef": round(c, 4), "expected_sign": exp, "state": state,
                  "basis": why}

    if firm_bad:
        print(f"\n  >>> {firm_bad}: sign OPPOSITE to firmly established")
        print("  >>> ecology, at a magnitude large enough to mean it. The")
        print("  >>> model has fitted site geometry rather than ecology.")
        print("  >>> Do not proceed to valuation.")
    if silent:
        print(f"\n  >>> {silent}: |coefficient| below "
              f"{SIGN_MIN_MAGNITUDE:.2f} standardised units, i.e.")
        print("  >>> NO DETECTABLE EFFECT rather than a wrong one. That is a")
        print("  >>> statement about the training data, not about the")
        print("  >>> covariate: either the range sampled is too narrow to")
        print("  >>> learn from, or the effect is confounded with something")
        print("  >>> already in the model. Report the term as untested; do")
        print("  >>> NOT report it as evidence the covariate does not matter.")
    if not firm_bad and not silent:
        print("\n  >>> every term has a detectable effect in the expected"
              " direction.")
    return out, firm_bad, silent


# ---------------------------------------------------------------------------
# Site-balanced weights and per-site intercepts
# ---------------------------------------------------------------------------

def site_weights(site_idx, n_sites) -> np.ndarray:
    """Weights giving every site the same total influence on the likelihood.

    Without this the fit is dominated by whoever surveyed most: Kilkieran
    contributed 30,223 cells against Valencia's 2,838, more than ten to one.
    The likelihood then describes the big sites and the model is theirs.
    """
    w = np.ones(site_idx.size, dtype=float)
    for k in range(n_sites):
        m = site_idx == k
        n = int(m.sum())
        if n:
            w[m] = 1.0 / n
    return w * (site_idx.size / max(n_sites, 1))    # keep the total near n


def add_interaction(Z, features):
    """Append standardised depth x standardised fetch.

    WHY THIS TERM EXISTS
    Without it the model can only say "shallow means kelp", uniformly. That is
    what it said, at a depth coefficient of -4.072 against fetch +0.685, and it
    is why inner_roaringwater - shallow AND sheltered, NPWS say not Laminaria -
    scored 0.885 and produced an 82.9% false-positive rate.

    The ecology the term encodes is not ours: the lower limit of kelp is set by
    light, exposed water is clearer than sheltered water, so the depth to which
    kelp reaches is not one number but a function of exposure. A model with
    only additive depth and fetch cannot express that; one shallow sheltered
    cell and one shallow exposed cell must get the same depth contribution.

    Z must already be standardised, and depth and fetch must be in `features`.
    """
    di = features.index("depth_m")
    fi = features.index("log10_fetch")
    return np.hstack([Z, (Z[:, di] * Z[:, fi]).reshape(-1, 1)])


def design(Z, site_idx, n_sites):
    """One-hot site columns followed by the standardised covariates.

    WHY PER-SITE INTERCEPTS, AND WHY THIS IS THE ACTUAL FIX
    Kelp prevalence among labelled cells runs from 5.6% at Saltee Islands to
    77% at Kilkieran. Saltee is an exposed offshore group; Kilkieran is a
    sheltered bay. A single pooled intercept forces one baseline on both, so
    the fit can only explain that difference through the covariates - and the
    covariate that most separates those two sites is fetch. The pooled model
    therefore learns "high fetch means no kelp", which is backwards, and which
    is exactly the -0.278 and then -0.028 we kept seeing.

    Giving each site its own intercept absorbs the prevalence difference. The
    remaining slopes are then WITHIN-site effects: what makes one cell more
    kelp-like than its neighbour at the same site. That is the quantity we
    want, and it is the quantity that can transfer.

    The cost is real and must be stated: a site outside the training set has no
    intercept, so predicted PROBABILITIES are not calibrated for it. Only the
    ranking transfers. AUC is rank-based and is unaffected; a fixed probability
    cut-off is not, which is why the operating threshold below is taken from
    out-of-site predictions rather than left at 0.5.
    """
    D = np.zeros((Z.shape[0], n_sites))
    D[np.arange(Z.shape[0]), site_idx] = 1.0
    return np.hstack([D, Z])


def reef_mask(bbox, grid_m, gdf_all, to_itm):
    """Cells falling inside ANY layer-21 polygon, i.e. mapped reef of any kind.

    WHY PREDICTION MUST BE RESTRICTED TO IT
    Layer 21 is a REEF inventory. Every training cell we have - Laminaria-
    dominated reef and Faunal turf reef alike - is hard substrate, because
    that is all the layer contains. The model therefore never saw sand, mud or
    gravel and has no way to recognise them; substrate is constant across the
    entire training set, which is also why slope came out at +0.002 and
    curvature with the wrong sign. There was nothing there to separate.

    Predicting on every cell of an AOI then asks the model a question it was
    never trained to answer, and it answers confidently anyway. So prediction
    is confined to mapped reef, and everything else is reported as NOT
    ASSESSED - which is not the same as unsuitable and must never be shown or
    summed as if it were zero.

    The cost, and it goes on the slide: the tool needs a pre-existing reef map.
    Inside Irish SACs one exists; outside them it does not, and that is a real
    limit on where this can be deployed today.
    """
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    polys = [g for g in gdf_all.geometry if g is not None and not g.is_empty]
    lons, lats = axes(bbox, grid_m)
    m = np.zeros((len(lats), len(lons)), dtype=bool)
    if not polys:
        return m
    tree = STRtree(polys)
    pts = [(float(lo), float(la)) for la in lats for lo in lons]
    xs, ys = to_itm.transform([p[0] for p in pts], [p[1] for p in pts])
    nx = len(lons)
    for i, (x, y) in enumerate(zip(xs, ys)):
        pt = Point(x, y)
        if any(polys[j].covers(pt) for j in tree.query(pt)):
            m[i // nx, i % nx] = True
    return m


def calibrated_threshold(y, scores, specificity=TARGET_SPECIFICITY):
    """Score cut-off achieving the target specificity on known negatives."""
    neg = np.asarray(scores)[np.asarray(y) == 0]
    if neg.size < 30:
        return float("nan")
    return float(np.percentile(neg, 100.0 * specificity))


def site_diagnostics(parts, site_names):
    """Why a site transfers or does not: prevalence, depth split, exposure."""
    di = FEATURES_ALL.index("depth_m")
    fi = FEATURES_ALL.index("log10_fetch")
    print(f"\n  {'site':<40}{'kelp%':>7}{'kelp d':>8}{'turf d':>8}"
          f"{'depth AUC':>11}{'fetch range':>13}")
    rows = []
    for d, name in zip(parts, site_names):
        X, y = d["X"], d["y"]
        prev = float(y.mean())
        dk = float(np.median(X[y == 1, di])) if (y == 1).any() else float("nan")
        dt = float(np.median(X[y == 0, di])) if (y == 0).any() else float("nan")
        a_depth = 1.0 - auc(y, X[:, di])        # shallower = kelp
        fr = float(X[:, fi].max() - X[:, fi].min())
        print(f"  {name[:39]:<40}{prev:>7.1%}{dk:>8.1f}{dt:>8.1f}"
              f"{a_depth:>11.3f}{10 ** fr:>12.0f}x")
        rows.append({"site": name, "kelp_share": round(prev, 4),
                     "median_depth_kelp": round(dk, 2),
                     "median_depth_turf": round(dt, 2),
                     "depth_only_auc": round(a_depth, 4),
                     "fetch_range_x": round(10 ** fr, 1)})
    print("  >>> 'depth AUC' is the depth-only separation WITHIN that site. If")
    print("  >>> it is ~0.95 everywhere, the label is effectively a depth band")
    print("  >>> and no model can do better than reproduce it - which would")
    print("  >>> make the honest product a depth-band rule, reported as one.")
    return rows


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    print("SELFTEST (no network, no files)\n")
    rng = np.random.default_rng(5)

    # --- dilate ------------------------------------------------------------
    m = np.zeros((9, 9), dtype=bool)
    m[4, 4] = True
    assert dilate(m, 0).sum() == 1
    assert dilate(m, 1).sum() == 5          # plus-shape
    assert dilate(m, 3).sum() == 25         # diamond of radius 3
    assert not dilate(m, 1)[4, 6]
    print(f"  dilate: 1 -> {dilate(m, 1).sum()} -> {dilate(m, 3).sum()} cells, "
          f"diamond not square  ok")

    # --- LOSO folds --------------------------------------------------------
    sites = ["A", "B", "C"]
    si = np.array([0] * 100 + [1] * 100 + [2] * 100)
    yy = np.concatenate([rng.integers(0, 2, 100).astype(float) for _ in sites])
    XX = rng.normal(size=(300, 2))
    _, per, oof, _ = loso(XX, yy, si, sites)
    assert np.isfinite(oof).all(), "every row must get an out-of-site prediction"
    assert set(per) == set(sites)
    print("  LOSO: every row predicted by a model that never saw its site  ok")

    # --- THE test: a site-specific relationship must be caught by LOSO -----
    # Two sites where the SAME predictor points the OPPOSITE way. Pooled
    # random CV can still score well by averaging; LOSO cannot, because each
    # site is predicted from the other. If LOSO did not collapse here, it
    # would not be measuring transfer at all.
    n = 400
    xa = rng.normal(size=n)
    ya = (xa > 0).astype(float)
    xb = rng.normal(size=n)
    yb = (xb < 0).astype(float)          # reversed relationship
    X2 = np.concatenate([xa, xb]).reshape(-1, 1)
    y2 = np.concatenate([ya, yb])
    s2 = np.array([0] * n + [1] * n)
    a_loso, per2, _, _ = loso(X2, y2, s2, ["A", "B"])
    assert a_loso < 0.35, (a_loso, per2)
    print(f"  LOSO on sites with opposite relationships: AUC {a_loso:.3f}"
          f"  (collapses, as it must)  ok")

    # And when the sites AGREE, LOSO must score well - otherwise the test
    # above only shows LOSO can fail, not that it can succeed.
    yb_same = (xb > 0).astype(float)
    a_ok, _, _, _ = loso(X2, np.concatenate([ya, yb_same]), s2,
                         ["A", "B"])
    assert a_ok > 0.9, a_ok
    print(f"  LOSO on sites that agree: AUC {a_ok:.3f}  ok")

    # --- site-balanced weights ---------------------------------------------
    si2 = np.array([0] * 900 + [1] * 100)
    w2 = site_weights(si2, 2)
    assert abs(w2[si2 == 0].sum() - w2[si2 == 1].sum()) < 1e-9
    assert abs(w2.sum() - si2.size) < 1e-6
    print(f"  site weights: 900 vs 100 cells -> equal total influence "
          f"({w2[si2 == 0].sum():.0f} each)  ok")

    # --- THE fix, demonstrated -------------------------------------------
    # Two sites. WITHIN each, higher fetch means more kelp. But the exposed
    # site has low kelp prevalence and the sheltered site has high prevalence -
    # which is Saltee (5.6% kelp, exposed) against Kilkieran (77%, sheltered).
    # A pooled intercept must give fetch the WRONG sign; per-site intercepts
    # must recover the right one. If both fits agreed, the fix would be doing
    # nothing.
    nA = nB = 700
    fa = 2.0 + rng.normal(0, 0.3, nA)
    ya2 = ((fa - 2.0) + rng.normal(0, 0.25, nA) > -0.35).astype(float)
    fb = 4.0 + rng.normal(0, 0.3, nB)
    yb2 = ((fb - 4.0) + rng.normal(0, 0.25, nB) > +0.35).astype(float)
    Zc = np.concatenate([fa, fb]).reshape(-1, 1)
    Zc = (Zc - Zc.mean()) / Zc.std()
    yc = np.concatenate([ya2, yb2])
    sc = np.array([0] * nA + [1] * nB)

    b_pooled = fit_logistic(Zc, yc)
    b_sites = fit_logistic(design(Zc, sc, 2), yc,
                           sample_weight=site_weights(sc, 2),
                           add_intercept=False, unpenalised=(0, 1))
    print(f"\n  confounded fixture: prevalence {ya2.mean():.0%} (sheltered) "
          f"vs {yb2.mean():.0%} (exposed)")
    print(f"    pooled intercept   -> fetch coefficient {b_pooled[1]:+.3f}")
    print(f"    per-site intercepts -> fetch coefficient {b_sites[2]:+.3f}")
    assert b_pooled[1] < 0, b_pooled
    assert b_sites[2] > 0, b_sites
    print("  per-site intercepts flip the confounded sign back  ok")

    # --- sign check, all three verdicts ------------------------------------
    feats = ("depth_m", "slope_deg", "curvature", "log10_fetch")
    _, bad_ok, sil_ok = check_signs(np.array([-2.0, +0.5, +0.5, +0.5]), feats)
    assert bad_ok == [] and sil_ok == [], (bad_ok, sil_ok)
    # the FIRST model: a genuinely wrong-signed fetch effect
    _, bad2, sil2 = check_signs(np.array([-3.976, +0.542, -0.777, -0.278]),
                                feats)
    assert "log10_fetch" in bad2 and sil2 == [], (bad2, sil2)
    # the SECOND model: fetch at -0.028 is no effect, NOT a wrong sign. The
    # version of this function without a magnitude floor called it OPPOSITE.
    _, bad3, sil3 = check_signs(np.array([-2.343, +0.393, -0.280, -0.028]),
                                feats)
    assert bad3 == [], bad3
    assert "log10_fetch" in sil3, sil3
    print(f"\n  sign check: clean passes, -0.278 flagged OPPOSITE {bad2}, "
          f"-0.028 flagged as no effect {sil3}  ok")

    # --- what the interaction actually does, measured not assumed --------
    # Fixture: the depth limit GROWS with exposure, 6 m sheltered to ~25 m
    # exposed, on a curved boundary an additive model cannot draw.
    #
    # The first version of this test asserted the interaction would lift AUC by
    # at least 0.02. It does not. Measured across noise levels the gain is
    # about +0.004, because AUC is rank-based and an additive model still ranks
    # a curved boundary nearly as well. The assertion was written from what the
    # term was hoped to do; it has been replaced with what it does.
    #
    # What IS robust is the coefficient sign, and that is worth having: it is
    # the one term whose direction the ecology predicts unambiguously, so a
    # negative value would be a red flag. Nobody should expect this term to
    # rescue a failing false-positive rate.
    nn = 4000
    dep = rng.uniform(0, 35, nn)
    fet = rng.uniform(2.0, 4.3, nn)
    limit = 6.0 * 2.0 ** ((fet - 2.0) / 0.6)
    Zk = np.column_stack([dep, fet])
    Zk = (Zk - Zk.mean(axis=0)) / Zk.std(axis=0)
    Zi = add_interaction(Zk, ("depth_m", "log10_fetch"))
    sk = np.zeros(nn, dtype=int)

    def score(b, Z, yv):
        eta = b[0] + Z @ b[1:]
        return auc(yv, 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30))))

    print("\n  exposure-dependent depth limit (6 m sheltered -> 25 m exposed):")
    for noise in (0.0, 2.0, 4.0):
        yk = (dep + rng.normal(0, noise, nn) < limit).astype(float)
        b_add = fit_logistic(design(Zk, sk, 1), yk, add_intercept=False,
                             unpenalised=(0,))
        b_int = fit_logistic(design(Zi, sk, 1), yk, add_intercept=False,
                             unpenalised=(0,))
        a_add, a_int = score(b_add, Zk, yk), score(b_int, Zi, yk)
        print(f"    noise {noise:.0f} m: additive {a_add:.4f}, "
              f"interaction {a_int:.4f} ({a_int - a_add:+.4f}), "
              f"coef {b_int[3]:+.2f}")
        # nesting: the larger model can never rank worse than the one inside it
        assert a_int >= a_add - 1e-6, (a_add, a_int)
        # and the sign the ecology predicts, at every noise level
        assert b_int[3] > 0, b_int
    print("  interaction: correct sign at every noise level, AUC gain small")
    print("  (~+0.004) - it is a shape correction, not a rescue  ok")

    # --- calibrated threshold ---------------------------------------------
    yt = np.concatenate([np.ones(300), np.zeros(300)])
    st = np.concatenate([rng.normal(0.7, 0.1, 300), rng.normal(0.3, 0.1, 300)])
    t = calibrated_threshold(yt, st, 0.90)
    spec = float((st[yt == 0] <= t).mean())
    assert abs(spec - 0.90) < 0.02, (t, spec)
    # too few negatives must give NaN, never a fabricated cut-off
    assert np.isnan(calibrated_threshold(np.ones(10), np.ones(10)))
    assert np.isnan(calibrated_threshold(yt[:20], st[:20]))
    print(f"  calibrated threshold {t:.3f} gives {spec:.0%} specificity, and "
          f"returns NaN when there are too few negatives  ok")

    print("\nSELFTEST PASSED. dilate grows a diamond; LOSO gives every row an")
    print("out-of-site prediction, collapses when sites disagree and succeeds")
    print("when they agree; site weights equalise unequal sites; per-site")
    print("intercepts flip a confounded coefficient back to the right sign;")
    print("the sign check separates a wrong sign from no effect; and the")
    print("operating threshold hits its target specificity.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Multi-site kelp suitability model with leave-one-site-out "
                    "validation.")
    ap.add_argument("--shp", type=Path)
    ap.add_argument("--fetch", type=Path)
    ap.add_argument("--grid", type=float, default=GRID_M_DEFAULT)
    ap.add_argument("--max-sites", type=int, default=MAX_SITES)
    ap.add_argument("--sites", nargs="*", help="override site discovery")
    ap.add_argument("--list-sites", action="store_true",
                    help="show the candidate sites and stop")
    ap.add_argument("--no-interaction", action="store_true",
                    help="drop the depth x fetch term, for comparison")
    ap.add_argument("--all-cells", action="store_true",
                    help="predict everywhere instead of on mapped reef only. "
                         "Off by default: the model only ever saw reef, so a "
                         "score on sand is not a prediction, it is a guess.")
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

    import geopandas as gpd
    from pyproj import Transformer

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)
    to_wgs = Transformer.from_crs(CRS_FOR_AREA, 4326, always_xy=True)

    print("Multi-site kelp suitability model - build step 2 of 7, attempt 2.")
    print("NPWS layer 21 x INFOMAR bathymetry (GSI & Marine Institute, "
          "CC BY 4.0).")
    print("Wave fetch: Burrows, figshare. LICENCE STILL UNREAD - nothing from "
          "this run may be published until it is.\n")

    gdf = gpd.read_file(args.shp).to_crs(epsg=CRS_FOR_AREA)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    bad = ~gdf.geometry.is_valid
    if int(bad.sum()):
        gdf.loc[bad, "geometry"] = gdf.loc[bad].geometry.buffer(0)
    if "Extent" in gdf.columns:
        gdf = gdf[gdf["Extent"].map(norm).str.lower() == "subtidal"].copy()
    for req in ("Site_name", "Community"):
        if req not in gdf.columns:
            print(f"  >>> no '{req}' field. This is not layer 21.")
            return 2

    print("=" * 74)
    print("SITE DISCOVERY")
    print("=" * 74)
    chosen, all_sites = discover_sites(gdf, args.max_sites, args.list_sites)
    if args.list_sites:
        return 0
    if args.sites:
        chosen = args.sites
        print(f"\n  overridden by --sites: {chosen}")
    if len(chosen) < 2:
        print("\n  >>> fewer than two training sites. Leave-one-site-out")
        print("  >>> cannot run, and a single site is what failed last time.")
        return 2

    print("\n" + "=" * 74)
    print("BUILDING TRAINING DATA")
    print("=" * 74)
    parts, site_names = [], []
    for site in chosen:
        print(f"\n  {site}")
        sub = gdf[gdf["Site_name"].map(norm) == site]
        key = "".join(ch if ch.isalnum() else "_" for ch in site.lower())[:40]
        d = build_site(key, sub, args.grid, to_itm, to_wgs, args.fetch)
        if d["y"].sum() < MIN_PER_CLASS or (1 - d["y"]).sum() < MIN_PER_CLASS:
            print(f"    >>> fewer than {MIN_PER_CLASS} cells in one class; "
                  f"site not used")
            continue
        parts.append(d)
        site_names.append(site)

    if len(parts) < 2:
        print("\n  >>> fewer than two usable sites after filtering.")
        return 2

    X = np.vstack([d["X"] for d in parts])
    y = np.concatenate([d["y"] for d in parts])
    site_idx = np.concatenate([np.full(d["y"].size, i)
                               for i, d in enumerate(parts)])
    print(f"\n  TOTAL: {y.size} cells across {len(parts)} sites"
          f"   kelp {int(y.sum())}, turf {int((1 - y).sum())}")

    fi = FEATURES_ALL.index("log10_fetch")
    print(f"  fetch range across training sites: "
          f"{X[:, fi].min():.2f} to {X[:, fi].max():.2f} log10"
          f"  = {10 ** (X[:, fi].max() - X[:, fi].min()):.0f}x")
    print("  >>> Kenmare alone spanned about 11x and could not learn exposure.")

    print("\n" + "=" * 74)
    print("PER-SITE DIAGNOSTICS")
    print("=" * 74)
    diag = site_diagnostics(parts, site_names)

    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Xz = (X - mu) / sd

    feat_names = list(FEATURES_ALL)
    if not args.no_interaction:
        Xz = add_interaction(Xz, FEATURES_ALL)
        feat_names.append(INTERACTION)
        print(f"\n  interaction term added: {INTERACTION}")
        print("  >>> Without it the model can only say 'shallow means kelp',")
        print("  >>> uniformly, which is what produced the 82.9% false")
        print("  >>> positives at shallow sheltered inner_roaringwater.")

    n_sites = len(site_names)
    w = site_weights(site_idx, n_sites)
    Dz = design(Xz, site_idx, n_sites)
    b_full = fit_logistic(Dz, y, sample_weight=w, add_intercept=False,
                          unpenalised=tuple(range(n_sites)))
    intercepts = b_full[:n_sites]
    beta_z = b_full[n_sites:]

    print("\n  per-site intercepts (baseline log-odds of kelp):")
    for i, nm in enumerate(site_names):
        print(f"    {nm[:44]:<46}{intercepts[i]:>+8.2f}")
    print("  >>> These absorb the prevalence differences between sites, so the")
    print("  >>> covariate coefficients below are WITHIN-site effects. A site")
    print("  >>> outside the training set has no intercept, so its predicted")
    print("  >>> probabilities are uncalibrated - only the ranking transfers.")

    print("\n" + "=" * 74)
    print("COEFFICIENT SIGNS vs PUBLISHED ECOLOGY")
    print("=" * 74)
    signs, firm_bad, silent = check_signs(beta_z, feat_names)

    print("\n" + "=" * 74)
    print("LEAVE-ONE-SITE-OUT VALIDATION")
    print("=" * 74)
    a_loso, per_site, oof, loso_slopes = loso(Xz, y, site_idx, site_names,
                                              weights=True)
    eta_in = intercepts[site_idx] + Xz @ beta_z
    a_in = auc(y, 1.0 / (1.0 + np.exp(-np.clip(eta_in, -30, 30))))
    print(f"  in-sample AUC (not performance)   {a_in:.3f}")
    print(f"  LEAVE-ONE-SITE-OUT AUC            {a_loso:.3f}   <-- the number")
    print(f"                                                    for the slide")
    print(f"\n  {'held-out site':<42}{'AUC':>8}{'n':>8}")
    for i, s in enumerate(site_names):
        n = int((site_idx == i).sum())
        v = per_site.get(s)
        print(f"  {s[:41]:<42}{(f'{v:.3f}' if v is not None else '-'):>8}{n:>8}")
    vals = [v for v in per_site.values() if v is not None]
    worst = min(vals) if vals else float("nan")
    print(f"\n  worst site {worst:.3f}   >>> this, not the mean, is what")
    print("  >>> transfer to an unseen coast actually looks like.")

    # ---------------- application ----------------
    print("\n" + "=" * 74)
    print("APPLICATION  Roaringwater (held out entirely)")
    print("=" * 74)
    ranges = training_ranges(X, FEATURES_ALL)
    for f in FEATURES_ALL:
        print(f"    {f:<14}{ranges[f][0]:>10.3f}  to {ranges[f][1]:>10.3f}")

    thr = calibrated_threshold(y, oof, TARGET_SPECIFICITY)
    print(f"\n  operating threshold at {TARGET_SPECIFICITY:.0%} specificity on")
    print(f"  out-of-site predictions: {thr:.4f}")
    print("  >>> Not 0.5. With per-site intercepts a fixed 0.5 has no meaning")
    print("  >>> on an unseen site, and with prevalence running from 5.6% to")
    print("  >>> 77% across the training sites it had little meaning anyway.")

    from suitability_model import build_grid, flatten
    rows, summaries, ext_pos, ext_n = [], [], 0, 0
    mean_intercept = float(np.mean(intercepts))
    for name in ("sherkin_baltimore", "inner_roaringwater", "mizen_outer"):
        print(f"\n  --- {name} ---")
        g = build_grid(name, AOIS[name], args.grid, gdf, to_itm, args.fetch)
        Xa, _, lo_a, la_a, mk, okmask = flatten(g, FEATURES_ALL,
                                                labelled_only=False)
        if Xa.shape[0] == 0:
            print("    nothing predictable here.")
            continue
        inside, detail = in_range(Xa, ranges, FEATURES_ALL)
        Za = (Xa - mu) / sd
        if not args.no_interaction:
            Za = add_interaction(Za, FEATURES_ALL)
        eta_a = mean_intercept + Za @ beta_z
        pr = 1.0 / (1.0 + np.exp(-np.clip(eta_a, -30, 30)))
        cell_ha = (args.grid ** 2) / 1e4

        # Restrict to mapped reef unless explicitly told not to.
        if args.all_cells:
            on_reef = np.ones(Xa.shape[0], dtype=bool)
        else:
            rm = reef_mask(AOIS[name], args.grid, gdf, to_itm)
            on_reef = rm[okmask]
        n_off = int((~on_reef).sum())
        print(f"    cells {Xa.shape[0]} ({Xa.shape[0] * cell_ha:.0f} ha), "
              f"inside training range {inside.mean():.0%}")
        if not args.all_cells:
            print(f"    on mapped reef {int(on_reef.sum())}"
                  f"  ({on_reef.mean():.0%})"
                  f"   NOT ASSESSED off reef: {n_off} cells "
                  f"({n_off * cell_ha:.0f} ha)")
            print("    >>> 'not assessed' is not 'unsuitable'. It must be blank")
            print("    >>> on the map and absent from every area and euro sum.")
        inside = inside & on_reef
        for f, sh in detail.items():
            if sh > 0.10:
                print(f"      {f}: {sh:.0%} outside")
        if inside.sum():
            print(f"    suitability inside range: median "
                  f"{np.median(pr[inside]):.3f}")
        usable = (mk == 2) & inside
        if usable.sum() >= 30:
            fp = float((pr[usable] > thr).mean())
            ext_pos += int((pr[usable] > thr).sum())
            ext_n += int(usable.sum())
            print(f"    EXTERNAL NEGATIVES: {int(usable.sum())} cells, "
                  f"{fp:.1%} above the {thr:.3f} operating threshold")
        for k in range(Xa.shape[0]):
            rows.append({"aoi": name, "lon": round(float(lo_a[k]), 6),
                         "lat": round(float(la_a[k]), 6),
                         "suitability": round(float(pr[k]), 4),
                         "on_mapped_reef": int(on_reef[k]),
                         "in_training_range": int(inside[k]),
                         "assessed": int(on_reef[k] and inside[k]),
                         "npws_label": int(mk[k]),
                         **{f: round(float(Xa[k, i]), 4)
                            for i, f in enumerate(FEATURES_ALL)}})
                         
        summaries.append({"aoi": name, "cells": int(Xa.shape[0]),
                          "on_mapped_reef": int(on_reef.sum()),
                          "not_assessed_off_reef_ha": round(n_off * cell_ha, 1),
                          "share_assessed": round(float(inside.mean()), 4),
                          "median_suitability_in_range":
                              (round(float(np.median(pr[inside])), 4)
                               if inside.sum() else None)})

    # ---------------- acceptance ----------------
    print("\n" + "=" * 74)
    print("PRE-REGISTERED ACCEPTANCE CRITERIA")
    print("=" * 74)
    res = {}
    ok1 = a_loso == a_loso and a_loso >= ACCEPTANCE["loso_auc_min"]
    print(f"  1. LOSO AUC >= {ACCEPTANCE['loso_auc_min']:.2f}"
          f"                    {a_loso:.3f}   {'PASS' if ok1 else 'FAIL'}")
    res["loso_auc"] = {"value": round(a_loso, 4), "pass": bool(ok1)}

    ok2 = worst == worst and worst >= ACCEPTANCE["worst_site_auc_min"]
    print(f"  2. worst site AUC >= {ACCEPTANCE['worst_site_auc_min']:.2f}"
          f"              {worst:.3f}   {'PASS' if ok2 else 'FAIL'}")
    res["worst_site"] = {"value": round(worst, 4), "pass": bool(ok2)}

    if ext_n >= 30:
        fpr = ext_pos / ext_n
        ok3 = fpr <= ACCEPTANCE["external_false_positive_max"]
        print(f"  3. external false positives <= "
              f"{ACCEPTANCE['external_false_positive_max']:.0%}"
              f"       {fpr:.1%}   {'PASS' if ok3 else 'FAIL'}")
        print(f"     ({ext_n} Roaringwater Faunal turf cells. One-sided: no")
        print("      external positives exist, so sensitivity is unmeasured.)")
        res["external_fpr"] = {"value": round(fpr, 4), "n": ext_n,
                               "pass": bool(ok3)}
    else:
        print(f"  3. external false positives          only {ext_n} cells   "
              "NOT TESTED")
        res["external_fpr"] = {"value": None, "n": ext_n, "pass": None}

    ok4 = len(firm_bad) <= ACCEPTANCE["sign_mismatches_max_firm"]
    print(f"  4. no firm sign contradicted           {firm_bad or 'none'}"
          f"   {'PASS' if ok4 else 'FAIL'}")
    res["signs"] = {"contradicted": firm_bad, "pass": bool(ok4)}
    if silent:
        print(f"  -  terms with no detectable effect     {silent}   "
              f"NOT A FAILURE, but they must be reported as untested rather")
        print("     than as evidence the covariate does not matter.")
    # NOTE: `res` holds one dict per pre-registered criterion and nothing else.
    # An earlier version also stashed a list and a float in here, and the
    # verdict scan below - which calls v.get("pass") on every value - crashed
    # on them. Anything that is not a criterion goes in `extras`.
    extras = {"silent_terms": silent,
              "operating_threshold": (round(thr, 4) if thr == thr else None)}

    fails = [k for k, v in res.items()
             if isinstance(v, dict) and v.get("pass") is False]
    print("")
    if fails:
        print(f"  >>> FAILED: {fails}. NOT accepted. The thresholds were fixed")
        print("  >>> before the run; fix the model, not the thresholds.")
    else:
        print("  >>> ALL PRE-REGISTERED CRITERIA PASSED.")

    if rows:
        p = OUT_DIR / "suitability_multisite_predictions.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  written: {p}   ({len(rows)} cells)")
    (OUT_DIR / "model_multisite_report.json").write_text(json.dumps({
        "features": list(FEATURES_ALL), "grid_m": args.grid, "seed": SEED,
        "sites_considered": all_sites, "sites_used": site_names,
        "training": {"n": int(y.size), "n_kelp": int(y.sum()),
                     "n_turf": int((1 - y).sum())},
        "site_intercepts": {nm: round(float(intercepts[i]), 4)
                            for i, nm in enumerate(site_names)},
        "features_fitted": feat_names,
        "coefficients_standardised_within_site": {
            f: round(float(beta_z[i]), 4)
            for i, f in enumerate(feat_names)},
        "loso_slopes_per_fold": loso_slopes,
        "site_diagnostics": diag,
        "operating_threshold": (round(thr, 4) if thr == thr else None),
        "standardisation": {f: {"mean": round(float(mu[i]), 4),
                                "sd": round(float(sd[i]), 4)}
                            for i, f in enumerate(FEATURES_ALL)},
        "sign_check": signs,
        "auc": {"in_sample": round(a_in, 4),
                "leave_one_site_out": round(a_loso, 4),
                "per_site": per_site, "worst_site": worst},
        "training_ranges": ranges, "application": summaries,
        "acceptance": {"thresholds": ACCEPTANCE, "results": res,
                       "extras": extras},
        "caveats": [
            "Leave-one-site-out AUC measures transfer between SURVEYED sites. "
            "It does not validate the Roaringwater output, where no kelp "
            "ground truth exists.",
            "There are no external positives anywhere outside the training "
            "sites, so sensitivity outside them is unmeasurable and the "
            "external test reports false positives only.",
            "The depth term partly reproduces the NPWS delineation rule; at "
            "Kenmare 41% of the shared class boundary lies within 3 m of 20 m "
            "against 7% of a control boundary.",
            "Cells with in_training_range = 0 are extrapolation and must be "
            "excluded from any area or euro figure.",
            "The Burrows wave-fetch licence has not been read.",
        ],
    }, indent=2, default=str), encoding="utf-8")
    print(f"  written: {OUT_DIR / 'model_multisite_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())