"""Historical log transport preserves controls in memory without rendering them."""
from contextlib import redirect_stderr, redirect_stdout
import io
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from tools import github_job_log_bytes as logs


RAW_LOG = b'\xef\xbb\xbfupload proof\r\n\x1b[31mred\x1b[0m\x1b]0;private title\x07\r\n'


class JobLogTransportContracts(unittest.TestCase):
    def setUp(self):
        logs._supports_escape_flag.cache_clear()
        self.addCleanup(logs._supports_escape_flag.cache_clear)

    def test_old_cli_uses_only_its_supported_flags_and_caches_capability(self):
        with patch.object(logs, '_capture', side_effect=[b'USAGE\n  gh api <endpoint>\n', RAW_LOG, RAW_LOG]) as capture:
            self.assertEqual(logs.read_job_log('owner/project', 116499469833), RAW_LOG)
            self.assertEqual(logs.read_job_log('owner/project', '116499469834'), RAW_LOG)
        self.assertEqual(capture.call_count, 3)
        self.assertEqual(capture.call_args_list[0].args,
                         (['gh', 'api', '--help'], logs.MAX_HELP_BYTES, 'capability check'))
        self.assertEqual(capture.call_args_list[1].args,
                         (['gh', 'api', 'repos/owner/project/actions/jobs/116499469833/logs'],
                          logs.MAX_LOG_BYTES, 'retrieval'))

    def test_new_cli_opt_in_applies_only_to_the_exact_job_log_request(self):
        help_bytes = b'FLAGS\n      --allow-escape-sequences   Allow printing terminal escape sequences\n'
        with patch.object(logs, '_capture', side_effect=[help_bytes, RAW_LOG]) as capture:
            self.assertEqual(logs.read_job_log('owner/.github', '116499469833'), RAW_LOG)
        self.assertEqual(capture.call_args_list[1].args[0],
                         ['gh', 'api', 'repos/owner/.github/actions/jobs/116499469833/logs',
                          '--allow-escape-sequences'])

    def test_an_unrelated_help_mention_does_not_enable_an_unsupported_flag(self):
        with patch.object(logs, '_capture', side_effect=[b'See --allow-escape-sequences in future versions\n', RAW_LOG]) as capture:
            logs.read_job_log('owner/project', 1)
        self.assertNotIn('--allow-escape-sequences', capture.call_args_list[1].args[0])

    def test_malformed_selectors_fail_before_any_subprocess(self):
        repositories = ('owner/project/extra', '../project', 'owner/..', 'owner/.', '-owner/project',
                        'owner/project?x=1', 'owner/project\n', '--hostname/host', None)
        identifiers = (0, -1, True, False, '01', '1/logs', '1?x=1', '1\n', '--help', 1.0, None)
        with patch.object(logs, '_capture') as capture:
            for repository in repositories:
                with self.subTest(repository=repository), self.assertRaisesRegex(ValueError, 'repository'):
                    logs.read_job_log(repository, 1)
            for identifier in identifiers:
                with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, 'identifier'):
                    logs.read_job_log('owner/project', identifier)
        capture.assert_not_called()

    def test_help_failure_prevents_log_retrieval_and_is_not_cached_as_success(self):
        with patch.object(logs, '_capture', side_effect=logs.JobLogReadError('safe help failure')) as capture:
            with self.assertRaisesRegex(logs.JobLogReadError, 'safe help failure'):
                logs.read_job_log('owner/project', 1)
        self.assertEqual(capture.call_count, 1)
        with patch.object(logs, '_capture', side_effect=[b'', RAW_LOG]) as capture:
            self.assertEqual(logs.read_job_log('owner/project', 1), RAW_LOG)
        self.assertEqual(capture.call_count, 2)

    def test_capture_preserves_escape_and_osc_bytes_and_silently_captures_stderr(self):
        command = [sys.executable, '-c',
                   'import sys; sys.stdout.buffer.write(' + repr(RAW_LOG) + '); '
                   'sys.stderr.buffer.write(b"\\x1b]0;stderr title\\x07")']
        stdout, stderr = io.StringIO(), io.StringIO()
        real_popen = subprocess.Popen
        with redirect_stdout(stdout), redirect_stderr(stderr), patch.object(logs.subprocess, 'Popen', wraps=real_popen) as popen:
            self.assertEqual(logs._capture(command, logs.MAX_LOG_BYTES, 'retrieval'), RAW_LOG)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs['stderr'], subprocess.PIPE)

    def test_command_failure_never_exposes_raw_captured_output_or_chained_error(self):
        command = [sys.executable, '-c',
                   'import sys; sys.stdout.buffer.write(' + repr(RAW_LOG) + '); '
                   'sys.stderr.buffer.write(b"SECRET\\x1b[2J"); sys.exit(1)']
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(logs.JobLogReadError) as raised:
            logs._capture(command, logs.MAX_LOG_BYTES, 'retrieval')
        self.assertEqual(str(raised.exception), 'GitHub job log retrieval failed')
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(hasattr(raised.exception, 'output'))
        self.assertFalse(hasattr(raised.exception, 'stderr'))
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')

    def test_stdout_and_stderr_limits_abort_with_a_safe_error(self):
        for stream, limit in (('stdout', 10), ('stderr', logs.MAX_LOG_BYTES)):
            amount = 11 if stream == 'stdout' else logs.MAX_ERROR_BYTES + 1
            command = [sys.executable, '-c',
                       f'import sys, time; sys.{stream}.buffer.write(b"x" * {amount}); '
                       f'sys.{stream}.flush(); time.sleep(60)']
            processes = []
            real_popen = subprocess.Popen
            def launch(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process
            start = time.monotonic()
            with self.subTest(stream=stream), patch.object(logs.subprocess, 'Popen', side_effect=launch):
                with self.assertRaisesRegex(logs.JobLogReadError, 'byte limit'):
                    logs._capture(command, limit, 'retrieval')
                self.assertLess(time.monotonic() - start, 5)
                self.assertIsNotNone(processes[0].poll())
                self.assertFalse(any(thread.name.startswith('github-job-log-')
                                     for thread in threading.enumerate()))

    def test_timeout_kills_child_and_reports_only_safe_text(self):
        command = [sys.executable, '-c', 'import time; time.sleep(60)']
        start = time.monotonic()
        processes = []
        real_popen = subprocess.Popen
        def launch(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(logs.subprocess, 'Popen', side_effect=launch), patch.object(logs, 'TIMEOUT_SECONDS', 0.05):
            with self.assertRaisesRegex(logs.JobLogReadError, 'timed out') as raised:
                logs._capture(command, logs.MAX_LOG_BYTES, 'retrieval')
        self.assertLess(time.monotonic() - start, 5)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNotNone(processes[0].poll())
        self.assertFalse(any(thread.name.startswith('github-job-log-')
                             for thread in threading.enumerate()))

    def test_launch_failure_does_not_render_or_chain_the_original_error(self):
        with patch.object(logs.subprocess, 'Popen', side_effect=OSError('SECRET\x1b[2J')):
            with self.assertRaisesRegex(logs.JobLogReadError, 'could not start') as raised:
                logs._capture(['gh', 'api', '--help'], logs.MAX_HELP_BYTES, 'capability check')
        self.assertNotIn('SECRET', str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertTrue(raised.exception.__suppress_context__)


if __name__ == '__main__':
    unittest.main()
