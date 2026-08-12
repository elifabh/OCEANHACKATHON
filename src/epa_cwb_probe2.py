#!/usr/bin/env python3
"""
epa_cwb_probe2.py -- bbox-free retry.

The first probe returned 0 features on all 33 layers. That is not absence, it is
a CRS/axis-order failure: EPA layers are in Irish Grid / ITM, not WGS84, and the
bbox filter silently matched nothing.

Fix: drop the bbox. Ireland has ~110 coastal waterbodies. Download the whole
layer and filter by NAME in Python. Also prints the CRS actually returned, so
we learn the projection for every future EPA call.

Run: python src/epa_cwb_probe2.py
"""

import json
import re
import sys
from pathlib import Path

import requests

OWS = "https://gis.epa.ie/geoserver/EPA/ows"
UA = {"User-Agent": "OceanHackathonCork2026/0.1 (MSc research; kelp valuation)"}
OUTDIR = Path("outputs/epa_cwb")

LAYERS = [
    "EPA:WFD_CWBStatus_20072009",
    "EPA:WFD_CWBStatus_20102012",
    "EPA:WFD_CWBStatus_20102015",
    "EPA:WFD_CWBStatus_20132018",
    "EPA:WFD_CWBStatus_20162021",
    "EPA:WFD_CWBStatus_20192024",
    "EPA:WFD_COASTALWATERBODIES_CYCLE3",
]

# West Cork place names likely to appear in a waterbody name
WESTCORK = re.compile(
    r"roaring|baltimore|sherkin|long island|schull|clear|dunmanus|"
    r"bantry|mizen|crookhaven|toe head|castletown|cork coastal|"
    r"south west|dunworley|galley", re.I)


def fetch(layer):
    p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
         "typeNames": layer, "outputFormat": "application/json", "count": 5000}
    r = requests.get(OWS, params=p, headers=UA, timeout=120)
    r.raise_for_status()
    if not r.text.lstrip().startswith("{"):
        raise ValueError(f"non-JSON response ({r.text[:200]})")
    return r.json()


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    matched = {}

    for layer in LAYERS:
        short = layer.split(":")[1]
        print("\n" + "=" * 70)
        print(short)
        print("=" * 70)
        try:
            gj = fetch(layer)
        except Exception as e:
            print(f"  FAILED: {e}")
            continue

        feats = gj.get("features", [])
        crs = json.dumps(gj.get("crs", "not stated"))
        print(f"  {len(feats)} features   crs={crs}")
        if not feats:
            continue

        # what does a feature actually look like?
        props = feats[0].get("properties", {})
        print(f"  fields: {list(props)}")
        geom = feats[0].get("geometry") or {}
        coords = geom.get("coordinates")
        while isinstance(coords, list) and coords and isinstance(coords[0], list):
            coords = coords[0]
        print(f"  first coordinate: {coords}   <-- tells us the projection")

        (OUTDIR / f"{short}.geojson").write_text(json.dumps(gj), encoding="utf-8")

        # name-based filter
        hits = []
        for f in feats:
            p = f.get("properties", {})
            blob = " ".join(str(v) for v in p.values() if v)
            if WESTCORK.search(blob):
                hits.append({k: v for k, v in p.items()
                             if v not in (None, "", " ")
                             and re.search(r"name|code|status|class|risk|year|cycle",
                                           k, re.I)})
        print(f"  West Cork name matches: {len(hits)}")
        for h in hits:
            print("   ", h)
        matched[short] = hits

    # --- the actual question -------------------------------------------
    print("\n" + "=" * 70)
    print("SAME WATERBODY ACROSS CYCLES?")
    print("=" * 70)
    codes = {}
    for layer, hits in matched.items():
        for h in hits:
            code = next((v for k, v in h.items()
                         if re.search(r"code|_id$", k, re.I)), None)
            name = next((v for k, v in h.items()
                         if re.search(r"name", k, re.I)), "?")
            status = next((v for k, v in h.items()
                           if re.search(r"status|class", k, re.I)), "?")
            if code:
                codes.setdefault((code, name), []).append((layer, status))

    if not codes:
        print("No West Cork waterbody matched by name.")
        print("Open outputs/epa_cwb/*.geojson and inspect the name field manually,")
        print("then widen the WESTCORK regex.")
    for (code, name), series in sorted(codes.items()):
        print(f"\n{code}  {name}   ({len(series)} cycles)")
        for lyr, st in series:
            print(f"    {lyr:35s} {st}")

    print(f"\nraw layers saved to {OUTDIR}/")


if __name__ == "__main__":
    main()