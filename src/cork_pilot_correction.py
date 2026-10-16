"""One controls-only correction of the Cork intertidal macroalgae experiment.

The existing application, raw inputs and original holdout are read-only.
Run --acquire once online, --prepare before fitting, then --fit offline.
All generated files are confined to outputs/cork_pilot_correction_20261015.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.transform import rowcol
from shapely.geometry import box, Point, mapping
from shapely.ops import transform, unary_union
from scipy.ndimage import binary_dilation
from scipy.spatial import cKDTree
from sklearn.ensemble import RandomForestClassifier

import cork_pilot_analysis as base

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'outputs/cork_pilot_20261015'
OUT = ROOT / 'outputs/cork_pilot_correction_20261015'
SERVICE = ('https://services-eu1.arcgis.com/FH5XCsx8rYXqnjF5/arcgis/rest/services/'
           'MapGenieNationalLandCover2018ITM/FeatureServer/0')
BBOX = [-9.405, 51.460, -9.355, 51.495]
CONTEXT = [-9.42, 51.45, -9.355, 51.51]
VEGETATION = ['Improved Grassland', 'Amenity Grassland', 'Dry Grassland',
              'Wet Grassland', 'Broadleaved Forest and Woodland', 'Coniferous Forest',
              'Mixed Forest', 'Scrub', 'Bracken', 'Dry Heath', 'Wet Heath']
BARE = ['Coastal Sediments', 'Exposed Rock and Sediments']
WATER = ['Lakes and Ponds', 'Marine Water']
PARAMS = dict(n_estimators=300, min_samples_leaf=10, max_depth=12,
              class_weight='balanced_subsample', random_state=20261015, n_jobs=1)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(name, value):
    (OUT / name).write_text(json.dumps(base.clean(value), indent=2, allow_nan=False,
                                      default=lambda x: x.isoformat()), encoding='utf-8')


def acquire():
    """Cache public service responses with full per-feature capture provenance."""
    import requests
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / 'nlc2018'
    dest.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'CorkIntertidalResearch/1.0 public-data-audit'
    requests_log = []

    def request(name, url, params):
        path = dest / name
        if path.exists():
            result = read(path)
        else:
            response = (session.post(url, data=params, timeout=90) if 'objectIds' in params
                        else session.get(url, params=params, timeout=90))
            response.raise_for_status()
            result = response.json()
            if 'error' in result:
                raise RuntimeError(result['error'])
            path.write_bytes(response.content)
        requests_log.append({'file': name, 'url': url, 'params': params,
                             'http_method': 'POST' if 'objectIds' in params else 'GET',
                             'sha256': digest(path)})
        return result

    metadata = request('service.json', SERVICE, {'f': 'json'})
    params = {'f': 'json', 'where': '1=1',
              'geometry': ','.join(map(str, CONTEXT)),
              'geometryType': 'esriGeometryEnvelope', 'inSR': 4326,
              'spatialRel': 'esriSpatialRelIntersects', 'returnIdsOnly': 'true'}
    ids = sorted(request('ids.json', SERVICE + '/query', params)['objectIds'])
    found = []
    for start in range(0, len(ids), 400):
        page = request(f'features_{start:05}.json', SERVICE + '/query', {
            'f': 'json', 'objectIds': ','.join(map(str, ids[start:start+400])),
            'outFields': '*', 'outSR': 2157, 'returnGeometry': 'true',
            'geometryPrecision': 2})
        assert not page.get('exceededTransferLimit'), 'Incomplete service response'
        found.extend(v['attributes']['OBJECTID'] for v in page['features'])
        print('NLC cached', len(found), '/', len(ids), flush=True)
    assert sorted(found) == ids and len(set(found)) == len(ids)
    save('nlc_acquisition.json', {
        'retrieved_utc': datetime.now(timezone.utc).isoformat(),
        'source': SERVICE, 'copyright': metadata.get('copyrightText'),
        'description': metadata.get('description'),
        'bbox_wgs84': CONTEXT, 'count': len(ids), 'requests': requests_log,
        'data_age': 'Map named 2018; retain actual feature image/capture dates.',
        'use': 'Local research subset; no application or presentation publication.'})


def image_features():
    """Read-only reproduction of the original 21 features and fixed QA mask."""
    manifest = read(OLD / 'imagery_context/manifest.json')
    data, masks = [], []
    for m in manifest:
        with rasterio.open(OLD / f"imagery_context/{m['date']}.tif") as ds:
            dn = ds.read()
            profile, affine = ds.profile.copy(), ds.transform
        refl = np.stack([(dn[i].astype(float) + m['reflectance'][b]['offset_dn'])
                         * m['reflectance'][b]['scale']
                         for i, b in enumerate(['B02', 'B03', 'B04', 'B08', 'B11'])])
        cloud = binary_dilation(np.isin(dn[5], [1, 3, 8, 9, 10, 11]), iterations=3)
        clear = np.isin(dn[5], [4, 5, 6]) & ~cloud & np.all(dn[:5] > 0, axis=0)
        masks.append(clear & (refl[2] >= 0) & (refl[3] >= 0) & ((refl[2]+refl[3]) > 1e-6))
        data.append(refl)
    cube = np.stack(data)
    valid = np.logical_and.reduce(masks)
    valid &= base.raster_mask(base.CONTEXT_DOMAIN, valid, affine)
    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi = np.clip((cube[:, 3]-cube[:, 2])/(cube[:, 3]+cube[:, 2]), -1, 1)
        ndwi = (cube[:, 1]-cube[:, 3])/(cube[:, 1]+cube[:, 3])
        tide = np.array([m['tide_m_LAT'] for m in manifest])
        w = tide-tide.mean()
        mean = ndvi.mean(axis=0)
        sxy = np.sum(w[:, None, None]*ndvi, axis=0)
        syy = np.sum((ndvi-mean)**2, axis=0)
        slope = sxy/np.sum(w*w)
        corr = sxy/np.sqrt(np.sum(w*w)*syy)
    names, features = [], []
    for i, band in enumerate(['B02', 'B03', 'B04', 'B08', 'B11']):
        for stat, fn in [('min', np.min), ('median', np.median), ('max', np.max)]:
            names.append(f'{band}_{stat}')
            features.append(fn(cube[:, i], axis=0))
    for name, a in [('ndvi_min', ndvi.min(axis=0)), ('ndvi_max', ndvi.max(axis=0)),
                    ('ndvi_mean', mean), ('ndvi_tide_slope', slope),
                    ('ndvi_tide_corr', corr), ('ndwi_median', np.median(ndwi, axis=0))]:
        names.append(name)
        features.append(a)
    features = np.stack(features, axis=-1)
    valid &= (syy > 0) & np.all(np.isfinite(features), axis=-1)
    inside = base.raster_mask(base.DOMAIN, valid, affine)
    with rasterio.open(OLD / 'rf_historical_intertidal_probability.tif') as ds:
        before = ds.read(1)
        assert ds.transform == affine and ds.crs.to_epsg() == 2157
    assert np.array_equal(valid & inside, before != -9999), 'Original coverage changed'
    assert names == read(OLD / 'experiment_results.json')['features']
    profile.update(count=1, dtype='float32', nodata=-9999, compress='deflate')
    return features, valid, inside, affine, profile, before, names


def nlc_polygons():
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='organizePolygons')
        parts = [gpd.read_file(p) for p in sorted((OUT / 'nlc2018').glob('features_*.json'))]
    result = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=2157)
    assert len(result) == read(OUT / 'nlc_acquisition.json')['count']
    assert result.OBJECTID.is_unique
    result.geometry = result.geometry.make_valid()
    return result


def protected_files():
    paths = {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p)
             for p in OLD.rglob('*') if p.is_file()}
    # Previous original-file inventory includes all app resources and source inputs.
    for p in read(OLD / 'preserved_originals.json'):
        paths[p] = digest(ROOT / p)
    for p in (ROOT / 'src').glob('cork_pilot*.py'):
        if p.name != Path(__file__).name:
            paths[str(p.relative_to(ROOT)).replace('\\', '/')] = digest(p)
    return paths


def verify_protected():
    recorded = read(OUT / 'protected_inputs.json')
    actual = {p: digest(ROOT / p) for p in recorded}
    assert actual == recorded, 'An original input, holdout, or app resource changed'
    return len(recorded)


def prepare():
    """Freeze application domain, class interpretation and samples BEFORE fitting."""
    assert not (OUT / 'fit_started.json').exists(), 'Do not revise a fitted protocol'
    OUT.mkdir(parents=True, exist_ok=True)
    save('protected_inputs.json', protected_files())
    feat, valid, inside, affine, profile, before, names = image_features()
    print('Original feature coverage verified', flush=True)
    frozen = pd.read_csv(OLD / 'spatial_pixel_predictions.csv')
    events = read(OLD / 'held_out_observation_results.json')
    train = frozen[frozen.split.eq(1)].copy()
    test = frozen[frozen.split.eq(2)].copy()
    assert len(test) == 15 and len(train) == 5205
    assert valid[frozen.row, frozen.col].all()
    assert np.allclose(before[test.row, test.col], test.rf_probability, atol=3e-8)
    label = np.full(valid.shape, -1, dtype='int8')
    groups = np.zeros(valid.shape, dtype='int32')
    label[train.row, train.col] = train.reference_class
    groups[train.row, train.col] = train.group
    occupied = np.zeros(valid.shape, dtype=bool)
    occupied[frozen.row, frozen.col] = True
    land, coast, _, coastinfo = __import__('evidence_pipeline').build_coast()
    land_interior = base.raster_mask(land.buffer(-100), valid, affine) & inside & valid
    assert int(((before >= .5) & land_interior).sum()) == 6709
    # Exclude all historical positive/ambiguous habitats, not only fitted polygons.
    a = gpd.read_file(base.OLD_REF, bbox=(-9.55, 51.42, -9.30, 51.56)).to_crs(2157)
    b = gpd.read_file(base.SSCO, where="Site_Code = '000101'").to_crs(2157)
    uncertain = unary_union(list(a[a.Community.str.contains('fucoid|Laminaria', case=False, na=False)].geometry.make_valid())
                            + list(b[b.Commun_Typ.str.contains('Laminaria|Sheltered reef', case=False, na=False)].geometry.make_valid()))
    reserves = unary_union([Point(*base.TO_ITM(e['lon'], e['lat'])).buffer(max(250, e['uncertainty_m'] or 0))
                            for e in events])
    test_geom = unary_union(gpd.read_file(OLD / 'spatial_split.geojson').query("split == 'test'").to_crs(2157).geometry)
    exclude = uncertain.buffer(20).union(reserves).union(test_geom.buffer(500))
    originals = pd.read_csv(OLD / 'spatial_polygon_results.csv')
    original_groups = originals[originals.split.eq('train')].copy()
    records = [{'group': int(r.group_id), 'binary_label': int(r['class']),
                'control_class': 'historical_intertidal_macroalgae_proxy' if r['class'] else 'historical_marine_other',
                'source': r.source, 'source_id': str(r.source_row), 'pixels': int(r.pixels)}
               for _, r in original_groups.iterrows()]
    selection, control_geoms = [], []
    nlc = nlc_polygons().sort_values('OBJECTID')
    print('NLC source geometry loaded:', len(nlc), flush=True)
    for nrow, (_, r) in enumerate(nlc.iterrows()):
        if nrow % 500 == 0:
            print('Preparing source polygon', nrow, '/', len(nlc), flush=True)
        cls = r.LEVEL_2_VALUE
        if cls not in VEGETATION + BARE + WATER:
            continue
        subtype = ('terrestrial_vegetation' if cls in VEGETATION else
                   'bare_shore_surface_proxy' if cls in BARE else 'water_surface_control')
        obj = {'source_id': int(r.OBJECTID), 'source_class': cls, 'control_class': subtype,
               'geometry_classification_source': r.POLY_GEOM_CAPTURE_SRC_VALUE,
               'label_capture_source': r.LEVEL_2_CAPTURE_SRC_VALUE,
               'image_date': r.IMAGE_1_CAPTURE_DATE,
               'satellite_date_from': r.SAT_IMAGE_1_DATE_FROM,
               'satellite_date_to': r.SAT_IMAGE_2_DATE_TO,
               'status': 'excluded', 'pixels': 0}
        # Split by entire SOURCE polygon, before clipping; never move the old holdout.
        if transform(base.TO_WGS, r.geometry).bounds[2] >= -9.385:
            obj['reason'] = 'source_polygon_not_wholly_west_of_training_boundary'
            selection.append(obj)
            continue
        g = r.geometry.buffer(-20).intersection(base.CONTEXT_DOMAIN).difference(exclude)
        if cls in VEGETATION:
            # Coast is only a predeclared training eligibility guard, never an output mask.
            g = g.intersection(land.buffer(-30))
        elif cls in BARE:
            g = g.intersection(coast.buffer(250))
        mask = base.raster_mask(g, valid, affine) & valid & ~occupied
        if not mask.any():
            obj['reason'] = 'no_clear_pixel_after_20m_erosion_spatial_and_reference_guards'
            selection.append(obj)
            continue
        # NLC is a separately produced 2018 map, NOT a field absence observation.
        gid = 10000 + int(r.OBJECTID)
        label[mask] = 0
        groups[mask] = gid
        occupied |= mask
        obj.update(status='selected', reason='historical_map_control_only', pixels=int(mask.sum()), group=gid)
        selection.append(obj)
        records.append({'group': gid, 'binary_label': 0, 'control_class': subtype,
                        'source': 'NLC2018', 'source_id': str(r.OBJECTID),
                        'source_class': cls, 'pixels': int(mask.sum())})
        control_geoms.append(base.feature(g, **obj))
    table = pd.DataFrame(records)
    counts = table.groupby('control_class').agg(pixels=('pixels', 'sum'), polygons=('group', 'size'))
    assert set(counts.index) >= {'terrestrial_vegetation', 'bare_shore_surface_proxy', 'water_surface_control'}, counts
    training = label >= 0
    rr, cc = np.where(training)
    coords = np.column_stack([affine.c+(cc+.5)*affine.a, affine.f+(rr+.5)*affine.e])
    separation = cKDTree(coords).query(test[['east_m', 'north_m']].values)[0]
    assert separation.min() > 500
    assert np.all(label[test.row, test.col] == -1), 'Test data entered training'
    assert np.array_equal(label[train.row, train.col], train.reference_class)
    assert np.array_equal(groups[train.row, train.col], train.group)
    weights = np.zeros(valid.shape)
    for cls in [0, 1]:
        subset = table[table.binary_label.eq(cls)]
        nclass = int((label == cls).sum())
        for _, r in subset.iterrows():
            weights[groups == r.group] = nclass/(len(subset)*r.pixels)
        assert np.isclose(weights[label == cls].sum(), nclass)
    samples = pd.DataFrame({'row': rr, 'col': cc, 'east_m': coords[:, 0], 'north_m': coords[:, 1],
                            'group': groups[rr, cc], 'binary_label': label[rr, cc],
                            'sample_weight': weights[rr, cc]})
    samples = samples.merge(table.drop(columns=['pixels', 'binary_label']), on='group', validate='many_to_one')
    samples.to_csv(OUT / 'training_samples.csv', index=False)
    table.to_csv(OUT / 'training_groups.csv', index=False)
    counts.to_csv(OUT / 'training_classes.csv')
    pd.DataFrame(selection).to_csv(OUT / 'control_selection_audit.csv', index=False)
    test.to_csv(OUT / 'frozen_test_copy.csv', index=False)
    save('training_controls.geojson', {'type': 'FeatureCollection', 'features': control_geoms})
    save('application_area.geojson', {'type': 'FeatureCollection', 'features': [
        base.feature(base.DOMAIN, role='application_and_error_audit', target='intertidal macroalgae', masks_land=False),
        base.feature(base.CONTEXT_DOMAIN, role='unchanged_training_context') ]})
    np.savez_compressed(OUT / 'prepared_arrays.npz', features=feat, valid=valid, inside=inside,
                        before=before, labels=label, groups=groups, weights=weights,
                        land_interior=land_interior)
    class_definitions = {
        'historical_intertidal_macroalgae_proxy': 'UNCHANGED positive: NPWS fucoid habitat intersected with intertidal community, 10m erosion; historical weak habitat label, not pixel-confirmed algae.',
        'historical_marine_other': 'UNCHANGED negative: NPWS sediment/deep reef habitat, 20m erosion; weak habitat negative, not a documented biological absence.',
        'terrestrial_vegetation': 'NEW negative: NLC2018 mapped grassland, woodland, scrub, bracken or heath; 20m polygon erosion and at least 30m inside OSM land.',
        'bare_shore_surface_proxy': 'NEW weak negative: NLC2018 exposed rock/coastal sediments within 250m of coast, eroded 20m; exposed surface classification, not proof of algae absence in 2022. Rocky intertidal absence is not independently confirmed.',
        'water_surface_control': 'NEW negative for the INTERTIDAL target: NLC2018 mapped lake/marine water, eroded 20m. This does not label the seabed or establish subtidal kelp absence.'}
    protocol = {
        'locked_before_refit': True, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'target': 'Intertidal macroalgae candidate extent, species-agnostic, for May-August 2022 imagery; NOT confirmed subtidal kelp.',
        'application_area': {'name': 'Sherkin eastern shore / Baltimore harbour entrance, Cork',
                             'bbox_wgs84': BBOX, 'area_km2': base.DOMAIN.area/1e6,
                             'training_context_bbox_wgs84': CONTEXT,
                             'all_grid_pixels': int(inside.sum()), 'assessed_pixels': int((inside & valid).sum()),
                             'scope': 'Predict ALL shared-valid pilot pixels, including land and water. Unlabelled classes remain application-domain risks. No land or habitat post-hoc mask.'},
        'single_change': 'Add externally mapped control samples; preserve original training rows and all held-out rows. No feature, model, threshold, positive-label or cloud-mask search.',
        'model': PARAMS, 'threshold': .5, 'features': names,
        'image_preprocessing': 'Exactly the previous 7 L2A dates, BOA offsets, 21 features and common valid-pixel mask; B11/SCL are natively 20m.',
        'training_classes': class_definitions, 'training_class_counts': counts.to_dict('index'),
        'new_control_spatial_rules': 'Whole NLC polygon west of -9.385; 20m inward buffer; exclude historical fucoid/Laminaria/sheltered habitats +20m, 500m around frozen test polygons, all 8 observation uncertainty buffers (minimum 250m). No image-threshold-derived labels.',
        'sample_weight': 'Same rule as baseline: equal total weight per polygon within binary class, preserve class total before balanced_subsample. Adding polygons necessarily redistributes negative-group weight; no separate tuning.',
        'minimum_training_test_distance_m': float(separation.min()),
        'holdout': {'pixels': 15, 'positive_pixels': 5, 'negative_pixels': 10, 'source_polygons': 2,
                    'events': len(events), 'intertidal_presence_events': 2,
                    'unchanged_original_csv_sha256': digest(OLD / 'spatial_pixel_predictions.csv'),
                    'unchanged_observations_sha256': digest(OLD / 'held_out_observation_results.json'),
                    'previous_results_already_seen': True,
                    'interpretation': 'Diagnostic agreement only; reused, previously inspected test cannot be an unbiased new model-selection test.'},
        'independence': {'npws_training_and_test_independent': False,
                        'new_control_label_source': SERVICE,
                        'nlc_labels_derived_from_2022_experiment': False,
                        'nlc_source': 'Separate national mapping workflow from 2018 aerial imagery, 2018 Sentinel-2 and existing national data. Feature provenance records Machine Learning / Multiple sources.',
                        'complete_upstream_source_independence_proven': False,
                        'warning': 'NLC is a model-derived historical label source. NPWS participated in the national mapping programme; complete upstream sample lineage is unavailable. Do not call it independent field truth or copy national accuracy figures into this pilot.',
                        'dated_presence': 'Two 2019 intertidal collection events remain held out; temporal mismatch, nearby locations, no absences and incomplete source lineage remain.'},
        'evaluation': ['Frozen 15-pixel historical diagnostic agreement: confusion counts, F1, balanced agreement, AUC; only 2 source polygons.',
                       'Same 8 reserved dated events, with intertidal and subtidal interpretation separate.',
                       'Before/after positive area on identical full-pilot coverage, plus OSM land-interior >100m diagnostic including residual errors.',
                       'Separate land error audit east of -9.375, beyond all new training source polygons; not added to the original labelled test.'],
        'coast_provenance': coastinfo['source_date'],
        'no_current_ecological_accuracy_claim': True,
        'no_species_or_subtidal_kelp_claim': True,
        'preserve_previous_product_requirements': True,
        'no_app_or_presentation_build': True,
        'sources': ['https://storymaps.arcgis.com/stories/187d2948da2f4ae6a6c68f202eb8f6f5',
                    'https://tailte.ie/wp-content/uploads/2025/03/National-Land-Cover-Map-Final-Report-2018.pdf', SERVICE]}
    save('protocol_before_refit.json', protocol)
    text = f"""# Frozen correction protocol — before model refit

Target: **intertidal macroalgae candidates in the seven May–August 2022 images**.
No species or confirmed subtidal kelp interpretation is supported.

Application: Sherkin eastern shore / Baltimore harbour entrance, Cork. WGS84
{BBOX}; {base.DOMAIN.area/1e6:.4f} km². Training context remains {CONTEXT}.
All {int((inside & valid).sum()):,} previously valid pilot pixels are predicted,
including land and water. No post-hoc land mask is allowed.

Only change: add separately mapped historical control samples. Original 5,205
training samples, 15 test pixels (two polygons), eight dated events, imagery,
features, RF settings, weighting rule and 0.5 threshold remain fixed. No parameter
search. Test results were already seen; all comparisons are diagnostic agreement.

"""
    for name, definition in class_definitions.items():
        text += f"* **{name}** — {definition} {int(counts.loc[name, 'pixels'])} pixels / {int(counts.loc[name, 'polygons'])} polygons.\n"
    text += """

New polygons must lie wholly west of -9.385 before clipping. Apply a 20 m interior
buffer, the stated class-specific geographical guards, historical habitat exclusions,
500 m test-polygon guard and at least 250 m around every reserved dated observation.
Images determine valid coverage only; NDVI, SCL classes, RF predictions and
spectral thresholds do not generate or select the external class labels.

NLC2018 uses 2018 aerial/Sentinel imagery and national data. It is separate from
our 2022 image experiment, but model-derived and temporally mismatched. Full
upstream lineage is unavailable, so full statistical/source independence is not
asserted. Bare-surface controls are weak historical surface labels; there are no
independently confirmed 2022 rocky-intertidal absence observations. Existing NPWS
train/test labels share provenance. All comparisons retain these limitations.

Evaluate the frozen historical pixels, reserved dated events, unchanged full-pilot
coverage and visible land-interior errors. Also report the eastern land-interior
audit outside training geography, without altering the original labelled holdout.
Do not import this diagnostic layer into the application. Preserve all previous
product requirements for later phases; no UI or presentation build.
"""
    (OUT / 'PROTOCOL_BEFORE_REFIT.md').write_text(text, encoding='utf-8')
    lock_files = ['protocol_before_refit.json', 'PROTOCOL_BEFORE_REFIT.md', 'training_samples.csv',
                  'training_groups.csv', 'training_classes.csv', 'control_selection_audit.csv',
                  'frozen_test_copy.csv', 'training_controls.geojson', 'application_area.geojson',
                  'prepared_arrays.npz', 'protected_inputs.json', 'nlc_acquisition.json']
    save('prefit_lock.json', {p: digest(OUT / p) for p in lock_files})
    verify_protected()
    print(counts.to_string())
    print('PREPARED, not fitted. Minimum train/test distance:', separation.min())


def diagnostic_metrics(y, score):
    result = base.metrics(np.asarray(y), (np.asarray(score) >= .5).astype(int), np.asarray(score))
    result['balanced_diagnostic_agreement'] = result.pop('balanced_accuracy')
    result['interpretation'] = 'Historical reference agreement, NOT current ecological accuracy'
    return result


def compare_events(probability, valid, affine, training):
    events = read(OLD / 'held_out_observation_results.json')
    tree = cKDTree(training[['east_m', 'north_m']].values)
    result = []
    for e in events:
        point = Point(*base.TO_ITM(e['lon'], e['lat']))
        row, col = rowcol(affine, point.x, point.y)
        assessed = bool(valid[row, col])
        assert assessed == e['l2a_point_assessed']
        nearest = float(tree.query([point.x, point.y])[0])
        assert nearest >= 240, 'Observation buffer leakage'
        item = {k: e[k] for k in ['event_group', 'date', 'lon', 'lat', 'taxa', 'dataset',
                                  'uncertainty_m', 'kind', 'source_independence']}
        item.update(assessed=assessed, nearest_training_pixel_m=nearest,
                    before_point_hit=e['rf_point_hit'], before_point_probability=e['rf_point_probability'],
                    after_point_hit=bool(probability[row, col] >= .5) if assessed else None,
                    after_point_probability=float(probability[row, col]) if assessed else None,
                    ecological_accuracy_trial=False)
        if e['uncertainty_m'] is not None:
            mask = base.raster_mask(point.buffer(e['uncertainty_m']), valid, affine) & valid
            item.update(before_buffer_hit=e.get('rf_buffer_hit'),
                        after_buffer_hit=bool((probability[mask] >= .5).any()) if mask.any() else None)
        result.append(item)
    intertidal = [e for e in result if e['kind'] == 'intertidal_macroalgae_presence']
    summary = {'events': len(result), 'intertidal_events': len(intertidal),
               'before_point_hits': sum(e['before_point_hit'] is True for e in intertidal),
               'after_point_hits': sum(e['after_point_hit'] is True for e in intertidal),
               'before_buffer_hits': sum(e.get('before_buffer_hit') is True for e in intertidal),
               'after_buffer_hits': sum(e.get('after_buffer_hit') is True for e in intertidal),
               'same_image_year_events': sum(e['date'].startswith('2022') for e in intertidal),
               'independent_absence_events': 0,
               'meaning': '2019 presence compatibility only; subtidal/unspecified kelp events are retained but not counted as intertidal accuracy trials.'}
    return result, summary


def preview(feat, before, after, valid, inside, land, affine):
    """Static scientific error diagnostic, no application UI changes."""
    from PIL import Image, ImageDraw, ImageFont
    font_path = 'C:/Windows/Fonts/arial.ttf'
    font = ImageFont.truetype(font_path, 19)
    small = ImageFont.truetype(font_path, 16)
    title = ImageFont.truetype(font_path, 25)
    rr, cc = np.where(inside)
    sl = np.s_[rr.min():rr.max()+1, cc.min():cc.max()+1]
    with np.errstate(invalid='ignore'):
        rgb = (np.clip(np.nan_to_num(feat[:, :, [7, 4, 1]]) / .22, 0, 1)**.7*255).astype('uint8')
    canvas = Image.new('RGB', (1420, 1035), '#f6f8fa')
    draw = ImageDraw.Draw(canvas)
    draw.text((35, 22), 'Cork | intertidal macroalgae correction — diagnostic only', fill='#173142', font=title)
    draw.text((35, 61), 'Same 2022 imagery and full pilot coverage. No post-hoc land mask. North is up; EPSG:2157.', fill='#364956', font=small)
    for x, label, proba in [(35, 'BEFORE | historical habitat labels', before),
                             (730, 'AFTER | added mapped surface controls', after)]:
        panel = rgb.copy()
        panel[~(valid & inside)] = [190, 195, 200]
        positive = (proba >= .5) & valid & inside
        panel[positive] = [32, 190, 104]
        panel[positive & land] = [220, 48, 128]
        im = Image.fromarray(panel[sl])
        factor = min(650/im.width, 740/im.height)
        im = im.resize((round(im.width*factor), round(im.height*factor)), Image.Resampling.NEAREST)
        draw.text((x, 105), label, fill='#173142', font=font)
        canvas.paste(im, (x, 141))
        y = 150 + im.height
        draw.text((x, y), f'Candidate output: {positive.sum()/100:.2f} ha', fill='#173142', font=font)
        draw.text((x, y+28), f'Land interior errors: {(positive & land).sum()/100:.2f} ha', fill='#9b1354', font=font)
        draw.line((x+12, y-30, x+12+round(500/10*factor), y-30), fill='white', width=4)
        draw.text((x+12, y-56), '500 m', fill='white', font=small)
    draw.rectangle((35, 952, 53, 970), fill=(32, 190, 104))
    draw.text((64, 950), 'RF candidate >= 0.5', fill='#173142', font=small)
    draw.rectangle((320, 952, 338, 970), fill=(220, 48, 128))
    draw.text((348, 950), 'Candidate on OSM land >100 m inland', fill='#173142', font=small)
    draw.rectangle((745, 952, 763, 970), fill=(190, 195, 200))
    draw.text((775, 950), 'Outside shared image coverage', fill='#173142', font=small)
    draw.text((35, 995), 'Not a species map; not confirmed subtidal kelp. Remaining errors are retained. Current ecological accuracy is unknown.', fill='#344c59', font=small)
    canvas.save(OUT / 'before_after_diagnostic.png')


def fit(reproduce=False):
    import joblib
    import importlib.metadata
    import platform
    locks = read(OUT / 'prefit_lock.json')
    assert all(digest(OUT / p) == value for p, value in locks.items()), 'Prefit artefact changed'
    protected_count = verify_protected()
    acquisition = read(OUT / 'nlc_acquisition.json')
    assert all(digest(OUT / 'nlc2018' / r['file']) == r['sha256'] for r in acquisition['requests'])
    protocol = read(OUT / 'protocol_before_refit.json')
    assert protocol['model'] == PARAMS
    if not reproduce:
        assert not (OUT / 'fit_started.json').exists(), 'One correction only; use --reproduce for the SAME locked model'
        save('fit_started.json', {'started_utc': datetime.now(timezone.utc).isoformat(),
                                 'prefit_lock_sha256': digest(OUT / 'prefit_lock.json'),
                                 'script_sha256': digest(__file__), 'variant': 'one controls-only correction'})
    arrays = np.load(OUT / 'prepared_arrays.npz')
    feat, valid, inside = arrays['features'], arrays['valid'], arrays['inside']
    before, label, weights = arrays['before'], arrays['labels'], arrays['weights']
    land_interior = arrays['land_interior']
    train = label >= 0
    samples = pd.read_csv(OUT / 'training_samples.csv')
    frozen = pd.read_csv(OLD / 'spatial_pixel_predictions.csv')
    test = frozen[frozen.split.eq(2)]
    copy = pd.read_csv(OUT / 'frozen_test_copy.csv')
    pd.testing.assert_frame_equal(test.reset_index(drop=True), copy)
    assert np.all(label[test.row, test.col] == -1)
    assert len(samples) == int(train.sum())
    assert np.array_equal(samples.binary_label, label[samples.row, samples.col])
    assert np.allclose(samples.sample_weight, weights[samples.row, samples.col])
    print('Fitting one locked correction:', int(train.sum()), 'pixels', flush=True)
    rf = RandomForestClassifier(**PARAMS)
    rf.fit(feat[train], label[train], sample_weight=weights[train])
    probability = np.full(valid.shape, np.nan)
    probability[valid] = rf.predict_proba(feat[valid])[:, 1]
    if reproduce:
        saved = np.load(OUT / 'corrected_probabilities_full_precision.npy')
        assert np.array_equal(saved, probability, equal_nan=True), 'Deterministic replay differs'
        verify_protected()
        save('reproduction_verification.json', {'same_locked_model_reproduced_exactly': True,
                                               'originals_unchanged': True, 'new_variant_or_tuning': False})
        print('EXACT REPRODUCTION PASSED')
        return
    with rasterio.open(OLD / 'rf_historical_intertidal_probability.tif') as ds:
        profile, affine = ds.profile.copy(), ds.transform
    assert np.array_equal(valid & inside, before != -9999)
    results = {'target': protocol['target'], 'status': 'DIAGNOSTIC_ONLY_NOT_AN_ACCEPTED_HABITAT_MAP',
               'single_change': protocol['single_change'], 'threshold': .5,
               'before': diagnostic_metrics(test.reference_class, test.rf_probability),
               'after': diagnostic_metrics(test.reference_class, probability[test.row, test.col]),
               'test_source_polygons': 2, 'test_unchanged': True,
               'independent_ecological_accuracy': None,
               'independent_current_kelp_accuracy': None,
               'protocol_sha256': digest(OUT / 'protocol_before_refit.json'),
               'training_class_counts': protocol['training_class_counts'],
               'minimum_training_test_distance_m': protocol['minimum_training_test_distance_m'],
               'no_posthoc_land_mask': True, 'no_parameter_search': True,
               'test_already_seen_and_used_for_diagnostics': True}
    test_results = test.copy()
    test_results['before_prediction'] = (test.rf_probability >= .5).astype(int)
    test_results['after_probability'] = probability[test.row, test.col]
    test_results['after_prediction'] = (test_results.after_probability >= .5).astype(int)
    test_results.to_csv(OUT / 'frozen_test_before_after.csv', index=False)
    polygon_results = test_results.groupby(['group', 'reference_class']).agg(
        pixels=('row', 'size'), before_positive_fraction=('before_prediction', 'mean'),
        after_positive_fraction=('after_prediction', 'mean'))
    polygon_results.to_csv(OUT / 'frozen_test_polygon_diagnostics.csv')
    east = base.raster_mask(transform(base.TO_ITM, box(-9.375, BBOX[1], BBOX[2], BBOX[3])), valid, affine)
    assert not np.any(east & train), 'Eastern land audit overlapped training'
    area_rows = []
    for name, mask in [('full_pilot_shared_valid', valid & inside),
                        ('land_interior_over_100m', land_interior),
                        ('east_land_interior_outside_training_geography', land_interior & east)]:
        area_rows.append({'domain': name, 'assessed_pixels': int(mask.sum()),
                          'before_positive_pixels': int(((before >= .5) & mask).sum()),
                          'after_positive_pixels': int(((probability >= .5) & mask).sum()),
                          'before_positive_ha': float(((before >= .5) & mask).sum()/100),
                          'after_positive_ha': float(((probability >= .5) & mask).sum()/100),
                          'interpretation': 'Geographic sanity diagnostic; not ecological accuracy. Full land audit includes training geography.'})
    results['area_diagnostics'] = area_rows
    pd.DataFrame(area_rows).to_csv(OUT / 'area_diagnostics.csv', index=False)
    events, presence = compare_events(probability, valid, affine, samples)
    save('reserved_events_before_after.json', events)
    pd.DataFrame(events).to_csv(OUT / 'reserved_events_before_after.csv', index=False)
    results['reserved_intertidal_presence_diagnostic'] = presence
    # Expose training-class fit separately, never as validation.
    fit_samples = samples.copy()
    fit_samples['after_probability'] = probability[fit_samples.row, fit_samples.col]
    fit_samples['after_positive'] = fit_samples.after_probability >= .5
    fit_samples.groupby('control_class').agg(pixels=('row', 'size'),
        after_positive_fraction=('after_positive', 'mean')).to_csv(OUT / 'training_fit_diagnostic_NOT_VALIDATION.csv')
    np.save(OUT / 'corrected_probabilities_full_precision.npy', probability)
    joblib.dump(rf, OUT / 'corrected_random_forest.joblib', compress=3)
    pd.DataFrame({'feature': protocol['features'], 'importance': rf.feature_importances_}).to_csv(
        OUT / 'feature_importance.csv', index=False)
    profile.update(dtype='float32', nodata=-9999, compress='deflate')
    out_raster = np.where(valid & inside, probability, -9999).astype('float32')
    with rasterio.open(OUT / 'intertidal_macroalgae_diagnostic_probability.tif', 'w', **profile) as ds:
        ds.write(out_raster, 1)
        ds.set_band_description(1, 'Uncalibrated intertidal macroalgae candidate score; diagnostic only, not kelp')
        ds.update_tags(target='intertidal macroalgae', ecological_accuracy='unknown', land_mask='none', threshold='0.5')
    with rasterio.open(OUT / 'intertidal_macroalgae_diagnostic_probability.tif') as ds:
        assert np.array_equal(ds.read(1), out_raster)
    preview(feat, before, probability, valid, inside, land_interior, affine)
    save('results.json', results)
    save('verification.json', {'original_files_checked': protected_count,
                               'originals_and_application_unchanged': verify_protected() == protected_count,
                               'original_heldout_rows_and_labels_unchanged': True,
                               'original_training_rows_preserved': True,
                               'no_training_test_overlap': True,
                               'identical_before_after_assessed_pilot_pixels': int((valid & inside).sum()),
                               'protocol_written_before_refit': True,
                               'raster_roundtrip_matches': True,
                               'no_land_mask': True, 'no_app_or_presentation_build': True})
    save('runtime.json', {'python': platform.python_version(),
                          'packages': {k: importlib.metadata.version(k) for k in
                                       ['numpy', 'pandas', 'geopandas', 'rasterio', 'pyproj', 'shapely', 'scipy', 'scikit-learn', 'joblib', 'Pillow']},
                          'script_sha256': digest(__file__),
                          'offline_replay': '.venv/Scripts/python.exe src/cork_pilot_correction.py --reproduce'})
    report(results)
    save('delivery_manifest.json', {'files': {str(p.relative_to(OUT)).replace('\\', '/'): digest(p)
                                             for p in OUT.rglob('*') if p.is_file() and p.name != 'delivery_manifest.json'},
                                    'source_script': str(Path(__file__).relative_to(ROOT)),
                                    'script_sha256': digest(__file__)})
    print(json.dumps(base.clean(results), indent=2))


def report(results):
    p = read(OUT / 'protocol_before_refit.json')
    before, after = results['before'], results['after']
    area = {r['domain']: r for r in results['area_diagnostics']}
    land = area['land_interior_over_100m']
    eastern = area['east_land_interior_outside_training_geography']
    presence = results['reserved_intertidal_presence_diagnostic']
    counts = p['training_class_counts']
    text = f"""# Cork: one focused intertidal macroalgae correction

The model was refitted once with added historical surface controls. **The target
is intertidal macroalgae candidates, not confirmed subtidal kelp.** All results are
diagnostics. This is not an accepted ecological map or a contemporary accuracy estimate.

## Application area and prefit record

Sherkin eastern shore / Baltimore harbour entrance, Cork; WGS84 {BBOX},
{base.DOMAIN.area/1e6:.4f} km². The original training context {CONTEXT} is unchanged.
Prediction covers all {p['application_area']['assessed_pixels']:,} shared-valid
10 m pixels in the pilot, including terrestrial land and water. Seven images from
May–August 2022 and all 21 spectral/temporal features are reused exactly. B11 and
SCL remain natively 20 m. See `PROTOCOL_BEFORE_REFIT.md`,
`protocol_before_refit.json` and their SHA256 lock in `prefit_lock.json`.

## Classes actually used

Binary Random Forest: positive = historical intertidal macroalgae habitat proxy;
negative = the four documented control/habitat categories below. Subclasses are
retained in sample provenance; the experiment does **not** claim a validated
five-class classifier.

| Training category | Pixels | Source polygons |
|---|---:|---:|
"""
    for name, values in counts.items():
        text += f"| {name} | {values['pixels']} | {values['polygons']} |\n"
    text += f"""
Original 23 positive and 5,182 negative pixels are preserved. The added vegetation,
bare-shore surface and water controls come from the **Tailte Éireann / EPA National
Land Cover Map 2018**. `control_selection_audit.csv` records every considered
source polygon, its source class, capture metadata and inclusion/exclusion reason.
`training_samples.csv` records every fitted grid cell, source group and weight.

NLC class definitions support vegetation, exposed surface and water labels; they
do not supply confirmed 2022 biological absence. Bare shore is therefore explicitly
a **historical exposed-surface proxy**. Water is a negative for the intertidal
target only, not evidence that subtidal kelp is absent. Unlabelled buildings,
artificial surfaces and other omitted classes remain application-domain risks.

New source polygons are wholly west of -9.385 before clipping, eroded 20 m, and
guarded against ambiguous/positive historical habitats, the frozen test and all
reserved dated events. Vegetation must be at least 30 m inside mapped land;
bare surfaces must be within 250 m of shore. These are prefit sampling rules,
**never prediction masks**. No NDVI, SCL label, model output or hand-drawn presumed
absence creates a training label. Images only restrict usable input coverage.
Minimum fitted-cell/test-cell separation: {p['minimum_training_test_distance_m']:.2f} m.

RF settings are unchanged: 300 trees, minimum leaf 10, maximum depth 12,
balanced_subsample, seed 20261015, threshold 0.5. Polygon weighting follows the
same within-class rule. Adding negative polygons changes their share of total
weight as an unavoidable part of this single correction. There was no threshold,
feature or hyperparameter search.

## Before / after: diagnostic agreement only

The original **15 test pixels in only two historical polygons** are untouched:
five positives and ten negatives. Their identities, labels and original input
file hash are locked. The prior results were already inspected, so this reused
holdout cannot be presented as an unbiased new model-selection test.

| Diagnostic | Before RF | Corrected RF |
|---|---:|---:|
| True positive / false negative | {before['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][1][1]} / {before['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][1][0]} | {after['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][1][1]} / {after['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][1][0]} |
| True negative / false positive | {before['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][0][0]} / {before['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][0][1]} | {after['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][0][0]} / {after['confusion_matrix_rows_reference_0_1_cols_prediction_0_1'][0][1]} |
| F1 agreement | {before['f1']:.4f} | {after['f1']:.4f} |
| Balanced agreement | {before['balanced_diagnostic_agreement']:.4f} | {after['balanced_diagnostic_agreement']:.4f} |
| ROC AUC agreement | {before['roc_auc']:.4f} | {after['roc_auc']:.4f} |
| Candidate output area (ha) | {area['full_pilot_shared_valid']['before_positive_ha']:.2f} | {area['full_pilot_shared_valid']['after_positive_ha']:.2f} |
| Candidate on mapped land >100 m inland (ha) | {land['before_positive_ha']:.2f} | {land['after_positive_ha']:.2f} |
| Eastern land >100 m inland, outside training geography (ha) | {eastern['before_positive_ha']:.2f} | {eastern['after_positive_ha']:.2f} |

Land-error domains and image coverage are identical before and after. The complete
land audit includes training geography; the separately reported eastern domain
(longitude east of -9.375) contains no training pixels. It has {eastern['assessed_pixels']}
assessed land pixels. It is a geographic diagnostic, not a new labelled ecological
test. The full output retains every remaining land error. The land check does not
detect every possible false positive on shore, buildings, water or submerged reefs.
Model output area is **not** measured algae area or a change estimate.

Eight dated events are retained unchanged. For the two applicable intertidal
presence events (both 2019), point compatibility is
{presence['before_point_hits']}/2 before and {presence['after_point_hits']}/2 after;
within the same recorded coordinate-uncertainty buffers it is
{presence['before_buffer_hits']}/2 and {presence['after_buffer_hits']}/2.
There are no 2022-matched or independently confirmed absence events. Subtidal or
unspecified kelp records are listed separately and never counted as intertidal
classification successes or failures. See `reserved_events_before_after.json`.

## Source independence and remaining limits

NPWS Article17 and SSCO share historical provenance. Their train/test polygons are
spatially separate, not genuinely independent reference products. The previously
documented Laminaria/faunal-label disagreement remains unresolved; neither map is
promoted to current ground truth.

NLC controls come from a separate production workflow with 2018 aerial and Sentinel-2
imagery, not the experiment's 2022 imagery. The cached per-feature metadata states
Machine Learning and Multiple sources. National datasets and NPWS participation
mean complete upstream source independence is **not proven**. These are externally
supported historical control labels, not independent field validation. National
NLC accuracy statistics are not transferred to this pilot. NLC's 2022 processing
dates must not be confused with its 2018 image dates.

The two reserved 2019 intertidal observation events have distinct collection dates
and sources but are few, close together, temporally mismatched and presence-only.
The positive training support remains just 23 pixels from two historical polygons.
No species identity, current ecological accuracy, subtidal kelp extent, decline,
restoration effect, wave protection or monetary benefit is inferred.

Next necessary step: collect an independently labelled, spatially separated
intertidal presence/absence and confuser dataset matched to imagery and tide,
including bare rock, wrack, sediment, terrestrial vegetation and water. Use a new
untouched evaluation set before any model acceptance or product integration.

## Reproduce and inspect

From `C:\\Users\\Elif\\Desktop\\OCEANHACKATHON`:

```powershell
.venv/Scripts/python.exe src/cork_pilot_correction.py --reproduce
```

This refits the **same locked configuration** offline from `prepared_arrays.npz`
and requires byte-exact full-precision probability reproduction; it does not alter
the protocol, original holdout, app or earlier outputs. It writes only a replay
verification record. For the first preparation/run the recorded command sequence
was `--acquire`, `--prepare`, `--fit`. Acquisition is not needed for replay.

* `results.json`, `frozen_test_before_after.csv`: exact before/after scores and rows.
* `before_after_diagnostic.png`: full-pilot diagnostic with visible land errors.
* `intertidal_macroalgae_diagnostic_probability.tif`: uncalibrated RF score;
  nodata = -9999 only for unchanged invalid/outside-pilot coverage.
* `corrected_random_forest.joblib`: fitted local model; `runtime.json`: versions.
* `verification.json`, `protected_inputs.json`, `delivery_manifest.json`: integrity.
* `nlc2018/`, `nlc_acquisition.json`: cached service responses and query provenance.

Original satellite detections, historical kelp references and modelled suitability
remain separate in the previous experiment directory. The working application,
presentations, original inputs and all earlier product requirements are preserved.
This output is not automatically promoted into any product layer.

## Sources

* [Tailte Éireann / EPA NLC2018 service]({SERVICE}) — locally cached feature provenance.
* [Official NLC definitions and production overview](https://storymaps.arcgis.com/stories/187d2948da2f4ae6a6c68f202eb8f6f5).
* [National Land Cover Map final report](https://tailte.ie/wp-content/uploads/2025/03/National-Land-Cover-Map-Final-Report-2018.pdf).
* Original experiment: `../cork_pilot_20261015/README.md` and source audit.
* © Tailte Éireann and EPA for NLC; © OpenStreetMap contributors for coast context.
  Raw NLC subset is retained locally for research provenance; no app publication.
"""
    (OUT / 'README.md').write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire', action='store_true')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--fit', action='store_true')
    parser.add_argument('--reproduce', action='store_true')
    args = parser.parse_args()
    if args.acquire:
        acquire()
    if args.prepare:
        prepare()
    if args.fit:
        fit()
    if args.reproduce:
        fit(reproduce=True)
