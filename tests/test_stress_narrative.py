import copy
import unittest
from unittest.mock import patch

import test_stress as base
import test_stress_report_context as context_tests


class GroundedNarrativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        panels=base.data.parse_panel('demo.csv',base.data.csv_bytes(base.data.demo_rows()))[0]
        cls.result=context_tests.QuantitativeReportContextTests().result(panels['SIM-ABS-01'],parameters={'months':12})
        cls.context,cls.bindings=base.stress.reporting.build_context(cls.result)
        cls.refs={e['ref'] for e in cls.context['evidence']}

    def validate(self,report):
        return base.stress.validate_report(report,self.refs,self.bindings,self.context['section_refs'])

    def test_numeric_values_are_bound_to_the_cited_metric(self):
        report=base.mock_report(self.context)
        report['sections'][1].update(analysis='本期逾期率为{{M1.value}}，此前为{{M1.previous}}，距关注线还有{{M1.yellow_margin}}。在判断风险程度时需要结合这一实际缓冲，优先核对账龄明细，不直接把上升等同于触发违约。',evidence_refs=['M1'])
        result=self.validate(report)
        prose=result['sections'][1]['analysis']
        self.assertIn(self.bindings['M1.value']['text'],prose)
        self.assertIn(self.bindings['M1.yellow_margin']['text'],prose)
        self.assertNotIn('{{',prose)
        copied=copy.deepcopy(report)
        copied['sections'][1]['analysis']=copied['sections'][1]['analysis'].replace('{{M1.value}}',self.bindings['M1.value']['text'])
        self.assertEqual(self.validate(copied)['sections'][1]['analysis'],prose)
        rendered=base.stress.narrative.render_bound_text('已评估{{D3.assessed}}项；DPD为{{M1.value}}%。',self.bindings,['D3','M1'])
        self.assertIn('24项',rendered)
        self.assertNotIn('项项',rendered)
        self.assertNotIn('%%',rendered)
        directional=base.stress.narrative.render_bound_text('较上期下降{{M1.delta}}。',self.bindings,['M1'])
        self.assertEqual(directional,'较上期变化为'+self.bindings['M1.delta']['text']+'。')
        report['sections'][3]['analysis']+='本次共模拟五种情景。'
        self.validate(report)
        report['sections'][3]['analysis']=report['sections'][3]['analysis'].replace('五种','四种')
        with self.assertRaisesRegex(ValueError,'numeric claims'):self.validate(report)
        for replacement in ('{{M999.value}}','{{M14.value}}','3.7%','百分之三','三点五%','五十九分','三期'):
            bad=copy.deepcopy(report);bad['sections'][1]['analysis']=bad['sections'][1]['analysis'].replace('{{M1.value}}',replacement)
            with self.subTest(replacement=replacement),self.assertRaises(ValueError):self.validate(bad)

    def test_generic_repeated_irrelevant_and_uncompared_prose_is_rejected(self):
        good=base.mock_report(self.context)
        for field in ('repeat','irrelevant','no_values','no_comparison','same_action'):
            bad=copy.deepcopy(good)
            if field=='repeat':bad['sections'][1]=dict(bad['sections'][0],id='quality')
            elif field=='irrelevant':bad['sections'][2].update(evidence_refs=['M1'],analysis=bad['sections'][1]['analysis'])
            elif field=='no_values':bad['sections'][1]['analysis']='本次应密切关注基础资产变化情况，同时结合当前交易结构评估潜在传导路径，建议管理人持续核对数据口径并保持沟通。'
            elif field=='no_comparison':bad['sections'][3]['evidence_refs']=['S-base']
            else:bad['actions'][1]['action']=bad['actions'][0]['action']
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(bad)

    def test_scenario_count_matches_global_simulation_and_never_rewrites_wrong_count(self):
        refs={'S-base','S-deterioration','S-prepayment','S-default','S-macro'}
        for count in ('五种','5种','五个','5个'):
            with self.subTest(valid=count):
                self.assertFalse(base.stress.narrative.numeric_parts('本次模拟涵盖'+count+'情景。',refs)[1])
        for count in ('四种','4种','四个','4个','十五种','55个'):
            with self.subTest(invalid=count):
                cleaned,violations=base.stress.narrative.numeric_parts('本次模拟涵盖'+count+'情景。',refs)
                self.assertTrue(violations)
                self.assertIn(count+'情景',cleaned)
        self.assertTrue(base.stress.narrative.numeric_parts('本次包含五个情景。',{'S-base'})[1])
        self.assertFalse(base.stress.narrative.numeric_parts('第一，核对输入。第二，检查模型假设。',refs)[1])

    def test_missing_score_and_absent_event_are_not_replaced_with_zero(self):
        context,bindings=base.stress.reporting.build_context(context_tests.QuantitativeReportContextTests().result([{'product_id':'p','date':'2026-08-31','balance':100}]))
        report=base.mock_report(context);refs={e['ref'] for e in context['evidence']}
        result=base.stress.validate_report(report,refs,bindings,context['section_refs'])
        self.assertNotIn('{{',str(result))
        report['sections'][0]['analysis']+='整体信用表现尚处绿灯。'
        with self.assertRaisesRegex(ValueError,'incomplete score'):base.stress.validate_report(report,refs,bindings,context['section_refs'])
        report['sections'][0]['analysis']=report['sections'][0]['analysis'].replace('整体信用表现尚处绿灯。','无法得出总体低风险结论。')
        report['sections'][0]['analysis']+='内部总分为{{D6.score}}。'
        rendered=base.stress.validate_report(report,refs,bindings,context['section_refs'])
        self.assertIn('待评估（未形成总分）',rendered['sections'][0]['analysis'])
        self.assertNotIn('0分',rendered['sections'][0]['analysis'])
        report['sections'][0]['analysis']+='内部总分为0分。'
        with self.assertRaisesRegex(ValueError,'numeric claims'):base.stress.validate_report(report,refs,bindings,context['section_refs'])

    def test_unavailable_scenarios_and_events_accept_explicit_nonnumeric_missing_data_explanation(self):
        context,bindings=base.stress.reporting.build_context(context_tests.QuantitativeReportContextTests().result(
            [{'product_id':'p','date':'2026-08-31','balance':100}]))
        refs={e['ref'] for e in context['evidence']}
        report=base.mock_report(context)
        report['sections'][3].update(
            analysis='本次缺少现金流与储备账户资料，无法形成可用的压力情景结果。需补齐汇总口径和账户流水后再运行，当前不比较各档证券的受压程度或最不利情景。',
            evidence_refs=['D7','D3','D12'])
        report['sections'][4].update(
            analysis='由于关键输入尚未补齐，本次无法推演瀑布状态切换或到期欠付路径。应先核对合同和账户资料，待数据完备后重新模拟；不能将无法预测解释为实际交易安全。',
            evidence_refs=['D7','D3','D12'])
        # D3 has a numeric assessed-count binding, but a missing-data explanation
        # must not be forced to insert that unrelated number to pass validation.
        self.assertIn('D3.assessed',bindings)
        rendered=base.stress.validate_report(report,refs,bindings,context['section_refs'])
        self.assertEqual(rendered['sections'][3]['analysis'],report['sections'][3]['analysis'])
        self.assertEqual(rendered['sections'][4]['analysis'],report['sections'][4]['analysis'])

    def test_missing_score_negation_is_clause_scoped_not_a_short_character_window(self):
        context,bindings=base.stress.reporting.build_context(context_tests.QuantitativeReportContextTests().result(
            [{'product_id':'p','date':'2026-08-31','balance':100}]))
        refs={e['ref'] for e in context['evidence']}
        report=base.mock_report(context)
        report['sections'][0]['analysis']+='无法依据已评估指标判定总体为低风险。'
        rendered=base.stress.validate_report(report,refs,bindings,context['section_refs'])
        self.assertIn('无法依据已评估指标判定总体为低风险。',rendered['sections'][0]['analysis'])
        # The preceding sentence's negation must not excuse an affirmative claim.
        report['sections'][0]['analysis']+='本次总体风险低，整体为绿灯。'
        with self.assertRaisesRegex(ValueError,'incomplete score'):
            base.stress.validate_report(report,refs,bindings,context['section_refs'])

    def test_one_bounded_format_correction_preserves_context(self):
        good=base.mock_report(self.context)
        bad=copy.deepcopy(good);bad['sections'][0]['analysis']+='当前总分五十九分。'
        import json
        with patch.object(base.stress,'model_call',side_effect=[json.dumps(bad),json.dumps(good)]) as call:
            report,model,corrections=base.stress.generate_report(base.api,'qa',self.context,self.bindings)
        self.assertEqual(corrections,1)
        self.assertEqual(len(report['sections']),6)
        self.assertEqual(call.call_count,2)
        self.assertLessEqual(call.call_args.kwargs['timeout'],120)
        self.assertIn(base.stress.dumps(self.context),call.call_args.args[2]['messages'][1]['content'])
        with patch.object(base.stress,'model_call',return_value=json.dumps(bad)) as call:
            with self.assertRaisesRegex(ValueError,'numeric claims'):
                base.stress.generate_report(base.api,'qa',self.context,self.bindings)
        self.assertEqual(call.call_count,3)

    def test_known_binding_citation_is_attached_without_another_model_call(self):
        import json
        report=base.mock_report(self.context)
        report['sections'][0]['analysis']+='数据截至{{D11.as_of}}。'
        report['sections'][0]['evidence_refs']=[ref for ref in report['sections'][0]['evidence_refs'] if ref!='D11']
        with patch.object(base.stress,'model_call',return_value=json.dumps(report)) as call:
            rendered,_,corrections=base.stress.generate_report(base.api,'qa',self.context,self.bindings)
        self.assertIn('D11',rendered['sections'][0]['evidence_refs'])
        self.assertEqual(corrections,0)
        self.assertEqual(call.call_count,1)

    def test_trigger_operators_and_unavailable_simulation_remain_grounded(self):
        report=base.mock_report(self.context)
        report['actions'][0]['trigger']='若逾期率达到{{M1.yellow}}，则核对账龄明细。'
        with self.assertRaisesRegex(ValueError,'trigger condition'):self.validate(report)
        report['actions'][0]['trigger']='若{{M1.yellow_condition}}，则核对账龄明细。'
        self.assertIn('大于3%',self.validate(report)['actions'][0]['trigger'])
        report['sections'][2]['analysis']+='循环购买机制正常运行。'
        with self.assertRaisesRegex(ValueError,'unsupported inference'):self.validate(report)
        report['sections'][2]['analysis']=report['sections'][2]['analysis'].replace('循环购买机制正常运行。','不能证明循环购买机制正常运行。')
        self.validate(report)
        context,bindings=base.stress.reporting.build_context(context_tests.QuantitativeReportContextTests().result([{'product_id':'p','date':'2026-08-31','balance':100}]))
        report=base.mock_report(context)
        report['sections'][3]['analysis']+='预测期间未出现到期缺口。'
        with self.assertRaisesRegex(ValueError,'unavailable simulation'):
            base.stress.validate_report(report,{e['ref'] for e in context['evidence']},bindings,context['section_refs'])
        report['sections'][3]['analysis']=report['sections'][3]['analysis'].replace('预测期间未出现到期缺口。','没有模拟结果不代表未出现到期缺口。')
        base.stress.validate_report(report,{e['ref'] for e in context['evidence']},bindings,context['section_refs'])


if __name__=='__main__':unittest.main()
