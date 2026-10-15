"""Decode every frame of the delivered demos with the existing FFmpeg binary."""
from pathlib import Path
import subprocess,json,re
root=Path(__file__).resolve().parents[1]
out=root/'outputs/final_creative_20261015'
rows=[]
for duration in [75,30]:
    p=subprocess.run([str(root/'work/story_20261014/ffmpeg.exe'),'-hide_banner','-i',str(out/f'DEMO_{duration}_SECONDS.mp4'),'-f','null','-'],capture_output=True,text=True)
    (out/f'qa/decode-{duration}.log').write_text(p.stderr,encoding='utf8')
    source=p.stderr.split('Stream mapping:')[0]
    frames=re.findall(r'frame=\s*(\d+)',p.stderr)
    rows.append({'seconds':duration,'exit_code':p.returncode,'frames_decoded':int(frames[-1]) if frames else None,'audio_streams':len(re.findall(r'Stream.*Audio:',source)),'subtitle_streams':len(re.findall(r'Stream.*Subtitle:',source)),'resolution_1920_1080':'1920x1080' in source,'fps_30':'30 fps' in source})
passed=all(r['exit_code']==0 and r['frames_decoded']==r['seconds']*30 and r['audio_streams']==r['subtitle_streams']==0 and r['resolution_1920_1080'] and r['fps_30'] for r in rows)
result={'status':'PASS' if passed else 'FAIL','films':rows}
(out/'qa/media-decode.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
raise SystemExit(0 if passed else 1)
