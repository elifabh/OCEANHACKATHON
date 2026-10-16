"""Read-only delivery checks. No app rebuilds or changes to prior evidence."""
from pathlib import Path
import json,hashlib,zipfile,re,subprocess
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs/final_creative_20261015'; QA=OUT/'qa'; rows=[]
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def check(name,condition,detail=None):
    rows.append({'name':name,'pass':bool(condition),'detail':detail})
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
baseline=load(ROOT/'work/creative_20261015/preservation-before.json');changed=[]
for item in baseline['files']:
    p=ROOT/item['path']
    if not p.exists() or sha(p)!=item['sha256']:changed.append(item['path'])
check('Original product/research delivery preserved',not changed,{'files':len(baseline['files']),'changed':changed})
contract=load(OUT/'presentation_contract.json');old=load(ROOT/'outputs/final_overnight_20261015/presentation_contract.json')
check('Application build unchanged',contract['build_id']==old['build_id']=='6a84de90fe69')
check('Canonical engine results unchanged',contract['canonical_result']==old['canonical_result'])
check('All twelve approved messages retained',contract['titles']==old['titles'] and len(contract['titles'])==12)
deck=OUT/'INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx';ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
with zipfile.ZipFile(deck) as z:
    check('PowerPoint package integrity',z.testzip() is None)
    slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)]
    check('Twelve editable PowerPoint slides',len(slides)==12)
    for n in range(1,13):
        x=ET.fromstring(z.read(f'ppt/slides/slide{n}.xml'));transition=x.find('p:transition',ns)
        check(f'Slide {n}: manual advancement',transition is None or 'advTm' not in transition.attrib)
    notes=[n for n in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n)]
    check('No embedded narration notes',all(not ''.join(ET.fromstring(z.read(n)).itertext()).strip() for n in notes))
    check('Editable native financial chart',any(re.fullmatch(r'ppt/charts/chart\d+\.xml',n) for n in z.namelist()))
    check('Five embedded animation assets',sum(n.endswith('.gif') for n in z.namelist())==5)
pacing=load(QA/'narration-pacing.json')
check('Ten-minute manual cue plan including demo',pacing['total_seconds']==600 and pacing['video_seconds']==75)
check('Comfortable overall speaking pace',95<=pacing['combined_words_per_minute']<=105,pacing['combined_words_per_minute'])
check('All slide narration pacing 95–105 wpm',all(95<=r['words_per_minute']<=105 for r in pacing['slides']))
native=load(QA/'native-authoring-r6.json')
check('No overflowing native text boxes',all(not r['overflow'] for r in native['rows']))
check('No primary Fade dependence',all(e['kind']!='fade' for r in native['rows'] for e in r['events']))
check('No forced slide timers',native['manual_slide_advancement'] and not native['automatic_slide_transitions'])
for duration in [75,30]:
    record=load(OUT/f'DEMO_{duration}_SECONDS.mp4.json');actions={r['name']:r for r in record['actions']}
    check(f'{duration}s: real offline app with no errors',not record['errors'] and not record['network'])
    check(f'{duration}s: visible native focus',all(r['visible'] and not r['outline'].startswith('none') for r in record['focusChecks']))
    check(f'{duration}s: wave scenario is independent from euros',actions['depth']['state']['assessment']['bands']==actions['with']['state']['assessment']['bands'])
    check(f'{duration}s: frontage changes the comparator only',abs(actions['cost']['state']['assessment']['bands']['project_pooled']['capital_eur']/contract['canonical_result']['bands']['project_pooled']['capital_eur']-1.5)<1e-9 and actions['cost']['state']['assessment']['height_fraction']==contract['canonical_result']['height_fraction'])
    check(f'{duration}s: default inputs and results restored',record['final']['inputs']==contract['inputs'] and record['final']['assessment']['height_fraction']==contract['canonical_result']['height_fraction'])
    check(f'{duration}s: report downloaded before film ends',record['actions'][-1]['seconds']<duration-.3)
    check(f'{duration}s: capture in real time',abs(record['actual_capture_seconds']-duration)<3,record['actual_capture_seconds'])
    check(f'{duration}s: no audio/subtitles/added graphics',record['audio'] is False and record['subtitles'] is False and record['graphic_overlays'] is False)
    check(f'{duration}s: file hash matches recorded artifact',sha(OUT/record['file'])==record['sha256'])
    freeze=load(QA/f'video-freeze-{duration}.json')
    check(f'{duration}s: final slides/scripts frozen before capture',all(sha(OUT/n)==h for n,h in freeze['files'].items()))
    check(f'{duration}s: actual HTML/JSON report downloads',all((QA/f'DEMO_REPORT_{duration}.{ext}').stat().st_size>10000 for ext in ['html','json']))
    report=load(QA/f'DEMO_REPORT_{duration}.json')
    check(f'{duration}s: downloaded report matches demonstrated calculation',report['build_id']==contract['build_id'] and report['selected_state']['inputs']==contract['inputs'] and report['selected_state']['assessment']==record['final']['assessment'])
playback=load(QA/'media-playback.json')
check('Both films played to the end in Chrome',all(r['ended'] and abs(r['current_time']-r['expected_duration'])<.1 for r in playback['films']))
check('Both films are silent 1080p',all(r['width']==1920 and r['height']==1080 and r['audio_tracks']==0 for r in playback['films']))
decode=load(QA/'media-decode.json')
check('Both complete H.264 streams decode without errors',decode['status']=='PASS' and all(r['frames_decoded']==r['seconds']*30 for r in decode['films']))
launcher=load(QA/'launcher-test.json')
check('Actual double-click launcher opens revised deck',launcher['status']=='PASS' and launcher['opened_file'].endswith(deck.name) and launcher['advance_mode']=='manual')
rehearsal=load(QA/'native-10-minute-rehearsal.json')
check('Actual PowerPoint show manual for all 12 scenes',rehearsal['status']=='PASS' and len(rehearsal['slides'])==12 and all(r['manual_hold'] for r in rehearsal['slides']))
visual=load(QA/'visual-review.json')
check('Actual animated native output visually inspected',visual['status']=='PASS' and len(visual['slides'])==12 and visual['source']==deck.name)
check('Actual film frames inspected',visual['films']==[75,30])
check('Seven published promises documented',len(re.findall(r'^\| (?!Published|---)',(OUT/'PROMISE_MATRIX_FINAL.md').read_text(),re.M))==7)
check('Six jury criteria documented',len(re.findall(r'^\| (?!Criterion|---)',(OUT/'JURY_MATRIX_FINAL.md').read_text(),re.M))==6)
result={'status':'PASS' if all(r['pass'] for r in rows) else 'FAIL','build_id':contract['build_id'],'checks':len(rows),'passed':sum(r['pass'] for r in rows),'failed':sum(not r['pass'] for r in rows),'preserved_files':len(baseline['files']),'tests':rows,'not_claimed':['Human speaking rehearsal','Physical projector venue test','New ecological validation','Measured coastal or economic benefits']}
(QA/'CREATIVE_ACCEPTANCE.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in result.items() if k!='tests'},indent=2))
for r in rows:
    if not r['pass']:print('FAIL:',r['name'],r['detail'])
raise SystemExit(0 if result['status']=='PASS' else 1)
