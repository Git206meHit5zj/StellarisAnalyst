from pathlib import Path
import tempfile
import unittest

from fast_import import PARSER, entries, unpack_entries
from game_names import Names
from stellaris_analyst import country_snapshot, field


class FastImportTests(unittest.TestCase):
    def test_protocol_full_entries_and_projected_entries(self):
        self.assertEqual(unpack_entries([{'_key': '3', '_value': {'name': 'A'}}]), {'3': {'name': 'A'}})
        self.assertEqual(unpack_entries([{'_key': '3', 'name': 'A'}]), {'3': {'name': 'A'}})
        with self.assertRaises(ValueError):
            unpack_entries('bad')

    def test_numbers_lists_and_nulls(self):
        tree = entries({'x': ['0', '1'], 'null': None, 'energy': '0.10001'})
        self.assertEqual(field(tree, 'x'), [{'key': None, 'value': '0'}, {'key': None, 'value': '1'}])
        self.assertIsNone(field(tree, 'null'))
        self.assertEqual(field(tree, 'energy'), '0.10001')

    def test_chinese_localization_templates_and_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'localisation/simp_chinese'
            path.mkdir(parents=True)
            (path / 'names.yml').write_text('l_simp_chinese:\n X:0 "菲尔诺"\n TEMPLATE:0 "%NAME%星"\n LOOP:0 "$LOOP$"\n', encoding='utf-8-sig')
            names = Names(tmp)
            raw = entries({'key': 'TEMPLATE', 'variables': [{'key': 'NAME', 'value': {'key': 'X'}}]})
            self.assertEqual(names.resolve(raw), '菲尔诺星')
            self.assertEqual(names.resolve('Unknown'), 'Unknown')
            self.assertIn('LOOP', names.translate('LOOP'))

    def test_district_levels_and_same_name_distinct_systems(self):
        state = entries({'country': {'1': {'owned_planets': ['10', '11']}},
                         'colony': {'10': {'carrier': {'type': 'planet', 'reference': '20'}, 'districts': ['30', '31']},
                                    '11': {'carrier': {'type': 'planet', 'reference': '21'}}},
                         'planets': {'planet': {'20': {'name': 'Same', 'coordinate': {'origin': '40'}},
                                               '21': {'name': 'Same', 'coordinate': {'origin': '41'}}}},
                         'galactic_object': {'40': {'name': 'TestSystemAlpha'}, '41': {'name': 'TestSystemBeta'}},
                         'districts': {'30': {'level': '9'}, '31': {'level': '5'}}})
        colonies = country_snapshot(state, '1')['colonies']
        self.assertEqual(colonies[0]['district_level_total'], 14)
        self.assertEqual([c['system_name'] for c in colonies], ['TestSystemAlpha', 'TestSystemBeta'])

    @unittest.skipUnless(PARSER.is_file(), 'Optional Rust binary is not installed')
    def test_real_rust_protocol_on_synthetic_multiplayer_save(self):
        from zipfile import ZipFile
        from stellaris_analyst import inspect_save
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.sav'
            with ZipFile(source, 'w') as archive:
                archive.writestr('meta', 'version="fixture" date="2200.01.01"')
                archive.writestr('gamestate', 'player={ {country=0} {country=9} } country={ 0={name="TestA" owned_planets={}} 9={name="TestB" owned_planets={}} } planets={planet={}}')
            report = inspect_save(source, 'rust')
            self.assertEqual(report['summary']['parser'], 'rust')
            self.assertEqual([c['id'] for c in report['summary']['countries']], ['0', '9'])
            self.assertEqual([c['display_name'] for c in report['summary']['countries']], ['TestA', 'TestB'])


if __name__ == '__main__':
    unittest.main()
