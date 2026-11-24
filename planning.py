"""Capacity and labour estimates, deliberately separate from game-rule simulation."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
from pathlib import Path
import re


FAMILIES = {
    'food': ('agri_drone', 'farmer'),
    'energy': ('technician_drone', 'technician'),
}
LABELS = {'food': '食物', 'energy': '能量'}


def decimal(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('请输入有效数字')
    if not result.is_finite():
        raise ValueError('数值必须有限')
    return result


def value(entries, key):
    return next((e['value'] for e in entries or [] if e['key'] == key), None)


def rural_rule_reference(game_dir, save_version):
    """Read a narrowly scoped base capacity; do not evaluate scripted triggers."""
    game = Path(game_dir)
    settings = json.loads((game / 'launcher-settings.json').read_text(encoding='utf-8-sig'))
    version = settings.get('rawVersion', '').lstrip('v')
    match = re.search(r'\bv?(\d+\.\d+\.\d+)\b', str(save_version))
    if not match or match.group(1) != version:
        raise ValueError('游戏目录版本与存档版本不一致')
    source = game / 'common/scripted_variables/100_scripted_variables_zones.txt'
    text = source.read_text(encoding='utf-8-sig')
    found = re.search(r'^\s*@base_rural_district_jobs\s*=\s*(\d+)\s*(?:#.*)?$', text, re.M)
    if not found or int(found.group(1)) <= 0:
        raise ValueError('无法识别基础乡村区域岗位容量')
    return {'version': version, 'workforce_per_district': int(found.group(1)),
            'source': str(source),
            'note': '基础岗位容量参考；未计算科技、国民理念、Mod 和区域上限。'}


def labour_overview(snapshot):
    rows = []
    for colony in snapshot['colonies']:
        assigned = Decimal(0)
        families = {r: {'filled': Decimal(0), 'vacant': Decimal(0)} for r in FAMILIES}
        unknown = False
        for job in colony.get('jobs', []):
            if job.get('workforce') is None or job.get('max_workforce') is None:
                unknown = True
                continue
            filled, maximum = decimal(job['workforce']), decimal(job['max_workforce'])
            if maximum < 0:  # unlimited/special sentinel, not finite production capacity
                if filled > 0:
                    assigned += filled
                continue
            if filled < 0:
                unknown = True
                continue
            assigned += filled
            for resource, types in FAMILIES.items():
                if job['type'] in types:
                    families[resource]['filled'] += filled
                    families[resource]['vacant'] += max(Decimal(0), maximum - filled)
        employable = colony.get('employable_pops')
        idle = None if employable is None or unknown else max(Decimal(0), decimal(employable) - assigned)
        rows.append({'colony_id': colony['colony_id'],
                     'idle_upper_bound': str(idle) if idle is not None else None,
                     'families': {r: {k: str(v) for k, v in vals.items()} for r, vals in families.items()}})
    return rows


def target_estimate(snapshot, country, targets, rates=None, workforce_per_district=None):
    """Conditional estimates, not a feasible assignment or a construction queue.

    Rates are output per 100 raw workforce units, not game UI population units.
    Existing vacant capacity is shared only within its resource family.
    """
    rates = rates or {}
    overview = labour_overview(snapshot)
    results = {}
    needed_total = 0
    missing = []
    for resource, target in targets.items():
        if resource not in FAMILIES:
            raise ValueError('暂只支持食物与能量目标')
        target = decimal(target)
        baseline = snapshot['economy']['resources'].get(resource, {}).get('net')
        filled = sum((decimal(c['families'][resource]['filled']) for c in overview), Decimal(0))
        vacant = sum((decimal(c['families'][resource]['vacant']) for c in overview), Decimal(0))
        source = '用户输入的每 100 存档劳动力产出假设'
        rate = rates.get(resource)
        if rate is None:
            source = '上月岗位收入 / 当前已分配劳动力；跨期平均，仅作情景假设'
            category = 'planet_farmers' if resource == 'food' else 'planet_technician'
            income = value(value(value(country, 'budget'), 'last_month'), 'income')
            category_rows = [e['value'] for e in income or [] if e['key'] == category]
            production = []
            for group in category_rows:
                production.extend(e['value'] for e in group if e['key'] == resource)
            rate = sum((decimal(p) for p in production), Decimal(0)) * 100 / filled if production and filled > 0 else None
        if rate is not None:
            rate = decimal(rate)
            if rate <= 0:
                raise ValueError('每 100 劳动力产出必须大于零')
        gap = max(Decimal(0), target - decimal(baseline)) if baseline is not None else None
        required = None
        if gap == 0:
            required = 0
        elif gap is not None and rate is not None:
            required = int((gap * 100 / rate).to_integral_value(rounding=ROUND_CEILING))
        if required is None:
            missing.append(resource)
        else:
            needed_total += required
        capacity_gap = max(Decimal(0), decimal(required) - vacant) if required is not None else None
        districts = None
        if capacity_gap is not None and workforce_per_district is not None:
            per_district = decimal(workforce_per_district)
            if per_district <= 0:
                raise ValueError('区域基础岗位容量必须大于零')
            districts = int((capacity_gap / per_district).to_integral_value(rounding=ROUND_CEILING))
        results[resource] = {
            'target': str(target), 'baseline_net': baseline,
            'gap': str(gap) if gap is not None else None,
            'assumed_output_per_100_workforce': str(rate) if rate is not None else None,
            'rate_source': source, 'required_extra_workforce': required,
            'existing_vacant_workforce_capacity': str(vacant),
            'capacity_shortfall': str(capacity_gap) if capacity_gap is not None else None,
            'additional_district_capacity_lower_bound': districts,
        }
    idle_values = [c['idle_upper_bound'] for c in overview]
    idle = sum((decimal(v) for v in idle_values), Decimal(0)) if all(v is not None for v in idle_values) else None
    labour_gap = max(Decimal(0), decimal(needed_total) - idle) if not missing and idle is not None else None
    return {
        'status': 'conditional_estimate', 'resources': results, 'colonies': overview,
        'assumed_workforce_per_district': str(workforce_per_district) if workforce_per_district is not None else None,
        'idle_workforce_upper_bound': str(idle) if idle is not None else None,
        'extra_workforce_needed_total': needed_total if not missing else None,
        'workforce_shortfall_after_idle': str(labour_gap) if labour_gap is not None else None,
        'limitations': [
            '不是可执行建设方案：空岗不等于可调配人口，跨星球迁移与岗位资格尚未校验。',
            '调岗会损失原岗位产出；本测算未模拟这些损失及稳定度、维护费和副产物变化。',
            '区域数量仅为额外岗位容量下限；科技、建筑槽、区域上限和建设资金尚未校验。',
        ],
    }


def format_estimate(plan):
    def shown(value, places=2):
        return '未知' if value is None else format(decimal(value), '.' + str(places) + 'f')

    lines = ['目标缺口测算（情景估算，非最终建设队列）', '所有劳动力数量均为存档原始单位。']
    for resource, row in plan['resources'].items():
        lines.extend([
            '\n%s：上月净收入 %s → 目标 %s，缺口 %s' %
            (LABELS[resource], shown(row['baseline_net']), shown(row['target']), shown(row['gap'])),
            '每 100 劳动力假设产出：%s' % shown(row['assumed_output_per_100_workforce'], 4),
            '来源：' + row['rate_source'],
            '需额外分配劳动力：%s；已有空岗容量：%s' %
            (row['required_extra_workforce'], row['existing_vacant_workforce_capacity']),
            '补足容量至少新增区域：%s（未知表示未提供区域基础容量）' %
            row['additional_district_capacity_lower_bound'],
        ])
    lines.append('\n未分配劳动力上限：%s；仍需新增或调岗：%s' %
                 (plan['idle_workforce_upper_bound'], plan['workforce_shortfall_after_idle']))
    if plan['workforce_shortfall_after_idle'] is not None and decimal(plan['workforce_shortfall_after_idle']) > 0:
        lines.append('当前不能仅靠填补空岗实现目标：先确定人口来源与调岗代价，再决定是否建设。')
    lines.append('\n各殖民地现有空岗容量：')
    for colony in plan['colonies']:
        lines.append('殖民地 %s：农业 %s，发电 %s，未分配上限 %s' %
                     (colony['colony_id'], colony['families']['food']['vacant'],
                      colony['families']['energy']['vacant'], colony['idle_upper_bound']))
    lines.extend(plan['limitations'])
    return '\n'.join(lines)
