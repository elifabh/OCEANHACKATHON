"""Build-specific PDF semantic regression and page rendering; no source data changes."""
from pathlib import Path
import json, re, hashlib, subprocess
from datetime import datetime, timezone
from pypdf import PdfReader
from PIL import Image, ImageOps, ImageDraw
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/product_cape_clear_20261015';QA=OUT/'qa'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    manifest=json.loads((ROOT/'outputs/map/build_manifest.json').read_text());build=manifest['build_id'];checks=[]
    poppler=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
    for name,folder,frontage,share in [('ASSESSMENT_CAPE_CLEAR',OUT,100,1),('ASSESSMENT_MODIFIED',QA,150,.25)]:
        data=json.loads((folder/(name+'.json')).read_text(encoding='utf8'));s=data['selected_state'];r=s['assessment']
        assert data['build_id']==build
        assert s['inputs']['frontage_m']==frontage and s['inputs']['cost_share']==share
        pdf=folder/(name+'.pdf');pages=PdfReader(pdf).pages;text='\n'.join(p.extract_text() or '' for p in pages)
        normalized=re.sub(r'\s+',' ',text)
        assert 'illustrative 100 m' not in text
        assert 'source project' in text and 'not the user-selected frontage' in normalized
        assert build in text and 'f611c7dbc4e7' not in text and '32caac3b209d' not in text
        assert 'AllSurvey' in text and 'datum is unverified' in normalized
        assert 'Current bed extent requires a contemporary survey' in normalized
        assert 'Avoided damage and kelp service value: not quantified' in normalized
        assert '1 / ' in text
        for label,numerator,denominator in [('low',668921,155),('project_pooled',668921+657338+500535,325),('high',500535,70)]:
            expected=frontage*numerator/denominator*share*s['inputs']['rate_multiplier']
            assert abs(r['bands'][label]['capital_eur']-expected)<.00001
            assert f'€{expected:,.0f}' in normalized,(name,label,expected)
            rate=s['inputs']['discount_rate'];years=s['inputs']['years'];annual=expected*(rate/(1-(1+rate)**(-years)) if rate else 1/years)
            assert abs(r['bands'][label]['annualised_eur_per_year']-annual)<.00001
            assert f'€{annual:,.0f}' in normalized
        assert f'{frontage} m' in text and f'{share*100:.0f}%' in text
        assert f'{r["from_deg"]:.0f}°' in text
        assert f'{r["height_fraction"]*100:.2f}%' in text
        assert 'not measured at Cape Clear' in normalized
        # A report contains all twelve real sections; no blank or almost-empty page.
        for i in range(1,13):assert f'INVISIBLE SHIELD / {i:02}' in text
        counts=[len(p.extract_text().strip()) for p in pages];assert min(counts)>180,counts
        render=QA/'rendered'/build/name;render.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(poppler),'-scale-to','1250','-png',str(pdf),str(render/'page')],check=True,capture_output=True)
        images=sorted(render.glob('page-*.png'));assert len(images)==len(pages)
        thumbs=[]
        for i,file in enumerate(images):
            im=Image.open(file).convert('RGB');im.thumbnail((270,390));tile=Image.new('RGB',(290,420),'#dde6eb');tile.paste(im,((290-im.width)//2,20));ImageDraw.Draw(tile).text((10,402),f'{name} / {i+1}',fill='#16364a');thumbs.append(tile)
        sheet=Image.new('RGB',(290*4,420*((len(thumbs)+3)//4)),'white')
        for i,im in enumerate(thumbs):sheet.paste(im,((i%4)*290,(i//4)*420))
        sheet.save(render/'contact.png')
        (render/'extracted.txt').write_text(text,encoding='utf8')
        checks.append({'report':name,'pages':len(pages),'frontage_m':frontage,'share':share,'pdf_sha256':sha(pdf),'json_sha256':sha(folder/(name+'.json')),'html_sha256':sha(folder/(name+'.html')),'render_folder':str(render.relative_to(ROOT)),'page_text_counts':counts,'status':'PASS'})
    result={'status':'PASS','build_id':build,'checked_utc':datetime.now(timezone.utc).isoformat(),'checks':checks,'visual_review':'PNG pages generated; human-readable visual inspection is recorded separately in ACCEPTANCE.txt'}
    (QA/'pdf_readback.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
