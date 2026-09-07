import subprocess
import unittest
from unittest.mock import Mock

from tools.wait_refresh_review import wait_for_merge


class ManualRefreshCheckpoint(unittest.TestCase):
    def wait(self, states, **kwargs):
        stamp = [0]
        def sleep(seconds):
            stamp[0] += seconds
        self.read = Mock(side_effect=states)
        return wait_for_merge('https://github.com/example/repository/pull/42', 'a' * 40,
            read=self.read, now=lambda: stamp[0], sleep=sleep, interval=1, timeout=kwargs.get('timeout', 10))

    def test_only_exact_protected_merge_releases_checkpoint(self):
        self.assertEqual(self.wait([
            {'headRefOid': 'a' * 40, 'state': 'OPEN'},
            {'headRefOid': 'a' * 40, 'state': 'MERGED', 'mergeCommit': {'oid': 'b' * 40}},
        ]), 'b' * 40)
        self.assertEqual(self.read.call_count, 2)

    def test_changed_closed_or_malformed_candidates_cannot_continue(self):
        for value in [None, [], {'headRefOid': 'c' * 40, 'state': 'MERGED'},
                      {'headRefOid': 'a' * 40, 'state': 'CLOSED'},
                      {'headRefOid': 'a' * 40, 'state': 'MERGED', 'mergeCommit': ['untrusted']},
                      {'headRefOid': 'a' * 40, 'state': 'MERGED', 'mergeCommit': {}}]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.wait([value])

    def test_timeout_and_external_failure_are_bounded(self):
        with self.assertRaisesRegex(RuntimeError, 'window expired'):
            self.wait([{'headRefOid': 'a' * 40, 'state': 'OPEN'}] * 3, timeout=3)
        self.assertEqual(self.read.call_count, 3)
        with self.assertRaisesRegex(RuntimeError, 'bounded retries'):
            self.wait([subprocess.TimeoutExpired('gh', 30)] * 3)
        self.assertEqual(self.read.call_count, 3)

    def test_transient_failure_recovers_without_mutating_the_candidate(self):
        self.assertEqual(self.wait([OSError(), {'headRefOid': 'a' * 40, 'state': 'MERGED',
                                               'mergeCommit': {'oid': 'b' * 40}}]), 'b' * 40)

    def test_invalid_command_inputs_make_no_external_calls(self):
        read = Mock()
        for url, head in [('https://github.com/example/repo/pull/1;command', 'a' * 40),
                          ('https://github.com/example/repo/pull/1', 'HEAD')]:
            with self.assertRaises(ValueError):
                wait_for_merge(url, head, read=read)
        read.assert_not_called()
