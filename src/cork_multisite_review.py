"""Cork multi-location evidence audit. No model training or app build.

Online acquisition: .venv/Scripts/python.exe src/cork_multisite_review.py --acquire
Offline analysis:  .venv/Scripts/python.exe src/cork_multisite_review.py --analyse
All new files are confined to outputs/cork_multisite_review_20261015.
"""
from pathlib import Path
import json, argparse, math, hashlib
from datetime import datetime, timezone
from collections import Counter
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.windows import from_bounds
from rasterio.transform import from_origin
from shapely.geometry import box, Point, shape, mapping
from shapely.ops import transform, unary_union
from pyproj import Transformer
from scipy.ndimage import binary_dilation
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/cork_multisite_review_20261015'
SSCO = ROOT/'outputs/npws_source_review/20261013T020954_399007Z/layer_01/CO_Marine_Community_Types.shp'
ARTICLE = ROOT/'data/npws/gis_files/21 NPWSArticle17Habitat.shp'
TO_ITM = Transformer.from_crs(4326,2157,always_xy=True).transform
TO_WGS = Transformer.from_crs(2157,4326,always_xy=True).transform
SITES = {
 'sherkin': {'name':'Sherkin / Baltimore','bbox':[-9.44,51.45,-9.355,51.505], 'anchor':[-9.405,51.475]},
 'cape_clear': {'name':'Cape Clear','bbox':[-9.53,51.425,-9.43,51.47], 'anchor':[-9.486,51.445]},
 'long_island': {'name':'Long Island / Copper Point','bbox':[-9.585,51.48,-9.51,51.525], 'anchor':[-9.5347777778,51.5018888889]},
 'inner_roaringwater': {'name':'Inner Roaringwater Bay','bbox':[-9.52,51.49,-9.44,51.54], 'anchor':[-9.48,51.515]},
 'bantry': {'name':'Bantry Bay / north shore','bbox':[-9.72,51.62,-9.48,51.74], 'anchor':[-9.60,51.69]},
 'lough_hyne': {'name':'Lough Hyne / adjacent open coast','bbox':[-9.32,51.475,-9.27,51.515], 'anchor':[-9.30,51.49]},
 'ballydonegan': {'name':'Ballydonegan / Allihies','bbox':[-10.10,51.60,-10.02,51.65], 'anchor':[-10.06,51.63]},
 'mizen': {'name':'Mizen / Crookhaven','bbox':[-9.86,51.44,-9.70,51.52], 'anchor':[-9.79,51.475]}}
DATES = ['2022-05-15','2022-07-14']
DEPTH_URL = 'https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer'
STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1/search'


def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,np.ndarray)):return [clean(v) for v in value]
    if isinstance(value,(np.integer,)):return int(value)
    if isinstance(value,(np.bool_,)):return bool(value)
    if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
    if isinstance(value,(pd.Timestamp,datetime)):return value.isoformat()
    return value


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),indent=2,allow_nan=False),encoding='utf-8')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''):h.update(block)
    return h.hexdigest()


def fetch_json(path,url,params,post=False):
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    r=requests.post(url,json=params,timeout=90) if post else requests.get(url,params=params,timeout=90)
    r.raise_for_status(); data=r.json()
    if 'error' in data:raise RuntimeError(str(data['error']))
    save(path,data)
    save(path.with_suffix('.request.json'),{'url':url,'parameters':params,'method':'POST_JSON' if post else 'GET',
                                          'retrieved_utc':datetime.now(timezone.utc).isoformat(),'sha256':sha(path)})
    return data


def acquire():
    from cork_pilot_acquire import signed
    OUT.mkdir(parents=True,exist_ok=True)
    save(OUT/'sites_and_protocol.json',{'sites':SITES,'dates':DATES,'no_training':True,
         'selection_policy':'Compare all named candidates and four alternatives. No money-based ranking. Regional windows differ in area; counts are availability measures, not a site score.',
         'imagery':'Two fixed dates shared across all sites. SCL QA only, not underwater visibility or vegetation classification.',
         'depth':'11 by 11 regular points in each regional window; coverage probe only, not a bathymetric survey or inferred kelp.',
         'references':'Recompute SSCO and Article17 separately; never treat layer agreement or disagreement as current ecological truth.'})
    for key,site in SITES.items():
        folder=OUT/'inputs'/key;folder.mkdir(parents=True,exist_ok=True)
        bbox=site['bbox']; xs=np.linspace(bbox[0],bbox[2],11);ys=np.linspace(bbox[1],bbox[3],11)
        points=[[float(x),float(y)] for x in xs for y in ys]
        params={'f':'json','geometryType':'esriGeometryMultipoint',
                'geometry':json.dumps({'points':points,'spatialReference':{'wkid':4326}}),
                'returnFirstValueOnly':'true','interpolation':'RSP_NearestNeighbor'}
        path=folder/'depth.json'
        if not path.exists():
            r=requests.post(DEPTH_URL+'/getSamples',data=params,timeout=90);r.raise_for_status();d=r.json()
            if 'samples' not in d:raise RuntimeError(str(d)[:300])
            save(path,d);save(folder/'depth_request.json',{'url':DEPTH_URL+'/getSamples','parameters':params,'requested_points':points,'retrieved_utc':datetime.now(timezone.utc).isoformat()})
        for day in DATES:
            query={'collections':['sentinel-2-l2a'],'bbox':bbox,'datetime':f'{day}T00:00:00Z/{day}T23:59:59Z','limit':100}
            catalog=fetch_json(folder/f'{day}_stac.json',STAC,query,True)
            domain=box(*bbox)
            candidates=[f for f in catalog['features'] if shape(f['geometry']).covers(domain)]
            assert candidates, f'No single full-coverage tile for {key}/{day}; do not claim missing imagery'
            item=sorted(candidates,key=lambda f:(f['properties']['eo:cloud_cover'],f['id']))[0]
            target=folder/f'{day}_SCL.tif'
            if target.exists():continue
            href=item['assets']['SCL']['href']
            xmin,ymin,xmax,ymax=transform_bounds(4326,2157,*bbox,densify_pts=21)
            xmin,ymin=math.floor(xmin/20)*20,math.floor(ymin/20)*20
            xmax,ymax=math.ceil(xmax/20)*20,math.ceil(ymax/20)*20
            affine=from_origin(xmin,ymax,20,20);width,height=int((xmax-xmin)/20),int((ymax-ymin)/20)
            dest=np.zeros((height,width),dtype='uint8')
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',GDAL_HTTP_TIMEOUT='60',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
                with rasterio.open(signed(href)) as ds:
                    bounds=transform_bounds(2157,ds.crs,xmin-40,ymin-40,xmax+40,ymax+40,densify_pts=21)
                    win=from_bounds(*bounds,transform=ds.transform).round_offsets().round_lengths()
                    src=ds.read(1,window=win,boundless=True,fill_value=0)
                    reproject(src,dest,src_transform=ds.window_transform(win),src_crs=ds.crs,
                              dst_transform=affine,dst_crs=2157,src_nodata=0,dst_nodata=0,resampling=Resampling.nearest)
            with rasterio.open(target,'w',driver='GTiff',width=width,height=height,count=1,dtype='uint8',crs=2157,transform=affine,nodata=0,compress='deflate') as ds:ds.write(dest,1)
            save(folder/f'{day}_SCL_metadata.json',{'source_url':href,'item_id':item['id'],'datetime':item['properties']['datetime'],
                                                  'tile_cloud_percent':item['properties']['eo:cloud_cover'],'qa_only':True,'not_benthic_visibility':True})
        print('Acquired regional depth and shared-date image QA:',key,flush=True)


def analyse():
    import xarray as xr
    from rasterio.features import rasterize
    OUT.mkdir(parents=True,exist_ok=True)
    old=json.loads((ROOT/'outputs/cork_pilot_20261015/preserved_originals.json').read_text())
    before={p:sha(ROOT/p) for p in old}
    a=gpd.read_file(ARTICLE,bbox=(-10.2,51.4,-9.2,51.8),fid_as_index=True).to_crs(2157)
    b=gpd.read_file(SSCO).to_crs(2157)
    for g,col in [(a,'Community'),(b,'Commun_Typ')]:
        g['label']=g[col].str.replace(r'\s+',' ',regex=True).str.strip();g.geometry=g.geometry.make_valid()
        g['dedupe']=g.geometry.normalize().to_wkb(hex=True)+'|'+g.label
    a=a.drop_duplicates('dedupe');b=b.drop_duplicates('dedupe')
    obs=pd.DataFrame(json.loads((ROOT/'outputs/obis_raw_occurrences.json').read_text()))
    obs=obs[obs.genus.isin(['Laminaria','Saccharina','Saccorhiza'])|obs.scientificName.eq('Laminariales')].drop_duplicates('occurrenceID')
    obs['date_day']=obs.eventDate.astype(str).str[:10]
    obs['event_key']=obs.decimalLongitude.round(6).astype(str)+'|'+obs.decimalLatitude.round(6).astype(str)+'|'+obs.date_day
    buildings=pd.read_csv(ROOT/'outputs/national_candidate_table.csv').query("county == 'Cork'")
    results=[];events=[];xref=[];assetrows=[];imagerows=[];depthrows=[]
    wave_files=list((ROOT/'data/cmems').glob('ibi_wav_*.nc'))
    # Small coordinate inventory first; read hourly arrays only for the nearest wet candidate.
    wave_points=[]
    for file in wave_files:
        with xr.open_dataset(file) as d:
            if 'longitude' not in d.coords or 'latitude' not in d.coords:continue
            for ix,lon in enumerate(d.longitude.values):
                for iy,lat in enumerate(d.latitude.values):
                    wave_points.append((float(lon),float(lat),str(file.relative_to(ROOT)),iy,ix))
    for key,site in SITES.items():
        bbox=site['bbox'];domain=transform(TO_ITM,box(*bbox));anchor=Point(*TO_ITM(*site['anchor']))
        aa=a[a.intersects(domain)];bb=b[b.intersects(domain)]
        ageom=unary_union(aa[aa.label.str.contains('Laminaria',case=False,na=False)].geometry).intersection(domain)
        bgeom=unary_union(bb[bb.label.str.contains('Laminaria',case=False,na=False)].geometry).intersection(domain)
        conflict=unary_union(aa[aa.label.eq('Faunal turf reef')].geometry).intersection(bgeom)
        for source,g in [('Article17',aa),('SSCO',bb)]:
            for label,group in g.groupby('label'):
                xref.append({'site':key,'source':source,'class':label,'union_area_ha':unary_union(group.geometry).intersection(domain).area/1e4})
        oo=obs[obs.decimalLongitude.between(bbox[0],bbox[2]) & obs.decimalLatitude.between(bbox[1],bbox[3])].copy()
        for event,s in oo.groupby('event_key'):
            r=s.iloc[0];events.append({'site':key,'event_key':event,'date':r.date_day,'lon':r.decimalLongitude,'lat':r.decimalLatitude,
                'taxa':'|'.join(sorted(set(s.scientificName.dropna().astype(str)))),'datasets':'|'.join(sorted(set(s.datasetName.fillna('UNSPECIFIED_IN_CACHE').astype(str)))),
                'records':len(s),'max_uncertainty_m':pd.to_numeric(s.coordinateUncertaintyInMeters,errors='coerce').max(),
                'occurrence_ids':'|'.join(s.occurrenceID.astype(str))})
        within=buildings[buildings.lon.between(bbox[0],bbox[2]) & buildings.lat.between(bbox[1],bbox[3])]
        for _,r in within.iterrows():assetrows.append({'site':key,'cluster':r.cluster,'lon':r.lon,'lat':r.lat,'buildings_within_200m_shore':r.n_buildings_200m,'nearest_place_unverified_archive_name':r.nearest_place})
        points=[]
        folder=OUT/'inputs'/key
        depth=json.loads((folder/'depth.json').read_text())
        for sample in depth['samples']:
            try:value=float(sample['value'])
            except (ValueError,TypeError):continue
            if not np.isfinite(value):continue
            x,y=sample['location']['x'],sample['location']['y'];p=Point(*TO_ITM(x,y))
            points.append(-value)
            depthrows.append({'site':key,'lon':x,'lat':y,'elevation_service_units':value,'nominal_depth_m':-value,
                              'inside_ssco_historical_laminaria':bgeom.covers(p),
                              'datum_verified_for_coastal_modelling':False})
        imagery=[]
        for day in DATES:
            with rasterio.open(folder/f'{day}_SCL.tif') as ds:
                scl=ds.read(1);mask=rasterize([(domain,1)],out_shape=scl.shape,transform=ds.transform,dtype='uint8').astype(bool)
            clouds=binary_dilation(np.isin(scl,[1,3,8,9,10,11]),iterations=2)
            clear=mask & np.isin(scl,[4,5,6]) & ~clouds
            q={'site':key,'date':day,'full_window_pixels':int(mask.sum()),'scl_valid_fraction':float(((scl!=0)&mask).sum()/mask.sum()),
               'clear_scl_456_with_40m_cloud_guard_fraction':float(clear.sum()/mask.sum()),
               'scl_classes':dict(Counter(scl[mask].tolist())),'not_underwater_visibility':True}
            imagerows.append(q);imagery.append(q['clear_scl_456_with_40m_cloud_guard_fraction'])
        ranked=sorted(wave_points,key=lambda v:anchor.distance(Point(*TO_ITM(v[0],v[1]))))
        seen=set();wave=None
        for lon,lat,path,iy,ix in ranked:
            if (lon,lat) in seen:continue
            seen.add((lon,lat))
            with xr.open_dataset(ROOT/path) as ds:
                h=ds.VHM0.isel(latitude=iy,longitude=ix).values
                if not np.isfinite(h).any():continue
                direction=ds.VMDR.isel(latitude=iy,longitude=ix).values
                good=np.isfinite(h)&np.isfinite(direction);h=h[good];direction=direction[good]
                theta=np.radians(direction);weights=h*h
                bearing=float(np.degrees(np.arctan2(np.sum(weights*np.sin(theta)),np.sum(weights*np.cos(theta))))%360)
                wave={'source_file':path,'lon':lon,'lat':lat,'distance_to_anchor_km':anchor.distance(Point(*TO_ITM(lon,lat)))/1000,
                      'hours':len(h),'first':str(ds.time.values[0]),'last':str(ds.time.values[-1]),
                      'hs_median_m':float(np.median(h)),'hs_p95_m':float(np.percentile(h,95)),
                      'hs2_weighted_from_deg':bearing,'travel_deg':(bearing+180)%360,
                      'nearshore_validation':False,'wave_period_in_cached_file':False}
                break
        r={'site':key,'name':site['name'],'bbox_wgs84':bbox,'window_area_km2':domain.area/1e6,
           'ssco_historical_laminaria_ha':bgeom.area/1e4,'article17_historical_laminaria_ha':ageom.area/1e4,
           'ssco_laminaria_vs_article17_faunal_ha':conflict.area/1e4,
           'references_independent':False,'current_kelp_presence_from_polygons':None,
           'cached_obis_records':len(oo),'cached_obis_events':oo.event_key.nunique(),
           'cached_obis_first':oo.date_day.min() if len(oo) else None,'cached_obis_last':oo.date_day.max() if len(oo) else None,
           'obis_cache_is_complete_for_this_site':False,
           'archive_building_clusters':len(within),'archive_building_counts_sum_not_deduplicated':int(within.n_buildings_200m.sum()),
           'assets_protected_by_kelp':None,'depth_requested':121,'finite_depth_samples':len(points),
           'nominal_wet_depth_samples':sum(v>0 for v in points),'nominal_4_to_10m_samples':sum(4<=v<=10 for v in points),
           'depth_median_positive_m':float(np.median([v for v in points if v>0])) if any(v>0 for v in points) else None,
           'two_date_clear_fractions':imagery,'satellite_species_validation':False,'nearest_cached_offshore_wave':wave}
        results.append(r);print('Analysed',key,'SSCO ha',round(bgeom.area/1e4,2),'events',r['cached_obis_events'],'clear',np.round(imagery,3),'wave km',round(wave['distance_to_anchor_km'],2) if wave else None,flush=True)
    pd.DataFrame(events).to_csv(OUT/'dated_kelp_events.csv',index=False)
    pd.DataFrame(xref).to_csv(OUT/'reference_crosswalk.csv',index=False)
    pd.DataFrame(assetrows).to_csv(OUT/'potential_coastal_building_clusters.csv',index=False)
    pd.DataFrame(depthrows).to_csv(OUT/'depth_coverage_samples.csv',index=False)
    save(OUT/'image_qa.json',imagerows)
    save(OUT/'site_comparison.json',results)
    pd.DataFrame([{k:v for k,v in r.items() if not isinstance(v,(list,dict))} for r in results]).to_csv(OUT/'site_comparison.csv',index=False)
    save(OUT/'site_windows.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':mapping(box(*s['bbox'])),'properties':{'site':k,'name':s['name'],'evidence':'COMPARISON_WINDOW_NOT_KELP_EXTENT'}} for k,s in SITES.items()]})
    assert before=={p:sha(ROOT/p) for p in before}
    save(OUT/'verification.json',{'original_files_checked':len(before),'original_files_unchanged':True,'new_model_training_runs':0,
         'application_and_presentations_rebuilt':False,'comparison_site_count':len(results),'shared_dates':DATES,
         'sparse_depth_probe_not_habitat_map':True,'source_independence_not_asserted':True})
    save(OUT/'input_hashes.json',before | {str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [Path(__file__),ARTICLE,SSCO,ROOT/'outputs/obis_raw_occurrences.json',ROOT/'outputs/national_candidate_table.csv']})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--acquire',action='store_true');p.add_argument('--analyse',action='store_true');args=p.parse_args()
    if args.acquire:acquire()
    if args.analyse:analyse()
