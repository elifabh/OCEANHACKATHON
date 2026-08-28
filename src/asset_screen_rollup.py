#!/usr/bin/env python3
"""
asset_screen_rollup.py -- rebuild the asset screen's tables from its
per-cluster cache, without re-running the screen.

WHY
---
`national_asset_screen.py` writes its aggregate CSVs at the END of a run.
Its per-cluster cache is written continuously and atomically, so after an
Overpass outage the WORK survives but the TABLES do not. That is the wrong
way round: the tables are what everything downstream reads.

This reads every complete cache file and writes exactly the same three
tables the screen writes. It issues no network calls and computes nothing
new -- it re-aggregates results that are already on disk, so it can be run
at any moment during a long screen to see where the run has got to, and
after a crash to recover the tables.

THE NO-DOWNGRADE RULE STILL HOLDS. Only cache files marked complete and
carrying the current CACHE_VERSION are read, and the number of clusters is
reported beside every total, so a partial rollup can never be mistaken for
a finished national screen.

Run:  PYTHONPATH=src python src/asset_screen_rollup.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_classes as ac  # noqa: E402
from national_asset_screen import CACHE, CACHE_VERSION, OUT  # noqa: E402
from national_exposure_screen import select_clusters  # noqa: E402


def load_complete() -> list:
    out = []
    if not CACHE.exists():
        return out
    for f in sorted(CACHE.glob("cluster_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            continue
        if d.get("complete") and d.get("cache_version") == CACHE_VERSION:
            out.append(d)
    return out


def main() -> int:
    cached = load_complete()
    if not cached:
        print("no complete cluster caches at %s" % CACHE)
        return 1
    try:
        n_target = len(select_clusters())
    except Exception:                                         # noqa: BLE001
        n_target = None

    summaries = [d["summary"] for d in cached]
    frames = [pd.DataFrame(d["receptors"]) for d in cached if d["receptors"]]
    rdf = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    sdf = pd.DataFrame([{k: v for k, v in s.items()
                         if k not in ("per_class", "opw_internal")}
                        for s in summaries])
    sdf.to_csv(OUT / "national_asset_screen.csv", index=False)
    if len(rdf):
        rdf.to_csv(OUT / "national_asset_receptors.csv", index=False)

    rows = []
    for key in ac.KEYS:
        c = ac.BY_KEY[key]
        tot = {"n": 0, "n_low_5m": 0, "n_low_10m": 0, "n_gate_pass": 0,
               "n_exposed": 0}
        mins, with_any = [], 0
        for s in summaries:
            pc = s["per_class"][key]
            for k in tot:
                tot[k] += pc[k]
            if pc["n"]:
                with_any += 1
            if pc["elev_min_m"] is not None:
                mins.append(pc["elev_min_m"])
        rows.append({"class": key, "family": c["family"], "label": c["label"],
                     "completeness": c["completeness"],
                     "clusters_with_any": with_any,
                     "n_total": tot["n"], "n_low_5m": tot["n_low_5m"],
                     "n_low_10m": tot["n_low_10m"],
                     "n_gate_pass": tot["n_gate_pass"],
                     "n_exposed": tot["n_exposed"],
                     "elev_min_m": min(mins) if mins else None})
    cls = pd.DataFrame(rows)
    cls.to_csv(OUT / "national_asset_by_class.csv", index=False)

    fl = sdf[sdf.n_exposed > 0].sort_values("n_exposed", ascending=False)
    fl.to_csv(OUT / "asset_flagged_clusters.csv", index=False)

    partial = (n_target is not None and len(summaries) < n_target)
    print("=" * 78)
    print("ASSET SCREEN ROLLUP -- rebuilt from cache, no network")
    print("=" * 78)
    print("rebuilt %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print("clusters in cache        %d%s"
          % (len(summaries), "" if n_target is None else " of %d" % n_target))
    if partial:
        print("  >>> PARTIAL. These totals are over %d of %d clusters and are "
              "NOT a\n      national result." % (len(summaries), n_target))
    print("receptors                %d" % len(rdf))
    print("  below 5 m              %d" % (int(rdf.low_5m.sum()) if len(rdf) else 0))
    print("  exposed (low + gate)   %d" % (int(rdf.exposed.sum()) if len(rdf) else 0))
    print("clusters with >0 exposed %d" % len(fl))
    print("")
    print("%-24s %-16s %-6s %6s %7s %8s %8s"
          % ("class", "family", "compl", "clust", "n", "<5 m", "EXPOSED"))
    print("-" * 82)
    for _, r in cls[cls.n_total > 0].iterrows():
        print("%-24s %-16s %-6s %6d %7d %8d %8d"
              % (r["class"], r["family"], r["completeness"],
                 r["clusters_with_any"], r["n_total"], r["n_low_5m"],
                 r["n_exposed"]))
    zero = cls[cls.n_total == 0]
    print("\nclasses with NOTHING found anywhere yet (%d): %s"
          % (len(zero), ", ".join(zero["class"])))
    print("  a zero in a low-completeness class is not an absence -- see "
          "asset_completeness_probe.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
