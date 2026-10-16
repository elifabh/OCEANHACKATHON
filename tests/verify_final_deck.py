"""Package, native numbers, timing, no-notes and PDF checks; create montage."""
import json,zipfile,xml.etree.ElementTree as E,re,hashlib,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_overnight_20261015';contract=json.loads((ROOT/'work/final_overnight/deck-contract.json').read_text());checks=[]
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
ppt=OUT/'INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pptx';z=zipfile.ZipFile(ppt);slides=[n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',n)];assert len(slides)==12;checks.append('Exactly twelve approved slides')
text=[];seconds=[]
for i in range(1,13):
    tree=E.fromstring(z.read(f'ppt/slides/slide{i}.xml'));words=' '.join(n.text or '' for n in tree.findall('.//a:t',ns));assert contract['titles'][i-1] in words,(i,words[:300]);text.append(words)
    transition=tree.find('p:transition',ns);seconds.append(int(transition.attrib['advTm'])/1000)
    assert tree.find('p:timing',ns) is not None
assert seconds==contract['native_slide_seconds'] and sum(seconds)==600;checks.append('Approved order and exact 600-second schedule including 75-second demo interval')
for n in z.namelist():
    if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml',n):assert not ''.join(t.text or '' for t in E.fromstring(z.read(n)).findall('.//a:t',ns)).strip()
checks.append('No embedded speaker-note text')
assert '8.43%' in text[5];assert '562,090' in text[6];assert '154 records / 109 taxon names' in text[7];assert 'avoided damage' in text[6];checks.append('Canonical percentage, funding and biodiversity inventory match app')
chart_values=[]
for n in z.namelist():
    if re.fullmatch(r'ppt/charts/chart\d+\.xml',n):
        tree=E.fromstring(z.read(n));values=[float(v.text) for v in tree.findall('.//c:val//c:v',ns)];chart_values.append(values);assert tree.find('c:externalData',ns) is not None
expected=[[round(b['capital_eur']) for b in contract['canonical_result']['bands'].values()],[round(b['annualised_eur_per_year']) for b in contract['canonical_result']['bands'].values()]]
assert sorted(chart_values)==sorted(expected),(chart_values,expected);checks.append('Two editable charts retain exact capital/annual values and embedded workbook relationships')
pdf=PdfReader(OUT/'INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pdf');assert len(pdf.pages)==12
for i,page in enumerate(pdf.pages):
    t=re.sub(r'\s+',' ',page.extract_text());assert contract['build_id'] in t;assert re.sub(r'\s+',' ',contract['titles'][i]) in t
checks.append('Twelve-page PDF contains each approved title and matching build')
tiles=[]
for i in range(1,13):
    im=Image.open(OUT/f'presentation_assets/slides/slide-{i}.png').convert('RGB');assert im.size==(1920,1080);im.thumbnail((480,270));tile=Image.new('RGB',(500,302),'#e3eff4');tile.paste(im,(10,8));ImageDraw.Draw(tile).text((12,282),f'{i:02} / {contract["titles"][i-1]}',fill='#123b4a');tiles.append(tile)
montage=Image.new('RGB',(1500,1208),'white')
for i,tile in enumerate(tiles):montage.paste(tile,((i%3)*500,(i//3)*302))
montage.save(OUT/'PRESENTATION_MONTAGE.png');checks.append('All slides rendered at 1920×1080 and montage generated')
render=OUT/'presentation_assets/pdf';render.mkdir(parents=True,exist_ok=True);poppler=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
subprocess.run([str(poppler),'-scale-to','1280','-png',str(OUT/'INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pdf'),str(render/'slide')],check=True,capture_output=True)
(OUT/'qa/deck-tests.json').write_text(json.dumps({'status':'PASS','build_id':contract['build_id'],'checks':checks,'pptx_sha256':hashlib.sha256(ppt.read_bytes()).hexdigest(),'chart_values':chart_values},indent=2),encoding='utf8');print('PASS',len(checks),'deck checks')
