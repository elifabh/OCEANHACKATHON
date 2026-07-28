#!/usr/bin/env python3
"""
common.py - single source of truth for the Ocean Hackathon Cork 2026 kelp prototype.

WHY THIS FILE EXISTS
AOIS, EE_PROJECT and data_coverage() were duplicated across scene_selection.py,
make_thumbnails.py and band_panels.py. That duplication already produced one
silent wrong result (a scene with 1% AOI coverage was reported as "100% water,
no land"). Three copies are not maintainable in a 48-hour hackathon. Import
from here; do not copy.

STATUS 2026-07-28. Build step 1 of 7 (the INFOMAR backscatter probe) has been
RUN LIVE against all three AOIs. Several comments in the previous version of
this file were written before that run and were falsified by it. They have been
corrected in place and the correction is noted at each site, because a stale
comment in a single-source-of-truth file is worse than no comment: it is a
confident wrong answer that the next session will believe.

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

# Expected wave-exposure ordering across the three AOIs. This is a PREDICTION
# from coastal geometry, not a measurement: mizen_outer faces the open Atlantic,
# sherkin_baltimore is partly screened by Sherkin and Cape Clear, and
# inner_roaringwater sits behind the island chain. Any exposure layer we adopt
# must reproduce this ordering, otherwise the layer is wrong or misprojected.
# It is also the negative control for the step 2 suitability model.
EXPECTED_EXPOSURE_ORDER = ("mizen_outer", "sherkin_baltimore", "inner_roaringwater")

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
# Projected CRSs for AREA and DISTANCE work
#
# Never compute an area in EPSG:4326 (degrees are not metres) and never trust
# an area computed in EPSG:3857 (see mercator_area_inflation below).
# ---------------------------------------------------------------------------
CRS_ITM = 2157        # IRENET95 / Irish Transverse Mercator. National standard.
CRS_UTM29N = 32629    # WGS84 / UTM zone 29N. Zone 29 spans 12W-6W: West Cork.
CRS_LAEA_EUROPE = 3035  # ETRS89-extended / LAEA Europe. Genuinely EQUAL-AREA.

# Which to use for areas: ITM and UTM are Transverse Mercator, i.e. conformal,
# NOT equal-area. Over an AOI a few km across the area error is well under
# 0.1%, so either is fine in practice and ITM is the one an Irish reviewer
# expects. EPSG:3035 is the pedantically correct choice if anyone challenges
# the area figure. State whichever you used on the slide.
CRS_FOR_AREA = CRS_ITM

# ---------------------------------------------------------------------------
# INFOMAR / GSI ArcGIS REST endpoints
#
# STATUS 2026-07-27, from the live probe run (src/infomar_backscatter.py).
#
# CORRECTION. The previous version of this file said the endpoint
# "INFOMAR/AllSurvey_Backscatter" "could NOT be confirmed to exist". THAT WAS
# WRONG. It does exist and it responds. The doubt came from its absence in web
# search results, which is not evidence about a server. The original URL was
# correct all along. Recorded here so the mistake is not repeated: absence from
# a search index is not absence from the internet - probe the endpoint.
#
# The bathymetry endpoint is confirmed live: Band Count 1, Pixel Type F32,
# min -4904.0 m, max +62.2 m, i.e. a real elevation surface in metres,
# vertical datum LAT (confirmed twice: survey report ROS_GEO19_04_FINAL, and
# the GSI service declaring VCS 5861).
# ---------------------------------------------------------------------------
INFOMAR_BATHY = (
    "https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer"
)

# CONFIRMED AND SELECTED. Geological Survey Ireland image host, 10 m inshore
# backscatter, WGS84 horizontal (EPSG:4326) and LAT vertical (VCSWkid 5861).
# Published on data.gov.ie under CC BY 4.0. The probe picks this one because
# it is the only candidate already in lon/lat with a LAT vertical CRS.
#
# PROPERTY 1 - WHAT THE PIXELS ARE. Band Count 3, Pixel Type U8, Service Data
# Type esriImageServiceDataTypeRGB, Min 0 / Max 255 on every band. This is a
# RENDERED GREYSCALE IMAGE, NOT calibrated decibels. Permitted pitch wording:
# "relative acoustic hardness proxy derived from a rendered national mosaic".
# Forbidden: "calibrated backscatter in dB".
#
# PROPERTY 2 - IT CANNOT SEPARATE HARD FROM SOFT. Proven 27 Jul across all
# three AOIs: DN medians in every depth band sit in a narrow 64-110 range with
# overlapping IQRs on a single-moded histogram. No bimodality, so any threshold
# would be arbitrary. AOI means differ (93.4 / 73.7 / 94.7) and the
# depth-hardness relationship REVERSES between AOIs, which is the signature of
# per-survey contrast stretching, not of physical hardness. Absolute DN is
# therefore NOT comparable across surveys. The negative control also fails on
# it: inner_roaringwater is indistinguishable from sherkin's shallow bands.
#
# CONSEQUENCE FOR STEP 2. This service is demoted to an OPTIONAL covariate,
# usable as TEXTURE only (e.g. GLCM), never as absolute DN. The primary
# substrate source is INFOMAR_SEDIMENT below. Render seams and nadir lines are
# a named artefact risk for any texture measure.
#
# PROPERTY 3 - POLARITY IS STILL UNVALIDATED. The GSI service description says
# DARK / low DN = HARD (rock, gravel), LIGHT / high DN = SOFT (sand, silt,
# mud). That is documentation, not measurement. It has NOT been checked against
# a known reef and a known sandy bay. Getting this sign backwards would
# silently invert a suitability model. Validate before relying on it.
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

# CONFIRMED 2026-07-27. Formerly named INFOMAR_BACKSCATTER_UNVERIFIED on the
# mistaken belief that it did not exist. It does. Kept third in the candidate
# list only because the GSI service has the better spatial reference, not
# because there is anything wrong with this one.
INFOMAR_BACKSCATTER_MI_ALLSURVEY = (
    "https://image.marine.ie/arcgis/rest/services/INFOMAR/"
    "AllSurvey_Backscatter/ImageServer"
)

# Back-compatibility alias. Any older script still importing the old name keeps
# working. Do not use it in new code - the name is now factually wrong.
INFOMAR_BACKSCATTER_UNVERIFIED = INFOMAR_BACKSCATTER_MI_ALLSURVEY

# Ordered by preference. infomar_backscatter.py walks this list and uses the
# first endpoint whose metadata request succeeds.
BACKSCATTER_CANDIDATES: list[tuple[str, str]] = [
    ("gsi_10m_inshore", INFOMAR_BACKSCATTER_GSI_10M),
    ("mi_5m_all", INFOMAR_BACKSCATTER_MI_5M),
    ("mi_allsurvey_backscatter", INFOMAR_BACKSCATTER_MI_ALLSURVEY),
]

INFOMAR_COVERAGE = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "SurveyCoverageViewer/MapServer"
)

# INFOMAR Seabed Substrate: the INTERPRETED substrate product, and after the
# step 1 probe the PRIMARY substrate source for the suitability model.
#
# It is an official INFOMAR interpretation: acoustic classes extracted from
# backscatter by segmentation, isoclustering and manual tracing, classified
# into a modified Folk scheme using physical sediment samples, with rock
# outcrops manually digitised from shaded relief. Defensible to a jury in a way
# that a threshold we invent on a rendered greyscale image is not.
#
# CORRECTION. The previous comment here said "Class is in the INF_Class field".
# THERE IS NO INF_Class FIELD. That guess made an early version of the probe
# report every polygon as UNCLASSED and print a false "no rock found"
# conclusion. The real published schema is INFOMAR_SEDIMENT_FIELDS below. Read
# the schema, never guess a field name.
#
# It DOES discriminate the AOIs where the backscatter render did not:
# sherkin_baltimore 16 Rock polygons of 50; inner_roaringwater 2 of 11
# (plus 5 unclassified).
INFOMAR_SEDIMENT = (
    "https://maps.marine.ie/arcgis/rest/services/Infomar/"
    "INFOMAR_Seabed_Folk/MapServer"
)
INFOMAR_SEDIMENT_LAYER = 0

# Fields actually published by the layer, read from its schema on 2026-07-27.
INFOMAR_SEDIMENT_FIELDS = (
    "Biozone", "Substrate", "Folk_5", "EUNIS", "MSFD_BBHT",
    "Source", "Resolution", "Shape_Area",
)

# Substrate values observed in the three AOIs. Not guaranteed exhaustive
# nationally - re-read the distinct values if the AOIs change.
SUBSTRATE_VALUES_SEEN = (
    "Rock", "Coarse sediment", "Sand", "sandy Mud/muddy Sand",
    "Unclassified substrate",
)
SUBSTRATE_HARD = "Rock"

# Biozone values are NOT yet known. Pulling the distinct list is an open task
# for step 2, and it is a gating one: the target habitat definition is
# Substrate = Rock AND Biozone = infralittoral, i.e. EUNIS A3, which EUNIS
# bounds above by the top of the kelp zone and below by the lower limit of kelp
# growth. If Biozone carries no infralittoral class, the depth band has to come
# from light attenuation instead, which needs a local Kd estimate and is a much
# bigger job. Do not hard-code a guessed string here.
BIOZONE_VALUES_SEEN: tuple[str, ...] = ()

# WARNING - Shape_Area. The MapServer reports SR 102100/3857 (Web Mercator),
# which inflates area by 1/cos^2(latitude), about 2.6x at 51.5 N. Shape_Area as
# delivered would overstate the habitat area 2.6x and the euro figure with it.
# Do not scale it: re-project the geometry and recompute the area in
# CRS_FOR_AREA. Scaling assumes the whole polygon sits at one latitude, and it
# hides the assumption inside a magic number.
INFOMAR_SEDIMENT_AREA_IS_MERCATOR = True

# EUSeaMap-derived MSFD broad benthic habitat types for Ireland (2019).
#
# NOT AN INDEPENDENT CHECK. EUSeaMap is built by combining EMODnet bathymetry,
# EMODnet Geology substrate and modelled environmental variables, and the
# substrate layer is the base layer of that model; Ireland's contribution to
# EMODnet Geology is INFOMAR's own seabed substrate data (Guinan et al. 2021,
# Quarterly Journal of Engineering Geology and Hydrogeology 54(1),
# doi 10.1144/qjegh2020-033). So validating an INFOMAR-based model against
# EUSeaMap is close to circular. Use it as a coarse sanity check and say so;
# for external validation prefer NPWS Annex I reef polygons and the published
# dive literature, and note that those are not fully independent either.
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

    THE EMPTY-BATCH RULE - PROVEN 2026-07-27, APPLIES TO ALL CALLERS.
    An INFOMAR getSamples request whose points ALL fall outside raster coverage
    returns HTTP 400 "Invalid or missing input parameters" instead of an empty
    samples list. One single point inside coverage is enough for the same
    request to succeed. Controlled test (empty_batch_test.py):

        100 points, all outside coverage      -> FAIL (with and without
                                                 any mosaicRule)
        50 outside + 50 inside                -> OK, 35 samples
        100 points, all inside coverage       -> OK, 72 samples

    This is a SERVER-SIDE BUG, not a malformed request on our side, and the
    earlier hypothesis blaming the mosaicRule where-clause "Category = 1" is
    DISPROVEN - the all-outside case fails without any mosaicRule at all.

    So: never send a batch that could be entirely outside coverage. Send the
    whole AOI in one request, or catch the 400 and treat it as zero samples.
    The old infomar_coverage.py sent 100-point batches over a 50x50 grid, which
    made whole northern rows into all-empty requests - that, and nothing more
    exotic, was the inner_roaringwater 400.

    Reproducible coordinates for the bug report to data@infomar.ie:
    lon -9.5192 to -9.4408, lat 51.5345 to 51.5395.
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


def mercator_area_inflation(lat_deg: float) -> float:
    """Factor by which EPSG:3857 overstates ground area at a given latitude.

    Web Mercator is conformal, so it stretches BOTH axes by 1/cos(lat), and
    area therefore by 1/cos^2(lat). At 51.5 N that is about 2.58.

    THIS IS THE HIGHEST-CONSEQUENCE NUMBER IN THE PROJECT. It multiplies the
    habitat area, and the habitat area multiplies the euro figure. An
    uncorrected Shape_Area from the Seabed Substrate MapServer overstates the
    coastal-protection value by a factor of ~2.6.

    Approximate, deliberately: EPSG:3857 applies spherical formulae to
    ellipsoidal latitudes, worth roughly another 1% at this latitude. Use this
    function to SANITY-CHECK an area, not to correct one. To correct one,
    re-project the geometry into CRS_FOR_AREA and recompute - that carries no
    single-latitude assumption.
    """
    return 1.0 / (math.cos(math.radians(lat_deg)) ** 2)


def mercator_area_to_true_km2(area_3857_m2: float, lat_deg: float) -> float:
    """Rough true area in km2 from a Web Mercator Shape_Area, for sanity checks.

    See mercator_area_inflation for why this is a check and not a correction.
    """
    return (area_3857_m2 / mercator_area_inflation(lat_deg)) / 1.0e6


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
    # Licence NOT yet read off the figshare record. Fill this in from the
    # dataset page before the layer is used in anything published, and add it
    # to DEPENDENCIES.md. Do not assume CC BY.
    "WAVE_FETCH": (
        "Wave fetch layer: Burrows, M.T., figshare. Method after Burrows et al. "
        "(2008) Marine Ecology Progress Series 353:1-12 and Burrows (2012). "
        "LICENCE UNVERIFIED - check the figshare record before publishing."
    ),
}