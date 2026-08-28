#!/usr/bin/env python3
"""
site_wave_climate.py — per-site wave direction for the national Phase B run.

WHY THIS EXISTS
---------------
`NOTE_2026-08-28_anaird_phaseB.md` §4 established the bearing test: habitat only
shelters a receptor if it lies between that receptor and the water the waves come
from. The test needs ONE number per site — the direction waves arrive FROM — and
that number must be measured at that site, never carried across from another one.
Sherkin is 212.7 deg, An Aird 252.7 deg; the two are 40 deg apart on the same
coast.

This script is a thin driver around `src/swell_direction.py`, which is the script
that produced BOTH locked directions. Driving the same script rather than
re-implementing its circular statistics is deliberate: it is the same guarantee
that `national_receptor_screen.py` gets by importing `FETCH_EXCLUSION_MAX`
instead of re-typing 3.73.

    PYTHONPATH=src python src/site_wave_climate.py --sites outputs/.../sites.csv

WHAT IT DOES NOT DO
-------------------
It does not choose a direction when CMEMS is unreachable. A site with no wave
data gets `status = unavailable` and is skipped by everything downstream. There
is no fallback direction, because a guessed bearing would silently decide how
much habitat counts as "in front of" a receptor.

CACHING AND OUTAGES
-------------------
Every download is cached at `data/cmems/ibi_wav_c<cluster>.nc` and skipped if the
file is already there and opens. Failures are retried with exponential backoff
across the whole site list, so one site's outage never costs another site's work,
and re-running resumes from the cache.

LIMITATION CARRIED UNCHANGED FROM swell_direction.py
-----------------------------------------------------
This is the OFFSHORE direction. Refraction over the shelf rotates waves towards
shore-normal and is not modelled.

Licence: CMEMS IBI_MULTIYEAR_WAV_005_006, E.U. Copernicus Marine Service
Information. See DEPENDENCIES.md §3.1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
NC_DIR = REPO / "data" / "cmems"
OUT_DIR = REPO / "outputs" / "model"
PY = sys.executable

# Same period and product as the two locked sites. Do not change per site.
START, END = "2015-01-01", "2024-12-31"

# Half-width of the download box in degrees. The IBI grid is 0.027 deg, so
# +/-0.08 lon x +/-0.055 lat is about 6 x 4 grid points -- enough to contain a
# wet cell beside any Atlantic settlement, small enough that ten sites fit on
# disk. Widened automatically (see WIDEN) if every cell in the box is land.
LON_HALF, LAT_HALF = 0.08, 0.055
WIDEN = [(0.08, 0.055), (0.14, 0.095), (0.22, 0.150)]

DOWNLOAD_RETRIES = 4
BACKOFF_S = 20.0


def nc_ok(nc: Path) -> bool:
    """A cached file counts only if it opens and holds the variables we read."""
    if not nc.exists() or nc.stat().st_size < 1_000_000:
        return False
    try:
        import xarray as xr
        with xr.open_dataset(nc) as ds:
            return {"VHM0", "VMDR"} <= set(ds.variables)
    except Exception:
        return False


def download(nc: Path, lon: float, lat: float, half: tuple[float, float]) -> bool:
    """One copernicusmarine.subset call. Returns True on a usable file."""
    import copernicusmarine as cm
    lh, ah = half
    NC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cm.subset(
            dataset_id="cmems_mod_ibi_wav_my_0.027deg_PT1H-i",
            variables=["VHM0", "VMDR", "VHM0_SW1", "VMDR_SW1"],
            minimum_longitude=lon - lh, maximum_longitude=lon + lh,
            minimum_latitude=lat - ah, maximum_latitude=lat + ah,
            start_datetime=START, end_datetime=END,
            output_filename=nc.name, output_directory=str(nc.parent),
            overwrite=True,
        )
    except Exception as exc:                      # network, auth, service
        print(f"      subset failed: {type(exc).__name__}: {str(exc)[:200]}")
        return False
    return nc_ok(nc)


def has_wet_cell(nc: Path) -> bool:
    import xarray as xr
    with xr.open_dataset(nc) as ds:
        return bool((ds["VHM0"].notnull().sum("time") > 0).any())


def run_swell(nc: Path, lon: float, lat: float, half: tuple[float, float],
              out_stem: Path) -> dict | None:
    """Drive src/swell_direction.py unmodified and read its summary back."""
    lh, ah = half
    cmd = [PY, str(REPO / "src" / "swell_direction.py"),
           "--nc", str(nc),
           "--start", START, "--end", END,
           "--lon-min", f"{lon - lh:.4f}", "--lon-max", f"{lon + lh:.4f}",
           "--lat-min", f"{lat - ah:.4f}", "--lat-max", f"{lat + ah:.4f}",
           "--near-lon", f"{lon:.5f}", "--near-lat", f"{lat:.5f}",
           "--out", str(out_stem)]
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    log = out_stem.with_name(out_stem.name + "_run.log")
    log.write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
    summ = out_stem.with_name(out_stem.name + "_summary.csv")
    if p.returncode != 0 or not summ.exists():
        print(f"      swell_direction.py exit {p.returncode}; see {log.name}")
        return None
    df = pd.read_csv(summ)
    row = df[df.basis == "energy_weighted"].iloc[0].to_dict()
    row["all_bases"] = df.to_dict(orient="records")
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", required=True,
                    help="CSV with columns cluster, lon, lat (extra columns kept)")
    ap.add_argument("--out", default="outputs/exposure_screen/site_wave_climate.csv")
    args = ap.parse_args()

    sites = pd.read_csv(args.sites)
    need = {"cluster", "lon", "lat"}
    if not need <= set(sites.columns):
        sys.exit(f"ERROR: --sites needs columns {sorted(need)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("PER-SITE WAVE CLIMATE  —  CMEMS IBI_MULTIYEAR_WAV_005_006")
    print("=" * 78)
    print(f"  sites: {len(sites)}   period {START} .. {END}")
    print("  Directions are measured per site. None is carried from another site.\n")

    rows = []
    for s in sites.itertuples():
        cl = int(s.cluster)
        nc = NC_DIR / f"ibi_wav_c{cl}.nc"
        stem = OUT_DIR / f"swell_direction_c{cl}"
        print(f"--- cluster {cl}  ({s.lon:.5f}, {s.lat:.5f})")

        half = WIDEN[0]
        ok = nc_ok(nc)
        if ok:
            print(f"    cached: {nc.name}")
        for attempt in range(DOWNLOAD_RETRIES):
            if ok:
                break
            half = WIDEN[min(attempt, len(WIDEN) - 1)]
            print(f"    download attempt {attempt + 1}/{DOWNLOAD_RETRIES} "
                  f"box +/-{half[0]}/{half[1]} deg")
            ok = download(nc, float(s.lon), float(s.lat), half)
            if not ok:
                wait = BACKOFF_S * (2 ** attempt)
                print(f"    backing off {wait:.0f}s")
                time.sleep(wait)
        if ok and not has_wet_cell(nc):
            print("    every cell in the box is land-masked; widening once")
            ok = download(nc, float(s.lon), float(s.lat), WIDEN[-1]) and has_wet_cell(nc)
            half = WIDEN[-1]
        if not ok:
            print("    UNAVAILABLE — no wave direction for this site.\n")
            rows.append({"cluster": cl, "status": "unavailable",
                         "wave_from_deg": None, "wave_to_deg": None,
                         "concentration_R": None})
            continue

        res = run_swell(nc, float(s.lon), float(s.lat), half, stem)
        if res is None:
            rows.append({"cluster": cl, "status": "swell_script_failed",
                         "wave_from_deg": None, "wave_to_deg": None,
                         "concentration_R": None})
            print()
            continue
        print(f"    waves FROM {res['mean_from_deg']:.1f} deg, "
              f"travelling TO {res['travels_to_deg']:.1f} deg, "
              f"R = {res['concentration_R']:.3f}, n = {int(res['n'])}\n")
        rows.append({"cluster": cl, "status": "ok",
                     "wave_from_deg": float(res["mean_from_deg"]),
                     "wave_to_deg": float(res["travels_to_deg"]),
                     "concentration_R": float(res["concentration_R"]),
                     "n_hours": int(res["n"]),
                     "basis": "energy_weighted (Hs^2)",
                     "summary_csv": str(stem.with_name(stem.name + "_summary.csv")
                                        .relative_to(REPO)).replace("\\", "/")})

    out = pd.DataFrame(rows)
    out = sites.merge(out, on="cluster", how="left")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print("=" * 78)
    print(out[["cluster", "status", "wave_from_deg", "wave_to_deg",
               "concentration_R"]].to_string(index=False))
    print(f"\nWrote {args.out}")
    print(f"Run finished {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
