"""First allocation and producer identity require complete authenticated history."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import yaml

from tools import generation_spend_checkpoint as spending, generation_spend_recovery as finite
from tools import release_attempt_history as history

HEAD = 'a' * 40
REPOSITORY = 'mporosoff/grants-scraper'


def metadata(attempt=2, **changes):
    return {'id': 200, 'run_attempt': attempt, 'head_sha': HEAD, 'head_branch': 'main',
            'path': history.WORKFLOW, 'event': 'schedule', 'status': 'in_progress'} | changes


def jobs(attempt, names=None):
    names = sorted(history.KNOWN_JOBS if names is None else names)
    return [{'id': attempt * 1000 + index, 'name': name, 'run_id': 200, 'run_attempt': attempt,
             'head_sha': HEAD, 'head_branch': 'main', 'status': 'completed',
             'conclusion': 'success' if name == 'plan' else 'failure' if name in ('sam-preflight', 'closeout') else 'skipped'}
            for index, name in enumerate(names, 1)]


class AttemptHistoryContracts(unittest.TestCase):
    def setUp(self):
        self.meta = metadata()
        self.attempts = {1: metadata(1, status='completed', conclusion='failure'),
                         2: metadata(2, status='completed', conclusion='failure')}
        self.jobs = {1: jobs(1), 2: jobs(2)}
        self.artifacts = [{'id': 10, 'name': 'release-plan-1', 'expired': False, 'digest': 'sha256:' + 'b' * 64},
                          {'id': 11, 'name': 'sam-preflight-200-1', 'expired': False, 'digest': 'sha256:' + 'c' * 64},
                          {'id': 12, 'name': 'release-plan-2', 'expired': False, 'digest': 'sha256:' + 'd' * 64},
                          {'id': 13, 'name': 'sam-preflight-200-2', 'expired': False, 'digest': 'sha256:' + 'e' * 64}]
        self.inventory = patch.object(history, 'run_artifacts', side_effect=lambda *_a, **_kw: deepcopy(self.artifacts))
        self.inventory.start()
        self.addCleanup(self.inventory.stop)
        workflow = patch.object(history, 'workflow_job_names', return_value=history.KNOWN_JOBS)
        workflow.start()
        self.addCleanup(workflow.stop)
        self.api = Mock(side_effect=self.response)

    def response(self, path):
        fields = path.split('/')
        number = int(fields[4])
        if len(fields) == 5:
            return json.dumps(self.attempts[number])
        if fields[5].startswith('jobs?'):
            return json.dumps({'jobs': self.jobs[number], 'total_count': len(self.jobs[number])})
        raise AssertionError(path)

    def prove(self):
        return history.require_preflight_only_before_allocation(REPOSITORY, self.meta, self.meta['run_attempt'],
                                                                self.artifacts, api=self.api)

    def downstream(self, *, allowed=None):
        return history.require_downstream_only(REPOSITORY, self.meta, 1, self.artifacts,
                                               api=self.api, allowed_candidate_ids=allowed)

    def public_prefix_failure(self, attempt=1, *, failed_id='verify-sam-preflight'):
        raw = (history.candidate.ROOT / history.WORKFLOW).read_text(encoding='utf8')
        declared = yaml.safe_load(raw)['jobs']['generate']['steps']
        failed = next(index for index, step in enumerate(declared) if step.get('id') == failed_id)
        steps = [{'name': 'Set up job', 'number': 1, 'status': 'completed', 'conclusion': 'success'}]
        for index, step in enumerate(declared):
            name = step.get('name', 'Run ' + step.get('uses', step.get('run', '').split('\n')[0]))
            steps.append({'name': name, 'number': index + 2, 'status': 'completed',
                          'conclusion': 'success' if index < failed else 'failure' if index == failed else 'skipped'})
        for name, conclusion in (('sam-preflight', 'success'), ('generate', 'failure')):
            row = next(job for job in self.jobs[attempt] if job['name'] == name)
            row['conclusion'] = conclusion
            if name == 'generate': row['steps'] = steps
        return raw, steps

    def test_first_allocation_after_only_failed_preflight_records_exact_bounded_proof(self):
        proof = self.prove()
        self.assertEqual(proof['run_id'], '200')
        self.assertEqual(proof['current_attempt'], 2)
        self.assertEqual(proof['prior_attempts'][0]['attempt'], 1)
        self.assertFalse(proof['prior_allowance_reserved'])
        self.assertFalse(proof['prior_provider_dispatch'])
        self.assertEqual(proof['prior_attempts'][0]['jobs']['generate']['conclusion'], 'skipped')
        self.assertRegex(proof['artifact_inventory_sha256'], '^[a-f0-9]{64}$')
        self.assertFalse(any('/attempts/2/' in call.args[0] for call in self.api.call_args_list))

    def test_all_prior_attempts_must_be_preflight_only(self):
        self.meta['run_attempt'] = 3
        proof = self.prove()
        self.assertEqual([item['attempt'] for item in proof['prior_attempts']], [1, 2])
        next(job for job in self.jobs[1] if job['name'] == 'generate')['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'work started'):
            self.prove()

    def test_any_producer_or_downstream_work_prevents_fresh_allocation(self):
        for name in history.KNOWN_JOBS - {'plan', 'sam-preflight', 'closeout'}:
            with self.subTest(name=name):
                self.jobs[1] = jobs(1)
                next(job for job in self.jobs[1] if job['name'] == name)['conclusion'] = 'failure'
                with self.assertRaisesRegex(ValueError, 'work started'):
                    self.prove()

    def test_setup_download_fresh_check_or_verify_failure_before_allocation_can_reserve_once(self):
        for failed_id in ('restore', 'download-sam-preflight', 'rerun-sam-preflight', 'verify-sam-preflight'):
            with self.subTest(failed_id=failed_id):
                self.jobs[1] = jobs(1)
                raw, steps = self.public_prefix_failure(failed_id=failed_id)
                if failed_id == 'restore':
                    # A checkout/toolchain failure is equally safe if all native
                    # allocation/source/provider steps are proved skipped.
                    steps[1]['conclusion'] = 'failure'
                    for step in steps[2:]: step['conclusion'] = 'skipped'
                with patch.object(history.candidate, 'git', return_value=raw):
                    proof = self.prove()
                stop = proof['prior_attempts'][0]['generate_preallocation_stop']
                self.assertEqual(stop['job_id'], next(job['id'] for job in self.jobs[1] if job['name'] == 'generate'))
                self.assertRegex(stop['native_steps_sha256'], '^[a-f0-9]{64}$')
                self.assertFalse(proof['prior_provider_dispatch'])

    def test_selective_failed_job_retry_inherits_only_authenticated_prior_prerequisites(self):
        self.meta['run_attempt'] = 3
        raw, _ = self.public_prefix_failure(1)
        self.public_prefix_failure(2, failed_id='rerun-sam-preflight')
        self.jobs[2] = [job for job in self.jobs[2] if job['name'] in ('generate', 'closeout')]
        with patch.object(history.candidate, 'git', return_value=raw):
            proof = self.prove()
        self.assertEqual(set(proof['prior_attempts'][1]['jobs']), {'generate', 'closeout'})
        self.assertTrue(all('generate_preallocation_stop' in row for row in proof['prior_attempts']))
        # No prior full inventory may be reconstructed from guessed omissions.
        self.jobs[1] = [job for job in self.jobs[1] if job['name'] != 'plan']
        with patch.object(history.candidate, 'git', return_value=raw), self.assertRaisesRegex(ValueError, 'missing declared'):
            self.prove()

    def test_missing_ambiguous_or_started_allocation_and_source_steps_fail_closed(self):
        for change in ('missing', 'duplicate', 'duplicate-number', 'active', 'allocation', 'source', 'provider', 'no-prefix-failure'):
            with self.subTest(change=change):
                self.jobs[1] = jobs(1)
                raw, steps = self.public_prefix_failure()
                if change == 'missing': steps.pop()
                elif change == 'duplicate': steps.append(deepcopy(steps[-1]))
                elif change == 'duplicate-number': steps[-1]['number'] = steps[-2]['number']
                elif change == 'active': steps[-1]['status'] = 'in_progress'
                elif change == 'no-prefix-failure':
                    for step in steps:
                        if step['conclusion'] == 'failure': step['conclusion'] = 'success'
                else:
                    name = {'allocation': 'Restore the logical spend checkpoint',
                            'source': 'Build and validate complete public opportunity catalog',
                            'provider': 'Build compatible production document vectors'}[change]
                    next(step for step in steps if step['name'] == name)['conclusion'] = 'success'
                with patch.object(history.candidate, 'git', return_value=raw), self.assertRaises(ValueError):
                    self.prove()

    def test_reservation_or_orphan_state_candidate_and_unknown_artifact_cannot_reset_allowance(self):
        for name in ('generation-spend-reservation-200-1', 'generation-spend-state-200-1',
                     'offline-ai-economical-ai-20260908-state-200-1', 'candidate-' + 'a' * 64,
                     'program-area-vectors-' + 'a' * 64 + '-reservation-200-1', 'unknown'):
            with self.subTest(name=name):
                self.artifacts.append({'id': 99, 'name': name})
                with self.assertRaisesRegex(ValueError, 'prior work or unknown artifact'):
                    self.prove()
                self.artifacts.pop()

    def test_wrong_attempt_protected_origin_or_terminal_metadata_is_rejected(self):
        original = deepcopy(self.attempts[1])
        for field, value in (('id', 201), ('run_attempt', 2), ('head_sha', 'b' * 40), ('head_branch', 'feature'),
                             ('path', 'other.yml'), ('event', 'pull_request'), ('status', 'in_progress'),
                             ('conclusion', None)):
            with self.subTest(field=field):
                self.attempts[1] = original | {field: value}
                with self.assertRaises(ValueError): self.prove()
        self.attempts[1] = original
        for value in (11, '2', True):
            self.meta['run_attempt'] = value
            with self.subTest(attempt=value), self.assertRaises(ValueError): self.prove()

    def test_missing_duplicate_unknown_active_or_foreign_jobs_are_rejected(self):
        original = jobs(1)
        cases = [original[1:], original + [deepcopy(original[0])], []]
        for key, value in (('id', original[1]['id']), ('name', 'unknown'), ('run_id', 201), ('run_attempt', 2),
                           ('head_sha', 'b' * 40), ('head_branch', 'other'), ('status', 'queued'), ('conclusion', None)):
            changed = deepcopy(original); changed[0][key] = value; cases.append(changed)
        for rows in cases:
            self.jobs[1] = rows
            with self.subTest(rows=rows[:1]), self.assertRaises(ValueError): self.prove()

    def test_incomplete_changing_or_duplicate_artifact_inventory_fails_closed(self):
        rows = deepcopy(self.artifacts)
        for replacement in (rows[:-1], rows + [dict(rows[0])], rows + [{'id': 99, 'name': 'generation-spend-state-200-1'}]):
            with self.subTest(replacement=replacement), patch.object(history, 'run_artifacts', return_value=replacement), self.assertRaises(ValueError):
                self.prove()

    def test_job_pagination_follows_total_count_and_rejects_missing_or_unstable_pages(self):
        first, second = self.jobs[1][:9], self.jobs[1][9:]
        def response(path):
            if '/jobs?' not in path: return self.response(path)
            return json.dumps({'total_count': 17, 'jobs': first if path.endswith('page=1') else second})
        self.api.side_effect = response
        self.prove()
        self.assertTrue(any('page=2' in call.args[0] for call in self.api.call_args_list))
        for second_page in ({'total_count': 17, 'jobs': []}, {'total_count': 18, 'jobs': second},
                            {'total_count': 17, 'jobs': first}):
            def bad(path):
                return json.dumps(second_page) if '/jobs?' in path and path.endswith('page=2') else response(path)
            self.api.side_effect = bad
            with self.subTest(page=second_page), self.assertRaises(ValueError): self.prove()

    def test_later_downstream_only_subset_keeps_original_producer_metadata(self):
        self.meta.update(status='completed', conclusion='failure')
        self.jobs[2] = jobs(2, {'validate', 'publish', 'pages', 'verify-live', 'closeout'})
        for job in self.jobs[2]: job['conclusion'] = 'success'
        next(job for job in self.jobs[2] if job['name'] == 'pages')['name'] = 'pages / deploy'
        original = self.downstream()
        self.assertEqual(original, self.attempts[1])
        self.assertEqual(original['run_attempt'], 1)
        self.assertEqual(self.meta['run_attempt'], 2)

    def test_later_executed_producer_or_new_accounting_or_extra_candidate_is_rejected(self):
        self.meta.update(status='completed', conclusion='failure')
        self.jobs[2] = jobs(2, {'validate', 'closeout'})
        for job in self.jobs[2]: job['conclusion'] = 'success'
        for name in history.PRODUCERS:
            self.jobs[2].extend(jobs(2, {name}))
            self.jobs[2][-1].update(id=9000, conclusion='failure')
            with self.subTest(name=name), self.assertRaises(ValueError): self.downstream()
            self.jobs[2].pop()
        for name in ('generation-spend-reservation-200-2', 'generation-spend-state-200-2',
                     'offline-ai-economical-ai-20260908-reservation-200-2',
                     'offline-ai-reconcile-' + 'a' * 64 + '-reservation-200-2'):
            self.artifacts.append({'id': 99, 'name': name})
            with self.subTest(name=name), self.assertRaises(ValueError): self.downstream()
            self.artifacts.pop()
        self.artifacts.extend([{'id': 98, 'name': 'candidate-' + 'a' * 64}, {'id': 99, 'name': 'candidate-' + 'b' * 64}])
        with self.assertRaisesRegex(ValueError, 'competing candidate'): self.downstream()
        self.downstream(allowed={98, 99})
        with self.assertRaises(ValueError): self.downstream(allowed={98})

    def test_first_reservation_retains_new_zero_dispatch_proof_without_provider_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = root / 'reservation.json'
            def api(repository, path):
                return json.dumps(self.meta) if path == 'actions/runs/200' else self.response(path)
            with patch.object(spending, 'api', side_effect=api), patch.object(spending, 'run_artifacts', return_value=self.artifacts), \
                    patch.object(finite, 'restore', wraps=finite.restore) as recovery:
                spending.prepare(REPOSITORY, '200', '2', root / 'offline-200', reservation, 'maintenance')
            recovery.assert_called_once()
            ledger = json.loads((root / 'offline-200/ledger.json').read_text(encoding='utf8'))
            self.assertEqual(ledger['requests'], [])
            proof = json.loads((root / 'offline-200/initial-allocation-provenance.json').read_text(encoding='utf8'))
            value = json.loads(reservation.read_text(encoding='utf8'))
            self.assertEqual(value['first_allocation_proof_sha256'], spending.identity(proof))
            self.assertEqual(value['maximum_logical_spend_usd'], spending.config()['budgets_usd']['maintenance'])

    def test_first_pilot_allocation_still_restores_the_existing_cumulative_task_allowance(self):
        self.meta['event'] = 'workflow_dispatch'
        self.attempts[1]['event'] = 'workflow_dispatch'
        def api(repository, path):
            return json.dumps(self.meta) if path == 'actions/runs/200' else self.response(path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'offline-200'
            with patch.object(spending, 'api', side_effect=api), patch.object(spending, 'run_artifacts', return_value=self.artifacts), \
                    patch('tools.offline_ai_checkpoint.prepare') as task, \
                    patch('tools.offline_spend.restore_ledger') as restore_task:
                spending.prepare(REPOSITORY, '200', '2', state, root / 'reservation.json', 'pilot', qualification_pilot=True)
            task.assert_called_once_with(REPOSITORY, state / 'task', state / 'task-reservation.json')
            self.assertEqual(restore_task.call_count, 1)
            self.assertEqual(restore_task.call_args.args[0], state / 'task/ledger.json')
            self.assertEqual(restore_task.call_args.args[2], spending.config()['budgets_usd']['evaluation'])
            self.assertTrue((state / 'task-accounting.json').exists())

    def test_unknown_prior_work_is_rejected_before_ledger_or_any_write(self):
        next(job for job in self.jobs[1] if job['name'] == 'generate')['conclusion'] = 'failure'
        def api(repository, path):
            return json.dumps(self.meta) if path == 'actions/runs/200' else self.response(path)
        with patch.object(spending, 'api', side_effect=api), patch.object(spending, 'run_artifacts', return_value=self.artifacts), \
                patch.object(spending, 'Ledger') as ledger, patch.object(spending, 'atomic_json') as write:
            with self.assertRaises(ValueError):
                spending.prepare(REPOSITORY, '200', '2', Path('unused'), Path('unused.json'), 'maintenance')
        ledger.assert_not_called()
        write.assert_not_called()


class ProtectedWorkflowJobNames(unittest.TestCase):
    def test_protected_workflow_profiles_and_actual_skipped_pages_metadata(self):
        old_sha, current_sha = '1' * 40, '2' * 40
        old_jobs = {name: {'runs-on': 'ubuntu-latest'} for name in history.KNOWN_JOBS - {'sam-preflight', 'catalog-reconcile'}}
        old_jobs['pages'] = {'uses': './.github/workflows/pages.yml'}
        sources = {
            old_sha + ':' + history.WORKFLOW: yaml.safe_dump({'jobs': old_jobs}),
            current_sha + ':' + history.WORKFLOW: (history.candidate.ROOT / history.WORKFLOW).read_text(encoding='utf8'),
            old_sha + ':.github/workflows/pages.yml': 'jobs:\n  deploy:\n    runs-on: ubuntu-latest\n',
            current_sha + ':.github/workflows/pages.yml': (history.candidate.ROOT / '.github/workflows/pages.yml').read_text(encoding='utf8'),
        }
        def git(root, command, selector):
            self.assertEqual(root, history.candidate.ROOT)
            self.assertEqual(command, 'show')
            return sources[selector]
        with patch.object(history.candidate, 'git', side_effect=git) as read:
            old = history.workflow_job_names(old_sha)
            current = history.workflow_job_names(current_sha)
        self.assertEqual(len(old), 15)
        self.assertEqual(current - old, {'sam-preflight', 'catalog-reconcile'})
        self.assertIn('pages', old)
        read.assert_has_calls([call(history.candidate.ROOT, 'show', old_sha + ':' + history.WORKFLOW),
                               call(history.candidate.ROOT, 'show', old_sha + ':.github/workflows/pages.yml'),
                               call(history.candidate.ROOT, 'show', current_sha + ':' + history.WORKFLOW),
                               call(history.candidate.ROOT, 'show', current_sha + ':.github/workflows/pages.yml')])
        # Actual GitHub attempt2 metadata: skipped reusable Pages is "pages".
        actual = {'id': 116992685768, 'run_id': 38757294301, 'run_attempt': 2,
                  'head_sha': 'c90cab07610580488024109532b6bbf12cb3d79c', 'head_branch': 'main',
                  'name': 'pages', 'status': 'completed', 'conclusion': 'skipped'}
        meta = metadata(2, id=38757294301, head_sha=actual['head_sha'], status='completed', conclusion='failure')
        response = json.dumps({'total_count': 1, 'jobs': [actual]})
        with patch.object(history, 'workflow_job_names', return_value=old):
            self.assertEqual(set(history._jobs(meta, meta, api=lambda _path: response, full=False)), {'pages'})


if __name__ == '__main__':
    unittest.main()
