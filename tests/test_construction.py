import unittest

from construction import block, repair_plan, load_repair_rules
from fast_import import entries


RULE = {'housing': '1500', 'amenities': '1500', 'minerals': '400', 'energy_upkeep': '2', 'base_days': '360'}
RULES = {'buildings': {'building_luxury_residence': RULE, 'building_hive_warren': RULE},
         'default_zone_capacity': 6, 'assumption': 'synthetic rules'}


def colony(cid, amenity, housing='1000', occupied=3):
    return {'colony_id': cid, 'name': cid, 'system_name': 'test', 'free_amenities': amenity,
            'free_housing': housing, 'stability': '10', 'planet_class': 'pc_continental',
            'zones': [{'raw': entries({'type': 'zone_default', 'buildings': list(range(occupied))})}]}


def snapshot(cols):
    return {'country_id': '9', 'colonies': cols, 'inventory': {'minerals': '1000'},
            'economy': {'resources': {'energy': {'net': '-100'}}}}


class ConstructionTests(unittest.TestCase):
    def test_joint_housing_amenity_integer_requirement(self):
        plan = repair_plan(snapshot([colony('1', '-1501', '-3001')]), entries({'government': {'authority': 'auth_corporate'}}), RULES)
        self.assertEqual(plan['quantity_total'], 3)
        self.assertEqual(plan['minerals_base_total'], '1200')
        self.assertFalse(plan['base_cost_within_current_stockpile'])
        self.assertEqual(plan['energy_net_after_base_upkeep'], '-106')

    def test_full_zone_is_not_ready_to_build(self):
        plan = repair_plan(snapshot([colony('1', '-500', occupied=6)]), entries({'government': {'authority': 'auth_corporate'}}), RULES)
        self.assertEqual(plan['rows'][0]['status'], 'slot_review_required')
        self.assertEqual(plan['rows'][0]['default_zone_free_slots_base'], 0)

    def test_unknown_and_no_need_are_distinct(self):
        plan = repair_plan(snapshot([colony('1', None), colony('2', '0')]), entries({'government': {'authority': 'auth_hive_mind'}}), RULES)
        self.assertIsNone(plan['rows'][0]['quantity'])
        self.assertEqual(plan['unknown_colony_count'], 1)
        self.assertEqual(plan['rows'][1]['quantity'], 0)

    def test_unsupported_government_is_rejected(self):
        with self.assertRaises(ValueError):
            repair_plan(snapshot([]), entries({'government': {'authority': 'auth_machine_intelligence'}}), RULES)

    def test_rule_block_strings_comments_and_nested_braces(self):
        text = 'test={ text="}" # }\n nested={ a=2 } value=3 } other={x=4}'
        self.assertIn('value=3', block(text, 'test'))
        self.assertNotIn('other', block(text, 'test'))

    def test_version_mismatch_is_rejected_before_reading_rules(self):
        import tempfile,json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'launcher-settings.json').write_text(json.dumps({'rawVersion':'v4.6.0'}))
            with self.assertRaisesRegex(ValueError, '版本'):
                load_repair_rules(tmp, 'Cygnus v4.5.4')


if __name__ == '__main__':
    unittest.main()
