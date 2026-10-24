"""Read-only transport survives transient failures without weakening evidence."""
from contextlib import redirect_stderr
from datetime import datetime, timezone
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from tools import github_read as reader


def response(status=200, body=b'{"jobs":[]}', headers=None):
    values = {'X-GitHub-Request-Id': 'FIXTURE:123', **(headers or {})}
    return (f'HTTP/2.0 {status} Response\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in values.items())
            + '\r\n').encode() + body


def failure(status, headers=None):
    return subprocess.CalledProcessError(1, ['gh'], output=response(status, b'private response text', headers),
                                        stderr=f'gh: failure (HTTP {status})'.encode())


class GitHubReadContracts(unittest.TestCase):
    def setUp(self):
        self.calls = patch.object(reader.subprocess, 'check_output').start()
        self.sleep = patch.object(reader.time, 'sleep').start()
        self.addCleanup(patch.stopall)
        self.diagnostics = io.StringIO()
        self.addCleanup(self.diagnostics.close)
        self.redirect = redirect_stderr(self.diagnostics)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def read(self):
        return reader.get('owner/repo', 'actions/runs/123/jobs?per_page=100&page=1')

    def test_502_from_native_incident_retries_same_get_then_returns_exact_json(self):
        body = b'{"jobs":[{"id":123}],"total_count":1}'
        self.calls.side_effect = [failure(502), response(body=body)]
        self.assertEqual(self.read(), body)
        self.assertEqual(self.calls.call_args_list[0], self.calls.call_args_list[1])
        command = self.calls.call_args.args[0]
        self.assertEqual(command[:5], ['gh', 'api', '--method', 'GET', '--include'])
        self.sleep.assert_called_once_with(2)
        diagnostic = json.loads(self.diagnostics.getvalue())
        self.assertEqual((diagnostic['status'], diagnostic['request_id']), (502, 'FIXTURE:123'))

    def test_binary_artifact_body_is_byte_identical_including_embedded_headers(self):
        body = b'PK\x03\x04\x00\xff\r\n\r\nHTTP/2.0 200 OK\n\nexact artifact bytes'
        self.calls.return_value = response(body=body)
        self.assertEqual(reader.get('owner/repo', 'actions/artifacts/12/zip'), body)
        self.sleep.assert_not_called()

    def test_rate_limit_obeys_retry_after_and_long_wait_holds_without_early_retry(self):
        self.calls.side_effect = [failure(429, {'Retry-After': '9'}), response()]
        self.read()
        self.sleep.assert_called_once_with(9)
        self.calls.reset_mock(); self.sleep.reset_mock()
        self.calls.side_effect = [failure(429, {'Retry-After': '120'})]
        with self.assertRaisesRegex(reader.ReadFailure, '1 attempt.*429'):
            self.read()
        self.calls.assert_called_once()
        self.sleep.assert_not_called()

    def test_http_date_retry_after_is_observed(self):
        with patch.object(reader, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
            self.assertEqual(reader._retry_after({'retry-after': 'Sat, 24 Oct 2026 20:00:12 GMT'}), 12)

    def test_network_timeout_and_connection_reset_retry_with_bound(self):
        self.calls.side_effect = [subprocess.TimeoutExpired(['gh'], 60),
            subprocess.CalledProcessError(1, ['gh'], stderr=b'connection reset by peer'), response()]
        self.assertEqual(self.read(), b'{"jobs":[]}')
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [2, 4])

    def test_repeated_transient_errors_exhaust_three_attempts_and_stay_failed(self):
        self.calls.side_effect = [failure(503)] * 3
        with self.assertRaisesRegex(reader.ReadFailure, '3 attempt.*503,503,503'):
            self.read()
        self.assertEqual(self.calls.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_access_denial_and_not_found_do_not_retry(self):
        for status in (401, 403, 404, 422):
            with self.subTest(status=status):
                self.calls.reset_mock(); self.sleep.reset_mock()
                self.calls.side_effect = failure(status)
                with self.assertRaises(reader.ReadFailure):
                    self.read()
                self.calls.assert_called_once()
                self.sleep.assert_not_called()

    def test_stderr_http_status_can_retry_without_printing_sensitive_text(self):
        self.calls.side_effect = [subprocess.CalledProcessError(1, ['gh'],
            output=b'secret body', stderr=b'private signed URL gh: Server Error (HTTP 502)'), response()]
        self.read()
        self.assertNotIn('secret', self.diagnostics.getvalue())
        self.assertNotIn('signed', self.diagnostics.getvalue())

    def test_malformed_success_and_unknown_cli_errors_fail_closed(self):
        for result in (b'{"unframed":"body"}', subprocess.CalledProcessError(1, ['gh'], stderr=b'login needed')):
            self.calls.reset_mock(); self.sleep.reset_mock()
            self.calls.side_effect = [result]
            with self.assertRaises(reader.ReadFailure):
                self.read()
            self.calls.assert_called_once()
            self.sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
