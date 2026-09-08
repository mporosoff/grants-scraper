"""Public release probes identify themselves and preserve safe failure evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools import verify_release_live as live


def response(status, body, content_type='application/json', **headers):
    result = MagicMock(status_code=status, content=body)
    result.headers = {'Content-Type': content_type, 'Server': 'cloudflare', 'CF-Ray': 'test-ray', **headers}
    result.iter_content.return_value = iter([body[:8192]])
    result.__enter__.return_value = result
    return result


class ReleaseHTTPTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'candidate_id': 'candidate-exact', 'release_identity': {
            'current_corpus_sha256': 'corpus', 'model_space_fingerprint': 'space'}}
        self.health = {'service': 'available', 'budget_state': 'available',
                       'corpus_sha256': 'corpus', 'model_space_fingerprint': 'space'}

    def test_worker_handshake_uses_complete_truthful_deterministic_profile(self):
        with patch.object(live.requests, 'get', return_value=response(200, json.dumps(self.health).encode())) as get:
            self.assertEqual(live.worker_check(self.manifest), self.health)
        get.assert_called_once_with(live.WORKER, headers={
            'Accept': 'application/json', 'Origin': 'https://mporosoff.github.io',
            'Cache-Control': 'no-cache',
            'User-Agent': 'FundingFinder-ReleaseVerifier/1.0 (+https://github.com/mporosoff/grants-scraper)',
        }, timeout=45, allow_redirects=False, stream=True)

    def test_edge_1010_and_worker_origin_denial_remain_distinct_without_raw_text(self):
        cases = [
            (response(403, b'error code: 1010\n private text must not be logged', 'text/plain; charset=UTF-8'),
             'cloudflare_edge', False, {'cloudflare_error_code': 1010}),
            (response(403, b'{"error":{"code":"origin_forbidden"},"private":"must not be logged"}'),
             'worker_error_contract', True, {'worker_error_code': 'origin_forbidden'}),
        ]
        for reply, source, application, extra in cases:
            with self.subTest(source=source), patch.object(live.requests, 'get', return_value=reply):
                with self.assertRaises(live.ProbeHTTPError) as caught:
                    live.fetch(live.WORKER)
                diagnostic = caught.exception.diagnostic
                self.assertEqual(diagnostic, {'http_profile': live.HTTP_PROFILE, 'status': 403,
                    'content_type': reply.headers['Content-Type'], 'server': 'cloudflare', 'cf_ray': 'test-ray',
                    'response_source': source, 'worker_application_response': application, **extra})
                self.assertNotIn('private', str(caught.exception))
                reply.iter_content.assert_called_once_with(chunk_size=8192)

    def test_redirect_and_unknown_denial_fail_closed_without_logging_arbitrary_body(self):
        for status in (302, 403, 429, 503):
            with self.subTest(status=status), patch.object(live.requests, 'get', return_value=response(
                    status, b'private payload' * 1000, 'text/html', Server='x' * 1000)):
                with self.assertRaises(live.ProbeHTTPError) as caught:
                    live.fetch(live.WORKER)
                self.assertEqual(caught.exception.diagnostic['response_source'], 'unknown')
                self.assertLessEqual(len(caught.exception.diagnostic['server']), 160)
                self.assertNotIn('private payload', str(caught.exception))

    def test_failed_handshake_retains_candidate_diagnostics_and_retry_reuses_candidate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(live.c, 'load', return_value=self.manifest), \
                patch.object(live.requests, 'get') as get:
            get.return_value = response(403, b'error code: 1010', 'text/plain')
            with self.assertRaisesRegex(ValueError, 'retain candidate'):
                live.verify_worker('immutable-candidate', directory, attempts=1)
            report = json.loads((Path(directory) / 'worker-handshake.json').read_text())
            self.assertFalse(report['verified'])
            self.assertEqual(report['candidate_id'], self.manifest['candidate_id'])
            self.assertEqual(report['failures'][0]['http']['cloudflare_error_code'], 1010)
            self.assertEqual(report['next_retry_stage'], 'publish')
            get.return_value = response(200, json.dumps(self.health).encode())
            ready = live.verify_worker('immutable-candidate', directory, attempts=1)
            self.assertTrue(ready['verified'])
            self.assertEqual(ready['candidate_id'], report['candidate_id'])

    def test_bounded_retry_keeps_failure_evidence_after_success(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(live.c, 'load', return_value=self.manifest), \
                patch.object(live.requests, 'get', side_effect=[response(503, b'unavailable', 'text/plain'),
                    response(200, json.dumps(self.health).encode())]), patch.object(live.time, 'sleep') as sleep:
            report = live.verify_worker('immutable-candidate', directory, attempts=2, sleep=sleep)
            sleep.assert_called_once_with(5)
            self.assertTrue(report['verified'])
            self.assertEqual(report['failures'][0]['http']['status'], 503)

    def test_workflow_retains_handshake_report_in_publication_artifact(self):
        workflow = (live.c.ROOT / '.github/workflows/refresh-opportunities.yml').read_text()
        self.assertIn('tools.verify_release_live worker --bundle "$RUNNER_TEMP/candidate" --reports "$RUNNER_TEMP/reports"', workflow)
        self.assertIn('path: ${{ runner.temp }}/reports', workflow)


if __name__ == '__main__':
    unittest.main()
