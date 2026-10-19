"""Public-byte recovery of complete private checkpoints, without new work."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import program_area_revalidation as p, release_candidate as c
from tools import catalog_reconcile_spend as spend
from tests import test_modern_program_area_budget as fixture_module


def write_bundle(path, raw, manifest=None):
    path = Path(path)
    if manifest is None:
        manifest = {'schema_version': 1, 'candidate_format': c.VERSION,
            'files': {name: c.digest(value) for name, value in raw.items()}}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
    path.mkdir(parents=True, exist_ok=True)
    (path/'candidate.json').write_bytes(c.encoded(manifest))
    for name, value in raw.items():
        target = path/'files'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    return manifest


def inventory(path):
    return {n.relative_to(path).as_posix(): n.read_bytes()
        for n in Path(path).rglob('*') if n.is_file()}


class PublicBundleHydration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = {'.nojekyll': b'\n', 'data/science.json': b'{"retained":true}\n',
            'data/search-v2-voyage-vectors.f16': bytes([0, 255, 127, 128])}
        self.public = self.root/'authenticated-public'
        self.manifest = write_bundle(self.public, self.raw)
        self.assertEqual(c.load(self.public), self.manifest)

    def partial(self, missing=('.nojekyll',)):
        target = self.root/'private'
        write_bundle(target, {n: b for n, b in self.raw.items() if n not in missing}, self.manifest)
        return target

    def test_missing_hidden_file_is_copied_as_exact_public_bytes(self):
        private = self.partial()
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ: .nojekyll'):
            c.load(private)
        p.hydrate_public_bundle(private, self.manifest, [self.public])
        self.assertEqual(c.load(private), self.manifest)
        self.assertEqual(inventory(private), inventory(self.public))

    def test_binary_public_file_is_recovered_without_text_conversion(self):
        private = self.partial(('.nojekyll', 'data/search-v2-voyage-vectors.f16'))
        p.hydrate_public_bundle(private, self.manifest, [self.public])
        self.assertEqual(inventory(private), inventory(self.public))

    def test_present_corrupt_bytes_are_never_replaced(self):
        private = self.partial()
        (private/'files/data/science.json').write_bytes(b'corrupt existing checkpoint')
        before = inventory(private)
        with self.assertRaises(ValueError):
            p.hydrate_public_bundle(private, self.manifest, [self.public])
        self.assertEqual(inventory(private), before)

    def test_unmanifested_member_is_rejected_before_missing_file_write(self):
        private = self.partial()
        (private/'files/extra.json').write_bytes(b'{}')
        before = inventory(private)
        with self.assertRaises(ValueError):
            p.hydrate_public_bundle(private, self.manifest, [self.public])
        self.assertEqual(inventory(private), before)

    def test_changed_canonical_manifest_or_candidate_id_cannot_be_repaired(self):
        for change in ('identity', 'manifest'):
            with self.subTest(change=change):
                private = self.root/change
                write_bundle(private, {n: b for n, b in self.raw.items() if n != '.nojekyll'}, self.manifest)
                value = deepcopy(self.manifest)
                if change == 'identity':
                    value['candidate_id'] = 'f'*64
                else:
                    value['extra_field'] = 'different immutable manifest'
                    value['candidate_id'] = c.digest(c.encoded({k: v for k, v in value.items() if k != 'candidate_id'}))
                (private/'candidate.json').write_bytes(c.encoded(value))
                before = inventory(private)
                with self.assertRaises(ValueError):
                    p.hydrate_public_bundle(private, self.manifest, [self.public])
                self.assertEqual(inventory(private), before)

    def test_parent_public_fallback_requires_each_child_declared_hash(self):
        child_raw = dict(self.raw, **{'data/science.json': b'{"corrected":true}\n'})
        child = self.root/'child'
        manifest = write_bundle(child, child_raw)
        (child/'files/.nojekyll').unlink()
        p.hydrate_public_bundle(child, manifest, [self.public])
        self.assertEqual(c.load(child), manifest)
        self.assertEqual((child/'files/data/science.json').read_bytes(), child_raw['data/science.json'])

    def test_all_missing_hashes_must_be_proven_before_any_write(self):
        child_raw = dict(self.raw, **{'data/science.json': b'{"corrected":true}\n'})
        child = self.root/'child'
        manifest = write_bundle(child, child_raw)
        for name in ('.nojekyll', 'data/science.json'):
            (child/'files'/name).unlink()
        before = inventory(child)
        with self.assertRaises(ValueError):
            p.hydrate_public_bundle(child, manifest, [self.public])
        self.assertEqual(inventory(child), before)

    def test_missing_public_proof_does_not_synthesize_known_hidden_file(self):
        private = self.partial()
        before = inventory(private)
        with self.assertRaises(ValueError):
            p.hydrate_public_bundle(private, self.manifest, [])
        self.assertEqual(inventory(private), before)


class CompletedPrivateCheckpointHydration(unittest.TestCase):
    def setUp(self):
        # Instantiate the shared fixture without inheriting its unittest cases.
        self.fixture = fixture_module.ModernProgramAreaBudget(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        f.raw['.nojekyll'] = b'\n'
        (f.root/'.nojekyll').write_bytes(b'\n')
        (f.bundle/'files/.nojekyll').write_bytes(b'\n')
        f.manifest['files']['.nojekyll'] = c.digest(b'\n')
        f.manifest['generation_files']['.nojekyll'] = c.digest(b'\n')
        f.manifest.pop('candidate_id')
        f.manifest['candidate_id'] = c.digest(c.encoded(f.manifest))
        f.cid = f.manifest['candidate_id']
        (f.bundle/'candidate.json').write_bytes(c.encoded(f.manifest))
        parent = f.artifacts[0]
        parent['name'] = 'candidate-'+f.cid
        f.archives[parent['id']] = fixture_module.zipped({'candidate.json': c.encoded(f.manifest),
            **{'files/'+n: raw for n, raw in f.raw.items()}})
        parent['digest'] = 'sha256:'+p.sha(f.archives[parent['id']])
        self.assertEqual(c.load(f.bundle), f.manifest)

    def completed_checkpoint(self, *, native_child=True, child_hidden=b'\n'):
        f = self.fixture
        state = f.root/'program-state'
        prepared = f.prepare(state, changed=False)
        outputs = {n: ('corrected projection '+n).encode() for n in p.PROJECTION}
        with patch.object(p, 'vector_packet', return_value=dict(f.packet, retained_asset_eligible=True)), \
                patch.object(p, 'modern_scope'), \
                patch.object(p, 'modern_contract', return_value={'scripts/extract_document_evidence.py': '6'*64}), \
                patch.object(p, 'projection', return_value=(outputs, {'source_requests': 0,
                    'document_ai_requests': 0, 'team_requests': 0})):
            sealed = p.checkpoint_modern(f.root/'receipt.json', state, root=f.root)
        child = deepcopy(f.manifest)
        child.pop('candidate_id')
        child['derived_from_candidate'] = f.cid
        child['program_area_revalidation'] = sealed | {'affected_generation': {
            'generation_run_id': '456', 'generation_run_attempt': '1', 'generation_sha': 'e'*40,
            'generation_timestamp': '2026-10-19T02:00:00Z'}}
        child['files']['.nojekyll'] = c.digest(child_hidden)
        child['candidate_id'] = c.digest(c.encoded(child))
        bundle = f.root/'complete-child'
        write_bundle(bundle, dict(f.raw, **{'.nojekyll': child_hidden}), child)
        p.record_modern_candidate(state, bundle)
        payload = inventory(bundle)
        if native_child:
            f.add_artifact('candidate-'+child['candidate_id'], '456', payload)
        f.add_artifact(prepared['reservation_artifact'], '456',
            {'reservation.json': Path(prepared['reservation_path']).read_bytes()})
        private = {n: raw for n, raw in f.state_files(state).items() if not n.endswith('/.nojekyll')}
        self.assertEqual(sum(n.endswith('/candidate.json') for n in private), 2)
        f.add_artifact(prepared['state_artifact'], '456', private)
        f.runs[('456','1')]['status'] = 'completed'
        return state, bundle, child

    def restore(self, run, state, output):
        f = self.fixture
        f.runs[(run,'1')] = f.run_meta(run, '1', run[0]*40, current=True)
        with patch.object(c, 'verify_dependencies'), \
                patch.object(p, 'projection', side_effect=AssertionError('completed projection must not run')), \
                patch.object(p, 'vector_packet', side_effect=AssertionError('completed vectors must not run')):
            # The fixture's prepare patches projection/vector collection itself;
            # use the production entry point with only immutable scope stubs.
            with patch.dict('os.environ', GITHUB_RUN_ID=run, GITHUB_RUN_ATTEMPT='1',
                    GITHUB_SHA=f.runs[(run,'1')]['head_sha']), patch.object(p, 'modern_scope'), \
                    patch.object(p, 'modern_contract', return_value={'scripts/extract_document_evidence.py': '6'*64}):
                return p.prepare_modern(f.bundle, f.root/('receipt-'+run+'.json'), state,
                    '123', f.cid, root=f.root, api=f.api, output=output)

    def test_consecutive_cold_completed_resumes_rehydrate_once_and_preserve_budget_caches(self):
        f = self.fixture
        original_state, bundle, child = self.completed_checkpoint()
        book = (original_state/'ledger.json').read_bytes()
        caches = {n: b for n, b in inventory(original_state).items()
            if n.startswith(('vector-responses/', 'vector-requests/', 'vector-completions/'))}
        first_state = f.root/'restore-one'
        with patch('tools.program_area_history.completed_restore') as proof:
            first = self.restore('789', first_state, f.root/'child-one')
            self.assertEqual(first['candidate_id'], child['candidate_id'])
            self.assertEqual(first['artifact_run'], '456')
            self.assertEqual(first['upload_candidate'], 'false')
            self.assertEqual(inventory(f.root/'child-one'), inventory(bundle))
            self.assertEqual((first_state/'ledger.json').read_bytes(), book)
            self.assertEqual({n: b for n, b in inventory(first_state).items() if n in caches}, caches)
            f.add_artifact(first['state_artifact'], '789', f.state_files(first_state))
            f.runs[('789','1')]['status'] = 'completed'
            second_state = f.root/'restore-two'
            second = self.restore('888', second_state, f.root/'child-two')
            self.assertEqual(second['candidate_id'], child['candidate_id'])
            self.assertEqual(second['artifact_run'], '456')
            self.assertEqual(second['upload_candidate'], 'false')
            self.assertEqual(inventory(f.root/'child-two'), inventory(bundle))
            self.assertEqual((second_state/'ledger.json').read_bytes(), book)
            self.assertEqual({n: b for n, b in inventory(second_state).items() if n in caches}, caches)
            links = p.read(second_state/'consumed-checkpoints.json')
            self.assertEqual([n['producer']['run_id'] for n in links], ['456', '789'])
            self.assertTrue(links[-1]['restored'])
            proof.assert_called_once()
        f.http.assert_not_called()

    def test_absent_native_child_can_recover_matching_public_parent_file_only(self):
        f = self.fixture
        original_state, bundle, child = self.completed_checkpoint(native_child=False)
        state = f.root/'restore-parent-fallback'
        restored = self.restore('789', state, f.root/'child-fallback')
        self.assertEqual(restored['candidate_id'], child['candidate_id'])
        self.assertEqual(restored['upload_candidate'], 'true')
        self.assertEqual(restored['artifact_run'], '789')
        self.assertEqual(inventory(f.root/'child-fallback'), inventory(bundle))
        self.assertEqual((state/'ledger.json').read_bytes(), (original_state/'ledger.json').read_bytes())
        f.http.assert_not_called()

    def test_absent_native_child_cannot_guess_hidden_bytes_with_different_child_hash(self):
        f = self.fixture
        original_state, _, _ = self.completed_checkpoint(native_child=False, child_hidden=b'\n\n')
        before = (original_state/'ledger.json').read_bytes()
        with self.assertRaises(ValueError):
            self.restore('789', f.root/'unproven-child', f.root/'unproven-output')
        self.assertFalse((f.root/'unproven-output').exists())
        self.assertEqual((original_state/'ledger.json').read_bytes(), before)
        f.http.assert_not_called()

    def test_older_state_only_transport_missing_hidden_files_is_normalized_before_comparison(self):
        f = self.fixture
        original_state, bundle, child = self.completed_checkpoint()
        first_state = f.root/'old-upload-one'
        first = self.restore('789', first_state, f.root/'old-child-one')
        omitted = {n: raw for n, raw in f.state_files(first_state).items() if not n.endswith('/.nojekyll')}
        f.add_artifact(first['state_artifact'], '789', omitted)
        f.runs[('789','1')]['status'] = 'completed'
        second_state = f.root/'old-upload-two'
        with patch('tools.program_area_history.completed_restore') as proof:
            second = self.restore('888', second_state, f.root/'old-child-two')
            self.assertEqual(second['candidate_id'], child['candidate_id'])
            self.assertEqual(inventory(f.root/'old-child-two'), inventory(bundle))
            self.assertEqual((second_state/'ledger.json').read_bytes(), (original_state/'ledger.json').read_bytes())
            proof.assert_called_once()
        f.http.assert_not_called()

    def test_corrupted_authenticated_public_transport_does_not_repair_private_bytes(self):
        f = self.fixture
        self.completed_checkpoint()
        row = next(r for r in f.artifacts if r['name'].startswith('candidate-')
            and r['workflow_run']['id'] == 456)
        f.archives[row['id']] += b'corrupted raw transport'
        with self.assertRaisesRegex(ValueError, 'artifact_digest'):
            self.restore('789', f.root/'bad-transport', f.root/'bad-output')
        self.assertFalse((f.root/'bad-output').exists())
        f.http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
