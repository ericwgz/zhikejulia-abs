import base64
import copy
import io
import json
import math
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import abs_api as api
import abs_work as work
import abs_stress as stress
import abs_stress_calc as calc
import abs_stress_data as data
import abs_stress_sim as sim


class DataAndCalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.panels=data.parse_panel('demo.csv',data.csv_bytes(data.demo_rows()))[0]

    def test_csv_xlsx_roundtrip_and_24_indicators(self):
        xlsx=data.parse_panel('demo.xlsx',data.xlsx_bytes(data.demo_rows()))[0]
        self.assertEqual(xlsx,self.panels)
        self.assertEqual(sum(len(p) for p in xlsx.values()),540)
        expected=['green','yellow','red']
        for (pid,panel),color in zip(xlsx.items(),expected):
            a=calc.calculate(panel)
            self.assertEqual(len(a['metrics']),24);self.assertEqual(a['assessed'],24);self.assertEqual(a['status'],color)
            values={m['id']:m['value'] for m in a['metrics']}
            r=panel[-1]
            self.assertAlmostEqual(values['dpd'],r['dpd30_balance']/r['balance']*100)
            self.assertAlmostEqual(values['average'],r['balance']/r['loan_count'])
            self.assertAlmostEqual(values['wac'],r['balance_rate']/r['balance']*100)
            self.assertAlmostEqual(values['wal'],r['principal_time']/r['future_principal'])

    def test_annualization_uses_new_events_and_calendar_month(self):
        p=copy.deepcopy(self.panels['SIM-ABS-01'])
        for r in p:r.update(performing_open=1000,new_defaults=1,scheduled_principal=100,prepayments=9,dpd90_balance=0)
        values={m['id']:m['value'] for m in calc.calculate(p)['metrics']}
        self.assertAlmostEqual(values['cdr'],(1-.999**365)*100)
        self.assertAlmostEqual(values['cpr'],(1-.99**365)*100)

    def test_incomplete_month_and_missing_comparators_fail_closed(self):
        p=copy.deepcopy(self.panels['SIM-ABS-01'])[:-2]
        a=calc.calculate(p);metrics={m['id']:m for m in a['metrics']}
        self.assertIsNone(a['score']);self.assertEqual(metrics['cdr']['status'],'gray');self.assertEqual(metrics['dsc']['status'],'gray')
        p=self.panels['SIM-ABS-03'][-62:]
        residual=next(m for m in calc.calculate(p)['metrics'] if m['id']=='residual')
        self.assertEqual(residual['status'],'gray','two negative months do not prove a three-month rule')
        self.assertEqual(next(m for m in calc.calculate(self.panels['SIM-ABS-03'])['metrics'] if m['id']=='residual')['status'],'red')

    def test_zero_denominator_pd_and_duration_never_infinite(self):
        p=copy.deepcopy(self.panels['SIM-ABS-01']);p[-1].update(loan_count=0,pd_covered_balance=0,duration_pv=0)
        a=calc.calculate(p);self.assertIsNone(a['aggregates']['weighted_pd_12m']);self.assertIsNone(a['aggregates']['duration_years']);self.assertIsNone(a['score'])
        self.assertIsNone(calc.ratio(1,1e-320))

    def test_policy_and_threshold_strict_boundaries(self):
        p=copy.deepcopy(self.panels['SIM-ABS-01']);p[-1]['policy']='无新增政策，但原有政策今天生效'
        a=calc.calculate(p);self.assertEqual(a['metrics'][-1]['status'],'yellow')
        p[-1]['dpd30_balance']=p[-1]['balance']*.03
        m=calc.calculate(p)['metrics'][0];self.assertEqual(m['status'],'green')
        p[-1]['dpd30_balance']=p[-1]['balance']*.05001
        self.assertEqual(calc.calculate(p)['metrics'][0]['status'],'red')
        with self.assertRaises(data.DataError):calc.thresholds({'dpd':{'yellow':5,'red':3}},100)

    def test_bad_data_is_rejected_not_coerced(self):
        for text in ['产品编号,日期,资产池余额,手机号\np,2026-08-31,1,123',
                     'product_id,date,balance\np,2026-08-31,NaN',
                     'product_id,date,balance\np,2026-08-31,Infinity',
                     'product_id,date,balance\np,2026-08-31,1e-320',
                     'product_id,date,balance\np,2026-08-31,-1',
                     'product_id,date,balance\np,2026-08-31,1\np,2026-08-31,2',
                     'product_id,date,balance,balance\np,2026-08-31,1,1',
                     'product_id,date,balance,dpd30_balance,dpd90_balance\np,2026-08-31,10,1,2',
                     'product_id,date,balance,balance_pd,pd_covered_balance\np,2026-08-31,10,5,1']:
            with self.subTest(text=text),self.assertRaises(data.DataError):data.parse_panel('test.csv',text.encode())

    def test_archive_formula_entity_and_compression_bounds(self):
        attack='<!DOCTYPE x [<!ENTITY e "expanded">]><x>&e;</x>'
        for raw in [attack.encode(),('<?xml version="1.0" encoding="utf-16"?>'+attack).encode('utf-16')]:
            with self.assertRaises(data.DataError):data.xml(raw)
        raw=data.xlsx_bytes(data.demo_rows()[:2]);source=zipfile.ZipFile(io.BytesIO(raw));out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for name in source.namelist():
                item=source.read(name)
                if name=='xl/worksheets/sheet1.xml':item=item.replace(b'<c r="D2"><v>',b'<c r="D2"><f>1+1</f><v>')
                z.writestr(name,item)
        with self.assertRaises(data.DataError):data.parse_panel('f.xlsx',out.getvalue())
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('bomb',b'0'*8_000_001)
        with self.assertRaises(data.DataError):data.archive(out.getvalue())

    def test_scenario_ledgers_and_unmatured_principal(self):
        for p in self.panels.values():
            a=calc.calculate(p);result=sim.simulate(p[-1],a,{'months':12})
            for scenario in result['scenarios']:
                for m in scenario['months']:
                    self.assertTrue(all(abs(v)<.01 for v in m['ledger_errors'].values()))
                    self.assertTrue(all(m[k]>=-1e-8 for k in ('ending_cash','ending_reserve','performing_principal','pending_recoveries')))
                    self.assertAlmostEqual(m['principal_impairment'],sum(t['coverage_impairment'] for t in m['tranches']))
        p=self.panels['SIM-ABS-01'];r=sim.simulate(p[-1],calc.calculate(p),{'months':3})['scenarios'][0]
        self.assertGreater(r['tranches'][0]['balance'],0);self.assertEqual(r['tranches'][0]['end_due_shortfall'],0)

    def test_prepayment_is_principal_not_automatic_excess_income(self):
        p=self.panels['SIM-ABS-01'];s=sim.simulate(p[-1],calc.calculate(p))['scenarios'];base,early=s[0],s[2]
        self.assertGreater(early['months'][0]['prepayment_principal'],base['months'][0]['prepayment_principal'])
        self.assertLess(early['interest_income'],base['interest_income'])

    def test_acceleration_does_not_withhold_matured_junior_after_seniors_paid(self):
        p=self.panels['SIM-ABS-02']
        s=sim.simulate(p[-1],calc.calculate(p),{'months':12})['scenarios'][1]
        self.assertEqual(s['months'][-1]['tranches'][-1]['due_shortfall'],0)
        self.assertEqual(s['tranches'][-1]['balance'],0)

    def simple_sim(self,**changes):
        r={'balance':100,'dpd90_balance':0,'balance_term':12000,'reserve':0,'original_balance':100,'cumulative_additions':0,'cumulative_defaults':0,
           'a_balance':90,'b_balance':5,'sub_balance':5,'a_rate':0,'b_rate':0,'sub_rate':0,'a_maturity':120,'b_maturity':120,'sub_maturity':120}
        r.update(changes);m={'cdr':0,'cpr':0,'wac':0,'dpd':0};p=sim.parameters({'fee_pct':0,'reserve_target_pct':0,'default_accelerates':False,'months':3})
        return r,m,p

    def test_accelerated_matured_principal_can_draw_reserve(self):
        r,m,p=self.simple_sim(a_balance=100,b_balance=0,sub_balance=0,a_maturity=1,reserve=100)
        m['dpd']=10;s=sim.one_scenario(r,m,p,'base','test')
        self.assertEqual(s['months'][0]['tranches'][0]['due_shortfall'],0)
        self.assertGreater(s['months'][0]['reserve_drawn'],0)

    def test_subordinate_interest_does_not_impair_senior_principal(self):
        r,m,p=self.simple_sim(balance=96,balance_term=11520,sub_rate=.9,cumulative_defaults=11)
        s=sim.one_scenario(r,m,p,'base','test')
        self.assertEqual(s['tranches'][1]['max_impairment'],0);self.assertEqual(s['status'],'red')

    def test_recoveries_stay_out_of_cash_before_lag(self):
        r,m,p=self.simple_sim(dpd90_balance=10);p['recovery_pct']=100;p['recovery_lag']=3
        s=sim.one_scenario(r,m,p,'base','test')
        self.assertEqual(s['months'][0]['default_recovery'],0);self.assertEqual(s['months'][0]['pending_recoveries'],10)
        self.assertEqual(s['months'][2]['default_recovery'],10)
        self.assertIsNone(s['sub_breach'])


class Client:
    def __init__(self,base):self.base=base;self.cookie='';self.csrf=''
    def call(self,path,value=None,csrf=True,origin='https://zhikejulia.com'):
        headers={'Cookie':self.cookie,'Content-Type':'application/json','Origin':origin}
        if csrf:headers['X-CSRF-Token']=self.csrf
        req=urllib.request.Request(self.base+path,data=json.dumps(value).encode() if value is not None else None,headers=headers)
        try:r=urllib.request.urlopen(req,timeout=10)
        except urllib.error.HTTPError as e:r=e
        with r:
            if r.headers.get('Set-Cookie'):self.cookie=r.headers['Set-Cookie'].split(';')[0]
            raw=r.read();b=json.loads(raw) if 'json' in r.headers.get('Content-Type','') else raw
            if path=='session':self.csrf=b.get('csrf','')
            return r.status,b
    def demo(self):self.call('auth/demo',{});self.call('session')


def mock_report(context=None):
    def tokens(value):
        if isinstance(value,dict):
            if 'token' in value:yield value['token']
            for child in value.values():yield from tokens(child)
        elif isinstance(value,list):
            for child in value:yield from tokens(child)
    evidence={e['ref']:e for e in (context or {}).get('evidence',[])}
    sections=[]
    for key,title in stress.SECTIONS:
        refs=list((context or {}).get('section_refs',{}).get(key,['M1']))[:2]
        if key=='summary' and context:refs=['D6','D3']
        if key=='scenarios' and 'S-base' in evidence:refs=['S-base','S-default']
        token=next((token for ref in refs for token in tokens(evidence.get(ref,{}))), '')
        sections.append({'id':key,'analysis':title+'：本次计算依据显示'+token+'，应结合对应统计期间和确认的交易参数解释结果。该项观察需要通过上传记录核查，不能直接认定因果或实际发生法律事件。','evidence_refs':refs})
    return {'sections':sections,'actions':[
        {'priority':'P1','action':'复核本期逾期与回款台账','reason':'应核实逾期余额的统计区间与新增违约去重口径。','trigger':'出现逾期变化时，核对新增与存量记录。','evidence_refs':['M1']},
        {'priority':'P2','action':'补充资产池的历史分组台账','reason':'汇总记录不足以判断具体借款人行为，需要核对原始分组明细。','trigger':'核对发现统计口径不一致时补充资料。','evidence_refs':['M1']} ]}


class StressApiTests(unittest.TestCase):
    def setUp(self):
        self.old={k:getattr(api,k) for k in ('DATA_DIR','API_KEY','MODEL','URL','ALLOWED_ORIGINS','call_model')}
        self.tmp=tempfile.TemporaryDirectory();api.DATA_DIR=Path(self.tmp.name);api.ALLOWED_ORIGINS={'https://zhikejulia.com'}
        api.API_KEY='unit-test';api.MODEL='mock';api.URL='https://mock.invalid';work.RATE.clear();api.RECENT.clear();self.payloads=[]
        os.environ['ABS_WORK_SECURE_COOKIE']='false'
        def model(payload,**kwargs):
            self.payloads.append(payload)
            value=payload.get('messages',[{},{}])[1].get('content','')
            context=json.loads(value.split('\n',1)[1]) if value else None
            return json.dumps(mock_report(context),ensure_ascii=False)
        api.call_model=model
        self.server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base=f'http://127.0.0.1:{self.server.server_port}/api/abs/work/';self.client=Client(self.base);self.client.demo()
    def tearDown(self):
        self.server.shutdown();self.server.server_close()
        # Every test waits for its model jobs before disposing their isolated database.
        for k,v in self.old.items():setattr(api,k,v)
        self.tmp.cleanup()
    def dataset(self):
        code,b=self.client.call('stress/demo',{});self.assertEqual(code,201,b);return b['dataset']
    def run_report(self,ds):
        code,r=self.client.call('stress/run',{'dataset_id':ds['id'],'product_id':ds['products'][0]['id'],'assumptions_confirmed':True,'parameters':{'months':3}})
        self.assertEqual(code,201,r)
        for _ in range(100):
            code,r=self.client.call('stress/runs/'+r['id'])
            if r['ai']['status']!='pending':break
            time.sleep(.01)
        return r
    def test_upload_auth_csrf_origin_and_json_limits(self):
        anon=Client(self.base);self.assertEqual(anon.call('stress/demo',{})[0],401)
        self.assertEqual(self.client.call('stress/demo',{},csrf=False)[0],403)
        self.assertEqual(self.client.call('stress/demo',{},origin='https://evil.invalid')[0],403)
        self.assertEqual(self.client.call('stress/upload',{'filename':'a.csv','content':'%%%bad'})[0],400)
        self.assertEqual(self.client.call('stress/run',{'parameters':{'months':float('nan')}})[0],400)
        self.assertEqual(self.client.call('stress/upload',{'filename':'a.csv','content':base64.b64encode(b'x'*700001).decode()})[0],400)
    def test_frozen_run_real_schema_model_context_and_team_isolation(self):
        ds=self.dataset();r=self.run_report(ds);self.assertEqual(r['ai']['status'],'ready',r['ai']);self.assertEqual(len(r['ai']['report']['sections']),6)
        self.assertEqual(r['ai']['prompt_version'],'data-grounded-2.0');self.assertEqual(len(r['ai']['context_hash']),64)
        self.assertNotIn('{{',json.dumps(r['ai']['report']))
        self.assertEqual(r['assessment']['assessed'],24);self.assertEqual(len(r['simulation']['scenarios']),5)
        ctx=json.loads(self.payloads[-1]['messages'][1]['content'].split('\n',1)[1]);self.assertNotIn('source_evidence',ctx);self.assertNotIn('panel_json',ctx)
        reserve=next(m for m in r['assessment']['metrics'] if m['id']=='reserve')
        self.assertIn('红线 ≤0',stress.facts_for_model(r)[1][reserve['ref']])
        self.assertEqual(next(e for e in ctx['evidence'] if e['ref']==reserve['ref'])['signal'],'绿灯')
        b=Client(self.base);b.demo();self.assertEqual(b.call('stress/runs/'+r['id'])[0],404)
        self.assertEqual(b.call('stress/report/retry',{'run_id':r['id']})[0],404)
        self.assertEqual(b.call('stress/datasets/delete',{'dataset_id':ds['id']})[0],404)
        self.assertEqual(b.call('stress/run',{'dataset_id':ds['id'],'product_id':'SIM-ABS-01','assumptions_confirmed':True})[0],404)
        self.assertEqual(self.client.call('stress/datasets/delete',{'dataset_id':ds['id']})[0],200)
        self.assertEqual(self.client.call('stress/runs/'+r['id'])[0],404)
    def test_bad_model_preserves_results_and_retry(self):
        ds=self.dataset();good=api.call_model;api.call_model=lambda p,**kwargs:'{"sections":[]}'
        r=self.run_report(ds);self.assertEqual(r['ai']['status'],'failed');self.assertEqual(len(r['assessment']['metrics']),24)
        api.call_model=good;self.assertEqual(self.client.call('stress/report/retry',{'run_id':r['id']})[0],202)
        for _ in range(100):
            b=self.client.call('stress/runs/'+r['id'])[1]
            if b['ai']['status']!='pending':break
            time.sleep(.01)
        self.assertEqual(b['ai']['status'],'ready');self.assertEqual(b['input_hash'],r['input_hash'])
    def test_evidence_ids_and_contract_quote_validation(self):
        payload=stress.llm_payload(api,'JSON',{},model='qwen3-max')
        self.assertEqual(payload['model'],'qwen3-max');self.assertEqual(payload['response_format'],{'type':'json_object'});self.assertFalse(payload['enable_thinking'])
        bad={'sections':[{'id':k,'analysis':'有效长度的分析文本'*10,'evidence_refs':['M999']} for k,_ in stress.SECTIONS],'actions':[]}
        with self.assertRaises(ValueError):stress.validate_report(bad,{'M1'})
        self.assertEqual(stress.REF_ALIASES['parameters'],'A1')
        good=json.loads(api.call_model({}))
        good['sections'][0]['evidence_refs']=['parameters','synthetic','M1']
        normalized=stress.validate_report(good,{'M1','A1','D1'})
        self.assertEqual(normalized['sections'][0]['evidence_refs'],['A1','D1','M1'])
        good['sections'][0]['analysis']='DPD30逾期指标与M1证据应核对，前10%金额集中度可能放大共同冲击，PD12m覆盖仍需补充核验。'
        stress.validate_report(good,{'M1','A1','D1'})
        action_trigger=good['actions'][0]['trigger'];good['actions'][0]['trigger']="S-default.reserve_used === true"
        with self.assertRaisesRegex(ValueError,'Report text'):stress.validate_report(good,{'M1','A1','D1'})
        good['actions'][0]['trigger']=action_trigger
        good['sections'][0]['analysis']='本期CPR上升63.5%，但未超过50%的黄灯阈值。'+('需要核实数据依据。'*8)
        with self.assertRaisesRegex(ValueError,'numeric claims'):stress.validate_report(good,{'M1','A1','D1'})
        good['sections'][0]['analysis']='早偿率环比激增六成以上，基础恶化第六月触发加速。'+('需要核实数据依据。'*8)
        with self.assertRaisesRegex(ValueError,'numeric claims'):stress.validate_report(good,{'M1','A1','D1'})
        excerpt='本合约明确规定：DPD30逾期率超过3%为关注，超过5%为严重预警。'
        api.call_model=lambda p,**kwargs:json.dumps({'thresholds':[{'metric_id':'dpd','yellow':3,'red':5,'quote':'DPD30逾期率超过3%为关注，超过5%为严重预警。'}],'notes':[]},ensure_ascii=False)
        result=stress.parse_contract(api,'test','clause.txt',excerpt.encode());self.assertTrue(result['requires_confirmation']);self.assertEqual(result['thresholds']['dpd']['red'],5)
        api.call_model=lambda p,**kwargs:json.dumps({'thresholds':[{'metric_id':'dpd','yellow':3,'red':5,'quote_refs':['C1']}],'notes':[]})
        self.assertEqual(stress.parse_contract(api,'test','clause.txt',excerpt.encode())['thresholds']['dpd']['quote'],excerpt)
        api.call_model=lambda p,**kwargs:json.dumps({'thresholds':[{'metric_id':'dpd','yellow':3,'red':5,'quote_refs':['C999']}],'notes':[]})
        with self.assertRaises(ValueError):stress.parse_contract(api,'test','clause.txt',excerpt.encode())
        api.call_model=lambda p,**kwargs:json.dumps({'thresholds':[{'metric_id':'dpd','yellow':3,'red':5,'quote':'这是伪造的合同条款'}],'notes':[]},ensure_ascii=False)
        with self.assertRaises(ValueError):stress.parse_contract(api,'test','clause.txt',excerpt.encode())
    def test_csv_xlsx_download_upload_and_partial_data(self):
        for suffix in ('csv','xlsx'):
            code,raw=self.client.call('stress/sample.'+suffix);self.assertEqual(code,200)
            code,b=self.client.call('stress/upload',{'filename':'sample.'+suffix,'content':base64.b64encode(raw).decode()});self.assertEqual(code,201,b)
            self.assertEqual(len(b['dataset']['products']),3);self.assertFalse(b['dataset']['synthetic'])
        raw='product_id,date,balance\np,2026-08-31,100'.encode()
        code,b=self.client.call('stress/upload',{'filename':'partial.csv','content':base64.b64encode(raw).decode()});self.assertEqual(code,201,b)
        r=self.run_report(b['dataset']);self.assertIsNone(r['assessment']['score']);self.assertFalse(r['simulation']['ready'])


if __name__=='__main__':unittest.main()
