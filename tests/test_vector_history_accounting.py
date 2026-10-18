"""Parent accounting classification uses sealed logical provenance, never guesses."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_catalog_reconcile_spend as fixtures
from tools import catalog_reconcile_spend as spend, release_candidate as candidate
from tools.offline_spend import atomic_json, identity


class VectorHistoryAccounting(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReconcileSpendTests('runTest')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    @contextmanager
    def event_workflow(self, command='node tools/run_budgeted_vectors.mjs --production --write'):
        git = candidate.git
        def protected(root, *args):
            if args == ('show', 'f' * 40 + ':.github/workflows/refresh-opportunities.yml'):
                return 'jobs:\n  generate:\n    steps:\n      - id: semantic-vectors\n        run: ' + command + '\n'
            return git(root, *args)
        with patch.object(candidate, 'git', side_effect=protected):
            yield

    def modern_parent(self, *, request_id='c' * 32, repeated_receipt=1):
        f = self.fixture
        self.state, self.book, _ = f.generation()
        value = spend.context(self.state, generation=True)
        value['operation_contract'] = {'corpus_sha256': 'd' * 64, 'configuration_sha256': 'e' * 64,
            'passage_count': 1, 'source_hashes': {'protected-builder': 'f' * 64}}
        value.pop('operation_sha256'); value['operation_sha256'] = identity(value)
        atomic_json(self.state / 'vector-operation.json', value)
        with patch.object(spend, 'production_ledger', return_value=self.book):
            reservation = spend.reserve(self.state, f.packet(), generation=True)
            response = f.finish_packet(reservation); response['request_id'] = request_id
            spend.finish(self.state, response, generation=True)
            row = {'model': spend.MODEL, 'usage_total_tokens': 51, 'http_status': 200,
                   'request_id': request_id, 'passage_count': 1}
            report = {'status': 'written', 'model': spend.MODEL, 'API_request_count': repeated_receipt,
                'usage_total_tokens': 51 * repeated_receipt, 'API_requests': [deepcopy(row) for _ in range(repeated_receipt)]}
            raw = {name: ('completed public bytes: ' + name).encode() for name in spend.VECTOR_OUTPUTS}
            raw[spend.VECTOR_OUTPUTS[-1]] = json.dumps(report).encode()
            self.origin = spend.budgeted_origin(self.state, value, raw, self.book)
            spend.retain_outputs(self.state, value, value['operation_contract'], raw, self.origin)
        self.parent = f.root / 'modern-parent'
        for name, content in raw.items():
            path = self.parent / 'files' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        self.manifest = {'candidate_id': 'b' * 64, 'generation_run_id': '123', 'generation_run_attempt': '1',
                         'generation_sha': 'd' * 40,
                         'files': {name: hashlib.sha256(content).hexdigest() for name, content in raw.items()}}
        self.original = deepcopy(self.book.read())
        self.write_parent()
        self.value = value

    def write_parent(self):
        atomic_json(self.parent / 'candidate.json', self.manifest)
        self.contract = {'parent_run': '123', 'parent_candidate_id': self.manifest['candidate_id'],
            'parent_manifest_sha256': hashlib.sha256((self.parent / 'candidate.json').read_bytes()).hexdigest(),
            'parent_generation_sha': self.manifest['generation_sha'],
            'parent_producer': {'run_id': '123', 'run_attempt': '1', 'head_sha': 'f' * 40,
                'path': '.github/workflows/refresh-opportunities.yml', 'event': 'schedule'},
            'original_spend': {'ledger_sha256': identity(self.original)},
            'operation_contract': {'reviewed-repair': 'a' * 64}}
        self.contract['operation_sha256'] = identity(self.contract)
        atomic_json(self.state / 'reconciliation.json', self.contract)

    def import_parent(self):
        with self.event_workflow():
            spend.import_history(self.state, self.parent, identity(self.original))

    def test_already_budgeted_requests_add_no_rows_or_charges_and_retry_is_identical(self):
        self.modern_parent()
        self.import_parent(); first = deepcopy(self.book.read()); self.import_parent()
        self.assertEqual(first['requests'], self.original['requests'])
        self.assertEqual(self.book.read(), first)
        self.assertEqual(first['events'][:-1], self.original['events'])
        self.assertEqual(first['events'][-1]['classification'], 'budgeted')
        self.assertEqual(first['events'][-1]['requests'], [])
        self.assertEqual(len(self.origin['requests']), 1)

    def test_optional_provider_id_and_repeated_cached_logical_rows_do_not_add_charges(self):
        self.modern_parent(request_id=None, repeated_receipt=2)
        self.import_parent()
        self.assertEqual(self.book.read()['requests'], self.original['requests'])
        self.assertEqual(len(self.origin['requests']), 1)
        self.assertEqual(self.origin['requests'][0]['charged_microusd'], 2)

    def test_partial_mixed_or_changed_modern_proof_rejects_before_any_accounting_write(self):
        self.modern_parent()
        path = self.state / 'vector-completions' / (self.value['operation_sha256'] + '.json')
        receipt = json.loads(path.read_bytes())
        variants = [None, dict(receipt, accounting_origin={}),
            dict(receipt, vector_binding={}),
            dict(receipt, accounting_origin=dict(self.origin, requests=[])),
            dict(receipt, accounting_origin=dict(self.origin, logical_id='offline-other'))]
        for variant in variants:
            with self.subTest(variant=variant):
                if variant is None:
                    path.unlink()
                else:
                    atomic_json(path, variant)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.import_parent()
                self.assertEqual(self.book.read(), self.original)
                atomic_json(path, receipt)
        token = self.origin['requests'][0]['id']
        broken = deepcopy(self.original)
        next(row for row in broken['requests'] if row['id'] == token)['charged_microusd'] += 1
        atomic_json(self.book.path, broken)
        with self.assertRaisesRegex(ValueError, 'original_ledger_before_import'):
            self.import_parent()

    def test_request_or_output_cache_tampering_does_not_claim_already_paid_coverage(self):
        self.modern_parent()
        key = self.origin['requests'][0]['key']
        cache = self.state / 'vector-responses' / (key + '.json')
        raw = cache.read_bytes(); cache.unlink()
        with self.assertRaises(FileNotFoundError):
            self.import_parent()
        self.assertEqual(self.book.read(), self.original); cache.write_bytes(raw)
        path = self.parent / 'files' / spend.VECTOR_OUTPUTS[0]
        path.write_bytes(b'changed parent vector manifest')
        with self.assertRaisesRegex(ValueError, 'parent_vector_output'):
            self.import_parent()
        self.assertEqual(self.book.read(), self.original)

    def test_budgeted_parent_at_full_request_cap_can_be_authenticated_without_new_allowance(self):
        self.modern_parent()
        original = deepcopy(self.original)
        for index in range(300 - len(original['requests'])):
            row = deepcopy(original['requests'][0]); row.update(id=f'completed-{index}', key=f'prior-{index}')
            original['requests'].append(row)
        atomic_json(self.book.path, original); self.original = original; self.write_parent()
        self.import_parent()
        self.assertEqual(len(self.book.read()['requests']), 300)
        self.assertEqual(self.book.read()['requests'], original['requests'])

    def test_producer_event_workflow_is_authoritative_and_derived_parents_are_explicitly_rejected(self):
        self.modern_parent()
        self.assertNotEqual(self.contract['parent_producer']['head_sha'], self.manifest['generation_sha'])
        self.import_parent()
        self.manifest['derived_from_candidate'] = '9' * 64; self.write_parent()
        with self.assertRaisesRegex(ValueError, 'original_generation_parent_required'):
            self.import_parent()

    def test_known_legacy_seven_request_usage_imports_once_with_original_empty_prefix(self):
        f = self.fixture
        self.state, self.book, self.parent = f.state, f.book, f.parent
        self.original = dict(f.original, requests=[], events=[])
        atomic_json(self.book.path, self.original)
        # Authenticated legacy633 token counts; request identifiers are safe
        # public receipt metadata. This unit fixture uses synthetic producer IDs.
        calls = [(25900, '31bcfcf44460930de42cedaa31240d16'), (58561, 'cc4d2575fd1718736ccf2986fd6dab00'),
            (56883, '69b1325dcf0f889de42cedaa312406e4'), (61593, '49729480386381b06ccf2986fd6da35c'),
            (51815, 'f78399ac1a4ffb80e42cedaa312400aa'), (51648, '829b945545e8cc286ccf2986fd6daccb'),
            (1074, 'b8f9f1dbb99f8cdae42cedaa312405e0')]
        report = {'status': 'written', 'model': spend.MODEL, 'API_request_count': 7,
            'usage_total_tokens': sum(tokens for tokens, _ in calls), 'API_requests': [
                {'model': spend.MODEL, 'usage_total_tokens': tokens, 'http_status': 200, 'request_id': request}
                for tokens, request in calls]}
        relative = spend.VECTOR_OUTPUTS[-1]; raw = json.dumps(report).encode()
        (self.parent / 'files' / relative).write_bytes(raw)
        self.manifest = {'candidate_id': 'a' * 64, 'generation_run_id': '123', 'generation_run_attempt': '1',
            'generation_sha': 'd' * 40, 'files': {relative: hashlib.sha256(raw).hexdigest()}}
        self.write_parent()
        command = 'node tools/build_search_v2_voyage_vectors.mjs --production --write'
        with self.event_workflow(command):
            spend.import_history(self.state, self.parent, identity(self.original))
            first = deepcopy(self.book.read())
            spend.import_history(self.state, self.parent, identity(self.original))
        self.assertEqual(self.book.read(), first)
        self.assertEqual(len(first['requests']), 7)
        self.assertEqual(sum(row['charged_microusd'] for row in first['requests']), 6152)
        self.assertEqual(sum(row['usage']['input_tokens'] for row in first['requests']), 307474)
        self.assertEqual(first['events'][-1]['classification'], 'legacy_untracked')


if __name__ == '__main__':
    unittest.main()
