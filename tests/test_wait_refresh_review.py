import subprocess
import unittest
from unittest.mock import Mock

from tools.wait_refresh_review import wait_for_merge


class ManualRefreshCheckpoint(unittest.TestCase):
    def wait(self, states, **kwargs):
        stamp = [0]
        def sleep(seconds):
            stamp[0] += seconds
        self.read = Mock(side_effect=[{'baseRefName': 'main', 'baseRefOid': 'd' * 40} | state
                                     if isinstance(state, dict) else state for state in states])
        commit = {'sha': 'b' * 40, 'parents': [{'sha': 'd' * 40}], 'tree': {'sha': 'e' * 40}}
        self.read_commit = kwargs.get('read_commit', Mock(return_value=kwargs.get('commit', commit)))
        return wait_for_merge('https://github.com/example/repository/pull/42', 'a' * 40, 'd' * 40, 'e' * 40,
            read=self.read, read_commit=self.read_commit, now=lambda: stamp[0], sleep=sleep,
            interval=1, timeout=kwargs.get('timeout', 10))

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
                wait_for_merge(url, head, 'd' * 40, 'e' * 40, read=read)
        read.assert_not_called()

    def test_changed_or_retargeted_base_cannot_release_the_candidate(self):
        for change in [{'baseRefName': 'another-branch'}, {'baseRefOid': 'f' * 40}]:
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'Protected base changed'):
                self.wait([{'headRefOid': 'a' * 40, 'state': 'OPEN'} | change])

    def test_merge_must_preserve_exact_validated_parent_and_tree(self):
        valid = {'sha': 'b' * 40, 'parents': [{'sha': 'd' * 40}], 'tree': {'sha': 'e' * 40}}
        for change in [{'parents': [{'sha': 'f' * 40}]}, {'tree': {'sha': 'f' * 40}},
                       {'sha': 'f' * 40}, {'parents': []}]:
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'validated base and tree'):
                self.wait([{'headRefOid': 'a' * 40, 'state': 'MERGED', 'mergeCommit': {'oid': 'b' * 40}}],
                          commit=valid | change)

    def test_merge_metadata_failure_retries_within_the_same_budget(self):
        valid = {'sha': 'b' * 40, 'parents': [{'sha': 'd' * 40}], 'tree': {'sha': 'e' * 40}}
        read_commit = Mock(side_effect=[OSError(), valid])
        self.assertEqual(self.wait([{'headRefOid': 'a' * 40, 'state': 'MERGED', 'mergeCommit': {'oid': 'b' * 40}}] * 2,
                                   read_commit=read_commit), 'b' * 40)
        self.assertEqual(read_commit.call_count, 2)
