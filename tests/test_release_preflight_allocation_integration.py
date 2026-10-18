"""Actual release-job conditions must preserve a preflight-only retry history."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_release_candidate_gate import (
    RESUME_STAGE_GUARD, evaluate_downstream, evaluate_job_condition, skipped_needs, workflow_jobs,
)
from tools import generation_spend_checkpoint as spending, generation_spend_recovery as finite
from tools import release_attempt_history as history

REPOSITORY = 'mporosoff/grants-scraper'
HEAD = 'a' * 40
RUN = 200
DOWNSTREAM = ('candidate', 'validate', 'publish', 'pages', 'verify-live')


class PreflightAllocationIntegration(unittest.TestCase):
    def setUp(self):
        self.jobs = workflow_jobs()
        self.meta = {'id': RUN, 'run_attempt': 2, 'head_sha': HEAD, 'head_branch': 'main',
                     'event': 'schedule', 'path': history.WORKFLOW, 'status': 'in_progress'}
        self.prior = dict(self.meta, run_attempt=1, status='completed', conclusion='failure')
        self.artifacts = [{'id': number, 'name': name, 'expired': False,
                           'digest': 'sha256:' + str(number) * 64,
                           'workflow_run': {'id': RUN, 'head_branch': 'main', 'head_sha': HEAD}}
                          for number, name in enumerate(('release-plan-1', 'sam-preflight-200-1',
                                                         'release-plan-2', 'sam-preflight-200-2'), 1)]

    def matrix(self, *, old=False):
        definitions = deepcopy(self.jobs)
        if old:
            condition = definitions['candidate']['if']
            self.assertIn(RESUME_STAGE_GUARD + ' && ', condition)
            definitions['candidate']['if'] = condition.replace(RESUME_STAGE_GUARD + ' && ', '', 1)
        needs = skipped_needs(stage='generate')
        self.assertTrue(evaluate_job_condition(definitions['sam-preflight'], needs))
        needs['sam-preflight']['result'] = 'failure'
        # Derive producer conclusions from the declared stage conditions AND
        # Actions' implicit success() dependency gate, rather than assuming them.
        for name, job in definitions.items():
            if name in history.PRODUCERS:
                needs[name]['result'] = 'success' if evaluate_job_condition(job, needs) else 'skipped'
        needs = evaluate_downstream(needs, jobs=definitions, outcomes={'validate': 'failure'})
        # The existing always-running closeout reports the failed preflight.
        needs['closeout']['result'] = 'failure'
        return needs

    def historical_jobs(self, matrix):
        self.assertEqual(set(matrix), set(self.jobs))
        return [{'id': 1000 + index, 'name': name, 'run_id': RUN, 'run_attempt': 1,
                 'head_sha': HEAD, 'head_branch': 'main', 'status': 'completed',
                 'conclusion': matrix[name]['result']}
                for index, name in enumerate(sorted(self.jobs), 1)]

    def mocks(self, matrix):
        rows = self.historical_jobs(matrix)
        def api(repository, path):
            self.assertEqual(repository, REPOSITORY)
            if path == 'actions/runs/200':
                return json.dumps(self.meta)
            if path == 'actions/runs/200/attempts/1':
                return json.dumps(self.prior)
            if path == 'actions/runs/200/attempts/1/jobs?per_page=100&page=1':
                return json.dumps({'total_count': len(rows), 'jobs': rows})
            raise AssertionError('Unexpected API route: ' + path)
        stack = ExitStack()
        stack.enter_context(patch.object(spending, 'api', side_effect=api))
        stack.enter_context(patch.object(spending, 'run_artifacts', return_value=deepcopy(self.artifacts)))
        stack.enter_context(patch.object(history, 'run_artifacts', return_value=deepcopy(self.artifacts)))
        stack.enter_context(patch.object(history, 'workflow_job_names', return_value=frozenset(self.jobs)))
        stack.enter_context(patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No external source or provider')))
        stack.enter_context(patch('requests.Session.request', side_effect=AssertionError('No provider request')))
        return stack

    def test_fixed_yaml_skips_every_downstream_stage_and_allows_first_reservation_on_retry(self):
        matrix = self.matrix()
        self.assertEqual(matrix['sam-preflight']['result'], 'failure')
        for name in history.PRODUCERS | set(DOWNSTREAM):
            with self.subTest(job=name): self.assertEqual(matrix[name]['result'], 'skipped')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, reservation = root / 'offline-200', root / 'reservation.json'
            with self.mocks(matrix), patch.object(finite, 'restore', wraps=finite.restore) as recovery:
                spending.prepare(REPOSITORY, str(RUN), '2', state, reservation, 'maintenance')
            recovery.assert_called_once()
            ledger = json.loads((state / 'ledger.json').read_text(encoding='utf8'))
            self.assertEqual(ledger['requests'], [])
            proof = json.loads((state / 'initial-allocation-provenance.json').read_text(encoding='utf8'))
            self.assertFalse(proof['prior_allowance_reserved'])
            self.assertFalse(proof['prior_provider_dispatch'])
            for name in DOWNSTREAM:
                self.assertEqual(proof['prior_attempts'][0]['jobs'][name]['conclusion'], 'skipped')
            value = json.loads(reservation.read_text(encoding='utf8'))
            self.assertEqual((value['run_id'], value['attempt'], value['mode']), ('200', '2', 'maintenance'))
            self.assertEqual(value['maximum_logical_spend_usd'], spending.config()['budgets_usd']['maintenance'])
            self.assertEqual(value['first_allocation_proof_sha256'], spending.identity(proof))

    def test_old_yaml_fallback_started_downstream_and_remains_rejected_before_any_allocation(self):
        matrix = self.matrix(old=True)
        self.assertEqual(matrix['generate']['result'], 'skipped')
        self.assertEqual(matrix['assemble']['result'], 'skipped')
        self.assertEqual(matrix['candidate']['result'], 'success')
        self.assertEqual(matrix['validate']['result'], 'failure')
        with self.mocks(matrix), patch.object(spending, 'Ledger') as ledger, \
                patch.object(spending, 'atomic_json') as write, self.assertRaisesRegex(ValueError, 'work started'):
            spending.prepare(REPOSITORY, str(RUN), '2', Path('unused-no-write'), Path('unused-reservation.json'), 'maintenance')
        ledger.assert_not_called()
        write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
