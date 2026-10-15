"""Extract actual PowerPoint-rendered motion, not static authoring previews."""
from pathlib import Path
import subprocess,json
from PIL import Image,ImageOps,ImageDraw
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs/final_creative_20261015'; QA=OUT/'qa'; DEST=QA/'native-motion-frames'; DEST.mkdir(exist_ok=True)
FF=ROOT/'work/story_20261014/ffmpeg.exe'; VIDEO=QA/'POWERPOINT_NATIVE_ANIMATION_REVIEW.mp4'
rows=[]
for slide in range(1,13):
    canvas=Image.new('RGB',(1920,3*564),'#071b28')
    for j,t in enumerate([2,8,16,24,29,31]):
        absolute=(slide-1)*32+t+.15
        dest=DEST/f'slide-{slide:02d}-{t:02d}s.png'
        subprocess.run([str(FF),'-hide_banner','-loglevel','error','-ss',str(absolute),'-i',str(VIDEO),'-frames:v','1','-y',str(dest)],check=True)
        pic=Image.open(dest).convert('RGB'); small=pic.resize((960,540),Image.Resampling.LANCZOS)
        x=(j%2)*960;y=(j//2)*564;canvas.paste(small,(x,y+24));ImageDraw.Draw(canvas).text((x+12,y+4),f'SLIDE {slide} / {t}s / actual PowerPoint native render',fill='white')
        rows.append({'slide':slide,'slide_seconds':t,'video_seconds':absolute,'path':str(dest.relative_to(OUT))})
    canvas.save(DEST/f'contact-{slide:02d}.jpg',quality=93)
(QA/'native-motion-frames.json').write_text(json.dumps(rows,indent=2))
print(f'Extracted {len(rows)} actual native animation frames.')
