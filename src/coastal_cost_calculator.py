#!/usr/bin/env python3
"""Calculate the project's documented coastal-engineering cost scenarios.

This is a numerical calculator, NOT an estimate of avoided damage.
Source method: docs/DEVIR_NOTU_2026-08-12_step5b_replacement_cost.md, section 3.
It reads the existing model-cell count and map inputs; it never invents a
measured protective frontage or converts asset counts into euros.

Example (Windows):
  py calculate_coastal_costs.py C:\\Users\\Elif\\Desktop\\OCEANHACKATHON --apply

Without --apply it prints calculations only. With --apply it also saves JSON/CSV
results and adds the calculator to BOTH the existing map and its build template.
It does not require apply_coastal_zero_fix.py. No third-party packages, network
requests, automatic package installation or full map rebuild are used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import struct
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "1.0.1"
CELL_SIDE_M = 50.0  # SAME model-footprint convention as src/build_map.py; not a survey.
ASSUMED_WIDTHS_M = (50.0, 100.0, 150.0, 200.0)  # Existing handover-note scenarios.
START = "<!-- COASTAL_COST_CALCULATOR_V1_START -->"
END = "<!-- COASTAL_COST_CALCULATOR_V1_END -->"
SOURCES = [
    {"key": "Seaview_2024_155m", "year": 2024, "approved_funding_eur": 668921,
     "reported_length_m": 155,
     "url": "https://www.floodinfo.ie/county-summary/?c=25"},
    {"key": "Seaview_2024_100m", "year": 2024, "approved_funding_eur": 657338,
     "reported_length_m": 100,
     "url": "https://www.floodinfo.ie/county-summary/?c=25"},
    {"key": "Seaview_2026_70m", "year": 2026, "approved_funding_eur": 500535,
     "reported_length_m": 70,
     "url": "https://www.gov.ie/en/office-of-public-works/press-releases/"
            "minister-kevin-boxer-moran-announces-additional-funding-approval-"
            "for-minor-flood-mitigation-works-and-coastal-protection-for-seaview-"
            "bastardstown-county-wexford/"},
]
LIMITS = [
    "Not estimated avoided damage, annual benefit, validated ecosystem value, or a construction quote.",
    "Model area = model-cell count x 50 m x 50 m. Not surveyed current kelp area.",
    "Comparison frontage = model area / ASSUMED cross-shore width. No protected coastline was measured.",
    "The project energy-reduction percentage is an unvalidated model input, not a cost-saving fraction.",
    "Multiplying engineering funding by that percentage is the project's own pro-rata scenario, not a published cost-response model.",
    "No equivalence, least-cost alternative, or demand condition has been demonstrated by this calculator.",
    "Rock revetment is not functionally identical to kelp or a nearshore breakwater.",
    "Three selected interventions at one Wexford site; approved grants, not final project costs. Not three independent sites.",
    "2024 and 2026 nominal amounts are not inflation-adjusted. No grant gross-up, local design adjustment or maintenance cost is added.",
    "Annualised figures are mathematical capital equivalents, not observed annual savings. Ranges are scenario ranges, not confidence intervals.",
    "The 4% rate and 50-year life are retained project assumptions, not re-certified policy requirements.",
    "Do not add these scenario figures to fisheries, nitrogen, biodiversity, or other service totals.",
]


def checked(value: Any, name: str, *, minimum: float = 0.0,
            maximum: float | None = None, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: a number is required, not a boolean")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}: a finite number is required") from exc
    if not math.isfinite(result) or result < minimum or (positive and result <= minimum):
        raise ValueError(f"{name}: invalid value {value!r}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name}: must not exceed {maximum}")
    return result


def capital_recovery_factor(rate: float, years: float) -> float:
    rate = checked(rate, "annual discount rate", maximum=1.0)
    years = checked(years, "design life", positive=True, maximum=1000.0)
    if rate == 0.0:
        return 1.0 / years
    # Stable at very small positive rates too.
    return rate / (-math.expm1(-years * math.log1p(rate)))


def unit_rates() -> dict[str, float]:
    individual = [s["approved_funding_eur"] / s["reported_length_m"] for s in SOURCES]
    return {
        "low": min(individual),
        "project_pooled": sum(s["approved_funding_eur"] for s in SOURCES) /
                          sum(s["reported_length_m"] for s in SOURCES),
        "high": max(individual),
    }


def calculate(area_m2: float, assumed_width_m: float, energy_fraction: float,
              discount_rate: float, years: float,
              rates: dict[str, float] | None = None) -> dict[str, Any]:
    area_m2 = checked(area_m2, "model area", positive=True)
    width = checked(assumed_width_m, "ASSUMED cross-shore width", positive=True)
    fraction = checked(energy_fraction, "energy fraction", maximum=1.0)
    crf = capital_recovery_factor(discount_rate, years)
    rates = unit_rates() if rates is None else rates
    if set(rates) != {"low", "project_pooled", "high"}:
        raise ValueError("Three rate keys required: low, project_pooled, high")
    rates = {k: checked(v, f"unit rate {k}", positive=True) for k, v in rates.items()}
    if not rates["low"] <= rates["project_pooled"] <= rates["high"]:
        raise ValueError("Unit-rate bands are not ordered")
    length = area_m2 / width
    rows = {}
    for band, rate in rates.items():
        full = length * rate
        scaled = full * fraction
        rows[band] = {
            "approved_funding_rate_eur_per_m": rate,
            "full_length_funding_benchmark_eur": full,
            "pro_rata_cost_scenario_eur": scaled,
            "annualised_full_benchmark_eur_per_year": full * crf,
            "annualised_pro_rata_scenario_eur_per_year": scaled * crf,
        }
    return {
        "status": "CALCULATED_CONDITIONAL_COST_SCENARIO_NOT_ECOSYSTEM_VALUATION",
        "model_area_m2": area_m2,
        "assumed_cross_shore_width_m": width,
        "inferred_comparison_frontage_m": length,
        "frontage_is_measured": False,
        "energy_reduction_fraction_parameter": fraction,
        "annual_discount_rate_assumption": discount_rate,
        "design_life_years_assumption": years,
        "capital_recovery_factor": crf,
        "bands": rows,
        "avoided_damage_eur": None,
        "annual_avoided_damage_eur": None,
        "kelp_service_value_eur": None,
        "cost_equals_benefit": False,
    }


def read_point(blob: bytes) -> tuple[float, float]:
    if not isinstance(blob, bytes) or len(blob) < 29 or blob[:2] != b"GP":
        raise ValueError("Invalid GeoPackage point geometry")
    flag = blob[3]
    if flag & 0x10:
        raise ValueError("Empty model-cell geometry")
    env = (flag >> 1) & 7
    envelopes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if env not in envelopes:
        raise ValueError("Unsupported GeoPackage envelope")
    off = 8 + envelopes[env]
    if len(blob) < off + 21 or blob[off] not in (0, 1):
        raise ValueError("Invalid WKB point")
    endian = "<" if blob[off] == 1 else ">"
    kind = struct.unpack_from(endian + "I", blob, off + 1)[0]
    if kind not in (1, 1001, 2001, 3001):
        raise ValueError("kelp_cells must contain points")
    x, y = struct.unpack_from(endian + "dd", blob, off + 5)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("Non-finite model-cell coordinate")
    return x, y


def snapshot_from_html(text: str) -> dict[str, Any]:
    """Read D from either the built map or the template-like test fixture.

    src/build_map.py replaces the *whole* `/*__MAP_DATA__*/null` token with
    JSON, so production index.html intentionally does NOT contain the marker.
    Read the actual `const D = {...};` declaration instead.
    """
    matches = list(re.finditer(r"\bconst\s+D\s*=\s*", text))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one embedded 'const D =' map data declaration "
            f"in outputs/map/index.html; found {len(matches)}"
        )
    tail = text[matches[0].end():]
    # Support the original pre-fix test fixtures too, without requiring a
    # marker that is absent from the real built file.
    tail = re.sub(r"^\s*/\*__MAP_DATA__\*/\s*", "", tail, count=1)
    try:
        result, _end = json.JSONDecoder().raw_decode(tail.lstrip())
    except json.JSONDecodeError as exc:
        raise ValueError("Cannot read embedded JSON from built map's const D declaration") from exc
    if not isinstance(result, dict) or not (isinstance(result.get("locked"), dict) or result.get('schema_version')==2):
        raise ValueError("Embedded map data is missing; read outputs/map/index.html, not the unbuilt template")
    return result


def read_inputs(root: Path) -> dict[str, Any]:
    gpkg = root / "outputs" / "valuation" / "step3b2_flood_check.gpkg"
    index = root / "outputs" / "map" / "index.html"
    if not gpkg.is_file() or not index.is_file():
        raise ValueError("Required files: outputs/valuation/step3b2_flood_check.gpkg and outputs/map/index.html")
    with closing(sqlite3.connect(gpkg.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        rec = con.execute("SELECT column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns WHERE table_name=?", ("kelp_cells",)).fetchone()
        if not rec or rec[1].upper() != "POINT" or rec[2] != 2157:
            raise ValueError("Expected kelp_cells POINT geometry in EPSG:2157")
        col = '"' + rec[0].replace('"', '""') + '"'
        coords = [read_point(r[0]) for r in con.execute(f'SELECT {col} FROM "kelp_cells"')]
    if not coords or len(coords) != len(set(coords)):
        raise ValueError("Model cells are missing or have duplicate centres")
    snapshot = snapshot_from_html(index.read_text(encoding="utf-8-sig"))
    modern=snapshot.get('schema_version')==2
    locked = snapshot.get("locked",{})
    area = len(coords) * CELL_SIDE_M ** 2
    map_area = checked(snapshot['site']['area_ha'] if modern else locked.get("bed_ha"), "map model area", positive=True) * 10000.0
    if not math.isclose(area, map_area, rel_tol=0.0, abs_tol=0.01):
        raise ValueError(f"Map/GPKG model-area mismatch: {map_area} vs {area} m2. No patch applied.")
    pct = checked(snapshot['costs']['default']['energy_reduction_fraction_parameter']*100 if modern else locked.get("wave_energy_reduction_pct"), "existing scenario parameter", maximum=100.0)
    return {
        "model_cell_count": len(coords), "model_cell_side_m_assumption": CELL_SIDE_M,
        "model_area_m2": area, "energy_reduction_fraction": pct / 100.0,
        "model_inputs_are_validated_observations": False,
        "gpkg_sha256": hashlib.sha256(gpkg.read_bytes()).hexdigest(),
        "original_map_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "area_source": "outputs/valuation/step3b2_flood_check.gpkg:kelp_cells; map's 50 m-square model convention",
        "energy_source": "existing outputs/map/index.html: D.costs.default (legacy pro-rata assumption)" if modern else "existing outputs/map/index.html: D.locked.wave_energy_reduction_pct",
        "integrated_v2":modern,
        "method_source": "docs/DEVIR_NOTU_2026-08-12_step5b_replacement_cost.md section 3 (conditional illustration)",
    }


JS = r'''
(function () {
  "use strict";
  const cfg = __CONFIG__;
  const frame = document.querySelector(".frame.coastal");
  if (!frame) { console.error("Coastal calculator: .frame.coastal not found. Original map unchanged."); return; }
  const oldD = typeof D === "object" && D ? D : null;
  if (!oldD || !oldD.locked || Math.abs(Number(oldD.locked.bed_ha) * 10000 - cfg.model_area_m2) > .01) {
    frame.innerHTML = "<h3>Coastal cost calculator</h3><p>Input mismatch. Re-run calculate_coastal_costs.py --apply after rebuilding model data. No stale monetary result is shown.</p>";
    return;
  }
  // Uses the map's model parameter, never an observed reduction or a cost-saving claim.
  const mappedPct = Number(oldD.locked.wave_energy_reduction_pct);
  if (!Number.isFinite(mappedPct) || mappedPct < 0 || mappedPct > 100) {
    frame.innerHTML = "<h3>Coastal cost calculator</h3><p>Missing model parameter. No monetary result computed.</p>"; return;
  }
  const money = n => new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(n);
  const number = n => new Intl.NumberFormat("en-IE", { maximumFractionDigits: 2 }).format(n);
  function crf(r, n) { return r === 0 ? 1/n : r / (-Math.expm1(-n * Math.log1p(r))); }
  function run(area, width, share, r, years, rates) {
    const args = [area, width, share, r, years, rates.low, rates.project_pooled, rates.high];
    if (args.some(v => !Number.isFinite(v)) || area <= 0 || width <= 0 || share < 0 || share > 1 || r < 0 || r > 1 || years <= 0 || years > 1000 || rates.low <= 0 || rates.low > rates.project_pooled || rates.project_pooled > rates.high) throw new Error("Enter valid, finite inputs. Width/life/rates must be positive; reduction 0-100%; discount 0-100%.");
    const length = area/width, f=crf(r, years), bands={};
    for (const key of ["low", "project_pooled", "high"]) {
      const full=length*rates[key];
      bands[key] = {full: full, pro: full*share, annual: full*share*f};
    }
    return {length, bands};
  }
  frame.id = "coastal-cost-calculator";
  frame.innerHTML = `
    <h3>Coastal protection — calculated cost scenarios</h3>
    <p><b>Engineering-funding comparison, not avoided damage.</b></p>
    <p class="fineprint">Runs the project's existing area / width × funding rate × model-percentage scenario. Amounts change when inputs change. It does not establish what the kelp protects or what damage it prevents.</p>
    <p class="fineprint">Model-cell area: <b>${number(cfg.model_area_m2/10000)} ha</b>. Not surveyed current kelp area.</p>
    <div style="display:grid;grid-template-columns:1fr 90px;gap:8px;align-items:center;margin:12px 0">
      <label for="cc-width">ASSUMED cross-shore width (m)</label><input id="cc-width" type="number" min="1" step="1" value="${cfg.default_width_m}">
      <label for="cc-effect">Model-energy parameter (%)</label><input id="cc-effect" type="number" min="0" max="100" step="0.1" value="${mappedPct}">
      <label for="cc-rate">Discount-rate assumption (%)</label><input id="cc-rate" type="number" min="0" max="100" step="0.1" value="${cfg.discount_rate*100}">
      <label for="cc-life">Lifetime assumption (years)</label><input id="cc-life" type="number" min="1" max="1000" step="1" value="${cfg.years}">
    </div>
    <p class="fineprint">Derived comparison length: <b id="cc-length"></b>. Area ÷ assumed width; <b>not a measured protected frontage.</b></p>
    <p id="cc-error" role="alert" style="display:none"></p>
    <div id="cc-values" aria-live="polite">
      <div class="row"><span class="what">Full-length funding benchmark — one-off</span><span class="amount" id="cc-full"></span></div>
      <div class="row"><span class="what">Project pro-rata scenario — one-off</span><span class="amount" id="cc-pro"></span></div>
      <div class="row"><span class="what">Annualised pro-rata scenario — €/year</span><span class="amount" id="cc-annual"></span></div>
      <p class="fineprint">Project pooled-rate baseline: <b id="cc-central"></b>/year. This is a capital-cost equivalent, <b>not annual savings</b>.</p>
    </div>
    <p class="fineprint"><b>Key assumption:</b> the cost share is set equal to the model-energy percentage only to reproduce the existing project scenario. This is <b>not a validated cost-response relationship</b>; reducing wave energy by 15.2% does not establish a 15.2% cost or damage saving.</p>
    <details><summary>Width sensitivity — all other inputs unchanged</summary>
      <table style="width:100%;font-size:11px"><thead><tr><th>Assumed width</th><th>Derived length</th><th>Annual cost scenario</th></tr></thead><tbody id="cc-sensitivity"></tbody></table>
    </details>
    <details style="margin-top:8px"><summary>Sources and limits</summary>
      <p class="fineprint">Rates: €668,921/155 m (2024), €657,338/100 m (2024), €500,535/70 m (2026). Three selected interventions at one Wexford site; approved funding, not final construction costs. Pooled rate = selected funding / selected reported lengths. Local Cork design, inflation, grant gross-up and maintenance are not included.</p>
      <p class="fineprint"><a href="https://www.floodinfo.ie/county-summary/?c=25" target="_blank" rel="noopener noreferrer">OPW funding records</a> · <a href="${cfg.sources[2].url}" target="_blank" rel="noopener noreferrer">2026 70 m approval</a></p>
      <p class="fineprint">Rock revetment is not the same service as a kelp bed or nearshore breakwater. Service equivalence, least-cost substitution and demand have not been demonstrated. These figures are a <b>counterfactual illustration — not a value</b>, not a proven upper bound, not a confidence interval, and not a construction recommendation.</p>
      <p class="fineprint">Existing model habitat, species, density and wave attenuation require validation. Do not sum these scenarios with fisheries or other services. Method reproduced from the project's 12 August replacement-cost note, section 3.</p>
    </details>
    <p class="fineprint" style="margin-top:12px"><b>Actual avoided coastal damage: not estimated by this calculator.</b> Missing evidence is not recorded as €0.</p>
    <button type="button" id="cc-download" style="margin-top:8px">Export current calculation (JSON)</button>
  `;
  for (const e of frame.querySelectorAll("input")) {e.style.width="88px";e.style.boxSizing="border-box";e.style.font="inherit";}
  for (const e of frame.querySelectorAll(".row")) {e.style.display="block";e.style.marginTop="10px";}
  for (const e of frame.querySelectorAll(".amount")) {e.style.display="block";e.style.whiteSpace="normal";e.style.fontWeight="650";}
  let last=null;
  const at = id => document.getElementById(id);
  function update() {
    try {
      const numeric = id => {const raw=at(id).value.trim();if(raw === "")throw new Error("An input is blank; no result is displayed.");return Number(raw);};
      const width=numeric("cc-width"), share=numeric("cc-effect")/100, rate=numeric("cc-rate")/100, years=numeric("cc-life");
      const result=run(cfg.model_area_m2,width,share,rate,years,cfg.rates);
      const range = key => money(result.bands.low[key])+" – "+money(result.bands.high[key]);
      at("cc-length").textContent=number(result.length)+" m";
      at("cc-full").textContent=range("full");at("cc-pro").textContent=range("pro");at("cc-annual").textContent=range("annual")+"/year";
      at("cc-central").textContent=money(result.bands.project_pooled.annual);
      at("cc-error").style.display="none";at("cc-values").hidden=false;at("cc-download").disabled=false;
      at("cc-sensitivity").innerHTML=cfg.assumed_widths_m.map(w=>{const t=run(cfg.model_area_m2,w,share,rate,years,cfg.rates);return `<tr><td>${number(w)} m</td><td>${number(t.length)} m</td><td>${money(t.bands.low.annual)} – ${money(t.bands.high.annual)}</td></tr>`;}).join("");
      last={status:"CALCULATED_CONDITIONAL_COST_SCENARIO_NOT_ECOSYSTEM_VALUATION", model_area_m2:cfg.model_area_m2,assumed_cross_shore_width_m:width,inferred_comparison_frontage_m:result.length,frontage_is_measured:false,energy_fraction_parameter:share,discount_rate_assumption:rate,lifetime_years_assumption:years,rates:cfg.rates,bands:result.bands,avoided_damage_eur:null,kelp_service_value_eur:null,sources:cfg.sources,limitations:cfg.limitations};
    } catch(e) {
      last=null;at("cc-error").textContent=e.message;at("cc-error").style.display="block";at("cc-values").hidden=true;at("cc-sensitivity").innerHTML="";at("cc-length").textContent="invalid input";at("cc-download").disabled=true;
    }
  }
  for(const id of ["cc-width","cc-effect","cc-rate","cc-life"]) at(id).addEventListener("input",update);
  at("cc-download").addEventListener("click",()=>{if(!last)return;const blob=new Blob([JSON.stringify(last,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="coastal_cost_scenario.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  update();
  // Read-only test hook; no other map variables or datasets are modified.
  window.CoastalCostCalculator={version:"1.0.1",calculate:run,getResult:()=>last};
})();
'''


def make_block(inputs: dict[str, Any], width: float, rate: float, years: float) -> str:
    cfg = {"model_area_m2": inputs["model_area_m2"], "default_width_m": width,
           "discount_rate": rate, "years": years, "assumed_widths_m": ASSUMED_WIDTHS_M,
           "sources": SOURCES, "rates": unit_rates(), "limitations": LIMITS}
    # ASCII-safe embedding also avoids HTML entities / Windows encoding changes.
    payload = json.dumps(cfg, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    script = JS.replace("__CONFIG__", payload)
    return START + '\n<script id="coastal-cost-calculator-script">\n' + script + '\n</script>\n' + END


def patch_html(text: str, block: str) -> str:
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise ValueError("Ambiguous existing calculator markers; no edits made")
    if START in text:
        a=text.index(START); b=text.index(END,a)+len(END)

        if text[b:b+2] == "\r\n": b += 2
        elif text[b:b+1] == "\n": b += 1
        text=text[:a]+text[b:]
    if not re.search(r'class\s*=\s*[\"\'][^\"\']*\bcoastal\b', text):
        raise ValueError("Cannot locate the existing coastal panel; no edits made")
    matches=list(re.finditer(r"</body\s*>",text,re.IGNORECASE))
    if len(matches)!=1:
        raise ValueError("Expected one closing body tag; no edits made")
    pos=matches[0].start()
    return text[:pos]+block+"\n"+text[pos:]


def encode_like(data: bytes, text: str) -> bytes:
    return text.encode("utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".coastal-calc-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    except BaseException:
        try:os.unlink(tmp)
        except OSError:pass
        raise


def apply_files(root: Path, inputs: dict[str, Any], selected: dict[str, Any], scenarios: list,
                width: float, rate: float, years: float) -> Path:
    block=make_block(inputs,width,rate,years)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backup=root/"data"/"_coastal_calculator_backup"/stamp
    planned: list[tuple[Path,bytes|None,bytes]]=[]
    # Both targets are preflighted BEFORE any original file is changed.
    for rel in ("src/map_template.html","outputs/map/index.html"):
        path=root/rel;old=path.read_bytes();text=old.decode("utf-8-sig")
        new=encode_like(old,patch_html(text,block))
        planned.append((path,old,new))
    result={"version":VERSION,"created_utc":datetime.now(timezone.utc).isoformat(),
            "inputs":inputs,"selected_scenario":selected,"width_scenarios":scenarios,
            "sources":SOURCES,"limitations":LIMITS}
    out=root/"outputs"/"coastal_cost_calculation"
    buf=io.StringIO(newline="")
    fields=["assumed_cross_shore_width_m","inferred_comparison_frontage_m","rate_band",
            "approved_funding_rate_eur_per_m","full_length_funding_benchmark_eur",
            "pro_rata_cost_scenario_eur","annualised_pro_rata_scenario_eur_per_year",
            "annual_discount_rate_assumption","design_life_years_assumption","status"]
    writer=csv.DictWriter(buf,fieldnames=fields);writer.writeheader()
    for s in scenarios:
        for band,b in s["bands"].items():
            row={k:s.get(k) for k in fields};row.update({k:b[k] for k in fields if k in b});row["rate_band"]=band;writer.writerow(row)
    for path,content in [(out/"calculation.json",json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8")),
                         (out/"scenarios.csv",buf.getvalue().encode("utf-8-sig")),
                         (root/"src"/"coastal_cost_calculator.py",Path(__file__).read_bytes())]:
        old=path.read_bytes() if path.exists() else None;planned.append((path,old,content))
    manifest=[]
    for path,old,new in planned:
        rel=path.relative_to(root)
        if old is not None:
            dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old)
        manifest.append({"path":str(rel),"previously_existed":old is not None,
                         "before_sha256":hashlib.sha256(old).hexdigest() if old is not None else None,
                         "after_sha256":hashlib.sha256(new).hexdigest()})
    backup.mkdir(parents=True,exist_ok=True)
    (backup/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    written=[]
    try:
        for path,old,new in planned:
            written.append((path,old));atomic_write(path,new)
    except BaseException:
        for path,old in reversed(written):
            if old is None:
                try:path.unlink()
                except FileNotFoundError:pass
            else:atomic_write(path,old)
        raise
    return backup


def main(argv: list[str] | None = None) -> int:
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project",type=Path)
    ap.add_argument("--apply",action="store_true",help="Back up files, add working calculator to existing map, and save calculations")
    ap.add_argument("--width-m",type=float,default=100.0,help="ASSUMED cross-shore width; default from project note (not measured)")
    ap.add_argument("--discount-percent",type=float,default=4.0)
    ap.add_argument("--years",type=float,default=50.0)
    args=ap.parse_args(argv)
    try:
        root=args.project.expanduser().resolve();inputs=read_inputs(root)
        rate=checked(args.discount_percent,"discount percentage",maximum=100)/100
        selected=calculate(inputs["model_area_m2"],args.width_m,inputs["energy_reduction_fraction"],rate,args.years)
        scenarios=[calculate(inputs["model_area_m2"],w,inputs["energy_reduction_fraction"],rate,args.years) for w in ASSUMED_WIDTHS_M]
        print("CALCULATION COMPLETE: CONDITIONAL COST SCENARIOS (NOT AVOIDED DAMAGE)")
        print(f"Model footprint: {inputs['model_cell_count']} x 50 m cells = {inputs['model_area_m2']/10000:g} ha")
        print(f"Energy-model input: {inputs['energy_reduction_fraction']*100:g}% (not a verified cost-saving fraction)")
        print(f"Annualisation assumptions: {args.discount_percent:g}% over {args.years:g} years")
        print("\nASSUMED width | INFERRED length | pro-rata one-off EUR | annualised pro-rata EUR/year")
        for s in scenarios:
            lo=s["bands"]["low"];hi=s["bands"]["high"]
            print(f"{s['assumed_cross_shore_width_m']:>12.1f} | {s['inferred_comparison_frontage_m']:>15.2f} | "
                  f"{lo['pro_rata_cost_scenario_eur']:>10,.0f} - {hi['pro_rata_cost_scenario_eur']:>10,.0f} | "
                  f"{lo['annualised_pro_rata_scenario_eur_per_year']:>8,.0f} - {hi['annualised_pro_rata_scenario_eur_per_year']:>8,.0f}")
        print("\nThis reproduces the project's explicit pro-rata assumption, not a measured kelp benefit.")
        print("Actual avoided damage and ecosystem service value remain missing, never forced to zero.")
        if args.apply:
            if inputs.get('integrated_v2'):
                out=root/'outputs/overnight_20261013/calculator_cli.json'
                atomic_write(out,json.dumps({'inputs':inputs,'selected_scenario':selected,'width_scenarios':scenarios,'sources':SOURCES,'limitations':LIMITS},indent=2).encode())
                print('Integrated v2 calculator is already built into the application. Saved CLI scenario:',out)
                print('Change live assumptions in the application. Use REBUILD_DEMO.bat to rebuild its sources.')
                return 0
            backup=apply_files(root,inputs,selected,scenarios,args.width_m,rate,args.years)
            print("\nSUCCESS: actual calculator added to current map AND build template.")
            print("No previous patch is required. No new HTML report. No model/flood data or CLAUDE.md edits.")
            print("Calculations:",root/"outputs"/"coastal_cost_calculation"/"calculation.json")
            print("Backups:",backup)
            print("Refresh localhost:8000/index.html with Ctrl+F5.")
            print("Find: Coastal protection - calculated cost scenarios (below Fisheries support).")
        else:
            print("\nPRINT-ONLY: no files changed. Add --apply to install this calculator in the existing map.")
        return 0
    except (ValueError,OSError,UnicodeError,sqlite3.Error,struct.error) as exc:
        print(f"STOPPED: {exc}",file=sys.stderr)
        print("Calculations/installation not completed. Original model inputs were not edited.",file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
