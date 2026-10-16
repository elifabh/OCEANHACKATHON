"""Small human handoff documents. No research data duplication."""
from pathlib import Path
import json,html
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_delivery_20261014'
build=json.loads((ROOT/'outputs/map/build_manifest.json').read_text())['build_id']
css='body{max-width:950px;margin:35px auto;padding:0 28px;font:18px/1.6 Segoe UI,sans-serif;color:#153d42;background:#faf9f2}h1,h2{font-family:Georgia;font-weight:400;line-height:1.2}h1{font-size:40px}h2{margin-top:35px;font-size:30px}a{color:#226350}pre{white-space:pre-wrap;font:inherit}nav{padding:14px;background:#e4ebe3;position:sticky;top:0}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.3}td,th{border:1px solid #b8c9bd;padding:7px;vertical-align:top;text-align:left}th{background:#e4ebe3}@media print{body{margin:0;font-size:11pt}nav,button{display:none}h2{break-after:avoid}section{break-before:page}@page{size:A4;margin:17mm}}'
def document(title,body):return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+css+'</style><h1>'+title+'</h1>'+body+'</html>'
notes=[('main','Sunday · 10 minutes','SUNDAY_10_MINUTES_NOTES.md'),('short','Sunday · 5 minutes','SUNDAY_5_MINUTES_NOTES.md'),('friday','Friday · 2 minutes','FRIDAY_2_MINUTES.md'),('backup','90-second no-video route','NO_VIDEO_90_SECONDS.md'),('questions','20 jury questions','JURY_Q_AND_A.md')]
body='<p>Build '+build+'. Human English speaker notes. Bracketed text is a stage cue, not spoken narration.</p><nav>'+' / '.join('<a href="#'+key+'">'+label+'</a>' for key,label,_ in notes)+'</nav>'
for key,label,name in notes:
    raw=(OUT/name).read_text(encoding='utf-8');parts=[]
    for part in raw.split('\n\n'):
        if part.startswith('## '):parts.append('<h2>'+html.escape(part[3:])+'</h2>')
        elif part.startswith('# '):continue
        else:parts.append('<p>'+html.escape(part).replace('\n','<br>')+'</p>')
    body+='<section id="'+key+'"><h2>'+label+'</h2>'+''.join(parts)+'</section>'
(OUT/'SPEAKER_NOTES.html').write_text(document('Speaker notes and jury discussion',body),encoding='utf-8')
commitments=[
('Habitat geography','Interactive model / historical / satellite layers; real area selection.','qa/desktop-stage-0.png','workspace.geometry; report 2–3; slides 3–4','PASS for mapped evidence; current bed unverified'),
('Condition and potential decline / stress','Six separate evidence components; five risk factors; real year filter.','qa/desktop-stage-1.png','workspace.health / decline_risk; report 4–5; slide 5','Components implemented; measured decline unavailable'),
('Parametric coastal protection','Polygon-ray model with depth limits and asset/barrier geometry.','qa/desktop-stage-2.png','parametric.scopes; report 6; slide 6','Conditional within-habitat model; shore benefit unvalidated'),
('Conditional economics in euros','Live low / pooled / high funding scenario; independent cost share.','qa/desktop-stage-3.png','workspace.reference_scenario; report 7; slide 7','Conditional comparison implemented; avoided damage unavailable'),
('Biodiversity indicators','14/17 checklist, 35 sites, source-ID deduplication and dated effort.','qa/desktop-stage-4.png','workspace.biodiversity; report 8; slide 9','Regional historical indicator; local health unassessed'),
('Restoration / research priorities','126 candidate cells, reasons and changing sort, mapped selections.','presentation_assets/map-priorities.png','workspace.priorities; report 9–11; slide 9','Research priorities implemented; planting recommendation unsupported'),
('Transferable pipeline','Real Galway/Clare context changes; unsupported model inputs return null.','qa/context-galway.png','workspace.context_layers; report 10; slide 3','Workflow transferable; quantitative local recalibration required')]
criteria=[('Demonstrator / proof of concept','Actual six-stage app, changed-state export and offline PDF tests','Slides 4, 6–9; qa/test_report.json'),('Use of digital data','Source ledger, hashed Sentinel/NPWS/INFOMAR/CMEMS/OBIS inputs','Slides 4–5; report 12; APP_REPORT_FREEZE.json'),('Project ambition','Connected evidence, physics, conditional economics and field brief','Slides 4–10; actual report'),('Environmental and societal impact','Kelp ecology, candidate receptors and explicit field actions','Slides 2, 6, 9–10; benefits not monetised without evidence'),('Innovative nature','Auditable selected-state assessment across source types','Slides 4–9; reproducible scenario and source manifest'),('Team cohesion and communication','Clear pitch, accessible notes and blank actual-contribution log','Slide 10; TEAM_CONTRIBUTIONS_TEMPLATE.md; weekend work PENDING')]
rows=''.join('<tr><td>'+html.escape(a)+'</td><td>'+html.escape(b)+'<br><a href="'+shot+'">Actual proof image</a></td><td>'+html.escape(field)+'</td><td>'+html.escape(status)+'</td></tr>' for a,b,shot,field,status in commitments)
body='<p>Build '+build+'. Implementation proof is separate from scientific validation. A heading alone does not count as completion.</p><table><tr><th>Published commitment</th><th>Working proof</th><th>Machine field / report / pitch</th><th>Boundary</th></tr>'+rows+'</table><h2>Six jury criteria</h2><table><tr><th>Criterion</th><th>Evidence</th><th>Where to verify</th></tr>'+''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in row)+'</tr>' for row in criteria)+'</table>'
matrix_print='@media print{body{padding:0;font-size:10pt}h1{font-size:19pt;margin:0 0 10px}h2{font-size:14pt;margin:15px 0 8px}table{font-size:11.8px;line-height:1.15}td,th{padding:4px}@page{size:A4;margin:13mm}}'
(OUT/'COVERAGE_MATRIX.html').write_text(document('Published commitments and jury evidence',body).replace('font:18px/1.6','font:14px/1.35').replace('font-size:40px','font-size:28px').replace('font-size:30px','font-size:22px').replace('</style>',matrix_print+'</style>'),encoding='utf-8')
(OUT/'FACILITATOR_NOTES.md').write_text(f'''# Offline presentation operation

Build {build}. The user-reported slot is 15 minutes. Whether this includes questions is not independently confirmed. Use the 10-minute main talk, retaining about five minutes for questions, setup or contingency. Use the 5-minute cut if asked to shorten.

1. Double-click START_JURY_PRESENTATION.bat in the repository. Choose Sunday 10 minutes or 5 minutes. Open SPEAKER_NOTES.html separately if useful.
2. Choose Manual presentation for a live talk, or Timed rehearsal for the fixed 600/300-second route. Click Start. Full screen is optional. The left/right buttons or arrow keys change slides. Space pauses/resumes; F toggles full screen. Header controls reappear on pointer hover in full screen.
3. Slide 8 automatically plays the silent local MP4. Narrate from the separate cue notes. Normal application labels are part of the recording. No subtitles or voiceover were added.
4. If the movie fails, choose Use stills. Real application stills advance predictably. The native PowerPoint files use the same explicit still fallback, not a claimed embedded playing movie. Standalone MP4 files are also in this folder.
5. Friday has its own one-slide invitation and two-minute script. It does not describe future weekend work as completed.
6. Before Sunday, complete the actual team contribution log and update the spoken contribution cue with evidence. Keep pre-event preparation distinct.

For a complete playback test record see qa/rehearsal-tests.json after final acceptance. The presentation package is frozen before movie recording, and its SHA-256 values are in PRESENTATION_FREEZE.json.
''',encoding='utf-8')
print('Speaker notes, coverage matrix and facilitator guide:',build)
