"""Collect executed checks and final artefact hashes; retain unresolved science explicitly."""
from pathlib import Path
import json,subprocess,hashlib,datetime
R=Path(__file__).resolve().parents[1];W=R/'work/visual_v2';O=R/'outputs/presentations_visual_v2_20261014'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
app=read(R/'outputs/final_20261014/test_report.json');browser=read(W/'browser-qa/results.json');files=read(W/'delivery-file-checks.json');native=read(W/'final-powerpoint-check.json');live=read(W/'live-slideshow.json');preserved=read(W/'original-input-preservation.json')
assert app['status']==browser['status']==files['status']==preserved['status']=='PASS'
assert all(x['native_open']=='PASS' for x in native)
assert live['samples'][-1]['slide']==6
media=[]
for length in [55,30]:
    p=O/f'DEMO_{length}_SECONDS.mp4';meta=read(p.with_suffix('.mp4.json'))
    assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256']
    proc=subprocess.run([str(R/'work/story_20261014/ffmpeg.exe'),'-v','error','-i',str(p),'-f','null','NUL'],capture_output=True,text=True)
    assert proc.returncode==0 and not proc.stderr
    media.append({'name':p.name,'status':'PASS','duration':length,'build_id':meta['build_id'],'decode':'entire stream decoded without errors','sha256':meta['sha256']})
movie=read(W/'movie-probe.json')
status={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'build_id':app['build_id'],'delivery_status':'WORKING_SCREENING_PROTOTYPE_WITH_EXPLICIT_SCIENTIFIC_LIMITS',
'launch_app':str(R/'START_DEMO.bat'),'launch_jury':str(R/'START_JURY_PRESENTATION.bat'),
'acceptance':[
{'requirement':'Select supported area, inspect distinct evidence, assess protection and independent euro assumptions, download/print report','status':'PASS','scope':'Whole seven-cell pilot or three supported Sherkin model groups, not arbitrary sites'},
{'requirement':'Reproducible parametric physical model and geographic engineering funding comparison','status':'PASS','scope':'Published laboratory coefficients, actual polygon paths, candidate shoreline geometry, conditional costs and sensitivity; not validated ecosystem-service value'},
{'requirement':'Cork demonstration-site screening','status':'PASS','scope':'103 available building clusters and focused Cape Clear/Firkeel/inner Roaringwater checks, not an exhaustive county census'},
{'requirement':'Measured present kelp extent, decline rate and calibrated decline risk','status':'BLOCKED_BY_DATA','reason':'Historical mapping and sparse regional environmental context cannot establish current local species/density or a repeated decline observation'},
{'requirement':'Site-specific actual avoided damage / verified replacement ecosystem-service value','status':'BLOCKED_BY_DATA','reason':'No validated receptor hazard change, probability/loss functions, service equivalence, least-cost alternative and demonstrated demand; null is not zero'},
{'requirement':'Validated restoration recommendations','status':'FAIL_SCIENTIFIC_VALIDATION','reason':'Legacy external false-positive rate 63.45% exceeds 30%. Historical overlap does not repair this; output is survey priorities'},
{'requirement':'Editable 6-scene 3/5-minute decks, Friday introduction, notes, Q&A, credits, rehearsal, crosswalk','status':'PASS'},
{'requirement':'Real application films including calculations and report download','status':'PASS'},
{'requirement':'Continuous embedded PowerPoint movie in this installation','status':'FAIL_ENVIRONMENT','reason':'Saved/reopened correct embedded movie did not advance after Play; positions stayed zero. No codec/registry changes attempted.'},
{'requirement':'Reliable offline primary presentation and no-switch native picture fallback','status':'PASS','scope':'HTML complete real-speed 180.213/300.212s; native PowerPoint animations rendered and live scene 5 advanced to scene 6'},
{'requirement':'Actual weekend teamwork / official speaking-slot and IP approval','status':'PENDING_EVENT_OR_ORGANISER','reason':'Future contributions left editable; organiser draft not sent'}],
'application_checks':app,'offline_presentation_checks':browser,'final_file_checks':files,'powerpoint_native':native,'live_powerpoint_slideshow':live,'media_checks':media,'original_input_preservation':preserved,
'native_movie_probe':movie,'visual_review':{'status':'COMPLETED','scope':'All 13 native slides inspected; final renders pixel-identical; before/after six-scene montage; four UI screenshots; three report PDF pages; one-page Turkish PDF; native animation frames checked'},
'limits':['No full hydrodynamic or flood-damage model','Sensitivity ranges are scenario ranges, not statistical confidence intervals','Regional 14/17 taxa is effort-biased presence context','Nominal 50m model cells are not measured bed boundaries','PowerPoint timing includes transition overhead; exact 3/5-minute rehearsal path is HTML','Human spoken pace and projector conditions still require presenter rehearsal'],
'final_decks':['SUNDAY_3_MINUTES_FINAL_VERIFIED.pptx','SUNDAY_5_MINUTES_FINAL_VERIFIED.pptx','FRIDAY_INVITATION.pptx']}
(O/'DELIVERY_STATUS.json').write_text(json.dumps(status,indent=2,ensure_ascii=False),encoding='utf8')
(O/'REVISION_CHANGELOG.md').write_text('''# Final revision, 14 October 2026

The application now completes selection, distinct evidence inspection, geographic protection modelling, independent engineering cost scenarios and a downloadable three-page assessment. Published coefficient/domain checks and Cork comparisons remain visible. Actual avoided damage, verified service value and measured decline remain unquantified.

The jury revision uses authentic Irish coastal photographs, large maps, an editable physical comparison, readable real app films and an actual selected report. PowerPoint's SVG rendering incompatibility was repaired with a faithful raster of the report map. Map proportions and native animation timing were checked in rendered output. All 13 final native slide images match the reviewed versions.

The offline HTML presentation passed complete real-speed 3- and 5-minute runs. The installed PowerPoint movie player still fails; the labelled native picture sequence and live transition into the closing scene work. Exact speaker notes, 15 jury answers, one-minute spoken backup, 90-second equipment rehearsal, source credits and editable weekend contributions accompany the delivery.

CHECK_DEMO passed again after resuming: 34 numerical tests, source/input/output consistency, localhost launch, 13 browser smoke checks, 11 story checks and 6 assessment workflow checks including actual download, PDF, offline and mobile. Original raw inputs present in the pre-revision build manifest retained their hashes. The full original datasets and previous research outputs remain in place; no full project copy was made.

Current launchers: START_DEMO.bat and START_JURY_PRESENTATION.bat. See KULLANIM_TR.html or its one-page PDF. DELIVERY_STATUS.json records passes and unresolved failures separately. Earlier unsuffixed Sunday PPTXs in this revision folder are superseded by the FINAL_VERIFIED files linked from the menu.
''',encoding='utf8')
manifest={str(p.relative_to(O)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in O.rglob('*') if p.is_file() and p.name!='DELIVERY_HASHES.json'}
(O/'DELIVERY_HASHES.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
print('Delivery status and hashes saved; scientific data blockers and native movie failure remain explicit.')
