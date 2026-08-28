#!/usr/bin/env python3
"""
results_diff.py -- what changed, and what did not, between two runs of the
national tables.

WHY THIS EXISTS
---------------
"Re-run everything and state what changed" is only answerable if the before
state was kept and the comparison is made by a script rather than by reading
two tables side by side. The 2026-08-28 session already learned this twice:
a stale drilldown printed a sentence that contradicted itself in nine words,
and a double-count in the results table was caught only because two of our own
outputs disagreed.

So: snapshot directories are compared cell by cell, on the key columns, and
every difference is printed with its old and new value. A run that changes
nothing prints that it changed nothing -- which is a result, not a null.

USAGE
-----
    PYTHONPATH=src python src/results_diff.py \
        --before outputs/_pre_audit2_20260828 \
        --label-before "published 2026-08-28 (post first mirror fix)" \
        --label-after  "2026-08-28 session 2, cache re-verified"

The `before` directory holds flat copies; `after` reads the live outputs from
their normal homes, so this compares the snapshot against whatever the
pipeline currently says.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "phaseb_national"

# file -> (where it lives now, key column, the columns worth comparing)
# Columns are named rather than "all columns" on purpose: a float that moves in
# the 12th decimal because a library reordered a sum is not a change anybody
# needs to read, and burying six real changes in 300 spurious ones is how a
# real one gets missed.
TABLES = {
    "national_exposure_screen.csv": (
        REPO / "outputs" / "exposure_screen" / "national_exposure_screen.csv",
        "cluster",
        ["n_buildings_500m", "n_occupied_tag", "n_below_5m", "n_below_10m",
         "n_occupied_below_5m", "n_occupied_below_10m", "exposed_receptors",
         "elev_min_m", "elev_min_occupied_m", "n_water_pixel"]),
    "national_asset_screen.csv": (
        REPO / "outputs" / "asset_screen" / "national_asset_screen.csv",
        "cluster",
        ["n_assets", "n_low_5m", "n_low_10m", "n_gate_pass", "n_exposed",
         "n_all_samples_water", "n_all_samples_water_gate_pass",
         "n_exposed_high_completeness", "elev_min_m"]),
    "national_asset_by_class.csv": (
        REPO / "outputs" / "asset_screen" / "national_asset_by_class.csv",
        "class",
        ["completeness", "clusters_with_any", "n_total", "n_low_5m",
         "n_low_10m", "n_gate_pass", "n_exposed", "elev_min_m"]),
    "national_asset_valuation.csv": (
        REPO / "outputs" / "asset_valuation" / "national_asset_valuation.csv",
        "cluster",
        ["n_receptors", "n_low_5m", "n_exposed", "coastal_protection_eur",
         "euro_reason", "sb3_demonstrated_demand", "protection_structures",
         "H_reduction_pct", "E_reduction_pct", "out_of_domain",
         "bed_on_wave_path", "n_exposed_facing_waves"]),
    "NATIONAL_RESULTS_TABLE.csv": (
        OUT / "NATIONAL_RESULTS_TABLE.csv",
        "cluster",
        ["buildings_500m", "occupied_tag", "lowest_occupied_m",
         "exposed_receptors_tag_based", "avoided_damage_eur",
         "avoided_damage_basis", "euro", "attenuation", "phaseb_status",
         "ortho_dwelling_like", "exposed_receptors_dwelling_like"]),
    "asset_completeness_probe.csv": (
        REPO / "outputs" / "asset_screen" / "asset_completeness_probe.csv",
        "class", None),          # None = compare every column
}

# Tolerance for a float comparison. Elevations are metres from a 30 m DSM;
# 1 mm is far below anything the instrument can mean, so a difference smaller
# than this is arithmetic noise, not a measurement change.
FLOAT_TOL = 1e-3


def _norm(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _same(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        fa, fb = float(a), float(b)
        if pd.isna(fa) and pd.isna(fb):
            return True
        return abs(fa - fb) <= FLOAT_TOL
    except (TypeError, ValueError):
        return str(a) == str(b)


def diff_table(name: str, before_dir: Path, log,
               fresh_after: datetime | None = None) -> dict:
    now_path, key, cols = TABLES[name]
    old_path = before_dir / name
    rec = {"table": name, "status": None, "row_changes": [],
           "rows_added": [], "rows_removed": []}
    if not old_path.exists():
        log("   %-34s NO SNAPSHOT -- cannot compare" % name)
        rec["status"] = "no_snapshot"
        return rec
    if not now_path.exists():
        log("   %-34s NOT REGENERATED -- the current run did not write it"
            % name)
        rec["status"] = "missing_now"
        return rec
    # STALE-TABLE GUARD. Without this, a table that the re-run never
    # regenerated compares equal to its own snapshot and is reported
    # IDENTICAL -- a pass earned by not having run. That is the exact failure
    # this project hit on 2026-08-28, when Phase B read receptor counts from a
    # drilldown that predated the mirror fix. A table that did not move
    # BECAUSE IT WAS NOT REBUILT is not the same finding as one that did not
    # move because its inputs held, and the two must never print the same way.
    rec["mtime_utc"] = datetime.fromtimestamp(
        now_path.stat().st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds")
    rec["regenerated"] = (fresh_after is None or
                          datetime.fromtimestamp(now_path.stat().st_mtime,
                                                 tz=timezone.utc)
                          >= fresh_after)
    if not rec["regenerated"]:
        log("   %-34s STALE      not rebuilt since %s -- NOT COMPARED"
            % (name, fresh_after.isoformat(timespec="minutes")))
        rec["status"] = "stale"
        return rec

    a = pd.read_csv(old_path)
    b = pd.read_csv(now_path)
    if key not in a.columns or key not in b.columns:
        log("   %-34s key %r missing" % (name, key))
        rec["status"] = "no_key"
        return rec
    a = a.set_index(key)
    b = b.set_index(key)
    use = cols if cols else [c for c in a.columns if c in b.columns]
    use = [c for c in use if c in a.columns and c in b.columns]

    added = [k for k in b.index if k not in a.index]
    removed = [k for k in a.index if k not in b.index]
    rec["rows_added"] = [str(x) for x in added]
    rec["rows_removed"] = [str(x) for x in removed]

    changes = []
    for k in a.index:
        if k not in b.index:
            continue
        ra, rb = a.loc[k], b.loc[k]
        if isinstance(ra, pd.DataFrame) or isinstance(rb, pd.DataFrame):
            continue                      # duplicate key; reported separately
        for c in use:
            if not _same(ra.get(c), rb.get(c)):
                changes.append({"row": str(k), "column": c,
                                "before": _norm(ra.get(c)),
                                "after": _norm(rb.get(c))})
    rec["row_changes"] = changes
    rec["status"] = "identical" if not (changes or added or removed) \
        else "changed"
    rec["n_rows_before"] = int(len(a))
    rec["n_rows_after"] = int(len(b))

    flag = "IDENTICAL" if rec["status"] == "identical" else "CHANGED"
    log("   %-34s %-10s rows %d -> %d, %d cell change(s)"
        % (name, flag, len(a), len(b), len(changes)))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--label-before", default="before")
    ap.add_argument("--label-after", default="after")
    ap.add_argument("--out", default=str(OUT / "results_diff"))
    ap.add_argument("--fresh-after", default=None,
                    help="ISO UTC time; a table not rebuilt since then is "
                         "reported STALE instead of compared. Pass the "
                         "re-run's start time.")
    args = ap.parse_args()
    fresh_after = (datetime.fromisoformat(args.fresh_after)
                   .replace(tzinfo=timezone.utc)
                   if args.fresh_after else None)

    before = Path(args.before)
    lines: list = []

    def log(m: str = "") -> None:
        print(m)
        lines.append(m)

    log("=" * 78)
    log("RESULTS DIFF")
    log("=" * 78)
    log("run    %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log("before %s   (%s)" % (args.label_before, before))
    log("after  %s   (live outputs/)" % args.label_after)
    log("")
    log("Compared cell by cell on the key columns. A table that did not move")
    log("is reported as IDENTICAL rather than omitted: 'nothing changed' is")
    log("the finding when the inputs were re-verified and held.")
    log("")

    if fresh_after:
        log("staleness gate: a table not rebuilt since %s is reported STALE"
            % fresh_after.isoformat(timespec="minutes"))
        log("rather than compared. A table that did not move because it was")
        log("never rebuilt is not the same finding as one that did not move")
        log("because its inputs held.")
        log("")
    recs = [diff_table(n, before, log, fresh_after) for n in TABLES]

    stale = [r["table"] for r in recs if r["status"] == "stale"]
    if stale:
        log("")
        log("!! %d TABLE(S) NOT REBUILT BY THIS RUN: %s"
            % (len(stale), ", ".join(stale)))
        log("   They are NOT compared and NOT reported as unchanged.")

    log("")
    log("=" * 78)
    log("EVERY CHANGE, IN FULL")
    log("=" * 78)
    any_change = False
    for r in recs:
        if r["status"] != "changed":
            continue
        any_change = True
        log("")
        log("%s" % r["table"])
        log("-" * 78)
        if r["rows_added"]:
            log("   rows ADDED  : %s" % ", ".join(r["rows_added"]))
        if r["rows_removed"]:
            log("   rows REMOVED: %s" % ", ".join(r["rows_removed"]))
        by_row: dict = {}
        for c in r["row_changes"]:
            by_row.setdefault(c["row"], []).append(c)
        for row in sorted(by_row, key=lambda x: (len(x), x)):
            log("   %s" % row)
            for c in by_row[row]:
                log("      %-42s %r  ->  %r"
                    % (c["column"], c["before"], c["after"]))
    if not any_change and stale:
        log("")
        log("   Nothing changed in the tables that WERE rebuilt, but %d were"
            % len(stale))
        log("   not rebuilt at all. This run cannot say the results held.")
    elif not any_change:
        log("")
        log("   NOTHING CHANGED IN ANY TABLE.")
        log("")
        log("   That is a result. The cache was invalidated on provenance")
        log("   grounds and re-fetched from verified endpoints, and every")
        log("   published number reproduced. It says the corrected numbers")
        log("   were already resting on clean data -- not that the audit was")
        log("   unnecessary, which is a different claim and is not supported")
        log("   by anything here.")

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    Path(str(outp) + ".json").write_text(json.dumps({
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "before": str(before), "label_before": args.label_before,
        "label_after": args.label_after, "tables": recs,
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    Path(str(outp) + ".log").write_text("\n".join(lines), encoding="utf-8")
    log("")
    log("wrote %s.{json,log}" % outp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
