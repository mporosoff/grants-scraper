"""Complete runner lifecycle with real packet/evidence identities, fixture replies."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import test_contextual_team_wire_repair as old_fixture
import test_contextual_team_luna_repair as fixture
from test_contextual_team_shared_rows import answer
from tools import contextual_team_completion_check as check
from tools import contextual_team_completion_policy as policy
from tools import contextual_team_token_preflight as tokens
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import RecoveryRequired
from tools.offline_spend import identity, encoded, atomic_json, ConfigurationFailure, Deferred, Refusal, Incomplete


class CompletionCheck(unittest.TestCase):
    def setUp(self):
        self.base = old_fixture.WireRepair(); self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.state = self.base.state; self.data = self.base.data
        self.calls = []; self.counts = []; self.native = 20000
        self.status = 'success'; self.strict_run_status = 'completed'
        self.strict_run_conclusion = 'failure'; self.active = []
        folder = Path(__file__).parent/'fixtures/completion-check-evidence'
        state = self.base.runner().ledger.read()
        state['requests'].append(json.loads((folder/'request.json').read_bytes()))
        self.original = copy.deepcopy(state['requests'])
        atomic_json(self.state/'ledger.json', state)
        for name in ('receipts', 'diagnostics'):
            shutil.copyfile(folder/(name+'.json'), self.state/name/(policy.FAILED+'.json'))
        counts = json.loads((folder/'native-counts.json').read_bytes())
        existing.checkpoint(self.state, token_preflight=counts)
        # Only synthetic historical request/events/checkpoint identities differ.
        # Original scientific packet locks, final failure bytes and all 188 real
        # native-count rows retain their production identities.
        authority = copy.deepcopy(policy.plan())
        authority['starting_checkpoint'].update(
            requests_sha256=identity(state['requests']), events=len(state['events']),
            events_sha256=identity(state['events']),
            ledger_sha256=existing.sha((self.state/'ledger.json').read_bytes()),
            checkpoint_sha256=existing.sha((self.state/'checkpoint.json').read_bytes()))
        self.bind(patch.object(policy, 'plan', return_value=authority))
        self.bind(patch.object(check, 'Counter', side_effect=lambda state: tokens.Counter(state, post=self.count_provider)))
        policy.install_authority(self.state, self.api)

    def bind(self, mock):
        value = mock.start(); self.addCleanup(mock.stop); return value

    def api(self, path):
        if '?status=' in path: return encoded({'workflow_runs': self.active})
        if path.endswith(str(policy.plan()['terminal_run']['id'])):
            return encoded(policy.plan()['terminal_run'])
        return encoded({'id': 999, 'run_attempt': 1, 'status': self.strict_run_status,
            'conclusion': self.strict_run_conclusion, 'head_branch': 'main',
            'event': 'workflow_dispatch', 'path': existing.WORKFLOW, 'head_sha': 'a'*40})

    def count_provider(self, *args, **kwargs):
        self.counts.append(kwargs['json'])
        return fixture.Response({'input_tokens': self.native})

    def provider(self, *args, **kwargs):
        self.calls.append(kwargs['json'])
        if self.status == 'transport': raise OSError('fixture uncertain transport')
        if self.status in ('grammar', 'other400'):
            message = 'Compiled grammar is too large' if self.status == 'grammar' else 'Invalid request parameter'
            return fixture.Response({'error': {'type': 'invalid_request_error', 'message': message}}, 400)
        payload = {'model': 'claude-sonnet-5', 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 100, 'output_tokens': 200},
            'content': [{'type': 'text', 'text': json.dumps(answer(self.data))}]}
        if self.status == 'invalid': payload['content'][0]['text'] = '{}'
        if self.status == 'refusal': payload['stop_reason'] = 'refusal'
        if self.status == 'incomplete': payload['stop_reason'] = 'max_tokens'
        if self.status == 'wrong_model': payload['model'] = 'other-model'
        return fixture.Response(payload)

    def runner(self, **kwargs):
        return check.CompletionRunner(self.state, {}, post=self.provider, **kwargs)

    def restored(self):
        existing.checkpoint(self.state)
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for path in self.state.rglob('*.json'):
                archive.write(path, path.relative_to(self.state).as_posix())
        target = self.state.parent/(self.state.name+'-restored')
        existing.unpack_state(raw.getvalue(), target); self.state = target

    def grammar_failure(self):
        self.status = 'grammar'
        with self.assertRaises(RecoveryRequired): self.runner().perform(check.STRICT)
        self.status = 'success'
        return json.loads((self.state/'checkpoint.json').read_bytes())

    def authorize_fallback(self):
        checkpoint = self.grammar_failure()
        check.install_fallback(self.state, checkpoint, self.api)
        return checkpoint

    def test_strict_success_reuses_exact_cache_and_all_historical_rows(self):
        first = self.runner().perform(check.STRICT)
        for _ in range(3):
            self.restored()
            cached = self.runner().perform(check.STRICT)
            self.assertEqual(cached['value'], first['value']); self.assertTrue(cached['cache_hit'])
        state = self.runner().ledger.read()
        self.assertEqual(state['requests'][:687], self.original)
        self.assertEqual((len(self.calls), len(self.counts), len(state['requests'])), (1, 1, 688))
        self.assertEqual(sum(r['charged_microusd'] for r in self.original), 8161490)
        self.assertEqual(state['requests'][-1]['charged_microusd'], 2200)
        self.assertEqual(first['provider_acceptance'], 'complete_valid_independent_result')
        self.assertEqual(len(first['value']['people']), 12)
        self.assertEqual(sum(len(p['decisions']) for p in first['value']['people']), 24)
        self.assertNotIn('Luna', self.calls[0]['messages'][0]['content'])

    def test_paid_crash_boundaries_preserve_no_replay(self):
        original = self.state
        for boundary in ('after_reserve', 'after_reservation_checkpoint', 'after_dispatch',
                         'before_reconcile', 'after_reconcile', 'after_cache', 'after_receipt'):
            with self.subTest(boundary=boundary):
                self.state = original.parent/boundary; shutil.copytree(original, self.state)
                before = len(self.calls)
                def crash(point):
                    if point == boundary: raise KeyboardInterrupt()
                with self.assertRaises(KeyboardInterrupt): self.runner(crash=crash).perform(check.STRICT)
                sent = len(self.calls)-before
                for _ in range(3):
                    self.restored()
                    try: self.runner().perform(check.STRICT)
                    except (RecoveryRequired, Deferred): pass
                self.assertEqual(len(self.calls)-before, sent)
                self.assertEqual(self.runner().ledger.read()['requests'][:687], self.original)
        self.state = original

    def test_concurrency_claims_one_count_and_one_provider_attempt(self):
        def run(_):
            try: return self.runner().perform(check.STRICT)
            except (RecoveryRequired, Deferred): return None
        with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(run, range(2)))
        self.assertEqual((len(self.calls), len(self.counts)), (1, 1))

    def test_native_count_failure_and_sizing_never_dispatch_or_recount(self):
        self.native = 40000
        for _ in range(3):
            with self.assertRaisesRegex(Deferred, 'input_exceeds'): self.runner().perform(check.STRICT)
            self.restored()
        self.assertEqual((len(self.calls), len(self.counts)), (0, 1))
        self.assertEqual(self.runner().ledger.read()['requests'], self.original)

    def test_uncertain_count_is_durable_and_cannot_repeat(self):
        def uncertain(*args, **kwargs):
            self.counts.append(kwargs['json']); raise OSError('uncertain count')
        with patch.object(check, 'Counter', side_effect=lambda state: tokens.Counter(state, post=uncertain)):
            with self.assertRaises(OSError): self.runner().perform(check.STRICT)
        for _ in range(3):
            self.restored()
            with self.assertRaises(RecoveryRequired): self.runner().perform(check.STRICT)
        self.assertEqual((len(self.calls), len(self.counts)), (0, 1))

    def test_terminal_grammar_failure_allows_exactly_one_same_model_json_fallback(self):
        checkpoint = self.authorize_fallback()
        first = self.runner().perform(check.FALLBACK)
        for _ in range(3):
            self.restored()
            check.install_fallback(self.state, checkpoint, self.api)
            self.assertEqual(self.runner().perform(check.FALLBACK)['value'], first['value'])
        state = self.runner().ledger.read()
        self.assertEqual((len(self.calls), len(self.counts), len(state['requests'])), (2, 2, 689))
        self.assertIn('output_config', self.calls[0]); self.assertNotIn('output_config', self.calls[1])
        self.assertEqual(self.calls[0]['messages'], self.calls[1]['messages'])
        self.assertTrue(all(body['model'] == 'claude-sonnet-5' for body in self.calls))
        self.assertEqual(state['requests'][-2]['charged_microusd'], 200000)
        self.assertEqual(state['requests'][-2]['status'], 'reserved_unknown')
        self.assertEqual(state['requests'][:687], self.original)
        with self.assertRaises(RecoveryRequired): self.runner().perform(check.STRICT)
        with self.assertRaises(RecoveryRequired): check.available(state, check.FALLBACK)

    def test_no_fallback_for_silence_refusal_truncation_invalid_response_or_other_error(self):
        original = self.state
        for kind in ('transport', 'refusal', 'incomplete', 'invalid', 'wrong_model', 'other400'):
            with self.subTest(kind=kind):
                self.state = original.parent/kind; shutil.copytree(original, self.state)
                self.status = kind; before = len(self.calls)
                with self.assertRaises((RecoveryRequired, Refusal, Incomplete, ValueError)):
                    self.runner().perform(check.STRICT)
                checkpoint = json.loads((self.state/'checkpoint.json').read_bytes())
                with self.assertRaises((RecoveryRequired, FileNotFoundError)):
                    check.install_fallback(self.state, checkpoint, self.api)
                self.status = 'success'
                with self.assertRaises((RecoveryRequired, FileNotFoundError)):
                    self.runner().perform(check.FALLBACK)
                self.restored()
                with self.assertRaises(RecoveryRequired): self.runner().perform(check.STRICT)
                self.assertEqual(len(self.calls)-before, 1)
        self.state = original

    def test_fallback_needs_terminal_authenticated_run_and_untampered_evidence(self):
        checkpoint = self.grammar_failure()
        for status, conclusion in (('in_progress', None), ('completed', 'success')):
            self.strict_run_status = status; self.strict_run_conclusion = conclusion
            with self.assertRaisesRegex(RecoveryRequired, 'not_terminal'):
                check.install_fallback(self.state, checkpoint, self.api)
        self.strict_run_status = 'completed'; self.strict_run_conclusion = 'failure'
        with self.assertRaisesRegex(RecoveryRequired, 'not_terminal'):
            check.install_fallback(self.state, checkpoint | {'code_sha': 'b'*40}, self.api)
        state = self.runner().ledger.read(); rid = state['requests'][-1]['id']
        path = self.state/'diagnostics'/(rid+'.json'); raw = path.read_bytes()
        diagnostic = json.loads(raw); diagnostic['http_status'] = 200; atomic_json(path, diagnostic)
        with self.assertRaises(RecoveryRequired): check.install_fallback(self.state, checkpoint, self.api)
        path.write_bytes(raw)
        check.install_fallback(self.state, checkpoint, self.api)
        # Exact evidence remains required even after the disposition is installed.
        diagnostic['http_status'] = 400; diagnostic['error']['message'] = 'different error'
        atomic_json(path, diagnostic)
        with self.assertRaises(RecoveryRequired): self.runner().perform(check.FALLBACK)
        self.assertEqual(len(self.calls), 1)

    def test_fallback_failure_is_terminal_without_more_variants(self):
        self.authorize_fallback(); self.status = 'grammar'
        with self.assertRaises(RecoveryRequired): self.runner().perform(check.FALLBACK)
        for _ in range(3):
            self.restored()
            with self.assertRaises(RecoveryRequired): self.runner().perform(check.FALLBACK)
        self.assertEqual((len(self.calls), len(self.counts)), (2, 2))
        self.assertEqual(sum(r['charged_microusd'] for r in self.runner().ledger.read()['requests'][687:]), 400000)

    def test_fallback_authority_receipt_is_bound_to_ledger_before_dispatch_and_cache_reuse(self):
        checkpoint = self.authorize_fallback()
        _, base = check.fallback_evidence(self.state, self.runner().ledger.read())
        path = self.state/'receipts'/(identity(base)[:32]+'.json')
        raw = path.read_bytes()
        for cached in (False, True):
            if cached: self.runner().perform(check.FALLBACK)
            sent = len(self.calls)
            for mutation in ('missing', 'malformed', 'run_id', 'event_run_id', 'not_terminal', 'extra'):
                with self.subTest(cached=cached, mutation=mutation):
                    authority = json.loads(raw)
                    if mutation == 'missing': path.unlink()
                    elif mutation == 'malformed': path.write_bytes(b'{')
                    else:
                        if mutation == 'run_id': authority['authenticated_run']['id'] = 12345
                        if mutation == 'event_run_id': authority['event']['authenticated_run']['id'] = 12345
                        if mutation == 'not_terminal': authority['authenticated_run']['status'] = 'in_progress'
                        if mutation == 'extra': authority['extra'] = True
                        atomic_json(path, authority)
                    with self.assertRaises(RecoveryRequired): check.install_fallback(self.state, checkpoint, self.api)
                    with self.assertRaises(RecoveryRequired): self.runner().perform(check.FALLBACK)
                    self.assertEqual(len(self.calls), sent)
                    path.write_bytes(raw)
            state = self.runner().ledger.read(); original = copy.deepcopy(state)
            event = next(e for e in state['events'] if e.get('authority') == check.FALLBACK_AUTHORITY)
            event['authenticated_run']['id'] = 54321
            atomic_json(self.state/'ledger.json', state)
            with self.assertRaises(RecoveryRequired): self.runner().perform(check.FALLBACK)
            atomic_json(self.state/'ledger.json', original)
        self.assertEqual((len(self.calls), len(self.counts)), (2, 2))

    def test_changed_scientific_input_cannot_bypass_frozen_packet_identity(self):
        for mutation in ('retirement', 'source'):
            changed = copy.deepcopy(self.data)
            if mutation == 'retirement': changed['people'][0]['claims'].pop(0)
            else: changed['scope']['science']['title'] += ' changed'
            with patch.object(check.original, 'packet', return_value=(changed, {}, {})):
                with self.assertRaisesRegex(ConfigurationFailure, 'frozen_packet'):
                    self.runner().perform(check.STRICT)
        self.assertEqual((len(self.calls), len(self.counts)), (0, 0))

    def test_fallback_authority_interrupted_writes_resume_without_changing_holds(self):
        checkpoint = self.grammar_failure(); original = self.state
        historical = self.runner().ledger.read()['requests']
        for boundary in ('receipt', 'ledger', 'checkpoint'):
            with self.subTest(boundary=boundary):
                self.state = original.parent/('authority-'+boundary); shutil.copytree(original, self.state)
                def write(path, value):
                    atomic_json(path, value)
                    if boundary == 'receipt' and path.parent.name == 'receipts' or boundary == 'ledger' and path.name == 'ledger.json':
                        raise KeyboardInterrupt()
                with patch.object(check, 'atomic_json', side_effect=write), patch.object(existing, 'checkpoint',
                        side_effect=KeyboardInterrupt() if boundary == 'checkpoint' else existing.checkpoint):
                    with self.assertRaises(KeyboardInterrupt): check.install_fallback(self.state, checkpoint, self.api)
                for _ in range(3):
                    self.restored(); check.install_fallback(self.state, checkpoint, self.api)
                state = self.runner().ledger.read()
                self.assertEqual(state['requests'], historical)
                self.assertEqual(sum(e.get('authority') == check.FALLBACK_AUTHORITY for e in state['events']), 1)
                self.runner().perform(check.FALLBACK)
        self.state = original
        self.assertEqual((len(self.calls), len(self.counts)), (4, 4))

    def test_lost_or_tampered_valid_cache_never_replays(self):
        original = self.state
        for kind in ('missing', 'tampered'):
            self.state = original.parent/kind; shutil.copytree(original, self.state)
            before = len(self.calls); self.runner().perform(check.STRICT)
            row = self.runner().ledger.read()['requests'][-1]
            path = self.state/'cache'/(row['key']+'.json')
            if kind == 'missing': path.unlink()
            else:
                value = json.loads(path.read_bytes()); value['value']['people'].pop(); atomic_json(path, value)
            for _ in range(3):
                self.restored()
                with self.assertRaises(RecoveryRequired): self.runner().perform(check.STRICT)
            self.assertEqual(len(self.calls)-before, 1)
        self.state = original

    def test_reservation_metadata_bounds_and_unrelated_uncertainty_fail_closed(self):
        state = self.runner().ledger.read(); op = check.plan()['operations'][check.STRICT]
        metadata = {'purpose': check.STRICT, 'completion_authority': policy.VERSION,
            'completion_transport': check.TRANSPORTS[check.STRICT], 'completion_lock_sha256': identity(check.plan()),
            'body_sha256': op['body_sha256'], 'pair_contract_sha256': op['contract_sha256'],
            'repair_of': policy.FAILED, 'packet_sha256': check.original.prior.plan()['source_inputs_sha256']}
        check.check_reservation(state, 'anthropic', metadata, 200000, 40000, 12000)
        for key in metadata:
            with self.subTest(field=key):
                with self.assertRaises(ConfigurationFailure):
                    check.check_reservation(state, 'anthropic', metadata | {key: 'wrong'}, 200000, 40000, 12000)
        for limits in ((199999, 40000, 12000), (200000, 39999, 12000), (200000, 40000, 11999)):
            with self.assertRaises(ConfigurationFailure): check.check_reservation(state, 'anthropic', metadata, *limits)
        changed = copy.deepcopy(state)
        changed['requests'].append({'id': 'unrelated', 'status': 'reserved_unknown', 'charged_microusd': 1})
        with self.assertRaises(RecoveryRequired): check.available(changed, check.STRICT)
        changed['requests'][-1].update(status='valid', charged_microusd=45000000)
        with self.assertRaises(Deferred): check.available(changed, check.STRICT)

    def test_entrypoint_and_mixed_selectors_only_allow_iteration_one(self):
        args = SimpleNamespace(action='prepare', state=self.state,
            reservation=self.state.parent/'reservation.json', result=self.state.parent/'result.json')
        with patch.object(existing, 'trusted_environment'), patch.object(existing, 'restore'), \
             patch.object(existing, 'api', side_effect=self.api), patch.dict(os.environ, {
                 'CONTEXTUAL_CHECK': json.dumps({'completion_iteration1': 'strict'})}):
            check.run(args)
            reserved = json.loads(args.reservation.read_bytes())
            self.assertEqual((reserved['maximum_new_attempts'], reserved['maximum_new_microusd']), (1, 200000))
            args.action = 'execute'
            with patch.object(check, 'CompletionRunner', return_value=self.runner()): check.run(args)
            self.assertEqual(json.loads(args.result.read_bytes())['provider_acceptance'], 'complete_valid_independent_result')
        for selector in ({'completion_iteration1': 'later'}, {'completion_iteration1': 'strict', 'extra': True}):
            with patch.object(existing, 'trusted_environment'), patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps(selector)}):
                with self.assertRaises(ConfigurationFailure): check.run(args)
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__': unittest.main()
