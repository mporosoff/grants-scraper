"""Daily-owner retirement follows exact modern candidates and private ledgers."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import yaml

from tools import program_area_history as h, scheduled_catalog as daily
from tools.offline_spend import identity


class ModernHistory(unittest.TestCase):
    def setUp(self):
        self.run = {'id': 200, 'run_attempt': 1, 'head_sha': 'a'*40, 'head_branch': 'main',
            'path': h.WORKFLOW, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success'}
        self.ledger = {'logical_id': 'offline-100', 'limit_microusd': 2_000_000, 'max_requests': 300, 'requests': []}
        self.context = {'version': h.VERSION, 'parent_candidate_id': 'b'*64, 'parent_run': '100',
            'parent_attempt': '1', 'parent_generation_sha': 'c'*40, 'parent_manifest_sha256': 'd'*64,
            'parent_producer': {}, 'parent_artifact': {}, 'original_spend': {},
            'operation_contract': {}, 'audit_at': '2026-10-19T00:00:00Z'}
        self.context['operation_sha256'] = identity(self.context)
        self.receipt = dict(self.context, ledger_sha256=identity(self.ledger), consumed_checkpoints=[],
            affected_generation={'generation_run_id': '200', 'generation_run_attempt': '1', 'generation_sha': 'e'*40})
        self.child = {'generation_sha': 'c'*40, 'generation_run_id': '100', 'assembly_sha': 'e'*40,
            'derived_from_candidate': 'b'*64, h.FIELD: self.receipt}
        self.child['candidate_id'] = daily.c.digest(daily.c.encoded(self.child))
        self.context['completed_candidate_id'] = self.child['candidate_id']
        self.voucher = {'version': h.VERSION, 'parent_candidate_id': 'b'*64,
            'producer_run': '200', 'producer_attempt': '1', 'prior_ledger_sha256': 'f'*64,
            'operation_sha256': self.context['operation_sha256']}
        self.artifacts = [self.artifact(1, 'reservation'), self.artifact(2, 'state'),
            self.artifact(3, 'candidate')]
        self.pointer = {'candidate_id': self.child['candidate_id'], 'artifact_run': '200'}
        self.state = {'reservation.json': self.voucher, 'ledger.json': self.ledger,
            'reconciliation.json': self.context,
            'complete-candidates/' + self.child['candidate_id'] + '/candidate.json': self.child}
        self.meta = patch.object(h.history, 'authenticate_attempt', side_effect=self.attempt).start()
        self.docs = patch.object(daily, '_reconciliation_documents', side_effect=self.documents).start()
        self.history = patch.object(daily, '_require_reconciliation_restore_history').start()
        patch.object(daily.c, 'git', side_effect=self.git).start()
        self.addCleanup(patch.stopall)

    def artifact(self, identifier, role, attempt=1):
        name = ('candidate-' + self.child['candidate_id'] if role == 'candidate' else
            f'{h.prefix("b"*64)}-{role}-200-{attempt}')
        return {'id': identifier, 'name': name, 'digest': 'sha256:' + str(identifier)*64,
            'expired': False, 'workflow_run': {'id': 200, 'head_sha': 'a'*40, 'head_branch': 'main'}}

    def attempt(self, repository, run, attempt, **kwargs):
        if attempt > run['run_attempt']:
            raise ValueError('attempt unavailable')
        return dict(run, run_attempt=int(attempt))

    def git(self, root, *args):
        if args[0] == 'log':
            return 'f'*40
        return json.dumps(self.pointer if args[-1].endswith('candidate-source.json') else self.child)

    def documents(self, repository, run, artifact, names, **kwargs):
        source = ({'candidate.json': self.child} if artifact['name'].startswith('candidate-') else
            {'reservation.json': self.voucher} if '-reservation-' in artifact['name'] else self.state)
        return {name: deepcopy(source[name]) for name in names}

    def retire(self):
        return h.published_consumes('.', self.run, self.artifacts, repository='owner/repo')

    def test_exact_published_producer_retires_original_allowance(self):
        self.assertTrue(self.retire())
        self.history.assert_called_once()

    def test_unrelated_published_candidate_does_not_retire_run(self):
        self.run['id'] = 201
        self.assertFalse(self.retire())

    def test_new_reservation_after_publication_stays_owner(self):
        self.run['run_attempt'] = 2
        self.artifacts.append(self.artifact(4, 'reservation', 2))
        with self.assertRaisesRegex(daily.Hold, 'unacknowledged allowance'):
            self.retire()

    def test_unacknowledged_candidate_stays_owner(self):
        extra = self.artifact(4, 'candidate'); extra['name'] = 'candidate-' + '9'*64
        self.artifacts.append(extra)
        with self.assertRaisesRegex(daily.Hold, 'unacknowledged candidate'):
            self.retire()

    def test_completed_state_tampering_holds(self):
        self.context['audit_at'] = '2026-10-20T00:00:00Z'
        with self.assertRaisesRegex(daily.Hold, 'sealed operation'):
            self.retire()

    def test_reallocated_budget_holds(self):
        self.ledger['logical_id'] = 'offline-200'
        with self.assertRaisesRegex(daily.Hold, 'original logical allowance'):
            self.retire()

    def test_changed_completed_candidate_holds(self):
        path = 'complete-candidates/' + self.child['candidate_id'] + '/candidate.json'
        self.state[path] = dict(self.child, assembly_sha='9'*40)
        with self.assertRaisesRegex(daily.Hold, 'exact completed child'):
            self.retire()

    def test_changed_native_reservation_holds(self):
        self.artifacts[0]['expired'] = True
        with self.assertRaisesRegex(daily.Hold, 'retained artifact identity'):
            self.retire()

    def test_unchanged_state_only_resume_requires_skipped_generation(self):
        self.run['run_attempt'] = 2
        self.artifacts.append(self.artifact(4, 'state', 2))
        with patch.object(h, 'completed_restore') as restored:
            self.assertTrue(self.retire())
            restored.assert_called_once()
        self.assertEqual(self.history.call_args.args[3][0]['state_id'], 4)

    def test_transport_retains_original_receipt_producer(self):
        self.run.update(id=201)
        self.pointer['artifact_run'] = '201'
        self.artifacts = [dict(self.artifact(4, 'state'), name=f'{h.prefix("b"*64)}-state-201-1'),
            self.artifact(3, 'candidate')]
        with patch.object(h, 'completed_restore') as restored:
            self.assertTrue(self.retire())
            restored.assert_called_once()
        self.assertEqual(self.receipt['affected_generation']['generation_run_id'], '200')

    def test_actual_workflow_restoration_guards_are_authenticated(self):
        workflow = yaml.safe_load((h.c.ROOT/h.WORKFLOW).read_text(encoding='utf8'))
        declared = workflow['jobs']['program-area-revalidation']['steps']
        guarded = [s['name'] for s in declared if s.get('if', '').startswith(
            "steps.restore.outputs.candidate_id == '' && steps.prepare.outputs.candidate_id == ''")]
        steps = [{'name': s['name'], 'status': 'completed', 'conclusion':
            'skipped' if s['name'] in guarded else 'success'} for s in declared if 'name' in s]
        jobs = {'program-area-revalidation': {'conclusion': 'success', 'steps': steps},
            'generate': {'conclusion': 'skipped'}, 'assemble': {'conclusion': 'skipped'}}
        with patch.object(h.history, '_jobs', return_value=jobs), patch.object(h.c, 'git', return_value=yaml.safe_dump(workflow)):
            h.completed_restore('owner/repo', self.run, self.run)
            vector = next(s for s in steps if s['name'] == 'Rebuild the corrected corpus inside its original durable logical allowance')
            vector['conclusion'] = 'success'
            with self.assertRaisesRegex(ValueError, 'restore repeated'):
                h.completed_restore('owner/repo', self.run, self.run)


if __name__ == '__main__':
    unittest.main()
