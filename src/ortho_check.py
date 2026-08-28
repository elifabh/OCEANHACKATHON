#!/usr/bin/env python3
"""
ortho_check.py — image evidence for the flagged receptors.

WHY THIS EXISTS
---------------
Every receptor count in this project rests on an OSM `building` tag, and the
dominant tag is a bare `building=yes`, which says only "a mapper drew a polygon
here". `NOTE_2026-08-28_national_exposure_screen.md` limitation 5 states the
problem plainly: 6 of the 11 low buildings at cluster 596 and all 6 at cluster
1335 are bare `building=yes` with no name and no address, and `yes` is treated
as occupied — the generous reading. If those polygons are sheds, ruins or field
huts, the exposed-receptor count is wrong in the direction that matters.

This script does not answer that question. It PREPARES the evidence for a human
(or an assistant) to answer it: for every requested building it writes an
annotated image chip from two independent orthophoto sources with the OSM
footprint drawn on top, plus a machine-readable manifest with the footprint area,
the tags, and an empty verdict column. The verdicts are then filled in by
inspection and travel with the result.

TWO SOURCES, DELIBERATELY
-------------------------
1. **Copernicus VHR Image Mosaic 2021** (EEA, 2 m RGB). Licence-clean: Copernicus
   open data, redistribution permitted. Coarse — a 10 m house is 5 px — so it
   confirms that a structure exists and roughly how big it is, and little more.
2. **Esri World Imagery** (sub-metre in Ireland). High enough resolution to
   separate a roofed dwelling from a roofless ruin, a caravan or a slab.
   **Licence: Esri/Maxar terms. Used here for INTERNAL VISUAL VERIFICATION ONLY.
   No image, tile or derivative from this source is published, committed, or put
   on the demo map.** Recorded in DEPENDENCIES.md the same way the OPW layer is.

Where the two disagree, the verdict says so. Where only Esri supports a call,
the verdict is labelled as resting on the licence-restricted source, so a reader
knows which claims survive if that source has to be dropped.

WHAT AN IMAGE CAN AND CANNOT SETTLE
-----------------------------------
It can settle: is there a structure; does it have an intact roof; is it a
dwelling-sized building or an outbuilding; is there a vehicle, a track, a garden,
a turf stack. It cannot settle: whether anyone lives there; the date is the
imagery date, not today; a roofed shed and a roofed cottage look similar from
above. Verdicts are therefore recorded on a three-way scale — `dwelling_like`,
`ancillary_or_ruin`, `uncertain` — never as occupancy.

    PYTHONPATH=src python src/ortho_check.py --buildings <csv> --out-dir <dir>

The input CSV needs `osm_id`, `lon`, `lat`; `cluster` and `building` are used
when present. Resumable: a chip already on disk is not re-downloaded.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from PIL import Image, ImageDraw
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wide_receptor_screen import overpass  # noqa: E402  (mirrors + backoff)

REPO = Path(__file__).resolve().parents[1]
UA = "OceanHackathon-Cork2026-research/1.0 (mielmt17@gmail.com)"

# Half-width of a chip in metres. 60 m puts a 10 m house comfortably in frame
# with its plot, its track and its neighbours.
CHIP_HALF_M = 60.0
CHIP_PX = 600                       # 0.2 m/px nominal; the servers resample

ESRI = ("https://services.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/export")
VHR = ("https://image.discomap.eea.europa.eu/arcgis/rest/services/"
       "GioLand/VHR_2021_LAEA/ImageServer/exportImage")

RETRIES = 4
BACKOFF_S = 8.0


def _get_image(url: str, params: dict, dest: Path) -> bool:
    """One image request with backoff. An HTML body means an error page."""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=90,
                             headers={"User-Agent": UA})
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and ct.startswith("image/"):
                dest.write_bytes(r.content)
                return True
            raise RuntimeError(f"HTTP {r.status_code} {ct} {r.text[:120]}")
        except Exception as exc:                            # noqa: BLE001
            if attempt == RETRIES:
                print(f"      image failed after {RETRIES}: "
                      f"{type(exc).__name__}: {str(exc)[:140]}")
                return False
            time.sleep(BACKOFF_S * attempt)
    return False


def fetch_footprints(osm_ids: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Full polygons for the given OSM way ids, via the cached Overpass helper.

    The screens all used `out center`, so only centroids are on disk. The
    outline is what makes a chip readable: without it there is no way to say
    WHICH of three roofs in frame the row refers to.
    """
    ways = [i.split("/", 1)[1] for i in osm_ids if i.startswith("way/")]
    if not ways:
        return {}
    out: dict[str, list[tuple[float, float]]] = {}
    CHUNK = 120
    for i in range(0, len(ways), CHUNK):
        part = ways[i:i + CHUNK]
        q = ("[out:json][timeout:180];\n"
             f"way(id:{','.join(part)});\n"
             "out geom;")
        try:
            payload = overpass(q)
        except Exception as exc:                            # noqa: BLE001
            print(f"    Overpass unavailable for footprints "
                  f"({type(exc).__name__}); chips will carry a marker only")
            continue
        for el in payload.get("elements", []):
            if el.get("type") != "way" or "geometry" not in el:
                continue
            out[f"way/{el['id']}"] = [(p["lon"], p["lat"]) for p in el["geometry"]]
    return out


def polygon_area_m2(ring: list[tuple[float, float]]) -> float:
    """Shoelace in Irish Transverse Mercator — never from lon/lat degrees."""
    if len(ring) < 4:
        return float("nan")
    tr = Transformer.from_crs(4326, 2157, always_xy=True)
    xs, ys = tr.transform([p[0] for p in ring], [p[1] for p in ring])
    a = 0.0
    for i in range(len(xs) - 1):
        a += xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
    return abs(a) / 2.0


def annotate(png: Path, lon: float, lat: float, half_m: float,
             ring: list[tuple[float, float]] | None, label: str,
             crs_epsg: int) -> None:
    """Draw the footprint, a crosshair, a scale bar and a caption on the chip."""
    try:
        im = Image.open(png).convert("RGB")
    except Exception:
        return
    w, h = im.size
    tr = Transformer.from_crs(4326, crs_epsg, always_xy=True)
    cx, cy = tr.transform(lon, lat)
    # Web Mercator: a metre on the ground is 1/cos(lat) map units.
    sf = 1.0 / math.cos(math.radians(lat)) if crs_epsg == 3857 else 1.0
    hm = half_m * sf

    def to_px(x, y):
        return ((x - (cx - hm)) / (2 * hm) * w,
                ((cy + hm) - y) / (2 * hm) * h)

    d = ImageDraw.Draw(im)
    if ring and len(ring) >= 3:
        xs, ys = tr.transform([p[0] for p in ring], [p[1] for p in ring])
        pts = [to_px(x, y) for x, y in zip(xs, ys)]
        d.line(pts + [pts[0]], fill=(255, 235, 0), width=3)
    # crosshair on the recorded point
    d.line([(w / 2 - 16, h / 2), (w / 2 - 5, h / 2)], fill=(255, 60, 60), width=3)
    d.line([(w / 2 + 5, h / 2), (w / 2 + 16, h / 2)], fill=(255, 60, 60), width=3)
    d.line([(w / 2, h / 2 - 16), (w / 2, h / 2 - 5)], fill=(255, 60, 60), width=3)
    d.line([(w / 2, h / 2 + 5), (w / 2, h / 2 + 16)], fill=(255, 60, 60), width=3)
    # 20 m scale bar
    bar = 20.0 / (2 * half_m) * w
    d.rectangle([12, h - 30, 12 + bar, h - 22], fill=(255, 255, 255),
                outline=(0, 0, 0))
    d.text((12, h - 46), "20 m", fill=(255, 255, 255))
    d.rectangle([0, 0, w, 20], fill=(0, 0, 0))
    d.text((6, 5), label[:110], fill=(255, 255, 0))
    im.save(png)


def chip_esri(lon: float, lat: float, dest: Path) -> bool:
    tr = Transformer.from_crs(4326, 3857, always_xy=True)
    x, y = tr.transform(lon, lat)
    half = CHIP_HALF_M / math.cos(math.radians(lat))
    return _get_image(ESRI, {
        "bbox": f"{x-half},{y-half},{x+half},{y+half}", "bboxSR": 3857,
        "imageSR": 3857, "size": f"{CHIP_PX},{CHIP_PX}", "format": "png",
        "f": "image"}, dest)


def chip_vhr(lon: float, lat: float, dest: Path) -> bool:
    tr = Transformer.from_crs(4326, 3035, always_xy=True)
    x, y = tr.transform(lon, lat)
    half = CHIP_HALF_M
    return _get_image(VHR, {
        "bbox": f"{x-half},{y-half},{x+half},{y+half}", "bboxSR": 3035,
        "imageSR": 3035, "size": f"{CHIP_PX},{CHIP_PX}", "format": "png",
        "f": "image"}, dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--buildings", required=True)
    ap.add_argument("--out-dir", default="outputs/exposure_screen/ortho")
    ap.add_argument("--manifest", default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.buildings)
    for c in ("osm_id", "lon", "lat"):
        if c not in df.columns:
            sys.exit(f"ERROR: --buildings needs column {c}")
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir
    (out_dir / "esri").mkdir(parents=True, exist_ok=True)
    (out_dir / "vhr").mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("ORTHOPHOTO CHECK — image evidence for the flagged receptors")
    print("=" * 78)
    print(f"  buildings: {len(df)}")
    print("  Source 1  Copernicus VHR Image Mosaic 2021 (2 m, licence-clean)")
    print("  Source 2  Esri World Imagery (sub-metre, INTERNAL USE ONLY —")
    print("            no image or derivative is published or committed)\n")

    print("  fetching OSM footprints ...")
    rings = fetch_footprints(df.osm_id.astype(str).tolist())
    print(f"  footprints: {len(rings)} of {len(df)}\n")

    rows = []
    for r in df.itertuples():
        oid = str(r.osm_id)
        tag = str(getattr(r, "building", ""))
        cl = getattr(r, "cluster", "")
        stem = oid.replace("/", "_")
        ring = rings.get(oid)
        area = polygon_area_m2(ring) if ring else float("nan")
        lab = (f"cluster {cl} | {oid} | building={tag} | "
               f"{area:.0f} m2" if np.isfinite(area) else
               f"cluster {cl} | {oid} | building={tag}")

        pe = out_dir / "esri" / f"{stem}.png"
        pv = out_dir / "vhr" / f"{stem}.png"
        got_e = pe.exists() or chip_esri(float(r.lon), float(r.lat), pe)
        got_v = pv.exists() or chip_vhr(float(r.lon), float(r.lat), pv)
        if got_e and not (out_dir / "esri" / f".{stem}.done").exists():
            annotate(pe, float(r.lon), float(r.lat), CHIP_HALF_M, ring,
                     "ESRI " + lab, 3857)
            (out_dir / "esri" / f".{stem}.done").write_text("1")
        if got_v and not (out_dir / "vhr" / f".{stem}.done").exists():
            annotate(pv, float(r.lon), float(r.lat), CHIP_HALF_M, ring,
                     "VHR2021 " + lab, 3035)
            (out_dir / "vhr" / f".{stem}.done").write_text("1")
        print(f"   {oid:<18} tag={tag:<8} area={area:7.0f} m2  "
              f"esri={'ok' if got_e else 'FAIL':<4} vhr={'ok' if got_v else 'FAIL'}")
        rows.append({
            "cluster": cl, "osm_id": oid, "building_tag": tag,
            "lon": r.lon, "lat": r.lat,
            "footprint_m2": round(area, 1) if np.isfinite(area) else None,
            "footprint_from_osm": bool(ring),
            "chip_esri": str(pe.relative_to(REPO)).replace("\\", "/") if got_e else "",
            "chip_vhr": str(pv.relative_to(REPO)).replace("\\", "/") if got_v else "",
            # filled in by inspection:
            "verdict": "", "verdict_basis": "", "notes": "",
        })

    man = Path(args.manifest or (out_dir / "ortho_manifest.csv"))
    pd.DataFrame(rows).to_csv(man, index=False)
    print(f"\nWrote {man}")
    print(f"Chips in {out_dir}/esri and {out_dir}/vhr")
    print("Verdict vocabulary: dwelling_like | ancillary_or_ruin | uncertain")
    print("An image cannot establish occupancy. Do not record one.")
    print(f"Run finished {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
