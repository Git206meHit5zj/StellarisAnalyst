"""Small Python 3.8-compatible client for Companion's Rust session protocol."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

PARSER = Path(__file__).resolve().parent / 'external/artifacts/parser/stellaris-parser.exe'


def unpack_entries(result):
    if isinstance(result, list):
        result = {str(e['_key']): e.get('_value', {k: v for k, v in e.items() if k != '_key'})
                  for e in result if isinstance(e, dict) and '_key' in e}
    if not isinstance(result, dict):
        raise ValueError('不支持的 Rust get_entries 响应结构')
    return result


def entries(value):
    if isinstance(value, dict):
        return [{'key': str(k), 'value': entries(v)} for k, v in value.items()]
    if isinstance(value, list):
        return [{'key': None, 'value': entries(v)} for v in value]
    if value is None:
        return None
    return str(value)


class Session:
    def __init__(self, path, binary=PARSER):
        self.process = subprocess.Popen(
            [str(binary), 'serve', '--path', str(Path(path).resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.responses = queue.Queue()
        def read():
            try:
                for line in self.process.stdout:
                    self.responses.put(line)
            finally:
                self.responses.put(None)
        threading.Thread(target=read, daemon=True).start()

    def ask(self, **request):
        try:
            self.process.stdin.write((json.dumps(request) + '\n').encode('utf-8'))
            self.process.stdin.flush()
            line = self.responses.get(timeout=45)
            if line is None:
                raise ValueError('Rust 解析器提前退出')
            reply = json.loads(line, parse_float=str, parse_int=str)
            if reply.get('ok') is not True:
                raise ValueError('Rust 解析失败：' + reply.get('message', '未知错误'))
            return reply
        except queue.Empty:
            raise ValueError('Rust 解析器响应超时')

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def read_save(path):
    session = Session(path)
    try:
        header = session.ask(op='extract_sections', sections=['meta', 'player'])['data']
        players = header.get('player', [])
        if isinstance(players, dict):
            players = list(players.values())
        ids = list(dict.fromkeys(str(p['country']) for p in players if isinstance(p, dict) and 'country' in p))
        if not ids:
            raise ValueError('未识别人类玩家；请切换 python 解析器查看完整存档')
        data = {'player': players}

        def fetch(section, keys, fields=None):
            keys = list(dict.fromkeys(str(k) for k in keys))
            if not keys:
                return {}
            request = dict(op='get_entries', section=section, keys=keys)
            if fields:
                request['fields'] = fields
            reply = session.ask(**request)
            return unpack_entries(reply.get('entries', {}))

        data['country'] = fetch('country', ids)
        colony_ids = [c for country in data['country'].values() for c in country.get('owned_planets', [])]
        data['colony'] = fetch('colony', colony_ids)
        planet_ids = [c['carrier']['reference'] for c in data['colony'].values()
                      if c.get('carrier', {}).get('type') == 'planet']
        # planets is wrapped under planets.planet; get_entries cannot address the wrapper.
        wrapped = session.ask(op='get_entry', section='planets', key='planet').get('entry', {}) or {}
        planets = {str(k): wrapped[str(k)] for k in planet_ids if str(k) in wrapped}
        data['planets'] = {'planet': planets}
        for section, ref in (('pop_jobs', 'pop_jobs'), ('districts', 'districts'), ('buildings', 'buildings_cache')):
            keys = [k for c in data['colony'].values() for k in c.get(ref, [])]
            data[section] = fetch(section, keys)
        data['zones'] = fetch('zones', [z for d in data['districts'].values() for z in d.get('zones', []) if z != '4294967295'])
        system_ids = [p.get('coordinate', {}).get('origin') for p in planets.values()]
        data['galactic_object'] = fetch('galactic_object', [k for k in system_ids if k is not None], ['name'])
        return {'meta': entries(header.get('meta', {})), 'gamestate': entries(data)}
    finally:
        session.close()
