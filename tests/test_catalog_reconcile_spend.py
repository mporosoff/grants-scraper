"""Original-allowance vector bridge: synthetic transport, never HTTP/providers."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import catalog_reconcile_spend as spend
from tools.offline_spend import Deferred, Ledger, LinkedLedger, atomic_json, identity


class ReconcileSpendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.state = self.root / 'state'; self.parent = self.root / 'parent'
        self.state.mkdir(); self.parent.mkdir()
        self.book = Ledger(self.state / 'ledger.json', 'offline-123', 2, 300)
        token = self.book.reserve('anthropic', 'prior-model', 'prior-stage', 'prior-key', 30, 1)
        self.book.complete(token, status='complete', charged_microusd=25)
        self.original = self.book.read(); self.original_hash = identity(self.original)
        report = {'status': 'written', 'model': spend.MODEL, 'API_request_count': 1, 'usage_total_tokens': 51,
                  'API_requests': [{'model': spend.MODEL, 'usage_total_tokens': 51, 'http_status': 200,
                                    'request_id': 'a' * 32}]}
        raw = json.dumps(report).encode(); relative = 'evaluation/search_v2_hybrid_vector_build.json'
        path = self.parent / 'files' / relative; path.parent.mkdir(parents=True); path.write_bytes(raw)
        manifest = {'candidate_id': 'a' * 64, 'files': {relative: hashlib.sha256(raw).hexdigest()}}
        parent_raw = json.dumps(manifest).encode(); (self.parent / 'candidate.json').write_bytes(parent_raw)
        self.contract = {'parent_run': '123', 'parent_candidate_id': manifest['candidate_id'],
            'parent_manifest_sha256': hashlib.sha256(parent_raw).hexdigest(),
            'original_spend': {'ledger_sha256': self.original_hash}, 'operation_contract': {'safe-source': 'b' * 64}}
        self.contract['operation_sha256'] = identity(self.contract)
        atomic_json(self.state / 'reconciliation.json', self.contract)
        spend.import_history(self.state, self.parent, self.original_hash)

    def packet(self, text='Public scientific funding passage'):
        return {'url': spend.URL, 'body': json.dumps({'input': [text], 'model': spend.MODEL,
            'input_type': 'document', 'truncation': True, 'output_dimension': 1024, 'output_dtype': 'float'})}

    def finish_packet(self, reserved):
        return {'key': reserved['key'], 'token': reserved['token'], 'status': 200, 'request_id': 'c' * 32,
                'payload': {'model': spend.MODEL, 'data': [{'index': 0, 'embedding': [.125] * 1024}],
                            'usage': {'total_tokens': 51}}}

    def test_measured_history_import_is_once_and_preserves_exact_original_prefix(self):
        first = deepcopy(self.book.read())
        spend.import_history(self.state, self.parent, self.original_hash)
        self.assertEqual(self.book.read(), first)
        self.assertEqual(first['requests'][:len(self.original['requests'])], self.original['requests'])
        self.assertEqual(first['events'][:len(self.original['events'])], self.original['events'])
        self.assertEqual(first['requests'][-1]['charged_microusd'], 2)
        broken = deepcopy(first); broken['requests'][0]['charged_microusd'] = 0
        atomic_json(self.book.path, broken)
        with self.assertRaisesRegex(ValueError, 'original_ledger_prefix'):
            spend.import_history(self.state, self.parent, self.original_hash)

    def test_success_and_retry_reuse_one_validated_response_and_one_charge(self):
        packet = self.packet(); reserved = spend.reserve(self.state, packet)
        spend.finish(self.state, self.finish_packet(reserved))
        first = self.book.read(); result = spend.reserve(self.state, packet)
        self.assertEqual(result['status'], 'cached'); self.assertEqual(self.book.read(), first)
        self.assertEqual(first['requests'][-1]['charged_microusd'], 2)
        self.assertEqual(first['requests'][-1]['status'], 'valid')
        self.assertEqual(first['requests'][:len(self.original['requests'])], self.original['requests'])

    def test_accepted_cache_recovers_crash_before_completion_without_another_reservation(self):
        packet = self.packet(); reserved = spend.reserve(self.state, packet)
        with patch.object(spend, 'complete_saved', side_effect=RuntimeError('simulated interruption')):
            with self.assertRaisesRegex(RuntimeError, 'simulated interruption'):
                spend.finish(self.state, self.finish_packet(reserved))
        self.assertEqual(self.book.read()['requests'][-1]['status'], 'reserved_unknown')
        result = spend.reserve(self.state, packet)
        self.assertEqual(result['status'], 'cached')
        self.assertEqual(len(self.book.read()['requests']), 3)
        self.assertEqual(self.book.read()['requests'][-1]['charged_microusd'], 2)

    def test_unknown_dispatch_is_charged_and_concurrent_callers_cannot_redispatch(self):
        packet = self.packet()
        def attempt(_):
            try: return spend.reserve(self.state, packet)['status']
            except ValueError: return 'refused'
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(attempt, range(4)))
        self.assertEqual(outcomes.count('reserved'), 1)
        self.assertEqual(outcomes.count('refused'), 3)
        rows = self.book.read()['requests']; self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]['charged_microusd'], rows[-1]['reserved_microusd'])

    def test_budget_owner_limits_and_operation_contract_cannot_change(self):
        for field, value in (('logical_id', 'new-allowance'), ('limit_microusd', 3_000_000), ('max_requests', 301)):
            with self.subTest(field=field):
                original = self.book.read(); broken = dict(original, **{field: value}); atomic_json(self.book.path, broken)
                with self.assertRaisesRegex(ValueError, 'logical_budget_identity_mismatch'):
                    spend.reserve(self.state, self.packet())
                atomic_json(self.book.path, original)
        changed = deepcopy(self.contract); changed['operation_contract']['safe-source'] = 'd' * 64
        atomic_json(self.state / 'reconciliation.json', changed)
        with self.assertRaisesRegex(ValueError, 'operation_identity'):
            spend.reserve(self.state, self.packet())

    def test_invalid_transport_response_or_cache_stays_fail_closed(self):
        for change in (lambda p: p.update(url='https://other.example/'),
                       lambda p: p.update(body=p['body'].replace('document', 'query'))):
            packet = self.packet(); change(packet)
            with self.assertRaises(ValueError): spend.reserve(self.state, packet)
        reserved = spend.reserve(self.state, self.packet())
        for change in (lambda p: p.update(status=429), lambda p: p['payload'].update(model='other-model'),
                       lambda p: p['payload']['data'][0]['embedding'].__setitem__(0, float('nan')),
                       lambda p: p['payload']['data'][0].update(index=True),
                       lambda p: p['payload']['usage'].update(total_tokens=1000000)):
            packet = self.finish_packet(reserved); change(packet)
            with self.assertRaises(ValueError): spend.finish(self.state, packet)
        self.assertEqual(self.book.read()['requests'][-1]['status'], 'reserved_unknown')
        self.assertFalse((self.state / 'vector-responses').exists())

    def test_cache_binds_payload_body_operation_and_dispatch(self):
        packet = self.packet(); reserved = spend.reserve(self.state, packet)
        result = spend.finish(self.state, self.finish_packet(reserved)); path = Path(result['cache'])
        saved = json.loads(path.read_bytes())
        for field, value in (('token', 'wrong'), ('body_sha256', 'd' * 64), ('operation_sha256', 'e' * 64),
                             ('response_sha256', 'f' * 64)):
            with self.subTest(field=field):
                atomic_json(path, dict(saved, **{field: value}))
                with self.assertRaises(ValueError): spend.reserve(self.state, packet)
        atomic_json(path, saved)
        self.assertEqual(spend.reserve(self.state, self.packet('A genuinely new public passage'))['status'], 'reserved')

    def test_node_preload_uses_normal_transport_once_and_retains_no_secret_fields(self):
        source = r'''
import {pathToFileURL} from 'node:url';
process.env.CATALOG_RECONCILE_STATE=process.argv[1];process.env.PYTHON=process.argv[2];
let calls=0;globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({model:'voyage-4-lite',
data:[{index:0,embedding:Array(1024).fill(.125),unexpected:'raw-secret'}],usage:{total_tokens:51},api_key:'raw-secret'}),
{headers:{'request-id':'cccccccccccccccccccccccccccccccc',authorization:'raw-secret'}});};
await import(pathToFileURL(process.cwd()+'/tools/catalog_reconcile_vectors.mjs'));
const packet={method:'POST',body:JSON.stringify({input:['Public scientific funding passage'],model:'voyage-4-lite',input_type:'document',truncation:true,output_dimension:1024,output_dtype:'float'})};
const first=await fetch('https://api.voyageai.com/v1/embeddings',packet),a=await first.json();
const second=await fetch('https://api.voyageai.com/v1/embeddings',packet),b=await second.json();
console.log(JSON.stringify({calls,equal:JSON.stringify(a)===JSON.stringify(b),authorization:first.headers.get('authorization'),keys:Object.keys(a)}));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', source, str(self.state), sys.executable],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=True)
        value = json.loads(result.stdout)
        self.assertEqual(value, {'calls': 1, 'equal': True, 'authorization': None, 'keys': ['data', 'model', 'usage']})
        for path in self.state.rglob('*.json'):
            self.assertNotIn('raw-secret', path.read_text(encoding='utf-8'))

    def generation(self, mode='maintenance', task_limit=2):
        state = self.root / 'offline-123'; state.mkdir()
        book = Ledger(state / 'ledger.json', 'offline-123', 2, 300)
        document = book.reserve('anthropic', 'prior-model', 'documents', 'completed-document', 10, 1)
        book.complete(document, status='complete', charged_microusd=5)
        task = Ledger(state / 'task/ledger.json', 'qualification-task', task_limit, 300)
        contract = {'version': 'generation-vector-operation-1', 'parent_run': '123', 'mode': mode,
                    'operation_contract': {'corpus_sha256': 'd' * 64}}
        contract['operation_sha256'] = identity(contract)
        atomic_json(state / 'vector-operation.json', contract)
        return state, book, task

    def test_fresh_generation_uses_existing_local_book_without_history_import_or_reset(self):
        state, book, _ = self.generation(); original = deepcopy(book.read())
        with patch.object(spend, 'production_ledger', return_value=book):
            reserved = spend.reserve(state, self.packet(), generation=True)
            spend.finish(state, self.finish_packet(reserved), generation=True)
            self.assertEqual(spend.reserve(state, self.packet(), generation=True)['status'], 'cached')
        value = book.read()
        self.assertEqual(value['requests'][:1], original['requests'])
        self.assertEqual(value['events'], original['events'])
        self.assertEqual(len(value['requests']), 2)
        self.assertEqual(value['requests'][-1]['charged_microusd'], 2)

    def test_pilot_cache_recovers_between_linked_completions_without_extra_task_spending(self):
        state, book, task = self.generation('pilot'); linked = LinkedLedger(book, task)
        with patch.object(spend, 'production_ledger', return_value=linked):
            reserved = spend.reserve(state, self.packet(), generation=True)
            original_complete = book.complete
            def interrupt(token, **kwargs):
                if kwargs.get('status') == 'valid': raise RuntimeError('after task completion')
                original_complete(token, **kwargs)
            with patch.object(book, 'complete', side_effect=interrupt):
                with self.assertRaisesRegex(RuntimeError, 'after task completion'):
                    spend.finish(state, self.finish_packet(reserved), generation=True)
            self.assertEqual(task.read()['requests'][0]['status'], 'valid')
            self.assertEqual(book.read()['requests'][-1]['status'], 'reserved_unknown')
            self.assertEqual(spend.reserve(state, self.packet(), generation=True)['status'], 'cached')
        self.assertEqual(len(task.read()['requests']), 1)
        self.assertEqual(task.read()['requests'][0]['charged_microusd'], 2)
        self.assertEqual(book.read()['requests'][-1]['charged_microusd'], 2)

    def test_pilot_task_limit_blocks_before_http_and_keeps_prior_document_charge(self):
        state, book, task = self.generation('pilot', task_limit=0)
        with patch.object(spend, 'production_ledger', return_value=LinkedLedger(book, task)):
            with self.assertRaises(Deferred): spend.reserve(state, self.packet(), generation=True)
        self.assertEqual(task.read()['requests'], [])
        self.assertEqual(book.read()['requests'][0]['charged_microusd'], 5)
        self.assertEqual(book.read()['requests'][-1]['status'], 'not_dispatched_task_limit')
        self.assertEqual(book.read()['requests'][-1]['charged_microusd'], 0)

    def test_generation_checkpoint_reuses_exact_outputs_and_changed_inputs_keep_same_allowance(self):
        state, book, _ = self.generation()
        root = Path(spend.__file__).resolve().parents[1]
        inputs = ('tools/catalog_reconcile_spend.py',)
        packet = {'run_id': '123', 'mode': 'maintenance', 'corpus_sha256': 'd' * 64,
                  'configuration_sha256': 'e' * 64, 'passage_count': 1,
                  'source_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}}
        original = deepcopy(book.read())
        with patch.object(spend, 'GENERATION_INPUTS', inputs), patch.dict('os.environ', GITHUB_RUN_ID='123'), \
                patch.object(spend, 'production_ledger', return_value=book):
            prepared = spend.prepare(state, packet, generation=True)
            self.assertEqual(prepared['status'], 'prepared')
            outputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in spend.VECTOR_OUTPUTS}
            spend.checkpoint(state, {'operation_sha256': prepared['operation_sha256'], 'outputs': outputs}, generation=True)
            self.assertEqual(spend.prepare(state, packet, generation=True)['status'], 'complete')
            changed = dict(packet, corpus_sha256='f' * 64)
            self.assertEqual(spend.prepare(state, changed, generation=True)['status'], 'prepared')
        self.assertEqual(book.read(), original)

    def changed_operation(self):
        contract = deepcopy(self.contract)
        contract['operation_contract']['safe-source'] = 'e' * 64
        contract.pop('operation_sha256')
        contract['operation_sha256'] = identity(contract)
        atomic_json(self.state / 'reconciliation.json', contract)

    def test_vector_history_and_completion_use_canonical_summary_usage(self):
        reserved = spend.reserve(self.state, self.packet())
        completed = spend.finish(self.state, self.finish_packet(reserved))
        saved = json.loads(Path(completed['cache']).read_bytes())
        self.assertEqual(saved['payload']['usage'], {'total_tokens': 51})
        summary = self.book.summary()['by_provider_model_stage']
        for stage in ('historical_vector_generation', 'reconciled_vectors'):
            group = summary['voyage/voyage-4-lite/' + stage]
            self.assertEqual(group['valid_completions'], 1)
            self.assertEqual(group['failures'], 0)
            self.assertEqual(group['input_tokens'], 51)
            self.assertEqual(group['output_tokens'], 0)
            self.assertEqual(group['charged_microusd'], 2)

    def test_protected_whole_asset_requires_exact_semantics_outputs_and_corpus(self):
        from tools import release_candidate as c
        root = self.root / 'protected'; root.mkdir()
        packet = {'retained_asset_eligible': True, 'corpus_sha256': 'd' * 64,
                  'configuration_sha256': 'e' * 64, 'passage_count': 1}
        for name in spend.VECTOR_OUTPUTS:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(json.dumps(dict(packet, reuse_permitted=False)).encode())
        outputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in spend.VECTOR_OUTPUTS}
        semantic = {'files': {'vector-code': 'a' * 64}, 'fingerprint': 'b' * 64}
        manifest = {'files': outputs, 'generation_sha': 'f' * 40, 'dependency_groups': {'semantic': semantic}}
        manifest['candidate_id'] = c.digest(c.encoded(manifest))
        receipt = {'candidate_id': manifest['candidate_id'], 'generation_sha': manifest['generation_sha'],
                   'identity': {'candidate_id': manifest['candidate_id'], 'candidate_hashes': outputs},
                   'gates': {gate: 'passed' for gate in c.GATES}}
        protected = {'release/candidate.json': manifest, 'release/validation.json': receipt,
                     'release/candidate-source.json': {'candidate_id': manifest['candidate_id']}}
        def git_read(command, **kwargs):
            return json.dumps(protected[command[-1].removeprefix('HEAD:')]).encode()
        before = {name: (root / name).read_bytes() for name in spend.VECTOR_OUTPUTS}
        with patch.object(spend.subprocess, 'check_output', side_effect=git_read), \
                patch('tools.release_dependencies.snapshot', return_value={'semantic': semantic}) as snapshot:
            result = spend.protected_vector_asset(root, packet)
            self.assertEqual(result['outputs'], outputs)
            self.assertEqual(result['protected_candidate_id'], manifest['candidate_id'])
            self.assertIsNone(spend.protected_vector_asset(root, dict(packet, retained_asset_eligible=False)))
            for field, value in (('corpus_sha256', 'c' * 64), ('configuration_sha256', 'c' * 64), ('passage_count', 2)):
                self.assertIsNone(spend.protected_vector_asset(root, dict(packet, **{field: value})))
            snapshot.return_value = {'semantic': dict(semantic, fingerprint='c' * 64)}
            self.assertIsNone(spend.protected_vector_asset(root, packet))
            snapshot.return_value = {'semantic': semantic}
            receipt['gates']['scoring'] = 'failed'
            with self.assertRaisesRegex(ValueError, 'protected_vector_provenance'):
                spend.protected_vector_asset(root, packet)
            receipt['gates']['scoring'] = 'passed'
            (root / spend.VECTOR_OUTPUTS[-1]).write_bytes(b'changed receipt')
            self.assertIsNone(spend.protected_vector_asset(root, packet))
        for name in spend.VECTOR_OUTPUTS[:-1]:
            self.assertEqual((root / name).read_bytes(), before[name])

    def test_generation_retains_complete_asset_without_reservation_or_rewriting_vector_receipts(self):
        state, book, _ = self.generation()
        root = Path(spend.__file__).resolve().parents[1]
        inputs = ('tools/catalog_reconcile_spend.py',)
        outputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in spend.VECTOR_OUTPUTS}
        packet = {'run_id': '123', 'mode': 'maintenance', 'corpus_sha256': 'd' * 64,
                  'configuration_sha256': 'e' * 64, 'passage_count': 1, 'retained_asset_eligible': True,
                  'source_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}}
        before = deepcopy(book.read())
        with patch.object(spend, 'GENERATION_INPUTS', inputs), patch.dict('os.environ', GITHUB_RUN_ID='123'), \
                patch.object(spend, 'production_ledger', return_value=book), \
                patch.object(spend, 'protected_vector_asset', return_value={'outputs': outputs,
                    'protected_candidate_id': 'a' * 64, 'semantic_fingerprint': 'b' * 64}):
            result = spend.prepare(state, packet, generation=True)
        self.assertEqual(result['status'], 'complete'); self.assertEqual(result['new_requests'], 0)
        receipt = json.loads((state / 'vector-stage.json').read_bytes())
        self.assertEqual(receipt['new_requests'], 0); self.assertEqual(receipt['new_usage_total_tokens'], 0)
        self.assertEqual(receipt['status'], 'retained_complete_asset')
        self.assertEqual(book.read(), before)
        self.assertEqual({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in spend.VECTOR_OUTPUTS}, outputs)

    def test_changed_operation_cannot_hide_an_unknown_identical_body(self):
        spend.reserve(self.state, self.packet())
        original = deepcopy(self.book.read()); self.changed_operation()
        with self.assertRaisesRegex(ValueError, 'previous_operation_dispatch_unknown_no_retry'):
            spend.reserve(self.state, self.packet())
        self.assertEqual(self.book.read(), original)

    def test_old_accepted_cache_recovers_accounting_without_mixing_its_vectors_into_new_operation(self):
        reserved = spend.reserve(self.state, self.packet())
        with patch.object(spend, 'complete_saved', side_effect=RuntimeError('interruption')):
            with self.assertRaises(RuntimeError): spend.finish(self.state, self.finish_packet(reserved))
        self.changed_operation()
        with self.assertRaisesRegex(Deferred, 'previous_operation_response_recovered_retry_generation'):
            spend.reserve(self.state, self.packet())
        self.assertEqual(len(self.book.read()['requests']), 3)
        self.assertEqual(self.book.read()['requests'][-1]['status'], 'valid')


if __name__ == '__main__':
    unittest.main()
