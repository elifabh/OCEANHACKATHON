"""Small offline product views of existing evidence. No training or source mutation.

All distances/chords are computed in EPSG:2157. The selected 50 m sampling
square is a habitat hypothesis, never an observed bed or bathymetric transect.
"""
from pathlib import Path
from collections import Counter
import json, math
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import shape, box, Point, LineString, mapping
from shapely.ops import transform, nearest_points
from evidence_pipeline import ROOT, TO_ITM, TO_WGS, feature, fc, clean
from coastal_physics import direction_vector

F = ROOT/'outputs/cork_feasibility_20261015'
R = ROOT/'outputs/cork_multisite_review_20261015'
INPUTS = [str(p.relative_to(ROOT)).replace('\\','/') for p in [
    F/'cape_clear_south_harbour_case.json', F/'sample_cells.geojson', F/'candidate_paths.geojson',
    F/'historical_footprints.geojson', F/'coastline.geojson', F/'assets.geojson',
    F/'cape_clear_regional_wave_diagnostic.json', F/'conditional_physics_and_euros.json',
    F/'directional_waves.json', F/'bantry_subtidal_observations.json', F/'copper_point_data_availability.json',
    F/'inputs/waves_cape_clear_south_boundary.nc', R/'site_comparison.json', R/'source_register.json',
    R/'equal_region_occurrence_records.json', ROOT/'outputs/obis_raw_occurrences.json',
    ROOT/'outputs/cork_pilot_correction_20261015/STATUS_NO_REFIT.json']]
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def clipped(collection, bounds, select=lambda f: True):
    clip=box(*bounds); rows=[]
    for f in collection['features']:
        if not select(f): continue
        geom=shape(f['geometry']).intersection(clip)
        if not geom.is_empty: rows.append({'type':'Feature','geometry':mapping(geom),'properties':f['properties']})
    return fc(rows)

def biodiversity(raw,bounds):
    """Spatial inventory, retaining flags and provider IDs. No bed-richness score."""
    rows=[];seen=set();duplicates=0
    for r in raw:
        lon,lat=r.get('decimalLongitude'),r.get('decimalLatitude')
        if lon is None or lat is None or not(bounds[0]<=lon<=bounds[2] and bounds[1]<=lat<=bounds[3]):continue
        key=(r.get('dataset_id'),r.get('occurrenceID') or r.get('id'))
        if key in seen: duplicates+=1;continue
        seen.add(key)
        rows.append({k:r.get(k) for k in ['id','dataset_id','datasetName','occurrenceID','eventID','eventDate','scientificName','class','phylum','decimalLongitude','decimalLatitude','coordinateUncertaintyInMeters','minimumDepthInMeters','maximumDepthInMeters','flags','locality','absence','occurrenceStatus','samplingProtocol']})
    return {'scope_bounds':bounds,'records':rows,'duplicates_removed':duplicates,'inventory_count':len(rows),
            'taxa_count':len(set(r['scientificName'] for r in rows if r['scientificName'])),
            'on_land_flag_count':sum('ON_LAND' in (r['flags'] or []) for r in rows),
            'local_bed_richness':None,'sampling_effort_standardised':False,
            'method':'Existing OBIS archive intersected with the displayed assessment rectangle; deduplicated by provider dataset + occurrence ID (record ID fallback). Mixed marine, shore, bird and mammal records. Taxa counts are not kelp-associated diversity or abundance. Flags are retained, not silently masked. A recorded locality can disagree with coordinates.',
            'independence':'OBIS aggregates provider records. Historical survey reports, NPWS layers and Marine Recorder snapshots may reuse the same surveys; no independent validation is inferred.'}

def cape_waves(case):
    with xr.open_dataset(F/'inputs/waves_cape_clear_south_boundary.nc') as ds:
        q=ds.sel(longitude=case['wave_assignment']['grid_point'][0],latitude=case['wave_assignment']['grid_point'][1],method='nearest')
        h=q.VHM0.values.ravel();t=q.VTM10.values.ravel();a=q.VMDR.values.ravel();dates=pd.DatetimeIndex(q.time.values)
        valid=np.isfinite(h)&np.isfinite(t)&np.isfinite(a);weight=h*h*t;total=weight[valid].sum()
        bins=(np.floor((a+5)%360/10)*10).astype(int)
        sectors=[{'from_deg':i,'travel_deg':(i+180)%360,'hours':int(np.sum(valid&(bins==i))),
                  'flux_proxy_fraction':float(weight[valid&(bins==i)].sum()/total)} for i in range(0,360,10)]
        annual=[]
        for year in sorted(set(dates.year)):
            ix=(dates.year==year)&valid
            annual.append({'year':int(year),'hours':int(ix.sum()),'height_p50_m':float(np.quantile(h[ix],.5)),'height_p95_m':float(np.quantile(h[ix],.95))})
        return {'grid_point':[float(q.longitude),float(q.latitude)],'hours':int(valid.sum()),'expected_hours':87672,
                'first':str(dates.min()),'last':str(dates.max()),'sectors':sectors,'annual':annual,
                'height_p50_m':float(np.quantile(h[valid],.5)),'height_p95_m':float(np.quantile(h[valid],.95)),
                'distance_m':case['wave_assignment']['distance_m'],'direction':'FROM degrees; travel = FROM + 180',
                'weight':'H² × energy period, an offshore flux proxy, not energy delivered to habitat or annual benefit',
                'source':'cmems_mod_ibi_wav_my_0.027deg_PT1H-i / version 202511 / VHM0, VMDR, VTM10'}

def build_product(legacy):
    case=read(F/'cape_clear_south_harbour_case.json'); cells=read(F/'sample_cells.geojson')
    coast=read(F/'coastline.geojson'); assets=read(F/'assets.geojson'); hist=read(F/'historical_footprints.geojson')
    paths=read(F/'candidate_paths.geojson'); raw=read(ROOT/'outputs/obis_raw_occurrences.json')
    review={r['site']:r for r in read(R/'site_comparison.json')}; obs=read(R/'equal_region_occurrence_records.json')
    costs=read(F/'conditional_physics_and_euros.json'); waves=read(F/'directional_waves.json')
    # The archived 100 m illustration is preserved in the input file. Product
    # text must describe the live user inputs instead of repeating that example.
    costs['cost_warning']='Wexford approved funding benchmarks, nominal mixed 2024/2026 amounts. Your comparison frontage and budget share are independent assumptions; no measured protected frontage, savings, kelp value or Cork quote is established.'
    sourcecell=next(f for f in cells['features'] if f['properties']['site']=='cape_clear' and f['properties']['sample_id']==1351)
    poly=transform(TO_ITM,shape(sourcecell['geometry']));origin=Point(*TO_ITM(*case['habitat_scenario_origin_lonlat']))
    coastgeom={f['properties']['kind']:transform(TO_ITM,shape(f['geometry'])) for f in coast['features']}
    directions={};localpaths={f['properties']['from_deg']:f for f in paths['features'] if f['properties']['site']=='cape_clear' and f['properties']['origin_id']==1351}
    wave=cape_waves(case)
    for sector in wave['sectors']:
        deg=sector['from_deg'];u=direction_vector(sector['travel_deg']);xy=np.array([origin.x,origin.y])
        up=LineString([xy-5000*u,xy-2*u]);down=LineString([xy+2*u,xy+2000*u]);chord=LineString([xy-100*u,xy+100*u]).intersection(poly)
        blocked=up.intersects(coastgeom['coastline']) or up.intersection(coastgeom['land']).length>1 or up.intersects(coastgeom['unresolved_faces'])
        hit=down.intersection(coastgeom['coastline']);shore=None;shorepath=None
        if not hit.is_empty:
            shore=nearest_points(origin,hit)[1];shorepath=LineString([origin,shore])
        old=localpaths.get(deg);props=old['properties'] if old else {}
        directions[str(deg)]={'bearing_deg':sector['travel_deg'],'from_deg':deg,'rays':[{'weight_m':1,'land_blocked':False,'segments':[{'depth_m':sourcecell['properties']['point_depth_m'],'length_m':chord.length}]}],
            'shoreline':{'length_m':0},'shore_length_sensitivity_m':None,'open_upwave_5km':not blocked,
            'shore_distance_m':shorepath.length if shorepath is not None else None,
            'asset_ids':props.get('assets',[]) if not blocked else [],'flux_proxy_fraction':sector['flux_proxy_fraction'],
            'geometry':fc([feature(up,{'role':'Incoming 5 km screening ray'}),feature(chord,{'role':'Within assumed habitat cell'})]+([feature(shorepath,{'role':'Straight candidate shoreline path'})] if shorepath is not None else [])),
            'chord_m':chord.length,'cell_model_scope':'CENTRAL_RAY_ASSUMED_CELL_ONLY'}
    scenarios={'integration_mode':'central_ray','area_m2':poly.area,'depth_m':sourcecell['properties']['point_depth_m'],'datum':'AllSurvey mosaic datum unverified; depth changes are sensitivity assumptions, not tidal forecasts.',
               'directions':directions,'default_direction':'210','method':'Existing Dubi & Torum damping kernel; one central ray through historical-footprint-clipped 50 m sampling square. Centre depth assigned to whole cell. Assumed 2 m plants / 12 plants per m²; not measured locally.'}
    definitions=[('cape_clear','Cape Clear / South Harbour',case['display_bounds'],'Main conditional assessment'),
        ('sherkin','Sherkin / Baltimore',[-9.44,51.45,-9.355,51.505],'Supporting mapping and model example'),
        ('copper_point','Copper Point / Long Island',[-9.55,51.49,-9.52,51.515],'Supporting sonar feasibility evidence'),
        ('bantry','Bantry Bay / dated dive record',[-9.715,51.663,-9.68,51.69],'Supporting subtidal observation')]
    cases={}
    for key,name,bounds,role in definitions:
        base={'id':key,'name':name,'role':role,'bounds':bounds,'biodiversity':biodiversity(raw,bounds),
              'observations':[r for r in obs if r['site']==key], 'current_observed_kelp_geometry':None,
              'habitat_condition':None,'measured_decline_rate':None,'avoided_damage_eur_per_year':None,
              'land':clipped(coast,[bounds[0]-.06,bounds[1]-.04,bounds[2]+.06,bounds[3]+.04],lambda f:f['properties']['kind']=='land'),
              'historical':clipped(hist,bounds,lambda f:f['properties']['site']==key),
              'assets':clipped(assets,bounds,lambda f:f['properties']['site']==key),
              'intertidal':fc([]),'suitability':fc([]),'scenario_layer':fc([]),'scenario':None,
              'satellite':review.get(key,{}).get('two_date_clear_fractions',[]),
              'wave':waves.get(key), 'sources':['npws','infomar','cmems','osm','biodiversity','dubi','opw-cost']}
        if key=='cape_clear':
            base.update({'scenario':scenarios,'scenario_layer':fc([sourcecell]),'wave':wave,'case':case,
                         'observations':case['nearby_dated_observations'],
                         'history_note':'SSCO Laminaria-dominated community and Article 17 faunal-turf label disagree at sample 1351. Products reuse legacy evidence; dates are not a measured change series.',
                         'mapping_note':'No Cape Clear satellite habitat classification has been fitted or validated. 2022 SCL scene-clear fractions are imagery availability only; they cannot identify submerged kelp.'})
        elif key=='sherkin':
            scope=legacy['parametric']['scopes']['0']
            base.update({'land':legacy['coastline']['land'],'historical':legacy['historical']['layer'],
                         'suitability':legacy['groups'],
                         'scenario_layer':fc([legacy['groups']['features'][0]]),'intertidal':legacy['intertidal']['extent'],
                         'assets':legacy['assets']['layer'],'wave':legacy['wave'],
                         'scenario':{**scope,'default_direction':'0','depth_m':None,'datum':'Legacy Sherkin source depth convention; never transferred to Cape Clear.','method':'Legacy 5 m ray bundle in model group 0; unsupported current species/extent assumptions remain.'},
                         'history_note':'Frozen Sherkin experiments are diagnostics against historical references, not current ecological accuracy. No refit has been performed.',
                         'mapping_note':'Satellite layer: legacy 2022 intertidal macroalgae index, not confirmed subtidal kelp. The separate frozen RF experiment has substantial terrestrial false positives; no post-hoc masking or new accuracy claim.',
                         'mapping_diagnostic':read(ROOT/'outputs/cork_pilot_correction_20261015/STATUS_NO_REFIT.json')})
        elif key=='copper_point':
            base.update({'history_note':'July 2019 sonar and drop-video campaign is documented in Rossiter (2020). Actual experimental WCD, navigation, footprint and videos were not obtained. Generic LIR19_03 bathymetry is available; anchor depth 17.90 m LAT is outside the 4–10 m damping domain.',
                         'mapping_note':'Supporting method example only; no experimental sonar canopy map is displayed.',
                         'sonar_access':read(F/'copper_point_data_availability.json')})
        else:
            base.update({'observations':read(F/'bantry_subtidal_observations.json'),
                         'history_note':'2019 SeaSearch L. hyperborea observation reports 2–8.8 m dive depth. No bed width or extent. The 2018 on-land-flagged point is retained as a data-quality issue, not truth.',
                         'mapping_note':'Dated dive evidence only. Nominal mosaic depth 2.116 m is outside the 4–10 m model domain; no local attenuation or euro benefit is transferred.'})
        base['priorities']=[
            {'id':'P1','title':'Resolve the habitat evidence','status':'Research first','reason':base['history_note'],'action':'Georeferenced species/canopy video or diver transects; reconcile the original survey and reference lineage.','owner':'Marine ecology / GIS'},
            {'id':'P2','title':'Validate the physical connection','status':'Research first','reason':'Straight rays and offshore reanalysis do not model shoreline hazard.','action':'Confirm datum and nearshore depths; paired habitat/shore wave observations and a wave transformation model.','owner':'Coastal engineering'},
            {'id':'P3','title':'Assess restoration eligibility','status':'Not established','reason':'Historical presence and suitability do not demonstrate loss, restoration feasibility or benefit. Legacy external false-positive rate 63.45% exceeded the 30% threshold.','action':'Confirm present habitat, substrate, pressure, permissions and recovery mechanism before selecting restoration.','owner':'Ecology / local partners'},
            {'id':'P4','title':'Test the economic benefit claim','status':'Not quantified','reason':'Approved funding rates are comparators; maintenance, ecological delivery and damages are missing.','action':'Estimate with/without receptor hazard, event probabilities, asset values, damage functions and lifecycle costs.','owner':'Economics / engineering'}]
        cases[key]=base
    sources=list(legacy['sources'])+[{'id':s['id'],'name':s['title'],'url':s.get('url') or s['urls'][0],'dates':s.get('field_date','See source'),'limits':s.get('independence',s.get('limitation',s.get('access','Historical evidence; not present validation'))),'role':'Supporting research','licence':'See original provider terms; source files retained locally'} for s in read(R/'source_register.json')['sources']]
    sources += [{'id':'south-harbour-tender','name':case['actual_coastal_asset_context']['title'],'url':case['actual_coastal_asset_context']['url'],'dates':'Published 23 July 2025','role':'Engineering need context','limits':'No published price or verified alignment to an OSM segment; no evidence of kelp savings.','licence':'Public tender metadata'},
                {'id':'obis','name':'OBIS provider occurrence records','url':'https://obis.org','dates':'Dates and provider dataset IDs retained on each record','role':'Dated, mixed-taxa inventory','limits':'Aggregator; overlapping survey lineage, heterogeneous effort and coordinate flags. Not local kelp-bed richness.','licence':'Provider-specific terms; see dataset pages'}]
    for source in sources:
        if source['id']=='dubi':source['name']='Dubi & Torum (1996) laboratory wave damping'
        if source['id']=='infomar':source['limits']='Cape Clear AllSurvey mosaic vertical datum is unverified. Copper Point LIR bathymetry uses LAT; that convention is not transferred to Cape Clear. A centre point does not resolve within-cell relief or tidal depth.'
    return clean({'version':'cape-product-2','default_case':'cape_clear','cases':cases,'costs':costs,'sources':sources,
                  'method_crs':'EPSG:2157 for geometry, EPSG:4326 for display','training_runs':0,
                  'promise_sections':['Habitat map','Condition and decline-risk components','Conditional coastal protection','Transparent euro scenarios','Biodiversity evidence','Research and restoration priorities','Integrated clickable assessment'],
                  'input_files':INPUTS,'disclosure':'AI-assisted preparation. Role assignments are proposed for event teamwork; no completed team contribution is asserted.'})
