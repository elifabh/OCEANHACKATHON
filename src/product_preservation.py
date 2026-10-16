"""Hash-only preservation audit; archive only the small previously working web app."""
from pathlib import Path
import hashlib, json, sys, zipfile
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/product_cape_clear_20261015'
def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = OUT / 'preserved_files.json'
    if '--capture' in sys.argv:
        if baseline.exists(): raise SystemExit('Baseline already exists; refusing to replace it.')
        files = [p for folder in ['data', 'outputs', 'docs'] for p in (ROOT/folder).rglob('*')
                 if p.is_file() and not p.is_relative_to(OUT) and not p.is_relative_to(ROOT/'outputs/map')]
        baseline.write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in files}, indent=2))
        with zipfile.ZipFile(OUT/'previous_working_app.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for p in (ROOT/'outputs/map').rglob('*'):
                if p.is_file(): z.write(p, p.relative_to(ROOT/'outputs/map'))
        print('Preserved',len(files),'files; previous web app archived without duplicating raw datasets.')
    else:
        expected=json.loads(baseline.read_text())
        changed=[n for n,h in expected.items() if not (ROOT/n).is_file() or sha(ROOT/n)!=h]
        result={'status':'FAIL' if changed else 'PASS','files_checked':len(expected),'changed':changed,
                'new_training_runs':0,'final_presentation_or_video_modified':False if not changed else None}
        (OUT/'preservation_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        return bool(changed)
if __name__=='__main__':sys.exit(main())
