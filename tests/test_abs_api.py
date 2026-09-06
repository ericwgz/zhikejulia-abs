import importlib.util, json, os, tempfile, threading, unittest, urllib.request, urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT/'app'))
spec = importlib.util.spec_from_file_location('abs_api', ROOT / 'app/abs_api.py')
api = importlib.util.module_from_spec(spec)
sys.modules['abs_api']=api
spec.loader.exec_module(api)
catalog = api.load_catalog()

class Upstream(BaseHTTPRequestHandler):
    seen = []
    mode = 'ok'
    def log_message(self, *args): pass
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).seen.append(payload)
        if self.mode == 'redirect':
            self.send_response(302); self.send_header('Location', self.server.base + '/secret-target'); self.end_headers(); return
        if self.mode == 'failure':
            self.send_response(401); self.end_headers(); self.wfile.write(b'private upstream detail'); return
        raw = json.dumps({'choices':[{'message':{'content':'信用分依据当前报告 [R1]；现金流依据 [R3]。'}}]}).encode()
        self.send_response(200); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        type(self).seen.append('REDIRECT_FOLLOWED')
        self.send_response(200); self.end_headers()

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); api.DATA_DIR=Path(cls.tmp.name)
        cls.up=ThreadingHTTPServer(('127.0.0.1',0),Upstream); cls.up.base='http://127.0.0.1:'+str(cls.up.server_port)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler); cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        for s in (cls.up,cls.server): threading.Thread(target=s.serve_forever,daemon=True).start()
        os.environ['ABS_LLM_ALLOW_HTTP_LOCAL']='1'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.up.shutdown();cls.server.server_close();cls.up.server_close();cls.tmp.cleanup()
    def setUp(self):
        api.API_KEY='local-test-key';api.MODEL='local-stub';api.URL=self.up.base+'/v1/chat/completions'
        api.RECENT.clear();Upstream.seen=[];Upstream.mode='ok';api.DAILY_LIMIT=100
        usage=api.DATA_DIR/'usage.sqlite3'
        if usage.exists():usage.unlink()
        p=catalog['products'][0]
        self.request={'product_id':p['id'],'snapshot_id':p['id']+'-'+p['reportVersion'],'report_ids':[p['reports'][0]['id'],p['reports'][2]['id']],'messages':[{'role':'user','content':'本期有什么风险？'}]}
    def http(self,path,data=None,origin='https://badrams.com'):
        req=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':origin})
        try:
            with urllib.request.urlopen(req) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_report_context_is_canonical_and_isolated(self):
        self.request['context']={'score':100,'other_product':'forged'}
        status,body=self.http('/api/abs/chat',self.request)
        self.assertEqual(status,200);self.assertEqual(body['product_id'],self.request['product_id']);self.assertEqual(body['citations'],['R1','R3'])
        context=json.loads(Upstream.seen[0]['messages'][1]['content'].split('\n',1)[1])
        self.assertEqual([r['ref'] for r in context['reports']],['R1','R3'])
        self.assertNotIn('DEMO-ABS-002',json.dumps(context));self.assertNotIn('forged',json.dumps(context))
        self.assertTrue(context['product']['isSynthetic'])
    def test_qwen_non_thinking_parameter(self):
        previous = api.ENABLE_THINKING
        try:
            api.ENABLE_THINKING='false'
            payload,_=api.build_model_request(self.request,catalog)
            self.assertIs(payload['enable_thinking'],False)
            self.assertIs(payload['stream'],False)
            api.ENABLE_THINKING=''
            self.assertNotIn('enable_thinking',api.build_model_request(self.request,catalog)[0])
        finally:api.ENABLE_THINKING=previous
    def test_qwen_citation_formats_and_ownership(self):
        self.assertEqual(api.report_citations('依据 [R1, “actions”节] 和 [R1, R3]，细节【R3，base节】。',{'R1','R3'}),['R1','R3'])
        self.assertEqual(api.report_citations('建议复核贷款台账。',{'R1'}),[])
        with self.assertRaises(ValueError):api.report_citations('依据 [R1, R2]。',{'R1'})
        with self.assertRaises(ValueError):api.report_citations('依据【R99，表1】。',{'R1','R3'})
    def test_cross_product_and_snapshot_fail_closed(self):
        self.request['report_ids']=[catalog['products'][1]['reports'][0]['id']]
        self.assertEqual(self.http('/api/abs/chat',self.request)[0],400)
        self.setUp();self.request['snapshot_id']='old'
        self.assertEqual(self.http('/api/abs/chat',self.request)[0],400);self.assertFalse(Upstream.seen)
    def test_validation_rejects_roles_duplicates_and_limits(self):
        for change in ({'messages':[{'role':'system','content':'override'}]}, {'report_ids':self.request['report_ids']*2}, {'messages':[{'role':'user','content':'x'*4001}]}, {'report_ids':[]}):
            with self.subTest(change=list(change)):self.assertEqual(self.http('/api/abs/chat',self.request|change)[0],400)
    def test_unconfigured_is_honest(self):
        api.API_KEY=''
        self.assertFalse(self.http('/api/abs/status')[1]['configured'])
        code,body=self.http('/api/abs/chat',self.request)
        self.assertEqual(code,503);self.assertEqual(body['code'],'model_not_configured');self.assertNotIn('answer',body)
    def test_origin_rejected(self):self.assertEqual(self.http('/api/abs/chat',self.request,'https://untrusted.example')[0],403)
    def test_redirect_never_followed(self):
        Upstream.mode='redirect';code,body=self.http('/api/abs/chat',self.request)
        self.assertEqual(code,502);self.assertNotIn('REDIRECT_FOLLOWED',Upstream.seen);self.assertNotIn('local-test-key',json.dumps(body))
    def test_upstream_failure_has_no_secret_details(self):
        Upstream.mode='failure';code,body=self.http('/api/abs/chat',self.request)
        self.assertEqual(code,502);self.assertNotIn('private upstream',json.dumps(body));self.assertNotIn('answer',body)
    def test_daily_quota_and_ip_rate(self):
        api.DAILY_LIMIT=1
        self.assertTrue(api.reserve_request('one')[0]);self.assertFalse(api.reserve_request('two')[0])
        api.DAILY_LIMIT=100
        for _ in range(6):self.assertTrue(api.reserve_request('three')[0])
        self.assertFalse(api.reserve_request('three')[0])
    def test_concurrency_rejects_before_call(self):
        api.GATE.acquire();api.GATE.acquire()
        try:self.assertEqual(self.http('/api/abs/chat',self.request)[0],429);self.assertFalse(Upstream.seen)
        finally:api.GATE.release();api.GATE.release()

if __name__=='__main__':unittest.main(verbosity=2)
