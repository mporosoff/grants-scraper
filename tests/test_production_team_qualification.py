"""Production request equivalence and ordinary, unpinned amendment handling."""
from contextlib import chdir
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import build_opportunity_teams as teams, researcher_registry as registry
from tools import evaluate_offline_ai as evaluation, team_provider, team_maintenance
from tools.offline_ai import Client, Ledger, ConfigurationFailure, identity, atomic_json
from tests import test_build_opportunity_teams as fixtures
from tests.test_sonnet_structured_transport import sonnet_response


class ProductionTeamQualification(unittest.TestCase):
    def test_changed_preflight_inputs_stop_before_team_dispatch(self):
        original_settings = evaluation.config()
        original_schemas = evaluation.schemas()
        for changed in ('route', 'settings', 'schema', 'team_route'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp)
                ledger = Ledger(state / 'ledger.json', 'synthetic', 2)
                atomic_json(state / 'production-preflight-receipt.json', {
                    'complete': True, 'transport': evaluation.production_preflight_configuration()['transport'],
                    'contract': identity(evaluation.production_preflight_configuration())})
                settings, contracts = copy.deepcopy(original_settings), copy.deepcopy(original_schemas)
                stages = team_provider.contract()
                if changed == 'route':
                    settings['routes']['sonnet']['model'] += '-changed'
                elif changed == 'settings':
                    settings['stages']['preflight']['max_output_tokens'] += 1
                elif changed == 'schema':
                    contracts['preflight']['properties']['ready']['description'] = 'Changed contract'
                else:
                    stages['verification']['route'] = stages['verification']['route'] | {'model': 'different-model'}
                before = ledger.read()
                with patch.object(evaluation, 'evaluation_ledger', return_value=ledger), \
                        patch.object(evaluation, 'config', return_value=settings), \
                        patch.object(evaluation, 'schemas', return_value=contracts), \
                        patch.object(team_provider, 'contract', return_value=stages), \
                        patch('requests.post', side_effect=AssertionError('No dispatch before compatible preflight')) as post:
                    with self.assertRaises(ConfigurationFailure):
                        evaluation.production_teams(state, 'regression')
                self.assertEqual(ledger.read(), before)
                post.assert_not_called()

    def test_retained_qualification_rejects_changed_protocol_and_adapter(self):
        class NoProviderClient:
            def json(self, route, stage, prompt, data, schema, validate, **kwargs):
                return validate({'specific': False, 'objective': 'Synthetic negative control.', 'roles': []})
        original_read, original_hash = Path.read_bytes, evaluation.function_hash
        with tempfile.TemporaryDirectory() as tmp, patch('requests.post', side_effect=AssertionError('No provider calls')):
            state = Path(tmp)
            ledger = Ledger(state / 'ledger.json', 'synthetic', 2)
            atomic_json(state / 'production-preflight-receipt.json', {
                'complete': True, 'transport': evaluation.production_preflight_configuration()['transport'],
                'contract': identity(evaluation.production_preflight_configuration())})
            with patch.object(evaluation, 'evaluation_ledger', return_value=ledger), \
                    patch.object(evaluation, 'Client', return_value=NoProviderClient()):
                first = evaluation.production_teams(state, 'regression')
                retained = {path: path.read_bytes() for path in (state / 'sonnet-production-teams-1').rglob('*.json')}
                self.assertTrue(first['execution_complete'])
                self.assertFalse(first['quality_gate_passed'])
                self.assertEqual(evaluation.production_teams(state, 'regression'), first)
                for change in ('threshold', 'source_checks', 'rule', 'adapter', 'scientific_states'):
                    def changed_read(path):
                        value = original_read(path)
                        if path.name == 'sonnet_production_teams.json' and change not in ('adapter', 'scientific_states'):
                            protocol = json.loads(value)
                            if change == 'threshold':
                                protocol['acceptance']['scope_decision_accuracy_min'] = .1
                            else:
                                protocol[change] = 'Materially changed qualification requirement'
                            return json.dumps(protocol).encode()
                        return value
                    def changed_hash(function):
                        if change == 'adapter' and function is evaluation.team_case:
                            return 'changed-adapter-identity'
                        return original_hash(function)
                    with self.subTest(change=change), patch.object(Path, 'read_bytes', changed_read), \
                            patch.object(evaluation, 'function_hash', side_effect=changed_hash), \
                            patch.object(evaluation, 'SCIENTIFIC_STATES', evaluation.SCIENTIFIC_STATES | ({'invalid'} if change == 'scientific_states' else set())):
                        with self.assertRaisesRegex(ValueError, 'contract changed'):
                            evaluation.production_teams(state, 'regression')
                    self.assertEqual({path: path.read_bytes() for path in retained}, retained)
                self.assertEqual(ledger.read()['requests'], [])

    def test_transport_change_requires_a_new_bounded_probe_and_preserves_history(self):
        original_module_hash = evaluation.module_hash
        for prior_success in (True, False):
            with self.subTest(prior_success=prior_success), tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
                state = Path(tmp)
                Ledger(state / 'ledger.json', evaluation.TASK, 15)
                with patch('requests.post', return_value=sonnet_response({'ready': prior_success})) as post:
                    prior = evaluation.production_preflight(state)
                    ledger_before = evaluation.evaluation_ledger(state / 'ledger.json').read()
                    self.assertEqual(post.call_count, 1)
                    def changed(path):
                        return 'changed-native-transport' if path == 'tools/offline_ai.py' else original_module_hash(path)
                    with patch.object(evaluation, 'module_hash', side_effect=changed):
                        with self.assertRaises(ConfigurationFailure):
                            evaluation.production_teams(state, 'regression')
                        self.assertEqual(post.call_count, 1)
                        if prior_success:
                            current = evaluation.production_preflight(state)
                            self.assertTrue(current['complete'])
                            self.assertNotEqual(prior['contract'], current['contract'])
                            self.assertEqual(post.call_count, 2)
                            self.assertEqual(evaluation.production_preflight(state), current)
                            self.assertEqual(post.call_count, 2)
                            history = state / 'history' / ('production-preflight-' + identity(prior) + '.json')
                            self.assertEqual(json.loads(history.read_bytes()), prior)
                        else:
                            with self.assertRaisesRegex(ConfigurationFailure, 'after_failure'):
                                evaluation.production_preflight(state)
                            self.assertEqual(post.call_count, 1)
                    ledger = evaluation.evaluation_ledger(state / 'ledger.json').read()
                    self.assertEqual(ledger['requests'][0], ledger_before['requests'][0])
                    self.assertEqual(sum(row.get('kind') == 'task_allowance' for row in ledger['events']), 1)
                    if prior_success:
                        self.assertNotEqual(ledger['requests'][0]['key'], ledger['requests'][1]['key'])

    def test_contract_change_cannot_reset_an_interrupted_correction(self):
        from tools import offline_ai as ai
        original_hash = evaluation.module_hash
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            state = Path(tmp)
            Ledger(state / 'ledger.json', evaluation.TASK, 15)
            with patch('requests.post', side_effect=[sonnet_response({'ready': 'yes'}), sonnet_response({'ready': True})]) as post:
                with patch.object(ai.time, 'sleep', side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        evaluation.production_preflight(state)
                before = evaluation.evaluation_ledger(state / 'ledger.json').read()
                with patch.object(evaluation, 'module_hash', side_effect=lambda path: 'changed' if path == 'tools/offline_ai.py' else original_hash(path)):
                    with self.assertRaisesRegex(ConfigurationFailure, 'incomplete_attempt'):
                        evaluation.production_preflight(state)
                self.assertEqual(evaluation.evaluation_ledger(state / 'ledger.json').read(), before)
                self.assertEqual(post.call_count, 1)
                self.assertTrue(evaluation.production_preflight(state)['complete'])
                self.assertEqual(post.call_count, 2)
                self.assertIn('Format diagnostic:', post.call_args_list[1].kwargs['json']['system'])

    def test_qualification_transmits_the_exact_production_stage_requests(self):
        fixtures.ProposedTeamTests.setUp(self)
        self.scope['source_fingerprint'] = 'exact-source'
        case = {'scope': self.scope, 'claims': list(self.claims.values()), 'holdout': False}
        payload = {'scope': self.scope['text'], 'source_fingerprint': 'exact-source',
            'objective': self.decomposition['objective'], 'roles': self.roles,
            'claims': [{key: row[key] for key in ('claim_id', 'revision', 'material_hash', 'researcher_id', 'label', 'evidence', 'source_url')} for row in self.claims.values()]}
        responses = [self.decomposition, {'edges': self.edges}, {'suitable_for_team': True, 'edges': self.edges}]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, ANTHROPIC_API_KEY='synthetic'):
            root = Path(tmp)
            provider = teams.Provider(root / 'provider', ledger=Ledger(root / 'production/ledger.json', 'production', 2))
            with patch('requests.post', side_effect=[sonnet_response(row) for row in responses]) as production:
                provider.json(teams.DECOMPOSE, {'scope': self.scope['text'], 'record_type': self.scope['record_type'], 'source_fingerprint': 'exact-source'})
                provider.json(teams.ADJUDICATE, payload)
                provider.json(teams.VERIFY, payload | {'proposed_edges': self.edges})
            with patch('requests.post', side_effect=[sonnet_response(row) for row in responses]) as qualification:
                row = evaluation.team_case(Client(Ledger(root / 'qualification/ledger.json', 'qualification', 2), root / 'cache'), 'sonnet', case, production=True)
            self.assertEqual(row['state'], 'proposed')
            self.assertEqual([call.kwargs['json'] for call in production.call_args_list], [call.kwargs['json'] for call in qualification.call_args_list])
            self.assertEqual(row['request_contracts'], {stage: proof['request_contract'] for stage, proof in provider.provenance.stages.items()})
        prior = json.loads(Path('evaluation/established_sonnet_repair_2_frozen.json').read_bytes())
        for stage in ('decomposition', 'adjudication'):
            self.assertEqual(team_provider.stage_prompt(stage), prior['prompts'][stage])
            self.assertEqual(team_provider.stage_settings(stage)['prompt_version'], prior['version'])

    def test_ordinary_registry_outputs_reassemble_unpinned_dependents_only(self):
        fixture = json.loads(Path('tests/fixtures/claim_retirement_recovery.json').read_bytes())
        model, candidates, current = fixture['model'], fixture['candidates'], fixture['registry']
        # These IDs cannot use the historical restoration allowlist.
        for row in model['opportunities']:
            row['id'] = 'synthetic-' + row['id']
        for scope in candidates:
            scope['id'] = 'synthetic-' + scope['id']
        before = copy.deepcopy(model)
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), patch('requests.post', side_effect=AssertionError('No provider in registry updates')):
            Path('config').mkdir()
            Path('data').mkdir()
            path = Path('config/model.json')
            path.write_text(json.dumps(model))
            def rebuild():
                with patch.object(registry, 'load_registry', return_value=current), patch.object(teams, 'scopes', return_value=candidates), patch('scripts.import_opportunity_team_model.write_outputs'), patch('scripts.faculty_match.match_to_catalog'):
                    return registry.build_outputs(Path('config/registry.json'), team_model_path=path)['team_model']
            restored = rebuild()
            active = [row for row in restored['opportunities'] if row['review_state'] == 'proposed']
            self.assertEqual(len(active), 3)
            retired = {claim['claim_id'] for person in current['researchers'] for claim in person['claims'] if claim['status'] == 'retired'}
            for row in active:
                original = next(r for r in before['opportunities'] if r['id'] == row['id'])
                self.assertEqual(row['decision_contract'], original['decision_contract'])
                self.assertEqual(row['pipeline_hash'], original['pipeline_hash'])
                self.assertFalse(retired & {ref['claim_id'] for role in row['roles'] for ref in role['claim_refs']})
            self.assertEqual(rebuild()['opportunities'], restored['opportunities'])
            # Display metadata changes no scientific evidence or team identity.
            current['researchers'][0]['display_name'] += ' Display correction'
            current['registry_generation'] = registry.registry_generation(current)
            self.assertEqual(rebuild()['opportunities'], restored['opportunities'])
            # A changed claim affects its actual references, not every team of
            # that researcher or unrelated records in the registry.
            ref = active[0]['roles'][0]['claim_refs'][0]
            changed_id = ref['claim_id']
            affected = {row['id'] for row in active if any(r['claim_id'] == changed_id for role in row['roles'] for r in role['claim_refs'])}
            claim = next(claim for person in current['researchers'] for claim in person['claims'] if claim['claim_id'] == changed_id)
            claim['revision'] += 1
            claim['evidence'] += ' Reviewed synthetic correction.'
            claim['material_hash'] = registry.material_claim_hash(claim)
            current['registry_generation'] = registry.registry_generation(current)
            amended = rebuild()
            for row in amended['opportunities']:
                original = next(r for r in restored['opportunities'] if r['id'] == row['id'])
                if row['id'] not in affected:
                    self.assertEqual(row, original)
                elif row['review_state'] == 'proposed':
                    self.assertNotIn(changed_id, {r['claim_id'] for role in row['roles'] for r in role['claim_refs']})
                else:
                    self.assertEqual(row['review_state'], 'needs_revalidation')
            self.assertEqual(rebuild()['opportunities'], amended['opportunities'])

    def test_confirmation_selection_is_disjoint_and_input_hashes_are_pinned(self):
        _, confirmed = evaluation.production_team_cases('confirmation')
        _, regression = evaluation.production_team_cases('regression')
        _, population = evaluation.production_team_cases('population')
        ids = lambda rows: {row['scope']['id'] for row in rows}
        self.assertEqual(len(confirmed), 6)
        self.assertFalse(ids(confirmed) & (ids(regression) | ids(population)))
        self.assertEqual(sum(row['annotations']['expected_scope'] == 'reject' for row in confirmed), 2)


if __name__ == '__main__':
    unittest.main()
