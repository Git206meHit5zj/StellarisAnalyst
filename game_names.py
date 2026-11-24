"""Read installed Chinese localization without distributing game content."""
from functools import lru_cache
import os
from pathlib import Path
import re


def field(block, key):
    return next((e['value'] for e in block or [] if e['key'] == key), None) if isinstance(block, list) else None


class Names:
    def __init__(self, game_dir=None):
        self.table = {}
        self.game_dir = game_dir or os.environ.get('STELLARIS_GAME_DIR', '')
        if not self.game_dir:
            candidate = Path('F:/SteamLibrary/steamapps/common/Stellaris')
            self.game_dir = str(candidate) if candidate.is_dir() else ''
        directory = Path(self.game_dir) / 'localisation/simp_chinese'
        if self.game_dir and directory.is_dir():
            pattern = re.compile(r'^\s*([^\s:#]+):\d*\s*"(.*)"\s*(?:#.*)?$')
            for file in sorted(directory.rglob('*.yml')):
                for line in file.read_text(encoding='utf-8-sig').splitlines():
                    match = pattern.match(line)
                    if match:
                        self.table[match[1]] = match[2]

    def translate(self, key, depth=0):
        if depth > 8 or not isinstance(key, str):
            return str(key or '未知')
        text = self.table.get(key, key)
        return re.sub(r'\$([^$]+)\$', lambda m: self.translate(m[1], depth + 1), text)

    def resolve(self, raw):
        if not isinstance(raw, list):
            return self.translate(raw)
        key = field(raw, 'key')
        result = self.translate(key)
        for variable in field(raw, 'variables') or []:
            name = field(variable['value'], 'key')
            replacement = self.resolve(field(variable['value'], 'value'))
            if name:
                result = re.sub('%' + re.escape(name) + '%', lambda m: replacement, result, flags=re.I)
                result = result.replace('[' + name + ']', replacement)
        return result


@lru_cache(maxsize=4)
def load_names(game_dir=None):
    return Names(game_dir)
