#!/usr/bin/env python3
"""
poisoned_cache_impact.py -- what did the Swiss mirror actually cost the
published 28 August national result?

BACKGROUND
----------
`overpass.osm.ch` serves a Switzerland-only database and answers Irish
queries with HTTP 200 and zero elements (see `overpass_audit.py`). Because
`overpass()` caches by query hash, any query that fell through to it was
stored as an empty result. This measures the damage instead of estimating
it.

THE THREE TESTS
---------------
1  WHICH cached empty responses predate this session. Only those can have
   affected a published number. (Answer: exactly one, written 05:53 on
   2026-08-28, during the national exposure screen re-run.)

2  WHICH clusters that query covered, reconstructed by rebuilding the
   exposure screen's own box batches and hashing each query. The hashes are
   deterministic, so this identifies the affected clusters exactly rather
   than by inference.

3  HOW MANY BUILDINGS were lost, proven against an INDEPENDENT earlier run.
   The 27 August wide screen created these clusters by DBSCAN over
   shore-proximate buildings and stored every member's coordinates in
   `outputs/national_receptor_screen_buildings.geojson`. Counting the
   members that fall inside the very same 500 m receptor disc gives a
   PROVABLE MINIMUM for what the exposure screen should have found. It is a
   minimum and not the true count, because the screen counts every OSM
   building in the disc, not only cluster members -- cluster 594 is the
   control for that: it legitimately found MORE than its member count.

WHY THIS IS NOT A ROUNDING ERROR
--------------------------------
A cluster exists BECAUSE buildings were found there. A cluster with zero
buildings inside a disc larger than the one that created it is a logical
contradiction, not a low number. Every affected cluster is reported in the
published national table as "EUR 0 -- evidenced zero", and the 28 August
note's own standard is that "an evidenced zero requires a named test that
could have returned non-zero". At these sites the test returned nothing
because it was never given any receptors to test.

Run:  PYTHONPATH=src python src/poisoned_cache_impact.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))

from national_exposure_screen import (BOXES_PER_QUERY,  # noqa: E402
                                      BOX_HALF_M, RECEPTOR_RADIUS_M,
                                      select_clusters)
from wide_receptor_screen import ITM, OSM_CACHE, WGS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "asset_screen"
QUAR = OSM_CACHE / "quarantine_poisoned"
BUILDINGS_GJ = REPO / "outputs" / "national_receptor_screen_buildings.geojson"
CAND = REPO / "outputs" / "national_candidate_table.csv"
PUBLISHED = REPO / "outputs" / "_pre_mirrorfix_20260828" / "national_exposure_screen.csv"

# This session began at ~09:00 UTC on 2026-08-28. Anything cached after that
# is our own run and cannot have touched a published number.
SESSION_START = datetime(2026, 8, 28, 8, 30, tzinfo=timezone.utc)


def batch_hashes() -> dict:
    """{query_hash: (kind, [clusters])} for the exposure screen's own batches."""
    sel = select_clusters()
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    boxes = []
    for _, r in sel.iterrows():
        cx, cy = to_itm.transform(r.lon, r.lat)
        x0, y0 = to_wgs.transform(cx - BOX_HALF_M, cy - BOX_HALF_M)
        x1, y1 = to_wgs.transform(cx + BOX_HALF_M, cy + BOX_HALF_M)
        boxes.append((x0, y0, x1, y1))
    out = {}
    for i in range(0, len(boxes), BOXES_PER_QUERY):
        chunk = boxes[i:i + BOXES_PER_QUERY]
        bbs = ["%.6f,%.6f,%.6f,%.6f" % (b[1], b[0], b[3], b[2]) for b in chunk]
        clusters = [int(c) for c in sel.cluster.iloc[i:i + len(chunk)]]
        parts = "".join('way["building"](%s);relation["building"](%s);'
                        'node["building"](%s);' % (bb, bb, bb) for bb in bbs)
        qb = "[out:json][timeout:300];(%s);out center tags;" % parts
        parts = "".join('way["natural"="coastline"](%s);' % bb for bb in bbs)
        qc = "[out:json][timeout:300];(%s);out geom;" % parts
        for kind, q in (("buildings", qb), ("coastline", qc)):
            out[hashlib.sha1(q.encode()).hexdigest()[:12]] = (kind, clusters)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list = []

    def log(m: str = "") -> None:
        print(m)
        lines.append(m)

    log("=" * 78)
    log("POISONED-CACHE IMPACT ON THE PUBLISHED 28 AUGUST RESULT")
    log("=" * 78)

    # ---- test 1: which empties predate this session ----
    log("\n1. QUARANTINED EMPTY RESPONSES, BY AGE")
    log("-" * 78)
    if not QUAR.exists():
        log("   no quarantine directory; run overpass_audit.py first")
        return 1
    files = sorted(QUAR.glob("overpass_*.json"))
    pre, mine = [], []
    for f in files:
        ts = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        (pre if ts < SESSION_START else mine).append((f, ts))
    log("   quarantined total            %d" % len(files))
    log("   written by THIS session      %d  (cannot affect a published number)"
        % len(mine))
    log("   PREDATE this session         %d  <- the only ones in scope"
        % len(pre))
    for f, ts in pre:
        log("      %s  %s" % (f.name, ts.isoformat(timespec="seconds")))

    # ---- test 2: which clusters those queries covered ----
    log("\n2. WHAT THOSE QUERIES WERE")
    log("-" * 78)
    hashes = batch_hashes()
    affected: list = []
    for f, ts in pre:
        h = f.stem.replace("overpass_", "")
        if h in hashes:
            kind, clusters = hashes[h]
            log("   %s -> exposure screen %s query, clusters %s"
                % (h, kind.upper(), clusters))
            if kind == "buildings":
                affected = clusters
        else:
            log("   %s -> not an exposure-screen batch query (issued by "
                "another script; its caller re-asks on its next run)" % h)
    if not affected:
        log("\n   No published BUILDINGS query was poisoned. Nothing further "
            "to measure.")
        (OUT / "poisoned_cache_impact.log").write_text("\n".join(lines),
                                                       encoding="utf-8")
        return 0

    # ---- test 3: how many buildings, proven independently ----
    log("\n3. HOW MANY BUILDINGS WERE LOST -- proven against the 27 August run")
    log("-" * 78)
    log("   The 27 Aug wide screen created these clusters from buildings and")
    log("   stored every member. Members inside the SAME %.0f m receptor disc"
        % RECEPTOR_RADIUS_M)
    log("   are a PROVABLE MINIMUM for what the exposure screen should have")
    log("   found. It is a minimum: the screen counts every OSM building in")
    log("   the disc, not only cluster members.")
    log("")
    g = gpd.read_file(BUILDINGS_GJ)
    cand = pd.read_csv(CAND).set_index("cluster")
    pub = pd.read_csv(PUBLISHED).set_index("cluster")
    t = Transformer.from_crs(WGS, ITM, always_xy=True)
    rows = []
    for cl in affected:
        sub = g[g.cluster == cl]
        cx, cy = t.transform(cand.loc[cl, "lon"], cand.loc[cl, "lat"])
        if len(sub):
            xs, ys = t.transform(sub.geometry.x.values, sub.geometry.y.values)
            d = np.hypot(np.asarray(xs) - cx, np.asarray(ys) - cy)
            within = int((d <= RECEPTOR_RADIUS_M).sum())
        else:
            within = 0
        found = int(pub.loc[cl, "n_buildings_500m"]) if cl in pub.index else None
        rows.append({"cluster": cl, "county": cand.loc[cl, "county"],
                     "nearest_place": str(cand.loc[cl, "nearest_place"]),
                     "members_within_500m": within,
                     "published_28aug_found": found,
                     "provably_missed": max(0, within - (found or 0))})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "poisoned_cache_impact.csv", index=False)
    log("%-8s %-9s %-34s %8s %8s %8s"
        % ("cluster", "county", "place", "members", "found", "MISSED"))
    for _, r in d.iterrows():
        log("%-8d %-9s %-34s %8d %8s %8d"
            % (r.cluster, r.county, r.nearest_place[:34],
               r.members_within_500m, r.published_28aug_found,
               r.provably_missed))
    total = int(d.provably_missed.sum())
    n_zero = int((d.published_28aug_found == 0).sum())
    log("")
    log("   clusters returning ZERO buildings          %d" % n_zero)
    log("   buildings the published screen never saw   >= %d" % total)
    log("")
    log("   Control: a cluster whose `found` EXCEEDS its member count is")
    log("   behaving correctly -- the screen counts all OSM buildings in the")
    log("   disc, not only members. %d of the %d do."
        % (int((d.published_28aug_found > d.members_within_500m).sum()), len(d)))
    log("")
    log("   Every one of the %d zero clusters is reported in the published" % n_zero)
    log("   national table as 'EUR 0 - evidenced zero'. That zero is NOT")
    log("   evidenced: the receptor term was empty because no receptor was")
    log("   ever returned, not because none is there.")

    summ = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "quarantined_total": len(files),
            "quarantined_this_session": len(mine),
            "quarantined_predating_session": len(pre),
            "affected_clusters": affected,
            "clusters_returning_zero": n_zero,
            "buildings_provably_missed_minimum": total,
            "per_cluster": rows}
    (OUT / "poisoned_cache_impact.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    (OUT / "poisoned_cache_impact.log").write_text("\n".join(lines),
                                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
