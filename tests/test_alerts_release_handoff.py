from pathlib import Path
import json
import unittest
from unittest.mock import Mock, patch

from tools import alerts_release_handoff as handoff
from tools import release_candidate as candidate


class AlertsHandoffTests(unittest.TestCase):
    repository = 'owner/repo'
    publication_sha = 'a' * 40
    control_sha = 'b' * 40
    candidate_id = 'c' * 64
    attempt = 2
    run_id = 101

    def setUp(self):
        self.root = Path('checkout')
        self.event = {'id': self.run_id, 'run_attempt': self.attempt,
                      'path': handoff.history.WORKFLOW, 'head_branch': 'main',
                      'head_repository': {'full_name': self.repository},
                      'head_sha': self.control_sha, 'event': 'schedule',
                      'status': 'completed', 'conclusion': 'success'}
        self.jobs = {'plan': 'success', 'verify-live': 'success', 'closeout': 'success'}
        self.prior_jobs = {}
        self.latest_attempt = None
        self.artifacts = [{'name': f'live-{self.candidate_id}-{self.attempt}'}]
        self.files = dict.fromkeys(handoff.ALERTS_PAGES_FILES, 'd' * 64)
        self.manifest = {'candidate_id': self.candidate_id, 'files': self.files}
        self.head = self.publication_sha
        self.changed = 'workers/alerts/src/index.js\ntests/browser/alerts-phase2-contract.test.mjs'
        self.download = Mock()
        self.addCleanup(patch.stopall)
        patch.object(handoff.history, 'workflow_job_names', return_value=set(self.jobs)).start()
        patch.object(candidate, 'git', side_effect=self.git).start()
        patch.object(candidate, 'read_json', return_value=self.manifest).start()
        self.verify_files = patch.object(candidate, 'verify_files').start()
        self.verify_live = patch.object(handoff, 'verify_live_receipt').start()

    def git(self, root, command, *_):
        self.assertEqual(root, self.root)
        return {'rev-parse': self.head, 'log': self.publication_sha, 'diff': self.changed}[command]

    def api(self, path):
        run_path = f'actions/runs/{self.run_id}'
        if path == run_path:
            return json.dumps(dict(self.event, run_attempt=self.latest_attempt or self.attempt))
        for number, outcomes in {**self.prior_jobs, self.attempt: self.jobs}.items():
            attempt_path = f'{run_path}/attempts/{number}'
            metadata = dict(self.event, run_attempt=number,
                            conclusion='success' if number == self.attempt else 'failure')
            if path == attempt_path:
                return json.dumps(metadata)
            if path == f'{attempt_path}/jobs?per_page=100&page=1':
                jobs = [dict(metadata, id=index, name=name, run_id=self.run_id, conclusion=conclusion)
                        for index, (name, conclusion) in enumerate(outcomes.items(), 1)]
                return json.dumps({'total_count': len(jobs), 'jobs': jobs})
        if path == f'{run_path}/artifacts?per_page=100&page=1':
            return json.dumps({'total_count': len(self.artifacts), 'artifacts': self.artifacts})
        self.fail(f'Unexpected evidence request {path}')

    def route(self, event=None):
        return handoff.automatic_handoff(self.root, self.repository, event or self.event,
                                         api=self.api, download=self.download)

    def test_exact_completed_attempt_hands_off_the_published_catalog(self):
        self.assertEqual(self.route(), 'catalog')
        self.assertEqual(self.download.call_args.args[:3],
                         (self.repository, self.run_id, f'live-{self.candidate_id}-{self.attempt}'))
        self.assertEqual(self.verify_live.call_args.args[-2:], (self.manifest, self.head))

    def test_closeout_only_retry_inherits_exact_live_receipt(self):
        self.prior_jobs[1] = dict(self.jobs, closeout='failure')
        self.jobs = {'closeout': 'success'}
        self.artifacts = [{'name': f'live-{self.candidate_id}-1'}]
        self.assertEqual(self.route(), 'catalog')
        self.assertEqual(self.download.call_args.args[:3],
                         (self.repository, self.run_id, f'live-{self.candidate_id}-1'))

    def test_closeout_only_retry_of_worker_push_inherits_successful_plan_and_skipped_verify(self):
        self.event.update(event='push', head_sha=self.head)
        self.prior_jobs[1] = {'plan': 'success', 'verify-live': 'skipped', 'closeout': 'failure'}
        self.jobs = {'closeout': 'success'}
        with (patch.object(handoff, 'candidate_groups'), patch.object(handoff, 'snapshot'),
              patch.object(handoff, 'changed_groups', return_value={})):
            self.assertEqual(self.route(), 'worker')
        self.verify_files.assert_called_once_with(self.root, self.files)
        self.download.assert_not_called()

    def test_newer_explicit_live_attempt_never_inherits_prior_success(self):
        self.attempt = 3
        self.event['run_attempt'] = self.attempt
        self.prior_jobs[1] = dict(self.jobs, closeout='failure')
        self.jobs = {'closeout': 'success'}
        self.artifacts = [{'name': f'live-{self.candidate_id}-1'}]
        for conclusion in ('failure', 'cancelled', 'skipped'):
            self.prior_jobs[2] = {'verify-live': conclusion, 'closeout': 'failure'}
            with self.subTest(conclusion=conclusion):
                self.assertEqual(self.route(), 'skip')
        self.download.assert_not_called()

    def test_older_completion_does_not_launch_while_a_newer_attempt_exists(self):
        self.latest_attempt = self.attempt + 1
        self.assertEqual(self.route(), 'skip')
        self.download.assert_not_called()

    def test_noop_schedule_and_unrelated_push_skip_catalog_gates(self):
        self.jobs['verify-live'] = 'skipped'
        self.assertEqual(self.route(), 'skip')
        self.event.update(event='push', head_sha=self.head)
        self.changed = 'scripts/extract_document_evidence.py'
        self.assertEqual(self.route(), 'skip')
        self.download.assert_not_called()
        self.verify_live.assert_not_called()
        self.verify_files.assert_not_called()

    def test_superseded_live_attempt_does_not_gate_current_catalog(self):
        self.artifacts = [{'name': f'live-{"e" * 64}-{self.attempt}'}]
        self.assertEqual(self.route(), 'skip')
        self.head = self.control_sha
        self.assertEqual(self.route(), 'skip')
        self.download.assert_not_called()

    def test_missing_attempt_receipt_or_foreign_event_cannot_pass(self):
        self.artifacts = [{'name': f'live-{self.candidate_id}-1'}]
        with self.assertRaisesRegex(ValueError, 'exact attempt'):
            self.route()
        with self.assertRaisesRegex(ValueError, 'same-repository'):
            self.route(dict(self.event, head_repository={'full_name': 'fork/repo'}))
        self.download.assert_not_called()

    def test_worker_only_push_preserves_deployment_path_but_mixed_source_work_waits(self):
        self.event.update(event='push', head_sha=self.head)
        self.jobs['verify-live'] = 'skipped'
        with (patch.object(handoff, 'candidate_groups'), patch.object(handoff, 'snapshot'),
              patch.object(handoff, 'changed_groups', return_value={'validation': ['tests/worker.py']}) as changes):
            self.assertEqual(self.route(), 'worker')
            self.verify_files.assert_called_once_with(self.root, self.files)
            changes.return_value = {'source': ['scripts/source.py']}
            self.assertEqual(self.route(), 'skip')
        self.download.assert_not_called()


class AlertsLiveReceiptTests(unittest.TestCase):
    def test_live_verification_must_cover_the_exact_publication_and_serving_worker(self):
        root, reports = Path('checkout'), Path('reports')
        head = 'a' * 40
        files = dict.fromkeys(handoff.ALERTS_PAGES_FILES, 'b' * 64)
        manifest = {'candidate_id': 'c' * 64, 'files': files, 'generation_sha': 'd' * 40,
                    'generation_run_id': '101', 'release_identity': {'catalog': 'exact'}}
        validation = {'candidate_id': manifest['candidate_id'], 'validation_sha': head,
                      'identity': {'candidate_hashes': files},
                      'gates': dict.fromkeys(candidate.GATES, 'passed')}
        publication = {'schema_version': 1, 'candidate_id': manifest['candidate_id'], 'candidate_hashes': files,
                       'generation_sha': manifest['generation_sha'], 'generation_run_id': '101',
                       'validation_sha': head, 'release_code_sha': head, 'publication_sha': head,
                       'validation_receipt_sha256': candidate.digest(candidate.encoded(validation))}
        live = {'verified': True, 'candidate_id': manifest['candidate_id'], 'publication_sha': head,
                'publication_receipt_sha256': candidate.digest(candidate.encoded(publication)),
                'differences': [], 'asset_verification': 'success', 'provider_smoke': 'success',
                'worker_provenance': {'verified': True}, 'live_release_identity': manifest['release_identity']}
        fixtures = {'publication.json': publication, 'validation.json': validation, 'live-verification.json': live}
        with (patch.object(candidate, 'read_json', side_effect=lambda path: fixtures[path.name]),
              patch.object(candidate, 'verify_files') as verify_files):
            self.assertTrue(handoff.verify_live_receipt(root, reports, manifest, head))
            verify_files.assert_called_once_with(root, files)
            self.assertFalse(handoff.verify_live_receipt(root, reports, manifest, 'e' * 40))
            for key, value in {'publication_receipt_sha256': 'e' * 64, 'provider_smoke': 'skipped',
                               'worker_provenance': {'verified': False}}.items():
                fixtures['live-verification.json'] = dict(live, **{key: value})
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'exact successful live verification'):
                    handoff.verify_live_receipt(root, reports, manifest, head)


if __name__ == '__main__':
    unittest.main()
