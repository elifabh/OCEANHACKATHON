"""Cape numerical parity, spatial provenance and no cross-case evidence leakage."""
import json, math, subprocess, unittest, sys
from pathlib import Path
from collections import Counter
from shapely.geometry import shape, Point, LineString
from shapely.ops import transform
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from evidence_pipeline import TO_ITM
from coastal_physics import damping, effect, direction_vector
class CapeProduct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=json.loads((ROOT/'outputs/map/evidence.json').read_text(encoding='utf8'))
        cls.p=cls.d['product'];cls.c=cls.p['cases']['cape_clear'];cls.f=ROOT/'outputs/cork_feasibility_20261015'
        node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        code="""require('./src/parametric.js');const p=require('./outputs/map/evidence.json').product,c=p.cases.cape_clear,rows=[];for(const [key,d]of Object.entries(c.scenario.directions))for(const level of [0,1,2,3])for(const method of ['interpolated','fitted'])for(const m of [.5,1,1.5])rows.push({key,level,method,m,result:ParametricCoast.calculate(c.scenario,d,p.costs.cost_rates,{water_level_m:level,method,coefficient_multiplier:m,length_mode:'fixed_frontage',frontage_m:100})});process.stdout.write(JSON.stringify(rows));"""
        cls.rows=json.loads(subprocess.check_output([str(node),'-e',code],cwd=ROOT,text=True))
    def test_864_scenarios_match_python_geometry_and_kernel(self):
        cell=next(f for f in json.loads((self.f/'sample_cells.geojson').read_text())['features'] if f['properties']['site']=='cape_clear' and f['properties']['sample_id']==1351)
        poly=transform(TO_ITM,shape(cell['geometry']));pt=TO_ITM(*self.c['case']['habitat_scenario_origin_lonlat'])
        for row in self.rows:
            u=direction_vector((int(row['key'])+180)%360)
            line=LineString([(pt[0]-100*u[0],pt[1]-100*u[1]),(pt[0]+100*u[0],pt[1]+100*u[1])]);length=line.intersection(poly).length
            r=row['result'];self.assertAlmostEqual(length,r['path_m_mean'],places=6)
            depth=cell['properties']['point_depth_m']+row['level']
            if depth>10:self.assertIsNone(r['height_fraction']);self.assertIsNone(r['with_relative_height'])
            else:
                expected=effect(length*damping(depth,row['method'])*row['m'])
                self.assertAlmostEqual(r['height_fraction'],expected['height_fraction'],places=7)
                self.assertAlmostEqual(r['energy_fraction'],expected['energy_fraction'],places=7)
            self.assertIsNone(r['avoided_damage_eur_per_year']);self.assertIsNone(r['ecosystem_service_value_eur'])
            self.assertAlmostEqual(r['bands']['project_pooled']['capital_eur'],562090.461538,places=5)
        self.assertEqual(len(self.rows),864)
    def test_selected_case_reproduces_saved_feasibility(self):
        for old in self.c['case']['example_paths']:
            new=self.c['scenario']['directions'][str(old['from_deg'])]
            # Saved WGS84 origin is rounded to eight decimal places; allow 1 mm.
            self.assertTrue(new['open_upwave_5km']);self.assertAlmostEqual(new['chord_m'],old['sampling_cell_chord_m'],delta=.001)
            self.assertAlmostEqual(new['shore_distance_m'],old['water_path_to_shore_m'],places=3)
        self.assertEqual(self.c['wave']['hours'],87672)
        self.assertAlmostEqual(sum(s['flux_proxy_fraction'] for s in self.c['wave']['sectors']),1,places=6)
        share=sum(s['flux_proxy_fraction'] for s in self.c['wave']['sectors'] if s['from_deg'] in [200,210])
        self.assertAlmostEqual(share,.06817351,places=7)
        self.assertTrue(any(not d['open_upwave_5km'] for d in self.c['scenario']['directions'].values()))
    def test_biodiversity_is_spatially_local_and_flags_are_retained(self):
        raw=json.loads((ROOT/'outputs/obis_raw_occurrences.json').read_text());b=self.c['bounds'];expected={}
        for r in raw:
            x,y=r.get('decimalLongitude'),r.get('decimalLatitude')
            if x is not None and y is not None and b[0]<=x<=b[2] and b[1]<=y<=b[3]:expected[(r.get('dataset_id'),r.get('occurrenceID') or r.get('id'))]=r
        bio=self.c['biodiversity'];self.assertEqual(bio['inventory_count'],len(expected));self.assertEqual(len(expected),154)
        self.assertEqual(bio['on_land_flag_count'],sum('ON_LAND' in (r.get('flags') or []) for r in expected.values()))
        self.assertIsNone(bio['local_bed_richness']);self.assertFalse(bio['sampling_effort_standardised'])
    def test_support_cases_and_claim_boundaries(self):
        self.assertEqual(set(self.p['cases']),{'cape_clear','sherkin','copper_point','bantry'})
        self.assertEqual(self.p['default_case'],'cape_clear');self.assertEqual(self.p['training_runs'],0)
        for c in self.p['cases'].values():
            for key in ['current_observed_kelp_geometry','habitat_condition','measured_decline_rate','avoided_damage_eur_per_year']:self.assertIsNone(c[key])
        for name in ['copper_point','bantry']:self.assertIsNone(self.p['cases'][name]['scenario'])
        self.assertEqual(len(self.c['intertidal']['features']),0)
        self.assertGreater(len(self.p['cases']['sherkin']['intertidal']['features']),0)
        self.assertEqual(len(self.p['promise_sections']),7)
if __name__=='__main__':unittest.main()
