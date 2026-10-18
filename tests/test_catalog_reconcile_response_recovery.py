"""Recover accepted usage across changed requests without returning old vectors."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_catalog_reconcile_spend as fixtures
from tools import catalog_reconcile_spend as spend
from tools.offline_spend import Deferred, LinkedLedger, atomic_json, identity


class AcceptedResponseRecovery(unittest.TestCase):
    setUp = fixtures.ReconcileSpendTests.setUp
    packet = fixtures.ReconcileSpendTests.packet
    finish_packet = fixtures.ReconcileSpendTests.finish_packet
    changed_operation = fixtures.ReconcileSpendTests.changed_operation
    generation = fixtures.ReconcileSpendTests.generation

    def accepted_unknown(self):
        reserved = spend.reserve(self.state, self.packet())
        with patch.object(spend, 'complete_saved', side_effect=RuntimeError('after accepted response persistence')):
            with self.assertRaises(RuntimeError):
                spend.finish(self.state, self.finish_packet(reserved))
        return reserved

    def row(self, token):
        return next(row for row in self.book.read()['requests'] if row['id'] == token)

    def test_changed_body_and_batch_size_settle_original_response_then_defer_without_new_reservation(self):
        old = self.accepted_unknown(); self.changed_operation()
        changed = self.packet('Changed reviewed scientific passage')
        body = json.loads(changed['body']); body['input'].append('Second new passage')
        changed['body'] = json.dumps(body)
        before = deepcopy(self.book.read())
        with self.assertRaisesRegex(Deferred, 'previous_operation_response_recovered_retry_generation'):
            spend.reserve(self.state, changed)
        current = self.book.read()
        self.assertEqual(len(current['requests']), len(before['requests']))
        self.assertEqual(current['requests'][:-1], before['requests'][:-1])
        self.assertEqual((self.row(old['token'])['status'], self.row(old['token'])['charged_microusd']), ('valid', 2))
        # The old vector is not returned for this new body/space. A later call
        # reserves fresh work under the same original allowance.
        self.assertEqual(spend.reserve(self.state, changed)['status'], 'reserved')
        self.assertEqual(self.book.read()['limit_microusd'], 2_000_000)

    def test_original_accepted_usage_is_settled_even_if_current_request_already_has_a_cache(self):
        old = self.accepted_unknown(); self.changed_operation()
        intent = self.state / 'vector-intents' / (old['key'] + '.json')
        hidden = intent.with_suffix('.fixture-retained')
        intent.rename(hidden)
        try:
            # Reproduce state the old implementation could already retain:
            # a new operation completed while the old accepted row stayed unknown.
            current_packet = self.packet('New operation public passage')
            current = spend.reserve(self.state, current_packet)
            spend.finish(self.state, self.finish_packet(current))
        finally:
            hidden.rename(intent)
        before_count = len(self.book.read()['requests'])
        with self.assertRaisesRegex(Deferred, 'previous_operation_response_recovered_retry_generation'):
            spend.reserve(self.state, current_packet)
        self.assertEqual(self.row(old['token'])['status'], 'valid')
        self.assertEqual(len(self.book.read()['requests']), before_count)
        self.assertEqual(spend.reserve(self.state, current_packet)['status'], 'cached')

    def test_changed_body_without_accepted_cache_keeps_unknown_charge(self):
        old = spend.reserve(self.state, self.packet()); before = deepcopy(self.row(old['token']))
        self.changed_operation()
        self.assertEqual(spend.reserve(self.state, self.packet('Genuinely changed corpus input'))['status'], 'reserved')
        self.assertEqual(self.row(old['token']), before)

    def test_same_body_without_accepted_cache_cannot_redispatch_under_changed_operation(self):
        spend.reserve(self.state, self.packet()); before = deepcopy(self.book.read())
        self.changed_operation()
        with self.assertRaisesRegex(ValueError, 'previous_operation_dispatch_unknown_no_retry'):
            spend.reserve(self.state, self.packet())
        self.assertEqual(self.book.read(), before)

    def test_old_cache_and_intent_identity_tampering_cannot_settle_or_reserve(self):
        old = self.accepted_unknown(); self.changed_operation()
        intent_path = self.state / 'vector-intents' / (old['key'] + '.json')
        cache_path = self.state / 'vector-responses' / (old['key'] + '.json')
        intent, cached = json.loads(intent_path.read_bytes()), json.loads(cache_path.read_bytes())
        before = deepcopy(self.book.read())
        cases = [('cache', field, value) for field, value in (
            ('token', 'wrong'), ('operation_sha256', 'f' * 64), ('body_sha256', 'f' * 64),
            ('response_sha256', 'f' * 64))]
        cases += [('intent', field, value) for field, value in (
            ('key', 'f' * 64), ('body_sha256', 'f' * 64), ('input_count', 2), ('input_count', True))]
        for kind, field, value in cases:
            with self.subTest(kind=kind, field=field, value=value):
                atomic_json(intent_path, dict(intent, **{field: value}) if kind == 'intent' else intent)
                atomic_json(cache_path, dict(cached, **{field: value}) if kind == 'cache' else cached)
                with self.assertRaises(ValueError):
                    spend.reserve(self.state, self.packet('Changed public input'))
                self.assertEqual(self.book.read(), before)

    def test_settlement_releases_only_known_overcharge_at_original_budget_boundary(self):
        old = self.accepted_unknown()
        spent = sum(row['charged_microusd'] for row in self.book.read()['requests'])
        amount = self.book.limit - spent - 10
        prior = self.book.reserve('anthropic', 'prior-model', 'completed-other-work', 'budget-boundary', amount, 1)
        self.book.complete(prior, status='valid', charged_microusd=amount)
        self.changed_operation()
        packet = self.packet('Changed scientific funding passage')
        before_count = len(self.book.read()['requests'])
        with self.assertRaisesRegex(Deferred, 'previous_operation_response_recovered_retry_generation'):
            spend.reserve(self.state, packet)
        self.assertEqual(len(self.book.read()['requests']), before_count)
        self.assertEqual(self.row(old['token'])['charged_microusd'], 2)
        self.assertEqual(spend.reserve(self.state, packet)['status'], 'reserved')
        self.assertEqual((self.book.read()['logical_id'], self.book.read()['max_requests']), ('offline-123', 300))

    def test_changed_generation_recovers_both_linked_ledgers_without_new_task_spending(self):
        state, book, task = self.generation('pilot'); linked = LinkedLedger(book, task)
        with patch.object(spend, 'production_ledger', return_value=linked):
            old = spend.reserve(state, self.packet(), generation=True)
            original_complete = book.complete
            def interrupt(token, **result):
                if result.get('status') == 'valid':
                    raise RuntimeError('task settled before local completion')
                original_complete(token, **result)
            with patch.object(book, 'complete', side_effect=interrupt):
                with self.assertRaises(RuntimeError):
                    spend.finish(state, self.finish_packet(old), generation=True)
            context = json.loads((state / 'vector-operation.json').read_bytes())
            context['operation_contract']['corpus_sha256'] = 'e' * 64
            context.pop('operation_sha256'); context['operation_sha256'] = identity(context)
            atomic_json(state / 'vector-operation.json', context)
            with self.assertRaisesRegex(Deferred, 'previous_operation_response_recovered_retry_generation'):
                spend.reserve(state, self.packet('Changed pilot corpus'), generation=True)
        self.assertEqual(len(task.read()['requests']), 1)
        self.assertEqual(task.read()['requests'][0]['charged_microusd'], 2)
        self.assertEqual((book.read()['requests'][-1]['status'], book.read()['requests'][-1]['charged_microusd']), ('valid', 2))


if __name__ == '__main__':
    unittest.main()
