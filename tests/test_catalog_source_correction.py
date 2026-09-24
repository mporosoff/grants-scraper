"""Fixed artifact admission and immutable source preparation, with no HTTP."""
import io
import json
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import catalog_source_correction as correction
from tools import release_candidate as release
from tools import catalog_projection_recovery as projection
from tools.offline_spend import ConfigurationFailure


class CatalogCorrectionArtifact(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name) / 'original'
        manifest = {'schema_version': 1, 'candidate_format': release.VERSION,
            'files': {'data/safe.json': correction.sha(b'{}')}}
        manifest['candidate_id'] = correction.sha(release.encoded(manifest))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('candidate.json', release.encoded(manifest))
            z.writestr('files/data/safe.json', b'{}')
        self.raw = archive.getvalue()
        self.config = {'repository': 'mporosoff/grants-scraper', 'candidate_run': '123',
            'prior_sha': 'a' * 40, 'candidate_id': manifest['candidate_id'],
            'candidate_artifact_id': 456, 'candidate_artifact_digest': 'sha256:' + correction.sha(self.raw)}
        self.meta = {'id': 123, 'head_sha': 'a' * 40, 'head_branch': 'main',
            'path': '.github/workflows/refresh-opportunities.yml', 'event': 'schedule', 'status': 'completed'}
        self.artifact = {'id': 456, 'digest': self.config['candidate_artifact_digest'],
            'name': 'candidate-' + manifest['candidate_id'], 'expired': False,
            'workflow_run': {'id': 123, 'head_sha': 'a' * 40}}
        self.addCleanup(patch.stopall)
        patch.object(correction, 'plan', return_value=self.config).start()

    def api(self, path):
        return {'actions/runs/123': json.dumps(self.meta).encode(),
            'actions/artifacts/456': json.dumps(self.artifact).encode(),
            'actions/artifacts/456/zip': self.raw}[path]

    def test_failed_downstream_run_can_retain_exact_safe_generation(self):
        self.meta['conclusion'] = 'failure'
        correction.fetch_candidate(self.dest, api=self.api)
        self.assertEqual((self.dest / 'files/data/safe.json').read_bytes(), b'{}')
        with self.assertRaisesRegex(ValueError, 'new_artifact_destination'):
            correction.fetch_candidate(self.dest, api=self.api)

    def test_foreign_branch_workflow_and_artifact_owner_reject_before_copy(self):
        for key, value in [('head_branch', 'feature'), ('path', '.github/workflows/tests.yml'), ('head_sha', 'b' * 40)]:
            original = self.meta[key]; self.meta[key] = value
            with self.assertRaisesRegex(ValueError, 'original_refresh_run'):
                correction.fetch_candidate(self.dest, api=self.api)
            self.meta[key] = original
        self.artifact['workflow_run']['id'] = 124
        with self.assertRaisesRegex(ValueError, 'original_artifact'):
            correction.fetch_candidate(self.dest, api=self.api)
        self.assertFalse(self.dest.exists())

    def test_complete_archive_digest_not_only_manifest_is_required(self):
        self.raw += b'tampering'
        with self.assertRaisesRegex(ValueError, 'original_zip_digest'):
            correction.fetch_candidate(self.dest, api=self.api)
        self.assertFalse(self.dest.exists())

    def test_traversal_and_duplicate_entries_fail_closed(self):
        for name in ('../escaped', 'files/data/safe.json'):
            stream = io.BytesIO(self.raw)
            with zipfile.ZipFile(stream, 'a') as z:
                z.writestr(name, b'bad')
            self.raw = stream.getvalue()
            self.config['candidate_artifact_digest'] = 'sha256:' + correction.sha(self.raw)
            self.artifact['digest'] = self.config['candidate_artifact_digest']
            with self.assertRaises(ValueError):
                correction.fetch_candidate(self.dest, api=self.api)
            self.assertFalse((self.dest.parent / 'escaped').exists())


class AuthenticatedSmokeDispatch(unittest.TestCase):
    def setUp(self):
        self.context = {'expected': {'operations': [{'purpose': 'cb-fc-cat-smoke-embed',
            'public_body_text': '{"query":"catalysis"}',
            'provider_body_text': '{"input":["catalysis"],"model":"voyage-4-lite"}'}]},
            'serving_proof': {'candidate': {'candidate_id': 'a' * 64}},
            'external_bodies': {'smoke-embed': {'query': 'catalysis'}}}
        self.provider = json.loads(self.context['expected']['operations'][0]['provider_body_text'])
        self.auth = unittest.mock.Mock(return_value=self.context)
        patcher = patch.dict('sys.modules', {'tools.catalog_smoke_receipt': SimpleNamespace(load_context=self.auth)})
        patcher.start(); self.addCleanup(patcher.stop)
        correction._smoke_dispatch = None
        self.addCleanup(setattr, correction, '_smoke_dispatch', None)

    def test_only_authenticated_exact_named_context_can_dispatch(self):
        args = correction.smoke_dispatch_inputs(Path('state'), Path('inputs'), 'smoke-embed')
        self.auth.assert_called_once_with(Path('state'), Path('inputs'))
        actual = correction.verify_smoke_dispatch('smoke-embed', self.provider, **args)
        self.assertEqual(actual, {'query': 'catalysis'})
        with self.assertRaisesRegex(ValueError, 'authenticated_in_this_process'):
            correction.verify_smoke_dispatch('smoke-embed', self.provider,
                args['external_body'], json.loads(json.dumps(args['serving_proof'])))
        with self.assertRaisesRegex(ValueError, 'authenticated_in_this_process'):
            correction.verify_smoke_dispatch('smoke-current-rerank', self.provider, **args)

    def test_changed_body_proof_or_expired_context_never_dispatches(self):
        args = correction.smoke_dispatch_inputs('state', 'inputs', 'smoke-embed')
        for body, provider in (({'query': 'different'}, self.provider),
                               (args['external_body'], {'input': ['different']})):
            with self.assertRaisesRegex(ValueError, 'unchanged_authenticated'):
                correction.verify_smoke_dispatch('smoke-embed', provider, body, args['serving_proof'])
        args['serving_proof']['candidate']['candidate_id'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'unchanged_authenticated'):
            correction.verify_smoke_dispatch('smoke-embed', self.provider, **args)
        with patch.object(correction.time, 'monotonic', return_value=correction._smoke_dispatch['authenticated_at'] + 301):
            with self.assertRaisesRegex(ValueError, 'fresh_smoke'):
                correction.verify_smoke_dispatch('smoke-embed', self.provider, **args)

    def test_failed_authentication_cannot_reuse_an_earlier_context(self):
        args = correction.smoke_dispatch_inputs('state', 'inputs', 'smoke-embed')
        self.auth.side_effect = ValueError('authentication failed')
        with self.assertRaisesRegex(ValueError, 'authentication failed'):
            correction.smoke_dispatch_inputs('state', 'inputs', 'smoke-embed')
        with self.assertRaisesRegex(ValueError, 'authenticated_in_this_process'):
            correction.verify_smoke_dispatch('smoke-embed', self.provider, **args)


class ProjectionContextBinding(unittest.TestCase):
    """Synthetic context boundary; the projection module owns exact 126-file tests."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs, self.bundle, self.original, self.export = [self.root / n for n in ('inputs', 'candidate', 'original', 'export')]
        for path in (self.inputs, self.bundle, self.original, self.export): path.mkdir()
        self.worker = b'export const fixed = true;\n'
        self.catalog = {'opportunities': [{'opportunity_id': 'public-1', 'title': 'Public research'}],
            'diagnostics': {'additional_sources': {'lifecycle': []}}}
        self.previous = {'corpus_sha256': '1' * 64, 'model_space_fingerprint': '2' * 64}
        self.current = {'corpus_sha256': '3' * 64, 'model_space_fingerprint': '4' * 64}
        self.payloads = {n: b'{}' for n in correction.VECTOR_FILES}
        self.payloads.update({'data/opportunities.js': b'globalThis.GRANT_CATALOG=' + release.encoded(self.catalog) + b';\n',
            'data/source_records.json': b'{"records":{}}', 'data/document_evidence.json': b'{"records":{}}',
            'data/unrelated.json': b'{"retained":true}',
            'data/search-v2-voyage-manifest.json': release.encoded({'model_space_fingerprint': self.current['model_space_fingerprint']}),
            'workers/search-voyage-proxy/generated/corpus-allowlist.json': release.encoded({'current': self.current, 'previous': self.previous}),
            'workers/search-voyage-proxy/wrangler.jsonc': b'{}',
            'workers/search-voyage-proxy/src/index.js': self.worker})
        self.original_manifest = {'schema_version': 1, 'candidate_format': release.VERSION,
            'generation_sha': 'a' * 40, 'generation_run_id': '7', 'generation_run_attempt': '1',
            'generation_timestamp': '2026-09-23T00:00:00Z', 'generation_dependencies': {},
            'generation_baseline': {}, 'semantic_identity': {},
            'files': {n: correction.sha(raw) for n, raw in self.payloads.items()}}
        self.original_manifest['generation_files'] = {n: h for n, h in self.original_manifest['files'].items() if n.startswith('data/')}
        self.write_bundle(self.original, self.original_manifest)
        self.config = {'candidate_id': self.original_manifest['candidate_id'], 'prior_sha': 'a' * 40,
            'corpus_sha256': self.current['corpus_sha256'], 'smoke_passage_id': 'parent:public-1',
            'smoke_passage_sha256': correction.sha(b'Public passage.')}
        self.config_path = self.root / 'source.json'; self.config_path.write_bytes(b'{}')
        self.exported = {'spending_plan_sha256': '5' * 64,
            'files': {n: self.original_manifest['files'][n] for n in correction.VECTOR_FILES}}
        (self.export / 'export.json').write_bytes(release.encoded(self.exported))
        self.manifest = deepcopy(self.original_manifest)
        self.manifest['worker_fingerprint'] = '6' * 64
        self.manifest['original_generation'] = {k: deepcopy(self.original_manifest[k]) for k in (
            'generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
            'generation_dependencies', 'generation_baseline', 'generation_files', 'semantic_identity')}
        self.manifest['source_correction'] = {'version': correction.VERSION,
            'source_plan_sha256': correction.sha(b'{}'), 'spending_plan_sha256': '5' * 64,
            'export_sha256': correction.sha((self.export / 'export.json').read_bytes()),
            'owner_run': 100, 'original_candidate_id': self.config['candidate_id']}
        self.context = {'version': 'catalog-correction-smoke-context-v1', 'source_plan_sha256': correction.sha(b'{}'),
            'candidate': {}, 'correction_export': {'export_sha256': self.manifest['source_correction']['export_sha256'], 'owner_run': 100},
            'generations': {'current': self.current, 'previous': self.previous}, 'refresh': {'head_sha': 'b' * 40}}
        (self.inputs / 'corrected-catalog.json').write_bytes(release.encoded(self.catalog))
        (self.inputs / 'corrected-source-cache.json').write_bytes(self.payloads['data/source_records.json'])
        (self.inputs / 'corpus.json').write_bytes(release.encoded([{'passage_id': 'parent:public-1', 'text': 'Public passage.'}]))
        for name in ('embed', 'current-rerank', 'previous-rerank'):
            (self.inputs / ('smoke-' + name + '-provider.json')).write_bytes(b'{"query":"catalysis"}')
        self.refresh()
        self.addCleanup(patch.stopall)
        patch.object(correction, 'CONFIG', self.config_path).start()
        patch.object(correction, 'plan', return_value=self.config).start()
        self.inputs_check = patch.object(correction, 'verify_inputs', return_value={'candidate_root': self.original}).start()
        patch.object(correction, 'verify_export', return_value=self.exported).start()
        self.worker_read = patch.object(correction.subprocess, 'check_output', return_value=self.worker).start()

    def write_bundle(self, bundle, manifest):
        for name, raw in self.payloads.items():
            target = bundle / 'files' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        manifest['files'] = {n: correction.sha(raw) for n, raw in self.payloads.items()}
        manifest.pop('candidate_id', None); manifest['candidate_id'] = correction.sha(release.encoded(manifest))
        (bundle / 'candidate.json').write_bytes(release.encoded(manifest))

    def refresh(self):
        self.write_bundle(self.bundle, self.manifest)
        self.context['candidate'] = {'candidate_id': self.manifest['candidate_id'],
            'manifest_sha256': correction.sha((self.bundle / 'candidate.json').read_bytes())}

    def repaired(self):
        self.manifest['projection_recovery'] = {'version': 'synthetic-fixed-projection'}
        self.payloads['data/document_evidence.json'] = b'{"records":{"public-1":{"retained":true}}}'
        value = deepcopy(self.catalog); value['opportunities'][0]['next_submission'] = {'as_of': '2026-09-23'}
        self.payloads['data/opportunities.js'] = b'globalThis.GRANT_CATALOG=' + release.encoded(value) + b';\n'
        self.refresh()

    def run_context(self):
        return correction.validate_context_packet(self.context, self.bundle, self.export, self.root / 'state', self.inputs)

    def test_ordinary_candidate_uses_original_catalog_rule_without_projection_verifier(self):
        with patch.object(projection, 'verify_candidate', side_effect=AssertionError('ordinary path')):
            self.assertEqual(len(self.run_context()['expected']['operations']), 3)
        self.repaired(); self.manifest.pop('projection_recovery'); self.refresh()
        with self.assertRaisesRegex(ValueError, 'unaffected_generation_retained'):
            self.run_context()

    def test_verified_fixed_projection_admits_only_its_exact_catalog_and_cache(self):
        self.repaired()
        with patch.object(projection, 'verify_candidate', return_value={'manifest': deepcopy(self.manifest)}) as verify:
            value = self.run_context()
        verify.assert_called_once_with(self.bundle, root=correction.ROOT)
        self.assertEqual(len(value['expected']['operations']), 3)
        self.assertEqual(value['expected']['worker_input_fingerprint'], '6' * 64)
        self.worker_read.assert_called_once()

    def test_present_malformed_projection_never_falls_back_even_with_ordinary_catalog(self):
        for marker in (None, False, {}, {'version': 'unknown'}):
            with self.subTest(marker=marker):
                self.manifest['projection_recovery'] = marker; self.refresh()
                self.inputs_check.reset_mock()
                with patch.object(projection, 'verify_candidate', side_effect=ValueError('fixed_projection_rejected')) as verify:
                    with self.assertRaisesRegex(ValueError, 'fixed_projection_rejected'): self.run_context()
                verify.assert_called_once(); self.inputs_check.assert_not_called()

    def test_real_fixed_verifier_rejects_unpinned_manifest_before_context_admission(self):
        self.repaired()
        with self.assertRaisesRegex(ConfigurationFailure, 'projection_recovery_derived_manifest_bytes'):
            self.run_context()
        self.inputs_check.assert_not_called()

    def test_projection_result_must_be_same_manifest_and_all_owned_checks_still_apply(self):
        self.repaired()
        with patch.object(projection, 'verify_candidate', return_value={'manifest': {'foreign': True}}):
            with self.assertRaisesRegex(ValueError, 'exact_verified_projection_candidate'): self.run_context()
        for category, expected in [('owner', 'candidate_affected_generation_lineage'),
                ('vector', 'exact_owned_vector_export'), ('sources', 'complete_corrected_public_sources'),
                ('unrelated', 'unaffected_generation_retained'), ('worker', 'protected_worker_runtime')]:
            saved_manifest, saved_payloads = deepcopy(self.manifest), dict(self.payloads)
            if category == 'owner': self.manifest['source_correction']['owner_run'] += 1
            elif category == 'vector': self.payloads['data/search-v2-voyage-vectors.f16'] = b'changed'
            elif category == 'sources': self.payloads['data/source_records.json'] = b'{"foreign":true}'
            elif category == 'unrelated': self.payloads['data/unrelated.json'] = b'{"retained":false}'
            else: self.payloads['workers/search-voyage-proxy/src/index.js'] = b'export const changed = true;'
            self.refresh()
            with self.subTest(category=category), patch.object(projection, 'verify_candidate', return_value={'manifest': deepcopy(self.manifest)}):
                with self.assertRaisesRegex(ValueError, expected): self.run_context()
            self.manifest, self.payloads = saved_manifest, saved_payloads; self.refresh()


if __name__ == '__main__':
    unittest.main()
