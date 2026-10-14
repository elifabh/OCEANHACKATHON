"""Offline geometry cache for a reproducible, interactive screening assessment.

Only lengths and depths travel to the browser. Transmission is recalculated
there for each water-level/coefficient scenario, never a reused percentage.
No economic service value follows from a geometric shoreline connection.
"""
from __future__ import annotations
import math
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, LineString, box, shape
from shapely.ops import unary_union, transform, nearest_points
from coastal_physics import direction_vector, projected_intervals, path_status, connected_groups, sample_bundle
from evidence_pipeline import ROOT, NPWS, ITM, TO_ITM, feature, fc, build_coast, clean


def ray_inputs(cells, depths, bearing, land, spacing=5):
    u=direction_vector(bearing);v=np.array([u[1],-u[0]])
    centre=unary_union(cells).centroid;along=np.dot([centre.x,centre.y],u)
    rows=[]
    for lo,hi in projected_intervals(cells,bearing):
        n=max(1,math.ceil((hi-lo)/spacing));width=(hi-lo)/n
        for q in range(n):
            xy=along*u+(lo+(q+.5)*width)*v
            line=LineString([xy-20000*u,xy+20000*u]);hits=[];positions=[]
            for cell,depth in zip(cells,depths):
                inter=line.intersection(cell)
                if inter.length<1e-6:continue
                hits.append({'length_m':inter.length,'depth_m_LAT':float(depth)})
                parts=list(inter.geoms) if hasattr(inter,'geoms') else [inter]
                positions.extend(line.project(Point(c)) for p in parts for c in p.coords)
            blocked=False
            if positions:
                span=LineString([line.interpolate(min(positions)),line.interpolate(max(positions))])
                blocked=span.intersection(land).length>1
            rows.append({'weight_m':width,'land_blocked':blocked,'segments':hits})
    return rows


def shore_inputs(cells,bearing,coast,land,domain,spacing):
    u=direction_vector(bearing);bed=unary_union(cells);features=[]
    lines=list(coast.geoms) if hasattr(coast,'geoms') else [coast]
    for ln in lines:
        if ln.geom_type!='LineString' or ln.distance(bed)>2000:continue
        n=max(1,math.ceil(ln.length/spacing));step=ln.length/n
        for i in range(n):
            pt=ln.interpolate((i+.5)*step)
            if pt.distance(bed)>2000:continue
            ray=LineString([(pt.x-u[0]*2000,pt.y-u[1]*2000),(pt.x,pt.y)])
            hit=ray.intersection(bed)
            if hit.is_empty:continue
            origin=nearest_points(pt,hit)[1]
            check=path_status(origin,pt,land,coast,bearing,tolerance_degrees=1,endpoint_allowance_m=5)
            if check['status']=='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED' and domain.covers(LineString([origin,pt])):
                seg=LineString([ln.interpolate(i*step),ln.interpolate((i+1)*step)])
                features.append(feature(seg,{'length_m':step,'status':'GEOMETRIC_CANDIDATE_NOT_VERIFIED_PROTECTED'}))
    return {'length_m':sum(f['properties']['length_m'] for f in features),'step_m':spacing,'layer':fc(features)}


def cork_screen():
    c=pd.read_csv(ROOT/'outputs/national_candidate_table.csv');c=c[c.county=='Cork'].copy()
    # Reconcile against the newer SSCO source rather than repeating old absence labels.
    ref=gpd.read_file(NPWS).to_crs(ITM)
    ref=ref[ref.Commun_Typ.str.contains('Laminaria',case=False,na=False)]
    points=gpd.GeoSeries([Point(*TO_ITM(r.lon,r.lat)) for r in c.itertuples()],crs=ITM)
    domain=unary_union(points.buffer(1100).tolist())
    ref=ref[ref.intersects(domain)]
    kelp=unary_union(ref.geometry.tolist())
    rows=[]
    for (_,r),p in zip(c.iterrows(),points):
        area=kelp.intersection(p.buffer(1000)).area/10000
        rows.append({'cluster':int(r.cluster),'place':str(r.nearest_place),'lon':r.lon,'lat':r.lat,
          'historical_Laminaria_ha_within_1km':area,'archive_fetch_strict_pass':bool(r.pass_fetch_strict),
          'archive_evidence_class':str(r.evidence_class),'current_habitat_validated':False,
          'status':'NEEDS_LOCAL_DEPTH_SPECIES_WAVE_AND_ASSET_VALIDATION',
          'note':'Historical proximity is not a current bed or a wave-path connection. Archived negative labels superseded where SSCO overlap is present.'})
    pred=pd.read_csv(ROOT/'outputs/model/suitability_multisite_predictions.csv')
    import json
    threshold=json.loads((ROOT/'outputs/model/model_multisite_report.json').read_text())['operating_threshold']
    aois=[]
    for name,g in pred.groupby('aoi'):
        a=g[g.assessed==1];pos=a[a.suitability>=threshold];eligible=pos[pos.depth_m.between(4,10)]
        status={'inner_roaringwater':'SPECIES_AND_EXPOSURE_MISMATCH','mizen_outer':'NO_THRESHOLD_PASSING_ASSESSED_HABITAT','sherkin_baltimore':'RETAIN_EXPOSED_SEVEN_CELL_PILOT'}[name]
        aois.append({'site':name,'grid_cells':len(g),'assessed_cells':len(a),'above_threshold':len(pos),'depth_eligible':len(eligible),'status':status})
    gap=pd.read_csv(ROOT/'outputs/habitat_gap_model_cells.csv');near=gap[gap.aoi=='gap_westcork_kerry_sw_31'];positive=near[(near.in_training_range==1)&(near.suitability>=threshold)]
    cape=json.loads((ROOT/'outputs/visual_v2_20261014/inputs/cape_clear_screen.json').read_text())
    cape_summary={k:cape[k] for k in ['site','location','historical_area_ha_within_1km','requested_depth_points','valid_depth_points','depth_eligible_points','sources']}
    cape_summary.update(groups=len(cape['groups']),incoming_blocked_groups=sum(r['incoming_2km_land_blocked'] for r in cape['groups']),
        status='NO_DIRECT_OFFSHORE_WAVE_PATH_IN_FOCUSED_SCREEN',
        limitation='Generic historical Laminaria; point depths do not define a current bed or confirm species/density. Local wave transformation and source datum verification required.')
    return clean({'scope':'103 existing Cork coastal building clusters; not a complete county census',
      'clusters':rows,'aois':aois,'threshold':threshold,
      'cape_clear':cape_summary,
      'firkeel':{'candidate_cells_in_gap_AOI':len(positive),'depth_min_m':positive.depth_m.min(),'depth_max_m':positive.depth_m.max(),
        'eligible_4_to_10m':int(positive.depth_m.between(4,10).sum()),'mapped_asset_records':81,
        'status':'NO_SUPPORTED_ATTENUATION_IN_AVAILABLE_DEPTH_DOMAIN'},
      'decision':'Retain the exposed Roaringwater seven-cell pilot for conditional within-habitat calculations, not demonstrated asset protection. Cape Clear has historical Laminaria and 40 depth-eligible points, but all 11 sampled groups have a land-blocked incoming straight wave path. Firkeel fails the depth domain; inner Roaringwater has a species/exposure mismatch. None establishes a validated habitat-wave-asset benefit chain.',
      'priorities':['Review SSCO habitat evidence near other Cork clusters with a marine ecologist.','Acquire current species/density and nearshore spectra before applying this laboratory model at another site.','Use Firkeel as a data-acquisition example, not a positive valuation.']})


def build_parametric(payload):
    kg=gpd.read_file(ROOT/'outputs/valuation/step3b2_flood_check.gpkg',layer='kelp_cells').to_crs(ITM)
    cells=list(kg.geometry.buffer(25,cap_style='square'));depths=kg.depth_m.to_numpy();groups=connected_groups(cells)
    land,coast,domain,_=build_coast();base=payload['wave']['travel_deg'];scopes={}
    assets=[(f['properties']['osm_id'],transform(TO_ITM,shape(f['geometry']))) for f in payload['assets']['layer']['features']]
    for group,ids in [(0,list(range(len(cells)))),*[(i+1,g) for i,g in enumerate(groups)]]:
        local=[cells[i] for i in ids];dd=depths[ids];directions={}
        for offset in [-30,-15,0,15,30]:
            bearing=(base+offset)%360
            shores={str(step):shore_inputs(local,bearing,coast,land,domain,step) for step in [10,20,40]}
            from collections import Counter
            counts=Counter();passes=[];asset_rows=[]
            components=connected_groups(local)
            for osm_id,geometry in assets:
                choices=[]
                for indices in components:
                    origin=unary_union([local[i] for i in indices]).centroid;target=nearest_points(origin,geometry)[1]
                    check=path_status(origin,target,land,coast,bearing)
                    if not domain.covers(LineString([origin,target])):check['status']='OUTSIDE_COASTLINE_COVERAGE'
                    if check['distance_m']>2000:check['status']='BEYOND_2KM_SCREEN'
                    choices.append((check['status']=='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED',-check['distance_m'],check,origin,target))
                _,_,check,origin,target=max(choices,key=lambda r:(r[0],r[1]))
                counts[check['status']]+=1;asset_rows.append({'osm_id':osm_id,**check})
                if check['status']=='DIRECTIONALLY_PLAUSIBLE_UNVALIDATED':passes.append(feature(LineString([origin,target]),{'osm_id':osm_id,'status':check['status']}))
            upstream=[];u=direction_vector(bearing)
            for cell in local:
                pt=cell.centroid;line=LineString([(pt.x-2000*u[0],pt.y-2000*u[1]),(pt.x-2*u[0],pt.y-2*u[1])])
                upstream.append({'land_blocked':line.intersection(land).length>1 or line.intersects(coast),'inside_coastline_domain':domain.covers(line)})
            directions[str(offset)]={'bearing_deg':bearing,'rays':ray_inputs(local,dd,bearing,land),
              'shoreline':shores['10'],'shore_length_sensitivity_m':{k:v['length_m'] for k,v in shores.items()},
              'asset_screen':{'counts':dict(counts),'records':asset_rows,'paths':fc(passes),'note':'Direction-specific straight geographic screen, not a flood-hazard or beneficiary estimate.'},
              'incoming_screen':{'cell_centres':len(upstream),'land_blocked':sum(x['land_blocked'] for x in upstream),'outside_domain':sum(not x['inside_coastline_domain'] for x in upstream),'distance_m':2000,'note':'Straight upstream rays at cell centres, not a local wave transformation.'},
              'baseline':sample_bundle(local,dd,bearing,land=land)}
        scopes[str(group)]={'area_m2':unary_union(local).area,'cells':len(local),'directions':directions}
    return clean({'version':'1.0','method_source':'https://doi.org/10.1061/9780784402429.203',
      'coefficient_depths_m':[4,6,8,10],'height_damping_per_m':[.0094,.0032,.0014,.0005],
      'geometry_crs':'EPSG:2157','ray_spacing_max_m':5,'scopes':scopes,
      'method':'Hout/Hin = exp(-sum(k(depth + water level) * actual polygon chord length)); energy transmission = exp(-2*tau). Weight rays across the union-projected footprint.',
      'shoreline_method':'Trace back from OSM coastal midpoint segments at <=10 m, require actual habitat intersection and no earlier land crossing, maximum 2 km. Candidate length only; sensitivity at <=20 and <=40 m.',
      'economic_method':'Candidate shoreline length * user-selected engineering unit cost * independent cost share. Annualise using the capital recovery factor. No conversion of wave-energy percentage to euros.',
      'validity':{'equivalent_service':False,'least_cost':False,'demand_demonstrated':False,'ecosystem_service_value_eur':None,'avoided_damage_eur_per_year':None},
      'uncertainty':'Direction, tide, coefficient and shoreline discretisation are scenarios, not probabilities or confidence intervals. Species/density, local waves and construction design remain unvalidated.'})
