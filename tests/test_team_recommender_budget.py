import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from tools.team_recommender_budget import ExperimentLedger
from tools.offline_spend import Deferred, ConfigurationFailure


class BudgetContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.json'
        self.ledger = ExperimentLedger(self.path, initialize=True)

    def reserve(self, amount, key='one', provider='voyage', model='voyage-4-lite', attempt=1):
        return self.ledger.reserve_experiment(provider, model, 2, key, amount, attempt, trusted_route=True,input_tokens=10,output_tokens=512 if provider=='anthropic' else 0)

    def test_shared_stage_ceiling_and_restore(self):
        self.reserve(200_000)
        self.reserve(5_376_000, 'two', 'anthropic', 'claude-sonnet-5')
        self.ledger = ExperimentLedger(self.path)
        with self.assertRaises(Deferred): self.reserve(1, 'three')
        self.assertEqual(sum(r['charged_microusd'] for r in self.ledger.read()['requests']), 5_576_000)
        self.assertGreaterEqual(10_000_000 - sum(r['charged_microusd'] for r in self.ledger.read()['requests']), 4_000_000)
        self.assertEqual(self.ledger.read()['limit_microusd'], 10_000_000)

    def test_route_stage_and_base_api_cannot_bypass(self):
        with self.assertRaises(ConfigurationFailure): self.ledger.reserve_experiment('voyage', 'voyage-4-lite', 2, 'k', 100, 1)
        with self.assertRaises(ConfigurationFailure): self.ledger.reserve_experiment('voyage', 'voyage-4-lite', 3, 'k', 100, 1, trusted_route=True)
        with self.assertRaises(ConfigurationFailure): self.ledger.reserve('voyage', 'voyage-4-lite', 2, 'k', 100, 1)

    def test_uncertain_retries_reconcile_once(self):
        token = self.reserve(100_000)
        with self.assertRaises(Deferred): self.reserve(100_000, attempt=2)
        with self.assertRaises(Deferred): self.reserve(1, attempt=2)
        self.ledger.reconcile(token, cost_usd=.01, usage={'input_tokens': 50}, status='valid')
        self.ledger.reconcile(token, cost_usd=.01, usage={'input_tokens': 50}, status='valid')
        with self.assertRaises(ValueError): self.ledger.reconcile(token, cost_usd=0, usage={}, status='valid')
        self.assertEqual(sum(r['charged_microusd'] for r in self.ledger.read()['requests']), 10_000)

    def test_logical_claim_is_atomic_across_concurrent_ledger_instances(self):
        def request(_):
            try:
                ledger = ExperimentLedger(self.path)
                return ledger.reserve_experiment('voyage', 'voyage-4-lite', 2, 'same', 100, 1,
                    trusted_route=True, input_tokens=10)
            except Deferred:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(24)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.ledger.read()['requests']), 1)

    def test_all_retained_lifecycle_states_permanently_claim_the_key(self):
        for status in ('reserved_unknown', 'valid', 'failed', 'not_dispatched_unproven'):
            with self.subTest(status=status):
                token = self.reserve(100, key=status)
                state = self.ledger.read()
                next(r for r in state['requests'] if r['id'] == token)['status'] = status
                # Legacy rows also claim the key without new metadata/markers.
                next(r for r in state['requests'] if r['id'] == token).pop('dispatch_claim')
                self.path.write_text(json.dumps(state))
                for attempt in (1, 2):
                    with self.assertRaisesRegex(Deferred, 'already_claimed'):
                        self.reserve(100, key=status, attempt=attempt)

    def test_concurrent_reservations_are_atomic(self):
        def request(i):
            try: self.reserve(40_000, str(i)); return True
            except Deferred: return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(10)))
        self.assertEqual(sum(results), 5)

    def test_missing_or_mismatched_checkpoint_fails(self):
        with self.assertRaises(Deferred): ExperimentLedger(self.path.with_name('missing.json'))
        state = self.ledger.read(); state['logical_id'] = 'old-sonnet'
        self.path.write_text(json.dumps(state))
        with self.assertRaises(ValueError): ExperimentLedger(self.path)

    def test_unexpected_receipt_is_recorded_and_blocks_further_spend(self):
        token = self.reserve(10)
        with self.assertRaises(ValueError): self.ledger.reconcile(token, cost_usd=1, usage={}, status='valid')
        self.assertEqual(self.ledger.read()['requests'][0]['charged_microusd'], 1_000_000)
        with self.assertRaisesRegex(Deferred, 'overrun'):
            self.reserve(10, 'next')

    def test_finite_retry_and_later_stage_limits(self):
        self.reserve(10_000, 'one', 'anthropic', 'claude-sonnet-5')
        with self.assertRaisesRegex(Deferred, 'retry'):
            self.reserve(10_000, 'never-dispatched', 'anthropic', 'claude-sonnet-5', attempt=2)
        with self.assertRaises(ConfigurationFailure):
            self.ledger.reserve_experiment('anthropic','claude-sonnet-5',4,'four',10_000,1,
                trusted_route=True,approved_stage=4,input_tokens=10,output_tokens=512)

    def test_variable_packet_sizes_share_the_finite_token_envelope(self):
        for i in range(119):
            self.ledger.reserve_experiment('anthropic','claude-sonnet-5',2,str(i),35120,1,
                trusted_route=True,input_tokens=12000,output_tokens=512)
        with self.assertRaisesRegex(Deferred,'phase_envelope'):
            self.ledger.reserve_experiment('anthropic','claude-sonnet-5',2,'overflow',35120,1,
                trusted_route=True,input_tokens=12000,output_tokens=512)
        with self.assertRaisesRegex(ValueError,'underreserved'):
            self.ledger.reserve_experiment('anthropic','claude-sonnet-5',2,'under',1,1,
                trusted_route=True,input_tokens=100,output_tokens=512)
