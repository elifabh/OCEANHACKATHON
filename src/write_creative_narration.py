"""Separate English narration, word counts and manual cue sheet; no embedded notes."""
from pathlib import Path
import json,re,shutil
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/final_creative_20261015'
data=json.loads((ROOT/'src/creative_narration.json').read_text(encoding='utf8'))
contract=json.loads((OUT/'presentation_contract.json').read_text(encoding='utf8'))
def words(s):return re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*",s)
def clock(s):return f'{s//60:02d}:{s%60:02d}'
rows=[];total=0;spoken=0
parts=['# The Invisible Shield: English jury narration','',f"Application build: `{data['build_id']}`. Creative presentation revision, manual slide advancement.",'','Target: 10:00 including the 75-second silent application video. Use a stopwatch. The times below are presenter cues, never automatic slide transitions. Speak calmly at approximately 95–105 words per minute; pause briefly as each mechanism becomes visible. Bracketed instructions are not spoken.','', 'The native builds run inside each slide; wait for the scene to settle, then advance with Right Arrow or Space. Do not click through builds rapidly. No narration is embedded in PowerPoint.','']
for item in data['slides']:
 n=item['slide'];end=total+item['seconds'];count=len(words(item['spoken']));rate=count/item['seconds']*60
 rows.append({'slide':n,'start':total,'end':end,'seconds':item['seconds'],'words':count,'words_per_minute':round(rate,2)})
 parts.extend([f"## {clock(total)}–{clock(end)} · Slide {n}: {contract['titles'][n-1]}",'',item['spoken'],'',f"[{item['cue']}]",''])
 total=end;spoken+=count
 if n==10:parts.extend(['## 07:30–08:45 · Application demo','', 'Play `DEMO_75_SECONDS.mp4`. Read the separate `VIDEO_LIVE_NARRATION.md` while the silent video runs. Return to PowerPoint, then advance once to slide 11.','']);total+=75
assert total==600
(OUT/'SUNDAY_10_MIN_SCRIPT.md').write_text('\n'.join(parts),encoding='utf8')
video=['# Live narration for the silent 75-second application demo','',f"Build `{data['build_id']}`. Start at presentation time 07:30. This is spoken live; the MP4 has no sound, subtitles or added captions. The sentences describe operation rather than repeating the earlier scientific explanation.",'']
for item in data['video']:video.extend([f"## {clock(item['start'])}–{clock(item['end'])}",'',item['spoken'],''])
(OUT/'VIDEO_LIVE_NARRATION.md').write_text('\n'.join(video),encoding='utf8')
vcount=sum(len(words(x['spoken'])) for x in data['video'])
report={'status':'PASS_WORD_COUNT_AND_MANUAL_CUE_REVIEW','build_id':data['build_id'],'total_seconds':600,'slide_seconds':525,'video_seconds':75,'slide_spoken_words':spoken,'video_spoken_words':vcount,'combined_spoken_words':spoken+vcount,'combined_words_per_minute':round((spoken+vcount)/10,2),'slide_words_per_minute':round(spoken/525*60,2),'video_words_per_minute':round(vcount/75*60,2),'slides':rows,'human_spoken_rehearsal_performed':False,'notes':'Word count is an estimate of speaking pace, not a human rehearsal or language proficiency certification.'}
(OUT/'qa/narration-pacing.json').write_text(json.dumps(report,indent=2),encoding='utf8')
shutil.copy2(ROOT/'outputs/final_overnight_20261015/Q_AND_A_20.md',OUT/'Q_AND_A_20.md')
print(json.dumps(report,indent=2))
