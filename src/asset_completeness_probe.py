#!/usr/bin/env python3
"""
asset_completeness_probe.py -- can a ZERO in this receptor class be used as
evidence of absence?

THE PROBLEM
-----------
The asset screen reports, per class, how many receptors it found at 53 rural
coastal clusters. Many classes will report zero. A zero has two completely
different meanings and the screen cannot tell them apart:

    (a) the asset is not there;
    (b) the asset is there and OSM does not record it.

For a road, (a) is likely -- OSM's Irish road network is essentially
complete. For a manhole, a buried pipeline, a street cabinet or a culvert,
(b) is likely, and quoting a zero as "no receptors" would be a false
negative dressed as a finding. `asset_classes.py` assigns every class a
prior judgement (high / medium / low). This script tests that judgement
against data instead of leaving it as an assertion.

THE TEST
--------
Run the SAME five family queries, over boxes of the SAME size, at:

    RURAL   the 53 screened coastal clusters
    URBAN   six western/north-western Irish town centres, where the same
            national mapping community has been active and where the
            physical asset is known to exist (every Irish town has
            manholes, street cabinets, sewers and street lighting)

and compare the count per box. If a class is richly mapped in the towns and
absent from the rural coast, the class is one where mapper attention, not
the asset, may be what varies.

WHAT THIS TEST CAN AND CANNOT SETTLE
------------------------------------
It CANNOT separate "genuinely urban asset" from "only mapped in towns". A
traffic signal really is an urban object; so is a street cabinet; the ratio
looks the same for both. So a high urban:rural ratio is a REASON FOR
CAUTION, not proof of under-mapping, and it is reported as such.

It CAN settle one thing decisively, in one direction: a class with zero
features in BOTH the rural and the urban sample is a class this pipeline has
no ability to observe at all in Ireland. For such a class an empty cell at a
cluster carries no information whatever, and the screen must not count it as
a negative. That is the `blind` verdict below.

VERDICTS
--------
    observable_rural   found at rural clusters -- absence elsewhere is
                       informative to the degree the class allows
    urban_skewed       found in towns, absent or near-absent at the coast,
                       with a per-box ratio at or above URBAN_SKEW_RATIO --
                       treat rural zeros with caution
    blind              found nowhere in either sample -- a rural zero is
                       UNINFORMATIVE and may not be reported as absence

The verdict is written beside every class in the output, and the handover
note reproduces the `blind` and `urban_skewed` lists in full.

PROVENANCE
----------
  (c) OpenStreetMap contributors, ODbL 1.0.
  Town centre coordinates are approximate centroids typed here to place a
  1.6 km probe box; they are not surveyed positions and nothing depends on
  their precision beyond "this box is in that town".

Run:  PYTHONPATH=src python src/asset_completeness_probe.py
Writes only under outputs/asset_screen/.
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box as shp_box

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_classes as ac  # noqa: E402
from national_asset_screen import BOX_HALF_M, fetch_assets_for_boxes  # noqa: E402
from national_exposure_screen import select_clusters  # noqa: E402
from wide_receptor_screen import ITM, WGS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "asset_screen"

# Six town centres in the same coastal counties the screen covers, so the
# comparison is with the same national mapping community rather than with
# Dublin. Approximate centroids; the box is 1.6 km across.
URBAN_BOXES = [
    ("Galway",      -9.0568, 53.2707),
    ("Sligo",       -8.4761, 54.2766),
    ("Letterkenny", -7.7342, 54.9503),
    ("Tralee",      -9.7016, 52.2713),
    ("Ennis",       -8.9864, 52.8438),
    ("Westport",    -9.5229, 53.8008),
]

URBAN_SKEW_RATIO = 5.0     # urban per-box count / rural per-box count


def box_around(lon: float, lat: float, to_itm, to_wgs) -> tuple:
    cx, cy = to_itm.transform(lon, lat)
    sw = to_wgs.transform(cx - BOX_HALF_M, cy - BOX_HALF_M)
    ne = to_wgs.transform(cx + BOX_HALF_M, cy + BOX_HALF_M)
    return (sw[0], sw[1], ne[0], ne[1])


def count_classes(assets) -> dict:
    counts = {k: 0 for k in ac.KEYS}
    if not len(assets):
        return counts
    for cls in assets["classes"]:
        for k in cls:
            counts[k] += 1
    return counts


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list = []

    def log(m: str = "") -> None:
        print(m)
        lines.append(m)

    log("=" * 78)
    log("ASSET COMPLETENESS PROBE -- when is a zero evidence of absence?")
    log("=" * 78)
    log("run %s" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    log("box half-width %.0f m (identical to the screen), %d classes"
        % (BOX_HALF_M, len(ac.KEYS)))
    log("urban skew ratio flagged at >= %.1fx per box" % URBAN_SKEW_RATIO)
    log("(c) OpenStreetMap contributors, ODbL 1.0")

    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)

    # ---------------- urban ----------------
    log("\n-- URBAN reference boxes --")
    # All six boxes in ONE batched pull (fetch_assets_for_boxes batches 8 per
    # query), then attributed to a town by which box the element falls in.
    # Six separate calls would be 36 Overpass requests against an endpoint
    # that has been returning 429 all session, for exactly the same answer.
    urban_counts = {k: 0 for k in ac.KEYS}
    urban_boxes_with = {k: 0 for k in ac.KEYS}
    tboxes = [(name, box_around(lon, lat, to_itm, to_wgs))
              for name, lon, lat in URBAN_BOXES]
    assets, _, _ = fetch_assets_for_boxes([b for _, b in tboxes],
                                          lambda m: None)
    log("   %d classified elements across %d town boxes"
        % (len(assets), len(tboxes)))
    for name, b in tboxes:
        if len(assets):
            env = shp_box(b[0], b[1], b[2], b[3])
            sub = assets[assets.geometry.intersects(env)]
        else:
            sub = assets
        c = count_classes(sub)
        for k, v in c.items():
            urban_counts[k] += v
            if v:
                urban_boxes_with[k] += 1
        log("   %-12s %5d classified elements" % (name, len(sub)))

    # ---------------- rural ----------------
    # Read from the screen's own per-cluster cache: the rural counts must be
    # the SAME numbers the screen produced, not a second, subtly different
    # pull. If the cache is not there, say so and stop rather than issue 53
    # more Overpass queries that could disagree with it.
    log("\n-- RURAL: the screened clusters, read from the screen's cache --")
    cache = OUT / "cache"
    files = sorted(cache.glob("cluster_*.json")) if cache.exists() else []
    rural_counts = {k: 0 for k in ac.KEYS}
    rural_boxes_with = {k: 0 for k in ac.KEYS}
    n_rural = 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                     # noqa: BLE001
            continue
        if not d.get("complete"):
            continue
        n_rural += 1
        for k, pc in d["summary"]["per_class"].items():
            rural_counts[k] += pc["n"]
            if pc["n"]:
                rural_boxes_with[k] += 1
    log("   %d complete cluster caches read" % n_rural)
    if n_rural == 0:
        log("   >>> no screened clusters on disk. Run national_asset_screen.py "
            "first; this probe reports the screen's own counts and will not "
            "issue a second, possibly divergent pull.")
        (OUT / "asset_completeness_probe.log").write_text("\n".join(lines),
                                                          encoding="utf-8")
        return 1

    n_urban = len(URBAN_BOXES)
    rows = []
    for k in ac.KEYS:
        c = ac.BY_KEY[k]
        r_per = rural_counts[k] / n_rural
        u_per = urban_counts[k] / n_urban
        if rural_counts[k] == 0 and urban_counts[k] == 0:
            verdict = "blind"
        elif rural_counts[k] > 0 and (u_per <= URBAN_SKEW_RATIO * max(r_per, 1e-9)):
            verdict = "observable_rural"
        elif rural_counts[k] > 0:
            verdict = "urban_skewed"
        else:
            verdict = "urban_skewed"       # urban>0, rural==0
        ratio = (u_per / r_per) if r_per > 0 else (np.inf if u_per > 0 else np.nan)
        rows.append({
            "class": k, "family": c["family"], "label": c["label"],
            "prior_completeness": c["completeness"],
            "rural_n": rural_counts[k], "rural_boxes": n_rural,
            "rural_boxes_with_any": rural_boxes_with[k],
            "rural_per_box": round(r_per, 3),
            "urban_n": urban_counts[k], "urban_boxes": n_urban,
            "urban_boxes_with_any": urban_boxes_with[k],
            "urban_per_box": round(u_per, 3),
            "urban_rural_ratio": (None if not np.isfinite(ratio)
                                  else round(float(ratio), 2)),
            "ratio_is_infinite": bool(r_per == 0 and u_per > 0),
            "verdict": verdict,
            "absence_usable": verdict == "observable_rural",
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "asset_completeness_probe.csv", index=False)

    log("\n%-24s %-6s %8s %8s %8s  %s"
        % ("class", "prior", "rural/bx", "urban/bx", "ratio", "verdict"))
    log("-" * 78)
    for _, r in df.sort_values(["verdict", "class"]).iterrows():
        ratio = "inf" if r["ratio_is_infinite"] else (
            "-" if r["urban_rural_ratio"] is None else "%.1f" % r["urban_rural_ratio"])
        log("%-24s %-6s %8.2f %8.2f %8s  %s"
            % (r["class"], r["prior_completeness"], r["rural_per_box"],
               r["urban_per_box"], ratio, r["verdict"]))

    blind = df[df.verdict == "blind"]["class"].tolist()
    skew = df[df.verdict == "urban_skewed"]["class"].tolist()
    obs = df[df.verdict == "observable_rural"]["class"].tolist()

    log("\n" + "=" * 78)
    log("VERDICTS")
    log("=" * 78)
    log("observable_rural (%d): a zero here is informative" % len(obs))
    log("   %s" % ", ".join(obs))
    log("\nurban_skewed (%d): found in towns, absent/near-absent on the rural "
        "coast." % len(skew))
    log("   TREAT RURAL ZEROS WITH CAUTION -- this test cannot separate 'the "
        "asset is\n   genuinely urban' from 'the class is only mapped in "
        "towns'.")
    log("   %s" % ", ".join(skew))
    log("\nblind (%d): ZERO IN BOTH SAMPLES. This pipeline cannot observe the "
        "class in\n   Ireland at all. A rural zero carries NO information and "
        "may not be reported\n   as absence." % len(blind))
    log("   %s" % ", ".join(blind))

    # where the prior judgement in asset_classes disagrees with the data
    log("\n" + "=" * 78)
    log("PRIOR vs DATA -- where the hand-assigned completeness was wrong")
    log("=" * 78)
    dis = df[((df.prior_completeness == "high") & (df.verdict != "observable_rural"))
             | ((df.prior_completeness == "low") & (df.verdict == "observable_rural"))]
    if len(dis):
        for _, r in dis.iterrows():
            log("   %-24s prior %-6s -> %s (rural %d, urban %d)"
                % (r["class"], r["prior_completeness"], r["verdict"],
                   r["rural_n"], r["urban_n"]))
        log("\n   The prior is a judgement and the data is a measurement. "
            "Where they\n   disagree the data is reported and the prior is "
            "left visible, not edited\n   after the fact to match.")
    else:
        log("   none")

    summ = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_rural_boxes": n_rural, "n_urban_boxes": n_urban,
            "urban_skew_ratio": URBAN_SKEW_RATIO,
            "urban_boxes": [{"name": n, "lon": lo, "lat": la}
                            for n, lo, la in URBAN_BOXES],
            "verdicts": {"observable_rural": obs, "urban_skewed": skew,
                         "blind": blind},
            "prior_vs_data_disagreements": dis["class"].tolist() if len(dis) else [],
            "what_this_cannot_settle": (
                "A high urban:rural ratio is consistent BOTH with a genuinely "
                "urban asset and with a class that is only mapped in towns. "
                "The test flags; it does not prove under-mapping."),
            }
    (OUT / "asset_completeness_probe.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "asset_completeness_probe.log").write_text("\n".join(lines),
                                                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
