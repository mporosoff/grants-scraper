"""Finite I3 policy against the real shared ledger machinery; no providers."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_contextual_team_iteration3_capacity as capacity_fixture
from tools import contextual_team_iteration3_policy as policy
from tools import contextual_team_completion_policy as pool
from tools import contextual_team_checkpoint_disposition as disposition
from tools import contextual_team_policy as dispatch
from tools import contextual_team_token_preflight as tokens
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred

REAL_PLAN = policy.plan
REAL_CURRENTNESS = policy.source_currentness


class Iteration3Policy(unittest.TestCase):
    def bind(self, item):
        result = item.start(); self.addCleanup(item.stop); return result

    def setUp(self):
        self.fixture = capacity_fixture.Capacity('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.path
        state = copy.deepcopy(self.fixture.original); repairs = {}
        for row in state['requests'][pool.plan()['starting_checkpoint']['requests']:]:
            row.setdefault('key', identity(['retained', row['id']]))
            row.setdefault('stage', 2)
        for index, (purpose, original_purpose) in enumerate(policy.REPAIRS.items()):
            body = {'original': purpose}; request_id = 'retained-failed-'+str(index)
            row = {'id': request_id, 'purpose': original_purpose, 'status': 'failed',
                'provider': 'openai' if index == 0 else 'anthropic', 'body_sha256': identity(body),
                'key': identity(['failed', request_id]), 'stage': 2,
                'charged_microusd': 1000, 'usage': {'input_tokens': 100, 'output_tokens': 10}}
            state['requests'][-1-index] = row
            receipt = {'request_id': request_id, 'status': 'failed', 'usage': row['usage']}
            diagnostic = {'request_id': request_id, 'body_sha256': identity(body), 'diagnosis': 'synthetic invalid evidence'}
            for folder, value in (('receipts', receipt), ('diagnostics', diagnostic)):
                atomic_json(self.path/folder/(request_id+'.json'), value)
            repairs[purpose] = {'request_id': request_id, 'request_sha256': identity(row), 'body_sha256': identity(body),
                'receipt_sha256': existing.sha((self.path/'receipts'/(request_id+'.json')).read_bytes()),
                'diagnostic_sha256': existing.sha((self.path/'diagnostics'/(request_id+'.json')).read_bytes())}
        atomic_json(self.path/'ledger.json', state)
        saved = json.loads((self.path/'checkpoint.json').read_bytes())['phase2_token_preflight']
        for row in saved['rows'][pool.plan()['starting_checkpoint']['native_counts']:]:
            row.setdefault('key', identity(['retained-count', row['id']]))
        existing.checkpoint(self.path, token_preflight=saved)
        cp = json.loads((self.path/'checkpoint.json').read_bytes()); source = self.fixture.p['source']
        source.update(ledger_sha256=existing.sha((self.path/'ledger.json').read_bytes()),
            checkpoint_sha256=existing.sha((self.path/'checkpoint.json').read_bytes()),
            native_counts_sha256=identity(saved['rows']),
            requests_sha256=identity(state['requests']), checkpoint_files=len(cp['files']), checkpoint_files_sha256=identity(cp['files']))
        ledger = self.fixture.install(); state = ledger.read()
        cp = json.loads((self.path/'checkpoint.json').read_bytes())
        self.before = {p.relative_to(self.path).as_posix(): p.read_bytes() for p in self.path.rglob('*.json')}
        self.original = copy.deepcopy(state)
        self.p = {'version': policy.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
            'scope_ids': list(policy.SCOPE_IDS), 'build_scope_ids': list(policy.BUILD_STAGES), 'first_scope_id': '332894',
            'operations': policy.expected_operations(),
            'stages': {k: {'provider': v[0], 'model': v[1], 'output_tokens': v[2]} for k, v in policy.STAGES.items()},
            'input_token_ceilings': {stage: 180000 for stage in policy.STAGES},
            'source_inputs_sha256': 'a'*64, 'source_receipts_sha256': 'b'*64,
            'maximum_wire_bytes': 524288, 'maximum_graph_bytes': 393216,
            'max_requests': 9, 'max_native_counts': 8, 'repairs': repairs,
            'no_second_allowance': True, 'public_activation': False, 'recurring_paid_usage': False, 'paid_builds_enabled': False,
            'starting_checkpoint': {'requests': len(state['requests']), 'requests_sha256': identity(state['requests']),
                'events': len(state['events']), 'events_sha256': identity(state['events']),
                'native_counts': len(cp['phase2_token_preflight']['rows']), 'native_counts_sha256': identity(cp['phase2_token_preflight']['rows']),
                'ledger_sha256': existing.sha(self.before['ledger.json']), 'checkpoint_sha256': existing.sha(self.before['checkpoint.json']),
                'checkpoint_files': len(cp['files']), 'checkpoint_files_sha256': identity(cp['files']),
                'run': {'id': 35760388493, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success'}}}
        self.p['release_id'] = identity(self.p)
        self.bind(patch.object(policy, 'plan', return_value=self.p))
        self.bind(patch.object(policy, 'source_currentness', return_value={}))
        self.active = []; self.terminal = 'completed'

    def api(self, path):
        return encoded({'workflow_runs': self.active, 'total_count': len(self.active)} if '?status=' in path else
            self.p['starting_checkpoint']['run'] | {'status': self.terminal})

    def install(self, **kwargs):
        return policy.install_authority(self.path, self.api, **kwargs)

    def packet(self, scope='332894', stage='integrity'):
        provider, model, output = policy.STAGES[stage]
        body = {'model': model, 'messages': [{'role': 'user', 'content': 'Exact complete synthetic evidence'}],
            'thinking': {'type': 'disabled'}, 'max_tokens': output} if provider == 'anthropic' else {
            'model': model, 'input': 'Exact complete synthetic evidence', 'reasoning': {'effort': 'low'}, 'max_output_tokens': output}
        return policy.operation(scope, stage), body, {'version': 'synthetic-strict-contract-v1'}, identity(['complete', scope, stage])

    def bind_packet(self, ledger, scope='332894', stage='integrity'):
        purpose, body, contract, input_id = self.packet(scope, stage)
        metadata = policy.bind_operation(ledger, purpose, body, contract, input_id)
        return purpose, body, metadata | {'purpose': purpose, 'body_sha256': identity(body)}

    def native(self, purpose, body, *, status='complete'):
        cp = json.loads((self.path/'checkpoint.json').read_bytes()); saved = cp['phase2_token_preflight']
        saved['rows'].append({'id': purpose, 'key': identity(tokens.count_projection(body)),
            'status': status, 'input_tokens': 1000, 'metered_inference': False, 'charged_microusd': 0})
        existing.checkpoint(self.path, token_preflight=saved)

    def test_authority_has_exactly_nine_operations_and_no_generation_expansion(self):
        self.assertEqual(len(policy.expected_operations()), 9)
        self.assertEqual(sum(o['provider'] == 'anthropic' for o in policy.expected_operations()), 8)
        for scope, stage in (('363268', 'interpret'), ('363268', 'query'), ('351715', 'assess'),
                ('341997', 'check'), ('344592:ab-0025', 'integrity'), ('332894', 'assess')):
            with self.subTest(scope=scope, stage=stage), self.assertRaises(ConfigurationFailure): policy.operation(scope, stage)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); target = root/'config/contextual_team'; target.mkdir(parents=True)
            value = copy.deepcopy(self.p)
            for name, key in (('iteration3-source-inputs-v1.json', 'source_inputs_sha256'),
                              ('iteration3-source-receipts-v1.json', 'source_receipts_sha256')):
                raw = encoded({'synthetic_source': name}); (target/name).write_bytes(raw); value[key] = existing.sha(raw)
            # Fixture histories use exact original accounting mechanics but their
            # compact event count differs; the production inventory stays fixed.
            value['starting_checkpoint'].update(requests=718, native_counts=200, events=56)
            def write():
                value['release_id'] = identity({k: v for k, v in value.items() if k != 'release_id'})
                atomic_json(target/'iteration3-authority-v1.json', value)
            write()
            with patch.object(policy, 'ROOT', root):
                self.assertEqual(REAL_PLAN(), value)
                value['operations'].append(value['operations'][0]); write()
                with self.assertRaises(ConfigurationFailure): REAL_PLAN()

    def test_install_preserves_all_history_holds_and_is_byte_idempotent(self):
        ledger = self.install(); state = ledger.read(); first = (self.path/'ledger.json').read_bytes()
        self.install(); self.assertEqual(first, (self.path/'ledger.json').read_bytes())
        self.assertEqual(state['requests'], self.original['requests'])
        self.assertEqual(state['events'][:-1], self.original['events'])
        self.assertEqual(state['events'][-1], policy.event())
        self.assertEqual((ledger.limit, ledger.max_requests), (60000000, 1490))
        self.assertEqual(disposition.exposure(state), {'microusd': 713400, 'attempts': 4, 'native_counts': 1})
        for name, raw in self.before.items():
            if name not in ('ledger.json', 'checkpoint.json'): self.assertEqual((self.path/name).read_bytes(), raw)

    def test_authenticated_owner_and_atomic_interruption(self):
        self.active = [{'id': 100}]
        with self.assertRaises(Deferred): self.install()
        self.active = []; self.terminal = 'in_progress'
        with self.assertRaises(Deferred): self.install()
        self.terminal = 'completed'
        def crash(point):
            if point == 'after_atomic_write': raise SystemExit('fixture termination')
        with self.assertRaises(SystemExit): self.install(crash=crash)
        self.assertEqual((self.path/'checkpoint.json').read_bytes(), self.before['checkpoint.json'])
        self.install(); policy.history(json.loads((self.path/'ledger.json').read_bytes()))
        self.assertEqual(len(json.loads((self.path/'ledger.json').read_bytes())['events']), len(self.original['events'])+1)

    def test_history_capacity_repair_and_typed_event_tampering_rejected(self):
        state = self.install().read()
        for mutation in ('prefix', 'duplicate', 'boolean', 'position', 'remove-capacity'):
            changed = copy.deepcopy(state)
            if mutation == 'prefix': changed['requests'][-1]['charged_microusd'] += 1
            elif mutation == 'duplicate': changed['events'].append(policy.event())
            elif mutation == 'boolean': changed['events'][-1]['additional_allowance'] = False
            elif mutation == 'position': changed['events'].insert(-1, {'kind': 'other'})
            else: changed['events'] = [e for e in changed['events'] if e.get('authority') != policy.capacity.VERSION]
            with self.subTest(mutation=mutation), self.assertRaises(ConfigurationFailure): policy.history(changed)
        repair = next(iter(self.p['repairs'].values()))
        (self.path/'receipts'/(repair['request_id']+'.json')).write_bytes(b'{}')
        with self.assertRaises(ConfigurationFailure): policy.prepare_record(self.path, {'scope_id': '332894', 'job_id': 'fixture'})

    def test_exact_operation_is_concurrent_idempotent_and_never_rekeyed(self):
        ledger = self.install(); args = self.packet()
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(*list(workers.map(lambda _: policy.bind_operation(ledger, *args), range(2))))
        self.assertEqual(len(policy._operation_events(ledger.read())), 1)
        purpose, body, contract, input_id = args
        with self.assertRaises(Deferred): policy.bind_operation(ledger, purpose, body | {'system': 'changed'}, contract, input_id)
        for key, value in (('model', 'different'), ('thinking', {'type': 'enabled'}), ('max_tokens', True)):
            with self.assertRaises(ConfigurationFailure): policy.packet_event(purpose, body | {key: value}, contract, input_id)

    def test_failed_original_body_and_original_evidence_never_replayed(self):
        ledger = self.install(); purpose, body, contract, input_id = self.packet('363268', 'assess')
        self.p['repairs'][purpose]['body_sha256'] = identity(body)
        with self.assertRaisesRegex(Deferred, 'unchanged_failed_body'): policy.packet_event(purpose, body, contract, input_id)
        self.assertEqual(ledger.read()['requests'], self.original['requests'])

    def test_native_exact_operation_uncertainty_and_foreign_rows_stop(self):
        ledger = self.install(); purpose, body, _ = self.bind_packet(ledger)
        self.native(purpose, body); self.assertEqual(len(policy.check_counts(self.path)), self.p['starting_checkpoint']['native_counts']+1)
        original = (self.path/'checkpoint.json').read_bytes()
        for mutation in ('unknown', 'foreign', 'duplicate', 'key', 'boolean'):
            cp = json.loads(original); row = cp['phase2_token_preflight']['rows'][-1]
            if mutation == 'unknown': row['status'] = 'dispatched_or_uncertain'
            elif mutation == 'foreign': row['id'] = policy.PREFIX+'363268:interpret'
            elif mutation == 'duplicate': cp['phase2_token_preflight']['rows'].append(copy.deepcopy(row))
            elif mutation == 'key': row['key'] = 'f'*64
            else: row['charged_microusd'] = False
            atomic_json(self.path/'checkpoint.json', cp)
            with self.subTest(mutation=mutation), self.assertRaises((ConfigurationFailure, Deferred)):
                policy.bind_operation(ledger, *self.packet())
        (self.path/'checkpoint.json').write_bytes(original)

    def test_direct_counter_requires_bound_operation_before_cache_or_claim(self):
        ledger = self.install(); purpose, body, _ = self.bind_packet(ledger)
        self.native(purpose, body)
        def forbidden(*args, **kwargs): raise AssertionError('Unexpected native request')
        counter = tokens.Counter(self.path, post=forbidden)
        self.assertEqual(counter.count({'id': purpose, 'body': body}), 1000)
        for bad in (policy.PREFIX+'363268:interpret', policy.operation('363268', 'verify')):
            with self.assertRaises(ConfigurationFailure): counter.count({'id': bad, 'body': body})
        with self.assertRaises(ConfigurationFailure): counter.count({'id': purpose, 'body': body | {'system': 'changed evidence'}})
        cp = json.loads((self.path/'checkpoint.json').read_bytes())
        cp['phase2_token_preflight']['rows'].append({'id': policy.operation('363268', 'verify'),
            'key': 'f'*64, 'status': 'dispatched_or_uncertain', 'metered_inference': False, 'charged_microusd': 0})
        atomic_json(self.path/'checkpoint.json', cp)
        with self.assertRaisesRegex(Deferred, 'native_uncertainty'): counter.count({'id': purpose, 'body': body})

    def test_direct_counter_checks_expiry_and_full_envelope_immediately_before_claim(self):
        ledger = self.install(); purpose, body, _ = self.bind_packet(ledger)
        before = (self.path/'checkpoint.json').read_bytes()
        def forbidden(*args, **kwargs): raise AssertionError('Unexpected native request')
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture-only'}):
            with patch.object(policy, 'source_currentness', side_effect=Deferred('fixture expired source')):
                with self.assertRaisesRegex(Deferred, 'expired'): tokens.Counter(self.path, post=forbidden).count({'id': purpose, 'body': body})
            with patch.object(policy, 'finite_envelope', side_effect=Deferred('fixture full envelope unavailable')):
                with self.assertRaisesRegex(Deferred, 'envelope'): tokens.Counter(self.path, post=forbidden).count({'id': purpose, 'body': body})
        self.assertEqual((self.path/'checkpoint.json').read_bytes(), before)

    def test_valid_direct_counter_has_one_attempt_and_exact_guarded_cache(self):
        import test_contextual_team_luna_repair as responses
        ledger = self.install(); purpose, body, _ = self.bind_packet(ledger); calls = []
        def post(*args, **kwargs):
            calls.append(kwargs['json']); return responses.Response({'input_tokens': 321})
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'fixture-only'}):
            counter = tokens.Counter(self.path, post=post)
            self.assertEqual(counter.count({'id': purpose, 'body': body}), 321)
            with patch.object(policy, 'source_currentness', side_effect=AssertionError('Expired source cannot prevent a read-only count cache')):
                self.assertEqual(counter.count({'id': purpose, 'body': body}), 321)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(policy.check_counts(self.path)), self.p['starting_checkpoint']['native_counts']+1)
        self.assertEqual(ledger.read()['requests'], self.original['requests'])

    def test_reservation_routes_exact_native_cost_metadata_and_no_replay(self):
        ledger = self.install(); purpose, body, meta = self.bind_packet(ledger)
        self.native(purpose, body); key = identity(tokens.count_projection(body)); n = 2224
        meta |= {'native_input_tokens': 1000, 'native_count_key': key, 'count_body_sha256': key}
        cost = n*2 + 120000
        dispatch.check_reservation(ledger.read(), 'anthropic', meta, cost, n, 12000)
        for changed, amount in (({'body_sha256': 'd'*64}, cost), ({'native_count_key': 'e'*64}, cost), ({}, cost-1)):
            with self.assertRaises(ConfigurationFailure): policy.check_reservation(ledger.read(), 'anthropic', meta | changed, amount, n, 12000)
        token = ledger.reserve_experiment('anthropic', 'claude-sonnet-5', 2, identity(['new-request']), cost, 1,
            trusted_route=True, input_tokens=n, output_tokens=12000, execution_metadata=meta)
        with self.assertRaisesRegex(Deferred, 'new_uncertainty'): policy.history(ledger.read())
        ledger.reconcile(token, cost_usd='0.003', usage={'input_tokens': 1000, 'output_tokens': 100}, status='valid')
        policy.history(ledger.read())
        with self.assertRaisesRegex(Deferred, 'already_claimed'): policy.check_reservation(ledger.read(), 'anthropic', meta, cost, n, 12000)

    def test_luna_allowed_but_voyage_and_different_models_are_not(self):
        ledger = self.install(); purpose, body, meta = self.bind_packet(ledger, '363268', 'assess')
        for provider, model in (('voyage', 'voyage-4-large'), ('openai', 'gpt-5.6-sol')):
            with self.assertRaises(ConfigurationFailure):
                ledger.reserve_experiment(provider, model, 2, identity([provider]), 30000, 1,
                    trusted_route=True, input_tokens=1000, output_tokens=24000, execution_metadata=meta)
        token = ledger.reserve_experiment('openai', 'gpt-5.6-luna', 2, identity(['luna']), 29000, 1,
            trusted_route=True, input_tokens=1000, output_tokens=24000, execution_metadata=meta)
        self.assertEqual(ledger.read()['requests'][-1]['id'], token)
        self.assertEqual(ledger.read()['requests'][-1]['repair_of'], self.p['repairs'][purpose]['request_id'])

    def test_complete_workflow_envelopes_and_protected_caps(self):
        ledger = self.install(); state = ledger.read()
        for scope, mode, requests, counts, cost in (('363268', 'build', 3, 2, 1144800),
                ('332894', 'build', 1, 1, 480000), ('344592:ab-0025', 'check', 1, 1, 480000)):
            record = policy.prepare_record(self.path, {'scope_id': scope, 'job_id': 'fixture', 'operation': mode})
            self.assertEqual((record['maximum_new_metered_attempts'], record['maximum_new_native_counts'], record['maximum_new_microusd']), (requests, counts, cost))
            self.assertEqual(record['original_additional_allowance'], {'microusd': 50000000, 'attempts': 800, 'native_counts': 400})
            self.assertEqual({k: record['remaining_finite_inventory_envelope'][k] for k in ('microusd', 'attempts', 'native_counts')},
                {'microusd': 4024800, 'attempts': 9, 'native_counts': 8})
        base = pool.effective_plan(state)
        for constraint in ('dollars', 'attempts', 'counts', 'lifetime-counts'):
            p = copy.deepcopy(base)
            if constraint == 'dollars': p['additional']['microusd'] = 713400 + 31000 + 5000000 + 1144799
            elif constraint == 'attempts': p['additional']['attempts'] = len(state['requests']) - p['starting_checkpoint']['requests'] + 4 + 2
            elif constraint == 'counts': p['additional']['native_counts'] = len(self.fixture.rows) - p['starting_checkpoint']['native_counts'] + 1 + 1
            else: p['lifetime']['native_counts'] = len(self.fixture.rows) + 1 + 1
            with self.subTest(constraint=constraint), patch.object(pool, 'effective_plan', return_value=p), self.assertRaises(Deferred):
                policy.prepare_record(self.path, {'scope_id': '363268', 'job_id': 'fixture'})
        with self.assertRaises(ConfigurationFailure): policy.prepare_record(self.path, {'scope_id': '344592:ab-0025', 'job_id': 'fixture'})

    def test_exact_current_source_receipts_and_expiry_do_not_rewrite_science(self):
        with patch.object(policy, 'plan', side_effect=REAL_PLAN):
            for scope in policy.SCOPE_IDS:
                receipt = REAL_CURRENTNESS(scope, datetime(2026, 9, 23, tzinfo=timezone.utc))
                self.assertEqual(receipt['scope_id'], scope)
                for clock in (datetime(2026, 9, 22, 16, tzinfo=timezone.utc), datetime(2026, 9, 24, 17, tzinfo=timezone.utc)):
                    with self.assertRaises(Deferred): REAL_CURRENTNESS(scope, clock)
            with self.assertRaises(ConfigurationFailure): REAL_CURRENTNESS('345241:tdac-baa-003')
        ledger = self.install()
        with patch.object(policy, 'source_currentness', side_effect=Deferred('fixture expiry')):
            with self.assertRaises(Deferred): policy.bind_operation(ledger, *self.packet())
        self.assertEqual(len(policy._operation_events(ledger.read())), 0)


if __name__ == '__main__':
    unittest.main()
