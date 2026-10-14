"""Cross-deliverable acceptance gate; scientific unavailability is reported separately."""
from pathlib import Path
from zipfile import ZipFile
import json,hashlib,datetime,subprocess,re,math,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_delivery_20261014';QA=OUT/'qa'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def check(name,condition,detail=None):checks.append(dict(name=name,status='PASS' if condition else 'FAIL',detail=detail))
m=read(ROOT/'outputs/map/build_manifest.json');d=read(ROOT/'outputs/map/evidence.json');build=m['build_id'];app=read(OUT/'APP_REPORT_FREEZE.json');pitch=read(OUT/'PRESENTATION_FREEZE.json');report=read(OUT/'ASSESSMENT_STATE.json');scenario=read(OUT/'PRESENTATION_SCENARIO.json')
check('same_build_id',len({build,d['build_id'],app['build_id'],pitch['build_id'],report['build_id'],scenario['build_id']})==1)
mismatch=[]
for field,base in [('source_sha256',ROOT),('input_sha256',ROOT),('output_sha256',ROOT/'outputs/map')]:
    for name,value in m[field].items():
        if not (base/name).exists() or sha(base/name)!=value:mismatch.append(name)
check('source_inputs_and_application_outputs_unchanged',not mismatch,mismatch)
check('frozen_pdf_unchanged',sha(OUT/'ASSESSMENT_PILOT.pdf')==app['report_sha256'])
changed=[name for name,value in pitch['files'].items() if not (OUT/name).exists() or sha(OUT/name)!=value]
check('frozen_presentation_unchanged',not changed,changed)
reference=d['workspace']['reference_scenario'];check('same_scenario_inputs',reference['inputs']==scenario['scenario']['inputs']==report['assessment']['inputs'])
for field in ['height_fraction','energy_fraction','comparison_length_m']:
    check('shared_'+field,math.isclose(reference[field],scenario['model'][field],abs_tol=1e-7) and math.isclose(reference[field],report['assessment'][field],abs_tol=1e-7))
for key in ['low','project_pooled','high']:
    check('shared_capital_'+key,math.isclose(reference['bands'][key]['capital_eur'],scenario['model']['bands'][key]['capital_eur'],abs_tol=.01) and math.isclose(reference['bands'][key]['capital_eur'],report['assessment']['bands'][key]['capital_eur'],abs_tol=.01))
results={}
for name in ['test_report','workspace-tests','report-tests','presentation-ui-tests','media-tests','rehearsal-tests']:
    p=QA/(name+'.json');result=read(p) if p.exists() else {'status':'MISSING'};results[name]=result;check(name,result['status']=='PASS')
check('final_app_tests_use_current_build',results['test_report'].get('build_id')==build)
check('all_browser_tests_use_current_build',all(results[name].get('build_id')==build for name in ['workspace-tests','report-tests']))
rehearsals=results['rehearsal-tests'].get('results',[])
check('all_rehearsals_use_current_build',len(rehearsals)==3 and all(row.get('build_id')==build for row in rehearsals))
native=read(QA/'final-powerpoint-checks.json');check('native_decks_rendered',all(row['status']=='PASS' and row['opened_in_powerpoint'] and all(s['render_unchanged'] for s in row['slides']) for row in native))
check('native_timings',sum(s['seconds'] for s in native[0]['slides'])==600 and sum(s['seconds'] for s in native[1]['slides'])==300)
check('native_editable_charts',native[0]['native_chart_count']==3 and native[1]['native_chart_count']==3)
for name,count in [('SUNDAY_10_MINUTES',10),('SUNDAY_5_MINUTES',10),('FRIDAY_INVITATION',1)]:
    receipt=read(ROOT/'work/product_pitch'/f'{name}.validation.json');check(name+'_validated',sha(OUT/f'{name}.pptx')==receipt['finalSha256'])
    with ZipFile(OUT/f'{name}.pptx') as z:
        notes=[z.read(n).decode() for n in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
        check(name+'_notes_and_build',len(notes)==count and all(build in s and 'SOURCES AND LIMITS' in s for s in notes))
for duration in [75,30]:
    movie=OUT/f'DEMO_{duration}_SECONDS.mp4';meta=read(Path(str(movie)+'.json'))
    check(f'movie_{duration}_freeze_and_hash',meta['build_id']==build and sha(movie)==meta['sha256'] and meta['presentation_frozen_utc']==pitch['frozen_utc'] and meta['started_utc']>pitch['frozen_utc'])
    check(f'movie_{duration}_same_final_inputs',meta['initial']['inputs']==reference['inputs']==meta['final']['inputs'] and meta['final']['presentation_scenario_id']==reference['id'])
    check(f'movie_{duration}_real_report_download',any(x.get('completed')=='report' and x['actual_seconds']<duration for x in meta['actions']) and (QA/f'VIDEO_DOWNLOADED_{duration}.html').exists())
check('chronological_phase_order',app['frozen_utc']<pitch['frozen_utc'])
check('no_fabricated_damage_or_health',reference['avoided_damage_eur'] is None and reference['ecosystem_service_value_eur'] is None and d['workspace']['composite_health'] is None and d['workspace']['composite_decline_risk'] is None)
withheld=[dict(result='Current local kelp species, canopy density and extent',status='BLOCKED',reason='Contemporary georeferenced field observations absent'),dict(result='Measured kelp decline and numerical habitat health',status='BLOCKED',reason='Comparable repeat extent/biomass and calibrated ecological thresholds absent'),dict(result='Verified shoreline protection and protected assets',status='BLOCKED',reason='Nearshore transformation, surge and receptor hazard unvalidated'),dict(result='Actual avoided damage and ecosystem-service euros',status='BLOCKED',reason='Receptor hazard/probability/exposure/loss data and substitution validity absent'),dict(result='Restoration intervention recommendation',status='BLOCKED',reason='Current condition, recruitment and feasibility evidence absent'),dict(result='Historical external suitability validation',status='FAIL',reason='63.45% false-positive rate exceeds declared 30% maximum; retained without changing criterion'),dict(result='OPW flood geometry distribution',status='BLOCKED',reason='Source-specific reuse permission unresolved; geometry and derived flags withheld'),dict(result='Weekend team contribution claims',status='BLOCKED',reason='Event has not occurred; named contributions remain blank')]
git=lambda *args:subprocess.check_output(['git','-c',f'safe.directory={ROOT.as_posix()}',*args],cwd=ROOT,text=True).strip()
evidence={ 'build_id':build,'canonical_evidence':'../map/evidence.json','source_manifest':'../map/build_manifest.json','scenario':reference,'units':dict(height_fraction='fraction of incoming height',energy_fraction='fraction of incoming energy',comparison_length_m='metres, geometric candidate shoreline',capital_eur='nominal conditional capital euros',annualised_eur_per_year='annual capital equivalent, not savings'),'biodiversity':{k:d['workspace']['biodiversity'][k] for k in ['records','site_count','dates','repeat_survey_sites','duplicate_ids_removed']},'source_ledger':d['sources'],'scientifically_unavailable':withheld}
(OUT/'RESULTS_MANIFEST.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
files=[p for p in OUT.iterdir() if p.is_file() and p.name!='FINAL_ACCEPTANCE.json']
status='PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL'
body=dict(build_id=build,checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),engineering_acceptance=status,scientific_validation='CONDITIONAL_MODEL_WITH_EXPLICIT_UNAVAILABLE_RESULTS',commit=git('rev-parse','HEAD'),branch=git('branch','--show-current'),git_status=git('status','--short'),checks=checks,scientifically_unavailable=withheld,canonical_scenario=reference,source_files_sha256=m['source_sha256'],input_versions_sha256=m['input_sha256'],production_source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'src').glob('*product*') if p.is_file()},test_records={k:'qa/'+k+'.json' for k in results},screenshots={'before':'qa/before.png','desktop':['qa/desktop-stage-'+str(i)+'.png' for i in range(6)],'mobile':['qa/mobile-stage-'+str(i)+'.png' for i in range(6)],'projector':['qa/projector-stage-'+str(i)+'.png' for i in range(6)],'report':['qa/report-final-'+str(i).zfill(2)+'.png' for i in range(1,18)],'slides':['presentation_assets/main/slide-'+str(i)+'.png' for i in range(1,11)]},media=results['media-tests'],rehearsal=results['rehearsal-tests'],powerpoint_movie_probe=read(QA/'powerpoint-movie-probe.json') if (QA/'powerpoint-movie-probe.json').exists() else {'status':'NOT_TESTED_CURRENT_MOVIE','fallback':'Native timed real-app stills; continuous movie in offline HTML'},deliverable_sha256={p.name:sha(p) for p in files},preservation='Original raw research files remain in place. No raw datasets or virtual environment were duplicated. Versioned input hashes verified above.')
(OUT/'FINAL_ACCEPTANCE.json').write_text(json.dumps(body,indent=2),encoding='utf-8');print(json.dumps(dict(build_id=build,engineering_acceptance=status,failed=[c for c in checks if c['status']!='PASS']),indent=2));raise SystemExit(0 if status=='PASS' else 1)
