"""Quantitative, bounded report evidence from an immutable calculated run.

The model selects and explains observations. Numeric prose is bound to these
values instead of asking the model to calculate, copy or round them.
"""
import math

from abs_stress_data import FIELDS

VERSION = 'stress-report-2.0'
LABELS = {'green': '绿灯', 'yellow': '黄灯', 'red': '红灯', 'gray': '待评估'}
STATES = {'normal': '正常分配', 'accelerated': '加速分配', 'default': '违约分配'}
BASIS = {'value': '当前水平', 'change_pct': '环比相对变化', 'change_pp': '环比百分点变化',
         'forecast_multiple': '相对发行预测倍数', 'negative_periods': '连续负余缺完整月数'}
MEANINGS = {
    'ccr': '累计违约本金比例，未扣回收，不是累计净损失。',
    'term': '存量余额加权剩余期限，不能据此支持或排除新发放贷款的期限、金额或客群特征，也不能推断借款人还款变化的原因。',
    'average': '存量平均贷款余额，不能据此支持或排除新发放贷款的金额、期限或客群特征，也不能推断借款人还款变化的原因。',
    'region': '最大单省余额占比，仅是地域汇总集中度。未越预警线不表示不存在地域集中风险，也不能排除单一借款人暴露风险。',
    'top10': '余额最高的前百分之十贷款合计占比，不是前十笔贷款，也不是统计学偏度。仅有汇总比例不能排除单一借款人暴露风险；未越线不等于不存在集中风险。',
    'wal': '计划本金加权回收期限，不等于实际摊还速度。',
    'replacement': '本期新增与到期本金比，不能单独证明合同允许循环购买、交易实际处于循环期或循环购买机制正常运作；单期不足也不证明长期缺乏补充资产。',
    'spread': '利率差，当前水平及变化均以百分点表达。',
    'policy': '上传者的政策排查标记，不是联网核实的政策结论。',
}
PARAMETERS = {
    'months': ('预测窗口', '个月'), 'deterioration_pp': ('逾期抬升', '个百分点'),
    'collection_drop_pct': ('回款率下降假设', '%'), 'early_cpr_pct': ('早偿冲击年化CPR', '%'),
    'shock_default_pct': ('集中违约本金比例', '%'), 'shock_month': ('集中违约预测期', '期'),
    'recovery_pct': ('违约回收比例假设', '%'), 'recovery_lag': ('回收滞后', '个月'),
    'macro_unemployment_pp': ('失业率冲击', '个百分点'), 'macro_income_pp': ('收入增速冲击', '个百分点'),
    'macro_confidence_pct': ('信心指数相对冲击', '%'), 'macro_lpr_bp': ('LPR冲击', 'bp'),
    'macro_lag': ('宏观传导滞后', '个月'), 'macro_cdr_multiplier': ('宏观违约倍率假设', '倍'),
    'fee_pct': ('服务费年率', '%'), 'reserve_target_pct': ('储备目标占余额', '%'),
    'acceleration_dpd_pct': ('演示加速触发DPD', '%'), 'default_ccr_pct': ('演示违约触发CCR', '%'),
}
FIELD_NAMES = {key: name for key, name, _ in FIELDS}


def build_context(result):
    """Return model context and token bindings; never mutate the frozen result."""
    assessment, simulation = result['assessment'], result['simulation']
    latest = result.get('source_evidence', {}).get('latest', {})
    evidence, bindings, metrics = [], {}, assessment['metrics']

    def quantity(ref, field, value, unit, label, missing='缺失'):
        if value is None:
            return {'value': None, 'unit': unit, 'label': label, 'text': missing}
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Report evidence requires a finite number')
        shown, display_unit = (value / 10000, '万元') if unit == '元' else (value, unit)
        formatted = f'{shown:,.4f}'.rstrip('0').rstrip('.')
        if formatted in ('-0', ''):
            formatted = '0'
        key = ref + '.' + field
        item = {'token': '{{' + key + '}}', 'label': label, 'value': value, 'unit': unit,
                'text': formatted + display_unit}
        if display_unit != unit:
            item['display_unit'] = display_unit
        bindings[key] = {'ref': ref, **item}
        return item

    def cash(ref, field, value, label):
        return quantity(ref, field, value, '元', label)

    def period(ref, field, value, label):
        return quantity(ref, field, value, '期', label, '本次预测窗口内未发生')

    def literal(ref, field, value, label):
        """Allow exact source dates/names without authorizing invented numeric text."""
        if value is None or value == '':
            return {'value': None, 'label': label, 'text': '未提供'}
        if not isinstance(value, str):
            raise ValueError('Report literal evidence requires text')
        key = ref + '.' + field
        item = {'token': '{{' + key + '}}', 'label': label, 'value': value, 'unit': '', 'text': value,
                'kind': 'literal'}
        bindings[key] = {'ref': ref, **item}
        return item

    metric_items, ranked, near_thresholds = {}, [], []
    for metric in metrics:
        ref, mid, rule = metric['ref'], metric['id'], metric['threshold']
        value, previous, comparison = metric['value'], metric['previous'], metric['comparison']
        # Percent levels differ in percentage points; relative-change rules still use %.
        unit = '个百分点' if mid == 'spread' else metric['unit']
        delta_unit = '个百分点' if metric['unit'] == '%' else unit
        compare_unit = {'change_pct': '%', 'change_pp': '个百分点', 'forecast_multiple': '倍',
                        'negative_periods': '个月'}.get(rule['basis'], unit)
        delta = value - previous if value is not None and previous is not None else None
        item = {'ref': ref, 'id': mid, 'name': metric['name'], 'dimension': metric['dimension'],
                'signal': LABELS[metric['status']], 'status': metric['status'],
                'value': quantity(ref, 'value', value, unit, '本期' + metric['name']),
                'previous': quantity(ref, 'previous', previous, unit, '上期' + metric['name']),
                'delta': quantity(ref, 'delta', delta, delta_unit, '本期减上期'),
                'comparison': quantity(ref, 'comparison', comparison, compare_unit, BASIS[rule['basis']]),
                'basis': rule['basis'], 'basis_label': BASIS[rule['basis']],
                'formula': metric['formula'], 'thresholds': {},
                'threshold_source': '用户已确认的合约摘录' if rule.get('quote') else
                                    '用户设置' if rule['source'].startswith('用户') else '文档参考或演示假设',
                'meaning': MEANINGS.get(mid, '监控预警不自动构成法律事件；相关变化不证明因果。'),
                'missing': [name for name, val in [('本期值', value), ('前期值', previous), ('判灯比较值', comparison)] if val is None]}
        # Signed safety margin: positive is safe-side distance, negative is beyond the line.
        margins = []
        for level in ('yellow', 'red'):
            bound = rule[level]
            op = 'le' if mid == 'reserve' and bound == 0 else rule['op']
            margin = None if bound is None or comparison is None else (
                comparison - bound if op in ('lt', 'le') else bound - comparison)
            item['thresholds'][level] = {
                'operator': op, 'value': quantity(ref, level, bound, compare_unit, level + '预警线', '该级未设置'),
                'safety_margin': quantity(ref, level + '_margin', margin, '个百分点' if compare_unit == '%' else compare_unit,
                                          '比较值至预警线的有符号安全余量'),
            }
            if bound is not None:
                operator_text = {'gt': '大于', 'ge': '大于或等于', 'lt': '小于', 'le': '小于或等于'}[op]
                metric_name = metric['name'].split('（')[0].replace(' ', '')
                subject = metric_name if rule['basis'] == 'value' else metric_name + '的' + BASIS[rule['basis']]
                condition = subject + operator_text + item['thresholds'][level]['value']['text']
                key = ref + '.' + level + '_condition'
                bound_condition = {'token': '{{' + key + '}}', 'label': ('黄色' if level == 'yellow' else '红色') + '预警触发条件',
                                   'value': condition, 'unit': '', 'text': condition, 'kind': 'condition', 'operator': op}
                bindings[key] = {'ref': ref, **bound_condition}
                item['thresholds'][level]['condition'] = bound_condition
            if margin is not None:
                margins.append(margin / max(abs(bound), 1e-9))
                # Compare distance only with this indicator's own nonzero line.
                # A zero threshold has no meaningful relative-distance denominator.
                if abs(bound) > 1e-9 and abs(margin) / abs(bound) <= .1 + 1e-12:
                    near_thresholds.append({'ref': ref, 'level': level,
                                            'side': '安全侧' if margin > 0 else '已越线' if margin < 0 else '边界相等',
                                            'threshold_token': '{{' + ref + '.' + level + '}}',
                                            'margin_token': '{{' + ref + '.' + level + '_margin}}'})
        item['margin_meaning'] = '正值在安全侧，负值已越线；零值是否触发按operator判断。仅同一指标口径内比较。'
        evidence.append(item)
        metric_items[ref] = item
        ranked.append(({'red': 0, 'yellow': 1, 'gray': 2, 'green': 3}[metric['status']],
                       min(margins) if margins else math.inf, ref))

    scenario_items, event_refs, selected_period_refs = [], [], []
    for scenario in simulation.get('scenarios', []):
        ref, months = scenario['ref'], scenario['months']
        final = months[-1]
        first_gap = next((m['period'] for m in months if m['due_shortfall'] > .01), None)
        first_loss = next((m['period'] for m in months if m['principal_impairment'] > .01), None)
        first_depleted = next((m['period'] for m in months if m['ending_reserve'] <= .01), None)
        item = {'ref': ref, 'id': scenario['id'], 'name': scenario['name'], 'status': scenario['status'],
                'signal': LABELS[scenario['status']], 'ending_state': STATES[final['state']],
                'max_due_shortfall': cash(ref, 'max_due_shortfall', scenario['max_due_shortfall'], '窗口最大到期欠付存量'),
                'end_due_shortfall': cash(ref, 'end_due_shortfall', final['due_shortfall'], '期末到期欠付存量'),
                'max_principal_impairment': cash(ref, 'max_principal_impairment', scenario['max_principal_impairment'], '最大预计本金覆盖损失'),
                'interest_income': cash(ref, 'interest_income', scenario['interest_income'], '窗口利息回款合计'),
                'principal_collections': cash(ref, 'principal_collections', scenario['principal_collections'], '计划与早偿本金回款合计'),
                'ending_reserve': cash(ref, 'ending_reserve', final['ending_reserve'], '期末储备'),
                'reserve_drawn': cash(ref, 'reserve_drawn', sum(m['reserve_drawn'] for m in months), '窗口储备支用流量合计'),
                'first_shortfall': period(ref, 'first_shortfall', first_gap, '首次到期欠付预测期'),
                'first_coverage_loss': period(ref, 'first_coverage_loss', first_loss, '首次本金覆盖不足预测期'),
                'first_reserve_depletion': period(ref, 'first_reserve_depletion', first_depleted, '首次期末储备为零预测期'),
                'first_acceleration': period(ref, 'first_acceleration', scenario['first_acceleration'], '首次加速预测期'),
                'first_default': period(ref, 'first_default', scenario['first_default'], '首次违约分配预测期'),
                'delta_vs_base': {key: cash(ref, 'delta_' + key, val, '相对基准的' + key) for key, val in scenario['delta_vs_base'].items()},
                'tranches': [], 'event_refs': [], 'selected_period_refs': [],
                'meaning': '欠付是到期后仍未支付的存量，不能逐期相加；未到期本金不是欠付；预计覆盖损失不是实际核销，不含未来未实现利差。'}
        for tranche in scenario['tranches']:
            key = tranche['id']
            end_tranche = next(t for t in final['tranches'] if t['id'] == key)
            item['tranches'].append({
                'name': tranche['name'],
                'initial': cash(ref, key + '_initial', tranche['initial'], tranche['name'] + '初始本金'),
                'max_impairment': cash(ref, key + '_max_impairment', tranche['max_impairment'], tranche['name'] + '最大本金覆盖损失'),
                'impairment_ratio': quantity(ref, key + '_impairment_ratio', tranche['impairment_ratio'], '%', '覆盖损失占该档初始本金'),
                'end_due_shortfall': cash(ref, key + '_end_due_shortfall', tranche['end_due_shortfall'], tranche['name'] + '期末到期欠付'),
                'not_yet_due_principal': cash(ref, key + '_not_yet_due', end_tranche['not_yet_due_principal'], tranche['name'] + '期末未到期本金'),
                'first_shortfall': period(ref, key + '_first_shortfall', tranche['first_shortfall'], tranche['name'] + '首次欠付预测期'),
                'breach_month': period(ref, key + '_breach', tranche['breach_month'], tranche['name'] + '剩余本金首次全额失去覆盖预测期'),
            })
        chosen = {1, final['period'], first_gap, first_loss, first_depleted}
        chosen.update(event['period'] for event in scenario['events'])
        for event in scenario['events']:
            er = event['ref']
            event_refs.append(er)
            item['event_refs'].append(er)
            evidence.append({'ref': er, 'scenario': scenario['name'], 'from': STATES[event['from']], 'to': STATES[event['to']],
                             'period': period(er, 'period', event['period'], '条件情景切换预测期'),
                             'metric': event['metric'], 'value': quantity(er, 'value', event['value'], '%', '预测触发指标'),
                             'threshold': quantity(er, 'threshold', event['threshold'], '%', '演示事件触发线'),
                             'operator': 'ge', 'meaning': '基于确认的演示参数作出的预测，不表示实际法律事件已经发生。'})
        for month in months:
            if month['period'] not in chosen:
                continue
            fr = month['ref']
            selected_period_refs.append(fr)
            item['selected_period_refs'].append(fr)
            evidence.append({'ref': fr, 'scenario': scenario['name'], 'state': STATES[month['state']],
                             'period': period(fr, 'period', month['period'], '预测期'),
                             **{key: cash(fr, key, month[key], label) for key, label in (
                                 ('interest_income', '本期利息回款'), ('scheduled_principal', '本期计划本金回款'),
                                 ('prepayment_principal', '本期早偿本金'), ('default_recovery', '本期到账回收'),
                                 ('due_shortfall', '期末到期欠付存量'), ('principal_impairment', '期末预计本金覆盖损失'),
                                 ('ending_reserve', '期末储备'), ('pending_recoveries', '尚未到账预计回收'))}})
        scenario_items.append(item)
        evidence.append(item)

    missing_metrics = [{'ref': m['ref'], 'name': m['name'], 'missing': metric_items[m['ref']]['missing'],
                        'reason': m['note'] or '未设置可用阈值'} for m in metrics if m['status'] == 'gray']
    missing_fields = [{'field': key, 'name': FIELD_NAMES.get(key.removeprefix('month_sum:'), key)} for key, value in assessment['period'].items()
                      if value is None and (key in FIELD_NAMES or key.startswith('month_sum:'))]
    missing_sim = [{'field': key, 'name': FIELD_NAMES.get(key, next((m['name'] for m in metrics if m['id'] == key), key))}
                   for key in simulation.get('missing', [])]
    metadata = [
        {'ref': 'D1', 'name': '数据来源', 'synthetic': result['synthetic'],
         'dataset_name': literal('D1', 'dataset_name', result.get('dataset_name'), '上传数据集文件名'),
         'source': '系统生成的合成示例' if result['synthetic'] else '用户上传汇总，可能包含演示数据，未独立核验'},
        {'ref': 'D2', 'name': '计算方法', 'method_version': assessment['method_version'], 'notes': assessment['notes']},
        {'ref': 'D3', 'name': '完整性', 'missing_metrics': missing_metrics, 'missing_fields': missing_fields,
         'issues': result.get('issues', []), 'assessed': quantity('D3', 'assessed', assessment['assessed'], '项', '已评估指标数量')},
        {'ref': 'D4', 'name': '本次指标自然月期间',
         'from': literal('D4', 'from', assessment['period']['period_start'], '本期指标统计起日'),
         'to': literal('D4', 'to', assessment['as_of'], '本期指标统计截止日'),
         'complete_month': assessment['period']['complete_month'],
         'days': quantity('D4', 'days', assessment['period']['days'], '天', '本期日度观测天数')},
        {'ref': 'D5', 'name': '规模及补充指标', 'balance': cash('D5', 'balance', latest.get('balance'), '期末资产池余额'),
         'rows': quantity('D5', 'rows', result.get('source_evidence', {}).get('row_count'), '行', '该产品上传观测数'),
         'aggregates': {key: quantity('D5', key, val, '年' if key == 'duration_years' else '%', key)
                        for key, val in assessment['aggregates'].items()}},
        {'ref': 'D6', 'name': '内部监控总览', 'score': quantity('D6', 'score', assessment['score'], '分', '程序计算的信用监控分'),
         'signal': LABELS[assessment['status']], 'score_boundary': '内部阈值监控分，不是信用评级'},
        {'ref': 'D7', 'name': '压力推演完整性', 'ready': simulation['ready'], 'missing': missing_sim},
        {'ref': 'D8', 'name': '政策来源', 'source': '仅来自上传汇总的政策标记，未联网核实；原始自由文本不传给模型'},
        {'ref': 'D9', 'name': '当前分析产品', 'product': result['product']},
        {'ref': 'D10', 'name': '冻结输入身份', 'input_hash': result['input_hash'],
         'data_hash': result.get('source_evidence', {}).get('data_hash')},
        {'ref': 'D11', 'name': '观察截止日', 'as_of': literal('D11', 'as_of', assessment['as_of'], '数据观察截止日')},
        {'ref': 'D12', 'name': '适用边界', 'meaning': '汇总未独立核验；没有逐笔借款人行为或法律履约证据；未执行任何处置。'},
        {'ref': 'A1', 'name': '用户确认的条件假设', 'parameters': {
            key: quantity('A1', key, simulation['parameters'][key], unit, label)
            for key, (label, unit) in PARAMETERS.items()}, 'default_accelerates': simulation['parameters']['default_accelerates']},
        {'ref': 'A2', 'name': '模拟假设与限制', 'assumptions': simulation.get('assumptions', []),
         'boundary': '条件测算，不是概率预测；封闭池与汇总摊还近似；宏观传导强度未从上传样本拟合。'},
    ]
    evidence.extend(metadata)
    # Rank only to guide attention: this does not alter or reinterpret the score.
    ranked.sort()
    focus = [ref for _, _, ref in ranked[:6]]
    worst = {}
    for key in ('max_due_shortfall', 'max_principal_impairment'):
        if scenario_items:
            maximum = max(s[key]['value'] for s in scenario_items)
            worst[key] = {'all_tied': all(abs(s[key]['value'] - maximum) <= .01 for s in scenario_items),
                          'refs': [s['ref'] for s in scenario_items if abs(s[key]['value'] - maximum) <= .01],
                          'has_positive_loss_or_shortfall': maximum > .01}
    scenario_refs = [s['ref'] for s in scenario_items]
    section_refs = {
        'summary': ['D6', 'D5', 'D3'] + focus + scenario_refs,
        'quality': [m['ref'] for m in metrics if m['dimension'] in ('loan', 'macro')],
        'structure': [m['ref'] for m in metrics if m['dimension'] in ('pool', 'cash')] + ['D5'] + scenario_refs,
        'scenarios': scenario_refs + selected_period_refs if scenario_items else ['D7'],
        'events': event_refs + scenario_refs if scenario_items else ['D7'],
        'limitations': ['D1', 'D2', 'D3', 'D7', 'D12', 'A1', 'A2'],
    }
    context = {'version': VERSION, 'product': result['product'], 'as_of': assessment['as_of'],
               'input_hash': result['input_hash'], 'evidence': evidence, 'section_refs': section_refs,
               'focus': {'metric_refs': focus, 'ranking_basis': '先预警等级，再同指标归一化阈值余量；不是因果贡献或统计重要性',
                         'has_alerts': bool(assessment['alerts']), 'unassessed_refs': [m['ref'] for m in missing_metrics],
                         'near_threshold_refs': list(dict.fromkeys(item['ref'] for item in near_thresholds)),
                         'near_thresholds': near_thresholds,
                         'near_threshold_basis': '比较值与该指标非零阈值的绝对距离不超过该阈值绝对值的十分之一；同时列示安全侧、越线侧及边界相等。只是关注提示，不改变分数或灯色，不比较不同指标的原始单位。',
                         'worst_scenarios': worst},
               'numeric_contract': '仅通过给定token写数值；token替换为text。value是原始单位值，货币text换算为万元。不可混淆百分比和百分点，不得计算新比率。'}
    return context, bindings
