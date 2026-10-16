"""Inspect frames from delivered MP4s, including real focus and results."""
from pathlib import Path
from PIL import Image,ImageDraw
import subprocess,json
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_creative_20261015';DEST=OUT/'qa/demo-frames';DEST.mkdir(exist_ok=True)
FF=ROOT/'work/story_20261014/ffmpeg.exe';rows=[]
for n,times in [(75,[0,5,9,12,15,19,24,28,31,35,41,47,51,55,61,65,68,71,74]),(30,[0,3,6,8,10,12,15,18,21,24,26,29])]:
    for i,t in enumerate(times):
        target=DEST/f'demo-{n}-{t:02d}.png'
        subprocess.run([str(FF),'-hide_banner','-loglevel','error','-ss',str(t),'-i',str(OUT/f'DEMO_{n}_SECONDS.mp4'),'-frames:v','1','-y',str(target)],check=True)
        rows.append({'duration':n,'seconds':t,'frame':str(target.relative_to(OUT))})
    for start in range(0,len(times),6):
        canvas=Image.new('RGB',(1920,3*564),'#082b3b');d=ImageDraw.Draw(canvas)
        for j,t in enumerate(times[start:start+6]):
            img=Image.open(DEST/f'demo-{n}-{t:02d}.png').resize((960,540),Image.Resampling.LANCZOS);x=j%2*960;y=j//2*564;canvas.paste(img,(x,y+24));d.text((x+12,y+5),f'ACTUAL {n}s DEMO / {t}s',fill='white')
        canvas.save(DEST/f'contact-{n}-{start//6+1}.jpg',quality=94)
(OUT/'qa/demo-frame-register.json').write_text(json.dumps(rows,indent=2))
print(f'Extracted {len(rows)} actual MP4 frames.')
