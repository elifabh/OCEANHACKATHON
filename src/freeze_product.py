"""Record the completed phase before any dependent media production."""
from pathlib import Path
import json,hashlib,datetime,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_delivery_20261014';m=json.loads((ROOT/'outputs/map/build_manifest.json').read_text());now=datetime.datetime.now(datetime.timezone.utc).isoformat()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if sys.argv[1]=='app':
    tests=json.loads((OUT/'qa/test_report.json').read_text());assert tests['status']=='PASS' and tests['build_id']==m['build_id']
    body=dict(build_id=m['build_id'],frozen_utc=now,test_status=tests['status'],report_sha256=sha(OUT/'ASSESSMENT_PILOT.pdf'),source_sha256=m['source_sha256'],input_sha256=m['input_sha256'])
    (OUT/'APP_REPORT_FREEZE.json').write_text(json.dumps(body,indent=2))
else:
    assert json.loads((OUT/'qa/presentation-ui-tests.json').read_text())['status']=='PASS'
    names=['SUNDAY_10_MINUTES.pptx','SUNDAY_5_MINUTES.pptx','FRIDAY_INVITATION.pptx','OFFLINE_PRESENTATION.html','SPEAKER_NOTES.html','PRESENTATION_SCENARIO.json']
    names += [p.relative_to(OUT).as_posix() for p in (OUT/'presentation_assets').rglob('*.png')]
    body=dict(build_id=m['build_id'],frozen_utc=now,app_report_freeze=json.loads((OUT/'APP_REPORT_FREEZE.json').read_text())['frozen_utc'],ui_test_status='PASS',files={name:sha(OUT/name) for name in names})
    (OUT/'PRESENTATION_FREEZE.json').write_text(json.dumps(body,indent=2))
print(sys.argv[1],m['build_id'],now)
