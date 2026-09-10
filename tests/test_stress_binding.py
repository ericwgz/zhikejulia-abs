import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from abs_stress_binding import normalize


class ExactNumberBindingTests(unittest.TestCase):
    def setUp(self):
        self.bindings = {
            'M1.value': {'ref': 'M1', 'text': '2.9%'},
            'M1.yellow': {'ref': 'M1', 'text': '3%'},
            'M1.delta': {'ref': 'M1', 'text': '0.1个百分点'},
            'M15.value': {'ref': 'M15', 'text': '1.31×'},
            'S-base.interest': {'ref': 'S-base', 'text': '1,234.5678万元'},
            'S-base.delta': {'ref': 'S-base', 'text': '-69.1717万元'},
            'D6.score': {'ref': 'D6', 'text': '100分'},
            'D11.as_of': {'ref': 'D11', 'text': '2026-08-31', 'kind': 'literal'},
            'D1.dataset_name': {'ref': 'D1', 'text': '资产3个月-2026-08-31.csv', 'kind': 'literal'},
            'M1.yellow_condition': {'ref': 'M1', 'text': '逾期率DPD30+大于3%', 'kind': 'condition'},
        }

    def test_correct_copied_display_numbers_become_owned_tokens(self):
        result = normalize('DPD30为2.9000％，变化0.10个百分点；DSC为1.310倍，得分100分。', self.bindings, ['M1', 'M15', 'D6'])
        self.assertEqual(result, 'DPD30为{{M1.value}}，变化{{M1.delta}}；DSC为{{M15.value}}，得分{{D6.score}}。')

    def test_invented_wrong_ref_and_unit_quantities_remain_rejectable(self):
        text = 'DPD30为3.7%，DSC为1.31×，本金2.9万元，另有3。'
        self.assertEqual(normalize(text, self.bindings, ['M1']), text)
        # A rounded value cannot be substituted for a more precise displayed value.
        self.assertEqual(normalize('利息1,234.57万元', self.bindings, ['S-base']), '利息1,234.57万元')

    def test_commas_and_negative_sign_are_preserved_semantically(self):
        text = '利息1234.567800万元，变化-69.1717万元，而正数69.1717万元无依据。'
        expected = '利息{{S-base.interest}}，变化{{S-base.delta}}，而正数69.1717万元无依据。'
        self.assertEqual(normalize(text, self.bindings, ['S-base']), expected)
        self.assertEqual(normalize('利息12345678元', self.bindings, ['S-base']), '利息12345678元')

    def test_existing_tokens_dates_and_source_filename_are_protected(self):
        text = '截至2026-08-31，依据{{M1.value}}和{{S-base.delta}}，文件资产3个月-2026-08-31.csv。'
        expected = '截至{{D11.as_of}}，依据{{M1.value}}和{{S-base.delta}}，文件资产3个月-2026-08-31.csv。'
        self.assertEqual(normalize(text, self.bindings, ['M1', 'S-base', 'D11', 'D1']), expected)
        self.assertEqual(normalize('截至2026-08-30。', self.bindings, ['D11']), '截至2026-08-30。')
        self.assertEqual(normalize('截至2026-08-31。', self.bindings, ['M1']), '截至2026-08-31。')
        self.assertEqual(normalize('{{M1.2.9%}}', self.bindings, ['M1']), '{{M1.2.9%}}')

    def test_no_chinese_numbers_bare_integer_or_comparison_normalization(self):
        text = '百分之三，三期，DPD30，Top10，编号100，DPD >= 3%，DPD≤2.9%。'
        self.assertEqual(normalize(text, self.bindings, ['M1', 'D6']), text)
        self.assertEqual(normalize('S-base-2.9%和M1.value', self.bindings, ['M1']), 'S-base-2.9%和M1.value')

    def test_matching_is_deterministic_and_cited_only(self):
        bindings = {'M2.value': {'ref': 'M2', 'text': '3%'}, 'M1.value': {'ref': 'M1', 'text': '3.0%'}}
        self.assertEqual(normalize('3%', bindings, ['M1', 'M2']), '{{M1.value}}')
        self.assertEqual(normalize('3%', bindings, ['M2']), '{{M2.value}}')
        self.assertEqual(normalize('3%', bindings, []), '3%')
        self.assertEqual(normalize('−3%', bindings, ['M1']), '−3%')
        self.assertEqual(normalize('3%%', bindings, ['M1']), '3%%')

    def test_invalid_types_empty_bindings_and_supported_units(self):
        self.assertIsNone(normalize(None, {}, []))
        self.assertEqual(normalize({'bad': 'type'}, {}, []), {'bad': 'type'})
        self.assertEqual(normalize('3%', {}, []), '3%')
        for unit in ('元', '万元', '个百分点', '倍', '×', '分', '期', '个月', '天', '项', '年'):
            bindings = {'D5.value': {'ref': 'D5', 'text': '2' + unit}}
            with self.subTest(unit=unit):
                self.assertEqual(normalize('数值为2.00' + unit + '。', bindings, ['D5']), '数值为{{D5.value}}。')


if __name__ == '__main__':
    unittest.main()
