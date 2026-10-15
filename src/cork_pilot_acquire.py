"""Cache small public Sentinel-2 L2A subsets; never modify existing inputs.

Run from repository root: .venv/Scripts/python.exe src/cork_pilot_acquire.py
Network is needed only for acquisition. Analysis is entirely offline.
"""
from pathlib import Path
import json
import math
import sys
import xml.etree.ElementTree as ET
import concurrent.futures
import threading
import time
from urllib.parse import urlsplit, parse_qs
import requests
import numpy as np
import rasterio
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.transform import from_origin
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/cork_pilot_20261015'
CACHE = OUT / 'imagery'
BBOX = [-9.405, 51.460, -9.355, 51.495]
if '--context' in sys.argv:
    BBOX = [-9.42, 51.45, -9.355, 51.51]
    CACHE = OUT / 'imagery_context'
BANDS = ['B02', 'B03', 'B04', 'B08', 'B11', 'SCL']
SIGN_CACHE = {}
SIGN_LOCK = threading.Lock()


def signed(url):
    parts = urlsplit(url)
    key = (parts.netloc, parts.path.split('/')[1])
    with SIGN_LOCK:
        if key in SIGN_CACHE:
            return url+'?'+SIGN_CACHE[key]
        for attempt in range(4):
            account = parts.netloc.split('.')[0]
            r = requests.get(f'https://planetarycomputer.microsoft.com/api/sas/v1/token/{account}/{key[1]}', timeout=45)
            if r.status_code != 429:
                break
            time.sleep(min(15, 3*(attempt+1)))
        r.raise_for_status()
        SIGN_CACHE[key] = r.json()['token']
        return url+'?'+SIGN_CACHE[key]


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    scenes = json.loads((ROOT/'outputs/intertidal/report_sherkin_baltimore_7scenes.json').read_text())['scenes']
    xmin, ymin, xmax, ymax = transform_bounds(4326, 2157, *BBOX, densify_pts=21)
    xmin, ymin = math.floor(xmin/10)*10, math.floor(ymin/10)*10
    xmax, ymax = math.ceil(xmax/10)*10, math.ceil(ymax/10)*10
    width, height = int((xmax-xmin)/10), int((ymax-ymin)/10)
    dst_transform = from_origin(xmin, ymax, 10, 10)
    manifest = []
    for sc in scenes:
        day = sc['date']
        target = CACHE/f'{day}.tif'
        meta_path = CACHE/f'{day}.json'
        if target.exists() and meta_path.exists():
            manifest.append(json.loads(meta_path.read_text()))
            print(day, 'cached', flush=True)
            continue
        request = {'collections':['sentinel-2-l2a'], 'bbox':BBOX,
                   'datetime':f'{day}T00:00:00Z/{day}T23:59:59Z','limit':20}
        r = requests.post('https://planetarycomputer.microsoft.com/api/stac/v1/search', json=request, timeout=60)
        r.raise_for_status()
        # Use one tile consistently; the old report sometimes recorded an MS
        # tile ID although its implementation fell back to MT on the same date.
        candidates = [f for f in r.json()['features'] if '_T29UMT_' in f['id']]
        if not candidates:
            raise ValueError(f'No T29UMT product for {day}')
        item = sorted(candidates, key=lambda f:f['id'])[-1]
        r = requests.get(signed(item['assets']['product-metadata']['href']), timeout=60)
        r.raise_for_status()
        xml = ET.fromstring(r.content)
        offsets = {int(x.attrib['band_id']):float(x.text) for x in xml.iter() if x.tag.split('}')[-1]=='BOA_ADD_OFFSET'}
        quant = [float(x.text) for x in xml.iter() if x.tag.split('}')[-1]=='BOA_QUANTIFICATION_VALUE']
        if len(quant)!=1:
            raise ValueError('Missing or ambiguous quantification metadata')
        (CACHE/f'{day}_product.xml').write_bytes(r.content)
        band_ids = {'B02':1,'B03':2,'B04':3,'B08':7,'B11':11}
        scales = {b:{'scale':1/quant[0], 'offset_dn':offsets.get(band_ids[b],0)} for b in BANDS[:-1]}

        def read_band(band):
            href = item['assets'][band]['href']
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_TIMEOUT='60',
                              GDAL_HTTP_MAX_RETRY='2', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
                with rasterio.open(signed(href)) as ds:
                    native_bounds = transform_bounds(2157, ds.crs, xmin-40,ymin-40,xmax+40,ymax+40,densify_pts=21)
                    window = from_bounds(*native_bounds, transform=ds.transform).round_offsets().round_lengths()
                    source = ds.read(1, window=window, boundless=True, fill_value=0)
                    dest = np.zeros((height,width), dtype=np.uint16)
                    reproject(source, dest, src_transform=ds.window_transform(window), src_crs=ds.crs,
                              dst_transform=dst_transform,dst_crs='EPSG:2157',src_nodata=0,dst_nodata=0,
                              resampling=Resampling.nearest)
                    return band, dest, {'source_url':href,'source_crs':str(ds.crs),'native_resolution_m':list(ds.res),
                                        'native_scales':list(ds.scales),'native_offsets':list(ds.offsets)}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            bands = list(pool.map(read_band, BANDS))
        with rasterio.open(target,'w',driver='GTiff',width=width,height=height,count=len(BANDS),
                           dtype='uint16',crs='EPSG:2157',transform=dst_transform,nodata=0,
                           compress='deflate') as ds:
            for i,(b,a,_) in enumerate(bands,1):
                ds.write(a,i); ds.set_band_description(i,b)
            ds.update_tags(data_kind='Raw DN, apply offsets from matching JSON before reflectance arithmetic',
                           source_item=item['id'],resampling='nearest; B11 and SCL native 20m')
        meta = {'date':day,'tide_m_LAT':sc['tide'],'legacy_scene_id':sc['scene_id'],
                'actual_item_id':item['id'],'actual_datetime_utc':item['properties']['datetime'],
                'processing_baseline':item['properties'].get('s2:processing_baseline'),
                'bbox_wgs84':BBOX,'crs':'EPSG:2157','grid_m':10,'width':width,'height':height,
                'reflectance':scales,'bands':{b:m for b,_,m in bands},
                'level':'L2A, differs from original L1C/Cloud Score Plus processing',
                'query':request,'item':item}
        meta_path.write_text(json.dumps(meta,indent=2),encoding='utf-8')
        manifest.append(meta)
        print(day,item['id'],'offsets',scales,'bytes',target.stat().st_size,flush=True)
    (CACHE/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Acquisition complete',len(manifest),'scenes',flush=True)


if __name__=='__main__':
    main()
