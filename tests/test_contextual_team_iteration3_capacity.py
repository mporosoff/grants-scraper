"""Exact capacity amendment with portable history; never contact a provider."""
import copy
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import test_contextual_team_checkpoint_disposition as fixtures
from tools import contextual_team_completion_policy as pool
from tools import contextual_team_iteration2_policy as iteration2
from tools import contextual_team_iteration3_capacity as capacity
from tools import contextual_team_checkpoint_disposition as disposition
from tools import team_recommender_executor as executor
from tools import contextual_team_token_preflight as tokens
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure, Deferred


class Capacity(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CheckpointDisposition('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.path
        state = copy.deepcopy(self.fixture.state)
        state['requests'].extend({'id': f'new-{i}', 'charged_microusd': 1000,
            'provider': 'openai', 'status': 'valid'} for i in range(31))
        state['events'].extend({'kind': 'unchanged_later_history', 'sequence': i} for i in range(33))
        self.rows = copy.deepcopy(self.fixture.counts) + [{'id': f'cb-fc-prior-{i}',
            'status': 'complete', 'input_tokens': 10} for i in range(12)]
        atomic_json(self.path/'ledger.json', state)
        executor.checkpoint(self.path, token_preflight={'version': tokens.VERSION,
            'source_sha256': tokens.SOURCE_SHA, 'rows': self.rows})
        self.before = {p.relative_to(self.path).as_posix(): p.read_bytes() for p in self.path.rglob('*.json')}
        self.original = state
        self.p = json.loads((capacity.ROOT/'config/contextual_team/iteration3-capacity-amendment-v1.json').read_bytes())
        checkpoint = json.loads(self.before['checkpoint.json'])
        self.p['source'].update(ledger_sha256=executor.sha(self.before['ledger.json']),
            checkpoint_sha256=executor.sha(self.before['checkpoint.json']), requests=len(state['requests']),
            requests_sha256=identity(state['requests']), events=len(state['events']),
            events_sha256=identity(state['events']), native_counts=len(self.rows),
            native_counts_sha256=identity(self.rows), checkpoint_files=len(checkpoint['files']),
            checkpoint_files_sha256=identity(checkpoint['files']))
        self.bind(patch.object(capacity, 'plan', return_value=self.p))
        self.api_changes = {}; self.active = []

    def bind(self, value):
        result = value.start(); self.addCleanup(value.stop); return result

    def api(self, path):
        source = self.p['source']
        if '?status=' in path:
            value = {'workflow_runs': self.active, 'total_count': len(self.active)}
        elif '/artifacts/' in path:
            value = source['artifact'] | {'expired': False, 'workflow_run': source['run']}
        else: value = source['run']
        return encoded(value | self.api_changes)

    def install(self, **kwargs):
        return capacity.install(self.path, self.api, **kwargs)

    def test_history_files_holds_dollars_and_original_baseline_remain(self):
        ledger = self.install(); state = ledger.read()
        self.assertEqual(state['requests'], self.original['requests'])
        self.assertEqual(state['events'][:-1], self.original['events'])
        self.assertEqual(state['events'][-1], capacity.event())
        self.assertEqual((ledger.limit, ledger.max_requests), (60000000, 1490))
        self.assertEqual(disposition.exposure(state), {'microusd': 713400, 'attempts': 4, 'native_counts': 1})
        effective = pool.effective_plan(state)
        self.assertEqual(effective['starting_checkpoint'], pool.plan()['starting_checkpoint'])
        self.assertEqual(effective['protected'], pool.plan()['protected'])
        for name, raw in self.before.items():
            if name not in ('ledger.json', 'checkpoint.json'):
                self.assertEqual((self.path/name).read_bytes(), raw)
        with patch.object(iteration2, 'history'), patch.object(iteration2, 'check_counts', return_value=self.rows):
            balance = iteration2.remaining(state, self.path)
        self.assertEqual(balance, {'microusd': 49255600, 'attempts': 765, 'native_counts': 387})
        pool.check_pool(state, balance['microusd'] - 5000000, balance['attempts'])
        with self.assertRaises(Deferred): pool.check_pool(state, balance['microusd'] - 5000000 + 1)
        with self.assertRaises(Deferred): pool.check_pool(state, 0, balance['attempts'] + 1)

    def test_idempotent_concurrent_and_restored_install_has_one_event(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(lambda _: self.install(), range(2)))
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            for p in self.path.rglob('*.json'): archive.write(p, p.relative_to(self.path).as_posix())
        target = self.path.parent/'restored'; executor.unpack_state(raw.getvalue(), target)
        self.path = target; self.install(); state = self.install().read()
        self.assertEqual(len(state['events']), len(self.original['events']) + 1)
        self.assertEqual(state['requests'], self.original['requests'])

    def test_original_and_intervening_history_tampering_or_duplicate_event_rejected(self):
        state = self.install().read()
        for mutation in ('request', 'event', 'duplicate', 'boolean', 'caps', 'owner', 'delete'):
            changed = copy.deepcopy(state)
            if mutation == 'request': changed['requests'][-1]['charged_microusd'] = 0
            elif mutation == 'event': changed['events'][-2]['sequence'] = 999
            elif mutation == 'duplicate': changed['events'].append(capacity.event())
            elif mutation == 'boolean': changed['events'][-1]['increment']['microusd'] = False
            elif mutation == 'caps': changed['max_requests'] = 1290
            elif mutation == 'owner': changed['logical_id'] = 'another-owner'
            else: changed['events'].pop()
            with self.subTest(mutation=mutation), self.assertRaises(ConfigurationFailure): pool.history(changed)

    def test_unamended_history_does_not_receive_new_capacity(self):
        self.assertEqual(pool.effective_plan(self.original), pool.plan())
        with self.assertRaises(Deferred): pool.check_pool(self.original, 0, 566)
        changed = copy.deepcopy(self.original); changed['max_requests'] = 1490
        with self.assertRaises(ConfigurationFailure): pool.history(changed)

    def test_native_prefix_capacity_and_closed_math_precede_dispatch(self):
        state = self.install().read()
        rows = self.rows + [{'id': f'cb-fc-new-{i}', 'status': 'dispatched_or_uncertain'} for i in range(386)]
        pool.check_count_budget(state, {'rows': rows}, {'id': 'cb-fc-new'})
        with self.assertRaises(Deferred):
            pool.check_count_budget(state, {'rows': rows + [{'id': 'cb-fc-last'}]}, {'id': 'cb-fc-new'})
        rows = copy.deepcopy(self.rows); rows[-1]['input_tokens'] += 1
        with self.assertRaises(ConfigurationFailure): capacity.validate_counts(state, rows)
        with self.assertRaisesRegex(Deferred, 'permanently_closed'):
            pool.check_count_budget(state, {'rows': self.rows}, {'id': 'cb-fc-i2-341997:verify'})

    def test_unverified_source_or_other_active_owner_cannot_install(self):
        for changes in ({'status': 'in_progress'}, {'digest': 'different'}, {'expired': True}):
            self.api_changes = changes
            with self.assertRaises(Deferred): self.install()
            self.assertEqual((self.path/'ledger.json').read_bytes(), self.before['ledger.json'])
        self.api_changes = {}; self.active = [{'id': 1000}]
        with self.assertRaises(Deferred): self.install()
        self.active = [{'id': 999}]; self.install()

    def test_cached_native_hit_checks_the_entire_new_prefix_before_return(self):
        self.install()
        body = tokens.count_body('retained cached count')
        cached = {'id': 'cb-fc-later', 'key': identity(tokens.count_projection(body)),
            'status': 'complete', 'input_tokens': 20}
        # No mocked success or network may replace rejection of altered history.
        for change in ('modified', 'deleted'):
            rows = copy.deepcopy(self.rows)
            if change == 'modified': rows[-1]['input_tokens'] += 1
            else: rows.pop()
            rows.append(cached)
            executor.checkpoint(self.path, token_preflight={'version': tokens.VERSION,
                'source_sha256': tokens.SOURCE_SHA, 'rows': rows})
            with self.subTest(change=change), self.assertRaisesRegex(ConfigurationFailure, 'capacity_native_history'):
                tokens.Counter(self.path, post=lambda *a, **kw: self.fail('no HTTP')).count(
                    {'id': 'cb-fc-later', 'body': body})

    def test_complete_starting_files_must_match_before_and_after_install(self):
        evidence = self.path/'diagnostics'/ (pool.FAILED + '.json')
        original = evidence.read_bytes(); evidence.write_bytes(b'{}')
        with self.assertRaises(ConfigurationFailure): self.install()
        evidence.write_bytes(original); self.install(); evidence.write_bytes(b'{}')
        with self.assertRaisesRegex(ConfigurationFailure, 'checkpoint_files_changed'): self.install()

    def test_crashes_on_each_side_of_atomic_write_recover_once(self):
        for point in ('before_atomic_write', 'after_atomic_write'):
            def crash(actual):
                if actual == point: raise OSError(point)
            with self.assertRaises(OSError): self.install(crash=crash)
            state = executor.ExperimentLedger(self.path/'ledger.json').read()
            self.assertEqual(capacity.validate(state), point == 'after_atomic_write')
        state = self.install().read()
        self.assertEqual(len(state['events']), len(self.original['events']) + 1)

    def test_interrupted_checkpoint_swap_can_only_recover_exact_ledger_transition(self):
        with patch.object(executor, 'checkpoint', side_effect=OSError('killed')):
            with self.assertRaises(OSError): self.install()
        self.assertEqual((self.path/'checkpoint.json').read_bytes(), self.before['checkpoint.json'])
        self.install(); pool.history(executor.ExperimentLedger(self.path/'ledger.json').read())

    def test_exact_zero_provider_selector_and_reservation_are_required(self):
        args = SimpleNamespace(action='prepare', state=self.path, reservation=self.path.parent/'reservation.json',
            result=self.path.parent/'result.json')
        with patch.object(executor, 'trusted_environment'), patch.object(executor, 'restore') as restore, \
                patch.object(capacity, 'install') as install, patch.dict(os.environ, {
                    'CONTEXTUAL_CHECK': json.dumps(capacity.SELECTOR), 'CONTEXTUAL_JOB': '',
                    'PACKET_HASH': '', 'PACKET_COMMIT': '', 'GITHUB_OUTPUT': str(self.path.parent/'output')}):
            capacity.run(args)
            self.assertEqual((self.path.parent/'output').read_text(), 'text_provider=none\n')
            self.assertEqual(json.loads(args.reservation.read_bytes()), capacity.reservation_record())
            restore.assert_called_once(); install.assert_called_once()
            for invalid in ({'iteration3_capacity': 'other'}, capacity.SELECTOR | {'scope_id': '341997'}):
                with patch.dict(os.environ, {'CONTEXTUAL_CHECK': json.dumps(invalid)}), self.assertRaises(ConfigurationFailure):
                    capacity.run(args)
            with patch.dict(os.environ, {'CONTEXTUAL_JOB': '{}'}), self.assertRaises(ConfigurationFailure): capacity.run(args)
            args.action = 'execute'; args.reservation.write_text('{}')
            with self.assertRaises(ConfigurationFailure): capacity.run(args)


class ProductionAuthority(unittest.TestCase):
    def test_exact_original_authority_and_new_zero_dollar_increment(self):
        p = capacity.plan()
        self.assertEqual(p['original_completion_authority_sha256'], identity(pool.plan()))
        self.assertEqual(p['increment'], {'microusd': 0, 'attempts': 200, 'native_counts': 100})
        self.assertEqual(p['source']['requests'], 718)
        self.assertEqual(p['source']['native_counts'], 200)


if __name__ == '__main__': unittest.main()
