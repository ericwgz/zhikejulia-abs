import json, os, sys, tempfile, threading, unittest, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import abs_api as api
import abs_work as work
from http.server import ThreadingHTTPServer
os.environ['ABS_WORK_SECURE_COOKIE']='false'

class Client:
    def __init__(self,base):self.base=base;self.cookie='';self.csrf=''
    def call(self,path,data=None,csrf=True):
        headers={'Cookie':self.cookie,'Content-Type':'application/json','Origin':'https://zhikejulia.com'}
        if csrf:headers['X-CSRF-Token']=self.csrf
        req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=headers)
        try:r=urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:r=e
        with r:
            if r.headers.get('Set-Cookie'):self.cookie=r.headers['Set-Cookie'].split(';')[0]
            body=json.load(r)
            if path=='session' and body.get('csrf'):self.csrf=body['csrf']
            return r.status,body
    def demo(self):
        assert self.call('auth/demo',{})[0]==201
        return self.call('session')[1]

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();api.DATA_DIR=Path(cls.tmp.name);api.ALLOWED_ORIGINS={'https://zhikejulia.com'}
        api.API_KEY='test-key';api.MODEL='test';api.URL='https://test.invalid';api.call_model=lambda payload:json.dumps({'summary':'请复核当前指标口径。','hypotheses':['可能为观察期口径变化，需核实。'],'actions':['核对台账。','核对观察日。','记录复核结果。']},ensure_ascii=False)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start();cls.base='http://127.0.0.1:'+str(cls.server.server_port)+'/api/abs/work/'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
    def setUp(self):work.RATE.clear();api.RECENT.clear();self.a=Client(self.base);self.s=self.a.demo()
    def create(self):
        code,body=self.a.call('tickets',{'product_id':'DEMO-ABS-004','metric_id':'coverage','snapshot_id':'DEMO-ABS-004-20260831-v2'})
        self.assertEqual(code,201,body);self.assertEqual(body['ticket']['ai']['status'],'ready');return body['ticket']
    def test_full_followup_cc_and_reviewer(self):
        t=self.create();owner=next(m for m in self.s['members'] if m['department']=='cash');cc=next(m for m in self.s['members'] if m['department']=='pool')
        code,body=self.a.call('tickets/'+t['id']+'/assign',{'version':1,'owner_id':owner['id'],'cc_ids':[cc['id']],'include_manager':True,'priority':'P0','due_date':'2026-09-30'})
        self.assertEqual(code,200,body);t=body['ticket'];self.assertIn(self.s['user']['id'],t['cc_ids']);self.assertEqual(t['reviewer_id'],self.s['user']['id']);self.assertEqual(len(t['cc_ids']),2)
        self.a.call('auth/switch',{'member_id':owner['id']});self.a.call('session');self.assertGreater(len(self.a.call('notifications')[1]['notifications']),0)
        code,body=self.a.call('tickets/'+t['id']+'/status',{'version':t['version'],'status':'in_progress','comment':'已开始核查台账。'});self.assertEqual(code,200);t=body['ticket']
        code,body=self.a.call('tickets/'+t['id']+'/status',{'version':t['version'],'status':'review','comment':'已完成台账复核，提交领导确认。'});self.assertEqual(code,200);t=body['ticket']
        self.assertEqual(self.a.call('tickets/'+t['id']+'/status',{'version':t['version'],'status':'closed','comment':'自己关闭。','resolution':'风险已缓释'})[0],403)
        self.a.call('auth/switch',{'member_id':self.s['user']['id']});self.a.call('session')
        code,body=self.a.call('tickets/'+t['id']+'/status',{'version':t['version'],'status':'closed','comment':'复核证据充分，继续观察下期。','resolution':'已确认并持续跟踪'});self.assertEqual(code,200);self.assertEqual(body['ticket']['source']['content_hash'],t['source']['content_hash']);self.assertEqual(body['ticket']['status'],'closed')
        duplicate=self.a.call('tickets',{'product_id':t['product_id'],'metric_id':t['metric_id'],'snapshot_id':t['snapshot_id']});self.assertEqual(duplicate[0],200);self.assertTrue(duplicate[1]['existing']);self.assertEqual(duplicate[1]['ticket']['id'],t['id'])
    def test_team_isolation_csrf_and_revision(self):
        t=self.create();b=Client(self.base);s2=b.demo()
        self.assertEqual(b.call('tickets/'+t['id'])[0],404)
        self.assertEqual(len(b.call('tickets')[1]['tickets']),0)
        self.assertEqual(self.a.call('tickets/'+t['id']+'/comment',{'content':'跨站请求'},csrf=False)[0],403)
        self.assertEqual(self.a.call('tickets/'+t['id']+'/assign',{'version':1,'owner_id':s2['user']['id'],'cc_ids':[]})[0],400)
        self.assertEqual(self.a.call('tickets/'+t['id']+'/assign',{'version':0,'owner_id':self.s['user']['id'],'cc_ids':[]})[0],409)
        unauth=Client(self.base);self.assertEqual(unauth.call('tickets')[0],401)
    def test_fixed_anomalies_and_snapshot(self):
        c=api.load_catalog()
        self.assertEqual([len(work.anomalies(c,p['id'])[1]) for p in c['products']],[5,5,2,12,6,1])
        with self.assertRaises(work.WorkError):work.source_snapshot(c,'DEMO-ABS-005','reserve','DEMO-ABS-005-20260831-v2')
        with self.assertRaises(work.WorkError):work.source_snapshot(c,'DEMO-ABS-004','coverage','old')
        s=work.source_snapshot(c,'DEMO-ABS-004','loss','DEMO-ABS-004-20260831-v2');self.assertTrue(s['alert']['forced']);self.assertEqual(s['alert']['signal'],'red')
    def test_real_team_invite_single_use(self):
        a=Client(self.base);email='owner-'+work.uid()+'@example.org'
        code,body=a.call('auth/register',{'name':'栀可 Julia','workspace_name':'测试协作团队','email':email,'password':'a-secure-test-password'});self.assertEqual(code,201,body);s=a.call('session')[1]
        code,body=a.call('team',{'name':'测试同事','email':'colleague-'+work.uid()+'@example.org','department':'loan','manager_id':s['user']['id']});self.assertEqual(code,201,body)
        b=Client(self.base);invite=body['invite_token'];self.assertEqual(b.call('auth/invite',{'token':invite,'password':'colleague-password'})[0],200)
        self.assertEqual(b.call('session')[1]['workspace']['id'],s['workspace']['id']);self.assertEqual(b.call('auth/invite',{'token':invite,'password':'colleague-password'})[0],400)
        self.assertEqual(b.call('auth/switch',{'member_id':s['user']['id']})[0],403)
    def test_ai_failure_keeps_ticket(self):
        old=api.API_KEY;api.API_KEY=''
        try:
            code,body=self.a.call('tickets',{'product_id':'DEMO-ABS-001','metric_id':'dpd','snapshot_id':'DEMO-ABS-001-20260831-v2'});self.assertEqual(code,201,body);self.assertEqual(body['ticket']['ai']['status'],'failed');self.assertEqual(body['ticket']['source']['metric']['value'],2.65)
        finally:api.API_KEY=old

    def test_demo_reuses_existing_workspace(self):
        code,body=self.a.call('auth/demo',{})
        self.assertEqual(code,200);self.assertTrue(body['existing'])
        self.assertEqual(self.a.call('session')[1]['workspace']['id'],self.s['workspace']['id'])

    def test_ai_interrupted_retry_and_current_recipients(self):
        t=self.create();owner=next(m for m in self.s['members'] if m['department']=='cash')
        with work.db(api) as conn:
            conn.execute('UPDATE tickets SET ai_json=? WHERE id=?',(work.dumps({'status':'pending','started_at':'2020-01-01T00:00:00+00:00','attempt_id':'old'}),t['id']))
        self.assertEqual(self.a.call('tickets/'+t['id'])[1]['ticket']['ai']['status'],'failed')
        original=api.call_model
        def reassign_during_model(payload):
            with work.db(api) as conn:conn.execute('UPDATE tickets SET owner_id=? WHERE id=?',(owner['id'],t['id']))
            return original(payload)
        api.call_model=reassign_during_model
        try:
            code,body=self.a.call('tickets/'+t['id']+'/ai',{})
            self.assertEqual(code,200,body);self.assertEqual(body['ticket']['ai']['status'],'ready')
            with work.db(api) as conn:
                notice=conn.execute('SELECT count(*) FROM notifications n JOIN events e ON e.id=n.event_id WHERE n.member_id=? AND e.kind=?',(owner['id'],'ai')).fetchone()[0]
            self.assertEqual(notice,1)
        finally:api.call_model=original

    def test_old_ai_attempt_cannot_overwrite_newer_attempt(self):
        t=self.create();original=api.call_model
        def replace_attempt(payload):
            with work.db(api) as conn:
                conn.execute('UPDATE tickets SET ai_json=? WHERE id=?',(work.dumps({'status':'pending','started_at':work.now(),'attempt_id':'newer-attempt'}),t['id']))
            return original(payload)
        api.call_model=replace_attempt
        try:
            code,body=self.a.call('tickets/'+t['id']+'/ai',{})
            self.assertEqual(code,200,body);self.assertEqual(body['ticket']['ai']['attempt_id'],'newer-attempt');self.assertEqual(body['ticket']['ai']['status'],'pending')
            self.assertEqual(self.a.call('tickets/'+t['id']+'/ai',{})[0],409)
        finally:api.call_model=original

if __name__=='__main__':unittest.main(verbosity=2)
