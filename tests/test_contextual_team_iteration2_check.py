"""Independent development evaluation, real evidence and fixture responses only."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_contextual_team_iteration2 as lifecycle
import test_contextual_team_luna_repair as evidence_fixture
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration2_check as check
from tools import contextual_team_iteration2 as workflow
from tools import contextual_team_iteration2_policy as policy
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import RecoveryRequired
from tools.offline_spend import identity, encoded, atomic_json, Refusal, Incomplete, ConfigurationFailure, Deferred


def answer(body):
    evidence = json.loads(body['messages'][0]['content'])
    return {'answers': [{'item_id': q['item_id'], 'verdict':
        'coherent-research-scope' if q['task_type'] == 'source_suitability' else
        'faithful' if q['task_type'] == 'explanation_audit' else 'unrelated',
        'evidence_ref': 'scope.science', 'reason': 'Independent fixture judgment remains a result, not a retry trigger.'}
        for q in evidence['items']]}


class DevelopmentCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = lifecycle.Iteration2('runTest'); cls.f.setUp()
        cls.addClassCleanup(cls.f.doCleanups)
        cls.f.p['input_token_ceilings']['check'] = 180000
        cls.f.p['release_id'] = identity({k: v for k, v in cls.f.p.items() if k != 'release_id'})
        cls.f.config['snapshot_id'] = cls.f.p['release_id']
        cls.f.install(); original_vectors = workflow.Iteration2Runner.vectors
        chosen = {p['person_id'] for p in cls.f.data['people']}
        def vectors(runner, docs, role, scope=None):
            if role == 'query': return original_vectors(runner, docs, role, scope)
            return [{'id': d['input_id'], 'embedding':
                ([1.0, 0.0] if d['person_id'] in chosen else [0.0, 1.0]) + [0.0]*1022} for d in docs]
        with patch.object(workflow.Iteration2Runner, 'vectors', vectors):
            cls.graph = cls.f.runner().run_scope(cls.f.scope)
        cls.scope, _, cls.assessment, cls.selection = check.actual_result(cls.f.state, cls.f.config, cls.f.scope['id'])
        cls.starting_calls = len(cls.f.calls)
        blocked = patch('socket.socket.connect', side_effect=AssertionError('no_network'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def packet(self, graph=None, selection=None):
        return check.packet(self.scope, self.graph if graph is None else graph, self.assessment,
            self.selection if selection is None else selection, self.f.config)

    def test_exact_production_graph_and_actual_composer_are_reconstructed_without_new_requests(self):
        before = existing.ExperimentLedger(self.f.state/'ledger.json').read()
        scope, graph, assessment, selection = check.actual_result(self.f.state, self.f.config, self.scope['id'])
        self.assertEqual(graph, self.graph); self.assertEqual(assessment, self.assessment)
        self.assertEqual(selection, self.selection); self.assertEqual(scope, self.scope)
        self.assertEqual(existing.ExperimentLedger(self.f.state/'ledger.json').read(), before)
        self.assertEqual(len(self.f.calls), self.starting_calls)
        self.assertEqual(selection['graph_id'], graph['graph_id']); self.assertTrue(selection['groups'])

    def test_completed_verifier_abstentions_and_coherent_negatives_keep_actual_evaluation_questions(self):
        for state in ('unsuitable', 'insufficient_source', 'needs_scope_selection', 'coherent'):
            with self.subTest(state=state):
                f = lifecycle.Iteration2('runTest'); f.setUp()
                try:
                    f.install(); original_post = f.post
                    def post(url, **kwargs):
                        body = kwargs['json']
                        if body['model'] != 'claude-sonnet-5': return original_post(url, **kwargs)
                        f.calls.append(copy.deepcopy(body))
                        evidence = json.loads(body['messages'][0]['content'])
                        wire = {'state': state, 'answers': [{'question_id': qid,
                            'coverage': 'insufficient_information', 'claims': [], 'central': False,
                            'reason': 'Fixture verifier abstains after reviewing the complete original evidence.',
                            'gap': 'Fixture unresolved scope or scientific evidence.'} for qid in evidence['wire_questions']]}
                        response = payload(json.dumps(wire), 'anthropic')
                        response['usage'] = {'input_tokens': 1000, 'output_tokens': 100}
                        return evidence_fixture.Response(response)
                    original_vectors = workflow.Iteration2Runner.vectors
                    chosen = {p['person_id'] for p in f.data['people']}
                    def vectors(runner, docs, role, scope=None):
                        if role == 'query': return original_vectors(runner, docs, role, scope)
                        return [{'id': d['input_id'], 'embedding':
                            ([1.0, 0.0] if d['person_id'] in chosen else [0.0, 1.0]) + [0.0]*1022} for d in docs]
                    runner = workflow.Iteration2Runner(f.state, f.config, post=post, counter_post=f.counter)
                    with patch.object(workflow.Iteration2Runner, 'vectors', vectors):
                        produced = runner.run_scope(f.scope)
                    before = runner.ledger.read(); calls = len(f.calls); counts = f.count_calls
                    with patch.object(check, 'select', wraps=check.select) as selector:
                        scope, graph, assessment, selection = check.actual_result(f.state, f.config, f.scope['id'])
                    self.assertEqual(graph, produced)
                    self.assertEqual(selector.call_count, int(state == 'coherent'))
                    self.assertEqual(graph['state'], state if state != 'coherent' else 'no_supported_group_in_assessed_set')
                    self.assertEqual(selection['graph_id'], graph['graph_id'])
                    self.assertEqual(selection['groups'], []); self.assertEqual(selection['primary_view'], [])
                    _, body, validate, report = check.packet(scope, graph, assessment, selection, f.config)
                    questions = json.loads(body['messages'][0]['content'])['items']
                    self.assertEqual([q['task_type'] for q in questions], ['source_suitability']+['call_person']*5+['aspect_person']*3)
                    self.assertEqual(report['exclusion_pair_count'], 24)
                    self.assertTrue(report['missing_primary_group']); self.assertTrue(report['missing_first_alternative'])
                    self.assertIsNone(report['feasible_scope_yield']['denominator'])
                    result = validate(payload(json.dumps(answer(body)), 'anthropic'), False)
                    self.assertEqual(len(result['verdicts']), 9)
                    self.assertEqual(runner.ledger.read(), before)
                    self.assertEqual((len(f.calls), f.count_calls), (calls, counts))
                finally: f.doCleanups()

    def test_full_evidence_fixed_questions_and_blinding_have_no_feasibility_inference(self):
        contract, body, _, report = self.packet(); evidence = json.loads(body['messages'][0]['content'])
        self.assertEqual((body['model'], body['thinking'], body['max_tokens']), ('claude-sonnet-5', {'type': 'disabled'}, 12000))
        self.assertEqual(evidence['scope'], self.f.data['scope'])
        documents = {p['person_id']: p for p in self.f.config['people']}
        self.assertTrue(all(p == documents[p['person_id']] for p in evidence['profile_documents']))
        ordinary = copy.deepcopy(evidence)
        ordinary['items'] = [q for q in ordinary['items'] if q['task_type'] != 'explanation_audit']
        text = json.dumps(ordinary)
        for secret in ('Fixture documented activity', 'Fixture independent verification', '"coverage"', '"outcome"', '"central"'):
            self.assertNotIn(secret, text)
        top = [q['people'][0] for q in evidence['items'] if q['item_id'].startswith('top-')]
        self.assertEqual(top, self.graph['retrieval']['shortlist'][:5])
        people_items = [q['people'][0] for q in evidence['items'] if q['task_type'] == 'call_person']
        self.assertEqual(len(people_items), len(set(people_items)))
        self.assertTrue(set(self.selection['groups'][0]) <= set(people_items))
        self.assertEqual(report['feasible_scope_yield']['denominator'], None)
        self.assertFalse(contract['production_admission']); self.assertIn(check.science.CLARIFICATION, body['system'])

    def test_exact_questions_owned_canonical_references_and_task_specific_labels(self):
        _, body, validate, _ = self.packet(); wire = answer(body)
        accepted = validate(payload(json.dumps(wire), 'anthropic'), False)
        self.assertEqual(accepted['verdicts'][1]['verdict'], 'unrelated')
        for change in (lambda w: w['answers'].pop(),
                       lambda w: w['answers'].__setitem__(1, copy.deepcopy(w['answers'][0])),
                       lambda w: w['answers'][0].update(verdict='strong'),
                       lambda w: w['answers'][1].update(evidence_ref='p01c01'),
                       lambda w: w['answers'][1].update(grade='strong'),
                       lambda w: w['answers'][1].update(reason='short')):
            changed = copy.deepcopy(wire); change(changed)
            with self.assertRaises(ValueError): validate(payload(json.dumps(changed), 'anthropic'), False)
        evidence = json.loads(body['messages'][0]['content']); person = next(
            p for p in evidence['profile_documents'] if p['person_id'] == evidence['items'][1]['people'][0])
        claim = person['claims'][0]; ref = claim['claim_id']+'@'+str(claim['revision'])
        wire['answers'][1]['evidence_ref'] = ref
        validate(payload(json.dumps(wire), 'anthropic'), False)
        for target in (0, 2):
            changed = copy.deepcopy(wire); changed['answers'][target]['evidence_ref'] = ref
            with self.assertRaises(ValueError): validate(payload(json.dumps(changed), 'anthropic'), False)
        wire['answers'][1]['evidence_ref'] = claim['claim_id']+'@99'
        with self.assertRaises(ValueError): validate(payload(json.dumps(wire), 'anthropic'), False)

    def test_complete_response_parser_and_immutable_canonical_cache(self):
        _, body, validate, _ = self.packet(); raw = json.dumps(answer(body)); response = payload(raw, 'anthropic')
        value = validate(response, False)
        self.assertEqual(validate(json.loads(encoded(value)), True), value)
        for stop, exc in (('max_tokens', Incomplete), ('refusal', Refusal)):
            with self.assertRaises(exc): validate(response | {'stop_reason': stop}, False)
        for bad in (raw.replace('"answers":', '"answers":[],"answers":', 1), 'NaN'):
            with self.assertRaises(ValueError): validate(payload(bad, 'anthropic'), False)
        with patch.object(check, 'response_value', side_effect=AssertionError('bound_before_decode')):
            with self.assertRaisesRegex(ValueError, 'response_bound'):
                validate(payload(' '*(check.MAX_RESPONSE_BYTES+1), 'anthropic'), False)
        for change in (lambda v: v.update(version='historical'), lambda v: v.update(input_sha256='0'*64),
                       lambda v: v['verdicts'].reverse(), lambda v: v.update(extra=True)):
            changed = copy.deepcopy(value); change(changed)
            with self.assertRaises(ValueError): validate(changed, True)

    def test_exclusions_are_bounded_aspect_questions_without_grades_or_rationales(self):
        graph = copy.deepcopy(self.graph)
        for person in graph['pair_decisions'][:3]:
            for decision in person['decisions']: decision['coverage'] = 'adjacent'
        selection = self.selection | {'groups': [], 'primary_view': []}
        _, body, _, report = self.packet(graph=graph, selection=selection)
        evidence = json.loads(body['messages'][0]['content'])
        questions = [q for q in evidence['items'] if q['task_type'] == 'aspect_person']
        self.assertEqual(len(questions), 3); self.assertEqual(report['exclusion_pair_count'], 6)
        self.assertEqual(report['missing_exclusion_judgments'], 3)
        self.assertTrue(all(set(q) == {'item_id', 'task_type', 'people', 'target_aspect'} for q in questions))
        self.assertNotIn('coverage', json.dumps(questions)); self.assertNotIn('reason', json.dumps(questions))
        self.assertTrue(report['missing_primary_group']); self.assertTrue(report['missing_first_alternative'])
        self.assertFalse(any(q['task_type'] == 'group_usefulness' for q in evidence['items']))

    def test_graph_self_rehash_does_not_substitute_for_original_paid_stage_provenance(self):
        path = workflow.result_path(self.f.state, self.scope['id']); original = path.read_bytes()
        changed = json.loads(original); changed['value']['pair_decisions'][0]['outcome'] = 'adjacent'
        changed['value']['graph_id'] = identity({k: v for k, v in changed['value'].items() if k not in ('requests', 'graph_id')})
        try:
            atomic_json(path, changed)
            with self.assertRaisesRegex(ConfigurationFailure, 'not_exact_production_result'):
                check.actual_result(self.f.state, self.f.config, self.scope['id'])
        finally: path.write_bytes(original)
        ledger = existing.ExperimentLedger(self.f.state/'ledger.json').read()
        row = next(r for r in ledger['requests'] if r.get('purpose') == policy.operation(self.scope['id'], 'assess'))
        path = self.f.state/'cache'/(row['key']+'.json'); original = path.read_bytes(); changed = json.loads(original)
        changed['request_id'] = '0'*32
        try:
            atomic_json(path, changed)
            with self.assertRaises(ValueError): check.actual_result(self.f.state, self.f.config, self.scope['id'])
        finally: path.write_bytes(original)

    def test_fixed_veterans_control_keeps_all_exact_original_person_evidence(self):
        sources = json.loads((policy.ROOT/'config/contextual_team/iteration2-source-inputs-v1.json').read_bytes())
        scope = next(s for s in sources['scopes'] if s['id'] == check.CONTROL_SCOPE)
        selection = {'groups': [], 'primary_view': [], 'option_count': 0}
        c, body, validate, report = check.packet(scope, None, None, selection, self.f.config)
        evidence = json.loads(body['messages'][0]['content'])
        self.assertEqual(identity(evidence['profile_documents'][0]), check.CONTROL_PERSON_SHA256)
        self.assertEqual([q['item_id'] for q in evidence['items']], ['source', 'control-person'])
        self.assertTrue(report['source_only_control']); self.assertFalse(c['production_admission'])
        validate(payload(json.dumps(answer(body)), 'anthropic'), False)
        config = copy.deepcopy(self.f.config)
        next(p for p in config['people'] if p['person_id'] == check.CONTROL_PERSON)['claims'].pop()
        with self.assertRaisesRegex(ConfigurationFailure, 'fixed_control_person_changed'):
            check.packet(scope, None, None, selection, config)

    def test_prepare_rejects_caller_science_and_excess_wire_before_any_count(self):
        for request in ({'iteration2_check': self.scope['id'], 'groups': []}, {'iteration2_check': []}, {'iteration2_check': 'sealed'}):
            with patch.object(workflow, 'configuration', return_value=self.f.config):
                with self.assertRaises(ConfigurationFailure): check.prepared(self.f.state, request)
        with patch.object(policy, 'plan', return_value=self.f.p | {'maximum_wire_bytes': 100}):
            with self.assertRaisesRegex(ValueError, 'complete_evidence_wire_bound'): self.packet()

    def test_same_authority_request_is_cached_without_paid_replay_or_rekey(self):
        contract, body, validate, _ = self.packet(); calls = []
        def post(url, **kwargs):
            calls.append(kwargs['json'])
            response = payload(json.dumps(answer(kwargs['json'])), 'anthropic')
            response['usage'] = {'input_tokens': 1000, 'output_tokens': 100}
            return evidence_fixture.Response(response)
        runner = workflow.Iteration2Runner(self.f.state, self.f.config, post=post, counter_post=self.f.counter)
        purpose = policy.operation(self.scope['id'], 'check'); input_id = contract['evidence_sha256']
        metadata = policy.bind_operation(runner.ledger, purpose, body, contract, input_id)
        logical = [policy.VERSION, purpose, identity(contract), input_id]
        before_counts = self.f.count_calls
        first = runner.request(purpose, logical, body, validate, repair_metadata=metadata)
        ledger_rows = runner.ledger.read()['requests']
        second = runner.request(purpose, logical, body, validate, repair_metadata=metadata)
        self.assertEqual(second, first); self.assertEqual(len(calls), 1)
        self.assertEqual(self.f.count_calls, before_counts+1)
        self.assertEqual(runner.ledger.read()['requests'], ledger_rows)
        self.assertTrue(runner.used[-1]['cache_hit'])
        self.assertEqual(ledger_rows[-1]['completion_authority'], policy.VERSION)
        with self.assertRaises(Deferred):
            policy.bind_operation(runner.ledger, purpose, body | {'max_tokens': 12001}, contract, input_id)
        path = self.f.state/'cache'/(ledger_rows[-1]['key']+'.json'); original = path.read_bytes()
        corrupted = json.loads(original); corrupted['value']['input_sha256'] = '0'*64
        try:
            atomic_json(path, corrupted)
            with self.assertRaises(RecoveryRequired): runner.request(purpose, logical, body, validate, repair_metadata=metadata)
        finally: path.write_bytes(original)
        self.assertEqual(len(calls), 1); self.assertEqual(self.f.count_calls, before_counts+1)


if __name__ == '__main__': unittest.main()
