"""Focused established-route evaluation preserves evidence, budgets and pauses."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from tools import evaluate_established_sonnet as probe
from tools.offline_ai import Client, Ledger, ConfigurationFailure, atomic_json, config, identity
from tools.offline_team_contract import schemas
from scripts import build_opportunity_teams as teams
from scripts import subtopic_cov4 as gate


class EstablishedSonnetTests(unittest.TestCase):
    def test_frozen_failure_population_and_criteria_are_preserved(self):
        protocol, cases = probe.population()
        self.assertEqual(len(cases), 9)
        self.assertEqual(set(protocol['cases']), set(protocol['required_source_checks']))
        self.assertTrue({'361050', '361526:g-12', '362218', '361205', '356811'} <= set(protocol['cases']))
        self.assertEqual(protocol['acceptance'], probe.trial.population()[0]['acceptance'])
        self.assertEqual(len(protocol['cov4_cases']), 2)
        for stage, prompt in protocol['prompts'].items():
            self.assertIn('Return JSON only', prompt)
        self.assertIn('explicitly essential', protocol['prompts']['decomposition'])
        self.assertIn('does not by itself establish', protocol['prompts']['verification'])

    def test_wire_repair_preserves_input_schema_validator_model_and_cap(self):
        protocol, cases = probe.population()
        delegate, validate = Mock(), Mock()
        data = {'scope': cases[0]['scope']['text']}
        before = copy.deepcopy(data)
        for name, prompt in [('decomposition', teams.DECOMPOSE), ('adjudication', teams.ADJUDICATE), ('verification', teams.VERIFY)]:
            settings = config()['stages'][name] | {'max_output_tokens': 8000}
            probe.RepairClient(delegate, protocol).json(config()['routes']['sonnet'], name, prompt,
                data, schemas()[name], validate, stage_config=settings)
            args, kwargs = delegate.json.call_args
            self.assertEqual(args[2], protocol['prompts'][name])
            self.assertEqual(args[3], before)
            self.assertEqual(args[4], schemas()[name])
            self.assertIs(args[5], validate)
            self.assertEqual(kwargs['stage_config'], settings | {'prompt_version': protocol['version']})
        with self.assertRaises(ValueError):
            probe.RepairClient(delegate, protocol).json(config()['routes']['luna'], 'decomposition', teams.DECOMPOSE,
                data, schemas()['decomposition'], validate)

    def test_grant_cannot_clear_new_billing_security_or_configuration_stop(self):
        protocol, _ = probe.population()
        for reason in ('insufficient_credit', 'anthropic_configuration_http_400', 'anthropic_configuration_http_401',
                       'anthropic_configuration_http_403', 'unexpected_returned_model_identity'):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='test-only'):
                ledger = Ledger(Path(tmp) / 'ledger.json', probe.original.TASK, 15)
                ledger.block('anthropic', probe.trial.SCOPED_PAUSE)
                probe.authorize(ledger, protocol, 'recovery-sonnet')
                ledger.block('anthropic', reason)
                before = ledger.path.read_bytes()
                with self.assertRaises(ConfigurationFailure):
                    probe.authorize(ledger, protocol, 'recovery-sonnet')
                probe.pause(ledger)
                self.assertEqual(ledger.path.read_bytes(), before)

    def test_real_entrypoint_resumes_exact_decision_and_replays_without_requests_or_ledger_change(self):
        protocol, cases = probe.population()
        value = {'specific': False, 'objective': 'Explicitly rejected negative test fixture.', 'roles': []}
        response = Mock(status_code=200, json=Mock(return_value={'model': 'claude-sonnet-5', 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 80, 'output_tokens': 40}, 'content': [{'type': 'text', 'text': json.dumps(value)}]}))
        production = Path('config/offline_ai.json').read_bytes()
        with tempfile.TemporaryDirectory() as tmp, patch.object(probe, 'population', return_value=(protocol, cases[:1])), \
                patch.dict(os.environ, ANTHROPIC_API_KEY='test-only'):
            state = Path(tmp)
            ledger = Ledger(state / 'ledger.json', probe.original.TASK, 15)
            token = ledger.reserve('anthropic', 'claude-sonnet-5', 'decomposition', 'old-charge', 88875, 1)
            ledger.complete(token, status='ConfigurationFailure')
            ledger.block('anthropic', probe.trial.SCOPED_PAUSE)
            prior = ledger.read()['requests'][0]
            with patch('requests.post', return_value=response) as post, patch('sys.argv', ['probe', 'recovery-sonnet', '--state', tmp]):
                probe.main()
                probe.main()
                self.assertEqual(post.call_count, 1)
            self.assertEqual(ledger.read()['requests'][0], prior)
            before = ledger.path.read_bytes()
            with patch('requests.post', side_effect=AssertionError('replay must be offline')), \
                    patch('sys.argv', ['probe', 'recovery-replay', '--state', tmp]):
                probe.main()
            self.assertEqual(before, ledger.path.read_bytes())
            self.assertEqual(ledger.read()['blocked_providers']['anthropic'], probe.PAUSE)
            row = next((state / protocol['version']).glob('team-*.json'))
            retained = json.loads(row.read_bytes()); retained['state'] = 'proposed'; atomic_json(row, retained)
            with patch('sys.argv', ['probe', 'recovery-sonnet', '--state', tmp]), self.assertRaises(ValueError):
                probe.main()
        self.assertEqual(production, Path('config/offline_ai.json').read_bytes())

    def test_cov4_calls_unchanged_production_request_and_records_separate_access_result(self):
        protocol, _ = probe.population()
        responses = [Mock(status_code=200, json=Mock(return_value={'model': gate.MODEL,
            'usage': {'input_tokens': 100, 'output_tokens': 30}, 'content': [{'type': 'text',
                'text': json.dumps({'owned': 'yes', 'fundable': answer, 'reason': 'Frozen access contract fixture.'})}]}))
            for answer in ('yes', 'no')]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='test-only'):
            ledger = Ledger(Path(tmp) / 'ledger.json', probe.original.TASK, 15)
            with patch('requests.post', side_effect=responses) as post:
                result = probe.cov4(ledger, Path(tmp), protocol)
            self.assertTrue(result['access_contract_passed'])
            self.assertEqual(result['production_topics_published'], 0)
            self.assertEqual(post.call_count, 2)
            for call in post.call_args_list:
                self.assertEqual(call.args, (gate.API_URL,))
                self.assertEqual(set(call.kwargs['json']), {'model', 'max_tokens', 'messages'})
                self.assertEqual(call.kwargs['json']['model'], gate.MODEL)
                self.assertEqual(call.kwargs['json']['max_tokens'], gate.MAX_TOKENS)
            with patch('requests.post', side_effect=AssertionError('reuse completed checks')):
                self.assertTrue(probe.cov4(ledger, Path(tmp), protocol)['access_contract_passed'])
            self.assertEqual(len(ledger.read()['requests']), 2)

    def test_cov4_missing_or_different_serving_model_fails_closed_and_stops_calls(self):
        protocol, _ = probe.population()
        for model in (None, 'unverified-build'):
            response = Mock(status_code=200, json=Mock(return_value={'model': model}))
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='test-only'):
                ledger = Ledger(Path(tmp) / 'ledger.json', probe.original.TASK, 15)
                with patch('requests.post', return_value=response) as post:
                    result = probe.cov4(ledger, Path(tmp), protocol)
                self.assertFalse(result['access_contract_passed'])
                self.assertEqual(post.call_count, 1)
                self.assertEqual(ledger.read()['blocked_providers']['anthropic'], 'unexpected_returned_model_identity')

    def test_workflow_confines_keys_and_restores_one_shared_budget(self):
        workflow = yaml.safe_load(Path('.github/workflows/offline-ai-evaluation.yml').read_bytes())
        steps = workflow['jobs']['evaluate']['steps']
        step = next(step for step in steps if 'EVALUATION_PHASE' in step.get('env', {}))
        for phase in ('recovery-sonnet', 'cov4-sonnet', 'recovery-replay'):
            self.assertIn("inputs.phase != '" + phase + "'", step['env']['OPENAI_API_KEY'])
        self.assertNotIn('recovery-replay', step['env']['ANTHROPIC_API_KEY'])
        self.assertIn('tools.offline_ai_checkpoint', str(steps))
        self.assertIn('tools.evaluate_established_sonnet', step['run'])


if __name__ == '__main__':
    unittest.main()
