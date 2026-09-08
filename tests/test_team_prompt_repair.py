"""Finite evaluation identity, baseline authority and reuse; no provider traffic."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

from scripts import build_opportunity_teams as teams
from tools import evaluate_team_prompt_repair as trial
from tools.offline_ai import Client, Ledger, ConfigurationFailure, atomic_json, config, identity
from tools.offline_team_contract import schemas


class TeamPromptRepairContracts(unittest.TestCase):
    def test_fresh_holdouts_preserve_original_inputs_and_all_acceptance_criteria(self):
        protocol, cases = trial.population()
        original = json.loads(Path('evaluation/offline_team_frozen.json').read_bytes())
        self.assertEqual(identity(original), '362444a7f5418f6306bdfc88483edae65cee8cfc557c2ada30991b59d372887d')
        self.assertEqual(len(cases), 24)
        self.assertEqual(sum(case['holdout'] for case in cases), 6)
        self.assertEqual(protocol['acceptance'], original['acceptance'])
        self.assertEqual(cases[:18], [case for case in original['cases'] if not case['holdout']])
        self.assertFalse({case['scope']['id'] for case in cases[18:]} &
                         {case['scope']['id'] for case in original['cases']})
        for case in cases[18:]:
            self.assertEqual(len(case['claims']), 24)
            self.assertTrue(case['scope']['source_url'].startswith('https://'))
            self.assertTrue(case['annotations']['source_quote'] in case['scope']['text'])

    def test_candidate_changes_only_wire_decomposition_prompt_not_validation_or_inputs(self):
        protocol, cases = trial.population()
        data = {'scope': cases[0]['scope']['text'], 'record_type': cases[0]['scope']['record_type']}
        before = copy.deepcopy(data)
        validate = Mock()
        delegate = Mock()
        settings = config()
        for route in ('sonnet', 'luna'):
            wrapper = trial.TrialClient(delegate, protocol, route)
            wrapper.json(settings['routes'][route], 'decomposition', teams.DECOMPOSE,
                         data, schemas()['decomposition'], validate,
                         stage_config=settings['stages']['decomposition'])
            args, kwargs = delegate.json.call_args
            self.assertEqual(args[2], teams.DECOMPOSE if route == 'sonnet' else protocol['candidate_decomposition_prompt'])
            self.assertIs(args[5], validate)
            self.assertEqual(args[3], before)
            self.assertEqual(kwargs['stage_config']['max_output_tokens'], settings['stages']['decomposition']['max_output_tokens'])
            wrapper.json(settings['routes'][route], 'verification', teams.VERIFY, data,
                         schemas()['verification'], validate)
            self.assertEqual(delegate.json.call_args.args[2], teams.VERIFY)
        self.assertEqual(data, before)

    def test_baseline_grant_is_once_and_cannot_clear_a_new_failure_or_change_protocol(self):
        protocol, _ = trial.population()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='test-only'):
            ledger = Ledger(Path(tmp) / 'ledger.json', trial.original.TASK, 15)
            token = ledger.reserve('anthropic', 'claude-sonnet-5', 'decomposition', 'historical', 88875, 1)
            ledger.complete(token, status='ConfigurationFailure')
            ledger.block('anthropic', 'anthropic_configuration_http_400')
            before = ledger.read()
            with self.assertRaises(ConfigurationFailure):
                trial.authorize_baseline(ledger, protocol, False)
            trial.authorize_baseline(ledger, protocol, True)
            self.assertEqual(before['requests'], ledger.read()['requests'])
            self.assertNotIn('anthropic', ledger.read()['blocked_providers'])
            trial.pause_outside_baseline(ledger)
            self.assertEqual(ledger.read()['blocked_providers']['anthropic'], trial.SCOPED_PAUSE)
            trial.authorize_baseline(ledger, protocol, False)  # Same finite baseline resumes.
            ledger.block('anthropic', 'anthropic_configuration_http_400')
            trial.authorize_baseline(ledger, protocol, True)
            self.assertEqual(ledger.read()['blocked_providers']['anthropic'], 'anthropic_configuration_http_400')
            trial.pause_outside_baseline(ledger)
            self.assertEqual(ledger.read()['blocked_providers']['anthropic'], 'anthropic_configuration_http_400')
            self.assertEqual(sum(e.get('kind') == trial.GRANT_EVENT for e in ledger.read()['events']), 1)
            with self.assertRaises(ConfigurationFailure):
                trial.authorize_baseline(ledger, protocol | {'changed': True}, True)

    def test_baseline_permission_does_not_clear_authentication_denial_or_missing_key(self):
        protocol, _ = trial.population()
        for reason in ('anthropic_configuration_http_401', 'anthropic_configuration_http_403', 'unexpected_returned_model_identity'):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='test-only'):
                ledger = Ledger(Path(tmp) / 'ledger.json', trial.original.TASK, 15)
                ledger.block('anthropic', reason)
                with self.assertRaises(ConfigurationFailure):
                    trial.authorize_baseline(ledger, protocol, True)
                self.assertEqual(ledger.read()['blocked_providers']['anthropic'], reason)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY=''):
            ledger = Ledger(Path(tmp) / 'ledger.json', trial.original.TASK, 15)
            ledger.block('anthropic', 'anthropic_configuration_http_400')
            with self.assertRaises(ConfigurationFailure):
                trial.authorize_baseline(ledger, protocol, True)
            self.assertFalse(ledger.read()['events'])

    def test_real_entrypoint_retains_charges_reuses_completed_baseline_and_keeps_production_pause(self):
        protocol, cases = trial.population()
        production_bytes = Path('config/offline_ai.json').read_bytes()
        value = {'specific': False, 'objective': 'Test fixture negative decision with sufficient explanation.', 'roles': []}
        response = Mock(status_code=200, json=Mock(return_value={
            'model': 'claude-sonnet-5', 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 100, 'output_tokens': 40},
            'content': [{'type': 'text', 'text': json.dumps(value)}]}))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='test-only',
                AUTHORIZE_ANTHROPIC_BASELINE='true'), patch.object(trial, 'population', return_value=(protocol, cases[:1])):
            state = Path(tmp)
            ledger = Ledger(state / 'ledger.json', trial.original.TASK, 15)
            token = ledger.reserve('anthropic', 'claude-sonnet-5', 'decomposition', 'historical', 88875, 1)
            ledger.complete(token, status='ConfigurationFailure')
            ledger.block('anthropic', 'anthropic_configuration_http_400')
            original_request = ledger.read()['requests'][0]
            with patch('sys.argv', ['trial', 'round2-sonnet', '--state', str(state)]), patch('requests.post', return_value=response) as post:
                trial.main()
                self.assertEqual(post.call_count, 1)
                self.assertEqual(post.call_args.args[0], 'https://api.anthropic.com/v1/messages')
                with patch.dict(os.environ, ANTHROPIC_API_KEY='', AUTHORIZE_ANTHROPIC_BASELINE='false'):
                    trial.main()
                self.assertEqual(post.call_count, 1)
            self.assertEqual(ledger.read()['requests'][0], original_request)
            self.assertEqual(len(ledger.read()['requests']), 2)
            self.assertEqual(ledger.read()['blocked_providers']['anthropic'], trial.SCOPED_PAUSE)
            with self.assertRaises(ConfigurationFailure):
                ledger.reserve('anthropic', 'claude-sonnet-5', 'verification', 'outside-baseline', 1, 1)
            self.assertNotIn('test-only', ledger.path.read_text())
        self.assertEqual(Path('config/offline_ai.json').read_bytes(), production_bytes)
        self.assertEqual(config()['generation_provider_pauses']['anthropic']['reason'], 'insufficient_credit')

    def test_valid_decisions_and_refusals_are_reused_but_changed_contract_fails_closed(self):
        protocol, cases = trial.population()
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial.original, 'evaluation_contract', return_value='unchanged-team-contract'), patch.object(trial.original, 'team_case',
                return_value={'scope_id': cases[0]['scope']['id'], 'holdout': False,
                              'state': 'not_specific', 'stages': {}}) as assess:
            directory = Path(tmp)
            client = Mock()
            first = trial.assess(client, directory, protocol, 'luna', cases[0])
            self.assertEqual(trial.assess(client, directory, protocol, 'luna', cases[0]), first)
            self.assertEqual(assess.call_count, 1)
            with self.assertRaises(ValueError):
                trial.assess(client, directory, protocol | {'changed': True}, 'luna', cases[0])
            path = directory / ('luna-' + identity(cases[0]) + '.json')
            atomic_json(path, first | {'state': 'provider_refusal'})
            self.assertEqual(trial.assess(client, directory, protocol, 'luna', cases[0])['state'], 'provider_refusal')
            self.assertEqual(assess.call_count, 1)

    def test_three_stage_trial_uses_original_validators_and_replays_exact_responses(self):
        protocol, cases = trial.population()
        decomposition = {'specific': True, 'objective': 'Investigate semiconductor structures and integrated optical components.',
            'roles': [{'id': 'role-1', 'label': 'Semiconductor structures', 'required': True,
                       'quote': 'novel semiconductor structures'},
                      {'id': 'role-2', 'label': 'Integrated optical components', 'required': True,
                       'quote': 'integrated optical components'}]}
        def reply(value):
            return Mock(status_code=200, json=Mock(return_value={'model': 'gpt-5.6-luna', 'status': 'completed',
                'usage': {'input_tokens': 80, 'output_tokens': 40},
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, OPENAI_API_KEY='test-only'):
            directory = Path(tmp)
            ledger = Ledger(directory / 'ledger.json', trial.original.TASK, 15)
            post = Mock(side_effect=[reply(decomposition), reply({'edges': []}), reply({'suitable_for_team': True, 'edges': []})])
            client = Client(ledger, directory / 'cache', post=post)
            row = trial.assess(client, directory / 'results', protocol, 'luna', cases[0])
            self.assertEqual(row['state'], 'insufficient_evidence')
            self.assertEqual(post.call_count, 3)
            self.assertEqual(post.call_args_list[0].kwargs['json']['instructions'], protocol['candidate_decomposition_prompt'])
            self.assertEqual(post.call_args_list[2].kwargs['json']['instructions'], teams.VERIFY)
            before = ledger.read()['requests']
            result = trial.replay(client, directory / 'results', protocol, cases[:1])
            self.assertEqual(result, {'completed_scopes_replayed': 1, 'new_provider_requests': 0})
            self.assertEqual(ledger.read()['requests'], before)

    def test_metrics_do_not_turn_execution_success_into_quality_promotion(self):
        _, cases = trial.population()
        rows = [{'state': 'not_specific'} for _ in cases]
        result = trial.metrics(cases, rows)
        self.assertEqual(result['completed'], 24)
        self.assertEqual(result['legitimate_acceptance'], 0)
        self.assertLess(result['scope_accuracy'], .9)

    def test_workflow_has_explicit_baseline_grant_and_no_anthropic_stability_or_replay_key(self):
        workflow = yaml.safe_load(Path('.github/workflows/offline-ai-evaluation.yml').read_bytes())
        steps = workflow['jobs']['evaluate']['steps']
        generation = next(s for s in steps if 'EVALUATION_PHASE' in s.get('env', {}))
        self.assertIn('round2-sonnet', generation['env']['ANTHROPIC_API_KEY'])
        self.assertNotIn('round2-stability', generation['env']['ANTHROPIC_API_KEY'])
        self.assertNotIn('round2-replay', generation['env']['ANTHROPIC_API_KEY'])
        self.assertIn("inputs.phase != 'round2-sonnet'", generation['env']['OPENAI_API_KEY'])
        self.assertIn("inputs.phase != 'round2-replay'", generation['env']['OPENAI_API_KEY'])
        self.assertIn('inputs.authorize_anthropic_baseline', generation['env']['AUTHORIZE_ANTHROPIC_BASELINE'])
        self.assertIn('tools.evaluate_team_prompt_repair', generation['run'])
        for step in steps:
            if step is not generation:
                self.assertNotIn('ANTHROPIC_API_KEY', step.get('env', {}))


if __name__ == '__main__':
    unittest.main()
