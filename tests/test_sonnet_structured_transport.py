"""The real shared client: shape, stage reuse, retries and durable authorization."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import offline_ai as ai
from tools.offline_team_contract import schemas
from tools.offline_spend import authorize_allowance, restore_ledger


def sonnet_response(value, stop='end_turn'):
    return Mock(status_code=200, json=Mock(return_value={
        'model': 'claude-sonnet-5', 'stop_reason': stop,
        'usage': {'input_tokens': 100, 'output_tokens': 50},
        'content': [{'type': 'text', 'text': json.dumps(value)}]}))


class SonnetTransport(unittest.TestCase):
    def test_scientific_identity_failure_has_safe_rule_diagnostics_without_format_retry(self):
        from scripts import build_opportunity_teams as teams
        from tools import team_provider
        selected = team_provider.stage_contract('adjudication')
        roles = [{'id': 'role-1'}]
        claims = {'supplied': {}}
        invalid = {'edges': [{'role_id': 'role-1', 'claim_id': 'not-supplied',
                             'coverage': 'direct', 'reason': 'PRIVATE_SENTINEL valid-length reason.'}]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            root = Path(tmp)
            ledger = ai.Ledger(root / 'ledger.json', 'synthetic', 2)
            with patch('requests.post', return_value=sonnet_response(invalid)) as post:
                with self.assertRaises(ai.SemanticFailure):
                    ai.Client(ledger, root / 'cache').json(selected['route'], 'adjudication', selected['prompt'],
                        {'scope': 'Synthetic scope'}, selected['schema'],
                        lambda value: teams.validate_edges(value, roles, claims), stage_config=selected['settings'])
                self.assertEqual(post.call_count, 1)
            row = ledger.read()['requests'][0]
            diagnostic = row['diagnostics']
            self.assertEqual(diagnostic['category'], 'semantic_validation_failure')
            self.assertEqual(diagnostic['path'], '$.edges[0]')
            self.assertFalse(diagnostic['supplied_claim'])
            self.assertTrue(diagnostic['supplied_role'])
            self.assertEqual(row['usage']['output_tokens'], 50)
            self.assertGreater(row['charged_microusd'], 0)
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(diagnostic))
            self.assertNotIn('not-supplied', json.dumps(diagnostic))

    def test_production_default_resumes_one_correction_without_changing_cache_identity(self):
        from tools import team_provider
        for corrected_valid in (True, False):
            with self.subTest(corrected_valid=corrected_valid), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
                root = Path(tmp)
                ledger = ai.Ledger(root / 'ledger.json', 'production', 2)
                selected = team_provider.stage_contract('verification')
                self.assertNotIn('durable_attempts', selected['settings'])
                invalid = {'suitable_for_team': True, 'edges': [{}]}
                corrected = {'suitable_for_team': True, 'edges': []} if corrected_valid else invalid
                def invoke():
                    return ai.Client(ledger, root / 'cache').json(selected['route'], 'verification',
                        selected['prompt'], {'scope': 'Synthetic scope'}, selected['schema'], lambda value: value,
                        stage_config=selected['settings'])
                with patch('requests.post', side_effect=[sonnet_response(invalid), sonnet_response(corrected)]) as post:
                    with patch.object(ai.time, 'sleep', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                        invoke()
                    original = copy.deepcopy(ledger.read()['requests'][0])
                    if corrected_valid:
                        self.assertEqual(invoke(), corrected)
                        self.assertEqual(invoke(), corrected)
                    else:
                        with self.assertRaises(ai.SchemaFailure):
                            invoke()
                        with self.assertRaises(ai.Deferred):
                            invoke()
                    self.assertEqual(post.call_count, 2)
                    first, second = [call.kwargs['json'] for call in post.call_args_list]
                    self.assertNotEqual(first, second)
                    self.assertEqual(second['system'], first['system'] +
                        '\nReturn a complete new decision conforming to the schema. Format diagnostic: ' +
                        json.dumps(original['diagnostics'], sort_keys=True))
                attempts = ledger.read()['requests']
                self.assertEqual(attempts[0], original)
                self.assertEqual([row['attempt'] for row in attempts], [1, 2])
                self.assertEqual(attempts[0]['key'], attempts[1]['key'])

    def test_interrupted_preflight_reconstructs_exact_correction_and_accounts_once(self):
        from tools import evaluate_offline_ai as evaluation
        configuration = (ai.ROOT / 'config/offline_ai.json').read_bytes()
        for malformed_json in (False, True):
            for corrected_valid in (False, True):
                for interruption in ('sleep', 'diagnostic_write', 'deadline'):
                    with self.subTest(json=malformed_json, valid=corrected_valid, interruption=interruption), tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
                        state = Path(tmp)
                        ai.Ledger(state / 'ledger.json', evaluation.TASK, 15)
                        first = sonnet_response({'ready': 'PRIVATE-RESPONSE'})
                        if malformed_json:
                            first.json.return_value['content'][0]['text'] = 'PRIVATE-RESPONSE malformed JSON'
                        second = sonnet_response({'ready': True if corrected_valid else 'PRIVATE-RESPONSE'})
                        write = ai.atomic_json
                        def interrupt_write(path, value):
                            if Path(path).parent.name == 'failures':
                                raise KeyboardInterrupt
                            return write(path, value)
                        interruption_patch = (patch.object(ai, 'atomic_json', side_effect=interrupt_write)
                            if interruption == 'diagnostic_write' else patch.object(ai.time, 'sleep',
                                side_effect=ai.Deferred('retry_deadline_exhausted') if interruption == 'deadline' else KeyboardInterrupt))
                        with patch('requests.post', side_effect=[first, second]) as post:
                            with interruption_patch:
                                if interruption == 'deadline':
                                    self.assertEqual(evaluation.production_preflight(state)['status'], 'retryable_processing')
                                else:
                                    with self.assertRaises(KeyboardInterrupt):
                                        evaluation.production_preflight(state)
                            self.assertFalse((state / 'production-preflight-receipt.json').exists())
                            retained = evaluation.evaluation_ledger(state / 'ledger.json').read()
                            self.assertEqual(len(retained['requests']), 1)
                            prior = retained['requests'][0]
                            self.assertEqual(prior['diagnostics']['category'], 'schema_failure')
                            original_body = copy.deepcopy(post.call_args_list[0].kwargs['json'])
                            expected = copy.deepcopy(original_body)
                            expected['system'] += ('\nReturn a complete new decision conforming to the schema. Format diagnostic: '
                                + json.dumps(prior['diagnostics'], sort_keys=True))
                            receipt = evaluation.production_preflight(state)
                            self.assertEqual(receipt['complete'], corrected_valid)
                            self.assertEqual(post.call_count, 2)
                            self.assertEqual(post.call_args_list[1].kwargs['json'], expected)
                            self.assertNotEqual(original_body, expected)
                            saved = evaluation.evaluation_ledger(state / 'ledger.json').read()
                            self.assertEqual(saved['requests'][0], prior)
                            self.assertEqual([r['attempt'] for r in saved['requests']], [1, 2])
                            self.assertEqual(saved['requests'][1]['key'], prior['key'])
                            self.assertGreater(saved['requests'][1]['reserved_microusd'], prior['reserved_microusd'])
                            self.assertEqual(sum(e.get('kind') == 'task_allowance' for e in saved['events']), 1)
                            self.assertEqual(saved['blocked_providers'], {})
                            # Model loss of the terminal receipt: a valid exact
                            # cache replays, while an invalid correction stays terminal.
                            (state / 'production-preflight-receipt.json').unlink()
                            replay = evaluation.production_preflight(state)
                            self.assertEqual(replay['complete'], corrected_valid)
                            self.assertEqual(post.call_count, 2)
                        for path in state.rglob('*.json'):
                            text = path.read_text()
                            self.assertNotIn('PRIVATE-RESPONSE', text)
                            self.assertNotIn('synthetic', text)
        self.assertEqual((ai.ROOT / 'config/offline_ai.json').read_bytes(), configuration)

    def test_interrupted_transport_retry_can_precede_one_schema_correction(self):
        from tools import evaluate_offline_ai as evaluation
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            state = Path(tmp)
            ai.Ledger(state / 'ledger.json', evaluation.TASK, 15)
            with patch('requests.post', side_effect=[Mock(status_code=429), sonnet_response({'ready': 'yes'}), sonnet_response({'ready': True})]) as post:
                with patch.object(ai.time, 'sleep', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                    evaluation.production_preflight(state)
                self.assertFalse((state / 'production-preflight-receipt.json').exists())
                with patch.object(ai.time, 'sleep'):
                    self.assertTrue(evaluation.production_preflight(state)['complete'])
                self.assertEqual(post.call_count, 3)
                self.assertEqual(post.call_args_list[0].kwargs['json'], post.call_args_list[1].kwargs['json'])
                self.assertIn('Format diagnostic:', post.call_args_list[2].kwargs['json']['system'])
                self.assertEqual([r['attempt'] for r in evaluation.evaluation_ledger(state / 'ledger.json').read()['requests']], [1, 2, 3])

    def test_resumed_semantic_failure_does_not_become_format_retry(self):
        from tools import evaluate_offline_ai as evaluation
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            state = Path(tmp)
            ai.Ledger(state / 'ledger.json', evaluation.TASK, 15)
            with patch('requests.post', return_value=sonnet_response({'ready': False})) as post:
                self.assertFalse(evaluation.production_preflight(state)['complete'])
                (state / 'production-preflight-receipt.json').unlink()
                self.assertFalse(evaluation.production_preflight(state)['complete'])
                self.assertEqual(post.call_count, 1)

    def test_preflight_transient_retry_and_durable_attempt_limit(self):
        from tools import evaluate_offline_ai as evaluation
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'), patch.object(ai.time, 'sleep'):
            state = Path(tmp)
            ai.Ledger(state / 'ledger.json', evaluation.TASK, 15)
            with patch('requests.post', side_effect=[Mock(status_code=429), sonnet_response({'ready': True})]) as post:
                self.assertTrue(evaluation.production_preflight(state)['complete'])
            self.assertEqual(post.call_count, 2)
            restored = evaluation.evaluation_ledger(state / 'ledger.json')
            self.assertEqual(len(restored.read()['requests']), 2)
            self.assertEqual(restored.max_requests, restored.read()['active_allowance']['additional_requests'])
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'), patch.object(ai.time, 'sleep'):
            state = Path(tmp)
            ai.Ledger(state / 'ledger.json', evaluation.TASK, 15)
            with patch('requests.post', return_value=Mock(status_code=503)) as post:
                self.assertFalse(evaluation.production_preflight(state)['complete'])
                # Model a runner dying after spending but before the receipt upload.
                (state / 'production-preflight-receipt.json').unlink()
                self.assertFalse(evaluation.production_preflight(state)['complete'])
            self.assertEqual(post.call_count, 3)
            self.assertEqual(len(evaluation.evaluation_ledger(state / 'ledger.json').read()['requests']), 3)

    def test_actual_preflight_entrypoint_is_once_and_separates_access_from_quality(self):
        from tools import evaluate_offline_ai as evaluation
        for successful in (True, False):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
                state = Path(tmp)
                ledger = ai.Ledger(state / 'ledger.json', evaluation.TASK, 15, 50)
                ledger.reserve('anthropic', 'claude-sonnet-5', 'verification', 'old-uncertain', 1000, 1)
                ledger.block('anthropic', 'bounded_established_service_check_only')
                prior = ledger.read()['requests'][0]
                reply = sonnet_response({'ready': True}) if successful else Mock(status_code=403,
                    json=Mock(return_value={'error': {'type': 'permission_error', 'message': 'denied'}}))
                with patch('requests.post', return_value=reply) as post:
                    receipt = evaluation.production_preflight(state)
                    self.assertEqual(evaluation.production_preflight(state), receipt)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(receipt['complete'], successful)
                self.assertFalse(receipt['quality_gate_passed'])
                self.assertFalse(receipt['production_enabled'])
                saved = json.loads((state / 'ledger.json').read_bytes())
                self.assertEqual(saved['requests'][0], prior)
                self.assertEqual(sum(e.get('kind') == 'task_allowance' for e in saved['events']), 1)
                self.assertEqual(len(saved['requests']), 2)

    def test_native_schema_projection_preserves_properties_and_original_constraints(self):
        for schema in schemas().values():
            original = copy.deepcopy(schema)
            projected = ai.anthropic_schema(schema)
            self.assertEqual(schema, original)
            self.assertEqual(projected['required'], schema['required'])
            self.assertIs(projected['additionalProperties'], False)
        schema = schemas()['verification']
        body = ai.request_body(ai.config()['routes']['sonnet'], ai.config()['stages']['verification'], 'p', {}, schema)
        sent = body['output_config']['format']
        self.assertEqual(sent['type'], 'json_schema')
        self.assertNotIn('maxItems', sent['schema']['properties']['edges'])
        self.assertIn('maxItems', sent['schema']['properties']['edges']['description'])
        self.assertEqual(set(sent['schema']['properties']['edges']['items']['properties']),
                         {'role_id', 'claim_id', 'coverage', 'reason'})
        with self.assertRaises(ai.SchemaFailure):
            ai.validate_schema({'suitable_for_team': True, 'edges': [{}] * 25}, schema)
        with self.assertRaises(ValueError):
            ai.anthropic_schema({'type': 'string', 'unevaluatedProperties': False})

    def test_missing_extra_type_diagnostics_without_evidence_or_reason_text(self):
        edge = {'role_id': 'role-1', 'claim_id': 'claim-1', 'coverage': 'direct',
                'private_rationale': 'SENSITIVE-RESPONSE-TEXT'}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            ledger = ai.Ledger(Path(tmp) / 'ledger.json', 'test', 1)
            post = Mock(return_value=sonnet_response({'suitable_for_team': True, 'edges': [edge]}))
            client = ai.Client(ledger, Path(tmp) / 'cache', post=post)
            with self.assertRaises(ai.SchemaFailure):
                client.json(ai.config()['routes']['sonnet'], 'verification', 'p', {'scope': 'PRIVATE-SCOPE'},
                    schemas()['verification'], lambda value: value,
                    stage_config=ai.config()['stages']['verification'] | {'max_attempts': 1})
            row = ledger.read()['requests'][0]
            diagnostic = row['diagnostics']
            self.assertEqual(diagnostic['path'], '$.edges[0]')
            self.assertEqual(diagnostic['missing_keys'], ['reason'])
            self.assertEqual(diagnostic['unexpected_keys'], ['private_rationale'])
            self.assertEqual(diagnostic['actual_type'], 'dict')
            self.assertEqual(row['provider_stop_reason'], 'end_turn')
            self.assertEqual(row['usage']['output_tokens'], 50)
            self.assertLess(row['charged_microusd'], row['reserved_microusd'])
            for text in ('SENSITIVE-RESPONSE-TEXT', 'PRIVATE-SCOPE', 'synthetic'):
                self.assertNotIn(text, ledger.path.read_text())

    def test_schema_correction_is_one_different_request_and_never_patches_science(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'), patch.object(ai.time, 'sleep'):
            ledger = ai.Ledger(Path(tmp) / 'ledger.json', 'test', 1)
            post = Mock(side_effect=[sonnet_response({'ready': 'yes'}), sonnet_response({'ready': True})])
            client = ai.Client(ledger, Path(tmp) / 'cache', post=post)
            call = lambda: client.json(ai.config()['routes']['sonnet'], 'preflight', 'p', {},
                schemas()['preflight'], lambda value: value,
                stage_config=ai.config()['stages']['preflight'] | {'max_attempts': 3})
            self.assertEqual(call(), {'ready': True})
            self.assertEqual(post.call_count, 2)
            self.assertNotEqual(post.call_args_list[0].kwargs['json'], post.call_args_list[1].kwargs['json'])
            self.assertEqual(call(), {'ready': True})
            self.assertEqual(post.call_count, 2)

    def test_truncation_refusal_and_semantic_failure_are_distinct_and_not_retried(self):
        for stop, error_type, semantic in [('max_tokens', ai.Incomplete, False),
                ('refusal', ai.Refusal, False), ('end_turn', ValueError, True)]:
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
                ledger = ai.Ledger(Path(tmp) / 'ledger.json', 'test', 1)
                post = Mock(return_value=sonnet_response({'ready': True}, stop))
                def validate(value):
                    if semantic:
                        raise ValueError('unsupported capability')
                    return value
                with self.assertRaises(error_type):
                    ai.Client(ledger, Path(tmp) / 'cache', post=post).json(ai.config()['routes']['sonnet'],
                        'decomposition', 'p', {}, schemas()['preflight'], validate)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(ledger.read()['blocked_providers'], {})

    def test_dynamic_allowance_is_idempotent_and_preserves_uncertainty_and_stops(self):
        for prior_count, prior_cost in [(2, 600000), (19, 14800000)]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'ledger.json'
                old = ai.Ledger(path, 'test', 15, 50)
                for index in range(prior_count):
                    old.reserve('anthropic', 'claude-sonnet-5', 'verification', str(index), prior_cost // prior_count, 1)
                old.block('anthropic', 'anthropic_configuration_http_403')
                before = old.read()
                auth = {'id': 'synthetic-grant', 'additional_requests': 200, 'additional_usd': 10,
                        'cumulative_usd': 15, 'providers': ['anthropic']}
                new = authorize_allowance(path, 'test', auth)
                after = new.read()
                self.assertEqual(after['requests'], before['requests'])
                self.assertEqual(after['blocked_providers'], before['blocked_providers'])
                self.assertEqual(after['max_requests'], prior_count + 200)
                self.assertEqual(after['limit_microusd'], min(15000000,
                    sum(row['charged_microusd'] for row in before['requests']) + 10000000))
                self.assertEqual(authorize_allowance(path, 'test', auth).read(), after)
                self.assertEqual(restore_ledger(path, 'test', 15, 50, auth).read(), after)
                changed = copy.deepcopy(after)
                changed['requests'][0]['charged_microusd'] += 1
                ai.atomic_json(path, changed)
                with self.assertRaises(ai.ConfigurationFailure):
                    restore_ledger(path, 'test', 15, 50, auth)
                ai.atomic_json(path, after)
                with self.assertRaises(ai.ConfigurationFailure):
                    authorize_allowance(path, 'test', auth | {'additional_requests': 201})
                with self.assertRaises(ai.ConfigurationFailure):
                    new.reserve('openai', 'unapproved-model', 'preflight', 'x', 1, 1)


if __name__ == '__main__':
    unittest.main()
