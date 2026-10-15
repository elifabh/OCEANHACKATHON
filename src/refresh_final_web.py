"""Refresh only web/assistant sources over the verified saved geospatial payload.

Refuses if any scientific source or input hash changed. Use build_map.py for a
full deterministic rebuild. No raw research or previous accepted output is edited.
"""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_overnight_20261015/app'
sys.path.insert(0,str(ROOT/'src'))
from assessment_graph import build_graph
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    manifest=json.loads((OUT/'build_manifest.json').read_text());data=json.loads((OUT/'evidence.json').read_text(encoding='utf8'))
    allowed={'src/assessment_graph.py','src/assessment_assistant.js','src/assistant_panel.js','src/assistant_panel.css','src/assistant_server.py','src/assistant_config.json','src/assistant_cli.cjs','src/cape_report.js','src/cape_visuals.js','src/cape_template.html','src/cape_workspace.css','src/cape_workspace.js','src/launch_demo.py','src/check_demo.py','START_ASSISTANT.bat','START_DEMO.bat','CHECK_DEMO.bat'}
    for key,expected in manifest['source_sha256'].items():
        if sha(ROOT/key)!=expected and key not in allowed:raise ValueError('Full rebuild required: '+key)
    for key,expected in manifest['input_sha256'].items():
        if sha(ROOT/key)!=expected:raise ValueError('Full rebuild required for changed scientific input: '+key)
    manifest['source_sha256']={k:sha(ROOT/k) for k in manifest['source_sha256']}
    base={k:manifest[k] for k in ['build_date','source_sha256','input_sha256']};build=hashlib.sha256(json.dumps(base,sort_keys=True).encode()).hexdigest()[:12]
    data['build_id']=build;data['assistant_graph']=build_graph(data['product'])
    encoded=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    html=(ROOT/'src/cape_template.html').read_text(encoding='utf8').replace('/*__MAP_DATA__*/null',encoded)
    assert len(html.encode())<15e6
    (OUT/'index.html').write_text(html,encoding='utf8');(OUT/'evidence.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');(OUT/'assistant_graph.json').write_text(json.dumps(data['assistant_graph'],ensure_ascii=False,indent=2),encoding='utf8')
    for name in manifest['output_sha256']:
        if '/' not in name and name.endswith(('.js','.css')) and (ROOT/'src'/name).is_file():(OUT/name).write_bytes((ROOT/'src'/name).read_bytes())
    manifest['build_id']=build;manifest['output_sha256']={k:sha(OUT/k) for k in manifest['output_sha256']};(OUT/'build_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8');print('Verified web refresh:',build)
if __name__=='__main__':main()
