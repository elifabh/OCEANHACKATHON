import math, json, sys, geopandas as gpd, rasterio
from shapely.geometry import box
from rasterio.crs import CRS as RC
from rasterio.warp import transform as wt
sys.path.insert(0, 'src')
from common import arcgis_request, INFOMAR_BATHY, ArcGISError

B = [-9.93, 51.75, -9.78, 51.81]

h = gpd.read_file('data/npws/gis_files/21 NPWSArticle17Habitat.shp').to_crs(4326)
k = h[(h.Community == 'Laminaria-dominated reef') & h.intersects(box(*B))]
print('kelp poligon:', len(k), '| ha:', round((k.to_crs(2157).geometry.area / 1e4).sum(), 1))

pts, y = [], B[1]
while y < B[3]:
    x = B[0]
    while x < B[2]:
        pts.append([x, y])
        x += 100 / (111320 * math.cos(math.radians(51.78)))
    y += 100 / 110574
print('grid:', len(pts))

with rasterio.open('data/fetch/log10_eu200m1a.tif') as s:
    xs, ys = wt(RC.from_epsg(4326), s.crs, [p[0] for p in pts], [p[1] for p in pts])
    n = sum(1 for v in s.sample(list(zip(xs, ys)), indexes=1, masked=True)
            if not (hasattr(v[0], 'mask') and v[0].mask))
print('FETCH kapsama:', n, '/', len(pts))

d = 0
for i in range(0, len(pts), 400):
    try:
        p = arcgis_request(f'{INFOMAR_BATHY}/getSamples', {
            'geometry': json.dumps({'points': pts[i:i+400],
                                    'spatialReference': {'wkid': 4326}}),
            'geometryType': 'esriGeometryMultipoint',
            'returnFirstValueOnly': 'true',
            'interpolation': 'RSP_NearestNeighbor', 'f': 'json'})
        d += sum(1 for s_ in p.get('samples', []) if s_.get('value') not in (None, '', 'NaN'))
    except ArcGISError:
        pass
print('INFOMAR derinlik kapsama:', d, '/', len(pts))