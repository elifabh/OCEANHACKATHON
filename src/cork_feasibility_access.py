"""Bounded public-data feasibility acquisition. Does not change the application.

Run with the existing .venv Python. Each successful response is cached verbatim.
No credentials are read or printed. No requests to data owners are sent.
"""
from pathlib import Path
import argparse, json, hashlib, datetime, requests, re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/cork_feasibility_20261015'
RAW = OUT / 'inputs'
RAW.mkdir(parents=True, exist_ok=True)
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'CorkHabitatFeasibility/1.0 public-research'
SERVICE = 'https://image.marine.ie/arcgis/rest/services/INFOMAR/AllSurvey/ImageServer'
REPO = 'https://researchrepository.universityofgalway.ie'
ITEM = 'd7b94a47-ad7f-4566-951e-b8f544d63d83'

def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False,
        default=lambda x:x.item() if hasattr(x,'item') else str(x)), encoding='utf-8')

def get(name, url, params=None, data=None):
    dest = RAW / name
    if dest.exists():
        try: return json.loads(dest.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError): return dest.read_text(encoding='utf-8')
    r = SESSION.post(url, data=data, timeout=100) if data is not None else SESSION.get(url, params=params, timeout=60)
    save(RAW/(name+'.request.json'), {'url':url,'parameters':params,'post_data':data,
        'status':r.status_code,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'content_type':r.headers.get('Content-Type'), 'bytes':len(r.content)})
    r.raise_for_status()
    dest.write_bytes(r.content)
    try: return r.json()
    except ValueError: return r.text

def access():
    jobs = [
      ('repository_item.json', REPO+'/server/api/core/items/'+ITEM, None),
      ('repository_bundles.json', REPO+'/server/api/core/items/'+ITEM+'/bundles', None),
      ('infomar_service.json', SERVICE, {'f':'pjson'}),
      ('infomar_copper_catalog.json', SERVICE+'/query', {'f':'json','where':'1=1','outFields':'*',
        'geometry':'-9.545,51.495,-9.525,51.510','geometryType':'esriGeometryEnvelope','inSR':4326,
        'outSR':4326,'returnGeometry':'true','spatialRel':'esriSpatialRelIntersects'}),
      ('infomar_surveys_map.html','https://maps.marine.ie/infomarsurveysmap/',None),
    ]
    for name,url,params in jobs:
        try:
            d=get(name,url,params)
            print(name, 'keys='+str(list(d)[:10]) if isinstance(d,dict) else 'text bytes='+str(len(d)),flush=True)
        except Exception as e: print(name, type(e).__name__,str(e)[:180],flush=True)
    p=RAW/'repository_bundles.json'
    if p.exists():
        d=json.loads(p.read_text())
        for b in d.get('_embedded',{}).get('bundles',[]):
            print('BUNDLE',b.get('name'),b.get('uuid'),flush=True)
            url=b.get('_links',{}).get('bitstreams',{}).get('href')
            if url:
                try:
                    d=get('repository_bundle_'+b['name']+'.json',url)
                    for v in d.get('_embedded',{}).get('bitstreams',[]):
                        print('FILE',v.get('name'),v.get('sizeBytes'),v.get('uuid'),flush=True)
                except Exception as e:print(type(e).__name__,str(e)[:180],flush=True)

def osm():
    # One regional coast query closes island boundaries; three bounded asset queries.
    bounds={'coast':(-10.03,51.32,-9.30,51.82),
        'copper_point':(-9.60,51.475,-9.49,51.54),
        'cape_clear':(-9.54,51.415,-9.425,51.48),
        'bantry':(-9.74,51.62,-9.42,51.765)}
    for key,(w,s,e,n) in bounds.items():
        bb=f'{s},{w},{n},{e}'
        selectors=[f'way[natural=coastline]({bb});'] if key=='coast' else [
            f'nwr[building]({bb});',f'way[highway]({bb});',f'nwr[man_made~"^(pier|breakwater|groyne)$"]({bb});',
            f'nwr[leisure=marina]({bb});',f'nwr[harbour]({bb});',f'nwr[waterway=dock]({bb});',f'nwr["seamark:type"=harbour]({bb});']
        query='[out:json][timeout:85];('+''.join(selectors)+');out body geom;'
        try:
            d=get('osm_'+key+'.json','https://overpass-api.de/api/interpreter',data={'data':query})
            if d.get('remark'): raise RuntimeError(d['remark'])
            print(key,len(d.get('elements',[])),d.get('osm3s'),flush=True)
        except Exception as e:print(key,type(e).__name__,str(e)[:180],flush=True)

def waves():
    import copernicusmarine as cm
    import xarray as xr
    probe=RAW/'wave_grid_probe.nc'
    if not probe.exists():
        cm.subset(dataset_id='cmems_mod_ibi_wav_my_0.027deg_PT1H-i',
            minimum_longitude=-10.02,maximum_longitude=-9.3,minimum_latitude=51.32,maximum_latitude=51.80,
            start_datetime='2024-07-01T00:00:00',end_datetime='2024-07-01T00:00:00',
            output_filename=probe.name,output_directory=str(RAW),overwrite=False)
    with xr.open_dataset(probe) as ds:
        print('WAVE VARS',list(ds.data_vars),flush=True)
        print('Wet cells',int(ds.VHM0.notnull().sum()),flush=True)
        save(RAW/'wave_probe_metadata.json',{'variables':{k:dict(v.attrs) for k,v in ds.data_vars.items()},'attrs':dict(ds.attrs)})
        wet=ds[['VHM0','VMDR']].to_dataframe().dropna().reset_index()
        anchors={'copper_point':(-9.5347777778,51.5018888889),
            'cape_clear':(-9.486,51.445),'bantry':(-9.698616,51.67628)}
        selections={}
        for key,(lon,lat) in anchors.items():
            distance=(wet.longitude-lon)**2*.6225**2+(wet.latitude-lat)**2
            r=wet.loc[distance.idxmin()]; selections[key]={'lon':float(r.longitude),'lat':float(r.latitude),
                'selection':'Nearest finite grid cell to published survey anchor (Cape: fixed island centre)',
                'anchor':[lon,lat],'is_nearshore_observation':False}
    save(RAW/'wave_cells.json',selections)
    for key,r in selections.items():
        dest=RAW/('waves_'+key+'.nc')
        if not dest.exists():
            args=dict(dataset_id='cmems_mod_ibi_wav_my_0.027deg_PT1H-i',dataset_version='202511',
                variables=['VHM0','VMDR','VTM10'],minimum_longitude=r['lon'],maximum_longitude=r['lon'],
                minimum_latitude=r['lat'],maximum_latitude=r['lat'],start_datetime='2015-01-01T00:00:00',
                end_datetime='2024-12-31T23:00:00',output_filename=dest.name,output_directory=str(RAW),
                overwrite=False,netcdf3_compatible=True)
            save(RAW/('waves_'+key+'.request.json'),args)
            cm.subset(**args)
        print(key,r,'downloaded',dest.stat().st_size,flush=True)

def portal():
    d=get('infomar_portal.json','https://www.arcgis.com/sharing/rest/content/items/3f2815ec89e745d2b65630429d06385c/data',{'f':'json'})
    def walk(v):
        if isinstance(v,dict):
            if v.get('url'): print('URL',str(v['url'])[:250])
            if v.get('itemId'):print('ITEM',v['itemId'])
            for t in v.values():walk(t)
        elif isinstance(v,list):
            for t in v:walk(t)
    walk(d)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['access','osm','waves','portal']);a=p.parse_args()
    globals()[a.mode]()
