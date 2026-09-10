import base64
import copy
import json
import threading
import time
import unittest
from unittest.mock import patch

import test_stress as base

api, stress, data = base.api, base.stress, base.data
pdf = stress.pdf
RAW = b'%PDF-1.7\n1 0 obj <</Type /Catalog>> endobj\n%%EOF\n'


def answer():
    return {'complete': True, 'thresholds': [
        {'metric_id': 'dpd', 'yellow': 3, 'red': 5, 'page': 1,
         'quote': 'DPD30逾期率超过3%为黄色关注预警，超过5%为红色严重预警。'},
        {'metric_id': 'oc', 'yellow': 105, 'red': 102, 'page': 2,
         'quote': '超额抵押率低于105%为黄色关注预警，低于102%为红色严重预警。'}], 'notes': []}


class PdfContractTests(unittest.TestCase):
    def setUp(self):
        base.StressApiTests.setUp(self)
        self.old_report = stress.REPORT_MODEL
        stress.REPORT_MODEL = 'qwen3.8-max'
        self.unblock = threading.Event()
        with pdf.LOCK: pdf.JOBS.clear()

    def tearDown(self):
        self.unblock.set()
        for _ in range(200):
            with pdf.LOCK: pending = any(j['status'] == 'pending' for j in pdf.JOBS.values())
            if not pending: break
            time.sleep(.01)
        stress.REPORT_MODEL = self.old_report
        base.StressApiTests.tearDown(self)
        with pdf.LOCK: pdf.JOBS.clear()

    def upload(self, raw=RAW, name='synthetic.pdf', client=None, **kwargs):
        return (client or self.client).call('stress/contract', {'filename': name, 'content': base64.b64encode(raw).decode()}, **kwargs)

    def wait_job(self, identity):
        for _ in range(200):
            code, job = self.client.call('stress/contracts/' + identity)
            self.assertEqual(code, 200, job)
            if job['status'] != 'pending': return job
            time.sleep(.01)
        self.fail('PDF worker did not finish')

    def test_async_pdf_native_payload_citations_and_team_isolation(self):
        seen = []
        def model(payload, **kwargs):
            seen.append((payload, kwargs))
            self.unblock.wait(5)
            return json.dumps(answer(), ensure_ascii=False)
        api.call_model = model
        code, pending = self.upload()
        self.assertEqual(code, 202, pending)
        self.assertEqual(pending['status'], 'pending')
        self.assertEqual(self.client.call('stress/contracts/' + pending['id'])[1]['status'], 'pending')
        other = base.Client(self.base); other.demo()
        self.assertEqual(other.call('stress/contracts/' + pending['id'])[0], 404)
        self.assertEqual(base.Client(self.base).call('stress/contracts/' + pending['id'])[0], 401)
        self.unblock.set()
        job = self.wait_job(pending['id']); self.assertEqual(job['status'], 'ready', job)
        result = job['result']
        self.assertTrue(result['requires_confirmation']); self.assertEqual(result['input_type'], 'pdf')
        self.assertEqual(result['model'], 'qwen3.8-max'); self.assertEqual(result['citations']['oc']['page'], 2)
        self.assertEqual(result['citations']['dpd']['kind'], 'ai_recognized')
        self.assertIn('AI识别', result['thresholds']['dpd']['source'])
        self.assertIn('待人工确认', result['thresholds']['dpd']['source'])
        base.calc.thresholds(result['thresholds'], 1)
        payload, kwargs = seen[0]
        attachment = payload['messages'][1]['content'][0]
        self.assertEqual(attachment['type'], 'file')
        self.assertEqual(attachment['file']['filename'], 'contract.pdf')
        self.assertEqual(attachment['file']['file_data'], 'data:application/pdf;base64,' + base64.b64encode(RAW).decode())
        self.assertEqual(payload['response_format']['type'], 'json_schema')
        self.assertTrue(payload['response_format']['json_schema']['strict'])
        props = payload['response_format']['json_schema']['schema']['properties']['thresholds']['items']['properties']
        self.assertEqual(props['yellow']['type'], ['number', 'null'])
        self.assertEqual(set(props['metric_id']['enum']), base.calc.IDS)
        self.assertFalse(payload['enable_thinking']); self.assertFalse(payload['stream'])
        self.assertEqual(kwargs['timeout'], 300)
        self.assertNotIn('file_data', json.dumps(job))

    def test_pdf_limits_format_encryption_and_auth_before_model(self):
        calls = []
        api.call_model = lambda *args, **kwargs: calls.append(args)
        self.assertEqual(self.upload(csrf=False)[0], 403)
        self.assertEqual(self.upload(origin='https://evil.invalid')[0], 403)
        self.assertEqual(self.upload(client=base.Client(self.base))[0], 401)
        for raw in (b'not a PDF', RAW.replace(b'%%EOF', b'broken'), RAW.replace(b'/Type', b'/Encrypt')):
            self.assertEqual(self.upload(raw)[0], 400)
        self.assertEqual(self.upload(b'x' * 5_000_001)[0], 400)
        self.assertEqual(self.upload(b'x' * 700_001, name='contract.txt')[0], 400)
        self.assertEqual(self.upload(RAW, name='contract.doc')[0], 400)
        self.assertEqual(calls, [])

    def test_pdf_larger_than_data_limit_and_scope_of_expansion(self):
        api.call_model = lambda *args, **kwargs: json.dumps(answer())
        large = RAW.replace(b'%%EOF', b'\n%' + b'x' * 1_100_000 + b'\n%%EOF')
        code, job = self.upload(large)
        self.assertEqual(code, 202, job); self.assertEqual(self.wait_job(job['id'])['status'], 'ready')
        code, error = self.client.call('stress/upload', {'filename': 'data.csv', 'content': base64.b64encode(large).decode()})
        self.assertEqual(code, 413, error)
        self.assertEqual(self.upload(b'x' * 5_110_000)[0], 413)

    def test_pdf_schema_incomplete_and_unsupported_claims_fail_closed(self):
        valid = answer()
        result = pdf.validate_result(valid, 'test.pdf', RAW, 'qwen3.8-max')
        self.assertEqual(result['thresholds']['dpd']['red'], 5)
        for key, value in [('page', 0), ('page', 501), ('page', True), ('metric_id', 'unknown'),
                           ('yellow', 13), ('yellow', True), ('red', float('nan')), ('quote', '无数字的识别片段')]:
            changed = copy.deepcopy(valid); changed['thresholds'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, data.DataError)):
                pdf.validate_result(changed, 'test.pdf', RAW, 'qwen3.8-max')
        for changed in ({**valid, 'complete': False}, {**valid, 'notes': [123]},
                        {**valid, 'thresholds': [valid['thresholds'][0]] * 2}):
            with self.assertRaises((ValueError, data.DataError)):
                pdf.validate_result(changed, 'test.pdf', RAW, 'qwen3.8-max')
        changed = copy.deepcopy(valid); changed['thresholds'][0].update(yellow=None, red=None)
        with self.assertRaises(ValueError): pdf.validate_result(changed, 'test.pdf', RAW, 'qwen3.8-max')
        self.assertIn(2_000_000, pdf.quote_numbers('储备低于200万元时为红灯。'))
        empty = pdf.validate_result({'complete': True, 'thresholds': [], 'notes': ['无可匹配阈值。']}, 'blank.pdf', RAW, 'qwen3.8-max')
        self.assertEqual(empty['thresholds'], {}); self.assertTrue(empty['requires_confirmation'])

    def test_failed_expired_and_interrupted_jobs_are_actionable(self):
        api.call_model = lambda *args, **kwargs: '{"secret": "not for output"}'
        code, job = self.upload(); self.assertEqual(code, 202)
        failed = self.wait_job(job['id']); self.assertEqual(failed['status'], 'failed')
        self.assertNotIn('secret', json.dumps(failed)); self.assertIn('重试', failed['message'])
        with pdf.LOCK: pdf.JOBS[job['id']].update(status='pending', started=time.monotonic() - 331)
        self.assertEqual(self.client.call('stress/contracts/' + job['id'])[1]['status'], 'failed')
        with pdf.LOCK: pdf.JOBS[job['id']]['started'] = time.monotonic() - 601
        self.assertEqual(self.client.call('stress/contracts/' + job['id'])[0], 404)

    def test_pdf_configuration_capacity_and_thread_start_failure(self):
        stress.REPORT_MODEL = 'qwen-plus'
        self.assertEqual(self.upload()[0], 503)
        stress.REPORT_MODEL = 'qwen3.8-max'
        api.API_KEY = ''
        self.assertEqual(self.upload()[0], 503)
        api.API_KEY = 'unit-test'
        pdf.GATE.acquire(); pdf.GATE.acquire()
        try: self.assertEqual(self.upload()[0], 429)
        finally: pdf.GATE.release(); pdf.GATE.release()
        with patch.object(pdf.threading.Thread, 'start', side_effect=RuntimeError('worker failed')):
            with self.assertRaises(RuntimeError):
                pdf.start(api, {'workspace_id': 'test'}, 'test', 'test.pdf', RAW, 'qwen3.8-max', stress.model_call, stress.safe_json)
        self.assertEqual(pdf.JOBS, {})
        self.assertTrue(pdf.GATE.acquire(blocking=False)); pdf.GATE.release()

    def test_model_truncation_has_static_diagnostic_without_source_text(self):
        def call(*args, **kwargs): return '{"thresholds": [{"quote": "private fragment'
        with self.assertRaisesRegex(pdf.PdfResultError, '^pdf_json_invalid_or_truncated$'):
            pdf.extract(api, 'test', 'test.pdf', RAW, 'qwen3.8-max', call, stress.safe_json)

    def test_provider_http_errors_are_not_reported_as_timeouts(self):
        for status, expected in ((400, '重新导出'), (401, '认证失败'), (403, '权限'), (429, '请求较多'), (503, '暂时不可用')):
            api.RECENT.clear()
            def model(*args, **kwargs):
                raise base.urllib.error.HTTPError('https://mock.invalid', status, 'provider secret text', {}, None)
            api.call_model = model
            code, job = self.upload(); self.assertEqual(code, 202)
            failed = self.wait_job(job['id']); self.assertEqual(failed['status'], 'failed')
            self.assertIn(expected, failed['message']); self.assertNotIn('secret', json.dumps(failed))


if __name__ == '__main__': unittest.main()
