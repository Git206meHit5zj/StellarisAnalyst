"""Read-only, opt-in compatibility probe for the upstream Companion extractor.

Run with Python 3.10+, an explicit country ID, and a local upstream checkout.
No AI provider, desktop backend, or network service is started.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('save', type=Path)
    cli.add_argument('--country', required=True, type=int)
    cli.add_argument('--repo', type=Path, default=Path('external/stellaris-companion'))
    cli.add_argument('--parser', type=Path, default=Path('external/artifacts/parser/stellaris-parser.exe'))
    cli.add_argument('--reference', type=Path)
    cli.add_argument('--output', type=Path, default=Path('companion-evaluation.json'))
    args = cli.parse_args()
    if args.save.resolve() == args.output.resolve():
        cli.error('Output must not overwrite the source save')
    if not args.parser.is_file():
        cli.error('Parser executable not found')
    os.environ['PARSER_BINARY'] = str(args.parser.resolve())
    os.environ['STELLARIS_PLAYER_COUNTRY_ID'] = str(args.country)
    sys.path.insert(0, str(args.repo.resolve()))
    from stellaris_companion.rust_bridge import session
    from stellaris_save_extractor import SaveExtractor
    from stellaris_save_extractor.player import _normalize_player_entries

    before = hashlib.sha256(args.save.read_bytes()).hexdigest()
    started = time.perf_counter()
    with session(args.save) as rust:
        header = rust.extract_sections(['meta', 'player'])
        players = _normalize_player_entries(header.get('player'))
        if args.country not in [p['country'] for p in players]:
            cli.error('Country ID is not a human player in this save')
        with SaveExtractor(str(args.save)) as extractor:
            planets = extractor.get_planets()
            economy = extractor.get_resources()
            selected = extractor.get_player_empire_id()
        country = rust.get_entry('country', str(args.country))
        last_month = country.get('budget', {}).get('last_month', {})
        net = {}
        for side, sign in (('income', 1), ('expenses', -1)):
            for category in last_month.get(side, {}).values():
                for resource, amount in category.items():
                    net[resource] = net.get(resource, Decimal(0)) + sign * Decimal(str(amount))
    checks = {'selected_country': selected == args.country,
              'source_unchanged': before == hashlib.sha256(args.save.read_bytes()).hexdigest()}
    if args.reference:
        ref = json.loads(args.reference.read_text(encoding='utf-8'))
        if str(ref['country_id']) != str(args.country):
            cli.error('Reference report is for a different country')
        checks['colony_ids_match'] = sorted(str(p.get('colony_id')) for p in planets['planets']) == sorted(c['colony_id'] for c in ref['colonies'])
        checks['stockpiles_match'] = all(
            key in economy['stockpiles'] and abs(Decimal(str(economy['stockpiles'][key])) - Decimal(amount)) < Decimal('0.00001')
            for key, amount in ref['inventory'].items())
        checks['last_month_net_match'] = all(
            key in net and abs(net[key] - Decimal(amounts['net'])) < Decimal('0.00001')
            for key, amounts in ref['economy']['resources'].items() if amounts['net'] is not None)
    report = {'country_id': selected, 'save_version': header.get('meta', {}).get('version'),
              'elapsed_seconds': round(time.perf_counter() - started, 3),
              'parser_sha256': hashlib.sha256(args.parser.read_bytes()).hexdigest(),
              'source_sha256': before, 'checks': checks, 'planets': planets,
              'economy_current_month': economy,
              'net_last_month': {key: str(amount) for key, amount in net.items()},
              'note': 'Upstream economy uses current_month; our earlier report uses last_month. Do not compare them as the same period.'}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'country_id': selected, 'planet_count': planets['count'],
                      'elapsed_seconds': report['elapsed_seconds'], 'checks': checks}, ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
