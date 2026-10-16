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
OUT=ROOT/'outputs/final_overnight_20261015/qa'


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
    manifest=json.loads((ROOT/'outputs/final_overnight_20261015/app/build_manifest.json').read_text())
    mismatch=[]
    for field,base in [('source_sha256',ROOT),('input_sha256',ROOT),('output_sha256',ROOT/'outputs/final_overnight_20261015/app')]:
        for name,expected in manifest[field].items():
            if not (base/name).is_file() or sha(base/name)!=expected:mismatch.append(name)
    rows.append({'name':'source_input_output_consistency','status':'FAIL' if mismatch else 'PASS','mismatches':mismatch})
    print('Build consistency:',rows[-1]['status'])
    command('numerical_tests',[sys.executable,'src/run_final_regressions.py','python'])
    command('assistant_questions',[sys.executable,'src/run_final_regressions.py','assistant'])
    command('assistant_service',[sys.executable,'tests/assistant_service_acceptance.py'])
    command('localhost_smoke',[sys.executable,'src/launch_demo.py','--smoke','--no-browser'])
    runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
    node=shutil.which('node') or str(runtime/'bin/node.exe')
    packages=runtime/'node_modules'
    if Path(node).is_file() and (packages/'playwright').exists():
        command('all_original_browser_assertions',[sys.executable,'src/run_final_regressions.py','browser'])
        command('assistant_browser',[node,'tests/browser_assistant.mjs'])
        pdf_python=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        from run_final_regressions import adapt,TMP
        pdf_test=TMP/'verify_cape_pdf.py'
        pdf_test.write_text(adapt((ROOT/'tests/verify_cape_pdf.py').read_text(encoding='utf8')).replace('Path(__file__).resolve().parents[1]', 'Path('+repr(str(ROOT))+')'),encoding='utf8')
        command('pdf_readback_and_render',[str(pdf_python),'-X','utf8',str(pdf_test)])
    else:
        rows.append({'name':'browser_tests','status':'BLOCKED','reason':'Existing Node/Playwright runtime unavailable. No installation attempted.'})
    baseline=json.loads((ROOT/'outputs/product_cape_clear_20261015/preserved_files.json').read_text())
    old=json.loads((ROOT/'outputs/map/build_manifest.json').read_text())
    changed=[n for n,h in baseline.items() if not (ROOT/n).is_file() or sha(ROOT/n)!=h]
    changed += ['outputs/map/'+n for n,h in old['output_sha256'].items() if sha(ROOT/'outputs/map'/n)!=h]
    preservation={'status':'FAIL' if changed else 'PASS','original_files':len(baseline),'accepted_app_files':len(old['output_sha256']),'changed':changed,'new_training_runs':0}
    (OUT/'preservation_result.json').write_text(json.dumps(preservation,indent=2))
    rows.append({'name':'original_data_and_accepted_app_preservation',**preservation})
    report={'checked_utc':datetime.now(timezone.utc).isoformat(),'build_id':manifest['build_id'],'checks':rows,
            'status':'PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL_OR_BLOCKED'}
    (OUT/'test_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
