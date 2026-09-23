"""Catalog admission and irreversible execution; all generated responses are synthetic.

The optional retained-owner checks read private artifacts without changing their
constants or bytes. Portable mechanism fixtures deliberately use an empty,
synthetic predecessor and never represent a successful real catalog execution.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
import base64
import json
import os
import subprocess
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from tools import catalog_correction_executor as executor
from tools import catalog_correction_policy as policy
from tools import contextual_team_iteration3_continuation_policy as predecessor
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, encoded, identity


class Interrupted(BaseException):
    """A simulated process interruption, not a provider error or retry."""


class Synthetic:
    def __init__(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='catalog-unit-')))
        self.state = self.root/'s'; self.inputs = self.root/'i'
        self.inputs.mkdir()
        self.p = deepcopy(policy.plan())
        self.p['starting_checkpoint'].update(requests=0, events=0, native_counts=0,
            requests_sha256=identity([]), events_sha256=identity([]), native_counts_sha256=identity([]))
        for name, op in self.p['operations'].items():
            body = {'model': op['model'], 'input': [f'synthetic {name} {i}' for i in range(7)]}
            atomic_json(self.inputs/op['body_file'], body)
            op.update(body_sha256=identity(body), wire_sha256=executor.existing.sha(
                (self.inputs/op['body_file']).read_bytes()), input_tokens=len(encoded(body))+1024,
                row_inputs=[identity([name, i]) for i in range(7)] if name.startswith('embedding-') else [])
            op['maximum_microusd'] = (op['input_tokens']+(19 if name.endswith('rerank') else 49)) // (
                20 if name.endswith('rerank') else 50)
        self.p['maximum_microusd'] = sum(o['maximum_microusd'] for o in self.p['operations'].values())
        self.stack.enter_context(patch.object(policy, 'plan', return_value=self.p))
        self.stack.enter_context(patch.object(policy, 'PLAN_SHA', identity(self.p)))
        self.stack.enter_context(patch.object(predecessor, 'history'))
        self.stack.enter_context(patch.object(predecessor, 'counts', return_value=[]))
        # The real pooled caps are exercised separately against the immutable
        # retained owner. This fixture isolates the executor/atomic ledger seam.
        self.stack.enter_context(patch.object(policy.pool, 'check_pool'))
        # Production builder prefix gates have their own complete vector tests.
        # This fixture exercises the irreversible accounting/persistence seam.
        self.prefix = self.stack.enter_context(patch.object(executor, 'validate_vector_prefix'))
        self.stack.enter_context(patch.dict(os.environ, {
            'VOYAGE_API_KEY': 'synthetic-test-key', 'GITHUB_SHA': 'a'*40,
            'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_REPOSITORY': executor.existing.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_WORKFLOW_REF':
                executor.existing.REPOSITORY+'/'+executor.existing.WORKFLOW+'@refs/heads/main'}, clear=True))
        self.ledger = executor.existing.ExperimentLedger(self.state/'ledger.json', initialize=True)
        policy.install(self.state)

    def close(self):
        self.stack.close()

    def body(self, name='embedding-1'):
        return executor.input_body(self.inputs, name)

    def payload(self, name='embedding-1'):
        result = {'model': policy.operation(name)['model'], 'usage': {'total_tokens': 51}}
        vector = [1.0]+[0.0]*1023
        if name.startswith('embedding-'):
            result['data'] = [{'index': i, 'embedding': vector[:]} for i in range(len(self.body(name)['input']))]
        elif name == 'smoke-embed':
            result['embedding'] = vector
            result['latency_ms'] = 1.5
        else:
            result['latency_ms'] = 1.5
            result['rankings'] = [{'index': 0, 'passage_id': self.p['smoke_shared_passage_id'],
                'relevance_score': .75}]
        return result

    def response(self, name='embedding-1', payload=None):
        raw = encoded(payload if payload is not None else self.payload(name))
        response = Mock(status_code=200)
        response.iter_content.return_value = [raw]
        return response

    def runner(self, **kwargs):
        return executor.CatalogRunner(self.state, self.inputs, **kwargs)


class CatalogContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('No network in catalog contracts'))
        blocker.start(); cls.addClassCleanup(blocker.stop)

    def fixture(self):
        fixture = Synthetic(); self.addCleanup(fixture.close)
        return fixture

    def test_locked_plan_fixed_inventory_costs_and_native_zero(self):
        p = policy.plan()
        self.assertEqual(identity(p), policy.PLAN_SHA)
        self.assertEqual((len(p['operations']), p['native_counts']), (10, 0))
        self.assertLessEqual(p['maximum_microusd'], 34845)
        self.assertEqual(p['additional_allowance'], 0)
        self.assertEqual(p['automatic_retries'], 0)
        self.assertEqual(sum(len(op['row_inputs']) for op in p['operations'].values()), 1580)
        self.assertEqual(p['operations']['smoke-embed']['row_inputs'],
            [p['operations']['smoke-embed']['body_sha256']])
        for name in ('embedding-8', 'smoke-other', 'retry'):
            with self.subTest(name=name), self.assertRaises(ConfigurationFailure): policy.operation(name)
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'plan.json'
            altered = deepcopy(p); altered['maximum_microusd'] += 1; atomic_json(config, altered)
            with patch.object(policy, 'CONFIG', config), self.assertRaisesRegex(ConfigurationFailure, 'exact_plan'):
                policy.plan()

    def test_capacity_install_is_singleton_zero_allowance_and_idempotent(self):
        f = self.fixture(); before = (f.state/'ledger.json').read_bytes()
        policy.install(f.state)
        self.assertEqual(before, (f.state/'ledger.json').read_bytes())
        state = f.ledger.read()
        self.assertEqual(state['events'], [policy.scope_event()])
        self.assertEqual(state['requests'], [])
        self.assertEqual((state['limit_microusd'], state['max_requests']), (10000000, 690))
        self.assertEqual(policy.unique_input_limit(state), 4343)
        self.assertEqual(policy.scope_event()['row_input_capacity']['older_routes_total_ceiling'], 3840)
        self.assertEqual(policy.counts(f.state), [])

    def test_prepared_accepted_cache_reports_zero_new_spend_and_has_no_provider_credential(self):
        f = self.fixture()
        f.runner(post=Mock(return_value=f.response())).execute('embedding-1')
        ledger_before = (f.state/'ledger.json').read_bytes()
        destination = f.state.parent/'catalog-correction-inputs'
        f.inputs.rename(destination); f.inputs = destination
        args = SimpleNamespace(action='prepare', state=f.state,
            reservation=f.root/'reservation.json', result=f.root/'result.json')
        output = f.root/'github-output'
        with patch('tools.catalog_source_correction.prepare_inputs'), \
                patch.object(executor.existing, 'restore', return_value=f.ledger), \
                patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps({'catalog_correction': 'embedding-1'}),
                    'GITHUB_OUTPUT': str(output)}):
            executor.run(args)
            prepared = json.loads(args.reservation.read_bytes())
            self.assertTrue(prepared['cache_only'])
            self.assertEqual((prepared['maximum_new_microusd'], prepared['maximum_new_metered_attempts'],
                prepared['maximum_new_native_counts']), (0, 0, 0))
            self.assertIn('catalog_provider=cache\n', output.read_text())
            args.action = 'execute'
            executor.run(args)
        self.assertEqual((f.state/'ledger.json').read_bytes(), ledger_before)
        self.assertEqual(json.loads(args.result.read_bytes())['maximum_new_metered_attempts'], 0)

    def test_missing_duplicate_and_typed_event_tampering_fail_closed(self):
        f = self.fixture(); state = f.ledger.read()
        absent = deepcopy(state); absent['events'] = []
        with self.assertRaisesRegex(ConfigurationFailure, 'explicit_input_amendment'):
            policy.unique_input_limit(absent)
        for mutate in (lambda s: s['events'].append(deepcopy(s['events'][0])),
            lambda s: s['events'][0].update(additional_allowance=False),
            lambda s: s['events'][0]['row_input_capacity'].update(catalog_total_ceiling=5000)):
            altered = deepcopy(state); mutate(altered)
            with self.subTest(event=altered['events']), self.assertRaises(ConfigurationFailure):
                policy.history(altered)

    def test_exact_input_bytes_and_body_bound_cannot_be_reencoded_or_changed(self):
        f = self.fixture(); name = 'embedding-1'; target = f.inputs/policy.operation(name)['body_file']
        original = target.read_bytes()
        for altered in (original+b' ', encoded({'model': 'voyage-4-lite', 'input': ['changed']})):
            target.write_bytes(altered)
            with self.assertRaisesRegex(ConfigurationFailure, 'exact_input_bytes'):
                executor.input_body(f.inputs, name)
        target.write_bytes(original)
        self.assertEqual(identity(f.body()), policy.operation(name)['body_sha256'])

    def test_embedding_model_usage_dimensions_indices_and_finiteness(self):
        f = self.fixture(); original = f.payload()
        alterations = [lambda p: p.update(model='voyage-4-large'),
            lambda p: p.update(usage={'total_tokens': True}), lambda p: p.update(usage={}),
            lambda p: p['data'].pop(), lambda p: p['data'][1].update(index=0),
            lambda p: p['data'][0].update(index=False),
            lambda p: p['data'][0]['embedding'].pop(),
            lambda p: p['data'][0]['embedding'].__setitem__(0, float('nan')),
            lambda p: p['data'][0]['embedding'].__setitem__(0, True),
            lambda p: p['data'][0].update(embedding=[0.0]*1024)]
        for index, alter in enumerate(alterations):
            payload = deepcopy(original); alter(payload)
            with self.subTest(index=index), self.assertRaises(ConfigurationFailure):
                executor.validate_response('embedding-1', f.body(), payload)
        self.assertEqual(executor.usage(original, policy.operation('embedding-1')), ({'total_tokens': 51}, 2))
        self.assertEqual(executor.usage(f.payload('smoke-current-rerank'),
            policy.operation('smoke-current-rerank')), ({'total_tokens': 51}, 3))

    def test_smoke_ranking_requires_exact_shared_passage_and_finite_score(self):
        f = self.fixture(); name = 'smoke-current-rerank'
        for operation in ('smoke-embed', name, 'smoke-previous-rerank'):
            self.assertEqual(executor.validate_response(operation, f.body(operation), f.payload(operation)), f.payload(operation))
        for change in ({'passage_id': 'foreign'}, {'index': True}, {'index': 1},
            {'relevance_score': float('inf')}, {'relevance_score': False}, {'relevance_score': -1}):
            payload = f.payload(name); payload['rankings'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ConfigurationFailure):
                executor.validate_response(name, f.body(name), payload)

    def test_reservation_identity_and_order_before_dispatch(self):
        f = self.fixture(); post = Mock(side_effect=AssertionError('No dispatch for rejected admission'))
        with self.assertRaisesRegex(ConfigurationFailure, 'complete_accepted_predecessors'):
            f.runner(post=post).execute('embedding-2')
        op = policy.operation('embedding-1')
        for provider, supplied, amount, incoming, outgoing in (
            ('anthropic', policy.metadata('embedding-1'), op['maximum_microusd'], op['input_tokens'], 0),
            ('voyage', policy.metadata('embedding-1') | {'body_sha256': '0'*64}, op['maximum_microusd'], op['input_tokens'], 0),
            ('voyage', policy.metadata('embedding-1'), op['maximum_microusd']-1, op['input_tokens'], 0)):
            with self.assertRaises(ConfigurationFailure):
                policy.check_reservation(f.ledger.read(), provider, supplied, amount, incoming, outgoing)
        post.assert_not_called(); self.assertEqual(f.ledger.read()['requests'], [])

    def test_wrong_model_and_old_route_cannot_use_catalog_row_extension(self):
        f = self.fixture(); op = policy.operation('embedding-1')
        with self.assertRaisesRegex(ConfigurationFailure, 'outside_experiment_authority'):
            f.ledger.reserve_experiment('voyage', 'voyage-4-large', 2, policy.logical_key('embedding-1'),
                op['maximum_microusd'], 1, trusted_route=True, input_tokens=op['input_tokens'],
                output_tokens=0, execution_metadata=policy.metadata('embedding-1'))
        # Synthetic historical inventory isolates the older route's independent
        # guard. Its extra row is rejected before any historical paid admission.
        state = f.ledger.read(); state['requests'] = [{'key': 'synthetic-history',
            'row_inputs': [identity(i) for i in range(3840)]}]
        atomic_json(f.ledger.path, state)
        with self.assertRaisesRegex(Deferred, 'unique_embedding_inventory_exhausted'):
            f.ledger.reserve_experiment('voyage', 'voyage-4-lite', 2, 'new-legacy-key', 1, 1,
                trusted_route=True, input_tokens=1, output_tokens=0,
                execution_metadata={'purpose': 'embedding', 'row_inputs': ['new-legacy-input'],
                    'judge_items': [], 'body_sha256': '0'*64})
        self.assertEqual(len(f.ledger.read()['requests']), 1)

    def test_complete_budget_and_persistence_envelopes_precede_any_claim(self):
        f = self.fixture(); post = Mock(side_effect=AssertionError('No provider before complete admission'))
        for boundary in ('budget', 'persistence'):
            guard = patch.object(policy.pool, 'check_pool', side_effect=Deferred('synthetic pool exhausted')) if boundary == 'budget' else patch.object(executor.existing, 'STATE_LIMIT', 1)
            with self.subTest(boundary=boundary), guard, self.assertRaises(Deferred):
                f.runner(post=post).execute('embedding-1')
        self.assertEqual(f.ledger.read()['requests'], []); post.assert_not_called()

    def test_zero_provider_capacity_route_has_no_request_or_credential(self):
        f = self.fixture(); args = Mock(action='prepare', state=f.state,
            reservation=f.root/'reservation.json', result=f.root/'result.json')
        output = f.root/'output.txt'; before = f.ledger.path.read_bytes()
        with patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps({'catalog_capacity': policy.VERSION}),
            'GITHUB_OUTPUT': str(output), 'VOYAGE_API_KEY': ''}), \
            patch.object(executor.existing, 'restore', return_value=f.ledger), \
            patch.object(executor.requests, 'post', side_effect=AssertionError('Zero-provider route')):
            executor.run(args)
            args.action = 'execute'; executor.run(args)
        self.assertEqual(output.read_text(), 'text_provider=none\n')
        record = json.loads(args.result.read_bytes())
        self.assertTrue(all(record[k] == 0 for k in (
            'maximum_new_microusd', 'maximum_new_metered_attempts', 'maximum_new_native_counts')))
        self.assertEqual(f.ledger.path.read_bytes(), before)

    def test_success_cache_reuse_preserves_exact_bytes_and_charge_without_provider(self):
        f = self.fixture(); response = f.response(); post = Mock(return_value=response)
        runner = f.runner(post=post); result = runner.execute('embedding-1')
        before = (f.state/'ledger.json').read_bytes()
        self.assertEqual(runner.execute('embedding-1'), result)
        self.assertEqual(post.call_count, 1); response.close.assert_called_once()
        self.assertEqual(before, (f.state/'ledger.json').read_bytes())
        row = f.ledger.read()['requests'][0]
        self.assertEqual((row['status'], row['charged_microusd'], row['attempt']), ('valid', 2, 1))
        self.assertEqual(post.call_args.kwargs['timeout'], (10, 120))
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertEqual(post.call_args.kwargs['data'], (f.inputs/policy.operation('embedding-1')['body_file']).read_bytes())
        cp = json.loads((f.state/'checkpoint.json').read_bytes())
        self.assertEqual(cp['files']['ledger.json'], executor.existing.sha(before))
        self.assertNotIn('response_base64', json.loads((f.state/'diagnostics'/(row['id']+'.json')).read_bytes()))

    def test_cache_owner_and_usage_tampering_never_reissues(self):
        f = self.fixture(); post = Mock(return_value=f.response()); runner = f.runner(post=post)
        runner.execute('embedding-1'); cache = f.state/'cache'/(policy.logical_key('embedding-1')+'.json')
        original = json.loads(cache.read_bytes())
        for change in ({'request_id': '0'*32}, {'body_sha256': '0'*64}, {'model': 'voyage-4-large'},
            {'response_sha256': '0'*64}):
            atomic_json(cache, original | change)
            with self.subTest(change=change), self.assertRaises(ConfigurationFailure): runner.execute('embedding-1')
        payload = json.loads(original['response_text']); payload['usage']['total_tokens'] += 100
        changed = encoded(payload).decode(); atomic_json(cache, original | {
            'response_text': changed, 'response_sha256': executor.existing.sha(changed.encode())})
        with self.assertRaisesRegex(ConfigurationFailure, 'cache_usage_owner'): runner.execute('embedding-1')
        self.assertEqual(post.call_count, 1)

    def test_malformed_known_response_is_charged_failed_retained_and_not_replayed(self):
        f = self.fixture(); payload = f.payload(); payload['data'].pop()
        post = Mock(return_value=f.response(payload=payload)); runner = f.runner(post=post)
        with self.assertRaisesRegex(ConfigurationFailure, 'complete_owned_embedding_rows'): runner.execute('embedding-1')
        row = f.ledger.read()['requests'][0]
        self.assertEqual((row['status'], row['charged_microusd'], row['usage']), ('failed', 2, {'total_tokens': 51}))
        diagnostic = json.loads((f.state/'diagnostics'/(row['id']+'.json')).read_bytes())
        self.assertEqual(base64.b64decode(diagnostic['response_base64']), encoded(payload))
        with self.assertRaisesRegex(ConfigurationFailure, 'accepted_cache_required'): runner.execute('embedding-1')
        self.assertEqual(post.call_count, 1)

    def test_timeout_unknown_is_fully_held_and_blocks_other_operations(self):
        f = self.fixture(); post = Mock(side_effect=requests.ReadTimeout('synthetic'))
        with self.assertRaises(requests.ReadTimeout): f.runner(post=post).execute('embedding-1')
        row = f.ledger.read()['requests'][0]
        self.assertEqual((row['status'], row['usage'], row['charged_microusd']),
            ('reserved_unknown', None, policy.operation('embedding-1')['maximum_microusd']))
        for name in ('embedding-1', 'embedding-2'):
            with self.assertRaisesRegex(Deferred, 'new_uncertainty'): f.runner(post=post).execute(name)
        self.assertEqual(post.call_count, 1)

    def test_non_success_http_is_fully_held_and_never_replayed(self):
        f = self.fixture(); response = f.response(); response.status_code = 503
        post = Mock(return_value=response); runner = f.runner(post=post)
        with self.assertRaisesRegex(ConfigurationFailure, 'http_503'):
            runner.execute('embedding-1')
        row = f.ledger.read()['requests'][0]
        self.assertEqual((row['status'], row['charged_microusd'], row['usage']),
            ('reserved_unknown', policy.operation('embedding-1')['maximum_microusd'], None))
        with self.assertRaisesRegex(Deferred, 'new_uncertainty'):
            runner.execute('embedding-1')
        self.assertEqual(post.call_count, 1)

    def test_malformed_response_bytes_are_retained_without_json_escape_growth(self):
        f = self.fixture(); raw = b'\x00'*64
        response = Mock(status_code=200); response.iter_content.return_value = [raw]
        post = Mock(return_value=response)
        with self.assertRaises(ValueError): f.runner(post=post).execute('embedding-1')
        row = f.ledger.read()['requests'][0]
        diagnostic = json.loads((f.state/'diagnostics'/(row['id']+'.json')).read_bytes())
        self.assertEqual(base64.b64decode(diagnostic['response_base64']), raw)
        self.assertEqual(row['status'], 'reserved_unknown')
        with self.assertRaises(Deferred): f.runner(post=post).execute('embedding-1')
        self.assertEqual(post.call_count, 1)

    def test_escaped_cache_cannot_exceed_reserved_persistence_capacity(self):
        f = self.fixture(); payload = f.payload(); payload['extra'] = '"'*70000
        post = Mock(return_value=f.response(payload=payload))
        with patch.object(executor.existing, 'PACKET_LIMIT', 200000):
            with self.assertRaisesRegex(ConfigurationFailure, 'serialized_cache_capacity'):
                f.runner(post=post).execute('embedding-1')
        row = f.ledger.read()['requests'][0]
        self.assertEqual((row['status'], row['charged_microusd']), ('failed', 2))
        self.assertFalse((f.state/'cache'/(row['key']+'.json')).exists())
        self.assertEqual(post.call_count, 1)

    def test_accounting_overrun_preserved_and_blocks_new_claim(self):
        f = self.fixture(); payload = f.payload(); payload['usage']['total_tokens'] = 1000000
        post = Mock(return_value=f.response(payload=payload))
        with self.assertRaisesRegex(ValueError, 'receipt_exceeds'): f.runner(post=post).execute('embedding-1')
        state = f.ledger.read()
        self.assertEqual(state['requests'][0]['charged_microusd'], 20000)
        self.assertIn('reservation_overrun', state)
        with self.assertRaises(ConfigurationFailure): f.runner(post=post).execute('embedding-2')
        self.assertEqual(post.call_count, 1)

    def test_simultaneous_claims_dispatch_at_most_once(self):
        f = self.fixture(); entered = threading.Event(); release = threading.Event(); calls = []
        def post(*args, **kwargs):
            calls.append(1); entered.set(); self.assertTrue(release.wait(5)); return f.response()
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(f.runner(post=post).execute, 'embedding-1')
            self.assertTrue(entered.wait(5))
            try:
                second = workers.submit(f.runner(post=post).execute, 'embedding-1')
                with self.assertRaises(Deferred): second.result(timeout=5)
            finally: release.set()
            first.result(timeout=5)
        self.assertEqual(len(calls), 1); self.assertEqual(len(f.ledger.read()['requests']), 1)

    def test_interrupted_persistence_never_dispatches_a_claimed_request_again(self):
        for boundary in ('after_reserve', 'after_reservation_checkpoint', 'after_dispatch',
            'before_reconcile', 'after_reconcile', 'after_cache', 'after_receipt'):
            with self.subTest(boundary=boundary):
                f = Synthetic()
                try:
                    post = Mock(return_value=f.response())
                    def crash(point):
                        if point == boundary: raise Interrupted(point)
                    with self.assertRaises(Interrupted): f.runner(post=post, crash=crash).execute('embedding-1')
                    calls = post.call_count; row = f.ledger.read()['requests'][0]
                    cached = (f.state/'cache'/(policy.logical_key('embedding-1')+'.json')).exists()
                    receipt = f.state/'receipts'/(row['id']+'.json')
                    if receipt.exists():
                        self.assertEqual(json.loads(receipt.read_bytes())['status'], row['status'])
                    if row['status'] == 'valid' and cached:
                        self.assertEqual(f.runner(post=post).execute('embedding-1'), f.payload())
                        self.assertEqual(json.loads(receipt.read_bytes())['response_sha256'],
                            json.loads((f.state/'cache'/(policy.logical_key('embedding-1')+'.json')).read_bytes())['response_sha256'])
                    else:
                        with self.assertRaises((Deferred, OSError)): f.runner(post=post).execute('embedding-1')
                    self.assertEqual(post.call_count, calls)
                    self.assertEqual(len(f.ledger.read()['requests']), 1)
                finally: f.close()

    def test_release_prefix_rejection_is_charged_and_blocks_later_batches(self):
        f = self.fixture(); f.runner(post=Mock(return_value=f.response())).execute('embedding-1')
        changed = f.payload('embedding-2')
        f.prefix.side_effect = ConfigurationFailure('synthetic_release_prefix_rejected')
        post = Mock(return_value=f.response('embedding-2', changed))
        with self.assertRaisesRegex(ConfigurationFailure, 'release_prefix_rejected'):
            f.runner(post=post).execute('embedding-2')
        self.assertEqual(f.ledger.read()['requests'][-1]['status'], 'failed')
        with self.assertRaisesRegex(ConfigurationFailure, 'accepted_cache_required'):
            f.runner(post=post).execute('embedding-3')
        self.assertEqual(post.call_count, 1)

    def test_builder_process_failure_preserves_known_charge(self):
        f = self.fixture(); post = Mock(return_value=f.response())
        f.prefix.side_effect = subprocess.CalledProcessError(1, ['node', 'prefix-validator'])
        with self.assertRaises(subprocess.CalledProcessError):
            f.runner(post=post).execute('embedding-1')
        row = f.ledger.read()['requests'][0]
        self.assertEqual((row['status'], row['charged_microusd'], row['usage']),
            ('failed', 2, {'total_tokens': 51}))
        self.assertEqual(post.call_count, 1)


class RetainedOwnerAdmission(unittest.TestCase):
    """Optional private real-identity evidence; never installs or spends."""
    @classmethod
    def setUpClass(cls):
        default = policy.ROOT.parent/'contextual-team-demand-service/outputs/iteration3-20260923-continuation/runs/35903126571/state'
        raw = Path(os.environ.get('CATALOG_REAL_STATE', default)).resolve()
        cls.state = Path('\\\\?\\'+str(raw)) if os.name == 'nt' else raw
        if not cls.state.is_dir(): raise unittest.SkipTest('Private authenticated retained owner not present')

    def test_exact_actual_owner_fails_before_amendment_and_fits_only_explicit_event(self):
        raw = (self.state/'ledger.json').read_bytes(); cp = (self.state/'checkpoint.json').read_bytes()
        p = policy.plan(); state = json.loads(raw); start = p['starting_checkpoint']
        self.assertEqual(executor.existing.sha(raw), 'cf672248506662995aba1ad15fee151accaf87f75cc52e63cbd009c261fffe9e')
        self.assertEqual(executor.existing.sha(cp), '74ff04e649c5c807f21159cc3bf03afa606a6b6d66a153b152ab00267eca8eb0')
        self.assertEqual((len(state['requests']), len(state['events']), len(policy.counts(self.state))), (731, 73, 211))
        self.assertEqual(identity(state['requests']), start['requests_sha256'])
        self.assertEqual(identity(state['events']), start['events_sha256'])
        policy.history(state)
        with self.assertRaisesRegex(Deferred, 'complete_embedding_inventory'): policy.envelope(state)
        amended = deepcopy(state); amended['events'].append(policy.scope_event())
        self.assertEqual(policy.envelope(amended), {'maximum_microusd': p['maximum_microusd'], 'metered_attempts': 10, 'native_counts': 0})
        self.assertEqual(amended['requests'], state['requests'])
        self.assertEqual((amended['limit_microusd'], amended['max_requests']), (60000000, 1490))
        self.assertEqual((self.state/'ledger.json').read_bytes(), raw)
        self.assertEqual((self.state/'checkpoint.json').read_bytes(), cp)


if __name__ == '__main__':
    unittest.main()
