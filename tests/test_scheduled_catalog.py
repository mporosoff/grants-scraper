"""Hermetic scheduled retry decisions: never purchase replacement generation."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import release_candidate as c, scheduled_catalog as scheduled


ENV = {'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '300'}
NOW = datetime(2026, 9, 28, 18, 17, tzinfo=timezone.utc)


def candidate(root, generated='2026-09-28T10:30:00Z', run='100'):
    raw = ('globalThis.GRANT_CATALOG_METADATA=' + json.dumps({
        'schema_version': 1, 'generated_at': generated,
        'pipeline_generated_at': '2026-09-28T17:00:00Z'}) + ';\n').encode()
    path = root / scheduled.METADATA
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    manifest = {'schema_version': 1, 'candidate_format': c.VERSION, 'generation_run_id': run,
                'generation_sha': 'a' * 40, 'release_identity': {'current_corpus_sha256': 'b' * 64},
                'files': {scheduled.METADATA: c.digest(raw)}}
    manifest['candidate_id'] = c.digest(c.encoded(manifest))
    return manifest


def publication(manifest):
    validation = {'candidate_id': manifest['candidate_id'], 'validation_sha': 'a' * 40,
                  'identity': {'candidate_hashes': manifest['files']},
                  'gates': {gate: 'passed' for gate in c.GATES}}
    receipt = {'schema_version': 1, 'candidate_id': manifest['candidate_id'],
               'candidate_hashes': manifest['files'], 'generation_sha': manifest['generation_sha'],
               'generation_run_id': manifest['generation_run_id'], 'validation_sha': 'a' * 40,
               'validation_receipt_sha256': c.digest(c.encoded(validation)),
               'publication_sha': 'b' * 40, 'release_code_sha': 'a' * 40}
    return {'receipt': receipt, 'validation': validation, 'pages_complete': True, 'run': '210', 'attempt': '2'}


def live(manifest, published):
    return {'candidate_id': manifest['candidate_id'], 'verified': True,
            'asset_verification': 'success', 'provider_smoke': 'success',
            'completed_at': '2026-09-28T17:30:00Z', 'publication_sha': published['receipt']['publication_sha'],
            'publication_receipt_sha256': c.digest(c.encoded(published['receipt'])),
            'live_release_identity': manifest['release_identity']}


class ScheduledDecisions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.saved = self.root / 'saved'
        self.saved.mkdir()
        self.manifest = self.current()
        self.base = {'stage': 'generate', 'candidate_run': '100',
                     'candidate_id': self.manifest['candidate_id'], 'changes': {},
                     'runtime_changes': [], 'receipt_run': '110', 'receipt_current': True}
        for name, value in [('prior_generation', None), ('snapshot', {}), ('candidate_groups', {}),
                            ('changed_groups', {})]:
            mocked = patch.object(scheduled, name, return_value=value).start()
            self.addCleanup(patch.stopall)
            setattr(self, name, mocked)
        self.deps = patch.object(c, 'verify_dependencies', return_value='compatible').start()
        self.identity = {'validation': 'same'}
        patch.object(c, 'validation_identity', return_value=self.identity).start()
        self.download = patch.object(scheduled, 'fetch', side_effect=self.fetch).start()
        self.reports = Mock(return_value=('', None))

    def current(self, generated='2026-09-28T10:30:00Z'):
        manifest = candidate(self.root, generated)
        c.write_json(self.root / 'release/candidate.json', manifest)
        self.published = publication(manifest)
        self.verified = live(manifest, self.published)
        return manifest

    def fetch(self, repository, run, name, destination):
        self.assertEqual(repository, ENV['GITHUB_REPOSITORY'])
        shutil.copytree(self.saved / name, destination)

    def retained(self, generated='2026-09-28T10:30:00Z', run='200'):
        build = self.root / ('build-' + run)
        manifest = candidate(build / 'files', generated, run)
        c.write_json(build / c.MANIFEST, manifest)
        shutil.move(str(build), self.saved / ('candidate-' + manifest['candidate_id']))
        return manifest

    def resolve(self, **kwargs):
        return scheduled.resolve(self.root, ENV, self.base, self.root / 'reports',
                                 live=self.verified, publication=self.published,
                                 reports=self.reports, now=NOW, **kwargs)

    def test_repeated_schedules_skip_exact_completed_daily_refresh(self):
        for _ in range(2):
            value = self.resolve()
            self.assertEqual((value['stage'], value['daily_status']), ('noop', 'already_current'))
            self.assertEqual(value['daily_window_start'], '2026-09-28T10:17:00Z')
            self.assertEqual(value['catalog_generated_at'], '2026-09-28T10:30:00Z')
            self.assertIs(value['live_verified'], True)
        self.download.assert_not_called()

    def test_new_day_uses_source_generation_not_new_pipeline_or_live_dates(self):
        self.manifest = self.current('2026-09-27T10:30:00Z')
        value = self.resolve()
        self.assertEqual((value['stage'], value['daily_status']), ('generate', 'due'))
        self.assertEqual(value['catalog_generated_at'], '2026-09-27T10:30:00Z')
        self.download.assert_not_called()

    def test_future_source_and_mismatched_metadata_hold(self):
        for invalid in ('future', 'mismatch'):
            with self.subTest(invalid=invalid):
                self.current('2026-09-29T10:30:00Z' if invalid == 'future' else '2026-09-28T10:30:00Z')
                if invalid == 'mismatch':
                    (self.root / scheduled.METADATA).write_text('changed')
                value = self.resolve()
                self.assertEqual((value['stage'], value['daily_status']), ('noop', 'held'))
        self.download.assert_not_called()

    def test_missing_metadata_holds_instead_of_regenerating(self):
        (self.root / scheduled.METADATA).unlink()
        self.assertEqual(self.resolve()['daily_status'], 'held')

    def test_fresh_day_preserves_supported_dependency_stages_and_disabled_teams(self):
        for group, ready, expected in [('source', True, 'generate'), ('semantic', True, 'generate'),
                                      ('runtime', True, 'reuse'), ('teams', True, 'teams'),
                                      ('teams', False, 'noop'), ('validation', False, 'noop')]:
            with self.subTest(group=group, ready=ready):
                self.base.update(changes={group: ['changed']}, team_generation_ready=ready,
                                 runtime_changes=['changed'] if group == 'runtime' else [])
                value = self.resolve()
                self.assertEqual(value['stage'], expected)
                status = 'already_current' if group == 'validation' else 'held' if expected == 'noop' else 'due'
                self.assertEqual(value['daily_status'], status)

    def test_incomplete_or_mismatched_live_proof_cannot_skip(self):
        for override in ({'provider_smoke': 'failure'}, {'completed_at': None},
                         {'publication_receipt_sha256': 'bad'}, {'live_release_identity': {}}, {'verified': False}):
            with self.subTest(override=override):
                self.verified = live(self.manifest, self.published) | override
                self.download.side_effect = ValueError('Retained evidence unavailable')
                value = self.resolve()
                self.assertEqual(value['daily_status'], 'held')
                self.assertEqual(value['recovery_run'], '100')

    def test_recovery_precedes_fresh_current_catalog_and_keeps_original_owner(self):
        retained = self.retained()
        self.prior_generation.return_value = ('200', retained['candidate_id'])
        self.reports.side_effect = [('205', {'identity': self.identity,
                                          'gates': {gate: 'passed' for gate in c.GATES}}), ('', None)]
        value = self.resolve()
        self.assertEqual((value['stage'], value['daily_status']), ('publish', 'recovering'))
        self.assertEqual((value['candidate_run'], value['recovery_run'], value['receipt_run']), ('200', '200', '205'))
        self.assertEqual(value['candidate_id'], retained['candidate_id'])
        self.deps.assert_called_once()

    def test_yesterdays_candidate_recovers_first_but_is_not_counted_fresh(self):
        retained = self.retained('2026-09-27T10:30:00Z')
        self.prior_generation.return_value = ('200', retained['candidate_id'])
        value = self.resolve()
        self.assertEqual((value['stage'], value['daily_status']), ('publish', 'recovering'))
        self.assertLess(value['catalog_generated_at'], value['daily_window_start'])

    def test_completed_pages_recover_verify_with_exact_publication_attempt(self):
        retained = self.retained()
        self.prior_generation.return_value = ('200', retained['candidate_id'])
        self.reports.side_effect = [('205', None), ('210', publication(retained))]
        value = self.resolve()
        self.assertEqual((value['stage'], value['publication_run'], value['publication_attempt']), ('verify', '210', '2'))

    def test_unchanged_failed_validation_holds_without_another_gate(self):
        retained = self.retained()
        self.prior_generation.return_value = ('200', retained['candidate_id'])
        self.reports.return_value = ('205', {'identity': self.identity, 'gates': {'python': 'failed'}})
        value = self.resolve()
        self.assertEqual((value['stage'], value['daily_status'], value['recovery_run']), ('noop', 'held', '200'))
        self.assertIn('failed unchanged validation', value['reason'])
        self.assertEqual(self.reports.call_count, 1)

    def test_changed_validation_allows_exact_candidate_revalidation(self):
        retained = self.retained()
        self.prior_generation.return_value = ('200', retained['candidate_id'])
        self.changed_groups.return_value = {'validation': ['fixed.py']}
        self.reports.side_effect = [('205', {'identity': {'validation': 'old'}, 'gates': {'python': 'failed'}}), ('', None)]
        self.assertEqual(self.resolve()['stage'], 'publish')

    def test_incompatible_candidate_and_failed_download_hold_named_original_run(self):
        retained = self.retained()
        self.prior_generation.return_value = ('200', retained['candidate_id'])
        self.deps.side_effect = ValueError('Generation dependencies changed')
        value = self.resolve()
        self.assertEqual((value['daily_status'], value['recovery_run']), ('held', '200'))
        self.assertIn('Original run: 200', value['reason'])

    def test_pending_publication_and_same_run_resume_keep_priority(self):
        retained = self.retained(run='300')
        self.base.update(candidate_run='300', candidate_id=retained['candidate_id'])
        value = self.resolve(explicit_resume=True)
        self.assertEqual((value['stage'], value['candidate_run']), ('publish', '300'))
        self.prior_generation.assert_not_called()


class ScheduledHistory(unittest.TestCase):
    def setUp(self):
        self.runs = [self.workflow_run(200), self.workflow_run(100)]
        self.artifacts = {'200': []}
        self.jobs = {'200': [{'name': name, 'conclusion': 'skipped'} for name in ('generate', 'assemble')]}
        self.api = patch.object(scheduled, 'api', side_effect=self.response).start()
        self.published = patch.object(scheduled, '_published', return_value=set()).start()
        self.addCleanup(patch.stopall)

    @staticmethod
    def workflow_run(identifier, **overrides):
        return {'id': identifier, 'path': scheduled.WORKFLOW, 'head_branch': 'main', 'event': 'schedule',
                'status': 'completed', 'run_attempt': 1} | overrides

    def response(self, repository, path):
        self.assertEqual(repository, ENV['GITHUB_REPOSITORY'])
        self.assertIn('per_page=100&page=', path)
        if path.startswith('actions/workflows/'):
            return json.dumps({'workflow_runs': self.runs})
        run = path.split('/')[2]
        return json.dumps({'artifacts': self.artifacts[run]} if '/artifacts?' in path else {'jobs': self.jobs[run]})

    def discover(self):
        return scheduled.prior_generation(Path('unused'), ENV, {'generation_run_id': '100'})

    def guard_push(self, *, environment=None, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = candidate(root)
            if corrupt:
                manifest['generation_run_id'] = '200'
            c.write_json(root / 'release/candidate.json', manifest)
            return scheduled.hold_competing_generation(root, ENV | {'GITHUB_EVENT_NAME': 'push'} | (environment or {}),
                {'stage': 'generate', 'release_sha': 'a' * 40, 'candidate_id': manifest['candidate_id'],
                 'candidate_run': '100'})

    def test_push_guard_uses_retained_reservation_and_unpublished_candidate_ownership(self):
        for name in ('generation-spend-reservation-200-1', 'candidate-' + 'c' * 64):
            with self.subTest(artifact=name):
                self.artifacts['200'] = [{'name': name, 'expired': False}]
                value = self.guard_push()
                self.assertEqual((value['stage'], value['held_stage'], value['recovery_run']), ('noop', 'generate', '200'))
                self.assertEqual(value['candidate_run'], '100')
                self.assertNotIn('daily_status', value)

    def test_push_guard_keeps_published_noop_and_current_owner_recovery_paths(self):
        self.assertEqual(self.guard_push()['stage'], 'generate')
        self.artifacts['200'] = [{'name': 'candidate-' + 'c' * 64, 'expired': False}]
        self.published.return_value = {('200', 'c' * 64)}
        self.assertEqual(self.guard_push()['stage'], 'generate')
        self.published.return_value = set()
        self.artifacts['200'] = [{'name': 'generation-spend-reservation-200-1', 'expired': False}]
        self.api.reset_mock()
        value = self.guard_push(environment={'GITHUB_RUN_ID': '200', 'GITHUB_RUN_ATTEMPT': '4'})
        self.assertEqual(value['stage'], 'generate')
        self.assertFalse(any('/200/artifacts?' in call.args[1] for call in self.api.call_args_list),
                         'The original run restores its own allowance in the spend checkpoint step')

    def test_push_guard_holds_ambiguous_missing_or_invalid_history(self):
        self.artifacts['200'] = [{'name': 'candidate-' + char * 64, 'expired': False} for char in ('c', 'd')]
        self.assertEqual(self.guard_push()['stage'], 'noop')
        self.runs.insert(0, self.workflow_run(250))
        self.artifacts['250'] = [self.artifacts['200'].pop()]
        self.assertIn('Multiple unfinished generation runs', self.guard_push()['reason'])
        self.runs = [self.workflow_run(200)]
        self.artifacts['200'] = []
        self.assertIn('boundary is missing', self.guard_push()['reason'])
        self.runs = [self.workflow_run(200, status='in_progress'), self.workflow_run(100)]
        self.assertIn('still pending', self.guard_push()['reason'])
        self.api.reset_mock()
        self.assertIn('Protected candidate identity is invalid', self.guard_push(corrupt=True)['reason'])
        self.api.assert_not_called()

    def test_noop_runs_do_not_hide_a_future_due_generation(self):
        self.assertIsNone(self.discover())

    def test_cancelled_first_attempt_with_no_jobs_or_artifacts_never_started(self):
        self.runs[0]['conclusion'] = 'cancelled'
        self.jobs['200'] = []
        self.assertIsNone(self.discover())
        self.assertTrue(any('/200/jobs?' in call.args[1] for call in self.api.call_args_list))
        self.assertTrue(any('/200/artifacts?' in call.args[1] for call in self.api.call_args_list))

    def test_empty_jobs_only_prove_no_start_for_conclusive_cancelled_first_attempt(self):
        self.jobs['200'] = []
        cases = [{'conclusion': conclusion} for conclusion in ('success', 'failure', 'skipped', None)]
        cases += [{'conclusion': 'cancelled', 'run_attempt': attempt} for attempt in (2, 3, '1', None)]
        cases += [{'conclusion': 'cancelled', 'status': 'in_progress'}]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.runs[0] = self.workflow_run(200, **overrides)
                with self.assertRaises((scheduled.Hold, TypeError, ValueError)):
                    self.discover()
        self.runs[0] = self.workflow_run(200, conclusion='cancelled')
        del self.runs[0]['run_attempt']
        with self.assertRaises(scheduled.Hold):
            self.discover()

    def test_cancelled_run_with_started_jobs_or_retained_artifacts_is_not_ignored(self):
        self.runs[0]['conclusion'] = 'cancelled'
        for jobs in ([{'name': 'plan', 'conclusion': 'cancelled'}],
                     [{'name': 'generate', 'conclusion': 'cancelled'}],
                     [{'name': name, 'conclusion': 'cancelled'} for name in ('generate', 'assemble')]):
            with self.subTest(jobs=jobs):
                self.jobs['200'] = jobs
                with self.assertRaises(scheduled.Hold):
                    self.discover()
        self.jobs['200'] = []
        for name in ('generation-spend-reservation-200-1', 'generation-spend-state-200-1', 'release-plan'):
            with self.subTest(artifact=name):
                self.artifacts['200'] = [{'name': name, 'expired': False}]
                with self.assertRaises(scheduled.Hold):
                    self.discover()
        self.artifacts['200'] = [{'name': 'candidate-' + 'c' * 64, 'expired': False}]
        self.assertEqual(self.discover(), ('200', 'c' * 64), 'A complete candidate keeps its recovery owner')

    def test_retained_candidate_selects_original_run(self):
        self.artifacts['200'] = [{'name': 'candidate-' + 'c' * 64, 'expired': False}]
        self.assertEqual(self.discover(), ('200', 'c' * 64))

    def test_published_derived_candidate_is_not_an_unfinished_generation(self):
        self.artifacts['200'] = [{'name': 'candidate-' + 'c' * 64, 'expired': False}]
        self.published.return_value = {('200', 'c' * 64)}
        self.assertIsNone(self.discover())

    def test_identity_child_publication_uses_original_owner_floor_without_retirement_exception(self):
        parent_id, child_id = 'c' * 64, 'd' * 64
        self.artifacts['200'] = [{'name': 'candidate-' + parent_id, 'expired': False}]
        self.assertEqual(self.discover(), ('200', parent_id))
        self.assertEqual(self.guard_push()['recovery_run'], '200')
        self.runs.insert(0, self.workflow_run(250))
        self.artifacts['250'] = [{'name': 'candidate-' + child_id, 'expired': False}]
        with self.assertRaisesRegex(scheduled.Hold, 'Multiple unfinished'):
            self.discover()
        self.published.return_value = {('250', child_id)}
        self.api.reset_mock()
        # The authenticated published child retains its parent's generation run.
        # That existing source floor excludes the rejected parent without a new
        # blanket exemption for correction artifacts or their receipts.
        manifest = {'generation_run_id': '200'}
        self.assertIsNone(scheduled.prior_generation(Path('unused'), ENV, manifest))
        self.assertFalse(any('/200/artifacts?' in call.args[1] for call in self.api.call_args_list))
        self.runs.insert(0, self.workflow_run(275))
        self.artifacts['275'] = [{'name': 'candidate-' + 'e' * 64, 'expired': False}]
        self.assertEqual(scheduled.prior_generation(Path('unused'), ENV, manifest), ('275', 'e' * 64))

    def test_reserved_allowance_without_candidate_holds_its_owner(self):
        self.artifacts['200'] = [{'name': 'generation-spend-reservation-200-1', 'expired': False}]
        with self.assertRaises(scheduled.Hold) as raised:
            self.discover()
        self.assertEqual(raised.exception.run, '200')
        self.assertIn('no complete candidate', str(raised.exception))

    def test_missing_evidence_after_generation_cannot_create_another_allowance(self):
        for conclusion in ('success', 'failure', 'cancelled', None):
            with self.subTest(conclusion=conclusion):
                self.jobs['200'][0]['conclusion'] = conclusion
                with self.assertRaises(scheduled.Hold):
                    self.discover()

    def test_correction_reservation_without_candidate_holds_original_owner(self):
        self.artifacts['200'] = [{'name': 'program-area-vectors-' + 'c' * 64 + '-reservation-200-1', 'expired': False}]
        with self.assertRaises(scheduled.Hold) as raised:
            self.discover()
        self.assertEqual(raised.exception.run, '200')
        self.assertIn('no complete candidate', str(raised.exception))

    def test_started_correction_without_evidence_cannot_be_ignored(self):
        for name in ('program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction', 'catalog-identity-correction', 'catalog-url-correction'):
            for conclusion in ('success', 'failure', 'cancelled', None):
                with self.subTest(producer=name, conclusion=conclusion):
                    self.jobs['200'] = [{'name': job, 'conclusion': 'skipped'} for job in ('generate', 'assemble')]
                    self.jobs['200'].append({'name': name, 'conclusion': conclusion})
                    with self.assertRaises(scheduled.Hold):
                        self.discover()
                    self.assertEqual(self.guard_push()['stage'], 'noop')
            self.jobs['200'][-1]['conclusion'] = 'skipped'
            self.assertIsNone(self.discover())

    def test_all_five_skipped_correction_jobs_preserve_no_owner_planning(self):
        self.jobs['200'].extend({'name': name, 'conclusion': 'skipped'} for name in
            ('program-area-revalidation', 'catalog-source-recovery', 'catalog-access-correction', 'catalog-identity-correction', 'catalog-url-correction'))
        self.assertIsNone(self.discover())
        self.assertEqual(self.guard_push()['stage'], 'generate')

    def test_prior_rerun_missing_earlier_attempt_evidence_holds(self):
        self.runs[0]['run_attempt'] = 2
        with self.assertRaises(scheduled.Hold):
            self.discover()

    def test_ambiguous_candidate_or_multiple_owners_hold(self):
        self.artifacts['200'] = [{'name': 'candidate-' + char * 64, 'expired': False} for char in ('c', 'd')]
        with self.assertRaises(scheduled.Hold):
            self.discover()
        self.runs.insert(0, self.workflow_run(250))
        self.artifacts['250'] = [self.artifacts['200'].pop()]
        with self.assertRaisesRegex(scheduled.Hold, 'Multiple unfinished generation runs'):
            self.discover()

    def test_expired_unpublished_candidate_and_untrusted_origin_hold(self):
        self.artifacts['200'] = [{'name': 'candidate-' + 'c' * 64, 'expired': True}]
        with self.assertRaises(scheduled.Hold):
            self.discover()
        self.artifacts['200'][0]['expired'] = False
        self.runs[0]['head_branch'] = 'untrusted'
        with self.assertRaises(scheduled.Hold):
            self.discover()

    def test_missing_history_boundary_and_active_prior_run_hold(self):
        self.runs.pop()
        with self.assertRaisesRegex(scheduled.Hold, 'boundary is missing'):
            self.discover()
        self.runs = [self.workflow_run(200, status='in_progress'), self.workflow_run(100)]
        with self.assertRaisesRegex(scheduled.Hold, 'still pending'):
            self.discover()

    def test_bounded_history_cannot_fall_through_to_paid_generation(self):
        self.runs = [self.workflow_run(350)] * 100
        with patch.object(scheduled, 'MAX_PAGES', 2), self.assertRaisesRegex(scheduled.Hold, 'bounded recovery'):
            self.discover()
        self.assertEqual(self.api.call_count, 2)


class AccessParentSupersession(unittest.TestCase):
    def setUp(self):
        from tools import catalog_access_correction as access
        self.access = access
        self.run = {'id': access.RUN, 'run_attempt': access.ATTEMPT, 'head_sha': access.EVENT_SHA,
                    'head_branch': 'main', 'path': scheduled.WORKFLOW, 'event': 'workflow_dispatch',
                    'status': 'completed', 'conclusion': 'failure'}
        self.artifacts = [{'id': ident, 'name': name, 'digest': 'sha256:' + digest, 'expired': False}
                          for ident, name, digest in access.ARTIFACTS.values()]
        self.child = {'generation_run_id': '36896442720', 'derived_from_candidate': access.PARENT,
                      'source_recovery': {'affected_generation': {'generation_run_id': str(access.RUN),
                          'generation_run_attempt': str(access.ATTEMPT), 'generation_sha': access.EVENT_SHA}},
                      'access_correction': {'version': access.VERSION, 'parent_candidate': access.PARENT,
                          'parent_run': access.RUN, 'parent_manifest_sha256': access.MANIFEST_SHA,
                          'affected_generation': {'generation_run_id': '40000000000'}}}
        self.seal()
        self.git = patch.object(c, 'git', side_effect=self.git_read).start()
        self.addCleanup(patch.stopall)

    def seal(self):
        self.child.pop('candidate_id', None)
        self.child['candidate_id'] = c.digest(c.encoded(self.child))
        self.pointer = {'candidate_id': self.child['candidate_id'], 'artifact_run': '40000000000'}

    def git_read(self, root, *args):
        if args[0] == 'log':
            return 'published-revision'
        return json.dumps(self.pointer if args[-1].endswith('candidate-source.json') else self.child)

    def superseded(self):
        return scheduled._published_access_supersedes(Path('unused'), self.run, self.artifacts)

    def test_exact_published_child_retires_only_its_unchanged_parent(self):
        self.assertTrue(self.superseded())
        self.run['id'] += 1
        self.assertFalse(self.superseded())

    def test_runtime_descendant_does_not_hide_the_published_immediate_correction(self):
        from copy import deepcopy
        descendant = deepcopy(self.child)
        descendant['derived_from_candidate'] = self.child['candidate_id']
        descendant.pop('candidate_id')
        descendant['candidate_id'] = c.digest(c.encoded(descendant))
        def read(root, *args):
            if args[0] == 'log':
                return 'runtime-revision\npublished-revision'
            if args[-1].startswith('runtime-revision:'):
                return json.dumps({'artifact_run': '40500000000', 'candidate_id': descendant['candidate_id']}
                    if args[-1].endswith('candidate-source.json') else descendant)
            return self.git_read(root, *args)
        self.git.side_effect = read
        self.assertTrue(self.superseded())

    def test_absent_publication_and_unrelated_child_do_not_retire_parent(self):
        self.git.side_effect = lambda root, *args: '' if args[0] == 'log' else '{}'
        self.assertFalse(self.superseded())
        self.git.side_effect = self.git_read
        self.child['access_correction']['parent_candidate'] = 'c' * 64
        self.seal()
        self.assertFalse(self.superseded())

    def test_later_attempt_active_run_or_changed_origin_keep_recovery_owner(self):
        for key, value in [('run_attempt', 2), ('run_attempt', '1'), ('status', 'in_progress'),
                           ('head_sha', 'f' * 40), ('event', 'push'), ('conclusion', 'success')]:
            original = self.run[key]
            self.run[key] = value
            self.assertFalse(self.superseded(), key)
            self.run[key] = original

    def test_artifact_replacement_expiry_missing_receipt_and_new_reservation_fail_closed(self):
        for key, value in [('id', 1), ('digest', 'sha256:' + '0' * 64), ('expired', True)]:
            original = self.artifacts[0][key]
            self.artifacts[0][key] = value
            self.assertFalse(self.superseded(), key)
            self.artifacts[0][key] = original
        receipt = self.artifacts.pop()
        self.assertFalse(self.superseded())
        self.artifacts.append(receipt)
        self.artifacts.append({'name': 'generation-spend-reservation-' + str(self.access.RUN) + '-1'})
        self.assertFalse(self.superseded())
        self.artifacts[-1] = {'name': 'candidate-' + 'e' * 64}
        self.assertFalse(self.superseded())

    def test_invalid_published_identity_or_receipt_is_not_supersession(self):
        self.child['generation_run_id'] = 'bad'
        with self.assertRaises(scheduled.Hold):
            self.superseded()
        self.child['generation_run_id'] = '36896442720'
        self.child['access_correction']['parent_manifest_sha256'] = 'f' * 64
        self.seal()
        with self.assertRaises(scheduled.Hold):
            self.superseded()

    def test_prior_generation_skips_only_authenticated_superseded_candidate(self):
        boundary = {'id': 36896442720}
        batches = {'actions/workflows/refresh-opportunities.yml/runs?branch=main': [self.run, boundary],
                   'actions/runs/' + str(self.access.RUN) + '/artifacts': self.artifacts}
        with patch.object(scheduled, '_published', return_value={(self.pointer['artifact_run'], self.pointer['candidate_id'])}), \
             patch.object(scheduled, '_pages', side_effect=lambda repository, path, key: iter([batches[path]])):
            environment = ENV | {'GITHUB_RUN_ID': '41000000000'}
            self.assertIsNone(scheduled.prior_generation(Path('unused'), environment, {'generation_run_id': '36896442720'}))
            self.run['run_attempt'] = 2
            self.assertEqual(scheduled.prior_generation(Path('unused'), environment, {'generation_run_id': '36896442720'}),
                             (str(self.access.RUN), self.access.PARENT))


class UrlParentSupersession(unittest.TestCase):
    def setUp(self):
        from tools import catalog_url_correction as url
        self.url = url
        self.run = {'id': url.RUN, 'run_attempt': url.ATTEMPT, 'head_sha': url.EVENT_SHA,
                    'head_branch': 'main', 'path': scheduled.WORKFLOW, 'event': 'workflow_dispatch',
                    'status': 'completed', 'conclusion': 'failure'}
        self.artifacts = [{'id': ident, 'name': name, 'digest': 'sha256:' + digest, 'expired': False}
                          for ident, name, digest in url.ARTIFACTS.values()]
        self.child = {'generation_run_id': '38275115281', 'derived_from_candidate': url.PARENT,
                      'identity_correction': {'affected_generation': {'generation_run_id': str(url.RUN),
                          'generation_run_attempt': str(url.ATTEMPT), 'generation_sha': url.EVENT_SHA}},
                      'url_correction': {'version': url.VERSION, 'parent_candidate': url.PARENT,
                          'parent_run': url.RUN, 'parent_manifest_sha256': url.MANIFEST_SHA,
                          'affected_generation': {'generation_run_id': '40000000000'}}}
        self.seal()
        self.git = patch.object(c, 'git', side_effect=self.git_read).start()
        self.addCleanup(patch.stopall)

    def seal(self):
        self.child.pop('candidate_id', None)
        self.child['candidate_id'] = c.digest(c.encoded(self.child))
        self.pointer = {'candidate_id': self.child['candidate_id'], 'artifact_run': '40000000000'}

    def git_read(self, root, *args):
        if args[0] == 'log':
            return 'published-revision'
        return json.dumps(self.pointer if args[-1].endswith('candidate-source.json') else self.child)

    def superseded(self):
        return scheduled._published_url_supersedes(Path('unused'), self.run, self.artifacts)

    def test_exact_published_child_retires_only_its_unchanged_parent(self):
        self.assertTrue(self.superseded())
        self.run['id'] += 1
        self.assertFalse(self.superseded())

    def test_runtime_descendant_does_not_hide_the_published_immediate_correction(self):
        from copy import deepcopy
        descendant = deepcopy(self.child)
        descendant['derived_from_candidate'] = self.child['candidate_id']
        descendant.pop('candidate_id')
        descendant['candidate_id'] = c.digest(c.encoded(descendant))
        def read(root, *args):
            if args[0] == 'log':
                return 'runtime-revision\npublished-revision'
            if args[-1].startswith('runtime-revision:'):
                return json.dumps({'artifact_run': '40500000000', 'candidate_id': descendant['candidate_id']}
                    if args[-1].endswith('candidate-source.json') else descendant)
            return self.git_read(root, *args)
        self.git.side_effect = read
        self.assertTrue(self.superseded())

    def test_absent_publication_and_unrelated_child_do_not_retire_parent(self):
        self.git.side_effect = lambda root, *args: '' if args[0] == 'log' else '{}'
        self.assertFalse(self.superseded())
        self.git.side_effect = self.git_read
        self.child['url_correction']['parent_candidate'] = 'c' * 64
        self.seal()
        self.assertFalse(self.superseded())

    def test_later_attempt_active_run_or_changed_origin_keep_recovery_owner(self):
        for key, value in [('run_attempt', 2), ('run_attempt', '1'), ('status', 'in_progress'),
                           ('head_sha', 'f' * 40), ('event', 'push'), ('conclusion', 'success')]:
            original = self.run[key]
            self.run[key] = value
            self.assertFalse(self.superseded(), key)
            self.run[key] = original

    def test_artifact_replacement_expiry_missing_receipt_and_new_reservation_fail_closed(self):
        for key, value in [('id', 1), ('digest', 'sha256:' + '0' * 64), ('expired', True)]:
            original = self.artifacts[0][key]
            self.artifacts[0][key] = value
            self.assertFalse(self.superseded(), key)
            self.artifacts[0][key] = original
        receipt = self.artifacts.pop()
        self.assertFalse(self.superseded())
        self.artifacts.append(receipt)
        self.artifacts.append({'name': 'generation-spend-reservation-' + str(self.url.RUN) + '-1'})
        self.assertFalse(self.superseded())
        self.artifacts[-1] = {'name': 'candidate-' + 'e' * 64}
        self.assertFalse(self.superseded())

    def test_invalid_published_identity_or_receipt_is_not_supersession(self):
        self.child['generation_run_id'] = 'bad'
        with self.assertRaises(scheduled.Hold):
            self.superseded()
        self.child['generation_run_id'] = '38275115281'
        self.child['url_correction']['parent_manifest_sha256'] = 'f' * 64
        self.seal()
        with self.assertRaises(scheduled.Hold):
            self.superseded()

    def test_prior_generation_skips_only_authenticated_superseded_candidate(self):
        boundary = {'id': 38275115281}
        batches = {'actions/workflows/refresh-opportunities.yml/runs?branch=main': [self.run, boundary],
                   'actions/runs/' + str(self.url.RUN) + '/artifacts': self.artifacts}
        with patch.object(scheduled, '_published', return_value={(self.pointer['artifact_run'], self.pointer['candidate_id'])}), \
             patch.object(scheduled, '_pages', side_effect=lambda repository, path, key: iter([batches[path]])):
            environment = ENV | {'GITHUB_RUN_ID': '41000000000'}
            self.assertIsNone(scheduled.prior_generation(Path('unused'), environment, {'generation_run_id': '38275115281'}))
            self.run['run_attempt'] = 2
            self.assertEqual(scheduled.prior_generation(Path('unused'), environment, {'generation_run_id': '38275115281'}),
                             (str(self.url.RUN), self.url.PARENT))


    def test_prepublication_parent_holds_automatic_push_until_exact_child_is_published(self):
        boundary = {'id': 38275115281}
        batches = {'actions/workflows/refresh-opportunities.yml/runs?branch=main': [self.run, boundary],
                   'actions/runs/' + str(self.url.RUN) + '/artifacts': self.artifacts}
        manifest = {'generation_run_id': '38275115281'}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        environment = ENV | {'GITHUB_RUN_ID': '41000000000'}
        base = {'stage': 'generate', 'reason': 'source changes require generation'}
        with patch.object(scheduled, '_published', return_value=set()), \
             patch.object(scheduled, '_pages', side_effect=lambda repository, path, key: iter([batches[path]])), \
             patch.object(c, 'read_json', return_value=manifest):
            self.git.side_effect = lambda root, *args: '' if args[0] == 'log' else '{}'
            held = scheduled.hold_competing_generation(Path('unused'), environment, base)
            self.assertEqual((held['stage'], held['held_stage'], held['recovery_run']),
                             ('noop', 'generate', str(self.url.RUN)))
            self.git.side_effect = self.git_read
            self.assertEqual(scheduled.hold_competing_generation(Path('unused'), environment, base), base)

    def test_published_child_requires_original_generation_and_exact_identity_parent_producer(self):
        for field, value in [('generation_run_id', '38275115281'),
                             ('generation_run_attempt', '2'), ('generation_sha', 'f' * 40)]:
            producer = self.child['identity_correction']['affected_generation']
            original = producer[field]
            producer[field] = value
            self.seal()
            with self.subTest(field=field), self.assertRaises(scheduled.Hold):
                self.superseded()
            producer[field] = original
        self.child['generation_run_id'] = str(self.url.RUN)
        self.seal()
        with self.assertRaises(scheduled.Hold):
            self.superseded()


class UrlSiblingSupersession(unittest.TestCase):
    # Reuse only the synthetic fixture helpers, not the parent's test suite.
    seal = UrlParentSupersession.seal
    git_read = UrlParentSupersession.git_read
    superseded = UrlParentSupersession.superseded

    def setUp(self):
        from copy import deepcopy
        UrlParentSupersession.setUp(self)
        self.parent_run, self.parent_artifacts = self.run, self.artifacts
        self.proof = deepcopy(self.url.SUPERSEDED_URL_CORRECTION)
        owner = self.proof['producer']
        self.run = self.run | {'id': owner['run_id'], 'run_attempt': owner['run_attempt'],
                              'head_sha': owner['event_sha']}
        names = {'candidate': 'candidate-' + self.proof['candidate_id'],
                 'receipt': f"url-correction-{owner['run_id']}-{owner['run_attempt']}"}
        self.artifacts = [{'id': item['id'], 'name': names[role],
                           'digest': 'sha256:' + item['sha256'], 'expired': False}
                          for role, item in self.proof['artifacts'].items()]
        self.child['url_correction']['superseded_url_correction'] = deepcopy(self.proof)
        self.seal()

    def test_only_exact_published_v2_sibling_retires_the_failed_owner(self):
        self.assertTrue(self.superseded())
        self.run['id'] += 1
        self.assertFalse(self.superseded())
        self.run['id'] -= 1
        self.git.side_effect = lambda root, *args: '' if args[0] == 'log' else '{}'
        self.assertFalse(self.superseded())
        self.git.side_effect = self.git_read
        self.child['derived_from_candidate'] = self.proof['candidate_id']
        self.seal()
        self.assertFalse(self.superseded(), 'Only the fixed direct051d v2 sibling is supported')

    def test_missing_changed_extra_and_mistyped_supersession_proof_do_not_retire(self):
        from copy import deepcopy
        receipt = self.child['url_correction']
        for path, value in [(('candidate_id',), 'f' * 64), (('manifest_sha256',), 'f' * 64),
                            (('receipt_sha256',), 'f' * 64), (('producer', 'run_id'), self.url.RUN),
                            (('producer', 'run_attempt'), True), (('producer', 'event_sha'), 'f' * 40),
                            (('artifacts', 'candidate', 'id'), 1), (('artifacts', 'receipt', 'sha256'), 'f' * 64),
                            (('unrecognized',), 'extra')]:
            proof = deepcopy(self.proof)
            target = proof
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            receipt['superseded_url_correction'] = proof
            self.seal()
            with self.subTest(path=path): self.assertFalse(self.superseded())
        for proof in (None, {}, self.proof['candidate_id']):
            receipt['superseded_url_correction'] = proof
            self.seal()
            self.assertFalse(self.superseded())
        receipt.pop('superseded_url_correction')
        self.seal()
        self.assertFalse(self.superseded())

    def test_v1_receipt_or_wrong_published_pointer_cannot_retire_sibling(self):
        self.child['url_correction']['version'] = 'catalog-url-correction-20261012-v1'
        self.seal()
        with self.assertRaises(scheduled.Hold): self.superseded()
        self.child['url_correction']['version'] = self.url.VERSION
        self.seal()
        self.pointer['artifact_run'] = '40000000001'
        with self.assertRaises(scheduled.Hold): self.superseded()
        self.seal()
        self.child['identity_correction']['affected_generation']['generation_run_id'] = str(self.run['id'])
        self.seal()
        with self.assertRaises(scheduled.Hold): self.superseded()

    def test_later_attempt_active_run_changed_event_or_origin_remains_an_owner(self):
        for key, value in [('run_attempt', 2), ('run_attempt', '1'), ('status', 'in_progress'),
                           ('head_sha', 'f' * 40), ('head_branch', 'other'), ('event', 'push'),
                           ('path', 'other.yml'), ('conclusion', 'success')]:
            original = self.run[key]
            self.run[key] = value
            with self.subTest(key=key): self.assertFalse(self.superseded())
            self.run[key] = original

    def test_exact_artifacts_and_no_reservations_are_required(self):
        for index in (0, 1):
            for key, value in [('id', 1), ('name', 'replaced'), ('digest', 'sha256:' + 'f' * 64), ('expired', True)]:
                original = self.artifacts[index][key]
                self.artifacts[index][key] = value
                with self.subTest(index=index, key=key): self.assertFalse(self.superseded())
                self.artifacts[index][key] = original
        receipt = self.artifacts.pop()
        self.assertFalse(self.superseded())
        self.artifacts.append(receipt)
        for name in ('generation-spend-reservation-' + str(self.run['id']) + '-1',
                     'program-area-vectors-' + 'a' * 64 + '-reservation-' + str(self.run['id']) + '-1',
                     'candidate-' + 'e' * 64):
            self.artifacts.append({'name': name})
            self.assertFalse(self.superseded())
            self.artifacts.pop()

    def test_both_failed_owners_hold_before_publication_and_retire_only_after_v2(self):
        boundary = {'id': 38275115281}
        batches = {'actions/workflows/refresh-opportunities.yml/runs?branch=main':
                       [self.run, self.parent_run, boundary],
                   f"actions/runs/{self.run['id']}/artifacts": self.artifacts,
                   f"actions/runs/{self.parent_run['id']}/artifacts": self.parent_artifacts}
        environment = ENV | {'GITHUB_RUN_ID': '41000000000'}
        manifest = {'generation_run_id': str(boundary['id'])}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        base = {'stage': 'generate', 'reason': 'current source inputs changed'}
        with patch.object(scheduled, '_published', return_value=set()), \
             patch.object(scheduled, '_pages', side_effect=lambda repository, path, key: iter([batches[path]])), \
             patch.object(c, 'read_json', return_value=manifest):
            self.git.side_effect = lambda root, *args: '' if args[0] == 'log' else '{}'
            held = scheduled.hold_competing_generation(Path('unused'), environment, base)
            self.assertEqual((held['stage'], held['held_stage']), ('noop', 'generate'))
            self.assertIn(str(self.run['id']), held['reason'])
            self.assertIn(str(self.parent_run['id']), held['reason'])
            self.git.side_effect = self.git_read
            self.assertIsNone(scheduled.prior_generation(Path('unused'), environment, manifest))
            self.assertEqual(scheduled.hold_competing_generation(Path('unused'), environment, base), base)
            self.run['run_attempt'] = 2
            self.assertEqual(scheduled.prior_generation(Path('unused'), environment, manifest),
                             (str(self.run['id']), self.proof['candidate_id']))
            self.run['run_attempt'] = 1
            self.artifacts.append({'name': 'candidate-' + 'f' * 64, 'expired': False})
            with self.assertRaisesRegex(scheduled.Hold, 'Multiple candidate identities'):
                scheduled.prior_generation(Path('unused'), environment, manifest)


if __name__ == '__main__':
    unittest.main()
