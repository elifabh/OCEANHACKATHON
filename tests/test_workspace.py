"""Regression checks for real-data components and unavailable ecological results."""
import unittest
import sys
import json
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from workspace_evidence import biodiversity_audit, geometry_indicators, reference_scenario, water_clarity, record


class WorkspaceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=json.loads((ROOT/'outputs/map/evidence.json').read_text(encoding='utf8'))
        cls.bio=biodiversity_audit(cls.d)

    def test_occurrence_deduplication_and_single_event_limit(self):
        b=self.bio
        self.assertEqual(b['records'],1854)
        self.assertEqual(b['duplicate_ids_removed'],0)
        self.assertEqual(b['site_count'],35)
        self.assertEqual(b['repeat_survey_sites'],0)
        self.assertEqual(sum(r['records'] for r in b['records_by_year']),b['records'])
        self.assertIsNone(b['local_bed_richness'])
        self.assertEqual(sum(g['recorded'] for g in b['groups']),14)
        self.assertEqual(sum(g['reference'] for g in b['groups']),17)

    def test_projected_overlap_is_bounded_and_not_fragmentation(self):
        result=geometry_indicators(self.d)
        self.assertAlmostEqual(result['0']['model_area_m2'],17500,delta=.1)
        for row in result.values():
            self.assertGreaterEqual(row['historical_overlap_fraction'],0)
            self.assertLessEqual(row['historical_overlap_fraction'],1)
            self.assertIsNone(row['actual_fragmentation'])

    def test_canonical_costs_use_current_inputs_and_keep_damage_null(self):
        r=reference_scenario(self.d)
        for key,band in r['bands'].items():
            self.assertAlmostEqual(band['capital_eur'],r['comparison_length_m']*self.d['costs']['rates'][key])
        self.assertEqual(r['inputs']['cost_share'],1)
        self.assertIsNone(r['avoided_damage_eur'])
        self.assertAlmostEqual(r['energy_fraction'],self.d['physical']['energy_fraction'],places=7)

    def test_missing_water_clarity_is_not_zero(self):
        with patch('pathlib.Path.exists',return_value=False):r=water_clarity()
        self.assertEqual(r['status'],'UNAVAILABLE');self.assertEqual(r['annual'],[])

    def test_missing_metric_has_no_invented_rating(self):
        r=record('x','Example',None,'m','proxy','source','old','regional','method','limits','measure')
        self.assertEqual(r['quantification_status'],'NOT_ASSESSED')
        self.assertIsNone(r['value']);self.assertNotIn('confidence',r)


if __name__=='__main__':unittest.main()
