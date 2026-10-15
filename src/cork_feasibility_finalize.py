"""Build a concrete, reviewable prototype configuration and verify the pass."""
from pathlib import Path
import json, math, importlib.metadata as md
import geopandas as gpd
from shapely.geometry import Point, LineString
from cork_feasibility import ROOT,OUT,RAW,REVIEW,read,save,clean,sha,TO_ITM,coast
from coastal_physics import direction_vector

def main():
    diagnostic=read(OUT/'cape_clear_regional_wave_diagnostic.json')
    origin=diagnostic['origin_summaries']['1351']
    rows=[p for p in read(OUT/'cape_clear_paths.json') if p['origin_id']==1351 and p['from_deg'] in [200,210]]
    climate=diagnostic['grid_cells'][origin['grid_index']]
    for r in rows:
        r['flux_proxy_fraction']=climate['flux_proxy_by_from_deg'][str(r['from_deg'])]
        r['wave_grid_point']=climate['grid_point']
        r['model_status']='ASSUMED_HABITAT_CELL_ATTENUATION_ONLY_NOT_SHORELINE_HAZARD'
    point=Point(*TO_ITM(*origin['origin_lonlat']))
    article=gpd.read_file(ROOT/'data/npws/gis_files/21 NPWSArticle17Habitat.shp',bbox=(-9.52,51.42,-9.48,51.45)).to_crs(2157)
    article_labels=sorted(set(r.Community for _,r in article.iterrows() if r.geometry.covers(point)))
    obs=read(REVIEW/'equal_region_occurrence_records.json');near=[]
    for r in obs:
        if r['site']!='cape_clear':continue
        distance=point.distance(Point(*TO_ITM(r['decimalLongitude'],r['decimalLatitude'])))
        near.append({**r,'distance_to_case_origin_m':distance,'validates_case_pixel':False})
    near=sorted(near,key=lambda r:r['distance_to_case_origin_m'])[:6]
    case={'site':'Cape Clear / South Harbour','role':'Conditional process demonstration, not validated benefit site',
        'habitat_sample_id':1351,'habitat_scenario_origin_lonlat':origin['origin_lonlat'],
        'display_bounds':[-9.516,51.425,-9.487,51.443],
        'current_observed_kelp_geometry':None,'historical_reference':'NPWS SSCO Laminaria dominated communities',
        'Article17_labels_at_same_point':article_labels,'reference_conflict_unresolved':True,
        'reference_independence':'NPWS products inherit legacy survey material; OBIS is an aggregator. No independent contemporaneous validation claimed.',
        'nearby_dated_observations':near,'wave_assignment':origin,'example_paths':rows,
        'candidate_low_DSM_objects':[r for r in diagnostic['records'] if r['origin_id']==1351 and r['from_deg'] in [200,210]
            and r['osm_id'] in origin['low_DSM_road_building_objects']],
        'physical_caveats':['Only a clipped 50 m sampling square is assigned its centre depth; this is not a measured bed width or continuous depth survey.',
            'The AllSurvey point is nominal 7.04 m depth. Its source-specific vertical datum is not established by the mosaic response; +2 m is a sensitivity, not a tidal forecast.',
            'The downloaded LIR19_03 grid has no data at this Cape sample. Its LAT datum cannot be silently assigned to the mosaic.',
            'No refraction, diffraction, breaking, surge, erosion or asset hazard model was run. There is no shore-level attenuation percentage.',
            'Existing damping coefficients assume laboratory plant geometry/density; local biomass and drag are not measured.'],
        'actual_coastal_asset_context':{'title':'Cork County Council: South Harbour Cape Clear Island Seawall Repairs',
            'url':'https://www.etenders.gov.ie/epps/cft/prepareViewCfTWS.do?resourceId=6170913',
            'published':'2025-07-23','description':'Two concrete seawall/deck sections for the public access road to the quay at Oilean Faha.',
            'contract_alignment_to_specific_OSM_segment':'Not established; regional engineering need only.',
            'estimated_value_published':None,'evidence_of_kelp_saving':False},
        'harbour_or_pier_geometry_chain_demonstrated':False,
        'avoided_damage_eur_per_year':None,'kelp_ecosystem_value_eur':None,
        'cost_scenario_file':'conditional_physics_and_euros.json','satellite_mapping_target':'Intertidal macroalgae only'}
    save(OUT/'cape_clear_south_harbour_case.json',clean(case))
    decision={'recommendation':'CAPE_CLEAR_SOUTH_HARBOUR_CONDITIONAL_PROTOTYPE',
        'any_site_demonstrates_current_kelp_plus_validated_shore_protection_plus_avoided_damage':False,
        'Long_Island_final_integrated_site_approved':False,
        'copper_point':'Do not make the prototype depend on unavailable experimental sonar/navigation/video. Use the dated thesis as methodological evidence and downloaded bathymetry as seabed context.',
        'bantry':'Keep the unflagged 2019 SeaSearch point as habitat evidence and a road-connection control. No mapped bed width; point bathymetry about 2.12 m is outside the existing 4-10 m damping domain.',
        'cape_clear':'Best executable conditional prototype: historical geometry, sampled depth, sector-specific sea-connected wave data, actual mapped roads/buildings, and documented road/quay defence need.',
        'reason_not_a_verified_benefit_site':'Current kelp extent is unknown and NPWS classes conflict; nearshore transfer and receptor damage inputs are missing.',
        'no_further_site_search_required_for_next_phase':True,'selection_used_euro_totals':False,
        'next_phase':'Integrate the saved South Harbour case into existing modules without claiming current kelp validation or protected assets; keep benefit fields null.'}
    save(OUT/'decision.json',decision)
    promises=[
        ['Habitat mapping','Satellite intertidal macroalgae, historical kelp reference, and subtidal suitability remain separate; no new training.'],
        ['Condition / decline risk','Retain risk layers and distinguish stress/change indicators from measured kelp loss.'],
        ['Coastal protection','Use the saved directional paths and within-assumed-cell physics; do not substitute them for shore hazard.'],
        ['Transparent euros','Retain independent cost scenarios; avoided damage and kelp service value remain null.'],
        ['Biodiversity','Retain source records and sampling-effort caveats; do not copy Sherkin score to Cape Clear.'],
        ['Restoration priority','Keep indicative status and failed external suitability validation; no high-confidence restoration claim.'],
        ['Clickable integrated map','Later wire this case to existing map/assessment/parametric modules; all confidence and unknown states visible.']]
    jury=['Working demonstrator','Digital data','Ambition','Environmental and societal impact','Innovation','Team cohesion and communication']
    save(OUT/'requirements_preserved.json',{'seven_original_promises':[{'requirement':a,'retained':True,'implementation_guard':b} for a,b in promises],
        'transferability_retained':True,'six_jury_criteria':[{'criterion':c,'retained':True} for c in jury],
        'original_sources':['docs/overnight_20261013/MASTER_BRIEF.md sections 1-2','CLAUDE.md project/jury requirements'],
        'previous_site_comparison_preserved':True,'application_presentations_video_untouched':True})
    # Meaningful conservation, geographic and temporal checks.
    land,coastline,domain,unknown,info=coast();max_angle=0.;checked=0
    for site in ['copper_point','cape_clear','bantry']:
        wave=read(OUT/'directional_waves.json')[site]
        assert wave['hours']==wave['expected_hours']==87672
        assert abs(sum(s['flux_proxy_fraction'] for s in wave['sectors'])-1)<1e-6
        for p in read(OUT/(site+'_paths.json')):
            a=Point(*TO_ITM(*p['origin_lonlat']));b=Point(*TO_ITM(*p['shore_lonlat']))
            bearing=math.degrees(math.atan2(b.x-a.x,b.y-a.y))%360
            error=abs((bearing-(p['from_deg']+180)+180)%360-180);max_angle=max(max_angle,error)
            assert error<.01
            assert len(p['assets'])==len(set(p['assets']))
            assert p['avoided_damage_eur'] is None
            if p['open_upwave_5km']:
                u=direction_vector(p['from_deg']+180)
                line=LineString([(a.x-5000*u[0],a.y-5000*u[1]),(a.x-2*u[0],a.y-2*u[1])])
                assert not line.intersects(coastline)
                assert line.intersection(land).length<1
            checked+=1
    old_manifest=read(REVIEW/'delivery_manifest.json')
    changed_review=[p for p,h in old_manifest.items() if sha(REVIEW/p)!=h['sha256']]
    assert not changed_review,changed_review
    # Previously protected application/raw inputs and frozen hold-out remain byte identical.
    from cork_feasibility import verify
    verify()
    inputs=read(OUT/'input_hashes.json')
    for p in [Path(__file__),ROOT/'src/cork_feasibility_diagnostics.py',ROOT/'docs/overnight_20261013/MASTER_BRIEF.md',ROOT/'CLAUDE.md']:
        inputs[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
    for p in (ROOT/'data/npws/gis_files').glob('21 NPWSArticle17Habitat.*'):
        inputs[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
    save(OUT/'input_hashes.json',inputs)
    verification=read(OUT/'verification.json');verification.update({'previous_comparison_manifest_files_checked':len(old_manifest),
        'changed_previous_comparison_files':changed_review,'directional_paths_checked':checked,'max_bearing_error_degrees':max_angle,
        'coastline_unresolved_faces':info['unresolved_faces'],
        'dependency_versions':{m:md.version(m) for m in ['numpy','pandas','geopandas','shapely','rasterio','pyproj','xarray','requests','copernicusmarine']}})
    save(OUT/'verification.json',clean(verification));print(json.dumps(clean(verification),indent=2))

if __name__=='__main__':main()
