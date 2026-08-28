#!/usr/bin/env python3
"""
overpass_cache_audit.py -- audit EVERY cached Overpass response, not only the
empty ones.

WHY A SECOND AUDIT
------------------
`overpass_audit.py` (2026-08-28) quarantined 25 zero-element cache entries on
this argument, written into its own docstring:

    "It never touches a cached response that has elements: osm.ch could only
     return too few, never too many, so a non-empty cache entry cannot have
     come from it."

The argument is sound for the failure mode it names, and the note that shipped
with it said so (limitation 13). But it is an ARGUMENT, and it decides which
files are examined. Three things are wrong with letting an argument do that:

  1. It is false as stated. Asked `out count;`, osm.ch returns ONE element
     carrying total="0" -- a NON-EMPTY response whose content is a zero. Such
     an entry would have been skipped unread. (Measured 2026-08-28. No such
     entry is in the cache; the hole is real, the damage is not.)
  2. Emptiness is a property of the ANSWER. Provenance is a property of the
     SERVER. A test on the answer cannot establish which server produced it.
  3. It cannot see a failure mode nobody has thought of yet.

This audit tests provenance directly. Every Overpass response carries the
identity of the instance that produced it, and this project's cache preserved
it all along:

    generator          "Overpass API 0.7.59.1 2a9d9642"   <- osm.ch
    timestamp_osm_base "116721"                           <- an INTEGER

Every legitimate instance reports an ISO-8601 database timestamp. Measured
2026-08-28 12:30 UTC:

    endpoint                    Cork    Galway  generator             ts_osm_base
    overpass-api.de            22315     7284   0.7.62.11 87bfad18    ISO
    overpass.openstreetmap.fr  22315     7284   0.7.62.7  375dc00a    ISO
    maps.mail.ru               22315     7284   0.7.62.4  2390de5a    ISO
    overpass.osm.ch                0        0   0.7.59.1  2a9d9642    "116725"

So a cached file can be attributed to an instance without knowing what was
asked -- and, unlike the emptiness rule, that works on non-empty entries.

WHAT IT DOES
------------
PHASE A (no network) -- classify every cache entry, live and quarantined:
    * instance verdict from the fingerprint: BANNED / VERIFIED / UNKNOWN
    * the empty-claim test in BOTH forms (zero elements, out-count-of-zero)
    * whether the file was written inside the at-risk window, i.e. the period
      when the banned mirror was in OVERPASS_MIRRORS

  The window is the conservative test and the fingerprint is the decisive one.
  They are reported separately and neither is allowed to overrule the other:
  an in-window entry with a verified fingerprint is still re-checked in
  phase B, because "the fingerprint says it is fine" is exactly the kind of
  argument this audit exists to stop trusting.

PHASE B (network) -- re-issue and compare.
  The cache stores the response, not the query, so an entry can only be
  re-issued if its query text is known. It is known for any entry with a
  `.meta.json` sidecar; `overpass()` now writes one on a cache HIT as well as
  on a write, so re-running the callers retro-fills the registry for entries
  that predate sidecars. Entries whose query is still unknown are reported as
  UNVERIFIABLE by name and count. They are not called clean.

  Each verifiable at-risk entry is re-issued against a verified-good endpoint
  and compared on element count and element id set. Verdicts:
    IDENTICAL   -- same id set. The cached answer stands.
    DIFFERS     -- id sets differ. Reported with the delta, and the fresh
                   response replaces the cached one; the original is
                   quarantined, never deleted.
    UNVERIFIABLE-- query text unknown, or every endpoint failed.

  OSM is a live database, so a difference is not by itself proof of poisoning:
  somebody may have mapped a shed. The audit therefore reports the DIRECTION
  and SIZE of every difference and does not label a small symmetric change as
  contamination. A cached zero against a fresh non-zero is the signature that
  matters, and it is called out separately.

Run:
    PYTHONPATH=src python src/overpass_cache_audit.py --phase a
    PYTHONPATH=src python src/overpass_cache_audit.py --phase b
    PYTHONPATH=src python src/overpass_cache_audit.py --phase b --dry-run

Phase B is resumable: every comparison is appended to a JSONL ledger as it
completes, and a re-run skips what the ledger already holds. A time budget can
stop it, and stopping never overwrites a completed comparison.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wide_receptor_screen import (BANNED_GENERATOR_PREFIXES,  # noqa: E402
                                  OSM_CACHE, OVERPASS_BANNED,
                                  OVERPASS_MIRRORS, BannedInstanceError,
                                  _count_total, _is_empty_claim,
                                  _overpass_post, instance_fingerprint,
                                  guard_selftest, mirror_coverage_selftest,
                                  query_key)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "asset_screen"
QUAR = OSM_CACHE / "quarantine_poisoned"
QUAR2 = OSM_CACHE / "quarantine_audit2"
LEDGER = OUT / "overpass_cache_audit_ledger.jsonl"
HOLD = OSM_CACHE / "verify_holdout"

# ---------------------------------------------------------------------------
# The at-risk window
# ---------------------------------------------------------------------------
# The banned mirror was added to OVERPASS_MIRRORS on 2026-08-28 for the
# national Phase B run and removed at 10:26 the same morning. The exact minute
# it was added is not in git -- it was added and committed in the same working
# session -- so the window opens at 00:00 on 2026-08-28, which is earlier than
# it can possibly have been added and therefore cannot exclude an affected
# entry. Everything cached on 2026-08-27 predates the mirror entirely.
#
# This is deliberately wider than the evidence. The osm.ch-fingerprinted files
# run 04:53 to 09:17 UTC; the window is 00:00 to 10:26 UTC. A window drawn
# around the evidence would be a window drawn around what we already found.
#
# TIMEZONE, because it is the kind of thing that silently halves a window:
# this machine runs UTC+1 (Irish Summer Time), and the removal commit is
# stamped 10:26 LOCAL = 09:26 UTC. The window is declared in UTC and shuts at
# 10:26 UTC, i.e. a full hour AFTER the mirror was actually removed. Both ends
# err outwards on purpose.
WINDOW_OPEN = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
WINDOW_SHUT = datetime(2026, 8, 28, 10, 26, tzinfo=timezone.utc)

# Generators measured today on endpoints that pass mirror_coverage_selftest.
# An entry whose generator is not here is UNKNOWN, not bad -- an endpoint may
# simply have been upgraded since. UNKNOWN means "re-check", not "discard".
VERIFIED_GENERATORS = (
    "Overpass API 0.7.62.11",   # overpass-api.de
    "Overpass API 0.7.62.7",    # overpass.openstreetmap.fr
    "Overpass API 0.7.62.4",    # maps.mail.ru
)


def _mtime(p: Path) -> datetime:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)


def classify(path: Path) -> dict:
    """Everything phase A can say about one cache file, from the file alone."""
    rec = {"file": path.name, "dir": path.parent.name,
           "mtime_utc": _mtime(path).isoformat(timespec="seconds"),
           "bytes": path.stat().st_size,
           "key": path.stem.replace("overpass_", "")}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                                  # noqa: BLE001
        rec.update({"readable": False, "error": str(exc)[:120],
                    "instance": "UNREADABLE"})
        return rec
    fp = instance_fingerprint(payload)
    rec.update({"readable": True, **fp,
                "n_elements": len(payload.get("elements") or []),
                "count_total": _count_total(payload),
                "empty_claim": _is_empty_claim(payload)})

    gen = fp["generator"]
    if any(gen.startswith(b) for b in BANNED_GENERATOR_PREFIXES):
        rec["instance"] = "BANNED"
        rec["instance_why"] = "generator matches a banned instance"
    elif fp["timestamp_osm_base"] and not fp["timestamp_is_iso"]:
        rec["instance"] = "BANNED"
        rec["instance_why"] = "timestamp_osm_base is not ISO-8601"
    elif any(gen.startswith(v) for v in VERIFIED_GENERATORS):
        rec["instance"] = "VERIFIED"
        rec["instance_why"] = "generator matches an endpoint verified today"
    else:
        rec["instance"] = "UNKNOWN"
        rec["instance_why"] = "generator not among today's verified endpoints"

    mt = _mtime(path)
    rec["in_window"] = bool(WINDOW_OPEN <= mt <= WINDOW_SHUT)

    # The sidecar is what makes an entry re-issuable.
    side = path.parent / ("overpass_%s.meta.json" % rec["key"])
    rec["has_query"] = side.exists()
    if side.exists():
        try:
            rec["query"] = json.loads(side.read_text(encoding="utf-8"))["query"]
        except Exception:                                     # noqa: BLE001
            rec["has_query"] = False
    return rec


def phase_a(log) -> list:
    log("=" * 78)
    log("PHASE A -- classify every cached response (no network)")
    log("=" * 78)
    # Every directory an entry can be in, including the holdout -- otherwise
    # invalidating an entry would make it vanish from the audit that
    # invalidated it, and the totals would silently shrink between phases.
    files = (sorted(OSM_CACHE.glob("overpass_*.json"))
             + sorted(QUAR.glob("overpass_*.json"))
             + sorted(QUAR2.glob("overpass_*.json"))
             + sorted(HOLD.glob("overpass_*.json")))
    files = [f for f in files if not f.name.endswith(".meta.json")]
    recs = [classify(f) for f in files]

    log("")
    log("at-risk window: %s .. %s  (wider than the evidence, deliberately)"
        % (WINDOW_OPEN.isoformat(timespec="minutes"),
           WINDOW_SHUT.isoformat(timespec="minutes")))
    log("cache entries examined: %d  (%d live, %d quarantined, %d held out)"
        % (len(recs),
           sum(1 for r in recs if r["dir"] == OSM_CACHE.name),
           sum(1 for r in recs if r["dir"] in (QUAR.name, QUAR2.name)),
           sum(1 for r in recs if r["dir"] == HOLD.name)))
    log("")

    by = {}
    for r in recs:
        by.setdefault(r.get("instance", "?"), []).append(r)
    log("%-12s %6s   %s" % ("instance", "n", "meaning"))
    log("-" * 78)
    for k in ("BANNED", "UNKNOWN", "VERIFIED", "UNREADABLE"):
        if k in by:
            log("%-12s %6d   %s" % (k, len(by[k]), by[k][0].get(
                "instance_why", "")))
    log("")

    banned = by.get("BANNED", [])
    log("BANNED-INSTANCE ENTRIES: %d" % len(banned))
    live_banned = [r for r in banned if r["dir"] == OSM_CACHE.name]
    log("   of which STILL LIVE in the cache: %d %s"
        % (len(live_banned),
           "<-- these must be removed" if live_banned else "(none)"))
    nonempty_banned = [r for r in banned if not r.get("empty_claim")]
    log("   of which NON-EMPTY: %d %s"
        % (len(nonempty_banned),
           "<-- the first audit could not have found these"
           if nonempty_banned else
           "(none -- the first audit's emptiness rule happened to be "
           "sufficient here, which is now measured rather than argued)"))
    log("")

    inwin = [r for r in recs if r.get("in_window")]
    log("IN-WINDOW ENTRIES (written while the banned mirror was listed): %d"
        % len(inwin))
    log("   with a verified fingerprint : %d"
        % sum(1 for r in inwin if r.get("instance") == "VERIFIED"))
    log("   banned fingerprint          : %d"
        % sum(1 for r in inwin if r.get("instance") == "BANNED"))
    log("   unknown fingerprint         : %d"
        % sum(1 for r in inwin if r.get("instance") == "UNKNOWN"))
    log("   query text known (sidecar)  : %d of %d"
        % (sum(1 for r in inwin if r.get("has_query")), len(inwin)))
    log("")
    log("Entries carrying an EMPTY CLAIM (either form): %d"
        % sum(1 for r in recs if r.get("empty_claim")))
    log("   zero elements    : %d"
        % sum(1 for r in recs if r.get("n_elements") == 0))
    log("   out count == 0   : %d"
        % sum(1 for r in recs if r.get("count_total") == 0))

    # Zeros this project could not check. They are not in the cache -- that is
    # the point of them -- so they cannot be found by walking the cache, and
    # they are the one class of empty that never appears in any of the counts
    # above. Each one is a zero that some run reported without a second
    # opinion.
    log("")
    log("UNCONFIRMED EMPTIES (a zero no second endpoint could confirm):")
    ulog = OSM_CACHE / "unconfirmed_empties.jsonl"
    if not ulog.exists():
        log("   none recorded. (The log is written by overpass() from "
            "2026-08-28 session 2 onward; runs before that recorded the")
        log("   event in a counter that was never printed, so an absence here "
            "for an earlier run means 'not recorded', not 'none happened'.)")
    else:
        rows = [json.loads(x) for x in
                ulog.read_text(encoding="utf-8").splitlines() if x.strip()]
        log("   %d recorded" % len(rows))
        for r in rows[-20:]:
            log("      %s  %s  %s" % (r.get("seen_utc"), r.get("key"),
                                      (r.get("endpoint") or "")[:44]))

    # The four that the first audit quarantined although they are not from the
    # banned instance. Naming them is the point: an over-quarantine is also an
    # error, and it removed four genuine measurements from the cache.
    over = [r for r in recs
            if r["dir"] == QUAR.name and r.get("instance") != "BANNED"]
    log("")
    log("OVER-QUARANTINED BY THE FIRST AUDIT: %d" % len(over))
    if over:
        log("   quarantined for being empty, but NOT from the banned "
            "instance. These are genuine empties from a verified endpoint")
        log("   and phase B re-checks them like any other entry.")
        for r in over:
            log("      %s  %s  %s" % (r["file"], r["generator"],
                                       r["timestamp_osm_base"]))
    return recs


def _fetch_verified(query: str, tries: int = 4):
    """Re-issue one query against a verified-good endpoint.

    Backoff is exponential and the endpoint rotates, so a rate-limited primary
    does not stall the audit. Returns (payload, url) or (None, reason).
    """
    last = "no endpoint tried"
    for attempt in range(tries):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            return _overpass_post(url, query, timeout=300), url
        except BannedInstanceError:
            raise
        except Exception as exc:                              # noqa: BLE001
            last = "%s: %s" % (url.split("//")[-1].split("/")[0],
                               str(exc)[:80])
            wait = min(60, 10 * (attempt + 1))
            print("      re-fetch attempt %d failed (%s); %ds"
                  % (attempt + 1, last, wait), file=sys.stderr)
            time.sleep(wait)
    return None, last


def _ids(payload: dict) -> set:
    return {(e.get("type"), e.get("id")) for e in (payload.get("elements") or [])}


def _ledger_done() -> dict:
    done = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    done[r["key"]] = r
                except Exception:                             # noqa: BLE001
                    continue
    return done


def _ledger_append(rec: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def phase_b(recs: list, log, dry_run: bool = False,
            budget_s: float = 0.0) -> list:
    log("")
    log("=" * 78)
    log("PHASE B -- re-issue every at-risk entry against a verified endpoint")
    log("=" * 78)

    # Scope: anything the fingerprint doubts, anything inside the window, and
    # every empty claim anywhere. The three overlap heavily and that is fine;
    # the union is the point.
    scope = [r for r in recs
             if r.get("instance") in ("BANNED", "UNKNOWN", "UNREADABLE")
             or r.get("in_window")
             or r.get("empty_claim")]
    log("in scope: %d entries" % len(scope))
    log("   because fingerprint is not VERIFIED : %d"
        % sum(1 for r in scope if r.get("instance") != "VERIFIED"))
    log("   because written inside the window   : %d"
        % sum(1 for r in scope if r.get("in_window")))
    log("   because it carries an empty claim   : %d"
        % sum(1 for r in scope if r.get("empty_claim")))

    have = [r for r in scope if r.get("has_query")]
    lack = [r for r in scope if not r.get("has_query")]
    log("")
    log("   query text known   : %d  (re-issuable)" % len(have))
    log("   query text UNKNOWN : %d  (UNVERIFIABLE -- reported, not cleared)"
        % len(lack))
    if lack:
        log("      These predate the sidecar and their callers have not been")
        log("      re-run since. Re-running any caller retro-fills its own")
        log("      sidecars on the cache hit, so this number falls to zero")
        log("      once part 3 has run. They are NOT counted as clean.")

    done = _ledger_done()
    log("")
    log("   already in the ledger from an earlier run: %d" % len(done))

    t0 = time.time()
    results, stopped = [], False
    for i, r in enumerate(have, 1):
        if r["key"] in done:
            results.append(done[r["key"]])
            continue
        if budget_s and (time.time() - t0) > budget_s:
            log("   time budget reached after %d re-fetches; %d left."
                % (i - 1, len(have) - i + 1))
            log("   Nothing is overwritten and nothing is marked clean: the")
            log("   ledger holds the completed comparisons and a re-run")
            log("   continues from there.")
            stopped = True
            break
        old = json.loads((OSM_CACHE / r["file"] if r["dir"] == OSM_CACHE.name
                          else Path(OSM_CACHE / r["dir"] / r["file"])
                          ).read_text(encoding="utf-8"))
        print("   [%d/%d] %s  (cached n=%d)"
              % (i, len(have), r["key"], r.get("n_elements", -1)))
        fresh, url = _fetch_verified(r["query"])
        if fresh is None:
            rec = {"key": r["key"], "file": r["file"], "dir": r["dir"],
                   "verdict": "UNVERIFIABLE", "reason": url,
                   "cached_n": r.get("n_elements"),
                   "checked_utc": datetime.now(timezone.utc)
                   .isoformat(timespec="seconds")}
            _ledger_append(rec)
            results.append(rec)
            continue
        oid, nid = _ids(old), _ids(fresh)
        rec = {"key": r["key"], "file": r["file"], "dir": r["dir"],
               "endpoint": url,
               "cached_n": len(oid), "fresh_n": len(nid),
               "only_cached": len(oid - nid), "only_fresh": len(nid - oid),
               "cached_empty": bool(r.get("empty_claim")),
               "fresh_empty": bool(_is_empty_claim(fresh)),
               "verdict": "IDENTICAL" if oid == nid else "DIFFERS",
               "checked_utc": datetime.now(timezone.utc)
               .isoformat(timespec="seconds")}
        # The signature that means poisoning rather than live-database drift:
        # the cache says nothing is there and a verified endpoint says
        # something is.
        rec["zero_overturned"] = bool(rec["cached_empty"]
                                      and not rec["fresh_empty"])
        if rec["verdict"] == "DIFFERS" and not dry_run:
            src = (OSM_CACHE / r["file"] if r["dir"] == OSM_CACHE.name
                   else OSM_CACHE / r["dir"] / r["file"])
            QUAR2.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(QUAR2 / r["file"]))
            tmp = OSM_CACHE / (r["file"] + ".tmp")
            tmp.write_text(json.dumps(fresh), encoding="utf-8")
            tmp.replace(OSM_CACHE / r["file"])
            side = {"key": r["key"], "query": r["query"], "endpoint": url,
                    "fetched_utc": rec["checked_utc"],
                    "n_elements": len(fresh.get("elements") or []),
                    "count_total": _count_total(fresh),
                    **instance_fingerprint(fresh)}
            (OSM_CACHE / ("overpass_%s.meta.json" % r["key"])).write_text(
                json.dumps(side, ensure_ascii=False, indent=1),
                encoding="utf-8")
            rec["action"] = "replaced; original copied to " + QUAR2.name
        elif rec["verdict"] == "IDENTICAL" and r["dir"] != OSM_CACHE.name \
                and not dry_run:
            # A quarantined entry that a verified endpoint reproduces exactly
            # is a genuine measurement, not damage. Restoring it is part of
            # being right rather than merely being safe.
            shutil.copy2(str(OSM_CACHE / r["dir"] / r["file"]),
                         str(OSM_CACHE / r["file"]))
            rec["action"] = "restored to the live cache (confirmed genuine)"
        _ledger_append(rec)
        results.append(rec)

    log("")
    log("-" * 78)
    log("PHASE B RESULT")
    log("-" * 78)
    v = {}
    for r in results:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    for k in sorted(v):
        log("   %-14s %d" % (k, v[k]))
    log("   %-14s %d  (query text unknown; excluded above, not cleared)"
        % ("NO QUERY", len(lack)))
    zo = [r for r in results if r.get("zero_overturned")]
    log("")
    log("   cached-zero OVERTURNED by a verified endpoint: %d" % len(zo))
    for r in zo:
        log("      %s  cached %d -> fresh %d"
            % (r["key"], r["cached_n"], r["fresh_n"]))
    diff = [r for r in results if r["verdict"] == "DIFFERS"
            and not r.get("zero_overturned")]
    if diff:
        log("")
        log("   DIFFERS without a cached zero: %d. OSM is a live database, so"
            % len(diff))
        log("   a small symmetric change is editing, not contamination. The")
        log("   direction and size of each is reported so the reader judges:")
        for r in diff[:40]:
            log("      %s  cached %d -> fresh %d  (-%d/+%d)"
                % (r["key"], r["cached_n"], r["fresh_n"],
                   r["only_cached"], r["only_fresh"]))
    if stopped:
        log("")
        log("   INCOMPLETE: stopped on the time budget. Re-run to continue.")
    return results


HOLD_MANIFEST = OUT / "overpass_holdout_manifest.json"


def in_scope(r: dict) -> bool:
    """The union of the three suspicions. An entry is at risk if the
    fingerprint is not one of today's verified endpoints, OR it was written
    inside the window, OR it carries an empty claim in either form."""
    return (r.get("instance") in ("BANNED", "UNKNOWN", "UNREADABLE")
            or bool(r.get("in_window"))
            or bool(r.get("empty_claim")))


def phase_holdout(recs: list, log, dry_run: bool = False) -> dict:
    """INVALIDATE. Move every at-risk LIVE entry out of the cache so the next
    run of each caller has to re-ask.

    This is the honest way round the fact that the cache never stored the
    query. Re-issuing an entry needs its query text; making the CALLER re-ask
    needs nothing, uses the caller's own query rather than a copy of the
    caller's logic, and cannot drift from it. The originals are moved, not
    deleted, so the comparison in --phase compare has something to compare to.
    """
    log("")
    log("=" * 78)
    log("PHASE HOLDOUT -- invalidate every at-risk cache entry")
    log("=" * 78)
    live = [r for r in recs if r["dir"] == OSM_CACHE.name and in_scope(r)]
    keep = [r for r in recs if r["dir"] == OSM_CACHE.name and not in_scope(r)]
    log("live cache entries        : %d" % (len(live) + len(keep)))
    log("   AT RISK -> held out    : %d" % len(live))
    log("   out of scope, untouched: %d  (all cached 2026-08-27, before the"
        % len(keep))
    log("                             banned mirror existed, and all carrying")
    log("                             a verified fingerprint)")
    log("")
    log("A held-out entry is not a finding. It is a cache entry whose")
    log("provenance this project will not vouch for, removed so that the next")
    log("run measures it again instead of inheriting it.")
    if dry_run:
        log("")
        log("DRY RUN -- nothing moved.")
        return {}
    HOLD.mkdir(parents=True, exist_ok=True)
    moved = {}
    for r in live:
        src = OSM_CACHE / r["file"]
        shutil.move(str(src), str(HOLD / r["file"]))
        side = OSM_CACHE / ("overpass_%s.meta.json" % r["key"])
        if side.exists():
            shutil.move(str(side), str(HOLD / side.name))
        moved[r["key"]] = {k: r.get(k) for k in
                           ("file", "mtime_utc", "n_elements", "count_total",
                            "empty_claim", "generator", "timestamp_osm_base",
                            "instance", "in_window")}
    HOLD_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    HOLD_MANIFEST.write_text(json.dumps({
        "held_out_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": [WINDOW_OPEN.isoformat(), WINDOW_SHUT.isoformat()],
        "n": len(moved), "entries": moved,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log("")
    log("held out %d entries -> %s" % (len(moved), HOLD))
    log("manifest: %s" % HOLD_MANIFEST)
    log("")
    log("NEXT: re-run the chain. Every held-out query is re-asked from a")
    log("verified endpoint, and `overpass()` writes a sidecar recording the")
    log("query text and the endpoint that answered. Then --phase compare.")
    return moved


def phase_compare(log) -> list:
    """VERIFY. Compare what the re-run fetched against what was held out."""
    log("")
    log("=" * 78)
    log("PHASE COMPARE -- held-out cache vs what the re-run fetched")
    log("=" * 78)
    if not HOLD_MANIFEST.exists():
        log("no holdout manifest; run --phase holdout first.")
        return []
    man = json.loads(HOLD_MANIFEST.read_text(encoding="utf-8"))

    # A LIST, not a dict keyed by hash. The first version of this used
    # setdefault on the query hash, and it silently dropped four comparisons:
    # a query the banned mirror answered with 0 was quarantined, then RE-ASKED
    # by the callers after the first audit, so a second file with the SAME
    # HASH existed live and was later held out. Keying by hash kept the good
    # copy and skipped the poisoned one -- so the four entries that most
    # needed comparing were the four that were not compared.
    #
    # It was caught the same way two of the 28 August bugs were caught: two of
    # our own numbers disagreed. The header said "21 already in quarantine"
    # where 25 files are quarantined, and "THE BANNED INSTANCE'S OWN ENTRIES:
    # 17" where 21 carry its fingerprint. Both gaps were exactly 4.
    sources = [(HOLD, k, v) for k, v in man["entries"].items()]

    # The QUARANTINE is compared too, and it is where the poisoning
    # measurement actually lives. The banned-instance entries and the ones the
    # first audit over-quarantined were removed from the cache before this
    # session, so they are not in the holdout manifest -- and leaving them out
    # would mean comparing everything EXCEPT the files known to be bad.
    for qd in (QUAR, QUAR2):
        if not qd.exists():
            continue
        for f in sorted(qd.glob("overpass_*.json")):
            if f.name.endswith(".meta.json"):
                continue
            r = classify(f)
            sources.append((qd, r["key"], r))

    rows = []
    for srcdir, key, old in sources:
        fresh_p = OSM_CACHE / ("overpass_%s.json" % key)
        held_p = srcdir / old["file"]
        rec = {"key": key, "cached_n": old.get("n_elements"),
               "cached_empty": bool(old.get("empty_claim")),
               "was_instance": old.get("instance"),
               "held_in": srcdir.name}
        if not fresh_p.exists():
            # No fresh answer in the live cache. Before calling this
            # unmeasured, check for a VERIFIED answer to the same query
            # elsewhere: when the first audit quarantined a poisoned entry,
            # the callers re-asked and wrote a new file under the SAME HASH,
            # which this session then held out. That held-out file is a
            # verified endpoint's answer to exactly this query, and comparing
            # against it measures what the banned instance cost -- which is
            # the whole point and would otherwise be reported as NOT_REASKED.
            alt_p = HOLD / ("overpass_%s.json" % key)
            alt_ok = (srcdir != HOLD and alt_p.exists()
                      and classify(alt_p).get("instance") == "VERIFIED")
            if not alt_ok:
                # Nothing re-asked this query and nothing else answered it.
                # That is information, not a pass: no caller in the current
                # pipeline issues it any more.
                rec["verdict"] = "NOT_REASKED"
                rows.append(rec)
                continue
            fresh_p = alt_p
            rec["compared_against"] = "verified answer held out from the " \
                                      "cache (same query hash)"
        fresh = json.loads(fresh_p.read_text(encoding="utf-8"))
        try:
            held = json.loads(held_p.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            held = {"elements": []}
        oid, nid = _ids(held), _ids(fresh)
        side = OSM_CACHE / ("overpass_%s.meta.json" % key)
        rec.update({
            "fresh_n": len(nid), "only_cached": len(oid - nid),
            "only_fresh": len(nid - oid),
            "fresh_empty": _is_empty_claim(fresh),
            "endpoint": (json.loads(side.read_text(encoding="utf-8"))
                         .get("endpoint") if side.exists() else None),
            "fresh_generator": instance_fingerprint(fresh)["generator"],
            "verdict": "IDENTICAL" if oid == nid else "DIFFERS",
        })
        rec["zero_overturned"] = bool(rec["cached_empty"]
                                      and not rec["fresh_empty"])
        rows.append(rec)

    v = {}
    for r in rows:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    nh = sum(1 for r in rows if r["held_in"] == HOLD.name)
    nq = len(rows) - nh
    log("compared: %d cached responses  (%d held out this session, %d "
        "already in quarantine)" % (len(rows), nh, nq))
    dup = len({r["key"] for r in rows}) != len(rows)
    if dup:
        log("   NOTE: %d responses share a query hash with another -- the "
            "same query was answered twice, once by the banned instance and"
            % (len(rows) - len({r["key"] for r in rows})))
        log("   once by a verified one. BOTH are compared; keying this table "
            "by hash would drop the poisoned half.")
    for k in sorted(v):
        log("   %-13s %d" % (k, v[k]))
    log("")
    nr = [r for r in rows if r["verdict"] == "NOT_REASKED"]
    if nr:
        log("NOT_REASKED (%d): no caller in the current pipeline issues these"
            % len(nr))
        log("   queries any more -- they are from earlier parameterisations.")
        log("   They stay in the holdout. Nothing reads them, and they are")
        log("   NOT being called clean.")
    zo = [r for r in rows if r.get("zero_overturned")]
    log("")
    log("cached-zero OVERTURNED by a verified endpoint: %d" % len(zo))
    for r in sorted(zo, key=lambda x: -x["fresh_n"]):
        log("   %s  cached %d -> fresh %-6d  (%s)"
            % (r["key"], r["cached_n"], r["fresh_n"], r["was_instance"]))

    banned = [r for r in rows if r.get("was_instance") == "BANNED"]
    log("")
    log("THE BANNED INSTANCE'S OWN ENTRIES: %d" % len(banned))
    log("   re-asked and overturned : %d"
        % sum(1 for r in banned if r.get("zero_overturned")))
    log("   re-asked, still empty   : %d  (the query really does return "
        "nothing; the mirror happened to be right by accident)"
        % sum(1 for r in banned if r["verdict"] != "NOT_REASKED"
              and not r.get("zero_overturned")))
    log("   NOT re-asked            : %d  (no current caller issues this "
        "query)" % sum(1 for r in banned if r["verdict"] == "NOT_REASKED"))
    log("   total elements recovered: %d"
        % sum(r.get("fresh_n", 0) for r in banned))
    viaheld = [r for r in banned if r.get("compared_against")]
    if viaheld:
        log("   of the re-asked, %d were measured against a verified answer "
            "to the same" % len(viaheld))
        log("   query that already existed in the cache (the first audit's "
            "own re-ask):")
        for r in viaheld:
            log("      %s  banned said %d -> verified says %d"
                % (r["key"], r["cached_n"], r["fresh_n"]))

    over = [r for r in rows
            if r["held_in"] == QUAR.name and r.get("was_instance") != "BANNED"]
    if over:
        log("")
        log("OVER-QUARANTINED BY THE FIRST AUDIT: %d" % len(over))
        log("   These are empties from a VERIFIED endpoint that were "
            "quarantined for being empty.")
        for r in over:
            log("   %s  cached %d -> %s"
                % (r["key"], r["cached_n"],
                   ("fresh %d" % r["fresh_n"]) if r["verdict"] != "NOT_REASKED"
                   else "NOT re-asked"))
    diff = [r for r in rows if r["verdict"] == "DIFFERS"]
    if diff:
        log("")
        log("DIFFERS: %d. OSM is a live database and this cache was written"
            % len(diff))
        log("   over two days, so a small symmetric change is somebody")
        log("   editing the map, not contamination. Direction and size are")
        log("   reported so the reader judges rather than the script:")
        for r in sorted(diff, key=lambda x: -(x["only_cached"]))[:60]:
            log("   %s  held %6d -> fresh %6d   lost %5d  gained %5d"
                % (r["key"], r["cached_n"], r["fresh_n"],
                   r["only_cached"], r["only_fresh"]))
        tot_lost = sum(r["only_cached"] for r in diff)
        tot_gain = sum(r["only_fresh"] for r in diff)
        log("")
        log("   totals: %d elements only in the held-out cache, %d only in"
            % (tot_lost, tot_gain))
        log("   the fresh fetch.")
    (OUT / "overpass_holdout_compare.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    log("")
    log("wrote outputs/asset_screen/overpass_holdout_compare.json")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase",
                    choices=["a", "b", "ab", "holdout", "compare"],
                    default="ab")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--budget-s", type=float, default=0.0,
                    help="soft wall-clock budget for phase B; 0 = none")
    ap.add_argument("--skip-selftest", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    lines: list = []

    def log(m: str = "") -> None:
        print(m)
        lines.append(m)

    log("OVERPASS CACHE AUDIT (2) -- provenance, not emptiness")
    log("run %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log("")
    log("BANNED INSTANCES:")
    for u, meta in OVERPASS_BANNED.items():
        log("   %s" % u)
        log("      banned %s -- %s" % (meta["banned"], meta["why"]))
        log("      fingerprint: generator=%r  timestamp_osm_base=%s"
            % (meta["generator"], meta["timestamp_osm_base_form"]))
        log("      cost: %s" % meta["cost"])
    log("")

    log("GUARD SELF-TEST -- do the guards stop a banned response?")
    log("   A tool should show its instrument works before reporting")
    log("   measurements from it.")
    gs = guard_selftest(live=not args.skip_selftest)
    for k, v in gs.items():
        log("   %-34s %s  %s" % (k, "PASS" if v["passed"] else "FAIL",
                                 v.get("detail", "")))
    log("")

    if not args.skip_selftest:
        log("MIRROR COVERAGE SELF-TEST (Cork + Galway building counts):")
        cov = mirror_coverage_selftest()
        log("   every listed mirror holds Irish data in both areas and "
            "reports an ISO database timestamp, or this run would have "
            "aborted here.")
    else:
        cov = {"skipped": True}

    recs = phase_a(log)
    results = []
    if args.phase == "holdout":
        phase_holdout(recs, log, dry_run=args.dry_run)
    elif args.phase == "compare":
        results = phase_compare(log)
    elif args.phase in ("b", "ab"):
        results = phase_b(recs, log, dry_run=args.dry_run,
                          budget_s=args.budget_s)

    (OUT / "overpass_cache_audit.json").write_text(json.dumps({
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": [WINDOW_OPEN.isoformat(), WINDOW_SHUT.isoformat()],
        "banned": OVERPASS_BANNED,
        "verified_generators": VERIFIED_GENERATORS,
        "mirror_coverage": cov,
        "guard_selftest": gs,
        "entries": recs,
        "phase_b": results,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / ("overpass_cache_audit_%s.log" % args.phase)).write_text(
        "\n".join(lines), encoding="utf-8")
    log("")
    log("wrote outputs/asset_screen/overpass_cache_audit.json and "
        "overpass_cache_audit_%s.log" % args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
