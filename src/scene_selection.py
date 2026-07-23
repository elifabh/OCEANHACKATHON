"""
scene_selection.py -- Ocean Hackathon Cork 2026, "Seeing the Invisible Shield"
Step 1 of the kelp detection feasibility test.

PURPOSE
-------
Rank archived Sentinel-2 L1C scenes over a West Cork AOI by their suitability for
SUBTIDAL benthic mapping. Suitability here is dominated by three things:

  1. AOI-LOCAL cloud cover. CLOUDY_PIXEL_PERCENTAGE is a granule-level property
     (110 x 110 km) and is far too strict as a scene filter for a ~5 km bay.
     We therefore use a loose scene filter and compute per-pixel clear fraction
     over the AOI from Cloud Score+ (Pasquarella et al. 2023).
  2. TIDAL HEIGHT at acquisition time. Bottom signal falls off roughly as
     exp(-Kd * z * pathfactor); a 3 m spring range over a 4 m bed is a large
     multiplicative change in the retrievable signal. Observed water level comes
     from the Irish National Tide Gauge Network (Marine Institute, CC-BY 4.0).
  3. SEASON. Solar elevation at the ~11:54 UTC overpass ranges from ~15 deg
     (Dec) to ~61 deg (Jun) at 51.5 N. Incident irradiance varies by ~4x; the
     in-water path length varies by only ~18%. So the seasonal driver is
     available light, not geometry. May-August scenes are strongly preferred.

WHAT THIS SCRIPT DOES NOT DO
----------------------------
It does not detect kelp, and it does not prove kelp is detectable. It only
produces a shortlist of scenes worth putting through ACOLITE. Detection
feasibility is the NEXT step and is still unproven for Irish subtidal
L. hyperborea.

REQUIREMENTS
------------
earthengine-api, pandas, requests   (record versions in DEPENDENCIES.md)
An authenticated Earth Engine session: `earthengine authenticate`
"""

from __future__ import annotations

import io
import sys

import ee
import pandas as pd
import requests

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
EE_PROJECT = "gen-lang-client-0871366385"  # <-- real project ID, not the display name "kelp-ee"

# Candidate AOIs. Keep them small (a few km) -- water optical properties vary
# over short distances, so a per-bay AOI is the right unit, not the MGRS tile.
AOIS = {
    # Primary test site: outer Roaringwater Bay, Sherkin / Baltimore approaches.
    # Inside Roaringwater Bay and Islands SAC (site code 000101, Reefs [1170]).
    "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
    # Clear-water / high-exposure comparison: Mizen Head - Three Castle Head.
    "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
    # NEGATIVE CONTROL: inner Roaringwater Bay near the Ilen outflow. Expected to
    # fail. Included deliberately -- a feasibility test needs a known-bad case to
    # locate the turbidity/CDOM boundary rather than just asserting one exists.
    "inner_ilen": [-9.42, 51.51, -9.34, 51.56],
}

START, END = "2018-01-01", "2025-12-31"
MAX_SCENE_CLOUD = 80          # deliberately loose; real filtering is done per-pixel
MIN_AOI_CLEAR_FRAC = 0.90     # fraction of AOI pixels that must be clear
CS_PLUS_THRESHOLD = 0.60      # Cloud Score+ 'cs_cdf' value above which a pixel is clear
PREFERRED_MONTHS = (5, 6, 7, 8)

# Nearest Irish National Tide Gauge Network station to West Cork.
# Castletownbere Port: 51.649730 N, -9.903538 W. Mean spring range 3.012 m.
# CAVEAT: ~50 km from Roaringwater Bay, so tidal PHASE differs. Treat the value
# as indicative for ranking, and verify the final 3-5 scenes against a local
# prediction before drawing conclusions.
ERDDAP = "https://erddap.marine.ie/erddap/tabledap/IrishNationalTideGaugeNetwork.csv"
GAUGE_BBOX = dict(lat_min=51.63, lat_max=51.67, lon_min=-9.92, lon_max=-9.89)

OUT_CSV = "candidate_scenes.csv"


# --------------------------------------------------------------------------
# PART 1 -- Sentinel-2 inventory with AOI-local cloud
# --------------------------------------------------------------------------
def scene_inventory(aoi_name: str, bbox: list[float]) -> pd.DataFrame:
    """Return one row per S2 L1C scene with the clear-pixel fraction over the AOI."""
    geom = ee.Geometry.Rectangle(bbox)

    cs_plus = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_HARMONIZED")  # L1C -- ACOLITE needs TOA, not L2A
        .filterBounds(geom)
        .filterDate(START, END)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", MAX_SCENE_CLOUD))
        .linkCollection(cs_plus, ["cs_cdf"])
    )

    def clear_fraction(img: ee.Image) -> ee.Feature:
        clear = img.select("cs_cdf").gte(CS_PLUS_THRESHOLD).rename("clear")
        frac = clear.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geom, scale=20, maxPixels=1e9
        ).get("clear")
        return ee.Feature(
            None,
            {
                "aoi": aoi_name,
                "scene_id": img.get("system:index"),
                "datetime_utc": img.date().format("YYYY-MM-dd'T'HH:mm:ss"),
                "granule_cloud_pct": img.get("CLOUDY_PIXEL_PERCENTAGE"),
                "aoi_clear_frac": frac,
                "sun_elev_deg": ee.Number(90).subtract(img.get("MEAN_SOLAR_ZENITH_ANGLE")),
            },
        )

    feats = s2.map(clear_fraction).filter(
        ee.Filter.gte("aoi_clear_frac", MIN_AOI_CLEAR_FRAC)
    )
    rows = feats.getInfo()["features"]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([f["properties"] for f in rows])
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
    return df


# --------------------------------------------------------------------------
# PART 2 -- Observed water level from the Irish National Tide Gauge Network
# --------------------------------------------------------------------------
def list_gauge_stations() -> pd.DataFrame:
    """Print the station_id values ERDDAP actually uses. Run once, then hard-code."""
    r = requests.get(f"{ERDDAP}?station_id&distinct()", timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), skiprows=[1])


def fetch_water_level(start: str, end: str) -> pd.DataFrame:
    """Water level relative to Lowest Astronomical Tide, 5-minute resolution, UTC."""
    query = (
        "time,latitude,longitude,station_id,Water_Level_LAT,QC_Flag"
        f"&time>={start}T00:00:00Z&time<={end}T23:59:59Z"
        f"&latitude>={GAUGE_BBOX['lat_min']}&latitude<={GAUGE_BBOX['lat_max']}"
        f"&longitude>={GAUGE_BBOX['lon_min']}&longitude<={GAUGE_BBOX['lon_max']}"
    )
    r = requests.get(f"{ERDDAP}?{query}", timeout=600)
    r.raise_for_status()
    tide = pd.read_csv(io.StringIO(r.text), skiprows=[1])
    tide["time"] = pd.to_datetime(tide["time"], utc=True)
    return tide.sort_values("time").reset_index(drop=True)


def join_tide(scenes: pd.DataFrame, tide: pd.DataFrame) -> pd.DataFrame:
    """Nearest-in-time join, rejecting matches more than 15 min from the overpass."""
    merged = pd.merge_asof(
        scenes.sort_values("datetime_utc"),
        tide[["time", "Water_Level_LAT"]].rename(columns={"time": "datetime_utc"}),
        on="datetime_utc",
        direction="nearest",
        tolerance=pd.Timedelta("15min"),
    )
    return merged.rename(columns={"Water_Level_LAT": "water_level_LAT_m"})


# --------------------------------------------------------------------------
# PART 3 -- Rank
# --------------------------------------------------------------------------
def rank(df: pd.DataFrame) -> pd.DataFrame:
    """
    Simple transparent ranking. Deliberately NOT a learned or weighted-optimal
    score -- it is a sorting convenience, and every scene on the shortlist still
    gets inspected by eye before use.
    """
    df = df.copy()
    df["month"] = df["datetime_utc"].dt.month
    df["in_preferred_season"] = df["month"].isin(PREFERRED_MONTHS)
    return df.sort_values(
        ["in_preferred_season", "water_level_LAT_m", "aoi_clear_frac"],
        ascending=[False, True, False],
    ).reset_index(drop=True)


def main() -> None:
    ee.Initialize(project=EE_PROJECT)

    frames = []
    for name, bbox in AOIS.items():
        print(f"[ee] {name} ...", file=sys.stderr)
        df = scene_inventory(name, bbox)
        print(f"     {len(df)} scenes with AOI clear fraction >= {MIN_AOI_CLEAR_FRAC}",
              file=sys.stderr)
        if not df.empty:
            frames.append(df)

    if not frames:
        print("No scenes passed. Loosen MIN_AOI_CLEAR_FRAC and retry.", file=sys.stderr)
        return

    scenes = pd.concat(frames, ignore_index=True)
    tide = fetch_water_level(START, END)
    out = rank(join_tide(scenes, tide))
    out.to_csv(OUT_CSV, index=False)

    print(f"\nWrote {OUT_CSV} ({len(out)} rows). Top candidates per AOI:\n")
    cols = ["aoi", "datetime_utc", "aoi_clear_frac", "water_level_LAT_m", "sun_elev_deg"]
    for aoi, grp in out.groupby("aoi"):
        print(f"--- {aoi} ---")
        print(grp[cols].head(5).to_string(index=False), "\n")


if __name__ == "__main__":
    print(list_gauge_stations())