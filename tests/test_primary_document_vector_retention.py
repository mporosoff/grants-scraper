"""A corrected notice recipe reuses a complete paid asset without relabelling it."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import catalog_reconcile_spend as spend, program_area_revalidation as p, release_candidate as c
from tools.catalog_reconcile import request_identity
from tools.offline_spend import Ledger, atomic_json, identity


class PrimaryDocumentVectorRetention(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.state = self.root/'state'
        (self.root/'tools').mkdir(); (self.root/'tools/clock.py').write_bytes(b'unchanged passage preprocessing')
        self.inputs = ('tools/clock.py',)
        self.packet = {'corpus_sha256': 'd'*64, 'configuration_sha256': 'e'*64, 'passage_count': 1,
            'source_hashes': {name: c.digest((self.root/name).read_bytes()) for name in self.inputs}}
        parent = {'schema_version': 1, 'candidate_format': c.VERSION, 'files': {}, 'generation_files': {}}
        parent['candidate_id'] = c.digest(c.encoded(parent)); self.parent = parent
        atomic_json(self.state/'parent-candidate/candidate.json', parent)
        self.book = Ledger(self.state/'ledger.json', 'offline-123', 2, 300)
        prior = self.book.reserve('voyage', spend.MODEL, 'generation_vectors', '1'*64, 3, 1)
        self.book.complete(prior, status='valid', charged_microusd=2, usage=spend.vector_usage(51),
            response_sha256='2'*64, provider_request_id='3'*32)
        self.book.event(kind='authenticated_vector_history', candidate_id=parent['candidate_id'])
        self.value = {'version': p.MODERN_VERSION, 'projection_kind': 'primary_document', 'parent_run': '123',
            'parent_candidate_id': parent['candidate_id'], 'parent_manifest_sha256': c.digest(c.encoded(parent)),
            'original_spend': {'ledger_sha256': identity(self.book.read())},
            'retained_requests': p.retained_requests(self.book.read()),
            # Match the first native primary checkpoint: clock is in the public
            # semantic dependency receipt, not yet the private operation recipe.
            'operation_contract': {'tools/primary_document_revalidation.py': 'a'*64}}
        self.value['operation_sha256'] = identity(self.value)
        atomic_json(self.state/'reconciliation.json', self.value)
        stack = ExitStack(); self.addCleanup(stack.close)
        stack.enter_context(patch.object(spend, '__file__', str(self.root/'tools/catalog_reconcile_spend.py')))
        stack.enter_context(patch.object(spend, 'GENERATION_INPUTS', self.inputs))
        stack.enter_context(patch.object(spend, 'VECTOR_PREPROCESSORS', self.inputs))
        stack.enter_context(patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('No HTTP')))
        stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('No provider')))
        prepared = spend.prepare(self.state, self.packet)
        request = spend.reserve(self.state, {'url': spend.URL, 'body': json.dumps({'input': ['One public passage'],
            'model': spend.MODEL, 'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})})
        spend.finish(self.state, {'key': request['key'], 'token': request['token'], 'status': 200,
            'request_id': 'f'*32, 'payload': {'model': spend.MODEL, 'usage': {'total_tokens': 51},
                'data': [{'index': 0, 'embedding': [.125]*1024}]}})
        report = {'status': 'written', 'model': spend.MODEL, 'API_request_count': 1, 'usage_total_tokens': 51,
            'API_requests': [{'model': spend.MODEL, 'http_status': 200, 'request_id': 'f'*32,
                'usage_total_tokens': 51, 'passage_count': 1}]}
        self.raw = {name: ('complete paid asset: '+name).encode() for name in spend.VECTOR_OUTPUTS}
        self.raw[spend.VECTOR_OUTPUTS[-1]] = c.encoded(report)
        self.hashes = {name: c.digest(raw) for name, raw in self.raw.items()}; self.write_outputs(self.raw)
        spend.checkpoint(self.state, {'operation_sha256': prepared['operation_sha256'], 'outputs': self.hashes})
        self.sealed = self.state/'vector-completions'/(self.value['operation_sha256']+'.json')
        self.original_sealed = self.sealed.read_bytes(); self.original_ledger = self.book.path.read_bytes()
        self.source = self.complete_candidate(self.value)
        self.value['completed_candidate_id'] = self.source['candidate_id']
        atomic_json(self.state/'reconciliation.json', self.value)
        self.new_operation(self.value, self.source, 'b')

    def write_outputs(self, raw):
        for name, value in raw.items():
            path = self.root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)

    def complete_candidate(self, value, accounting=None):
        receipt = value | {'ledger_sha256': identity(self.book.read()),
            'vector_accounting': accounting or {'classification': 'budgeted'}}
        manifest = {'schema_version': 1, 'candidate_format': c.VERSION, 'files': self.hashes,
            'dependency_groups': {'semantic': {'files': {'tools/corpus_clock.mjs': 'c'*64}}},
            'program_area_revalidation': receipt}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        bundle = self.state/'complete-candidates'/manifest['candidate_id']
        for name, raw in self.raw.items():
            path = bundle/'files'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        atomic_json(bundle/'candidate.json', manifest); self.assertEqual(c.load(bundle), manifest)
        return manifest

    def new_operation(self, prior, source, revision):
        bundle = self.state/'complete-candidates'/source['candidate_id']
        retained = p.retain_primary_vector_source(self.state, prior, source, bundle)
        value = {k: deepcopy(v) for k,v in prior.items() if k not in ('operation_sha256', 'completed_candidate_id')}
        value['operation_contract'].update({'tools/primary_document_revalidation.py': revision*64,
            'tools/corpus_clock.mjs': 'c'*64})
        value['retained_vector_source'] = retained; value['operation_sha256'] = identity(value)
        atomic_json(self.state/'reconciliation.json', value); self.current = value

    def restore(self):
        self.write_outputs({name: b'cold predecessor' for name in spend.VECTOR_OUTPUTS})
        prepared = spend.prepare(self.state, self.packet)
        self.assertEqual(prepared['status'], 'restore'); self.assertEqual(prepared['outputs'], self.hashes)
        self.write_outputs({name: Path(path).read_bytes() for name,path in prepared['blobs'].items()})
        spend.checkpoint(self.state, {'operation_sha256': self.current['operation_sha256'],
            'outputs': self.hashes, 'restored': True})
        self.assertEqual(spend.prepare(self.state, self.packet)['status'], 'complete')
        self.assertEqual(self.sealed.read_bytes(), self.original_sealed)
        self.assertEqual(self.book.path.read_bytes(), self.original_ledger)
        return json.loads((self.state/'vector-stage.json').read_bytes())

    def test_cold_recipe_repair_keeps_whole_asset_original_accounting_and_ledger(self):
        proof = self.restore()
        self.assertEqual(proof['new_requests'], 0)
        self.assertEqual(proof['source']['operation_sha256'], self.value['operation_sha256'])
        self.assertFalse((self.state/'vector-completions'/(self.current['operation_sha256']+'.json')).exists())
        p.require_administrative_budget(self.current, self.book.read())
        self.assertEqual(len(self.book.read()['requests']), 2)

    def test_modern_checkpoint_and_second_recipe_forward_the_original_paid_asset(self):
        stage = self.restore(); rows = self.book.read()['requests']
        link = {'request_count': len(rows), 'request_identity_prefix_sha256': request_identity(rows),
            'charged_microusd': sum(row['charged_microusd'] for row in rows)}
        receipt = self.current | {'consumed_checkpoints': [link]}
        path = self.root/'receipt.json'; atomic_json(path, receipt)
        atomic_json(self.state/'program-vector-inputs.json', {'packet': self.packet, 'vector_reused': False})
        with patch.object(p, 'modern_contract', return_value=self.current['operation_contract']), \
                patch.object(p, 'vector_packet', return_value=self.packet | {'retained_asset_eligible': True}):
            sealed = p.checkpoint_modern(path, self.state, root=self.root)
        accounting = sealed['vector_accounting']
        self.assertEqual(accounting['classification'], 'retained_completed_asset')
        self.assertEqual(accounting['retention'], stage)
        self.assertEqual(accounting['accounting_origin']['operation_sha256'], self.value['operation_sha256'])
        self.assertEqual(sealed['consumed_checkpoints'], [link])
        child = self.complete_candidate(self.current, accounting)
        self.new_operation(self.current | {'completed_candidate_id': child['candidate_id']}, child, 'd')
        self.assertEqual(self.current['retained_vector_source'], stage['source'])
        self.assertEqual(self.restore()['source'], stage['source'])

    def test_changed_corpus_configuration_clock_or_preprocessor_uses_no_old_asset(self):
        binding = spend.vector_binding(self.packet)
        for field in ('corpus_sha256', 'configuration_sha256', 'passage_count', 'clock', 'preprocessor'):
            with self.subTest(field=field):
                changed = deepcopy(binding); value = deepcopy(self.current)
                if field == 'clock': value['operation_contract']['tools/corpus_clock.mjs'] = 'f'*64
                elif field == 'preprocessor': changed['source_hashes']['tools/clock.py'] = 'f'*64
                else: changed[field] = 2 if field == 'passage_count' else 'f'*64
                self.assertIsNone(spend.retained_reconciliation_outputs(self.state, value, changed, self.root))
        self.assertEqual(self.book.path.read_bytes(), self.original_ledger)

    def test_tampered_context_completion_blob_manifest_or_ledger_fails_closed(self):
        pin = self.current['retained_vector_source']
        paths = [self.state/'retained-vector-contexts'/(pin['operation_sha256']+'.json'), self.sealed,
            self.state/'vector-outputs'/next(iter(self.hashes.values())), self.book.path,
            self.state/'complete-candidates'/pin['candidate_id']/'candidate.json']
        for path in paths:
            with self.subTest(path=path.name):
                original = path.read_bytes(); path.write_bytes(original+b' altered')
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    spend.prepare(self.state, self.packet)
                path.write_bytes(original)
        self.assertEqual(self.book.path.read_bytes(), self.original_ledger)

    def test_other_projection_kind_cannot_consume_primary_asset(self):
        changed = deepcopy(self.current); changed['projection_kind'] = 'document_facts'
        with self.assertRaisesRegex(ValueError, 'retained_primary_projection_kind'):
            spend.retained_reconciliation_outputs(self.state, changed, spend.vector_binding(self.packet), self.root)


if __name__ == '__main__':
    unittest.main()
