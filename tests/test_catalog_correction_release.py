"""Fixed release dispatch and isolation contracts; no network or provider calls."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
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
            self.assertEqual(bridge.mode('bundle'), {'fixed_correction': 'true'})
            fixed['source_correction']['source_plan_sha256'] = 'a'*64
            with self.assertRaisesRegex(ConfigurationFailure, 'known_source_correction'): bridge.mode('bundle')
        with patch.object(bridge.release, 'load', return_value={}): self.assertEqual(bridge.mode('bundle'), {'fixed_correction': 'false'})

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
            bridge.plan(); ordinary.assert_called_once()

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
        self.assertEqual(uploads, ['${{ runner.temp }}/candidate'])
        self.assertIn("needs.catalog-correction.result == 'skipped'", self.jobs['candidate']['if'])
        self.assertIn("needs.catalog-correction.result == 'success'", self.jobs['candidate']['if'])

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
        step = next(s for s in self.jobs['publish']['steps'] if s.get('id') == 'owned-worker-retained')
        script = step['run'].split("python - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        for merged in (False, True):
            with self.subTest(merged=merged), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); reports = root/'reports'; manifest = {'candidate_id': 'a'*64}
                worker = {'candidate': manifest, 'version_id': 'tested-version', 'checkpoint': {'activeDeploymentId': 'tested-deployment'}}
                smoke = {'status': 'passed_reused', 'original_provider_requests': 3, 'current_corpus_sha256': 'b'*64,
                    'previous_corpus_sha256': 'c'*64, 'model_space_fingerprint': 'd'*64, 'previous_model_space_fingerprint': 'e'*64,
                    'serving_version_id': worker['version_id'], 'receipt_sha256': 'f'*64,
                    'authoritative_run_id': 123, 'authoritative_checkpoint_sha256': '1'*64}
                atomic_json(root/'candidate/candidate.json', manifest); atomic_json(reports/'worker-after.json', worker)
                atomic_json(reports/'catalog-smoke-reuse.json', smoke)
                atomic_json(reports/'known-good-live-release.json', {'current_corpus_sha256': smoke['previous_corpus_sha256'],
                    'model_space_fingerprint': smoke['previous_model_space_fingerprint']})
                if merged: atomic_json(reports/'publication-progress.json', manifest | {'protected_merge_completed': True, 'publication_sha': '2'*40})
                prior = {p.name: p.read_bytes() for p in reports.iterdir()}
                with patch.dict(os.environ, {'RUNNER_TEMP': temp, 'GITHUB_STEP_SUMMARY': str(root/'summary.md')}):
                    exec(compile(script, '<workflow-retention>', 'exec'), {})
                result = json.loads((reports/'owned-worker-retained.json').read_bytes())
                self.assertEqual(result['publication_status'], 'protected_merge_recorded_publication_incomplete' if merged else 'publication_unconfirmed')
                self.assertEqual(result['retained_version_id'], worker['version_id'])
                self.assertEqual(result['retained_deployment_id'], worker['checkpoint']['activeDeploymentId'])
                self.assertEqual(result['owned_smoke_receipt_sha256'], smoke['receipt_sha256'])
                self.assertEqual(result['pages_compatibility_checked_generation'], 'previous')
                self.assertFalse(result['pages_publication_complete']); self.assertEqual(result['new_provider_calls'], 0)
                self.assertFalse(result['worker_mutation_performed']); self.assertTrue(result['resume_requires_fresh_unchanged_serving_proof'])
                self.assertEqual({p.name: p.read_bytes() for p in reports.iterdir() if p.name in prior}, prior)


if __name__ == '__main__': unittest.main()
