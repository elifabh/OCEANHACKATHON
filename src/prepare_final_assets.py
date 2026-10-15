"""Clip existing spatial evidence for editable slide maps; no new observations."""
import json
from pathlib import Path
from shapely.geometry import shape,mapping,box,Point
from shapely.ops import transform,substring
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/final_overnight_20261015';ASSETS=OUT/'presentation_assets';ASSETS.mkdir(parents=True,exist_ok=True)
d=json.loads((OUT/'app/evidence.json').read_text(encoding='utf8'));c=d['product']['cases']['cape_clear'];bounds=[-9.509,51.4275,-9.495,51.4355];clip=box(*bounds)
layers={}
for name in ['land','historical','assets','scenario_layer']:
    fs=[]
    for f in c[name]['features']:
        g=shape(f['geometry']).intersection(clip)
        if not g.is_empty:fs.append({'type':'Feature','geometry':mapping(g),'properties':f['properties']})
    layers[name]=fs
for name,features in [('paths',c['scenario']['directions']['210']['geometry']['features'])]:
    layers[name]=[{'geometry':mapping(shape(f['geometry']).intersection(clip)),'properties':f['properties']} for f in features if not shape(f['geometry']).intersection(clip).is_empty]
to_itm=Transformer.from_crs(4326,2157,always_xy=True).transform;to_geo=Transformer.from_crs(2157,4326,always_xy=True).transform
coast=json.loads((ROOT/'outputs/cork_feasibility_20261015/coastline.geojson').read_text())
line=transform(to_itm,shape(next(f['geometry'] for f in coast['features'] if f['properties']['kind']=='coastline')))
end=c['scenario']['directions']['210']['geometry']['features'][-1]['geometry']['coordinates'][-1]
target=transform(to_itm,Point(end));parts=list(line.geoms) if hasattr(line,'geoms') else [line];near=min(parts,key=lambda g:g.distance(target));at=near.project(target);start=max(0,min(at-50,near.length-100));segment=substring(near,start,start+100)
assert abs(segment.length-100)<.001
layers['assumed_frontage']=[{'geometry':mapping(transform(to_geo,segment)),'properties':{'status':'ILLUSTRATIVE_ASSUMED_COMPARISON_ONLY','length_m':segment.length,'not_verified_protected_frontage':True,'not_tender_alignment':True}}]
(ASSETS/'cape_geometry.json').write_text(json.dumps({'build_id':d['build_id'],'bounds':bounds,'layers':layers}),encoding='utf8')
print('Prepared original-source map geometry:',d['build_id'])
# A static scientific map supports the native PowerPoint zoom fallback when
# Office refuses grouping imported freeforms. The underlying editable geometry
# remains in the slide. This is a data figure, not a photograph of habitat.
import math
W,H=1550,900;cos=math.cos(sum(bounds[1::2])/2*math.pi/180);sc=min((W-40)/((bounds[2]-bounds[0])*cos),(H-40)/(bounds[3]-bounds[1]));cx=(bounds[0]+bounds[2])/2;cy=(bounds[1]+bounds[3])/2
def xy(pt):return (W/2+(pt[0]-cx)*cos*sc,H/2-(pt[1]-cy)*sc)
def path(g):
    if g['type']=='GeometryCollection':return ''.join(path(a) for a in g['geometries'])
    rings=g['coordinates'] if g['type'] in ('Polygon','MultiLineString') else [g['coordinates']] if g['type']=='LineString' else [r for p in g['coordinates'] for r in p] if g['type']=='MultiPolygon' else []
    return ''.join('<path d="'+' '.join(('M' if n==0 else 'L')+','.join(f'{v:.2f}' for v in xy(pt)) for n,pt in enumerate(r))+(' Z' if 'Polygon' in g['type'] else '')+'"/>' for r in rings)
svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"><rect width="{W}" height="{H}" fill="#E3EFF4"/>'
for key,stroke,fill,width in [('land','#9DAFAA','#E7E9DD',2),('historical','#79589A','#D5CADD',2),('assets','#425D68','none',3),('paths','#006C67','none',4),('scenario_layer','#925F15','#E5C790',4)]:svg+=f'<g stroke="{stroke}" fill="{fill}" stroke-width="{width}" fill-rule="evenodd">'+''.join(path(f['geometry']) for f in layers[key])+'</g>'
svg+='</svg>';(ASSETS/'cape_zoom_map.svg').write_text(svg,encoding='utf8')
