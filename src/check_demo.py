"""Reproducible local checks. No downloads, credentials or raw-data mutation."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/final_20261014'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    def command(name,args):
        p=subprocess.run(args,cwd=ROOT,text=True,encoding='utf-8',errors='replace',capture_output=True)
        print(p.stdout);print(p.stderr)
        rows.append({'name':name,'status':'PASS' if p.returncode==0 else 'FAIL','returncode':p.returncode})
        (OUT/(name+'.log')).write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
    manifest=json.loads((ROOT/'outputs/map/build_manifest.json').read_text())
    mismatch=[]
    for field,base in [('source_sha256',ROOT),('input_sha256',ROOT),('output_sha256',ROOT/'outputs/map')]:
        for name,expected in manifest[field].items():
            if not (base/name).is_file() or sha(base/name)!=expected:mismatch.append(name)
    rows.append({'name':'source_input_output_consistency','status':'FAIL' if mismatch else 'PASS','mismatches':mismatch})
    print('Build consistency:',rows[-1]['status'])
    command('numerical_tests',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py','-v'])
    command('localhost_smoke',[sys.executable,'src/launch_demo.py','--smoke','--no-browser'])
    runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
    node=shutil.which('node') or str(runtime/'bin/node.exe')
    packages=runtime/'node_modules'
    if Path(node).is_file() and (packages/'playwright').exists():
        command('browser_tests',[node,'tests/browser_smoke.mjs',str(packages)])
        command('story_browser_tests',[node,'tests/browser_story.mjs'])
        command('assessment_browser_tests',[node,'tests/browser_assessment.mjs'])
    else:
        rows.append({'name':'browser_tests','status':'BLOCKED','reason':'Existing Node/Playwright runtime unavailable. No installation attempted.'})
    report={'checked_utc':datetime.now(timezone.utc).isoformat(),'build_id':manifest['build_id'],'checks':rows,
            'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL_OR_BLOCKED'}
    (OUT/'test_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
