"""Run original frozen assertions against the new output via temporary path adapters."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_overnight_20261015';TMP=OUT/'qa/adapted_tests';TMP.mkdir(parents=True,exist_ok=True)
NODE=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
def adapt(text):return text.replace('outputs/product_cape_clear_20261015','outputs/final_overnight_20261015').replace('outputs/map','outputs/final_overnight_20261015/app')
def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'all'
    if mode in ['all','python']:
        for source in (ROOT/'tests').glob('test_*.py'):
            content=adapt(source.read_text(encoding='utf8')).replace('Path(__file__).resolve().parents[1]',repr(str(ROOT)))
            # Keep Path operations valid; only the original test source location changes.
            content=content.replace(repr(str(ROOT)), 'Path('+repr(str(ROOT))+')')
            (TMP/source.name).write_text(content,encoding='utf8')
        p=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(TMP),'-p','test_*.py','-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf8',errors='replace');(OUT/'qa/numerical_tests.log').write_text(p.stdout+p.stderr,encoding='utf8');print(p.stdout+p.stderr);p.check_returncode()
    if mode in ['all','browser']:
        for name in ['browser_cape_product.mjs','browser_cape_report.mjs','browser_cape_acceptance.mjs','browser_cape_print.cjs']:
            target=TMP/name;target.write_text(adapt((ROOT/'tests'/name).read_text(encoding='utf8')),encoding='utf8');subprocess.run([str(NODE),str(target)],cwd=ROOT,check=True)
    if mode in ['all','assistant']:subprocess.run([str(NODE),'tests/assistant_acceptance.cjs'],cwd=ROOT,check=True)
if __name__=='__main__':main()
