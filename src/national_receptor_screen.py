#!/usr/bin/env python3
"""
national_receptor_screen.py
===========================
Phase A of the receptor screen, extended from ~150 km of West Cork / Kerry
coast to the whole Irish Atlantic seaboard: Kerry, Clare, Galway, Mayo,
Sligo, Donegal (2026-08-27).

QUESTION - unchanged from src/wide_receptor_screen.py
    Anywhere on the Irish Atlantic coast, is there a stretch where ALL of
    these hold?
      (a) Laminaria habitat sits in front of the frontage
      (b) built receptors sit behind it
      (c) the sea in front is exposed enough for the Dubi & Torum / Mork
          coefficients to be in domain (log10 fetch > 3.73)

METHOD FIDELITY - read this before changing anything
    Every screen parameter is IMPORTED from wide_receptor_screen, not
    re-declared here, so that no threshold can drift between the West Cork
    run and the national run. In particular:

        FETCH_EXCLUSION_MAX = 3.73

    was pre-registered on 2026-08-11, before any result was seen, and is
    used here as the same Python object. It is NOT tuned to make sites
    pass. Allihies (fetch 3.626, 53 ha of NPWS Laminaria within 1 km) is
    the standing test of that rule: it fails, and it stays failed.

    The OSM fetchers (fetch_buildings / fetch_coastline / fetch_places) are
    likewise imported and called unmodified, per search box, by rebinding
    wide_receptor_screen.EXTENT. The West Cork box is re-run with its
    original extent and bands, so it hits the 2026-08-27 Overpass cache and
    reproduces the Phase A numbers exactly. That is the regression test.

WHAT IS NEW
    1. SEARCH_BOXES - 15 named boxes covering Dingle to Malin Head. The
       box name IS the region label (an exact fact about where the cluster
       was found), replacing the nearest-anchor heuristic of the West Cork
       run. Boxes deliberately overlap; a cluster is assigned to the first
       box in list order that contains its centroid.
    2. National NPWS tier 1. Laminaria-dominated reef is mapped in eleven
       sites nationally, not the three inside the West Cork extent - Clew
       Bay (4 896 ha), Kilkieran Bay (8 085 ha), Galway Bay (2 861 ha) and
       Lower River Shannon (26 175 ha) all fall inside this extent. So the
       habitat term now has real data in Mayo, Galway and Clare.
    3. Mapping-quality flag. The step-2 model excluded sites whose median
       Laminaria polygon exceeds 50 ha as "coarse mapping". The same rule
       is applied here as a per-site label (fine / coarse), so a hit
       against a 160 ha Lower Shannon polygon is not read as equal evidence
       to a hit against a 0.27 ha Kenmare polygon.
    4. THE HABITAT-EVIDENCE GAP IS SPLIT FIVE WAYS. This is the main
       analytical change and it is what "no habitat map" was hiding.

       The split turns on WHERE EACH NPWS POLYGON CAME FROM, checked in the
       shapefile's own Source field on 2026-08-27:
         - "laminaria-dominated reef" (1 936) and "faunal turf reef" (1 528)
           both carry an "NPWS CO Series: <site> <year>" source, i.e. a
           site-specific dive/video survey that DETERMINED the biological
           community.
         - "geogenic reef" (42 142) carries "FinalPHTCoverage_20120926WGS84"
           (38 772) or "EUNIS Habitats Predicted 2007" (3 370). These are
           compiled or PREDICTED substrate coverage. They record that reef
           is there. They do NOT record what grows on it.
         - the intertidal classes (fucoid / mytilus / sabellaria) are a
           different zone and say nothing about subtidal Laminaria.

       So mapped reef is NOT the same as surveyed-and-found-not-Laminaria,
       and conflating the two would manufacture absence evidence out of a
       substrate layer. The five states:

         laminaria_present                   Laminaria within 1 km -> PRESENT
         surveyed_not_laminaria              faunal turf reef within 1 km,
                                             no Laminaria -> real ABSENCE,
                                             same survey provenance
         reef_mapped_community_undetermined  only geogenic reef within 1 km
                                             -> substrate known, community
                                             NEVER DETERMINED -> still a gap
         modelled_no_laminaria               step-2 model ran here and put
                                             nothing over threshold
         unmapped                            no subtidal layer-21 polygon

       The third and fifth states are the genuine blanks, and together they
       are the set handed to src/habitat_gap_model.py. Treating geogenic
       reef as an answer would have wrongly closed most of them.

WHAT THIS IS NOT
    Not a valuation. No euro is computed here, and none may be computed
    from this file's output without a separate Phase B decision.

    The receptor test is still SHORE PROXIMITY, not flood exposure: no OPW
    layer (licence CC BY-NC-ND 4.0 unresolved, CLAUDE.md rule 9) and no
    DEM. That makes the screen generous on the receptor side, so a zero is
    stronger than it looks and a positive means nothing until elevation is
    re-tested.

OUTPUT
    outputs/national_receptor_screen.csv            all clusters, ranked
    outputs/national_receptor_screen_candidates.csv clusters passing (a)+(b)+(c)
    outputs/national_receptor_screen_gap.csv        fetch-passing clusters whose
                                                    habitat term is a genuine
                                                    blank: nothing mapped, or
                                                    only geogenic reef whose
                                                    community was never
                                                    determined -> input to Part 2
    outputs/national_receptor_screen_summary.json   extent, parameters, counts
    outputs/national_receptor_screen_laminaria.geojson
    outputs/national_receptor_screen_buildings.geojson

CONTROLS
    1. Baltimore (-9.374, 51.484) must reappear and must still FAIL the
       fetch gate.
    2. The Sherkin cluster (-9.40638, 51.47332) must reappear with the same
       five tied fetch cells (1.903 .. 3.957).
    Either control failing means the screen is broken, not that the coast
    changed.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box as shapely_box
from shapely.strtree import STRtree
from sklearn.cluster import DBSCAN

import wide_receptor_screen as wrs
from wide_receptor_screen import (  # parameters imported, never re-declared
    BED_GPKG,
    CLUSTER_EPS_M,
    CLUSTER_MIN_N,
    FETCH_EXCLUSION_MAX,
    FETCH_RASTER,
    FETCH_SEARCH_M,
    HAB_SEARCH_M,
    ITM,
    MODEL_PRED,
    MODEL_REPORT,
    NPWS_SHP,
    NPWS_TARGET,
    SHORE_DIST_M,
    SHORE_DIST_STRICT_M,
    TIE_TOL_M,
    WGS,
    FetchSampler,
)

# ----------------------------------------------------------------------
# SEARCH BOXES
#
# (name, county, lon_min, lat_min, lon_max, lat_max)
#
# Consecutive boxes OVERLAP so that no length of coast falls between them.
# Every box was checked against a list of named coastal settlements before
# the run (see docs note). The first box reproduces the Phase A extent and
# bands verbatim.
#
# DELIBERATE EASTERN LIMITS, so the searched extent is honest:
#   - the inner Shannon estuary east of -9.05 (Foynes to Limerick) is not
#     searched: it is estuarine, its fetch is an order of magnitude below
#     the gate, and it is not Atlantic frontage;
#   - the south coast (Cork east of -9.30, Waterford, Wexford) is not
#     searched: not Atlantic seaboard, and outside the brief;
#   - the box at Inishowen runs to -6.95, which puts a short length of the
#     Northern Ireland shore of Lough Foyle inside the extent. Any cluster
#     there is labelled and reported, not silently dropped.
# ----------------------------------------------------------------------

SEARCH_BOXES: list[tuple[str, str, tuple[float, float, float, float]]] = [
    # Phase A extent, re-run unchanged as the regression test.
    ("westcork_kerry_sw",        "Cork/Kerry",    (-10.60, 51.42, -9.30, 52.30)),
    ("kerry_dingle_n_tralee",    "Kerry",         (-10.60, 52.20, -9.55, 52.60)),
    ("kerry_n_shannon_mouth",    "Kerry",         (-9.95, 52.40, -9.05, 52.78)),
    ("clare_loophead_shannon_n", "Clare",         (-9.95, 52.55, -9.05, 52.85)),
    ("clare_w",                  "Clare",         (-9.60, 52.80, -8.95, 53.20)),
    ("galway_bay_aran",          "Galway",        (-9.95, 53.00, -8.85, 53.35)),
    ("connemara",                "Galway",        (-10.30, 53.20, -9.30, 53.62)),
    ("mayo_killary_clew",        "Mayo",          (-10.30, 53.50, -9.15, 53.95)),
    ("mayo_achill_erris",        "Mayo",          (-10.35, 53.85, -9.35, 54.40)),
    ("mayo_n_killala_sligo_w",   "Mayo/Sligo",    (-10.10, 54.05, -8.30, 54.45)),
    ("sligo_donegal_bay_s",      "Sligo/Donegal", (-8.90, 54.20, -8.00, 54.72)),
    ("donegal_sw",               "Donegal",       (-8.95, 54.55, -8.05, 54.90)),
    ("donegal_w",                "Donegal",       (-8.90, 54.85, -8.05, 55.22)),
    ("donegal_nw",               "Donegal",       (-8.50, 54.98, -7.65, 55.38)),
    ("donegal_n_inishowen",      "Donegal",       (-7.95, 54.95, -6.95, 55.45)),
]

# The Phase A box must use its ORIGINAL bands, or the Overpass cache key
# changes and the regression test silently re-downloads a newer OSM
# snapshot instead of reproducing the 2026-08-27T17:52Z one.
PHASE_A_BOX = "westcork_kerry_sw"
BAND_DEG = 0.20          # latitude band height for every other box
COURTESY_SLEEP_S = 12.0  # between Overpass queries; 4 s triggered HTTP 429 rate-limiting

# The step-2 rule for calling a site's mapping too coarse to train on.
# Reused here as an evidence-quality label, not as a filter.
COARSE_MEDIAN_HA = 50.0

OUT_DIR = Path("outputs")
OUT_ALL = OUT_DIR / "national_receptor_screen.csv"
OUT_CAND = OUT_DIR / "national_receptor_screen_candidates.csv"
OUT_GAP = OUT_DIR / "national_receptor_screen_gap.csv"
OUT_SUMMARY = OUT_DIR / "national_receptor_screen_summary.json"
OUT_LAM = OUT_DIR / "national_receptor_screen_laminaria.geojson"
OUT_BLD = OUT_DIR / "national_receptor_screen_buildings.geojson"

CONTROLS = {
    "baltimore": (-9.37434, 51.48362),
    "sherkin": (-9.40638, 51.47332),
}
CONTROL_MATCH_M = 400.0


def bands_for(bbox: tuple[float, float, float, float], name: str):
    """Latitude bands for one search box."""
    if name == PHASE_A_BOX:
        return wrs.OVERPASS_LAT_BANDS
    lo, hi = bbox[1], bbox[3]
    n = max(1, int(np.ceil((hi - lo) / BAND_DEG)))
    edges = np.linspace(lo, hi, n + 1)
    return tuple((round(float(edges[i]), 4), round(float(edges[i + 1]), 4))
                 for i in range(n))


def fetch_all_boxes():
    """Buildings, coastline and place nodes for every search box.

    Calls the Phase A fetchers unmodified by rebinding their module-level
    EXTENT. Returns three WGS84 GeoDataFrames plus a per-box input count.
    """
    blds, coasts, places, per_box = [], [], [], {}
    for i, (name, county, bbox) in enumerate(SEARCH_BOXES, 1):
        bands = bands_for(bbox, name)
        print(f"\n-- box {i}/{len(SEARCH_BOXES)}: {name} ({county}) {bbox} "
              f"{len(bands)} band(s)")
        wrs.EXTENT = bbox                      # the fetchers read this global
        b = wrs.fetch_buildings(bands)
        time.sleep(COURTESY_SLEEP_S)
        c = wrs.fetch_coastline(bands)
        time.sleep(COURTESY_SLEEP_S)
        try:
            p = wrs.fetch_places()
        except Exception as exc:               # noqa: BLE001
            print(f"   places failed for {name}: {exc}")
            p = gpd.GeoDataFrame({"name": [], "place": []},
                                 geometry=[], crs=WGS)
        time.sleep(COURTESY_SLEEP_S)
        b["box"] = name
        blds.append(b)
        coasts.append(c)
        if len(p):
            places.append(p)
        per_box[name] = {"county": county, "bbox": list(bbox),
                         "bands": len(bands), "buildings": int(len(b)),
                         "coastline_ways": int(len(c)), "places": int(len(p))}
    bld = gpd.GeoDataFrame(pd.concat(blds, ignore_index=True), crs=WGS)
    coast = gpd.GeoDataFrame(pd.concat(coasts, ignore_index=True), crs=WGS)
    place = gpd.GeoDataFrame(pd.concat(places, ignore_index=True), crs=WGS)
    # Boxes overlap, so the same OSM object is returned by two queries.
    bld = bld[~bld.geometry.duplicated()].reset_index(drop=True)
    coast = coast[~coast.geometry.duplicated()].reset_index(drop=True)
    place = place[~place.geometry.duplicated()].reset_index(drop=True)
    return bld, coast, place, per_box


# Subtidal layer-21 communities that were DETERMINED by an NPWS CO Series
# dive/video survey, as opposed to inferred from a substrate coverage.
DETERMINED_COMMUNITIES = ("laminaria-dominated reef", "faunal turf reef")
UNDETERMINED_COMMUNITY = "geogenic reef"


def load_npws_national():
    """NPWS Reef Inventory layer 21, clipped to the union of search boxes.

    Returns (laminaria, faunal-turf, geogenic, quality dict, provenance dict),
    all SUBTIDAL only. The intertidal classes are counted and dropped: they
    are a different zone and carry no information about subtidal Laminaria.
    """
    g = gpd.read_file(NPWS_SHP)
    keep = np.zeros(len(g), dtype=bool)
    gb = g.geometry.bounds
    for _, _, (x0, y0, x1, y1) in SEARCH_BOXES:
        keep |= ((gb["maxx"] >= x0) & (gb["minx"] <= x1)
                 & (gb["maxy"] >= y0) & (gb["miny"] <= y1)).to_numpy()
    g = g[keep].to_crs(ITM).copy()

    # ------------------------------------------------------------------
    # DEDUPLICATE. Found 2026-08-27 while checking why the Loop Head
    # candidate reported 164.87 ha of Laminaria within 1 km: the shapefile
    # carries the same polygon more than once, with IDENTICAL geometry AND
    # identical attributes (same Id, Site_code, Community, Extent, Source).
    # Nationally 624 of the 1 936 Laminaria polygons are exact duplicates
    # and the summed area is inflated 2.10x (54 913 ha raw, 26 158 ha
    # deduplicated). Per site the factor runs from 1.0x (Kenmare, clean) to
    # 3.0x (Clew Bay, Galway Bay).
    #
    # A duplicate does NOT change a point-in-polygon or a rasterised class
    # mask, so the step-2 model is unaffected and the locked 1.75 ha Sherkin
    # bed - which comes from the model, not from polygon area - does not
    # move. What it does corrupt is any SUM of area, which is exactly what
    # the habitat term of this screen reports. Dedup by exact geometry is
    # the conservative fix: it removes only rows that are byte-identical in
    # geometry, never rows that merely overlap.
    # ------------------------------------------------------------------
    n_before = len(g)
    dup = g.geometry.to_wkb().duplicated()
    n_dupes = int(dup.sum())
    g = g[~dup].copy()
    print(f"   NPWS layer 21: dropped {n_dupes} exact duplicate geometries "
          f"of {n_before} ({n_dupes / max(n_before, 1):.1%})")

    g["ha"] = g.geometry.area / 1e4
    comm = g["Community"].astype(str).str.strip().str.lower()
    ext = g["Extent"].astype(str).str.strip().str.lower()
    n_intertidal = int((ext == "intertidal").sum())
    is_sub = ext == "subtidal"
    n_subtidal = int(is_sub.sum())
    lam = g[is_sub & (comm == NPWS_TARGET)].copy()
    turf = g[is_sub & (comm == "faunal turf reef")].copy()
    geo = g[is_sub & (comm == UNDETERMINED_COMMUNITY)].copy()
    provenance = {
        "layer21_rows_in_extent_before_dedup": n_before,
        "exact_duplicate_geometries_dropped": n_dupes,
        "subtidal_polygons": n_subtidal,
        "intertidal_polygons_dropped": n_intertidal,
        "laminaria_sources": lam["Source"].astype(str).value_counts()
            .head(12).to_dict(),
        "faunal_turf_sources": turf["Source"].astype(str).value_counts()
            .head(12).to_dict(),
        "geogenic_sources": geo["Source"].astype(str).value_counts()
            .head(12).to_dict(),
    }

    quality = {}
    for site, sub in lam.groupby("Site_name"):
        med = float(sub["ha"].median())
        quality[str(site)] = {
            "n_polygons": int(len(sub)), "ha": round(float(sub["ha"].sum()), 1),
            "median_polygon_ha": round(med, 3),
            "mapping": "coarse" if med > COARSE_MEDIAN_HA else "fine",
        }
    print(f"   NPWS layer 21 in extent: {len(g)} polygons; subtidal "
          f"{n_subtidal} ({len(lam)} Laminaria-dominated, {len(turf)} "
          f"faunal turf [both community-DETERMINED], {len(geo)} geogenic "
          f"[substrate only, community UNDETERMINED]); "
          f"{n_intertidal} intertidal dropped")
    print(f"   Laminaria total {lam['ha'].sum():.1f} ha across "
          f"{lam['Site_name'].nunique()} sites")
    for s, q in sorted(quality.items(), key=lambda kv: -kv[1]["ha"]):
        print(f"     {str(s)[:46]:<48}{q['ha']:>10.1f} ha  median "
              f"{q['median_polygon_ha']:>8.3f} ha  {q['mapping']}")
    return lam, turf, geo, quality, provenance


def load_model_cells(include_gap_extension: bool = False):
    """Step-2 suitability model v2 predictions (the three West Cork AOIs).

    include_gap_extension is OFF by default and should normally stay off.

    WHY. Part 2 (habitat_gap_model.py) takes this screen's `unmapped` /
    `reef_mapped_community_undetermined` clusters as its input. If this
    screen then folded Part 2's own output back in, those clusters would
    stop being blanks, the gap set would shrink on the next run, and the
    two scripts would chase each other - the answer would depend on how
    many times you had run them. Keeping it off makes this screen a pure
    function of its external inputs, so `outputs/national_receptor_screen*`
    is reproducible from OSM + NPWS + Burrows alone.

    The merged national table is produced by habitat_gap_model.py instead,
    which joins the two layers once, in one direction.
    """
    rep = json.loads(Path(MODEL_REPORT).read_text())
    thr = float(rep["operating_threshold"])
    df = pd.read_csv(MODEL_PRED)
    df["source"] = "step2_westcork"
    ext = OUT_DIR / "habitat_gap_model_cells.csv"
    if include_gap_extension and ext.exists():
        e = pd.read_csv(ext)
        e["source"] = "phaseA_gap_extension"
        df = pd.concat([df, e], ignore_index=True)
        print(f"   + {len(e)} cells from the Part 2 gap extension "
              "(NOT the default; the gap set is now self-referential)")
    elif ext.exists():
        print(f"   ({ext.name} exists and is deliberately NOT loaded - "
              "see load_model_cells docstring)")
    g = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.lon, df.lat),
                         crs=WGS).to_crs(ITM)
    print(f"   model cells: {len(g)}, operating threshold {thr}")
    return g, thr


def box_of(lon: float, lat: float) -> tuple[str, str]:
    for name, county, (x0, y0, x1, y1) in SEARCH_BOXES:
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            return name, county
    return "outside_all_boxes", "?"


# Island-wide bbox for the county lookup. One cached Overpass query.
COUNTY_BBOX = (51.3, -11.0, 55.5, -5.9)   # s, w, n, e


def fetch_counties() -> gpd.GeoDataFrame:
    """Republic of Ireland county boundaries (OSM admin_level 6), as polygons.

    WHY THIS EXISTS
    The county column used to come from SEARCH_BOXES, i.e. from boxes I drew
    by hand. Because the boxes overlap and a cluster is assigned to the first
    box that contains it, that column was WRONG wherever two boxes overlap:
    the run of 2026-08-27 put the Loop Head candidate (-9.933, 52.561, which
    is the Loop Head lighthouse in County Clare) in "kerry_dingle_n_tralee"
    and labelled it Kerry. A hand-drawn box is a fact about the search, not
    about the place, so the county now comes from the boundary data instead
    and `box` keeps its (correct) meaning of "which search box found this".

    Overpass returns the relation members, not assembled rings, so the outer
    ways are polygonized per relation. All 26 relations polygonize; counties
    come back as several polygons each (mainland plus islands), which is what
    an island-rich coast should look like.

    admin_level 6 covers the Republic only. A cluster on the Northern Ireland
    shore of Lough Foyle therefore matches nothing and is labelled as such
    rather than being silently attached to Donegal.
    """
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    s, w, n, e = COUNTY_BBOX
    q = f"""[out:json][timeout:280];
relation["boundary"="administrative"]["admin_level"="6"]({s},{w},{n},{e});
out geom;"""
    payload = wrs.overpass(q)
    names, geoms = [], []
    for el in payload.get("elements", []):
        nm = (el.get("tags") or {}).get("name", "")
        lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                 for m in el.get("members", [])
                 if m.get("role") == "outer" and m.get("type") == "way"
                 and len(m.get("geometry", [])) >= 2]
        if not lines:
            continue
        polys = list(polygonize(unary_union(lines)))
        if not polys:
            print(f"   >>> {nm} did not polygonize; it will match nothing")
            continue
        for p in polys:
            names.append(nm.replace("County ", "").strip())
            geoms.append(p)
    gdf = gpd.GeoDataFrame({"county": names}, geometry=geoms, crs=WGS)
    print(f"   county polygons: {len(gdf)} across "
          f"{gdf['county'].nunique()} counties")
    return gdf


def main() -> int:
    t0 = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("National receptor screen - Phase A. NO EURO VALUE IS COMPUTED HERE.")
    print(f"Pre-registered fetch gate FETCH_EXCLUSION_MAX = {FETCH_EXCLUSION_MAX} "
          "(imported, unchanged)\n")

    print("== habitat layers ==")
    lam, turf, geo, quality, provenance = load_npws_national()
    lam[["Site_name", "Community", "Extent", "Source", "ha", "geometry"]] \
        .to_crs(WGS).to_file(OUT_LAM, driver="GeoJSON")
    cells, thr = load_model_cells()
    bed = gpd.read_file(BED_GPKG, layer="kelp_cells").to_crs(ITM)
    bed_union = bed.geometry.buffer(25, cap_style="square").union_all()
    print(f"   locked Sherkin bed: {len(bed)} cells, {bed_union.area/1e4:.2f} ha")

    print("\n== OSM ==")
    bld, coast, places, per_box = fetch_all_boxes()
    print(f"\n   buildings total (deduplicated): {len(bld)}")
    print(f"   coastline ways (deduplicated):  {len(coast)}")
    print(f"   named places:                   {len(places)}")
    counties = fetch_counties()
    if bld.empty or coast.empty:
        print("OSM returned nothing. Zero here is a bug, not a finding.")
        return 1

    bld = bld.to_crs(ITM)
    coast = coast.to_crs(ITM)
    places = places.to_crs(ITM)

    print("\n== shore proximity ==")
    tree = STRtree(coast.geometry.values)
    near_idx = tree.nearest(bld.geometry.values)
    bld["dist_shore_m"] = [
        bld.geometry.values[i].distance(coast.geometry.values[j])
        for i, j in enumerate(near_idx)
    ]
    shore = bld[bld["dist_shore_m"] <= SHORE_DIST_M].copy()
    print(f"   buildings within {SHORE_DIST_M:.0f} m of coastline: "
          f"{len(shore)} of {len(bld)}")

    print("\n== clustering ==")
    xy = np.c_[shore.geometry.x.values, shore.geometry.y.values]
    labels = DBSCAN(eps=CLUSTER_EPS_M, min_samples=CLUSTER_MIN_N).fit_predict(xy)
    shore["cluster"] = labels
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"   clusters: {n_clusters} "
          f"(+{int((labels == -1).sum())} isolated shore buildings dropped)")

    print("\n== per-cluster evidence ==")
    sampler = FetchSampler(FETCH_RASTER)
    to_wgs = Transformer.from_crs(ITM, WGS, always_xy=True)
    lam_tree = STRtree(lam.geometry.values)
    turf_tree = STRtree(turf.geometry.values)
    geo_tree = STRtree(geo.geometry.values)
    place_tree = STRtree(places.geometry.values)
    counties_itm = counties.to_crs(ITM)
    county_tree = STRtree(counties_itm.geometry.values)
    county_names = counties_itm["county"].tolist()
    cell_geoms = cells.geometry.values
    cell_tree = STRtree(cell_geoms)
    suit = cells["suitability"].to_numpy(float)
    assessed = cells["assessed"].to_numpy(int)
    rows = []
    try:
        for k, cid in enumerate(sorted(set(labels))):
            if cid == -1:
                continue
            if k % 250 == 0:
                print(f"   ... cluster {k}/{n_clusters}")
            sub = shore[shore["cluster"] == cid]
            cx, cy = float(sub.geometry.x.mean()), float(sub.geometry.y.mean())
            cp = Point(cx, cy)
            lon, lat = to_wgs.transform(cx, cy)

            f = sampler.sample(cx, cy)

            # ---- tier 1a: NPWS Laminaria-dominated reef -------------------
            hits = lam_tree.query(cp.buffer(HAB_SEARCH_M), predicate="intersects")
            if len(hits):
                lam_sub = lam.iloc[hits]
                lam_dist = float(min(g.distance(cp) for g in lam_sub.geometry))
                lam_ha = float(lam_sub.geometry.intersection(
                    cp.buffer(HAB_SEARCH_M)).area.sum() / 1e4)
                lam_sites = sorted(set(str(s) for s in lam_sub["Site_name"]))
                lam_site = "; ".join(lam_sites)
                quals = {quality.get(s, {}).get("mapping", "?") for s in lam_sites}
                lam_quality = "fine" if "fine" in quals else ("coarse" if quals else "")
            else:
                lam_dist, lam_ha, lam_site, lam_quality = np.nan, 0.0, "", ""

            # ---- tier 1b: faunal turf reef. SAME survey provenance as the
            # Laminaria polygons (NPWS CO Series dive/video), so a hit here
            # with no Laminaria hit is real evidence of ABSENCE.
            th = turf_tree.query(cp.buffer(HAB_SEARCH_M), predicate="intersects")
            if len(th):
                t_sub = turf.iloc[th]
                turf_dist = float(min(g.distance(cp) for g in t_sub.geometry))
                turf_site = "; ".join(sorted(set(
                    str(x) for x in t_sub["Site_name"]))[:3])
                turf_n = int(len(t_sub))
            else:
                turf_dist, turf_site, turf_n = np.nan, "", 0

            # ---- tier 1c: geogenic reef. Substrate coverage only
            # (FinalPHTCoverage / EUNIS Predicted 2007). Says reef is there,
            # says NOTHING about the community. NOT absence evidence - it
            # leaves the cluster in the gap set.
            gh = geo_tree.query(cp.buffer(HAB_SEARCH_M), predicate="intersects")
            if len(gh):
                g_sub = geo.iloc[gh]
                geo_dist = float(min(g.distance(cp) for g in g_sub.geometry))
                geo_ha = float(g_sub.geometry.intersection(
                    cp.buffer(HAB_SEARCH_M)).area.sum() / 1e4)
                geo_src = "; ".join(sorted(set(
                    str(x) for x in g_sub["Source"]))[:2])
                geo_n = int(len(g_sub))
            else:
                geo_dist, geo_ha, geo_src, geo_n = np.nan, 0.0, "", 0

            # ---- tier 2: suitability model v2 -----------------------------
            ci = cell_tree.query(cp.buffer(HAB_SEARCH_M * 1.02),
                                 predicate="intersects")
            if len(ci):
                d = np.array([cell_geoms[j].distance(cp) for j in ci])
                ci = ci[d <= HAB_SEARCH_M]          # exact radius, not the buffer
            n_cells = int(len(ci))
            if n_cells:
                s_in = suit[ci]
                a_in = assessed[ci]
                n_pos = int((s_in >= thr).sum())
                n_pos_assessed = int(((s_in >= thr) & (a_in == 1)).sum())
                model_max = float(s_in.max())
            else:
                n_pos = n_pos_assessed = 0
                model_max = np.nan

            pj = place_tree.nearest(cp)
            place = places.iloc[pj]
            place_d = float(place.geometry.distance(cp))

            bname, box_county = box_of(lon, lat)
            ci_c = county_tree.query(cp, predicate="within")
            if len(ci_c):
                county = county_names[int(ci_c[0])]
            else:
                # No Republic-of-Ireland county contains it. On this coast
                # that means the Northern Ireland shore of Lough Foyle, or a
                # centroid that fell just outside the coastline polygon.
                county = "no RoI county (NI shore or off-boundary)"

            # ---- the five-way habitat evidence state (see module docstring)
            if len(hits) or n_pos_assessed > 0:
                hab_state = "laminaria_present"
            elif turf_n > 0:
                hab_state = "surveyed_not_laminaria"
            elif geo_n > 0:
                hab_state = "reef_mapped_community_undetermined"
            elif n_cells > 0:
                hab_state = "modelled_no_laminaria"
            else:
                hab_state = "unmapped"

            has_hab = bool(len(hits) > 0 or n_pos_assessed > 0)
            fetch_strict = bool(np.isfinite(f["fetch_nearest_min"])
                                and f["fetch_nearest_min"] > FETCH_EXCLUSION_MAX)
            fetch_lenient = bool(np.isfinite(f["fetch_nearest_max"])
                                 and f["fetch_nearest_max"] > FETCH_EXCLUSION_MAX)
            rows.append({
                "box": bname, "county": county, "box_county_label": box_county,
                "nearest_place": f"{place['name']} ({place['place']}, "
                                 f"{place_d/1000:.1f} km)",
                "cluster": int(cid),
                "n_buildings_200m": int(len(sub)),
                "n_buildings_100m": int((sub["dist_shore_m"]
                                         <= SHORE_DIST_STRICT_M).sum()),
                "min_dist_shore_m": round(float(sub["dist_shore_m"].min()), 1),
                "lon": round(lon, 5), "lat": round(lat, 5),
                "fetch_nearest_min": round(f["fetch_nearest_min"], 3)
                    if np.isfinite(f["fetch_nearest_min"]) else np.nan,
                "fetch_nearest_max": round(f["fetch_nearest_max"], 3)
                    if np.isfinite(f["fetch_nearest_max"]) else np.nan,
                "n_tied_sea_cells": f["n_tied"],
                "fetch_max_2km": round(f["fetch_max"], 3)
                    if np.isfinite(f["fetch_max"]) else np.nan,
                "dist_to_sea_cell_m": round(f["dist_to_sea_m"], 0)
                    if np.isfinite(f["dist_to_sea_m"]) else np.nan,
                "npws_lam_dist_m": round(lam_dist, 0)
                    if np.isfinite(lam_dist) else np.nan,
                "npws_lam_ha_1km": round(lam_ha, 2),
                "npws_site": lam_site,
                "npws_mapping_quality": lam_quality,
                "npws_turf_n_1km": turf_n,
                "npws_turf_dist_m": round(turf_dist, 0)
                    if np.isfinite(turf_dist) else np.nan,
                "npws_turf_site": turf_site,
                "npws_geogenic_n_1km": geo_n,
                "npws_geogenic_dist_m": round(geo_dist, 0)
                    if np.isfinite(geo_dist) else np.nan,
                "npws_geogenic_ha_1km": round(geo_ha, 2),
                "npws_geogenic_source": geo_src,
                "model_cells_1km": n_cells,
                "model_pos_1km": n_pos,
                "model_pos_assessed_1km": n_pos_assessed,
                "model_max_suit_1km": round(model_max, 3)
                    if np.isfinite(model_max) else np.nan,
                "habitat_evidence": hab_state,
                "locked_bed_dist_m": round(float(bed_union.distance(cp)), 0),
                "pass_fetch_strict": fetch_strict,
                "pass_fetch": fetch_lenient,
                "fetch_tie_ambiguous": bool(fetch_lenient and not fetch_strict),
                "pass_habitat": has_hab,
                "candidate": bool(fetch_lenient and has_hab),
            })
    finally:
        sampler.close()

    df = pd.DataFrame(rows)
    if df.empty:
        print("No shore-proximate building clusters anywhere. That is a bug.")
        return 1

    shore[shore["cluster"] >= 0].assign(
        dist_shore_m=lambda d: d.dist_shore_m.round(1)
    ).to_crs(WGS).to_file(OUT_BLD, driver="GeoJSON")

    df = df.sort_values(
        ["candidate", "pass_fetch", "fetch_nearest_max", "npws_lam_ha_1km"],
        ascending=[False, False, False, False]).reset_index(drop=True)
    df.to_csv(OUT_ALL, index=False)
    cand = df[df["candidate"]]
    cand.to_csv(OUT_CAND, index=False)

    # The Part 2 input: passes fetch, but NO NPWS polygon of any community
    # within 1 km, so the habitat term is unmapped rather than negative.
    GAP_STATES = ("unmapped", "reef_mapped_community_undetermined")
    gap = df[(df["pass_fetch"]) & (df["habitat_evidence"].isin(GAP_STATES))]
    gap.to_csv(OUT_GAP, index=False)
    print(f"\n   fetch-passing clusters whose habitat term is a "
          f"genuine blank ({' or '.join(GAP_STATES)}): "
          f"{len(gap)}  -> {OUT_GAP}")

    # ---- controls ----
    to_itm = Transformer.from_crs(WGS, ITM, always_xy=True)
    cxy = np.array([to_itm.transform(r.lon, r.lat) for r in df.itertuples()])
    ctrl_out = {}
    for cname, (clon, clat) in CONTROLS.items():
        px, py = to_itm.transform(clon, clat)
        d = np.hypot(cxy[:, 0] - px, cxy[:, 1] - py)
        j = int(np.argmin(d))
        found = bool(d[j] <= CONTROL_MATCH_M)
        ctrl_out[cname] = {
            "found": found, "match_dist_m": round(float(d[j]), 1),
            "row": df.iloc[j][["box", "nearest_place", "lon", "lat",
                               "n_buildings_200m", "fetch_nearest_min",
                               "fetch_nearest_max", "n_tied_sea_cells",
                               "pass_fetch", "pass_fetch_strict",
                               "habitat_evidence"]].to_dict() if found else None,
        }

    searched_km2 = 0.0
    for _, _, (x0, y0, x1, y1) in SEARCH_BOXES:
        searched_km2 += (x1 - x0) * 111.32 * np.cos(np.radians((y0 + y1) / 2)) \
                        * (y1 - y0) * 110.57
    summary = {
        "run_utc": t0,
        "note": "Phase A only. No euro value computed. Receptor test is shore "
                "proximity, not flood exposure: no OPW layer (licence) and no DEM.",
        "search_boxes": [{"name": n, "county": c, "bbox": list(b)}
                         for n, c, b in SEARCH_BOXES],
        "search_boxes_gross_km2_with_overlap": round(searched_km2, 0),
        "parameters": {
            "SHORE_DIST_M": SHORE_DIST_M, "CLUSTER_EPS_M": CLUSTER_EPS_M,
            "CLUSTER_MIN_N": CLUSTER_MIN_N, "FETCH_SEARCH_M": FETCH_SEARCH_M,
            "TIE_TOL_M": TIE_TOL_M, "HAB_SEARCH_M": HAB_SEARCH_M,
            "FETCH_EXCLUSION_MAX": FETCH_EXCLUSION_MAX,
            "FETCH_EXCLUSION_MAX_source": "pre-registered 2026-08-11 in "
                                          "src/mizen_receptor_screen.py; imported "
                                          "here, not re-declared, and not tuned",
            "model_threshold": thr,
            "COARSE_MEDIAN_HA": COARSE_MEDIAN_HA,
        },
        "inputs_per_box": per_box,
        "inputs": {
            "osm_buildings_total": int(len(bld)),
            "osm_buildings_within_shore_dist": int(len(shore)),
            "osm_coastline_ways": int(len(coast)),
            "osm_places": int(len(places)),
            "npws_laminaria_polygons": int(len(lam)),
            "npws_laminaria_ha": round(float(lam["ha"].sum()), 1),
            "npws_laminaria_by_site": quality,
            "npws_faunal_turf_polygons": int(len(turf)),
            "npws_geogenic_polygons": int(len(geo)),
            "npws_provenance": provenance,
            "model_cells_total": int(len(cells)),
            "opw_flood_layer_used": False,
            "elevation_used": False,
        },
        "results": {
            "clusters": int(len(df)),
            "clusters_pass_fetch_lenient": int(df["pass_fetch"].sum()),
            "clusters_pass_fetch_strict": int(df["pass_fetch_strict"].sum()),
            "clusters_fetch_tie_ambiguous": int(df["fetch_tie_ambiguous"].sum()),
            "clusters_pass_habitat": int(df["pass_habitat"].sum()),
            "candidates_lenient": int(len(cand)),
            "candidates_strict": int((df["candidate"]
                                      & df["pass_fetch_strict"]).sum()),
            "habitat_evidence_counts": df["habitat_evidence"]
                .value_counts().to_dict(),
            "fetch_passing_habitat_evidence_counts": df[df["pass_fetch"]]
                ["habitat_evidence"].value_counts().to_dict(),
            "clusters_by_box": df.groupby("box").size().to_dict(),
            "pass_fetch_by_box": df.groupby("box")["pass_fetch"].sum()
                .astype(int).to_dict(),
            "pass_habitat_by_box": df.groupby("box")["pass_habitat"].sum()
                .astype(int).to_dict(),
            "clusters_by_county": df.groupby("county").size().to_dict(),
            "pass_fetch_by_county": df.groupby("county")["pass_fetch"].sum()
                .astype(int).to_dict(),
            "candidates_by_county": df[df["candidate"]].groupby("county")
                .size().to_dict(),
        },
        "controls": ctrl_out,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))

    pd.set_option("display.width", 260)
    show = ["box", "nearest_place", "n_buildings_200m", "lon", "lat",
            "fetch_nearest_min", "fetch_nearest_max", "npws_lam_ha_1km",
            "habitat_evidence", "pass_fetch_strict", "pass_habitat", "candidate"]
    print("\n" + "=" * 118)
    print(df.head(45)[show].to_string(index=False))
    print("=" * 118)
    print(json.dumps(summary["results"], indent=2))
    for cname, c in ctrl_out.items():
        print(f"control {cname}: {'FOUND' if c['found'] else 'NOT FOUND - SCREEN BROKEN'} "
              f"{c['row'] if c['found'] else ''}")
    print(f"\nVERDICT: {len(cand)} cluster(s) pass habitat AND the "
          f"{FETCH_EXCLUSION_MAX} fetch gate under the lenient tie rule; "
          f"{int((cand['pass_fetch_strict']).sum())} under the strict rule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
