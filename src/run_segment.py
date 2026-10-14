"""Reusable local screening entry point. No habitat input means no estimate.

Example: python src/run_segment.py --site mizen_outer
Species and exposure suitability must pass before the laboratory model is used.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box
from coastal_physics import connected_groups, sample_bundle, finite

ROOT=Path(__file__).resolve().parents[1]


def run_segment(site, *, threshold=None, bearing=None, water_level=0, predictions=None):
    report=json.loads((ROOT/'outputs/model/model_multisite_report.json').read_text())
    threshold=finite(report['operating_threshold'] if threshold is None else threshold,'threshold')
    if not 0<=threshold<=1:raise ValueError('Threshold must lie in [0,1]')
    data=pd.read_csv(predictions or ROOT/'outputs/model/suitability_multisite_predictions.csv')
    required={'aoi','assessed','suitability','depth_m','lon','lat'}
    if not required.issubset(data.columns):raise ValueError('Prediction schema incomplete')
    if site not in set(data.aoi):raise ValueError('Unknown site; use an AOI present in the input')
    local=data[data.aoi==site]
    assessed=local[local.assessed==1]
    above=assessed[assessed.suitability>=threshold]
    eligible=above[above.depth_m.between(4,10)]
    result={'site':site,'status':'NO_ELIGIBLE_HABITAT_INPUT','grid_cells':len(local),
        'assessed_cells':len(assessed),'above_threshold':len(above),'depth_eligible_cells':len(eligible),
        'threshold':threshold,'height_fraction':None,'energy_fraction':None,
        'avoided_damage_eur':None,'habitat_validated':False,'local_wave_calibrated':False,
        'note':'External habitat validation failed. No inference of habitat absence, zero protection or economic benefit.'}
    if site=='inner_roaringwater':
        result.update(status='SPECIES_AND_EXPOSURE_MISMATCH',note='Available inner-bay reference describes Saccharina/Saccorhiza in sheltered conditions. L. hyperborea laboratory attenuation coefficients are not transferable without validation.')
    elif len(eligible):
        result['status']='LOCAL_INCIDENT_WAVE_INPUT_REQUIRED'
        if bearing is not None:
            bearing=finite(bearing,'bearing')%360
            t=Transformer.from_crs(4326,2157,always_xy=True)
            points=[t.transform(r.lon,r.lat) for r in eligible.itertuples()]
            cells=[box(x-25,y-25,x+25,y+25) for x,y in points]
            groups=connected_groups(cells)
            # Each connected footprint is reported separately. No cross-island
            # propagation or alongshore protection is inferred without land data.
            effects=[sample_bundle([cells[i] for i in ids],eligible.depth_m.to_numpy()[ids],bearing,water_level_m=water_level) for ids in groups]
            result.update(status='CONDITIONAL_GEOMETRY_DEMONSTRATION',groups=effects,
                          group_count=len(groups),wave_travel_scenario_deg=bearing,
                          note='Local depth/model inputs; user-supplied direction. Separate groups, no land-barrier, nearshore or receptor validation. No aggregated coastal-protection estimate.')
    result['summary']=(f"Mizen outer coast: {len(assessed):,} of {len(local):,} cells are within the original assessment mask. "
        f"{len(above):,} meet the {threshold:g} threshold. The pipeline returns no estimate instead of inventing zero protection.") if site=='mizen_outer' else f"{site}: {len(eligible)} depth-eligible model cells; {result['status']}."
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--site',default='mizen_outer');p.add_argument('--threshold',type=float)
    p.add_argument('--bearing',type=float);p.add_argument('--water-level',type=float,default=0)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    result=run_segment(a.site,threshold=a.threshold,bearing=a.bearing,water_level=a.water_level)
    text=json.dumps(result,indent=2,allow_nan=False)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8')
    print(text)
