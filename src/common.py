#!/usr/bin/env python3
"""
common.py - single source of truth for the Ocean Hackathon Cork 2026 kelp prototype.

WHY THIS FILE EXISTS
AOIS, EE_PROJECT and data_coverage() were duplicated across scene_selection.py,
make_thumbnails.py and band_panels.py. That duplication already produced one
silent wrong result (a scene with 1% AOI coverage was reported as "100% water,
no land"). Three copies are not maintainable in a 48-hour hackathon. Import
from here; do not copy.

Attribution obligations for anything published from this project are listed at
the bottom of this file.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Areas of interest - WGS84, [lon_min, lat_min, lon_max, lat_max]
# ---------------------------------------------------------------------------
AOIS: dict[str, list[float]] = {
    # PRIMARY. Roaringwater Bay and Islands SAC (site code 000101),
    # Annex I Reefs [1170]. Exposed shores here carry Laminaria hyperborea.
    "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],

    # Exposed-coast comparison. Clearest water, but previews show persistent
    # surface roughness. Tension to state in the pitch: L. hyperborea prefers
    # exposed coasts, and exposed coasts are the hardest places to see optically.
    "mizen_outer": [-9.86, 51.44, -9.74, 51.52],

    # Turbid negative control. Sheltered inner bay. MERC (2007) NPWS subtidal
    # survey records Saccharina latissima / Saccorhiza polyschides here, NOT
    # L. hyperborea - so the Norwegian wave-attenuation coefficients must not
    # be applied to vegetation pixels detected in this box.
    "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
}

PRIMARY_AOI = "sherkin_baltimore"

# ---------------------------------------------------------------------------
# Sentinel-2 context - empirically established, do not re-derive
# ---------------------------------------------------------------------------
S2_TILE = "T29UMT"
S2_OVERPASS_UTC = "11:54"          # match against West Cork tide tables
BEST_SCENE_DATE = "2021-05-28"     # tide 0.27 m LAT, solar elevation 59 deg
USABLE_MONTHS = (5, 6, 7, 8)       # May-Aug: irradiance, not geometry, is limiting

# ---------------------------------------------------------------------------
# Google Earth Engine
# ---------------------------------------------------------------------------
# TODO: paste your Cloud project id here, then delete the copies in the three
# existing scripts and import EE_PROJECT from this module instead.
EE_PROJECT = "gen-lang-client-0871366385"

# ---------------------------------------------------------------------------
# INFOMAR ArcGIS REST endpoints
# Source: https://www.infomar.ie/services  (checked 2026-07-24)
# ---------------------------------------------------------------------------
INFOMAR_BATHY = (
    "https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer"
)
INFOMAR_BACKSCATTER = (
    "https://image.marine.ie/arcgis/rest/services/INFOMAR/"
    "AllSurvey_Backscatter/ImageServer"
)
INFOMAR_COVERAGE = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "SurveyCoverageViewer/MapServer"
)
INFOMAR_SEDIMENT = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "INFOMAR_Seabed_Folk/MapServer"
)

# Mosaic item categories as published in the ImageServer metadata
CATEGORY_PRIMARY = 1
CATEGORY_OVERVIEW = 2

# Finest pixel size served by the "Inshore" primary mosaic, in EPSG:3857 metres
INFOMAR_INSHORE_LOWPS_3857 = 6.7826965740341585

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def webmercator_px_to_ground_m(px_size_3857: float, lat_deg: float) -> float:
    """Convert an EPSG:3857 pixel size to true ground metres at a latitude.

    Web Mercator inflates distances by 1/cos(lat). At 51.5 N the INFOMAR
    Inshore pixel of 6.78 Mercator-metres is about 4.2 ground-metres.
    """
    return px_size_3857 * math.cos(math.radians(lat_deg))


def aoi_centre(bbox: list[float]) -> tuple[float, float]:
    """Return (lon, lat) of the bbox centre."""
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def grid_points(bbox: list[float], nx: int = 20, ny: int = 20) -> list[list[float]]:
    """Cell-centred regular lon/lat grid inside a bbox."""
    xmin, ymin, xmax, ymax = bbox
    dx = (xmax - xmin) / nx
    dy = (ymax - ymin) / ny
    return [
        [xmin + (i + 0.5) * dx, ymin + (j + 0.5) * dy]
        for j in range(ny)
        for i in range(nx)
    ]


def chunked(seq, size: int):
    """Yield successive chunks of `size` from `seq`."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ---------------------------------------------------------------------------
# MIGRATION SLOT - do not leave this empty
# ---------------------------------------------------------------------------
# Paste your existing data_coverage() implementation below, verbatim, then
# delete it from scene_selection.py, make_thumbnails.py and band_panels.py and
# replace with:  from common import AOIS, EE_PROJECT, data_coverage
#
# def data_coverage(...):
#     ...


# ---------------------------------------------------------------------------
# Attribution - required in the prototype UI, the slides and DEPENDENCIES.md
# ---------------------------------------------------------------------------
ATTRIBUTION = {
    "INFOMAR": (
        "Contains Irish Public Sector Data (Geological Survey Ireland & Marine "
        "Institute) licensed under a Creative Commons Attribution 4.0 "
        "International (CC BY 4.0) licence."
    ),
    "TIDE_GAUGE": (
        "Irish National Tide Gauge Network, Marine Institute, via ERDDAP. "
        "CC BY 4.0."
    ),
    "SENTINEL2": (
        "Contains modified Copernicus Sentinel data. Processed by the authors."
    ),
}