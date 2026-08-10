#!/usr/bin/env python3
"""
swell_direction.py — settles the swell-direction assumption with data.

WHY THIS EXISTS
---------------
Step 3B2 showed the amount of coastal floodplain sitting in the wave shadow of
the surviving kelp cells swings by a factor of five depending on which swell
direction is assumed (0.47 ha for SW, 2.50 ha for S). "West Cork's dominant
swell is from the southwest" was an assumption carried in from general
knowledge, never checked against data. It is load-bearing, so it gets checked.

PRODUCT
-------
IBI_MULTIYEAR_WAV_005_006 — Atlantic Iberian-Biscay-Irish Ocean Wave Reanalysis.
MFWAM model, 1/36 degree (~2-3 km), hourly, 1980 to present minus ~4 months.
Chosen over the global WAVERYS product (GLOBAL_MULTIYEAR_WAV_001_032, 1/5 deg
~20 km) because 20 km cannot resolve anything near Roaringwater Bay.

Needs a Copernicus Marine account. NOTE: this is a DIFFERENT account from the
Copernicus Data Space Ecosystem one used for Sentinel-2. Register separately at
marine.copernicus.eu, then run `copernicusmarine login` once.

    pip install copernicusmarine xarray netcdf4

THE STATISTICS — READ THIS, IT IS THE POINT OF THE SCRIPT
---------------------------------------------------------
Three things are easy to get wrong here and all three change the answer.

1. Directions are circular. The arithmetic mean of 350 deg and 10 deg is 180,
   which is backwards. This script uses vector (circular) means throughout.

2. "From" versus "towards". The product follows the oceanographic convention:
   VMDR is the direction waves come FROM, 0 = from north, clockwise. The wave
   shadow lies in the direction waves travel TOWARDS, which is from + 180.
   Getting this backwards puts the shadow on the wrong side of the island.

3. The mean sea state is the wrong statistic. Avoided damage is driven by
   storms, not by average days. A calm summer easterly and a January Atlantic
   storm both count as one hour in a plain frequency rose. This script reports
   three roses: plain frequency, energy-weighted (energy ~ Hs^2), and
   high-energy only (Hs above a percentile). Use the last two for the shadow.

LIMITATION THAT MUST BE STATED ON THE SLIDE
-------------------------------------------
This is the OFFSHORE direction. As waves cross the shelf and shoal they refract
towards shore-normal, so the direction actually striking the coast will be
rotated from this figure, typically towards shore-perpendicular. Refraction is
not modelled here. That is a 48-hour simplification and it belongs in the same
list as the unmodelled shoaling between the bed and the shoreline.

Usage:
    python src/swell_direction.py --download
    python src/swell_direction.py --nc data/cmems/ibi_wav_sherkin.nc
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATASET_ID = "cmems_mod_ibi_wav_my_0.027deg_PT1H-i"
PRODUCT_ID = "IBI_MULTIYEAR_WAV_005_006"

# Total sea state, and the primary swell partition.
VARS = ["VHM0", "VMDR", "VHM0_SW1", "VMDR_SW1"]

SECTORS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def need(mod: str, pip_name: str | None = None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"ERROR: {mod} not installed.\n  pip install {pip_name or mod}\n"
                 f"  Then record it in DEPENDENCIES.md with version and licence.")


# ---------------------------------------------------------------------------
# circular statistics
# ---------------------------------------------------------------------------
def circular_mean(deg: np.ndarray, weights: np.ndarray | None = None) -> float:
    """Vector mean of directions in degrees. Never use np.mean on angles."""
    r = np.radians(deg)
    w = np.ones_like(r) if weights is None else weights
    s, c = np.sum(w * np.sin(r)), np.sum(w * np.cos(r))
    return float((np.degrees(np.arctan2(s, c)) + 360.0) % 360.0)


def circular_concentration(deg: np.ndarray, weights: np.ndarray | None = None) -> float:
    """Resultant length R in 0..1. R near 1 = tightly clustered directions,
    R near 0 = no dominant direction and the mean is meaningless."""
    r = np.radians(deg)
    w = np.ones_like(r) if weights is None else weights
    s, c = np.sum(w * np.sin(r)), np.sum(w * np.cos(r))
    return float(np.hypot(s, c) / np.sum(w))


def to_sector(deg: np.ndarray) -> np.ndarray:
    idx = np.floor(((deg % 360.0) + 11.25) / 22.5).astype(int) % 16
    return np.array(SECTORS)[idx]


def rose(deg: np.ndarray, weights: np.ndarray | None = None) -> pd.Series:
    w = np.ones_like(deg, dtype=float) if weights is None else weights
    s = pd.Series(w).groupby(to_sector(deg)).sum()
    s = s.reindex(SECTORS).fillna(0.0)
    return 100.0 * s / s.sum()


def print_rose(title: str, pct: pd.Series, top: int = 5) -> None:
    print(f"\n  {title}")
    for name, v in pct.sort_values(ascending=False).head(top).items():
        bar = "#" * int(round(v / 2))
        print(f"    from {name:<4} {v:5.1f} %  {bar}")


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--nc", default="data/cmems/ibi_wav_sherkin.nc")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2024-12-31")
    # Box offshore and south-west of Sherkin. Coastal grid cells are land-masked,
    # so the box deliberately sits in open water rather than on the cells.
    ap.add_argument("--lon-min", type=float, default=-9.60)
    ap.add_argument("--lon-max", type=float, default=-9.30)
    ap.add_argument("--lat-min", type=float, default=51.30)
    ap.add_argument("--lat-max", type=float, default=51.47)
    # Centroid of the 7 surviving cells. The nearest WET grid point to this is
    # used; the cells themselves sit on land-masked model cells.
    ap.add_argument("--near-lat", type=float, default=51.4652)
    ap.add_argument("--near-lon", type=float, default=-9.4051)
    ap.add_argument("--hs-pct", type=float, default=90.0,
                    help="percentile of Hs defining a high-energy sea state")
    ap.add_argument("--out", default="outputs/model/swell_direction")
    args = ap.parse_args()

    xr = need("xarray")

    nc = Path(args.nc)
    if args.download:
        cm = need("copernicusmarine")
        nc.parent.mkdir(parents=True, exist_ok=True)
        print(f"Subsetting {DATASET_ID}\n  {args.start} .. {args.end}\n"
              f"  lon {args.lon_min}..{args.lon_max}  lat {args.lat_min}..{args.lat_max}")
        cm.subset(
            dataset_id=DATASET_ID,
            variables=VARS,
            minimum_longitude=args.lon_min, maximum_longitude=args.lon_max,
            minimum_latitude=args.lat_min, maximum_latitude=args.lat_max,
            start_datetime=args.start, end_datetime=args.end,
            output_filename=nc.name, output_directory=str(nc.parent),
        )
    if not nc.exists():
        sys.exit(f"ERROR: {nc} not found. Run with --download first "
                 f"(needs `copernicusmarine login`).")

    ds = xr.open_dataset(nc)

    # Apply the box to the LOADED file too, not only to the download.
    # (Earlier version applied it only at download time, so re-running against
    # an existing .nc silently ignored the box.)
    lat = ds["latitude"]
    ds = ds.sel(
        latitude=slice(*sorted([args.lat_min, args.lat_max])[:: 1 if float(lat[0]) <= float(lat[-1]) else -1]),
        longitude=slice(args.lon_min, args.lon_max),
    )
    if ds.sizes.get("latitude", 0) == 0 or ds.sizes.get("longitude", 0) == 0:
        sys.exit("ERROR: the box selects no grid points from this file. "
                 "Widen it or re-download.")

    print("=" * 78)
    print(f"IBI WAVE REANALYSIS  {PRODUCT_ID}")
    print("=" * 78)
    print(f"  file        {nc}")
    print(f"  variables   {[v for v in VARS if v in ds]}")
    missing = [v for v in VARS if v not in ds]
    if missing:
        print(f"  MISSING     {missing} — swell partition results will be skipped")
    print(f"  time        {str(ds.time.values[0])[:10]} .. {str(ds.time.values[-1])[:10]}"
          f"   ({ds.sizes['time']} steps)")

    # --- pick the grid point with the most valid data ----------------------
    hs = ds["VHM0"]
    valid = hs.notnull().sum("time")
    flat = valid.stack(pt=("latitude", "longitude"))
    if int(flat.max()) == 0:
        sys.exit("ERROR: every grid point is land-masked. Move the box offshore.")

    # Pick the wet point NEAREST the kelp bed, not the one with the most valid
    # hours. Offshore points usually tie on valid hours, so argmax was really
    # returning whichever point happened to come first in the array.
    wet = flat.where(flat > 0, drop=True)
    wlat = wet["latitude"].values.astype(float)
    wlon = wet["longitude"].values.astype(float)
    dlat = (wlat - args.near_lat) * 111.132
    dlon = (wlon - args.near_lon) * 111.320 * np.cos(np.radians(args.near_lat))
    dkm = np.hypot(dlat, dlon)
    k = int(np.argmin(dkm))
    plat, plon, n_wet = float(wlat[k]), float(wlon[k]), int(wet.values[k])
    print(f"  grid points {int(flat.sizes['pt'])} in box, {int(wet.sizes['pt'])} wet")
    print(f"  reference   {args.near_lat:.4f} N, {abs(args.near_lon):.4f} W  (kelp bed)")
    print(f"  using       {plat:.4f} N, {abs(plon):.4f} W   "
          f"({dkm[k]:.1f} km away, {n_wet} valid hours)")

    sel = ds.sel(latitude=plat, longitude=plon)
    df = pd.DataFrame({v: sel[v].values for v in VARS if v in ds},
                      index=pd.to_datetime(sel.time.values)).dropna(subset=["VHM0", "VMDR"])
    if df.empty:
        sys.exit("ERROR: no valid rows after dropping NaNs.")

    # --- roses --------------------------------------------------------------
    energy = df["VHM0"].to_numpy() ** 2          # wave energy ~ Hs^2
    thr = float(np.percentile(df["VHM0"], args.hs_pct))
    big = df["VHM0"].to_numpy() >= thr

    print(f"\n  Hs          median {df['VHM0'].median():.2f} m, "
          f"p{args.hs_pct:.0f} {thr:.2f} m, max {df['VHM0'].max():.2f} m")
    print(f"  high-energy {int(big.sum())} hours above {thr:.2f} m")

    d = df["VMDR"].to_numpy()
    print("\n" + "=" * 78)
    print("WHERE THE WAVES COME FROM  (total sea state, VMDR)")
    print("=" * 78)
    print_rose("plain frequency (every hour counts once)", rose(d))
    print_rose("energy-weighted (Hs^2) — use this one", rose(d, energy))
    print_rose(f"high-energy only (Hs >= p{args.hs_pct:.0f})", rose(d[big]))

    rows = []
    for label, dd, ww in [
        ("plain", d, None),
        ("energy_weighted", d, energy),
        (f"high_energy_p{args.hs_pct:.0f}", d[big], None),
    ]:
        mu, R = circular_mean(dd, ww), circular_concentration(dd, ww)
        rows.append({"basis": label, "mean_from_deg": round(mu, 1),
                     "travels_to_deg": round((mu + 180) % 360, 1),
                     "concentration_R": round(R, 3), "n": len(dd)})

    if "VMDR_SW1" in df.columns:
        sw = df.dropna(subset=["VMDR_SW1", "VHM0_SW1"])
        if not sw.empty:
            print_rose("primary swell partition only (VMDR_SW1, energy-weighted)",
                       rose(sw["VMDR_SW1"].to_numpy(), sw["VHM0_SW1"].to_numpy() ** 2))
            mu = circular_mean(sw["VMDR_SW1"].to_numpy(), sw["VHM0_SW1"].to_numpy() ** 2)
            rows.append({"basis": "swell_partition_energy_weighted",
                         "mean_from_deg": round(mu, 1),
                         "travels_to_deg": round((mu + 180) % 360, 1),
                         "concentration_R": round(circular_concentration(
                             sw["VMDR_SW1"].to_numpy(), sw["VHM0_SW1"].to_numpy() ** 2), 3),
                         "n": len(sw)})

    res = pd.DataFrame(rows)
    print("\n" + "=" * 78)
    print("CIRCULAR MEANS")
    print("=" * 78)
    print(res.to_string(index=False))

    # --- verdict ------------------------------------------------------------
    key = res[res.basis == "energy_weighted"].iloc[0]
    frm, to, R = key.mean_from_deg, key.travels_to_deg, key.concentration_R
    print("\n" + "-" * 78)
    print(f"USE THIS: waves arrive FROM {frm:.0f} deg ({to_sector(np.array([frm]))[0]}), "
          f"travelling TOWARDS {to:.0f} deg ({to_sector(np.array([to]))[0]}).")
    print(f"  Feed {to:.0f} deg to step3b2 as the shadow-wedge centre.")
    if R < 0.4:
        print(f"  WARNING: concentration R = {R:.2f}. Directions are spread out; a single")
        print( "  mean direction is a poor summary. Run the shadow test for the top 2-3")
        print( "  sectors separately and report the range, not one number.")
    else:
        print(f"  Concentration R = {R:.2f} — directions are reasonably clustered.")
    print("  Remember: this is the OFFSHORE direction. Refraction over the shelf")
    print("  rotates waves towards shore-normal and is not modelled. State it.")
    print("-" * 78)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(out.with_name(out.name + "_summary.csv"), index=False)
    pd.DataFrame({"sector": SECTORS,
                  "plain_pct": rose(d).values,
                  "energy_pct": rose(d, energy).values,
                  f"high_p{args.hs_pct:.0f}_pct": rose(d[big]).values}).to_csv(
        out.with_name(out.name + "_rose.csv"), index=False)
    print(f"\nWrote {out.with_name(out.name + '_summary.csv')}")
    print(f"Wrote {out.with_name(out.name + '_rose.csv')}")
    print(f"\nProduct: {PRODUCT_ID} / {DATASET_ID}")
    print(f"Point:   {plat:.4f} N {plon:.4f} E   Period: {args.start}..{args.end}")
    print(f"Command: {' '.join(sys.argv)}")


if __name__ == "__main__":
    main()