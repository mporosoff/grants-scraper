"""Fixed release dispatch and isolation contracts; no network or provider calls."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import yaml
from tools import catalog_correction_release as bridge
from tools.offline_spend import atomic_json, encoded, ConfigurationFailure


ENV = {'GITHUB_REPOSITORY': bridge.smoke.existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF': bridge.smoke.existing.REPOSITORY+'/'+bridge.smoke.REFRESH+'@refs/heads/main',
    'GITHUB_RUN_ID': '700', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a'*40}


def zip_one(name, raw):
    value = io.BytesIO()
    with zipfile.ZipFile(value, 'w') as archive: archive.writestr(name, raw)
    return value.getvalue()


class DispatchFixture:
    def __init__(self, status='new_intent', finalize=False):
        self.stack = ExitStack(); self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='release-unit-')))
        self.work = self.root/'work'; self.reports = self.root/'reports'; self.reports.mkdir()
        self.stack.enter_context(patch.dict(os.environ, ENV))
        self.name = bridge.smoke.NAMES[-1] if finalize else bridge.smoke.NAMES[0]
        self.intent = {'version': bridge.VERSION, 'status': status, 'name': self.name, 'plan_sha256': bridge.policy.PLAN_SHA,
            'finalize_only': finalize, 'refresh': bridge.refresh_environment(), 'candidate_id': 'b'*64,
            'owner_run': 699, 'owner_checkpoint_sha256': 'c'*64, 'baseline_run_ids': [698, 699],
            'selector': {'catalog_correction': self.name}}
        atomic_json(self.work/self.name/'intent.json', self.intent)
        self.raw = (self.work/self.name/'intent.json').read_bytes()
        prefix = bridge.FINALIZE_PREFIX if finalize else bridge.DISPATCH_PREFIX
        self.artifact = {'id': 10, 'name': f'{prefix}{self.name}-700-1', 'digest': 'sha256:'+'d'*64}
        self.stack.enter_context(patch.object(bridge.smoke, 'artifacts', return_value=[self.artifact]))
        self.stack.enter_context(patch.object(bridge.smoke, 'trusted_run', return_value={'id': 700}))
        self.stack.enter_context(patch.object(bridge.smoke, 'authenticated_zip', side_effect=lambda *a, **k: (zip_one('intent.json', self.raw), self.artifact)))
        self.owner = self.stack.enter_context(patch.object(bridge, 'latest_owner', return_value={
            'run': {'id': 699}, 'checkpoint_sha256': 'c'*64}))
        self.api = Mock(return_value=encoded({'object': {'sha': 'a'*40}}))
        self.calls = Mock(); self.sleep = Mock()
        self.runs = self.stack.enter_context(patch.object(bridge, 'run_list', return_value=[]))
        self.stack.enter_context(patch.object(bridge, 'prepared_inputs', return_value={'root': self.root/'inputs'}))
        from tools import catalog_correction_executor as executor
        self.cached = self.stack.enter_context(patch.object(executor.CatalogRunner, 'cached', return_value={}))
        self.stack.enter_context(patch.object(executor.CatalogRunner, '__init__', return_value=None))
        self.stack.enter_context(patch.object(executor, 'input_body', return_value={}))

    def run(self):
        return bridge.run_smoke(self.name, self.work, self.reports, api=self.api,
            dispatch_call=self.calls, sleep=self.sleep, maximum_polls=1)

    def close(self): self.stack.close()


class DispatchContracts(unittest.TestCase):
    def setUp(self):
        self.f = DispatchFixture(); self.addCleanup(self.f.close)

    def test_dispatch_requires_exact_uploaded_intent_then_retains_no_replay_marker(self):
        with self.assertRaisesRegex(ValueError, 'bounded wait'): self.f.run()
        self.f.calls.assert_called_once_with('actions/workflows/team-recommender-offline.yml/dispatches',
            {'ref': 'main', 'inputs': {'contextual_check': '{"catalog_correction":"smoke-embed"}'}})
        self.assertTrue((self.f.work/self.f.name/'dispatch.json').is_file())
        with self.assertRaisesRegex(ValueError, 'bounded wait'): self.f.run()
        self.assertEqual(self.f.calls.call_count, 1)

    def test_upload_tampering_blocks_before_any_dispatch(self):
        self.f.raw = b'{}'
        with self.assertRaisesRegex(ConfigurationFailure, 'durable_exact_intent'): self.f.run()
        self.f.calls.assert_not_called()

    def test_missing_upload_blocks_before_any_dispatch(self):
        with patch.object(bridge.smoke, 'artifacts', return_value=[]):
            with self.assertRaisesRegex(ConfigurationFailure, 'durable_dispatch_intent'): self.f.run()
        self.f.calls.assert_not_called()

    def test_advanced_main_or_owner_blocks(self):
        self.f.api.return_value = encoded({'object': {'sha': 'e'*40}})
        with self.assertRaisesRegex(ConfigurationFailure, 'protected_head_advanced'): self.f.run()
        self.f.api.return_value = encoded({'object': {'sha': 'a'*40}})
        self.f.owner.return_value['checkpoint_sha256'] = 'e'*64
        with self.assertRaisesRegex(ConfigurationFailure, 'dispatch_owner_changed'): self.f.run()
        self.f.calls.assert_not_called()

    def test_indeterminate_dispatch_cannot_send_twice(self):
        self.f.calls.side_effect = TimeoutError('connection lost after submission')
        with self.assertRaises(TimeoutError): self.f.run()
        with self.assertRaisesRegex(ValueError, 'bounded wait'): self.f.run()
        self.assertEqual(self.f.calls.call_count, 1)

    def test_resume_without_discoverable_run_never_dispatches(self):
        self.f.intent['status'] = 'resume_intent'; atomic_json(self.f.work/self.f.name/'intent.json', self.f.intent)
        with self.assertRaisesRegex(ValueError, 'no redispatch'): self.f.run()
        self.f.calls.assert_not_called()

    def test_foreign_or_multiple_new_runs_fail_closed(self):
        self.f.intent['status'] = 'resume_intent'; atomic_json(self.f.work/self.f.name/'intent.json', self.f.intent)
        for rows, reason in [([{'id': 701, 'head_sha': 'f'*40}], 'dispatched_run_identity'),
                             ([{'id': 701}, {'id': 702}], 'ambiguous_dispatched_run')]:
            with self.subTest(reason=reason):
                self.f.runs.return_value = rows
                with self.assertRaisesRegex(ConfigurationFailure, reason): self.f.run()
        self.f.calls.assert_not_called()

    def test_terminal_failed_run_is_retained_without_retry(self):
        self.f.runs.return_value = [{'id': 701, 'head_sha': 'a'*40, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}]
        with self.assertRaisesRegex(ConfigurationFailure, 'dispatched_run_failed_no_retry'): self.f.run()
        self.assertEqual(json.loads((self.f.reports/(self.f.name+'.json')).read_bytes())['run_id'], 701)
        self.assertEqual(self.f.calls.call_count, 1)

    def test_success_requires_exact_new_owner_and_real_cache_validator(self):
        self.f.runs.return_value = [{'id': 701, 'head_sha': 'a'*40, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success'}]
        self.f.owner.side_effect = [{'run': {'id': 699}, 'checkpoint_sha256': 'c'*64}, {'run': {'id': 701}}]
        self.assertEqual(self.f.run(), {'status': 'accepted', 'run_id': 701})
        self.f.cached.assert_called_once()

    def test_cached_intent_never_dispatches_or_reserves(self):
        atomic_json(self.f.work/self.f.name/'intent.json', {'status': 'cached', 'name': self.f.name, 'request_id': 'd'*32})
        self.assertEqual(self.f.run()['status'], 'cached'); self.f.calls.assert_not_called(); self.f.owner.assert_not_called()

    def test_zero_provider_finalizer_requires_original_accepted_cache(self):
        f = DispatchFixture(finalize=True)
        try:
            f.cached.side_effect = ConfigurationFailure('invalid exact original response')
            with self.assertRaisesRegex(ConfigurationFailure, 'invalid exact original response'): f.run()
            f.calls.assert_not_called()
        finally: f.close()


class PlanningAndIsolation(unittest.TestCase):
    def setUp(self):
        no_record = patch.object(bridge, 'completion_record', return_value=None)
        no_record.start(); self.addCleanup(no_record.stop)
        no_runtime = patch('tools.catalog_runtime_smoke_reuse.classify', return_value=None)
        no_runtime.start(); self.addCleanup(no_runtime.stop)

    def test_projection_selector_is_manual_fixed_and_zero_generation(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV | {
                'REQUESTED_STAGE': 'catalog-projection', 'RUNNER_TEMP': temp,
                'GITHUB_OUTPUT': str(Path(temp)/'output')}, clear=True), \
                patch.object(bridge.release, 'git', return_value='a'*40), \
                patch('tools.plan_release.main') as ordinary, patch.object(bridge, 'correction_complete') as completion:
            bridge.plan()
            result = json.loads((Path(temp)/'release-plan.json').read_bytes())
            self.assertEqual(result['stage'], 'catalog-projection')
            self.assertEqual((result['openai'], result['anthropic']), ('false', 'false'))
            ordinary.assert_not_called(); completion.assert_not_called()
            for key in ('CANDIDATE_ID', 'CANDIDATE_RUN', 'RECEIPT_RUN', 'PUBLICATION_RUN', 'PUBLICATION_ATTEMPT', 'QUALIFICATION_PILOT'):
                with self.subTest(key=key), patch.dict(os.environ, {key: 'true'}):
                    with self.assertRaisesRegex(ConfigurationFailure, 'fixed_correction_selector'): bridge.plan()
            with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'push'}):
                with self.assertRaisesRegex(ConfigurationFailure, 'protected_manual_refresh'): bridge.plan()

    def test_projection_failure_never_falls_back_to_marker_recovery_or_creation(self):
        with patch.dict(os.environ, ENV | {'RECOVERY_STAGE': 'catalog-projection'}, clear=True), \
                patch('tools.catalog_projection_recovery.repair', side_effect=ValueError('retained evidence mismatch')) as repair, \
                patch('tools.catalog_candidate_recovery.recover') as old, patch.object(bridge, 'create') as create:
            with self.assertRaisesRegex(ValueError, 'retained evidence mismatch'):
                bridge.recover_candidate('bundle', 'reports')
            repair.assert_called_once_with('bundle', 'reports'); old.assert_not_called(); create.assert_not_called()
            with patch.dict(os.environ, {'RECOVERY_STAGE': 'unknown'}):
                with self.assertRaisesRegex(ConfigurationFailure, 'fixed_recovery_selector'):
                    bridge.recover_candidate('bundle', 'reports')
            self.assertEqual(repair.call_count, 1)

    def test_manual_main_is_required_for_mutating_refresh_bridge(self):
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/test'),
                           ('GITHUB_WORKFLOW_REF', 'untrusted'), ('GITHUB_REPOSITORY', 'other/repo')]:
            with self.subTest(key=key), patch.dict(os.environ, ENV | {key: value}):
                with self.assertRaisesRegex(ConfigurationFailure, 'protected_manual_refresh'): bridge.refresh_environment()

    def test_create_passes_only_exact_six_public_lineage_fields(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV), \
                patch.object(bridge, 'import_export', return_value=({'candidate_root': Path(temp)/'original'}, {},
                    {'correction_export': {'owner_run': 77, 'export_sha256': 'd'*64}, 'private_owner': 'must not escape'})), \
                patch.object(bridge, 'materialize_sources') as materialize, \
                patch.object(bridge.release, 'create_source_correction', return_value={'candidate_id': 'e'*64}) as create:
            bridge.create(Path(temp)/'work', Path(temp)/'bundle')
            self.assertEqual(set(create.call_args.args[3]), {'version', 'source_plan_sha256', 'spending_plan_sha256',
                'export_sha256', 'owner_run', 'original_candidate_id'})
            self.assertEqual(create.call_args.args[3]['owner_run'], 77); materialize.assert_called_once()

    def test_new_correction_refuses_existing_candidate(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV), patch.object(bridge, 'import_export') as load:
            with self.assertRaisesRegex(ConfigurationFailure, 'immutable_candidate_destination'): bridge.create(Path(temp)/'work', temp)
            load.assert_not_called()

    def test_fixed_lineage_cannot_fall_back_to_ordinary_smoke(self):
        fixed = {'source_correction': {'version': bridge.source.VERSION, 'source_plan_sha256': bridge.smoke.existing.sha(bridge.source.CONFIG.read_bytes()),
            'spending_plan_sha256': bridge.policy.PLAN_SHA}}
        with patch.object(bridge.release, 'load', return_value=fixed), patch.object(bridge, 'correction_completion', return_value=None):
            self.assertEqual(bridge.mode('bundle'), {'fixed_correction': 'true', 'zero_provider_descendant': 'false'})
            fixed['source_correction']['source_plan_sha256'] = 'a'*64
            with self.assertRaisesRegex(ConfigurationFailure, 'known_source_correction'): bridge.mode('bundle')
        with patch.object(bridge.release, 'load', return_value={}): self.assertEqual(bridge.mode('bundle'), {'fixed_correction': 'false', 'zero_provider_descendant': 'false'})

    def test_incomplete_correction_holds_auto_but_explicit_resume_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV | {'RUNNER_TEMP': temp, 'GITHUB_OUTPUT': str(Path(temp)/'outputs')}), \
                patch.object(bridge, 'correction_complete', return_value=False), patch.object(bridge.release, 'git', return_value='a'*40), \
                patch('tools.plan_release.main') as ordinary:
            with patch.dict(os.environ, {'REQUESTED_STAGE': 'auto'}):
                bridge.plan(); self.assertEqual(json.loads((Path(temp)/'release-plan.json').read_bytes())['stage'], 'noop')
            with patch.dict(os.environ, {'REQUESTED_STAGE': 'generate'}):
                with self.assertRaisesRegex(ConfigurationFailure, 'ordinary_generation_waits'): bridge.plan()
            with patch.dict(os.environ, {'REQUESTED_STAGE': 'publish'}): bridge.plan()
            ordinary.assert_called_once()

    def test_completed_fixed_repair_restores_ordinary_planning(self):
        with patch.dict(os.environ, ENV | {'REQUESTED_STAGE': 'auto'}), patch.object(bridge, 'correction_complete', return_value=True), \
                patch('tools.plan_release.main') as ordinary:
            bridge.plan(); ordinary.assert_called_once_with(automatic_paid_hold=True)

    def test_completed_finite_guard_constrains_outputs_before_any_paid_stage_is_exposed(self):
        from tools import plan_release as planner
        for event in ('push', 'schedule', 'workflow_dispatch'):
            for stage in ('generate', 'teams', 'backfill', 'reuse', 'validate', 'noop'):
                with self.subTest(event=event, stage=stage), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp); outputs = root/'outputs'
                    environment = ENV | {'GITHUB_EVENT_NAME': event, 'REQUESTED_STAGE': 'auto',
                        'RUNNER_TEMP': temp, 'GITHUB_OUTPUT': str(outputs), 'GITHUB_STEP_SUMMARY': str(root/'summary')}
                    with patch.dict(os.environ, environment, clear=True), \
                            patch.object(planner, 'pending_publication', return_value=None), \
                            patch.object(planner, 'latest_report', return_value=('', None)), \
                            patch.object(planner, 'plan', return_value={'stage': stage, 'release_sha': 'a'*40}) as decide, \
                            patch('tools.team_provider.provider_names', return_value=('openai', 'anthropic')) as providers, \
                            patch('sys.stdout', new=io.StringIO()):
                        planner.main(automatic_paid_hold=True)
                    value = json.loads((root/'release-plan.json').read_bytes())
                    held = event != 'workflow_dispatch' and stage in ('generate', 'teams', 'backfill')
                    self.assertEqual(value['stage'], 'noop' if held else stage)
                    self.assertEqual('held_stage' in value, held)
                    if held:
                        self.assertEqual(value['held_stage'], stage)
                        self.assertIn('keeps automatic paid', value['reason'])
                    paid = not held and stage in ('generate', 'teams', 'backfill')
                    self.assertEqual((value['openai'], value['anthropic']), ('true', 'true') if paid else ('false', 'false'))
                    self.assertEqual(providers.call_count, int(paid)); decide.assert_called_once()
                    lines = outputs.read_text().splitlines()
                    self.assertEqual([line for line in lines if line.startswith('stage=')], ['stage='+value['stage']])

    def test_historical_completion_survives_a_new_ordinary_pointer_without_live_claim(self):
        old = {'derived_from_candidate': bridge.source.plan()['candidate_id'], 'source_correction': {'version': bridge.source.VERSION, 'source_plan_sha256': bridge.smoke.existing.sha(bridge.source.CONFIG.read_bytes()),
            'spending_plan_sha256': bridge.policy.PLAN_SHA, 'original_candidate_id': bridge.source.plan()['candidate_id']}}
        old['candidate_id'] = bridge.release.digest(bridge.release.encoded(old))
        def report(repo, candidate, kind, destination):
            if kind == 'live':
                atomic_json(Path(destination)/'15/catalog-smoke-reuse.json', {'historical': True})
                return '11', {'candidate_id': candidate, 'verified': True, 'provider_smoke': 'success'}
            return '10', {'pages_complete': True}
        with patch.object(bridge, 'protected_candidates', return_value=[{'candidate_id': 'z'*64}, old]), \
                patch('tools.plan_release.latest_report', side_effect=report), patch('tools.plan_release.publication_ready', return_value=True), \
                patch.object(bridge, 'historical_smoke') as historical, patch.object(bridge, 'authenticate_report_files'), \
                patch.object(bridge.smoke, 'authenticate_owner') as current:
            self.assertTrue(bridge.correction_complete('root')); historical.assert_called_once(); current.assert_not_called()

    def test_exact_completed_correction_stays_owned_but_proven_team_runtime_descendants_resume(self):
        fixed = {'version': bridge.source.VERSION, 'source_plan_sha256': bridge.smoke.existing.sha(bridge.source.CONFIG.read_bytes()),
            'spending_plan_sha256': bridge.policy.PLAN_SHA, 'retained_output_hashes': {'team.json': 'b'*64}}
        completed = {'candidate_id': '1'*64, 'source_correction': fixed}
        runtime = {'candidate_id': '2'*64, 'source_correction': deepcopy(fixed), 'derived_from_candidate': completed['candidate_id']}
        team = {'candidate_id': '3'*64, 'source_correction': deepcopy(fixed), 'derived_from_candidate': runtime['candidate_id'],
            'team_generation': {'changed': True}}
        with patch.object(bridge, 'correction_completion', return_value=completed), \
                patch.object(bridge, 'protected_candidates', return_value=[runtime, completed]), patch.object(bridge.release, 'load') as load:
            load.return_value = completed; self.assertTrue(bridge.requires_owned_smoke('bundle'))
            load.return_value = runtime; self.assertFalse(bridge.requires_owned_smoke('bundle'))
            load.return_value = team; self.assertFalse(bridge.requires_owned_smoke('bundle'))
            team['derived_from_candidate'] = '9'*64
            with self.assertRaisesRegex(ConfigurationFailure, 'protected_correction_descendant'): bridge.requires_owned_smoke('bundle')
            team['source_correction']['retained_output_hashes'] = {}
            with self.assertRaisesRegex(ConfigurationFailure, 'same_completed_correction_lineage'): bridge.requires_owned_smoke('bundle')

    def test_historical_report_bytes_must_match_authenticated_full_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); atomic_json(root/'12/live-verification.json', {'verified': True})
            raw = (root/'12/live-verification.json').read_bytes()
            meta = {'id': 12, 'name': 'live-'+('a'*64)+'-2', 'workflow_run': {'id': 10}, 'digest': 'sha256:'+'b'*64}
            api = Mock(return_value=encoded(meta))
            with patch.object(bridge.smoke, 'trusted_run', return_value={'id': 10}) as run, \
                    patch.object(bridge.smoke, 'authenticated_zip', return_value=(zip_one('live-verification.json', raw), meta)):
                bridge.authenticate_report_files(root, 'live', 'a'*64, api=api)
                self.assertEqual(run.call_args.kwargs['attempt'], 2)
                self.assertFalse(run.call_args.kwargs['allow_failed'])
                atomic_json(root/'12/live-verification.json', {'verified': False})
                with self.assertRaisesRegex(ConfigurationFailure, 'authenticated_release_report_bytes'):
                    bridge.authenticate_report_files(root, 'live', 'a'*64, api=api)


class ProjectionCompletion(unittest.TestCase):
    def setUp(self):
        no_record = patch.object(bridge, 'completion_record', return_value=None)
        no_record.start(); self.addCleanup(no_record.stop)
        no_runtime = patch('tools.catalog_runtime_smoke_reuse.classify', return_value=None)
        no_runtime.start(); self.addCleanup(no_runtime.stop)
        from tests.test_catalog_projection_recovery import ProjectionFixture
        self.f = ProjectionFixture(); self.addCleanup(self.f.close)
        fixed = {'version': bridge.source.VERSION,
            'source_plan_sha256': bridge.smoke.existing.sha(bridge.source.CONFIG.read_bytes()),
            'spending_plan_sha256': bridge.policy.PLAN_SHA,
            'original_candidate_id': bridge.source.plan()['candidate_id']}
        self.f.parent['source_correction'] = fixed
        self.f.parent.pop('candidate_id')
        self.f.parent['candidate_id'] = bridge.release.digest(bridge.release.encoded(self.f.parent))
        self.f.parent_raw = bridge.release.encoded(self.f.parent)
        self.f.spec['parent'].update(candidate_id=self.f.parent['candidate_id'],
            manifest_sha256=bridge.release.digest(self.f.parent_raw),
            canonical_manifest_sha256=bridge.release.digest(self.f.parent_raw))
        self.f.parent_entries[0] = ('candidate.json', self.f.parent_raw)
        self.f.refresh_archives()
        self.manifest = self.f.derived
        self.publication = {'pages_complete': True}
        self.live = {'candidate_id': self.manifest['candidate_id'], 'verified': True, 'provider_smoke': 'success'}
        self.history = self.f.stack.enter_context(patch.object(bridge, 'protected_candidates', return_value=[self.manifest]))
        self.reports = self.f.stack.enter_context(patch('tools.plan_release.latest_report', side_effect=self.report))
        self.f.stack.enter_context(patch('tools.plan_release.publication_ready', side_effect=lambda m, p: bool(p and p['pages_complete'])))
        self.auth = self.f.stack.enter_context(patch.object(bridge, 'authenticate_report_files'))
        self.owned = self.f.stack.enter_context(patch.object(bridge, 'historical_smoke'))

    def report(self, repo, candidate, kind, destination):
        self.assertEqual(candidate, self.manifest['candidate_id'])
        if kind == 'live':
            atomic_json(Path(destination)/'15/catalog-smoke-reuse.json', {'historical': True})
            return '11', self.live
        return '10', self.publication

    def test_exact_projection_completes_without_parent_publication_and_unblocks_auto(self):
        self.assertNotEqual(self.manifest['derived_from_candidate'], bridge.source.plan()['candidate_id'])
        self.assertEqual(bridge.correction_completion('root'), self.manifest)
        self.assertEqual(self.auth.call_count, 2)
        self.owned.assert_called_once()
        self.assertEqual(self.owned.call_args.args[0], self.manifest)
        with patch.dict(os.environ, ENV | {'REQUESTED_STAGE': 'auto'}, clear=True), patch('tools.plan_release.main') as ordinary:
            bridge.plan(); ordinary.assert_called_once_with(automatic_paid_hold=True)

    def test_projection_cannot_complete_without_publication_live_and_owned_evidence(self):
        self.publication['pages_complete'] = False
        self.assertFalse(bridge.correction_complete('root')); self.owned.assert_not_called()
        self.publication['pages_complete'] = True; self.live['verified'] = False
        self.assertFalse(bridge.correction_complete('root')); self.owned.assert_not_called()
        self.live['verified'] = True; self.live['provider_smoke'] = 'failed'
        with self.assertRaisesRegex(ConfigurationFailure, 'complete_live_smoke_receipt'): bridge.correction_complete('root')
        self.live['provider_smoke'] = 'success'
        self.auth.side_effect = ValueError('forged report')
        with self.assertRaisesRegex(ValueError, 'forged report'): bridge.correction_complete('root')
        self.owned.assert_not_called(); self.auth.side_effect = None
        self.owned.side_effect = ValueError('missing owned operation')
        with self.assertRaisesRegex(ValueError, 'missing owned operation'): bridge.correction_complete('root')

    def test_forged_or_removed_projection_metadata_cannot_mint_completion(self):
        for value in (None, {'untrusted': True}):
            changed = deepcopy(self.manifest); changed['projection_recovery'] = value
            changed.pop('candidate_id'); changed['candidate_id'] = bridge.release.digest(bridge.release.encoded(changed))
            self.history.return_value = [changed]
            with self.assertRaisesRegex(ConfigurationFailure, 'projection_recovery_'): bridge.correction_complete('root')
        changed = deepcopy(self.manifest); changed.pop('projection_recovery')
        changed.pop('candidate_id'); changed['candidate_id'] = bridge.release.digest(bridge.release.encoded(changed))
        self.history.return_value = [changed]
        self.assertFalse(bridge.correction_complete('root')); self.reports.assert_not_called()

    def test_completed_projection_stays_owned_and_only_proven_descendants_resume(self):
        child = {'candidate_id': '9'*64, 'source_correction': deepcopy(self.manifest['source_correction']),
            'derived_from_candidate': self.manifest['candidate_id']}
        self.history.return_value = [child, self.manifest]
        with patch.object(bridge.release, 'load', return_value=self.manifest) as load:
            self.assertTrue(bridge.requires_owned_smoke('bundle'))
            load.return_value = child
            self.assertFalse(bridge.requires_owned_smoke('bundle'))
            child['derived_from_candidate'] = '8'*64
            with self.assertRaisesRegex(ConfigurationFailure, 'unproven_correction_descendant|protected_correction_descendant'):
                bridge.requires_owned_smoke('bundle')


class ProtectedCompletionRecord(unittest.TestCase):
    """Synthetic protected Git history, actual projection identity validator, no API."""
    def setUp(self):
        self.real_create = bridge.release.create
        no_runtime = patch('tools.catalog_runtime_smoke_reuse.classify', return_value=None)
        no_runtime.start(); self.addCleanup(no_runtime.stop)
        from tests.test_catalog_projection_recovery import ProjectionFixture
        from tools import catalog_projection_recovery as projection
        self.f = ProjectionFixture(); self.addCleanup(self.f.close)
        self.root = self.f.root/'repo'; self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.git('config', 'user.name', 'Synthetic contract')
        self.git('config', 'user.email', 'contract@example.test')
        self.git('config', 'core.autocrlf', 'false')
        ignore = self.f.root/'empty-global-ignore'; ignore.write_bytes(b'')
        self.git('config', 'core.excludesFile', str(ignore))
        for module in (bridge.source, projection):
            target = self.root/module.CONFIG.relative_to(module.ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(module.CONFIG.read_bytes())
        self.base = self.commit()
        self.f.parent['source_correction'] = {'version': bridge.source.VERSION,
            'source_plan_sha256': bridge.release.digest(bridge.source.CONFIG.read_bytes()),
            'spending_plan_sha256': bridge.policy.PLAN_SHA,
            'original_candidate_id': bridge.source.plan()['candidate_id']}
        self.f.parent.pop('candidate_id'); self.f.parent['candidate_id'] = bridge.release.digest(bridge.release.encoded(self.f.parent))
        self.f.parent_raw = bridge.release.encoded(self.f.parent)
        self.f.spec['parent'].update(candidate_id=self.f.parent['candidate_id'],
            manifest_sha256=bridge.release.digest(self.f.parent_raw), canonical_manifest_sha256=bridge.release.digest(self.f.parent_raw))
        self.f.parent_entries[0] = ('candidate.json', self.f.parent_raw); self.f.refresh_archives()
        self.anchor = self.f.derived
        self.publication = self.publish(self.anchor)
        digest = lambda value: bridge.release.digest(bridge.release.encoded(value))
        self.record = {'version': bridge.COMPLETION_VERSION,
            'source': self.anchor['source_correction'] | {'source_correction_sha256': digest(self.anchor['source_correction']),
                'original_generation_sha256': digest(self.anchor['original_generation'])},
            'candidate': {'candidate_id': self.anchor['candidate_id'], 'manifest_sha256': digest(self.anchor),
                'canonical_manifest_sha256': digest(self.anchor), 'projection_configuration_sha256': bridge.release.digest(projection.CONFIG.read_bytes()),
                'projection_derivation_sha256': digest(self.anchor['projection_recovery']), 'artifact_run_id': 201,
                'artifact_run_attempt': 1, 'artifact_head_sha': self.base, 'artifact_id': 202, 'artifact_sha256': 'a'*64},
            'publication': {'commit': self.publication, 'pr': 293, 'reviewed_head': self.base, 'review_comment_id': 303,
                'run_id': 201, 'run_attempt': 1, 'receipt_sha256': 'b'*64, 'artifact_id': 304, 'artifact_sha256': 'c'*64},
            'validation': {'sha': self.base, 'receipt_sha256': 'd'*64, 'status': 'passed'},
            'live': {'run_id': 201, 'run_attempt': 1, 'artifact_id': 305, 'artifact_sha256': 'e'*64,
                'receipt_sha256': 'f'*64, 'pages': 'success', 'assets': 'success', 'provider_smoke': 'success',
                'verified': True, 'worker_proof_sha256': '1'*64, 'completed_at': '2026-01-01T00:00:00Z'},
            'owned_smoke': {'aggregate_sha256': '2'*64, 'reuse_receipt_sha256': '3'*64, 'owner_run_id': 306,
                'owner_run_attempt': 1, 'owner_head_sha': self.base, 'state_artifact_id': 307, 'state_artifact_sha256': '4'*64,
                'checkpoint_sha256': '5'*64, 'ledger_sha256': '6'*64,
                'operations': [{'purpose': 'cb-fc-cat-'+name, 'request_id': str(i+1)*32,
                    'body_sha256': str(i+1)*64, 'response_sha256': str(i+4)*64} for i, name in enumerate(bridge.smoke.NAMES)]}}
        self.online = self.f.stack.enter_context(patch.object(bridge.smoke.existing, 'api', side_effect=AssertionError('No remote API')))
        self.reports = self.f.stack.enter_context(patch('tools.plan_release.latest_report', side_effect=AssertionError('No historical artifacts')))

    def git(self, *args):
        return bridge.release.git(self.root, *args)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic checkpoint')
        return self.git('rev-parse', 'HEAD')

    def publish(self, manifest):
        atomic_json(self.root/'release/candidate.json', manifest)
        atomic_json(self.root/'release/candidate-source.json', {'candidate_id': manifest['candidate_id'], 'artifact_run': '201'})
        return self.commit()

    def install(self, record=None):
        atomic_json(self.root/bridge.COMPLETION_PATH, self.record if record is None else record)
        return self.commit()

    def descendant(self, parent, **updates):
        result = deepcopy(parent); result.pop('candidate_id'); result.pop('projection_recovery', None)
        assembly = updates.pop('assembly_sha', None) or self.git('rev-parse', 'HEAD')
        result.update(derived_from_candidate=parent['candidate_id'], assembly_sha=assembly, **updates)
        result['candidate_id'] = bridge.release.digest(bridge.release.encoded(result))
        return result

    def owned(self, manifest):
        with patch.object(bridge.release, 'load', return_value=manifest):
            return bridge.requires_owned_smoke('synthetic-bundle', root=self.root)

    def test_real_git_projection_record_eliminates_only_historical_lookup(self):
        self.install()
        self.assertEqual(bridge.correction_completion(self.root), self.anchor)
        self.assertTrue(self.owned(self.anchor))
        self.reports.assert_not_called()
        # A dirty unreviewed file cannot overwrite the admitted HEAD blob.
        (self.root/bridge.COMPLETION_PATH).write_bytes(b'{}')
        self.assertEqual(bridge.correction_completion(self.root), self.anchor)
        self.assertNotIn('serving_version', bridge.completion_record(self.root)[0])

    def test_absent_and_present_invalid_are_different(self):
        self.assertIsNone(bridge.completion_record(self.root))
        with patch.object(bridge, 'protected_candidates', return_value=[]):
            self.assertFalse(bridge.correction_complete(self.root))
        for changed in ({}, self.record | {'private_payload': 'forbidden'}, self.record | {'version': 'unknown'}):
            with self.subTest(changed=changed.keys()):
                self.install(changed)
                with self.assertRaises(ConfigurationFailure): bridge.correction_completion(self.root)
        self.reports.assert_not_called()

    def test_closed_record_rejects_incomplete_wrong_plan_boolean_ids_and_forged_hashes(self):
        mutations = [('source', 'spending_plan_sha256', '9'*64), ('candidate', 'manifest_sha256', '9'*64),
            ('candidate', 'canonical_manifest_sha256', '9'*64), ('candidate', 'artifact_run_id', True),
            ('candidate', 'artifact_head_sha', '9'*40), ('validation', 'status', 'failed'),
            ('live', 'verified', 1), ('live', 'pages', 'skipped'), ('live', 'completed_at', 'not a date'),
            ('live', 'run_id', 202), ('publication', 'commit', '9'*40)]
        for section, name, value in mutations:
            with self.subTest(section=section, name=name):
                record = deepcopy(self.record); record[section][name] = value; self.install(record)
                with self.assertRaises((ConfigurationFailure, subprocess.CalledProcessError)):
                    bridge.correction_completion(self.root)
        record = deepcopy(self.record); record['owned_smoke']['operations'][1]['request_id'] = record['owned_smoke']['operations'][0]['request_id']
        self.install(record)
        with self.assertRaisesRegex(ConfigurationFailure, 'distinct_owned'): bridge.correction_completion(self.root)
        self.reports.assert_not_called()

    def test_protected_pointer_must_match_its_colocated_manifest(self):
        atomic_json(self.root/'release/candidate-source.json', {'candidate_id': '9'*64, 'artifact_run': '201'})
        wrong = self.commit(); record = deepcopy(self.record); record['publication']['commit'] = wrong
        self.install(record)
        with self.assertRaisesRegex(ConfigurationFailure, 'protected_manifest_pointer'): bridge.correction_completion(self.root)

    def test_rehashed_changed_projection_and_same_family_source_forgery_rejected(self):
        changed = deepcopy(self.anchor); changed['generation_timestamp'] = '2026-01-02T00:00:00Z'
        changed.pop('candidate_id'); changed['candidate_id'] = bridge.release.digest(bridge.release.encoded(changed))
        wrong = self.publish(changed); record = deepcopy(self.record); record['publication']['commit'] = wrong
        record['candidate']['candidate_id'] = changed['candidate_id']; self.install(record)
        with self.assertRaisesRegex(ConfigurationFailure, 'projection_recovery_'): bridge.correction_completion(self.root)

    def test_real_runtime_constructor_retains_origin_without_copying_projection_certificate(self):
        from tests.test_release_candidate import CandidateLifecycleTests
        fixture = CandidateLifecycleTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        original = self.real_create(fixture.root, fixture.bundle, generation_sha=fixture.source_sha, run_id='123', attempt='1')
        original['source_correction'] = deepcopy(self.anchor['source_correction'])
        original['original_generation'] = deepcopy(self.anchor['original_generation'])
        original['projection_recovery'] = {'synthetic_constructor_parent': True}
        original.pop('candidate_id'); original['candidate_id'] = bridge.release.digest(bridge.release.encoded(original))
        bridge.release.write_json(fixture.bundle/'candidate.json', original)
        atomic_json(fixture.root/'release/candidate.json', original)
        atomic_json(fixture.root/'release/candidate-source.json', {'candidate_id': original['candidate_id'], 'artifact_run': '201'})
        fixture.commit(); publication = bridge.release.git(fixture.root, 'rev-parse', 'HEAD')
        (fixture.root/'assets/app.css').write_text('main { color: blue; }')
        fixture.commit()
        child_bundle = fixture.root.parent/'runtime-child'
        child = self.real_create(fixture.root, child_bundle, parent=fixture.bundle, run_id='202')
        self.assertNotIn('projection_recovery', child)
        self.assertEqual(child['source_correction'], original['source_correction'])
        self.assertEqual(child['original_generation'], original['original_generation'])
        record = deepcopy(self.record); record['publication']['commit'] = publication
        with patch.object(bridge, 'completion_record', return_value=(record, original)), \
                patch.object(bridge, 'correction_completion', return_value=original):
            self.assertFalse(bridge.requires_owned_smoke(child_bundle, root=fixture.root))

    def test_one_multiple_and_over_100_runtime_publications_keep_exact_ancestry(self):
        self.install(); latest = self.anchor; wire = bytearray()
        branch = self.git('symbolic-ref', 'HEAD'); prior = self.git('rev-parse', 'HEAD')
        for i in range(103):
            latest = self.descendant(latest, assembly_sha=self.publication, team_identity={'generation_id': 'synthetic-'+str(i)})
            wire.extend(f'commit {branch}\nmark :{i+1}\ncommitter Contract <contract@example.test> {1700000000+i} +0000\ndata 9\nSynthetic\nfrom {prior}\n'.encode())
            for name, value in [('release/candidate.json', latest), ('release/candidate-source.json',
                    {'candidate_id': latest['candidate_id'], 'artifact_run': '201'})]:
                raw = bridge.release.encoded(value)
                wire.extend(f'M 100644 inline {name}\ndata {len(raw)}\n'.encode()+raw+b'\n')
            wire.extend(b'\n'); prior = ':'+str(i+1)
        subprocess.run(['git', '-C', str(self.root), 'fast-import', '--quiet'], input=wire, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.git('read-tree', 'HEAD')
        atomic_json(self.root/'release/candidate.json', latest)
        atomic_json(self.root/'release/candidate-source.json', {'candidate_id': latest['candidate_id'], 'artifact_run': '201'})
        self.assertGreater(len(list(bridge.protected_candidates(self.root, anchor_sha=self.publication))), 100)
        self.assertFalse(self.owned(latest))
        unpublished = self.descendant(latest)
        self.assertFalse(self.owned(unpublished))
        self.assertTrue(self.owned(self.anchor)); self.reports.assert_not_called()

    def test_side_branch_parent_is_not_protected_publication_history(self):
        self.install(); main = self.git('rev-parse', 'HEAD')
        self.git('checkout', '-qb', 'unpublished-side')
        side = self.descendant(self.anchor); self.publish(side)
        self.git('checkout', '--detach', main)
        child = self.descendant(side)
        with self.assertRaisesRegex(ConfigurationFailure, 'protected_correction_descendant'): self.owned(child)
        record = deepcopy(self.record); record['publication']['commit'] = self.git('rev-parse', 'unpublished-side')
        self.install(record)
        with self.assertRaisesRegex(ConfigurationFailure, 'protected_publication_ancestor'): bridge.correction_completion(self.root)

    def test_unknown_parent_changed_lineage_or_copied_projection_never_ordinary(self):
        self.install()
        for changes, reason in [({'derived_from_candidate': '9'*64}, 'protected_correction_descendant'),
                ({'original_generation': {}}, 'completed_generation_lineage'),
                ({'projection_recovery': self.anchor['projection_recovery']}, 'completed_generation_lineage')]:
            child = self.descendant(self.anchor)
            child.update(changes); child.pop('candidate_id'); child['candidate_id'] = bridge.release.digest(bridge.release.encoded(child))
            with self.subTest(reason=reason), self.assertRaisesRegex(ConfigurationFailure, reason): self.owned(child)
        child = self.descendant(self.anchor); child['source_correction'] = dict(child['source_correction'], export_sha256='9'*64)
        with self.assertRaisesRegex(ConfigurationFailure, 'same_completed_correction_lineage'): self.owned(child)
        with patch.object(bridge.release, 'load', return_value={}): self.assertFalse(bridge.requires_owned_smoke('ordinary', root=self.root))


class RuntimeCoverageRouting(unittest.TestCase):
    def test_covered_target_cannot_enter_bare_or_dispatch_paths(self):
        with patch('tools.catalog_runtime_smoke_reuse.classify', return_value={'synthetic': True}), \
                patch.object(bridge, 'requires_owned_smoke') as ordinary:
            self.assertEqual(bridge.mode('target'), {'fixed_correction': 'true', 'zero_provider_descendant': 'true'})
            ordinary.assert_not_called()
        with patch('tools.catalog_runtime_smoke_reuse.classify', side_effect=ValueError('unproved target')), \
                patch.object(bridge, 'requires_owned_smoke') as ordinary:
            with self.assertRaisesRegex(ValueError, 'unproved target'): bridge.mode('target')
            ordinary.assert_not_called()

    def test_fresh_worker_adapter_uses_explicit_retained_inputs_and_no_dispatch(self):
        result = {'worker_live': {'verified': True, 'candidate': {'candidate_id': 'original'}}}
        with patch('tools.catalog_runtime_smoke_reuse.classify', return_value={'synthetic': True}), \
                patch('tools.catalog_runtime_smoke_reuse.reuse', return_value=result) as reuse, \
                patch.object(bridge, 'prepared_inputs', return_value={'root': Path('exact-inputs')}) as inputs, \
                patch.object(bridge, 'context') as context, patch.object(bridge, 'plan_smoke') as plan, \
                patch.object(bridge, 'run_smoke') as dispatch:
            self.assertEqual(bridge.verify_worker('target', 'reports', work='retained-work'), result['worker_live'])
            self.assertEqual(reuse.call_args.kwargs['inputs'], Path('exact-inputs'))
            inputs.assert_called_once_with(Path('retained-work'))
            context.assert_not_called(); plan.assert_not_called(); dispatch.assert_not_called()
            reuse.side_effect = ValueError('fresh proof failed')
            with self.assertRaisesRegex(ValueError, 'fresh proof failed'): bridge.verify_worker('target', 'reports')
            dispatch.assert_not_called()

    def test_cli_reuse_preserves_helper_failure_without_original_candidate_fallback(self):
        with patch('sys.argv', ['bridge', 'reuse-smoke', '--bundle', 'target', '--reports', 'reports', '--work', 'work']), \
                patch('tools.catalog_runtime_smoke_reuse.classify', return_value={'synthetic': True}), \
                patch('tools.catalog_runtime_smoke_reuse.reuse', side_effect=ValueError('missing accepted aggregate')) as reuse, \
                patch.object(bridge, 'prepared_inputs', return_value={'root': Path('exact-inputs')}), \
                patch.object(bridge.smoke, 'authenticate_owner') as old, patch.object(bridge.smoke, 'node') as node:
            with self.assertRaisesRegex(ValueError, 'missing accepted aggregate'): bridge.main()
            old.assert_not_called(); node.assert_not_called()
            self.assertEqual(reuse.call_args.kwargs['inputs'], Path('exact-inputs'))

    def test_actual_workflow_routes_covered_target_without_context_or_three_plans(self):
        jobs = yaml.safe_load((bridge.ROOT/'.github/workflows/refresh-opportunities.yml').read_text())['jobs']
        def enabled(step, values):
            expression = step.get('if', '').removeprefix('${{').removesuffix('}}').strip()
            expression = re.sub(r'steps\.([\w-]+)\.(outcome|outputs\.[\w_]+)',
                lambda m: repr(values.get(m[1]+'.'+m[2], 'skipped' if m[2] == 'outcome' else '')), expression)
            return bool(eval(expression.replace('&&', 'and').replace('||', 'or'), {'__builtins__': {}}, {}))
        for covered in (True, False):
            values = {'review.outputs.review_ready': 'true', 'accounting.outputs.fixed_correction': 'true',
                'accounting.outputs.zero_provider_descendant': str(covered).lower()}
            steps = jobs['publish']['steps']
            context = next(s for s in steps if s.get('id') == 'smoke-context')
            self.assertEqual(enabled(context, values), not covered)
            values['smoke-context.outcome'] = 'skipped' if covered else 'success'
            plans = [s for s in steps if 'catalog_correction_release plan-smoke ' in s.get('run', '')]
            self.assertEqual(len(plans), 3)
            for step in plans:
                self.assertEqual(enabled(step, values), not covered)
                values[step['id']+'.outcome'] = 'skipped' if covered else 'success'
            dispatches = [s for s in steps if 'catalog_correction_release run-smoke ' in s.get('run', '')]
            self.assertEqual(len(dispatches), 3)
            for step in dispatches: self.assertEqual(enabled(step, values), not covered)
            self.assertTrue(enabled(next(s for s in steps if s.get('id') == 'owned-provider'), values))
            self.assertFalse(enabled(next(s for s in steps if s.get('run') == 'node tools/smoke_search_worker.mjs'), values))
            live = jobs['verify-live']['steps']
            self.assertTrue(enabled(next(s for s in live if s.get('id') == 'live-owned-provider'), values))
            self.assertFalse(enabled(next(s for s in live if s.get('id') == 'live-provider'), values))


class WorkflowContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (bridge.ROOT/'.github/workflows/refresh-opportunities.yml').read_text()
        cls.workflow = yaml.safe_load(cls.raw); cls.jobs = cls.workflow['jobs']

    def test_same_refresh_lock_and_schedule_no_new_credential_scope(self):
        self.assertEqual(self.workflow['concurrency'], {'group': 'funding-finder-coordinated-release', 'cancel-in-progress': False})
        self.assertEqual(self.workflow[True]['schedule'], [{'cron': '17 10 * * *'}])
        plan = next(s for s in self.jobs['plan']['steps'] if s.get('id') == 'plan')
        self.assertEqual(plan['run'], 'python -m tools.catalog_correction_release plan')

    def test_correction_has_no_generation_credentials_or_private_state_upload(self):
        job = self.jobs['catalog-correction']; text = json.dumps(job)
        self.assertNotIn('API_KEY', text); self.assertNotIn('CLOUDFLARE', text)
        self.assertIn('tools.restore_generation_checkpoint', text)
        uploads = [s['with']['path'] for s in job['steps'] if s.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(uploads, ['${{ runner.temp }}/catalog-recovery/recovery.json', '${{ runner.temp }}/candidate'])
        self.assertIn("needs.catalog-correction.result == 'skipped'", self.jobs['candidate']['if'])
        self.assertIn("needs.catalog-correction.result == 'success'", self.jobs['candidate']['if'])

    def test_all_candidate_producers_preserve_manifested_hidden_files(self):
        producers = {name: [s for s in job.get('steps', [])
            if s.get('uses') == 'actions/upload-artifact@v4'
            and s.get('with', {}).get('path') == '${{ runner.temp }}/candidate']
            for name, job in self.jobs.items()}
        producers = {name: steps for name, steps in producers.items() if steps}
        self.assertEqual(set(producers), {'generate', 'assemble', 'catalog-correction'})
        for name, steps in producers.items():
            with self.subTest(producer=name):
                self.assertEqual(len(steps), 1)
                self.assertIs(steps[0]['with']['include-hidden-files'], True)
                self.assertIsNot(steps[0]['with'].get('overwrite'), True)

    def test_exact_recovery_precedes_creation_and_keeps_receipt_separate(self):
        job = self.jobs['catalog-correction']; steps = job['steps']
        selected = {s['id']: s for s in steps if s.get('id')}
        self.assertLess(steps.index(selected['restore']), steps.index(selected['recover']))
        self.assertLess(steps.index(selected['recover']), steps.index(selected['persist']))
        self.assertEqual(selected['recover']['if'], "steps.restore.outputs.candidate_id == ''")
        self.assertEqual(selected['recover']['run'], 'python -m tools.catalog_correction_release recover-candidate '
            '--bundle "$RUNNER_TEMP/candidate" --reports "$RUNNER_TEMP/catalog-recovery"')
        self.assertEqual(selected['persist']['if'], "env.RECOVERY_STAGE == 'catalog-correction' && steps.restore.outputs.candidate_id == '' && steps.recover.outputs.candidate_id == ''")
        self.assertNotIn('continue-on-error', selected['recover'])
        self.assertEqual(job['outputs']['candidate_id'], '${{ steps.restore.outputs.candidate_id || steps.recover.outputs.candidate_id || steps.persist.outputs.candidate_id }}')
        uploads = [s for s in steps if s.get('uses') == 'actions/upload-artifact@v4']
        self.assertEqual(uploads[0]['id'], 'recovery-provenance')
        self.assertEqual(uploads[0]['with']['name'], 'catalog-candidate-recovery-${{ github.run_id }}-${{ github.run_attempt }}')
        self.assertEqual(uploads[0]['with']['path'], '${{ runner.temp }}/catalog-recovery/recovery.json')
        self.assertEqual(uploads[0]['if'], "always() && steps.recover.outcome == 'success'")
        self.assertEqual(uploads[1]['with']['name'], 'candidate-${{ steps.recover.outputs.candidate_id || steps.persist.outputs.candidate_id }}')
        self.assertEqual(uploads[1]['if'], "steps.restore.outputs.candidate_id == '' && ((steps.recover.outcome == 'success' && steps.recovery-provenance.outcome == 'success') || steps.persist.outcome == 'success')")
        for upload in uploads:
            self.assertEqual(upload['with']['if-no-files-found'], 'error')
            self.assertNotIn('continue-on-error', upload)

    @staticmethod
    def correction_step_enabled(step, state, prior_success=True, stage='catalog-correction'):
        """Evaluate the parsed step condition, including Actions' implicit success()."""
        expression = step.get('if', 'success()').removeprefix('${{').removesuffix('}}').strip()
        has_status = re.search(r'\b(?:always|success|failure|cancelled)\(', expression)
        if not has_status and not prior_success:
            return False
        expression = re.sub(r'steps\.([\w-]+)\.(outcome|outputs\.candidate_id)',
            lambda match: repr(state.get(match[1], {}).get(match[2],
                'skipped' if match[2] == 'outcome' else '')), expression)
        expression = expression.replace('always()', 'True').replace('success()', repr(prior_success))
        expression = expression.replace('env.RECOVERY_STAGE', repr(stage))
        return bool(eval(expression.replace('&&', 'and').replace('||', 'or'), {'__builtins__': {}}, {}))

    def correction_attempt(self, *, failed=None, restored='', recovery_candidate='a'*64, stage='catalog-correction'):
        """Run the real YAML's routing with injected local step outcomes only."""
        failed = failed or {}
        state = {'restore': {'outcome': 'success', 'outputs.candidate_id': restored}}
        steps = self.jobs['catalog-correction']['steps']
        after_restore = next(i for i, step in enumerate(steps) if step.get('id') == 'restore') + 1
        successful = True; ran = []; durable = []; publication_barriers = []
        for step in steps[after_restore:]:
            key = step.get('id', 'candidate-upload')
            if not self.correction_step_enabled(step, state, successful, stage):
                state[key] = {'outcome': 'skipped', 'outputs.candidate_id': ''}
                continue
            ran.append(key)
            outcome = failed.get(key, 'success')
            output = recovery_candidate if key == 'recover' else ('b'*64 if key == 'persist' else '')
            state[key] = {'outcome': outcome, 'outputs.candidate_id': output if outcome == 'success' else ''}
            if key == 'candidate-upload':
                publication_barriers.append(tuple(durable))
            if key in ('candidate-upload', 'recovery-provenance') and outcome == 'success':
                durable.append(key)
            successful = successful and outcome not in ('failure', 'cancelled')
        return {'state': state, 'ran': ran, 'durable': durable, 'barriers': publication_barriers}

    def test_projection_path_cannot_generate_and_preserves_receipt_publication_barrier(self):
        job = self.jobs['catalog-correction']
        self.assertIn("needs.plan.outputs.stage == 'catalog-projection'", job['if'])
        self.assertEqual(job['env']['RECOVERY_STAGE'], '${{ needs.plan.outputs.stage }}')
        restore = next(s for s in job['steps'] if s.get('id') == 'restore')
        self.assertIn('verify-projection --bundle', restore['run'])
        for failed in (None, 'recover', 'recovery-provenance', 'candidate-upload'):
            for outcome in ('failure', 'cancelled'):
                with self.subTest(failed=failed, outcome=outcome):
                    attempt = self.correction_attempt(stage='catalog-projection', failed={failed: outcome} if failed else {})
                    self.assertNotIn('persist', attempt['ran'])
                    for prior in attempt['barriers']: self.assertIn('recovery-provenance', prior)
                    if failed in ('recover', 'recovery-provenance'):
                        self.assertNotIn('candidate-upload', attempt['ran'])
        no_result = self.correction_attempt(stage='catalog-projection', failed={'recover': 'skipped'}, recovery_candidate='')
        self.assertEqual(no_result['ran'], ['recover'])
        restored = self.correction_attempt(stage='catalog-projection', restored='a'*64)
        self.assertEqual(restored['ran'], [])

    def test_recovered_candidate_requires_successful_prior_receipt_in_failure_cancel_matrix(self):
        for failed_step in (None, 'recover', 'recovery-provenance', 'candidate-upload'):
            for outcome in ('failure', 'cancelled'):
                with self.subTest(step=failed_step, outcome=outcome):
                    attempt = self.correction_attempt(failed={failed_step: outcome} if failed_step else {})
                    self.assertNotIn('persist', attempt['ran'])
                    for prior_uploads in attempt['barriers']:
                        self.assertIn('recovery-provenance', prior_uploads)
                    if failed_step in ('recover', 'recovery-provenance'):
                        self.assertNotIn('candidate-upload', attempt['ran'])
                        self.assertNotIn('candidate-upload', attempt['durable'])
                    if failed_step == 'candidate-upload':
                        self.assertEqual(attempt['durable'], ['recovery-provenance'])
                    if failed_step is None:
                        self.assertEqual(attempt['durable'], ['recovery-provenance', 'candidate-upload'])

    def test_cancellation_after_receipt_still_suppresses_candidate_upload(self):
        step = next(s for s in self.jobs['catalog-correction']['steps']
            if s.get('with', {}).get('path') == '${{ runner.temp }}/candidate')
        state = {'restore': {'outputs.candidate_id': ''}, 'recover': {'outcome': 'success'},
            'recovery-provenance': {'outcome': 'success'}}
        self.assertTrue(self.correction_step_enabled(step, state))
        self.assertFalse(self.correction_step_enabled(step, state, prior_success=False))
        self.assertNotRegex(step['if'], r'\b(?:always|failure|cancelled)\(')

    def test_receipt_only_retry_selects_recovery_and_paired_retry_skips_all_mutation(self):
        from tools import restore_generation_checkpoint as restore
        candidate_id = 'a'*64
        receipt = {'name': 'catalog-candidate-recovery-700-1', 'expired': False}
        candidate = {'name': 'candidate-'+candidate_id, 'expired': False}
        for retained in ([], [receipt], [receipt, candidate]):
            with self.subTest(retained=[a['name'] for a in retained]), tempfile.TemporaryDirectory() as temp:
                output = Path(temp)/'output'; output.write_bytes(b'')
                with patch.dict(os.environ, ENV | {'RUNNER_TEMP': temp, 'GITHUB_OUTPUT': str(output)}), \
                        patch.object(restore.subprocess, 'check_output', return_value=encoded({'artifacts': retained})), \
                        patch.object(restore, 'fetch') as fetch, \
                        patch.object(restore.c, 'load', return_value={'candidate_id': candidate_id}), \
                        patch.object(restore.c, 'verify_dependencies') as dependencies:
                    restore.main()
                restored = output.read_text().partition('candidate_id=')[2].strip()
                attempt = self.correction_attempt(restored=restored)
                if candidate in retained:
                    fetch.assert_called_once(); dependencies.assert_called_once()
                    self.assertEqual(restored, candidate_id)
                    self.assertEqual(attempt['ran'], [])
                    self.assertEqual(attempt['durable'], [])
                else:
                    fetch.assert_not_called(); dependencies.assert_not_called()
                    self.assertEqual(restored, '')
                    self.assertEqual(attempt['ran'], ['recover', 'recovery-provenance', 'candidate-upload'])
                    self.assertNotIn('persist', attempt['ran'])
        # Both a failed receipt upload and a later failed candidate upload leave a
        # retry on the same zero-generation recovery path until the pair exists.
        for failed in ('recovery-provenance', 'candidate-upload'):
            first = self.correction_attempt(failed={failed: 'failure'})
            self.assertNotIn('candidate-upload', first['durable'])
            retry = self.correction_attempt()
            self.assertEqual(retry['durable'], ['recovery-provenance', 'candidate-upload'])
            self.assertNotIn('persist', retry['ran'])

    def test_ordinary_persisted_branch_retains_existing_upload_behavior(self):
        attempt = self.correction_attempt(failed={'recover': 'skipped'}, recovery_candidate='')
        self.assertEqual(attempt['state']['persist']['outcome'], 'success')
        self.assertEqual(attempt['state']['recovery-provenance']['outcome'], 'skipped')
        self.assertEqual(attempt['durable'], ['candidate-upload'])

    def test_fixed_candidate_cannot_execute_either_bare_paid_smoke(self):
        bare = [s for job in self.jobs.values() for s in job.get('steps', []) if s.get('run') == 'node tools/smoke_search_worker.mjs']
        self.assertEqual(len(bare), 2)
        self.assertTrue(all("steps.accounting.outputs.fixed_correction == 'false'" in s['if'] for s in bare))

    def test_dispatches_are_serial_after_persisted_context_and_intents(self):
        steps = self.jobs['publish']['steps']; text = json.dumps(steps)
        self.assertNotIn('VOYAGE_API_KEY', text)
        context_upload = next(i for i, s in enumerate(steps) if s.get('uses') == 'actions/upload-artifact@v4'
            and s['with']['path'] == '${{ runner.temp }}/catalog-context/context')
        self.assertIn("steps.smoke-context.outputs.context_reused == 'false'", steps[context_upload]['if'])
        prior = context_upload
        for name in bridge.smoke.NAMES:
            planned = next(i for i, s in enumerate(steps) if 'plan-smoke --name '+name in s.get('run', ''))
            dispatched = next(i for i, s in enumerate(steps) if 'run-smoke --name '+name in s.get('run', ''))
            self.assertLess(prior, planned); self.assertLess(planned, dispatched)
            self.assertEqual(steps[planned+1]['uses'], 'actions/upload-artifact@v4')
            self.assertIn("== 'new_intent'", steps[planned+1]['if'])
            self.assertNotIn('context_reused', steps[planned]['if'])
            self.assertNotIn('always()', steps[dispatched]['if']); prior = dispatched

    def test_post_pages_uses_successful_exact_receipt_with_fresh_proof(self):
        steps = self.jobs['verify-live']['steps']
        reused = next(s for s in steps if s.get('id') == 'live-owned-provider')
        self.assertIn('reuse-smoke', reused['run']); self.assertIn('CLOUDFLARE_API_TOKEN', reused['env'])
        complete = next(s for s in steps if 'tools.verify_release_live complete' in s.get('run', ''))
        self.assertIn('steps.live-owned-provider.outcome', complete['env']['PROVIDER_OUTCOME'])

    def test_only_complete_owned_verification_suppresses_late_rollback(self):
        steps = self.jobs['publish']['steps']
        owned = next(s for s in steps if s.get('id') == 'owned-provider')
        retained = next(s for s in steps if s.get('id') == 'owned-worker-retained')
        rollback = next(s for s in steps if 'wrangler@4.125.0 rollback' in s.get('run', ''))
        self.assertIn('catalog_correction_release reuse-smoke', owned['run'])
        def enabled(step, status, review='true'):
            expression = step['if'].removeprefix('${{').removesuffix('}}').strip()
            expression = expression.replace('failure()', 'True').replace('&&', 'and')
            expression = expression.replace('steps.review.outputs.review_ready', repr(review))
            for key, value in status.items(): expression = expression.replace('steps.'+key+'.outcome', repr(value))
            return eval(expression, {'__builtins__': {}}, {})
        for owned_status in ('success', 'failure', 'skipped', 'cancelled'):
            for published in ('success', 'failure', 'skipped'):
                for deployed in ('success', 'skipped'):
                    with self.subTest(owned=owned_status, publication=published, deployed=deployed):
                        status = {'owned-provider': owned_status, 'publication': published, 'worker-deploy': deployed}
                        self.assertEqual(enabled(rollback, status), deployed == 'success' and published != 'success' and owned_status != 'success')
                        self.assertEqual(enabled(retained, status), published != 'success' and owned_status == 'success')
                        self.assertFalse(enabled(retained, status, 'false'))
                        self.assertEqual(enabled(rollback, status, 'false'), enabled(rollback, status))
        self.assertNotIn('CLOUDFLARE', json.dumps(retained)); self.assertNotIn('API_KEY', json.dumps(retained))

    def test_late_failure_receipt_preserves_proof_and_does_not_invent_unmerged_status(self):
        from tools import catalog_runtime_smoke_reuse as runtime
        step = next(s for s in self.jobs['publish']['steps'] if s.get('id') == 'owned-worker-retained')
        script = step['run'].split("python - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        for merged, covered in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(merged=merged, covered=covered), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); reports = root/'reports'; manifest = {'candidate_id': ('b' if covered else 'a')*64}
                worker = {'candidate': {'candidate_id': 'a'*64}, 'version_id': 'tested-version', 'checkpoint': {'activeDeploymentId': 'tested-deployment'}}
                smoke = {'status': 'passed_reused', 'original_provider_requests': 3, 'current_corpus_sha256': 'b'*64,
                    'previous_corpus_sha256': 'c'*64, 'model_space_fingerprint': 'd'*64, 'previous_model_space_fingerprint': 'e'*64,
                    'serving_version_id': worker['version_id'], 'receipt_sha256': 'f'*64,
                    'authoritative_run_id': 123, 'authoritative_checkpoint_sha256': '1'*64}
                atomic_json(root/'candidate/candidate.json', manifest); atomic_json(reports/'worker-after.json', worker)
                atomic_json(reports/'catalog-smoke-reuse.json', smoke)
                atomic_json(reports/'known-good-live-release.json', {'current_corpus_sha256': smoke['previous_corpus_sha256'],
                    'model_space_fingerprint': smoke['previous_model_space_fingerprint']})
                if covered: atomic_json(reports/'runtime-smoke-coverage.json', {'target_candidate_id': manifest['candidate_id']})
                if merged: atomic_json(reports/'publication-progress.json', manifest | {'protected_merge_completed': True, 'publication_sha': '2'*40})
                prior = {p.name: p.read_bytes() for p in reports.iterdir()}
                env = {'RUNNER_TEMP': temp, 'GITHUB_STEP_SUMMARY': str(root/'summary.md'), 'ZERO_PROVIDER_DESCENDANT': str(covered).lower()}
                with patch.dict(os.environ, env), patch.object(runtime, 'validate_retention') as validate:
                    exec(compile(script, '<workflow-retention>', 'exec'), {})
                if covered: validate.assert_called_once_with(root/'candidate', reports)
                else: validate.assert_not_called()
                result = json.loads((reports/'owned-worker-retained.json').read_bytes())
                self.assertEqual(result['publication_status'], 'protected_merge_recorded_publication_incomplete' if merged else 'publication_unconfirmed')
                self.assertEqual(result['retained_version_id'], worker['version_id'])
                self.assertEqual(result['retained_deployment_id'], worker['checkpoint']['activeDeploymentId'])
                self.assertEqual(result['owned_smoke_receipt_sha256'], smoke['receipt_sha256'])
                self.assertEqual(result['pages_compatibility_checked_generation'], 'previous')
                self.assertFalse(result['pages_publication_complete']); self.assertEqual(result['new_provider_calls'], 0)
                self.assertFalse(result['worker_mutation_performed']); self.assertTrue(result['resume_requires_fresh_unchanged_serving_proof'])
                self.assertEqual({p.name: p.read_bytes() for p in reports.iterdir() if p.name in prior}, prior)
                if covered:
                    self.assertEqual(result['worker_proof_candidate_id'], 'a'*64)
                    self.assertEqual(result['runtime_smoke_coverage_sha256'], bridge.release.digest(prior['runtime-smoke-coverage.json']))
                    (reports/'owned-worker-retained.json').unlink()
                    with patch.dict(os.environ, env), patch.object(runtime, 'validate_retention', side_effect=ValueError('invalid target coverage')):
                        with self.assertRaisesRegex(ValueError, 'invalid target coverage'):
                            exec(compile(script, '<workflow-retention>', 'exec'), {})
                    self.assertFalse((reports/'owned-worker-retained.json').exists())
                    with patch.dict(os.environ, env | {'ZERO_PROVIDER_DESCENDANT': 'false'}):
                        with self.assertRaises(AssertionError): exec(compile(script, '<workflow-retention>', 'exec'), {})
                    self.assertFalse((reports/'owned-worker-retained.json').exists())
                else:
                    self.assertNotIn('runtime_smoke_coverage_sha256', result)


if __name__ == '__main__': unittest.main()
