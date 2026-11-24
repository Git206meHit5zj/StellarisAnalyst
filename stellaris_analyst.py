"""Local, read-only Stellaris text save inspector. Python 3.8+, no dependencies."""
import argparse
import json
from pathlib import Path
import re
import zipfile
from decimal import Decimal, InvalidOperation


class SaveError(ValueError):
    pass


TOKEN = re.compile(r'\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|[{}=]|[^\s{}="#]+')


def parse(text):
    """Preserve order, duplicate keys and anonymous list items without coercion."""
    tokens = []
    pos = 0
    for match in TOKEN.finditer(text.lstrip('\ufeff')):
        if match.start() != pos:
            raise SaveError('无法解析的文本，位置 %d' % pos)
        pos = match.end()
        token = match.group()
        if not token.isspace() and not token.startswith('#'):
            tokens.append(token)
    if pos != len(text.lstrip('\ufeff')):
        raise SaveError('文本结尾存在未闭合字符串')
    index = 0

    def scalar(token):
        if token.startswith('"'):
            return re.sub(r'\\(["\\])', r'\1', token[1:-1])
        return token

    def value(depth):
        nonlocal index
        if depth > 150:
            raise SaveError('存档嵌套层数过多')
        if index >= len(tokens) or tokens[index] in ('}', '='):
            raise SaveError('字段缺少有效值')
        token = tokens[index]
        index += 1
        if token != '{':
            return scalar(token)
        result = block(depth + 1)
        if index >= len(tokens) or tokens[index] != '}':
            raise SaveError('缺少右花括号')
        index += 1
        return result

    def block(depth):
        nonlocal index
        entries = []
        while index < len(tokens) and tokens[index] != '}':
            first = value(depth)
            if index < len(tokens) and tokens[index] == '=':
                if not isinstance(first, str):
                    raise SaveError('字段名必须是文本')
                index += 1
                entries.append({'key': first, 'value': value(depth)})
            else:
                entries.append({'key': None, 'value': first})
        return entries

    result = block(0)
    if index != len(tokens):
        raise SaveError('多余的右花括号')
    return result


def field(entries, key):
    if isinstance(entries, list):
        return next((e['value'] for e in entries if e['key'] == key), None)
    return None


def economic_snapshot(country):
    """Sum saved last-month budget categories; never infer production rules."""
    period = field(field(country, 'budget'), 'last_month')
    totals = {}
    warnings = []
    for side in ('income', 'expenses'):
        categories = field(period, side)
        if not isinstance(categories, list):
            warnings.append('缺少 last_month.' + side)
            continue
        amounts = {}
        valid = True
        for category in categories:
            if not isinstance(category['value'], list):
                valid = False
                continue
            for resource in category['value']:
                try:
                    amount = Decimal(resource['value'])
                    if resource['key'] is None or not amount.is_finite():
                        raise ValueError()
                    key = resource['key']
                    amounts[key] = amounts.get(key, Decimal(0)) + amount
                except (InvalidOperation, ValueError, TypeError):
                    valid = False
        if valid:
            totals[side] = amounts
        else:
            warnings.append('无法完整识别 last_month.' + side)
    resources = {}
    for key in sorted(set(totals.get('income', {})) | set(totals.get('expenses', {}))):
        income = totals['income'].get(key, Decimal(0)) if 'income' in totals else None
        expense = totals['expenses'].get(key, Decimal(0)) if 'expenses' in totals else None
        resources[key] = {
            'income': str(income) if income is not None else None,
            'expenses': str(expense) if expense is not None else None,
            'net': str(income - expense) if income is not None and expense is not None else None,
        }
    return {'source': 'country.budget.last_month', 'resources': resources, 'warnings': warnings,
            'note': '存档上月账本汇总；尚未与游戏面板核对，不代表新增建筑的边际产量。'}


def country_snapshot(state, country_id):
    from game_names import load_names
    names = load_names()
    country = field(field(state, 'country'), str(country_id))
    if not isinstance(country, list):
        raise SaveError('找不到指定帝国')
    economy = economic_snapshot(country)
    stock = field(field(field(country, 'modules'), 'standard_economy_module'), 'resources')
    inventory = {e['key']: e['value'] for e in stock or []}
    runway = {}
    for resource, amounts in economy['resources'].items():
        if amounts['net'] is not None and resource in inventory:
            net = Decimal(amounts['net'])
            if net < 0:
                runway[resource] = str(Decimal(inventory[resource]) / -net)
    colonies = []
    planet_db = field(field(state, 'planets'), 'planet')
    for ref in field(country, 'owned_planets') or []:
        cid = ref['value']
        colony = field(field(state, 'colony'), cid)
        if not isinstance(colony, list):
            colonies.append({'colony_id': cid, 'warning': '殖民地结构尚未识别'})
            continue
        carrier = field(colony, 'carrier')
        pid = field(carrier, 'reference')
        planet = field(planet_db, pid) if field(carrier, 'type') == 'planet' else None
        data = {'colony_id': cid, 'planet_id': pid, 'name_raw': field(planet, 'name')}
        system_id = field(field(planet, 'coordinate'), 'origin')
        system = field(field(state, 'galactic_object'), system_id)
        data.update(name=names.resolve(data['name_raw']), system_id=system_id,
                    system_name=names.resolve(field(system, 'name')))
        data['planet_class'] = field(planet, 'planet_class')
        for key in ('stability', 'free_amenities', 'free_housing', 'num_sapient_pops', 'employable_pops',
                    'final_designation', 'produces', 'upkeep', 'profits'):
            data[key] = field(colony, key)
        data['jobs'] = []
        for job_ref in field(colony, 'pop_jobs') or []:
            job = field(field(state, 'pop_jobs'), job_ref['value'])
            data['jobs'].append({k: field(job, k) for k in
                                 ('type', 'workforce', 'max_workforce', 'automated_workforce')})
        for refs_key, db_key in (('districts', 'districts'), ('buildings_cache', 'buildings')):
            data[db_key] = []
            for item in field(colony, refs_key) or []:
                raw = field(field(state, db_key), item['value'])
                data[db_key].append({'id': item['value'], 'raw': raw})
        levels = [field(d['raw'], 'level') for d in data['districts']]
        data['district_level_total'] = sum(int(level) for level in levels) if all(level is not None for level in levels) else None
        data['zones'] = [{'id': z['value'], 'raw': field(field(state, 'zones'), z['value'])}
                         for d in data['districts'] for z in field(d['raw'], 'zones') or []
                         if z['value'] != '4294967295']
        colonies.append(data)
    return {'country_id': str(country_id), 'name_raw': field(country, 'name'),
            'name': names.resolve(field(country, 'name')),
            'economy': economy, 'inventory': inventory, 'colonies': colonies,
            'months_until_empty_at_last_month_rate': runway,
            'limitations': ['耗尽时间假设上月净收入保持不变，未模拟交易、事件和建设。',
                            '人口、劳动力、住房和舒适度保留存档原始单位，尚未做界面单位换算。',
                            '尚未求解建筑数量与建设顺序。']}


RESOURCE_NAMES = {'energy': '能量', 'minerals': '矿物', 'food': '食物',
                  'alloys': '合金', 'consumer_goods': '消费品', 'unity': '凝聚力',
                  'trade': '贸易', 'exotic_gases': '异星天然气',
                  'volatile_motes': '易爆微粒', 'rare_crystals': '稀有水晶'}


def format_country(snapshot):
    lines = ['帝国：%s（ID %s）' % (snapshot.get('name', '未知'), snapshot['country_id']), '上月账本（未与游戏面板核对）',
             '资源 | 库存 | 收入 | 支出 | 净结余']
    for key, amounts in snapshot['economy']['resources'].items():
        def number(value):
            return '未知' if value is None else format(Decimal(value), '.2f')
        lines.append(' | '.join([RESOURCE_NAMES.get(key, key),
                                number(snapshot['inventory'].get(key)),
                                number(amounts['income']), number(amounts['expenses']),
                                number(amounts['net'])]))
    for key, months in snapshot['months_until_empty_at_last_month_rate'].items():
        lines.append('%s：若维持上月净收入，约 %.2f 个月耗尽' %
                     (RESOURCE_NAMES.get(key, key), Decimal(months)))
    lines.append('\n殖民地（住房、舒适度为存档原始单位）')
    for colony in snapshot['colonies']:
        lines.append('%s｜%s星系｜区域层级合计 %s' %
                     (colony.get('name', '未知'), colony.get('system_name', '未知'), colony.get('district_level_total', '未知')))
        lines.append('殖民地 %s / 星球 %s：稳定度 %s，住房余量 %s，舒适度余量 %s' %
                     (colony['colony_id'], colony.get('planet_id', '未知'),
                      colony.get('stability', '未知'), colony.get('free_housing', '未知'),
                      colony.get('free_amenities', '未知')))
    lines.extend(snapshot['limitations'])
    return '\n'.join(lines)


def inspect_save(filename, engine='auto'):
    from fast_import import PARSER, read_save
    from game_names import load_names
    if engine not in ('auto', 'rust', 'python'):
        raise SaveError('不支持的解析器')
    path = Path(filename)
    try:
        with zipfile.ZipFile(path) as archive:
            trees = {}
            for name in ('meta', 'gamestate'):
                matches = [i for i in archive.infolist() if i.filename == name]
                if len(matches) != 1:
                    raise SaveError('存档必须包含唯一的 %s 文件' % name)
                info = matches[0]
                if info.file_size > 256 * 1024 * 1024:
                    raise SaveError('%s 超过原型支持的 256 MiB 上限' % name)
                if engine == 'python' or (engine == 'auto' and not PARSER.is_file()):
                    trees[name] = parse(archive.read(info).decode('utf-8-sig'))
        selected_engine = 'python' if trees else 'rust'
        if selected_engine == 'rust':
            trees = read_save(path)
    except (OSError, zipfile.BadZipFile, UnicodeError, RuntimeError, NotImplementedError, ValueError) as exc:
        raise SaveError('无法读取此存档：%s' % exc) from exc
    meta, state = trees['meta'], trees['gamestate']
    country = field(state, 'country')
    countries = []
    if isinstance(country, list):
        for entry in country:
            if entry['key'] is not None and isinstance(entry['value'], list):
                countries.append({'id': entry['key'], 'name': field(entry['value'], 'name'),
                                  'type': field(entry['value'], 'type')})
    player_economies = []
    players = field(state, 'player')
    if isinstance(players, list):
        seen = set()
        for player in players:
            cid = field(player['value'], 'country')
            if cid is not None and cid not in seen:
                seen.add(cid)
                data = field(country, cid)
                player_economies.append({'country_id': cid,
                                        'owned_planets': field(data, 'owned_planets'),
                                        'economy': economic_snapshot(data)})
    for candidate in countries:
        snapshot = country_snapshot(state, candidate['id'])
        data = field(country, candidate['id'])
        capital = next((c for c in snapshot['colonies'] if c['colony_id'] == field(data, 'capital')), {})
        candidate.update(display_name=snapshot['name'], capital_name=capital.get('name', '未知'),
                         colony_count=len(snapshot['colonies']))
    return {
        'summary': {
            'filename': path.name,
            'parser': selected_engine,
            'scope': 'human_player_empires' if selected_engine == 'rust' else 'full_save',
            'version': field(meta, 'version') or field(state, 'version'),
            'date': field(state, 'date') or field(meta, 'date'),
            'player': field(state, 'player'),
            'countries': countries,
            'player_economies': player_economies,
            'warnings': ['建设规则尚未完整适配；不能据此给出最终建设数量。',
                         '帝国名称可能是本地化结构；字段缺失表示未知，不能解释为零。'],
        },
        'raw': trees,
    }


def export_report(report, destination, source):
    if Path(destination).resolve() == Path(source).resolve():
        raise SaveError('导出路径不能覆盖原始存档')
    Path(destination).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from concurrent.futures import ThreadPoolExecutor
    from tkinter.scrolledtext import ScrolledText
    from planning import target_estimate, format_estimate, rural_rule_reference
    from construction import load_repair_rules, repair_plan, format_repairs

    root = tk.Tk()
    root.title('群星建设分析器 · 经济与岗位规划')
    root.geometry('1150x820')
    executor = ThreadPoolExecutor(max_workers=1)
    current = {}
    status = tk.StringVar(value='选择 .sav 存档，数据仅在本机读取。')
    toolbar = ttk.Frame(root, padding=12)
    toolbar.pack(fill='x')
    ttk.Label(root, textvariable=status, padding=12).pack(fill='x')
    notebook = ttk.Notebook(root)
    notebook.pack(fill='both', expand=True, padx=12, pady=12)
    summary_tab, plan_tab, frame = (ttk.Frame(notebook) for _ in range(3))
    notebook.add(summary_tab, text='经济概览')
    notebook.add(plan_tab, text='目标与岗位测算')
    repair_tab = ttk.Frame(notebook)
    notebook.add(repair_tab, text='逐星球修复方案')
    notebook.add(frame, text='原始数据')
    repair_bar = ttk.Frame(repair_tab, padding=8)
    repair_bar.pack(fill='x')
    repair_text = ScrolledText(repair_tab, wrap='word')
    repair_text.pack(fill='both', expand=True, padx=8, pady=8)
    text = ScrolledText(summary_tab, wrap='word')
    text.pack(fill='both', expand=True)
    goals_bar = ttk.Frame(plan_tab, padding=8)
    goals_bar.pack(fill='x')
    goal_values = {}
    rate_values = {}
    for resource, label in (('food', '食物'), ('energy', '能量')):
        ttk.Label(goals_bar, text=label + '月净收入目标').pack(side='left')
        goal_values[resource] = tk.StringVar(value='0')
        ttk.Entry(goals_bar, textvariable=goal_values[resource], width=8).pack(side='left', padx=6)
    rate_bar = ttk.Frame(plan_tab, padding=8)
    rate_bar.pack(fill='x')
    for resource, label in (('food', '农业'), ('energy', '发电')):
        ttk.Label(rate_bar, text=label + '每100劳动力产出（留空自动估算）').pack(side='left')
        rate_values[resource] = tk.StringVar()
        ttk.Entry(rate_bar, textvariable=rate_values[resource], width=9).pack(side='left', padx=6)
    rule_bar = ttk.Frame(plan_tab, padding=8)
    rule_bar.pack(fill='x')
    ttk.Label(rule_bar, text='每个新区域基础岗位容量（存档单位）').pack(side='left')
    district_capacity = tk.StringVar()
    ttk.Entry(rule_bar, textvariable=district_capacity, width=9).pack(side='left', padx=6)
    rule_label = tk.StringVar(value='可选：读取同版本游戏目录作为基础容量参考。')
    ttk.Label(plan_tab, textvariable=rule_label, padding=8, wraplength=1050).pack(fill='x')
    plan_text = ScrolledText(plan_tab, wrap='word')
    plan_text.pack(fill='both', expand=True, padx=8, pady=8)
    tree = ttk.Treeview(frame, columns=('value',))
    tree.heading('#0', text='已提取字段（Rust 模式仅包含玩家相关数据）')
    tree.heading('value', text='值')
    scroll = ttk.Scrollbar(frame, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    tree.pack(fill='both', expand=True)
    pending = {}

    def selected_id():
        return selected_country.get().split(' | ', 1)[0]

    def show_country(event=None):
        if 'report' not in current or not selected_country.get():
            return
        snapshot = country_snapshot(current['report']['raw']['gamestate'], selected_id())
        current['country_snapshot'] = snapshot
        current.pop('plan', None)
        current.pop('repairs', None)
        repair_text.delete('1.0', 'end')
        repair_text.insert('end', '点击“生成修复方案”，按匹配版本的游戏规则计算住房和舒适度建筑数量。')
        plan_text.delete('1.0', 'end')
        plan_text.insert('end', '设置目标后点击“计算缺口”；结果不会修改存档。')
        text.delete('1.0', 'end')
        text.insert('end', format_country(snapshot))

    def invalidate_plan(*args):
        if current.pop('plan', None) is not None:
            plan_text.delete('1.0', 'end')
            plan_text.insert('end', '输入已改变，请重新计算缺口。')

    for variable in list(goal_values.values()) + list(rate_values.values()) + [district_capacity]:
        variable.trace_add('write', invalidate_plan)

    def insert(parent, entries):
        for entry in entries:
            value = entry['value']
            item = tree.insert(parent, 'end', text=entry['key'] or '(列表项)',
                               values=('点击展开' if isinstance(value, list) else value,))
            if isinstance(value, list) and value:
                pending[item] = value
                tree.insert(item, 'end', text='…')

    def expand(event):
        item = tree.focus()
        if item in pending:
            tree.delete(*tree.get_children(item))
            insert(item, pending.pop(item))

    tree.bind('<<TreeviewOpen>>', expand)

    def calculate():
        if 'country_snapshot' not in current or not selected_country.get():
            messagebox.showinfo('目标测算', '请先导入存档并选择玩家帝国。')
            return
        try:
            country = field(field(current['report']['raw']['gamestate'], 'country'), selected_id())
            plan = target_estimate(current['country_snapshot'], country,
                                   {k: v.get() for k, v in goal_values.items()},
                                   {k: v.get() for k, v in rate_values.items() if v.get().strip()},
                                   district_capacity.get().strip() or None)
            current['plan'] = plan
            plan_text.delete('1.0', 'end')
            plan_text.insert('end', format_estimate(plan))
        except ValueError as exc:
            messagebox.showerror('目标测算失败', str(exc))

    def read_rules():
        if 'report' not in current:
            messagebox.showinfo('读取规则', '请先导入存档，以核对游戏版本。')
            return
        directory = filedialog.askdirectory(title='选择包含 stellaris.exe 的游戏安装目录')
        if not directory:
            return
        try:
            reference = rural_rule_reference(directory, current['report']['summary']['version'])
            district_capacity.set(str(reference['workforce_per_district']))
            rule_label.set('版本 %s，基础容量 %s。%s' %
                           (reference['version'], reference['workforce_per_district'], reference['note']))
            current['rule_reference'] = reference
        except (OSError, ValueError) as exc:
            messagebox.showerror('读取规则失败', str(exc))

    def export_plan():
        if 'plan' not in current:
            messagebox.showinfo('导出测算', '请先计算缺口。')
            return
        destination = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')])
        if destination:
            try:
                export_report({'country_id': selected_id(),
                               'save_date': current['report']['summary']['date'],
                               'rule_reference': current.get('rule_reference'),
                               'plan': current['plan']}, destination, current['source'])
                status.set('已导出目标测算。')
            except (OSError, SaveError) as exc:
                messagebox.showerror('导出失败', str(exc))

    ttk.Button(goals_bar, text='计算缺口', command=calculate).pack(side='left', padx=8)
    ttk.Button(goals_bar, text='导出测算', command=export_plan).pack(side='left')
    ttk.Button(rule_bar, text='读取游戏目录基础容量', command=read_rules).pack(side='left', padx=8)

    def generate_repairs(choose_directory=False):
        from game_names import load_names
        if 'country_snapshot' not in current or not selected_id():
            messagebox.showinfo('修复方案', '请先导入存档并选择玩家帝国。')
            return
        directory = load_names().game_dir
        if choose_directory or not directory:
            directory = filedialog.askdirectory(title='选择与存档版本匹配的游戏安装目录')
        if not directory:
            return
        current.pop('repairs', None)
        try:
            rules = load_repair_rules(directory, current['report']['summary']['version'])
            country = field(field(current['report']['raw']['gamestate'], 'country'), selected_id())
            proposal = repair_plan(current['country_snapshot'], country, rules)
            current['repairs'] = proposal
            repair_text.delete('1.0', 'end')
            repair_text.insert('end', format_repairs(proposal))
        except (OSError, ValueError) as exc:
            repair_text.delete('1.0', 'end')
            repair_text.insert('end', '无法生成修复方案：%s\n存档版本：%s\n游戏目录：%s\n请选择匹配版本的目录，或导入由当前游戏版本保存的新存档。未套用其他版本的建筑效果。' %
                               (exc, current['report']['summary']['version'], directory))

    def export_repairs():
        if 'repairs' not in current:
            messagebox.showinfo('导出修复方案', '请先生成修复方案。')
            return
        destination = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')])
        if destination:
            try:
                export_report({'save_date': current['report']['summary']['date'], 'proposal': current['repairs']}, destination, current['source'])
                status.set('已导出逐星球修复方案。')
            except (OSError, SaveError) as exc:
                messagebox.showerror('导出失败', str(exc))

    ttk.Button(repair_bar, text='生成修复方案', command=generate_repairs).pack(side='left')
    ttk.Button(repair_bar, text='选择游戏目录并生成', command=lambda: generate_repairs(True)).pack(side='left', padx=8)
    ttk.Button(repair_bar, text='导出修复方案', command=export_repairs).pack(side='left')

    def load():
        source = filedialog.askopenfilename(filetypes=[('群星存档', '*.sav'), ('所有文件', '*.*')])
        if not source:
            return
        load_button.configure(state='disabled')
        status.set('正在解析存档…')
        country_picker.configure(state='disabled')
        future = executor.submit(inspect_save, source, parser_choice.get())

        def poll():
            if not future.done():
                root.after(100, poll)
                return
            load_button.configure(state='normal')
            country_picker.configure(state='readonly')
            try:
                report = future.result()
            except Exception as exc:
                status.set('导入失败；请检查存档格式。')
                messagebox.showerror('导入失败', str(exc))
                return
            current.clear()
            current.update(report=report, source=source)
            district_capacity.set('')
            rule_label.set('可选：读取同版本游戏目录作为基础容量参考。')
            plan_text.delete('1.0', 'end')
            repair_text.delete('1.0', 'end')
            ids = [p['country_id'] for p in report['summary']['player_economies']]
            candidates = {c['id']: c for c in report['summary']['countries']}
            labels = ['%s | %s | 首都 %s | %s颗殖民地' %
                      (cid, candidates[cid]['display_name'], candidates[cid]['capital_name'], candidates[cid]['colony_count'])
                      for cid in ids if cid in candidates]
            country_picker.configure(values=labels)
            selected_country.set(labels[0] if len(labels) == 1 else '')
            text.delete('1.0', 'end')
            text.insert('end', '存档日期：%s，版本：%s\n请选择要分析的玩家帝国 ID（多人存档不会自动选择）。' %
                        (report['summary']['date'], report['summary']['version']))
            show_country()
            tree.delete(*tree.get_children())
            pending.clear()
            insert('', [{'key': k, 'value': v} for k, v in report['raw'].items()])
            status.set('已导入 %s · %s解析器 · %s · 原始存档未修改' %
                       (Path(source).name, report['summary']['parser'],
                        '仅人类玩家相关数据' if report['summary']['scope'] == 'human_player_empires' else '完整存档'))
        root.after(100, poll)

    def export():
        if 'report' not in current:
            messagebox.showinfo('导出', '请先导入存档。')
            return
        dest = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')])
        if dest:
            try:
                export_report(current['report'], dest, current['source'])
                status.set('已导出解析报告。')
            except (OSError, SaveError) as exc:
                messagebox.showerror('导出失败', str(exc))

    load_button = ttk.Button(toolbar, text='导入存档', command=load)
    load_button.pack(side='left')
    ttk.Button(toolbar, text='导出 JSON', command=export).pack(side='left', padx=8)
    parser_choice = tk.StringVar(value='auto')
    ttk.Combobox(toolbar, textvariable=parser_choice, values=('auto', 'rust', 'python'), state='readonly', width=7).pack(side='left')
    ttk.Label(toolbar, text='玩家帝国').pack(side='left', padx=8)
    selected_country = tk.StringVar()
    country_picker = ttk.Combobox(toolbar, textvariable=selected_country, state='readonly', width=65)
    country_picker.pack(side='left')
    country_picker.bind('<<ComboboxSelected>>', show_country)
    root.mainloop()
    executor.shutdown(wait=False)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('save', nargs='?')
    cli.add_argument('--output', help='导出 JSON 文件')
    cli.add_argument('--parser', choices=('auto', 'rust', 'python'), default='auto')
    cli.add_argument('--game-dir', help='游戏安装目录，用于读取中文本地化')
    args = cli.parse_args()
    if args.game_dir:
        import os
        os.environ['STELLARIS_GAME_DIR'] = args.game_dir
    if args.save:
        try:
            report = inspect_save(args.save, args.parser)
            if args.output:
                export_report(report, args.output, args.save)
            print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
        except (SaveError, OSError) as exc:
            cli.exit(1, str(exc) + '\n')
    else:
        gui()
