"""Publish the local current-release pointer only after executed checks pass."""
from pathlib import Path
import json,hashlib,datetime,shutil
R=Path(__file__).resolve().parents[1];O=R/'outputs/jury_release_20261014';W=R/'work/jury_release_20261014'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
app=read(R/'outputs/final_20261014/test_report.json');consistency=read(O/'CONSISTENCY_CHECK.json');browser=read(W/'browser-qa/results.json');files=read(W/'delivery-file-checks.json');native=read(W/'final-powerpoint-check.json');live=read(W/'live-slideshow.json');animation=read(W/'native-animation-rehearsal.json');probe=read(W/'movie-probe.json')
b=app['build_id'];assert app['status']==consistency['status']==browser['status']==files['status']==animation['status']=='PASS'
assert consistency['build_id']==b and all(x['native_open']=='PASS' for x in native) and live['samples'][-1]['slide']==6
assert len(native)==3 and sum(x['slides'] for x in native)==13
e=read(O/'PRESENTATION_SCENARIO.json');assert e['build_id']==b
status={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'build_id':b,'scenario_id':e['id'],'delivery_status':'CORRECTED_AND_VERIFIED_WITH_DECLARED_SCIENTIFIC_LIMITS',
 'application':app,'consistency':consistency,'offline_real_time_rehearsals':browser,'final_files':files,'native_powerpoint':native,'live_slideshow':live,'native_animation_render':animation,
 'video_style':'Actual application recordings without subtitles, added overlays or audio; separate English narration for the presenter',
 'report_workflow':'Self-contained HTML download; offline Print / Save as PDF. Included PDF was printed from that actual download. No direct one-click PDF export is claimed.',
 'presentation_route':'START_JURY_PRESENTATION.bat opens the current offline HTML presentation with continuous real movies. PPTX uses labelled timed still frames.',
 'native_embedded_movie_probe':probe,
 'launcher_check':read(W/'launcher-check.json'),
 'visual_review':{'status':'COMPLETED','scope':'All 13 native slides, native animation frames, actual clean movie frames, current economic UI, three-page assessment and one-page Turkish handover. Final native slide pixels match reviewed render.'},
 'scientific_limits':['No measured present local kelp density or comparable observed decline','No calibrated receptor hazard/loss model; actual avoided damage is unknown, not zero','Replacement-cost equivalence, least-cost and demonstrated demand gates all unproven','Conditional within-habitat wave effect does not establish protected coastline or beneficiaries','Scenario ranges are not statistical confidence intervals','Regional 14/17 taxa is not local bed biodiversity','Legacy external false-positive rate 63.45% still fails the 30% criterion; restoration output is survey priorities'],
 'remaining_presentation_limits':['Installed PowerPoint embedded movie player did not advance; use verified offline HTML for continuous video','Speaking slot and presenter speaking pace still need organiser/presenter confirmation','Actual weekend team contributions must be recorded after they occur']}
for source,name in [(W/'compact-overview.png','PREVIEW_SLIDES.png'),(W/'ui-cost-full.png','PREVIEW_APP_ECONOMICS.png'),(W/'ui-wave-full.png','PREVIEW_APP_WAVES.png')]:shutil.copy2(source,O/name)
(O/'DELIVERY_STATUS.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
note=f'''SUPERSEDED PRESENTATION PACKAGE — preserved for history.

Use C:\\Users\\Elif\\Desktop\\OCEANHACKATHON\\START_JURY_PRESENTATION.bat
Current folder: {O}
Application build: {b}; scenario: {e['id']}.
Do not mix this older folder's slides, videos or euro figures with the current application.
'''
for old in ['presentations_final_20261014','presentations_visual_v2_20261014']:
 (R/'outputs'/old/'SUPERSEDED_READ_FIRST.txt').write_text(note,encoding='utf8')
(O/'REVISION_CHANGELOG.md').write_text(f'''# Consistency correction / 14 October 2026

Current build: {b}; presentation scenario: {e['id']}.

Preserved the approved visual design and science. Added a single versioned seven-cell, 1.75 ha presentation baseline, matching the app default. All updated decks, clean 30/55-second real recordings, English narration and the actual downloaded/printed report use that baseline. The films briefly change assumptions and restore the baseline before export. They have no subtitles or added overlays, as requested.

The report button now says Download HTML report. Print / Save as PDF is the accurate offline PDF route. The root jury launcher opens this current package; old packages are retained and marked superseded.

The independent consistency audit checks build/source/input/output hashes, report values, scientific nulls, all 13 slide notes, native chart values, speaker notes, actual recording actions and complete video decoding. Numerical and end-to-end application tests passed, as did real-speed 3/5-minute offline runs and native PowerPoint rendering/live transitions. DELIVERY_STATUS.json records the exact results and the remaining embedded-video and scientific limitations. Original research input hashes are unchanged.
''',encoding='utf8')
hashes={p.relative_to(O).as_posix():sha(p) for p in sorted(O.rglob('*')) if p.is_file() and p.name!='DELIVERY_HASHES.json'}
(O/'DELIVERY_HASHES.json').write_text(json.dumps(hashes,indent=2),encoding='utf8')
pointer={'build_id':b,'scenario_id':e['id'],'path':str(O),'launcher':str(R/'START_JURY_PRESENTATION.bat'),'status':'VERIFIED','manifest_sha256':sha(O/'DELIVERY_HASHES.json')}
(R/'outputs/JURY_CURRENT.json').write_text(json.dumps(pointer,indent=2),encoding='utf8')
print(json.dumps({'status':'PASS','build_id':b,'files':len(hashes),'current':str(O)}))
