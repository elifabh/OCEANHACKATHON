"""Preserve chart values while removing PowerPoint floating-point serialisation noise."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import json,re
root=Path(__file__).resolve().parents[1]
ev=json.loads((root/'outputs/presentations_visual_v2_20261014/EVIDENCE_TABLE.json').read_text())
height=round(100*(1-ev['model']['height_fraction']),6)
for variant in ['compact','extended','friday']:
    source=root/'work/visual_v2'/f'{variant}-native.pptx'
    with ZipFile(source) as zin, ZipFile(source.with_name(f'{variant}-ready.pptx'),'w',ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data=zin.read(item.filename)
            if item.filename.startswith('ppt/charts/chart') and item.filename.endswith('.xml'):
                def exact(m):
                    try:value=float(m.group(1))
                    except ValueError:return m.group(0)
                    if abs(value-height)<1e-10:return f'<c:v>{height:.6f}</c:v>'.encode()
                    return m.group(0)
                data=re.sub(rb'<c:v>([^<]+)</c:v>',exact,data)
            zout.writestr(item,data)
    print(variant,'source chart value preserved:',height)
