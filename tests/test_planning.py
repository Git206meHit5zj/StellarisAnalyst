import json
from pathlib import Path
import tempfile
import unittest

from planning import labour_overview, rural_rule_reference, target_estimate


def fixture():
    return {'economy': {'resources': {'food': {'net': '-21'}, 'energy': {'net': '-2'}}},
            'colonies': [{'colony_id': '0', 'employable_pops': '300', 'jobs': [
                {'type': 'agri_drone', 'workforce': '100', 'max_workforce': '300'},
                {'type': 'technician_drone', 'workforce': '100', 'max_workforce': '200'},
                {'type': 'civilian', 'workforce': '-1', 'max_workforce': '-1'}]}]}


class PlanningTests(unittest.TestCase):
    def test_existing_capacity_and_shared_idle_labour(self):
        plan = target_estimate(fixture(), [], {'food': 0, 'energy': 0}, {'food': 10, 'energy': 10}, 200)
        self.assertEqual(plan['resources']['food']['required_extra_workforce'], 210)
        self.assertEqual(plan['resources']['food']['additional_district_capacity_lower_bound'], 1)
        self.assertEqual(plan['resources']['energy']['additional_district_capacity_lower_bound'], 0)
        self.assertEqual(plan['idle_workforce_upper_bound'], '100')
        self.assertEqual(plan['workforce_shortfall_after_idle'], '130')
        self.assertEqual(plan['status'], 'conditional_estimate')

    def test_already_at_goal_needs_no_rate(self):
        plan = target_estimate(fixture(), [], {'food': -30})
        self.assertEqual(plan['resources']['food']['required_extra_workforce'], 0)

    def test_missing_baseline_rate_and_population_remain_unknown(self):
        snap = fixture()
        del snap['colonies'][0]['employable_pops']
        plan = target_estimate(snap, [], {'food': 0})
        self.assertIsNone(plan['resources']['food']['required_extra_workforce'])
        self.assertIsNone(plan['workforce_shortfall_after_idle'])
        snap['economy']['resources'] = {}
        plan = target_estimate(snap, [], {'food': 0}, {'food': 10})
        self.assertIsNone(plan['resources']['food']['required_extra_workforce'])

    def test_invalid_assumptions(self):
        for rate in ('NaN', 'Infinity', '0', '-2', 'bad'):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                target_estimate(fixture(), [], {'food': 0}, {'food': rate})

    def test_sentinels_are_not_population(self):
        rows = labour_overview(fixture())
        self.assertEqual(rows[0]['idle_upper_bound'], '100')
        self.assertEqual(rows[0]['families']['food']['vacant'], '200')

    def test_version_checked_rule_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'launcher-settings.json').write_text(json.dumps({'rawVersion': 'v4.5.4'}))
            path = root / 'common/scripted_variables/100_scripted_variables_zones.txt'
            path.parent.mkdir(parents=True)
            path.write_text('@base_rural_district_jobs = 200\n')
            self.assertEqual(rural_rule_reference(root, 'Cygnus v4.5.4')['workforce_per_district'], 200)
            with self.assertRaises(ValueError):
                rural_rule_reference(root, 'v4.4.0')


if __name__ == '__main__':
    unittest.main()
