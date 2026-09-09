"""Source-purpose contract, unchanged stage reuse, and replacement allowance."""
import copy
from contextlib import chdir, redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import evaluate_offline_ai as evaluation, team_maintenance, team_provider
from tools.offline_ai import Client, ConfigurationFailure, Ledger, atomic_json, identity
from tools.offline_spend import authorize_allowance
from tests.test_sonnet_structured_transport import sonnet_response


class ScopeRepairContracts(unittest.TestCase):
    def test_heading_revision_preserves_frozen_science_and_spending_limits(self):
        path = Path('evaluation/sonnet_team_scope_repair_20260909.json')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         'df3fc904c2e5f55b34ada061696c2aa57e6b19806f6b29af9af89986cab73a36')
        original = json.loads(path.read_bytes())
        active, _ = evaluation.production_team_cases('confirmation')
        for field in ('confirmation_cases', 'confirmation_selection', 'fresh_input_hashes',
                      'acceptance', 'exposed_cases', 'required_source_checks', 'useful_proposal_comparator'):
            self.assertEqual(active[field], original[field])
        for population in ('regression', 'population', 'exposed', 'confirmation'):
            self.assertEqual(active['case_hashes'][population], original['case_hashes'][population])
        for field in ('usd', 'requests', 'reserved_pilot_usd', 'reserved_pilot_requests'):
            self.assertEqual(active['qualification_budget'][field], original['qualification_budget'][field])
        self.assertEqual(active['qualification_budget']['ledger_id'], original['version'])
        self.assertIn('concise source-declared heading', team_provider.stage_prompt('decomposition'))
        for stage in ('adjudication', 'verification'):
            self.assertEqual(team_provider.stage_prompt(stage), original['final_prompts'][stage])

    def test_protocol_revision_cannot_reset_qualification_requests_or_spend(self):
        # Exercise the production qualification entrypoint with real linked
        # reservations and synthetic responses; no network/model invocation.
        for limits in ({'usd': 2, 'requests': 1}, {'usd': 1, 'requests': 10}):
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as directory, \
                    patch('requests.post', side_effect=AssertionError('No provider calls')) as post:
                state = Path(directory)
                parent = Ledger(state / 'ledger.json', 'task-fixture', 4, 10)
                atomic_json(state / 'production-preflight-receipt.json', {
                    'complete': True, 'transport': evaluation.production_preflight_configuration()['transport'],
                    'contract': identity(evaluation.production_preflight_configuration())})
                protocol = {'version': 'qualification-1', 'qualification_budget': limits,
                    'acceptance': {'scope_decision_accuracy_min': .9, 'legitimate_scope_acceptance_min': .85}}
                case = {'scope': {'id': 'control', 'text': 'Investigate catalytic reaction mechanisms.',
                    'record_type': 'specific_parent', 'source_fingerprint': 'first'}, 'claims': [],
                    'holdout': False, 'annotations': {'expected_scope': 'bounded_research'}}
                dispatches = []
                class ReservedClient:
                    def __init__(self, ledger, *args, **kwargs): self.ledger = ledger
                    def json(self, route, stage, prompt, data, schema, validate, **kwargs):
                        token = self.ledger.reserve(route['provider'], route['model'], stage, identity(data), 600000, 1)
                        dispatches.append(token)
                        self.ledger.complete(token, status='valid', charged_microusd=600000)
                        return validate({'specific': False, 'objective': 'Only administrative operations are funded.', 'roles': []})
                def cases(population):
                    return protocol, [case]
                with patch.object(evaluation, 'evaluation_ledger', return_value=parent), \
                        patch.object(evaluation, 'Client', ReservedClient), \
                        patch.object(evaluation, 'production_team_cases', new=cases):
                    first = evaluation.production_teams(state, 'regression')
                    self.assertTrue(first['execution_complete'])
                    self.assertFalse(first['numerical_gate_passed'])  # A stub is not scientific qualification.
                    local_path = state / 'qualification-1' / 'ledger.json'
                    prior = json.loads(local_path.read_bytes())
                    parent_prior = parent.read()
                    protocol['version'] = 'qualification-2'
                    protocol['qualification_budget'] = limits | {'ledger_id': 'qualification-1'}
                    case['scope']['source_fingerprint'] = 'amended'
                    second = evaluation.production_teams(state, 'regression')
                    self.assertFalse(second['execution_complete'])
                    self.assertEqual(second['new_provider_requests'], 0)
                    self.assertEqual(len(dispatches), 1)
                    self.assertEqual(json.loads(local_path.read_bytes()), prior)
                    self.assertEqual(parent.read(), parent_prior)
                    self.assertFalse((state / 'qualification-2' / 'ledger.json').exists())
                    row = json.loads(next((state / 'qualification-2' / 'regression').glob('team-*.json')).read_bytes())
                    self.assertEqual(row['state'], 'deferred')
                    self.assertEqual(sum(r['charged_microusd'] for r in prior['requests']), 600000)
                post.assert_not_called()

    def test_fresh_selection_preserves_exposed_cases_and_exact_input_contracts(self):
        prior = json.loads(Path('evaluation/sonnet_production_teams.json').read_bytes())
        protocol, fresh = evaluation.production_team_cases('confirmation')
        _, exposed = evaluation.production_team_cases('exposed')
        self.assertEqual(exposed, prior['confirmation_cases'])
        self.assertEqual(len(fresh), 12)
        self.assertEqual(sum(c['annotations']['expected_scope'] == 'bounded_research' for c in fresh), 8)
        self.assertFalse({c['scope']['id'] for c in fresh} & set(protocol['confirmation_selection']['excluded_previously_exposed_ids']))
        for case in fresh:
            self.assertEqual(identity({'scope':case['scope'], 'claims':case['claims']}), protocol['fresh_input_hashes'][case['scope']['id']])
            self.assertIn(case['annotations']['source_quote'], case['scope']['text'])
            self.assertEqual(len(case['claims']), 24)
            self.assertNotIn('annotations', team_provider.request_inputs('decomposition', {'scope':case['scope']['text']}))
        for pop in ('regression', 'population'):
            self.assertEqual(protocol['populations'][pop], prior['populations'][pop])
            self.assertEqual(protocol['case_hashes'][pop], prior['case_hashes'][pop])

    def test_changed_decomposition_cannot_reuse_old_cache(self):
        from scripts import build_opportunity_teams as teams
        old = json.loads(Path('evaluation/established_sonnet_repair_2_frozen.json').read_bytes())
        stage = team_provider.stage_contract('decomposition')
        data = {'scope':'An administrative-only synthetic supported-path control.', 'record_type':'specific_parent', 'source_fingerprint':'fixture'}
        response = {'specific':False, 'objective':'Only administrative operations are funded.', 'roles':[]}
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', ANTHROPIC_API_KEY='synthetic'):
            root=Path(directory); ledger=Ledger(root/'ledger.json','fixture',2)
            validate=lambda value: teams.validate_response(teams.DECOMPOSE,data,value)
            old_settings=stage['settings'] | {'prompt_version':old['version']}
            with patch('requests.post', return_value=sonnet_response(response)) as post:
                client=Client(ledger,root/'cache',post=post)
                client.json(stage['route'],'decomposition',old['prompts']['decomposition'],data,stage['schema'],validate,stage_config=old_settings)
                client.json(stage['route'],'decomposition',stage['prompt'],data,stage['schema'],validate,stage_config=stage['settings'])
                client.json(stage['route'],'decomposition',stage['prompt'],data,stage['schema'],validate,stage_config=stage['settings'])
            self.assertEqual(post.call_count,2)
            self.assertEqual(len(ledger.read()['requests']),2)
            self.assertNotEqual(ledger.read()['requests'][0]['key'],ledger.read()['requests'][1]['key'])

    def test_scope_rejections_expire_but_positive_evidence_keeps_its_identity(self):
        prior='25e9a5e0d34efdc1cb99675b1c35b6095a2beac2e98060f35fed241d22d25055'
        scope={'source_fingerprint':'source'}; claims={'claim':'revision'}
        for state in ['proposed','insufficient_evidence','not_specific','unsuitable_scope']:
            attempt={'state':state,'decision_contract':prior,'claim_dependencies':['claim']}
            actual=team_maintenance.decision_key(scope,attempt,claims)
            old=team_maintenance.decision_key(scope,attempt,claims,prior)
            self.assertEqual(actual==old,state in ['proposed','insufficient_evidence'])

    def test_team_only_hold_does_not_stop_source_or_cov4_generation(self):
        from tools.plan_release import decide
        self.assertEqual(decide({'teams':['prompt']},event='push',team_generation_ready=False),'noop')
        self.assertEqual(decide({'source':['document'],'teams':['prompt']},event='push',team_generation_ready=False),'generate')
        self.assertEqual(decide({},event='schedule',team_generation_ready=False),'generate')
        self.assertEqual(decide({'teams':['prompt']},event='workflow_dispatch',requested='teams',team_generation_ready=True),'teams')

    def test_ordinary_entrypoint_accepts_legacy_string_attempts_without_dispatch(self):
        from scripts import build_opportunity_teams as teams
        scope={'id':'synthetic-old-scope','parent_id':'synthetic-parent','source_fingerprint':'source'}
        model={'opportunities':[],'generation_attempts':{scope['id']:'legacy-fingerprint'}}
        with tempfile.TemporaryDirectory() as directory, chdir(directory), redirect_stdout(io.StringIO()):
            Path('config').mkdir()
            atomic_json(Path('config/opportunity_team_model.json'),model)
            with patch('sys.argv',['teams','--mode','replay','--report','report.json']), \
                    patch.object(teams,'load_registry',return_value={'registry_generation':'fixture','researchers':[]}), \
                    patch.object(teams,'eligible_claims',return_value={}), \
                    patch.object(teams,'synchronize_opportunity_team_model',return_value=model), \
                    patch.object(teams,'scopes',return_value=[scope]), \
                    patch.object(teams,'source_fingerprints',return_value={scope['id']:'source'}), \
                    patch('requests.post',side_effect=AssertionError('No provider in replay')) as post:
                self.assertEqual(teams.main(),0)
            report=json.loads(Path('report.json').read_bytes())
            self.assertEqual(report['status'],'completed')
            self.assertEqual(report['due_scopes'],0)
            self.assertEqual(model['generation_attempts'][scope['id']],'legacy-fingerprint')
            post.assert_not_called()


class ReplacementAllowance(unittest.TestCase):
    def exercise(self, *, fail_commit=False, changed_checkpoint=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'ledger.json'
            old=Ledger(path,evaluation.TASK,15,40)
            old.reserve('anthropic','claude-sonnet-5','decomposition','uncertain',300000,1)
            old.block('anthropic','account-denial-is-preserved')
            original_auth={'id':'prior','additional_requests':10,'additional_usd':1,'cumulative_usd':15,'providers':['anthropic']}
            old=authorize_allowance(path,evaluation.TASK,original_auth)
            before=path.read_bytes(); prior=old.read()
            auth={'id':'replacement','additional_requests':150,'additional_usd':10,'cumulative_usd':10.3,'providers':['anthropic'],
                  'replacement_checkpoint':{'ledger_sha256':hashlib.sha256(before).hexdigest(),'ledger_identity':identity(prior),'run_id':'fixture'}}
            if changed_checkpoint: auth['replacement_checkpoint']['ledger_identity']='different'
            read=Path.read_bytes; atomic=evaluation.atomic_json
            def configured(p):
                if p.as_posix()=='config/sonnet_production_qualification.json':
                    return json.dumps({'authorization':auth}).encode()
                return read(p)
            def interrupted(p,value):
                if Path(p)==path: raise KeyboardInterrupt()
                atomic(p,value)
            with patch.object(Path,'read_bytes',configured), patch('requests.post',side_effect=AssertionError('No provider in authorization')):
                if changed_checkpoint:
                    with self.assertRaisesRegex(ConfigurationFailure,'checkpoint_mismatch'):
                        evaluation.replacement_authorization(root)
                    self.assertEqual(path.read_bytes(),before)
                    return
                if fail_commit:
                    with patch.object(evaluation,'atomic_json',side_effect=interrupted):
                        with self.assertRaises(KeyboardInterrupt): evaluation.replacement_authorization(root)
                    self.assertEqual(path.read_bytes(),before)
                evaluation.replacement_authorization(root)
                after=path.read_bytes(); current=evaluation.evaluation_ledger(path).read()
                self.assertEqual(current['requests'],prior['requests'])
                self.assertEqual(current['blocked_providers'],prior['blocked_providers'])
                self.assertEqual(current['max_requests'],151)
                self.assertEqual(current['limit_microusd'],10300000)
                self.assertEqual(sum(e.get('kind')=='task_allowance' and e['authorization']['id']=='replacement' for e in current['events']),1)
                evaluation.replacement_authorization(root)
                self.assertEqual(path.read_bytes(),after)
                self.assertEqual(evaluation.evaluation_ledger(path).read(),current)
                with self.assertRaises(ConfigurationFailure):
                    evaluation.evaluation_ledger(path).reserve('openai','unapproved','decomposition','wrong-provider',1,1)

    def test_replacement_preserves_prior_and_uncertain_spend_and_denials(self): self.exercise()
    def test_interruption_before_atomic_grant_restarts_from_same_checkpoint(self): self.exercise(fail_commit=True)
    def test_mismatched_starting_checkpoint_is_not_rebased_on_resume(self): self.exercise(changed_checkpoint=True)


if __name__ == '__main__': unittest.main()
