"""Hermetic fixed-parent projection recovery; no private fixtures or network."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

from tools import catalog_projection_recovery as recovery
from tools.offline_spend import ConfigurationFailure


def encode(value):
    return recovery.release.encoded(value)


def sha(raw):
    return recovery.release.digest(raw)


def archive(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as writer, warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        for name, raw in entries:
            writer.writestr(name, raw)
    return buffer.getvalue()


class ProjectionFixture:
    """Real auth/unpack/manifest pipeline, with an exact synthetic payload delta."""
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='projection-unit-')))
        self.bundle, self.reports = self.root/'derived', self.root/'reports'
        self.payloads = {name: ('before '+name+'\n').encode() for name in sorted(recovery.CHANGED)}
        self.payloads.update({f'data/retained-{i:03}.json': encode({'ordinal': i}) for i in range(121)})
        self.after = self.payloads | {name: ('after '+name+'\n').encode() for name in recovery.CHANGED}
        self.parent = {'schema_version': 1, 'candidate_format': recovery.release.VERSION,
            'files': {n: sha(b) for n, b in self.payloads.items()},
            'generation_files': {n: sha(b) for n, b in self.payloads.items() if n.startswith('data/') and n != recovery.PACKAGE},
            'generation_sha': 'a'*40, 'generation_run_id': '99', 'generation_run_attempt': '1',
            'generation_timestamp': '2026-09-23T00:00:00Z', 'assembly_sha': 'b'*40,
            'derived_from_candidate': 'c'*64,
            'source_correction': {'version': 'retained-source', 'export_sha256': 'd'*64},
            'original_generation': {'generation_sha': 'a'*40, 'retained': True},
            'semantic_identity': {'corpus_sha256': 'e'*64}, 'team_identity': {'generation_id': 'f'*64}}
        self.parent['candidate_id'] = sha(encode(self.parent))
        self.parent_raw = encode(self.parent)
        self.receipt_raw = encode({'fixed_parent_marker_receipt': 'synthetic', 'provider_requests': 0})
        self.spec = {'version': recovery.VERSION, 'parent': {'run_id': 201, 'run_attempt': 1,
            'head_sha': 'b'*40, 'artifact_id': 202, 'receipt_artifact_id': 203,
            'candidate_id': self.parent['candidate_id'], 'manifest_sha256': sha(self.parent_raw),
            'canonical_manifest_sha256': sha(self.parent_raw), 'derived_from_candidate': 'c'*64,
            'receipt_sha256': sha(self.receipt_raw)}, 'prior_cache': {'commit': 'a'*40, 'sha256': '1'*64},
            'projection_clock': '2026-09-23T00:00:00Z', 'team_generation_id': 'f'*64,
            'restored_entries': {f'notice-{i}': {'entry_sha256': str(i+1)*64, 'document_sha256': str(i+1)*64} for i in range(4)},
            'changed_files': {n: {'before': sha(self.payloads[n]), 'after': sha(self.after[n])} for n in recovery.CHANGED},
            'expected_files': {n: sha(b) for n, b in self.after.items()}}
        self.parent_entries = [('candidate.json', self.parent_raw)] + [('files/'+n, b) for n, b in self.payloads.items()]
        self.receipt_entries = [('recovery.json', self.receipt_raw)]
        self.refresh_archives()
        self.run = {'id': 201, 'run_attempt': 1, 'head_branch': 'main', 'head_sha': 'b'*40,
            'path': recovery.smoke.REFRESH, 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'failure'}
        self.metadata = {202: {'id': 202, 'name': 'candidate-'+self.parent['candidate_id'],
            'created_at': '2026-09-23T01:00:02Z'}, 203: {'id': 203,
            'name': 'catalog-candidate-recovery-201-1', 'created_at': '2026-09-23T01:00:01Z'}}
        for identifier, meta in self.metadata.items():
            meta.update(expired=False, workflow_run={'id': 201, 'head_sha': 'b'*40},
                digest='sha256:'+sha(self.archives[identifier]))
        self.api = Mock(side_effect=self.read_api)
        self.stack.enter_context(patch.object(recovery, 'plan', return_value=self.spec))
        self.transform = self.stack.enter_context(patch.object(recovery, '_payloads', side_effect=self.transform_payloads))
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('No network')))
        self.forbidden = [self.stack.enter_context(patch.object(recovery.release, name,
            side_effect=AssertionError('No assembly or regeneration'))) for name in ('create', 'create_source_correction', 'materialize')]

    def refresh_archives(self):
        self.archives = {202: archive(self.parent_entries), 203: archive(self.receipt_entries)}
        self.spec['parent']['artifact_sha256'] = sha(self.archives[202])
        self.spec['parent']['receipt_artifact_sha256'] = sha(self.archives[203])
        if hasattr(self, 'metadata'):
            for identifier, meta in self.metadata.items():
                meta['digest'] = 'sha256:'+sha(self.archives[identifier])
        self.derived = deepcopy(self.parent)
        self.derived['files'] = deepcopy(self.spec['expected_files'])
        for name in recovery.DATA:
            self.derived['generation_files'][name] = self.spec['expected_files'][name]
        self.derived['derived_from_candidate'] = self.parent['candidate_id']
        self.derived['projection_recovery'] = recovery.derivation(self.spec)
        self.derived.pop('candidate_id')
        self.derived['candidate_id'] = sha(encode(self.derived))
        self.spec['candidate_id'] = self.derived['candidate_id']
        self.spec['manifest_sha256'] = sha(encode(self.derived))

    def transform_payloads(self, bundle, spec, *, root):
        for name in recovery.CHANGED:
            (Path(bundle)/'files'/name).write_bytes(self.after[name])
        return {'publication_ready': True, 'changed_records': 0, 'provider_requests': 0, 'source_requests': 0}

    def read_api(self, path):
        if path == 'actions/runs/201':
            return encode(self.run)
        for identifier in (202, 203):
            if path == f'actions/artifacts/{identifier}':
                return encode(self.metadata[identifier])
            if path == f'actions/artifacts/{identifier}/zip':
                return self.archives[identifier]
        raise AssertionError('Unexpected API route '+path)

    def repair(self):
        return recovery.repair(self.bundle, self.reports, root=self.root, api=self.api)

    def write_derived(self, path=None):
        path = Path(path or self.bundle)
        for name, raw in self.after.items():
            target = path/'files'/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        (path/'candidate.json').write_bytes(encode(self.derived))
        return path

    def close(self):
        self.stack.close()


class ProjectionRecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.f = ProjectionFixture(); self.addCleanup(self.f.close)

    def rejects(self, reason, exception=ConfigurationFailure):
        with self.assertRaisesRegex(exception, reason):
            self.f.repair()
        self.assertFalse(self.f.bundle.exists())
        self.assertFalse((self.f.reports/'recovery.json').exists())

    def test_exact_126_file_parent_derives_five_changes_and_retains_every_identity(self):
        parent_raw = self.f.parent_raw; archives = deepcopy(self.f.archives)
        result = self.f.repair()
        self.assertEqual(result, self.f.derived)
        verified = recovery.verify_candidate(self.f.bundle)
        self.assertEqual(verified['parent_manifest'], self.f.parent)
        self.assertEqual(encode(verified['parent_manifest']), parent_raw)
        actual = {p.relative_to(self.f.bundle/'files').as_posix(): p.read_bytes()
            for p in (self.f.bundle/'files').rglob('*') if p.is_file()}
        self.assertEqual(actual, self.f.after)
        self.assertEqual({n for n in actual if actual[n] != self.f.payloads[n]}, recovery.CHANGED)
        self.assertEqual(sum(actual[n] == b for n, b in self.f.payloads.items()), 121)
        for key in ('generation_sha', 'generation_run_id', 'generation_run_attempt', 'generation_timestamp',
                'assembly_sha', 'original_generation', 'source_correction', 'team_identity', 'semantic_identity'):
            self.assertEqual(result[key], self.f.parent[key])
        receipt = json.loads((self.f.reports/'recovery.json').read_bytes())
        self.assertEqual(receipt['derivation'], recovery.derivation(self.f.spec))
        self.assertEqual(receipt['derivation']['retained_payload_files'], 121)
        for key in ('provider_requests', 'source_requests', 'native_counts', 'ledger_writes'):
            self.assertEqual(receipt['derivation'][key], 0)
        self.assertEqual(self.f.archives, archives)
        self.assertEqual(self.f.api.call_count, 5)
        for forbidden in self.f.forbidden: forbidden.assert_not_called()

    def test_archive_entry_order_does_not_change_candidate_identity(self):
        self.f.parent_entries.reverse(); self.f.refresh_archives()
        self.assertEqual(self.f.repair()['candidate_id'], self.f.spec['candidate_id'])

    def test_altered_parent_manifest_fails_before_projection(self):
        self.f.parent_entries[0] = ('candidate.json', self.f.parent_raw+b'\n')
        self.f.refresh_archives(); self.rejects('exact_parent_manifest'); self.f.transform.assert_not_called()

    def test_missing_extra_and_changed_parent_payloads_are_rejected(self):
        for kind in ('missing', 'extra', 'changed'):
            with self.subTest(kind=kind):
                original = list(self.f.parent_entries)
                if kind == 'missing': self.f.parent_entries.pop()
                elif kind == 'extra': self.f.parent_entries.append(('files/unexpected.json', b'{}'))
                else: self.f.parent_entries[-1] = (self.f.parent_entries[-1][0], b'changed')
                self.f.refresh_archives()
                self.rejects('Candidate bytes differ|Unmanifested candidate files', ValueError)
                self.f.parent_entries = original
        self.f.transform.assert_not_called()

    def test_symlink_duplicate_and_traversal_zip_members_are_rejected(self):
        for kind in ('symlink', 'duplicate', 'traversal'):
            with self.subTest(kind=kind):
                original = list(self.f.parent_entries)
                name = self.f.parent_entries[-1][0]
                if kind == 'duplicate': self.f.parent_entries.append((name, b'duplicate'))
                elif kind == 'traversal': self.f.parent_entries.append(('../escape.json', b'{}'))
                else:
                    link = zipfile.ZipInfo('files/link'); link.create_system = 3
                    link.external_attr = (stat.S_IFLNK | 0o777) << 16
                    self.f.parent_entries.append((link, b'../outside'))
                self.f.refresh_archives(); self.rejects('unsafe_public_archive')
                self.f.parent_entries = original
        self.f.transform.assert_not_called()

    def test_wrong_failed_run_or_receipt_producer_is_rejected(self):
        self.f.run['head_sha'] = 'c'*40
        self.rejects('exact_failed_parent_run')
        self.f.run['head_sha'] = 'b'*40; self.f.run['conclusion'] = 'success'
        self.rejects('exact_failed_parent_run')
        self.f.run['conclusion'] = 'failure'; self.f.metadata[203]['workflow_run']['id'] = 999
        self.rejects('artifact_metadata'); self.f.transform.assert_not_called()

    def test_candidate_cannot_precede_paired_receipt(self):
        self.f.metadata[203]['created_at'] = '2026-09-23T01:00:03Z'
        self.rejects('paired_receipt_precedes_candidate')

    def test_receipt_bytes_and_inventory_are_exact(self):
        self.f.receipt_entries = [('recovery.json', self.f.receipt_raw+b' ')]
        self.f.refresh_archives(); self.rejects('exact_paired_receipt')
        self.f.receipt_entries.append(('other.json', b'{}'))
        self.f.refresh_archives(); self.rejects('only_paired_receipt')

    def test_actual_archive_digest_is_checked(self):
        self.f.archives[202] += b'changed raw archive'
        self.rejects('raw_artifact_digest')

    def test_unpinned_sixth_payload_or_wrong_package_hash_cannot_get_receipt(self):
        original = self.f.transform.side_effect
        for name in ('data/retained-000.json', recovery.PACKAGE):
            with self.subTest(name=name):
                def corrupt(bundle, spec, *, root):
                    report = original(bundle, spec, root=root)
                    (Path(bundle)/'files'/name).write_bytes(b'changed')
                    return report
                self.f.transform.side_effect = corrupt
                self.rejects('Candidate bytes differ', ValueError)

    def test_full_parent_identity_blocks_unrelated_manifest_changes_even_if_resealed(self):
        for key, value in (('generation_sha', '9'*40), ('source_correction', {}),
                ('team_identity', {}), ('semantic_identity', {}), ('extra', True)):
            with self.subTest(key=key):
                changed = deepcopy(self.f.derived); changed[key] = value
                with self.assertRaisesRegex(ConfigurationFailure, 'full_parent_identity'):
                    recovery.parent_manifest(changed, self.f.spec)

    def test_derived_verification_rejects_raw_change_missing_extra_and_unpinned_bytes(self):
        self.f.write_derived()
        manifest = self.f.bundle/'candidate.json'; manifest.write_bytes(encode(self.f.derived)+b'\n')
        with self.assertRaisesRegex(ConfigurationFailure, 'derived_manifest_bytes'):
            recovery.verify_candidate(self.f.bundle)
        manifest.write_bytes(encode(self.f.derived))
        extra = self.f.bundle/'unexpected.json'; extra.write_bytes(b'{}')
        with self.assertRaisesRegex(ConfigurationFailure, 'complete_safe_inventory'):
            recovery.verify_candidate(self.f.bundle)
        extra.unlink(); (self.f.bundle/'files/data/retained-000.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Candidate bytes differ'):
            recovery.verify_candidate(self.f.bundle)

    def test_replay_or_existing_receipt_is_never_overwritten(self):
        self.f.repair(); before = (self.f.reports/'recovery.json').read_bytes()
        calls = self.f.api.call_count
        with self.assertRaisesRegex(ConfigurationFailure, 'new_destination'): self.f.repair()
        self.assertEqual((self.f.reports/'recovery.json').read_bytes(), before)
        self.assertEqual(self.f.api.call_count, calls)
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'new'
            with self.assertRaisesRegex(ConfigurationFailure, 'new_destination'):
                recovery.repair(destination, self.f.reports, api=self.f.api)
            self.assertFalse(destination.exists())

    def test_rename_failure_cannot_leave_a_success_receipt(self):
        with patch.object(Path, 'rename', side_effect=OSError('rename unavailable')):
            self.rejects('rename unavailable', OSError)

    def test_projection_failure_preserves_source_and_no_result_receipt(self):
        self.f.transform.side_effect = ConfigurationFailure('strict_notice_gate')
        original = deepcopy(self.f.archives); self.rejects('strict_notice_gate')
        self.assertEqual(self.f.archives, original)


class EvidenceFixture:
    """Four missing companions plus an unrelated fifth record, using real writers."""
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='projection-evidence-')))
        self.bundle = self.root/'parent'; self.files = self.bundle/'files'; self.files.mkdir(parents=True)
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('No source/provider network')))
        now = datetime(2026, 9, 23, tzinfo=timezone.utc)
        rows = []; entries = {}
        for index in range(5):
            row = {'opportunity_id': f'fixture-{index}', 'title': f'Notice {index}', 'status': 'posted',
                'primary_document_url': f'https://example.gov/notice-{index}.html', 'close_date': '2027-05-01'}
            source = recovery.evidence.source_for_record(row)
            entry, _ = recovery.evidence.build_document_entry(row, source, {'url': source['url'],
                'content_type': 'text/html', 'content': f'<p>Notice {index}. Cost sharing is not required.</p>'.encode()}, None, now)
            rows.append(row); entries[row['opportunity_id']] = entry
        with tempfile.TemporaryDirectory() as temp:
            catalog, self.prior = recovery.evidence.enrich_document_evidence(
                {'schema_version': 1, 'generated_at': recovery.evidence.iso_utc(now), 'record_count': 5, 'opportunities': rows},
                {'schema_version': 1, 'records': entries}, now=now, max_documents=0,
                structure_cache=recovery.StructureCache(temp))
        self.prior = json.loads(json.dumps(self.prior))
        self.correct = json.loads(json.dumps(recovery.compact_catalog_payload(catalog)))
        self.before = deepcopy(self.correct)
        for row in self.before['opportunities'][:4]: row['next_submission'] = {'date': '2099-01-01'}
        self.cache = deepcopy(self.prior)
        for identifier in list(entries)[:4]: del self.cache['records'][identifier]
        self.cache['retained_failure_note'] = {'code': 'prior-failure-kept'}
        self.spec = {'projection_clock': self.before['document_evidence_generated_at'], 'team_generation_id': 'f'*64,
            'parent': {'candidate_id': 'a'*64}, 'restored_entries': {identifier: {
                'entry_sha256': sha(encode(self.prior['records'][identifier])),
                'document_sha256': self.prior['records'][identifier]['document']['sha256']} for identifier in list(entries)[:4]}}
        self.write('data/document_evidence.json', encode(self.cache))
        self.write('data/opportunities.js', recovery.catalog_javascript_bytes(self.before))
        self.write('data/catalog-metadata.js', recovery.catalog_metadata_javascript_bytes(self.before))
        self.write('data/subtopics.js', encode({'schema_version': 1, 'records': {}}))
        from scripts.import_opportunity_team_model import CONTENT_HASHED_ASSETS, VERSIONED_ASSETS
        for name in set(CONTENT_HASHED_ASSETS) | set(VERSIONED_ASSETS): self.write(name, ('retained '+name).encode())
        for page in recovery.HTML:
            html = '<meta name="opportunity-team-generation" content="'+'0'*64+'">\n'
            html += '\n'.join('<script src="'+name+'?v='+'0'*64+'"></script>'
                for name in (*VERSIONED_ASSETS, *CONTENT_HASHED_ASSETS))+'\n'
            self.write(page, html.encode())
        package = {'current_corpus_sha256': 'c'*64, 'previous_corpus_sha256': 'd'*64,
            'source_hashes': {name: sha((self.files/name).read_bytes()) for name in (*recovery.HTML, recovery.DATA[1])}}
        self.write(recovery.PACKAGE, (json.dumps(package, indent=2)+'\n').encode())
        self.reader = self.stack.enter_context(patch.object(recovery, '_prior_cache', return_value=self.prior))

    def write(self, name, raw):
        path = self.files/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def project(self):
        return recovery._payloads(self.bundle, self.spec, root=self.root)

    def close(self): self.stack.close()


class ExactEvidenceProjection(unittest.TestCase):
    def setUp(self):
        self.f = EvidenceFixture(); self.addCleanup(self.f.close)

    def test_real_writer_restores_exact_four_owned_entries_only_and_preserves_other_fields(self):
        before = {p.relative_to(self.f.files).as_posix(): p.read_bytes() for p in self.f.files.rglob('*') if p.is_file()}
        report = self.f.project()
        self.assertTrue(report['publication_ready']); self.assertEqual(report['changed_records'], 0)
        after = {p.relative_to(self.f.files).as_posix(): p.read_bytes() for p in self.f.files.rglob('*') if p.is_file()}
        self.assertEqual({n for n in before if before[n] != after[n]}, recovery.CHANGED)
        cache = json.loads(after[recovery.DATA[0]])
        self.assertEqual(cache, self.f.cache | {'records': self.f.prior['records']})
        catalog = recovery.read_catalog(self.f.files/recovery.DATA[1])
        self.assertEqual(catalog, self.f.correct)
        package = json.loads(after[recovery.PACKAGE]); original = json.loads(before[recovery.PACKAGE])
        self.assertEqual({k:v for k,v in package.items() if k != 'source_hashes'},
            {k:v for k,v in original.items() if k != 'source_hashes'})
        self.assertEqual(package['source_hashes'], {n:sha(after[n]) for n in (*recovery.HTML, recovery.DATA[1])})

    def test_stale_wrong_source_wrong_document_or_already_present_entry_is_rejected(self):
        identifier = next(iter(self.f.spec['restored_entries']))
        for kind in ('entry_hash', 'stale', 'error', 'source', 'document', 'already_present'):
            with self.subTest(kind=kind):
                original = deepcopy(self.f.prior['records'][identifier]); pin = deepcopy(self.f.spec['restored_entries'][identifier])
                entry = self.f.prior['records'][identifier]
                if kind == 'stale': entry['status'] = 'stale'
                elif kind == 'error': entry['last_error'] = 'retained failure'
                elif kind == 'source': entry['source_signature'] = 'foreign notice'
                elif kind == 'document': entry['document']['sha256'] = '9'*64
                elif kind == 'entry_hash': entry['checked_at'] = 'changed'
                else:
                    changed = deepcopy(self.f.cache); changed['records'][identifier] = deepcopy(entry)
                    self.f.write(recovery.DATA[0], encode(changed))
                if kind not in ('entry_hash', 'already_present'):
                    self.f.spec['restored_entries'][identifier]['entry_sha256'] = sha(encode(entry))
                with self.assertRaisesRegex(ConfigurationFailure, 'exact_current_entry|owned_source_and_document|missing_companion_only'):
                    self.f.project()
                self.f.prior['records'][identifier] = original; self.f.spec['restored_entries'][identifier] = pin
                self.f.write(recovery.DATA[0], encode(self.f.cache))

    def test_unrelated_catalog_semantic_change_cannot_be_projected_as_schedule_repair(self):
        original = recovery.evidence.enrich_document_evidence
        def changed(*args, **kwargs):
            result, cache = original(*args, **kwargs)
            result['opportunities'][0]['title'] = 'changed semantics'
            return result, cache
        with patch.object(recovery.evidence, 'enrich_document_evidence', side_effect=changed):
            with self.assertRaisesRegex(ConfigurationFailure, 'only_schedule_projection'): self.f.project()

    def test_missing_owner_or_changed_clock_fails_before_projection(self):
        self.f.spec['projection_clock'] = '2026-09-24T00:00:00Z'
        with self.assertRaisesRegex(ConfigurationFailure, 'original_projection_clock'): self.f.project()
        self.f.spec['projection_clock'] = self.f.before['document_evidence_generated_at']
        self.f.spec['restored_entries']['foreign'] = self.f.spec['restored_entries'].pop('fixture-0')
        with self.assertRaisesRegex(ConfigurationFailure, 'all_restored_rows'): self.f.project()


class ProtectedProjectionPlan(unittest.TestCase):
    def test_actual_plan_has_exact_parent_four_entries_and_five_deltas(self):
        spec = recovery.plan()
        self.assertEqual(spec['parent']['run_id'], 35935924652)
        self.assertEqual(spec['parent']['artifact_id'], 10782818266)
        self.assertEqual(spec['parent']['receipt_artifact_id'], 10782704344)
        self.assertEqual(spec['parent']['candidate_id'], 'cd9872aada0a4ce3e89933bb4db95876a2debb2b0a20c5dec7774e57640fb61f')
        self.assertEqual(spec['parent']['manifest_sha256'], '777c8675a3164e67aca1c19d6bfbdc80081af2c0a490ece23dfc2a48b76d761d')
        self.assertEqual(len(spec['expected_files']), 126); self.assertEqual(len(spec['restored_entries']), 4)
        self.assertEqual(set(spec['changed_files']), recovery.CHANGED)
        self.assertEqual(spec['expected_files']['.nojekyll'], sha(b'\n'))

    def test_plan_rejects_extra_keys_boolean_ids_bad_dates_and_sixth_delta(self):
        original = recovery.plan()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'plan.json'
            for kind in ('extra', 'boolean', 'date', 'sixth', 'bad_hash'):
                with self.subTest(kind=kind):
                    value = deepcopy(original)
                    if kind == 'extra': value['allow_rebuild'] = True
                    elif kind == 'boolean': value['parent']['run_id'] = True
                    elif kind == 'date': value['projection_clock'] = '2026-02-30T01:00:00Z'
                    elif kind == 'sixth': value['changed_files']['data/subtopics.js'] = {'before':'a'*64,'after':'b'*64}
                    else: value['restored_entries'][next(iter(value['restored_entries']))]['entry_sha256'] = 'bad'
                    path.write_bytes(encode(value))
                    with patch.object(recovery, 'CONFIG', path):
                        with self.assertRaises(ConfigurationFailure): recovery.plan()

    def test_protected_cache_requires_ancestors_and_exact_raw_git_bytes(self):
        spec = recovery.plan(); raw = b'{"records":{}}\n'; spec['prior_cache']['sha256'] = sha(raw)
        with patch.object(recovery.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as ancestor, \
                patch.object(recovery.subprocess, 'check_output', return_value=raw) as git:
            self.assertEqual(recovery._prior_cache(Path('fixture'), spec), {'records': {}})
            self.assertEqual(ancestor.call_count, 2)
            self.assertIn(spec['prior_cache']['commit']+':data/document_evidence.json', git.call_args.args[0])
            git.return_value = raw+b' '
            with self.assertRaisesRegex(ConfigurationFailure, 'protected_prior_cache'): recovery._prior_cache(Path('fixture'), spec)
            ancestor.return_value.returncode = 1; git.reset_mock()
            with self.assertRaisesRegex(ConfigurationFailure, 'protected_ancestor'): recovery._prior_cache(Path('fixture'), spec)
            git.assert_not_called()


if __name__ == '__main__': unittest.main()
