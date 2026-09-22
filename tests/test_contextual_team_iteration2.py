"""Finite I2 lifecycle with real evidence identities and fixture providers only."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import io
import threading
import unittest
from unittest.mock import patch
import zipfile

import test_contextual_team_completion_policy as budget_fixture
import test_contextual_team_iteration2_contract as science_fixture
import test_contextual_team_luna_repair as evidence_fixture
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration2_policy as policy
from tools import contextual_team_completion_policy as pool
from tools import contextual_team_iteration2 as workflow
from tools import contextual_team_iteration2_contract as science
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs
from tools.contextual_team_policy import inputs
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred
from tools.team_recommender_budget import ExperimentLedger


class Iteration2(unittest.TestCase):
    def bind(self, value):
        result = value.start(); self.addCleanup(value.stop); return result

    def setUp(self):
        self.fixture = budget_fixture.CompletionBudget('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.state = self.fixture.state; ledger = self.fixture.install(); state = ledger.read()
        cp = json.loads((self.state/'checkpoint.json').read_bytes())
        self.p = {'version': policy.VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
            'scope_ids': ['363302:a-1', '351715'] + ['fixture-'+str(i) for i in range(10)],
            'first_scope_id': '363302:a-1', 'source_inputs_sha256': 'f'*64,
            'development_manifest_sha256': 'e'*64, 'maximum_wire_bytes': 524288,
            'maximum_graph_bytes': 393216,
            'input_token_ceilings': {'interpret': 180000, 'query': 25000, 'assess': 180000, 'verify': 180000},
            'stages': {k: {'provider': v[0], 'model': v[1], 'output_tokens': v[2]} for k, v in policy.STAGES.items()},
            'public_activation': False, 'recurring_paid_usage': False,
            'starting_checkpoint': {'ledger_sha256': existing.sha(ledger.path.read_bytes()),
                'checkpoint_sha256': existing.sha((self.state/'checkpoint.json').read_bytes()),
                'requests': len(state['requests']), 'requests_sha256': identity(state['requests']),
                'events': len(state['events']), 'events_sha256': identity(state['events']),
                'native_counts': len(cp['phase2_token_preflight']['rows']),
                'native_counts_sha256': identity(cp['phase2_token_preflight']['rows']),
                'run': {'id': 35634326282, 'status': 'completed', 'conclusion': 'success'}}}
        self.p['release_id'] = identity(self.p)
        self.bind(patch.object(policy, 'plan', return_value=self.p))
        self.bind(patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-only', 'VOYAGE_API_KEY': 'fixture-only'}))
        self.active = []; self.terminal = 'completed'; self.calls = []; self.count_calls = 0
        self.original_state = copy.deepcopy(state)
        self.data = science_fixture.selected(evidence_fixture.real_data())
        self.scope = copy.deepcopy(self.data['scope']) | {'source_id': identity({'scope': self.data['scope']}), 'state': 'unassessed'}
        self.config = copy.deepcopy(inputs())
        self.config.update(snapshot_id=self.p['release_id'], iteration2=self.p, scopes=[self.scope])

    def api(self, path):
        return encoded({'workflow_runs': self.active} if '?status=' in path else
            self.p['starting_checkpoint']['run'] | {'status': self.terminal})

    def install(self):
        return policy.install_authority(self.state, self.api)

    def counter(self, url, **kwargs):
        self.count_calls += 1
        return evidence_fixture.Response({'input_tokens': 1200})

    def post(self, url, **kwargs):
        body = kwargs['json']; self.calls.append(copy.deepcopy(body)); model = body['model']
        if model == 'voyage-4-large':
            return evidence_fixture.Response({'model': model, 'usage': {'total_tokens': 100},
                'data': [{'index': i, 'embedding': [1.0] + [0.0]*1023} for i in range(len(body['input']))]})
        if model == 'gpt-5.6-luna':
            evidence = json.loads(body['input'])
            if 'wire_questions' not in evidence:
                wire = copy.deepcopy(self.data['interpretation']); wire.pop('requirement_policy')
                for role in wire['roles']:
                    for key in ('required', 'quote', 'source_field'): role.pop(key)
            else:
                answers = []
                for qid, q in evidence['wire_questions'].items():
                    refs = [c['claim_ref'] for c in evidence['wire_claims'].values() if c['person_id'] == q['person_id']]
                    answers.append({'question_id': qid, 'coverage': 'direct', 'claims': refs[:1],
                        'reason': 'Fixture documented activity for the exact selected contribution.', 'gap': 'Fixture uncertainty.'})
                wire = {'answers': answers}
            response = payload(json.dumps(wire), 'openai')
        else:
            evidence = json.loads(body['messages'][0]['content'])
            qids = {(q['person_id'], q['role_id']): qid for qid, q in evidence['wire_questions'].items()}
            wire = {'state': 'coherent', 'answers': [{'question_id': qids[(p['person_id'], p['role_id'])],
                **{k: p[k] for k in ('coverage', 'claims', 'central')},
                'reason': 'Fixture independent verification of the original evidence.', 'gap': 'Fixture independent limitation.'}
                for p in evidence['proposed_pairs']]}
            response = payload(json.dumps(wire), 'anthropic')
        response['usage'] = {'input_tokens': 1000, 'output_tokens': 100}
        return evidence_fixture.Response(response)

    def runner(self, **kwargs):
        return workflow.Iteration2Runner(self.state, self.config, post=self.post, counter_post=self.counter, **kwargs)

    def test_scope_authority_preserves_original_owner_budget_and_is_idempotent(self):
        for _ in range(2):
            state = self.install().read()
            self.assertEqual(state['requests'], self.original_state['requests'])
            self.assertEqual(state['events'][:-1], self.original_state['events'])
            self.assertEqual(state['events'][-1], policy.event())
            self.assertEqual((state['limit_microusd'], state['max_requests']), (60000000, 1290))
        record = policy.prepare_record(self.state, {'job_id': identity([self.p['release_id'], self.scope['id'], '']),
            'release_id': self.p['release_id'], 'scope_id': self.scope['id'], 'person_id': ''})
        self.assertEqual(record['maximum_logical_spend_usd'], 60)
        self.assertEqual(record['original_additional_allowance']['microusd'], 50000000)
        self.assertEqual(record['remaining_completion_allowance']['attempts'], 600)
        self.assertEqual(self.calls, [])

    def test_starting_checkpoint_active_owner_and_historical_native_tampering_stop(self):
        self.active = [{'id': 123}]
        with self.assertRaises(Deferred): self.install()
        self.active = []; self.terminal = 'in_progress'
        with self.assertRaises(Deferred): self.install()
        self.terminal = 'completed'
        cp = json.loads((self.state/'checkpoint.json').read_bytes())
        cp['phase2_token_preflight']['rows'][0]['input_tokens'] += 1
        atomic_json(self.state/'checkpoint.json', cp)
        with self.assertRaises(ConfigurationFailure): self.install()
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read(), self.original_state)

    def test_operation_lock_is_concurrent_idempotent_and_refuses_new_body(self):
        ledger = self.install(); c, body = science.assessment_body(self.data)
        purpose = policy.operation('351715', 'assess')
        def bind(_): return policy.bind_operation(ledger, purpose, body, c, identity(self.data))
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(*list(executor.map(bind, range(2))))
        self.assertEqual(sum(e.get('purpose') == purpose for e in ledger.read()['events']), 1)
        with self.assertRaises(Deferred):
            policy.bind_operation(ledger, purpose, body | {'input': body['input']+' '}, c, identity(self.data))
        self.assertEqual(self.calls, [])

    def test_real_identity_assessment_verifier_cache_and_mixed_provider_accounting(self):
        self.install(); runner = self.runner()
        assessment = runner.scientific('adjudication', self.data, self.scope)
        verified = runner.scientific('verification', self.data, self.scope, assessment=assessment)
        self.assertEqual(len(verified['people']), 12)
        self.assertEqual(sum(len(p['decisions']) for p in verified['people']), 24)
        self.assertEqual([b['model'] for b in self.calls], ['gpt-5.6-luna', 'claude-sonnet-5'])
        self.assertEqual(self.count_calls, 1)
        before = ExperimentLedger(self.state/'ledger.json').read()['requests']
        again = self.runner(); value = again.scientific('adjudication', self.data, self.scope)
        self.assertEqual(again.scientific('verification', self.data, self.scope, assessment=value), verified)
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read()['requests'], before)
        self.assertEqual(len(self.calls), 2); self.assertEqual(self.count_calls, 1)
        self.assertEqual([r['charged_microusd'] for r in before[-2:]], [320, 3000])
        self.assertEqual({r['purpose'] for r in before[-2:]}, {'cb-fc-i2-351715:assess', 'cb-fc-i2-351715:verify'})

    def test_complete_full_directory_retrieval_persists_all_pairs_and_reuses_results(self):
        self.install(); original_vectors = workflow.Iteration2Runner.vectors; seen = []
        chosen = {p['person_id'] for p in self.data['people']}
        def vectors(runner, docs, role, scope=None):
            if role == 'query': return original_vectors(runner, docs, role, scope)
            seen.extend(d['person_id'] for d in docs)
            return [{'id': d['input_id'], 'embedding': ([1.0, 0.0] if d['person_id'] in chosen else [0.0, 1.0]) + [0.0]*1022} for d in docs]
        with patch.object(workflow.Iteration2Runner, 'vectors', vectors):
            graph = self.runner().run_scope(self.scope)
            repeat = self.runner().run_scope(self.scope)
        self.assertEqual(len(set(seen)), 155)
        self.assertEqual(graph, repeat); self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.count_calls, 1); self.assertEqual(graph['retrieval']['eligible'], 155)
        self.assertEqual(len(graph['pair_decisions']), 12)
        self.assertEqual(sum(len(p['decisions']) for p in graph['pair_decisions']), 24)
        self.assertEqual(graph['graph_id'], identity({k: v for k, v in graph.items() if k not in ('graph_id', 'requests')}))
        saved = json.loads(workflow.result_path(self.state, self.scope['id']).read_bytes())
        self.assertEqual(saved['value'], graph)
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read()['requests'][:687], self.original_state['requests'])

    def test_failed_paid_stage_is_not_rekeyed_or_recounted(self):
        self.install(); runner = self.runner()
        def failed(*args, **kwargs):
            response = payload('{"answers": []}', 'openai')
            response['usage'] = {'input_tokens': 1000, 'output_tokens': 100}
            return evidence_fixture.Response(response)
        runner.post = failed
        with self.assertRaises(ValueError): runner.scientific('adjudication', self.data, self.scope)
        ledger = runner.ledger.read(); self.assertEqual(ledger['requests'][-1]['status'], 'failed')
        with self.assertRaises(RecoveryRequired): self.runner().scientific('adjudication', self.data, self.scope)
        changed = copy.deepcopy(self.data); changed['people'][0]['summary'] += ' Changed input.'
        with self.assertRaises(Deferred): self.runner().scientific('adjudication', changed, self.scope)
        self.assertEqual(runner.ledger.read()['requests'], ledger['requests'])
        self.assertEqual(self.count_calls, 0)

    def test_missing_vectors_and_manual_extension_cannot_purchase(self):
        self.install(); runner = self.runner(); runner.scope_id = '351715'
        with self.assertRaises(RecoveryRequired): runner.vectors(self.config['documents'][:1], 'document')
        with self.assertRaises(ConfigurationFailure): runner.run_scope(self.scope, self.data['people'][0]['person_id'])
        self.assertEqual(self.calls, [])

    def test_conservative_reservation_exact_identity_and_pool_reserve(self):
        ledger = self.install(); c, body = science.assessment_body(self.data)
        purpose = policy.operation('351715', 'assess')
        metadata = policy.bind_operation(ledger, purpose, body, c, identity(self.data)) | {
            'purpose': purpose, 'body_sha256': identity(body)}
        n = len(encoded(body)) + 1024; amount = (n+4)//5 + 28800
        policy.check_reservation(ledger.read(), 'openai', metadata, amount, n, 24000)
        for patch_metadata, provider, cost in (({'body_sha256': 'b'*64}, 'openai', amount),
                ({}, 'anthropic', amount), ({}, 'openai', amount-1)):
            with self.assertRaises(ConfigurationFailure):
                policy.check_reservation(ledger.read(), provider, metadata | patch_metadata, cost, n, 24000)
        state = ledger.read(); state['requests'].append({'id': 'later', 'status': 'valid', 'charged_microusd': 45000000})
        with self.assertRaises(Deferred): policy.check_reservation(state, 'openai', metadata, amount, n, 24000)

    def test_lost_success_cache_and_uncertain_request_require_recovery(self):
        self.install(); runner = self.runner(); runner.scientific('adjudication', self.data, self.scope)
        row = runner.ledger.read()['requests'][-1]
        (self.state/'cache'/(row['key']+'.json')).unlink()
        with self.assertRaises(RecoveryRequired): self.runner().scientific('adjudication', self.data, self.scope)
        state = runner.ledger.read(); state['requests'][-1]['status'] = 'reserved_unknown'
        atomic_json(runner.ledger.path, state)
        with self.assertRaises(Deferred): policy.history(state)
        # A later uncertain row cannot impersonate a grandfathered hold ID.
        state['requests'][-1]['id'] = next(iter(pool.HISTORICAL_UNKNOWN_IDS))
        with self.assertRaises(Deferred): policy.history(state)
        self.assertEqual(len(self.calls), 1)

    def test_interrupted_native_count_never_changes_packet_or_repeats(self):
        self.install(); assessment = science_fixture.assessment(self.data)
        def failed_count(*args, **kwargs):
            self.count_calls += 1
            raise OSError('fixture interruption after native claim')
        runner = workflow.Iteration2Runner(self.state, self.config, post=self.post, counter_post=failed_count)
        with self.assertRaises(OSError): runner.scientific('verification', self.data, self.scope, assessment=assessment)
        with self.assertRaises(RecoveryRequired): self.runner().scientific('verification', self.data, self.scope, assessment=assessment)
        self.assertEqual(self.count_calls, 1); self.assertEqual(self.calls, [])
        self.assertEqual(runner.ledger.read()['requests'], self.original_state['requests'])

    def test_crash_after_reservation_preserves_hold_without_provider_replay(self):
        self.install()
        def crash(boundary):
            if boundary == 'after_reserve': raise SystemExit('fixture process loss')
        runner = self.runner(crash=crash)
        with self.assertRaises(SystemExit): runner.scientific('adjudication', self.data, self.scope)
        row = runner.ledger.read()['requests'][-1]
        self.assertEqual(row['status'], 'reserved_unknown')
        self.assertEqual(row['reserved_microusd'], row['charged_microusd'])
        with self.assertRaises(Deferred): self.runner().scientific('adjudication', self.data, self.scope)
        self.assertEqual(self.calls, []); self.assertEqual(self.count_calls, 0)

    def test_concurrent_same_operation_has_one_provider_attempt(self):
        self.install(); dispatched = threading.Event(); release = threading.Event()
        def post(*args, **kwargs):
            dispatched.set()
            if not release.wait(5): raise AssertionError('fixture synchronization timeout')
            return self.post(*args, **kwargs)
        runner = self.runner(); runner.post = post
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(runner.scientific, 'adjudication', self.data, self.scope)
            self.assertTrue(dispatched.wait(5))
            try:
                with self.assertRaises(Deferred): self.runner().scientific('adjudication', self.data, self.scope)
            finally:
                release.set()
            self.assertEqual(len(first.result()['people']), 12)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(runner.ledger.read()['requests']), len(self.original_state['requests'])+1)

    def test_paid_cache_survives_archive_restore_without_extra_provider_usage(self):
        self.install(); accepted = self.runner().scientific('adjudication', self.data, self.scope)
        before = ExperimentLedger(self.state/'ledger.json').read()['requests']
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as saved:
            for path in self.state.rglob('*.json'):
                saved.write(path, path.relative_to(self.state).as_posix())
        target = self.state.parent/'restored'; existing.unpack_state(archive.getvalue(), target); self.state = target
        self.install()
        self.assertEqual(self.runner().scientific('adjudication', self.data, self.scope), accepted)
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read()['requests'], before)
        self.assertEqual(len(self.calls), 1)

    def test_controls_and_source_incoherence_do_not_buy_assessment(self):
        self.install()
        for state in ('action_blocked', 'needs_scope_selection', 'unsuitable'):
            result = self.runner().run_scope(self.scope | {'state': state})
            self.assertEqual(result['state'], state)
        self.assertEqual(self.calls, []); self.assertEqual(self.count_calls, 0)

    def test_prepare_installs_same_owner_and_outputs_mixed_provider_route(self):
        from tools import contextual_team_executor as dispatcher
        job = {'release_id': self.p['release_id'], 'scope_id': self.scope['id'], 'person_id': '',
            'job_id': identity([self.p['release_id'], self.scope['id'], ''])}
        job_path = self.state.parent/'job.json'; output = self.state.parent/'reservation.json'
        github = self.state.parent/'github-output.txt'; atomic_json(job_path, job)
        with patch('tools.contextual_team_option1.configuration_for_job', return_value=self.config), \
                patch.object(existing, 'trusted_environment'), \
                patch.object(existing, 'restore', return_value=ExperimentLedger(self.state/'ledger.json')), \
                patch.object(existing, 'api', side_effect=self.api), \
                patch.dict(os.environ, {'GITHUB_OUTPUT': str(github)}):
            dispatcher.prepare(self.state, output, job_path)
        self.assertEqual(github.read_text(), 'text_provider=mixed\n')
        record = json.loads(output.read_bytes())
        self.assertEqual(record['maximum_logical_spend_usd'], 60)
        self.assertEqual(record['maximum_new_metered_attempts'], 4)
        self.assertEqual(ExperimentLedger(self.state/'ledger.json').read()['requests'], self.original_state['requests'])


if __name__ == '__main__': unittest.main()
