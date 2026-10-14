"""Scientific parity between browser calculation and the Python ray engine."""
import json,math,subprocess,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import geopandas as gpd
from shapely.ops import unary_union
from coastal_physics import sample_bundle,connected_groups
from evidence_pipeline import build_coast

ROOT=Path(__file__).resolve().parents[1]


class ParametricTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=json.loads((ROOT/'outputs/map/evidence.json').read_text(encoding='utf8'))
        node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        script="""require('./src/parametric.js');const d=require('./outputs/map/evidence.json'),rows=[];
for(const [group,s] of Object.entries(d.parametric.scopes))for(const [offset,dir] of Object.entries(s.directions))for(const level of [0,1,2,3])for(const method of ['interpolated','fitted'])rows.push({group,offset,level,method,result:ParametricCoast.calculate(s,dir,d.costs.rates,{water_level_m:level,method})});process.stdout.write(JSON.stringify(rows));"""
        cls.rows=json.loads(subprocess.check_output([str(node),'-e',script],cwd=ROOT,text=True))
        kg=gpd.read_file(ROOT/'outputs/valuation/step3b2_flood_check.gpkg',layer='kelp_cells').to_crs(2157)
        cls.cells=list(kg.geometry.buffer(25,cap_style='square'));cls.depths=kg.depth_m.to_numpy()
        cls.groups={0:list(range(len(cls.cells))),**{i+1:g for i,g in enumerate(connected_groups(cls.cells))}}
        cls.land=build_coast()[0]

    def test_all_browser_model_scenarios_match_independent_python_geometry(self):
        for row in self.rows:
            with self.subTest(group=row['group'],offset=row['offset'],level=row['level'],method=row['method']):
                ids=self.groups[int(row['group'])]
                p=sample_bundle([self.cells[i] for i in ids],self.depths[ids],self.d['wave']['travel_deg']+int(row['offset']),water_level_m=row['level'],method=row['method'],land=self.land)
                r=row['result']
                self.assertEqual(r['status'],p['status'])
                for key in ['height_fraction','energy_fraction','coverage_fraction']:
                    if p[key] is None:self.assertIsNone(r[key])
                    else:self.assertAlmostEqual(r[key],p[key],places=7)

    def test_costs_have_real_geometry_and_no_causal_energy_scaling(self):
        for row in self.rows:
            r=row['result'];self.assertIsNone(r['avoided_damage_eur_per_year']);self.assertIsNone(r['ecosystem_service_value_eur'])
            self.assertFalse(any(r['replacement_validity'].values()))
            self.assertEqual(r['inputs']['cost_share'],1)
            self.assertAlmostEqual(r['bands']['low']['capital_eur'],r['comparison_length_m']*self.d['costs']['rates']['low'],places=6)
            self.assertAlmostEqual(r['bands']['low']['annualised_eur_per_year'],r['bands']['low']['capital_eur']*.04/(1-1.04**-50),places=5)

    def test_cork_selection_does_not_silently_relax_depth_or_species(self):
        s=self.d['cork_screen'];self.assertEqual(len(s['clusters']),103)
        self.assertGreater(s['firkeel']['depth_min_m'],10)
        self.assertEqual(s['firkeel']['eligible_4_to_10m'],0)
        inner=next(r for r in s['aois'] if r['site']=='inner_roaringwater')
        self.assertEqual(inner['status'],'SPECIES_AND_EXPOSURE_MISMATCH')
        self.assertGreater(inner['depth_eligible'],0)
        self.assertEqual(s['cape_clear']['groups'],s['cape_clear']['incoming_blocked_groups'])
        from run_segment import run_segment
        r=run_segment('inner_roaringwater',bearing=33)
        self.assertEqual(r['status'],'SPECIES_AND_EXPOSURE_MISMATCH')
        self.assertIsNone(r['height_fraction'])

    def test_shoreline_quadrature_is_not_protected_frontage(self):
        p=self.d['parametric'];self.assertIsNone(p['validity']['ecosystem_service_value_eur'])
        for scope in p['scopes'].values():
            for direction in scope['directions'].values():
                shore=direction['shoreline'];self.assertEqual(shore['step_m'],10)
                self.assertAlmostEqual(shore['length_m'],sum(f['properties']['length_m'] for f in shore['layer']['features']),places=5)
                self.assertTrue(all(f['properties']['status']=='GEOMETRIC_CANDIDATE_NOT_VERIFIED_PROTECTED' for f in shore['layer']['features']))

if __name__=='__main__':unittest.main()
