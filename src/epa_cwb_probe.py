#!/usr/bin/env python3
"""
epa_cwb_probe.py -- is there a repeated WFD status series for Roaringwater Bay?

Step 1: ask EPA GeoServer what coastal-waterbody layers exist (one per WFD cycle).
Step 2: for each, pull the polygon(s) covering the Roaringwater Bay AOI and print
        the waterbody code + status class.

If the same waterbody code returns a status in >=3 cycles, we have an official,
repeated, classified series. If not, this route closes too.

Run: python src/epa_cwb_probe.py
"""

import re
import sys
import xml.etree.ElementTree as ET

import requests

OWS = "https://gis.epa.ie/geoserver/EPA/ows"
UA = {"User-Agent": "OceanHackathonCork2026/0.1 (MSc research; kelp valuation)"}

# Roaringwater Bay / Sherkin / Baltimore, WGS84
BBOX = (-9.70, 51.40, -9.25, 51.60)  # minlon, minlat, maxlon, maxlat

# what a coastal-waterbody status layer looks like in the EPA namespace
PATTERN = re.compile(r"(cwb|coastal)", re.I)


def capabilities():
    r = requests.get(OWS, params={"service": "WFS", "version": "2.0.0",
                                  "request": "GetCapabilities"},
                     headers=UA, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    names = [e.text for e in root.iter()
             if e.tag.endswith("}Name") and e.text and ":" in e.text]
    return sorted(set(names))


def get_features(layer):
    """Try 4326 first; fall back to no srsName if the server refuses."""
    base = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": layer, "outputFormat": "application/json", "count": 50}
    attempts = [
        {**base, "srsName": "EPSG:4326",
         "bbox": f"{BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]},EPSG:4326"},
        {**base, "bbox": f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]},EPSG:4326"},
    ]
    for p in attempts:
        try:
            r = requests.get(OWS, params=p, headers=UA, timeout=90)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                return r.json().get("features", [])
        except requests.RequestException as e:
            print(f"    request failed: {e}")
    return None


def main():
    try:
        names = capabilities()
    except Exception as e:
        sys.exit(f"GetCapabilities failed: {e}")

    print(f"{len(names)} layers published by EPA GeoServer\n")
    hits = [n for n in names if PATTERN.search(n)]
    print("=" * 70)
    print(f"COASTAL / CWB LAYERS: {len(hits)}")
    print("=" * 70)
    for n in hits:
        print(" ", n)

    if not hits:
        sys.exit("\nNo coastal layers matched -- widen PATTERN and rerun.")

    print("\n" + "=" * 70)
    print("FEATURES INTERSECTING THE ROARINGWATER BAY BBOX")
    print("=" * 70)
    for layer in hits:
        print(f"\n--- {layer}")
        feats = get_features(layer)
        if feats is None:
            print("    no JSON returned (layer may not support WFS/JSON)")
            continue
        if not feats:
            print("    0 features in bbox")
            continue
        for f in feats:
            p = f.get("properties", {})
            # print only the informative fields
            keep = {k: v for k, v in p.items()
                    if v not in (None, "", " ")
                    and re.search(r"name|code|status|class|cycle|year|risk|wb",
                                  k, re.I)}
            print("   ", keep)


if __name__ == "__main__":
    main()