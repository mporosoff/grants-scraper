"""Format clarification for unbound scopes; no scientific retries or providers."""
from copy import deepcopy
import json
import unittest

from tools import contextual_team_iteration2 as workflow
from tools import contextual_team_iteration2_policy as policy
from tools import contextual_team_latency_contract as wire
from tools.contextual_team_executor import RecoveryRequired, scope_inputs
from tools.offline_spend import encoded, identity


# Synthetic invalid interpretation. Actual provider output remains local/private.
NONCOHERENT_FIXTURE = '{"state":"needs_scope_selection","objective":"A synthetic broad source requires selection of a particular research direction.","roles":[],"limitations":["Select a source-warranted direction before assessment."],"approach":"Choose a specific direction before identifying contributions."}'



class InterpretationFormat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = json.loads((policy.ROOT/'config/contextual_team/iteration2-source-inputs-v1.json').read_bytes())
        cls.scope = next(s for s in source['scopes'] if s['id'] == '351715')
        cls.data = scope_inputs(cls.scope)

    def legacy(self):
        return wire.body('decomposition', self.data, 'L', 8000, repaired=True)

    def bound(self, contract, body, status=None):
        purpose = policy.operation(self.scope['id'], 'interpret')
        return {'events': [policy.packet_event(purpose, body, contract, identity(self.data))],
            'requests': [] if status is None else [{'purpose': purpose, 'status': status}]}

    def test_legacy_valid_failed_and_unsent_prepared_operations_keep_exact_bytes(self):
        legacy = self.legacy()
        for status in ('valid', 'failed', None):
            with self.subTest(status=status):
                state = self.bound(*legacy, status); before = deepcopy(state)
                actual = workflow.interpretation_body(self.data, self.scope['id'], state)
                self.assertEqual(encoded(actual), encoded(legacy))
                self.assertEqual(state, before)
                self.assertNotIn(workflow.NONCOHERENT_FORMAT, actual[1]['instructions'])

    def test_only_unbound_format_metadata_changes_source_model_and_validator_are_exact(self):
        old_contract, old_body = self.legacy()
        contract, body = workflow.interpretation_body(self.data, self.scope['id'], {'events': [], 'requests': []})
        self.assertEqual(contract['version'], workflow.INTERPRETATION_FORMAT)
        self.assertEqual(contract['validator_contract_sha256'], identity(old_contract))
        self.assertEqual(contract['prompt'], old_contract['prompt']+workflow.NONCOHERENT_FORMAT)
        self.assertEqual(body['instructions'], contract['prompt'])
        self.assertEqual(body['text']['format']['name'], workflow.INTERPRETATION_FORMAT)
        self.assertEqual(body['input'], old_body['input'])
        for key in ('model', 'reasoning', 'store', 'max_output_tokens'):
            self.assertEqual(body[key], old_body[key])
        self.assertEqual(body['text']['verbosity'], old_body['text']['verbosity'])
        self.assertIs(body['text']['format']['strict'], True)
        schema = deepcopy(contract['schema'])
        self.assertEqual(schema['properties']['approach'].pop('description'),
            'Empty string unless state is coherent; future scope-selection guidance belongs in limitations.')
        self.assertEqual(schema, old_contract['schema'])
        self.assertEqual(body['text']['format']['schema'], contract['schema'])
        self.assertNotEqual(identity(body), identity(old_body))
        roundtrip = json.loads(encoded(self.data))
        self.assertEqual(workflow.interpretation_body(roundtrip, self.scope['id'], {'events': []}), (contract, body))

    def test_bound_new_format_reconstructs_exactly_and_ignores_other_scopes(self):
        expected = workflow.interpretation_body(self.data, self.scope['id'], {'events': []})
        for status in ('valid', 'failed', None):
            self.assertEqual(workflow.interpretation_body(self.data, self.scope['id'], self.bound(*expected, status)), expected)
        other = self.bound(*self.legacy())
        other['events'][0]['purpose'] = policy.operation('363302:a-1', 'interpret')
        self.assertEqual(workflow.interpretation_body(self.data, self.scope['id'], other), expected)

    def test_unknown_and_duplicate_bound_versions_stop_before_another_request(self):
        state = self.bound(*self.legacy()); state['events'][0]['contract_version'] = 'unknown'
        with self.assertRaisesRegex(RecoveryRequired, 'unknown_interpretation_transport'):
            workflow.interpretation_body(self.data, self.scope['id'], state)
        state = self.bound(*self.legacy()); state['events'].append(deepcopy(state['events'][0]))
        with self.assertRaisesRegex(RecoveryRequired, 'conflicting_interpretation_transport'):
            workflow.interpretation_body(self.data, self.scope['id'], state)

    def test_noncoherent_approach_guidance_remains_rejected_by_unchanged_validator(self):
        response = json.loads(NONCOHERENT_FIXTURE); before = deepcopy(response)
        self.assertEqual(response['state'], 'needs_scope_selection'); self.assertEqual(response['roles'], [])
        for state in ({'events': []}, self.bound(*self.legacy(), 'failed')):
            workflow.interpretation_body(self.data, self.scope['id'], state)
            with self.assertRaisesRegex(ValueError, 'noncoherent_source_has_no_selected_approach'):
                wire.resolve('decomposition', response, self.data, repaired=True)
        self.assertEqual(response, before)


if __name__ == '__main__':
    unittest.main()
