"""Read-only source comparison; never modifies research data or infers authorship."""
import argparse, hashlib, json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/presentations_visual_v2_20261014'
BASE=OUT/'PRE_WEEKEND_SOURCE_BASELINE.json'
def snapshot():
    files=list((ROOT/'src').rglob('*'))+list((ROOT/'tests').rglob('*'))+list(ROOT.glob('*.bat'))
    return {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files) if p.is_file() and '__pycache__' not in str(p) and p.suffix.lower() not in ['.pyc']}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',action='store_true');args=ap.parse_args();now=snapshot()
    if args.baseline:
        if BASE.exists():raise SystemExit('Baseline already exists. Preserve it; use comparison mode.')
        BASE.write_text(json.dumps({'prepared':'2026-10-14','meaning':'AI-assisted preparation; no weekend authorship claimed','files':now},indent=2),encoding='utf-8');print(BASE);return
    old=json.loads(BASE.read_text(encoding='utf-8'))['files']
    changed=[p for p in now if p in old and now[p]!=old[p]];added=[p for p in now if p not in old];missing=[p for p in old if p not in now]
    print(json.dumps({'changed':changed,'added':added,'missing':missing,'note':'This proves file changes only, not who contributed or whether results are valid.'},indent=2))
if __name__=='__main__':main()
