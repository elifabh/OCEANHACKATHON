"""Three-site feasibility test; offline replay after --prepare / --depth.

Historical habitat is never renamed observed current kelp. Straight-ray
connectivity and a laboratory attenuation sensitivity are not shoreline hazard.
No classifier fitting, changes to held-out data, application, slides or video.
"""
from pathlib import Path
import argparse, json, math, hashlib
from collections import Counter
import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import Point, LineString, Polygon, box, shape
from shapely.ops import unary_union, transform, polygonize, nearest_points
from shapely.strtree import STRtree
from evidence_pipeline import ROOT, NPWS, TO_ITM, TO_WGS, clean, feature, fc, sha
from coastal_physics import direction_vector, effect, damping, ray_effect
from coastal_cost_calculator import unit_rates
from cork_feasibility_access import OUT, RAW, save, get, SERVICE

REVIEW = ROOT/'outputs/cork_multisite_review_20261015'
SITES = {
 'copper_point':{'bbox':[-9.55,51.49,-9.52,51.515], 'anchor':[-9.5347777778,51.5018888889]},
 'cape_clear':{'bbox':[-9.53,51.425,-9.44,51.465], 'anchor':[-9.486,51.445]},
 'bantry':{'bbox':[-9.74,51.62,-9.42,51.765], 'anchor':[-9.698616,51.67628]},
}

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def coast():
    raw=read(RAW/'osm_coast.json');domain=transform(TO_ITM,box(-10.03,51.32,-9.30,51.82))
    lines=[];votes=[]
    for e in raw['elements']:
        if e.get('tags',{}).get('natural')!='coastline':continue
        ln=transform(TO_ITM,LineString([(g['lon'],g['lat']) for g in e['geometry']]))
        lines.append(ln)
        for a,b in zip(list(ln.coords)[:-1],list(ln.coords)[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1];l=math.hypot(dx,dy)
            if l<1:continue
            x,y=(a[0]+b[0])/2,(a[1]+b[1])/2
            # Small local offset avoids jumping across narrow mapped rocks.
            votes.append((Point(x-.05*dy/l,y+.05*dx/l),Point(x+.05*dy/l,y-.05*dx/l)))
    boundary=unary_union(lines).intersection(domain)
    faces=list(polygonize(unary_union([boundary,domain.boundary])))
    land=[];unknown=[]
    # Spatial indexes avoid testing every vertex against every small island.
    lefttree=STRtree([v[0] for v in votes]);righttree=STRtree([v[1] for v in votes])
    for p in faces:
        left=sum(not p.covers(votes[int(i)][1]) for i in lefttree.query(p,predicate='contains'))
        right=sum(not p.covers(votes[int(i)][0]) for i in righttree.query(p,predicate='contains'))
        if left and not right:land.append(p)
        elif left and right:unknown.append(p)
    return unary_union(land),boundary,domain,unary_union(unknown),{
        'ways':len(lines),'faces':len(faces),'unresolved_faces':len(unknown),'timestamp':raw['osm3s']['timestamp_osm_base']}

def prepare():
    ref=gpd.read_file(NPWS).to_crs(2157)
    kelp=unary_union(ref[ref.Commun_Typ.str.contains('Laminaria',case=False,na=False)].geometry)
    hist=[];points=[]
    for key,s in SITES.items():
        if key=='bantry':continue
        h=kelp.intersection(transform(TO_ITM,box(*s['bbox'])))
        if key=='copper_point':h=h.intersection(Point(*TO_ITM(*s['anchor'])).buffer(750))
        hist.append(feature(h,{'site':key,'evidence':'NPWS_SSCO_HISTORICAL_REFERENCE',
            'not_current_ground_truth':True,'not_2019_sonar_footprint':True}))
        x0,y0,x1,y1=h.bounds
        # Fixed ITM-origin 50 m lattice: not optimised for the result.
        for x in np.arange(math.floor(x0/50)*50+25,x1,50):
            for y in np.arange(math.floor(y0/50)*50+25,y1,50):
                p=Point(x,y)
                if h.covers(p):
                    lon,lat=TO_WGS(x,y)
                    points.append({'site':key,'id':len(points),'x':float(x),'y':float(y),'lon':lon,'lat':lat})
    save(OUT/'historical_footprints.geojson',fc(hist));save(OUT/'sample_locations.json',points)
    obs=read(REVIEW/'equal_region_occurrence_records.json')
    # Explicitly retain the rejected on-land point and its flags in evidence.
    bantry=[r for r in obs if r['site']=='bantry' and r['scientificName']=='Laminaria hyperborea']
    save(OUT/'bantry_subtidal_observations.json',bantry)
    save(OUT/'protocol.json',{'sites':SITES,'new_training_runs':0,'target_of_previous_classifier':'INTERTIDAL_MACROALGAE',
        'subtidal_layer_status':'Historical references and conditional scenarios only',
        'point_lattice_m':50,'point_depth_eligibility_m':[4,10], 'wave_period':'2015-01-01 through 2024-12-31 inclusive',
        'direction_bin_width_degrees':10,'upwave_lengths_m':[2000,5000],'downwave_search_m':2000,
        'shore_asset_distance_m':100,'asset_point_setback_test_m':100,
        'selection_order':['usable spatial habitat evidence','unblocked directional habitat-shore-asset chain','data completeness'],
        'euros_used_in_selection':False,'posthoc_land_mask_on_classifier':False,
        'geometry_land_rejection':'Explicit physics-domain rejection, reported rather than hidden; no map classifier is changed.',
        'important':'NPWS cells are sampling hypotheses, not current kelp boundaries. Point depths do not establish whole-cell depth.'})
    print('Prepared',Counter(p['site'] for p in points),flush=True)

def depth():
    pts=read(OUT/'sample_locations.json')
    for start in range(0,len(pts),300):
        subset=pts[start:start+300]
        q={'f':'json','geometryType':'esriGeometryMultipoint',
           'geometry':json.dumps({'points':[[p['lon'],p['lat']] for p in subset],'spatialReference':{'wkid':4326}}),
           'returnFirstValueOnly':'true','interpolation':'RSP_NearestNeighbor'}
        d=get(f'depth_{start:05d}.json',SERVICE+'/getSamples',data=q)
        assert 'samples' in d,str(d)[:200]
        print('Depth batch',start,len(d['samples']),flush=True)
    obs=read(OUT/'bantry_subtidal_observations.json')
    q={'f':'json','geometryType':'esriGeometryMultipoint','geometry':json.dumps({'points':[[p['decimalLongitude'],p['decimalLatitude']] for p in obs],
        'spatialReference':{'wkid':4326}}),'returnFirstValueOnly':'true','interpolation':'RSP_NearestNeighbor'}
    get('depth_bantry_observations.json',SERVICE+'/getSamples',data=q)

def wave(key):
    with xr.open_dataset(RAW/f'waves_{key}.nc') as ds:
        assert ds.VMDR.attrs['standard_name']=='sea_surface_wave_from_direction'
        assert ds.VHM0.attrs['units']=='m' and ds.VTM10.attrs['units']=='s'
        frame=ds[['VHM0','VMDR','VTM10']].to_dataframe().dropna().reset_index()
        h=frame.VHM0.to_numpy();direction=frame.VMDR.to_numpy();period=frame.VTM10.to_numpy()
        bins=((direction+5)%360//10).astype(int)
        flux_proxy=h*h*period
        result={'grid_point':[float(ds.longitude.values[0]),float(ds.latitude.values[0])],
            'hours':len(frame),'expected_hours':87672,'first':str(frame.time.min()),'last':str(frame.time.max()),
            'height_p50_m':float(np.median(h)),'height_p95_m':float(np.percentile(h,95)),
            'energy_period_median_s':float(np.median(period)),
            'weight':'Hs squared times Tm-1,0; deep-water energy-flux proxy, not nearshore power or delivered energy',
            'direction':'VMDR FROM degrees; travel = FROM + 180', 'sectors':[]}
        for i in range(36):
            sel=bins==i
            result['sectors'].append({'from_deg':i*10,'travel_deg':(i*10+180)%360,'hours':int(sel.sum()),
                'frequency_fraction':float(sel.mean()),'flux_proxy_fraction':float(flux_proxy[sel].sum()/flux_proxy.sum())})
        return result

def assets(key):
    raw=read(RAW/f'osm_{key}.json');rows=[];skipped=Counter()
    for e in raw['elements']:
        t=e.get('tags',{});kind=None
        if t.get('building') and t['building']!='no':kind='building'
        elif t.get('highway'):kind='road_path'
        elif t.get('man_made') in ['pier','breakwater','groyne']:kind='pier_breakwater'
        elif t.get('harbour') or t.get('leisure')=='marina' or t.get('waterway')=='dock' or t.get('seamark:type')=='harbour':kind='harbour_marina'
        if not kind:continue
        g=e.get('geometry',[])
        if e['type']=='node':geom=Point(e['lon'],e['lat'])
        elif len(g)>=2:
            xy=[(v['lon'],v['lat']) for v in g]
            geom=Polygon(xy) if kind=='building' and len(xy)>=4 and xy[0]==xy[-1] else LineString(xy)
        else:
            # Do not invent polygon geometry from a relation centre.
            skipped[e['type']]+=1;continue
        geom=transform(TO_ITM,geom)
        if not geom.is_valid:geom=geom.buffer(0)
        if geom.is_empty:continue
        rows.append({'id':e['type']+'/'+str(e['id']),'kind':kind,'name':t.get('name',''),
            'highway':t.get('highway'),'geometry':geom})
    return rows,{'timestamp':raw['osm3s']['timestamp_osm_base'],'mapped_objects':len(rows),
        'by_kind':dict(Counter(r['kind'] for r in rows)),'unsupported_relation_geometries':dict(skipped)}

def analyse():
    land,boundary,domain,unknown,coastinfo=coast();print('COAST',coastinfo,flush=True)
    save(OUT/'coastline.geojson',fc([feature(boundary,{'kind':'coastline'}),feature(land,{'kind':'land'}),
        feature(unknown,{'kind':'unresolved_faces'})]));save(OUT/'coastline_quality.json',coastinfo)
    historical={f['properties']['site']:transform(TO_ITM,shape(f['geometry'])) for f in read(OUT/'historical_footprints.geojson')['features']}
    locations=read(OUT/'sample_locations.json');depthlookup={}
    for p in sorted(RAW.glob('depth_0*.json')):
        if p.name.endswith('request.json'):continue
        for v in read(p)['samples']:
            xy=TO_ITM(v['location']['x'],v['location']['y'])
            try:d=-float(v['value'])
            except (ValueError,TypeError):continue
            if math.isfinite(d):depthlookup[(round(xy[0]),round(xy[1]))]=d
    totals=[];allpaths=[];allcells=[];allwave={};allassets=[]
    for key,s in SITES.items():
        print('Analysing',key,flush=True)
        w=wave(key);allwave[key]=w
        ar,ainfo=assets(key);tree=STRtree([r['geometry'] for r in ar]);origins=[];counts=Counter()
        for p in locations:
            if p['site']!=key:continue
            counts['requested_depth_points']+=1;d=depthlookup.get((round(p['x']),round(p['y'])))
            if d is None:continue
            counts['finite_depth_points']+=1
            if not 4<=d<=10:continue
            counts['depth_eligible_points']+=1
            point=Point(p['x'],p['y'])
            if land.covers(point) or point.distance(boundary)<2 or unknown.intersects(point):
                counts['rejected_land_or_unresolved_points']+=1;continue
            cell=point.buffer(25,cap_style='square').intersection(historical[key])
            origins.append({'id':p['id'],'point':point,'depth':d,'cell':cell,'evidence':'historical_polygon_sample'})
            allcells.append(feature(cell,{'site':key,'sample_id':p['id'],'point_depth_m':d,'status':'HISTORICAL_SAMPLING_HYPOTHESIS'}))
        if key=='bantry':
            for i,r in enumerate(read(OUT/'bantry_subtidal_observations.json')):
                point=Point(*TO_ITM(r['decimalLongitude'],r['decimalLatitude']))
                if 'ON_LAND' in r['flags'] or land.covers(point) or unknown.intersects(point):
                    counts['rejected_flagged_or_land_observations']+=1;continue
                origins.append({'id':'obis_'+str(i),'point':point,'depth':None,'cell':None,'evidence':'dated_point_no_extent'})
        counts['tested_origins']=len(origins);paths=[];sectorresults=[];assetids=set();strictassets=set()
        localcoast=boundary.intersection(transform(TO_ITM,box(*s['bbox'])).buffer(3500))
        for sector in w['sectors']:
            u=direction_vector(sector['travel_deg']);sr={'from_deg':sector['from_deg'],'hours':sector['hours'],
                'flux_proxy_fraction':sector['flux_proxy_fraction'],'incoming_blocked_2km':0,'incoming_blocked_5km':0,
                'shore_hit_2km':0,'asset_chains_2km':0,'asset_chains_5km':0}
            for o in origins:
                p=o['point'];xy=np.array([p.x,p.y])
                up2=LineString([xy-2000*u,xy-2*u]);up5=LineString([xy-5000*u,xy-2*u])
                bad2=up2.intersects(boundary) or up2.intersection(land).length>1 or up2.intersects(unknown) or not domain.covers(up2)
                bad5=up5.intersects(boundary) or up5.intersection(land).length>1 or up5.intersects(unknown) or not domain.covers(up5)
                sr['incoming_blocked_2km']+=int(bad2);sr['incoming_blocked_5km']+=int(bad5)
                if bad2:continue
                down=LineString([xy+2*u,xy+2000*u]);hits=down.intersection(localcoast)
                if hits.is_empty:continue
                shore=nearest_points(p,hits)[1];path=LineString([p,shore])
                inner=LineString([p,path.interpolate(max(0,path.length-2))])
                if inner.intersection(land).length>1 or inner.intersects(unknown):continue
                sr['shore_hit_2km']+=1
                indices=tree.query(shore.buffer(100),predicate='intersects');valid=[]
                for index in indices:
                    a=ar[int(index)];target=nearest_points(shore,a['geometry'])[1]
                    # A nearby object across another inlet is not behind this shore.
                    last=LineString([shore,target])
                    if last.length>4:
                        mid=LineString([last.interpolate(2),last.interpolate(last.length-2)])
                        if mid.intersects(boundary):continue
                    valid.append(a)
                if not valid:continue
                sr['asset_chains_2km']+=1
                if not bad5:sr['asset_chains_5km']+=1
                ids=[a['id'] for a in valid];assetids.update(ids)
                if not bad5:strictassets.update(ids)
                props={'site':key,'origin_id':o['id'],'from_deg':sector['from_deg'],
                    'flux_proxy_fraction':sector['flux_proxy_fraction'],'water_path_to_shore_m':path.length,
                    'open_upwave_5km':not bad5,'assets':ids,'asset_kinds':sorted(set(a['kind'] for a in valid)),
                    'shore_lonlat':list(TO_WGS(shore.x,shore.y)),'origin_lonlat':list(TO_WGS(p.x,p.y)),
                    'status':'DIRECTIONALLY_PLAUSIBLE_UNVALIDATED','avoided_damage_eur':None,
                    'point_depth_m':o['depth'],'habitat_evidence':o['evidence']}
                # An isolated sampling-square chord is a sensitivity, not full-bed attenuation.
                if o['cell'] is not None:
                    chord=LineString([xy-100*u,xy+100*u]).intersection(o['cell']).length
                    props['sampling_cell_chord_m']=chord
                    props['conditional_cell_height_fraction']=effect(chord*damping(o['depth']))['height_fraction']
                    props['water_level_plus_2m_height_fraction']=effect(chord*damping(o['depth']+2))['height_fraction'] if o['depth']+2<=10 else None
                paths.append(props);allpaths.append(feature(path,props))
            sectorresults.append(sr)
        counts.update({'asset_chain_rays_2km':len(paths),'asset_chain_rays_5km':sum(p['open_upwave_5km'] for p in paths),
            'candidate_osm_objects_2km':len(assetids),'candidate_osm_objects_5km':len(strictassets)})
        linked=[a for a in ar if a['id'] in assetids]
        strict=[a for a in ar if a['id'] in strictassets]
        for a in ar:
            allassets.append(feature(a['geometry'],{'site':key,'osm_id':a['id'],'kind':a['kind'],'name':a['name'],
                'candidate_2km':a['id'] in assetids,'candidate_5km':a['id'] in strictassets,'not_verified_protected':True}))
        result={'site':key,'sample_counts':dict(counts),'assets':ainfo,
            'candidate_objects_2km_by_kind':dict(Counter(a['kind'] for a in linked)),
            'candidate_objects_5km_by_kind':dict(Counter(a['kind'] for a in strict)),
            'sectors':sectorresults,'historic_polygon_area_ha':historical[key].area/10000 if key in historical else None,
            'wave':{k:v for k,v in w.items() if k!='sectors'},
            'sector_union_flux_proxy_fraction_2km':sum(r['flux_proxy_fraction'] for r in sectorresults if r['asset_chains_2km']),
            'sector_union_flux_proxy_fraction_5km':sum(r['flux_proxy_fraction'] for r in sectorresults if r['asset_chains_5km']),
            'union_fraction_warning':'Fraction of offshore directional bins with ANY possible chain, not fraction of energy intercepted or attenuation.',
            'current_kelp_validated':False,'shoreline_hazard_model_run':False,'avoided_damage_eur':None}
        save(OUT/(key+'_paths.json'),clean(paths));totals.append(result)
        print(key,dict(counts),'strict kinds',result['candidate_objects_5km_by_kind'],flush=True)
    save(OUT/'comparison.json',clean(totals));save(OUT/'directional_waves.json',clean(allwave))
    save(OUT/'candidate_paths.geojson',fc(allpaths));save(OUT/'sample_cells.geojson',fc(allcells));save(OUT/'assets.geojson',fc(allassets))
    # Same scenarios for all sites: selection cannot be biased by a large euro result.
    rates=unit_rates();sensitivity=[]
    for d in [4,6,8,10]:
        for length in [20,50,100]:
            sensitivity.append({'assumed_depth_m':d,'assumed_kelp_path_m':length,**effect(length*damping(d))})
    save(OUT/'conditional_physics_and_euros.json',clean({'lab_sensitivity':sensitivity,
        'physics_basis':'Existing Dubi & Torum 1996 laboratory damping coefficients: assumed 2 m plants, 12 plants/m2; no local density/biomass fit.',
        'cost_rates':rates,'scenario_frontage_m':100,
        'gross_hard_defence_benchmark_eur':[100*rates[k] for k in ['low','project_pooled','high']],
        'engineering_budget_share_scenarios':[{'assumed_share':s,'conditional_budget_eur':[100*rates[k]*s for k in ['low','project_pooled','high']]} for s in [0,.25,.5,1]],
        'cost_warning':'Wexford approved funding benchmarks, nominal mixed 2024/2026 prices; illustrative 100 m, not measured protected frontage, savings, kelp value, or a quote.',
        'share_is_independent_of_wave_reduction':True,'avoided_damage_eur_per_year':None,'kelp_service_value_eur':None,
        'missing_for_benefit':['validated with/without-habitat receptor hazard','event probabilities','exposure values','damage functions','restoration and maintenance costs']}))

def verify():
    original=read(ROOT/'outputs/cork_pilot_20261015/preserved_originals.json')
    frozen=read(ROOT/'outputs/cork_pilot_correction_20261015/protected_inputs.json')
    changed=[p for p,h in (original|frozen).items() if sha(ROOT/p)!=h]
    assert not changed,changed
    used=[ROOT/'src/cork_feasibility.py',ROOT/'src/cork_feasibility_access.py',ROOT/'src/coastal_physics.py',ROOT/'src/coastal_cost_calculator.py',
        ROOT/'src/evidence_pipeline.py',REVIEW/'equal_region_occurrence_records.json',*RAW.glob('*')]
    used.extend(NPWS.parent.glob(NPWS.stem+'.*'))
    save(OUT/'input_hashes.json',{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in used if p.is_file()})
    save(OUT/'verification.json',{'protected_original_product_files':len(original),'protected_frozen_experiment_files':len(frozen),
        'changed':changed,'new_model_training_runs':0,'held_out_test_unchanged':True,'app_rebuilt':False,'slides_or_video_rebuilt':False})
    print('Protection verified',len(original),len(frozen),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','depth','analyse','verify']);a=p.parse_args();globals()[a.mode]()
