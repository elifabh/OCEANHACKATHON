#!/usr/bin/env python3
"""
Step 4 - Kelp Indicator Assemblage Score.

WHAT THIS DOES
--------------
Compares the observed West Cork Laminaria hyperborea assemblage (from OBIS dive
records) against the published Irish kelp indicator species list:

    Schoenrock, K.M., Chan, K.M., O'Callaghan, T., O'Callaghan, R., Golden, A.,
    Krueger-Hadfield, S.A. & Power, A.M. (2020) A review of subtidal kelp forests
    in Ireland: From first descriptions to new habitat monitoring techniques.
    Ecology and Evolution 10(13): 6819-6832. doi:10.1002/ece3.6345
    Table 1 (CC BY 4.0).

WHY THIS DESIGN AND NOT RICHNESS
--------------------------------
Per-site species richness in this dataset is an effort artefact (kelp sites had
~1.9x the records of non-kelp sites, and the richness gap disappears when binned
by effort). A fixed 17-species checklist behaves differently: it saturates fast,
so a short dive can still record most of the conspicuous indicators. It is not
immune to detection bias, but it is far less sensitive to it than a raw count.

WHY WORMS ON BOTH SIDES
-----------------------
A naive string join between a 2020 paper and an OBIS extract will silently fail.
Two of the 17 names are typos in the source, and at least two are affected by
taxonomic revisions since publication. A species that is present but recorded
under its current accepted name would be scored as ABSENT - i.e. the exact
failure mode that produces confident-looking but meaningless output. So both
sides are resolved to accepted AphiaIDs and compared by ID, not by string.

Only match_type == 'exact' is auto-accepted. Fuzzy/phonetic matches are printed
for manual review and NOT counted, for the same reason.

USAGE
-----
    python src/indicator_score.py
    python src/indicator_score.py --sites outputs/kelp_sites_long.csv
    python src/indicator_score.py --offline      # skip WoRMS, flag the risk

Requires: requests, pandas
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# --------------------------------------------------------------------------
# Paths (relative to project root)
# --------------------------------------------------------------------------
REF_CSV = Path("data/reference/schoenrock2020_indicators.csv")
ASSEMBLAGE_CSV = Path("outputs/kelp_site_assemblage.csv")
CACHE_JSON = Path("outputs/worms_cache.json")
OUT_MATCH = Path("outputs/indicator_match.csv")
OUT_SITES = Path("outputs/indicator_site_scores.csv")

WORMS_URL = "https://www.marinespecies.org/rest/AphiaRecordsByMatchNames"
BATCH = 40          # WoRMS accepts up to 50 names per call; 40 for headroom
PAUSE = 1.0         # be polite to a free public API

# Hand-entered fallbacks used ONLY with --offline. These are flagged in the
# output so they can never be mistaken for a verified resolution.
OFFLINE_ALIASES = {
    "gibbula umbilicalis": ["steromphala umbilicalis"],
    "gibbula cineraria": ["steromphala cinerea"],
    "gobiusculus flavescens": ["pomatoschistus flavescens"],
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def die(msg: str) -> None:
    print(f"\nFATAL: {msg}\n", file=sys.stderr)
    sys.exit(1)


def norm(s) -> str:
    return str(s).strip().lower()


def detect_column(df: pd.DataFrame, candidates, label: str) -> str:
    """Find a column by substring match. Fails loudly rather than guessing."""
    for want in candidates:
        for col in df.columns:
            if want in col.lower():
                return col
    die(
        f"Could not find a {label} column in {list(df.columns)}. "
        f"Looked for any of {candidates}. Rename the column or edit this script."
    )


def load_cache() -> dict:
    if CACHE_JSON.exists():
        return json.loads(CACHE_JSON.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    CACHE_JSON.write_text(json.dumps(cache, indent=1), encoding="utf-8")


def worms_resolve(names: list[str], cache: dict) -> dict:
    """
    Resolve a list of scientific names to accepted WoRMS records.

    Returns {input_name_lower: record_or_None}, where record has keys
    aphia_id, accepted_name, genus, rank, match_type, status.
    Non-exact matches are returned with match_type set so the caller can
    exclude them.
    """
    if requests is None:
        die("The 'requests' package is not installed. pip install requests")

    todo = [n for n in names if norm(n) not in cache]
    print(f"  WoRMS: {len(names)} names, {len(names) - len(todo)} cached, "
          f"{len(todo)} to fetch")

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        params = [("scientificnames[]", n) for n in chunk]
        params.append(("marine_only", "true"))
        try:
            r = requests.get(WORMS_URL, params=params, timeout=60)
        except Exception as exc:
            die(f"WoRMS request failed ({exc}). Re-run with --offline to "
                f"proceed without name resolution, but read the warning it prints.")

        if r.status_code == 204:          # WoRMS returns 204 for 'no matches'
            for n in chunk:
                cache[norm(n)] = None
            continue
        if r.status_code != 200:
            die(f"WoRMS returned HTTP {r.status_code} for batch starting "
                f"'{chunk[0]}'. Nothing written.")

        blocks = r.json()
        # WoRMS returns one list of candidates per submitted name, in order.
        if len(blocks) != len(chunk):
            die(f"WoRMS returned {len(blocks)} blocks for {len(chunk)} names. "
                f"Order cannot be trusted - aborting rather than mis-assigning.")

        for name, candidates in zip(chunk, blocks):
            if not candidates:
                cache[norm(name)] = None
                continue
            c = candidates[0]             # best match first
            cache[norm(name)] = {
                "aphia_id": c.get("valid_AphiaID") or c.get("AphiaID"),
                "accepted_name": c.get("valid_name") or c.get("scientificname"),
                "genus": c.get("genus"),
                "rank": c.get("rank"),
                "match_type": c.get("match_type"),
                "status": c.get("status"),
                "submitted_name": name,
            }
        print(f"    ... {min(i + BATCH, len(todo))}/{len(todo)}")
        time.sleep(PAUSE)

    save_cache(cache)
    return {norm(n): cache.get(norm(n)) for n in names}


def offline_resolve(names: list[str]) -> dict:
    """No API. Identity mapping plus the hand-entered alias table."""
    out = {}
    for n in names:
        out[norm(n)] = {
            "aphia_id": None,
            "accepted_name": n,
            "genus": str(n).split()[0],
            "rank": "Species" if len(str(n).split()) > 1 else "Genus",
            "match_type": "OFFLINE_NOT_VERIFIED",
            "status": None,
            "submitted_name": n,
        }
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", help="optional long table: one row per site x species")
    ap.add_argument("--offline", action="store_true",
                    help="skip WoRMS (results are NOT name-verified)")
    args = ap.parse_args()

    if not REF_CSV.exists():
        die(f"{REF_CSV} not found. Run from the project root.")
    if not ASSEMBLAGE_CSV.exists():
        die(f"{ASSEMBLAGE_CSV} not found. Run from the project root.")

    ref = pd.read_csv(REF_CSV)
    print(f"\nReference list: {len(ref)} indicator taxa "
          f"(Schoenrock et al. 2020, Table 1)")

    obs = pd.read_csv(ASSEMBLAGE_CSV)
    sp_col = detect_column(obs, ["species", "scientific", "taxon", "name"],
                           "species-name")
    n_col = detect_column(obs, ["n_site", "nsite", "sites", "count", "n"],
                          "site-count")
    print(f"Observed assemblage: {len(obs)} taxa from {ASSEMBLAGE_CSV}")
    print(f"  species column -> '{sp_col}'   site-count column -> '{n_col}'")
    print("  first 3 rows, CHECK THESE LOOK RIGHT:")
    print(obs[[sp_col, n_col]].head(3).to_string(index=False))

    # ---------------------------------------------------------------- resolve
    cache = load_cache()
    ref_names = ref["name_for_lookup"].tolist()
    obs_names = obs[sp_col].dropna().astype(str).tolist()

    if args.offline:
        print("\n*** OFFLINE MODE - names are NOT verified against WoRMS. ***")
        print("*** Any taxonomic revision since 2020 will show as ABSENT.  ***")
        ref_res = offline_resolve(ref_names)
        obs_res = offline_resolve(obs_names)
    else:
        print("\nResolving reference names...")
        ref_res = worms_resolve(ref_names, cache)
        print("Resolving observed assemblage names...")
        obs_res = worms_resolve(obs_names, cache)

    # -------------------------------------------- non-exact matches: report
    shaky = [r for r in list(ref_res.values()) if r
             and r["match_type"] not in ("exact", "OFFLINE_NOT_VERIFIED")]
    if shaky:
        print("\nREVIEW REQUIRED - these reference names did not match exactly.")
        print("They are NOT counted until you check them by hand:")
        for r in shaky:
            print(f"  {r['submitted_name']:<28} -> {r['accepted_name']} "
                  f"({r['match_type']})")

    # ----------------------------------- denominator integrity: duplicate IDs
    ids = [r["aphia_id"] for r in ref_res.values() if r and r["aphia_id"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        print("\nDENOMINATOR WARNING: two or more reference entries resolve to "
              "the same accepted taxon:")
        for r in ref_res.values():
            if r and r["aphia_id"] in dupes:
                print(f"  {r['submitted_name']} -> {r['accepted_name']} "
                      f"(AphiaID {r['aphia_id']})")
        print("  The denominator must be reduced accordingly, or the score is "
              "inflated. Decide this before reporting any number.")

    # ---------------------------------------------------------------- match
    # A taxon is identified by its accepted AphiaID when we have one. Offline
    # there is no ID, so we fall back to the normalised accepted name. Keeping
    # both in one keyspace means the matching logic below is identical either
    # way, and an ID match can never be confused with a string match.
    def key_of(rec) -> tuple | None:
        if not rec:
            return None
        if rec.get("aphia_id"):
            return ("id", rec["aphia_id"])
        if rec.get("accepted_name"):
            return ("name", norm(rec["accepted_name"]))
        return None

    obs_by_key, obs_by_genus = {}, {}
    site_counts = dict(zip(obs[sp_col].astype(str), obs[n_col]))
    for raw in obs_names:
        rec = obs_res.get(norm(raw))
        if not rec:
            continue
        n_sites = site_counts.get(raw)
        k = key_of(rec)
        if k:
            obs_by_key.setdefault(k, []).append((raw, n_sites))
        if rec.get("genus"):
            obs_by_genus.setdefault(norm(rec["genus"]), []).append((raw, n_sites))

    rows = []
    for _, row in ref.iterrows():
        rec = ref_res.get(norm(row["name_for_lookup"]))
        hit, matched, n_sites, via = False, "", 0, ""

        if rec and rec["match_type"] in ("exact", "OFFLINE_NOT_VERIFIED"):
            if row["rank"] == "genus":
                found = obs_by_genus.get(norm(row["name_for_lookup"]), [])
                # A species listed separately in Table 1 must not also be
                # counted inside its genus row. Gobiusculus flavescens is now
                # Pomatoschistus flavescens, so without this it scores twice.
                drop = str(row.get("genus_excludes") or "").strip().lower()
                if drop:
                    found = [(f, c) for f, c in found
                             if drop not in norm(obs_res[norm(f)]["accepted_name"])]
                via = "genus" if found else ""
            else:
                found = obs_by_key.get(key_of(rec), [])
                via = ("aphia_id" if rec.get("aphia_id") else "name") if found else ""
                # Offline only: try the hand-entered synonyms, on the FULL name.
                # Genus-level fallback is deliberately not used here - it would
                # match Gibbula umbilicalis to Steromphala cinerea.
                if not found and args.offline:
                    for alias in OFFLINE_ALIASES.get(
                            norm(row["name_for_lookup"]), []):
                        found += obs_by_key.get(("name", norm(alias)), [])
                    if found:
                        via = "hand_alias_UNVERIFIED"
            if found:
                hit = True
                matched = "; ".join(f for f, _ in found)
                n_sites = max((c for _, c in found if pd.notna(c)), default=0)

        rows.append({
            "id": row["id"],
            "name_as_published": row["name_as_published"],
            "accepted_name": rec["accepted_name"] if rec else "UNRESOLVED",
            "aphia_id": rec["aphia_id"] if rec else None,
            "match_type": rec["match_type"] if rec else "none",
            "present_in_west_cork": hit,
            "matched_as": matched,
            "matched_via": via,
            "n_sites_of_35": n_sites,
            "trophic_function": row["trophic_function"],
            "mean_abundance_per_m2": row["mean_abundance_per_m2"],
        })

    out = pd.DataFrame(rows).sort_values("n_sites_of_35", ascending=False)
    OUT_MATCH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_MATCH, index=False)

    present = int(out["present_in_west_cork"].sum())
    total = len(out)
    print("\n" + "=" * 66)
    print("REGIONAL INDICATOR COVERAGE")
    print("=" * 66)
    print(out[["name_as_published", "present_in_west_cork",
               "n_sites_of_35", "trophic_function"]].to_string(index=False))
    print(f"\n  {present} of {total} indicator taxa present in the West Cork "
          f"assemblage  ({present / total:.0%})")
    print(f"  written to {OUT_MATCH}")

    # ---------------------------------------------------- optional per-site
    if args.sites:
        sites_path = Path(args.sites)
        if not sites_path.exists():
            die(f"{sites_path} not found.")
        sdf = pd.read_csv(sites_path)
        s_site = detect_column(sdf, ["site", "station", "event", "location"],
                               "site-id")
        s_sp = detect_column(sdf, ["species", "scientific", "taxon", "name"],
                             "species-name")
        print(f"\nPer-site mode: '{s_site}' x '{s_sp}', {len(sdf)} rows")

        hit_keys = {key_of(ref_res.get(norm(n))) for n in ref_names}
        hit_keys.discard(None)
        hit_genera = {norm(r["name_for_lookup"])
                      for _, r in ref.iterrows() if r["rank"] == "genus"}

        recs = []
        for site, grp in sdf.groupby(s_site):
            names = grp[s_sp].dropna().astype(str).unique().tolist()
            found = set()
            for n in names:
                rec = obs_res.get(norm(n))
                if not rec:
                    continue
                k = key_of(rec)
                if k in hit_keys:
                    found.add(k)
                if rec.get("genus") and norm(rec["genus"]) in hit_genera:
                    found.add(("genus", norm(rec["genus"])))
            recs.append({
                "site": site,
                # True survey effort if the builder supplied it. len(grp) is
                # species richness, NOT effort - falling back to it is a last
                # resort and is labelled so in the printed warning below.
                "records_at_site": (int(grp["records_at_site"].iloc[0])
                                    if "records_at_site" in grp.columns
                                    else len(grp)),
                "species_at_site": len(names),
                "indicators_found": len(found),
                "indicator_score": round(len(found) / total, 3),
            })

        sc = pd.DataFrame(recs).sort_values("indicator_score", ascending=False)
        if "records_at_site" not in sdf.columns:
            print("\n  WARNING: the sites file has no 'records_at_site' column, "
                  "so effort has been substituted with species richness. That "
                  "is circular. Rebuild with the current build_site_long.py.")
        try:
            from scipy.stats import spearmanr
            for col in ("records_at_site", "species_at_site"):
                rho, p = spearmanr(sc[col], sc["indicators_found"])
                print(f"\n  Spearman(indicators, {col}) = {rho:.3f}  p = {p:.4g}")
            print("  If the score tracks records_at_site, it is measuring how "
                  "long the diver stayed, not the habitat.")
        except ImportError:
            print("\n  (pip install scipy to get the effort-correlation test)")
        sc.to_csv(OUT_SITES, index=False)
        print(sc.to_string(index=False))
        print(f"\n  written to {OUT_SITES}")
        print("\n  Read 'indicator_score' ALWAYS next to 'records_at_site'. "
              "A low score with few records is an unobserved site, not a "
              "degraded one. Do not map one without the other.")

    print("\nLIMITATIONS carried into any figure built from this file:")
    print("  1. Absence here is non-detection, not absence. There are no true "
          "absences in dive data.")
    print("  2. The source restricts Asterias rubens to individuals <3 cm. "
          "Dive records carry no size class, so that row is a looser match "
          "than the other 16.")
    print("  3. Schoenrock's own survey sites are in Galway/Clare and Lough "
          "Hyne. Lough Hyne is a semi-enclosed marine lake and is not "
          "representative of open West Cork coast.")
    print("  4. The same paper's BIOMAR analysis reports the lowest kelp "
          "community similarity in the country for the southwest (6.99%, "
          "n=9 sites), so a single West Cork reference assemblage is weakly "
          "supported by published data.")
    print("  5. BIOMAR (Picton & Morrow 2006, Ulster Museum) may be inside "
          "the OBIS extract via the NMNI dataset. Table 1 is independent of "
          "it; Tables 4 and 5 are not. Do not use Tables 4/5 as validation.\n")


if __name__ == "__main__":
    main()