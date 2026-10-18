"""One sealed paid asset survives successive source-only operations, offline."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import catalog_reconcile as repair, catalog_reconcile_spend as spend, release_candidate as c
from tools.offline_spend import Ledger, atomic_json, identity


class ReconciliationVectorRetention(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.state = self.root / 'state'
        (self.root / 'tools').mkdir()
        (self.root / 'tools/clock.py').write_bytes(b'unchanged passage preprocessing')
        self.inputs = ('tools/clock.py',)
        self.packet = {'corpus_sha256': 'd' * 64, 'configuration_sha256': 'e' * 64,
            'passage_count': 1, 'source_hashes': {name: c.digest((self.root / name).read_bytes()) for name in self.inputs}}
        self.book = Ledger(self.state / 'ledger.json', 'offline-123', 2, 300)
        self.book.event(kind='authenticated_vector_history', candidate_id='a' * 64)
        self.value = {'parent_run': '123', 'parent_candidate_id': 'a' * 64,
            'parent_manifest_sha256': 'b' * 64, 'original_spend': {'ledger_sha256': identity(self.book.read())},
            'operation_contract': {'config/sam_gov.json': 'a' * 64, 'tools/corpus_clock.mjs': 'c' * 64}}
        self.value['operation_sha256'] = identity(self.value)
        atomic_json(self.state / 'reconciliation.json', self.value)
        stack = ExitStack(); self.addCleanup(stack.close)
        stack.enter_context(patch.object(spend, '__file__', str(self.root / 'tools/catalog_reconcile_spend.py')))
        stack.enter_context(patch.object(spend, 'GENERATION_INPUTS', self.inputs))
        stack.enter_context(patch.object(spend, 'VECTOR_PREPROCESSORS', self.inputs))
        stack.enter_context(patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No HTTP')))
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('No provider')))
        prepared = spend.prepare(self.state, self.packet)
        reservation = spend.reserve(self.state, {'url': spend.URL, 'body': json.dumps({'input': ['One public passage'],
            'model': spend.MODEL, 'input_type': 'document', 'truncation': True,
            'output_dimension': 1024, 'output_dtype': 'float'})})
        spend.finish(self.state, {'key': reservation['key'], 'token': reservation['token'], 'status': 200,
            'request_id': 'f' * 32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 51},
                'data': [{'index': 0, 'embedding': [.125] * 1024}]}})
        report = {'status': 'written', 'model': spend.MODEL, 'API_request_count': 1, 'usage_total_tokens': 51,
            'API_requests': [{'model': spend.MODEL, 'http_status': 200, 'request_id': 'f' * 32,
                'usage_total_tokens': 51, 'passage_count': 1}]}
        self.raw = {name: ('unchanged paid asset: ' + name).encode() for name in spend.VECTOR_OUTPUTS}
        self.raw[spend.VECTOR_OUTPUTS[-1]] = c.encoded(report)
        self.hashes = {name: c.digest(raw) for name, raw in self.raw.items()}
        self.write_outputs(self.raw)
        spend.checkpoint(self.state, {'operation_sha256': prepared['operation_sha256'], 'outputs': self.hashes})
        self.sealed = self.state / 'vector-completions' / (self.value['operation_sha256'] + '.json')
        self.original_sealed = self.sealed.read_bytes(); self.original_ledger = self.book.path.read_bytes()
        self.source = self.complete_candidate(self.value)
        self.value['completed_candidate_id'] = self.source['candidate_id']
        atomic_json(self.state / 'reconciliation.json', self.value)
        self.new_operation(self.value, self.source, 'b')

    def write_outputs(self, raw):
        for name, value in raw.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)

    def complete_candidate(self, value, stage=None):
        receipt = {'operation_sha256': value['operation_sha256'],
            'cache_operation_contract': value['operation_contract'], 'ledger_sha256': identity(self.book.read())}
        if stage:
            receipt.update(retained_vector_source=value['retained_vector_source'], retained_vector_asset=stage)
        manifest = {'schema_version': 1, 'candidate_format': c.VERSION, 'files': self.hashes,
                    'source_reconciliation': receipt}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        bundle = self.state / 'complete-candidates' / manifest['candidate_id']
        for name, raw in self.raw.items():
            path = bundle / 'files' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        atomic_json(bundle / 'candidate.json', manifest)
        self.assertEqual(c.load(bundle), manifest)
        return manifest

    def new_operation(self, prior, source, revision):
        bundle = self.state / 'complete-candidates' / source['candidate_id']
        retained = repair.retain_vector_source(self.state, prior, source, bundle)
        value = {k: deepcopy(v) for k, v in prior.items() if k not in ('operation_sha256', 'completed_candidate_id')}
        value['operation_contract']['config/sam_gov.json'] = revision * 64
        value['retained_vector_source'] = retained
        value['operation_sha256'] = identity(value)
        atomic_json(self.state / 'reconciliation.json', value)
        self.current = value

    def reuse(self):
        self.write_outputs({name: b'cold predecessor' for name in spend.VECTOR_OUTPUTS})
        prepared = spend.prepare(self.state, self.packet)
        self.assertEqual(prepared['status'], 'restore')
        self.assertEqual(prepared['outputs'], self.hashes)
        self.write_outputs({name: Path(path).read_bytes() for name, path in prepared['blobs'].items()})
        spend.checkpoint(self.state, {'operation_sha256': self.current['operation_sha256'],
            'outputs': self.hashes, 'restored': True})
        self.assertEqual(spend.prepare(self.state, self.packet)['status'], 'complete')
        self.assertEqual(self.sealed.read_bytes(), self.original_sealed)
        self.assertEqual(self.book.path.read_bytes(), self.original_ledger)
        self.assertFalse((self.state / 'vector-completions' / (self.current['operation_sha256'] + '.json')).exists())
        return json.loads((self.state / 'vector-stage.json').read_bytes())

    def test_two_successive_source_repairs_restore_original_four_bytes_origin_and_budget(self):
        stage = self.reuse()
        self.assertEqual(stage['new_requests'], 0)
        self.assertEqual(stage['source']['operation_sha256'], self.value['operation_sha256'])
        child = self.complete_candidate(self.current, stage)
        prior = dict(self.current, completed_candidate_id=child['candidate_id'])
        self.new_operation(prior, child, 'c')
        self.assertEqual(self.current['retained_vector_source'], stage['source'])
        self.assertEqual(self.reuse()['source'], stage['source'])

    def test_changed_corpus_configuration_or_true_preprocessor_cannot_retain(self):
        binding = spend.vector_binding(self.packet)
        for name in ('corpus_sha256', 'configuration_sha256', 'passage_count', 'preprocessor', 'clock'):
            with self.subTest(name=name):
                changed = deepcopy(binding); current = deepcopy(self.current)
                if name == 'preprocessor': changed['source_hashes']['tools/clock.py'] = 'f' * 64
                elif name == 'clock': current['operation_contract']['tools/corpus_clock.mjs'] = 'f' * 64
                else: changed[name] = 2 if name == 'passage_count' else 'f' * 64
                self.assertIsNone(spend.retained_reconciliation_outputs(self.state, current, changed, self.root))
        self.assertEqual(self.book.path.read_bytes(), self.original_ledger)

    def test_reuse_then_fresh_corpus_seals_new_origin_and_later_reuses_new_asset(self):
        stage = self.reuse()
        child = self.complete_candidate(self.current, stage)
        self.new_operation(dict(self.current, completed_candidate_id=child['candidate_id']), child, 'c')
        changed = deepcopy(self.packet); changed['corpus_sha256'] = 'f' * 64
        self.assertEqual(spend.prepare(self.state, changed)['status'], 'prepared')
        before = self.book.read()
        reservation = spend.reserve(self.state, {'url': spend.URL, 'body': json.dumps({
            'input': ['Genuinely changed scientific passage'], 'model': spend.MODEL,
            'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})})
        spend.finish(self.state, {'key': reservation['key'], 'token': reservation['token'], 'status': 200,
            'request_id': 'e' * 32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 51},
                'data': [{'index': 0, 'embedding': [.25] * 1024}]}})
        self.raw = {name: ('new completed asset: ' + name).encode() for name in spend.VECTOR_OUTPUTS}
        self.raw[spend.VECTOR_OUTPUTS[-1]] = c.encoded({'status': 'written', 'model': spend.MODEL,
            'API_request_count': 1, 'usage_total_tokens': 51, 'API_requests': [{'model': spend.MODEL,
                'http_status': 200, 'request_id': 'e' * 32, 'usage_total_tokens': 51, 'passage_count': 1}]})
        self.hashes = {name: c.digest(raw) for name, raw in self.raw.items()}; self.write_outputs(self.raw)
        self.assertEqual(spend.checkpoint(self.state, {'operation_sha256': self.current['operation_sha256'],
            'outputs': self.hashes}), {'status': 'complete'})
        completion = self.state / 'vector-completions' / (self.current['operation_sha256'] + '.json')
        sealed = completion.read_bytes(); origin = json.loads(sealed)['accounting_origin']
        self.assertEqual(origin['operation_sha256'], self.current['operation_sha256'])
        self.assertEqual([row['id'] for row in origin['requests']], [reservation['token']])
        after = self.book.read()
        self.assertEqual(after['requests'][:-1], before['requests'])
        self.assertEqual(after['events'], before['events'])
        self.assertEqual(after['requests'][-1]['status'], 'valid')
        self.assertEqual(self.sealed.read_bytes(), self.original_sealed)
        fresh = self.complete_candidate(self.current)
        self.new_operation(dict(self.current, completed_candidate_id=fresh['candidate_id']), fresh, 'd')
        self.assertEqual(self.current['retained_vector_source']['candidate_id'], fresh['candidate_id'])
        self.write_outputs({name: b'cold predecessor' for name in spend.VECTOR_OUTPUTS})
        restored = spend.prepare(self.state, changed)
        self.assertEqual(restored['status'], 'restore')
        self.assertEqual(restored['outputs'], self.hashes)
        self.write_outputs({name: Path(path).read_bytes() for name, path in restored['blobs'].items()})
        spend.checkpoint(self.state, {'operation_sha256': self.current['operation_sha256'],
            'outputs': self.hashes, 'restored': True})
        self.assertEqual(self.book.read(), after)
        self.assertEqual(completion.read_bytes(), sealed)

    def test_same_corpus_valid_json_ledger_change_still_cannot_retain_old_asset(self):
        changed = self.book.read(); changed['requests'][0]['charged_microusd'] += 1
        atomic_json(self.book.path, changed)
        with self.assertRaisesRegex(ValueError, 'budgeted_measured_usage'):
            spend.retained_reconciliation_outputs(self.state, self.current, spend.vector_binding(self.packet), self.root)

    def test_old_binding_conflicting_with_sealed_completion_cannot_select_fresh_work(self):
        pointer = self.current['retained_vector_source']
        path = self.state / 'vector-bindings' / (pointer['operation_sha256'] + '.json')
        original = path.read_bytes()
        for key in ('corpus_sha256', 'configuration_sha256'):
            with self.subTest(key=key):
                changed = json.loads(original); changed[key] = 'f' * 64
                atomic_json(path, changed)
                with self.assertRaisesRegex(ValueError, 'completed_vector_identity'):
                    spend.prepare(self.state, self.packet)
                self.assertEqual(self.book.path.read_bytes(), self.original_ledger)
        path.write_bytes(original)

    def test_context_blob_ledger_or_manifest_tampering_fails_closed_without_dispatch(self):
        pointer = self.current['retained_vector_source']
        paths = [self.state / 'retained-vector-contexts' / (pointer['operation_sha256'] + '.json'),
            self.state / 'vector-outputs' / next(iter(self.hashes.values())), self.book.path,
            self.state / 'complete-candidates' / pointer['candidate_id'] / 'candidate.json']
        for path in paths:
            with self.subTest(path=path.name):
                before = path.read_bytes(); path.write_bytes(before + b' altered')
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    spend.retained_reconciliation_outputs(self.state, self.current, spend.vector_binding(self.packet), self.root)
                path.write_bytes(before)
        self.assertEqual(self.book.path.read_bytes(), self.original_ledger)

    def test_incomplete_preprocessor_identity_is_not_equivalent(self):
        binding = spend.vector_binding(self.packet); binding['source_hashes'].clear()
        with self.assertRaisesRegex(ValueError, 'retained_preprocessor_identity'):
            spend.retained_reconciliation_outputs(self.state, self.current, binding, self.root)


if __name__ == '__main__':
    unittest.main()
