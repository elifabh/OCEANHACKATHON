"""Restore authored chart literal precision after PowerPoint floating point serialization."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from decimal import Decimal
import re
root=Path(__file__).resolve().parents[1]/'work/product_pitch'
for variant in ['main','compact','friday']:
    with ZipFile(root/f'{variant}-draft.pptx') as source:
        authored={}
        for n in source.namelist():
            if '/charts/chart' in n and n.endswith('.xml'):
                for raw in re.findall(rb'<c:v>([^<]+)</c:v>',source.read(n)):
                    try:authored[float(raw)]=raw
                    except ValueError:pass
    with ZipFile(root/f'{variant}-native.pptx') as zin,ZipFile(root/f'{variant}-ready.pptx','w',ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data=zin.read(item.filename)
            if item.filename.startswith('ppt/charts/chart') and item.filename.endswith('.xml'):
                def restore(m):
                    try:v=float(m.group(1))
                    except ValueError:return m.group(0)
                    candidates=[raw for original,raw in authored.items() if abs(original-v)<1e-12]
                    return b'<c:v>'+candidates[0]+b'</c:v>' if len(candidates)==1 else m.group(0)
                data=re.sub(rb'<c:v>([^<]+)</c:v>',restore,data)
            zout.writestr(item,data)
    print(variant,'authored numeric values preserved')
