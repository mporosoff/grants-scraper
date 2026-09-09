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
            self.assertEqual(restored.max_requests, 200)
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
