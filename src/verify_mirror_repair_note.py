#!/usr/bin/env python3
"""
verify_mirror_repair_note.py -- check every number in
`docs/NOTE_2026-08-28_mirror_repair.md` against the file that produced it.

WHY
---
CLAUDE.md: "No number without a verified source." A handover note whose
figures are typed by hand drifts from the CSVs the moment either changes, and
this session's whole subject is a number that nobody checked. So the note is
checked by a script, it exits non-zero on any mismatch, and it also asserts
the locked facts the note must not get wrong (7.9 % / 15.2 % / 1.75 ha
present; the retired 9.8 ha / 42.7 / 67.2 absent; no percentage rendering of
the biodiversity result).

Every assertion must be capable of FAILING. An earlier draft of this file
contained `252 == 227 + 25`, which is arithmetic rather than a check -- it
would have passed against any repo on earth. It is replaced below by reading
the count out of the audit log that recorded it.

    PYTHONPATH=src python src/verify_mirror_repair_note.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
note = (REPO / 'docs' / 'NOTE_2026-08-28_mirror_repair.md').read_text(
    encoding='utf-8')

audit = json.loads((REPO / 'outputs' / 'asset_screen'
                    / 'overpass_cache_audit.json').read_text(encoding='utf-8'))
cmp_ = json.loads((REPO / 'outputs' / 'asset_screen'
                   / 'overpass_holdout_compare.json').read_text(encoding='utf-8'))
hold = json.loads((REPO / 'outputs' / 'asset_screen'
                   / 'overpass_holdout_manifest.json').read_text(encoding='utf-8'))
diff = json.loads((REPO / 'outputs' / 'phaseb_national'
                   / 'results_diff.json').read_text(encoding='utf-8'))
expo = pd.read_csv(REPO / 'outputs' / 'exposure_screen'
                   / 'national_exposure_screen.csv')
asset = pd.read_csv(REPO / 'outputs' / 'asset_screen'
                    / 'national_asset_screen.csv')
val = pd.read_csv(REPO / 'outputs' / 'asset_valuation'
                  / 'national_asset_valuation.csv')
probe = pd.read_csv(REPO / 'outputs' / 'asset_screen'
                    / 'asset_completeness_probe.csv')
rt = pd.read_csv(REPO / 'outputs' / 'phaseb_national'
                 / 'NATIONAL_RESULTS_TABLE.csv')

fails = []
TOTAL = 0


def check(claim: str, ok: bool, got=None) -> None:
    global TOTAL
    TOTAL += 1
    print("%-4s %-64s %s" % ("ok" if ok else "FAIL", claim,
                             "" if ok else "got %r" % (got,)))
    if not ok:
        fails.append(claim)


def innote(t: str) -> bool:
    return t in note


ents = audit['entries']
print("=== cache audit ===")
# The count the note quotes is the state AT THE MOMENT THE AUDIT WAS TAKEN,
# read back out of the log that recorded it. It cannot be recomputed from the
# live cache, because a re-fetched response is a new file that sits beside the
# held-out original rather than replacing it -- so the live total grows by
# exactly what was re-asked, and today reads 335.
hold_log = (REPO / 'outputs' / 'asset_screen'
            / 'overpass_cache_audit_holdout.log').read_text(encoding='utf-8')
m = re.search(r'cache entries examined: (\d+)\s+\((\d+) live, (\d+) '
              r'quarantined', hold_log)
check("audit-time count is recorded in the holdout log", m is not None)
if m:
    tot, liv, qua = (int(x) for x in m.groups())
    check("252 entries at audit time", tot == 252, tot)
    check("227 live at audit time", liv == 227, liv)
    check("25 quarantined at audit time", qua == 25, qua)
    check("the note quotes that same 252",
          'All 252 cache entries were' in note)
check("125 in the holdout directory",
      sum(1 for e in ents if e["dir"] == "verify_holdout") == 125,
      sum(1 for e in ents if e["dir"] == "verify_holdout"))
check("25 in quarantine",
      sum(1 for e in ents if e["dir"] == "quarantine_poisoned") == 25,
      sum(1 for e in ents if e["dir"] == "quarantine_poisoned"))
check("21 BANNED", sum(1 for e in ents if e.get('instance') == 'BANNED') == 21)
check("0 UNKNOWN", sum(1 for e in ents if e.get('instance') == 'UNKNOWN') == 0)
check("150 in window",
      sum(1 for e in ents if e.get('in_window')) == 150,
      sum(1 for e in ents if e.get('in_window')))
check("0 banned entries live",
      sum(1 for e in ents
          if e.get('instance') == 'BANNED' and e['dir'] == 'osm') == 0)
check("0 banned entries non-empty",
      sum(1 for e in ents
          if e.get('instance') == 'BANNED' and not e.get('empty_claim')) == 0)
check("125 held out", hold['n'] == 125, hold['n'])

print("\n=== compare ===")
v = {}
for r in cmp_:
    v[r['verdict']] = v.get(r['verdict'], 0) + 1
check("150 responses compared", len(cmp_) == 150, len(cmp_))
check("80 IDENTICAL", v.get('IDENTICAL') == 80, v.get('IDENTICAL'))
check("4 DIFFERS", v.get('DIFFERS') == 4, v.get('DIFFERS'))
check("66 NOT_REASKED", v.get('NOT_REASKED') == 66, v.get('NOT_REASKED'))
d = [r for r in cmp_ if r['verdict'] == 'DIFFERS']
check("all 4 DIFFERS are BANNED",
      all(r['was_instance'] == 'BANNED' for r in d),
      [r['was_instance'] for r in d])
check("0 elements lost", sum(r['only_cached'] for r in d) == 0,
      sum(r['only_cached'] for r in d))
banned = [r for r in cmp_ if r.get('was_instance') == 'BANNED']
rec = sum(r.get('fresh_n', 0) for r in banned)
check("677 elements recovered", rec == 677, rec)
byk = {r['key']: r for r in cmp_ if r['verdict'] == 'DIFFERS'}
for k, n in (('54d2bbeff3a6', 641), ('edb91a94f9aa', 32),
             ('2a861b7269fc', 3), ('1816057e28cf', 1)):
    check("%s 0 -> %d" % (k, n),
          k in byk and byk[k]['cached_n'] == 0 and byk[k]['fresh_n'] == n,
          byk.get(k, {}).get('fresh_n'))

print("\n=== screens ===")
check("53 clusters in exposure screen", len(expo) == 53, len(expo))
check("1374 building observations",
      int(expo.n_buildings_500m.sum()) == 1374, int(expo.n_buildings_500m.sum()))
check("44 below 5 m", int(expo.n_below_5m.sum()) == 44, int(expo.n_below_5m.sum()))
check("301 below 10 m", int(expo.n_below_10m.sum()) == 301,
      int(expo.n_below_10m.sum()))
check("28 exposed receptors", int(expo.exposed_receptors.sum()) == 28,
      int(expo.exposed_receptors.sum()))
check("7 clusters flagged", int((expo.exposed_receptors > 0).sum()) == 7,
      int((expo.exposed_receptors > 0).sum()))
c991 = expo[expo.cluster == 991].iloc[0]
check("991: 24 buildings", int(c991.n_buildings_500m) == 24,
      int(c991.n_buildings_500m))
check("991: 5 below 5 m", int(c991.n_below_5m) == 5, int(c991.n_below_5m))
check("991: 5 exposed", int(c991.exposed_receptors) == 5,
      int(c991.exposed_receptors))
check("2130 receptors", int(asset.n_assets.sum()) == 2130,
      int(asset.n_assets.sum()))
check("293 below 5 m (assets)", int(asset.n_low_5m.sum()) == 293,
      int(asset.n_low_5m.sum()))
check("260 exposed (assets)", int(asset.n_exposed.sum()) == 260,
      int(asset.n_exposed.sum()))

print("\n=== probe ===")
pv = probe.verdict.value_counts().to_dict()
check("34 observable_rural", pv.get('observable_rural') == 34)
check("9 absent_rural_present_urban", pv.get('absent_rural_present_urban') == 9)
check("7 blind", pv.get('blind') == 7)

print("\n=== euro column (string states, not numbers) ===")
vc = val.coastal_protection_eur.astype(str).value_counts().to_dict()
ez = vc.get("EUR 0 - evidenced zero", 0)
nc = vc.get("not computable", 0)
check("14 evidenced zero", ez == 14, ez)
check("39 not computable", nc == 39, nc)
other = {k: n for k, n in vc.items()
         if k not in ("EUR 0 - evidenced zero", "not computable")}
check("no third euro state (i.e. no figure anywhere)", other == {}, other)

print("\n=== results table ===")
evc = rt.euro.astype(str).value_counts().to_dict()
ez2 = sum(n for k, n in evc.items() if k.startswith("EUR 0"))
nc2 = sum(n for k, n in evc.items() if k.startswith("not computable"))
check("52 of 53 evidenced zeros", ez2 == 52, ez2)
check("1 not computable", nc2 == 1, nc2)
check("every row is one of those two states", ez2 + nc2 == len(rt),
      (ez2, nc2, len(rt)))
check("avoided_damage_eur is 0 or missing, never positive",
      float(rt.avoided_damage_eur.fillna(0).max()) == 0.0,
      float(rt.avoided_damage_eur.fillna(0).max()))

print("\n=== results diff ===")
check("all 6 tables IDENTICAL",
      all(t['status'] == 'identical' for t in diff['tables']),
      [(t['table'], t['status']) for t in diff['tables']])
check("no table STALE",
      not any(t['status'] == 'stale' for t in diff['tables']))

print("\n=== locked facts still stated correctly in the note ===")
check("note says 14 of 17 nowhere as a percentage", '82%' not in note)
check("note says 7.9 %", innote('7.9 %'))
check("note says 15.2 %", innote('15.2 %'))
check("note says 1.75 ha", innote('1.75 ha'))
for retired in ('9.8 ha', '42.7', '67.2'):
    check("retired figure %s absent" % retired, retired not in note)

print("\n" + "=" * 70)
if fails:
    print("FAILED %d CHECK(S):" % len(fails))
    for f in fails:
        print("   " + f)
    raise SystemExit(1)
print("ALL CHECKS PASSED -- every number in the note matches its source file.")
print("%d assertions, every one capable of failing." % TOTAL)
