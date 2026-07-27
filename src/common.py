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

import json
import math
import time

import requests

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
EE_PROJECT = "gen-lang-client-0871366385"

# ---------------------------------------------------------------------------
# INFOMAR / GSI ArcGIS REST endpoints
#
# STATUS 2026-07-27. The bathymetry endpoint below is confirmed live: its
# service metadata reports Band Count 1, Pixel Type F32, min -4904.0 m,
# max +62.2 m, which is a real elevation surface.
#
# The backscatter endpoint that was previously in this file
# ("INFOMAR/AllSurvey_Backscatter") could NOT be confirmed to exist. It is kept
# in BACKSCATTER_CANDIDATES so infomar_backscatter.py can settle the question
# empirically instead of by assumption. Two alternatives ARE confirmed to exist
# and are listed first.
# ---------------------------------------------------------------------------
INFOMAR_BATHY = (
    "https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer"
)

# CONFIRMED. Geological Survey Ireland image host, 10 m inshore backscatter,
# WGS84 horizontal (EPSG:4326) and LAT vertical (VCSWkid 5861). This is the
# service published on data.gov.ie under CC BY 4.0.
#
# CRITICAL PROPERTY: Band Count 3, Pixel Type U8, Service Data Type
# esriImageServiceDataTypeRGB, Min 0 / Max 255 / Mean 77.8 / StdDev 21.3 on
# every band. That is a RENDERED GREYSCALE IMAGE, not calibrated decibels.
# The service description states the polarity explicitly: DARKER = HARD seabed
# (rock, gravel), LIGHTER = SOFT seabed (sand, silt, mud). So low digital
# number = hard substrate = candidate Laminaria hyperborea ground.
# Getting this sign backwards would invert the entire suitability model.
INFOMAR_BACKSCATTER_GSI_10M = (
    "https://gsi.geodata.gov.ie/imagehost/rest/services/Marine/"
    "IE_GSI_MI_Backscatter_10m_Inshore_IE_WGS84_LAT_TIFF/ImageServer"
)

# CONFIRMED. Marine Institute mirror, 5 m pixel, 4 bands U8, EPSG:3395.
# Also a rendered product. Backup only: the fourth band is probably alpha and
# the spatial reference is World Mercator, which complicates lon/lat joins.
INFOMAR_BACKSCATTER_MI_5M = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "All_Backscatter/ImageServer"
)

# UNVERIFIED. Previous value of INFOMAR_BACKSCATTER. Retained only so the probe
# can prove or disprove it. Do not import this directly.
INFOMAR_BACKSCATTER_UNVERIFIED = (
    "https://image.marine.ie/arcgis/rest/services/INFOMAR/"
    "AllSurvey_Backscatter/ImageServer"
)

# Ordered by preference. infomar_backscatter.py walks this list and uses the
# first endpoint whose metadata request succeeds.
BACKSCATTER_CANDIDATES: list[tuple[str, str]] = [
    ("gsi_10m_inshore", INFOMAR_BACKSCATTER_GSI_10M),
    ("mi_5m_all", INFOMAR_BACKSCATTER_MI_5M),
    ("unverified_allsurvey_backscatter", INFOMAR_BACKSCATTER_UNVERIFIED),
]

INFOMAR_COVERAGE = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "SurveyCoverageViewer/MapServer"
)

# INFOMAR Seabed Folk: the INTERPRETED substrate product. Acoustic classes were
# extracted from the backscatter data (image segmentation, isoclustering, manual
# tracing), then classified into a modified Folk scheme using physical sediment
# samples; rock outcrops were manually digitised from shaded relief. Class is in
# the INF_Class field. For "is this hard ground", this official interpretation
# is more defensible in a pitch than any threshold we invent on a rendered
# greyscale image - use backscatter as the continuous covariate and this as the
# categorical check.
INFOMAR_SEDIMENT = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "INFOMAR_Seabed_Folk/MapServer"
)
INFOMAR_SEDIMENT_LAYER = 0

# EUSeaMap-derived MSFD broad benthic habitat types for Ireland (2019).
# Broad-scale and coarse - a sanity check on the substrate call, not evidence.
INFOMAR_BBHT = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "INFOMAR_BroadBenthicHabitats/MapServer"
)

# Mosaic item categories as published in the ImageServer metadata
CATEGORY_PRIMARY = 1
CATEGORY_OVERVIEW = 2

# Finest pixel size served by the "Inshore" primary mosaic, in EPSG:3857 metres
INFOMAR_INSHORE_LOWPS_3857 = 6.7826965740341585

# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OceanHackathonCork2026/kelp-prototype"})
HTTP_TIMEOUT = 90


class ArcGISError(RuntimeError):
    """An ArcGIS REST request that failed, with the server's own words kept.

    The previous helper called resp.raise_for_status() before touching
    resp.text. ArcGIS puts its actual diagnosis in the body of a 400 - fields
    that do not exist, mosaic rules the service does not allow, geometries it
    cannot project. Throwing the body away is what turned the
    inner_roaringwater 400 into "cause unknown".
    """

    def __init__(self, url: str, status: int | None, message: str,
                 details: list[str] | None = None, body: str = ""):
        self.url = url
        self.status = status
        self.message = message
        self.details = details or []
        self.body = body
        text = f"HTTP {status} from {url}: {message}"
        if self.details:
            text += " | details: " + "; ".join(str(d) for d in self.details)
        super().__init__(text)


def _extract_error(url: str, resp: requests.Response) -> ArcGISError:
    """Turn any ArcGIS failure into an ArcGISError that says something useful."""
    body = resp.text[:2000]
    message, details = "no message in body", []
    try:
        payload = resp.json()
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = err.get("message", message)
        details = err.get("details", [])
    except ValueError:
        message = f"non-JSON body: {body[:300]}"
    return ArcGISError(url, resp.status_code, message, details, body)


def arcgis_request(url: str, params: dict | None = None, method: str = "POST",
                   retries: int = 3, pause: float = 1.5) -> dict:
    """Call an ArcGIS REST endpoint and return parsed JSON, or raise ArcGISError.

    Two deliberate behaviours:

    1. A 4xx is NEVER retried. A 400 is a deterministic statement that the
       request was malformed; sending it twice more only wastes time and hides
       the message. Only timeouts, connection errors and 5xx are retried.
    2. On any failure the response body is parsed for the ArcGIS error message
       and details, and carried on the exception.
    """
    params = dict(params or {})
    params.setdefault("f", "json")
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            if method.upper() == "GET":
                resp = SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
            else:
                resp = SESSION.post(url, data=params, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:      # transport-level only
            last_exc = exc
            if attempt < retries:
                time.sleep(pause * attempt)
                continue
            raise ArcGISError(url, None, f"transport failure: {exc}") from exc

        if 400 <= resp.status_code < 500:
            raise _extract_error(url, resp)           # deterministic: no retry

        if resp.status_code >= 500:
            last_exc = _extract_error(url, resp)
            if attempt < retries:
                time.sleep(pause * attempt)
                continue
            raise last_exc

        try:
            payload = resp.json()
        except ValueError:
            raise ArcGISError(
                url, resp.status_code, "HTTP 200 but body was not JSON",
                body=resp.text[:2000],
            )

        # ArcGIS habitually returns HTTP 200 with an error object inside.
        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            raise ArcGISError(
                url, err.get("code"), err.get("message", "unspecified"),
                err.get("details", []), json.dumps(err)[:2000],
            )
        return payload

    raise ArcGISError(url, None, f"exhausted retries: {last_exc}")


def service_metadata(url: str) -> dict:
    """Fetch an ArcGIS service description. Cheap liveness + capability probe."""
    return arcgis_request(url, {"f": "json"}, method="GET")


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


def aoi_area_km2(bbox: list[float]) -> float:
    """Approximate bbox area in km2 on a sphere at the bbox mid-latitude."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lat_mid = math.radians((lat_min + lat_max) / 2.0)
    width_km = (lon_max - lon_min) * 111.320 * math.cos(lat_mid)
    height_km = (lat_max - lat_min) * 110.574
    return width_km * height_km


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