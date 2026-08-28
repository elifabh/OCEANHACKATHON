#!/usr/bin/env python3
"""
rerun_after_audit.py -- re-run the whole chain over a cache that has just been
invalidated, in dependency order, unattended.

WHY A DRIVER AND NOT A LIST OF COMMANDS
---------------------------------------
`overpass_cache_audit.py --phase holdout` removes every cache entry whose
provenance this project will not vouch for. The chain then has to be re-run so
each caller re-asks its own queries -- and re-run IN ORDER, because the asset
screen reads the exposure screen's cluster set, the valuation reads the asset
screen, and the results table reads all of them. Running them by hand invites
exactly one mistake: a fresh valuation over a stale screen. The 2026-08-28
session already made the same class of mistake once, when Phase B read its
receptor counts from a drilldown that predated the mirror fix and printed a
sentence contradicting itself in nine words.

RULES THIS DRIVER KEEPS
-----------------------
  * A step that fails is REPORTED and the run continues. A half-finished chain
    that says which half finished is more useful than one that dies silently.
  * Nothing is deleted. Every step writes where it normally writes; the
    before-state lives in the snapshot directory taken before the holdout.
  * No time budget overwrites a complete result: each underlying script keeps
    its own resumable cache and its own atomic writes, and this driver adds
    none of its own.
  * Timings and exit codes go to a manifest, so "what did this run actually
    do" is answerable afterwards without reading six logs.

    PYTHONPATH=src python src/rerun_after_audit.py
    PYTHONPATH=src python src/rerun_after_audit.py --from national_asset_screen
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
LOGS = REPO / "outputs" / "rerun2"
PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=str(SRC))

# name, argv, why it is here and what it depends on
STEPS = [
    ("national_exposure_screen",
     [str(SRC / "national_exposure_screen.py")],
     "buildings + coastline per cluster box; carries the An Aird control"),
    ("exposure_flag_drilldown",
     [str(SRC / "exposure_flag_drilldown.py")],
     "per-building fetch and OPW drilldown; reads the exposure screen. It "
     "CACHES a derived count, which is why it must follow the screen -- the "
     "28 Aug session was bitten by exactly this"),
    ("national_asset_screen",
     [str(SRC / "national_asset_screen.py")],
     "the 50-class screen: full geometry, min-along-geometry GLO-30, "
     "per-receptor fetch and true bearing. Per-cluster cache was held out"),
    ("asset_completeness_probe",
     [str(SRC / "asset_completeness_probe.py")],
     "which class zeros can carry an absence claim; rural vs urban"),
    ("national_asset_valuation",
     [str(SRC / "national_asset_valuation.py")],
     "the chain over the widened receptor set, euro rules R1-R6, and the "
     "three guards (Sherkin re-derivation, E1/An Aird control, damage "
     "function applicability)"),
    ("national_phaseb",
     [str(SRC / "national_phaseb.py")],
     "national bearing test and Sherkin chain per site"),
    ("national_results_table",
     [str(SRC / "national_results_table.py")],
     "the one national results table"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=None,
                    help="skip to this step name")
    ap.add_argument("--only", default=None, help="run just this step")
    args = ap.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    manifest = {"run_utc": started.isoformat(timespec="seconds"), "steps": []}
    seen_start = args.start is None

    print("RE-RUN AFTER CACHE AUDIT  %s" % started.isoformat(timespec="seconds"))
    print("logs -> %s" % LOGS)

    for name, argv, why in STEPS:
        if args.only and name != args.only:
            continue
        if not seen_start:
            if name == args.start:
                seen_start = True
            else:
                print("   skip %s" % name)
                continue
        print("\n" + "=" * 78)
        print(">>> %s" % name)
        print("    %s" % why)
        print("=" * 78, flush=True)
        t0 = time.time()
        log = LOGS / ("%s.log" % name)
        p = subprocess.run([PY, "-u"] + argv, cwd=str(REPO), env=ENV,
                           capture_output=True, text=True)
        log.write_text((p.stdout or "") + "\n" + (p.stderr or ""),
                       encoding="utf-8")
        dt = time.time() - t0
        tail = "\n".join((p.stdout or "").rstrip().split("\n")[-14:])
        print(tail)
        print("    [%s] exit %d in %.1f min -> %s"
              % (name, p.returncode, dt / 60, log.name), flush=True)
        if p.returncode != 0:
            print("    !! FAILED. Reported, not fatal; the chain continues so")
            print("       that a partial re-run says which part is partial.")
        manifest["steps"].append({"step": name, "exit": p.returncode,
                                  "minutes": round(dt / 60, 2),
                                  "log": str(log)})
        (LOGS / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1),
            encoding="utf-8")

    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    (LOGS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [s["step"] for s in manifest["steps"] if s["exit"] != 0]
    print("\n" + "=" * 78)
    print("DONE. %d steps, %d failed%s"
          % (len(manifest["steps"]), len(bad),
             (": " + ", ".join(bad)) if bad else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
