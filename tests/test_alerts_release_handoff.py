from pathlib import Path
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tools import alerts_release_handoff as handoff
from tools import release_candidate as candidate


class AlertsHandoffTests(unittest.TestCase):
    service = None  # Existing callers retain the default Alerts contract.
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
        self.changed = f'workers/{self.service or "alerts"}/src/index.js\ntests/browser/worker.test.mjs'
        self.download = Mock()
        self.addCleanup(patch.stopall)
        patch.object(handoff.history, 'workflow_job_names', return_value=set(self.jobs)).start()
        patch.object(candidate, 'git', side_effect=self.git).start()
        patch.object(candidate, 'read_json', return_value=self.manifest).start()
        self.verify_files = patch.object(candidate, 'verify_files').start()
        self.verify_live = patch.object(handoff, 'verify_live_receipt').start()
        self.publication = patch.object(handoff, 'protected_publication', return_value=self.publication_sha).start()

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
                                         api=self.api, download=self.download,
                                         **({'service': self.service} if self.service else {}))

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
            self.publication.reset_mock()
            changes.return_value = {'source': ['scripts/source.py']}
            self.assertEqual(self.route(), 'skip')
            self.publication.assert_not_called()
        self.download.assert_not_called()

    def test_another_service_only_push_does_not_launch_this_worker(self):
        self.event.update(event='push', head_sha=self.head)
        self.jobs['verify-live'] = 'skipped'
        other = 'alerts' if self.service == 'award-api' else 'award-api'
        self.changed = f'workers/{other}/src/index.js'
        self.assertEqual(self.route(), 'skip')
        self.verify_files.assert_not_called()
        self.download.assert_not_called()
        self.publication.assert_not_called()


class AwardsHandoffTests(AlertsHandoffTests):
    service = 'award-api'


class HandoffCommandTests(unittest.TestCase):
    def test_command_selects_awards_explicitly_and_preserves_default_alerts(self):
        event = {'workflow_run': {'id': 101}}
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            environment = {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_PATH': 'event.json',
                           'GITHUB_OUTPUT': str(output)}
            with (patch.dict(os.environ, environment),
                  patch.object(candidate, 'read_json', return_value=event),
                  patch.object(handoff, 'automatic_handoff', return_value='skip') as route):
                for arguments, service in (([], 'alerts'), (['--service', 'award-api'], 'award-api')):
                    with self.subTest(service=service):
                        handoff.main(arguments)
                        self.assertEqual(route.call_args.kwargs['service'], service)
                        self.assertEqual(route.call_args.args, (candidate.ROOT, 'owner/repo', event['workflow_run']))
            self.assertEqual(output.read_text(encoding='utf-8'), 'route=skip\nroute=skip\n')

    def test_worker_handoff_exports_the_retained_protected_pages_publication(self):
        event = {'workflow_run': {'id': 101}}
        publication = 'a' * 40
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            environment = {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_PATH': 'event.json',
                           'GITHUB_OUTPUT': str(output)}
            def select(*args, outputs, **kwargs):
                outputs['pages_publication_sha'] = publication
                return 'worker'
            with (patch.dict(os.environ, environment),
                  patch.object(candidate, 'read_json', return_value=event),
                  patch.object(handoff, 'automatic_handoff', side_effect=select),
                  patch.object(handoff, 'protected_publication') as protected):
                handoff.main(['--service', 'award-api'])
                protected.assert_not_called()  # Output must carry the already authenticated selection.
            self.assertEqual(output.read_text(encoding='utf-8'),
                             f'route=worker\npages_publication_sha={publication}\n')

    def test_unknown_service_is_rejected_before_reading_release_evidence(self):
        api = Mock()
        with self.assertRaisesRegex(ValueError, 'Unknown Worker'):
            handoff.automatic_handoff(Path('checkout'), 'owner/repo', {}, api=api, service='search')
        api.assert_not_called()


class RetainedWorkerPublicationTests(unittest.TestCase):
    repository = 'owner/repo'

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        files = {}
        for name in handoff.ALERTS_PAGES_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('exact ' + name).encode())
            files[name] = candidate.digest(path.read_bytes())
        self.head = 'e' * 40
        self.manifest = {'candidate_id': 'c' * 64, 'files': files, 'generation_sha': 'd' * 40,
                         'generation_run_id': '101', 'release_identity': {'catalog': 'exact'}}
        self.validation = {'candidate_id': self.manifest['candidate_id'], 'validation_sha': 'a' * 40,
                           'identity': {'candidate_hashes': files},
                           'gates': dict.fromkeys(candidate.GATES, 'passed')}
        self.publication = {'schema_version': 1, 'candidate_id': self.manifest['candidate_id'],
                            'candidate_hashes': files, 'generation_sha': 'd' * 40, 'generation_run_id': '101',
                            'validation_sha': 'a' * 40, 'release_code_sha': 'b' * 40,
                            'publication_sha': 'a' * 40,
                            'validation_receipt_sha256': candidate.digest(candidate.encoded(self.validation))}
        self.live = self.live_receipt()
        self.rows = [self.artifact(1, 510, 'publication', 1), self.artifact(2, 511, 'live', 1)]
        self.jobs = {510: {1: {'publish': 'success'}}, 511: {1: {'verify-live': 'success'}},
                     512: {1: {'plan': 'success', 'verify-live': 'skipped', 'closeout': 'success'}}}
        self.heads = {510: 'b' * 40, 511: 'b' * 40, 512: self.head}
        self.chain = '\n'.join((self.head, 'a' * 40, 'b' * 40))
        candidate.write_json(self.root / 'release/candidate.json', self.manifest)
        self.addCleanup(patch.stopall)
        self.git_patch = patch.object(candidate, 'git', side_effect=self.git)
        self.git_patch.start()
        self.committed_patch = patch.object(handoff, 'committed_candidate_matches', return_value=True)
        self.committed = self.committed_patch.start()
        patch.object(handoff, 'repository_artifacts', side_effect=lambda *args, **kwargs: self.rows).start()
        patch.object(handoff.history, 'workflow_job_names',
                     return_value={'plan', 'publish', 'pages', 'verify-live', 'closeout'}).start()
        verify_pages = handoff.verify_pages_identity
        patch.object(handoff, 'verify_pages_identity',
                     side_effect=lambda m, p: verify_pages(m, p, http=self.http, attempts=1)).start()

    def artifact(self, identifier, run, kind, attempt):
        moment = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(seconds=run * 10 + attempt)
        return {'id': identifier, 'name': f'{kind}-{self.manifest["candidate_id"]}-{attempt}',
                'created_at': moment.isoformat().replace('+00:00', 'Z'),
                'expired': False, 'workflow_run': {'id': run}}

    def live_receipt(self):
        return {'verified': True, 'candidate_id': self.manifest['candidate_id'],
                'publication_sha': self.publication['publication_sha'],
                'publication_receipt_sha256': candidate.digest(candidate.encoded(self.publication)),
                'differences': [], 'asset_verification': 'success', 'provider_smoke': 'success',
                'worker_provenance': {'verified': True}, 'live_release_identity': self.manifest['release_identity']}

    def git(self, root, command, *_):
        return {'rev-list': self.chain, 'rev-parse': self.head,
                'log': 'a' * 40, 'diff': 'workers/award-api/src/index.js'}[command]

    def metadata(self, run, attempt=None):
        return {'id': run, 'run_attempt': attempt or max(self.jobs[run]),
                'path': handoff.history.WORKFLOW, 'head_branch': 'main', 'head_sha': self.heads[run],
                'head_repository': {'full_name': self.repository}, 'event': 'push',
                'status': 'completed', 'conclusion': 'success'}

    def api(self, path):
        parts = path.split('/')
        run = int(parts[2])
        if len(parts) == 3:
            return json.dumps(self.metadata(run))
        attempt = int(parts[4])
        metadata = self.metadata(run, attempt)
        if len(parts) == 5:
            return json.dumps(metadata)
        jobs = [dict(metadata, id=index, run_id=run, name=name, conclusion=conclusion)
                for index, (name, conclusion) in enumerate(self.jobs[run][attempt].items(), 1)]
        return json.dumps({'total_count': len(jobs), 'jobs': jobs})

    def download(self, repository, run, name, destination):
        candidate.write_json(destination / 'publication.json', self.publication)
        candidate.write_json(destination / 'validation.json', self.validation)
        if name.startswith('live-'):
            candidate.write_json(destination / 'live-verification.json', self.live)

    def http(self, url):
        path = url.removeprefix(handoff.SITE).split('?')[0]
        return {'release/candidate.json': candidate.encoded(self.manifest),
                'release/publication.json': candidate.encoded(self.publication),
                'pages-release-sha.txt': (self.publication['publication_sha'] + '\n').encode()}[path]

    def route(self, outputs=None):
        with (patch.object(handoff, 'candidate_groups'), patch.object(handoff, 'snapshot'),
              patch.object(handoff, 'changed_groups', return_value={'validation': ['tools/validator.py']})):
            return handoff.automatic_handoff(self.root, self.repository, self.metadata(512),
                api=self.api, download=self.download, service='award-api', outputs=outputs)

    def test_worker_route_carries_one_exact_authenticated_publication(self):
        outputs = {}
        self.assertEqual(self.route(outputs), 'worker')
        self.assertEqual(outputs, {'pages_publication_sha': self.publication['publication_sha']})
        self.committed.assert_called_once_with(self.root, self.publication['publication_sha'], self.manifest)

    def test_old_pointer_hint_cannot_redeploy_work_already_in_the_serving_publication(self):
        def git(root, command, *arguments):
            if command == 'log':
                return 'b' * 40
            if command == 'diff':
                return 'workers/award-api/src/index.js' if arguments[2] == 'b' * 40 else ''
            return self.git(root, command, *arguments)
        outputs = {}
        with patch.object(candidate, 'git', side_effect=git):
            self.assertEqual(self.route(outputs), 'skip')
        self.assertEqual(outputs, {})

    def test_pages_and_live_retry_inherits_the_successful_earlier_publication(self):
        self.rows[1] = self.artifact(2, 510, 'live', 2)
        self.jobs[510] = {1: {'publish': 'success', 'pages': 'failure'},
                          2: {'pages': 'success', 'verify-live': 'success', 'closeout': 'success'}}
        self.assertEqual(self.route(), 'worker')

    def test_newer_failed_native_producer_cannot_borrow_older_live_success(self):
        self.jobs[511][2] = {'verify-live': 'failure', 'closeout': 'failure'}
        with self.assertRaisesRegex(ValueError, 'exact successful producer'):
            self.route()

    def test_newer_publication_attempt_without_live_evidence_does_not_fall_back(self):
        self.rows.append(self.artifact(3, 510, 'publication', 2))
        self.jobs[510][2] = {'publish': 'failure'}
        with self.assertRaisesRegex(ValueError, 'exact successful producer'):
            self.route()

    def test_latest_incomplete_or_conflicting_receipt_is_not_an_older_pass(self):
        original = self.download
        def incomplete(repository, run, name, destination):
            if name.startswith('publication-'):
                candidate.write_json(destination / 'review-ready.json', {})
            else:
                original(repository, run, name, destination)
        with self.assertRaises(FileNotFoundError):
            handoff.protected_publication(self.root, self.repository, self.manifest,
                                         api=self.api, download=incomplete)
        self.rows.append(deepcopy(self.rows[-1]))
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            self.route()

    def test_latest_publication_must_match_the_exact_live_receipt(self):
        original = self.download
        def conflicting(repository, run, name, destination):
            original(repository, run, name, destination)
            if name.startswith('live-'):
                candidate.write_json(destination / 'publication.json', dict(self.publication, timestamp='older'))
        with self.assertRaisesRegex(ValueError, 'matching live evidence'):
            handoff.protected_publication(self.root, self.repository, self.manifest,
                                         api=self.api, download=conflicting)

    def test_publication_candidate_and_validation_bindings_cannot_change(self):
        original = deepcopy(self.publication)
        for field, value in (('candidate_id', 'f' * 64), ('candidate_hashes', {}),
                             ('validation_receipt_sha256', 'f' * 64)):
            self.publication = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'exact candidate'):
                self.route()

    def test_publication_and_producer_must_be_protected_and_committed_bytes_exact(self):
        self.chain = self.head
        with self.assertRaisesRegex(ValueError, 'outside protected'):
            self.route()
        self.chain = '\n'.join((self.head, 'a' * 40, 'b' * 40))
        self.committed.return_value = False
        with self.assertRaisesRegex(ValueError, 'exact candidate bytes'):
            self.route()

    def test_failed_or_rebound_live_receipt_cannot_authorize_worker_route(self):
        original = deepcopy(self.live)
        for field, value in (('verified', False), ('publication_receipt_sha256', 'f' * 64),
                             ('provider_smoke', 'failure'), ('worker_provenance', {'verified': False})):
            self.live = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'exact successful live'):
                self.route()

    def test_same_candidate_idempotent_republish_uses_the_new_receipt_not_pointer_history(self):
        from tests.test_release_candidate import CandidateLifecycleTests
        from tools import publish_release_candidate as publisher
        from tools.validate_release_candidate import validate
        self.git_patch.stop()
        self.committed_patch.stop()
        lifecycle = CandidateLifecycleTests()
        self.addCleanup(lifecycle.doCleanups)
        lifecycle.setUp()
        for name in ('match_explorer.html', 'funded_awards.html'):
            (lifecycle.root / name).write_text('<main>same retained package</main>', encoding='utf-8')
            lifecycle.policy['runtime'].append(name)
        candidate.write_json(lifecycle.root / candidate.POLICY, lifecycle.policy)
        lifecycle.commit()
        lifecycle.source_sha = candidate.git(lifecycle.root, 'rev-parse', 'HEAD')
        manifest = lifecycle.create()
        validate(lifecycle.root, lifecycle.bundle, lifecycle.reports, execute=lifecycle.execute([]))
        candidate.write_json(lifecycle.root / 'release/candidate.json', manifest)
        candidate.write_json(lifecycle.root / 'release/candidate-source.json',
                             {'candidate_id': manifest['candidate_id'], 'artifact_run': '123'})
        lifecycle.commit()
        old_pointer_sha = candidate.git(lifecycle.root, 'rev-parse', 'HEAD')
        (lifecycle.root / 'tools/validator.py').write_text('VERSION = 2\n')
        lifecycle.commit()
        republished_sha = candidate.git(lifecycle.root, 'rev-parse', 'HEAD')
        validation = validate(lifecycle.root, lifecycle.bundle, lifecycle.reports, execute=lifecycle.execute([]))
        with (patch.object(candidate, 'ROOT', lifecycle.root),
              patch.dict(os.environ, {'GITHUB_REPOSITORY': self.repository}),
              patch.object(publisher, 'run', return_value=republished_sha + '\trefs/heads/main')):
            ready = publisher.prepare(lifecycle.bundle, lifecycle.reports / 'validation.json', lifecycle.reports, '123')
            self.assertIsNone(ready['pr_url'])
            publication = publisher.publish(lifecycle.bundle, lifecycle.reports / 'validation.json',
                lifecycle.reports, '123', prepared=lifecycle.reports / 'review-ready.json')
        self.assertEqual(publication['publication_sha'], republished_sha)
        self.assertNotEqual(old_pointer_sha, republished_sha)
        self.assertEqual(candidate.git(lifecycle.root, 'log', '--first-parent', '-1', '--format=%H', '--',
                                       'release/candidate-source.json'), old_pointer_sha)
        worker = lifecycle.root / 'workers/award-api/src/index.js'
        worker.parent.mkdir(parents=True, exist_ok=True)
        worker.write_text('export default {};\n')
        lifecycle.commit()
        self.root, self.manifest, self.validation, self.publication = lifecycle.root, manifest, validation, publication
        self.head = candidate.git(self.root, 'rev-parse', 'HEAD')
        self.heads = {510: republished_sha, 511: republished_sha, 512: self.head}
        self.live = self.live_receipt()
        self.rows = [self.artifact(1, 510, 'publication', 1), self.artifact(2, 511, 'live', 1)]
        outputs = {}
        self.assertEqual(self.route(outputs), 'worker')
        self.assertEqual(outputs['pages_publication_sha'], republished_sha)


class RetainedPagesIdentityTests(unittest.TestCase):
    def test_pages_candidate_receipt_and_marker_must_all_match_with_bounded_propagation(self):
        manifest = {'candidate_id': 'c' * 64}
        publication = {'publication_sha': 'a' * 40}
        expected = {'release/candidate.json': candidate.encoded(manifest),
                    'release/publication.json': candidate.encoded(publication),
                    'pages-release-sha.txt': ('a' * 40 + '\n').encode()}
        for path in expected:
            requests = []
            def http(url):
                name = url.removeprefix(handoff.SITE).split('?')[0]
                requests.append(name)
                return b'{}' if name == path else expected[name]
            sleep = Mock()
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'current Pages publication'):
                handoff.verify_pages_identity(manifest, publication, http=http, sleep=sleep, attempts=3)
            self.assertEqual(len(requests), 9)
            self.assertEqual(sleep.call_count, 2)
        requests = []
        def propagating(url):
            name = url.removeprefix(handoff.SITE).split('?')[0]
            requests.append(name)
            return b'{}' if name == 'release/candidate.json' and requests.count(name) == 1 else expected[name]
        sleep = Mock()
        handoff.verify_pages_identity(manifest, publication, http=propagating, sleep=sleep, attempts=3)
        self.assertEqual(len(requests), 6)
        sleep.assert_called_once_with(5)


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
