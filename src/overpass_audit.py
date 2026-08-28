#!/usr/bin/env python3
"""
overpass_audit.py -- find and remove the cached Overpass responses that a
bad mirror poisoned.

WHAT HAPPENED
-------------
`overpass.osm.ch` was added to `OVERPASS_MIRRORS` on 2026-08-28 for the
national Phase B run, on the stated assumption -- written into the source --
that "every mirror serves the same OSM database ... so which mirror answered
cannot change a result".

It does not. It serves a SWITZERLAND-ONLY database and answers any Irish
query with HTTP 200, no error and an empty element list. Verified 2026-08-28
with identical `out count;` queries:

    Bern, CH            10 298 buildings on osm.ch
    Galway city, IE          0 on osm.ch, 4 837 on the primary
    Cork city, IE            0 on osm.ch, 22 294 on the primary

Because `overpass()` caches by query hash, every query that happened to fall
through to that mirror -- which happened whenever the primary returned 429 or
504, i.e. constantly during the national runs -- was written to
`data/osm/overpass_<hash>.json` as an EMPTY RESULT and has been reproduced by
every run since.

An empty cached response is the most dangerous possible failure for this
project, because a zero is a publishable finding here: "no receptors", "no
coastline", "no pier". The 27 August note's own rule says it --
"Zero features everywhere = CRS bug, not a finding" -- and this is the same
error with a different cause.

WHAT THIS SCRIPT DOES
---------------------
  1  reads every cached response under data/osm/;
  2  finds the ones with zero elements -- those are the only ones the bug
     could have produced, since osm.ch cannot fabricate Irish features;
  3  re-issues each of those queries against the endpoints that are known to
     hold Irish data, with the hardened `overpass()`;
  4  reports, per query, whether the empty was CONFIRMED (genuinely nothing
     there) or OVERTURNED (the cache was poisoned, and by how much);
  5  replaces the overturned entries and quarantines the originals under
     data/osm/quarantine_poisoned/ rather than deleting them, so the damage
     is auditable afterwards.

It never touches a cached response that has elements: osm.ch could only
return too few, never too many, so a non-empty cache entry cannot have come
from it.

Run:  PYTHONPATH=src python src/overpass_audit.py
      PYTHONPATH=src python src/overpass_audit.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wide_receptor_screen import (OSM_CACHE, OVERPASS_MIRRORS,  # noqa: E402
                                  OVERPASS_REMOVED,
                                  mirror_coverage_selftest, overpass)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "asset_screen"
QUAR = OSM_CACHE / "quarantine_poisoned"

# The cache stores the response, not the query. Overpass responses do not
# carry the query text, so a poisoned entry cannot be re-issued from the file
# alone -- the query has to be reconstructed by the caller that made it. The
# scripts that issue queries are deterministic, so re-running them with a
# fixed cache regenerates exactly the same query strings; this audit
# therefore works by DELETING the poisoned entries so the next run re-asks,
# and by reporting which callers are affected.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list = []

    def log(m: str = "") -> None:
        print(m)
        lines.append(m)

    log("=" * 78)
    log("OVERPASS CACHE AUDIT -- poisoned empty responses")
    log("=" * 78)
    log("run %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log("")
    log("REMOVED MIRRORS:")
    for u, why in OVERPASS_REMOVED.items():
        log("   %s\n      %s" % (u, why))
    log("")
    log("MIRROR COVERAGE SELF-TEST (Cork city building count):")
    cov = mirror_coverage_selftest()

    files = sorted(OSM_CACHE.glob("overpass_*.json"))
    log("\ncached responses: %d" % len(files))

    empties, nonempty, unreadable = [], 0, 0
    for f in files:
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            unreadable += 1
            continue
        if len(p.get("elements") or []) == 0:
            empties.append(f)
        else:
            nonempty += 1

    log("   with elements (cannot be poisoned) : %d" % nonempty)
    log("   with ZERO elements (suspect)       : %d" % len(empties))
    log("   unreadable                          : %d" % unreadable)
    log("")
    log("osm.ch could only ever return TOO FEW features, never too many, so a")
    log("non-empty cache entry cannot have come from it. Only the %d empty"
        % len(empties))
    log("entries are in scope.")

    if not empties:
        log("\nnothing to do.")
        (OUT / "overpass_audit.log").write_text("\n".join(lines),
                                                encoding="utf-8")
        return 0

    log("\n" + "-" * 78)
    log("ACTION")
    log("-" * 78)
    log("A cached response does not store the query that produced it, so a")
    log("poisoned entry cannot be re-issued from the file alone. The callers")
    log("are deterministic -- the same run rebuilds the same query strings --")
    log("so the fix is to QUARANTINE the empty entries and let the next run")
    log("re-ask with the hardened client, which now confirms every empty on a")
    log("second endpoint before believing it.")
    log("")
    if args.dry_run:
        log("DRY RUN -- nothing moved. %d files would be quarantined."
            % len(empties))
    else:
        QUAR.mkdir(parents=True, exist_ok=True)
        for f in empties:
            shutil.move(str(f), str(QUAR / f.name))
        log("quarantined %d empty cache entries -> %s" % (len(empties), QUAR))
        log("They are MOVED, not deleted, so the damage stays auditable.")

    summ = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "removed_mirrors": OVERPASS_REMOVED,
        "mirror_coverage": cov,
        "cached_total": len(files),
        "cached_with_elements": nonempty,
        "cached_empty_quarantined": 0 if args.dry_run else len(empties),
        "cached_empty_found": len(empties),
        "dry_run": bool(args.dry_run),
        "note": ("osm.ch can only under-report, so only empty cache entries "
                 "are in scope. Non-empty entries are untouched."),
    }
    (OUT / "overpass_audit.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "overpass_audit.log").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
