#!/usr/bin/env python3
"""
run_national_finish.py — drive Parts 1b, 2, 3 and 4 in order, once.

WHY THIS EXISTS
---------------
Part 1 (finishing the habitat-gap model) can ADD clusters to the candidate
table, and every downstream step then has a different input set: the exposure
screen must screen the new clusters, any new flag needs a wave direction and an
orthophoto check, and only then can the Phase B chain and the national table be
rebuilt. Doing that by hand invites exactly one mistake — running Phase B on
yesterday's flag list — so it is a script.

    PYTHONPATH=src python src/run_national_finish.py

It is idempotent and resumable in the same sense the underlying scripts are:
Overpass and CMEMS responses are cached, image chips are not re-downloaded, and
re-running after an outage picks up where it stopped. It does NOT run
`habitat_gap_model.py`; that is Part 1 proper and is driven separately so its
INFOMAR budget is under direct control.

Each step is allowed to fail without taking the rest down: a step that fails is
reported and the run continues, because a stale exposure screen with a fresh
Phase B is a visible inconsistency, while a run that dies halfway leaves
nothing at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
EXPO = REPO / "outputs" / "exposure_screen"
PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=str(SRC))


def run(name: str, args: list[str], log: Path) -> bool:
    print(f"\n{'='*78}\n>>> {name}\n{'='*78}")
    log.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([PY, "-u"] + args, cwd=str(REPO), env=ENV,
                       capture_output=True, text=True)
    log.write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
    tail = "\n".join((p.stdout or "").rstrip().split("\n")[-12:])
    print(tail)
    if p.returncode != 0:
        print(f"    !! {name} exited {p.returncode}; see {log}")
        print("    continuing — a failed step is reported, not fatal")
    return p.returncode == 0


def flagged() -> pd.DataFrame:
    f = EXPO / "national_exposure_screen.csv"
    if not f.exists():
        return pd.DataFrame()
    d = pd.read_csv(f)
    return d[d.exposed_receptors > 0]


def main() -> int:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"NATIONAL FINISH-OUT DRIVER  {t0}")

    before = set(flagged().cluster.astype(int)) if not flagged().empty else set()
    print(f"  flagged clusters before this run: {sorted(before)}")

    # ---- Part 1b: re-screen exposure over the refreshed candidate table ----
    run("Part 1b — national exposure screen",
        [str(SRC / "national_exposure_screen.py")],
        EXPO / "national_exposure_run.log")
    run("Part 1b — per-building fetch and OPW drilldown",
        [str(SRC / "exposure_flag_drilldown.py")],
        EXPO / "exposure_flag_drilldown.log")

    after_df = flagged()
    after = set(after_df.cluster.astype(int))
    new = sorted(after - before)
    print(f"\n  flagged clusters after:  {sorted(after)}")
    print(f"  NEW flagged clusters:    {new if new else 'none'}")

    # ---- new flags need their own wave direction and orthophoto check ----
    if new:
        sub = after_df[after_df.cluster.isin(new)][
            ["cluster", "county", "nearest_place", "lon", "lat",
             "evidence_class"]]
        p_sites = EXPO / "flagged_sites_new.csv"
        sub.to_csv(p_sites, index=False)
        run("Part 2 — wave climate for the new sites",
            [str(SRC / "site_wave_climate.py"), "--sites", str(p_sites),
             "--out", str(EXPO / "site_wave_climate_new.csv")],
            EXPO / "site_wave_climate_new_run.log")

        drill = pd.read_csv(EXPO / "exposure_flag_drilldown.csv")
        low = drill[(drill.cluster.isin(new)) & (drill.occupied_tag)
                    & (drill.elev_m < 5) & (~drill.elev_is_water_pixel)]
        if not low.empty:
            p_b = EXPO / "ortho_input_new.csv"
            low[["cluster", "osm_id", "building", "lon", "lat", "elev_m",
                 "dist_shore_m"]].to_csv(p_b, index=False)
            run("Part 3 — orthophoto chips for the new receptors",
                [str(SRC / "ortho_check.py"), "--buildings", str(p_b),
                 "--out-dir", str(EXPO / "ortho_new"),
                 "--manifest", str(EXPO / "ortho_new" / "ortho_manifest_new.csv")],
                EXPO / "ortho_new_run.log")
            print("\n  >>> NEW CHIPS WRITTEN. They carry EMPTY verdicts until a")
            print("      human (or assistant) looks at them. Until then those")
            print("      receptors count as tag-based only, which is the")
            print("      GENEROUS reading — never the other way round.")
        else:
            print("  no new low-lying occupied-tag receptor to photograph")

    # No merge step here on purpose: national_phaseb.py and
    # national_results_table.py both GLOB their inputs
    # (site_wave_climate*.csv, ortho*/ortho_manifest*.csv), so a new batch is
    # picked up without any file being rewritten in place.

    # ---- Parts 2 and 4, then the table ----
    run("Parts 2 and 4 — bearing test, Sherkin chain, valuation",
        [str(SRC / "national_phaseb.py")],
        REPO / "outputs" / "phaseb_national" / "national_phaseb_run.log")
    run("the national results table",
        [str(SRC / "national_results_table.py")],
        REPO / "outputs" / "phaseb_national" / "national_results_table_run.log")

    print(f"\nDriver finished "
          f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
