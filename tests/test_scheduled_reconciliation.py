"""A published correction retires its exact authenticated parent, never siblings."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import release_candidate as c, scheduled_catalog as s


class CorrectedOwner(unittest.TestCase):
    def setUp(self):
        self.parent = 'a' * 64
        self.run = {'id': 200, 'run_attempt': 1, 'head_sha': 'b' * 40,
            'head_branch': 'main', 'event': 'schedule', 'path': s.WORKFLOW, 'status': 'completed'}
        self.artifact = {'id': 10, 'name': 'candidate-' + self.parent,
                         'digest': 'sha256:' + 'c' * 64, 'expired': False}
        receipt = {'version': 'catalog-source-reconciliation-1', 'source_slug': 'sam-gov',
            'parent_candidate_id': self.parent, 'parent_run': '200', 'parent_attempt': '1',
            'parent_generation_sha': 'b' * 40, 'parent_manifest_sha256': 'd' * 64,
            'parent_producer': {'run_id': '200', 'run_attempt': '1', 'head_sha': 'b' * 40,
                                'event': 'schedule', 'path': s.WORKFLOW},
            'parent_artifact': {'id': 10, 'name': self.artifact['name'], 'sha256': 'c' * 64},
            'affected_generation': {'generation_run_id': '250', 'generation_sha': 'e' * 40}}
        self.child = {'generation_sha': 'b' * 40, 'assembly_sha': 'e' * 40,
                      'derived_from_candidate': self.parent, 'source_reconciliation': receipt}

    def check(self):
        child = deepcopy(self.child)
        child['candidate_id'] = c.digest(c.encoded(child))
        pointer = {'candidate_id': child['candidate_id'], 'artifact_run': '250'}
        def git(root, *args):
            if args[0] == 'log':
                return 'published'
            return json.dumps(pointer if args[-1].endswith('candidate-source.json') else child)
        with patch.object(c, 'git', side_effect=git), \
                patch.object(s, 'api', side_effect=ValueError('Attempt history must be injected')):
            return s._published_reconciliation_supersedes(Path('.'), self.run, [self.artifact], repository='owner/repo')

    def test_exact_published_child_releases_original_owner(self):
        self.assertTrue(self.check())

    def test_another_owner_or_unpublished_sibling_does_not_release_it(self):
        self.child['source_reconciliation']['parent_run'] = '201'
        self.assertFalse(self.check())

    def test_changed_artifact_attempt_or_producer_cannot_reset_allowance(self):
        for field, value in [('digest', 'sha256:' + 'f' * 64), ('id', 11), ('expired', True)]:
            with self.subTest(field=field):
                old = self.artifact[field]
                self.artifact[field] = value
                with self.assertRaises(s.Hold):
                    self.check()
                self.artifact[field] = old
        self.run['run_attempt'] = 2
        with self.assertRaises(s.Hold):
            self.check()

    def test_later_downstream_retry_authenticates_original_attempt_without_relabelling_it(self):
        original = deepcopy(self.run)
        self.run['run_attempt'] = 2
        with patch('tools.release_attempt_history.require_downstream_only', return_value=original) as history:
            self.assertTrue(self.check())
        self.assertEqual(history.call_args.args[:4], ('owner/repo', self.run, 1, [self.artifact]))
        self.assertEqual(self.child['source_reconciliation']['parent_producer']['run_attempt'], '1')

    def test_incomplete_or_changed_historical_producer_still_holds(self):
        original = deepcopy(self.run)
        self.run['run_attempt'] = 2
        with patch('tools.release_attempt_history.require_downstream_only', side_effect=ValueError('Executed later producer')):
            with self.assertRaises(s.Hold):
                self.check()
        with patch('tools.release_attempt_history.require_downstream_only', return_value=original | {'head_sha': 'f' * 40}):
            with self.assertRaises(s.Hold):
                self.check()

    def consumed(self, *, candidate=False):
        producer = {'run_id': '220', 'run_attempt': '1', 'head_sha': 'f' * 40,
                    'event': 'workflow_dispatch', 'path': s.WORKFLOW}
        family = 'offline-ai-reconcile-' + self.parent
        pins = {role: {'id': number, 'name': f'{family}-{role}-220-1', 'sha256': 'd' * 64}
                for role, number in [('reservation', 20), ('state', 21)]}
        self.run.update(id=220, head_sha='f' * 40, event='workflow_dispatch')
        self.artifacts = [dict(pin, digest='sha256:' + pin['sha256']) for pin in pins.values()]
        link = {'producer': producer, **pins, 'request_count': 7, 'charged_microusd': 6152,
                **{name: 'c' * 64 for name in ('ledger_sha256', 'request_prefix_sha256', 'request_identity_prefix_sha256')}}
        if candidate:
            pin = {'id': 22, 'name': 'candidate-' + '9' * 64, 'sha256': 'a' * 64}
            self.artifacts.append(dict(pin, digest='sha256:' + pin['sha256']))
            link['candidate'] = {'candidate_id': '9' * 64, 'manifest_sha256': 'b' * 64,
                                 'producer': producer, 'artifact': pin}
        self.child['source_reconciliation']['consumed_checkpoints'] = [link]

    def check_consumed(self):
        child = deepcopy(self.child)
        child['candidate_id'] = c.digest(c.encoded(child))
        pointer = {'candidate_id': child['candidate_id'], 'artifact_run': '250'}
        with patch.object(c, 'git', side_effect=lambda root, *args: 'published' if args[0] == 'log'
                else json.dumps(pointer if args[-1].endswith('candidate-source.json') else child)), \
                patch.object(s, 'api', side_effect=ValueError('Attempt history must be injected')):
            return s._published_reconciliation_consumes(Path('.'), self.run, self.artifacts, repository='owner/repo')

    def test_published_child_consumes_exact_failed_repair_and_rejected_candidate(self):
        for candidate in (False, True):
            with self.subTest(candidate=candidate):
                self.consumed(candidate=candidate)
                self.assertTrue(self.check_consumed())

    def test_unacknowledged_new_allowance_or_candidate_still_holds(self):
        self.consumed(candidate=True)
        self.artifacts.append({'id': 23, 'name': 'candidate-' + '8' * 64, 'digest': 'sha256:' + 'a' * 64})
        with self.assertRaises(s.Hold):
            self.check_consumed()
        self.artifacts.pop()
        self.artifacts.append({'id': 24, 'name': f'offline-ai-reconcile-{self.parent}-reservation-220-2',
                               'digest': 'sha256:' + 'b' * 64})
        self.run['run_attempt'] = 2
        with self.assertRaises(s.Hold):
            self.check_consumed()

    def test_consumed_checkpoint_retires_only_after_proving_later_downstream_retry(self):
        self.consumed(candidate=True)
        original = deepcopy(self.run)
        self.run['run_attempt'] = 2
        with patch('tools.release_attempt_history.require_downstream_only', return_value=original) as history:
            self.assertTrue(self.check_consumed())
        self.assertEqual(history.call_args.args[2], 1)
        self.assertEqual(history.call_args.kwargs['allowed_candidate_ids'], {22})

    def test_pre_candidate_failure_does_not_invent_a_candidate_in_later_downstream_history(self):
        self.consumed()
        original = deepcopy(self.run)
        self.run['run_attempt'] = 2
        with patch('tools.release_attempt_history.require_downstream_only', return_value=original) as history:
            self.assertTrue(self.check_consumed())
        self.assertEqual(history.call_args.kwargs['allowed_candidate_ids'], set())

    def test_each_consumed_producer_is_authenticated_before_checking_only_later_unacknowledged_work(self):
        self.consumed()
        links = self.child['source_reconciliation']['consumed_checkpoints']
        later = deepcopy(links[0])
        later['producer']['run_attempt'] = '2'
        for role in ('reservation', 'state'):
            later[role]['id'] += 10
            later[role]['name'] = later[role]['name'].removesuffix('-1') + '-2'
            self.artifacts.append(dict(later[role], digest='sha256:' + later[role]['sha256']))
        links.append(later)
        self.run['run_attempt'] = 3
        with patch('tools.release_attempt_history.authenticate_attempt', return_value=self.run | {'run_attempt': 1}) as auth, \
                patch('tools.release_attempt_history.require_downstream_only', return_value=self.run | {'run_attempt': 2}) as history:
            self.assertTrue(self.check_consumed())
        self.assertEqual(auth.call_args.args[2], 1)
        self.assertEqual(history.call_args.args[2], 2)


if __name__ == '__main__':
    unittest.main()
