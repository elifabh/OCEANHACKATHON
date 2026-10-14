"""Extract genuine recorded frames; never reconstruct or replace application values."""
import subprocess,json
from pathlib import Path
R=Path(__file__).resolve().parents[1];W=R/'work/jury_release_20261014';O=R/'outputs/jury_release_20261014'
F=O/'fallback_stills';F.mkdir(exist_ok=True)
for duration,times in [(55,[0,6,12,17,22,29,38,42,47,50,53]),(30,[0,5,8,11,17,21,24,26,28])]:
 (W/f'frames-{duration}.json').write_text(json.dumps(times))
 for i,t in enumerate(times):
  subprocess.run([str(R/'work/story_20261014/ffmpeg.exe'),'-v','error','-ss',str(t),'-i',str(O/f'DEMO_{duration}_SECONDS.mp4'),'-frames:v','1','-y',str(F/f'{duration}_{i+1:02}.png')],check=True)
subprocess.run([str(R/'work/story_20261014/ffmpeg.exe'),'-v','error','-ss','38','-i',str(O/'DEMO_55_SECONDS.mp4'),'-frames:v','1','-y',str(W/'film-euro.png')],check=True)
print('Extracted actual frames from both final recordings.')
