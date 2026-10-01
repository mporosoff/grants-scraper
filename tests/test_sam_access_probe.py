"""One bounded SAM access request using synthetic responses, never live APIs."""
from contextlib import redirect_stdout
from datetime import date
from email.message import Message
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, quote_plus, urlsplit
from urllib.request import Request

import yaml

from tools import sam_access_probe as sam


KEY = 'synthetic-SAM-secret+with/slash and space'
TODAY = date(2026, 10, 1)
WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/sam-api-access-check.yml'


class Response:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.headers = headers or {}
        self.read_sizes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]


class SamAccessProbeTests(unittest.TestCase):
    def call(self, body, **kwargs):
        response = Response(body, **kwargs)
        opener = Mock()
        opener.open.return_value = response
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = sam.probe(KEY, today=TODAY, opener=opener)
        self.assertEqual(stdout.getvalue(), '')
        opener.open.assert_called_once()
        self.assertEqual(response.read_sizes, [1024 * 1024 + 1])
        self.assertTrue(response.closed)
        self.assertEqual(result['request_count'], 1)
        self.assertFalse(result['catalog_changed'])
        self.assertFalse(result['team_generation'])
        self.assert_safe(result)
        return result, opener

    def assert_safe(self, report):
        text = json.dumps(report)
        for secret in (KEY, quote(KEY, safe=''), quote_plus(KEY, safe=''), 'RAW_PRIVATE_DESCRIPTION', 'RAW_EXCEPTION'):
            self.assertNotIn(secret, text)
        self.assertNotIn('api_key=', text)

    def test_missing_key_performs_no_request_or_client_construction(self):
        for key in ('', ' \t\n', None):
            with self.subTest(key=key), patch.object(sam, 'build_opener') as build:
                opener = Mock()
                report = sam.probe(key, today=TODAY, opener=opener)
                self.assertEqual(report['outcome'], 'missing_key')
                self.assertEqual(report['request_count'], 0)
                self.assertIsNone(report['http_status'])
                self.assertFalse(report['api_access_verified'])
                self.assertEqual(report['samples'], [])
                opener.open.assert_not_called()
                build.assert_not_called()

    def test_fixed_bounded_get_and_empty_success_require_only_one_request(self):
        report, opener = self.call({'opportunitiesData': [], 'totalRecords': 0})
        request = opener.open.call_args.args[0]
        self.assertEqual(opener.open.call_args.kwargs, {'timeout': 30})
        parsed = urlsplit(request.full_url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ('https', 'api.sam.gov', '/opportunities/v2/search'))
        query = parse_qs(parsed.query)
        self.assertEqual(query, {'postedFrom': ['07/03/2026'], 'postedTo': ['10/01/2026'],
            'title': ['Broad Agency Announcement'], 'ptype': ['o'], 'limit': ['3'], 'offset': ['0'], 'api_key': [KEY]})
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertNotIn(KEY, json.dumps(dict(request.header_items())))
        self.assertEqual(report['query'], {'postedFrom': '07/03/2026', 'postedTo': '10/01/2026',
            'title': 'Broad Agency Announcement', 'ptype': 'o', 'limit': 3, 'offset': 0})
        self.assertEqual(report['outcome'], 'ok')
        self.assertTrue(report['api_access_verified'])
        self.assertEqual(report['http_status'], 200)
        self.assertEqual((report['total_records'], report['returned_records'], report['samples']), (0, 0, []))

    def test_samples_are_public_bounded_and_redact_raw_and_encoded_key_echoes(self):
        rows = []
        for index, echo in enumerate((KEY, quote(KEY, safe=''), quote_plus(KEY, safe=''), 'fourth')):
            rows.append({'noticeId': f'notice-{index}', 'title': f'BAA {echo} ' + 'x' * 500,
                'solicitationNumber': 'BAA-2026', 'fullParentPathName': 'DEPT.SUBAGENCY',
                'postedDate': '2026-09-29', 'type': 'Combined Synopsis/Solicitation', 'active': 'Yes',
                'responseDeadLine': '2026-11-01', 'naicsCode': '541715', 'classificationCode': 'AD11',
                'description': 'RAW_PRIVATE_DESCRIPTION ' + KEY, 'resourceLinks': [KEY],
                'award': {'private': KEY}, 'pointOfContact': [{'email': 'private@example.test'}]})
        report, _ = self.call({'opportunitiesData': rows, 'totalRecords': 200})
        self.assertEqual(len(report['samples']), 3)
        self.assertEqual(report['total_records'], 200)
        expected = {'noticeId', 'title', 'solicitationNumber', 'fullParentPathName', 'postedDate',
                    'type', 'active', 'responseDeadLine', 'naicsCode', 'classificationCode', 'description_present'}
        for index, sample in enumerate(report['samples']):
            self.assertEqual(set(sample), expected)
            self.assertEqual(sample['noticeId'], f'notice-{index}')
            self.assertTrue(sample['description_present'])
            self.assertIn('[redacted]', sample['title'])
            self.assertTrue(all(len(value) <= 300 for value in sample.values() if isinstance(value, str)))

    def test_sample_fields_drop_nested_or_nonstring_values(self):
        report, _ = self.call({'opportunitiesData': [{'noticeId': 'public-id', 'title': {'echo': KEY},
            'active': True, 'naicsCode': 541715, 'description': None}], 'totalRecords': 1})
        self.assertEqual(report['samples'], [{'noticeId': 'public-id', 'description_present': False}])

    def test_http_failures_keep_only_allowlisted_error_codes_and_numeric_quota_headers(self):
        for status, code in ((403, 'API_KEY_INVALID'), (429, 'OVER_RATE_LIMIT'), (403, 'RAW_EXCEPTION ' + KEY)):
            with self.subTest(status=status, code=code):
                body = io.BytesIO(json.dumps({'error': {'code': code, 'message': 'RAW_EXCEPTION ' + KEY},
                                              'echo': quote_plus(KEY, safe='')}).encode())
                error = HTTPError(sam.ENDPOINT + '?api_key=' + quote_plus(KEY), status,
                    'RAW_EXCEPTION ' + KEY, {'X-RateLimit-Limit': '1000', 'X-RateLimit-Remaining': '0',
                    'Retry-After': '60', 'Authorization': KEY, 'X-Other': 'RAW_EXCEPTION'}, body)
                opener = Mock()
                opener.open.side_effect = error
                with redirect_stdout(io.StringIO()) as stdout:
                    report = sam.probe(KEY, today=TODAY, opener=opener)
                self.assertEqual(stdout.getvalue(), '')
                opener.open.assert_called_once()
                self.assertTrue(body.closed)
                self.assertEqual(report['outcome'], 'http_error')
                self.assertEqual((report['request_count'], report['http_status']), (1, status))
                self.assertFalse(report['api_access_verified'])
                self.assertEqual(report['samples'], [])
                self.assertEqual(report['rate_limit'], {'X-RateLimit-Limit': 1000, 'X-RateLimit-Remaining': 0, 'Retry-After': 60})
                self.assertEqual(report.get('error_code'), code if code in {'API_KEY_INVALID', 'OVER_RATE_LIMIT'} else None)
                self.assert_safe(report)

    def test_quota_echoes_dates_and_unbounded_or_signed_values_are_omitted(self):
        for value in (KEY, '99999999999', '-1', '1.5', 'Wed, 01 Oct 2026 12:00:00 GMT', '12\n'):
            with self.subTest(value=value):
                report, _ = self.call({'opportunitiesData': [], 'totalRecords': 0}, headers={
                    'X-RateLimit-Limit': value, 'X-RateLimit-Remaining': value, 'Retry-After': value})
                self.assertEqual(report['rate_limit'], {})

    def test_network_exception_text_and_request_url_never_enter_report(self):
        for error in (URLError('RAW_EXCEPTION ' + KEY), TimeoutError('RAW_EXCEPTION ' + quote_plus(KEY))):
            with self.subTest(error=type(error).__name__):
                opener = Mock()
                opener.open.side_effect = error
                report = sam.probe(KEY, today=TODAY, opener=opener)
                opener.open.assert_called_once()
                self.assertEqual(report['outcome'], 'network_error')
                self.assertEqual(report['request_count'], 1)
                self.assertIsNone(report['http_status'])
                self.assertFalse(report['api_access_verified'])
                self.assert_safe(report)

    def test_default_client_refuses_redirect_before_a_second_credentialed_request(self):
        client = Mock()
        client.open.side_effect = HTTPError(sam.ENDPOINT, 302, 'redirect', {}, io.BytesIO(b''))
        with patch.object(sam, 'build_opener', return_value=client) as build:
            report = sam.probe(KEY, today=TODAY)
        handler = build.call_args.args[0]
        self.assertIsInstance(handler, sam.NoRedirect)
        handler.parent = Mock()
        headers = Message()
        headers['Location'] = 'https://other.example/?api_key=' + quote_plus(KEY)
        original = Request(sam.ENDPOINT + '?api_key=' + quote_plus(KEY))
        self.assertIsNone(handler.http_error_302(original, io.BytesIO(b''), 302, 'redirect', headers))
        handler.parent.open.assert_not_called()
        client.open.assert_called_once()
        self.assertEqual((report['outcome'], report['http_status'], report['request_count']), ('http_error', 302, 1))
        self.assert_safe(report)

    def test_invalid_json_schema_and_non_200_success_responses_fail_closed(self):
        invalid = [b'RAW_EXCEPTION ' + KEY.encode(), b'\xff', [], {},
                   {'opportunitiesData': {}, 'totalRecords': 0},
                   {'opportunitiesData': [], 'totalRecords': True},
                   {'opportunitiesData': [], 'totalRecords': -1},
                   {'opportunitiesData': [], 'totalRecords': '0'},
                   {'opportunitiesData': ['bad'], 'totalRecords': 1},
                   {'opportunitiesData': [{}], 'totalRecords': 0}]
        for body in invalid:
            with self.subTest(body=type(body).__name__):
                report, _ = self.call(body)
                self.assertFalse(report['api_access_verified'])
                self.assertEqual(report['outcome'], 'invalid_response')
                self.assertEqual(report['samples'], [])
        report, _ = self.call({'opportunitiesData': [], 'totalRecords': 0}, status=204)
        self.assertFalse(report['api_access_verified'])
        self.assertEqual(report['outcome'], 'invalid_response')

    def test_body_limit_is_bounded_and_an_exact_limit_valid_body_is_allowed(self):
        raw = json.dumps({'opportunitiesData': [], 'totalRecords': 0}).encode()
        exact = raw + b' ' * (1024 * 1024 - len(raw))
        report, _ = self.call(exact)
        self.assertTrue(report['api_access_verified'])
        report, _ = self.call(exact + b' ')
        self.assertEqual(report['outcome'], 'response_too_large')
        self.assertFalse(report['api_access_verified'])


class SamAccessWorkflowTests(unittest.TestCase):
    def test_manual_main_job_has_read_only_permissions_and_one_step_scoped_secret(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf8'))
        events = workflow.get('on') or workflow[True]
        self.assertEqual(set(events), {'workflow_dispatch'})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertNotIn('env', workflow)
        self.assertEqual(set(workflow['jobs']), {'check'})
        job = workflow['jobs']['check']
        self.assertEqual(job['if'], "github.repository == 'mporosoff/grants-scraper' && github.ref == 'refs/heads/main' && github.event_name == 'workflow_dispatch'")
        self.assertNotIn('env', job)
        self.assertLessEqual(job['timeout-minutes'], 3)
        self.assertIs(workflow['concurrency']['cancel-in-progress'], False)
        secret_steps = [step for step in job['steps'] if 'secrets.' in json.dumps(step)]
        commands = [step for step in job['steps'] if 'run' in step]
        self.assertEqual(secret_steps, commands)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]['env'], {'SAM_API_KEY': '${{ secrets.SAM_API_KEY }}'})
        self.assertEqual(commands[0]['run'], 'python -m tools.sam_access_probe --report "$RUNNER_TEMP/sam-access-check/report.json"')
        upload = next(step for step in job['steps'] if step.get('uses') == 'actions/upload-artifact@v4')
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['path'], '${{ runner.temp }}/sam-access-check/report.json')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        checkout = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/checkout@'))
        self.assertIs(checkout['with']['persist-credentials'], False)

    def test_cli_rejects_foreign_workflow_context_before_any_request(self):
        valid = {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY': 'mporosoff/grants-scraper',
                 'GITHUB_WORKFLOW_REF': 'mporosoff/grants-scraper/.github/workflows/sam-api-access-check.yml@refs/heads/main',
                 'SAM_API_KEY': KEY}
        cases = [('GITHUB_EVENT_NAME', 'schedule'), ('GITHUB_REF', 'refs/heads/feature'),
                 ('GITHUB_REPOSITORY', 'someone/fork'), ('GITHUB_WORKFLOW_REF', 'untrusted-workflow'),
                 ('GITHUB_EVENT_NAME', '')]
        with tempfile.TemporaryDirectory() as folder:
            for index, (name, value) in enumerate(cases):
                target = Path(folder) / str(index) / 'report.json'
                with self.subTest(name=name, value=value), patch.dict(os.environ, valid | {name: value}, clear=True), \
                        patch('sys.argv', ['sam_access_probe', '--report', str(target)]), \
                        patch.object(sam, 'probe') as probe, redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(sam.main(), 1)
                probe.assert_not_called()
                report = json.loads(target.read_text(encoding='utf8'))
                self.assertEqual(report, {'schema_version': 1, 'api_access_verified': False,
                                         'request_count': 0, 'outcome': 'invalid_workflow_context'})
                self.assertEqual(json.loads(stdout.getvalue()), report)
                self.assertNotIn(KEY, stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
