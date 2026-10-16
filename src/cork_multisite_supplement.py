"""Equal-region occurrence audit and Copper Point geographic screen. No fitting.

Run --acquire once for public sources, then --analyse offline after
cork_multisite_review.py --analyse. Source PDFs are preserved verbatim.
"""
from pathlib import Path
import argparse, json, math
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString, mapping
from shapely.ops import transform
from cork_multisite_review import ROOT, OUT, SITES, save, sha, TO_ITM, TO_WGS

PUBLIC_SOURCES = {
 'rossiter_2020_thesis.pdf': 'https://researchrepository.universityofgalway.ie/bitstreams/8af41e9f-0bea-43b8-9f94-6a892179d375/download',
 'bantry_baseline_2016.pdf': 'https://cdn.thejournal.ie/media/2017/11/baseline-survey.pdf',
 'emblow_1994_bantry.pdf': 'https://www.npws.ie/sites/default/files/publications/pdf/Emblow_et_al_1994_Bantry_Bay.pdf',
 'irish_shelf_swan_metadata.json': 'https://erddap.marine.ie/erddap/info/IMI_IRISH_SHELF_SWAN_WAVE/index.json',
}

def acquire():
    folder=OUT/'inputs/obis_equal_region'; folder.mkdir(parents=True,exist_ok=True)
    for taxon in ['Laminariales','Saccorhiza']:
        url='https://api.obis.org/v3/occurrence'
        params={'geometry':'POLYGON((-10.2 51.4,-9.2 51.4,-9.2 51.8,-10.2 51.8,-10.2 51.4))',
                'scientificname':taxon,'size':5000,'offset':0}
        p=folder/(taxon+'.json')
        if p.exists():d=json.loads(p.read_text())
        else:
            r=requests.get(url,params=params,timeout=90);r.raise_for_status();d=r.json();save(p,d)
            save(folder/(taxon+'.request.json'),{'url':url,'parameters':params,'retrieved_utc':datetime.now(timezone.utc).isoformat()})
        assert len(d['results'])==d['total'] and d['total']<5000, 'Pagination required; do not report a truncated query as complete.'
    folder=OUT/'sources';folder.mkdir(exist_ok=True);ledger=[]
    for name,url in PUBLIC_SOURCES.items():
        p=folder/name
        if not p.exists():
            r=requests.get(url,timeout=90);r.raise_for_status()
            if name.endswith('.pdf'):assert r.content[:4]==b'%PDF'
            else:r.json()
            p.write_bytes(r.content)
        ledger.append({'file':str(p.relative_to(OUT)), 'url':url,'sha256':sha(p),'bytes':p.stat().st_size})
    save(folder/'download_ledger.json',ledger)

def analyse():
    rows=[];folder=OUT/'inputs/obis_equal_region'
    for taxon in ['Laminariales','Saccorhiza']:
        d=json.loads((folder/(taxon+'.json')).read_text());assert len(d['results'])==d['total'];rows.extend(d['results'])
    allobs=pd.DataFrame(rows)
    # OBIS IDs identify records; occurrence identifiers can be missing.
    allobs['record_key']=allobs['occurrenceID'].fillna(allobs['dataset_id'].astype(str)+'|'+allobs['id'].astype(str))
    allobs=allobs.drop_duplicates('record_key')
    allobs['date_day']=allobs.eventDate.fillna('UNDATED').astype(str).str[:10]
    allobs['event_key']=allobs.decimalLongitude.round(6).astype(str)+'|'+allobs.decimalLatitude.round(6).astype(str)+'|'+allobs.date_day
    # Event grouping only reduces obvious same-date, same-position repetition;
    # distinct event keys are NOT proof of survey/source independence.
    allobs['explicit_present']=allobs.occurrenceStatus.astype(str).str.lower().eq('present') & ~allobs.absence.fillna(False)
    summary=[];events=[];records=[]
    for key,s in SITES.items():
        b=s['bbox'];q=allobs[allobs.decimalLongitude.between(b[0],b[2]) & allobs.decimalLatitude.between(b[1],b[3])].copy()
        for _,r in q.iterrows():
            records.append({'site':key,**{c:r.get(c) for c in ['record_key','occurrenceID','datasetName','dataset_id','eventID','event_key',
                'eventDate','decimalLongitude','decimalLatitude','scientificName','occurrenceStatus','absence','explicit_present',
                'minimumDepthInMeters','maximumDepthInMeters','coordinateUncertaintyInMeters','samplingProtocol','flags']}})
        for event,g in q.groupby('event_key'):
            r=g.iloc[0];events.append({'site':key,'event_key':event,'date':r.date_day,'lon':r.decimalLongitude,'lat':r.decimalLatitude,
                'taxa':'|'.join(sorted(set(g.scientificName))), 'datasets':'|'.join(sorted(set(g.datasetName.fillna('UNKNOWN')))),
                'records':len(g),'explicit_present_records':int(g.explicit_present.sum()),'independent_ground_truth':False})
        summary.append({'site':key,'indexed_records':len(q),'explicit_present_records':int(q.explicit_present.sum()),
            'grouped_coordinate_date_events':q.event_key.nunique(),'first_date':q.date_day.min() if len(q) else None,
            'last_date':q.date_day.max() if len(q) else None,'dataset_names':sorted(set(q.datasetName.fillna('UNKNOWN'))),
            'complete_api_response_within_declared_bounds':True,'complete_ecological_inventory':False,
            'nonstandard_occurrence_status_records':int((~q.explicit_present).sum()),'verified_current_presence':None})
    save(OUT/'equal_region_occurrence_summary.json',summary)
    save(OUT/'equal_region_occurrence_records.json',records)
    pd.DataFrame(events).to_csv(OUT/'equal_region_kelp_events.csv',index=False)
    indexed={r['site']:r for r in summary};comparison=[]
    for r in json.loads((OUT/'site_comparison.json').read_text()):
        q=indexed[r['site']]
        comparison.append({'site':r['name'],
            'clear_scl_percent_2022_05_15':round(r['two_date_clear_fractions'][0]*100,2),
            'clear_scl_percent_2022_07_14':round(r['two_date_clear_fractions'][1]*100,2),
            'finite_depth_samples_of_121':r['finite_depth_samples'],'indexed_kelp_records':q['indexed_records'],
            'grouped_obis_coordinate_date_events':q['grouped_coordinate_date_events'],
            'first_reported_date':q['first_date'],'last_reported_date':q['last_date'],
            'ssco_historical_laminaria_ha':r['ssco_historical_laminaria_ha'],
            'article17_historical_laminaria_ha':r['article17_historical_laminaria_ha'],
            'archive_building_clusters':r['archive_building_clusters'],
            'confirmed_protected_assets':None,'current_kelp_extent_validated':False})
    pd.DataFrame(comparison).to_csv(OUT/'comparison_table.csv',index=False)
    save(OUT/'equal_region_occurrence_audit.json',{'raw_api_records':len(rows),'after_identifier_deduplication':len(allobs),
        'explicit_absences':int(allobs.absence.sum()),'query_taxa':['Laminariales','Saccorhiza'],
        'notes':['Both queries use identical regional bounds; replaces unequal historical cache for regional availability comparisons.',
                 'OBIS is an aggregator. BioMar/JNCC/NMNI legacy records can overlap NPWS survey inputs.',
                 'SeaSearch, Explore Your Shore and iNaturalist need event/photo provenance checks; no cross-provider independence assumed.',
                 'No occurrence was used as a training label or scored as a current ecological validation result.']})
    # Geographic sensitivity check at the published survey coordinate, not an
    # invented present-day kelp polygon. Expose incomplete coastline topology.
    from evidence_pipeline import build_coast
    from coastal_physics import direction_vector, path_status
    site=next(r for r in json.loads((OUT/'site_comparison.json').read_text()) if r['site']=='long_island')
    land,coast,domain,info=build_coast(bounds=(-9.64,51.44,-9.48,51.56))
    p=Point(*TO_ITM(*SITES['long_island']['anchor']));bearing=site['nearest_cached_offshore_wave']['travel_deg']
    a=np.array([p.x,p.y]);u=direction_vector(bearing)
    incoming=LineString([a-2000*u,a]);outgoing=LineString([a,a+2000*u]);assets=[]
    b=pd.read_csv(ROOT/'outputs/national_candidate_table.csv')
    for _,r in b[b.county.eq('Cork')].iterrows():
        receptor=Point(*TO_ITM(r.lon,r.lat))
        if p.distance(receptor)<=3500:
            assets.append({'cluster':int(r.cluster),'lon':r.lon,'lat':r.lat,'archive_building_count':int(r.n_buildings_200m),
                **path_status(p,receptor,land,coast,bearing),'confirmed_kelp_protection':False})
    result={'coastline_ways':info['coastline_ways'],'unresolved_faces':info['unresolved_faces'],
        'anchor_on_land':land.covers(p),'bearing_travel_deg':bearing,
        'incoming_ray_land_m':incoming.intersection(land).length,'incoming_ray_crosses_coast':incoming.intersects(coast),
        'outgoing_ray_land_m':outgoing.intersection(land).length,'wave_source':site['nearest_cached_offshore_wave'],
        'asset_screen_within_3500m':assets,
        'status':'INCOMPLETE_TOPOLOGY_GEOGRAPHIC_SCREEN_ONLY_NO_CONFIRMED_ASSET_LINK',
        'limitations':['Unresolved coastline faces prevent a positive connectivity claim.',
                      'A straight ray does not model refraction, diffraction, local wind waves, storm direction or attenuation.',
                      'Nearest cached offshore cell is not necessarily nearest available CMEMS cell.']}
    save(OUT/'copper_point_geometry_screen.json',result)
    features=[{'type':'Feature','geometry':mapping(transform(TO_WGS,g)),'properties':{'kind':name}} for name,g in
        [('land',land),('coast',coast),('incoming_2km_straight_ray',incoming),('outgoing_2km_straight_ray',outgoing),('published_copper_point_anchor',p)]]
    save(OUT/'copper_point_geometry_screen.geojson',{'type':'FeatureCollection','features':features})
    save(OUT/'supplement_hashes.json',{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in
        [Path(__file__),*folder.glob('*.json'),ROOT/'src/evidence_pipeline.py',ROOT/'src/coastal_physics.py',
         ROOT/'data/osm/overpass_1a75c6425bde.json',ROOT/'data/_sherkin_asset_audit_cache/49a3e38750e416e8a4b79a95697f37a192ad656477b7f35217523ebaba84492f.json']})
    print(json.dumps(summary,indent=2));print('Copper Point asset paths:',json.dumps(assets,indent=2))

def verify():
    import importlib.metadata as md
    original=json.loads((ROOT/'outputs/cork_pilot_20261015/preserved_originals.json').read_text())
    frozen=json.loads((ROOT/'outputs/cork_pilot_correction_20261015/protected_inputs.json').read_text())
    changed=[p for p,h in (original | frozen).items() if sha(ROOT/p)!=h]
    assert not changed, 'Protected input changed: '+str(changed)
    inputs=[p for p in (OUT/'inputs').rglob('*') if p.is_file()]
    inputs += [p for base in [ROOT/'data/npws/gis_files/21 NPWSArticle17Habitat',
        ROOT/'outputs/npws_source_review/20261013T020954_399007Z/layer_01/CO_Marine_Community_Types'] for p in base.parent.glob(base.name+'.*')]
    inputs += list((ROOT/'data/cmems').glob('ibi_wav_*.nc'))
    save(OUT/'complete_analysis_input_hashes.json',{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in inputs})
    save(OUT/'final_verification.json',{'original_product_files':len(original),'frozen_previous_experiment_files':len(frozen),
        'changed_protected_files':changed,'held_out_test_unchanged':True,'new_model_training_runs':0,
        'application_rebuilt':False,'presentations_rebuilt':False,'evidence_sites':8,
        'dependency_versions':{m:md.version(m) for m in ['numpy','pandas','geopandas','rasterio','scipy','shapely','pyproj','xarray','requests']},
        'no_dependency_installed':True})
    print('Verified original product and frozen experiment files:',len(original),len(frozen))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--acquire',action='store_true');p.add_argument('--analyse',action='store_true');p.add_argument('--verify',action='store_true');a=p.parse_args()
    if a.acquire:acquire()
    if a.analyse:analyse()
    if a.verify:verify()
