# CLAUDE.md — OCEANHACKATHON

This file is the authoritative brief. It intentionally restates everything a
new session needs, so that gaps in the handover notes (`docs/DEVIR_NOTU_*.md`)
cannot cause errors. If a handover note and this file conflict, THIS FILE WINS.
Read the handover notes for background, not for permission.

---

## 1. Project

Ocean Hackathon Cork 2026 (16–18 October). Challenge: "Seeing the Invisible
Shield: Valuing Coastal Habitats as Natural Infrastructure." Deliverable: a
working prototype — an **interactive map + valuation engine** that detects a
coastal kelp habitat from open satellite data, assesses its decline, and
assigns a coastal-protection value (€) plus a biodiversity score. Demo case:
kelp in West Cork, Ireland (Roaringwater Bay / Sherkin Island). The engine
must be designed to transfer to other habitats and Atlantic locations.

Jury criteria — every design decision is judged against these six:
1. Demonstrator / proof of concept built
2. Use of digital data
3. Project ambition
4. Potential environmental and societal impact
5. Innovative nature
6. Team cohesion and communication

## 2. Working with Elif

- Elif writes in Turkish. Reply with a SHORT plain-language summary in Turkish
  FIRST, then the technical part. No jargon without a plain explanation.
- All professional outputs (code, comments, docs, UI text) in ENGLISH.
- No hallucination. No number without a verified source. If unsure: say so.
- Separate (a) published methods from (b) our own 48h-prototype
  simplifications. Never present a simplification as validated.
- Self-check every deliverable and flag its weaknesses before Elif has to.
- Prefer generating files over explaining how to generate them.
- Commit to git after each milestone with a descriptive message.

## 3. Environment

- Repo: `~/Desktop/OCEANHACKATHON`. Windows 10/11, Git Bash (MINGW64).
- Python venv: `.venv` → activate with `source .venv/Scripts/activate`.
- pip inside venv works normally.
- Layout: `src/` scripts, `outputs/` generated artefacts, `docs/` handover
  notes, `data/` raw inputs (INFOMAR bathymetry, Burrows fetch raster at
  `data/fetch/log10_eu200m1a.tif` in EPSG:27700, OPW flood shapefile, etc.).
- `DEPENDENCIES.md` at repo root is MANDATORY for the hackathon: every
  third-party library with version number and licence. Update it whenever a
  dependency is added.

### CRS traps (all previously hit, all cost hours)
- Always compute areas from EPSG:2157 (Irish Transverse Mercator) geometry.
  Attribute `Shape_Area` fields are ALWAYS wrong (~2.6× Web Mercator inflation
  at 51.5°N).
- EPA GeoServer (`https://gis.epa.ie/geoserver/EPA/ows`, WFS 2.0.0) serves
  EPSG:29902 (Irish Grid TM65). A bbox in EPSG:4326 returns zero features
  SILENTLY. Zero features everywhere = CRS bug, not a finding. For small
  layers, download whole and filter in Python.
- Burrows fetch raster is EPSG:27700 (British National Grid).
- INFOMAR F32 bathymetry: LAT datum, ~4.2 m resolution.
- Overpass API needs a custom `User-Agent` header (default returns HTTP 406).

### The Overpass mirror trap (2026-08-28, cost hours and a published table)
- **`overpass.osm.ch` is BANNED. Never add it back.** It serves a
  Switzerland-only database and answers Irish queries with HTTP 200, no
  error, no `remark`, and zero elements. Its answers were cached, and in this
  project a zero is a publishable finding.
- The ban is enforced on the RESPONSE, not the URL: `check_instance()` in
  `wide_receptor_screen.py` refuses any response whose `generator` matches a
  banned instance **or** whose `osm3s.timestamp_osm_base` is not ISO-8601.
  osm.ch reports the integer `116725`. Restoring its URL will therefore not
  make it work; it will raise.
- **A mirror is not a mirror until `mirror_coverage_selftest()` says so.** It
  requires Irish data in two areas and an ISO database timestamp, and raises
  if a listed mirror fails. Run it before adding any endpoint.
- An empty result is confirmed on a second endpoint before it is believed or
  cached, and "empty" includes `out count;` returning `total="0"` — a
  non-empty response carrying a zero.
- A zero no second endpoint could confirm is appended to
  `data/osm/unconfirmed_empties.jsonl`. It is a result with a caveat, not a
  result.
- Every cache write lays down `overpass_<hash>.meta.json` with the query text,
  the endpoint and its fingerprint. A cached response that does not record the
  question it answers cannot be audited.
- Audit with `src/overpass_cache_audit.py` (provenance), not
  `src/overpass_audit.py` (emptiness only — superseded, kept for the record).

## 4. LOCKED FACTS — use verbatim, never recompute casually

### Defensible Sherkin figures
- Modelled *Laminaria hyperborea* bed: **1.75 ha**
- Wave-height attenuation: **7.9%**
- Wave-energy reduction: **15.2%**
- RETIRED figures (never use): 9.8 ha, 42.7%, 67.2% — traced to compounding
  errors and formally withdrawn.

### Valuation table (current, complete)
| Row | Value | Status |
|---|---|---|
| Coastal protection — avoided damage | **€0 — evidenced zero** | closed; no built receptors behind the frontage |
| Coastal protection — replacement cost | Irish unit rate **€5,621/m** (range €4,316–€7,150/m, OPW-sourced); **NOT applied as a value at Sherkin** | counterfactual illustration only; Shabman & Batie condition 3 (demonstrated demand) fails |
| Fisheries — velvet crab *Necora puber* | **€290,947/yr** (±1 SD €250,349–€331,544) | high confidence |
| Fisheries — lobster *Homarus gammarus* | **€1,051,907/yr** | GEAK low band |
| Biodiversity | **14 of 17** indicator taxa (Schoenrock et al. 2020 set) | non-monetary |
| Decline | **no decline detected** (EPA WFD, waterbody IE_SW_140_0000, 4 cycles) | non-monetary |
| Blue carbon | contested — not quantified | — |

- Euro headline: **≈ €1.34M/yr, fisheries only.**
- Rows are NEVER summed across service types (double-counting).
- Capital € (one-off) is never displayed beside annual €/yr as comparable.

### Absolute prohibitions
1. NEVER write the biodiversity result as a percentage ("82%"). Always
   **"14 of 17"**. The 82% in the competition submission image is invented.
2. NEVER state a percentage decline for West Cork kelp. The only defensible
   sentence: "No decline detected in the only official repeated assessment
   covering the AOI (EPA WFD, Roaring Water Bay IE_SW_140_0000; macroalgae
   element High in both reported cycles)." Its four limitations travel with it.
3. Dubi & Tørum (1996) / Mork (1996) / Løvås & Tørum (2001) coefficients apply
   ONLY to subtidal *L. hyperborea* on exposed Atlantic coasts — never to the
   intertidal macroalgae layer.
4. NEVER cite Jackson (1984) for wave attenuation (it is about internal waves).
5. The satellite product is intertidal macroalgae extent (species-agnostic),
   NOT a *L. hyperborea* map. The subtidal bed comes from the suitability
   model (v2, AUC 0.830). Keep the two layers visually and verbally distinct.
6. `inner_roaringwater` is locked out of positive kelp labelling (MERC 2007:
   *Saccharina*/*Saccorhiza* there, not *L. hyperborea*).
7. *Cancer pagurus* is not a supported *L. hyperborea* associate — never assume.
8. The 15.2% pro-rata scaling of structure cost is OUR simplification, not a
   published method — label it as such wherever shown.
9. OPW flood-map licence is CC BY-NC-ND 4.0 and UNRESOLVED: nothing visually
   derived from the OPW flood layer goes into a published/demo map until
   `flood_data@opw.ie` clears it. If in doubt, leave the layer out and note it.
10. Replacement cost is labelled "illustrative upper bound (Barbier 2016)"
    where demand is demonstrated, and "counterfactual illustration — not a
    value" where it is not (Sherkin).

## 5. Pipeline state

| Step | Status |
|---|---|
| 1 INFOMAR backscatter probe | closed |
| 2 Subtidal suitability model | closed (v2, AUC 0.830) |
| 3 Fisheries valuation engine | closed |
| 4 Biodiversity score | closed (14 of 17) |
| 5 Decline analysis | closed (no decline detected) |
| 5b Replacement cost | closed (unit rate found; Sherkin disqualified) |
| **6 Interactive map** | **← YOUR TASK** |
| 7 Presentation | not started (separate session; out of scope here) |

## 6. YOUR TASK — Step 6: the interactive map

### What it is
A single, professional, self-contained interactive web map that IS the
demonstrator (jury criterion 1). It shows the pipeline's evidence on a map of
Roaringwater Bay / Sherkin Island and exposes the valuation engine through a
scenario control.

### Hard requirements
- **Single HTML file** (Leaflet or MapLibre GL JS), opening by double-click
  from disk (`file://`), no server required. If data must be embedded, inline
  the GeoJSON as JS constants at build time via a Python build script
  (`src/build_map.py`) that reads `outputs/` and writes
  `outputs/map/index.html`.
- **Offline-safe for the demo**: vendor the JS/CSS libraries locally into
  `outputs/map/vendor/` (hackathon wifi cannot be trusted). Basemap tiles may
  come from the network (OSM); the map must still render its own layers and
  panels without tiles.
- **Layers** (each toggleable, each with a one-line provenance caption):
  1. Modelled subtidal *L. hyperborea* suitability / the 1.75 ha Sherkin bed
  2. Intertidal macroalgae detection extent (Sentinel-2) — visually distinct
     from layer 1, labelled species-agnostic
  3. Biodiversity: 14 of 17 indicator taxa (panel, not choropleth, unless a
     per-site layer already exists in `outputs/`)
  4. EPA WFD waterbody status (from `outputs/epa_cwb/*.geojson`) with the
     "no decline detected" sentence and its four limitations
  5. NO OPW flood layer (licence, rule 9) — show a greyed-out toggle with a
     "pending licence clearance" note instead. This is honest and looks
     professional.
- **Valuation panel — three visually separate frames** (Elif's design
  decision; the visual separation enforces the never-sum rule by layout):
  1. **Fisheries frame** (own accent colour): velvet crab €290,947/yr,
     lobster €1,051,907/yr, fisheries subtotal **€1.34M/yr**. This is the
     only subtotal anywhere on the panel.
  2. **Coastal protection frame** (different colour): avoided damage
     **€0 — evidenced zero** with a one-line reason ("no built receptors
     behind this frontage"), plus the €5,621/m Irish rock-armour rate shown
     as a comparison labelled "counterfactual illustration — not a value".
  3. **Ecological status box — OUTSIDE the price panel entirely**:
     biodiversity **14 of 17** indicator taxa and the decline statement.
     Non-monetary; never rendered as € or %.
  No grand total row exists anywhere. Per-row method + source + confidence
  in small print.
- **OPTIONAL row (verify before display, else omit)**: Nutrient cycling,
  benefit transfer from Eger et al. 2023 (Nat Commun 14:1894, the project's
  reference paper). Global genus mean for Laminaria/Saccharina C+N+P removal
  is $113,681/ha/yr; × 1.75 ha ≈ $199k/yr. Before displaying: (a) verify the
  genus-specific NITROGEN-only value from the paper/supplementary and prefer
  it (the carbon component is contested in this project); (b) label
  "illustrative benefit transfer — global means, replacement-cost basis,
  not site-specific"; (c) place it in its own fourth frame, never inside the
  fisheries frame, never in any subtotal. If verification fails, omit the
  row and note it in the handover.
- **Scenario slider**: "if X% of this bed is lost → €Y/yr of fisheries value
  at risk", computed from the €1.34M/yr headline, clearly labelled
  "a tool, not a prediction".
- **Design**: clean, restrained, human-made. No generic AI-dashboard look.
  One accent colour, serious typography, small print for provenance. The
  audience is a non-technical jury.

### Phased plan (commit after each phase)
- **Phase 0 — inventory (do this first, report before building).** List every
  file in `outputs/` and `data/` with format, CRS, size, and what it appears
  to be. Confirm which of the layers in the list above actually have data on
  disk. DO NOT invent placeholder data for missing layers; report the gap and
  proceed with what exists.
- **Phase 1 — data prep.** `src/build_map.py`: reproject everything to
  EPSG:4326 for Leaflet, simplify geometries to keep the HTML small
  (target < 15 MB), embed as JS constants. Record every dependency in
  `DEPENDENCIES.md`.
- **Phase 2 — map.** Layers, toggles, provenance captions, valuation panel,
  scenario slider.
- **Phase 3 — polish + self-check.** Test by double-clicking the file. Verify
  every number on screen against §4 of this file, character by character.
  Write `docs/DEVIR_NOTU_<date>_step6_map.md` in the established handover
  format (result → limitations → files → new locked rules → open items).

### Acceptance checklist
- [ ] Opens from disk by double-click, no console errors
- [ ] Every displayed number matches §4 exactly ("14 of 17", not 82%)
- [ ] No OPW-derived visual layer
- [ ] Scenario slider labelled "a tool, not a prediction"
- [ ] Panel uses the three-frame layout; no grand total anywhere
- [ ] Nutrient-cycling row either verified-and-labelled or omitted-and-noted
- [ ] Intertidal vs subtidal layers visually and verbally distinct
- [ ] Provenance caption on every layer
- [ ] `DEPENDENCIES.md` updated
- [ ] Handover note written, everything committed

## 7. Out of scope for this session
Presentation (Step 7), team recruitment, registration/IP, widening the
Atlantic receptor screen, thermal-exposure extension. Do not start these.
If time remains, improve the map's polish instead.
