"""Fail closed when app, scenario, movies, decks, reports or launchers disagree."""
from pathlib import Path
from zipfile import ZipFile
import json,re,hashlib,subprocess,math,datetime,xml.etree.ElementTree as ET
R=Path(__file__).resolve().parents[1];O=R/'outputs/jury_release_20261014';W=R/'work/jury_release_20261014'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
d=read(R/'outputs/map/evidence.json');b=d['build_id'];config=read(R/'src/presentation_scenario.json');e=read(O/'PRESENTATION_SCENARIO.json');r=e['result'];checks=[]
def close(a,b):assert math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-8),(a,b)
assert e['build_id']==b and e['id']==config['id']
assert e['inputs']==config['inputs']==r['inputs'];assert d['presentation_scenario']==config
scope=d['parametric']['scopes'][str(config['group'])];direction=scope['directions'][str(config['direction_offset_deg'])]
assert scope['cells']==7 and scope['area_m2']==17500 and e['group']==0
close(r['comparison_length_m'],direction['shoreline']['length_m'])
for band in ['low','high']:
 close(r['bands'][band]['capital_eur'],direction['shoreline']['length_m']*d['costs']['rates'][band])
 close(r['bands'][band]['annualised_eur_per_year'],r['bands'][band]['capital_eur']*.04/(1-1.04**-50))
assert r['avoided_damage_eur_per_year'] is None and r['ecosystem_service_value_eur'] is None
assert set(r['replacement_validity'].values())=={False}
checks.append({'name':'Single explicit default scenario; geographic length, independent capital and annuity identities','status':'PASS'})
manifest=read(R/'outputs/map/build_manifest.json');prior=read(W/'pre-correction-build.json')
assert manifest['build_id']==b
for category,base in [('source_sha256',R),('input_sha256',R),('output_sha256',R/'outputs/map')]:
 for file,h in manifest[category].items():assert sha(base/file)==h,(category,file)
for file,h in prior['input_sha256'].items():assert sha(R/file)==h,('Research input changed',file)
checks.append({'name':'App source/output hashes and all pre-correction research inputs preserved','status':'PASS','input_count':len(prior['input_sha256'])})
html=(O/'ASSESSMENT_PILOT.html').read_text(encoding='utf8')
report=json.loads(re.search(r'<script type="application/json" id="assessment-data">(.*?)</script>',html,re.S)[1])
assert report['build_id']==b and report['group']==0 and report['presentation_scenario_id']==e['id'] and report['inputs']==config['inputs']
for key in ['height_fraction','energy_fraction','comparison_length_m']:close(report[key],r[key])
for band,values in r['bands'].items():
 for key,value in values.items():close(report['bands'][band][key],value)
assert report['avoided_damage_eur_per_year'] is None and report['assets_are_protected'] is False
poppler=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'
pdfinfo=subprocess.check_output([str(poppler/'pdfinfo.exe'),str(O/'ASSESSMENT_PILOT.pdf')],text=True,encoding='utf8')
assert re.search(r'Pages:\s+3\b',pdfinfo)
runtime_python=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
pdftext=subprocess.check_output([str(runtime_python),'-X','utf8','-c','from pypdf import PdfReader; import sys; print("\\n".join(p.extract_text() for p in PdfReader(sys.argv[1]).pages))',str(O/'ASSESSMENT_PILOT.pdf')],text=True,encoding='utf8')
assert b in pdftext and e['id'] in pdftext and 'Not quantified' in pdftext
for band in ['low','high']:assert f"{round(r['bands'][band]['capital_eur']):,}" in pdftext
checks.append({'name':'Actual downloaded HTML and three-page printed PDF match current app and baseline','status':'PASS'})
old_claims=['c0960eb09d38','d493f82c1a12','114,795','190,203','115,000','190,000','1,034,122','1,713,425']
deckrows=[]
for name,count in [('SUNDAY_3_MINUTES_FINAL.pptx',6),('SUNDAY_5_MINUTES_FINAL.pptx',6),('FRIDAY_INVITATION.pptx',1)]:
 with ZipFile(O/name) as z:
  notes=[f for f in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',f)]
  assert len(notes)==count
  texts=[' '.join(ET.fromstring(z.read(f)).itertext()) for f in notes]
  assert all(b in t and e['id'] in t for t in texts)
  text=' '.join(texts)
  assert not any(old in text for old in old_claims)
  if count==6:
   assert all(f"{round(r['bands'][band]['capital_eur']):,}" in text for band in ['low','high'])
   chartfiles=[f for f in z.namelist() if re.fullmatch(r'ppt/charts/chart\d+\.xml',f)]
   assert len(chartfiles)==1
   chart=ET.fromstring(z.read(chartfiles[0]));vals=[float(n.text) for n in chart.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/chart}numCache/{http://schemas.openxmlformats.org/drawingml/2006/chart}pt/{http://schemas.openxmlformats.org/drawingml/2006/chart}v')]
   assert 100 in vals and round(100*(1-r['height_fraction']),6) in vals
 deckrows.append({'file':name,'notes':count,'build_id':b,'sha256':sha(O/name)})
checks.append({'name':'All 13 slide notes, economic claims and native charts use current scenario','status':'PASS','decks':deckrows})
for name in ['SUNDAY_3_MINUTES.md','SUNDAY_5_MINUTES.md','FRIDAY_2_MINUTES.md','JURY_Q_AND_A.md','NO_VIDEO_BACKUP.md']:
 text=(O/name).read_text(encoding='utf8');assert b in text and e['id'] in text
 assert not any(old in text for old in old_claims)
 assert 'Print / Save as PDF' in text and 'HTML' in text
checks.append({'name':'English scripts, jury answers and backup disclose the same baseline and HTML/PDF route','status':'PASS'})
media=[]
for seconds in [55,30]:
 f=O/f'DEMO_{seconds}_SECONDS.mp4';m=read(f.with_suffix('.mp4.json'))
 assert m['build_id']==b and m['scenario_id']==e['id'] and m['sha256']==sha(f) and m['baseline']==r
 assert m['uncaught_errors']==[] and m['duration_seconds']==seconds
 assert m['subtitles'] is False and m['overlays'] is False
 cues=(O/m['speaker_cues_file']).read_text(encoding='utf8');assert b in cues and e['id'] in cues
 assert '1.98–3.28 million conditional capital' in cues and 'Not verified avoided damage' in cues and 'HTML' in cues
 assert not any(old in cues for old in old_claims)
 states=[x for x in m['actions'] if 'completed' in x or 'variation' in x]
 for action in states:
  s=action['assessment'];assert s['build_id']==b and s['group']==0
  close(s['length_m'],r['comparison_length_m'])
  if action.get('variation')=='cost share 50%':close(s['low_capital'],r['bands']['low']['capital_eur']/2);assert s['scenario_id'] is None
  elif action.get('variation')=='water level +1 m':
   assert s['inputs']['water_level_m']==1 and s['scenario_id'] is None
   outside=any(seg['depth_m_LAT']+1>10 for ray in direction['rays'] for seg in ray['segments'])
   if outside:assert s['height'] is None and s['energy'] is None
   else:assert s['height']<r['height_fraction']
  else:
   assert s['inputs']==config['inputs'] and s['scenario_id']==e['id']
   close(s['low_capital'],r['bands']['low']['capital_eur']);close(s['height'],r['height_fraction'])
 assert {x.get('variation') for x in states}>={'cost share 50%','water level +1 m'}
 assert states[-1]['completed']=='report'
 p=subprocess.run([str(R/'work/story_20261014/ffmpeg.exe'),'-v','error','-i',str(f),'-f','null','NUL'],capture_output=True,text=True)
 assert p.returncode==0 and not p.stderr,p.stderr
 media.append({'file':f.name,'build_id':b,'seconds':seconds,'sha256':sha(f),'decode':'Entire H.264 stream decoded without errors','baseline_restored_before_report':True})
assert not list(O.glob('*.srt')) and not list(O.glob('*.ass'))
checks.append({'name':'Both clean movies, separate speaker cues, modified assumptions and restored report match','status':'PASS','media':media})
launcher=(R/'START_JURY_PRESENTATION.bat').read_text();assert 'outputs\\jury_release_20261014\\START_PRESENTATION.bat' in launcher
assert 'OFFLINE_PRESENTATION.html' in (O/'START_PRESENTATION.bat').read_text()
offline=(O/'OFFLINE_PRESENTATION.html').read_text(encoding='utf8');assert b in offline and e['id'] in offline and 'FINAL_VERIFIED' not in offline
root_guide=(R/'BASLA_BURADAN_TR.md').read_text(encoding='utf8')
assert b in root_guide and e['id'] in root_guide and 'jury_release_20261014' in root_guide
assert 'altyazısız' in root_guide and 'Download HTML report' in root_guide
assert all(f"{round(r['bands'][band]['capital_eur']):,}".replace(',','.') in root_guide for band in ['low','high'])
assert '114.795' not in root_guide and 'presentations_final_20261014' not in root_guide
checks.append({'name':'Root launcher, current menu, final decks and scenario share one release folder','status':'PASS'})
result={'status':'PASS','checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'build_id':b,'scenario_id':e['id'],'checks':checks}
(O/'CONSISTENCY_CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'status':'PASS','build_id':b,'checks':len(checks),'capital_eur':[r['bands'][x]['capital_eur'] for x in ['low','high']]}))
