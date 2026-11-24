"""Version-checked passive housing/amenity repair proposals, not a full rule VM."""
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import re

from planning import decimal, rural_rule_reference, value


def block(text, key):
    # Strip comments and tokenize strings so braces inside them are not structural.
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"|\#[^\n]*|[{}=]|[^\s{}="#]+', text))
    for i, token in enumerate(tokens[:-2]):
        if token.group() == key and tokens[i + 1].group() == '=' and tokens[i + 2].group() == '{':
            depth = 1
            for end in tokens[i + 3:]:
                if end.group() == '{':
                    depth += 1
                elif end.group() == '}':
                    depth -= 1
                    if depth == 0:
                        return text[tokens[i + 2].end():end.start()]
    raise ValueError('未找到规则块：' + key)


def number(text, key, variables):
    match = re.search(r'(?m)^\s*' + re.escape(key) + r'\s*=\s*(@?[\w.+-]+)', text)
    if not match:
        raise ValueError('缺少规则数值：' + key)
    token = match.group(1)
    if token.startswith('@') and token not in variables:
        raise ValueError('未找到规则变量：' + token)
    return decimal(variables[token] if token.startswith('@') else token)


def load_repair_rules(game_dir, save_version):
    reference = rural_rule_reference(game_dir, save_version)
    game = Path(game_dir)
    variables = {}
    for file in sorted((game / 'common/scripted_variables').glob('*.txt')):
        variables.update(re.findall(r'(?m)^\s*(@\w+)\s*=\s*([-+]?\d+(?:\.\d+)?)', file.read_text(encoding='utf-8-sig')))
    source = game / 'common/buildings/07_amenity_buildings.txt'
    text = source.read_text(encoding='utf-8-sig')
    rules = {}
    for key, amenity_key in (('building_luxury_residence', 'planet_amenities_add'),
                             ('building_hive_warren', 'planet_amenities_no_happiness_add')):
        definition = block(text, key)
        modifiers = block(definition, 'planet_modifier')
        resources = block(definition, 'resources')
        cost_script = block(resources, 'inline_script')
        rules[key] = {k: str(v) for k, v in {
            'housing': number(modifiers, 'planet_housing_add', variables),
            'amenities': number(modifiers, amenity_key, variables),
            'minerals': number(cost_script, 'COST', variables),
            'energy_upkeep': number(block(resources, 'upkeep'), 'energy', variables),
            'base_days': number(definition, 'base_buildtime', variables)}.items()}
        if decimal(rules[key]['amenities']) <= 0 or decimal(rules[key]['housing']) <= 0:
            raise ValueError('住房或舒适度规则必须为正')
    zones_source = game / 'common/zones/00_zones.txt'
    default = block(zones_source.read_text(encoding='utf-8-sig'), 'zone_default')
    return {'version': reference['version'], 'buildings': rules,
            'default_zone_capacity': int(number(default, 'max_buildings', variables)),
            'sources': [str(source), str(zones_source)],
            'assumption': '原版基础效果与基础成本；未计算 Mod、修正或完整触发器。'}


def repair_plan(snapshot, country, rules):
    authority = value(value(country, 'government'), 'authority')
    if authority == 'auth_hive_mind':
        building = 'building_hive_warren'
    elif authority in ('auth_democratic', 'auth_oligarchic', 'auth_dictatorial', 'auth_imperial', 'auth_corporate'):
        building = 'building_luxury_residence'
    else:
        raise ValueError('此政体尚未适配被动住房/舒适度建筑：' + str(authority))
    civics = [e['value'] for e in value(value(country, 'government'), 'civics') or []]
    if 'civic_shared_burden' in civics:
        raise ValueError('共享负担国民理念的建筑替代规则尚未适配')
    rule = rules['buildings'][building]
    rows = []
    for colony in snapshot['colonies']:
        housing, amenities = colony.get('free_housing'), colony.get('free_amenities')
        row = {'colony_id': colony['colony_id'], 'name': colony.get('name', '未知'),
               'system_name': colony.get('system_name', '未知'), 'building': building,
               'stability': colony.get('stability'), 'quantity': None, 'status': 'unknown',
               'notes': []}
        if housing is None or amenities is None:
            row['notes'].append('缺少住房或舒适度字段')
            rows.append(row)
            continue
        quantity = max(0, int((-decimal(housing) / decimal(rule['housing'])).to_integral_value(rounding=ROUND_CEILING)),
                       int((-decimal(amenities) / decimal(rule['amenities'])).to_integral_value(rounding=ROUND_CEILING)))
        row.update(quantity=quantity, status='no_repair_needed' if quantity == 0 else 'conditional',
                   housing_after_base=str(decimal(housing) + quantity * decimal(rule['housing'])),
                   amenities_after_base=str(decimal(amenities) + quantity * decimal(rule['amenities'])),
                   minerals_base=str(quantity * decimal(rule['minerals'])),
                   energy_upkeep_base=str(quantity * decimal(rule['energy_upkeep'])),
                   serial_base_days=str(quantity * decimal(rule['base_days'])))
        slots = sum(max(0, rules['default_zone_capacity'] - len(value(z['raw'], 'buildings') or []))
                    for z in colony.get('zones', []) if value(z['raw'], 'type') == 'zone_default')
        row['default_zone_free_slots_base'] = slots
        if quantity and slots < quantity:
            row['status'] = 'slot_review_required'
            row['notes'].append('默认分区空位不足；需核查其他分区资格或替换方案，不自动拆建筑')
        if quantity and colony.get('planet_class') in ('pc_habitat', None):
            row['status'] = 'eligibility_review_required'
            row['notes'].append('星球类型资格尚未确认')
        if quantity:
            row['notes'].append('科技/起源/星球修正/建设队列与 Mod 条件仍需核对')
        rows.append(row)
    desired = sum(r['quantity'] or 0 for r in rows)
    cost = sum((decimal(r.get('minerals_base', '0')) for r in rows), Decimal(0))
    upkeep = sum((decimal(r.get('energy_upkeep_base', '0')) for r in rows), Decimal(0))
    energy = snapshot['economy']['resources'].get('energy', {}).get('net')
    stock = snapshot['inventory'].get('minerals')
    queue = sorted([r for r in rows if r['quantity']], key=lambda r: decimal(r['stability']) if r['stability'] is not None else Decimal(100))
    return {'status': 'base_rule_proposal', 'country_id': snapshot['country_id'], 'rows': rows,
            'unknown_colony_count': sum(r['quantity'] is None for r in rows),
            'priority_colony_ids': [r['colony_id'] for r in queue], 'quantity_total': desired,
            'minerals_base_total': str(cost), 'energy_upkeep_base_total': str(upkeep),
            'base_cost_within_current_stockpile': decimal(stock) >= cost if stock is not None else None,
            'energy_net_after_base_upkeep': str(decimal(energy) - upkeep) if energy is not None else None,
            'rules': rules, 'limitations': [rules['assumption'],
                '排序按稳定度从低到高，仅为优先级；不是经过施工时间模拟的队列。',
                '未预测稳定度恢复后的资源增产，未自动批准替换、拆除或执行建设。']}


def format_repairs(plan):
    labels = {'building_luxury_residence': '奢侈住所', 'building_hive_warren': '蜂巢养殖场'}
    lines = ['逐星球住房与舒适度修复（基础规则方案）']
    for row in plan['rows']:
        lines.append('\n%s｜%s｜殖民地 %s' % (row['name'], row['system_name'], row['colony_id']))
        if row['quantity'] is None:
            lines.append('数据不足，无法计算数量。')
        elif row['quantity'] == 0:
            lines.append('新增 0 座：当前住房与舒适度无需修复。')
        else:
            lines.append('新增 %s × %s；基础矿物 %s；基础能量维护 +%s/月' %
                         (labels[row['building']], row['quantity'], row['minerals_base'], row['energy_upkeep_base']))
            lines.append('基础效果后：住房余量 %s，舒适度余量 %s；默认分区基础空位 %s' %
                         (row['housing_after_base'], row['amenities_after_base'], row['default_zone_free_slots_base']))
            lines.append('本星球串行基础工期 %s 天（未计队列与速度修正）' % row['serial_base_days'])
        lines.extend(row['notes'])
    lines.append('\n总计 %s 座，基础矿物 %s，基础能量维护 +%s/月。全部完成后仅计基础维护的能量净收入：%s。' %
                 (plan['quantity_total'], plan['minerals_base_total'], plan['energy_upkeep_base_total'], plan['energy_net_after_base_upkeep']))
    lines.append('稳定度优先顺序（含待核对项）：' + ' → '.join(plan['priority_colony_ids']))
    lines.extend(plan['limitations'])
    return '\n'.join(lines)
