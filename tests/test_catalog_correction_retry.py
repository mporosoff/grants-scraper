"""Actual retry script and retained-response validators, without remote work."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import yaml
from tools import catalog_correction_release as bridge
from tools.offline_spend import atomic_json, encoded, ConfigurationFailure
from test_catalog_correction_release import ENV
from test_catalog_smoke_receipt import Synthetic, proof, H


class ContextRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('No network'))
        blocker.start(); cls.addClassCleanup(blocker.stop)

    def fixture(self, count):
        f = Synthetic(); self.addCleanup(f.close)
        f.stack.enter_context(patch.dict(os.environ, ENV | {'GITHUB_SHA': 'b'*40}))
        f.bundle = f.root/'bundle'; f.reports = f.root/'reports'; f.reports.mkdir()
        f.candidate = {'candidate_id': H(200), 'artifact_run': 555, 'artifact_id': 201,
            'artifact_digest': 'sha256:'+H(202), 'manifest_sha256': H(203)}
        f.export = {'owner_run': 122, 'artifact_id': 202, 'artifact_digest': 'sha256:'+H(204), 'export_sha256': H(205)}
        p = proof(); p['checkpoint']['source'] = 'verified-candidate-serving-bytes'
        p['reconciliation']['method'] = 'authenticated-candidate-serving-bytes-and-configuration'
        p['candidate'] = {k: f.candidate[k] for k in ('candidate_id', 'artifact_id', 'artifact_digest', 'manifest_sha256')}
        p['candidate']['code_sha'] = 'a'*40
        f.generations = {'current': f.expected['current'], 'previous': f.expected['previous']}
        f.manifest = {'candidate_id': f.candidate['candidate_id'], 'source_correction': {'export_sha256': f.export['export_sha256']},
            'worker_fingerprint': p['fingerprint']}
        f.original = {'version': bridge.smoke.CONTEXT_VERSION, 'source_plan_sha256': bridge.smoke.existing.sha(bridge.source.CONFIG.read_bytes()),
            'refresh': {'run_id': 555, 'run_attempt': 1, 'head_sha': 'a'*40}, 'candidate': deepcopy(f.candidate),
            'correction_export': deepcopy(f.export), 'generations': deepcopy(f.generations), 'serving_proof': p}
        f.verified = {'context': f.original, 'expected': f.expected, 'serving_proof': deepcopy(p)}
        state = f.ledger.read()
        for i, row in enumerate(state['requests']):
            receipt_path = f.state/'receipts'/(row['id']+'.json')
            if i >= count:
                receipt_path.unlink(); (f.state/'cache'/(row['key']+'.json')).unlink()
            else:
                receipt = json.loads(receipt_path.read_bytes()); receipt['serving_proof'] = p; atomic_json(receipt_path, receipt)
        state['requests'] = state['requests'][:count]; atomic_json(f.ledger.path, state)
        bridge.smoke.existing.checkpoint(f.state)
        atomic_json(f.bundle/'files/workers/search-voyage-proxy/generated/corpus-allowlist.json', f.generations)
        atomic_json(f.bundle/'files/workers/search-voyage-proxy/wrangler.jsonc', {})
        atomic_json(f.reports/'deployments-after.json', [{'id': p['checkpoint']['activeDeploymentId'],
            'created_on': '2026-09-23T20:00:00Z', 'versions': [{'version_id': p['version_id'], 'percentage': 100}]}])
        f.stack.enter_context(patch.object(bridge, 'import_export', return_value=({'root': f.inputs}, {}, {'correction_export': f.export})))
        f.stack.enter_context(patch.object(bridge, 'candidate_anchor', return_value=(f.manifest, f.candidate)))
        f.loader = f.stack.enter_context(patch.object(bridge.smoke, 'load_context', return_value=f.verified))
        f.project = f.stack.enter_context(patch.object(bridge.source, 'validate_context_packet'))
        f.output = f.stack.enter_context(patch.object(bridge, 'output'))
        from tools.catalog_correction_executor import CatalogRunner
        f.execute = f.stack.enter_context(patch.object(CatalogRunner, 'execute', side_effect=AssertionError('No paid execution')))
        f.node_actions = []
        def node(action, value):
            f.node_actions.append(action)
            if action == 'candidate-proof':
                return deepcopy(p)
            return bridge.smoke.node(action, value)
        f.run = lambda: bridge.context(f.root, f.bundle, f.reports, api=Mock(side_effect=AssertionError('No remote API')), node_call=node)
        return f

    def test_initial_context_is_new_and_requires_upload(self):
        f = self.fixture(0); result = f.run()
        self.assertEqual(result['refresh']['head_sha'], 'b'*40)
        f.loader.assert_not_called(); f.project.assert_called_once()
        self.assertEqual(f.node_actions, ['candidate-proof'])
        self.assertEqual(f.output.call_args.args[0]['context_reused'], 'false')
        self.assertTrue((f.root/'context/context.json').is_file()); f.execute.assert_not_called()

    def test_partial_and_complete_smokes_reuse_original_context_after_head_advances(self):
        for count in (1, 2, 3):
            with self.subTest(count=count):
                f = self.fixture(count)
                old = {p.relative_to(f.state).as_posix(): p.read_bytes() for p in f.state.rglob('*.json')}
                result = f.run()
                self.assertEqual(encoded(result), encoded(f.original))
                self.assertEqual(f.node_actions, ['same-proof']*count)
                f.output.assert_called_once_with({'context_reused': 'true'})
                self.assertFalse((f.root/'context').exists()); f.project.assert_not_called(); f.execute.assert_not_called()
                report = json.loads((f.reports/'context-reuse.json').read_bytes())
                self.assertEqual(report['original_refresh']['head_sha'], 'a'*40)
                self.assertEqual(report['publication_refresh']['head_sha'], 'b'*40)
                self.assertEqual(len(report['accepted_claims']), count)
                self.assertEqual(report['new_provider_calls'], 0)
                self.assertEqual({p.relative_to(f.state).as_posix(): p.read_bytes() for p in f.state.rglob('*.json')}, old)

    def test_missing_original_context_cannot_create_a_replacement(self):
        f = self.fixture(1); f.loader.side_effect = ConfigurationFailure('context_missing')
        with self.assertRaisesRegex(ConfigurationFailure, 'context_missing'): f.run()
        self.assertEqual(f.node_actions, []); f.output.assert_not_called()
        self.assertFalse((f.root/'context').exists())

    def test_changed_candidate_export_generations_source_or_worker_fail_closed(self):
        for field in ('candidate', 'correction_export', 'generations', 'source_plan_sha256', 'fingerprint'):
            with self.subTest(field=field):
                f = self.fixture(1)
                if field == 'fingerprint': f.verified['serving_proof'][field] = H(999)
                elif field == 'source_plan_sha256': f.original[field] = H(999)
                else: f.original[field]['changed'] = True
                with self.assertRaisesRegex(ConfigurationFailure, 'same_original_context'): f.run()
                self.assertEqual(f.node_actions, []); f.output.assert_not_called()

    def test_failed_duplicate_or_tampered_cache_claims_cannot_be_replaced(self):
        for failure in ('failed', 'duplicate', 'cache'):
            with self.subTest(failure=failure):
                f = self.fixture(1); state = f.ledger.read(); row = state['requests'][0]
                if failure == 'failed': row['status'] = 'failed'
                elif failure == 'duplicate': state['requests'].append(deepcopy(row))
                else:
                    path = f.state/'cache'/(row['key']+'.json'); saved = json.loads(path.read_bytes())
                    saved['response_text'] += ' '; atomic_json(path, saved)
                atomic_json(f.ledger.path, state)
                with self.assertRaises(ConfigurationFailure): f.run()
                f.execute.assert_not_called(); f.output.assert_not_called(); self.assertNotIn('candidate-proof', f.node_actions)

    def test_each_present_receipt_keeps_full_lineage_and_original_proof(self):
        for field, bad in (('request_id', 'f'*32), ('public_body_text', '{}'), ('charged_microusd', True),
                           ('http_status', 201), ('serving_proof', None)):
            with self.subTest(field=field):
                f = self.fixture(2); row = f.ledger.read()['requests'][1]
                path = f.state/'receipts'/(row['id']+'.json'); saved = json.loads(path.read_bytes())
                saved[field] = bad; atomic_json(path, saved)
                with self.assertRaises(ConfigurationFailure): f.run()
                f.output.assert_not_called(); self.assertNotIn('candidate-proof', f.node_actions)

    def test_changed_serving_identity_is_not_equivalent_to_advanced_publication_head(self):
        for field in ('code_sha', 'deployment'):
            with self.subTest(field=field):
                f = self.fixture(1); changed = f.verified['serving_proof']
                if field == 'code_sha':
                    changed['candidate']['code_sha'] = 'b'*40
                    changed['checkpoint']['baseSha'] = 'b'*40
                    changed['reconciliation']['protected_input_sha'] = 'b'*40
                else: changed['checkpoint']['activeDeploymentId'] = 'bbbbbbbb-7777-8888-9999-aaaaaaaaaaaa'
                with self.assertRaisesRegex(ConfigurationFailure, 'node_same-proof_rejected'): f.run()
                f.output.assert_not_called(); self.assertNotIn('candidate-proof', f.node_actions)

    def test_partial_mode_does_not_change_full_default_or_allow_empty_claims(self):
        f = self.fixture(1)
        with self.assertRaisesRegex(ConfigurationFailure, 'unique_accepted_purpose'):
            bridge.smoke.accepted_operations(f.state, f.inputs, f.expected)
        state = f.ledger.read(); state['requests'] = []; atomic_json(f.ledger.path, state)
        with self.assertRaisesRegex(ConfigurationFailure, 'accepted_smoke_required'):
            bridge.smoke.accepted_operations(f.state, f.inputs, f.expected, allow_partial=True)
        with self.assertRaisesRegex(ConfigurationFailure, 'three_exact_inputs'):
            bridge.smoke.accepted_operations(f.state, f.inputs, f.expected, allow_partial=1)


class CloseoutRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flow = yaml.safe_load((bridge.ROOT/'.github/workflows/refresh-opportunities.yml').read_text())
        cls.script = flow['jobs']['closeout']['steps'][0]['with']['script']

    def run_script(self, failed=None, stage='catalog-correction', *, requested=None, jobs=None, env=None):
        needs = {name: {'result': 'skipped', 'outputs': {}} for name in
            ('plan', 'generate', 'assemble', 'catalog-correction', 'candidate', 'validate', 'publish', 'pages', 'verify-live')}
        needs['plan'] = {'result': 'success', 'outputs': {'stage': stage} if stage else {}}
        for name, values in (jobs or {}).items(): needs[name].update(deepcopy(values))
        if failed: needs[failed]['result'] = 'failure'
        values = {'REQUESTED_STAGE': requested or '', 'GITHUB_RUN_ATTEMPT': '4', **(env or {})}
        harness = """
          const fs = require('node:fs');
          const input = JSON.parse(fs.readFileSync(0, 'utf8'));
          for (const key of Object.keys(process.env)) if (key.startsWith('REQUESTED_') || key === 'GITHUB_RUN_ATTEMPT') delete process.env[key];
          Object.assign(process.env, input.env, {RESULTS: JSON.stringify(input.needs)});
          const observed = {writes: []};
          const core = {summary: {addRaw(body) {observed.body = body; return this;}, async write() {}}};
          const github = {rest: {issues: {async listForRepo() {return {data: []};},
            async create(value) {observed.writes.push(value);}, async update(value) {observed.writes.push(value);}}}};
          const context = {runId: 700, sha: 'b'.repeat(40), serverUrl: 'https://github.com', repo: {owner: 'owner', repo: 'repo'}};
          const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
          new AsyncFunction('core', 'github', 'context', input.script)(core, github, context)
            .then(() => process.stdout.write(JSON.stringify(observed))).catch(error => {console.error(error); process.exitCode = 1;});
        """
        raw = subprocess.check_output([shutil.which('node') or 'node', '-e', harness],
            input=encoded({'script': self.script, 'needs': needs, 'env': values}), cwd=bridge.ROOT, timeout=30)
        return json.loads(raw)

    def assert_route(self, result, route):
        self.assertIn('Allowed next retry: '+route+'\n', result['body'])
        self.assertNotIn('undefined', result['body'])

    def test_pre_candidate_failures_keep_exact_logical_stage_and_ignore_unpersisted_output(self):
        for producer, stage in (('generate', 'generate'), ('assemble', 'reuse'), ('assemble', 'teams'),
                                ('assemble', 'backfill'), ('catalog-correction', 'catalog-correction')):
            with self.subTest(producer=producer, stage=stage):
                result = self.run_script(producer, stage, jobs={producer: {'outputs': {'candidate_id': 'unuploaded'}}})
                self.assert_route(result, stage)
                self.assertIn('Candidate: not persisted', result['body'])
                self.assertIn('Resume the same workflow', result['body']); self.assertEqual(len(result['writes']), 1)

    def test_plan_failure_preserves_requested_stage_and_unknown_uses_auto(self):
        for requested in ('catalog-correction', 'reuse', 'teams', 'backfill', 'publish', 'verify', '', 'unsupported'):
            with self.subTest(requested=requested):
                self.assert_route(self.run_script('plan', None, requested=requested), requested if requested and requested != 'unsupported' else 'auto')

    def test_candidate_selection_failure_recovers_only_successful_producer_pair(self):
        for producer in ('generate', 'assemble', 'catalog-correction'):
            with self.subTest(producer=producer):
                result = self.run_script('candidate', jobs={producer: {'result': 'success', 'outputs': {'candidate_id': 'persisted-id'}}})
                self.assert_route(result, 'validate'); self.assertIn('Candidate: persisted-id\nArtifact run: 700\n', result['body'])
                self.assertIn('successful '+producer+' job', result['body'])
        self.assert_route(self.run_script('candidate'), 'catalog-correction')

    def test_selected_or_requested_checkpoint_preserves_resume_and_receipt_selectors(self):
        selectors = {'candidate_id': 'original-id', 'candidate_run': '600', 'receipt_run': '610', 'publication_run': '620', 'publication_attempt': '2'}
        for stage in ('publish', 'verify', 'validate'):
            with self.subTest(stage=stage):
                result = self.run_script('candidate', stage, jobs={'plan': {'outputs': {'stage': stage, **selectors}}})
                self.assert_route(result, stage)
                for line in ('Candidate: original-id', 'Artifact run: 600', 'Validation receipt run: 610',
                             'Publication evidence run: 620', 'Publication evidence attempt: 2'):
                    self.assertIn(line+'\n', result['body'])
        result = self.run_script('plan', None, requested='verify', env={
            'REQUESTED_'+key.upper(): value for key, value in selectors.items()})
        self.assert_route(result, 'verify'); self.assertIn('Publication evidence attempt: 2', result['body'])

    def test_incomplete_selectors_are_not_combined_into_another_candidate(self):
        result = self.run_script('candidate', jobs={'plan': {'outputs': {'stage': 'catalog-correction', 'candidate_id': 'partial-new'}}},
            env={'REQUESTED_CANDIDATE_ID': 'old-id', 'REQUESTED_CANDIDATE_RUN': '500'})
        self.assertIn('Candidate: old-id\nArtifact run: 500', result['body']); self.assert_route(result, 'validate')
        result = self.run_script('candidate', jobs={'candidate': {'outputs': {'candidate_id': 'partial-new'}}})
        self.assertIn('Candidate: not persisted', result['body']); self.assert_route(result, 'catalog-correction')

    def test_downstream_failures_keep_checkpoint_and_current_attempt_metadata(self):
        for failed, route in (('validate', 'validate'), ('publish', 'publish'), ('pages', 'publish'), ('verify-live', 'verify')):
            with self.subTest(failed=failed):
                jobs = {'candidate': {'result': 'success', 'outputs': {'candidate_id': 'selected-id', 'candidate_run': '600'}}}
                if failed != 'validate': jobs['validate'] = {'result': 'success'}
                if failed in ('pages', 'verify-live'): jobs['publish'] = {'result': 'success', 'outputs': {'merge_sha': 'c'*40}}
                result = self.run_script(failed, jobs=jobs); self.assert_route(result, route)
                self.assertIn('Candidate: selected-id\nArtifact run: 600', result['body'])
                if failed != 'validate': self.assertIn('Validation receipt run: 700', result['body'])
                if failed in ('publish', 'pages', 'verify-live'):
                    self.assertIn('Publication evidence run: 700\nPublication evidence attempt: 4', result['body'])
        result = self.run_script('publish', env={'GITHUB_RUN_ATTEMPT': ''})
        self.assertIn('Publication evidence attempt: unknown', result['body']); self.assertNotIn('undefined', result['body'])

    def test_review_wait_and_success_do_not_recommend_generation(self):
        result = self.run_script(jobs={'publish': {'result': 'success', 'outputs': {'review_ready': 'false'}}})
        self.assert_route(result, 'publish after exact-head review'); self.assertIn('Stage: awaiting_review', result['body'])
        self.assertEqual(result['writes'], [])
        result = self.run_script(jobs={'verify-live': {'result': 'success'}})
        self.assert_route(result, 'none'); self.assertEqual(result['writes'], [])


if __name__ == '__main__': unittest.main()
