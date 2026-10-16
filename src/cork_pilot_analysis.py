"""Offline, reproducible Cork mapping experiment with explicit evidence classes.

Usage: .venv/Scripts/python.exe src/cork_pilot_analysis.py
Inputs are read-only. Output is confined to outputs/cork_pilot_20261015.
No satellite feature or NPWS polygon is a contemporary species observation.
"""
from __future__ import annotations
from pathlib import Path
import json
import hashlib
import platform
import warnings
import importlib.metadata
from collections import Counter
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.transform import rowcol
from pyproj import Transformer
from shapely.geometry import box, Point, shape, mapping
from shapely.ops import transform, unary_union
from scipy.ndimage import binary_dilation
from scipy.spatial import cKDTree
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'outputs/cork_pilot_20261015'
ITM = 2157
TO_ITM = Transformer.from_crs(4326, ITM, always_xy=True).transform
TO_WGS = Transformer.from_crs(ITM, 4326, always_xy=True).transform
BBOX = [-9.405,51.460,-9.355,51.495]
DOMAIN = transform(TO_ITM, box(*BBOX))
CONTEXT_BBOX = [-9.42,51.45,-9.355,51.51]
CONTEXT_DOMAIN = transform(TO_ITM,box(*CONTEXT_BBOX))
OLD_REF = ROOT/'data/npws/gis_files/21 NPWSArticle17Habitat.shp'
SSCO = ROOT/'outputs/npws_source_review/20261013T020954_399007Z/layer_01/CO_Marine_Community_Types.shp'
GENERA = ['Laminaria','Saccharina','Saccorhiza','Fucus','Ascophyllum']
SEED = 20261015


def clean(x):
    if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple,np.ndarray)): return [clean(v) for v in x]
    if isinstance(x,(np.bool_,)): return bool(x)
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(float,np.floating)): return float(x) if np.isfinite(x) else None
    return x


def save(name, value):
    (OUT/name).write_text(json.dumps(clean(value),indent=2,allow_nan=False),encoding='utf-8')


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(2**20),b''): h.update(chunk)
    return h.hexdigest()


def feature(g, **props):
    return {'type':'Feature','geometry':mapping(transform(TO_WGS,g)),'properties':clean(props)}


def geojson(name, features):
    save(name,{'type':'FeatureCollection','features':features})


def source_hashes():
    sources=[p for p in (ROOT/'src').rglob('*') if p.is_file() and '__pycache__' not in str(p)
             and not p.name.startswith('cork_pilot')]
    sources += [p for p in (ROOT/'outputs/map').rglob('*') if p.is_file()]
    sources += list(OLD_REF.parent.glob(OLD_REF.stem+'.*')) + list(SSCO.parent.glob(SSCO.stem+'.*'))
    sources += [ROOT/p for p in ['CLAUDE.md','BASLA_BURADAN_TR.md','docs/overnight_20261013/MASTER_BRIEF.md',
               'outputs/candidate_scenes.csv','outputs/obis_raw_occurrences.json',
               'outputs/intertidal/pixels_sherkin_baltimore_7scenes.csv',
               'outputs/intertidal/report_sherkin_baltimore_7scenes.json',
               'outputs/intertidal/extent_sherkin_baltimore_7scenes.geojson',
               'outputs/model/suitability_multisite_predictions.csv','data/cmems/ibi_wav_sherkin.nc']]
    return {str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(set(sources))}


def refs():
    a=gpd.read_file(OLD_REF,bbox=(-9.55,51.42,-9.30,51.56),fid_as_index=True).to_crs(ITM)
    b=gpd.read_file(SSCO,where="Site_Code = '000101'",fid_as_index=True).to_crs(ITM)
    info={}
    for key,g,col in [('article17',a,'Community'),('ssco',b,'Commun_Typ')]:
        g['label']=g[col].str.replace(r'\s+',' ',regex=True).str.strip()
        g['source_row']=g.index.astype(str)
        g.geometry=g.geometry.make_valid()
        g['dedupe']=g.geometry.normalize().to_wkb(hex=True)+'|'+g.label
        info[key]={'rows_before':len(g),'exact_geometry_class_duplicates':int(g.dedupe.duplicated().sum()),
                   'native_crs':str(gpd.read_file(OLD_REF if key=='article17' else SSCO,rows=1).crs)}
    a=a.drop_duplicates('dedupe'); b=b.drop_duplicates('dedupe')
    rows=[]; summary={}
    for name,domain in [('pilot',DOMAIN),('sherkin_baltimore',transform(TO_ITM,box(-9.42,51.45,-9.32,51.51)))]:
        ag={k:unary_union(s.geometry).intersection(domain) for k,s in a.groupby('label')}
        bg={k:unary_union(s.geometry).intersection(domain) for k,s in b.groupby('label')}
        for ak,av in ag.items():
            for bk,bv in bg.items():
                overlap=av.intersection(bv).area/10000
                if overlap>1e-8: rows.append({'domain':name,'article17':ak,'ssco':bk,'overlap_ha':overlap})
        ka=ag.get('Laminaria-dominated reef',Point().buffer(0))
        kb=bg.get('Laminaria dominated communities',Point().buffer(0))
        conflict=ag.get('Faunal turf reef',Point().buffer(0)).intersection(kb)
        summary[name]={'article17_laminaria_ha':ka.area/1e4,'ssco_laminaria_ha':kb.area/1e4,
                       'laminaria_intersection_ha':ka.intersection(kb).area/1e4,
                       'article17_faunal_vs_ssco_laminaria_ha':conflict.area/1e4,
                       'fraction_ssco_laminaria_labelled_faunal_by_article17':conflict.area/kb.area if kb.area else None,
                       'article17_classes_ha':{k:v.area/1e4 for k,v in ag.items()},
                       'ssco_classes_ha':{k:v.area/1e4 for k,v in bg.items()}}
        if name=='pilot':
            geojson('npws_disagreement.geojson',[feature(conflict,evidence='REFERENCE_LABEL_CONFLICT',
                    article17='Faunal turf reef',ssco='Laminaria dominated communities',
                    interpretation='Shared historical source; not evidence of ecological change')])
    pd.DataFrame(rows).to_csv(OUT/'npws_crosswalk.csv',index=False)
    aa=a[a.intersects(DOMAIN)]; bb=b[b.intersects(DOMAIN)]
    info['article17']['pilot_sources']=aa.Source.fillna('').unique().tolist()
    info['article17']['pilot_references']=aa.Reference.fillna('').unique().tolist()
    # Pairwise near-identical geometry with contradictory classes is stronger
    # evidence of a recoding issue than aggregate area mismatch alone.
    pairs=[]
    for _,r in aa[aa.label.eq('Faunal turf reef')].iterrows():
        for _,s in bb[bb.label.eq('Laminaria dominated communities')].iterrows():
            inter=r.geometry.intersection(s.geometry).area
            if inter:
                iou=inter/r.geometry.union(s.geometry).area
                if iou>.5: pairs.append({'article17_row':r.source_row,'ssco_row':s.source_row,
                                        'whole_polygon_iou':iou,'intersection_ha':inter/1e4})
    pd.DataFrame(pairs).to_csv(OUT/'npws_conflicting_polygon_pairs.csv',index=False)
    info.update({'area_comparison':summary,'contradictory_pairs_iou_over_0_5':len(pairs),
                 'contradictory_pairs_iou_over_0_95':sum(p['whole_polygon_iou']>.95 for p in pairs),
                 'independent_sources':False,
                 'cause':'Shared 2011 provenance and near-identical geometry indicate classification/translation disagreement; exact processing history is unavailable. Do not infer loss or declare either current truth.',
                 'survey_years_in_2011_synthesis':[2002,2004,2009,2010],
                 'polygon_specific_survey_dates_available':False,
                 'publication_note':'NPWS 2011 p19 calls the Laminaria distribution an interpolation; polygons are not direct pixel observations.',
                 'source_url':'https://www.npws.ie/sites/default/files/publications/pdf/000101_Roaringwater%20Bay%20and%20Islands%20SAC%20Marine%20Supporting%20Doc_V1.pdf'})
    save('npws_audit.json',info)
    items=[]
    for source,g in [('NPWS Article17 / Reef Inventory 2023',aa),('NPWS SSCO March 2025 package',bb)]:
        for _,r in g[g.label.str.contains('Laminaria',case=False)].iterrows():
            items.append(feature(r.geometry.intersection(DOMAIN),evidence='HISTORICAL_KELP_REFERENCE',
                source=source,source_row=r.source_row,community=r.label,survey_date=None,
                date_context='2011 synthesis of earlier surveys; distribution package date is not survey date',
                current_presence_confirmed=False))
    geojson('historical_kelp_reference.geojson',items)
    return a,b,info


def observations():
    raw=pd.DataFrame(json.loads((ROOT/'outputs/obis_raw_occurrences.json').read_text()))
    d=raw[raw.genus.isin(GENERA)|raw.scientificName.eq('Laminariales')].copy()
    d=d[d.decimalLongitude.between(BBOX[0],BBOX[2]) & d.decimalLatitude.between(BBOX[1],BBOX[3])]
    d=d.drop_duplicates('occurrenceID')
    d['date_day']=d.eventDate.astype(str).str[:10]
    d['event_group']=d.decimalLongitude.round(6).astype(str)+'|'+d.decimalLatitude.round(6).astype(str)+'|'+d.date_day
    fields=['occurrenceID','event_group','scientificName','date_day','eventDate','decimalLongitude','decimalLatitude',
            'datasetName','dataset_id','eventID','coordinateUncertaintyInMeters','minimumDepthInMeters',
            'maximumDepthInMeters','references','license']
    d[fields].to_csv(OUT/'dated_observations.csv',index=False)
    events=[]
    for key,s in d.groupby('event_group'):
        r=s.iloc[0]; taxa=sorted(set(s.scientificName))
        intertidal=s.genus.isin(['Fucus','Ascophyllum']).any()
        date=str(r.date_day)
        uncertainty=pd.to_numeric(s.coordinateUncertaintyInMeters,errors='coerce').max()
        events.append({'event_group':key,'date':date,'lon':r.decimalLongitude,'lat':r.decimalLatitude,
            'taxa':taxa,'records':len(s),'dataset':str(r.datasetName),'dataset_id':str(r.dataset_id),
            'uncertainty_m':float(uncertainty) if np.isfinite(uncertainty) else None,
            'kind':'intertidal_macroalgae_presence' if intertidal else 'kelp_presence_subtidal_or_unspecified',
            'post_2011':date[:4].isdigit() and int(date[:4])>2011,
            'source_independence': 'Distinct post-2011 collection event, reserved from training; complete SSCO lineage unavailable, so full source independence is not proven' if date[:4].isdigit() and int(date[:4])>2011
               else 'Earlier than NPWS synthesis; reuse cannot be excluded',
            'point':Point(*TO_ITM(r.decimalLongitude,r.decimalLatitude))})
    geojson('historical_observation_events.geojson',[feature(e['point'],**{k:v for k,v in e.items() if k!='point'}) for e in events])
    return events


def legacy():
    d=pd.read_csv(ROOT/'outputs/intertidal/pixels_sherkin_baltimore_7scenes.csv')
    pred=np.zeros(len(d),dtype=int)
    pred[d.ndvi_min>=.25]=1
    pred[d.ndvi_max<=-.10]=2
    pred[(d.ndvi_max>=.20)&(d.ndvi_min<=0)&(d.slope<0)]=3
    assert (d.n_obs==7).all()
    d['recomputed_class']=pred
    d['class_matches']=pred==d.cls
    d.to_csv(OUT/'legacy_replay_pixels.csv',index=False)
    g=gpd.read_file(ROOT/'outputs/intertidal/extent_sherkin_baltimore_7scenes.geojson').to_crs(ITM)
    geom=unary_union(g.geometry).intersection(DOMAIN)
    geojson('satellite_macroalgae_legacy_2022.geojson',[feature(geom,evidence='SATELLITE_MACROALGAE_PROXY',
         dates='May-August 2022',method='Existing L1C NDVI-tide rule',species=None,field_validated=False)])
    result={'pixels_replayed':len(d),'class_matches':int((pred==d.cls).sum()),
            'rule':'NDVI max >= 0.20, NDVI min <= 0, slope < 0; all 7 observations retained',
            'pilot_area_ha':geom.area/10000,'validation':'Internal arithmetic replay only; classes were selected by these same image rules.',
            'tile_provenance_issue':'3 of 7 archived requested IDs are T29UMS, while original code filters T29UMT then falls back by date. Exact selected image IDs were not persisted. New acquisition records actual T29UMT IDs.',
            'cloud_mask':'Original Cloud Score Plus cs >=0.6; cannot reconstruct this mask from L2A SCL.',
            'pixel_summary_has_per_scene_values':False}
    save('legacy_replay.json',result)
    return geom,result


def images():
    cache=OUT/'imagery_context'
    manifest=json.loads((cache/'manifest.json').read_text())
    data=[]; masks=[]; qa=[]
    for m in manifest:
        with rasterio.open(cache/f"{m['date']}.tif") as ds:
            dn=ds.read(); profile=ds.profile.copy(); affine=ds.transform
        refl=np.stack([(dn[i].astype(float)+m['reflectance'][b]['offset_dn'])*m['reflectance'][b]['scale']
                       for i,b in enumerate(['B02','B03','B04','B08','B11'])])
        scl=dn[5]
        cloud=np.isin(scl,[1,3,8,9,10,11])
        cloud=binary_dilation(cloud,iterations=3)
        # Conservative shared mask: no interpretation of SCL water as absence.
        clear=np.isin(scl,[4,5,6]) & ~cloud & np.all(dn[:5]>0,axis=0)
        valid=clear & (refl[2]>=0) & (refl[3]>=0) & ((refl[2]+refl[3])>1e-6)
        data.append(refl); masks.append(valid)
        qa.append({'date':m['date'],'actual_scene':m['actual_item_id'],'processing_baseline':m['processing_baseline'],
            'tide_m_LAT':m['tide_m_LAT'],'clear_fraction':float(clear.mean()),
            'valid_reflectance_fraction':float(valid.mean()),
            'clear_pixels_excluded_negative_red_or_nir':int((clear & ~valid).sum()),
            'scl_counts':dict(Counter(scl.flatten().tolist()))})
    cube=np.stack(data); valid=np.logical_and.reduce(masks)
    shape_=valid.shape
    inside=rasterize([(DOMAIN,1)],out_shape=shape_,transform=affine,dtype='uint8').astype(bool)
    context=rasterize([(CONTEXT_DOMAIN,1)],out_shape=shape_,transform=affine,dtype='uint8').astype(bool)
    valid &= context
    with np.errstate(divide='ignore',invalid='ignore'):
        ndvi=(cube[:,3]-cube[:,2])/(cube[:,3]+cube[:,2])
        ndwi=(cube[:,1]-cube[:,3])/(cube[:,1]+cube[:,3])
    ndvi=np.clip(ndvi,-1,1)
    tide=np.array([m['tide_m_LAT'] for m in manifest]); weights=tide-tide.mean()
    ymean=np.mean(ndvi,axis=0)
    sxy=np.sum(weights[:,None,None]*ndvi,axis=0)
    syy=np.sum((ndvi-ymean)**2,axis=0)
    slope=sxy/np.sum(weights**2)
    with np.errstate(divide='ignore',invalid='ignore'):
        corr=sxy/np.sqrt(np.sum(weights**2)*syy)
    valid &= (syy>0) & np.isfinite(slope) & np.isfinite(corr)
    minimum=ndvi.min(axis=0); maximum=ndvi.max(axis=0)
    candidate=valid & (maximum>=.2)&(minimum<=0)&(slope<0)
    # Same masked image feature space for the threshold rule and RF comparison.
    names=[]; feat=[]
    for i,band in enumerate(['B02','B03','B04','B08','B11']):
        for stat,fn in [('min',np.min),('median',np.median),('max',np.max)]:
            names.append(f'{band}_{stat}'); feat.append(fn(cube[:,i],axis=0))
    for name,a in [('ndvi_min',minimum),('ndvi_max',maximum),('ndvi_mean',ymean),('ndvi_tide_slope',slope),
                   ('ndvi_tide_corr',corr),('ndwi_median',np.median(ndwi,axis=0))]:
        names.append(name); feat.append(a)
    features=np.stack(feat,axis=-1)
    valid &= np.all(np.isfinite(features),axis=-1)
    candidate &= valid
    coverage={'scene_qa':qa,'total_pilot_grid_cells':int(inside.sum()),'all_7_valid_cells':int((valid&inside).sum()),
              'all_7_valid_fraction':float((valid&inside).sum()/inside.sum()),'l2a_candidate_ha':(candidate&inside).sum()/100,
              'training_context_bbox':CONTEXT_BBOX,'training_context_valid_cells':int(valid.sum()),
              'mask':'SCL 4/5/6 only; cloud/shadow/snow dilation 30m; nonnegative red and NIR; all seven dates.',
              'processing_comparison':'L2A/SCL is a declared sensitivity run, not an exact L1C/Cloud Score Plus replay.',
              'tide_note':'Existing Union Hall measured water levels reused; local spatial phase/time mismatch unquantified.',
              'feature_names':names,'native_resolution_note':'B11 and SCL native 20m; nearest resampled to common 10m ITM grid'}
    control_stats={}
    for name,mask in [('vegetated_land',minimum>=.25),('deep_water',maximum<=-.1),('intertidal_candidate',candidate)]:
        mask &= valid&inside
        control_stats[name]={'pixels':int(mask.sum()),'median_corr':float(np.median(corr[mask])) if mask.any() else None,
                             'median_slope':float(np.median(slope[mask])) if mask.any() else None}
    coverage['internal_tide_controls']=control_stats
    coverage['controls_flat_by_legacy_limits']=all(s['median_corr'] is not None and abs(s['median_corr'])<=.4 and abs(s['median_slope'])<=.02
                                                for k,s in control_stats.items() if k!='intertidal_candidate')
    coverage['l2a_product_status']='DIAGNOSTIC_ONLY_FAILED_CONTROL' if not coverage['controls_flat_by_legacy_limits'] else 'UNVALIDATED_PROXY'
    coverage['controls_are_not_field_validation']=True
    days=np.array([(pd.Timestamp(m['date'])-pd.Timestamp('2022-01-01')).days for m in manifest])
    coverage['tide_calendar_day_pearson_r']=float(np.corrcoef(tide,days)[0,1])
    save('image_qa.json',coverage)
    pd.DataFrame(qa).drop(columns='scl_counts').to_csv(OUT/'image_qa.csv',index=False)
    profile.update(count=1,dtype='uint8',nodata=255,compress='deflate')
    layer=np.full(valid.shape,255,dtype=np.uint8); layer[valid&inside]=candidate[valid&inside].astype(np.uint8)
    with rasterio.open(OUT/'satellite_macroalgae_l2a_2022.tif','w',**profile) as ds:
        ds.write(layer,1); ds.set_band_description(1,'unvalidated macroalgae proxy 1 / assessed noncandidate 0 / unassessed 255')
    geoms=[shape(g) for g,v in shapes(candidate.astype('uint8'),mask=candidate,transform=affine) if v==1]
    geom=unary_union(geoms).intersection(DOMAIN)
    geojson('satellite_macroalgae_l2a_2022.geojson',[feature(geom,evidence='SATELLITE_MACROALGAE_PROXY',
            method='L2A sensitivity: existing NDVI tide rule',species=None,field_validated=False,
            status=coverage['l2a_product_status'])])
    return features,names,valid,candidate,affine,profile,cube,coverage,geom


def raster_mask(geom, valid, affine):
    if geom.is_empty: return np.zeros(valid.shape,dtype=bool)
    return rasterize([(geom,1)],out_shape=valid.shape,transform=affine,dtype='uint8').astype(bool)


def metrics(y,p,score=None):
    result={'n_pixels':len(y),'n_positive':int(y.sum()),'n_negative':int((y==0).sum()),
        'confusion_matrix_rows_reference_0_1_cols_prediction_0_1':confusion_matrix(y,p,labels=[0,1]).tolist(),
        'balanced_accuracy':balanced_accuracy_score(y,p),'f1':f1_score(y,p,zero_division=0),
        'precision':precision_score(y,p,zero_division=0),'recall':recall_score(y,p,zero_division=0)}
    if score is not None and len(np.unique(y))==2: result['roc_auc']=roc_auc_score(y,score)
    return result


def experiment(a,b,events,feat,names,valid,baseline,affine,profile,oldgeom):
    pos=a[a.label.eq('Intertidal fucoid reef')].copy()
    neg=b[b.label.isin(['Sediment','Shallow sand/mud community complex',
                       'Exposed to moderately exposed subtidal reef below 20m'])].copy()
    inter=unary_union(b[b.label.eq('Exposed to moderately exposed intertidal reef community complex')].geometry)
    ambiguous=unary_union(b[b.label.str.contains('Laminaria|Sheltered reef',case=False,regex=True)].geometry)
    reserves=unary_union([e['point'].buffer(max(250,e['uncertainty_m'] or 0)) for e in events])
    positive_union=unary_union(pos.geometry)
    records=[]; label=np.full(valid.shape,-1,dtype=int); groups=np.zeros(valid.shape,dtype=int)
    split=np.zeros(valid.shape,dtype=int)
    group_id=0
    for cls,g,erosion in [(1,pos,10),(0,neg,20)]:
        for _,r in g.iterrows():
            # Whole original polygons, before pilot clipping, determine split.
            bounds=transform(TO_WGS,r.geometry).bounds
            subset='train' if bounds[2]<-9.385 else ('test' if bounds[0]>-9.375 else 'excluded_crosses_split')
            if subset.startswith('excluded'): continue
            geom=r.geometry.buffer(-erosion).intersection(CONTEXT_DOMAIN if subset=='train' else DOMAIN)
            if cls==1: geom=geom.intersection(inter).difference(ambiguous)
            else: geom=geom.difference(positive_union).difference(ambiguous)
            if subset=='train': geom=geom.difference(reserves)
            mask=raster_mask(geom,valid,affine)&valid
            if not mask.any(): continue
            # A geometrically identical row can never supply both folds.
            assert not np.any((split>0)&mask), 'Overlapping weak labels or duplicate reference polygons'
            group_id+=1; label[mask]=cls; groups[mask]=group_id; split[mask]=1 if subset=='train' else 2
            records.append({'group_id':group_id,'class':cls,'split':subset,'source_row':r.source_row,
                            'source':'article17' if cls==1 else 'ssco','pixels':int(mask.sum()),
                            'geometry':geom})
    train=split==1; test=split==2
    assert set(label[train])=={0,1} and set(label[test])=={0,1}, 'Insufficient classes for comparison'
    assert (label[train]==1).sum()>=20 and len(set(groups[train & (label==1)]))>=2, 'Too few positive training pixels/polygons'
    # Do not claim thousands of pixels are independent observations.
    y,x=np.indices(valid.shape); xx=affine.c+(x+.5)*affine.a; yy=affine.f+(y+.5)*affine.e
    coords=np.stack([xx,yy],axis=-1)
    min_sep=float(cKDTree(coords[train]).query(coords[test])[0].min())
    assert min_sep>500, min_sep
    rf=RandomForestClassifier(n_estimators=300,min_samples_leaf=10,max_depth=12,
                              class_weight='balanced_subsample',random_state=SEED,n_jobs=1)
    # Give each reference polygon equal total weight within its class.
    weights=np.zeros(valid.shape)
    # Keep each class's original total weight before balanced_subsample acts.
    # Normalising only globally would double-correct the class imbalance.
    for cls in [0,1]:
        subset=[r for r in records if r['split']=='train' and r['class']==cls]
        n_class=int((train&(label==cls)).sum())
        for r in subset: weights[groups==r['group_id']]=n_class/(len(subset)*r['pixels'])
        assert np.isclose(weights[train&(label==cls)].sum(),n_class)
    rf.fit(feat[train],label[train],sample_weight=weights[train])
    probability=np.full(valid.shape,np.nan); probability[valid]=rf.predict_proba(feat[valid])[:,1]
    pred=probability>=.5
    oldmask=raster_mask(oldgeom,valid,affine)
    summary={'target':'Historical intertidal habitat proxy; not a trained kelp species detector',
        'train_pixels':int(train.sum()),'test_pixels':int(test.sum()),'train_groups':int(len(set(groups[train]))),
        'test_groups':int(len(set(groups[test]))),'min_train_test_distance_m':min_sep,
        'threshold':.5,'seed':SEED,'features':names,'model':rf.get_params(),
        'source_independent':False,'pixel_scores_are_not_field_accuracy':True,
        'evaluation_domain':'Identical held-out historical-labelled pixels valid in every L2A scene',
        'legacy_vector_test_overlap_only':{'reference_positive_pixels':int((label[test]==1).sum()),
            'detected_at_reference_positive_pixels':int((oldmask&test&(label==1)).sum()),
            'accuracy_not_calculated':'Original wall-to-wall coverage mask is unavailable; no detection cannot be treated as an assessed negative.'},
        'l2a_rule_on_shared_test':metrics(label[test],baseline[test].astype(int)),
        'random_forest_on_shared_test':metrics(label[test],pred[test].astype(int),probability[test]),
        'rf_positive_area_ha_unvalidated':float((pred&valid&raster_mask(DOMAIN,valid,affine)).sum()/100),
        'sample_weight':'Each polygon equal total weight within class, preserve original class total before balanced_subsample class weighting',
        'train_class_pixels':{str(c):int((train&(label==c)).sum()) for c in [0,1]},
        'train_class_polygon_count':{str(c):len(set(groups[train&(label==c)])) for c in [0,1]},
        'test_class_polygon_count':{str(c):len(set(groups[test&(label==c)])) for c in [0,1]},
        'claim':'Spatial transfer agreement with weak historical labels only. Does not establish present-day kelp accuracy.'}
    rows=[]; point_rows=[]
    for r in records:
        mask=groups==r['group_id']; cls=r['class']
        rows.append({k:v for k,v in r.items() if k!='geometry'}|{
            'rule_positive_fraction':float(baseline[mask].mean()),'rf_positive_fraction':float(pred[mask].mean()),
            'rf_mean_probability':float(probability[mask].mean())})
    pd.DataFrame(rows).to_csv(OUT/'spatial_polygon_results.csv',index=False)
    geojson('spatial_split.geojson',[feature(r['geometry'],**{k:v for k,v in r.items() if k!='geometry'}) for r in records])
    rr,cc=np.where(train|test)
    pd.DataFrame({'row':rr,'col':cc,'east_m':xx[rr,cc],'north_m':yy[rr,cc],
        'split':split[rr,cc],'group':groups[rr,cc],'reference_class':label[rr,cc],
        'legacy_candidate':oldmask[rr,cc],'l2a_rule_candidate':baseline[rr,cc],
        'rf_probability':probability[rr,cc]}).to_csv(OUT/'spatial_pixel_predictions.csv',index=False)
    pd.DataFrame({'feature':names,'importance':rf.feature_importances_}).to_csv(OUT/'rf_feature_importance.csv',index=False)
    # Event-level presence compatibility, uncertainty buffers, and spatial guards.
    trtree=cKDTree(coords[train]); event_results=[]
    for e in events:
        pt=e['point']; row,col=rowcol(affine,pt.x,pt.y)
        in_bounds=0<=row<valid.shape[0] and 0<=col<valid.shape[1]
        assessed=bool(in_bounds and valid[row,col])
        uncertainty=e['uncertainty_m']
        row_={k:v for k,v in e.items() if k!='point'}
        row_.update({'distance_to_nearest_train_pixel_m':float(trtree.query([pt.x,pt.y])[0]),
            'l2a_point_assessed':assessed,'legacy_point_hit':oldgeom.covers(pt),
            'l2a_point_hit':bool(baseline[row,col]) if assessed else None,
            'rf_point_hit':bool(pred[row,col]) if assessed else None,
            'rf_point_probability':float(probability[row,col]) if assessed else None,
            'legacy_nearest_detection_m':pt.distance(oldgeom),
            'legacy_point_nonhit_interpretation':'No vector detection; original valid-coverage mask unavailable',
            'temporal_match_to_2022':e['date'].startswith('2022'),
            'is_accuracy_trial':False})
        for radius in ([uncertainty] if uncertainty is not None else []):
            buf=pt.buffer(radius); mask=raster_mask(buf,valid,affine)
            usable=mask&valid
            row_.update({'uncertainty_buffer_valid_fraction':float(usable.sum()/mask.sum()) if mask.any() else None,
                'legacy_buffer_hit':oldgeom.intersects(buf),
                'l2a_buffer_hit':bool((baseline&usable).any()) if usable.any() else None,
                'rf_buffer_hit':bool((pred&usable).any()) if usable.any() else None})
        assert row_['distance_to_nearest_train_pixel_m']>=240
        event_results.append(row_)
    save('held_out_observation_results.json',event_results)
    pd.DataFrame([{k:('|'.join(v) if isinstance(v,list) else v) for k,v in r.items()} for r in event_results]).to_csv(OUT/'held_out_observation_results.csv',index=False)
    independent=[r for r in event_results if r['post_2011'] and r['kind']=='intertidal_macroalgae_presence']
    summary['independent_dated_presence_check']={'event_count':len(independent),
        'point_assessed_count':sum(r['l2a_point_assessed'] for r in independent),
        'legacy_point_hits':sum(r['legacy_point_hit'] for r in independent),
        'l2a_point_hits':sum(r['l2a_point_hit'] is True for r in independent),
        'rf_point_hits':sum(r['rf_point_hit'] is True for r in independent),
        'known_uncertainty_events':sum(r['uncertainty_m'] is not None for r in independent),
        'legacy_buffer_hits':sum(r.get('legacy_buffer_hit') is True for r in independent),
        'l2a_buffer_hits':sum(r.get('l2a_buffer_hit') is True for r in independent),
        'rf_buffer_hits':sum(r.get('rf_buffer_hit') is True for r in independent),
        'same_year_as_image_events':sum(r['temporal_match_to_2022'] for r in independent),
        'independent_absences':0,'current_kelp_accuracy':None,
        'full_source_lineage_independence_proven':False,
        'limitation':'Two nearby 2019 presence events may share spatial context; not a representative accuracy sample. No current field absences. Source independence does not remove temporal mismatch.'}
    save('experiment_results.json',summary)
    profile.update(dtype='float32',nodata=-9999,count=1)
    with rasterio.open(OUT/'rf_historical_intertidal_probability.tif','w',**profile) as ds:
        ds.write(np.where(valid&raster_mask(DOMAIN,valid,affine),probability,-9999).astype('float32'),1)
        ds.set_band_description(1,'Weak-label historical intertidal habitat RF probability; unvalidated, not species')
    return summary,probability,split


def contexts():
    from evidence_pipeline import build_wave, build_coast
    land,coast,domain,coastinfo=build_coast()
    wave=build_wave(DOMAIN.centroid)
    wave['distance_to_pilot_centroid_m']=wave.pop('distance_to_model_centroid_m')
    geojson('coastline_context.geojson',[feature(coast.intersection(DOMAIN),evidence='COASTLINE_CONTEXT',source='OpenStreetMap')])
    p=pd.read_csv(ROOT/'outputs/model/suitability_multisite_predictions.csv')
    p=p[p.aoi.eq('sherkin_baltimore') & p.lon.between(BBOX[0],BBOX[2]) & p.lat.between(BBOX[1],BBOX[3])]
    items=[]
    for _,r in p.iterrows():
        if not r.assessed: continue
        x,y=TO_ITM(r.lon,r.lat)
        items.append(feature(box(x-25,y-25,x+25,y+25).intersection(DOMAIN),
            evidence='MODELLED_SUITABILITY',score=r.suitability,above_legacy_threshold=bool(r.suitability>=.7104),
            in_training_range=bool(r.in_training_range),on_mapped_reef=bool(r.on_mapped_reef),
            current_presence_confirmed=False,source='Existing multisite suitability model, no retraining'))
    geojson('modelled_suitability.geojson',items)
    coastal={'wave':wave,'coast_source_dates':coastinfo['source_date'],
         'coastline_length_inside_pilot_m':coast.intersection(DOMAIN).length,
         'coastline_unresolved_faces':coastinfo['unresolved_faces'],
         'existing_bathymetry_cells':len(p),'assessed_suitability_cells':int(p.assessed.sum()),
         'bathymetry_finite_fraction':float(p.depth_m.notna().mean()),
         'wave_context_only':True,'nearshore_wave_validation':False}
    save('coastal_data_availability.json',coastal)
    scenes=pd.read_csv(ROOT/'outputs/candidate_scenes.csv')
    rows=[]
    for name,g in scenes.groupby('aoi'):
        d=pd.to_datetime(g.datetime_utc,utc=True)
        q=g[(g.aoi_clear_frac>=.9)&d.dt.month.isin([5,6,7,8])&g.wl_union_hall_harbor.notna()]
        rows.append({'candidate':name,'catalog_rows':len(g),'clear_summer_rows':len(q),
            'earliest_scene':str(d.min()),'latest_scene':str(d.max()),
            'local_deglint_band_samples':(ROOT/f'outputs/deglint/deglint_{name}.csv').exists(),
            'local_7scene_tide_result':name=='sherkin_baltimore',
            'selection':'Selected small subarea' if name=='sherkin_baltimore' else 'Not selected',
            'reason':{'sherkin_baltimore':'Reusable 7-scene experiment, dated field presences and complete local coastline/offshore wave inputs',
                      'inner_roaringwater':'No cached 7-scene tide experiment; more limited reusable image analysis',
                      'mizen_outer':'Existing deglint samples, but no cached 7-scene intertidal experiment; exposed surface-roughness issue recorded in common.py'}.get(name,'')})
    pd.DataFrame(rows).to_csv(OUT/'pilot_selection.csv',index=False)
    return coastal,land,coast


def preview(cube,valid,baseline,probability,affine,oldgeom,a,b,land,coast,summary):
    """Small static scientific map, not a product/UI redesign."""
    # Crop the scientific figure to the selected pilot, not the training context.
    left,bottom,right,top=DOMAIN.bounds
    r0,c0=rowcol(affine,left,top);r1,c1=rowcol(affine,right,bottom)
    r0,c0=max(0,r0),max(0,c0);r1,c1=min(valid.shape[0],r1+1),min(valid.shape[1],c1+1)
    cube=cube[:,:,r0:r1,c0:c1];valid=valid[r0:r1,c0:c1];baseline=baseline[r0:r1,c0:c1];probability=probability[r0:r1,c0:c1]
    affine=affine*rasterio.Affine.translation(c0,r0)
    h,w=valid.shape
    rgb=np.moveaxis(np.clip(cube[0,[2,1,0]]/.18,0,1),0,-1)
    rgb=(np.nan_to_num(rgb)*255).astype('uint8')
    legacy_mask=raster_mask(oldgeom,valid,affine)
    hk=unary_union(b[b.label.str.contains('Laminaria',case=False)].geometry).intersection(DOMAIN)
    historical=raster_mask(hk,valid,affine)
    conflict=unary_union(a[a.label.eq('Faunal turf reef')].geometry).intersection(hk)
    disputed=raster_mask(conflict,valid,affine)
    panels=[]
    titles=['Satellite processing comparison','Historical references, not current kelp','RF rejected as macroalgae map']
    for n in range(3):
        pixels=rgb.copy()
        if n==0:
            pixels[legacy_mask]=[0,225,220]; pixels[baseline]=[35,105,255]
        elif n==1:
            pixels[historical]=[175,75,220]; pixels[disputed]=[245,145,35]
        else:
            pixels[~valid]=[185,185,185]; pixels[(probability>=.5)&valid]=[45,190,100]
        im=Image.fromarray(pixels).resize((420,round(h/w*420)))
        panels.append(im)
    canvas=Image.new('RGB',(1340,panels[0].height+220),'white'); dr=ImageDraw.Draw(canvas)
    try:
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
        small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14)
        title=ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf',24)
    except OSError: font=small=title=ImageFont.load_default()
    dr.text((20,12),'Sherkin - Baltimore | Cork pilot | Evidence kept separate',fill='#16364a',font=title)
    for i,p in enumerate(panels):
        x=20+i*440; canvas.paste(p,(x,75)); dr.text((x,50),titles[i],fill='black',font=font)
    y=panels[0].height+88
    for i,lines in enumerate([
        ['Cyan: original L1C tide/NDVI detection','Blue: L2A fails the deep-water control','Neither is validated kelp extent'],
        ['Purple: SSCO historical Laminaria','Orange: Article17 calls this faunal turf','Both derive from the 2011 NPWS synthesis'],
        ['Green: RF probability >= 0.5','Grey: incomplete or invalid image coverage','Independent current accuracy: unavailable']]):
        for j,line in enumerate(lines):dr.text((20+i*440,y+j*22),line,fill='black',font=small)
    dr.text((20,y+78),'North up. WGS84 bounds: -9.405 to -9.355; 51.460 to 51.495. ITM grid 10 m. No economic ranking.',fill='#333333',font=small)
    dr.text((20,y+100),'Contains modified Copernicus Sentinel data; NPWS historical reference. Full data, masks, splits and provenance accompany this figure.',fill='#333333',font=small)
    canvas.save(OUT/'pilot_comparison_diagnostics.png')
    # Primary evidence map preserves the three requested evidence classes.
    first=rgb.copy();first[legacy_mask]=[0,225,220]
    model=rgb.copy()
    suitability=gpd.read_file(OUT/'modelled_suitability.geojson').to_crs(ITM)
    all_model=raster_mask(unary_union(suitability.geometry),valid,affine)
    above=raster_mask(unary_union(suitability[suitability.above_legacy_threshold].geometry),valid,affine)
    model[all_model]=[125,160,185];model[above]=[240,100,35]
    canvas.paste(Image.fromarray(first).resize(panels[0].size),(20,75))
    canvas.paste(Image.fromarray(model).resize(panels[0].size),(900,75))
    dr.rectangle((0,43,1340,73),fill='white')
    for i,t in enumerate(['Satellite macroalgae proxy, 2022','Historical kelp reference','Modelled suitability, unvalidated']):
        dr.text((20+i*440,50),t,fill='black',font=font)
    dr.rectangle((0,y,1340,y+73),fill='white')
    for i,lines in enumerate([
        ['Cyan: retained original L1C result','15.38 ha in this pilot; no species inference','Current extent / accuracy not established'],
        ['Purple: SSCO historical Laminaria','Orange: conflicting Article17 faunal label','Shared source; not independent validation'],
        ['Blue-grey: existing assessed model cells','Orange: score >= 0.7104 (legacy threshold)','Suitability only; no current kelp confirmation']]):
        for j,line in enumerate(lines):dr.text((20+i*440,y+j*22),line,fill='black',font=small)
    canvas.save(OUT/'pilot_evidence.png')


def report(audit,replay,qa,result,coastal,checks):
    q=result['independent_dated_presence_check']; h=audit['area_comparison']['pilot']
    r=result['random_forest_on_shared_test']; n=result['l2a_rule_on_shared_test']
    water=qa['internal_tide_controls']['deep_water']
    body=f'''# Cork pilot mapping experiment — 15 October 2026

**Selected pilot: Sherkin eastern shore and Baltimore harbour entrance, Cork.**
Bounds: {BBOX}; {result['pilot_area_km2']:.2f} km² including land and sea, approximately 3.5 × 3.9 km.
Selection used reusable imagery, dated habitat evidence, bathymetry, coastline and offshore wave data. No euro result was used.

**Decision: retain the original satellite layer as an unvalidated 2022 macroalgae proxy; do not promote either new experiment to a current kelp map.**
The L2A rerun fails the existing deep-water control. The Random Forest predicts terrestrial interiors and has only two historical test polygons. Independent current kelp accuracy remains **unknown**, not zero.

![Three separate evidence classes](pilot_evidence.png)

## What was actually run

1. Replayed the existing NDVI-tide classification against all {replay['pixels_replayed']} archived pixel summaries: {replay['class_matches']} identical classes. This verifies arithmetic, not ecology. The retained original vector layer covers **{replay['pilot_area_ha']:.2f} ha** in the pilot. No original file was regenerated or relabelled.
2. Acquired small Sentinel-2 **L2A** subsets on the same seven dates (15, 20, 23, 28 May; 14 July; 3, 21 August 2022), consistently from tile T29UMT. Applied each product XML's BOA offset and quantification; all spectral offsets were −1000 DN and scales 0.0001. Processing baselines 04.00 and 05.10 are both present. This is a processing sensitivity experiment, not a new year's extent estimate.
3. Repeated the existing rule: maximum NDVI ≥ 0.20, minimum ≤ 0, negative NDVI/tide slope. Retained SCL 4/5/6 pixels, dilated cloud/shadow/snow by 30 m, excluded negative red/NIR reflectance and required all seven dates. {qa['all_7_valid_fraction']:.1%} of pilot pixels remain. The resulting **{qa['l2a_candidate_ha']:.2f} ha is diagnostic only**: deep-water median r = {water['median_corr']:.3f}, slope = {water['median_slope']:.4f} NDVI/m, exceeding the existing |r| ≤ 0.40 and |slope| ≤ 0.02 controls. The original L1C report passed those controls; changing preprocessing did not reproduce that result.
4. Fitted a 300-tree Random Forest using 21 spectral/temporal image features, fixed probability threshold 0.5 and seed {SEED}. No coordinates, bathymetry or habitat codes were predictors. Historical fucoid reef and sediment/deep-reef polygons supplied weak habitat labels. These labels do not establish algae presence/absence at every pixel.

The initial within-pilot training design had no positive pixels after 10 m polygon erosion. This was recorded before model fitting. A documented context extension within the existing Sherkin-Baltimore area supplied **23 positive pixels from two polygons**, plus 5,182 negative proxy pixels from four polygons. The pilot and test rules stayed fixed. Training polygons lie wholly west of −9.385; test polygons lie wholly east of −9.375. All dated observation locations and at least 250 m around them were excluded from training. See both protocol JSON files and `label_feasibility_before_fitting.json`.

An implementation review corrected polygon weights to preserve each class's original total before applying class balancing; `diagnostic_before_weight_normalisation.json` is superseded debugging evidence. No test threshold or forest parameter was tuned to the results.

## Validation results and their limits

The reference test is spatially separate by at least **{result['min_train_test_distance_m']:.0f} m**, but contains just **15 pixels: five positive-proxy pixels from one polygon, ten negative-proxy pixels from another**. It measures historical habitat-label agreement, not independent field accuracy.

| On these same 15 reference pixels | L2A NDVI rule | Random Forest |
|---|---:|---:|
| TP / FN / FP / TN | 1 / 4 / 2 / 8 | 5 / 0 / 3 / 7 |
| F1, descriptive only | {n['f1']:.2f} | {r['f1']:.2f} |
| Balanced agreement, descriptive only | {n['balanced_accuracy']:.2f} | {r['balanced_accuracy']:.2f} |

Fifteen nearby pixels are **not fifteen independent field observations**. There is insufficient polygon replication for a meaningful confidence interval or model selection. Historical habitat polygons and satellite-emergent vegetation also have different targets. The old vector layer intersects one of the five positive reference pixels; accuracy is not calculated because its complete valid-coverage mask was not saved.

The RF predicts {result['rf_positive_area_ha_unvalidated']:.2f} ha as positive, including **{result['postfit_spatial_sanity_review']['land_interior_positive_ha']:.2f} ha of mapped land more than 100 m inside the shore**. Terrestrial negatives were missing from training. This exposes an application-domain failure and is why the higher F1 does **not** justify adopting it as a macroalgae map. No post-hoc masking is used to conceal that failure.

Eight dated observation events were reserved from training. Two are suitable intertidal macroalgae presence checks: Explore Your Shore, 4 August 2019 (four taxa at one place = **one event**, 100 m position uncertainty), and iNaturalist, 26 August 2019 (one event, 14 m uncertainty). The other records include historical subtidal kelp: they cannot validate an intertidal satellite product.

| Retrospective compatibility at the two 2019 events | Legacy L1C | L2A rule | RF |
|---|---:|---:|---:|
| Detection at reported point | {q['legacy_point_hits']}/2 | {q['l2a_point_hits']}/2 | {q['rf_point_hits']}/2 |
| Any detection within stated position uncertainty | {q['legacy_buffer_hits']}/2 | {q['l2a_buffer_hits']}/2 | {q['rf_buffer_hits']}/2 |

Buffer overlap is a permissive compatibility check, not confirmation. These events are separate post-2011 collections and were not used for training, but the complete SSCO lineage is unavailable, so absolute source independence is not proven. They are also nearby and **three years earlier than the images**. There are no same-year independent absence observations and no current field survey. Therefore current accuracy, precision/specificity and species-level validation cannot be estimated from them. Individual coordinates, dates, uncertainty and distances to training are saved in `held_out_observation_results.csv`.

## Why the two NPWS layers disagree

The pilot contains {h['ssco_laminaria_ha']:.2f} ha labelled Laminaria in SSCO, of which **{h['article17_faunal_vs_ssco_laminaria_ha']:.2f} ha ({h['fraction_ssco_laminaria_labelled_faunal_by_article17']:.2%}) is labelled faunal turf in Article 17**. Eighteen conflicting polygon pairs have whole-polygon intersection-over-union above 0.95. Article 17's local Source and Reference fields explicitly cite the **Roaringwater Bay 2011 Conservation Objectives**; the SSCO metadata traces the same community mapping workflow. In the broader inspected window, 412 of 824 Article 17 records were exact geometry/class duplicates and were removed in-memory only.

Shared provenance and nearly identical outlines support a classification/translation discrepancy, not measured ecological change. The exact recoding history remains unresolved. Neither layer is automatically current truth, and they cannot validate one another independently. The [NPWS 2011 supporting report](https://www.npws.ie/sites/default/files/publications/pdf/000101_Roaringwater%20Bay%20and%20Islands%20SAC%20Marine%20Supporting%20Doc_V1.pdf) describes surveys from 2002, 2004, 2009 and 2010 and calls the mapped Laminaria distribution an interpolation. Exact polygon survey dates are unavailable. The March 2025 package is a distribution date, not a 2025 field survey.

The earlier application's failed 63.45% external false-positive test is not replaced by these descriptive scores. The conflicting historical negative labels make that old number unsuitable as independent current ecological validation; the old result and its warning remain untouched.

## Why this pilot is usable for the next phase

Local inputs include seven usable image acquisitions with a 2.575 m gauge tide range, dated observations, {coastal['existing_bathymetry_cells']} existing bathymetry/model grid centres with finite depths, and {coastal['coastline_length_inside_pilot_m']/1000:.2f} km of mapped shoreline within this small area (not protected frontage). The existing CMEMS file supplies {coastal['wave']['hours']:,} hourly values from 2015–2024. The nearest valid wet cell to this pilot's centre is **{coastal['wave']['distance_to_pilot_centroid_m']/1000:.2f} km away**: offshore reanalysis is available, but nearshore wave validation is not. No wave benefit or monetary estimate was calculated.

Mizen and inner Roaringwater were compared using the existing scene catalogue and reusable local products; `pilot_selection.csv` records the comparison. Choosing Sherkin does not assert it has the best water clarity or the highest ecological value. It minimises new acquisition and provides multiple evidence types for a small, testable site.

## Deliverables and reproducibility

* `satellite_macroalgae_legacy_2022.geojson`: retained species-agnostic satellite proxy.
* `historical_kelp_reference.geojson` and `historical_observation_events.geojson`: historical evidence, with dates and uncertainties kept distinct.
* `modelled_suitability.geojson`: existing suitability scores, not detected or confirmed kelp. The threshold flag is not the application's additional depth-limited wave-model footprint.
* `npws_disagreement.geojson`, `npws_crosswalk.csv`, `npws_conflicting_polygon_pairs.csv`: unresolved reference disagreement.
* `satellite_macroalgae_l2a_2022.tif/.geojson`, `rf_historical_intertidal_probability.tif`, `pilot_comparison_diagnostics.png`: diagnostic experiments; **do not import as accepted habitat maps**.
* `spatial_split.geojson`, pixel/polygon prediction CSVs, scene metadata/XML, `experiment_results.json`, `verification.json` and checksums: audit trail.

Run the full analysis offline from the project root:

```powershell
.venv/Scripts/python.exe src/cork_pilot_analysis.py
```

If the small image cache is missing, acquisition is separate and uses public data:

```powershell
.venv/Scripts/python.exe src/cork_pilot_acquire.py --context
```

The original L1C processing cannot be reproduced exactly from the local summaries alone: per-scene NDVI arrays and the complete original coverage mask were not cached. Three archived scene IDs name T29UMS while the original code filters T29UMT and falls back by date. This provenance issue is recorded, not silently corrected. The new cached subsets record actual IDs, dates, raw DN, CRS, offsets and source URLs; no private access tokens are saved. [Copernicus product guidance](https://sentiwiki.copernicus.eu/web/s2-products) documents the radiometric offset; [Cloud Score Plus](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_CLOUD_SCORE_PLUS_V1_S2_HARMONIZED) describes the old quality mask; the two mask systems are not interchangeable.

**Preservation:** {checks['original_files_checked']} original input, source, requirement and app files were checksum-verified unchanged. The existing app's local startup and six-resource smoke check passed (see `app_smoke.log`). There was no UI, presentation, video, economics or application rebuild. Prior requirements remain active: habitat/condition, physical wave and receptor analysis, conditional valuation, biodiversity, survey/restoration priorities, transferable workflow, all previously requested user journeys, reports and media. This first task changes none of those commitments.

## Next necessary step

Collect georeferenced **presence and absence** observations on multiple spatially separate shore segments, matched to a new low-tide satellite acquisition, with photos, cover estimates and positional uncertainty. Use separate shallow-subtidal video/diver observations to establish kelp species and extent. Resolve the NPWS classification crosswalk with its source history. Then retrain using genuine algae, bare shore, water and terrestrial classes and evaluate on wholly withheld sites. Only after that should a current habitat map be promoted into the later wave, valuation and presentation phases.
'''
    (OUT/'README.md').write_text(body,encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    before=source_hashes()
    if not (OUT/'preserved_originals.json').exists(): save('preserved_originals.json',before)
    print('Reading historical references',flush=True)
    a,b,audit=refs(); events=observations(); oldgeom,replay=legacy()
    print('Processing seven image subsets',flush=True)
    feat,names,valid,baseline,affine,profile,cube,qa,newgeom=images()
    print('Spatial holdout and Random Forest',flush=True)
    result,probability,split=experiment(a,b,events,feat,names,valid,baseline,affine,profile,oldgeom)
    print('Coastal context and separate suitability layer',flush=True)
    coastal,land,coast=contexts()
    inside=raster_mask(DOMAIN,valid,affine)
    common=raster_mask(oldgeom,valid,affine)&valid&inside
    pilot_baseline=baseline&inside
    result['legacy_vs_l2a_shared_valid_grid']={'legacy_positive_cells':int(common.sum()),
        'l2a_positive_cells':int(pilot_baseline.sum()),'intersection_cells':int((common&pilot_baseline).sum()),
        'iou':float((common&pilot_baseline).sum()/(common|pilot_baseline).sum()) if (common|pilot_baseline).any() else None,
        'interpretation':'Processing sensitivity, not temporal change; same 2022 dates, different level/cloud mask.'}
    land_interior=raster_mask(land.buffer(-100),valid,affine)&inside
    rfpositive=(probability>=.5)&valid&inside
    result['postfit_spatial_sanity_review']={'rf_positive_pixels':int(rfpositive.sum()),
        'positive_pixels_in_known_land_over_100m_from_shore':int((rfpositive&land_interior).sum()),
        'land_interior_positive_ha':float((rfpositive&land_interior).sum()/100),
        'not_an_accuracy_estimate':'OSM land coverage may be incomplete; this checks obvious out-of-domain application only.',
        'map_use_decision':'DO_NOT_ADOPT_RF_AS_MACROALGAE_MAP',
        'reason':'Tiny historical reference test, missing terrestrial negative training, historical-vs-satellite target mismatch and no same-date independent field validation.'}
    result['pilot_area_km2']=DOMAIN.area/1e6
    save('experiment_results.json',result)
    preview(cube,valid,baseline,probability,affine,oldgeom,a,b,land,coast,result)
    after=source_hashes()
    preserved=json.loads((OUT/'preserved_originals.json').read_text())
    changes=[p for p,h in preserved.items() if after.get(p)!=h]
    assert not changes, f'Original files changed: {changes}'
    checks={'original_files_checked':len(before),'original_files_unchanged':not changes,
            'legacy_rule_exact_replay':replay['class_matches']==replay['pixels_replayed'],
            'spatial_train_test_separation_over_500m':result['min_train_test_distance_m']>500,
            'reference_sources_explicitly_not_independent':audit['independent_sources'] is False,
            'independent_accuracy_not_invented':result['independent_dated_presence_check']['current_kelp_accuracy'] is None,
            'all_image_inputs_cached':len(list((OUT/'imagery_context').glob('*.tif')))==7}
    assert all(v for k,v in checks.items() if k!='original_files_checked')
    save('verification.json',checks)
    manifest={'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,
         'geopandas':gpd.__version__,'rasterio':rasterio.__version__,
         'command':'.venv/Scripts/python.exe src/cork_pilot_analysis.py',
         'network_required_for_analysis':False,'acquisition_command':'.venv/Scripts/python.exe src/cork_pilot_acquire.py',
         'protocol_sha256':sha(OUT/'protocol.json'),'context_extension_sha256':sha(OUT/'protocol_context_extension.json'),
         'source_sha256':{p.name:sha(p) for p in (ROOT/'src').glob('cork_pilot*.py')},
         'analysis_input_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for cache in ['imagery','imagery_context'] for p in (OUT/cache).glob('*') if p.is_file()},
         'preserved_inputs_manifest':'preserved_originals.json'}
    manifest['package_versions']={n:importlib.metadata.version(n) for n in
        ['numpy','pandas','geopandas','rasterio','pyproj','shapely','scipy','scikit-learn','pillow','requests','xarray']}
    save('reproducibility.json',manifest)
    report(audit,replay,qa,result,coastal,checks)
    print(json.dumps(clean({'pilot':BBOX,'legacy_area_ha':replay['pilot_area_ha'],'image_valid_fraction':qa['all_7_valid_fraction'],
                            'l2a_area_ha':qa['l2a_candidate_ha'],'experiment':result,'checks':checks}),indent=2),flush=True)


if __name__=='__main__':
    main()
