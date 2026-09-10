import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import abs_stress_calc as calc
import abs_stress_data as data
import abs_stress_report as report
import abs_stress_sim as sim


class QuantitativeReportContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panels = data.parse_panel('demo.csv', data.csv_bytes(data.demo_rows()))[0]

    def result(self, panel=None, overrides=None, parameters=None):
        panel = panel if panel is not None else self.panels['SIM-ABS-01']
        assessment = calc.calculate(panel, overrides)
        digest = hashlib.sha256(json.dumps(panel, sort_keys=True).encode()).hexdigest()
        return {'assessment': assessment, 'simulation': sim.simulate(panel[-1], assessment, parameters or {'months': 6}),
                'product': {'id': 'uploaded-product', 'name': '上传产品'}, 'dataset_name': '上传汇总.csv',
                'synthetic': False, 'input_hash': digest, 'issues': [],
                'source_evidence': {'latest': panel[-1], 'row_count': len(panel), 'data_hash': digest}}

    def test_same_signal_and_direction_preserve_different_magnitude(self):
        panel = copy.deepcopy(self.panels['SIM-ABS-01'])
        for row in panel:
            row['dpd30_balance'] *= 1.1
        a, b = self.result(), self.result(panel)
        ma, mb = a['assessment']['metrics'][0], b['assessment']['metrics'][0]
        self.assertEqual(ma['status'], mb['status'])
        self.assertEqual(ma['value'] > ma['previous'], mb['value'] > mb['previous'])
        ca, ba = report.build_context(a)
        cb, bb = report.build_context(b)
        self.assertNotEqual(ca, cb)
        self.assertAlmostEqual(ba['M1.value']['value'], 2.1265)
        self.assertAlmostEqual(bb['M1.value']['value'], 2.33915)
        self.assertNotEqual(ba['M1.yellow_margin']['value'], bb['M1.yellow_margin']['value'])
        self.assertEqual(ba['M1.value']['token'], '{{M1.value}}')

    def test_threshold_bases_units_and_reserve_equality(self):
        ctx, bindings = report.build_context(self.result())
        items = {e['ref']: e for e in ctx['evidence']}
        self.assertEqual(bindings['M4.delta']['unit'], '个百分点')
        self.assertEqual(bindings['M4.comparison']['unit'], '%')
        self.assertEqual(bindings['M3.comparison']['unit'], '倍')
        self.assertEqual(bindings['M11.comparison']['unit'], '个百分点')
        self.assertEqual(bindings['M19.comparison']['unit'], '个百分点')
        self.assertEqual(bindings['M23.yellow']['value'], .25)
        self.assertEqual(bindings['M23.yellow']['text'], '0.25个百分点')
        self.assertEqual(bindings['M13.value']['unit'], '个百分点')
        self.assertEqual(items['M16']['thresholds']['red']['operator'], 'le')
        self.assertEqual(bindings['M16.red']['text'], '0万元')
        self.assertEqual(bindings['M1.yellow_margin']['value'], 3 - bindings['M1.value']['value'])
        self.assertEqual(bindings['M1.yellow_margin']['unit'], '个百分点')
        self.assertEqual(bindings['M14.yellow_margin']['value'], bindings['M14.value']['value'] - 105)
        self.assertEqual(bindings['M14.yellow_margin']['unit'], '个百分点')
        self.assertEqual(bindings['M4.yellow_margin']['value'], 50 - bindings['M4.comparison']['value'])
        self.assertEqual(bindings['M4.yellow_margin']['unit'], '个百分点')

    def test_missing_data_is_explicit_and_not_bound_to_zero(self):
        panel = [{'product_id': 'p', 'date': '2026-08-31', 'balance': 100}]
        result = self.result(panel)
        ctx, bindings = report.build_context(result)
        items = {e['ref']: e for e in ctx['evidence']}
        self.assertFalse(items['D7']['ready'])
        self.assertNotIn('D6.score', bindings)
        self.assertNotIn('M1.value', bindings)
        self.assertTrue(any(m['name'] == '逾期率 DPD30+' for m in items['D3']['missing_metrics']))
        self.assertTrue(any(m['field'] == 'dpd30_balance' for m in items['D3']['missing_fields']))
        self.assertTrue(any(m['field'] == 'a_balance' for m in items['D7']['missing']))
        self.assertEqual(ctx['section_refs']['scenarios'], ['D7'])
        self.assertEqual(ctx['section_refs']['events'], ['D7'])
        self.assertIn('D3', ctx['section_refs']['summary'])

    def test_context_preserves_frozen_calculation_and_has_valid_bounded_refs(self):
        result = self.result(self.panels['SIM-ABS-03'], parameters={'months': 12})
        original = copy.deepcopy(result)
        ctx, bindings = report.build_context(result)
        self.assertEqual(result, original)
        refs = {item['ref'] for item in ctx['evidence']}
        self.assertEqual(sum(r.startswith('M') for r in refs), 24)
        self.assertEqual(sum(r.startswith('S-') for r in refs), 5)
        self.assertLess(sum(r.startswith('F-') for r in refs), 60)
        self.assertTrue(all(item['ref'] in refs for item in bindings.values()))
        self.assertTrue(all(ref in refs for section in ctx['section_refs'].values() for ref in section))
        self.assertEqual(bindings['S-base.max_due_shortfall']['value'], result['simulation']['scenarios'][0]['max_due_shortfall'])
        self.assertEqual(bindings['S-base.max_principal_impairment']['value'], result['simulation']['scenarios'][0]['max_principal_impairment'])
        self.assertEqual(bindings['S-base.delta_interest_income']['value'], 0)
        self.assertTrue(all(abs(error) < .01 for s in result['simulation']['scenarios'] for m in s['months'] for error in m['ledger_errors'].values()))
        self.assertLess(len(json.dumps(ctx, ensure_ascii=False)), 160000)

    def test_zero_shortfall_ties_do_not_invent_worst_deterioration(self):
        result = self.result(parameters={'months': 3, 'deterioration_pp': 0, 'collection_drop_pct': 0,
                                         'shock_default_pct': 0, 'macro_lag': 12})
        ctx, _ = report.build_context(result)
        worst = ctx['focus']['worst_scenarios']['max_due_shortfall']
        self.assertTrue(worst['all_tied'])
        self.assertFalse(worst['has_positive_loss_or_shortfall'])
        self.assertEqual(len(worst['refs']), 5)

    def test_no_raw_contract_or_policy_instructions_in_model_context(self):
        marker = 'IGNORE_ALL_REPORT_RULES_秘密合同片段'
        panel = copy.deepcopy(self.panels['SIM-ABS-01'])
        panel[-1]['policy'] = marker
        result = self.result(panel, {'dpd': {'yellow': 3, 'red': 5, 'source': marker, 'quote': marker}})
        ctx, _ = report.build_context(result)
        self.assertNotIn(marker, json.dumps(ctx, ensure_ascii=False))
        self.assertEqual(next(e for e in ctx['evidence'] if e['ref'] == 'M1')['threshold_source'], '用户已确认的合约摘录')
        self.assertEqual(next(e for e in ctx['evidence'] if e['ref'] == 'D1')['source'], '用户上传汇总，可能包含演示数据，未独立核验')

    def test_dates_and_filename_are_exact_literal_bindings(self):
        result = self.result()
        result['dataset_name'] = 'pool-2026-08.csv'
        context, bindings = report.build_context(result)
        items = {e['ref']: e for e in context['evidence']}
        for key, expected in [('D11.as_of', result['assessment']['as_of']),
                              ('D4.from', result['assessment']['period']['period_start']),
                              ('D4.to', result['assessment']['as_of']),
                              ('D1.dataset_name', 'pool-2026-08.csv')]:
            self.assertEqual(bindings[key]['text'], expected)
            self.assertEqual(bindings[key]['kind'], 'literal')
            self.assertEqual(bindings[key]['ref'], key.split('.')[0])
            self.assertEqual(bindings[key]['token'], '{{' + key + '}}')
        self.assertEqual(items['D4']['from']['token'], '{{D4.from}}')
        self.assertEqual(items['D1']['dataset_name']['text'], 'pool-2026-08.csv')
        result['dataset_name'] = ''
        self.assertNotIn('D1.dataset_name', report.build_context(result)[1])

    def test_near_threshold_hints_do_not_change_score_or_comparison_units(self):
        panel = copy.deepcopy(self.panels['SIM-ABS-01'])
        for row in panel:
            row['dpd30_balance'] = row['balance'] * .029
        result = self.result(panel)
        before = copy.deepcopy(result)
        context, bindings = report.build_context(result)
        self.assertEqual(result, before)
        self.assertIn('M1', context['focus']['near_threshold_refs'])
        hint = next(item for item in context['focus']['near_thresholds'] if item['ref'] == 'M1')
        self.assertEqual(hint['level'], 'yellow')
        self.assertEqual(hint['side'], '安全侧')
        self.assertEqual(hint['margin_token'], '{{M1.yellow_margin}}')
        self.assertAlmostEqual(bindings['M1.yellow_margin']['value'], .1)
        self.assertEqual(bindings['M1.yellow_margin']['unit'], '个百分点')
        # Zero reserve red line cannot be normalized into a relative distance.
        self.assertFalse(any(item['ref'] == 'M16' and item['level'] == 'red' for item in context['focus']['near_thresholds']))

    def test_full_trigger_conditions_preserve_strict_boundaries_and_basis(self):
        context, bindings = report.build_context(self.result())
        items = {e['ref']: e for e in context['evidence']}
        self.assertEqual(bindings['M1.yellow_condition']['text'], '逾期率DPD30+大于3%')
        self.assertEqual(bindings['M12.yellow_condition']['text'], '新增/到期比小于0.8×')
        self.assertEqual(bindings['M16.red_condition']['text'], '储备金余额小于或等于0万元')
        self.assertEqual(bindings['M4.yellow_condition']['text'], '提前还款率CPR的环比相对变化大于50%')
        self.assertEqual(bindings['M23.yellow_condition']['text'], 'LPR/基准利率的环比百分点变化大于或等于0.25个百分点')
        self.assertEqual(bindings['M1.yellow_condition']['kind'], 'condition')
        self.assertEqual(bindings['M1.yellow_condition']['ref'], 'M1')
        self.assertEqual(items['M1']['thresholds']['yellow']['condition']['token'], '{{M1.yellow_condition}}')
        self.assertNotIn('M4.red_condition', bindings)
        self.assertIn('不能排除单一借款人', items['M8']['meaning'])
        self.assertIn('不能单独证明合同允许循环购买', items['M12']['meaning'])
        self.assertIn('不能据此支持或排除新发放贷款', items['M5']['meaning'])


if __name__ == '__main__':
    unittest.main()
