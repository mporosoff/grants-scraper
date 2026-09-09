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
        for field in ('usd', 'reserved_pilot_usd', 'reserved_pilot_requests'):
            self.assertEqual(active['qualification_budget'][field], original['qualification_budget'][field])
        self.assertEqual(active['qualification_budget']['requests'],
                         original['qualification_budget']['requests'] + active['request_extension']['new_requests'])
        self.assertEqual(active['request_extension']['new_usd'], 0)
        self.assertEqual(active['qualification_budget']['ledger_id'], original['version'])
        self.assertIn('concise source-declared heading', team_provider.stage_prompt('decomposition'))
        self.assertEqual(team_provider.stage_prompt('adjudication'), original['final_prompts']['adjudication'])
        self.assertEqual(team_provider.stage_prompt('verification'), active['final_prompts']['verification'])

    def test_failed_trial_evidence_is_preserved_without_production_promotion(self):
        prior = json.loads(Path('evaluation/sonnet_team_scope_repair_2_results_20260909.json').read_bytes())
        active, _ = evaluation.production_team_cases('focus')
        snapshot = Path(active['historical_protocol'])
        # The receipt identifies immutable Git bytes, not platform checkout EOLs.
        self.assertEqual(hashlib.sha256(snapshot.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                         active['revision_checkpoint']['prior_protocol_sha256'])
        self.assertTrue(prior['regression']['execution_complete'])
        self.assertFalse(prior['regression']['numerical_gate_passed'])
        self.assertFalse(prior['quality_gate_passed'])
        self.assertEqual(set(prior['consequential_findings']), {'363616', '361205', '361050'})
        for trial_contract in ('d385627271e50e9e7d4489519568930c712788e688a68046e71a7fd1f268a59b',
                               'e925feedd4e4c9b7e429d5d77632261c15b0b03ebec9bad6e02664cac7f0eea0'):
            self.assertNotIn(trial_contract, team_maintenance.compatible_contracts('proposed'))
        self.assertIn('25e9a5e0d34efdc1cb99675b1c35b6095a2beac2e98060f35fed241d22d25055',
                      team_maintenance.compatible_contracts('proposed'))
        # These assertions bind the active contract, not a claim of LLM quality.
        self.assertNotIn('A source-declared research pathway may be selected', team_provider.stage_prompt('decomposition'))
        self.assertIn('each as a separate required role', team_provider.stage_prompt('decomposition'))
        self.assertIn('cannot add an operation absent from its evidence phrase', team_provider.stage_prompt('verification'))

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

    def test_verifier_only_repair_reuses_exact_completed_prior_stages(self):
        historical = json.loads(Path('evaluation/sonnet_team_scope_repair_3_results_20260909.json').read_bytes())
        active, cases = evaluation.production_team_cases('focus')
        case = next(case for case in cases if case['scope']['id'] == '362185')
        prior = next(row for row in historical['focus_results'] if row['scope_id'] == case['scope']['id'])
        self.assertFalse(historical['quality_gate_passed'])
        self.assertEqual(prior['state'], 'unsuitable_scope')
        for stage in ('decomposition', 'adjudication'):
            self.assertEqual(team_provider.stage_contract(stage), historical['focus']['configuration']['stages'][stage])
        self.assertNotEqual(team_provider.stage_contract('verification'), historical['focus']['configuration']['stages']['verification'])
        self.assertEqual(active['qualification_budget'], historical['focus']['configuration']['protocol']['qualification_budget'])
        self.assertNotIn('663170468f111f36c46ef365b4784d86d199540a794d436e79d80664524692fc',
                         team_maintenance.compatible_contracts('proposed'))
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', ANTHROPIC_API_KEY='synthetic'):
            root = Path(directory)
            ledger = Ledger(root / 'ledger.json', 'synthetic-stage-reuse', 2)
            cache = root / 'cache'
            for stage, value in prior['stages'].items():
                key = prior['request_contracts'][stage]
                atomic_json(cache / (key + '.json'), {'key': key, 'returned_model': 'claude-sonnet-5', 'value': value})
            before = {path: path.read_bytes() for path in cache.glob('*.json')}
            # A synthetic response proves transport/cache behavior, not LLM quality.
            with patch('requests.post', return_value=sonnet_response({'suitable_for_team': True, 'edges': []})) as post:
                current = evaluation.team_case(Client(ledger, cache), 'sonnet', case, production=True)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs['json']['system'], team_provider.stage_prompt('verification'))
            self.assertEqual([row['stage'] for row in ledger.read()['requests']], ['verification'])
            self.assertEqual(current['state'], 'insufficient_evidence')
            for stage in ('decomposition', 'adjudication'):
                self.assertEqual(current['stages'][stage], prior['stages'][stage])
                self.assertEqual(current['request_contracts'][stage], prior['request_contracts'][stage])
            self.assertNotEqual(current['request_contracts']['verification'], prior['request_contracts']['verification'])
            self.assertEqual({path: path.read_bytes() for path in before}, before)

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
    def test_request_extension_resumes_both_ledgers_without_new_dollars_or_lost_history(self):
        from tools.offline_spend import LinkedLedger
        with tempfile.TemporaryDirectory() as directory, \
                patch('requests.post', side_effect=AssertionError('No provider in authorization')) as post:
            root = Path(directory)
            parent = Ledger(root / 'ledger.json', evaluation.TASK, 4, 20)
            child = Ledger(root / 'qualification' / 'ledger.json', 'qualification', 2, 15)
            linked = LinkedLedger(child, parent)
            completed = linked.reserve('anthropic', 'claude-sonnet-5', 'decomposition', 'completed', 300000, 1)
            linked.complete(completed, status='valid', charged_microusd=100000)
            linked.reserve('anthropic', 'claude-sonnet-5', 'verification', 'uncertain', 300000, 1)
            linked.block('anthropic', 'account-denial-is-preserved')
            parent = authorize_allowance(parent.path, evaluation.TASK, {
                'id': 'old', 'additional_requests': 18, 'additional_usd': 3.6,
                'cumulative_usd': 4, 'providers': ['anthropic']})
            before = {ledger.path: ledger.path.read_bytes() for ledger in (parent, child)}
            def extension(ledger, name):
                prior = ledger.read()
                return {'id': name, 'additional_requests': prior['max_requests'] - len(prior['requests']) + 5,
                    'additional_usd': (prior['limit_microusd'] - sum(r['charged_microusd'] for r in prior['requests'])) / 1e6,
                    'cumulative_usd': prior['limit_microusd'] / 1e6, 'providers': ['anthropic'],
                    'replacement_checkpoint': {'run_id': 'fixture', 'ledger_identity': identity(prior),
                        'ledger_sha256': hashlib.sha256(before[ledger.path]).hexdigest()}}
            parent_auth, child_auth = extension(parent, 'extension'), extension(child, 'qualification-extension')
            child_auth['parent_authorization_id'] = parent_auth['id']
            protocol = {'version': 'qualification', 'qualification_budget': {
                'usd': 2, 'requests': 20, 'authorization': child_auth}}
            configuration = {'authorization': parent_auth, 'team_protocol': 'fixture-protocol.json'}
            original_read, original_atomic = Path.read_bytes, evaluation.atomic_json
            def configured(path):
                if path.as_posix() == 'config/sonnet_production_qualification.json':
                    return json.dumps(configuration).encode()
                if path.as_posix() == configuration['team_protocol']:
                    return json.dumps(protocol).encode()
                return original_read(path)
            def interrupted(path, value):
                if Path(path) == child.path:
                    raise KeyboardInterrupt()
                original_atomic(path, value)
            with patch.object(Path, 'read_bytes', configured):
                with patch.object(evaluation, 'atomic_json', side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        evaluation.replacement_authorization(root)
                committed_parent = parent.path.read_bytes()
                self.assertNotEqual(committed_parent, before[parent.path])
                self.assertEqual(child.path.read_bytes(), before[child.path])
                evaluation.replacement_authorization(root)
                self.assertEqual(parent.path.read_bytes(), committed_parent)
                after = {path: path.read_bytes() for path in before}
                for path, old_bytes in before.items():
                    old, new = json.loads(old_bytes), json.loads(after[path])
                    self.assertEqual(new['requests'], old['requests'])
                    self.assertEqual(new['blocked_providers'], old['blocked_providers'])
                    self.assertEqual(new['events'][:len(old['events'])], old['events'])
                    self.assertEqual(new['limit_microusd'], old['limit_microusd'])
                    self.assertEqual(new['max_requests'], old['max_requests'] + 5)
                    self.assertEqual(sum(e.get('kind') == 'task_allowance' and
                        e['authorization']['id'] == new['active_allowance']['id'] for e in new['events']), 1)
                evaluation.replacement_authorization(root)
                self.assertEqual({path: path.read_bytes() for path in before}, after)
                self.assertEqual(evaluation.evaluation_ledger(parent.path).max_requests, 25)
            post.assert_not_called()

    def test_qualification_requires_its_retained_grant_before_dispatch(self):
        protocol, cases = evaluation.production_team_cases('focus')
        authorization = protocol['qualification_budget']['authorization']
        for missing_state in ('absent', 'old_cap', 'ungranted_new_cap', 'missing_grant_event'):
            with self.subTest(missing_state=missing_state), tempfile.TemporaryDirectory() as directory, \
                    patch('requests.post', side_effect=AssertionError('No provider calls')) as post:
                state = Path(directory)
                parent = Ledger(state / 'ledger.json', 'fixture', 4, 30)
                atomic_json(state / 'production-preflight-receipt.json', {
                    'complete': True, 'transport': evaluation.production_preflight_configuration()['transport'],
                    'contract': identity(evaluation.production_preflight_configuration())})
                budget = protocol['qualification_budget']
                child_path = state / budget['ledger_id'] / 'ledger.json'
                if missing_state != 'absent':
                    child = Ledger(child_path, budget['ledger_id'], budget['usd'],
                        budget['requests'] - 5 if missing_state == 'old_cap' else budget['requests'])
                    if missing_state == 'missing_grant_event':
                        atomic_json(child_path, child.read() | {'active_allowance': authorization})
                before = {path: path.read_bytes() for path in state.rglob('*.json')}
                with patch.object(evaluation, 'evaluation_ledger', return_value=parent), \
                        patch.object(evaluation, 'Client', side_effect=AssertionError('No client before reservation restoration')):
                    with self.assertRaises((ConfigurationFailure, ValueError)):
                        evaluation.production_teams(state, 'focus')
                self.assertEqual({path: path.read_bytes() for path in state.rglob('*.json')}, before)
                post.assert_not_called()

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
