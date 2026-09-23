"""Exact missing-marker recovery contracts; synthetic archives, no network or spend."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import catalog_candidate_recovery as recovery
from tools.offline_spend import ConfigurationFailure


class RecoveryFixture:
    """Only Git and HTTP are injected; artifact and candidate validators are real."""
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='marker-unit-')))
        self.bundle, self.reports = self.root/'bundle', self.root/'reports'
        self.spec = deepcopy(recovery.plan())
        self.spec.update(failed_run_id=101, artifact_id=102, failed_run_head='a'*40)
        self.payloads = {'index.html': b'<html>retained</html>\n', 'data/catalog.json': b'{"records":[]}\n'}
        self.manifest = {'schema_version': 1, 'candidate_format': recovery.release.VERSION,
            'files': {name: recovery.release.digest(raw) for name, raw in self.payloads.items()},
            'source_correction': {key: self.spec[key] for key in
                ('source_plan_sha256', 'spending_plan_sha256', 'export_sha256')}}
        self.manifest['files']['.nojekyll'] = self.spec['marker_sha256']
        self.seal_manifest()
        self.entries = {recovery.release.MANIFEST: self.manifest_raw,
            **{'files/'+name: raw for name, raw in self.payloads.items()}}
        self.run = {'id': 101, 'run_attempt': 1, 'path': recovery.smoke.REFRESH,
            'head_branch': 'main', 'head_sha': 'a'*40, 'event': 'workflow_dispatch',
            'status': 'completed', 'conclusion': 'failure'}
        self.repack()
        self.api = Mock(side_effect=self.read_api)
        self.stack.enter_context(patch.object(recovery, 'plan', return_value=self.spec))
        self.ancestor = self.stack.enter_context(patch.object(recovery.subprocess, 'run',
            return_value=subprocess.CompletedProcess([], 0)))
        self.git_blob = self.stack.enter_context(patch.object(recovery.subprocess, 'check_output', return_value=b'\n'))
        self.forbidden = [self.stack.enter_context(patch.object(module, name,
            side_effect=AssertionError('Generation is forbidden during recovery')))
            for module, name in ((recovery.source, 'prepare_inputs'),
                (recovery.release, 'create'), (recovery.release, 'create_source_correction'),
                (recovery.release, 'materialize'))]

    def seal_manifest(self):
        self.manifest.pop('candidate_id', None)
        self.manifest['candidate_id'] = recovery.release.digest(recovery.release.encoded(self.manifest))
        # Deliberately noncanonical formatting proves that recovery does not rewrite it.
        self.manifest_raw = (json.dumps(self.manifest, indent=3) + '\n').encode()
        self.spec['candidate_id'] = self.manifest['candidate_id']
        self.spec['manifest_sha256'] = recovery.release.digest(self.manifest_raw)

    def repack(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as writer:
            for name, raw in self.entries.items():
                writer.writestr(name, raw)
        self.archive = archive.getvalue()
        self.spec['artifact_sha256'] = recovery.release.digest(self.archive)
        self.artifact = {'id': 102, 'name': 'candidate-'+self.spec['candidate_id'],
            'expired': False, 'digest': 'sha256:'+self.spec['artifact_sha256'],
            'workflow_run': {'id': 101, 'head_sha': 'a'*40}}

    def update_manifest(self):
        self.seal_manifest()
        self.entries[recovery.release.MANIFEST] = self.manifest_raw
        self.repack()

    def read_api(self, path):
        if path == 'actions/runs/101':
            return recovery.release.encoded(self.run)
        if path == 'actions/artifacts/102':
            return recovery.release.encoded(self.artifact)
        if path == 'actions/artifacts/102/zip':
            return self.archive
        raise AssertionError('Unexpected API operation: '+path)

    def recover(self):
        return recovery.recover(self.bundle, self.reports, root=self.root, api=self.api)

    def close(self):
        self.stack.close()


class MarkerRecovery(unittest.TestCase):
    def setUp(self):
        self.f = RecoveryFixture()
        self.addCleanup(self.f.close)

    def rejects(self, reason, exception=ConfigurationFailure):
        with self.assertRaisesRegex(exception, reason):
            self.f.recover()
        self.assertFalse((self.f.bundle/'files/.nojekyll').exists())
        self.assertFalse((self.f.reports/'recovery.json').exists())

    def test_exact_lf_restored_with_raw_manifest_and_all_original_bytes_preserved(self):
        original_archive = self.f.archive
        actual = self.f.recover()
        self.assertEqual(actual, self.f.manifest)
        self.assertEqual((self.f.bundle/'candidate.json').read_bytes(), self.f.manifest_raw)
        self.assertEqual((self.f.bundle/'files/.nojekyll').read_bytes(), b'\n')
        self.assertEqual(self.f.archive, original_archive)
        for name, raw in self.f.payloads.items():
            self.assertEqual((self.f.bundle/'files'/name).read_bytes(), raw)
        self.assertEqual(recovery.release.load(self.f.bundle), self.f.manifest)
        self.ancestor_arguments_are_exact()
        receipt = json.loads((self.f.reports/'recovery.json').read_bytes())
        self.assertEqual(receipt['recovery_plan_sha256'],
            recovery.release.digest(recovery.release.encoded(self.f.spec)))
        self.assertEqual(receipt['candidate_id'], self.f.spec['candidate_id'])
        self.assertEqual(receipt['manifest_sha256'], recovery.release.digest(self.f.manifest_raw))
        self.assertEqual(receipt['original_artifact'], {'id': 102,
            'name': 'candidate-'+self.f.spec['candidate_id'], 'sha256': self.f.spec['artifact_sha256'],
            'run_id': 101, 'run_attempt': 1, 'head_sha': 'a'*40})
        self.assertEqual(receipt['restored_files'], {'.nojekyll': {'bytes': 1,
            'sha256': self.f.spec['marker_sha256'], 'protected_commit': 'a'*40}})
        self.assertEqual(receipt['preserved_present_files'], 2)
        self.assertEqual(receipt['verified_complete_files'], 3)
        self.assertTrue(receipt['requires_new_complete_candidate_artifact_and_validation'])
        for field in ('provider_requests', 'native_counts', 'source_collection_requests', 'assembly_runs', 'ledger_writes'):
            self.assertEqual(receipt[field], 0)
        self.assertEqual([c.args for c in self.f.api.call_args_list], [
            ('actions/runs/101',), ('actions/artifacts/102',), ('actions/artifacts/102/zip',)])
        for call in self.f.forbidden:
            call.assert_not_called()

    def ancestor_arguments_are_exact(self):
        self.f.ancestor.assert_called_once_with(['git', '-C', str(self.f.root),
            'merge-base', '--is-ancestor', 'a'*40, 'HEAD'], capture_output=True, timeout=30)
        self.f.git_blob.assert_called_once_with(['git', '-C', str(self.f.root),
            'show', 'a'*40+':.nojekyll'], timeout=30)

    def test_manifest_whitespace_change_is_rejected_before_marker_lookup(self):
        self.f.entries['candidate.json'] += b'\n'
        self.f.repack()
        self.rejects('exact_manifest_bytes')
        self.f.git_blob.assert_not_called()

    def test_hash_authenticated_but_false_candidate_identity_is_rejected(self):
        self.f.manifest['candidate_id'] = 'f'*64
        raw = recovery.release.encoded(self.f.manifest)
        self.f.spec.update(candidate_id='f'*64, manifest_sha256=recovery.release.digest(raw))
        self.f.entries['candidate.json'] = raw
        self.f.repack()
        self.rejects('exact_candidate_identity')

    def test_changed_source_or_vector_lineage_is_rejected(self):
        self.f.manifest['source_correction']['export_sha256'] = 'f'*64
        self.f.update_manifest()
        self.rejects('same_source_and_vectors')

    def test_another_missing_payload_is_not_reconstructed(self):
        del self.f.entries['files/data/catalog.json']
        self.f.repack()
        self.rejects('only_declared_marker_missing')

    def test_changed_present_payload_rejected_by_real_file_validator(self):
        self.f.entries['files/data/catalog.json'] = b'{"records":["changed"]}\n'
        self.f.repack()
        self.rejects('Candidate bytes differ', ValueError)
        self.f.git_blob.assert_not_called()

    def test_extra_payload_is_rejected(self):
        self.f.entries['files/unmanifested.json'] = b'{}'
        self.f.repack()
        self.rejects('only_declared_marker_missing')

    def test_already_supplied_marker_is_not_overwritten_even_when_exact(self):
        self.f.entries['files/.nojekyll'] = b'\n'
        self.f.repack()
        with self.assertRaisesRegex(ConfigurationFailure, 'only_declared_marker_missing'):
            self.f.recover()
        self.assertEqual((self.f.bundle/'files/.nojekyll').read_bytes(), b'\n')
        self.assertFalse((self.f.reports/'recovery.json').exists())
        self.f.git_blob.assert_not_called()

    def test_marker_must_be_the_exact_declared_hash(self):
        self.f.manifest['files']['.nojekyll'] = recovery.release.digest(b'x')
        self.f.update_manifest()
        self.rejects('manifest_marker_hash')

    def test_wrong_git_bytes_rejected_in_protected_reader(self):
        self.f.git_blob.return_value = b'\r\n'
        self.rejects('protected_marker_bytes')

    def test_injected_reader_cannot_skip_second_marker_hash_check(self):
        with patch.object(recovery, 'protected_marker', return_value=b'x'):
            self.rejects('restored_marker_hash')

    def test_nonancestor_commit_never_reads_or_copies_git_blob(self):
        self.f.ancestor.return_value.returncode = 1
        self.rejects('original_head_not_ancestor')
        self.f.git_blob.assert_not_called()

    def test_existing_destination_is_refused_before_authentication(self):
        self.f.bundle.mkdir()
        sentinel = self.f.bundle/'keep.txt'; sentinel.write_bytes(b'keep')
        self.rejects('new_destination')
        self.assertEqual(sentinel.read_bytes(), b'keep')
        self.f.api.assert_not_called()

    def test_existing_recovery_receipt_is_never_overwritten(self):
        self.f.reports.mkdir()
        receipt = self.f.reports/'recovery.json'; receipt.write_bytes(b'old receipt')
        with self.assertRaisesRegex(ConfigurationFailure, 'new_destination'):
            self.f.recover()
        self.assertEqual(receipt.read_bytes(), b'old receipt')
        self.assertFalse(self.f.bundle.exists())
        self.f.api.assert_not_called()

    def test_only_exact_failed_manual_main_run_is_allowed(self):
        for changes, why in [({'conclusion': 'success'}, 'exact_failed_run'),
                ({'head_sha': 'b'*40}, 'exact_failed_run'),
                ({'event': 'schedule'}, 'trusted_manual_main_run'),
                ({'head_branch': 'other'}, 'trusted_manual_main_run')]:
            with self.subTest(changes=changes):
                original = self.f.run.copy()
                self.f.run.update(changes)
                self.rejects(why)
                self.f.run = original
        self.f.git_blob.assert_not_called()

    def test_wrong_artifact_owner_or_digest_is_rejected_before_unpack(self):
        self.f.artifact['workflow_run']['id'] = 103
        self.rejects('artifact_metadata')
        self.assertFalse(self.f.bundle.exists())
        self.f.artifact['workflow_run']['id'] = 101
        self.f.archive += b'changed archive bytes'
        self.rejects('raw_artifact_digest')
        self.assertFalse(self.f.bundle.exists())


class ProtectedRecoveryPlan(unittest.TestCase):
    def test_config_pins_only_the_actual_failed_artifact_and_original_lf_marker(self):
        spec = recovery.plan()
        self.assertEqual(set(spec), recovery.FIELDS)
        self.assertEqual((spec['failed_run_id'], spec['failed_run_attempt'], spec['artifact_id']),
            (35932387025, 1, 10781671923))
        self.assertEqual(spec['failed_run_head'], '25b4cc54a287cbe29fbebe09f1c8ab23a992c00b')
        self.assertEqual(spec['artifact_sha256'], 'dae2a953268ae70bf1148fba559e64e5aace3770db93ed87f015cf5885f370d7')
        self.assertEqual(spec['candidate_id'], 'cd9872aada0a4ce3e89933bb4db95876a2debb2b0a20c5dec7774e57640fb61f')
        self.assertEqual(spec['manifest_sha256'], '777c8675a3164e67aca1c19d6bfbdc80081af2c0a490ece23dfc2a48b76d761d')
        self.assertEqual((spec['marker_path'], spec['marker_bytes'], spec['marker_sha256']),
            ('.nojekyll', 1, recovery.release.digest(b'\n')))
        self.assertEqual(spec['source_plan_sha256'], recovery.release.digest(recovery.source.CONFIG.read_bytes()))
        self.assertEqual(spec['spending_plan_sha256'], recovery.policy.PLAN_SHA)
        self.assertNotIn(b'\r', recovery.CONFIG.read_bytes())

    def test_plan_rejects_extra_scope_boolean_count_and_nonfixed_marker(self):
        actual = recovery.plan()
        with tempfile.TemporaryDirectory(prefix='marker-plan-') as directory:
            path = Path(directory)/'plan.json'
            for changes, why in [({'another_marker': '.hidden'}, 'strict_plan'),
                    ({'marker_bytes': True}, 'fixed_marker_scope'),
                    ({'marker_path': 'data/catalog.json'}, 'fixed_marker_scope'),
                    ({'failed_run_attempt': 2}, 'fixed_marker_scope'),
                    ({'spending_plan_sha256': '0'*64}, 'unchanged_fixed_plans')]:
                with self.subTest(changes=changes):
                    path.write_bytes(recovery.release.encoded({**actual, **changes}))
                    with patch.object(recovery, 'CONFIG', path):
                        with self.assertRaisesRegex(ConfigurationFailure, why):
                            recovery.plan()


if __name__ == '__main__':
    unittest.main()
