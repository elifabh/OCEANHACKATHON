"""Reproduce the focused Cape Clear alternative-site check without altering data.

The cached service response can be refreshed explicitly with --refresh-depth.
Point depths are not a surveyed continuous shallow-habitat boundary. The 50 m
sampling squares are clipped to the historical NPWS geometry, not called kelp.
"""
from pathlib import Path
import argparse,json,math,datetime
import requests,numpy as np,geopandas as gpd,pandas as pd
from shapely.geometry import Point,LineString,box
from shapely.ops import unary_union,transform,nearest_points
from evidence_pipeline import ROOT,NPWS,ITM,TO_ITM,TO_WGS,clean,fc,feature,build_coast,build_wave,sha
from coastal_physics import connected_groups,sample_bundle,direction_vector,path_status
from parametric_assessment import shore_inputs

OUT=ROOT/'outputs/visual_v2_20261014/inputs'
SERVICE='https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer'

def run(refresh=False):
    OUT.mkdir(parents=True,exist_ok=True)
    c=pd.read_csv(ROOT/'outputs/national_candidate_table.csv').query("county=='Cork' and cluster==5").iloc[0]
    centre=Point(*TO_ITM(c.lon,c.lat));search=centre.buffer(1000)
    ref=gpd.read_file(NPWS).to_crs(ITM)
    ref=ref[ref.Commun_Typ.str.contains('Laminaria',case=False,na=False)&ref.intersects(search)]
    historical=unary_union(ref.geometry.tolist()).intersection(search)
    x0,y0,x1,y1=historical.bounds
    pts=[Point(x,y) for x in np.arange(x0+25,x1,50) for y in np.arange(y0+25,y1,50) if historical.covers(Point(x,y))]
    query={'f':'json','geometryType':'esriGeometryMultipoint','geometry':json.dumps({'points':[TO_WGS(p.x,p.y) for p in pts],'spatialReference':{'wkid':4326}}),'returnFirstValueOnly':'true','interpolation':'RSP_NearestNeighbor'}
    (OUT/'c5_depth_request.json').write_text(json.dumps({'url':SERVICE+'/getSamples','parameters':query,'sampling':'50 m grid centres within historical geometry / 1 km of archive building cluster','query_reconstructed_from_sampling_rule':True},indent=2))
    rawpath=OUT/'c5_depth_raw.json'
    if refresh or not rawpath.exists():
        response=requests.post(SERVICE+'/getSamples',data=query,timeout=60);response.raise_for_status();raw=response.json()
        if 'samples' not in raw:raise ValueError(str(raw)[:300])
        rawpath.write_text(json.dumps(raw))
    raw=json.loads(rawpath.read_text());samples=[];cells=[];depths=[]
    for s in raw['samples']:
        try:depth=-float(s['value'])
        except (ValueError,TypeError):continue
        p=Point(*TO_ITM(s['location']['x'],s['location']['y']))
        # Cached points must correspond to the documented reconstruction.
        if min(p.distance(q) for q in pts)>.02:raise ValueError('Cached sample is not on reconstructed grid')
        samples.append({'lon':s['location']['x'],'lat':s['location']['y'],'depth_m':depth})
        if not 4<=depth<=10:continue
        poly=p.buffer(25,cap_style='square').intersection(historical)
        for part in (list(poly.geoms) if hasattr(poly,'geoms') else [poly]):
            if part.geom_type=='Polygon' and part.area>1:cells.append(part);depths.append(depth)
    land,coast,domain,context=build_coast((-9.53,51.42,-9.41,51.49))
    wave=build_wave(unary_union(cells).centroid);bearing=wave['travel_deg'];u=direction_vector(bearing)
    results=[];features=[]
    for i,ids in enumerate(connected_groups(cells),1):
        local=[cells[j] for j in ids];bed=unary_union(local);origin=bed.representative_point()
        # Does the straight incoming 2 km path hit land before this habitat?
        upstream=Point(origin.x-2000*u[0],origin.y-2000*u[1])
        incoming=LineString([upstream,origin]);inner=LineString([upstream,incoming.interpolate(max(0,incoming.length-2))])
        shadow=inner.intersection(land).length>1 or inner.intersects(coast)
        physical=sample_bundle(local,[depths[j] for j in ids],bearing,land=land)
        shoreline=shore_inputs(local,bearing,coast,land,domain,10)
        r={'group':i,'sampling_fragments':len(ids),'historical_sampling_area_ha':bed.area/10000,
           'incoming_2km_land_blocked':shadow,'model':physical,'candidate_shore_length_m':shoreline['length_m'],
           'current_habitat_validated':False,'depth_is_point_sample':True,'status':'INCOMING_WAVE_SHADOW' if shadow else 'FIELD_AND_NEARSHORE_VALIDATION_REQUIRED'}
        results.append(r);features.append(feature(bed,{k:v for k,v in r.items() if k!='model'}))
    output={'site':'Cape Clear vicinity / Cork archive cluster 5','location':[c.lon,c.lat],
       'historical_area_ha_within_1km':historical.area/10000,'historical_communities':sorted(set(ref.Commun_Typ)),
       'requested_depth_points':len(pts),'valid_depth_points':len(samples),'depth_eligible_points':sum(4<=s['depth_m']<=10 for s in samples),
       'point_depth_note':'Point depth does not prove every part of a sampling square lies within 4–10 m. Survey datum needs source-specific verification before valuation.',
       'wave':wave,'groups':results,'historical_layer':fc([feature(historical,{'evidence':'HISTORICAL_REFERENCE'})]),'sampling_layer':fc(features),'coastline':context,
       'sources':{'NPWS_shp_sha256':sha(NPWS),'depth_response_sha256':sha(rawpath),'depth_service':SERVICE,'coastline_sha256':sha(ROOT/'data/osm/overpass_1a75c6425bde.json')},
       'avoided_damage_eur':None,'ecosystem_service_value_eur':None}
    (OUT/'cape_clear_screen.json').write_text(json.dumps(clean(output),indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(clean({k:v for k,v in output.items() if k not in ['historical_layer','sampling_layer','coastline','sources']}),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--refresh-depth',action='store_true');a=p.parse_args();run(a.refresh_depth)
