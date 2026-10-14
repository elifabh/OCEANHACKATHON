"""Auditable workspace indicators. Reads original evidence; never rewrites it.

No cross-source composite health, decline or biodiversity score is produced.
Geometry summaries describe model footprints, not ecological fragmentation.
"""
from __future__ import annotations
from collections import Counter
import json
import math
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import shape, Point
from shapely.ops import transform, unary_union
from evidence_pipeline import ROOT, NPWS, ITM, TO_ITM, feature, fc, clean

VERSION = 'workspace-evidence-1.0'
INPUTS = ['outputs/obis_raw_occurrences.json', 'outputs/indicator_site_scores.csv',
          'outputs/indicator_match.csv', 'outputs/intertidal/report_sherkin_baltimore_7scenes.json',
          'outputs/light/kd_cache/raw_cmems_obs-oc_atl_bgc-transp_my_l3-multi-_-9.42_51.45.nc']


def record(key, label, value, unit, support, source, dates, scale, method, limits, next_step):
    return dict(id=key, label=label, value=value, units=unit, evidence_class=support,
                source=source, date_range=dates, spatial_scale=scale, method=method,
                quality_limits=limits, next_step=next_step, site='Roaringwater Bay / West Cork',
                quantification_status='NOT_ASSESSED' if value is None else 'DESCRIPTIVE_INDICATOR',
                assumptions='No composite health or decline score; source domains remain separate.',
                calculation_version=VERSION)


def biodiversity_audit(data):
    scored = pd.read_csv(ROOT/'outputs/indicator_site_scores.csv')
    raw = pd.DataFrame(json.loads((ROOT/'outputs/obis_raw_occurrences.json').read_text(encoding='utf8')))
    raw['site'] = raw.decimalLatitude.round(6).astype(str)+'_'+raw.decimalLongitude.round(6).astype(str)
    r = raw[raw.site.isin(scored.site)].copy()
    before = len(r)
    # Source occurrence IDs, not taxon names or null catalogue IDs, identify duplicates.
    if r[['dataset_id', 'occurrenceID']].isna().any().any():
        raise ValueError('Missing occurrence identity; do not silently deduplicate unknown records')
    r = r.drop_duplicates(['dataset_id', 'occurrenceID'])
    years = pd.to_datetime(r.eventDate, errors='coerce', utc=True).dt.year
    sites = []
    for key, g in r.groupby('site'):
        lat, lon = map(float, key.split('_'))
        scored_row = scored[scored.site == key].iloc[0]
        sites.append(dict(lat=lat, lon=lon, records=len(g), species=int(g.species.nunique()),
                          indicators=int(scored_row.indicators_found), dates=sorted(g.eventDate.dropna().unique().tolist()),
                          unique_survey_dates=int(g.eventDate.nunique())))
    groups = []
    for name, g in pd.DataFrame(data['biodiversity']['taxa']).groupby('trophic_function'):
        groups.append(dict(group=name.replace('_',' '), recorded=int(g.present_in_west_cork.sum()), reference=len(g)))
    return dict(records_before_deduplication=before, records=len(r), duplicate_ids_removed=before-len(r),
                distinct_species_labels=int(r.species.nunique()), species_identified_records=int(r.species.notna().sum()),
                deduplication_key=['dataset_id','occurrenceID'], gbif_records_merged=0,
                dates=[str(r.eventDate.min()), str(r.eventDate.max())],
                records_by_year=[dict(year=int(y), records=int(n)) for y,n in years.value_counts().sort_index().items()],
                dataset_counts={str(k):int(v) for k,v in r.dataset_id.value_counts().items()},
                sites=sites, site_count=len(sites), repeat_survey_sites=sum(s['unique_survey_dates']>1 for s in sites),
                groups=groups, local_bed_richness=None, habitat_structure=None,
                method='Source-ID deduplication in the 35 original faunal dive-site coordinates. Reference indicator presence uses accepted AphiaIDs; broad species labels are not a taxonomy-standardised richness estimate.',
                limits='Historical co-located records; unequal observation effort. A shared coordinate does not prove association with a current kelp bed. No GBIF records are added, so no OBIS/GBIF double counting. One dated event per site prevents a repeat-site trend.')


def geometry_indicators(data):
    historic = unary_union([transform(TO_ITM, shape(f['geometry'])) for f in data['historical']['layer']['features']])
    rows = {}
    for group, scope in data['parametric']['scopes'].items():
        cells = [transform(TO_ITM,shape(f['geometry'])) for f in data['cells']['features'] if group=='0' or f['properties']['group_id']==int(group)]
        geom=unary_union(cells)
        distances=[a.distance(b) for i,a in enumerate(cells) for b in cells[i+1:]]
        overlap=geom.intersection(historic).area
        rows[group]=dict(model_area_m2=geom.area,historical_overlap_m2=overlap,
                        historical_overlap_fraction=overlap/geom.area,minimum_cell_gap_m=min(distances) if distances else None,
                        actual_fragmentation=None,
                        note='EPSG:2157 area intersection of nominal model cells with historical generic Laminaria communities. Agreement of different dates/classes does not validate current L. hyperborea or ecological connectivity.')
    return rows


def monthly_waves(data):
    with xr.open_dataset(ROOT/'data/cmems/ibi_wav_sherkin.nc') as ds:
        g=ds.VHM0.sel(longitude=data['wave']['point'][0],latitude=data['wave']['point'][1],method='nearest').to_dataframe().reset_index()
    g=g.dropna(subset=['VHM0']); rows=[]
    for period, s in g.groupby(g.time.dt.to_period('M')):
        rows.append(dict(period=str(period),year=int(period.year),month=int(period.month),
                         hs_mean_m=float(s.VHM0.mean()),hs_p95_m=float(s.VHM0.quantile(.95)),
                         hours=len(s),expected_hours=int(period.days_in_month*24)))
    return rows


def reference_scenario(data):
    p=data['presentation_scenario']; scope=data['parametric']['scopes'][str(p['group'])]
    dr=scope['directions'][str(p['direction_offset_deg'])]; i=p['inputs']; phys=dr['baseline']
    length=dr['shoreline']['length_m'] if i['length_mode']=='shoreline' else scope['area_m2']/i['assumed_width_m']
    r=i['discount_rate']; n=i['years']; crf=1/n if r==0 else r/-math.expm1(-n*math.log1p(r))
    return dict(**p, area_m2=scope['area_m2'], comparison_length_m=length, height_fraction=phys['height_fraction'],
                energy_fraction=phys['energy_fraction'], capital_recovery_factor=crf,
                bands={k:dict(unit_eur_per_m=v*i['rate_multiplier'],capital_eur=length*v*i['rate_multiplier']*i['cost_share'],
                              annualised_eur_per_year=length*v*i['rate_multiplier']*i['cost_share']*crf) for k,v in data['costs']['rates'].items()},
                avoided_damage_eur=None, ecosystem_service_value_eur=None)


def water_clarity():
    path=ROOT/INPUTS[-1]
    if not path.exists():return dict(status='UNAVAILABLE',annual=[],note='No optical-water subset available.')
    with xr.open_dataset(path) as ds:
        array=ds['KD490'].sel(latitude=51.465,longitude=-9.405,method='nearest')
        units=array.attrs.get('units')
        frame=array.to_dataframe().reset_index().dropna(subset=['KD490'])
        point=[float(array.longitude),float(array.latitude)]
    rows=[]
    for year,g in frame.groupby(frame.time.dt.year):
        expected=366 if pd.Timestamp(int(year),12,31).is_leap_year else 365
        rows.append(dict(year=int(year),median_per_m=float(g.KD490.median()),valid_days=len(g),expected_days=expected))
    return dict(status='SATELLITE_OPTICAL_PROXY',point=point,units=units,annual=rows,
                source='Copernicus OCEANCOLOUR_ATL_BGC_L3_MY_009_113',resolution_km=1.1596,
                note='KD490 optical attenuation at 490 nm, multi-sensor ~1 km grid. Cloud/quality gaps bias coverage. Not KdPAR, canopy light, seabed health or kelp decline.')


def build_workspace(data):
    report=json.loads((ROOT/INPUTS[3]).read_text())
    scenes=sorted(report['scenes'],key=lambda r:r['date'])
    bio=biodiversity_audit(data); geo=geometry_indicators(data)
    evidence=[]
    evidence.append(record('temperature','Sea temperature pressure',data['sst'].get('n_days'),'sampled days','proxy','sst',data['sst'].get('baseline','Unavailable'),'0.25° regional surface grid',data['sst'].get('sampling','Unavailable'),data['sst']['note'],'Obtain daily seabed temperatures and a locally appropriate ecological threshold.'))
    evidence.append(record('waves','Wave exposure / storm pressure',data['wave']['hs_p95_m'],'m Hs, pooled hourly p95','modelled','cmems','2015–2024','Offshore point, '+str(round(data['wave']['distance_to_model_centroid_m']))+' m from model','Descriptive annual/monthly Hs mean and p95; p95 is not a design storm.',data['wave']['note'],'Measure nearshore waves, period and water levels across the habitat.'))
    evidence.append(record('continuity','Habitat continuity / fragmentation',None,'ecological connectivity','modelled','infomar','Static model input','50 m nominal cells','Geometric area and cell gaps only; no surveyed canopy boundaries.','Model grid fragmentation cannot establish ecological fragmentation.','Map contiguous present canopy with consistent repeat survey.'))
    evidence.append(record('agreement','Evidence agreement',geo['0']['historical_overlap_fraction']*100,'% model area overlapping history','historical','npws','2002–2010 surveys / 2011 synthesis','Selected model footprint','Projected area intersection, not agreement of independent contemporary observations.',geo['0']['note'],'Resolve historical label conflicts with georeferenced species observations.'))
    evidence.append(record('water','Water / environment indicator',None,'EPA macroalgae quality','proxy','epa','2007–2009 and 2010–2015','Whole coastal waterbody','Read official macroalgae element separately from overall ecological status.','High quality element in two reported cycles; later macroalgae values absent. Not a kelp extent measurement.','Acquire the relevant monitoring element and repeat local bed surveys.'))
    evidence.append(record('stability','Historical stability / change',None,'% kelp decline','historical','npws','Survey synthesis + seven 2022 scenes','Mixed spatial and temporal support','Inventory observation coverage; no defensible repeated-method extent series.','Data coverage is not ecological change. Historical polygons cannot be split by survey year.','Repeat the same extent/biomass survey at matched tides and seasons.'))
    risks=[dict(id=key,label=label,component=component,status='INVESTIGATE' if component in ['temperature','waves','agreement'] else 'NOT_ASSESSED',value=None,reason=reason) for key,label,component,reason in [
        ('warming','Warming risk','temperature','Sparse regional surface samples do not establish local physiological stress.'),
        ('storms','Storm / wave stress','waves','Offshore wave variability is available; bed damage thresholds are not.'),
        ('fragmentation','Fragmentation','continuity','No comparable canopy polygons or connectivity calibration.'),
        ('monitoring','Monitoring / evidence gap','agreement','Historical observations and failed external validation require a new field check.'),
        ('resilience','Resilience proxy','stability','Recruitment, canopy density and recovery observations are missing.')]]
    priorities=[]
    for index, f in enumerate(data['historical']['restoration']['features'],1):
        p=f['properties'];pt=shape(f['geometry']).centroid
        priorities.append(dict(id=index,lon=pt.x,lat=pt.y,category='Research/survey priority',reason=p['action'],
             historical_overlap=p['historical_overlap'],overlap_fraction=p['overlap_fraction'],suitability=p['suitability'],
             evidence_class='MODELLED_UNVALIDATED',decline=None,biodiversity_local=None,protected_assets=None,practical_feasibility=None,
             next_step='Confirm species, canopy extent, density and substrate. Restoration feasibility and demand have not been assessed.'))
    galway=gpd.read_file(NPWS,where="Site_Code = '002111'").to_crs(ITM)
    galway=galway[galway.Commun_Typ.str.contains('Laminaria',case=False,na=False)].copy()
    galway['_key']=galway.geometry.to_wkb(hex=True)+'|'+galway.Commun_Typ;galway=galway.drop_duplicates('_key')
    layer=fc([feature(r.geometry.simplify(15,preserve_topology=True),dict(community=r.Commun_Typ,evidence='HISTORICAL_REFERENCE',source='NPWS SSCO 002111; package March 2025, not current survey')) for _,r in galway.iterrows()])
    return clean(dict(version=VERSION,health=evidence,decline_risk=risks,composite_health=None,composite_decline_risk=None,
            scenes=scenes,sentinel_method=dict(year=2022,clear_fraction=report['selection_meta']['clear_frac_threshold_used'],
            tide_gauge=report['tide_gauge_column'],tide_datum='As recorded by the gauge; not converted to habitat LAT',
            note='Seven May–August acquisitions, tide dose-response composite. No per-scene extent or comparable second-year output; no hectare decline is calculated.'),
            chronology=[dict(period='2002–2010',label='Historic NPWS survey synthesis',kind='historical',source='npws'),dict(period='1975–2019',label='Regional occurrence records; one event per scored site',kind='historical',source='biodiversity'),dict(period='2015–2024',label='Offshore waves and sparse regional SST',kind='proxy',source='cmems / sst'),dict(period='2022',label='Seven Sentinel-2 tide-response scenes',kind='observed',source='sentinel'),dict(period='2025',label='NPWS distribution package, not a survey',kind='historical',source='npws'),dict(period='2026',label='Prototype calculations; no new field observation',kind='modelled',source='project')],
            wave_monthly=monthly_waves(data),water_clarity=water_clarity(),geometry=geo,biodiversity=bio,priorities=priorities,
            context_layers={'galway':layer},reference_scenario=reference_scenario(data),
            missing_avoided_damage_inputs=['With/without habitat hazard at each receptor','Event probabilities','Asset exposure and valuations','Applicable damage functions','Validated nearshore wave transformation'],
            source_files=INPUTS))
