"""Synthetic Git/payload contracts; never a claim of real provider execution."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from tools import catalog_runtime_smoke_reuse as reuse
from tools import catalog_correction_release as bridge
from tools.offline_spend import ConfigurationFailure, atomic_json, encoded, identity


class RuntimeReuse(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ui-smoke-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base/'repo'; self.root.mkdir()
        self.bundle = self.base/'candidate'; self.reports = self.base/'reports'
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.git('config', 'user.name', 'Synthetic reuse contract')
        self.git('config', 'user.email', 'contract@example.test')
        self.git('config', 'core.autocrlf', 'false')
        ignore = self.base/'empty-ignore'; ignore.write_bytes(b'')
        self.git('config', 'core.excludesFile', str(ignore))
        self.worker = ['workers/search-voyage-proxy/src/index.js',
            'workers/search-voyage-proxy/wrangler.jsonc',
            'workers/search-voyage-proxy/generated/corpus-allowlist.json']
        policy = {'worker': self.worker, 'worker_toolchain': {'wrangler': '4.125.0'}}
        self.write(reuse.release.POLICY, encoded(policy))
        for i, name in enumerate(self.worker): self.write(name, ('worker-' + str(i)).encode())
        self.write(reuse.SCRIPT, b'old snapshot controller')
        old_hash = identity_bytes(b'old snapshot controller')
        self.write(reuse.PAGE, ('<html><script src="./' + reuse.SCRIPT + '?v=' + old_hash + '"></script></html>').encode())
        self.write('data/science.json', b'{"retained":"all science"}')
        self.write('data/vectors.f16', b'original exact vectors')
        self.write('README.md', b'retained documentation')
        self.publication = self.commit()
        self.payloads = {name: (self.root/name).read_bytes() for name in self.worker +
            [reuse.SCRIPT, reuse.PAGE, 'data/science.json', 'data/vectors.f16', 'README.md']}
        self.worker_hashes = {name: identity_bytes(self.payloads[name]) for name in self.worker}
        self.worker_hashes['@toolchain'] = candidate_identity(policy['worker_toolchain'])
        group = lambda name: {'files': {name: 'a'*64}, 'fingerprint': candidate_identity({name: 'a'*64})}
        self.anchor = {'schema_version': 1, 'candidate_format': reuse.release.VERSION,
            'generation_sha': self.publication, 'generation_run_id': '90', 'generation_run_attempt': '1',
            'generation_timestamp': '2026-01-01T00:00:00Z', 'generation_dependencies': {'fingerprint': 'a'*64},
            'generator_versions': {}, 'generation_baseline': {},
            'generation_files': {name: identity_bytes(self.payloads[name]) for name in ('data/science.json', 'data/vectors.f16')},
            'source_correction': {'version': bridge.source.VERSION, 'fixed': 'synthetic',
                'source_plan_sha256': identity_bytes(bridge.source.CONFIG.read_bytes()),
                'spending_plan_sha256': bridge.policy.PLAN_SHA},
            'original_generation': {'sha': self.publication}, 'projection_recovery': {'synthetic': True},
            'derived_from_candidate': 'b'*64, 'assembly_sha': self.publication,
            'files': {name: identity_bytes(raw) for name, raw in self.payloads.items()},
            'runtime_baseline': {name: identity_bytes(self.payloads[name]) for name in self.worker+[reuse.SCRIPT, reuse.PAGE]},
            'documentation_baseline': {'README.md': identity_bytes(self.payloads['README.md'])},
            'dependency_groups': {name: group(name) for name in ('source', 'teams', 'semantic', 'runtime', 'validation')},
            'worker_fingerprint': candidate_identity(self.worker_hashes), 'team_identity': {'retained': 'team'},
            'semantic_identity': {'corpus_sha256': 'c'*64, 'model_space_fingerprint': 'd'*64},
            'release_identity': {'current_corpus_sha256': 'c'*64, 'previous_corpus_sha256': 'e'*64,
                'model_space_fingerprint': 'd'*64, 'worker_allowlist_sha256': identity_bytes(self.payloads[self.worker[-1]])}}
        self.anchor['candidate_id'] = candidate_identity(self.anchor)
        self.write(reuse.SCRIPT, b'new protected snapshot controller')
        new_hash = identity_bytes((self.root/reuse.SCRIPT).read_bytes())
        self.write(reuse.PAGE, self.payloads[reuse.PAGE].replace(old_hash.encode(), new_hash.encode()))
        self.head = self.commit()
        self.target = deepcopy(self.anchor); self.target.pop('projection_recovery'); self.target.pop('candidate_id')
        self.target.update(assembly_sha=self.head, derived_from_candidate=self.anchor['candidate_id'])
        for name in reuse.DELTAS:
            self.target['files'][name] = identity_bytes((self.root/name).read_bytes())
            self.target['runtime_baseline'][name] = self.target['files'][name]
        self.save_target()
        self.record = {'publication': {'commit': self.publication},
            'candidate': {'candidate_id': self.anchor['candidate_id'], 'manifest_sha256': candidate_identity(self.anchor),
                'artifact_id': 102, 'artifact_sha256': 'f'*64, 'artifact_head_sha': self.publication},
            'owned_smoke': {'owner_run_id': 103, 'owner_run_attempt': 1, 'owner_head_sha': self.publication,
                'state_artifact_id': 104, 'state_artifact_sha256': '1'*64,
                'checkpoint_sha256': '2'*64, 'ledger_sha256': '3'*64,
                'operations': [{'purpose': 'cb-fc-cat-'+name, 'request_id': str(i+1)*32,
                    'body_sha256': identity({'synthetic_request': i}), 'response_sha256': str(i+7)*64}
                    for i, name in enumerate(reuse.smoke.NAMES)]}}
        self.proof = {'candidate': {'candidate_id': self.anchor['candidate_id'], 'artifact_id': 102,
                'artifact_digest': 'sha256:'+'f'*64, 'manifest_sha256': candidate_identity(self.anchor), 'code_sha': self.publication},
            'fingerprint': self.anchor['worker_fingerprint'], 'version_id': 'synthetic-version',
            'reconciliation': {'input_hashes': self.worker_hashes}}
        input_operations = [{'purpose': row['purpose'], 'provider_body_text': json.dumps({'synthetic_request': i}, indent=2)+'\n'}
            for i, row in enumerate(self.record['owned_smoke']['operations'])]
        receipt = {'owner': {'run_id': 103}, 'serving_after': deepcopy(self.proof), 'inputs': {'operations': input_operations},
            'operations': [{'purpose': row['purpose'], 'request_id': row['request_id'],
                'provider_body_sha256': identity_bytes(input_operations[i]['provider_body_text'].encode()),
                'response_sha256': row['response_sha256']}
                for i, row in enumerate(self.record['owned_smoke']['operations'])]}
        self.record['owned_smoke']['aggregate_sha256'] = identity(receipt)
        self.auth = {'receipt_text': encoded(receipt).decode(), 'serving_proof': deepcopy(self.proof),
            'candidate_inputs': {}, 'expected': {'worker_input_fingerprint': self.anchor['worker_fingerprint'],
                'current': {'corpus_sha256': 'c'*64, 'model_space_fingerprint': 'd'*64},
                'previous': {'corpus_sha256': 'e'*64, 'model_space_fingerprint': 'd'*64}},
            'anchor': {'run': {'id': 103, 'run_attempt': 1, 'head_sha': self.publication},
                'artifact': {'id': 104, 'digest': 'sha256:'+'1'*64}, 'checkpoint_sha256': '2'*64,
                'ledger_sha256': '3'*64}}
        self.completed = self.stack.enter_context(patch.object(bridge, 'completion_record', return_value=(self.record, self.anchor)))
        self.history = self.stack.enter_context(patch.object(bridge, 'protected_candidates', return_value=[self.anchor]))
        self.owner = self.stack.enter_context(patch.object(reuse.smoke, 'authenticate_owner', side_effect=lambda *a, **k: deepcopy(self.auth)))
        self.real_anchor = bridge.candidate_anchor
        self.artifact = self.stack.enter_context(patch.object(bridge, 'candidate_anchor', side_effect=lambda *a, **k:
            (self.target, {'candidate_id': self.target['candidate_id'], 'manifest_sha256': identity_bytes((self.bundle/'candidate.json').read_bytes()),
                'artifact_id': 105, 'artifact_run': 106, 'artifact_digest': 'sha256:'+'9'*64})))
        self.no_api = Mock(side_effect=AssertionError('No network in contracts'))
        self.no_post = self.stack.enter_context(patch.object(reuse.smoke.requests, 'post', side_effect=AssertionError('No provider')))
        self.calls = []

    def git(self, *args): return reuse.release.git(self.root, *args)

    def write(self, name, raw):
        path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def commit(self):
        self.git('add', '.'); self.git('commit', '-qm', 'Synthetic protected fixture')
        return self.git('rev-parse', 'HEAD')

    def save_target(self):
        self.target.pop('candidate_id', None); self.target['candidate_id'] = candidate_identity(self.target)
        for name in self.target['files']:
            path = self.bundle/'files'/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root/name).read_bytes())
        (self.bundle/'candidate.json').write_bytes(reuse.release.encoded(self.target))

    def node(self, action, value):
        self.calls.append(action)
        if action == 'same-proof':
            self.assertEqual(value['before'], value['after']); return {}
        self.assertEqual(action, 'reuse')
        return {'version': 'search-worker-smoke-reuse-v1', 'status': 'passed_reused',
            'receipt_sha256': self.record['owned_smoke']['aggregate_sha256'], 'original_run_id': 103,
            'authoritative_run_id': self.auth['anchor']['run']['id'], 'serving_version_id': self.proof['version_id'],
            'serving_proof_sha256': identity(value['serving_proof']), 'verified_at': '2026-01-01T00:01:00Z',
            **{key: 0 for key in reuse.ZERO_FIELDS}}

    def run_reuse(self, node=None):
        return reuse.reuse(self.bundle, self.reports, root=self.root, inputs=self.base/'retained-inputs',
            api=self.no_api, node_call=node or self.node)

    def authenticated_artifact(self):
        """Actual automatic-release API shape with synthetic Git and ZIP bytes."""
        run_id = 35948724690
        run = {'id': run_id, 'run_attempt': 1, 'path': reuse.smoke.REFRESH,
            'event': 'push', 'head_branch': 'main', 'head_sha': self.head,
            'status': 'completed', 'conclusion': 'failure',
            'repository': {'full_name': reuse.smoke.existing.REPOSITORY},
            'head_repository': {'full_name': reuse.smoke.existing.REPOSITORY}}
        fixture = {'run': run, 'artifact': {'id': 105, 'name': 'candidate-'+self.target['candidate_id'],
            'expired': False, 'workflow_run': {'id': run_id, 'head_sha': self.head}}}
        self.archive_payloads(fixture)
        def api(path):
            if path == f'actions/runs/{run_id}': return encoded(fixture['run'])
            if path == 'actions/artifacts?per_page=100&page=1':
                return encoded({'artifacts': [fixture['artifact']]})
            if path == 'actions/artifacts/105': return encoded(fixture['artifact'])
            if path == 'actions/artifacts/105/zip': return fixture['raw']
            raise AssertionError('Unexpected API path: '+path)
        fixture['api'] = Mock(side_effect=api)
        return fixture

    def archive_payloads(self, fixture, alterations=None):
        entries = {p.relative_to(self.bundle).as_posix(): p.read_bytes()
            for p in self.bundle.rglob('*') if p.is_file()}
        entries.update(alterations or {})
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name, raw in entries.items(): archive.writestr(name, raw)
        fixture['raw'] = output.getvalue()
        fixture['artifact']['digest'] = 'sha256:'+identity_bytes(fixture['raw'])

    def run_authenticated(self, fixture):
        with patch.dict(os.environ, {'CANDIDATE_RUN': str(fixture['run']['id'])}), \
                patch.object(bridge, 'candidate_anchor', self.real_anchor):
            return reuse.reuse(self.bundle, self.reports, root=self.root, inputs='retained-inputs',
                api=fixture['api'], node_call=self.node)

    def test_exact_two_payloads_and_original_proof_are_separate_from_target(self):
        plan = reuse.classify(self.bundle, root=self.root)
        self.assertEqual(set(plan['changes']), reuse.DELTAS)
        result = self.run_reuse()
        self.assertEqual(result['worker_live']['candidate'], self.proof['candidate'])
        self.assertEqual(result['coverage_receipt']['target_candidate_id'], self.target['candidate_id'])
        self.assertEqual(self.calls, ['reuse']); self.no_api.assert_not_called(); self.no_post.assert_not_called()

    def test_original_candidate_and_unrelated_generation_are_not_runtime_reuse(self):
        with patch.object(reuse.release, 'load', return_value=self.anchor):
            self.assertIsNone(reuse.classify(self.bundle, root=self.root))
        plain = deepcopy(self.target); plain.pop('source_correction')
        with patch.object(reuse.release, 'load', return_value=plain):
            self.assertIsNone(reuse.classify(self.bundle, root=self.root))
        other = deepcopy(self.anchor); other['candidate_id'] = 'f'*64
        other['team_generation'] = {'supported': 'existing separate team route'}
        with patch.object(reuse.release, 'load', return_value=other):
            self.assertIsNone(reuse.classify(self.bundle, root=self.root))

    def test_missing_protected_record_fails_before_authentication(self):
        self.completed.return_value = None
        with patch('tools.catalog_projection_recovery.plan', return_value={'candidate_id': self.anchor['candidate_id']}):
            with self.assertRaisesRegex(ConfigurationFailure, 'protected_completion_required'): self.run_reuse()
        self.owner.assert_not_called()

    def test_third_payload_or_vector_change_fails_closed(self):
        for name in ('data/science.json', 'data/vectors.f16', self.worker[0]):
            with self.subTest(name=name):
                original = (self.root/name).read_bytes(); before = deepcopy(self.target)
                self.write(name, original+b'changed'); self.target['files'][name] = identity_bytes(original+b'changed'); self.save_target()
                with self.assertRaisesRegex(ConfigurationFailure, 'exact_awards_ui_delta'): self.run_reuse()
                self.write(name, original); self.target = before; self.save_target()
        self.owner.assert_not_called()

    def test_generation_lineage_parent_and_semantic_changes_rejected(self):
        for key, value in [('generation_sha', 'f'*40), ('release_identity', {}), ('original_generation', {}),
                ('derived_from_candidate', 'a'*64), ('team_generation', {'new': True})]:
            with self.subTest(key=key):
                before = deepcopy(self.target); self.target[key] = value; self.save_target()
                with self.assertRaises(ConfigurationFailure): self.run_reuse()
                self.target = before; self.save_target()
        self.owner.assert_not_called()

    def test_dirty_ui_and_extra_reviewed_html_change_rejected(self):
        self.write(reuse.SCRIPT, b'dirty unpublished JS')
        self.target['files'][reuse.SCRIPT] = identity_bytes(b'dirty unpublished JS'); self.save_target()
        with self.assertRaisesRegex(ConfigurationFailure, 'reviewed_ui_bytes'): self.run_reuse()
        self.write(reuse.PAGE, (self.root/reuse.PAGE).read_bytes()+b'<p>extra</p>')
        self.target['assembly_sha'] = self.commit()
        for name in reuse.DELTAS:
            self.target['files'][name] = identity_bytes((self.root/name).read_bytes())
            self.target['runtime_baseline'][name] = self.target['files'][name]
        self.save_target()
        with self.assertRaisesRegex(ConfigurationFailure, 'single_content_addressed_reference'): self.run_reuse()

    def test_worker_toolchain_and_source_dependency_tampering(self):
        self.target['dependency_groups']['semantic'] = {'files': {}, 'fingerprint': candidate_identity({})}; self.save_target()
        with self.assertRaisesRegex(ConfigurationFailure, 'source_semantic_team_dependencies'): self.run_reuse()
        self.target['dependency_groups']['semantic'] = deepcopy(self.anchor['dependency_groups']['semantic'])
        p = json.loads((self.root/reuse.release.POLICY).read_bytes()); p['worker_toolchain']['wrangler'] = '9.0.0'
        self.write(reuse.release.POLICY, encoded(p)); self.target['assembly_sha'] = self.commit(); self.save_target()
        with self.assertRaisesRegex(ConfigurationFailure, 'complete_worker_inputs'): self.run_reuse()

    def test_aggregate_origin_and_full_inputs_are_pinned(self):
        alterations = [lambda a: a.update(receipt_text=a['receipt_text']+' '),
            lambda a: a['anchor'].update(checkpoint_sha256='f'*64),
            lambda a: a['serving_proof']['candidate'].update(candidate_id=self.target['candidate_id']),
            lambda a: a['serving_proof']['reconciliation']['input_hashes'].update({'@toolchain': 'f'*64}),
            lambda a: a['expected']['current'].update(corpus_sha256='f'*64)]
        for alter in alterations:
            with self.subTest(alter=alter):
                before = deepcopy(self.auth); alter(self.auth)
                with self.assertRaises(ConfigurationFailure): self.run_reuse()
                self.auth = before
        self.assertFalse(self.reports.exists()); self.assertEqual(self.calls, [])

    def test_authenticated_later_owner_retains_original_origin(self):
        self.auth['anchor']['aggregate_origin'] = deepcopy(self.auth['anchor'])
        self.auth['anchor']['run']['id'] = 109
        result = self.run_reuse()
        self.assertEqual(result['coverage_receipt']['authoritative_owner']['run']['id'], 109)
        self.assertEqual(result['coverage_receipt']['original_operations'], self.record['owned_smoke']['operations'])

    def test_unknown_owner_and_nonzero_or_boolean_reuse_never_write_reports(self):
        self.owner.side_effect = ConfigurationFailure('new_unknown_or_missing_owner')
        with self.assertRaises(ConfigurationFailure): self.run_reuse()
        self.owner.side_effect = lambda *a, **k: deepcopy(self.auth)
        for value in (1, False):
            def bad(action, payload):
                result = self.node(action, payload); result['new_provider_calls'] = value; return result
            with self.assertRaisesRegex(ConfigurationFailure, 'zero_provider_reuse'): self.run_reuse(bad)
        self.assertFalse(self.reports.exists())

    def test_repeated_fresh_verification_preserves_first_worker_checkpoint(self):
        original_auth = deepcopy(self.auth)
        self.run_reuse(); before = (self.reports/'worker-after.json').read_bytes()
        self.run_reuse()
        self.assertEqual((self.reports/'worker-after.json').read_bytes(), before)
        self.assertEqual(self.auth, original_auth)
        self.assertEqual(self.calls, ['reuse', 'reuse', 'same-proof'])

    def test_interrupted_local_reports_resume_without_remote_mutation(self):
        real = reuse.atomic_json
        for stop in range(4):
            reports = self.base/('interrupted-'+str(stop)); calls = []
            def interrupted(path, value):
                if len(calls) == stop: raise RuntimeError('simulated interrupted report persistence')
                calls.append(str(path)); return real(path, value)
            with patch.object(reuse, 'atomic_json', side_effect=interrupted):
                with self.assertRaises(RuntimeError):
                    reuse.reuse(self.bundle, reports, root=self.root, inputs='retained', api=self.no_api, node_call=self.node)
            result = reuse.reuse(self.bundle, reports, root=self.root, inputs='retained', api=self.no_api, node_call=self.node)
            self.assertEqual(result['coverage_receipt']['target_candidate_id'], self.target['candidate_id'])
        self.no_post.assert_not_called(); self.no_api.assert_not_called()

    def test_changed_target_during_owner_authentication_is_not_covered(self):
        def changing(*a, **k):
            self.target['generation_timestamp'] = 'changed'; self.save_target(); return deepcopy(self.auth)
        self.owner.side_effect = changing
        with self.assertRaises(ConfigurationFailure): self.run_reuse()
        self.assertFalse(self.reports.exists())

    def test_explicit_inputs_and_exact_target_artifact_required(self):
        with self.assertRaisesRegex(ConfigurationFailure, 'verified_retained_inputs_required'):
            reuse.reuse(self.bundle, self.reports, root=self.root)
        self.artifact.side_effect = lambda *a, **k: (self.target, {'candidate_id': 'a'*64, 'manifest_sha256': 'b'*64})
        with self.assertRaisesRegex(ConfigurationFailure, 'target_artifact'): self.run_reuse()
        self.owner.assert_not_called()

    def test_late_failure_retention_validates_separate_target_without_live_request(self):
        self.run_reuse(); self.run_reuse()
        coverage = reuse.validate_retention(self.bundle, self.reports, root=self.root, node_call=self.node)
        self.assertEqual(coverage['target_candidate_id'], self.target['candidate_id'])
        self.assertEqual(self.calls[-1], 'same-proof')
        original_calls = self.owner.call_count
        coverage['target_candidate_id'] = self.anchor['candidate_id']
        atomic_json(self.reports/'runtime-smoke-coverage.json', coverage)
        with self.assertRaisesRegex(ConfigurationFailure, 'retention_exact_target'):
            reuse.validate_retention(self.bundle, self.reports, root=self.root, node_call=self.node)
        self.assertEqual(self.owner.call_count, original_calls)

    def test_late_failure_retention_does_not_relabel_original_proof(self):
        self.run_reuse()
        path = self.reports/'worker-after.json'; value = json.loads(path.read_bytes())
        value['candidate']['candidate_id'] = self.target['candidate_id']; atomic_json(path, value)
        with self.assertRaisesRegex(ConfigurationFailure, 'retention_original_proof_identity'):
            reuse.validate_retention(self.bundle, self.reports, root=self.root, node_call=self.node)

    def test_exact_named_candidate_survives_later_protected_head(self):
        assembly = self.target['assembly_sha']
        self.write('later-doc.md', b'Later protected publication or documentation')
        self.assertNotEqual(self.commit(), assembly)
        plan = reuse.classify(self.bundle, root=self.root)
        self.assertEqual(plan['assembly_sha'], assembly)
        self.assertEqual(self.run_reuse()['coverage_receipt']['target_candidate_id'], self.target['candidate_id'])

    def test_later_proven_successor_retaining_ui_uses_existing_guard(self):
        published_ui = deepcopy(self.target)
        self.history.return_value = [self.anchor, published_ui]
        self.target['derived_from_candidate'] = published_ui['candidate_id']
        self.target['team_generation'] = {'separate_existing_route': True}; self.save_target()
        self.assertIsNone(reuse.classify(self.bundle, root=self.root))
        self.history.return_value = [self.anchor]
        with self.assertRaisesRegex(ConfigurationFailure, 'immediate_protected_parent'):
            reuse.classify(self.bundle, root=self.root)

    def test_automatic_push_artifact_uses_real_authenticator_and_preserves_manual_origin(self):
        fixture = self.authenticated_artifact()
        result = self.run_authenticated(fixture)
        coverage = result['coverage_receipt']
        self.assertEqual(coverage['target_artifact']['artifact_run'], 35948724690)
        self.assertEqual(coverage['target_artifact']['artifact_digest'], fixture['artifact']['digest'])
        self.assertEqual(coverage['target_candidate_id'], self.target['candidate_id'])
        self.assertEqual(result['worker_live']['candidate'], self.proof['candidate'])
        self.assertEqual(coverage['original_operations'], self.record['owned_smoke']['operations'])
        self.assertEqual(self.calls, ['reuse']); self.no_post.assert_not_called()
        self.assertEqual([call.args[0] for call in fixture['api'].call_args_list], [
            'actions/runs/35948724690', 'actions/artifacts?per_page=100&page=1',
            'actions/artifacts/105', 'actions/artifacts/105/zip'])

    def test_retained_push_artifact_survives_later_protected_head_and_run_attempt(self):
        fixture = self.authenticated_artifact()
        self.write('later-fix.md', b'Later protected validation-only change'); self.commit()
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), fixture['run']['head_sha'])
        # A later attempt does not rewrite the run's immutable head or artifact.
        fixture['run'].update(run_attempt=2, status='in_progress', conclusion=None)
        result = self.run_authenticated(fixture)
        self.assertEqual(result['coverage_receipt']['assembly_sha'], self.head)
        self.assertEqual(result['coverage_receipt']['target_artifact']['artifact_digest'], fixture['artifact']['digest'])
        reuse.validate_retention(self.bundle, self.reports, root=self.root, node_call=self.node)

    def test_supported_release_events_are_target_only_not_manual_paid_authority(self):
        fixture = self.authenticated_artifact()
        for event in ('push', 'schedule', 'workflow_dispatch'):
            with self.subTest(event=event):
                fixture['run']['event'] = event
                self.run_authenticated(fixture)
        fixture['run']['event'] = 'push'
        with patch.dict(os.environ, {'CANDIDATE_RUN': str(fixture['run']['id'])}):
            with self.assertRaisesRegex(ConfigurationFailure, 'trusted_manual_main_run'):
                self.real_anchor(self.bundle, api=fixture['api'])
        with self.assertRaisesRegex(ConfigurationFailure, 'trusted_manual_main_run'):
            reuse.smoke.trusted_run(fixture['run']['id'], reuse.smoke.REFRESH,
                terminal=False, allow_failed=True, api=fixture['api'])

    def test_bad_target_run_metadata_fails_before_artifact_or_owner_access(self):
        cases = [('event', 'pull_request'), ('event', 'repository_dispatch'), ('head_branch', 'feature'),
            ('head_sha', self.publication), ('head_sha', 'f'*40), ('path', reuse.smoke.existing.WORKFLOW),
            ('repository', {'full_name': 'foreign/repo'}), ('head_repository', {'full_name': 'foreign/repo'}),
            ('run_attempt', None), ('run_attempt', True), ('run_attempt', 0), ('run_attempt', '1'),
            ('status', 'queued'), ('conclusion', 'neutral'), ('status', 'waiting')]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                fixture = self.authenticated_artifact(); fixture['run'][field] = value
                with self.assertRaises(ConfigurationFailure): self.run_authenticated(fixture)
                self.assertEqual(len(fixture['api'].call_args_list), 1)
        self.owner.assert_not_called(); self.assertEqual(self.calls, [])

    def test_artifact_metadata_digest_payload_and_manifest_identity_are_all_checked(self):
        def foreign_head(f): f['artifact']['workflow_run']['head_sha'] = self.publication
        def wrong_run(f): f['artifact']['workflow_run']['id'] = 1
        def expired(f): f['artifact']['expired'] = True
        def bad_id(f): f['artifact']['id'] = True
        def changed_raw(f): f['raw'] += b'tampered'
        def changed_payload(f): self.archive_payloads(f, {'files/data/science.json': b'changed science'})
        def extra_file(f): self.archive_payloads(f, {'private-note.json': b'not a public payload'})
        def changed_manifest_bytes(f):
            self.archive_payloads(f, {'candidate.json': (self.bundle/'candidate.json').read_bytes()+b' '})
        def changed_manifest_value(f):
            value = deepcopy(self.target); value['generation_timestamp'] = 'changed'
            self.archive_payloads(f, {'candidate.json': reuse.release.encoded(value)})
        for change in (foreign_head, wrong_run, expired, bad_id, changed_raw, changed_payload,
                extra_file, changed_manifest_bytes, changed_manifest_value):
            with self.subTest(change=change.__name__):
                fixture = self.authenticated_artifact(); change(fixture)
                with self.assertRaises((ConfigurationFailure, ValueError)): self.run_authenticated(fixture)
        self.owner.assert_not_called(); self.assertFalse(self.reports.exists())

    def test_runtime_target_route_requires_full_classification_even_when_called_directly(self):
        fixture = self.authenticated_artifact()
        self.completed.return_value = None
        with patch('tools.catalog_projection_recovery.plan', return_value={'candidate_id': self.anchor['candidate_id']}), \
                patch.dict(os.environ, {'CANDIDATE_RUN': str(fixture['run']['id'])}):
            with self.assertRaisesRegex(ConfigurationFailure, 'protected_completion_required'):
                self.real_anchor(self.bundle, runtime_root=self.root, api=fixture['api'])
        fixture['api'].assert_not_called(); self.owner.assert_not_called()


def identity_bytes(value): return reuse.release.digest(value)


def candidate_identity(value): return reuse.release.digest(reuse.release.encoded(value))


if __name__ == '__main__': unittest.main()
