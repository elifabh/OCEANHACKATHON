#!/usr/bin/env python3
"""
covariate_check.py - the last two measurements before the model is coded.

Run circularity_check.py first: this script reuses its depth cache, its grid
and its statistics, and it only makes sense in light of its result.

WHAT circularity_check.py LEFT OPEN
Stratifying by 2 m depth bands gave, at Kenmare, pooled AUCs of slope 0.686,
curvature 0.673, log10 fetch 0.590, from 2 usable strata out of 5 and 638
cells. Two things in that result cannot be taken at face value.

  QUESTION 1 - ARE slope AND curvature THE SAME VARIABLE?
      Both are finite differences of the SAME depth surface, and their scores
      (0.686, 0.673) are suspiciously close. If they are strongly related they
      are one piece of evidence, not two, and putting both in the model
      double-counts it - which inflates apparent skill and is exactly the kind
      of thing a technical judge asks about.
      Measured two ways. First Spearman rank correlation, which is the right
      correlation to use because the AUC statistic is itself rank-based.
      Second, and decisively: does curvature still separate the classes with
      SLOPE held constant, and vice versa? Same stratification logic as before,
      one level deeper. Correlation says they move together; the conditional
      test says whether either carries information the other does not.

  QUESTION 2 - IS KENMARE ABLE TO TEST WAVE EXPOSURE AT ALL?
      Fetch scored 0.590, i.e. marginal. But the step 1 result that made wave
      exposure a candidate was a 6.2x sheltered-versus-exposed contrast
      BETWEEN AOIs, not within one. Kenmare River is a single inlet. If the
      fetch values inside it barely vary, then "fetch is marginal" is a fact
      about the test site and not about fetch, and the honest conclusion is
      that the question is still open and must be tested at Roaringwater.
      Measured by comparing the spread of fetch INSIDE Kenmare against the
      spread ACROSS the four AOIs, in the same units.

Units. The Burrows raster is log10 of summed fetch in 200 m cell units over 32
compass sectors. Converting to something interpretable:
    km per sector = 10**log10_value * 0.2 / 32
That reproduces the step 1 table exactly (mizen 4.033 -> 67.4 km/sector), which
is the check that the conversion is right rather than plausible.

WHAT THIS SCRIPT CANNOT FIX
The narrow support. Only 16-20 m had both classes in useful numbers, while half
the mapped kelp sits shallower than 10 m and there is almost no faunal turf
there to compare against. No amount of statistics creates a comparison that the
survey did not make. That is a limitation to state on the slide, not a bug.

Dependencies: numpy (BSD-3), geopandas (BSD-3), shapely (BSD-3), pyproj (MIT),
rasterio (BSD-3). All to DEPENDENCIES.md with versions.

Data: NPWS Reef Inventory 2023 layer 21; INFOMAR bathymetry (GSI & Marine
Institute) CC BY 4.0; Burrows wave fetch (LICENCE STILL UNREAD).

Usage:
    python src/covariate_check.py --selftest
    python src/covariate_check.py \
        --shp "data/npws/gis_files/21 NPWSArticle17Habitat.shp" \
        --fetch data/fetch/log10_eu200m1a.tif
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

OUT_DIR = Path("outputs/labels")

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

# Reuse rather than reimplement. One wrong AUC is better than two.
from circularity_check import (auc_separation, class_mask, grid_axes,
                               sample_depth_grid, sample_fetch_grid, terrain,
                               norm, MIN_N_PER_CLASS, COND_BAND, COND_BIN_M,
                               STRATUM_CONTROL_MAX, COND_NULL_TOL, COND_USEFUL)

# Burrows raster: log10 of summed fetch in 200 m cells over 32 sectors.
FETCH_CELL_KM = 0.2
FETCH_SECTORS = 32

# |rho| at or above which two covariates are called strongly related.
RHO_STRONG = 0.70
# |rho| at or above which one is effectively a monotone function of the other.
# At that point redundancy is arithmetic, not a statistical inference, and no
# further test is needed.
RHO_DUPLICATE = 0.95
# Grid the residual is snapped to before its AUC is taken, in rank units.
# See the note inside residual_auc - without this, floating-point noise in a
# numerically-zero residual is ranked as if it were signal.
RESID_SNAP = 1e-6

# Kenmare can only test fetch if its internal spread is at least this share of
# the between-AOI spread.
FETCH_RANGE_MIN_SHARE = 0.50


def log10_to_km_per_sector(v):
    """Interpretable units. Verified against the step 1 table in the selftest."""
    return (10.0 ** np.asarray(v, dtype=float)) * FETCH_CELL_KM / FETCH_SECTORS


def spearman(a, b) -> float:
    """Rank correlation, no scipy. NaN pairs dropped pairwise."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < 3:
        return float("nan")

    def rank(x):
        order = np.argsort(x, kind="mergesort")
        r = np.empty(x.size, dtype=float)
        r[order] = np.arange(1, x.size + 1, dtype=float)
        # average ranks within ties, or a tie-heavy variable gets a spuriously
        # strong correlation
        xs = x[order]
        i = 0
        while i < xs.size:
            j = i
            while j + 1 < xs.size and xs[j + 1] == xs[i]:
                j += 1
            if j > i:
                r[order[i:j + 1]] = (i + j + 2) / 2.0
            i = j + 1
        return r

    ra, rb = rank(a), rank(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


def usable_strata(mask, depth, bin_m=COND_BIN_M, span=COND_BAND):
    """The depth strata that passed circularity_check's control, as boolean masks.

    Rebuilt here rather than read from JSON so the two scripts cannot silently
    disagree about which cells the conclusion rests on.
    """
    lo_all, hi_all = span
    out = []
    x = lo_all
    while x < hi_all - 1e-9:
        lo, hi = x, min(x + bin_m, hi_all)
        x += bin_m
        sel = np.isfinite(depth) & (depth > lo) & (depth <= hi)
        pos, neg = sel & (mask == 1), sel & (mask == 2)
        if min(int(pos.sum()), int(neg.sum())) < MIN_N_PER_CLASS:
            continue
        ctrl = auc_separation(depth[pos].tolist(), depth[neg].tolist())
        if ctrl > STRATUM_CONTROL_MAX:
            continue
        out.append({"lo": lo, "hi": hi, "sel": sel, "pos": pos, "neg": neg,
                    "control_auc": round(ctrl, 4)})
    return out


# ---------------------------------------------------------------------------
# QUESTION 1 - are slope and curvature one variable or two?
# ---------------------------------------------------------------------------

def _rank(x: np.ndarray) -> np.ndarray:
    """Ranks with ties averaged."""
    order = np.argsort(x, kind="mergesort")
    r = np.empty(x.size, dtype=float)
    r[order] = np.arange(1, x.size + 1, dtype=float)
    xs = x[order]
    i = 0
    while i < xs.size:
        j = i
        while j + 1 < xs.size and xs[j + 1] == xs[i]:
            j += 1
        if j > i:
            r[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return r


def residual_auc(other: np.ndarray, target: np.ndarray, pos, neg):
    """Does `target` separate the classes AFTER the part shared with `other`
    is removed?

    WHY A RESIDUAL AND NOT A STRATIFIED TEST
    The first version of this function held `other` constant with quantile
    bins, the same trick that fixed the depth confound one level up. On a
    fixture where the two covariates were literally the same variable
    (rho = 1.000) it still reported that each contributed at AUC 0.965, which
    is impossible. The reason is structural, not a coding slip: a quantile bin
    boundary cuts through both class distributions asymmetrically, so the
    binned variable still separates the classes INSIDE every bin, near the
    edges. Coarse binning cannot hold a variable constant when that variable is
    itself what distinguishes the classes. More bins reduce it but never remove
    it, and there are only a few hundred cells to spend.

    So the shared part is REMOVED rather than sliced. Both variables are
    converted to ranks - so any monotone relationship is captured, not just a
    linear one, and consistently with the rank-based AUC - a least-squares line
    is fitted through them, and the AUC is taken on the residual. If `target`
    is a monotone function of `other`, the residual is zero and the AUC is
    exactly 0.5. Whatever separation survives is information `other` does not
    carry.

    Returns (auc, n_cells).
    """
    sel = (pos | neg) & np.isfinite(other) & np.isfinite(target)
    n = int(sel.sum())
    if n < 4 * MIN_N_PER_CLASS:
        return float("nan"), n

    ro = _rank(other[sel])
    rt = _rank(target[sel])
    so = ro.std()
    if so == 0:
        return float("nan"), n
    slope_fit = ((ro - ro.mean()) * (rt - rt.mean())).mean() / (so ** 2)
    resid = rt - (rt.mean() + slope_fit * (ro - ro.mean()))

    # SNAP THE RESIDUAL, and this is not cosmetic. When `target` is an exact
    # monotone function of `other` the residual is zero in exact arithmetic but
    # comes out as floating-point dust around 1e-14. auc_separation is
    # rank-based, so it happily ORDERS that dust and returned 0.827 on a
    # fixture where the two variables were literally the same array - i.e. it
    # reported a redundant covariate as strongly informative. Ranks are spaced
    # one unit apart, so anything below 1e-6 rank units cannot be real
    # structure; snapping to that grid turns the dust into ties, which is what
    # it is.
    resid = np.round(resid / RESID_SNAP) * RESID_SNAP

    lab = pos[sel]
    p_ = resid[lab].tolist()
    q_ = resid[~lab].tolist()
    if min(len(p_), len(q_)) < MIN_N_PER_CLASS:
        return float("nan"), n
    return auc_separation(p_, q_), n


def test_redundancy(mask, depth, covars: dict, strata) -> dict:
    """Are two covariates one piece of evidence or two?"""
    if not strata:
        print("  no usable depth stratum, so there is nothing to test in.")
        return {"verdict": "no_stratum"}

    keep = np.zeros(mask.shape, dtype=bool)
    pos = np.zeros(mask.shape, dtype=bool)
    neg = np.zeros(mask.shape, dtype=bool)
    for s in strata:
        keep |= s["sel"]
        pos |= s["pos"]
        neg |= s["neg"]
    band_desc = ", ".join(f"{s['lo']:.0f}-{s['hi']:.0f} m" for s in strata)
    print(f"  measured inside the usable strata only: {band_desc}")
    print(f"  cells: kelp {int(pos.sum())}, faunal turf {int(neg.sum())}")

    names = [c for c in covars if covars[c] is not None]
    out = {"strata": band_desc, "n_pos": int(pos.sum()),
           "n_neg": int(neg.sum()), "pairs": {}, "marginal_auc": {}}

    print(f"\n  {'covariate':<20}{'AUC in these strata':>22}")
    for c in names:
        arr = covars[c]
        ok = np.isfinite(arr)
        a = auc_separation(arr[pos & ok].tolist(), arr[neg & ok].tolist())
        out["marginal_auc"][c] = round(a, 4) if a == a else None
        print(f"  {c:<20}{a:>22.3f}")

    print(f"\n  {'pair':<30}{'Spearman rho':>14}")
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            arr_a, arr_b = covars[a], covars[b]
            m = keep & np.isfinite(arr_a) & np.isfinite(arr_b)
            rho = spearman(arr_a[m], arr_b[m])
            print(f"  {a + ' x ' + b:<30}{rho:>14.3f}")
            out["pairs"][f"{a} x {b}"] = {"rho": round(rho, 4)
                                          if rho == rho else None}

    # The decisive test: after removing the part each shares with the other,
    # does either still separate the classes?
    print("\n  residual test - shared part removed, not sliced:")
    print(f"\n  {'target':<20}{'shared part removed':<22}{'AUC':>8}{'n':>7}"
          "   verdict")
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            key = f"{a} x {b}"
            out["pairs"].setdefault(key, {})
            for target, other in ((a, b), (b, a)):
                auc, n = residual_auc(covars[other], covars[target], pos, neg)
                if auc != auc:
                    print(f"  {target:<20}{other:<22}{'-':>8}{n:>7}"
                          "   too few cells")
                    v = "untestable"
                else:
                    if abs(auc - 0.5) < COND_NULL_TOL:
                        v = "adds nothing"
                    elif auc < COND_USEFUL:
                        v = "marginal"
                    else:
                        v = "ADDS SOMETHING"
                    print(f"  {target:<20}{other:<22}{auc:>8.3f}{n:>7}   {v}")
                out["pairs"][key][f"{target}|resid of {other}"] = {
                    "auc": round(auc, 4) if auc == auc else None,
                    "n": n, "verdict": v}

    print("")
    for pair, d in out["pairs"].items():
        a, b = pair.split(" x ")
        rho = d.get("rho")
        va = d.get(f"{a}|resid of {b}", {}).get("verdict")
        vb = d.get(f"{b}|resid of {a}", {}).get("verdict")
        aa, ab = out["marginal_auc"].get(a), out["marginal_auc"].get(b)
        keeps = a if (aa or 0) >= (ab or 0) else b
        drop = b if keeps == a else a

        strong = rho is not None and abs(rho) >= RHO_STRONG
        duplicate = rho is not None and abs(rho) >= RHO_DUPLICATE
        a_adds = va in ("ADDS SOMETHING", "marginal")
        b_adds = vb in ("ADDS SOMETHING", "marginal")

        if duplicate:
            verdict = "redundant"
            print(f"  >>> {pair}: REDUNDANT. rho {rho:+.3f} means one is very")
            print("  >>> nearly a monotone function of the other - that is")
            print("  >>> arithmetic, not a statistical judgement. They are ONE")
            print(f"  >>> piece of evidence. Keep '{keeps}' (higher marginal")
            print(f"  >>> AUC), DROP '{drop}', and state on the slide that it")
            print("  >>> was dropped because it was MEASURED to be the same")
            print("  >>> signal, not because it looked less interesting.")
        elif strong and not a_adds and not b_adds:
            verdict = "redundant"
            print(f"  >>> {pair}: REDUNDANT. rho {rho:+.3f}, and neither has")
            print("  >>> any separating power left once the shared part is")
            print(f"  >>> removed. Keep '{keeps}', DROP '{drop}'.")
        elif strong and a_adds != b_adds:
            verdict = "nested"
            adder, other = (a, b) if a_adds else (b, a)
            print(f"  >>> {pair}: NESTED. rho {rho:+.3f}. '{adder}' carries")
            print(f"  >>> information beyond '{other}', but not the reverse.")
            print(f"  >>> Keep '{adder}', DROP '{other}'.")
        elif strong:
            verdict = "correlated_but_both_informative"
            print(f"  >>> {pair}: correlated (rho {rho:+.3f}) but each keeps")
            print("  >>> separating power after the shared part is removed.")
            print("  >>> Both may stay. But the model must NOT be presented as")
            print("  >>> having two independent lines of evidence, and any")
            print("  >>> variable-importance split between them is arbitrary.")
        elif not a_adds and not b_adds:
            verdict = "neither_informative"
            print(f"  >>> {pair}: rho is low ({rho:+.3f}) yet neither has")
            print("  >>> residual separating power. Odd - check for a")
            print("  >>> non-monotone relationship before trusting either.")
        else:
            verdict = "independent"
            print(f"  >>> {pair}: INDEPENDENT (rho {rho:+.3f}). Each carries")
            print("  >>> information the other does not. Both stay.")
        d["verdict"] = verdict
        d["keep"], d["drop"] = keeps, drop
    return out


# ---------------------------------------------------------------------------
# QUESTION 2 - can Kenmare test fetch at all?
# ---------------------------------------------------------------------------

def test_fetch_range(fetch_path: Path, grid_m: float,
                     labelled_fetch: np.ndarray | None = None) -> dict:
    """Fetch spread inside Kenmare against the spread across all four AOIs."""
    per_aoi = {}
    print(f"  {'AOI':<22}{'p5':>8}{'p25':>8}{'med':>8}{'p75':>8}{'p95':>8}"
          f"{'km/sector med':>15}")
    for name, bbox in AOIS.items():
        arr = sample_fetch_grid_quiet(fetch_path, bbox, grid_m)
        if arr is None:
            print(f"  {name:<22}   no fetch coverage")
            per_aoi[name] = None
            continue
        v = arr[np.isfinite(arr)]
        if v.size == 0:
            print(f"  {name:<22}   no valid cells")
            per_aoi[name] = None
            continue
        p5, p25, med, p75, p95 = np.percentile(v, [5, 25, 50, 75, 95])
        km = log10_to_km_per_sector(med)
        print(f"  {name:<22}{p5:>8.3f}{p25:>8.3f}{med:>8.3f}{p75:>8.3f}"
              f"{p95:>8.3f}{km:>15.1f}")
        per_aoi[name] = {"p5": round(float(p5), 4), "p25": round(float(p25), 4),
                         "median": round(float(med), 4),
                         "p75": round(float(p75), 4),
                         "p95": round(float(p95), 4),
                         "km_per_sector_median": round(float(km), 2),
                         "n": int(v.size)}

    ken = per_aoi.get("kenmare_river")
    valid = {k: v for k, v in per_aoi.items() if v}
    if not ken or len(valid) < 2:
        print("\n  >>> cannot compare: Kenmare or the other AOIs have no fetch.")
        return {"verdict": "unmeasurable", "per_aoi": per_aoi}

    # Inside Kenmare, the range the model actually saw is the LABELLED cells,
    # not the whole box - most of the box is land or unlabelled water.
    if labelled_fetch is not None:
        lv = labelled_fetch[np.isfinite(labelled_fetch)]
        if lv.size:
            l5, l95 = np.percentile(lv, [5, 95])
            print(f"\n  Kenmare LABELLED cells only ({lv.size} cells): "
                  f"p5 {l5:.3f}, p95 {l95:.3f}")
            print(f"    = {log10_to_km_per_sector(l5):.1f} to "
                  f"{log10_to_km_per_sector(l95):.1f} km/sector")
            ken = {**ken, "p5": float(l5), "p95": float(l95),
                   "scope": "labelled cells"}

    internal = ken["p95"] - ken["p5"]
    meds = [v["median"] for v in valid.values()]
    between = max(meds) - min(meds)
    share = internal / between if between > 0 else float("inf")

    print(f"\n  spread INSIDE Kenmare  (p95-p5 of log10) : {internal:.3f}"
          f"   = {log10_to_km_per_sector(ken['p95']) / max(log10_to_km_per_sector(ken['p5']), 1e-9):.1f}x")
    print(f"  spread BETWEEN AOIs    (max-min median)  : {between:.3f}"
          f"   = {10 ** between:.1f}x")
    print(f"  ratio                                    : {share:.2f}")

    if share >= FETCH_RANGE_MIN_SHARE:
        verdict = "kenmare_can_test_fetch"
        print("\n  >>> KENMARE HAS ENOUGH EXPOSURE RANGE. The marginal fetch")
        print("  >>> score is a real result about fetch, not an artefact of")
        print("  >>> the test site. Report it as measured.")
    else:
        verdict = "kenmare_cannot_test_fetch"
        print("\n  >>> KENMARE CANNOT TEST FETCH. Its internal exposure range")
        print(f"  >>> is only {share:.0%} of the between-AOI range, so a")
        print("  >>> marginal score here is a property of the SITE, not of the")
        print("  >>> covariate. The step 1 conclusion that wave exposure")
        print("  >>> matters is neither confirmed nor refuted - it is UNTESTED.")
        print("  >>> Honest wording: \"wave exposure could not be evaluated at")
        print("  >>>  the training site, which spans a narrow exposure range.")
        print("  >>>  It is retained on published grounds (Bekkby et al. 2009)")
        print("  >>>  and its effect is reported at Roaringwater, where the")
        print("  >>>  sheltered-to-exposed contrast is 6.2x.\"")
        print("  >>> Do NOT quote 0.590 as evidence that fetch is weak.")
    return {"verdict": verdict, "per_aoi": per_aoi,
            "internal_log10_range": round(float(internal), 4),
            "between_aoi_log10_range": round(float(between), 4),
            "ratio": round(float(share), 4)}


def sample_fetch_grid_quiet(path, bbox, grid_m):
    """sample_fetch_grid without its per-AOI print."""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return sample_fetch_grid(path, bbox, grid_m)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    print("SELFTEST (no network, no files)\n")

    # --- unit conversion against the step 1 table -------------------------
    # mizen_outer median log10 4.033 was reported as 67.4 km/sector. If the
    # conversion is wrong, every exposure figure on the slide is wrong.
    got = float(log10_to_km_per_sector(4.033))
    assert abs(got - 67.4) < 0.2, got
    got2 = float(log10_to_km_per_sector(3.228))
    assert abs(got2 - 10.6) < 0.2, got2
    print(f"  log10 4.033 -> {got:.1f} km/sector (step 1 table: 67.4)  ok")
    print(f"  log10 3.228 -> {got2:.1f} km/sector (step 1 table: 10.6)  ok")

    # --- spearman ---------------------------------------------------------
    x = np.arange(50, dtype=float)
    assert abs(spearman(x, x) - 1.0) < 1e-9
    assert abs(spearman(x, -x) + 1.0) < 1e-9
    rng = np.random.default_rng(3)
    assert abs(spearman(rng.normal(size=500), rng.normal(size=500))) < 0.15
    # monotone but non-linear must still be 1.0 - that is the point of using
    # a rank correlation rather than Pearson
    assert abs(spearman(x, np.exp(x / 10)) - 1.0) < 1e-9
    # a zero-variance variable has no correlation to report; it must return
    # NaN rather than 0.0, because 0.0 would read as "measured, uncorrelated"
    flat = np.zeros(50)
    z = spearman(x, flat)
    assert z != z, z                      # NaN
    print("  spearman: +1 / -1 / ~0, monotone-nonlinear = +1, flat = NaN  ok")

    # residual_auc: a monotone copy must leave EXACTLY nothing behind
    pos_m = np.zeros(200, dtype=bool); pos_m[:100] = True
    neg_m = ~pos_m
    sig = np.concatenate([np.linspace(1, 2, 100), np.linspace(0, 1, 100)])
    dup = sig * 4.0 + 11.0
    a_dup, _ = residual_auc(dup, sig, pos_m, neg_m)
    assert abs(a_dup - 0.5) < 1e-9, a_dup
    # a non-linear monotone copy too - this is why ranks are used, not values
    a_exp, _ = residual_auc(np.exp(sig), sig, pos_m, neg_m)
    assert abs(a_exp - 0.5) < 1e-9, a_exp
    # and something genuinely independent must survive. The regressor is
    # built to be PROVABLY free of class information - the same values in both
    # halves - rather than drawn at random, because a single random draw can
    # correlate with the class split by chance and then the threshold below
    # would be measuring the draw instead of the function.
    seeded = np.random.default_rng(11)
    indep = np.where(pos_m, 1.0, 0.0) + seeded.normal(0, 0.2, 200)
    balanced = np.concatenate([np.arange(100.0), np.arange(100.0)])
    assert abs(spearman(balanced, pos_m.astype(float))) < 1e-12
    a_ind, _ = residual_auc(balanced, indep, pos_m, neg_m)
    assert a_ind > 0.95, a_ind
    print(f"  residual_auc: monotone copy -> 0.500 (linear and exponential),")
    print(f"                independent signal survives at {a_ind:.3f}  ok")

    # --- synthetic redundancy scenarios -----------------------------------
    ny, nx = 60, 60
    depth = np.full((ny, nx), 17.0)
    mask = np.zeros((ny, nx), dtype=int)
    mask[:, :nx // 2] = 1
    mask[:, nx // 2:] = 2
    strata = usable_strata(mask, depth, bin_m=2.0, span=(16.0, 18.0))
    assert len(strata) == 1, strata

    base = np.where(mask == 1, 1.0, 0.0) + rng.normal(0, 0.25, (ny, nx))

    # CASE A: a duplicate. Must be called redundant.
    print("\n  --- case A: B is a rescaled copy of A ---")
    ra = test_redundancy(mask, depth, {"A": base, "B": base * 3.0 + 7.0},
                         strata)
    assert ra["pairs"]["A x B"]["verdict"] == "redundant", ra
    assert abs(ra["pairs"]["A x B"]["rho"] - 1.0) < 1e-6, ra

    # CASE B: two genuinely independent separating covariates. MUST give the
    # other answer, or case A proves nothing.
    print("\n  --- case B: two covariates with independent information ---")
    # noise deliberately larger than in case A, so rho lands BELOW RHO_STRONG.
    # Case A only proves the function can say "redundant"; this one has to
    # prove it can say the opposite, or the first assertion is worthless.
    other = np.where(mask == 1, 1.0, 0.0) + rng.normal(0, 0.5, (ny, nx))
    rb = test_redundancy(mask, depth, {"A": base, "C": other}, strata)
    assert abs(rb["pairs"]["A x C"]["rho"]) < RHO_STRONG, rb["pairs"]
    assert rb["pairs"]["A x C"]["verdict"] == "independent", rb["pairs"]
    assert rb["pairs"]["A x C"]["keep"] in ("A", "C")
    print("\n  redundancy: duplicate detected, independent pair not"
          " misreported  ok")

    # --- fetch range: narrow vs wide, using a synthetic raster ------------
    import tempfile
    import rasterio
    from rasterio.transform import from_origin

    with tempfile.TemporaryDirectory() as d:
        def write(path, fn):
            # one raster covering all four AOIs, in WGS84 for simplicity
            w, h = 400, 400
            lon0, lat0 = -10.2, 52.1
            res = 0.003
            arr = np.zeros((h, w), dtype="float32")
            for i in range(h):
                for j in range(w):
                    arr[i, j] = fn(lon0 + j * res, lat0 - i * res)
            with rasterio.open(
                    path, "w", driver="GTiff", height=h, width=w, count=1,
                    dtype="float32", crs="EPSG:4326",
                    transform=from_origin(lon0, lat0, res, res),
                    nodata=-999.0) as dst:
                dst.write(arr, 1)

        # NARROW inside Kenmare (lat > 51.7), wide between AOIs.
        narrow = Path(d) / "narrow.tif"
        write(narrow, lambda lo, la: 3.60 if la > 51.70 else
              (4.05 if lo < -9.60 else 3.25))
        print("\n  --- fetch case A: Kenmare internally flat ---")
        fa = test_fetch_range(narrow, 200.0)
        assert fa["verdict"] == "kenmare_cannot_test_fetch", fa

        # WIDE inside Kenmare: a strong east-west gradient in the Kenmare box.
        wide = Path(d) / "wide.tif"
        write(wide, lambda lo, la: (2.8 + (lo + 9.93) / 0.15 * 1.4)
              if la > 51.70 else (4.05 if lo < -9.60 else 3.25))
        print("\n  --- fetch case B: Kenmare spans a real gradient ---")
        fb = test_fetch_range(wide, 200.0)
        assert fb["verdict"] == "kenmare_can_test_fetch", fb
        print("\n  fetch range: 'cannot test' AND 'can test' both reachable"
              "  ok")

    print("\nSELFTEST PASSED. The km/sector conversion reproduces the step 1")
    print("table, spearman is a true rank correlation, a duplicated covariate")
    print("is called redundant while an independent pair is not, and the fetch")
    print("range test can return both verdicts. Nothing touched INFOMAR.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Finalise the model term list: redundancy and fetch range.")
    ap.add_argument("--shp", type=Path)
    ap.add_argument("--fetch", type=Path, required=False)
    ap.add_argument("--aoi", default="kenmare_river", choices=sorted(AOIS))
    ap.add_argument("--grid", type=float, default=50.0)
    ap.add_argument("--band", type=float, nargs=2, default=list(COND_BAND))
    ap.add_argument("--bin", type=float, default=COND_BIN_M)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not HAVE_COMMON:
        print("cannot import common.py - run from the repo root.")
        return 2
    if not args.shp or not args.shp.exists():
        print("--shp is required and must exist (quote the path, it has a "
              "space)")
        return 2

    import geopandas as gpd
    from pyproj import Transformer
    from shapely.geometry import box as sbox

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    to_itm = Transformer.from_crs(4326, CRS_FOR_AREA, always_xy=True)
    name, bbox = args.aoi, AOIS[args.aoi]

    print("NPWS layer 21 x INFOMAR bathymetry (GSI & Marine Institute, "
          "CC BY 4.0).")
    if args.fetch:
        print("Wave fetch: Burrows, figshare. LICENCE STILL UNREAD.")
    print(f"AOI {name}, grid {args.grid:.0f} m.\n")

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

    x0, y0 = to_itm.transform(bbox[0], bbox[1])
    x1, y1 = to_itm.transform(bbox[2], bbox[3])
    clip = sbox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    local = gdf[gdf.geometry.intersects(clip)].copy()
    local["geometry"] = local.geometry.intersection(clip)
    local = local[local.geometry.notna() & ~local.geometry.is_empty].copy()

    print("=" * 74)
    print("LOADING (depth comes from the circularity_check cache)")
    print("=" * 74)
    depth = sample_depth_grid(name, bbox, args.grid, use_cache=True)
    slope, curv = terrain(depth, args.grid)
    fetch = sample_fetch_grid(args.fetch, bbox, args.grid) if args.fetch \
        else None
    mask, conf = class_mask(bbox, args.grid, local, to_itm)
    print(f"  labelled cells: kelp {int((mask == 1).sum())}, "
          f"faunal turf {int((mask == 2).sum())}, conflicts {conf}")

    strata = usable_strata(mask, depth, bin_m=args.bin,
                           span=(args.band[0], args.band[1]))
    if strata:
        desc = ", ".join(f"{st['lo']:.0f}-{st['hi']:.0f} m" for st in strata)
        print(f"  usable depth strata: {len(strata)}  ({desc})")
    else:
        print("  usable depth strata: 0")

    print("\n" + "=" * 74)
    print("QUESTION 1  ARE slope AND curvature THE SAME VARIABLE?")
    print("=" * 74)
    q1 = test_redundancy(mask, depth,
                         {"slope (deg)": slope, "curvature": curv}, strata)

    print("\n" + "=" * 74)
    print("QUESTION 2  CAN KENMARE TEST WAVE EXPOSURE AT ALL?")
    print("=" * 74)
    if not args.fetch:
        print("  --fetch not supplied; skipped.")
        q2 = {"verdict": "not_run"}
    else:
        lab = None
        if fetch is not None:
            lab = np.where((mask == 1) | (mask == 2), fetch, np.nan)
        q2 = test_fetch_range(args.fetch, args.grid, lab)

    print("\n" + "=" * 74)
    print("FINAL MODEL TERM LIST")
    print("=" * 74)
    terms = ["depth band (taken as given - the NPWS boundary is partly "
             "depth-guided)"]
    dropped = []
    pair = q1.get("pairs", {}).get("slope (deg) x curvature", {})
    pv = pair.get("verdict")
    if pv in ("redundant", "nested"):
        terms.append(f"{pair['keep']} (terrain, substrate proxy after "
                     f"Bekkby et al. 2009)")
        dropped.append(f"{pair['drop']} - MEASURED to be the same signal as "
                       f"{pair['keep']} (rho {pair.get('rho')})")
    elif pv == "neither_informative":
        dropped.append("slope AND curvature - neither has residual separating "
                       "power; investigate before using either")
    elif pv is None:
        terms.append("slope (deg) - redundancy UNTESTED (no usable stratum)")
        terms.append("curvature - redundancy UNTESTED (no usable stratum)")
    else:
        terms.append("slope (deg)")
        terms.append("curvature")
        if pv == "correlated_but_both_informative":
            terms.append("   ^ both kept, but they are correlated: do not "
                         "claim two independent lines of evidence")

    if q2.get("verdict") == "kenmare_cannot_test_fetch":
        terms.append("log10 fetch - RETAINED ON PUBLISHED GROUNDS ONLY "
                     "(Bekkby et al. 2009); untested at the training site")
    elif q2.get("verdict") == "kenmare_can_test_fetch":
        terms.append("log10 fetch - measured at the training site")
    else:
        terms.append("log10 fetch - status unresolved, --fetch not supplied")

    for t in terms:
        print(f"  KEEP  {t}")
    for t in dropped:
        print(f"  DROP  {t}")

    print("\n  LIMITATION THAT MUST GO ON THE SLIDE, VERBATIM:")
    n_cells = sum(int(s['pos'].sum()) + int(s['neg'].sum()) for s in strata)
    band_desc = ", ".join(f"{s['lo']:.0f}-{s['hi']:.0f} m" for s in strata) \
        or "none"
    print(f'    "Covariate contributions are measured only where the two')
    print(f'     surveyed classes co-occur in depth ({band_desc}),')
    print(f'     n = {n_cells} cells. Half the mapped kelp lies shallower than')
    print(f'     10 m, where the survey recorded almost no faunal turf reef to')
    print(f'     compare against. The contribution is therefore demonstrated')
    print(f'     for the deep edge of the kelp band, not for the whole of it."')

    (OUT_DIR / "covariate_verdicts.json").write_text(json.dumps(
        {"aoi": name, "grid_m": args.grid,
         "usable_strata": [{k: v for k, v in s.items() if k != "sel"
                            and not isinstance(v, np.ndarray)}
                           for s in strata],
         "redundancy": {k: v for k, v in q1.items()},
         "fetch_range": q2,
         "model_terms_keep": terms, "model_terms_drop": dropped,
         "n_cells_behind_conclusion": n_cells},
        indent=2, default=str), encoding="utf-8")
    print(f"\n  written: {OUT_DIR / 'covariate_verdicts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())