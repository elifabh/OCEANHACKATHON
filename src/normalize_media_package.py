"""Remove PowerPoint's empty, optional hyperlink r:id from media actions only.

The media relationships and ppaction://media remain untouched. This avoids a
generic package validator treating the empty optional ID as a missing relation.
"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import re, json
ROOT=Path(__file__).resolve().parents[1]
evidence=json.loads((ROOT/'outputs/map/evidence.json').read_text(encoding='utf-8'))
height_percent=round(100*(1-evidence['physical']['height_fraction']),6)
for variant in ['compact','extended','friday']:
    source=ROOT/'work/story_20261014'/f'{variant}-native.pptx'
    target=source.with_name(f'{variant}-ready.pptx')
    removed=0
    with ZipFile(source) as zin, ZipFile(target,'w',ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data=zin.read(item.filename)
            if item.filename.startswith('ppt/slides/slide') and item.filename.endswith('.xml'):
                def clean(m):
                    global removed
                    tag=m.group(0)
                    if b'action="ppaction://media"' in tag and b'r:id=""' in tag:
                        removed+=1;return tag.replace(b' r:id=""',b'')
                    return tag
                data=re.sub(rb'<a:hlinkClick\b[^>]*>',clean,data)
            if item.filename.startswith('ppt/charts/chart') and item.filename.endswith('.xml'):
                # PowerPoint serialises the IEEE float as 94.154079999999993.
                # Restore its six-decimal source representation for the editable
                # Excel snapshot. Require agreement, never replace other values.
                def exact_source(m):
                    try: value=float(m.group(1))
                    except ValueError:return m.group(0)
                    if abs(value-height_percent)<1e-10:
                        return ('<c:v>'+format(height_percent,'.8f').rstrip('0').rstrip('.')+'</c:v>').encode()
                    return m.group(0)
                data=re.sub(rb'<c:v>([^<]+)</c:v>',exact_source,data)
            zout.writestr(item,data)
    print(variant, 'empty optional media relation attributes normalised:',removed)
