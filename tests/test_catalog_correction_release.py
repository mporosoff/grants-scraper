"""Fixed release dispatch and isolation contracts; no network or provider calls."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import re
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
