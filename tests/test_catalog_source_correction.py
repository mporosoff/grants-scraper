"""Fixed artifact admission and immutable source preparation, with no HTTP."""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import catalog_source_correction as correction
from tools import release_candidate as release


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


if __name__ == '__main__':
    unittest.main()
