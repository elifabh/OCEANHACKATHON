"""Decode every movie frame and inspect native MP4 tracks without installing codecs."""
from pathlib import Path
import json,struct,subprocess,re,hashlib,datetime
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_delivery_20261014';QA=OUT/'qa';FF=ROOT/'work/story_20261014/ffmpeg.exe'
def boxes(data,start=0,end=None):
    end=len(data) if end is None else end
    while start+8<=end:
        size,tag=struct.unpack('>I4s',data[start:start+8]);header=8
        if size==1:size=struct.unpack('>Q',data[start+8:start+16])[0];header=16
        if size==0:size=end-start
        if size<header:raise ValueError('Invalid MP4 box')
        yield tag,data[start+header:start+size]
        start+=size
def child(data,tag):return next(payload for kind,payload in boxes(data) if kind==tag)
rows=[]
for duration in [75,30]:
    file=OUT/f'DEMO_{duration}_SECONDS.mp4';data=file.read_bytes();moov=child(data,b'moov');mvhd=child(moov,b'mvhd');version=mvhd[0]
    scale,total=struct.unpack('>II',mvhd[12:20]) if version==0 else (struct.unpack('>I',mvhd[20:24])[0],struct.unpack('>Q',mvhd[24:32])[0])
    tracks=[]
    for tag,payload in boxes(moov):
        if tag!=b'trak':continue
        mdia=child(payload,b'mdia');hdlr=child(mdia,b'hdlr');tracks.append(hdlr[8:12].decode())
    assert tracks==['vide'],tracks
    assert abs(total/scale-duration)<.05
    run=subprocess.run([str(FF),'-hide_banner','-i',str(file),'-map','0:v:0','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (QA/f'media-{duration}-decode.log').write_text(run.stderr,encoding='utf-8');assert run.returncode==0,run.stderr
    assert 'h264' in run.stderr and '1920x1080' in run.stderr
    pixel_format=re.search(r'Video: h264[^\n]*?\b(yuvj?420p)\b',run.stderr).group(1)
    frames=[float(t) for t in ([0,13,26,39,47,55,61,69,74.5] if duration==75 else [0,5,10,16,19,23,27,29.5])]
    for idx,at in enumerate(frames):
        dst=QA/f'media-{duration}-{idx:02}.png'
        p=subprocess.run([str(FF),'-hide_banner','-loglevel','error','-ss',str(at),'-i',str(file),'-frames:v','1','-y',str(dst)],capture_output=True)
        assert p.returncode==0 and dst.stat().st_size>10000
    manifest=json.loads(Path(str(file)+'.json').read_text());assert hashlib.sha256(data).hexdigest()==manifest['sha256'];assert manifest['started_utc']>manifest['presentation_frozen_utc']
    rows.append(dict(file=file.name,status='PASS',duration_seconds=total/scale,tracks=tracks,codec='H.264',pixel_format=pixel_format,width=1920,height=1080,full_decode=True,frame_samples=frames,last_frame_sample=frames[-1],recorded_after_presentation_freeze=True,sha256=manifest['sha256'],build_id=manifest['build_id']))
(QA/'media-tests.json').write_text(json.dumps(dict(status='PASS',checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),movies=rows),indent=2));print(json.dumps(rows,indent=2))
