"""Write honest, build-matched acceptance matrices from completed local QA."""
from pathlib import Path
import hashlib,html,json,subprocess
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/product_cape_clear_20261015';QA=OUT/'qa'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    manifest=read(ROOT/'outputs/map/build_manifest.json');build=manifest['build_id']
    commit=subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'rev-parse','--short','HEAD'],cwd=ROOT,text=True).strip()
    files=['test_report.json','workspace-tests.json','report-tests.json','acceptance-browser.json','pdf_readback.json','windows-launch.json','print-controls.json']
    tests={n:read(QA/n) for n in files}
    for name,report in tests.items():
        assert report['build_id']==build,(name,'stale build')
        assert report['status']=='PASS',(name,report['status'])
    for field,base in [('source_sha256',ROOT),('input_sha256',ROOT),('output_sha256',ROOT/'outputs/map')]:
        for name,digest in manifest[field].items():assert sha(base/name)==digest,name
    preservation=read(OUT/'preservation_result.json');assert preservation['status']=='PASS'
    promises=[
      ['1. Habitat mapping','PARTIAL; current kelp map unsupported','Case selection; historical/satellite/suitability toggles; collection year/search; record Locate/download; explicit analysis rectangle.','NPWS SSCO / Article 17 conflict at sample 1351; dated provider records; frozen Sherkin intertidal diagnostics. Shared survey lineage is explicit.','Stages 1–2; report §1–2: contextual map, historical timeline, same-area evidence overlays.','PASS: map click and all available layers; filtered 2019 Saccharina export; two-browser report filter round-trip. No current ecological validation claimed.','Contemporary georeferenced species/canopy map and independent spatial validation.'],
      ['2. Condition and decline risk','PARTIAL; measured health / decline unsupported','Condition and decline-driver tabs; annual wave graph; source/coverage explanations.','87,672 valid hourly CMEMS waves, 2015–2024. Point depth datum unverified. Local temperature/clarity and repeat canopy measurements absent.','Stage 2; report §3–4: median/P95 chart and four driver panels.','PASS: existing numerical/data tests; condition/risk navigation; report PDF readback. No invented composite score or loss probability.','Repeat standardised canopy/extent/density, light, temperature, pressure and recruitment observations.'],
      ['3. Coastal protection','PARTIAL; in-cell model supported as a conditional calculation','36 FROM bearings, habitat with/without, depth, coefficient sensitivity/method, A/B pin, asset filters and Locate.','EPSG:2157 central-ray intersection; Dubi & Torum laboratory kernel; 4–10 m gate; CMEMS offshore boundary; OSM coast/assets.','Stage 3; report §5–6: causal chain, rose, H/H0 comparison, depth sensitivity, path map.','PASS: 864 Cape combinations independently reconstructed in Python; 8.429535% baseline and 3.559098% at +2 m; all bearings, blocked rays, invalid depth, A/B.','Nearshore bathymetry/datum and wave transformation to receptor hazard. Four roads/three buildings remain candidates, not protected properties.'],
      ['4. Euro value','PARTIAL; funding comparator complete, avoided damage unsupported','Frontage, independent budget share, rate multiplier, discount and lifetime; low/pooled/high and annual equivalents.','Three Wexford nominal funding approvals. Frontage × funding rate × independent share; stable capital recovery factor. Never linked causally to attenuation.','Stage 4; report §7: formula, sensitivity bars, itemised inputs and bands.','PASS: 100 m/100% and 150 m/25% independent arithmetic and PDF text; zero interest; invalid inputs; source segment distinguished from selected frontage.','Hazard distributions, probabilities, exposure and damage functions plus lifecycle/maintenance/restoration costs.'],
      ['5. Biodiversity score','PARTIAL; inventory supported, kelp-bed score unsupported','Taxon, year, coordinate-flag and text filters; mapped provider records; downloads; offline report review search.','154 deduplicated Cape rectangle records from existing OBIS archive; original provider/record/event IDs, coordinates, dates and flags retained.','Stage 5; report §8: class breakdown, collection-date coverage and sampling explanation.','PASS: local bounds/dedup/flags test; class/year/search/quality map filters; frozen JSON count; empty/special-character filter round-trip.','Standardised sampling effort, habitat association and taxonomic/coordinate validation. No invented biodiversity screening score.'],
      ['6. Restoration prioritisation','PARTIAL; research plan supported, restoration approval unsupported','Priority filter and Locate investigation context; action, expertise and blockers.','Reference disagreement, depth/datum gaps, unvalidated shore transformation and missing economic inputs. Failed historical mapping diagnostics retained.','Stage 5; report §9: four action cards and investigation-context map.','PASS: all four priorities and map-linked P2 in Chrome/Edge; filtered priority preserved in report snapshot.','Present habitat, observed degradation, substrate, pressure, permissions and feasible recovery mechanism.'],
      ['7. Transferability / integrated tool','PARTIAL overall; four-case software workflow complete','Cape main case plus Sherkin, Copper Point and Bantry; optional local model in shared schema; six stages; report/JSON export.','Existing compact case contract in cape_product_evidence.py; calculations never transferred to cases lacking inputs.','All stages; report §10–12: selected state, A/B, transfer contract, licensing and provenance.','PASS: all four case reports; offline Chrome/Edge, 4 display sizes, exports, launcher and no-Python fallback.','New Atlantic sites need evidence and calibration; seagrass/saltmarsh need their own physical models. No claim of universal habitat validation.']]
    jury=[
      ['Working proof of concept','DEMONSTRATED','Six-stage offline tool; real feature inspection, numerical scenarios, comparison and selected-state HTML/PDF/JSON.','46 Python tests; 14 original workflow + 5 report + 11 new cross-browser/contrast groups; real PDFs and Windows launcher.','Scientific protection / avoided damage remains partial.'],
      ['Use of digital data','DEMONSTRATED within the saved evidence','NPWS geometry, OBIS records, 87,672-hour CMEMS series, point bathymetry, OSM geometry and preserved input/source hashes.','Build/input/output hashes; local inventory test; original-data preservation: 2,859 unchanged files.','Historical sources are not current independent ground truth.'],
      ['Ambition','DEMONSTRATED direction; full chain PARTIAL','One coherent evidence → physical scenario → coastal objects → independent funding → verification-plan workflow.','All six stages exercised on four display sizes and supporting cases.','No nearshore hazard/damage model has been calibrated.'],
      ['Environmental and social impact','POTENTIAL, not measured outcome','Real South Harbour seawall context; explicit research/monitoring priorities; avoidance of unsupported restoration and savings claims.','Map-linked investigation actions and report §6/9; scientific nulls remain null.','No ecological improvement, prevented loss or community benefit measured by this prototype.'],
      ['Innovation','DEMONSTRATED integration; novelty not certified','Directional geometric screening, provenance-aware filters, cell model A/B and independently controlled funding assumptions in one offline product.','864 independent geometry/kernel comparisons; two-browser interactive flow and full-state export.','Published coefficients are reused; no new mapping-accuracy or methodological novelty claim.'],
      ['Real team collaboration and communication','PARTIAL / event teamwork not yet evidenced','Readable case/state contracts, source trail, report and proposed ecology/GIS/engineering/economics responsibilities. Actual work is AI-assisted preparation under the owner’s direction.','Portable artifacts and build-matched acceptance evidence; no invented names, contributions or collaboration metrics.','Hackathon participants must record actual roles, joint decisions and contributions during the event.']]
    style='body{font:15px/1.55 system-ui;color:#16364a;background:#eef3f5;margin:0;padding:30px}main{max-width:1500px;margin:auto;background:white;padding:30px;border:1px solid #ccdbe1;border-radius:10px}h1{font-size:28px}p{max-width:1000px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid #cddce2;padding:13px;vertical-align:top;text-align:left}th{background:#e8f0f4}tr:nth-child(even){background:#f7f9fa}td:nth-child(2){font-weight:650}small{color:#526672}.scroll{overflow:auto}@media print{body{padding:0;background:white}main{border:0;padding:0}table{font-size:9px}td,th{padding:6px}@page{size:A3 landscape;margin:12mm}}'
    for filename,title,headers,rows in [('PROMISE_MATRIX','Seven published promises',['Promise','True status','Working control / layer','Evidence / calculation','App / report visual','Actual test result','Necessary scientific next step'],promises),('JURY_MATRIX','Six jury criteria',['Criterion','True status','Concrete demonstrable evidence','Verification','Honest limit'],jury)]:
        document='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+style+'</style><main><h1>'+title+'</h1><p>Build <b>'+build+'</b> · 15 October 2026. Software acceptance is not ecological validation. PARTIAL means the demonstrated component is real, but the full scientific promise is not established.</p><div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div><p><small>Acceptance evidence: qa/test_report.json, workspace-tests.json, report-tests.json, acceptance-browser.json, pdf_readback.json and windows-launch.json. Original data and final presentation/video are unchanged.</small></p></main></html>'
        (OUT/(filename+'.html')).write_text(document,encoding='utf8')
        (OUT/(filename+'.json')).write_text(json.dumps({'build_id':build,'columns':headers,'rows':rows},indent=2),encoding='utf8')
    totals={n:len(tests[n].get('checks',[])) for n in ['workspace-tests.json','report-tests.json','acceptance-browser.json']}
    acceptance={'build_id':build,'commit':commit,'created_utc':datetime.now(timezone.utc).isoformat(),'status':'PASS_SOFTWARE_SCIENTIFIC_PROMISES_PARTIAL','python_tests':46,'browser_check_groups':totals,'test_artifacts':{n:sha(QA/n) for n in files},'test_source_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'tests').glob('*') if p.is_file()},'report_artifacts':{n:sha(OUT/n) for n in ['ASSESSMENT_CAPE_CLEAR.html','ASSESSMENT_CAPE_CLEAR.json','ASSESSMENT_CAPE_CLEAR.pdf','PROMISE_MATRIX.html','JURY_MATRIX.html']},'preserved_files':preservation['files_checked'],'new_training_runs':0,'final_media_modified':False,'visual_review':'Both 13-page report contact sheets and key full pages, desktop/mobile/projector application screenshots inspected. No clipped, overlapping or empty pages found.','limits':['No current validated kelp extent','No measured habitat decline or kelp-bed biodiversity score','No validated shoreline hazard, protected buildings or avoided damage','Automated timed walkthrough is not a human usability study','Actual hackathon team contributions not yet evidenced']}
    (OUT/'acceptance.json').write_text(json.dumps(acceptance,indent=2),encoding='utf8')
    text=f'''CAPE CLEAR PRODUCT ACCEPTANCE — 15 October 2026
Build: {build}
Commit: {commit}
Status: software acceptance PASS; scientific promises remain PARTIAL as itemised in PROMISE_MATRIX.html.

LAUNCH
In Windows File Explorer open C:\\Users\\Elif\\Desktop\\OCEANHACKATHON and double-click START_DEMO.bat.
The current self-contained application opens offline in the default browser. No server or terminal must stay open.
When .venv/Python is missing, the same batch opens outputs/map/index.html directly. Rebuild/check still need the development runtime.
If an old tab remains open, use Ctrl+F5. A chat link to a batch file is not an execution guarantee.
Optional server: .venv\\Scripts\\python.exe src\\launch_demo.py --serve.

CONFIRMED FIXES
- Removed archived illustrative 100 m from active warnings. Live frontage/share drive all current values; the source project's own 100 m remains explicitly labelled.
- Cape AllSurvey datum is unverified throughout; no LAT transfer from Copper Point.
- Historical year/search filters now control report rows and exported selected records.
- Biology year/class/quality/search filters update the map and report; raw labels and provider IDs remain.
- Leaflet renderer initialises before boundary layers; actual map click and visible canvas are tested.
- Shared semantic palette, symbols and labels; accessible badge contrast; step guidance, progress, live scenario result strip and mobile assessment shortcut.
- Empty map layers are disabled with an explicit reason. Modelled Sherkin suitability is separate from satellite intertidal macroalgae and historical layers.
- Map-linked investigation actions, readable charts and no invented condition/biodiversity/benefit scores.

REPORT
12 sections, 13 A4 pages in each saved default and modified PDF.
First-page decision/map/findings; source comparison/timeline; annual wave series and risk drivers; directional rose, path and cell sensitivity; funding assumptions and bands; biodiversity coverage; mapped investigation actions; A/B and provenance.
Offline HTML has section navigation, print and read-only record review search. That review filter never changes the immutable selected state. Change assessment inputs in the app and regenerate. PDF is fixed, not an editable interactive PDF.
Default: ASSESSMENT_CAPE_CLEAR.html / .pdf / .json
Modified regression (150 m / 25%, FROM 200°, +2 m, zero discount, Phaeophyceae, pinned baseline): qa/ASSESSMENT_MODIFIED.html / .pdf / .json

ACTUAL TESTS
46 Python tests PASS, including 864 independently reconstructed Cape geometry/kernel scenarios.
14 existing workspace groups + 5 report groups + 11 cross-browser/contrast groups PASS. Two real print buttons also trigger the print lifecycle (qa/print-controls.json); the native Save dialog itself was not automated.
Windows Chrome and Edge, offline file operation, no external requests / JavaScript errors in tested flows.
1600x1000 desktop; 1366x768 laptop; 1280x720 and 1920x1080 projectors; 390x844 mobile.
Scripted guided six-stage walkthrough completed below 60 seconds in both browsers (about 1 second automated; no claim of a human user study).
Default and modified PDFs: extracted text, input-specific money/annual equivalents, direction, model result, sources/datum, all 12 sections and matching build IDs PASS. Page images rendered and visually inspected.
Windows shell invocation of actual START_DEMO.bat and isolated no-Python fallback: exit 0; equivalent file association to Explorer, not a physical mouse double-click claim. The fallback test uses a junction, not copied data.
2,859 protected original data/research/media files unchanged. Frozen held-out mapping tests untouched. No training. No jury presentation, speaker notes or demo video modified.

QA PROVENANCE
Current evidence is named in acceptance.json and sha256-hashed. qa/test_report.json and qa/pdf_readback.json match {build}.
Old f611c7dbc4e7 / 32caac3b209d PDF readback, reproduction and render sheets are under qa/archive_pre_improvement/, explicitly retired from current acceptance.
Other build-ID render folders are historical iterative checks, not current acceptance.

SCIENTIFIC NEXT STEP
Contemporary georeferenced kelp/canopy survey at the supported Cape hypothesis, source reconciliation and bathymetry datum check; then nearshore wave/hazard validation. No present-day kelp extent, measured decline, local bed score, protected property, restoration approval or avoided-damage euro claim is created by the visual redesign.

REPRODUCE
REBUILD_DEMO.bat --no-pause
CHECK_DEMO.bat --no-pause
powershell -File tests/check_launcher_windows.ps1
Bundled Node: tests/browser_cape_print.cjs
Bundled Python: tests/verify_cape_pdf.py and tests/write_cape_acceptance.py
The first three require the existing development/runtime paths on this workstation; the delivered application and reports do not.
'''
    (OUT/'ACCEPTANCE.txt').write_text(text,encoding='utf8');(OUT/'HANDOVER.txt').write_text(text,encoding='utf8')
    (QA/'product_reproduction.json').write_text(json.dumps({'build_id':build,'status':'PASS','basis':'Current manifest source/input/output hashes and completed CHECK_DEMO; no claim of a separate fresh-environment rebuild','acceptance_sha256':sha(OUT/'acceptance.json')},indent=2),encoding='utf8')
    print('PASS: current build matched across acceptance evidence; two honest matrices written.')
if __name__=='__main__':main()
