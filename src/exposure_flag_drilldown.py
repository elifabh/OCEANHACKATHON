#!/usr/bin/env python3
"""
exposure_flag_drilldown.py -- inspect the clusters that national_exposure_screen
flagged as having low-lying occupied buildings, and ask the one question the
screen itself cannot answer:

    is the LOW-LYING GROUND behind the EXPOSED water, or behind sheltered
    water on the other side of the same headland?

That distinction is the whole story of this project so far. At An Aird
(Phase B, section 6c) every flood-exposed house within 4 km sat on water
BELOW the fetch gate, while the two clusters that cleared the gate held no
exposed buildings. The national screen samples fetch once, at the cluster
CENTROID. A settlement wrapped around a point or a neck can therefore clear
the gate on its seaward side while its low houses face a bay.

So this script re-samples the imported, unmodified FetchSampler at EVERY
individual building in the flagged clusters, and reports the fetch of the
water each low building actually faces.

It adds no new parameter. FETCH_EXCLUSION_MAX and the tie rule are imported
from wide_receptor_screen exactly as everywhere else.

INTERNAL OPW cross-check is reproduced per building for the flagged
clusters only. CC BY-NC-ND 4.0, unresolved -- counts and distances stay in
this repo (CLAUDE.md rule 9).

Run:  PYTHONPATH=src python src/exposure_flag_drilldown.py
Writes only under outputs/exposure_screen/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wide_receptor_screen import (  # noqa: E402
    FETCH_EXCLUSION_MAX,
    FETCH_RASTER,
    ITM,
    WGS,
    FetchSampler,
)
from national_exposure_screen import (  # noqa: E402
    LOW_BANDS_M,
    OPW_LAYERS,
    opw_union,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "outputs" / "exposure_screen"


def main() -> int:
    scr = pd.read_csv(OUT / "national_exposure_screen.csv")
    rec = pd.read_csv(OUT / "national_exposure_receptors.csv")
    flagged = scr[scr.exposed_receptors > 0].sort_values(
        "exposed_receptors", ascending=False)

    print("=" * 78)
    print("DRILLDOWN -- clusters with >0 exposed receptors")
    print("=" * 78)
    print("imported gate FETCH_EXCLUSION_MAX = %s" % FETCH_EXCLUSION_MAX)
    print("%d flagged clusters, %d exposed receptors in total"
          % (len(flagged), int(flagged.exposed_receptors.sum())))

    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    fs = FetchSampler(FETCH_RASTER)
    rows = []
    try:
        for _, c in flagged.iterrows():
            sub = rec[rec.cluster == c.cluster].copy()
            print("\n" + "-" * 78)
            print("cluster %d  %s  %s" % (c.cluster, c.county, c.nearest_place))
            print("  %.5f N %.5f W   evidence %s   survey record: %s"
                  % (c.lat, abs(c.lon), c.evidence_class,
                     bool(c.evidence_is_survey_record)))
            print("  centroid fetch %.3f - %.3f (strict gate %.2f)"
                  % (c.fetch_nearest_min, c.fetch_nearest_max,
                     FETCH_EXCLUSION_MAX))
            print("  %d buildings, %d occupied-tag, %d occupied below 5 m"
                  % (c.n_buildings_500m, c.n_occupied_tag,
                     c.n_occupied_below_5m))

            cx, cy = to_itm.transform(c.lon, c.lat)
            opw = {}
            for label, code in OPW_LAYERS:
                u, n = opw_union(cx, cy, 2000.0, code)
                opw[label] = u

            for _, b in sub.iterrows():
                bx, by = to_itm.transform(b.lon, b.lat)
                f = fs.sample(bx, by)
                p = Point(bx, by)
                r = {
                    "cluster": int(c.cluster), "county": c.county,
                    "osm_id": b.osm_id, "building": b.building,
                    "occupied_tag": bool(b.occupied_tag),
                    "lon": b.lon, "lat": b.lat,
                    "dist_shore_m": round(float(b.dist_shore_m), 1),
                    "elev_m": (None if not np.isfinite(b.elev_used_m)
                               else round(float(b.elev_used_m), 2)),
                    "elev_is_water_pixel": bool(b.elev_is_water_pixel),
                    "bld_fetch_min": (None if not np.isfinite(f["fetch_nearest_min"])
                                      else round(f["fetch_nearest_min"], 3)),
                    "bld_fetch_max": (None if not np.isfinite(f["fetch_nearest_max"])
                                      else round(f["fetch_nearest_max"], 3)),
                    "bld_fetch_n_tied": f["n_tied"],
                    "bld_dist_to_sea_m": (None if not np.isfinite(f["dist_to_sea_m"])
                                          else round(f["dist_to_sea_m"])),
                    "bld_fetch_passes_strict": (
                        bool(f["fetch_nearest_min"] > FETCH_EXCLUSION_MAX)
                        if np.isfinite(f["fetch_nearest_min"]) else None),
                }
                for label in opw:
                    u = opw[label]
                    key = "opw_internal_%s" % label.replace(" ", "")
                    if u is None:
                        r[key + "_inside"] = None
                        r[key + "_dist_m"] = None
                    else:
                        r[key + "_inside"] = bool(u.contains(p))
                        r[key + "_dist_m"] = round(float(p.distance(u)), 1)
                rows.append(r)

            d = pd.DataFrame([r for r in rows if r["cluster"] == c.cluster])
            low = d[(d.elev_m.notna()) & (d.elev_m < LOW_BANDS_M[0])
                    & (d.occupied_tag)].sort_values("elev_m")
            print("\n  the %d occupied buildings below 5 m, and the water each "
                  "one actually faces:" % len(low))
            print("  %-16s %-9s %7s %7s %8s %8s %6s  %s"
                  % ("osm_id", "building", "shore m", "elev m", "fetch<",
                     "fetch>", "gate", "OPW 1000yr"))
            for _, b in low.iterrows():
                inside = b.get("opw_internal_1000yr_inside")
                dist = b.get("opw_internal_1000yr_dist_m")
                opw_txt = ("INSIDE" if inside else
                           ("outside by %.0f m" % dist if dist is not None
                            else "no extent mapped"))
                print("  %-16s %-9s %7.0f %7.2f %8s %8s %6s  %s"
                      % (b.osm_id, b.building, b.dist_shore_m, b.elev_m,
                         b.bld_fetch_min, b.bld_fetch_max,
                         "PASS" if b.bld_fetch_passes_strict else "fail",
                         opw_txt))

            n_pass = int(low.bld_fetch_passes_strict.fillna(False).sum())
            print("\n  -> %d of %d low occupied buildings face water that "
                  "itself clears the gate" % (n_pass, len(low)))
            if n_pass == 0 and len(low):
                print("     i.e. the An Aird pattern again: the exposure and "
                      "the low ground are on\n     opposite sides of the same "
                      "headland.")
    finally:
        fs.close()

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "exposure_flag_drilldown.csv", index=False)

    print("\n" + "=" * 78)
    print("SUMMARY -- per cluster")
    print("=" * 78)
    summ = []
    for cl, d in out.groupby("cluster"):
        low = d[(d.elev_m.notna()) & (d.elev_m < LOW_BANDS_M[0])
                & (d.occupied_tag)]
        c = flagged[flagged.cluster == cl].iloc[0]
        summ.append({
            "cluster": cl, "county": c.county, "place": c.nearest_place,
            "evidence": c.evidence_class,
            "low_occupied": len(low),
            "low_occupied_facing_gate_passing_water":
                int(low.bld_fetch_passes_strict.fillna(False).sum()),
            "low_occupied_in_opw_1000yr":
                int(low.opw_internal_1000yr_inside.fillna(False).sum()),
            "any_bld_in_opw_1000yr":
                int(d.opw_internal_1000yr_inside.fillna(False).sum()),
        })
    s = pd.DataFrame(summ).sort_values(
        ["low_occupied_facing_gate_passing_water", "low_occupied"],
        ascending=False)
    with pd.option_context("display.width", 220, "display.max_colwidth", 34):
        print(s.to_string(index=False))
    s.to_csv(OUT / "exposure_flag_drilldown_summary.csv", index=False)
    (OUT / "exposure_flag_drilldown_summary.json").write_text(
        json.dumps(summ, indent=2, default=str), encoding="utf-8")
    print("\nwrote outputs/exposure_screen/exposure_flag_drilldown.csv")
    print("wrote outputs/exposure_screen/exposure_flag_drilldown_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
