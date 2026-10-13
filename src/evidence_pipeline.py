"""Build auditable Cork evidence from local sources without altering raw data."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from collections import Counter

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from pyproj import Transformer, Geod
from rasterio.features import shapes
from rasterio.windows import from_bounds
from shapely.geometry import box, Point, LineString, Polygon, mapping, shape
from shapely.ops import unary_union, transform, polygonize, nearest_points

from coastal_physics import connected_groups, sample_bundle, path_status, avoided_damage, direction_vector
from coastal_cost_calculator import calculate, unit_rates, SOURCES as COST_SOURCES, LIMITS as COST_LIMITS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/overnight_20261013'
ITM=2157
TO_ITM=Transformer.from_crs(4326,ITM,always_xy=True).transform
TO_WGS=Transformer.from_crs(ITM,4326,always_xy=True).transform
AOI=[-9.42,51.45,-9.32,51.51]
AUDIT=ROOT/'outputs/sherkin_asset_audit/20261013_000940_959373'
NPWS=ROOT/'outputs/npws_source_review/20261013T020954_399007Z/layer_01/CO_Marine_Community_Types.shp'
OSM_CACHE=ROOT/'data/_sherkin_asset_audit_cache/49a3e38750e416e8a4b79a95697f37a192ad656477b7f35217523ebaba84492f.json'
OSM_COAST_COMPLETE=ROOT/'data/osm/overpass_1a75c6425bde.json'


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def clean(obj):
    if isinstance(obj,dict): return {str(k):clean(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple)): return [clean(v) for v in obj]
    if isinstance(obj,np.ndarray): return clean(obj.tolist())
    if isinstance(obj,(np.integer,)): return int(obj)
    if isinstance(obj,(float,np.floating)): return round(float(obj),8) if math.isfinite(obj) else None
    if isinstance(obj,(np.bool_,)): return bool(obj)
    return obj


def fc(items):
    return {'type':'FeatureCollection','features':items}


def feature(geom,props,projected=True):
    if projected: geom=transform(TO_WGS,geom)
    return {'type':'Feature','geometry':mapping(geom),'properties':clean(props)}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def build_coast():
    """OSM coastline segments, polygonised land only where edges close.

    Never infer a precise coastline from the coarse EMODnet raster. EMODnet
    is used only as an optional background depth layer and gap context.
    """
    raw=read_json(OSM_CACHE)['payload']; ways={}; source_dates=[]
    # The asset-query footprint clipped Sherkin's northern coastline. Complete
    # it from the pre-existing wider cache, keeping the newer audit ways first.
    for source in [raw,read_json(OSM_COAST_COMPLETE)]:
        source=source.get('payload',source)
        source_dates.append(source.get('osm3s',{}).get('timestamp_osm_base','unknown'))
        for e in source.get('elements',[]):
            if e.get('tags',{}).get('natural')=='coastline' and len(e.get('geometry',[]))>1:
                line=LineString([(p['lon'],p['lat']) for p in e['geometry']])
                if line.intersects(box(-9.47,51.43,-9.30,51.52)):
                    ways.setdefault(e['id'],line)
    lines=[transform(TO_ITM,p) for p in ways.values()]
    if not lines: raise ValueError('No OSM coastline in the local source cache')
    domain=transform(TO_ITM,box(-9.47,51.43,-9.30,51.52))
    coast=unary_union(lines).intersection(domain)
    faces=list(polygonize(unary_union([coast,domain.boundary])))
    # OSM coastal ways run with land to their left. Classify faces with the
    # original direction and require the opposite side to lie outside.
    left_right=[]
    for line in lines:
        c=list(line.coords)
        for a,b in zip(c[:-1],c[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1]; length=math.hypot(dx,dy)
            if length<1: continue
            m=Point((a[0]+b[0])/2,(a[1]+b[1])/2)
            left_right.append((Point(m.x-2*dy/length,m.y+2*dx/length),Point(m.x+2*dy/length,m.y-2*dx/length)))
    land=[]; unresolved=[]
    for p in faces:
        left=sum(p.contains(l) and not p.covers(r) for l,r in left_right)
        right=sum(p.contains(r) and not p.covers(l) for l,r in left_right)
        # A single land-side vote must never turn an incompletely enclosed
        # ocean face into land. Mixed votes flag incomplete/ambiguous topology.
        if left and not right:land.append(p)
        elif left and right:unresolved.append(p)
    land=unary_union(land)
    return land,coast,domain,{'land':fc([feature(land,{'source':'OSM coastline polygonisation'})]),
        'coast':fc([feature(coast,{'source':'OpenStreetMap contributors','date':raw['osm3s']['timestamp_osm_base']})]),
        'coverage':fc([feature(domain,{'status':'Coastline screening domain'})]),
        'source_date':source_dates,'coastline_ways':len(lines),
        'unresolved_faces':len(unresolved),
        'note':'OSM coastline is a geographic screening boundary. Intertidal shifts, missing coastline pieces and mapping errors remain possible.'}


def build_wave(centroid):
    path=ROOT/'data/cmems/ibi_wav_sherkin.nc'
    with xr.open_dataset(path) as ds:
        if ds.VHM0.attrs.get('units')!='m' or ds.VMDR.attrs.get('standard_name')!='sea_surface_wave_from_direction':
            raise ValueError('Unexpected wave variable units or direction convention')
        valid=ds.VHM0.notnull().sum('time').values
        xy=[]
        for iy,lat in enumerate(ds.latitude.values):
            for ix,lon in enumerate(ds.longitude.values):
                if valid[iy,ix]>0:
                    pt=Point(*TO_ITM(float(lon),float(lat)))
                    xy.append((centroid.distance(pt),iy,ix,float(lon),float(lat)))
        distance,iy,ix,lon,lat=min(xy)
        frame=ds[['VHM0','VMDR']].isel(latitude=iy,longitude=ix).to_dataframe().reset_index()
        frame=frame.dropna(subset=['VHM0','VMDR'])
        h=frame.VHM0.to_numpy(); a=np.radians(frame.VMDR.to_numpy()); weights=h*h
        s=float(np.sum(weights*np.sin(a))); c=float(np.sum(weights*np.cos(a)))
        frm=math.degrees(math.atan2(s,c))%360; bearing=(frm+180)%360
        annual=[]
        for year,g in frame.groupby(frame.time.dt.year):
            expected=8784 if pd.Timestamp(year=int(year),month=12,day=31).is_leap_year else 8760
            annual.append({'year':int(year),'hs_mean_m':float(g.VHM0.mean()),'hs_p95_m':float(g.VHM0.quantile(.95)),
                           'hours':len(g),'coverage_fraction':len(g)/expected})
        result={'status':'OFFSHORE_REANALYSIS','point':[lon,lat], 'distance_to_model_centroid_m':distance,
          'from_deg':frm,'travel_deg':bearing,'concentration':math.hypot(s,c)/float(weights.sum()),
          'hs_median_m':float(np.median(h)),'hs_p90_m':float(np.percentile(h,90)),
          'hs_p95_m':float(np.percentile(h,95)),'hs_max_m':float(h.max()),'hours':len(h),
          'first_date':str(frame.time.min())[:10],'last_date':str(frame.time.max())[:10],
          'annual':annual,'source':'CMEMS IBI_MULTIYEAR_WAV_005_006 / MFWAM-CY47R1',
          'note':'Offshore reanalysis, not an observed nearshore wave climate. Energy weighting uses Hs squared, not energy flux because period is absent.'}
    return result


def build_habitat_reference(cells):
    ref=gpd.read_file(NPWS,where="Site_Code = '000101'").to_crs(ITM)
    # Exact geometry + class duplicates only. Different ecological labels are
    # preserved and disagreements remain explicit.
    ref['_key']=ref.geometry.to_wkb(hex=True)+'|'+ref.Commun_Typ
    before=len(ref);ref=ref.drop_duplicates('_key')
    kelp=unary_union(ref.loc[ref.Commun_Typ.str.contains('Laminaria',case=False,na=False),'geometry'])
    rr=gpd.read_file(ROOT/'outputs/restoration/restoration_candidates.geojson').to_crs(ITM)
    r1=rr[(rr.restoration_class=='R1')&rr.geometry.intersects(transform(TO_ITM,box(*AOI)))].copy()
    centres=r1.geometry.centroid
    r1['historical_reference']=centres.apply(kelp.covers)
    r1['reference_area_fraction']=r1.geometry.intersection(kelp).area/r1.geometry.area
    items=[]
    for _,r in r1.iterrows():
        label='Historical habitat: revisit condition' if r.historical_reference else 'Resolve reference conflict: survey first'
        items.append(feature(r.geometry,{'action':label,'historical_overlap':bool(r.historical_reference),
            'overlap_fraction':r.reference_area_fraction,'suitability':float(r.suitability),'confidence':'LOW',
            'restoration_status':'NOT_CONFIRMED','source':'Old R1 candidate, reconciled with NPWS SSCO reference'}))
    footprints=[feature(p,{'community':row.Commun_Typ,'evidence':'HISTORICAL_REFERENCE',
                  'survey_context':'NPWS 2011 synthesis of 2002, 2004, 2009 and 2010 surveys; exact polygon survey date unavailable',
                  'release':'March 2025 distribution package'})
                for _,row in ref.iterrows() if 'Laminaria' in row.Commun_Typ
                for p in [row.geometry.intersection(transform(TO_ITM,box(*AOI))) ] if not p.is_empty]
    return {'layer':fc(footprints),'restoration':fc(items),'disputed_cells':len(r1),
      'historical_centre_matches':int(r1.historical_reference.sum()),'duplicates_removed':before-len(ref),
      'bed_centre_matches':sum(kelp.covers(p.centroid) for p in cells),
      'fpr_prior':.6345,'fpr_acceptance':.30,
      'fpr_note':'Legacy external test failed. The newly found reference conflicts make its labels questionable; 63.45% is not a revised error estimate for these cells. No retrained validation is claimed.',
      'survey_year_note':'Survey synthesis published 2011; 2025 is a package release, not contemporary ground truth.'}


def build_bathymetry():
    """Simplified, local cached EMODnet context, preserving coarse cell size."""
    with rasterio.open(ROOT/'data/emodnet/exposure_sherkin_baltimore.tif') as r:
        win=from_bounds(-9.44,51.44,-9.31,51.52,r.transform).round_offsets().round_lengths()
        a=r.read(1,window=win,masked=True); tr=r.window_transform(win)
        band=np.zeros(a.shape,dtype='uint8')
        for k,(lo,hi) in enumerate([(0,10),(10,20),(20,50),(50,1000)],1):
            band[(a< -lo)&(a>=-hi)&(~np.ma.getmaskarray(a))]=k
        features=[feature(shape(g),{'depth_band':int(v),'label':{1:'0–10 m',2:'10–20 m',3:'20–50 m',4:'>50 m'}[int(v)]},False)
                  for g,v in shapes(band,transform=tr) if v>0]
        return {'layer':fc(features),'resolution_degrees':r.res[0],
            'note':'Cached EMODnet DTM at 1/240 degree (about 290 x 464 m here). Context only; too coarse to resolve the habitat or a defence design.'}


def build_assets(cells,depths,wave,land,coast,domain,groups):
    # Read only OSM-origin geometry and an explicit public property whitelist.
    # OPW intersections and all flood-derived properties are excluded.
    g=gpd.read_file(AUDIT/'assets_INTERNAL_REVIEW.geojson').to_crs(ITM)
    core={'building','building_part','road_path','pier_quay_slipway','coastal_defence','power','parking','emergency','navigation','harbour_marina','public_service','telecom','water_waste_network'}
    features=[]; paths=[];group_stats={str(i+1):Counter() for i in range(len(groups))}
    for _,row in g.iterrows():
        classes=set(str(row.classes).split(';'))
        if not classes.intersection(core) or row.record_role=='context_boundary':continue
        candidates=[]
        for gi,ids in enumerate(groups,1):
            origin=unary_union([cells[i] for i in ids]).centroid
            target=nearest_points(origin,row.geometry)[1]
            status=path_status(origin,target,land,coast,wave['travel_deg'])
            path=LineString([origin,target])
            if not domain.covers(path):status['status']='OUTSIDE_COASTLINE_COVERAGE'
            if status['distance_m']>2000:status['status']='BEYOND_2KM_SCREEN'
            group_stats[str(gi)][status['status']]+=1
            candidates.append((status['status']=='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED',-status['distance_m'],gi,status,path))
        _,_,gi,status,line=max(candidates,key=lambda r:(r[0],r[1]))
        feature_props={'osm_id':row.osm_id,'name':str(row['name']) if pd.notna(row['name']) else '', 'kind':', '.join(sorted(classes.intersection(core))),
            'source':'OpenStreetMap contributors, ODbL','group_id':gi,**status,
            'avoided_damage_eur':None,'confidence':'LOW','note':'Mapped object, not a uniquely valued or independently damaged physical asset.'}
        features.append(feature(row.geometry,feature_props))
        if status['status']=='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED':
            paths.append(feature(line,{'osm_id':row.osm_id,'group_id':gi,'status':status['status']}))
    counts=Counter(f['properties']['status'] for f in features)
    return {'layer':fc(features),'paths':fc(paths),'counts':dict(counts),'mapped_records':len(features),
        'inventory_records':len(g),'by_group':{k:dict(v) for k,v in group_stats.items()},
        'direction_half_angle_deg':30,'radius_m':2000,'receptor_setback_m':30,
        'note':'A +/-30 degree straight-path screen and 30 m receptor setback are declared triage assumptions. OSM coverage is incomplete. Plausibility is not measured shelter or damage reduction.'}


def build_shore_screen(cells,wave,coast,land,domain):
    """Trace back from short shoreline pieces to actual habitat intersection.

    Sum only candidate alongshore pieces. Never substitute habitat envelope
    width or area/assumed-width for measured protective shoreline.
    """
    u=direction_vector(wave['travel_deg']); selected=[]; tested=0
    lines=list(coast.geoms) if hasattr(coast,'geoms') else [coast]
    allcells=unary_union(cells)
    for ln in lines:
        if ln.geom_type!='LineString': continue
        n=max(1,math.ceil(ln.length/20));step=ln.length/n
        for i in range(n):
            pt=ln.interpolate((i+.5)*step)
            if pt.distance(allcells)>2000:continue
            tested+=1
            ray=LineString([(pt.x-u[0]*2000,pt.y-u[1]*2000),(pt.x,pt.y)])
            hit=ray.intersection(allcells)
            if hit.is_empty:continue
            origin=nearest_points(pt,hit)[1]
            check=path_status(origin,pt,land,coast,wave['travel_deg'],tolerance_degrees=1,endpoint_allowance_m=5)
            if check['status']=='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED' and domain.covers(LineString([origin,pt])):
                seg=LineString([ln.interpolate(i*step),ln.interpolate((i+1)*step)])
                selected.append(feature(seg,{'status':'CANDIDATE_SHORELINE_UNVALIDATED','estimated_segment_m':step}))
    return {'layer':fc(selected),'candidate_frontage_m':sum(f['properties']['estimated_segment_m'] for f in selected),
            'screened_midpoints':tested,'step_m':20,'verified_protected_frontage_m':None,
            'note':'Midpoint quadrature of OSM shoreline within 2 km on the offshore bearing. Geometric candidate frontage only; no transformed shoreline hazard.'}


def build_sst():
    p=OUT/'inputs/oisst_point.csv'
    sparse=False
    if not p.exists():
        p=OUT/'inputs/oisst_snapshots.csv';sparse=True
    if not p.exists():
        return {'status':'UNAVAILABLE','annual':[],'note':'No compatible local SST subset is available. No temperature trend or measured loss is inferred.'}
    df=pd.read_csv(p,skiprows=[1]);df['time']=pd.to_datetime(df.time,utc=True)
    if not {'time','sst','latitude','longitude'}.issubset(df.columns): raise ValueError('SST schema mismatch')
    df=df[df.sst.notna()].copy()
    if len(df)<(100 if sparse else 365):return {'status':'INSUFFICIENT_COVERAGE','annual':[],'note':'Insufficient valid SST observations'}
    df['month']=df.time.dt.month
    clim=df.groupby('month').sst.mean()
    df['anomaly']=df.sst-df.month.map(clim)
    annual=[]
    for year,g in df.groupby(df.time.dt.year):
        expected=366 if pd.Timestamp(year=int(year),month=12,day=31).is_leap_year else 365
        annual.append({'year':int(year),'mean_c':float(g.sst.mean()),'anomaly_c':float(g.anomaly.mean()),
            'max_c':float(g.sst.max()),'days':len(g),'coverage_fraction':len(g)/expected})
    lon=float(df.longitude.iloc[0]);lat=float(df.latitude.iloc[0]); cx,cy=TO_ITM(lon,lat)
    bx,by=TO_ITM(-9.4051,51.4652)
    return {'status':'REGIONAL_SATELLITE_ANALYSIS','source':'NOAA OISST v2.1 final, 0.25 degree',
      'point':[lon,lat],'distance_to_bed_m':math.hypot(cx-bx,cy-by),'annual':annual,
      'baseline':f'{df.time.dt.year.min()}–{df.time.dt.year.max()} calendar-month climatology',
      'sampling':'Every 30th day; annual sample averages, not annual means' if sparse else 'Daily; annual means',
      'n_days':len(df),'note':('Sparse snapshots, not monthly means. ' if sparse else '')+'A regional alternative to unavailable local Copernicus SST. Surface satellite/in-situ analysis, not seabed temperature. Anomalies describe this record; no physiological stress threshold, marine-heatwave classification or kelp-loss attribution is asserted.'}


def build(base):
    OUT.mkdir(parents=True,exist_ok=True)
    kg=gpd.read_file(ROOT/'outputs/valuation/step3b2_flood_check.gpkg',layer='kelp_cells')
    if kg.crs.to_epsg()!=ITM:raise ValueError('Habitat geometry must use EPSG:2157')
    cells=list(kg.geometry.buffer(25,cap_style='square')); depths=kg.depth_m.to_numpy()
    groups=connected_groups(cells,tolerance_m=2)
    centroid=unary_union(cells).centroid
    wave=build_wave(centroid)
    land,coast,domain,coastal=build_coast()
    refs=build_habitat_reference(cells)
    physical=sample_bundle(cells,depths,wave['travel_deg'],land=land)
    physical['method']='Dubi & Torum laboratory coefficients, linearly interpolated in depth; actual polygon chords on parallel rays every <=5 m'
    physical['fitted_crosscheck']=sample_bundle(cells,depths,wave['travel_deg'],method='fitted',land=land)
    physical['direction_sensitivity']=[{'offset_deg':d,**sample_bundle(cells,depths,wave['travel_deg']+d,land=land)} for d in [-30,-15,0,15,30]]
    physical['tide_sensitivity']=[{'water_level_above_LAT_m':h,**sample_bundle(cells,depths,wave['travel_deg'],water_level_m=h,land=land)} for h in [0,1,2,3]]
    physical['conditions']=['Assumed living L. hyperborea with laboratory-like density and morphology; neither confirmed locally.',
        'Cell depths are INFOMAR model inputs referred to LAT. No event-specific water level or period is available.',
        'Published experiment: 4–10 m water depth. A domain violation gives missing values, never zero.',
        'Refraction, diffraction, shoaling, breaking, bottom friction and storm surge are not simulated.',
        'This is a uniform-incident-energy geometric illustration across assumed habitat, not a nearshore prediction or a confidence interval.']
    assets=build_assets(cells,depths,wave,land,coast,domain,groups)
    shore=build_shore_screen(cells,wave,coast,land,domain)
    group_features=[];cell_features=[]
    for gi,ids in enumerate(groups,1):
        geom=unary_union([cells[i] for i in ids])
        phys=sample_bundle([cells[i] for i in ids],depths[ids],wave['travel_deg'],land=land)
        group_features.append(feature(geom,{'group_id':gi,'cells':len(ids),'area_ha':geom.area/10000,
            'depth_min_m':float(min(depths[ids])),'depth_max_m':float(max(depths[ids])),
            'evidence':'MODELLED_UNVALIDATED',**phys,'avoided_damage_eur':None,
            'plausible_asset_records':assets['by_group'][str(gi)].get('DIRECTIONALLY_PLAUSIBLE_UNVALIDATED',0)}))
        for i in ids:
            cell_features.append(feature(cells[i],{'cell_id':i+1,'group_id':gi,'depth_m_LAT':float(depths[i]),'evidence':'MODELLED_UNVALIDATED'}))
    area=unary_union(cells).area
    legacy=read_json(ROOT/'outputs/coastal_cost_calculation/calculation.json')
    energy=legacy['inputs']['energy_reduction_fraction']
    costs={'rates':unit_rates(),'sources':COST_SOURCES,'limitations':COST_LIMITS,
        'default':calculate(area,100,energy,.04,50),
        'width_scenarios':[calculate(area,w,energy,.04,50) for w in [50,100,150,200]],
        'model_energy_fraction':physical['energy_fraction'],'scale_parameter_is_cost_sensitivity':True,
        'replacement_conditions':{'service_equivalence':'NOT_DEMONSTRATED','least_cost':'NOT_DEMONSTRATED','societal_demand':'NOT_DEMONSTRATED'}}
    # Source loader verification is retained, but no obsolete monetary claims
    # or nationally scaled fisheries numbers are allowed into habitat popups.
    base.pop('locked',None)
    if base.get('france'):
        base['france']={k:base['france'][k] for k in ['site','town','habitat_ha','cells_in_band','licence_note']}
    if base.get('nutrient'):
        base['nutrient']={'status':'ARCHIVED_UNVALIDATED_SERVICE_SCENARIO','note':'No permanent local nitrogen removal or economic benefit is established. Historical calculations remain in the original research outputs.'}
    from run_segment import run_segment
    result={**base,'schema_version':2,'build_date':'2026-10-13','title':'Seeing the Invisible Shield: Valuing Coastal Habitats as Natural Infrastructure',
        'site':{'id':'sherkin_baltimore','name':'Sherkin Island / Roaringwater Bay','region':'West Cork, Ireland',
                'bbox':AOI,'area_ha':area/10000,'cell_count':len(cells),'group_count':len(groups),
                'selection':'Retained original Cork pilot because satellite, depth, offshore wave and historical survey evidence coexist. No selection on positive monetary output.',
                'grouping_tolerance_m':2},
        'coastline':coastal,'wave':wave,'physical':physical,'historical':refs,
        'groups':fc(group_features),'cells':fc(cell_features),'assets':assets,'shoreline':shore,
        'bathymetry':build_bathymetry(),'sst':build_sst(),'costs':costs,'avoided_damage':avoided_damage(),
        'transfer':run_segment('mizen_outer'),
        'legacy':{'wave_height_pct':7.9,'wave_energy_pct':15.2,
                  'note':'Historical grid-axis/interpolated-direction baseline retained for audit. It included paths through other cells and differs from the new domain-limited polygon-ray illustration.'},
        'measured_kelp_decline':{'status':'NOT_MEASURABLE','percent':None,'reason':'No comparable repeat extent, biomass or density surveys of this bed. EPA WFD is a regional water-quality assessment.'}}
    result=clean(result)
    return result
