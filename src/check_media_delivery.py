"""Verify final media embeds, numerical chart provenance and timing metadata."""
import json,hashlib,re
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as E
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/presentations_final_20261014'
d=json.loads((ROOT/'outputs/map/evidence.json').read_text());results=[]
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
for minutes,seconds,frames in [(3,30,8),(5,55,9)]:
    ppt=OUT/f'SUNDAY_{minutes}_MINUTES_FINAL.pptx';movie=OUT/f'DEMO_{seconds}_SECONDS.mp4'
    movie_hash=hashlib.sha256(movie.read_bytes()).hexdigest()
    meta=json.loads(movie.with_suffix('.mp4.json').read_text())
    assert meta['build_id']==d['build_id'] and meta['sha256']==movie_hash
    with ZipFile(ppt) as z:
        slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)];assert len(slides)==6
        hashes={hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('ppt/media/')}
        assert movie_hash in hashes,'Standalone movie must be embedded byte-for-byte'
        notes=' '.join(z.read(n).decode() for n in z.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n))
        assert d['build_id'] in notes and 'DELIVERY NOTE' in notes
        ticks=0
        for name in slides:
            sl=E.fromstring(z.read(name));trans=sl.find('.//p:transition',ns);ticks+=int(trans.get('advTm','0'))
        assert ticks==minutes*60*1000
        s5=E.fromstring(z.read('ppt/slides/slide5.xml'))
        assert len([x for x in s5.findall('.//p:cNvPr',ns) if x.get('name','').startswith('verified-frame-')])==frames
        chart_names=[n for n in z.namelist() if n.startswith('ppt/charts/') and n.endswith('.xml') and '/_rels/' not in n]
        numbers=[]
        for name in chart_names:
            c=E.fromstring(z.read(name))
            for x in c.findall('.//c:val//c:pt/c:v',ns):numbers.append(float(x.text))
        assert any(abs(x-100*(1-d['physical']['height_fraction']))<1e-6 for x in numbers),numbers
        assert any(x==100 for x in numbers)
        assert any(n.startswith('ppt/embeddings/') and n.endswith('.xlsx') for n in z.namelist()),'Editable chart workbook missing'
    results.append({'file':ppt.name,'status':'PASS','slides':6,'embedded_movie_sha256':movie_hash,'default_native_frames':frames,'timing_budget_seconds':minutes*60,'native_chart_matches_evidence':True})
(ROOT/'outputs/final_20261014/qa/media_package_report.json').write_text(json.dumps({'status':'PASS','build_id':d['build_id'],'checks':results},indent=2))
print(json.dumps(results,indent=2))

