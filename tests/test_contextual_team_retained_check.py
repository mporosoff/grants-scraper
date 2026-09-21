"""Trusted retained-response lifecycle; fixture inference only, no provider IO."""
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

import test_contextual_team_completion_check as fixture
from test_contextual_team_retained_rows import canonical_answer
from tools import contextual_team_completion_check as strict
from tools import contextual_team_retained_check as recovery
from tools import contextual_team_retained_rows as retained
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import RecoveryRequired, Runner
from tools.contextual_team_token_preflight import Counter
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure


class RetainedCheck(unittest.TestCase):
    def setUp(self):
        self.base = fixture.CompletionCheck(); self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.state = self.base.state; self.data = self.base.data; self.dispatches = 0; self.restores = 0
        self.text = json.dumps(canonical_answer(self.data), ensure_ascii=False)
        def fixture_provider(*a, **kw):
            self.dispatches += 1
            return fixture.fixture.Response({'model': 'claude-sonnet-5', 'stop_reason': 'end_turn',
                'usage': {'input_tokens': 100, 'output_tokens': 200},
                'content': [{'type': 'text', 'text': self.text}]})
        with self.assertRaisesRegex(ValueError, 'answer_claim_owner_or_revision'):
            strict.CompletionRunner(self.state, {}, post=fixture_provider).perform(strict.STRICT)
        self.expected = retained.recover(self.text, self.data)
        ledger = existing.ExperimentLedger(self.state/'ledger.json').read()
        self.original = copy.deepcopy(ledger); row = ledger['requests'][-1]
        cp = json.loads((self.state/'checkpoint.json').read_bytes())
        self.original_counts = copy.deepcopy(cp['phase2_token_preflight'])
        self.original_receipt = (self.state/'receipts'/(row['id']+'.json')).read_bytes()
        self.original_diagnostic = (self.state/'diagnostics'/(row['id']+'.json')).read_bytes()
        diagnostic = json.loads(self.original_diagnostic)
        p = copy.deepcopy(recovery.plan()); s = p['source']
        s['run'].update(id=999, run_attempt=1, head_sha='a'*40)
        s.update(ledger_sha256=existing.sha((self.state/'ledger.json').read_bytes()),
            checkpoint_sha256=existing.sha((self.state/'checkpoint.json').read_bytes()),
            request_id=row['id'], request_sha256=identity(row),
            receipt_sha256=existing.sha(self.original_receipt),
            diagnostic_sha256=existing.sha(self.original_diagnostic),
            diagnostic_identity=identity(diagnostic), text_sha256=identity(self.text),
            requests_sha256=identity(ledger['requests']), native_counts_sha256=identity(self.original_counts['rows']))
        p['result_sha256'] = identity(self.expected)
        self.p = p; self.bind(patch.object(recovery, 'plan', return_value=p))
        self.bind(patch.dict(os.environ, {'GITHUB_RUN_ID': '1001', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_SHA': 'b'*40, 'GITHUB_REPOSITORY': existing.REPOSITORY,
            'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_WORKFLOW_REF': existing.REPOSITORY+'/'+existing.WORKFLOW+'@refs/heads/main',
            'CONTEXTUAL_CHECK': json.dumps(recovery.SELECTOR),
            'CONTEXTUAL_JOB': '', 'PACKET_HASH': '', 'PACKET_COMMIT': '',
            'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': '', 'VOYAGE_API_KEY': ''}))
        # Initialization above used a fixture response. Recovery itself may
        # never call either paid inference or even the free native endpoint.
        self.bind(patch.object(Runner, 'request', side_effect=AssertionError('no_paid_request')))
        self.bind(patch.object(Counter, 'count', side_effect=AssertionError('no_native_count')))
        self.bind(patch('requests.post', side_effect=AssertionError('no_provider_transport')))
        self.active = []; self.status = 'completed'

    def bind(self, p):
        value = p.start(); self.addCleanup(p.stop); return value

    def api(self, path):
        return encoded({'workflow_runs': self.active} if '?status=' in path else
            self.p['source']['run'] | {'status': self.status})

    def restored(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for p in self.state.rglob('*.json'):
                archive.write(p, p.relative_to(self.state).as_posix())
        self.restores += 1; target = self.state.parent/('r'+str(self.restores))
        existing.unpack_state(raw.getvalue(), target); self.state = target

    def assert_history(self):
        ledger = existing.ExperimentLedger(self.state/'ledger.json').read()
        self.assertEqual(ledger['requests'], self.original['requests'])
        self.assertEqual(ledger['events'], self.original['events']+[recovery.event()])
        self.assertEqual((self.state/'receipts'/(self.p['source']['request_id']+'.json')).read_bytes(), self.original_receipt)
        self.assertEqual((self.state/'diagnostics'/(self.p['source']['request_id']+'.json')).read_bytes(), self.original_diagnostic)
        self.assertEqual(json.loads((self.state/'checkpoint.json').read_bytes())['phase2_token_preflight'], self.original_counts)
        self.assertEqual(self.dispatches, 1); self.assertEqual(len(self.base.counts), 1)

    def test_complete_recovery_preserves_failed_row_and_reuses_exact_derived_cache(self):
        out = recovery.recover(self.state, self.api)
        self.assertEqual(out['value'], self.expected); self.assertFalse(out['cache_hit'])
        self.assertEqual(out['original_request_status'], 'failed')
        self.assertEqual((out['new_metered_attempts'], out['new_native_count_calls'], out['new_microusd']), (0, 0, 0))
        self.assertNotEqual(out['recovery_key'], self.original['requests'][-1]['key'])
        self.assertFalse((self.state/'cache'/(self.original['requests'][-1]['key']+'.json')).exists())
        for _ in range(3):
            self.assert_history(); self.restored()
            again = recovery.recover(self.state, self.api)
            self.assertTrue(again['cache_hit']); self.assertEqual(again['value'], out['value'])
        self.assert_history()

    def test_trusted_prepare_execute_emit_no_provider_credentials_and_zero_reservation(self):
        args = SimpleNamespace(action='prepare', state=self.state,
            reservation=self.state.parent/'reservation.json', result=self.state.parent/'result.json')
        output = self.state.parent/'step-output.txt'
        with patch.object(existing, 'restore', return_value=existing.ExperimentLedger(self.state/'ledger.json')), \
             patch.object(existing, 'api', side_effect=self.api), patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}):
            recovery.run(args)
            reservation = json.loads(args.reservation.read_bytes())
            self.assertEqual((reservation['maximum_new_microusd'], reservation['maximum_new_attempts'], reservation['native_count_calls']), (0, 0, 0))
            self.assertEqual(output.read_text(), 'text_provider=none\n')
            args.action = 'execute'; recovery.run(args)
            result = json.loads(args.result.read_bytes())
            self.assertEqual(result['value'], self.expected)
            self.assertEqual(result['validation_code_sha'], 'b'*40)
        self.assert_history()
        for supplied in ({**recovery.SELECTOR, 'extra': True}, {'completion_iteration1': 'strict'}):
            with patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps(supplied)}):
                with self.assertRaises(ConfigurationFailure): recovery.run(args)

    def test_execute_requires_all_prepared_artifacts(self):
        args = SimpleNamespace(action='execute', state=self.state, result=self.state.parent/'result.json')
        with self.assertRaises(RecoveryRequired): recovery.run(args)
        recovery.recover(self.state, self.api)
        cache, receipt = recovery.paths(self.state); cache.unlink()
        with self.assertRaises(RecoveryRequired): recovery.run(args)
        recovery.recover(self.state, self.api); receipt.unlink()
        with self.assertRaises(RecoveryRequired): recovery.run(args)
        recovery.recover(self.state, self.api); recovery.run(args); self.assert_history()

    def test_every_crash_boundary_restores_without_replaying_original_request(self):
        source = self.state
        for i, boundary in enumerate(('after_cache', 'after_receipt', 'after_event', 'before_checkpoint', 'after_checkpoint')):
            with self.subTest(boundary=boundary):
                self.state = source.parent/('c'+str(i)); shutil.copytree(source, self.state)
                def crash(point):
                    if point == boundary: raise KeyboardInterrupt('fixture crash')
                with self.assertRaises(KeyboardInterrupt): recovery.recover(self.state, self.api, crash=crash)
                self.restored()  # No repair/checkpoint helper before restore.
                for _ in range(2):
                    self.assertEqual(recovery.recover(self.state, self.api)['value'], self.expected)
                    self.assert_history(); self.restored()
        self.state = source

    def test_concurrent_recovery_uses_actual_packet_reader_without_nested_ledger_lock(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: recovery.recover(self.state, self.api), range(2)))
        self.assertEqual([v['value'] for v in values], [self.expected, self.expected])
        self.assert_history()

    def test_original_or_derived_evidence_tampering_fails_closed(self):
        source = self.state; recovery.recover(self.state, self.api)
        for i, kind in enumerate(('source_receipt', 'source_diagnostic', 'paid_row', 'native_count',
                                  'cache', 'receipt', 'event', 'unexpected_file')):
            with self.subTest(kind=kind):
                self.state = source.parent/('t'+str(i)); shutil.copytree(source, self.state)
                cache, receipt = recovery.paths(self.state)
                if kind in ('source_receipt', 'source_diagnostic'):
                    folder = 'receipts' if kind == 'source_receipt' else 'diagnostics'
                    target = self.state/folder/(self.p['source']['request_id']+'.json')
                    target.write_bytes(target.read_bytes()+b' ')
                elif kind in ('paid_row', 'event'):
                    path = self.state/'ledger.json'; state = json.loads(path.read_bytes())
                    if kind == 'paid_row': state['requests'][-1]['charged_microusd'] += 1
                    else: state['events'][-1]['result_sha256'] = '0'*64
                    atomic_json(path, state)
                elif kind == 'native_count':
                    path = self.state/'checkpoint.json'; cp = json.loads(path.read_bytes())
                    cp['phase2_token_preflight']['rows'][-1]['input_tokens'] += 1; atomic_json(path, cp)
                elif kind in ('cache', 'receipt'):
                    (cache if kind == 'cache' else receipt).write_text('{}')
                else: atomic_json(self.state/'cache'/('0'*64+'.json'), {'unexpected': True})
                with self.assertRaises(RecoveryRequired): recovery.recover(self.state, self.api)
        self.state = source; self.assert_history()

    def test_terminal_source_and_single_owner_required_before_writes(self):
        before = {str(p.relative_to(self.state)): p.read_bytes() for p in self.state.rglob('*.json')}
        self.status = 'in_progress'
        with self.assertRaises(RecoveryRequired): recovery.recover(self.state, self.api)
        self.status = 'completed'; self.active = [{'id': 123}]
        with self.assertRaises(RecoveryRequired): recovery.recover(self.state, self.api)
        self.assertEqual({str(p.relative_to(self.state)): p.read_bytes() for p in self.state.rglob('*.json')}, before)

    def test_evidence_change_between_packet_read_and_lock_is_detected(self):
        prepare = recovery.prepare_plan
        def changed(*args, **kwargs):
            result = prepare(*args, **kwargs)
            old = next((self.state/'cache').glob('*.json'))
            old.write_bytes(old.read_bytes()+b' ')
            return result
        with patch.object(recovery, 'prepare_plan', side_effect=changed):
            with self.assertRaisesRegex(RecoveryRequired, 'original_checkpoint_changed'):
                recovery.recover(self.state, self.api)


if __name__ == '__main__':
    unittest.main()
