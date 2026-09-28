"""Authenticated recovery, invariant firewall and durable vector ownership contracts."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import program_area_revalidation as p, release_candidate as c


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as output:
        for name, raw in files.items():
            output.writestr(name, raw)
    return stream.getvalue()


class FakeAPI:
    def __init__(self):
        self.rows = []
        self.runs = {}
        self.raw = {}

    def run(self, identifier, attempt=1, head='a' * 40):
        row = {'id': identifier, 'run_attempt': attempt, 'head_sha': head, 'head_branch': 'main',
            'event': 'workflow_dispatch', 'path': p.auth.REFRESH, 'status': 'in_progress', 'conclusion': None}
        self.runs[str(identifier)] = row
        self.runs[f'{identifier}/attempts/{attempt}'] = row
        return row

    def artifact(self, identifier, name, run, files):
        raw = archive(files)
        row = {'id': identifier, 'name': name, 'expired': False, 'digest': 'sha256:' + p.sha(raw),
            'workflow_run': {'id': run['id'], 'head_sha': run['head_sha']}}
        self.rows.append(row); self.raw[identifier] = raw
        return row

    def __call__(self, route):
        if route.startswith('actions/runs/'):
            return c.encoded(self.runs[route.removeprefix('actions/runs/')])
        if route.startswith('actions/artifacts?'):
            return c.encoded({'total_count': len(self.rows), 'artifacts': self.rows})
        identifier = int(route.split('/')[2])
        if route.endswith('/zip'):
            return self.raw[identifier]
        return c.encoded(next(row for row in self.rows if row['id'] == identifier))


class ParentAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        self.api = FakeAPI(); run = self.api.run(p.PARENT_RUN, 2, p.PARENT_EVENT_SHA)
        vector_receipt = c.encoded({'API_request_count': 7, 'usage_total_tokens': 313283})
        generated = {p.VECTORS[0]: c.encoded({'reuse_permitted': False}), p.VECTORS[3]: vector_receipt}
        manifest = {'schema_version': 1, 'candidate_format': c.VERSION,
            'generation_sha': p.PARENT_GENERATION_SHA, 'generation_run_id': str(p.PARENT_RUN),
            'generation_run_attempt': '2', 'dependency_groups': {'source': {'files': {
                'scripts/extract_document_evidence.py': p.PARENT_EXTRACTOR_SHA256}}},
            'files': {n: p.sha(raw) for n, raw in generated.items()},
            'generation_files': {n: p.sha(raw) for n, raw in generated.items()}}
        manifest['candidate_id'] = p.sha(c.encoded(manifest))
        self.manifest = manifest
        payload = {'candidate.json': c.encoded(manifest), **{'files/' + n: raw for n, raw in generated.items()}}
        for name, raw in payload.items():
            target = self.bundle/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        packets = {'candidate': payload, 'state': {'ledger.json': c.encoded({'logical_id': f'offline-{p.PARENT_RUN}',
            'limit_microusd': 2000000, 'max_requests': 300, 'requests': []}),
            'team-progress.json': b'{}', 'usage-summary.json': b'{}'},
            'reservation': {'spend-reservation.json': c.encoded({'attempt': '2', 'maximum_logical_spend_usd': 2,
                'mode': 'maintenance', 'prior_ledger_hash': 'ca9b06673147b96f093e891f870da4d5039f0c5dc300caf39348b740d2c475ee',
                'run_id': str(p.PARENT_RUN)})}}
        artifacts = {}
        for index, (role, files) in enumerate(packets.items(), 1):
            name = role + '-original'
            meta = self.api.artifact(index, name, run, files)
            artifacts[role] = (index, name, meta['digest'].removeprefix('sha256:'))
        for key, value in {'PARENT_CANDIDATE': manifest['candidate_id'], 'PARENT_ARTIFACTS': artifacts,
            'PARENT_MANIFEST_SHA256': p.sha(c.encoded(manifest)),
            'PARENT_VECTOR_RECEIPT_SHA256': p.sha(vector_receipt)}.items():
            patcher = patch.object(p, key, value); patcher.start(); self.addCleanup(patcher.stop)

    def test_exact_remote_bundle_and_original_spend_owner(self):
        original, spending = p.authenticate_parent(self.bundle, api=self.api)
        self.assertEqual(original, self.manifest)
        self.assertEqual(spending['logical_id'], f'offline-{p.PARENT_RUN}')
        self.assertEqual(spending['prior_vector_tokens'], 313283)
        self.assertEqual(spending['document_requests'], 0)

    def test_local_bundle_is_not_authentication(self):
        self.api.rows[0]['workflow_run']['head_sha'] = 'b' * 40
        with self.assertRaisesRegex(Exception, 'artifact_metadata'):
            p.authenticate_parent(self.bundle, api=self.api)

    def test_original_document_state_digest_is_required(self):
        self.api.raw[2] += b'tampering'
        with self.assertRaisesRegex(Exception, 'raw_artifact_digest'):
            p.authenticate_parent(self.bundle, api=self.api)

    def test_parent_event_and_generation_are_distinct(self):
        self.api.runs[str(p.PARENT_RUN)]['head_sha'] = p.PARENT_GENERATION_SHA
        with self.assertRaisesRegex(ValueError, 'parent_event_sha'):
            p.authenticate_parent(self.bundle, api=self.api)


class ProjectionContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root/'data').mkdir()
        self.before = {'generated_at': '2026-09-28T21:48:42.702959Z',
            'document_evidence_generated_at': '2026-09-28T21:50:18.818037Z', 'record_count': 1,
            'opportunities': [{'opportunity_id': '359655', 'title': 'Research education',
                'topic_areas': ['Education and workforce', 'Cybersecurity'],
                'document_program_areas': ['cybersecurity'], 'document_search_text': 'facts cybersecurity',
                'close_date': '2027-05-26', 'next_submission': {'date': '2027-05-26', 'as_of': '2026-09-28'}}]}
        self.cache = {'generated_at': self.before['document_evidence_generated_at'], 'records': {'359655': {
            'program_areas': [{'label': 'cybersecurity', 'citation': {'quote': 'NIST cybersecurity framework'}}],
            'checked_at': self.before['document_evidence_generated_at'], 'facts': [{'type': 'cost_share', 'value': False}]}}}
        (self.root/p.PROJECTION[2]).write_bytes(c.encoded(self.cache))
        self.after = deepcopy(self.before); self.updated = deepcopy(self.cache)
        self.updated['records']['359655']['program_areas'] = []
        self.after['opportunities'][0].update(topic_areas=['Education and workforce'], document_search_text='facts')
        del self.after['opportunities'][0]['document_program_areas']

    def project(self, transform=None, gate=True):
        after, updated = deepcopy(self.after), deepcopy(self.updated)
        if transform:
            transform(after, updated)
        with patch('scripts.enrich_catalog.read_catalog', return_value=deepcopy(self.before)), \
             patch('scripts.subtopic_records.read_cache', return_value={}), \
             patch('scripts.extract_document_evidence.revalidate_program_areas_only', return_value=(after, updated, ['359655'])), \
             patch('tools.verify_notice_publication.verify', return_value={'publication_ready': gate}):
            return p.projection(self.root, '2026-09-29T01:00:00+00:00')

    def test_deterministic_affected_only_projection_preserves_original_clocks(self):
        first, details = self.project(); second, _ = self.project()
        self.assertEqual(first, second)
        self.assertEqual(details['affected_catalog_ids'], ['359655'])
        cache = json.loads(first[p.PROJECTION[2]])
        self.assertEqual(cache['generated_at'], self.cache['generated_at'])
        self.assertEqual(cache['records']['359655']['facts'], self.cache['records']['359655']['facts'])
        self.assertEqual(details['source_requests'] + details['document_ai_requests'] + details['team_requests'], 0)

    def test_deadline_or_currentness_mutation_is_rejected(self):
        for key in ('close_date', 'next_submission'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'unchanged_facts'):
                self.project(lambda catalog, cache: catalog['opportunities'][0].update({key: 'changed'}))

    def test_evidence_fact_and_clock_mutation_is_rejected(self):
        for key in ('checked_at', 'facts'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'unchanged_evidence_facts'):
                self.project(lambda catalog, cache: cache['records']['359655'].update({key: 'changed'}))

    def test_new_program_area_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no_new_evidence_hits'):
            self.project(lambda catalog, cache: cache['records']['359655']['program_areas'].append({'label': 'new'}))

    def test_notice_gate_failure_prevents_preparation(self):
        with self.assertRaisesRegex(ValueError, 'notice_projection_gate'):
            self.project(gate=False)


class VectorOwnershipContracts(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI(); self.run = self.api.run(900, 1)
        self.owner = {'run_id': 900, 'run_attempt': 1, 'head_sha': 'a' * 40}
        self.receipt = {'audit_at': '2026-09-29T01:00:00+00:00',
            'projection_hashes': {n: p.sha(n.encode()) for n in p.PROJECTION}}
        self.reservation = {'version': p.VERSION, 'parent_candidate': p.PARENT_CANDIDATE, 'owner': self.owner,
            'max_requests': p.MAX_REQUESTS, 'max_seconds': p.MAX_SECONDS,
            'projection_hashes': self.receipt['projection_hashes'], 'receipt_sha256': p.sha(c.encoded(self.receipt))}

    def reserve(self):
        return self.api.artifact(91, p.artifact_name('reservation', self.owner), self.run,
            {'reservation.json': c.encoded(self.reservation)})

    def checkpoint(self):
        files = {'receipt.json': c.encoded(self.receipt), 'reservation.json': c.encoded(self.reservation),
            'prior-vector-receipt.json': b'prior', **{'files/' + n: n.encode() for n in p.PROJECTION + p.VECTORS}}
        checkpoint = {'version': p.VERSION, 'owner': self.owner, 'files': {n: p.sha(raw) for n, raw in files.items()}}
        files['checkpoint.json'] = c.encoded(checkpoint)
        return self.api.artifact(92, p.artifact_name('state', self.owner), self.run, files)

    def test_repository_wide_prior_reservation_blocks_new_spend(self):
        self.reserve()
        reservation, files = p.history(api=self.api)
        self.assertIsNone(files)
        self.assertEqual(reservation['owner']['run_id'], 900)
        with tempfile.TemporaryDirectory() as d, patch.object(p, 'validate_receipt', return_value={}):
            with self.assertRaisesRegex(ValueError, 'vector_pass_already_reserved'):
                p.reserve_vectors('unused', Path(d)/'reservation.json', api=self.api)

    def test_interrupted_reservation_without_state_never_allocates_again(self):
        self.reserve()
        with patch.object(p, 'validate_receipt', return_value=self.receipt), patch.object(p, 'owner', return_value=self.owner):
            with self.assertRaisesRegex(ValueError, 'requires_complete_checkpoint'):
                p.restore_vectors('unused', 'unused', api=self.api)

    def test_expired_reservation_fails_closed(self):
        self.reserve()['expired'] = True
        with self.assertRaisesRegex(Exception, 'artifact_metadata'):
            p.history(api=self.api)

    def test_complete_checkpoint_binds_original_audit_and_all_projection_vector_bytes(self):
        self.reserve(); self.checkpoint()
        with patch.object(p, 'PARENT_VECTOR_RECEIPT_SHA256', p.sha(b'prior')):
            _, files = p.history(api=self.api)
        self.assertEqual(json.loads(files['receipt.json'])['audit_at'], self.receipt['audit_at'])
        self.assertEqual(set(files), {'receipt.json', 'reservation.json', 'checkpoint.json',
            'prior-vector-receipt.json', *('files/' + n for n in p.PROJECTION + p.VECTORS)})

    def test_state_raw_tampering_rejected(self):
        self.reserve(); self.checkpoint(); self.api.raw[92] += b'tamper'
        with self.assertRaisesRegex(Exception, 'raw_artifact_digest'):
            p.history(api=self.api)

    def test_second_run_cannot_own_or_restore_original_correction(self):
        with patch.object(p, 'owner', return_value={**self.owner, 'run_id': 901}):
            with self.assertRaisesRegex(ValueError, 'resume_original_correction_run_900'):
                p.require_original_correction_run(self.reservation)
        with patch.object(p, 'owner', return_value={**self.owner, 'run_attempt': 2}):
            p.require_original_correction_run(self.reservation)

    def test_duplicate_reservations_and_incomplete_inventory_rejected(self):
        self.reserve()
        self.api.artifact(93, p.artifact_name('reservation', {**self.owner, 'run_attempt': 2}), self.run,
            {'reservation.json': c.encoded(self.reservation)})
        with self.assertRaisesRegex(ValueError, 'conflicting_vector_owners'):
            p.history(api=self.api)
        with self.assertRaisesRegex(ValueError, 'complete_artifact_inventory'):
            p.inventory(api=lambda _: c.encoded({'total_count': 1, 'artifacts': []}))

    def test_prepare_reuses_checkpoint_audit_timestamp_and_preserves_team_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'root'; root.mkdir(); bundle = Path(d)/'parent'
            original_bytes = {name: ('parent ' + name).encode() for name in p.PROJECTION + p.VECTORS}
            original_bytes['data/opportunity_teams.js'] = b'unchanged teams'
            for name, raw in original_bytes.items():
                target = bundle/'files'/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            original = {'generation_files': {n: p.sha(raw) for n, raw in original_bytes.items()}}
            projected = {name: ('corrected ' + name).encode() for name in p.PROJECTION}
            details = {'source_requests': 0}; spending = {'logical_id': 'original'}
            receipt = p.receipt_for(original, spending, projected, details, self.receipt['audit_at'])
            with patch.object(p, 'authenticate_parent', return_value=(original, spending)), \
                 patch.object(p, 'verify_dependency_scope'), \
                 patch.object(p, 'history', return_value=(self.reservation, {'receipt.json': c.encoded(receipt)})), \
                 patch.object(p, 'owner', return_value=self.owner), \
                 patch.object(p, 'projection', return_value=(projected, details)) as replay:
                actual = p.prepare(bundle, root/'receipt.json', root=root)
            self.assertEqual(actual['audit_at'], self.receipt['audit_at'])
            self.assertEqual(replay.call_args.args[1], self.receipt['audit_at'])
            self.assertEqual((root/'data/opportunity_teams.js').read_bytes(), b'unchanged teams')


class VectorReceiptContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('assets/search-hybrid.js', 'data/opportunities.js', 'data/subtopics.js'):
            target = self.root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(name.encode())
        self.manifest = {'dimension': 1024, 'passage_count': 1557, 'corpus_sha256': 'corpus', 'vector_sha256': 'vectors'}
        self.receipt = {'status': 'written', 'model': 'voyage-4-lite', 'passage_count': 1557,
            'reused_passage_count': 0, 'embedded_passage_count': 1557,
            'API_requests': [{'http_status': 200, 'model': 'voyage-4-lite', 'usage_total_tokens': 100}],
            'API_request_count': 1, 'usage_total_tokens': 100,
            'source_hashes': p.hashes(self.root, ('assets/search-hybrid.js', 'data/opportunities.js', 'data/subtopics.js')),
            'corpus_sha256': 'corpus', 'vector_sha256': 'vectors'}

    def validate(self):
        for name, value in ((p.VECTORS[0], self.manifest), (p.VECTORS[3], self.receipt)):
            target = self.root/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(c.encoded(value))
        with patch.object(p.subprocess, 'run', return_value=type('Result', (), {'returncode': 0})()):
            p.validate_vectors(self.root)

    def test_complete_coherent_receipt_is_accepted(self):
        self.validate()

    def test_request_cap_and_token_accounting_fail_closed(self):
        self.receipt['API_requests'] *= 9
        self.receipt['API_request_count'] = 9; self.receipt['usage_total_tokens'] = 900
        with self.assertRaisesRegex(ValueError, 'vector_receipt_and_budget'):
            self.validate()
        self.receipt['API_requests'] = self.receipt['API_requests'][:1]
        self.receipt['API_request_count'] = 1
        with self.assertRaisesRegex(ValueError, 'vector_receipt_and_budget'):
            self.validate()

    def test_stale_corpus_input_or_unstable_parent_reuse_is_rejected(self):
        for mutate in (lambda: self.receipt['source_hashes'].update({'data/opportunities.js': 'stale'}),
                       lambda: self.receipt.update(reused_passage_count=1)):
            before = deepcopy(self.receipt); mutate()
            with self.assertRaisesRegex(ValueError, 'vector_receipt_and_budget'):
                self.validate()
            self.receipt = before


class DependencyScopeContracts(unittest.TestCase):
    def test_only_extractor_change_is_permitted(self):
        original = {'dependency_groups': {group: {'files': {'input': 'original'}, 'fingerprint': 'old'}
            for group in ('source', 'teams', 'semantic')}}
        for changed in ({'source': ['scripts/extract_document_evidence.py']},
            {'source': ['scripts/extract_document_evidence.py', 'scripts/build_catalog.py']},
            {'source': ['scripts/extract_document_evidence.py'], 'teams': ['tools/team_provider.py']},
            {'source': ['scripts/extract_document_evidence.py'], 'semantic': ['assets/search-hybrid.js']}):
            with patch('tools.release_dependencies.snapshot', return_value={}), \
                 patch('tools.release_dependencies.changed_groups', return_value=changed), patch.object(c, 'git'):
                if changed == {'source': ['scripts/extract_document_evidence.py']}:
                    p.verify_dependency_scope('unused', original)
                else:
                    with self.assertRaisesRegex(ValueError, 'only_program_area_extractor'):
                        p.verify_dependency_scope('unused', original)


if __name__ == '__main__':
    unittest.main()
