#!/usr/bin/env python3
"""
restoration_priority.py -- the layer the published challenge promised.

WHY THIS EXISTS
---------------
The Ocean Hackathon challenge description promises "restoration priority" and
this project never built it. It can be built from what already exists: the
step-2 suitability model v2 says where the physical conditions suit
L. hyperborea, and the NPWS Article 17 survey says where L. hyperborea has
actually been recorded. Where the first says yes and the second does not say
yes, there is a candidate.

WHAT THIS LAYER IS NOT
----------------------
It is not a management recommendation, it carries no euro, and it never
enters any valuation row. It is a map of where a question is worth asking.

THE ONE NUMBER THAT DECIDES HOW MUCH TO BELIEVE IT
---------------------------------------------------
The model's own acceptance criteria, in outputs/model/model_multisite_report.json,
set a maximum external false-positive rate of 30 %. The measured rate is
63.4 % -- 599 of the 944 surveyed cells that are NOT Laminaria score above the
operating threshold anyway -- and the report records that criterion as FAILED.
(The prose here is a summary; every rate the code prints is read from the
report at run time, never typed.)

That matters more here than anywhere else in the project, because those 599
cells ARE this layer's class R1. The same cells that make the model's external
FPR a failure are the cells the layer proposes. So the layer's headline class
cannot be presented as "here is where restoration should happen"; the honest
reading is "here is where the model and the survey disagree, and the model is
wrong about that disagreement roughly two times in three."

This is stated on the layer itself, not buried here. A restoration layer whose
false-positive rate is not on its face is a recommendation pretending to be a
map.

THE TWO CLASSES, KEPT APART
---------------------------
R1  SURVEYED, ANOTHER COMMUNITY RECORDED  (npws_label == 2)
    NPWS looked, recorded faunal-turf reef rather than Laminaria, and the
    model says the conditions suit Laminaria. This is a genuine "suitable but
    kelp not recorded" cell -- and see the FPR paragraph above.

R2  NEVER SURVEYED FOR COMMUNITY  (npws_label == 0)
    No NPWS Article 17 community polygon covers the cell at all. The model
    says the conditions suit Laminaria; nobody has looked. These are SURVEY
    candidates, not restoration candidates, and conflating the two would turn
    "we do not know" into "it is not there". They are carried in the same
    file and rendered differently, never summed with R1.

WHAT IS EXCLUDED, AND WHY
-------------------------
* Cells that are not `assessed` -- i.e. off mapped reef or outside the
  model's training range. The model report bans area figures from
  extrapolation cells and this layer obeys that ban.
* `inner_roaringwater` in full. CLAUDE.md rule 6: MERC (2007) records
  Saccharina/Saccorhiza there, not L. hyperborea, so the AOI is locked out of
  positive kelp labelling. It holds 473 of the 599 R1 cells, so this
  exclusion removes most of the layer -- which is the point of the rule.
* Cells overlapping the Sentinel-2 intertidal macroalgae extent. This is an
  EXCLUSION ONLY and never a merge (CLAUDE.md rule 5): the detection is
  species-agnostic and intertidal, the model is L. hyperborea and subtidal,
  and the two layers are kept visually and verbally distinct everywhere.
  Removing overlaps can only shrink the candidate set, so using a
  species-agnostic layer this way cannot manufacture a candidate.

RANKING
-------
By suitability, descending, within class. The rank is ordinal. A cell ranked
first is not "twice as good" as one ranked second; the model outputs a
probability that was calibrated to a 0.9-specificity operating point, not to
a restoration benefit.

Run:  python src/restoration_priority.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
MODEL = REPO / "outputs" / "model"
OUT = REPO / "outputs" / "restoration"

PRED = MODEL / "suitability_multisite_predictions.csv"
REPORT = MODEL / "model_multisite_report.json"
GAP = REPO / "outputs" / "habitat_gap_model_cells.csv"
INTERTIDAL = REPO / "outputs" / "intertidal" / \
    "extent_sherkin_baltimore_7scenes.geojson"

CELL_HA = 0.25                       # 50 m grid
LOCKED_OUT_AOIS = {"inner_roaringwater"}    # CLAUDE.md rule 6

LAYER_LABEL = ("restoration candidate - modelled suitability without "
               "recorded presence; indicative, not a management "
               "recommendation")


def load_report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def external_fpr(rep: dict) -> dict:
    """The model's own external false-positive rate, read not recomputed."""
    acc = rep["acceptance"]["results"]["external_fpr"]
    thr = rep["acceptance"]["thresholds"]["external_false_positive_max"]
    return {"value": acc["value"], "n": acc["n"], "threshold_max": thr,
            "passes": bool(acc["pass"]),
            "meaning": f"{acc['value']:.1%} of the {acc['n']} surveyed cells "
                       f"that are NOT Laminaria score above the operating "
                       f"threshold anyway. The model's acceptance criterion "
                       f"was {thr:.0%} and it is recorded as FAILED. Those "
                       f"same cells are this layer's class R1."}


def intertidal_mask(df: pd.DataFrame) -> np.ndarray:
    """True where a cell centre falls inside the Sentinel-2 intertidal extent.

    Exclusion only. Never a merge (CLAUDE.md rule 5).
    """
    if not INTERTIDAL.exists():
        return np.zeros(len(df), dtype=bool)
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    g = gpd.read_file(INTERTIDAL).to_crs("EPSG:4326")
    polys = [p for p in g.geometry if p is not None and not p.is_empty]
    if not polys:
        return np.zeros(len(df), dtype=bool)
    tree = STRtree(polys)
    out = np.zeros(len(df), dtype=bool)
    for i, (lo, la) in enumerate(zip(df.lon.values, df.lat.values)):
        pt = Point(float(lo), float(la))
        out[i] = any(polys[j].covers(pt) for j in tree.query(pt))
    return out


def build() -> dict:
    rep = load_report()
    thr = float(rep["operating_threshold"])
    fpr = external_fpr(rep)

    frames = []
    for src, path in (("aoi", PRED), ("gap", GAP)):
        if not path.exists():
            print(f"   {path.name} absent -- source '{src}' NOT included")
            continue
        d = pd.read_csv(path)
        d["source"] = src
        frames.append(d)
    if not frames:
        raise SystemExit("no prediction table on disk")
    d = pd.concat(frames, ignore_index=True)

    funnel = [("all model cells", len(d))]
    a = d[d.assessed == 1].copy()
    funnel.append(("assessed (in training range AND on mapped reef)", len(a)))
    a = a[a.suitability >= thr]
    funnel.append((f"+ suitability >= {thr:.4f} (operating threshold)", len(a)))
    a = a[a.npws_label != 1]
    funnel.append(("+ no NPWS Laminaria record on the cell", len(a)))
    before = len(a)
    a = a[~a.aoi.isin(LOCKED_OUT_AOIS)]
    funnel.append((f"+ drop {sorted(LOCKED_OUT_AOIS)} (CLAUDE.md rule 6)",
                   len(a)))
    locked_out_n = before - len(a)

    inter = intertidal_mask(a)
    a = a[~inter]
    funnel.append(("+ drop cells inside the Sentinel-2 intertidal extent "
                   "(exclusion only, never a merge)", len(a)))

    a["restoration_class"] = np.where(a.npws_label == 2, "R1", "R2")
    a["class_meaning"] = np.where(
        a.npws_label == 2,
        "surveyed, another community recorded (NPWS faunal turf)",
        "never surveyed for community")
    a = a.sort_values(["restoration_class", "suitability"],
                      ascending=[True, False]).reset_index(drop=True)
    a["rank_in_class"] = a.groupby("restoration_class").cumcount() + 1
    a["layer_label"] = LAYER_LABEL

    cols = ["restoration_class", "class_meaning", "rank_in_class", "aoi",
            "source", "lon", "lat", "suitability", "depth_m", "slope_deg",
            "log10_fetch", "on_mapped_reef", "in_training_range",
            "npws_label", "layer_label"]
    a = a[cols]

    summary = {
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "layer_label": LAYER_LABEL,
        "operating_threshold": thr,
        "cell_ha": CELL_HA,
        "model": {"version": "v2", "auc_loso": rep["auc"]["leave_one_site_out"],
                  "worst_site_auc": rep["auc"]["worst_site"]},
        "external_false_positive_rate": fpr,
        "funnel": [{"step": s, "cells": n} for s, n in funnel],
        "locked_out_cells": {"aois": sorted(LOCKED_OUT_AOIS),
                             "cells_removed": int(locked_out_n),
                             "rule": "CLAUDE.md rule 6 -- MERC 2007 records "
                                     "Saccharina/Saccorhiza at inner "
                                     "Roaringwater, not L. hyperborea"},
        "intertidal_overlap_removed": int(inter.sum()),
        "classes": {},
        "euro": "NONE. This layer carries no monetary value and never enters "
                "a valuation row.",
    }
    for cls, g in a.groupby("restoration_class"):
        summary["classes"][cls] = {
            "meaning": g.class_meaning.iloc[0],
            "cells": int(len(g)),
            "ha": round(len(g) * CELL_HA, 2),
            "suitability_median": round(float(g.suitability.median()), 4),
            "suitability_max": round(float(g.suitability.max()), 4),
            "by_aoi": {k: int(v) for k, v in g.aoi.value_counts().items()},
            "is_a_restoration_candidate":
                cls == "R1",
            # The rate is interpolated from the report, never typed: a
            # hardcoded percentage beside a computed one is how the two
            # drift apart without anyone noticing.
            "caveat": (f"These are the same cells that make the model's "
                       f"external false-positive rate {fpr['value']:.1%} and "
                       f"fail its own acceptance criterion "
                       f"(<= {fpr['threshold_max']:.0%}). Roughly two in "
                       f"three are expected to be model error, not "
                       f"restoration opportunity." if cls == "R1" else
                       "SURVEY candidates, not restoration candidates. "
                       "Nobody has looked. 'We do not know' must not be "
                       "rendered as 'it is not there'."),
        }
    return {"table": a, "summary": summary}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    res = build()
    a, s = res["table"], res["summary"]

    print("=" * 78)
    print("RESTORATION PRIORITY LAYER")
    print("=" * 78)
    print(f"label: {LAYER_LABEL}")
    print()
    print("THE FUNNEL")
    for step in s["funnel"]:
        print(f"   {step['step']:62s} {step['cells']:7,d} cells")
    print()
    print("THE NUMBER THAT DECIDES HOW MUCH TO BELIEVE THIS LAYER")
    f = s["external_false_positive_rate"]
    print(f"   external false-positive rate {f['value']:.1%} "
          f"(criterion <= {f['threshold_max']:.0%}) -- "
          f"{'PASS' if f['passes'] else 'FAILED'}")
    print(f"   {f['meaning']}")
    print()
    print("CLASSES -- never summed with each other")
    for cls, c in s["classes"].items():
        print(f"   {cls}  {c['meaning']}")
        print(f"        {c['cells']:,} cells = {c['ha']:,.2f} ha   "
              f"suitability median {c['suitability_median']:.3f}, "
              f"max {c['suitability_max']:.3f}")
        print(f"        by AOI: {c['by_aoi']}")
        print(f"        {c['caveat']}")
        print()
    print(f"euro: {s['euro']}")

    a.to_csv(OUT / "restoration_candidates.csv", index=False)
    (OUT / "restoration_summary.json").write_text(
        json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

    # GeoJSON for the map: 50 m squares in EPSG:2157, written back in 4326.
    import geopandas as gpd
    from shapely.geometry import box
    from pyproj import Transformer
    to_itm = Transformer.from_crs("EPSG:4326", "EPSG:2157", always_xy=True)
    to_wgs = Transformer.from_crs("EPSG:2157", "EPSG:4326", always_xy=True)
    geoms = []
    for lo, la in zip(a.lon, a.lat):
        x, y = to_itm.transform(float(lo), float(la))
        geoms.append(box(x - 25, y - 25, x + 25, y + 25))
    g = gpd.GeoDataFrame(a.copy(), geometry=geoms, crs="EPSG:2157")
    # Area recomputed in ITM per the CLAUDE.md area rule, then verified.
    ha = float(g.area.sum() / 1e4)
    expect = len(g) * CELL_HA
    if abs(ha - expect) > 0.01:
        raise SystemExit(f"area check failed: {ha:.3f} ha != {expect:.3f} ha")
    print(f"\narea check (EPSG:2157): {ha:.2f} ha == {expect:.2f} ha expected")
    g.to_crs("EPSG:4326").to_file(OUT / "restoration_candidates.geojson",
                                  driver="GeoJSON")
    print(f"written: {OUT / 'restoration_candidates.csv'}")
    print(f"written: {OUT / 'restoration_candidates.geojson'}")
    print(f"written: {OUT / 'restoration_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
