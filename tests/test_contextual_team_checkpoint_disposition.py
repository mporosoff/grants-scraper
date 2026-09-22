"""Aggregate unknown exposure uses existing budget, without invented usage."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_contextual_team_completion_policy as budget_fixture
from tools import contextual_team_checkpoint_disposition as disposition
from tools import contextual_team_completion_policy as pool
from tools import contextual_team_iteration2_policy as iteration2
from tools import contextual_team_token_preflight as tokens
from tools import team_recommender_budget as budget
from tools import team_recommender_executor as existing
from tools.offline_spend import atomic_json, identity, ConfigurationFailure, Deferred


def fixture_plan(state, counts):
    """Bind synthetic history to the same exact disposition shape; no live data."""
    p = copy.deepcopy(disposition.plan())
    p['prior'].update(requests=len(state['requests']), requests_sha256=identity(state['requests']),
        events=len(state['events']), events_sha256=identity(state['events']),
        native_counts=len(counts), native_counts_sha256=identity(counts))
    return p


class CheckpointDisposition(unittest.TestCase):
    def setUp(self):
        self.fixture = budget_fixture.CompletionBudget('runTest'); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.state
        self.state = self.fixture.install().read()
        self.counts = copy.deepcopy(self.fixture.counts)
        self.p = fixture_plan(self.state, self.counts)
        self.bind(patch.object(disposition, 'plan', return_value=self.p))
        self.prior = copy.deepcopy(self.state)
        self.state['events'].append(disposition.event())
        atomic_json(self.path/'ledger.json', self.state)

    def bind(self, value):
        result = value.start(); self.addCleanup(value.stop); return result

    def test_old_checkpoints_have_no_aggregate_exposure(self):
        self.assertEqual(disposition.exposure(self.prior), disposition.ZERO)
        with patch.object(disposition, 'plan', side_effect=AssertionError('historical state does not need new pins')):
            self.assertEqual(disposition.exposure({'events': []}), disposition.ZERO)
        self.assertEqual(disposition.exposure(self.state), self.p['hold'])
        self.assertEqual(self.state['requests'], self.prior['requests'])
        self.assertEqual(self.state['events'][:-1], self.prior['events'])

    def test_duplicate_conflicting_typed_and_usage_events_fail_closed(self):
        for change in ('duplicate', 'amount', 'usage', 'boolean', 'authority', 'position'):
            state = copy.deepcopy(self.state)
            if change == 'duplicate': state['events'].append(disposition.event())
            elif change == 'amount': state['events'][-1]['exposure']['microusd'] -= 1
            elif change == 'usage': state['events'][-1]['actual_usage'] = {'input_tokens': 1}
            elif change == 'boolean': state['events'][-1]['exposure']['native_counts'] = True
            elif change == 'authority': state['events'][-1]['authority'] = 'unrecognized'
            else: state['events'].insert(-1, {'kind': 'intervening_unverified_event'})
            with self.subTest(change=change), self.assertRaises(ConfigurationFailure):
                disposition.exposure(state)

    def test_original_history_and_unknown_holds_cannot_change(self):
        for collection, index, field in (('requests', 0, 'charged_microusd'),
                ('requests', 682, 'charged_microusd'), ('events', 0, 'sequence')):
            state = copy.deepcopy(self.state); state[collection][index][field] += 1
            with self.assertRaises(ConfigurationFailure): disposition.exposure(state)
        state = copy.deepcopy(self.state); state['requests'].pop()
        with self.assertRaises(ConfigurationFailure): disposition.exposure(state)

    def test_all_math_operations_and_count_ids_are_closed_without_rekey(self):
        for stage in ('interpret', 'query', 'assess', 'verify', 'check', 'changed-contract'):
            with self.assertRaisesRegex(Deferred, 'permanently_closed'):
                disposition.assert_operation_open(self.state, 'cb-fc-i2-341997:' + stage)
        disposition.assert_operation_open(self.state, 'cb-fc-i2-363302:a-1:check')
        # A new iteration, changed contract or child-shaped scope cannot reopen
        # the permanently closed source under another purpose namespace.
        for purpose in ('cb-fc-i3-341997:assess', 'cb-fc-i3-341997:integrity',
                'cb-fc-i3-341997:a-1:check', 'cb-fc-i4-341997:changed-contract'):
            with self.assertRaisesRegex(Deferred, 'permanently_closed'):
                disposition.assert_operation_open(self.state, purpose)
        disposition.assert_operation_open(self.state, 'cb-fc-i3-3419970:check')
        for collection, item in (('requests', {'purpose': 'cb-fc-i2-341997:assess'}),
                ('events', {'purpose': 'cb-fc-i2-341997:verify'})):
            state = copy.deepcopy(self.state); state[collection].append(item)
            with self.assertRaises(ConfigurationFailure): disposition.validate(state)

    def test_count_prefix_and_future_math_counts_cannot_be_fabricated(self):
        disposition.validate_counts(self.state, self.counts)
        changed = copy.deepcopy(self.counts); changed[0]['input_tokens'] += 1
        with self.assertRaises(ConfigurationFailure): disposition.validate_counts(self.state, changed)
        with self.assertRaises(ConfigurationFailure):
            disposition.validate_counts(self.state, self.counts + [{'id': 'cb-fc-i2-341997:verify'}])
        with self.assertRaises(ConfigurationFailure):
            disposition.validate_counts(self.state, self.counts + [{'id': 'cb-fc-i3-341997:verify'}])

    def test_pool_limits_deduct_hold_once_and_preserve_both_reserves(self):
        available = 45000000 - 713400
        pool.check_pool(self.state, available, 596)
        with self.assertRaises(Deferred): pool.check_pool(self.state, available + 1, 1)
        with self.assertRaises(Deferred): pool.check_pool(self.state, 1, 597)
        state = copy.deepcopy(self.state)
        state['requests'].append({'charged_microusd': available, 'purpose': 'unrelated'})
        pool.check_pool(state)
        with self.assertRaises(Deferred): pool.check_pool(state, 1)
        self.assertEqual(disposition.exposure(state), self.p['hold'])

    def test_lifetime_dollar_and_attempt_caps_also_deduct_hold(self):
        p = copy.deepcopy(pool.plan())
        spent = sum(r['charged_microusd'] for r in self.state['requests'])
        p['lifetime']['microusd'] = spent + 713400 + 1267862 + 5000000 + 10
        p['lifetime']['attempts'] = len(self.state['requests']) + 4 + 2 + 1
        with patch.object(pool, 'plan', return_value=p), patch.object(pool, 'history'):
            pool.check_pool(self.state, 10, 1)
            with self.assertRaises(Deferred): pool.check_pool(self.state, 11, 1)
            with self.assertRaises(Deferred): pool.check_pool(self.state, 1, 2)

    def test_native_incremental_and_lifetime_caps_deduct_one_unknown(self):
        rows = self.counts + [{'id': 'cb-fc-new-'+str(i)} for i in range(298)]
        pool.check_count_budget(self.state, {'rows': rows}, {'id': 'cb-fc-other'})
        with self.assertRaises(Deferred):
            pool.check_count_budget(self.state, {'rows': rows + [{'id': 'cb-fc-extra'}]}, {'id': 'cb-fc-other'})
        p = copy.deepcopy(pool.plan()); p['lifetime']['native_counts'] = len(self.counts) + 1
        with patch.object(pool, 'plan', return_value=p), patch.object(pool, 'history'):
            with self.assertRaises(Deferred):
                pool.check_count_budget(self.state, {'rows': self.counts}, {'id': 'cb-fc-other'})

    def test_counter_math_closure_precedes_cached_body_reuse(self):
        body = tokens.count_body('synthetic cached body')
        self.counts.append({'id': 'cb-fc-other', 'key': identity(body), 'status': 'complete', 'input_tokens': 1})
        self.p['prior'].update(native_counts=len(self.counts), native_counts_sha256=identity(self.counts))
        self.state['events'][-1] = disposition.event(); atomic_json(self.path/'ledger.json', self.state)
        existing.checkpoint(self.path, token_preflight={'version': tokens.VERSION,
            'source_sha256': tokens.SOURCE_SHA, 'rows': self.counts})
        before = (self.path/'checkpoint.json').read_bytes()
        forbidden = lambda *a, **kw: self.fail('provider must not be reached')
        with self.assertRaisesRegex(Deferred, 'permanently_closed'):
            tokens.Counter(self.path, post=forbidden).count({'id': 'cb-fc-i2-341997:verify', 'body': body})
        self.assertEqual((self.path/'checkpoint.json').read_bytes(), before)

    def test_remaining_and_reservation_report_unknown_separately(self):
        with patch.object(iteration2, 'history'), patch.object(iteration2, 'check_counts', return_value=self.counts):
            balance = iteration2.remaining(self.state, self.path)
            self.assertEqual(balance, {'microusd': 49286600, 'attempts': 596, 'native_counts': 299})
            record = iteration2.prepare_record(self.path, {'job_id': 'a'*64, 'scope_id': '363302:a-1'})
            self.assertEqual(record['aggregate_unknown_exposure'], self.p['hold'])
            self.assertEqual(record['remaining_completion_allowance'], balance)
            with self.assertRaisesRegex(Deferred, 'permanently_closed'):
                iteration2.prepare_record(self.path, {'job_id': self.p['failed']['job_id'], 'scope_id': '341997'})

    def test_old_paid_routes_cannot_escape_aggregate_attempt_hold(self):
        ledger = budget.ExperimentLedger(self.path/'ledger.json')
        with patch('tools.contextual_team_policy.check_reservation'):
            with self.assertRaisesRegex(Deferred, 'total_budget_exhausted'):
                ledger.reserve_experiment('anthropic', 'claude-sonnet-5', 2, 'a'*64, 12, 1,
                    trusted_route=True, input_tokens=1, output_tokens=1,
                    execution_metadata={'purpose': 'cb-historical', 'row_inputs': []})
        self.assertEqual(ledger.read(), self.state)

    def test_concurrent_reservations_preserve_held_attempts_exactly_once(self):
        self.state['requests'].extend({'id': str(i), 'key': 'existing-'+str(i), 'charged_microusd': 0,
            'provider': 'anthropic', 'stage': 2, 'status': 'valid'}
            for i in range(595))
        atomic_json(self.path/'ledger.json', self.state)
        def claim(i):
            try:
                return budget.ExperimentLedger(self.path/'ledger.json').reserve_experiment(
                    'anthropic', 'claude-sonnet-5', 2, str(i), 12, 1,
                    trusted_route=True, input_tokens=1, output_tokens=1,
                    execution_metadata={'purpose': 'cb-fc-fixture', 'row_inputs': []})
            except Deferred:
                return None
        with patch('tools.contextual_team_policy.check_reservation'), ThreadPoolExecutor(max_workers=3) as executor:
            result = list(executor.map(claim, range(3)))
        self.assertEqual(sum(v is not None for v in result), 1)
        state = budget.ExperimentLedger(self.path/'ledger.json').read()
        self.assertEqual(len(state['requests']) - len(self.prior['requests']) + disposition.exposure(state)['attempts'], 600)


class DeployedDispositionPlan(unittest.TestCase):
    def test_exact_raw_config_and_reservation_scope_identity(self):
        p = disposition.plan()
        self.assertEqual(p['prior']['requests'], 694)
        self.assertEqual(p['prior']['events'], 30)
        self.assertEqual(p['prior']['native_counts'], 191)
        self.assertEqual(p['failed']['job_id'], identity([p['failed']['release_id'], '341997', '']))
        self.assertNotIn(b'\r', (disposition.ROOT/'config/contextual_team/iteration2-checkpoint-disposition-v1.json').read_bytes())
