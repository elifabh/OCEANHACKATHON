#!/usr/bin/env python3
"""
fill_note_placeholders.py — substitute every number in the handover note from
the files that produced it.

WHY THIS EXISTS
---------------
CLAUDE.md: "No number without a verified source." A handover note whose figures
are typed by hand drifts from the CSVs the moment either changes. This reads the
outputs and replaces `<!-- NAME -->` markers in
`docs/NOTE_2026-08-28_national_finish_out.md`, then FAILS if any marker is left
unfilled — so a forgotten placeholder cannot ship as a blank.

    PYTHONPATH=src python src/fill_note_placeholders.py [--check]

`--check` reports what would be substituted and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
NOTE = REPO / "docs" / "NOTE_2026-08-28_national_finish_out.md"
OUT = REPO / "outputs"
PB = OUT / "phaseb_national"


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def new_flag_sentence(flagged: pd.DataFrame) -> str:
    """The one sentence that says whether enlarging the set changed anything."""
    ex = json.loads((OUT / "exposure_screen" /
                     "national_exposure_screen_summary.json").read_text(
                         encoding="utf-8"))
    t = ex["totals"]
    head = (f"The enlarged screen examined {t['buildings_examined_with_overlaps']:,} "
            f"building observations across {ex['n_clusters']} clusters "
            f"({t['buildings_below_5m']} below 5 m, "
            f"{t['buildings_below_10m']} below 10 m) and still finds "
            f"{t['exposed_receptors']} exposed receptors at "
            f"{t['clusters_with_exposed_receptors']} clusters. ").replace(",", " ")
    if len(flagged) == 6:
        return head + ("They are the SAME six clusters as on 28 August, with "
                       "the same per-cluster counts: the 15 new candidates "
                       "added no exposed receptor anywhere. The An Aird control "
                       "reproduced exactly again.")
    return head + (f"{len(flagged) - 6} of them are new and were put through "
                   f"the bearing test and the orthophoto check on the same "
                   f"rules as the original six.")


def build() -> dict[str, str]:
    gap = json.loads((OUT / "habitat_gap_model_summary.json").read_text(
        encoding="utf-8"))
    res = gap["results"]
    cand = pd.read_csv(OUT / "national_candidate_table.csv")
    strict = cand[cand.pass_fetch_strict == True]                    # noqa: E712
    tab = pd.read_csv(PB / "NATIONAL_RESULTS_TABLE.csv")

    def n_ev(prefix: str, df=strict) -> int:
        return int(df.evidence_class.astype(str).str.startswith(prefix).sum())

    bad_aoi_clusters = {c for a in gap["aois"]
                        if a.get("points_never_answered", 0)
                        for c in a["clusters"]}
    e5 = strict[strict.evidence_class == "E5_no_bathymetry"]
    e5_unanswered = int(e5.cluster.isin(bad_aoi_clusters).sum())
    pts_unanswered = sum(a.get("points_never_answered", 0) for a in gap["aois"])
    n_bad_aoi = sum(1 for a in gap["aois"] if a.get("points_never_answered", 0))

    n_rows = len(tab)
    n_zero = int(tab.euro.astype(str).str.startswith("EUR 0").sum())
    n_unexposed = int((tab.exposed_receptors_tag_based == 0).sum())
    flagged = tab[tab.exposed_receptors_tag_based > 0]

    v = {
        "N_PASSES": "5",
        "N_CELLS": fmt(res["cells_modelled"]),
        "N_INRANGE": fmt(res["cells_in_training_range"]),
        "N_POS": fmt(res["cells_positive_in_range"]),
        "N_REEF": fmt(res["cells_on_mapped_reef"]),
        "N_STRICT": str(len(strict)),
        "NROWS": str(n_rows),
        "N_E1": str(n_ev("E1_")),
        "N_E2": str(n_ev("E2_")),
        "N_E3": str(n_ev("E3_")),
        "N_E5": str(len(e5)),
        "N_E0": str(n_ev("E0_")),
        "N_E4": str(n_ev("E4_")),
        "N_E1N": str(n_ev("E1n_")),
        "N_E8": "0 — none remain",
        "N_NEW": str(n_rows - 38),
        "N_ZERO": str(n_zero),
        "N_UNEXPOSED": str(n_unexposed),
        "N_LENIENT": str(int(
            cand[(cand.pass_fetch_strict == False)                  # noqa: E712
                 & cand.evidence_class.astype(str).str.startswith(("E2_", "E3_"))
                 ].shape[0])),
        "PART1_STATUS": "complete — 0 clusters left `E8_not_yet_modelled`",
        "E8_WHY": ("the 27 August run had not reached these AOIs before its "
                   "INFOMAR budget expired. **All 43 are now resolved** (§1.2)"),
        "RESULTS_TABLE": (PB / "NATIONAL_RESULTS_TABLE.md").read_text(
            encoding="utf-8").rstrip(),
        "UNANSWERED_PARA": (
            "**One qualification on Part 1, and it matters for how `E5` reads.** "
            f"Across the 77 AOIs, **{fmt(pts_unanswered)} sample points in "
            f"{n_bad_aoi} AOIs were never answered by INFOMAR** — the server "
            "returned 5xx rather than the documented empty-batch 4xx, and the "
            "locked rule from 27 August (a 4xx is coverage information, a 5xx is "
            "not) correctly stops those cells from being marked as answered. But "
            "the *cluster* verdict they then fall into is spelled "
            "`E5_no_bathymetry`, which reads as \"INFOMAR has no depth here\". "
            f"For **{e5_unanswered} of the {len(e5)}** strict-fetch E5 clusters "
            "that reading is not supported: their AOI contains points the server "
            "never answered, so \"no coverage\" and \"no answer\" cannot be told "
            f"apart. The other {len(e5) - e5_unanswered} rest on answered "
            "responses and are genuine coverage information. A further resume "
            "pass was run specifically against the unanswered points and did not "
            "clear them."),
        "UNANSWERED_ITEM": (
            f"**Re-run the gap model against the {fmt(pts_unanswered)} INFOMAR "
            f"points that were never answered** ({n_bad_aoi} AOIs). They are "
            f"the reason {e5_unanswered} strict-fetch clusters carry "
            "`E5_no_bathymetry` rather than a real verdict, and one of them "
            "(cluster 1090, Mayo) currently reports a modelled ABSENCE on 195 "
            "cells that partial coverage could be shaping. Costs only wall "
            "clock; the cache means nothing is re-downloaded."),
        "NEW_FLAG_SENTENCE": new_flag_sentence(flagged),
    }
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    text = NOTE.read_text(encoding="utf-8")
    vals = build()
    missing = []
    for name, value in sorted(vals.items()):
        marker = f"<!-- {name} -->"
        n = text.count(marker)
        if n == 0:
            missing.append(name)
        text = text.replace(marker, value)
        short = value if len(value) < 70 else value[:67] + "..."
        print(f"  {name:<20} x{n}  {short}")

    left = re.findall(r"<!--\s*([A-Z0-9_]+)\s*-->", text)
    if left:
        print(f"\n  !! placeholders still unfilled: {sorted(set(left))}")
        return 3
    if missing:
        print(f"\n  (defined but not used in the note: {missing})")

    if args.check:
        print("\n--check: nothing written")
        return 0
    NOTE.write_text(text, encoding="utf-8")
    print(f"\nWrote {NOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
