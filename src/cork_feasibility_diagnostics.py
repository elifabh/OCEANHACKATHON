"""Final terrain, boundary-source and accessibility diagnostics. Offline.

Retains every candidate; terrain thresholds are displayed sensitivities, not a
mask on habitat or proof of inundation. No coastal benefit is calculated.
"""
import json, math, zipfile
import numpy as np
import rasterio
from rasterio.windows import Window
from pyproj import Transformer
from shapely.geometry import Point,LineString
from shapely.ops import nearest_points
from cork_feasibility import OUT,RAW,SITES,read,save,clean,assets,coast,TO_ITM,TO_WGS,ROOT,REVIEW

def terrain():
    land,c,domain,unknown,info=coast();summary=[];records=[]
    for key in SITES:
        aa,_=assets(key);ad={a['id']:a for a in aa};wave=read(OUT/'directional_waves.json')[key]
        cell=Point(*TO_ITM(*wave['grid_point']));byasset={};rows=[]
        with rasterio.open(RAW/f'terrain_{key}.tif') as r:
            for path in read(OUT/(key+'_paths.json')):
                if not path['open_upwave_5km']:continue
                shore=Point(*TO_ITM(*path['shore_lonlat']));origin=Point(*TO_ITM(*path['origin_lonlat']))
                sourcepath=LineString([cell,origin]);between=LineString([sourcepath.interpolate(min(2,sourcepath.length/4)),sourcepath.interpolate(max(sourcepath.length-2,sourcepath.length/2))])
                for assetid in path['assets']:
                    a=ad[assetid];target=nearest_points(shore,a['geometry'])[1];lon,lat=TO_WGS(target.x,target.y)
                    y,x=r.index(lon,lat);vals=r.read(1,window=Window(x-1,y-1,3,3),boundless=True,masked=True)
                    z=r.read(1,window=Window(x,y,1,1),boundless=True,masked=True)
                    d={'site':key,'origin_id':path['origin_id'],'from_deg':path['from_deg'],'osm_id':assetid,
                        'kind':a['kind'],'highway':a['highway'],'name':a['name'],'target_lonlat':[lon,lat],
                        'target_DSM_m':float(z[0,0]) if z.count() else None,'neighbourhood_DSM_min_m':float(vals.min()) if vals.count() else None,
                        'neighbourhood_DSM_max_m':float(vals.max()) if vals.count() else None,
                        'flux_proxy_fraction':path['flux_proxy_fraction'],
                        'grid_to_habitat_distance_m':cell.distance(origin),
                        'grid_to_habitat_straight_connection_crosses_coast':between.intersects(c),
                        'building_floor_level_known':False,'is_protected_asset':False}
                    rows.append(d)
                    byasset.setdefault(assetid,[]).append(d)
        for k,rr in byasset.items():
            types=[v['target_DSM_m'] for v in rr if v['target_DSM_m'] is not None]
            if not types:continue
        diagnostic={'site':key,'geometric_candidate_objects':len(byasset),
            'objects_with_any_target_DSM_at_most_5m':sum(any(v['target_DSM_m'] is not None and v['target_DSM_m']<=5 for v in rr) for rr in byasset.values()),
            'objects_with_any_target_DSM_at_most_10m':sum(any(v['target_DSM_m'] is not None and v['target_DSM_m']<=10 for v in rr) for rr in byasset.values()),
            'thresholds_are_sensitivity_not_inundation_levels':True,
            'direction_bins_with_low_DSM_road_or_building':sorted(set(v['from_deg'] for v in rows if v['target_DSM_m'] is not None and v['target_DSM_m']<=10 and (v['kind']=='building' or (v['kind']=='road_path' and v['highway'] not in ['path','footway','track'])))),
            'coarse_wave_to_origin_blocked_records':sum(v['grid_to_habitat_straight_connection_crosses_coast'] for v in rows),
            'coarse_wave_to_origin_records':len(rows)}
        diagnostic['low_DSM_road_building_direction_union_flux_proxy']=sum(s['flux_proxy_fraction'] for s in wave['sectors'] if s['from_deg'] in diagnostic['direction_bins_with_low_DSM_road_or_building'])
        records.extend(rows);summary.append(diagnostic)
    save(OUT/'terrain_and_boundary_diagnostics.json',clean({'summary':summary,'records':records,
        'limitations':['DSM includes roofs and vegetation; 30 m pixels do not measure floor level, slope stability or cliff toe.',
            'EGM2008 terrain and LAT bathymetry are not combined into a flood surface.',
            'A straight grid-to-habitat line is a diagnostic; coastal wave propagation requires refraction, diffraction, depth breaking and local wind.',
            'Low terrain is neither proof of inundation nor evidence of kelp protection.']}))
    print(json.dumps(clean(summary),indent=2))

def archive():
    p=RAW/'LIR19_03_bathymetry.zip';inspection=[];locs=read(OUT/'sample_locations.json')
    with zipfile.ZipFile(p) as z:
        for name in z.namelist():
            if not name.endswith('.tif'):continue
            with rasterio.open('/vsizip/'+str(p.resolve()).replace('\\','/')+'/'+name) as r:
                transform=Transformer.from_crs(4326,r.crs,always_xy=True).transform
                x,y=transform(*SITES['copper_point']['anchor']);v=next(r.sample([(x,y)],masked=True))
                row={'member':name,'crs':str(r.crs),'resolution_m':list(r.res),'nodata':r.nodata,
                    'copper_anchor_elevation_LAT_m':None if v.mask[0] else float(v[0]),'sample_values':[]}
                if 'WestCork' in name:
                    for pt in locs:
                        if pt['site']!='copper_point' and pt['id'] not in [1351,1354,1569,1609,1718]:continue
                        v=next(r.sample([transform(pt['lon'],pt['lat'])],masked=True))
                        row['sample_values'].append({'site':pt['site'],'sample_id':pt['id'],'depth_LAT_m':None if v.mask[0] else -float(v[0])})
                inspection.append(row)
    save(OUT/'actual_lir19_03_grid_test.json',clean(inspection))
    print('Actual downloaded LIR19_03 grid read successfully')

def availability():
    bundles=[]
    for p in RAW.glob('repository_bundle_*.json'):
        if p.name.endswith('request.json'):continue
        for b in read(p).get('_embedded',{}).get('bitstreams',[]):
            bundles.append({'bundle':p.stem.removeprefix('repository_bundle_'),'name':b['name'],'sizeBytes':b['sizeBytes'],'uuid':b['uuid']})
    legs=[f['attributes'] for f in read(RAW/'portal_copper_survey_legs.json')['features']]
    summary={'decision':'NO_GO_FOR_2019_COPPER_POINT_RAW_SONAR_REPROCESSING_NOW',
        'scope':'Public repository file inventory and current official INFOMAR portal/catalogue, checked in this bounded pass; not proof files do not exist privately.',
        'repository_files':bundles,'thesis_license':'CC BY-NC-ND 3.0 Ireland; not a licence for absent raw data',
        'survey_legs_intersecting_copper_search_box':[{'id':a['SURVEY_ID'],'vessel':a['VESSELNAME'],'year':a['SURVEYYEAR'],'download_status':a['DATASTATUS']} for a in legs],
        'items':[
            {'item':'2019 experiment water-column acoustic raw files (QINSY/Qimera)','usable_now':False,'reason':'No raw files in repository; official portal offers processed bathymetry/backscatter, not verified experiment WCD.'},
            {'item':'Experiment matched GNSS/INS/navigation/SVP/tide files','usable_now':False,'reason':'2019 Lir report describes POS MV processing, but no corresponding downloadable raw navigation bundle identified.'},
            {'item':'Exact experiment transects/footprint','usable_now':False,'reason':'Thesis figure and coordinate only; official survey-leg polygons cover broader operations and cannot replace experiment extent.'},
            {'item':'17 matched Copper Point drop-camera videos and annotations','usable_now':False,'reason':'No video/annotation file in thesis repository or portal. No lasers; video cannot independently validate canopy dimensions.'},
            {'item':'LIR19_03 bathymetry ZIP','usable_now':True,'downloaded':True,'bytes':(RAW/'LIR19_03_bathymetry.zip').stat().st_size,'licence':'INFOMAR CC BY 4.0','purpose':'Seabed geometry only; not a kelp canopy measurement.'},
            {'item':'LIR19_02 and LIR19_03 backscatter ZIPs','usable_now':True,'downloaded':False,'reason':'HTTP 200 stream access checked; large processed seabed-intensity products, not verified water-column data.'},
            {'item':'Official general survey coverage polygons','usable_now':True,'downloaded':True,'purpose':'Survey context, not experiment footprint or navigation time series.'},
            {'item':'General survey trackline download','usable_now':'LINK_IDENTIFIED_NOT_DOWNLOADED','reason':'Public vector-download catalogue identifies trackline archive; cannot establish matching experimental navigation.'}],
        'misidentification_warning':'The Lir reports list Water Column .svp/.txt: these are sound-velocity profiles, not proof of acoustic canopy water-column recordings.',
        'stop_rule':'Do not wait for data owners or fieldwork; keep Copper Point as dated methodological evidence, not the main integrated prototype dependency.',
        'no_email_or_data_request_sent':True}
    save(OUT/'copper_point_data_availability.json',summary)

def regional_cape():
    """Nearest sea-connected model cell per origin, chosen without using euros or waves."""
    import xarray as xr
    land,c,domain,unknown,info=coast();allclimate=[]
    files=[RAW/'waves_cape_clear_regional.nc']
    if (RAW/'waves_cape_clear_south_boundary.nc').exists():files.append(RAW/'waves_cape_clear_south_boundary.nc')
    datasets=[xr.open_dataset(p) for p in files]
    with xr.combine_by_coords(datasets,combine_attrs='override') as ds:
        for iy,lat in enumerate(ds.latitude.values):
            for ix,lon in enumerate(ds.longitude.values):
                v=ds[['VHM0','VMDR','VTM10']].isel(latitude=iy,longitude=ix).to_dataframe().dropna()
                if v.empty:continue
                cp=Point(*TO_ITM(float(lon),float(lat)))
                if land.covers(cp):continue
                b=((v.VMDR.to_numpy()+5)%360//10).astype(int);flux=(v.VHM0**2*v.VTM10).to_numpy()
                allclimate.append({'grid_point':[float(lon),float(lat)],'hours':len(v),'flux_proxy_by_from_deg':{
                    str(i*10):float(flux[b==i].sum()/flux.sum()) for i in range(36)}})
    paths=read(OUT/'cape_clear_paths.json');origins={p['origin_id']:p['origin_lonlat'] for p in paths};assign={}
    for oid,xy in origins.items():
        p=Point(*TO_ITM(*xy));eligible=[]
        for i,cl in enumerate(allclimate):
            q=Point(*TO_ITM(*cl['grid_point']));line=LineString([p,q])
            if line.intersects(c) or line.intersection(land).length>1:continue
            eligible.append((line.length,i))
        if eligible:
            distance,i=min(eligible);assign[str(oid)]={'grid_index':i,'distance_m':distance,'grid_point':allclimate[i]['grid_point']}
    terrainrows=read(OUT/'terrain_and_boundary_diagnostics.json')['records'];groups={};records=[]
    for r in terrainrows:
        if r['site']!='cape_clear':continue
        a=assign.get(str(r['origin_id']))
        if not a:continue
        weight=allclimate[a['grid_index']]['flux_proxy_by_from_deg'][str(r['from_deg'])]
        rec={**r,'assigned_wave_cell':a,'local_flux_proxy_fraction':weight};records.append(rec)
        g=groups.setdefault(str(r['origin_id']),{'origin_lonlat':origins[r['origin_id']],**a,'directions':set(),'objects':set(),
            'low_DSM_road_building_directions':set(),'low_DSM_road_building_objects':set()})
        g['directions'].add(r['from_deg']);g['objects'].add(r['osm_id'])
        if r['target_DSM_m'] is not None and r['target_DSM_m']<=10 and (r['kind']=='building' or r['highway'] not in ['path','footway','track']):
            g['low_DSM_road_building_directions'].add(r['from_deg']);g['low_DSM_road_building_objects'].add(r['osm_id'])
    for k,g in groups.items():
        for t in ['directions','objects','low_DSM_road_building_directions','low_DSM_road_building_objects']:g[t]=sorted(g[t])
        g['low_DSM_road_building_direction_weight']=sum(allclimate[g['grid_index']]['flux_proxy_by_from_deg'][str(i)] for i in g['low_DSM_road_building_directions'])
    result={'grid_cells':allclimate,'origin_assignments':assign,'origin_summaries':groups,'records':records,
        'method':'Nearest finite 2015-2024 cell connected by a sea-only straight segment; no cross-island transfer. Same 36 sectors and 5 km upwave test.',
        'not_a_nearshore_wave_model':True,'warning':'Compare weights within one origin only. Never sum weights from different cells or treat them as energy interception or damage reduction.'}
    save(OUT/'cape_clear_regional_wave_diagnostic.json',clean(result))
    print('Regional Cape cells',len(allclimate),'assigned origins',len(assign))
    for k in ['1351','1354','1569','1609','1718']:
        print(k,clean(groups.get(k)))

if __name__=='__main__':
    terrain();archive();availability()
    if (RAW/'waves_cape_clear_regional.nc').exists():regional_cape()
