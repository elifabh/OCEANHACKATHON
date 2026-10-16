"""Extract unaltered recording frames and package an offline rehearsal fallback."""
from pathlib import Path
import json, subprocess, hashlib
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/presentations_final_20261014'
FF=ROOT/'work/story_20261014/ffmpeg.exe';STILLS=OUT/'fallback_stills';STILLS.mkdir(exist_ok=True)
scenes=[(2,'Select a Cork model group'),(9,'Separate satellite and historical evidence'),(17,'Regional biodiversity and the measured-decline gap'),(24,'Conditional wave illustration'),(30,'Adjustable capital scenario; avoided damage unknown'),(43,'Low-confidence survey priorities'),(49,'Mizen transfer returns no estimate'),(53,'A traceable next field decision')]
for i,(seconds,title) in enumerate(scenes,1):
    subprocess.run([str(FF),'-hide_banner','-loglevel','error','-ss',str(seconds),'-i',str(OUT/'DEMO_55_SECONDS.mp4'),'-frames:v','1','-y',str(STILLS/f'{i:02d}.png')],check=True)
for duration,points in [(55,[2,9,17,24,30,35,43,49,53]),(30,[1,5,9,14,18,21,25,29])]:
    for i,seconds in enumerate(points,1):
        subprocess.run([str(FF),'-hide_banner','-loglevel','error','-ss',str(seconds),'-i',str(OUT/f'DEMO_{duration}_SECONDS.mp4'),'-frames:v','1','-y',str(STILLS/f'{duration}_{i:02d}.png')],check=True)
videos=[]
for seconds in [55,30]:
    file=OUT/f'DEMO_{seconds}_SECONDS.mp4'
    result=subprocess.run([str(FF),'-hide_banner','-loglevel','error','-i',str(file),'-f','null','-'],capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr)
    meta=json.loads(file.with_suffix('.mp4.json').read_text())
    assert hashlib.sha256(file.read_bytes()).hexdigest()==meta['sha256']
    videos.append({'file':file.name,'full_decode':'PASS','duration_seconds':seconds,'sha256':meta['sha256'],'audio':'Deliberately silent, captions embedded'})
labels=json.dumps([x[1] for x in scenes])
html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Invisible Shield · offline rehearsal</title>
<style>body{margin:0;background:#f5f4ee;color:#15333a;font:18px/1.5 'Segoe UI',sans-serif}main{max-width:1200px;margin:auto;padding:28px}h1{font:42px Georgia}video,img{width:100%;display:block;background:#15333a}button,a{font:inherit;color:#176655}button{padding:9px 18px;border:1px solid #8caaa0;background:#fff;cursor:pointer}nav{display:flex;gap:12px;flex-wrap:wrap}small{font-size:14px}details{margin:24px 0}summary{cursor:pointer;font-weight:bold}#count{padding:12px}h2{font:26px Georgia}a{margin-right:18px}</style>
<main><h1>A living coast. A clearer next decision.</h1><p>Genuine local application recordings. Silent with English captions. All media and stills work without an internet connection.</p>
<nav><button data-film="55">55-second full demo</button><button data-film="30">30-second compact demo</button></nav><p id="film-label">55-second full demo</p><video id="film" controls preload="metadata" poster="demo_full_poster.png" src="DEMO_55_SECONDS.mp4"></video>
<details id="fallback"><summary>Video unavailable? Open the still sequence</summary><p>These are unaltered frames from the actual 55-second recording, including the on-screen qualifiers.</p><nav><button id="previous">Previous</button><button id="next">Next</button><span id="count"></span></nav><h2 id="scene"></h2><img id="still" src="fallback_stills/01.png" alt="Actual application recording frame"></details>
<p><a href="SUNDAY_3_MINUTES_FINAL.pptx">3-minute PowerPoint</a><a href="SUNDAY_5_MINUTES_FINAL.pptx">5-minute PowerPoint</a><a href="FRIDAY_INVITATION.pptx">Friday visual</a><a href="JURY_CROSSWALK.html">Jury crosswalk</a></p>
<small>Prepared 14 October 2026. Model effects and cost scenarios remain conditional. Actual avoided damage is not quantified. Map and visual rights: see VISUAL_ASSETS_AND_SOURCES.md. Rehearsal budgets are not a confirmed Sunday slot.</small></main>
<script>const labels=LABELS;let i=0;const update=()=>{document.getElementById('still').src='fallback_stills/'+String(i+1).padStart(2,'0')+'.png';document.getElementById('scene').textContent=labels[i];document.getElementById('count').textContent=(i+1)+' / '+labels.length;};document.getElementById('next').onclick=()=>{i=(i+1)%labels.length;update();};document.getElementById('previous').onclick=()=>{i=(i+labels.length-1)%labels.length;update();};document.querySelectorAll('[data-film]').forEach(b=>b.onclick=()=>{const f=document.getElementById('film');f.pause();f.src='DEMO_'+b.dataset.film+'_SECONDS.mp4';f.poster=b.dataset.film==='55'?'demo_full_poster.png':'demo_short_poster.png';document.getElementById('film-label').textContent=b.dataset.film+'-second real application demo';f.load();});update();</script></html>'''.replace('LABELS',labels)
(OUT/'OFFLINE_DEMO.html').write_text(html,encoding='utf-8')
(ROOT/'outputs/final_20261014/qa/video_decode.json').write_text(json.dumps(videos,indent=2),encoding='utf-8')
print(json.dumps(videos,indent=2))
