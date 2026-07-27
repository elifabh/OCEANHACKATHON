import json, sys
sys.path.insert(0, "src")
from common import INFOMAR_BATHY, arcgis_request, ArcGISError

# Northern strip of inner_roaringwater: the band that used to return HTTP 400.
strip = [[-9.5192 + i * 0.0016, 51.5345 + j * 0.001]
         for j in range(6) for i in range(50)]
# Southern part of the same AOI: known to have coverage.
south = [[-9.5192 + i * 0.0016, 51.4950 + j * 0.001]
         for j in range(6) for i in range(50)]

cases = [
    ("A  all-empty strip only", strip[:100]),
    ("B  half strip, half covered", strip[:50] + south[:50]),
    ("C  covered area only", south[:100]),
]
rule = {"mosaicMethod": "esriMosaicNorthwest", "where": "Category = 1"}

for label, pts in cases:
    for tag, mr in (("with where-clause", rule), ("no mosaicRule    ", None)):
        params = {
            "geometry": json.dumps({"points": pts,
                                    "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            "f": "json",
        }
        if mr:
            params["mosaicRule"] = json.dumps(mr)
        try:
            r = arcgis_request(f"{INFOMAR_BATHY}/getSamples", params)
            print(f"OK    {label:<30} {tag}  samples={len(r.get('samples', []))}")
        except ArcGISError as e:
            print(f"FAIL  {label:<30} {tag}  -> {e.message}")
