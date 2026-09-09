"""The incremental grant cannot replay provider work or reset prior spending."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import evaluate_sonnet_verification as repair
from tools.offline_ai import ConfigurationFailure, Deferred, atomic_json, config, identity


class VerificationRepairTests(unittest.TestCase):
    def test_population_preserves_criteria_and_only_repairs_verification(self):
        protocol, prior, cases = repair.population()
        self.assertEqual(len(cases), 9)
        self.assertEqual(protocol['acceptance'], prior['acceptance'])
        self.assertTrue(protocol['prompt'].startswith(prior['prompts']['verification']))
        self.assertIn('actual operation', protocol['prompt'])
        self.assertIn('adjacent', protocol['prompt'])
        self.assertEqual(config()['max_requests'], 300)
        self.assertEqual(config()['budgets_usd']['evaluation'], 15)

    def fixture(self, root):
        protocol = copy.deepcopy(repair.population()[0])
        state = {'version': 1, 'logical_id': repair.original.TASK, 'max_requests': 300,
                 'limit_microusd': 15_000_000, 'requests': [{'id': str(i), 'charged_microusd': 10}
                    for i in range(295)], 'events': [{'kind': 'historical_failure'}],
                 'blocked_providers': {'anthropic': repair.previous.PAUSE, 'openai': 'prior_stop'}}
        protocol['prior_ledger_sha256'] = identity(state)
        protocol['prior_requests_sha256'] = identity(state['requests'])
        path, manifest = root / 'ledger.json', root / 'protocol.json'
        atomic_json(path, state)
        atomic_json(manifest, protocol)
        return protocol, state, path, manifest

    def test_ceiling_grant_preserves_every_old_request_event_and_pause_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, old, path, manifest = self.fixture(Path(directory))
            with patch.object(repair, 'PROTOCOL', manifest):
                ledger = repair.VerificationLedger(path, protocol, migrate=True)
                state = ledger.read()
                self.assertEqual(state['requests'], old['requests'])
                self.assertEqual(state['events'][:-1], old['events'])
                self.assertEqual(state['blocked_providers'], old['blocked_providers'])
                self.assertEqual(state['limit_microusd'], old['limit_microusd'])
                before = path.read_bytes()
                repair.VerificationLedger(path, protocol, migrate=True)
                self.assertEqual(path.read_bytes(), before)
                with self.assertRaises(ConfigurationFailure):
                    ledger.reserve('anthropic', config()['routes']['sonnet']['model'], 'verification', 'key', 1, 0)

    def test_grant_fails_closed_for_missing_modified_or_foreign_history(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, old, path, manifest = self.fixture(Path(directory))
            with patch.object(repair, 'PROTOCOL', manifest):
                for changed in (old | {'logical_id': 'production'}, old | {'requests': old['requests'][:-1]},
                                old | {'blocked_providers': {}}):
                    atomic_json(path, changed)
                    before = path.read_bytes()
                    with self.assertRaises(ValueError):
                        repair.VerificationLedger(path, protocol, migrate=True)
                    self.assertEqual(path.read_bytes(), before)
                path.unlink()
                with self.assertRaises(FileNotFoundError):
                    repair.VerificationLedger(path, protocol, migrate=True)
                self.assertFalse(path.exists())

    def test_only_twelve_verifier_reservations_including_retries_are_available(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol, old, path, manifest = self.fixture(Path(directory))
            with patch.object(repair, 'PROTOCOL', manifest):
                ledger = repair.VerificationLedger(path, protocol, migrate=True)
                with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-only'}):
                    repair.previous.authorize(ledger, protocol, 'verification-sonnet')
                model = config()['routes']['sonnet']['model']
                for provider, stage in [('openai', 'verification'), ('anthropic', 'adjudication'),
                                        ('anthropic', 'decomposition'), ('anthropic', 'cov4')]:
                    with self.assertRaises(ConfigurationFailure):
                        ledger.reserve(provider, model, stage, 'key', 1, 0)
                for attempt in range(12):
                    ledger.reserve('anthropic', model, 'verification', 'key', 1, attempt)
                with self.assertRaises(Deferred):
                    ledger.reserve('anthropic', model, 'verification', 'key', 1, 12)
                self.assertEqual(len(ledger.read()['requests']), 307)
                self.assertEqual(ledger.read()['requests'][:295], old['requests'])
                repair.previous.pause(ledger)
                self.assertEqual(ledger.read()['blocked_providers'], old['blocked_providers'])

    def test_missing_earlier_cache_never_falls_back_to_paid_transport(self):
        protocol, prior, _ = repair.population()
        paid = Mock()
        with tempfile.TemporaryDirectory() as directory:
            client = repair.StageClient(repair.trial.ReplayClient(Path(directory)), paid, protocol, prior)
            with self.assertRaises(ValueError):
                client.json(config()['routes']['sonnet'], 'decomposition', 'ignored', {}, {}, lambda x: x)
            paid.json.assert_not_called()

    def test_stage_routing_preserves_earlier_prompt_identity_and_changes_only_verification(self):
        protocol, prior, _ = repair.population()
        readonly, paid = Mock(), Mock()
        client = repair.StageClient(readonly, paid, protocol, prior)
        route = config()['routes']['sonnet']
        for stage in ('decomposition', 'adjudication', 'verification'):
            client.json(route, stage, 'original', {'scope': 'frozen'}, {}, lambda x: x)
        self.assertEqual([call.args[1] for call in readonly.json.call_args_list], ['decomposition', 'adjudication'])
        self.assertEqual([call.args[1] for call in paid.json.call_args_list], ['verification'])
        self.assertEqual(paid.json.call_args.args[2], protocol['prompt'])
        for call in readonly.json.call_args_list:
            self.assertEqual(call.args[2], prior['prompts'][call.args[1]])
            self.assertEqual(call.kwargs['stage_config']['prompt_version'], prior['version'])


if __name__ == '__main__':
    unittest.main()
