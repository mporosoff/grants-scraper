"""Independent ZIP transport contracts, entirely offline and credential-free."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import release_checkpoint_archive as archive


REPOSITORY = 'owner/project'
RUN, ATTEMPT, BACKUP = '101', 2, '901'
SHA, CANDIDATE = 'a' * 40, 'c' * 64


def packed(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as handle:
        for name, value in files.items():
            info = zipfile.ZipInfo(name)
            # Preserve deliberately unsafe names even on Windows, where the
            # ZipInfo constructor normally normalizes backslashes.
            info.filename = info.orig_filename = name
            info.compress_type = zipfile.ZIP_DEFLATED
            handle.writestr(info, value)
    return stream.getvalue()


def run_metadata(identifier=RUN, *, backup=False):
    return {'id': int(identifier), 'run_attempt': ATTEMPT, 'workflow_id': 42,
            'head_branch': 'main', 'head_sha': SHA, 'status': 'completed',
            'conclusion': 'success' if backup else 'failure',
            'path': archive.BACKUP_WORKFLOW if backup else archive.SOURCE_WORKFLOW,
            'event': 'workflow_run' if backup else 'schedule',
            'repository': {'id': 10, 'full_name': REPOSITORY},
            'head_repository': {'id': 10, 'full_name': REPOSITORY}}


def artifact(identifier, name, raw, run=RUN):
    return {'id': identifier, 'name': name, 'expired': False, 'size_in_bytes': len(raw),
            'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
            'workflow_run': {'id': int(run), 'head_branch': 'main', 'head_sha': SHA,
                             'repository_id': 10, 'head_repository_id': 10}}


class CheckpointArchiveContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = {11: packed({'ledger.json': b'{"charges":44}'}),
                    12: packed({'validation.json': b'{"status":"failed"}'})}
        self.rows = [artifact(11, f'generation-spend-state-{RUN}-{ATTEMPT}', self.raw[11]),
                     artifact(12, f'validation-{CANDIDATE}-{ATTEMPT}', self.raw[12])]
        self.values = {f'actions/runs/{RUN}': run_metadata(),
                       f'actions/runs/{RUN}/attempts/{ATTEMPT}': run_metadata(),
                       f'actions/runs/{RUN}/artifacts?per_page=100&page=1': {'artifacts': self.rows, 'total_count': 2},
                       **{f'actions/artifacts/{identifier}/zip': raw for identifier, raw in self.raw.items()}}
        self.calls = []

    def read(self, path):
        self.calls.append(path)
        value = self.values[path]
        if callable(value):
            value = value()
        return value if isinstance(value, bytes) else json.dumps(value).encode()

    def capture(self):
        return archive.capture(REPOSITORY, RUN, ATTEMPT, self.root / 'snapshot', api=self.read)

    def backup(self, mutate=None, *, name=None):
        manifest = self.capture()
        files = {path.relative_to(self.root / 'snapshot').as_posix(): path.read_bytes()
                 for path in (self.root / 'snapshot').rglob('*') if path.is_file()}
        if mutate:
            mutate(manifest, files)
            files['manifest.json'] = json.dumps(manifest).encode()
        raw = packed(files)
        outer = artifact(1001, name or manifest['artifact_name'], raw, BACKUP)
        self.values.update({f'actions/runs/{BACKUP}': run_metadata(BACKUP, backup=True),
                            'actions/artifacts/1001': outer, 'actions/artifacts/1001/zip': raw,
                            'actions/artifacts?per_page=100&page=1': {'artifacts': [outer], 'total_count': 1}})
        return outer

    def test_capture_retains_every_exact_zip_and_outputs_candidate_selector(self):
        output = self.root / 'github-output'
        with patch.dict('os.environ', {'GITHUB_OUTPUT': str(output)}):
            manifest = self.capture()
        expected = f'originalrun-{RUN}-attempt-{ATTEMPT}-candidate-{CANDIDATE}'
        self.assertEqual(manifest['artifact_name'], expected)
        self.assertEqual(output.read_text(), 'artifact_name=' + expected + '\n')
        self.assertEqual(manifest['source']['run_attempt'], ATTEMPT)
        for row in manifest['artifacts']:
            self.assertEqual((self.root / 'snapshot' / row['path']).read_bytes(), self.raw[row['metadata']['id']])
        self.assertEqual(set(path.relative_to(self.root / 'snapshot').as_posix()
                             for path in (self.root / 'snapshot').rglob('*') if path.is_file()),
                         {'manifest.json', 'artifacts/11.zip', 'artifacts/12.zip'})

    def test_pre_candidate_archive_has_no_candidate_suffix(self):
        self.rows.pop()
        self.values[f'actions/runs/{RUN}/artifacts?per_page=100&page=1']['total_count'] = 1
        self.assertEqual(self.capture()['artifact_name'], f'originalrun-{RUN}-attempt-{ATTEMPT}')

    def test_roundtrip_restores_original_metadata_and_exact_raw_zip(self):
        outer = self.backup()
        # Source artifacts have disappeared; only independent transport remains.
        for identifier in self.raw:
            del self.values[f'actions/artifacts/{identifier}/zip']
        self.calls.clear()
        records = archive.preserved_artifacts(REPOSITORY, RUN, api=self.read)
        self.assertEqual(len(records), 2)
        for record, original in zip(records, self.rows):
            self.assertEqual({key: value for key, value in record.items() if key != '_checkpoint_archive'}, original)
            self.assertEqual(record['_checkpoint_archive']['backup_digest'], outer['digest'])
            self.assertEqual(archive.read_preserved_artifact(REPOSITORY, RUN, record, api=self.read), self.raw[record['id']])
        self.assertNotIn('actions/artifacts/11/zip', self.calls)

    def test_no_matching_archives_requires_no_backup_api_calls(self):
        self.assertEqual(archive.preserved_artifacts(REPOSITORY, RUN, inventory=self.rows, api=self.read), [])
        self.assertEqual(self.calls, [])

    def test_candidate_selector_filters_unrelated_large_archives_before_download(self):
        outer = self.backup()
        self.calls.clear()
        self.assertEqual(archive.preserved_artifacts(REPOSITORY, None, candidate='d' * 64,
                         inventory=[outer], api=self.read), [])
        self.assertEqual(self.calls, [])
        records = archive.preserved_artifacts(REPOSITORY, None, candidate=CANDIDATE,
                    inventory=[outer], api=self.read)
        self.assertEqual([row['id'] for row in records], [11, 12])

    def test_expired_backup_is_unavailable_without_using_its_zip(self):
        outer = self.backup()
        outer['expired'] = True
        self.calls.clear()
        self.assertEqual(archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer], api=self.read), [])
        self.assertEqual(self.calls, [])

    def test_capture_rejects_changed_attempt_and_inventory(self):
        for kind in ('attempt', 'inventory'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.root) as directory:
                calls = 0
                def changing(path):
                    nonlocal calls
                    if kind == 'attempt' and path == f'actions/runs/{RUN}':
                        calls += 1
                        if calls == 2:
                            value = run_metadata(); value['run_attempt'] += 1
                            return json.dumps(value).encode()
                    if kind == 'inventory' and path == f'actions/runs/{RUN}/artifacts?per_page=100&page=1':
                        calls += 1
                        if calls == 2:
                            return b'{"artifacts":[],"total_count":0}'
                    return self.read(path)
                with self.assertRaises(ValueError):
                    archive.capture(REPOSITORY, RUN, ATTEMPT, Path(directory) / 'capture', api=changing)
                self.assertFalse((Path(directory) / 'capture/manifest.json').exists())

    def test_capture_rejects_more_than_one_candidate_identity(self):
        self.rows.append(artifact(13, 'candidate-' + 'd' * 64, self.raw[11]))
        self.values[f'actions/runs/{RUN}/artifacts?per_page=100&page=1']['total_count'] = 3
        with self.assertRaisesRegex(ValueError, 'Multiple candidate'):
            self.capture()

    def test_capture_rejects_tampered_or_unsafe_original_zip(self):
        for raw in (b'not a ZIP', packed({'../escape': b'bad'}), packed({'bad\\name': b'bad'})):
            with self.subTest(raw=raw[:10]), tempfile.TemporaryDirectory(dir=self.root) as directory:
                self.values['actions/artifacts/11/zip'] = raw
                self.rows[0]['digest'] = 'sha256:' + hashlib.sha256(raw).hexdigest()
                with self.assertRaises(ValueError):
                    archive.capture(REPOSITORY, RUN, ATTEMPT, Path(directory) / 'capture', api=self.read)

    def test_capture_rejects_zip_digest_mismatch(self):
        self.values['actions/artifacts/11/zip'] = packed({'ledger.json': b'forged'})
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.capture()

    def test_capture_inspects_original_zip_directory_without_reading_payloads(self):
        with patch.object(zipfile.ZipFile, 'read', side_effect=AssertionError('Original payload extracted')):
            self.assertEqual(len(self.capture()['artifacts']), 2)

    def test_source_and_artifact_must_belong_to_the_same_protected_run(self):
        for kind in ('source', 'artifact'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.root) as directory:
                values = deepcopy(self.values)
                if kind == 'source':
                    values[f'actions/runs/{RUN}/attempts/{ATTEMPT}']['head_repository']['full_name'] = 'attacker/project'
                else:
                    values[f'actions/runs/{RUN}/artifacts?per_page=100&page=1']['artifacts'][0]['workflow_run']['id'] = 999
                def read(path):
                    value = values[path]
                    return value if isinstance(value, bytes) else json.dumps(value).encode()
                with self.assertRaises(ValueError):
                    archive.capture(REPOSITORY, RUN, ATTEMPT, Path(directory) / 'capture', api=read)

    def test_repository_discovery_reads_all_pages_before_selecting_backups(self):
        outer = self.backup()
        filler = [dict(self.rows[0], id=2000 + index, name=f'unrelated-{index}') for index in range(100)]
        self.values['actions/artifacts?per_page=100&page=1'] = {'artifacts': filler, 'total_count': 101}
        self.values['actions/artifacts?per_page=100&page=2'] = {'artifacts': [outer], 'total_count': 101}
        records = archive.preserved_artifacts(REPOSITORY, RUN, api=self.read)
        self.assertEqual([row['id'] for row in records], [11, 12])
        self.assertIn('actions/artifacts?per_page=100&page=2', self.calls)

    def test_repeated_independent_archives_coalesce_the_same_original_ids(self):
        outer = self.backup()
        newer = dict(outer, id=1002)
        self.values['actions/artifacts/1002/zip'] = self.values['actions/artifacts/1001/zip']
        records = archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer, newer], api=self.read)
        self.assertEqual([row['id'] for row in records], [11, 12])
        self.assertTrue(all(row['_checkpoint_archive']['backup_artifact_id'] == 1002 for row in records))

    def test_outer_github_digest_cannot_be_replaced_by_only_an_inner_manifest_hash(self):
        outer = self.backup()
        self.values['actions/artifacts/1001/zip'] = packed({'manifest.json': b'{}'})
        with self.assertRaisesRegex(ValueError, 'GitHub digest'):
            archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer], api=self.read)

    def test_manifest_rejects_ambiguous_json_and_unexpected_fields(self):
        outer = self.backup()
        original_files = {path.relative_to(self.root / 'snapshot').as_posix(): path.read_bytes()
                          for path in (self.root / 'snapshot').rglob('*') if path.is_file()}
        original_manifest = json.loads(original_files['manifest.json'])
        malformed = [b'{"schema_version":1,"schema_version":1}',
                     b'{"extra":NaN}', b'{"extra":Infinity}', b'{"extra":-Infinity}',
                     b'{"extra":1e999}', b'[]']
        for kind in ('boolean_schema', 'extra_top', 'extra_item', 'missing_item', 'conclusion'):
            manifest = deepcopy(original_manifest)
            if kind == 'boolean_schema': manifest['schema_version'] = True
            elif kind == 'extra_top': manifest['unexpected'] = 'field'
            elif kind == 'extra_item': manifest['artifacts'][0]['unexpected'] = 'field'
            elif kind == 'missing_item': del manifest['artifacts'][0]['zip_bytes']
            else: manifest['source_conclusion'] = 'success'
            malformed.append(json.dumps(manifest).encode())
        for payload in malformed:
            with self.subTest(payload=payload[:70]):
                files = dict(original_files, **{'manifest.json': payload})
                raw = packed(files)
                selected = dict(outer, digest='sha256:' + hashlib.sha256(raw).hexdigest(), size_in_bytes=len(raw))
                self.values['actions/artifacts/1001/zip'] = raw
                with self.assertRaises(ValueError):
                    archive.preserved_artifacts(REPOSITORY, RUN, inventory=[selected], api=self.read)

    def test_source_capture_requires_an_allowed_terminal_conclusion(self):
        for conclusion in (None, 'in_progress', 'unknown', True):
            with self.subTest(conclusion=conclusion), tempfile.TemporaryDirectory(dir=self.root) as directory:
                self.values[f'actions/runs/{RUN}/attempts/{ATTEMPT}']['conclusion'] = conclusion
                with self.assertRaises(ValueError):
                    archive.capture(REPOSITORY, RUN, ATTEMPT, Path(directory) / 'capture', api=self.read)

    def test_cancelled_first_attempt_without_any_jobs_or_artifacts_is_a_noop(self):
        meta = run_metadata(); meta.update(run_attempt=1, conclusion='cancelled')
        self.values.update({f'actions/runs/{RUN}': meta, f'actions/runs/{RUN}/attempts/1': meta,
                            f'actions/runs/{RUN}/artifacts?per_page=100&page=1': {'artifacts': [], 'total_count': 0},
                            f'actions/runs/{RUN}/attempts/1/jobs?per_page=100&page=1': {'jobs': [], 'total_count': 0}})
        output = self.root / 'github-output'
        with patch.dict('os.environ', {'GITHUB_OUTPUT': str(output)}):
            result = archive.capture(REPOSITORY, RUN, 1, self.root / 'capture', api=self.read)
        self.assertEqual(result['artifact_name'], '')
        self.assertEqual(result['artifacts'], [])
        self.assertFalse((self.root / 'capture').exists())
        self.assertEqual(output.read_text(), 'artifact_name=\n')

    def test_empty_artifacts_cannot_hide_jobs_incomplete_jobs_or_a_later_attempt(self):
        for kind in ('job', 'incomplete_jobs', 'missing_count', 'later_attempt', 'not_cancelled'):
            with self.subTest(kind=kind):
                attempt = 2 if kind == 'later_attempt' else 1
                meta = run_metadata(); meta.update(run_attempt=attempt,
                    conclusion='failure' if kind == 'not_cancelled' else 'cancelled')
                jobs = {'jobs': [{'id': 1}] if kind == 'job' else [],
                        'total_count': 1 if kind == 'incomplete_jobs' else (1 if kind == 'job' else 0)}
                if kind == 'missing_count': jobs.pop('total_count')
                self.values.update({f'actions/runs/{RUN}': meta, f'actions/runs/{RUN}/attempts/{attempt}': meta,
                    f'actions/runs/{RUN}/artifacts?per_page=100&page=1': {'artifacts': [], 'total_count': 0},
                    f'actions/runs/{RUN}/attempts/{attempt}/jobs?per_page=100&page=1': jobs})
                with self.assertRaises(ValueError):
                    archive.capture(REPOSITORY, RUN, attempt, self.root / 'capture', api=self.read)

    def test_raw_retrieval_refreshes_backup_and_original_attempt_metadata(self):
        self.backup()
        record = archive.preserved_artifacts(REPOSITORY, RUN, api=self.read)[0]
        self.calls.clear()
        self.assertEqual(archive.read_preserved_artifact(REPOSITORY, RUN, record, api=self.read), self.raw[11])
        self.assertIn('actions/artifacts/1001', self.calls)
        self.assertIn(f'actions/runs/{BACKUP}', self.calls)
        self.assertIn(f'actions/runs/{RUN}/attempts/{ATTEMPT}', self.calls)
        self.values[f'actions/runs/{BACKUP}']['conclusion'] = 'failure'
        with self.assertRaises(ValueError):
            archive.read_preserved_artifact(REPOSITORY, RUN, record, api=self.read)

    def test_backup_origin_must_be_successful_same_repository_workflow_run_on_main(self):
        outer = self.backup()
        for field, value in (('event', 'pull_request'), ('head_branch', 'feature'),
                             ('conclusion', 'failure'), ('path', archive.SOURCE_WORKFLOW),
                             ('head_repository', {'id': 20, 'full_name': 'attacker/project'})):
            with self.subTest(field=field):
                meta = run_metadata(BACKUP, backup=True); meta[field] = value
                self.values[f'actions/runs/{BACKUP}'] = meta
                with self.assertRaises(ValueError):
                    archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer], api=self.read)

    def test_backup_rejects_manifest_source_and_candidate_selector_forgery(self):
        for kind in ('source', 'candidate'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.root) as directory:
                previous = self.root; self.root = Path(directory)
                def mutate(manifest, _):
                    if kind == 'source': manifest['source']['head_sha'] = 'b' * 40
                    else: manifest['artifacts'][1]['metadata']['name'] = 'validation-' + 'd' * 64 + '-2'
                outer = self.backup(mutate)
                with self.assertRaises(ValueError):
                    archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer], api=self.read)
                self.root = previous

    def test_backup_rejects_missing_extra_or_modified_inner_zip(self):
        for kind in ('missing', 'extra', 'modified'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=self.root) as directory:
                previous = self.root; self.root = Path(directory)
                def mutate(_, files):
                    if kind == 'missing': del files['artifacts/11.zip']
                    elif kind == 'extra': files['unexpected.txt'] = b'extra'
                    else: files['artifacts/11.zip'] = packed({'ledger.json': b'changed'})
                outer = self.backup(mutate)
                with self.assertRaises(ValueError):
                    archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer], api=self.read)
                self.root = previous

    def test_read_rejects_mutated_original_record_or_backup_locator(self):
        self.backup()
        record = archive.preserved_artifacts(REPOSITORY, RUN, api=self.read)[0]
        for field, value in (('name', 'different-name'), ('digest', 'sha256:' + '0' * 64)):
            altered = deepcopy(record); altered[field] = value
            with self.assertRaisesRegex(ValueError, 'provenance changed'):
                archive.read_preserved_artifact(REPOSITORY, RUN, altered, api=self.read)

    def test_size_limits_are_enforced_before_extracting_inner_payloads(self):
        outer = self.backup()
        with patch.object(archive, 'MAX_ZIP_BYTES', 1):
            with self.assertRaises(ValueError):
                archive.preserved_artifacts(REPOSITORY, RUN, inventory=[outer], api=self.read)

    def test_zip_duplicate_and_symlink_members_are_rejected(self):
        for symlink in (False, True):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as handle:
                info = zipfile.ZipInfo('file')
                if symlink: info.external_attr = (stat.S_IFLNK | 0o777) << 16
                handle.writestr(info, b'data')
                if not symlink: handle.writestr('FILE', b'data')
            with self.assertRaises(ValueError):
                archive._members(stream.getvalue())


if __name__ == '__main__':
    unittest.main()
