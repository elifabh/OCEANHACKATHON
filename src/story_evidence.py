"""Story context derived from local evidence. No new valuation or habitat inference."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def build_story(data):
    model=json.loads((ROOT/'outputs/model/model_multisite_report.json').read_text())
    archive=json.loads((ROOT/'outputs/anaird/anaird_phaseb_summary.json').read_text())
    name='Kilkieran Bay and Islands SAC'
    return {
        'prepared_date':'2026-10-14',
        'purpose':'Transparent coastal screening and a clearer next field decision.',
        'ecology_source':'https://doi.org/10.1002/lno.11890',
        'sites':[
            {'id':'cork','name':'Roaringwater Bay / Sherkin','county':'West Cork','lat':51.465,'lon':-9.405,
             'role':'PRIMARY OPERATIONAL PILOT','why':'Local satellite, depth, wave and historical habitat evidence overlap here.',
             'evidence':'Sentinel-2 intertidal proxy; NPWS historical communities; local model cells; offshore CMEMS waves.',
             'calculated':f"{data['site']['area_ha']:.2f} ha model footprint. Conditional wave effects and adjustable engineering funding comparison.",
             'limit':'Present kelp and protected assets remain unvalidated. Actual avoided damage is not quantified.'},
            {'id':'galway','name':'Kilkieran Bay / An Aird','county':'Galway','lat':archive['site']['lat'],'lon':archive['site']['lon'],
             'role':'ARCHIVED METHOD / TRANSFER CONTEXT','why':'A different coast tests how much the method depends on local habitat and exposure.',
             'evidence':'NPWS historical dive/video mapping; existing local An Aird archive. Kilkieran also contributed to model training.',
             'calculated':'An archived physical scenario exists, using the older grid-axis method. It has not been rerun with the current Cork ray engine.',
             'limit':'Not independent validation of the final model. No current comparable euro or avoided-damage result is asserted.',
             'archived_run_utc':archive['run_utc'],'training_site':name in model['sites_used'],
             'legacy_loso_auc':model['auc']['per_site'][name],
             'legacy_conditions':{'service_equivalence':'partly met in archive','least_cost':'untested','demand':'not demonstrated'},
             'source':'https://www.npws.ie/protected-sites/sac/002111'},
            {'id':'clare','name':'Kilkee Harbour','county':'Clare','lat':52.68,'lon':-9.65,
             'role':'PUBLISHED ECOLOGY CONTEXT','why':'Field research connects the story to living Irish kelp ecosystems.',
             'evidence':'Schoenrock et al. (2021) includes Newfy, Kilkee Harbour among its western Irish monitoring settings.',
             'calculated':'No local habitat extent, protected road or euro result calculated by this app.',
             'limit':'The marker locates the harbour approximately, not an exact study transect.',
             'source':'https://doi.org/10.1002/lno.11890'}],
        'selected_action':{'area':'Sherkin model group 1','now':'Plan a habitat verification visit and review historical reference conflicts before ranking restoration.',
                           'next':'Confirm species, extent and density. Pair wave measurements across habitat, with tide and period, before modelling asset-level hazard.',
                           'user_gain':'One traceable screening brief for the ecology and coastal-engineering team.'},
        'disclosure':'AI-assisted preparation before 16–18 October. Event contributions must be added with names and evidence after they happen.'
    }
