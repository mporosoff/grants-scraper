"""Same-run public document inputs survive pre-candidate failure, offline."""
from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import generation_document_checkpoint as checkpoint
from tools import generation_spend_checkpoint as spending
from tools.offline_ai import Ledger


class DocumentCheckpoint(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root = self.temp / 'repository'
        self.root.mkdir()
        self.baseline = {'data/document_evidence.json': b'{"records":{"old":{"status":"current"}}}\n',
                         'data/subtopics.js': b'globalThis.SUBTOPIC_CATALOG={"subtopics":[]};\n'}
        self.updated = {name: raw + b'\n' for name, raw in self.baseline.items()}
        for name, raw in self.baseline.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'protected baseline')
        self.state = self.temp / 'offline-123'
        self.ledger = Ledger(self.state / 'ledger.json', 'offline-123', 2)
        self.ledger.reserve('anthropic', 'fixture-model', 'cov4', 'uncertain', 12345, 1)
        self.ledger_before = self.ledger.path.read_bytes()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL)

    def capture(self):
        for name, raw in self.updated.items():
            (self.root / name).write_bytes(raw)
        return checkpoint.capture(self.root, self.state, '123', '1')

    def reset_public_files(self):
        for name, raw in self.baseline.items():
            (self.root / name).write_bytes(raw)

    def manifest_path(self):
        return self.state / checkpoint.DIRECTORY / checkpoint.MANIFEST

    def change_manifest(self, **changes):
        value = json.loads(self.manifest_path().read_bytes())
        value.update(changes)
        self.manifest_path().write_text(json.dumps(value), encoding='utf-8')

    def assert_baseline(self):
        self.assertEqual({name: (self.root / name).read_bytes() for name in checkpoint.FILES}, self.baseline)
        self.assertEqual(self.ledger.path.read_bytes(), self.ledger_before)

    def test_original_run_without_checkpoint_keeps_existing_public_inputs_and_accounting(self):
        self.assertFalse(checkpoint.restore(self.root, self.state, '123', '2'))
        self.assert_baseline()

    def test_round_trip_restores_exact_public_bytes_without_catalog_or_private_files(self):
        (self.root / 'data/opportunities.js').write_bytes(b'current rebuilt source catalog')
        private = self.root / '.cache/notice-structure/private.txt'
        private.parent.mkdir(parents=True)
        private.write_bytes(b'private normalized notice')
        manifest = self.capture()
        self.reset_public_files()
        self.assertTrue(checkpoint.restore(self.root, self.state, '123', '2'))
        self.assertEqual({name: (self.root / name).read_bytes() for name in checkpoint.FILES}, self.updated)
        self.assertEqual((self.root / 'data/opportunities.js').read_bytes(), b'current rebuilt source catalog')
        retained = list((self.state / checkpoint.DIRECTORY).rglob('*'))
        self.assertEqual(set(manifest['files']), set(checkpoint.FILES))
        self.assertEqual(sum(path.is_file() for path in retained), 3)
        self.assertNotIn(b'private normalized notice', b''.join(path.read_bytes() for path in retained if path.is_file()))
        self.assertEqual(self.ledger.path.read_bytes(), self.ledger_before)

    def test_corrupt_second_blob_never_restores_the_first_file(self):
        manifest = self.capture()
        self.reset_public_files()
        blob = self.state / checkpoint.DIRECTORY / 'blobs' / manifest['files'][checkpoint.FILES[1]]
        blob.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            checkpoint.restore(self.root, self.state, '123', '2')
        self.assert_baseline()

    def test_identity_and_allowlist_fail_closed_before_mutating_public_inputs(self):
        manifest = self.capture()
        self.reset_public_files()
        mutations = ({'run_id': '124'}, {'run_attempt': '2'}, {'generation_sha': 'f' * 40},
                     {'files': manifest['files'] | {'data/opportunities.js': 'a' * 64}},
                     {'schema_version': True})
        for changes in mutations:
            with self.subTest(changes=changes):
                self.manifest_path().write_text(json.dumps(manifest | changes), encoding='utf-8')
                with self.assertRaises(ValueError):
                    checkpoint.restore(self.root, self.state, '123', '2')
                self.assert_baseline()

    def test_different_ledger_identity_cannot_restore_or_capture_another_run(self):
        self.capture()
        self.reset_public_files()
        for operation in (checkpoint.capture, checkpoint.restore):
            with self.assertRaisesRegex(ValueError, 'original generation ledger'):
                operation(self.root, self.state, '124', '2')
        self.assert_baseline()

    def test_changed_protected_baseline_requires_named_recovery(self):
        self.capture()
        self.reset_public_files()
        (self.root / checkpoint.FILES[0]).write_bytes(b'new protected evidence')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'new publication')
        before = {name: (self.root / name).read_bytes() for name in checkpoint.FILES}
        with self.assertRaisesRegex(ValueError, 'Protected document inputs changed'):
            checkpoint.restore(self.root, self.state, '123', '2')
        self.assertEqual({name: (self.root / name).read_bytes() for name in checkpoint.FILES}, before)

    def test_parser_only_commit_allows_native_revalidation_of_retained_outputs(self):
        self.capture()
        self.reset_public_files()
        (self.root / 'parser.py').write_text('# a protected parser repair\n', encoding='utf-8')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test', 'commit', '-qm', 'parser repair')
        self.assertTrue(checkpoint.restore(self.root, self.state, '123', '2'))
        self.assertEqual({name: (self.root / name).read_bytes() for name in checkpoint.FILES}, self.updated)

    def test_failed_capture_keeps_prior_complete_manifest_and_blobs(self):
        original = self.capture()
        for name in checkpoint.FILES:
            (self.root / name).write_bytes(b'new incomplete attempt')
        atomic = checkpoint._atomic_bytes
        calls = []
        def fail_second(path, raw):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('disk unavailable')
            return atomic(path, raw)
        with patch.object(checkpoint, '_atomic_bytes', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'disk unavailable'):
                checkpoint.capture(self.root, self.state, '123', '2')
        self.assertEqual(json.loads(self.manifest_path().read_bytes()), original)
        self.reset_public_files()
        self.assertTrue(checkpoint.restore(self.root, self.state, '123', '3'))
        self.assertEqual({name: (self.root / name).read_bytes() for name in checkpoint.FILES}, self.updated)

    def test_write_failure_rolls_back_both_public_files(self):
        self.capture()
        self.reset_public_files()
        atomic = checkpoint._atomic_bytes
        failed = False
        def fail_once(path, raw):
            nonlocal failed
            if path == self.root / checkpoint.FILES[1] and not failed:
                failed = True
                raise OSError('second destination unavailable')
            return atomic(path, raw)
        with patch.object(checkpoint, '_atomic_bytes', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'second destination unavailable'):
                checkpoint.restore(self.root, self.state, '123', '2')
        self.assert_baseline()

    def test_existing_spend_archive_transports_document_checkpoint_and_original_reservation(self):
        self.capture()
        self.reset_public_files()
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, 'w') as archive:
            for path in self.state.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(self.state).as_posix())
        artifacts = {'artifacts': [
            {'id': 1, 'name': 'generation-spend-reservation-123-1', 'expired': False},
            {'id': 2, 'name': 'generation-spend-state-123-1', 'expired': False}]}
        meta = {'path': '.github/workflows/refresh-opportunities.yml', 'head_branch': 'main'}
        def api(_repo, path):
            if path.endswith('/zip'):
                return archive_bytes.getvalue()
            return json.dumps(artifacts if 'artifacts?' in path else meta).encode()
        recovered = self.temp / 'rerun/offline-123'
        with patch.object(spending, 'api', side_effect=api):
            spending.prepare('owner/repo', '123', '2', recovered, self.temp / 'reservation.json', 'maintenance')
        self.assertTrue(checkpoint.restore(self.root, recovered, '123', '2'))
        self.assertEqual((recovered / 'ledger.json').read_bytes(), self.ledger_before)
        self.assertEqual({name: (self.root / name).read_bytes() for name in checkpoint.FILES}, self.updated)

    def test_helper_is_a_source_dependency(self):
        policy = checkpoint.release.read_json(checkpoint.release.ROOT / checkpoint.release.POLICY)
        self.assertIn('tools/generation_document_checkpoint.py', policy['dependency_groups']['source']['patterns'])


if __name__ == '__main__':
    unittest.main()
