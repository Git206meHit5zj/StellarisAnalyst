import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from stellaris_analyst import SaveError, country_snapshot, economic_snapshot, export_report, field, inspect_save, parse


class ImportTests(unittest.TestCase):
    def test_country_colony_reference_and_inventory_runway(self):
        state = parse('country={ 0={ owned_planets={ 105 } budget={ last_month={ income={} expenses={ ships={ food=10 } } } } modules={ standard_economy_module={ resources={ food=20 } } } } } colony={ 105={ carrier={ type=planet reference=333 } stability=25 } } planets={ planet={ 333={ name="Test" } } }')
        snapshot = country_snapshot(state, '0')
        self.assertEqual(snapshot['colonies'][0]['planet_id'], '333')
        self.assertEqual(snapshot['colonies'][0]['name_raw'], 'Test')
        self.assertEqual(snapshot['months_until_empty_at_last_month_rate']['food'], '2')
        self.assertNotIn('energy', snapshot['inventory'])
        with self.assertRaises(SaveError):
            country_snapshot(state, '1')

    def test_budget_decimal_and_repeated_categories(self):
        c = parse('budget={ last_month={ income={ jobs={ energy=0.1 } jobs={ energy=0.2 } } expenses={ ships={ energy=0.4 alloys=2 } } } }')
        r = economic_snapshot(c)['resources']
        self.assertEqual(r['energy']['net'], '-0.1')
        self.assertEqual(r['alloys']['net'], '-2')

    def test_missing_budget_is_unknown(self):
        c = parse('budget={ last_month={ income={ jobs={ energy=10 } } } }')
        r = economic_snapshot(c)
        self.assertIsNone(r['resources']['energy']['net'])
        self.assertTrue(r['warnings'])

    def test_duplicate_keys_lists_comments_and_quotes(self):
        tree = parse('# comment\na=1 a=2 list={ 3 "中 文" } name="a\\"b"')
        self.assertEqual([e['value'] for e in tree[:2]], ['1', '2'])
        self.assertEqual(field(tree, 'list')[1]['value'], '中 文')
        self.assertEqual(field(tree, 'name'), 'a"b')

    def test_bad_syntax(self):
        for source in ('a={', 'a=', '}', 'a="unclosed', 'a={ b==1 }'):
            with self.subTest(source=source), self.assertRaises(SaveError):
                parse(source)

    def test_import_and_export_preserve_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.sav'
            with ZipFile(source, 'w') as archive:
                archive.writestr('meta', 'version="fixture"')
                archive.writestr('gamestate', 'date="2200.01.01" country={ 0={ name="测试" type=default } }')
            original = source.read_bytes()
            report = inspect_save(source, engine='python')
            self.assertEqual(report['summary']['countries'][0]['name'], '测试')
            self.assertEqual(report['summary']['version'], 'fixture')
            export_report(report, Path(tmp) / 'report.json', source)
            with self.assertRaises(SaveError):
                export_report(report, source, source)
            self.assertEqual(source.read_bytes(), original)

    def test_invalid_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'bad.sav'
            source.write_text('invalid')
            with self.assertRaises(SaveError):
                inspect_save(source)
            with ZipFile(source, 'w') as archive:
                archive.writestr('meta', '')
            with self.assertRaises(SaveError):
                inspect_save(source)


if __name__ == '__main__':
    unittest.main()
