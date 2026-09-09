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
from tools.offline_ai import Client, Ledger
from tests import test_build_opportunity_teams as fixtures
from tests.test_sonnet_structured_transport import sonnet_response


class ProductionTeamQualification(unittest.TestCase):
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
