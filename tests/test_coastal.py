"""Numerical and evidence regression tests; synthetic fixtures are not findings."""
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np
from shapely.geometry import Point, LineString, box, shape
from shapely.ops import transform, unary_union
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from coastal_physics import damping,effect,sample_bundle,ray_effect,path_status,avoided_damage,connected_groups,projected_intervals
from coastal_cost_calculator import calculate,capital_recovery_factor,unit_rates,read_inputs,snapshot_from_html
from run_segment import run_segment
from evidence_pipeline import build_sst


class PhysicsTests(unittest.TestCase):
    def test_published_coefficients(self):
        for d,k in zip([4,6,8,10],[.0094,.0032,.0014,.0005]):self.assertAlmostEqual(damping(d),k)
        self.assertAlmostEqual(damping(9),.00095)
    def test_depth_domain_rejects_extrapolation(self):
        for d in [3.99,10.01,None,float('nan'),True]:
            with self.assertRaises((ValueError,TypeError)):damping(d)
    def test_energy_uses_squared_height(self):
        r=effect(.1)
        self.assertAlmostEqual(1-r['energy_fraction'],(1-r['height_fraction'])**2)
        self.assertEqual(effect(0)['energy_fraction'],0)
    def test_exact_square_chord(self):
        r=ray_effect([box(0,0,50,50)],[8],Point(25,25),0)
        self.assertAlmostEqual(r['path_m'],50)
        self.assertAlmostEqual(r['height_fraction'],1-math.exp(-.0014*50))
        diagonal=ray_effect([box(0,0,50,50)],[8],Point(25,25),45)
        self.assertAlmostEqual(diagonal['path_m'],math.sqrt(2)*50,places=6)
    def test_offset_diagonal_shortens_chord(self):
        r=ray_effect([box(0,0,50,50)],[8],Point(45,5),45)
        self.assertLess(r['path_m'],20)
    def test_disconnected_width_excludes_gaps(self):
        cells=[box(0,0,50,50),box(150,0,200,50)]
        self.assertEqual(connected_groups(cells),[[0],[1]])
        r=sample_bundle(cells,[8,8],0)
        self.assertEqual(r['wave_intercept_m'],100)
        self.assertEqual(r['envelope_width_m'],200)
        self.assertAlmostEqual(r['path_m_mean'],50)
    def test_ray_land_barrier_is_missing_not_zero(self):
        cells=[box(0,0,50,50),box(0,150,50,200)]
        r=ray_effect(cells,[8,8],Point(25,25),0,land=box(-10,75,60,100))
        self.assertEqual(r['status'],'LAND_BETWEEN_HABITAT');self.assertIsNone(r['height_fraction'])
    def test_domain_failure_and_empty_are_not_zero(self):
        r=sample_bundle([box(0,0,50,50)],[9.5],0,water_level_m=1)
        self.assertIsNone(r['energy_fraction']);self.assertEqual(r['coverage_fraction'],0)
        self.assertIsNone(sample_bundle([],[],0)['height_fraction'])
    def test_no_intersection_is_supported_physical_zero(self):
        r=ray_effect([box(0,0,50,50)],[8],Point(200,0),0)
        self.assertEqual(r['status'],'NO_HABITAT_INTERSECTION');self.assertEqual(r['energy_fraction'],0)
    def test_spacing_is_positive(self):
        with self.assertRaises(ValueError):sample_bundle([box(0,0,50,50)],[8],0,spacing_m=0)
    def test_path_direction_and_island(self):
        empty=unary_union([])
        island=box(-10,40,10,60)
        self.assertEqual(path_status(Point(0,0),Point(0,100),island,island.boundary,0)['status'],'LAND_BLOCKED')
        self.assertEqual(path_status(Point(0,0),Point(0,-100),empty,empty,0)['status'],'OUTSIDE_DIRECTION_SCREEN')
        self.assertEqual(path_status(Point(0,0),Point(0,100),empty,empty,359)['status'],'DIRECTIONALLY_PLAUSIBLE_UNVALIDATED')
        self.assertEqual(path_status(Point(0,0),Point(0,100),None,None,0)['status'],'LAND_MASK_UNAVAILABLE')
    def test_unknown_damage_is_not_zero(self):
        self.assertIsNone(avoided_damage()['eur_per_year'])
        self.assertIsNone(avoided_damage([100,0],[80,0],[0,1])['eur_per_year'])
    def test_damage_curve_analytical_integral_and_supported_zero(self):
        self.assertAlmostEqual(avoided_damage([100,0],[80,0],[0,1],validated=True)['eur_per_year'],10)
        self.assertEqual(avoided_damage([100,0],[100,0],[0,1],validated=True)['status'],'QUANTIFIED_ZERO')
    def test_bad_probability_and_loss_curves_rejected(self):
        for a,b,p in [([100,0],[80,0],[.01,1]),([0,100],[0,80],[0,1]),([100,np.nan],[0,0],[0,1])]:
            with self.assertRaises(ValueError):avoided_damage(a,b,p,validated=True)


class CostTests(unittest.TestCase):
    def test_original_scenario_preserved(self):
        r=calculate(17500,100,.152,.04,50)
        self.assertAlmostEqual(r['inferred_comparison_frontage_m'],175)
        self.assertAlmostEqual(r['bands']['low']['pro_rata_cost_scenario_eur'],114795.47483870966)
        self.assertAlmostEqual(r['bands']['high']['pro_rata_cost_scenario_eur'],190203.3)
        self.assertAlmostEqual(r['bands']['low']['annualised_pro_rata_scenario_eur_per_year'],114795.47483870966*capital_recovery_factor(.04,50))
        self.assertIsNone(r['annual_avoided_damage_eur'])
    def test_width_monotonicity(self):
        a=calculate(17500,50,.152,.04,50);b=calculate(17500,100,.152,.04,50)
        self.assertAlmostEqual(a['bands']['low']['pro_rata_cost_scenario_eur'],2*b['bands']['low']['pro_rata_cost_scenario_eur'])
    def test_zero_interest_and_tiny_rate_stability(self):
        self.assertEqual(capital_recovery_factor(0,50),.02)
        self.assertAlmostEqual(capital_recovery_factor(1e-12,50),.02,places=10)
    def test_zero_share_does_not_turn_into_zero_damage(self):
        r=calculate(17500,100,0,0,50)
        self.assertEqual(r['bands']['low']['pro_rata_cost_scenario_eur'],0)
        self.assertIsNone(r['avoided_damage_eur'])
    def test_invalid_cost_inputs(self):
        for args in [(17500,0,.152,.04,50),(17500,100,None,.04,50),(17500,100,1.01,.04,50),(17500,100,.152,-1,50),(17500,100,.152,.04,0),(17500,100,.152,.04,float('inf'))]:
            with self.assertRaises(ValueError):calculate(*args)
    def test_pooled_funding_is_length_weighted(self):
        self.assertAlmostEqual(unit_rates()['project_pooled'],(668921+657338+500535)/(155+100+70))


class BuiltEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.d=json.loads((ROOT/'outputs/map/evidence.json').read_text(encoding='utf-8'))
    def test_seven_cells_area_and_disjoint_groups(self):
        t=Transformer.from_crs(4326,2157,always_xy=True).transform
        cells=[transform(t,shape(f['geometry'])) for f in self.d['cells']['features']]
        self.assertEqual(len(cells),7);self.assertAlmostEqual(unary_union(cells).area,17500,delta=.1)
        self.assertEqual([len(x) for x in connected_groups(cells)],[5,1,1])
    def test_land_ocean_alignment(self):
        land=shape(self.d['coastline']['land']['features'][0]['geometry'])
        # The Abbey, OSM relation/5344826, is a mapped building on Sherkin.
        self.assertTrue(land.contains(Point(-9.40024047,51.47613390)))
        for f in self.d['cells']['features']:self.assertFalse(land.covers(shape(f['geometry']).centroid))
        self.assertEqual(self.d['coastline']['unresolved_faces'],0)
    def test_no_restricted_fields_and_no_local_paths(self):
        text=json.dumps(self.d).lower()
        for forbidden in ['intersects_any_supplied_extent','distance_to_flood_extent_m','ncfhm_itm_ext','c:\\users','api_key','access_token']:
            self.assertNotIn(forbidden,text)
    def test_unknown_and_source_specific_indicators(self):
        self.assertIsNone(self.d['avoided_damage']['eur_per_year'])
        self.assertIsNone(self.d['measured_kelp_decline']['percent'])
        self.assertEqual((self.d['biodiversity']['present'],self.d['biodiversity']['total']),(14,17))
        self.assertEqual((self.d['historical']['historical_centre_matches'],self.d['historical']['disputed_cells']),(79,126))
        self.assertGreater(self.d['historical']['fpr_prior'],self.d['historical']['fpr_acceptance'])
    def test_asset_inventory_and_accounting(self):
        a=self.d['assets'];self.assertEqual(a['inventory_records'],699)
        self.assertEqual(sum(a['counts'].values()),a['mapped_records'])
        self.assertTrue(any('road_path' in f['properties']['kind'] for f in a['layer']['features']))
        self.assertTrue(all(f['properties']['avoided_damage_eur'] is None for f in a['layer']['features']))
    def test_direction_convention(self):
        w=self.d['wave'];self.assertAlmostEqual((w['from_deg']+180)%360,w['travel_deg'])
        self.assertGreater(w['distance_to_model_centroid_m'],5000)
        self.assertTrue(all(.99<=r['coverage_fraction']<=1 for r in w['annual']))
    def test_ray_quadrature_convergence(self):
        t=Transformer.from_crs(4326,2157,always_xy=True).transform
        cells=[transform(t,shape(f['geometry'])) for f in self.d['cells']['features']]
        depth=[f['properties']['depth_m_LAT'] for f in self.d['cells']['features']]
        r=sample_bundle(cells,depth,self.d['wave']['travel_deg'],spacing_m=1)
        self.assertAlmostEqual(r['height_fraction'],self.d['physical']['height_fraction'],delta=.0006)
    def test_legacy_cli_reads_current_schema(self):
        r=read_inputs(ROOT);self.assertEqual(r['model_area_m2'],17500);self.assertAlmostEqual(r['energy_reduction_fraction'],.152)
        with self.assertRaises(ValueError):snapshot_from_html('const D = null;')
    def test_transfer_no_suitable_cells_is_no_estimate(self):
        r=run_segment('mizen_outer')
        self.assertEqual(r['assessed_cells'],556);self.assertEqual(r['above_threshold'],0)
        self.assertIsNone(r['height_fraction']);self.assertIsNone(r['avoided_damage_eur'])
    def test_optional_sst_missing_stays_unknown(self):
        with patch('pathlib.Path.exists',return_value=False):r=build_sst()
        self.assertEqual(r['status'],'UNAVAILABLE');self.assertEqual(r['annual'],[])


if __name__=='__main__':unittest.main(verbosity=2)
