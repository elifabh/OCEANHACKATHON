#!/usr/bin/env python3
"""
france_data.py -- cached, resumable data acquisition for the Iroise Sea site.

WHY THIS SITE EXISTS AT ALL
---------------------------
The coastal-protection euro row closed at "not computable" at every Irish
site, for one reason that is physical and not fixable by more data: the only
published L. hyperborea wave-attenuation coefficients (Dubi & Torum 1996;
Mork 1996; Lovas & Torum 2001) were measured at 4-10 m depth, and the Irish
beds this project can see sit either at 0.8 m or at 12-17 m. A coefficient
used outside its validity range is not a smaller result, it is a different
claim, so the chain was stopped rather than extrapolated.

A commissioned literature review identified one site where all three
conditions hold at once -- surveyed L. hyperborea, a bed whose core sits
inside 4-10 m, and built receptors landward:

    Molene Archipelago / Iroise Sea, Brittany, France
    Receptor town: Le Conquet (48.36 N, 4.77 W)

This module fetches that site's own data. It computes nothing. Every euro,
every percentage and every hectare is produced by france_chain.py from what
lands here.

THE LICENCE CHECK CAME FIRST, AND IT CHANGED THE PLAN
-----------------------------------------------------
The brief named the Ifremer/Sextant kelp dataset (Bajjouk et al. 2015,
DOI 10.12770/4adbe32a-8c81-4c18-8da3-4c361889820c) and instructed that its
licence be verified before anything else, substituting the EMODnet Seabed
Habitats layer if it was not openly re-usable.

It is not. Measured 2026-08-28 from the record's own ISO 19115-3 XML:

    resourceConstraints: "Creative Commons license to apply :
    Attribution + Non Commercial + No Derivs (BY-NC-ND)"

No-Derivatives forbids exactly what this chain does to a habitat layer --
intersect it with a depth band, rasterise it, and publish the result on a
map. Non-Commercial is a second, independent bar. This is the same licence
class as the OPW flood maps, which CLAUDE.md rule 9 already keeps off every
published map in this project. So the Sextant layer is NOT downloaded, NOT
cached and NOT derived from, and the EMODnet substitute is used instead:

    emodnet_open:macroalgae_eov_poly_2025
    "Available under the Creative Commons Attribution (CC-BY) License v4.0"
    (verified 2026-08-28 from the ICES GeoNetwork record 913a0ee4-...)

The substitute is not a lesser copy of the same thing and the difference is
recorded rather than glossed: its Molene polygons carry
map_id "OSPARHab2022FRv1", source "OFFICE FRANCAIS DE LA BIODIVERSITE",
determiner "DYNECO/BENTHOS" and det_date 2015-01-01. DYNECO/BENTHOS is
Ifremer's benthic ecology laboratory and 2015 is Bajjouk's year, so this is
very likely the same survey programme reaching us through the OSPAR habitat
submission rather than through Sextant. That is a provenance statement, not
a licence loophole: what is re-used here is the CC-BY-4.0 OSPAR/EMODnet
distribution, and only that.

A second correction the licence check turned up: the brief describes the
Sextant dataset as SURVEYED L. hyperborea. Its own abstract says otherwise --
"a habitat suitability model is fitted for each species on some carefully
selected field stations ... Predictive maps are produced". It is a modelled
predictive map anchored on survey stations, like this project's own step-2
model. Recorded so the France result is never described as more directly
observed than the Irish one.

WHAT EACH SOURCE IS, AND WHAT IT COST
-------------------------------------
kelp        EMODnet Seabed Habitats macroalgae EOV polygons 2025, CC-BY-4.0.
            L. hyperborea polygons only; L. digitata is excluded at source
            because it sits at 0-3 m, outside the coefficient band.
bathymetry  EMODnet Bathymetry DTM (emodnet:mean), CC-BY-4.0, 1/16 arcmin
            (~77 m E-W x ~116 m N-S at 48.4 N).
            NOT Litto3D, and that is a real downgrade. See LITTO3D_STATUS.
receptors   IGN BD TOPO v3 via the Geoplateforme WFS, Licence Ouverte Etalab
            2.0. Buildings, linear constructions (dikes/sea walls), and
            transport equipment (the ferry terminal and its car park).
land level  IGN RGE ALTI via the Geoplateforme altimetry REST API, Licence
            Ouverte Etalab 2.0. 1 m source data. Strictly better than the
            Copernicus GLO-30 DSM the Irish sites had to use.
waves       CMEMS IBI_MULTIYEAR_WAV_005_006, the SAME product and the same
            2015-2024 period as Sherkin and An Aird, so the bearing is
            comparable with the locked Irish ones rather than merely
            plausible. NWSHELF_REANALYSIS_WAV_004_015 is fetched too and the
            two are compared; see france_chain.py.

LITTO3D: OPEN LICENCE, CLOSED DOOR
----------------------------------
The brief named SHOM/IGN Litto3D (1 m and 5 m DTM, Licence Ouverte). It was
pursued and it is not machine-reachable. Measured 2026-08-28:

  * data.gouv.fr dataset "Litto3D Finistere 2014", licence `lov2`
    (Licence Ouverte v2.0) -- carries exactly ONE resource, a rendered WMS.
  * that WMS layer (LITTO3D_FINISTR_2014_PYR_3857_WMSR) answers
    GetFeatureInfo with `LayerNotQueryable`, so it yields pixels, not metres.
  * no WCS exists on services.data.shom.fr (404 on every documented path).
  * diffusion.shom.fr, the actual download route, is a login-and-basket
    portal requiring account creation.
  * "Litto3D Bretagne 2018-2021" does NOT cover Finistere in any case: it is
    Cotes-d'Armor, Ille-et-Vilaine and Morbihan. The AOI's products are
    Finistere 2014 and PNMI Iroise 2012.

Reading depth values off a rendered colour ramp would be inventing data, and
creating an account in Elif's name is not this session's to do. So the
conservative choice was taken -- use the open DTM that IS reachable, declare
the resolution loss, and leave a one-line manual task in the handover. This
is recorded in LITTO3D_STATUS and travels with every result.

CACHING AND OUTAGES
-------------------
Every artefact is written once, atomically, beside a `.meta.json` sidecar
recording the exact request, the server, the byte count and a SHA-256 of the
payload. The sidecar rule is inherited from NOTE_2026-08-28_mirror_repair:
a cached response that does not record the question it answers cannot be
audited, only re-run and hoped over.

A complete artefact is NEVER overwritten by a later run -- that is the
28 August hazard, where a time budget silently replaced a finished result
with a truncated one. `fetch()` returns the cached file untouched unless
--refresh is passed for that specific key.

Paged WFS downloads cache EACH PAGE separately, so an outage in page 40 of
90 costs one page, not forty.

Run:
    python src/france_data.py                # fetch everything missing
    python src/france_data.py --only kelp    # one source
    python src/france_data.py --report       # what is on disk, no network

Licences: see DEPENDENCIES.md section 3.1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "france"
OUT = REPO / "outputs" / "france"

UA = "OceanHackathon-Cork2026-research/1.0 (mielmt17@gmail.com)"

# ----------------------------------------------------------------- the site
SITE = {
    "name": "Le Conquet / Molene Archipelago, Iroise Sea, Brittany, France",
    "receptor_town": "Le Conquet",
    "receptor_lon": -4.77,
    "receptor_lat": 48.36,
    "molene_lon": -4.958,
    "molene_lat": 48.396,
    "commune_insee": "29040",          # Le Conquet
    "country": "FR",
    "crs_projected": "EPSG:2154",      # Lambert-93, the French analogue of ITM
}

# Analysis box: 20 km half-width around Le Conquet. Wide enough that the
# Molene archipelago beds (16 km W) are inside it and the bearing test, not
# the box edge, decides what counts as "in front of" the town.
BOX_HALF_M = 20_000.0

# WGS84 bbox derived from the box, computed once here so every fetcher asks
# for the same rectangle and a mismatch cannot creep in silently.
_DLAT = BOX_HALF_M / 111_320.0
_DLON = _DLAT / math.cos(math.radians(SITE["receptor_lat"]))
BBOX_WGS = (
    round(SITE["receptor_lon"] - _DLON, 6),   # min lon
    round(SITE["receptor_lat"] - _DLAT, 6),   # min lat
    round(SITE["receptor_lon"] + _DLON, 6),   # max lon
    round(SITE["receptor_lat"] + _DLAT, 6),   # max lat
)

# ------------------------------------------------------------- the licences
# Verified at source on the date shown. A licence recalled from memory is not
# a verified licence; each entry below names the document the wording came
# from so a reviewer can re-open it.
LICENCES = {
    "sextant_kelp_bajjouk_2015": {
        "dataset": "Kelp species L. digitata and L. hyperborea mapping along "
                   "Molene Archipelagos (France)",
        "doi": "10.12770/4adbe32a-8c81-4c18-8da3-4c361889820c",
        "record": "https://sextant.ifremer.fr/geonetwork/srv/api/records/"
                  "4adbe32a-8c81-4c18-8da3-4c361889820c/formatters/xml",
        "licence_verbatim": "Creative Commons license to apply : Attribution "
                            "+ Non Commercial + No Derivs (BY-NC-ND)",
        "verified_utc": "2026-08-28",
        "openly_reusable": False,
        "verdict": "NOT USED. NC and ND both bar this chain's use "
                   "(derive a frontage layer from it and publish it). "
                   "Substituted per the brief's own instruction.",
        "note": "Its abstract describes a habitat suitability MODEL fitted on "
                "field stations, not a wall-to-wall survey. The brief called "
                "it 'SURVEYED'; the record does not.",
    },
    "emodnet_macroalgae_eov_2025": {
        "dataset": "Macroalgal canopy cover (EOV) in Europe - polygons (2025)",
        "layer": "emodnet_open:macroalgae_eov_poly_2025",
        "record": "https://gis.ices.dk/geonetwork/srv/api/records/"
                  "913a0ee4-45d7-45aa-8de2-3d31af0f7c0e/formatters/xml",
        "licence_verbatim": "Available under the Creative Commons Attribution "
                            "(CC-BY) License v4.0 "
                            "(https://creativecommons.org/licenses/by/4.0/)",
        "verified_utc": "2026-08-28",
        "openly_reusable": True,
        "verdict": "USED as the kelp layer, L. hyperborea polygons only.",
        "attribution": "EMODnet Seabed Habitats; Molene polygons map_id "
                       "OSPARHab2022FRv1, source Office Francais de la "
                       "Biodiversite, determiner DYNECO/BENTHOS, 2015.",
    },
    "emodnet_bathymetry": {
        "dataset": "EMODnet Bathymetry DTM (emodnet:mean)",
        "terms": "https://emodnet.ec.europa.eu/en/"
                 "terms-use-emodnet-online-services-data-and-data-products",
        "licence_verbatim": "Creative Commons Attribution 4.0 International "
                            "(CC BY 4.0)",
        "verified_utc": "2026-08-28",
        "openly_reusable": True,
        "verdict": "USED as the depth source. ~77 m x ~116 m at 48.4 N.",
    },
    "ign_bdtopo_v3": {
        "dataset": "IGN BD TOPO v3 via Geoplateforme WFS",
        "licence_verbatim": "Licence Ouverte / Open Licence version 2.0 "
                            "(Etalab)",
        "attribution": "IGN - BD TOPO(R)",
        "verified_utc": "2026-08-28",
        "openly_reusable": True,
        "verdict": "USED as the receptor inventory.",
    },
    "ign_rge_alti": {
        "dataset": "IGN RGE ALTI via Geoplateforme altimetry REST API",
        "licence_verbatim": "Licence Ouverte / Open Licence version 2.0 "
                            "(Etalab)",
        "attribution": "IGN - RGE ALTI(R)",
        "verified_utc": "2026-08-28",
        "openly_reusable": True,
        "verdict": "USED as receptor ground elevation.",
    },
    "cmems_ibi_wav": {
        "dataset": "CMEMS IBI_MULTIYEAR_WAV_005_006 "
                   "(cmems_mod_ibi_wav_my_0.027deg_PT1H-i)",
        "licence_verbatim": "E.U. Copernicus Marine Service Information",
        "verified_utc": "2026-08-10 (carried; unchanged)",
        "openly_reusable": True,
        "verdict": "USED as the wave climate. Same product and period as the "
                   "two locked Irish sites, so bearings are comparable.",
    },
    "litto3d": {
        "dataset": "SHOM/IGN Litto3D Finistere 2014 / PNMI Iroise 2012",
        "licence_verbatim": "Licence Ouverte v2.0 (Etalab); data.gouv.fr "
                            "licence id 'lov2'",
        "verified_utc": "2026-08-28",
        "openly_reusable": True,
        "verdict": "NOT USED -- open licence, closed door. See LITTO3D_STATUS.",
    },
}

LITTO3D_STATUS = {
    "wanted_for": "the 4-10 m depth polygon, at 1 m instead of ~100 m",
    "licence": "Licence Ouverte v2.0 -- genuinely open",
    "reachable": False,
    "checks_run_2026_08_28": [
        "data.gouv.fr dataset 'Litto3D Finistere 2014' (licence lov2) lists "
        "exactly one resource: a rendered WMS.",
        "WMS LITTO3D_FINISTR_2014_PYR_3857_WMSR answers GetFeatureInfo with "
        "ServiceException 'LayerNotQueryable' -- pixels, not metres.",
        "No WCS on services.data.shom.fr: /INSPIRE/wcs and /inspire/wcs both "
        "404.",
        "diffusion.shom.fr requires account creation and a download basket.",
        "'Litto3D Bretagne 2018-2021' excludes Finistere (Cotes-d'Armor, "
        "Ille-et-Vilaine, Morbihan only), so it is not a substitute either.",
    ],
    "decision": "Use EMODnet Bathymetry (CC-BY-4.0, ~77x116 m) and declare "
                "the resolution loss on every derived figure. Reading depths "
                "off a rendered colour ramp would be inventing data.",
    "manual_task_for_elif": "One account on diffusion.shom.fr and a basket "
                            "download of the Finistere 2014 / PNMI 2012 5 m "
                            "DTM tiles covering X 104-132 km, Y 6828-6846 km "
                            "(Lambert-93) would replace the depth grid "
                            "wholesale. Nothing else in the chain changes.",
}

# --------------------------------------------------------------- endpoints
EMODNET_HAB_WFS = "https://ows.emodnet-seabedhabitats.eu/geoserver/emodnet_open/ows"
EMODNET_BATHY_WCS = "https://ows.emodnet-bathymetry.eu/wcs"
EMODNET_BATHY_WFS = "https://ows.emodnet-bathymetry.eu/wfs"
IGN_WFS = "https://data.geopf.fr/wfs/ows"
IGN_ALTI = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"

KELP_LAYER = "emodnet_open:macroalgae_eov_poly_2025"
# The habsubtype values present in this AOI, measured not assumed:
#   'Kelp forests dominated by Laminaria digitata'      35 065 in a 40k sample
#   'Kelp forests dominated by Laminaria hyperborea'     4 667
#   'Unknown'                                              268
# Only hyperborea is fetched. digitata sits at 0-3 m and the Dubi & Torum
# coefficients do not apply to it (CLAUDE.md rule 3); fetching it would only
# create an opportunity to mix the two later.
KELP_HYPERBOREA = "Kelp forests dominated by Laminaria hyperborea"
KELP_DIGITATA = "Kelp forests dominated by Laminaria digitata"

BDTOPO_LAYERS = {
    # layer -> why this one is a receptor
    "BDTOPO_V3:batiment": "buildings -- the primary receptor class",
    "BDTOPO_V3:construction_lineaire": "dikes, sea walls, quays -- these are "
                                       "also the evidence for Shabman & Batie "
                                       "condition 3 (demonstrated demand)",
    "BDTOPO_V3:construction_surfacique": "dams, tanks, surface structures",
    "BDTOPO_V3:equipement_de_transport": "ferry terminal, car parks, quays",
    "BDTOPO_V3:troncon_de_route": "roads -- the non-building receptor class "
                                  "the Irish screen also carried",
    "BDTOPO_V3:zone_d_activite_ou_d_interet": "named activity/interest zones, "
                                              "used to identify the port",
    "BDTOPO_V3:limite_terre_mer": "the authoritative land-sea limit; the "
                                  "shoreline every distance-to-shore gate is "
                                  "measured from",
}

# --------------------------------------------------------- fetch machinery
RETRIES = 5
BACKOFF_S = 8.0
TIMEOUT_S = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sidecar(path: Path, meta: dict) -> None:
    """Every cached artefact records the question it answers.

    Inherited from NOTE_2026-08-28_mirror_repair: a cache without provenance
    cannot be audited, only re-run and hoped over.
    """
    meta = dict(meta)
    meta["file"] = path.name
    meta["bytes"] = path.stat().st_size
    meta["sha256"] = _sha256(path)
    meta["written_utc"] = _now()
    tmp = path.with_suffix(path.suffix + ".meta.tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path.with_suffix(path.suffix + ".meta.json"))


def _atomic_write(path: Path, content: bytes) -> None:
    """Temp file plus replace. An interrupted run cannot leave a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def http_get(url: str, params: dict | None = None, *, stream_to: Path | None = None,
             accept: str | None = None) -> bytes:
    """GET with exponential backoff. Raises after RETRIES attempts."""
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=headers,
                             timeout=TIMEOUT_S)
            if r.status_code == 200:
                return r.content
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            # 4xx other than 429 will not fix themselves
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise RuntimeError(last)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {str(exc)[:200]}"
        if attempt < RETRIES:
            wait = BACKOFF_S * (2 ** (attempt - 1))
            print(f"      attempt {attempt}/{RETRIES} failed ({last}); "
                  f"retrying in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"giving up after {RETRIES} attempts: {last}")


def cached(path: Path, min_bytes: int = 64) -> bool:
    """A cached artefact counts only if it exists, is non-trivial, and has a
    sidecar. A file with no sidecar is a file whose provenance is unknown."""
    return (path.exists() and path.stat().st_size >= min_bytes
            and path.with_suffix(path.suffix + ".meta.json").exists())


# --------------------------------------------------------------- WFS paging
def _cql_bbox(geom_field: str, bbox: tuple) -> str:
    """CQL BBOX over a WGS84 rectangle.

    Two axis-order traps meet here and they disagree with each other:
    a WFS 2.0 `bbox=` parameter with the urn form of EPSG:4326 is lat,lon,
    while CQL's BBOX() takes minx,miny,maxx,maxy -- lon,lat. Getting this
    wrong returns zero features silently, which in this project is a
    publishable finding (CLAUDE.md section 3). Both forms are therefore
    checked against each other in check_bbox_axes() before any use.
    """
    return (f"BBOX({geom_field},{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},"
            f"'EPSG:4326')")


def wfs_hits(base: str, typename: str, bbox_latlon: tuple,
             cql: str | None = None, geom_field: str = "geom") -> int:
    p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
         "typeNames": typename, "resultType": "hits", "srsName": "EPSG:4326"}
    if cql:
        # GeoServer refuses bbox= and cql_filter= together; fold the box in.
        p["cql_filter"] = f"({cql}) AND {_cql_bbox(geom_field, bbox_latlon)}"
    else:
        p["bbox"] = (f"{bbox_latlon[1]},{bbox_latlon[0]},{bbox_latlon[3]},"
                     f"{bbox_latlon[2]},urn:ogc:def:crs:EPSG::4326")
    body = http_get(base, p)
    import re
    m = re.search(rb'numberMatched="(\d+)"', body)
    if not m:
        raise RuntimeError(f"no numberMatched in hits response: {body[:300]!r}")
    return int(m.group(1))


def check_bbox_axes(base: str, typename: str, bbox: tuple,
                    geom_field: str = "geom") -> dict:
    """The two bbox spellings must agree, and a wrong-hemisphere box must be 0.

    A zero from a CRS mistake looks exactly like a zero from an empty area.
    This runs both spellings of the same rectangle plus a control box in the
    Black Sea; if the two spellings disagree, or the control is non-zero, the
    caller is told rather than handed a number.
    """
    n_param = wfs_hits(base, typename, bbox, None, geom_field)
    n_cql = wfs_hits(base, typename, bbox, "1=1", geom_field)
    control = (31.9, 43.0, 32.1, 43.2)          # Black Sea, no Atlantic kelp
    n_ctrl = wfs_hits(base, typename, control, None, geom_field)
    ok = (n_param == n_cql) and n_ctrl == 0 and n_param > 0
    return {"bbox_param": n_param, "cql_bbox": n_cql,
            "black_sea_control": n_ctrl, "agree": bool(ok)}


def wfs_paged(base: str, typename: str, out_stem: Path, bbox_latlon: tuple,
              *, page: int = 5000, cql: str | None = None,
              geom_field: str = "geom", srs: str = "EPSG:4326") -> list[Path]:
    """Download a WFS layer in pages, caching EACH page separately.

    An outage in page 40 of 90 costs one page, not forty. Pages are only
    re-requested if their own file is missing.
    """
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    n = wfs_hits(base, typename, bbox_latlon, cql, geom_field)
    print(f"   {typename}: {n:,} features matched")
    if n == 0:
        return []
    pages = []
    start = 0
    idx = 0
    while start < n:
        pth = out_stem.parent / f"{out_stem.name}_p{idx:03d}.json"
        if cached(pth, min_bytes=32):
            print(f"      page {idx:03d} cached")
        else:
            p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                 "typeNames": typename, "outputFormat": "application/json",
                 "srsName": srs, "count": page, "startIndex": start,
                 "sortBy": "objectid" if "macroalgae" in typename else None}
            p = {k: v for k, v in p.items() if v is not None}
            if cql:
                p["cql_filter"] = (f"({cql}) AND "
                                   f"{_cql_bbox(geom_field, bbox_latlon)}")
            else:
                p["bbox"] = (f"{bbox_latlon[1]},{bbox_latlon[0]},"
                             f"{bbox_latlon[3]},{bbox_latlon[2]},"
                             f"urn:ogc:def:crs:EPSG::4326")
            print(f"      page {idx:03d}  start={start:,}")
            body = http_get(base, p)
            _atomic_write(pth, body)
            _sidecar(pth, {"endpoint": base, "typename": typename,
                           "params": p, "page_index": idx,
                           "number_matched_at_fetch": n})
        pages.append(pth)
        start += page
        idx += 1
    return pages


# ----------------------------------------------------------- source fetchers
def fetch_kelp(refresh: bool = False) -> Path:
    """EMODnet macroalgae EOV polygons, L. hyperborea only, over the AOI."""
    stem = DATA / "kelp" / "hyperborea"
    merged = DATA / "kelp_hyperborea.geojson"
    if cached(merged) and not refresh:
        print("   kelp: cached")
        return merged
    axes = check_bbox_axes(EMODNET_HAB_WFS, KELP_LAYER, BBOX_WGS)
    print(f"   bbox axis self-test: {axes}")
    if not axes["agree"]:
        raise RuntimeError(
            "bbox axis self-test failed -- the two spellings of the same "
            f"rectangle disagree or the control is non-zero: {axes}. "
            "A zero here would look like a finding. Refusing to fetch.")
    cql = f"habsubtype='{KELP_HYPERBOREA}'"
    pages = wfs_paged(EMODNET_HAB_WFS, KELP_LAYER, stem, BBOX_WGS, cql=cql)
    feats = []
    for p in pages:
        d = json.loads(p.read_text(encoding="utf-8"))
        feats.extend(d.get("features", []))
    fc = {"type": "FeatureCollection", "features": feats}
    _atomic_write(merged, json.dumps(fc).encode("utf-8"))
    _sidecar(merged, {"endpoint": EMODNET_HAB_WFS, "layer": KELP_LAYER,
                      "cql": cql, "bbox_wgs": BBOX_WGS,
                      "pages": [p.name for p in pages],
                      "features": len(feats),
                      "licence": LICENCES["emodnet_macroalgae_eov_2025"]})
    print(f"   kelp: {len(feats):,} L. hyperborea polygons -> {merged.name}")
    return merged


def fetch_kelp_digitata_count() -> Path:
    """Count L. digitata in the AOI without downloading its geometry.

    It is excluded from the analysis, but "excluded" is a claim about a
    quantity that exists, so the quantity is recorded.
    """
    p = DATA / "kelp_digitata_count.json"
    if cached(p):
        return p
    n = wfs_hits(EMODNET_HAB_WFS, KELP_LAYER, BBOX_WGS,
                 f"habsubtype='{KELP_DIGITATA}'")
    nh = wfs_hits(EMODNET_HAB_WFS, KELP_LAYER, BBOX_WGS,
                  f"habsubtype='{KELP_HYPERBOREA}'")
    body = json.dumps({"aoi_bbox_wgs": BBOX_WGS,
                       "l_digitata_polygons": n,
                       "l_hyperborea_polygons": nh,
                       "excluded": "L. digitata -- 0-3 m, outside the "
                                   "Dubi & Torum 4-10 m validity band "
                                   "(CLAUDE.md rule 3)",
                       "measured_utc": _now()}, indent=2)
    _atomic_write(p, body.encode("utf-8"))
    _sidecar(p, {"endpoint": EMODNET_HAB_WFS, "layer": KELP_LAYER,
                 "question": "how many polygons of each species in the AOI"})
    print(f"   species split: {nh:,} hyperborea / {n:,} digitata (excluded)")
    return p


def fetch_bathymetry(refresh: bool = False) -> Path:
    """EMODnet Bathymetry DTM over the AOI, at the product's native step."""
    p = DATA / "bathy_emodnet.tif"
    if cached(p, min_bytes=10_000) and not refresh:
        print("   bathymetry: cached")
        return p
    # 1/16 arcmin native step, requested exactly so the server does not
    # resample: asking for a width that does not match the native grid is how
    # a "115 m product" quietly becomes a smoothed one.
    step = 1.0 / 16.0 / 60.0
    w = int(round((BBOX_WGS[2] - BBOX_WGS[0]) / step))
    h = int(round((BBOX_WGS[3] - BBOX_WGS[1]) / step))
    params = {"service": "WCS", "version": "1.0.0", "request": "GetCoverage",
              "coverage": "emodnet:mean", "crs": "EPSG:4326",
              "bbox": f"{BBOX_WGS[0]},{BBOX_WGS[1]},{BBOX_WGS[2]},{BBOX_WGS[3]}",
              "width": w, "height": h, "format": "GeoTIFF"}
    print(f"   bathymetry: requesting {w} x {h} at 1/16 arcmin")
    body = http_get(EMODNET_BATHY_WCS, params)
    _atomic_write(p, body)
    _sidecar(p, {"endpoint": EMODNET_BATHY_WCS, "params": params,
                 "native_step_deg": step,
                 "licence": LICENCES["emodnet_bathymetry"],
                 "vertical_datum": "LAT (EMODnet DTM convention); see "
                                   "france_chain.py for the tidal-range "
                                   "sensitivity this forces at Le Conquet",
                 "not_litto3d": LITTO3D_STATUS})
    return p


def fetch_bathy_provenance(refresh: bool = False) -> Path:
    """Does the AOI's depth trace to a logged survey, or to GEBCO fill?

    Same test as src/emodnet_provenance.py: EMODnet's source-reference layer
    is a patchwork of the real datasets that went into the DTM, and areas
    with no observations are completed from GEBCO and fall in its holes.
    """
    p = DATA / "bathy_source_refs.geojson"
    if cached(p) and not refresh:
        print("   bathymetry provenance: cached")
        return p
    pages = wfs_paged(EMODNET_BATHY_WFS, "emodnet:source_references",
                      DATA / "bathysrc" / "src", BBOX_WGS, page=1000)
    feats = []
    for q in pages:
        feats.extend(json.loads(q.read_text(encoding="utf-8")).get("features", []))
    _atomic_write(p, json.dumps({"type": "FeatureCollection",
                                 "features": feats}).encode("utf-8"))
    _sidecar(p, {"endpoint": EMODNET_BATHY_WFS,
                 "layer": "emodnet:source_references",
                 "question": "does AOI depth trace to a logged survey",
                 "features": len(feats)})
    print(f"   bathymetry provenance: {len(feats)} source patches")
    return p


def fetch_bdtopo(refresh: bool = False) -> dict[str, Path]:
    """IGN BD TOPO receptor layers over the AOI."""
    out = {}
    for layer, why in BDTOPO_LAYERS.items():
        short = layer.split(":", 1)[1]
        merged = DATA / f"bdtopo_{short}.geojson"
        if cached(merged) and not refresh:
            print(f"   bdtopo {short}: cached")
            out[short] = merged
            continue
        try:
            pages = wfs_paged(IGN_WFS, layer, DATA / "bdtopo" / short,
                              BBOX_WGS, page=5000)
        except Exception as exc:
            print(f"   bdtopo {short}: FAILED ({type(exc).__name__}: "
                  f"{str(exc)[:150]}) -- moving on, will retry next run")
            continue
        feats = []
        for q in pages:
            feats.extend(json.loads(q.read_text(encoding="utf-8")).get("features", []))
        _atomic_write(merged, json.dumps({"type": "FeatureCollection",
                                          "features": feats}).encode("utf-8"))
        _sidecar(merged, {"endpoint": IGN_WFS, "layer": layer, "why": why,
                          "bbox_wgs": BBOX_WGS, "features": len(feats),
                          "licence": LICENCES["ign_bdtopo_v3"]})
        print(f"   bdtopo {short}: {len(feats):,} features")
        out[short] = merged
    return out


def rge_alti(points: list[tuple[float, float]], tag: str,
             batch: int = 150) -> list[float]:
    """IGN RGE ALTI ground elevation, batched and cached per batch.

    Returns metres above the French vertical datum (NGF-IGN69), or NaN where
    the API returns its -99999.01 no-data sentinel (i.e. over the sea).
    """
    d = DATA / "alti" / tag
    d.mkdir(parents=True, exist_ok=True)
    zs: list[float] = []
    for i in range(0, len(points), batch):
        chunk = points[i:i + batch]
        f = d / f"b{i // batch:04d}.json"
        if cached(f, min_bytes=16):
            data = json.loads(f.read_text(encoding="utf-8"))
        else:
            params = {"lon": "|".join(f"{lo:.6f}" for lo, _ in chunk),
                      "lat": "|".join(f"{la:.6f}" for _, la in chunk),
                      "resource": "ign_rge_alti_wld", "zonly": "false",
                      "delimiter": "|", "indent": "false"}
            body = http_get(IGN_ALTI, params)
            _atomic_write(f, body)
            _sidecar(f, {"endpoint": IGN_ALTI, "n_points": len(chunk),
                         "tag": tag, "batch_index": i // batch,
                         "licence": LICENCES["ign_rge_alti"]})
            data = json.loads(body.decode("utf-8"))
        for e in data.get("elevations", []):
            z = e.get("z")
            zs.append(float("nan") if z is None or z < -9000 else float(z))
    return zs


def fetch_waves(refresh: bool = False) -> Path:
    """CMEMS wave subset at Le Conquet, same product/period as the Irish sites."""
    nc = REPO / "data" / "cmems" / "ibi_wav_leconquet.nc"
    if nc.exists() and nc.stat().st_size > 1_000_000 and not refresh:
        try:
            import xarray as xr
            with xr.open_dataset(nc) as ds:
                if {"VHM0", "VMDR"} <= set(ds.variables):
                    print("   waves (IBI): cached")
                    return nc
        except Exception:
            pass
    import copernicusmarine as cm
    nc.parent.mkdir(parents=True, exist_ok=True)
    # Widen only if the first box is all land -- same ladder as
    # src/site_wave_climate.py, so the two sites are treated identically.
    for lh, ah in ((0.08, 0.055), (0.14, 0.095), (0.22, 0.150)):
        print(f"   waves (IBI): subset +/-{lh} lon, +/-{ah} lat")
        cm.subset(dataset_id="cmems_mod_ibi_wav_my_0.027deg_PT1H-i",
                  variables=["VHM0", "VMDR", "VHM0_SW1", "VMDR_SW1"],
                  minimum_longitude=SITE["receptor_lon"] - lh,
                  maximum_longitude=SITE["receptor_lon"] + lh,
                  minimum_latitude=SITE["receptor_lat"] - ah,
                  maximum_latitude=SITE["receptor_lat"] + ah,
                  start_datetime="2015-01-01", end_datetime="2024-12-31",
                  output_filename=nc.name, output_directory=str(nc.parent),
                  overwrite=True)
        import xarray as xr
        with xr.open_dataset(nc) as ds:
            if bool((ds["VHM0"].notnull().sum("time") > 0).any()):
                _sidecar(nc, {"product": "IBI_MULTIYEAR_WAV_005_006",
                              "dataset_id": "cmems_mod_ibi_wav_my_0.027deg_PT1H-i",
                              "half_box_deg": [lh, ah],
                              "period": "2015-01-01..2024-12-31",
                              "licence": LICENCES["cmems_ibi_wav"]})
                return nc
        print("      every cell in that box is land; widening")
    raise RuntimeError("no wet CMEMS cell found near Le Conquet")


def fetch_waves_nwshelf(refresh: bool = False) -> Path | None:
    """The product the brief named, fetched as an independent cross-check.

    The IBI product is primary because it is the one the two locked Irish
    bearings were measured on, and a bearing compared across products is a
    bearing compared across two different models. This one exists so that
    "the bearing is not an artefact of the product" is a measurement rather
    than an assumption. A failure here is not fatal.
    """
    nc = REPO / "data" / "cmems" / "nws_wav_leconquet.nc"
    if nc.exists() and nc.stat().st_size > 100_000 and not refresh:
        print("   waves (NWSHELF): cached")
        return nc
    import copernicusmarine as cm
    # Dataset id measured from the catalogue, not recalled: the documented
    # "cmems_mod_nws_wav_my_4km_PT1H-i" does not exist. copernicusmarine
    # describe(product_id="NWSHELF_REANALYSIS_WAV_004_015") returns exactly
    # one time-varying dataset, "MetO-NWS-WAV-RAN".
    for ds_id in ("MetO-NWS-WAV-RAN",):
        try:
            print(f"   waves (NWSHELF): trying {ds_id}")
            cm.subset(dataset_id=ds_id,
                      variables=["VHM0", "VMDR"],
                      minimum_longitude=SITE["receptor_lon"] - 0.10,
                      maximum_longitude=SITE["receptor_lon"] + 0.10,
                      minimum_latitude=SITE["receptor_lat"] - 0.07,
                      maximum_latitude=SITE["receptor_lat"] + 0.07,
                      start_datetime="2015-01-01", end_datetime="2024-12-31",
                      output_filename=nc.name, output_directory=str(nc.parent),
                      overwrite=True)
            _sidecar(nc, {"product": "NWSHELF_REANALYSIS_WAV_004_015",
                          "dataset_id": ds_id,
                          "role": "independent cross-check of the IBI bearing",
                          "period": "2015-01-01..2024-12-31"})
            return nc
        except Exception as exc:
            print(f"      {type(exc).__name__}: {str(exc)[:180]}")
    print("   waves (NWSHELF): unavailable -- cross-check will be reported "
          "as NOT RUN, not as agreement")
    return None


# ------------------------------------------------------------------- report
def write_licence_record() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "licence_verification.json"
    payload = {
        "site": SITE,
        "aoi_bbox_wgs84": BBOX_WGS,
        "box_half_m": BOX_HALF_M,
        "checked_utc": _now(),
        "first_action_required_by_brief":
            "verify the licence of the Sextant kelp dataset before anything "
            "else; substitute EMODnet if it is not openly re-usable",
        "verdict": "SUBSTITUTED. Sextant record is CC BY-NC-ND; EMODnet "
                   "macroalgae EOV 2025 (CC BY 4.0) used instead.",
        "licences": LICENCES,
        "litto3d": LITTO3D_STATUS,
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return p


def report() -> None:
    print("=" * 78)
    print("FRANCE / IROISE -- data on disk")
    print("=" * 78)
    print(f"AOI bbox (WGS84): {BBOX_WGS}")
    for p in sorted(DATA.glob("*")):
        if p.suffix == ".json" and p.name.endswith(".meta.json"):
            continue
        if p.is_dir():
            n = len(list(p.rglob("*.json"))) // 2
            print(f"  {p.name + '/':38s} {n:>6} cached pages")
        else:
            mb = p.stat().st_size / 1e6
            side = "meta" if p.with_suffix(p.suffix + ".meta.json").exists() else "NO META"
            print(f"  {p.name:38s} {mb:8.2f} MB  {side}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None,
                    choices=["kelp", "bathy", "provenance", "bdtopo", "waves",
                             "nwshelf", "licence"])
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch even if cached. Off by default: a complete "
                         "artefact is never silently replaced.")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    if a.report:
        report()
        return 0

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    want = set(a.only) if a.only else {"licence", "kelp", "bathy",
                                       "provenance", "bdtopo", "waves",
                                       "nwshelf"}

    print("=" * 78)
    print("FRANCE / IROISE -- data acquisition")
    print("=" * 78)
    print(f"site : {SITE['name']}")
    print(f"AOI  : {BBOX_WGS}  ({BOX_HALF_M/1000:.0f} km half-width)")
    print()

    if "licence" in want:
        p = write_licence_record()
        print(f"licence record -> {p}")
        print("   Sextant kelp dataset: CC BY-NC-ND -> NOT USED")
        print("   EMODnet macroalgae EOV 2025: CC BY 4.0 -> USED")
        print("   Litto3D: Licence Ouverte but not machine-reachable -> "
              "EMODnet Bathymetry used, resolution loss declared")
        print()

    failures = []
    steps = [("kelp", lambda: (fetch_kelp(a.refresh), fetch_kelp_digitata_count())),
             ("bathy", lambda: fetch_bathymetry(a.refresh)),
             ("provenance", lambda: fetch_bathy_provenance(a.refresh)),
             ("bdtopo", lambda: fetch_bdtopo(a.refresh)),
             ("waves", lambda: fetch_waves(a.refresh)),
             ("nwshelf", lambda: fetch_waves_nwshelf(a.refresh))]
    for key, fn in steps:
        if key not in want:
            continue
        print(f"-- {key}")
        try:
            fn()
        except Exception as exc:
            print(f"   {key}: FAILED -- {type(exc).__name__}: {str(exc)[:250]}")
            print(f"   moving on. Re-run to resume; cached pages are kept.")
            failures.append(key)
        print()

    print("=" * 78)
    if failures:
        print(f"INCOMPLETE: {', '.join(failures)} failed. Everything else is "
              f"on disk and cached; re-run to resume just the failures.")
    else:
        print("All sources on disk.")
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
