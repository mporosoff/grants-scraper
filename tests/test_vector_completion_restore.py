"""Cold-checkout completion recovery; no source or provider transport."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import catalog_reconcile_spend as spend
from tools.offline_spend import Ledger, atomic_json, identity


class VectorCompletionRestore(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); (self.root / 'tools').mkdir()
        (self.root / 'tools/clock.py').write_bytes(b'public_input = True\n')
        self.raw = {name: ('original completed bytes and timestamp: ' + name).encode() for name in spend.VECTOR_OUTPUTS}
        self.raw[spend.VECTOR_OUTPUTS[-1]] = json.dumps({'status': 'written', 'model': spend.MODEL,
            'API_request_count': 1, 'usage_total_tokens': 51, 'API_requests': [{'model': spend.MODEL,
                'http_status': 200, 'request_id': 'c' * 32, 'usage_total_tokens': 51, 'passage_count': 1}]}).encode()
        for name, raw in self.raw.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in self.raw.items()}
        self.packet = {'run_id': '123', 'mode': 'maintenance', 'corpus_sha256': 'd' * 64,
                       'configuration_sha256': 'e' * 64, 'passage_count': 1, 'retained_asset_eligible': False,
                       'source_hashes': {'tools/clock.py': hashlib.sha256((self.root / 'tools/clock.py').read_bytes()).hexdigest()}}
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(spend, '__file__', str(self.root / 'tools/catalog_reconcile_spend.py')))
        self.stack.enter_context(patch.object(spend, 'GENERATION_INPUTS', ('tools/clock.py',)))
        self.stack.enter_context(patch.dict('os.environ', GITHUB_RUN_ID='123'))

    def prepare(self, generation=True):
        self.state = self.root / ('offline-123' if generation else 'reconcile-state')
        self.book = Ledger(self.state / 'ledger.json', 'offline-123', 2, 300)
        if generation:
            self.stack.enter_context(patch.object(spend, 'production_ledger', return_value=self.book))
        else:
            value = {'parent_run': '123', 'parent_candidate_id': 'a' * 64,
                     'operation_contract': {'reviewed-source': 'b' * 64}}
            value['operation_sha256'] = identity(value)
            atomic_json(self.state / 'reconciliation.json', value)
            self.book.event(kind='authenticated_vector_history', candidate_id='a' * 64)
        prepared = spend.prepare(self.state, self.packet, generation=generation)
        body = {'url': spend.URL, 'body': json.dumps({'input': ['Public funded research passage'],
            'model': spend.MODEL, 'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})}
        reserved = spend.reserve(self.state, body, generation=generation)
        spend.finish(self.state, {'key': reserved['key'], 'token': reserved['token'], 'status': 200,
            'request_id': 'c' * 32, 'payload': {'model': spend.MODEL,
                'data': [{'index': 0, 'embedding': [.125] * 1024}], 'usage': {'total_tokens': 51}}}, generation=generation)
        return prepared

    def checkpoint(self, prepared, generation=True):
        return spend.checkpoint(self.state, {'operation_sha256': prepared['operation_sha256'], 'outputs': self.hashes},
                                generation=generation)

    def cold_checkout(self):
        for name in spend.VECTOR_OUTPUTS:
            (self.root / name).write_bytes(b'cold checkout protected predecessor')

    def test_normal_and_reconcile_cold_checkouts_recover_all_four_exact_blobs_without_spending(self):
        for generation in (True, False):
            with self.subTest(generation=generation):
                for name, raw in self.raw.items(): (self.root / name).write_bytes(raw)
                prepared = self.prepare(generation)
                self.checkpoint(prepared, generation)
                sealed_path = self.state / 'vector-completions' / (prepared['operation_sha256'] + '.json')
                sealed = json.loads(sealed_path.read_bytes())
                self.assertEqual(sealed['accounting_origin']['kind'], 'budgeted')
                before = deepcopy(self.book.read()); self.cold_checkout()
                restored = spend.prepare(self.state, self.packet, generation=generation)
                self.assertEqual(restored['status'], 'restore')
                self.assertEqual(restored['outputs'], self.hashes)
                self.assertEqual(set(restored['blobs']), set(spend.VECTOR_OUTPUTS))
                self.assertEqual({name: Path(path).read_bytes() for name, path in restored['blobs'].items()}, self.raw)
                self.assertTrue(all((self.root / name).read_bytes() == b'cold checkout protected predecessor'
                                    for name in spend.VECTOR_OUTPUTS), 'Python authenticates; the coherent Node writer restores')
                for name, path in restored['blobs'].items(): (self.root / name).write_bytes(Path(path).read_bytes())
                spend.checkpoint(self.state, {'operation_sha256': prepared['operation_sha256'],
                    'outputs': self.hashes, 'restored': True}, generation=generation)
                self.assertEqual(spend.prepare(self.state, self.packet, generation=generation)['status'], 'complete')
                self.assertEqual(json.loads(sealed_path.read_bytes())['accounting_origin'], sealed['accounting_origin'])
                self.assertEqual(self.book.read(), before)
                stage = json.loads((self.state / 'vector-stage.json').read_bytes())
                self.assertEqual(stage['new_requests'], 0); self.assertEqual(stage['new_usage_total_tokens'], 0)

    def test_interrupted_byte_checkpoint_never_seals_partial_output_and_retry_reuses_saved_bytes(self):
        prepared = self.prepare(); before = deepcopy(self.book.read())
        replace = spend.os.replace; calls = 0
        def interrupt(source, target):
            nonlocal calls
            calls += 1
            if calls == 3: raise OSError('interrupted durable blob write')
            return replace(source, target)
        with patch.object(spend.os, 'replace', side_effect=interrupt):
            with self.assertRaisesRegex(OSError, 'interrupted durable blob write'): self.checkpoint(prepared)
        self.assertFalse((self.state / 'vector-completions' / (prepared['operation_sha256'] + '.json')).exists())
        self.assertEqual(len(list((self.state / 'vector-outputs').glob('[!.]*'))), 2)
        self.checkpoint(prepared)
        self.assertEqual(spend.prepare(self.state, self.packet, generation=True)['status'], 'complete')
        self.assertEqual(self.book.read(), before)

    def test_missing_corrupt_or_misbound_completion_fails_before_output_mutation_or_budget_changes(self):
        prepared = self.prepare(); self.checkpoint(prepared); before = deepcopy(self.book.read()); self.cold_checkout()
        receipt_path = self.state / 'vector-completions' / (prepared['operation_sha256'] + '.json')
        receipt = json.loads(receipt_path.read_bytes())
        for change in (lambda r: r.update(operation_sha256='f' * 64),
                       lambda r: r['vector_binding'].update(corpus_sha256='f' * 64),
                       lambda r: r['outputs'].update({'../unexpected': 'f' * 64})):
            wrong = deepcopy(receipt); change(wrong); atomic_json(receipt_path, wrong)
            with self.assertRaisesRegex(ValueError, 'completed_vector_identity'):
                spend.prepare(self.state, self.packet, generation=True)
        atomic_json(receipt_path, receipt)
        wrong = deepcopy(receipt); wrong['accounting_origin']['report_sha256'] = 'f' * 64; atomic_json(receipt_path, wrong)
        with self.assertRaises(ValueError): spend.prepare(self.state, self.packet, generation=True)
        atomic_json(receipt_path, receipt)
        blob = self.state / 'vector-outputs' / next(iter(self.hashes.values()))
        raw = blob.read_bytes()
        for corrupt in (b'changed', None):
            if corrupt is None: blob.unlink()
            else: blob.write_bytes(corrupt)
            with self.assertRaisesRegex(ValueError, 'completed_output_blob_changed'):
                spend.prepare(self.state, self.packet, generation=True)
            blob.write_bytes(raw)
        self.assertEqual(self.book.read(), before)
        self.assertTrue(all((self.root / name).read_bytes() == b'cold checkout protected predecessor' for name in spend.VECTOR_OUTPUTS))

    def test_changed_corpus_requires_new_operation_and_never_restores_old_vectors(self):
        prepared = self.prepare(); self.checkpoint(prepared); self.cold_checkout()
        changed = dict(self.packet, corpus_sha256='f' * 64)
        self.assertEqual(spend.prepare(self.state, changed, generation=True)['status'], 'prepared')
        for name, raw in self.raw.items(): (self.root / name).write_bytes(raw)
        prepared = self.prepare(False); self.checkpoint(prepared, False)
        with self.assertRaisesRegex(ValueError, 'reconciliation_vector_inputs_changed'):
            spend.prepare(self.state, changed, generation=False)


if __name__ == '__main__':
    unittest.main()
