"""
band_panels.py -- Ocean Hackathon Cork 2026, "Seeing the Invisible Shield"
Step 3 of the kelp detection feasibility test: SURFACE vs BOTTOM DISCRIMINATION.

THE QUESTION
------------
An RGB preview cannot tell a bright shallow seabed from bright turbid water, and
cannot tell in-water structure from surface texture. Physics can. Water absorbs
near-infrared almost completely within centimetres, so:

  structure in B8 (833 nm)          -> SURFACE: waves, glint, foam, floating matter
  structure in B2/B3, fading in B4  -> BOTTOM:  red attenuates first with depth
  uniform brightness in every band  -> TURBID WATER or haze

This is the same physical argument behind Wilson et al. (2020, Front. Environ.
Sci. 8:579856) excluding the NIR band from their submerged-habitat classifier:
strong water absorption at that wavelength injects noise everywhere except the
shallowest water.

STRETCH CHOICE -- read this before interpreting the output
----------------------------------------------------------
Each band is stretched to its OWN 2nd-98th percentile over water pixels, not to
a shared scale. A shared scale would render B8 flat black and answer nothing;
the question is whether B8 contains PATTERN, not whether it is bright. The cost
is that sensor noise in B8 is stretched too. So judge coherent spatial structure
(streaks, ripple trains, wave fronts) as real, and fine random speckle as noise.

OUTPUT
------
outputs/bands/<aoi>__<date>__bands.png   (2x2 panel: B2, B3, B4, B8)
"""

from __future__ import annotations

import io
import os
import sys

import ee
import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont

EE_PROJECT = "gen-lang-client-0871366385"   # same ID as the other scripts

IN_CSV = "outputs/candidate_scenes.csv"
OUT_DIR = "outputs/bands"
TILE_WIDTH = 620          # pixels per panel
MIN_DATA_COVERAGE = 0.95

BANDS = [
    ("B2", "B2 blue 490nm  - deepest water penetration"),
    ("B3", "B3 green 560nm - good penetration, kelp signal"),
    ("B4", "B4 red 665nm   - shallow only, dies fast with depth"),
    ("B8", "B8 NIR 833nm   - SURFACE ONLY: any pattern here is not seabed"),
]

# Must match AOIS in scene_selection.py.
AOIS = {
    "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
    "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
    "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
}


def data_coverage(img: ee.Image, geom: ee.Geometry) -> float:
    return img.select("B3").mask().rename("d").reduceRegion(
        reducer=ee.Reducer.mean(), geometry=geom, scale=20,
        maxPixels=1e9, bestEffort=True,
    ).get("d").getInfo()


def band_png(img: ee.Image, geom: ee.Geometry, band: str) -> Image.Image:
    """One band, greyscale, stretched to its own 2-98 percentile over water."""
    water = img.normalizedDifference(["B3", "B8"]).gt(0)
    masked = img.select(band).updateMask(water)
    pct = masked.reduceRegion(
        reducer=ee.Reducer.percentile([2, 98]), geometry=geom, scale=20,
        maxPixels=1e9, bestEffort=True,
    ).getInfo()

    lo, hi = pct.get(f"{band}_p2"), pct.get(f"{band}_p98")
    if lo is None or hi is None or hi <= lo:
        lo, hi = 0, 1500

    vis = img.select(band).visualize(min=lo, max=hi, palette=["000000", "ffffff"])
    grey = ee.Image.constant([60, 60, 60]).toUint8().rename(vis.bandNames())
    out = vis.where(water.Not(), grey)

    url = out.getThumbURL(
        {"region": geom, "dimensions": TILE_WIDTH, "format": "png"}
    )
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def _font(size: int = 15) -> ImageFont.ImageFont:
    for path in (
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def build_panel(tiles: list[tuple[str, Image.Image]], title: str) -> Image.Image:
    """2x2 grid with a caption strip under each tile and a title bar on top."""
    w, h = tiles[0][1].size
    bar, top = 26, 30
    canvas = Image.new("RGB", (w * 2, top + (h + bar) * 2), "white")
    draw = ImageDraw.Draw(canvas)
    f_small, f_title = _font(14), _font(17)

    draw.text((8, 7), title, fill="black", font=f_title)
    for i, (label, im) in enumerate(tiles):
        x, y = (i % 2) * w, top + (i // 2) * (h + bar)
        canvas.paste(im, (x, y))
        draw.rectangle([x, y + h, x + w, y + h + bar], fill="white")
        draw.text((x + 6, y + h + 6), label, fill="black", font=f_small)
    return canvas


def main() -> None:
    ee.Initialize(project=EE_PROJECT)
    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_csv(IN_CSV)

    for aoi, bbox in AOIS.items():
        rows = df[df["aoi"] == aoi]
        if rows.empty:
            print(f"{aoi}: no scenes in {IN_CSV} -- skipped", file=sys.stderr)
            continue

        geom = ee.Geometry.Rectangle(bbox)
        picked = None
        for _, row in rows.iterrows():              # first scene that fully covers the AOI
            img = ee.Image(f"COPERNICUS/S2_HARMONIZED/{row['scene_id']}")
            if data_coverage(img, geom) >= MIN_DATA_COVERAGE:
                picked = (row, img)
                break
        if picked is None:
            print(f"{aoi}: no scene fully covers the AOI -- skipped", file=sys.stderr)
            continue

        row, img = picked
        date = str(row["datetime_utc"])[:10]
        print(f"{aoi}  {date}  tide={row.get('wl_union_hall_harbor')} m", file=sys.stderr)

        try:
            tiles = [(label, band_png(img, geom, band)) for band, label in BANDS]
        except (ee.EEException, requests.RequestException) as exc:
            print(f"  FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        title = (f"{aoi}   {date}   tide {row.get('wl_union_hall_harbor')} m LAT"
                 f"   sun {row.get('sun_elev_deg'):.0f} deg")
        out = os.path.join(OUT_DIR, f"{aoi}__{date}__bands.png")
        build_panel(tiles, title).save(out)
        print(f"  wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()