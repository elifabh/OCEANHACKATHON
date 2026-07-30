#!/usr/bin/env python3
"""
light_layer.py - light reaching the seabed, from satellite water clarity.

WHY THIS EXISTS
The multi-site model failed two of its four pre-registered criteria, and both
failures point at the same missing variable.

  inner_roaringwater  537 surveyed non-kelp cells, 82.9% scored as kelp
  Galway Bay          leave-one-site-out AUC 0.573, against 0.92-0.98 elsewhere

Their common feature is in the diagnostics: at Galway Bay the kelp cells sit at
a median 2.5 m and the non-kelp cells at 2.9 m, and at inner Roaringwater the
non-kelp reef sits at a median 7.2 m. Both are shallow, sheltered and turbid.
The model's only strong term is depth, so it calls shallow water kelp, and in
those two places shallow water is not kelp.

Depth was never the causal variable. It was standing in for LIGHT, and the
substitution only works where water clarity is roughly constant. Across an
Irish coast that runs from open Atlantic to silty inner bays it is not.

THE PHYSICS, AND WHY IT IS ONE TERM RATHER THAN TWO
Irradiance falls exponentially with depth:

    E(z) / E(0) = exp(-Kd * z)

Kd is the diffuse attenuation coefficient, in m^-1, and it is measured from
space. So the quantity that actually limits kelp is not z and not Kd but the
product, and a model given z and Kd as two additive terms cannot form it. That
is precisely what we observed: adding a depth x fetch interaction moved the
fetch coefficient from +0.685 to +0.119 and made inner_roaringwater worse
(82.9% -> 87.3%). A statistical interaction was the wrong shape; the physical
combination is the right one.

PRECEDENT, SO THIS IS NOT OUR INVENTION
Saulquin et al. (2013), Remote Sensing of Environment 128:224-233, derive KdPAR
from satellite Kd490 and cross-tabulate the resulting seabed-light fields with
in-situ Laminaria hyperborea observations on Atlantic shores, treating light as
the limiting factor on depth distribution. The same light layer underpins
EuSeaMap's infralittoral zonation. Guiry (seaweed.ie, NUI Galway) records
L. hyperborea growing on rock to 32 m "in optically clear water" while forming
closed communities at 0-24 m - the depth limit is explicitly a function of
clarity, not a constant. Bell et al. (2023), Ecological Modelling 486:110511,
model L. hyperborea across Britain and Ireland driven by wave exposure and
depth-attenuated light, and note the species occupies subtidal rocky reef on
all but the most wave sheltered coastlines.

HONEST LIMITS - ALL THREE GO ON THE SLIDE
  1. We use Kd490 as the attenuation coefficient. The photosynthetically
     relevant quantity is KdPAR, and Saulquin et al. give a conversion we have
     NOT applied. Kd490 is therefore a proxy, and the derived number must be
     called a "relative light index", never "PAR at the seabed". Because AUC is
     rank-based and Kd490 and KdPAR are monotonically related, the model's
     RANKING is largely unaffected; the coefficient magnitude is not
     interpretable as a physical response.
  2. Kd490 comes at 300 m (OLCI) or 100 m (Sentinel-2 HR-OC) while our grid is
     50 m. The light term's effective resolution is the coarser one and any
     accuracy figure must say so.
  3. A satellite sees the surface. Kd is a water-column average and says
     nothing about local shading by topography or by the kelp canopy itself.

WHAT THIS SCRIPT DOES NOT DO
It does not fit anything. It produces one covariate and the evidence that the
covariate is real. Wiring it into the model is the next step, and it should
only happen after the numbers below have been looked at.

ACCESS
Copernicus Marine requires a free account, separate from the Copernicus Data
Space account. Register at marine.copernicus.eu, then once:

    copernicusmarine login

Dataset IDs change between product versions, so this script does NOT hard-code
one. Run --describe to list the datasets that actually carry KD490 for our
region today, then pass the chosen one to --fetch.

Dependencies: numpy (BSD-3), xarray (Apache-2.0), copernicusmarine (EUPL-1.2 -
CONFIRM before publishing), rasterio (BSD-3), pyproj (MIT).

Data: E.U. Copernicus Marine Service Information. Attribution is mandatory -
see ATTRIBUTION at the bottom of this file.

Usage:
    python src/light_layer.py --selftest
    copernicusmarine login
    python src/light_layer.py --describe
    python src/light_layer.py --fetch --dataset-id <id> --aoi inner_roaringwater
    python src/light_layer.py --report          # compare Kd across the AOIs
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

OUT_DIR = Path("outputs/light")
CACHE_DIR = OUT_DIR / "kd_cache"

try:
    from common import AOIS
    HAVE_COMMON = True
except ImportError:                                       # pragma: no cover
    HAVE_COMMON = False
    AOIS = {
        "sherkin_baltimore": [-9.42, 51.45, -9.32, 51.51],
        "mizen_outer": [-9.86, 51.44, -9.74, 51.52],
        "inner_roaringwater": [-9.52, 51.49, -9.44, 51.54],
        "kenmare_river": [-9.93, 51.75, -9.78, 51.81],
    }

# Growing season. Matches common.USABLE_MONTHS: irradiance, not geometry, is
# what limits the Sentinel-2 work, and it is also when kelp is growing.
SEASON_MONTHS = (5, 6, 7, 8)
# Years to average over. A single date is weather; a multi-year seasonal median
# is a climatology, which is what a habitat model wants.
DEFAULT_YEARS = (2019, 2024)
# Padding around an AOI, in degrees, so the coarse Kd grid has cells to
# interpolate from at the edges.
PAD_DEG = 0.05

# Words that mark a dataset as carrying what we need.
WANT_VARS = ("KD490", "ZSD", "TUR", "SPM")

# The fraction of surface light below which kelp is not expected. 1% is the
# classical euphotic-depth threshold (Ryther 1956) and is the value Saulquin
# et al. found close to the observed minima. Used only for a readable summary,
# never as a hard filter in the model.
EUPHOTIC_FRACTION = 0.01


# ---------------------------------------------------------------------------
# The physics
# ---------------------------------------------------------------------------

def light_at_seabed(depth_m, kd) -> np.ndarray:
    """Fraction of surface irradiance reaching the seabed: exp(-Kd * z).

    Both arguments may be arrays. Depth is metres below the surface, positive
    down; a depth at or above the surface returns 1.0 because no water has
    been traversed. NaN in either input yields NaN out - never a filled value,
    because a fabricated light level would silently become a fabricated
    habitat.
    """
    z = np.asarray(depth_m, dtype=float)
    k = np.asarray(kd, dtype=float)
    out = np.exp(-k * np.clip(z, 0.0, None))
    return np.where(np.isfinite(z) & np.isfinite(k), out, np.nan)


def euphotic_depth(kd, fraction=EUPHOTIC_FRACTION):
    """Depth at which `fraction` of surface light remains, in metres."""
    k = np.asarray(kd, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = -np.log(fraction) / k
    return np.where(np.isfinite(k) & (k > 0), z, np.nan)


# ---------------------------------------------------------------------------
# Catalogue discovery - never hard-code a dataset id
# ---------------------------------------------------------------------------

def describe(keyword: str = "transp") -> int:
    """Search the whole Copernicus Marine catalogue for datasets by keyword.

    Searches DATASET ids, not product titles. The first version filtered on
    product_id containing "OCEANCOLOUR" and a region hint, which found the
    Atlantic 1 km transparency datasets but missed the Sentinel-2
    High-Resolution Ocean Colour products entirely, because those sit under
    different product names and under the IBI (Iberian-Biscay-Irish) region
    rather than ATL. A keyword search over dataset ids has no such blind spot.

    Useful keywords:
        transp   transparency - this is where KD490 and Secchi depth live
        tur      turbidity, including the Sentinel-2 100 m HR-OC products
        optics   inherent optical properties
        300m     anything at 300 m
        100m     anything at 100 m
    """
    try:
        import copernicusmarine as cm
    except ImportError:
        print("  copernicusmarine is not installed:  pip install copernicusmarine")
        return 2

    print(f"  searching the catalogue for dataset ids containing "
          f"'{keyword}' (takes a minute) ...")
    try:
        cat = cm.describe()
    except Exception as exc:
        print(f"  catalogue request failed: {exc}")
        print("  If this is an authentication error:  copernicusmarine login")
        return 2

    hits = []
    for prod in getattr(cat, "products", []) or []:
        pid = getattr(prod, "product_id", "") or ""
        title = getattr(prod, "title", "") or ""
        for ds in getattr(prod, "datasets", []) or []:
            did = getattr(ds, "dataset_id", "") or ""
            if keyword.lower() in did.lower():
                hits.append((pid, title, did))

    if not hits:
        print(f"  nothing matched '{keyword}'.")
        print("  Try: transp | tur | optics | 300m | 100m")
        return 1

    def res_rank(did):
        for tag, m in (("100m", 100), ("300m", 300), ("1km", 1000),
                       ("4km", 4000)):
            if tag in did.lower():
                return m
        return 9999

    hits.sort(key=lambda h: (res_rank(h[2]), h[2]))
    print(f"\n  {len(hits)} dataset(s), finest resolution first:\n")
    seen = set()
    for pid, title, did in hits:
        m = res_rank(did)
        note = ""
        if m <= 300:
            note = "   <-- fine enough to vary INSIDE an AOI"
        elif m <= 1000:
            note = "   <-- ~70 pixels per AOI: good between AOIs, blocky within"
        else:
            note = "   <-- TOO COARSE, an AOI would be one or two pixels"
        print(f"  {did}{note}")
        if pid not in seen:
            print(f"      product: {pid}")
            seen.add(pid)
    print("\n  Then:")
    print("    python src/light_layer.py --fetch --dataset-id <id>")
    print("\n  >>> Check the VARIABLE name too. KD490 lives in 'transp'")
    print("  >>> datasets; the Sentinel-2 high-resolution products carry TUR")
    print("  >>> (turbidity) or SPM instead, which are related to clarity but")
    print("  >>> are NOT the attenuation coefficient and cannot go straight")
    print("  >>> into exp(-Kd*z). If you use one of those, say so and treat")
    print("  >>> the result as a clarity INDEX, not as light.")
    return 0


# ---------------------------------------------------------------------------
# Fetch and build a seasonal climatology
# ---------------------------------------------------------------------------

def fetch_kd(dataset_id: str, bbox, years=DEFAULT_YEARS,
             months=SEASON_MONTHS, variable: str = "KD490",
             out_dir: Path = CACHE_DIR) -> Path | None:
    """Subset Kd for one AOI and season, and store a per-pixel median."""
    try:
        import copernicusmarine as cm
        import xarray as xr
    except ImportError as exc:
        print(f"  missing dependency: {exc}")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"raw_{dataset_id[:40]}_{bbox[0]:.2f}_{bbox[1]:.2f}.nc"

    if not raw.exists():
        print(f"  subsetting {dataset_id} for {variable} "
              f"{years[0]}-{years[1]} ...")
        try:
            cm.subset(
                dataset_id=dataset_id, variables=[variable],
                minimum_longitude=bbox[0] - PAD_DEG,
                maximum_longitude=bbox[2] + PAD_DEG,
                minimum_latitude=bbox[1] - PAD_DEG,
                maximum_latitude=bbox[3] + PAD_DEG,
                start_datetime=f"{years[0]}-01-01",
                end_datetime=f"{years[1]}-12-31",
                output_filename=raw.name, output_directory=str(out_dir),
            )
        except Exception as exc:
            print(f"  subset failed: {exc}")
            print("  If this mentions credentials, run:  copernicusmarine login")
            print("  If it mentions the variable, check the name with --describe")
            return None
    else:
        print(f"  reusing {raw}")

    ds = xr.open_dataset(raw)
    if variable not in ds:
        print(f"  >>> '{variable}' is not in the file. Present: "
              f"{list(ds.data_vars)}")
        return None
    da = ds[variable]
    if "time" in da.dims:
        da = da.sel(time=da["time"].dt.month.isin(list(months)))
        n_obs = int(da.sizes.get("time", 0))
        if n_obs == 0:
            print("  >>> no observation in the requested months. A seasonal")
            print("  >>> median cannot be built; widen the years or months.")
            return None
        valid = int(np.isfinite(da.values).sum(axis=0).max()) if n_obs else 0
        print(f"  {n_obs} scenes in months {months}; "
              f"best pixel has {valid} valid observations")
        med = da.median(dim="time", skipna=True)
    else:
        med = da
        print("  no time dimension: treating the file as already aggregated")

    lat_name = "latitude" if "latitude" in med.coords else "lat"
    lon_name = "longitude" if "longitude" in med.coords else "lon"
    arr = np.asarray(med.values, dtype=float)
    lats = np.asarray(med[lat_name].values, dtype=float)
    lons = np.asarray(med[lon_name].values, dtype=float)

    cover = float(np.isfinite(arr).mean())
    print(f"  climatology grid {arr.shape}, {cover:.0%} of pixels have a value")
    if cover < 0.2:
        print("  >>> under a fifth of pixels have a value. Coastal ocean-colour")
        print("  >>> retrievals fail near land and in the surf zone, which is")
        print("  >>> exactly where our habitat is. Check the coverage map")
        print("  >>> before relying on this.")

    npz = out_dir / f"kd_{Path(raw).stem}.npz"
    np.savez(npz, kd=arr, lat=lats, lon=lons,
             bbox=np.array(bbox), months=np.array(months),
             years=np.array(years), variable=np.array([variable]))
    print(f"  written: {npz}")
    return npz


def load_kd(npz_path: Path):
    z = np.load(npz_path, allow_pickle=False)
    return z["kd"], z["lat"], z["lon"]


def sample_kd_on_grid(npz_path: Path, bbox, grid_m: float) -> np.ndarray:
    """Nearest-neighbour Kd on our own 50 m grid.

    Nearest neighbour rather than interpolation, deliberately: interpolating a
    300 m field onto a 50 m grid invents structure that the sensor never
    resolved, and the resulting map would imply a precision we do not have.
    Nearest neighbour keeps the blockiness visible, which is honest.
    """
    kd, lat, lon = load_kd(npz_path)
    lat_mid = (bbox[1] + bbox[3]) / 2.0
    dlon = grid_m / (111320.0 * math.cos(math.radians(lat_mid)))
    dlat = grid_m / 110574.0
    lons = np.arange(bbox[0] + dlon / 2, bbox[2], dlon)
    lats = np.arange(bbox[1] + dlat / 2, bbox[3], dlat)

    jj = np.abs(lon[None, :] - lons[:, None]).argmin(axis=1)
    ii = np.abs(lat[None, :] - lats[:, None]).argmin(axis=1)
    return kd[np.ix_(ii, jj)]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def selftest() -> int:
    print("SELFTEST (no network, no account)\n")

    # --- the exponential must behave like an exponential -----------------
    assert light_at_seabed(0.0, 0.2) == 1.0
    assert abs(light_at_seabed(10.0, 0.0) - 1.0) < 1e-12
    a = light_at_seabed(10.0, 0.1)
    b = light_at_seabed(20.0, 0.1)
    c = light_at_seabed(10.0, 0.3)
    assert b < a and c < a, (a, b, c)
    assert abs(light_at_seabed(10.0, 0.1) - math.exp(-1.0)) < 1e-12
    print(f"  exp(-Kd*z): 0 m -> 1.00, 10 m at Kd 0.1 -> {a:.3f}, "
          f"20 m -> {b:.3f}, Kd 0.3 -> {c:.3f}  ok")

    # A depth above the surface must not amplify light.
    assert light_at_seabed(-3.0, 0.2) == 1.0
    print("  a depth above the surface returns 1.0, never >1  ok")

    # NaN must propagate, in both arguments.
    assert np.isnan(light_at_seabed(np.nan, 0.2))
    assert np.isnan(light_at_seabed(10.0, np.nan))
    print("  NaN in depth or Kd propagates, never filled  ok")

    # --- euphotic depth against published anchors ------------------------
    # seaweed.ie (Guiry, NUI Galway) records L. hyperborea to 32 m in
    # optically clear water and closed communities at 0-24 m. Clear Atlantic
    # water is around Kd 0.1 and turbid inshore water an order of magnitude
    # higher, so the 1% depth should bracket those observations. If it did not,
    # the formula or the units would be wrong.
    z_clear = float(euphotic_depth(0.10))
    z_turbid = float(euphotic_depth(0.50))
    print(f"  1% light depth: Kd 0.10 -> {z_clear:.0f} m, "
          f"Kd 0.50 -> {z_turbid:.0f} m")
    assert 30.0 < z_clear < 60.0, z_clear
    assert 5.0 < z_turbid < 15.0, z_turbid
    print("  brackets the published 32 m clear-water limit and the ~8 m")
    print("  turbid-water limit  ok")
    assert np.isnan(euphotic_depth(0.0)), "Kd=0 has no finite euphotic depth"
    print("  Kd = 0 returns NaN rather than infinity  ok")

    # --- THE point of the whole exercise ---------------------------------
    # Two cells the current model cannot tell apart, because it only has depth:
    # shallow turbid inner Roaringwater against deeper clear open coast. The
    # light term must rank them the OTHER way round, or it adds nothing that
    # depth did not already say.
    shallow_turbid = light_at_seabed(7.2, 0.45)     # inner_roaringwater-like
    deeper_clear = light_at_seabed(15.0, 0.12)      # exposed-coast-like
    print(f"\n  shallow + turbid  (7.2 m, Kd 0.45): light "
          f"{shallow_turbid:.4f}")
    print(f"  deeper  + clear  (15.0 m, Kd 0.12): light {deeper_clear:.4f}")
    assert deeper_clear > shallow_turbid, (deeper_clear, shallow_turbid)
    print("  the light term REVERSES the depth-only ordering - which is the")
    print("  whole reason for adding it  ok")

    # And the control: with the SAME clarity, deeper must still be darker, or
    # the term would just be a relabelled turbidity and depth would be lost.
    assert light_at_seabed(15.0, 0.3) < light_at_seabed(7.2, 0.3)
    print("  at equal clarity, deeper is still darker - depth is not thrown")
    print("  away  ok")

    # --- grid sampling ---------------------------------------------------
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "kd.npz"
        bbox = AOIS["inner_roaringwater"]
        lat = np.linspace(bbox[1] - 0.02, bbox[3] + 0.02, 12)
        lon = np.linspace(bbox[0] - 0.02, bbox[2] + 0.02, 14)
        # a west-east gradient, so a wrong axis order would be visible
        kd = np.tile(np.linspace(0.15, 0.55, 14), (12, 1))
        np.savez(p, kd=kd, lat=lat, lon=lon, bbox=np.array(bbox),
                 months=np.array(SEASON_MONTHS), years=np.array(DEFAULT_YEARS),
                 variable=np.array(["KD490"]))
        g = sample_kd_on_grid(p, bbox, 200.0)
        assert g.ndim == 2 and g.size > 100, g.shape
        assert np.all(np.isfinite(g))
        # the gradient must survive with the right orientation
        assert g[:, -1].mean() > g[:, 0].mean(), (g[:, 0].mean(), g[:, -1].mean())
        assert abs(g[0, 0] - g[-1, 0]) < 1e-9, "no north-south gradient expected"
        print(f"\n  grid sampling: {g.shape}, west {g[:, 0].mean():.3f} -> "
              f"east {g[:, -1].mean():.3f}, orientation preserved  ok")

    print("\nSELFTEST PASSED. The attenuation law behaves correctly and")
    print("propagates NaN, the 1% depth brackets the published clear-water and")
    print("turbid-water kelp limits, the light term reverses the depth-only")
    print("ordering for a shallow turbid cell against a deeper clear one while")
    print("still preserving depth at equal clarity, and grid sampling keeps")
    print("its orientation. Nothing here touched Copernicus Marine.")
    return 0


# ---------------------------------------------------------------------------
# Report - what Kd actually looks like across our AOIs
# ---------------------------------------------------------------------------

def report(grid_m: float = 50.0) -> int:
    """Compare Kd and the implied euphotic depth across the AOIs."""
    files = sorted(CACHE_DIR.glob("kd_*.npz"))
    if not files:
        print("  no Kd climatology cached yet. Run --fetch first.")
        return 1
    print(f"  {'AOI':<24}{'Kd p25':>9}{'Kd med':>9}{'Kd p75':>9}"
          f"{'1% depth':>11}{'cover':>8}")
    rows = []
    for name, bbox in AOIS.items():
        best = None
        for f in files:
            z = np.load(f)
            b = z["bbox"]
            if abs(b[0] - bbox[0]) < 1e-6 and abs(b[1] - bbox[1]) < 1e-6:
                best = f
                break
        if best is None:
            print(f"  {name:<24}   not fetched")
            continue
        g = sample_kd_on_grid(best, bbox, grid_m)
        v = g[np.isfinite(g)]
        if v.size == 0:
            print(f"  {name:<24}   no valid pixel")
            continue
        p25, med, p75 = np.percentile(v, [25, 50, 75])
        zeu = float(euphotic_depth(med))
        cover = float(np.isfinite(g).mean())
        print(f"  {name:<24}{p25:>9.3f}{med:>9.3f}{p75:>9.3f}"
              f"{zeu:>10.1f}m{cover:>8.0%}")
        rows.append({"aoi": name, "kd_p25": round(float(p25), 4),
                     "kd_median": round(float(med), 4),
                     "kd_p75": round(float(p75), 4),
                     "euphotic_depth_1pct_m": round(zeu, 2),
                     "pixel_coverage": round(cover, 4)})

    print("\n  >>> What to look for: inner_roaringwater should have a HIGHER")
    print("  >>> Kd, i.e. murkier water and a shallower 1% depth, than")
    print("  >>> mizen_outer and sherkin_baltimore. If it does, the light term")
    print("  >>> can separate the cells depth alone could not, and it is worth")
    print("  >>> adding to the model. If the AOIs all look the same, the term")
    print("  >>> will add nothing and should NOT be added - say so and move on.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "kd_summary.json").write_text(
        json.dumps({"grid_m": grid_m, "aois": rows,
                    "season_months": list(SEASON_MONTHS),
                    "attribution": ATTRIBUTION}, indent=2), encoding="utf-8")
    print(f"\n  written: {OUT_DIR / 'kd_summary.json'}")
    return 0


ATTRIBUTION = (
    "Generated using E.U. Copernicus Marine Service Information. "
    "Diffuse attenuation coefficient Kd490 from the Ocean Colour Thematic "
    "Assembly Centre. Method after Saulquin et al. (2013), Remote Sensing of "
    "Environment 128:224-233. NOTE: Kd490 is used directly as the attenuation "
    "coefficient; the Kd490 -> KdPAR conversion has NOT been applied, so the "
    "derived quantity is a relative light index, not PAR at the seabed."
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Light at the seabed from satellite water clarity.")
    ap.add_argument("--describe", action="store_true",
                    help="search the catalogue for datasets by keyword")
    ap.add_argument("--keyword", default="transp",
                    help="dataset-id keyword for --describe (default transp; "
                         "try tur, optics, 300m, 100m)")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--dataset-id")
    ap.add_argument("--variable", default="KD490")
    ap.add_argument("--aoi", choices=sorted(AOIS),
                    help="one AOI (default: all)")
    ap.add_argument("--years", type=int, nargs=2, default=list(DEFAULT_YEARS))
    ap.add_argument("--grid", type=float, default=50.0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.describe:
        return describe(args.keyword)
    if args.report:
        return report(args.grid)
    if args.fetch:
        if not args.dataset_id:
            print("  --dataset-id is required. Find it with --describe.")
            print("  It is not hard-coded here on purpose: Copernicus Marine")
            print("  dataset ids change between product versions, and a stale")
            print("  id in the code would fail confusingly a month from now.")
            return 2
        print(ATTRIBUTION + "\n")
        targets = {args.aoi: AOIS[args.aoi]} if args.aoi else AOIS
        ok = 0
        for name, bbox in targets.items():
            print(f"\n=== {name} ===")
            if fetch_kd(args.dataset_id, bbox, tuple(args.years),
                        SEASON_MONTHS, args.variable) is not None:
                ok += 1
        print(f"\n  {ok} of {len(targets)} AOIs fetched.")
        print("  Next: python src/light_layer.py --report")
        return 0 if ok else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())