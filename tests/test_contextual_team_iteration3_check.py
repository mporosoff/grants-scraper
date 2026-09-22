"""Independent check of actual composer VM output; replies are synthetic."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from test_contextual_team_iteration3_integrity import setup, wire, browser, ENGINE
from test_contextual_team_iteration2_contract import assessment, verified_wire
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration3_check as c
from tools import contextual_team_iteration3_integrity as integrity
from tools import contextual_team_iteration2_check as old
from tools import contextual_team_iteration2_contract as old_science
from tools.offline_spend import encoded, identity, Incomplete, Refusal


def selection(data, graph):
    rendered = browser(data, graph)
    return {'composer_version': 'contextual-composition-v4', 'composer_sha256': hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
        'bundle_id': identity('test-bundle'), 'direct_source': True, 'graph_id': graph['graph_id'],
        'eligible_ids': sorted(p['person_id'] for p in data['people']), 'candidate_groups': rendered['candidates'],
        'groups': [o['state']['selectedIds'] for o in rendered['options']], 'option_count': len(rendered['options']),
        'primary_view': [{'person_id': p['profile']['id'], 'evidence': p['evidence']} for p in rendered['view']['selected']],
        'group_explanation': rendered['view']['opportunity']['why_team'],
        'missing_skills': rendered['view']['opportunity']['missing_skills'], 'statistics': rendered['statistics']}


def answers(body):
    evidence = json.loads(body['messages'][0]['content'])
    return {'answers': [{'item_id': q['item_id'], 'verdict':
        'coherent-research-scope' if q['task_type'] == 'source_suitability' else
        'unsupported' if q['task_type'] == 'explanation_audit' else 'unrelated',
        'evidence_ref': 'scope.science', 'reason': 'Synthetic independent scientific disagreement remains a complete result.'}
        for q in evidence['items']]}


class Iteration3Check(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.base, cls.eligible = setup()
        cls.assessment = assessment(cls.data)
        cls.scope = copy.deepcopy(cls.data['scope']) | {'source_id': cls.base['source_id']}
        cls.config = {'people': cls.data['people'], 'snapshot_id': cls.base['snapshot_id']}
        result = integrity.resolve(wire(cls.data, cls.base, cls.eligible), cls.data, cls.base, cls.eligible)
        cls.graph = integrity.adapter(cls.data, cls.base, result, cls.eligible)
        cls.selection = selection(cls.data, cls.graph)
        cls.base_selection = selection(cls.data, cls.base)
        blocked = patch('socket.socket.connect', side_effect=AssertionError('zero_provider_or_source_calls'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def packet(self, **kwargs):
        return c.packet(self.scope, kwargs.pop('graph', self.graph), self.assessment,
            kwargs.pop('selection', self.selection), self.config, generation_id=kwargs.pop('generation_id', identity('generation')), **kwargs)

    def test_actual_composer_questions_complete_owned_and_blind_except_displayed_assertions(self):
        contract, body, check, report = self.packet()
        evidence = json.loads(body['messages'][0]['content'])
        self.assertEqual(len(evidence['items']), 11)
        self.assertEqual(evidence['scope'], self.data['scope'])
        self.assertEqual(evidence['source_selected_approach'], self.graph['approach'])
        self.assertEqual(report['groups'], self.selection['groups'][:2])
        self.assertEqual(report['all_composed_option_count'], 8)
        self.assertFalse(report['source_only_control'])
        self.assertEqual(report['feasible_scope_yield']['denominator'], None)
        self.assertEqual((body['model'], body['max_tokens'], body['thinking']), ('claude-sonnet-5', 12000, {'type': 'disabled'}))
        documents = {p['person_id']: p for p in evidence['profile_documents']}
        for question in evidence['items']:
            expected = {'scope.science'} | set(question['people']) | {
                claim['claim_id']+'@'+str(claim['revision']) for pid in question['people'] for claim in documents[pid]['claims']}
            self.assertEqual(question['allowed_evidence_refs'], sorted(expected))
            if question['task_type'] == 'explanation_audit':
                view = next(v for v in self.selection['primary_view'] if v['person_id'] == question['people'][0])
                self.assertEqual(question['assertion'], view['evidence'])
            else: self.assertNotIn('assertion', question)
        for person in documents.values():
            self.assertEqual(person, next(p for p in self.data['people'] if p['person_id'] == person['person_id']))
        blinded = copy.deepcopy(evidence)
        for q in blinded['items']: q.pop('assertion', None)
        for forbidden in ('Synthetic methods contribute distinct', 'Independent fixture verification', 'Fixture assessor', '"coverage"', '"outcome"'):
            self.assertNotIn(forbidden, json.dumps(blinded))
        self.assertEqual(contract['generation_id'], identity('generation'))
        value = check(payload(json.dumps(answers(body)), 'anthropic'), False)
        self.assertTrue(all(r['verdict'] in ('coherent-research-scope', 'unrelated', 'unsupported') for r in value['verdicts']))
        self.assertEqual(check(json.loads(encoded(value)), True), value)

    def test_retained_v3_packet_has_same_questions_and_full_scientific_evidence(self):
        selection = copy.deepcopy(self.base_selection); selection['groups'] = selection['groups'][:2]
        before = encoded(self.base)
        old_contract, old_body, _, _ = old.packet(self.scope, self.base, self.assessment, selection, self.config)
        contract, body, check, report = self.packet(graph=self.base, selection=self.base_selection)
        previous = json.loads(old_body['messages'][0]['content']); actual = json.loads(body['messages'][0]['content'])
        self.assertEqual(actual.pop('source_selected_approach'), self.base['approach'])
        self.assertEqual(actual, previous)
        self.assertNotEqual(identity(body), identity(old_body)); self.assertNotEqual(contract['version'], old_contract['version'])
        self.assertEqual(contract['schema'], old_contract['schema'])
        self.assertEqual(encoded(self.base), before)
        self.assertIn('Never emit a literal placeholder', body['system'])
        self.assertFalse(report['historical_scientific_results_changed'])

    def test_schema_owner_completeness_and_exact_rendered_claims(self):
        _, body, check, _ = self.packet(); original = answers(body)
        evidence = json.loads(body['messages'][0]['content'])
        top1 = next(q for q in evidence['items'] if q['item_id'] == 'top-1')
        top2 = next(q for q in evidence['items'] if q['item_id'] == 'top-2')
        foreign = next(ref for ref in top2['allowed_evidence_refs'] if ref not in top1['allowed_evidence_refs'])
        mutations = [lambda v: v['answers'].pop(), lambda v: v['answers'].__setitem__(1, copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'][1].update(evidence_ref=foreign), lambda v: v['answers'][1].update(evidence_ref='scope.science; scope.science'),
            lambda v: v['answers'][1].update(verdict='faithful'), lambda v: v['answers'][1].update(extra=True)]
        for mutate in mutations:
            value = copy.deepcopy(original); mutate(value)
            with self.assertRaises(ValueError): check(payload(json.dumps(value), 'anthropic'), False)
        for mutate in (lambda s: s['primary_view'][0]['evidence'].update(why_person='Invented performed operation'),
                       lambda s: s['primary_view'][0]['evidence'].update(evidence_phrase='Invented evidence'),
                       lambda s: s['groups'].__setitem__(0, [self.eligible[-2], self.eligible[-1]])):
            selected = copy.deepcopy(self.selection); mutate(selected)
            with self.assertRaises(ValueError): self.packet(selection=selected)

    def test_reasons_cannot_be_empty_padded_or_unfilled_placeholders(self):
        _, body, check, _ = self.packet()
        for reason in ('placeholder', 'placeholder for the scientific rationale', 'TODO: add evidence-based reason',
                       '<reason> fill this later', 'short'+(' '*30), ' '+('x'*1000)):
            value = answers(body); value['answers'][1]['reason'] = reason
            with self.subTest(reason=reason[:20]), self.assertRaises(ValueError):
                check(payload(json.dumps(value), 'anthropic'), False)
        value = answers(body); value['answers'][1]['reason'] = 'Evidence is insufficient to establish the proposed operation.'
        self.assertEqual(check(payload(json.dumps(value), 'anthropic'), False)['verdicts'][1]['reason'], value['answers'][1]['reason'])

    def test_completion_refusal_duplicate_json_bounds_and_cache_identity(self):
        _, body, check, _ = self.packet(); raw = json.dumps(answers(body)); response = payload(raw, 'anthropic')
        value = check(response, False)
        for stop, exception in (('max_tokens', Incomplete), ('refusal', Refusal)):
            with self.assertRaises(exception): check(response | {'stop_reason': stop}, False)
        duplicate = raw.replace('"item_id": "source"', '"item_id":"source","item_id":"source"')
        with self.assertRaisesRegex(ValueError, 'duplicate_response_key'): check(payload(duplicate, 'anthropic'), False)
        with self.assertRaisesRegex(ValueError, 'response_bound'): check(payload('x'*(c.MAX_RESPONSE_BYTES+1), 'anthropic'), False)
        for mutation in (lambda v: v.update(contract_sha256='0'*64), lambda v: v.update(version=old.VERSION),
                         lambda v: v['verdicts'].reverse(), lambda v: v['verdicts'][0].update(reason=' '*20)):
            altered = copy.deepcopy(value); mutation(altered)
            with self.assertRaises(ValueError): check(altered, True)

    def test_packaging_observation_does_not_rekey_but_generation_composer_or_graph_does(self):
        contract, body, _, report = self.packet()
        selected = self.selection | {'bundle_id': '0'*64, 'direct_source': False}
        other, other_body, _, other_report = self.packet(selection=selected)
        self.assertEqual((contract, body), (other, other_body))
        self.assertNotEqual(report['observed_ui_bundle_id'], other_report['observed_ui_bundle_id'])
        for selected in (self.selection | {'composer_sha256': 'f'*64},):
            other, _, _, _ = self.packet(selection=selected)
            self.assertNotEqual(identity(other), identity(contract))
        other, _, _, _ = self.packet(generation_id=identity('another-generation'))
        self.assertNotEqual(identity(other), identity(contract))
        with self.assertRaises(ValueError): self.packet(selection=self.selection | {'graph_id': 'f'*64})

    def test_all_negative_integrity_keeps_top_people_and_missing_group_denominator(self):
        value = integrity.resolve(wire(self.data, self.base, self.eligible, 'insufficient_information'), self.data, self.base, self.eligible)
        graph = integrity.adapter(self.data, self.base, value, self.eligible)
        _, body, check, report = self.packet(graph=graph, selection=selection(self.data, graph))
        evidence = json.loads(body['messages'][0]['content'])
        self.assertEqual([q['item_id'] for q in evidence['items']], ['source', 'top-1', 'top-2', 'top-3', 'top-4', 'top-5'])
        self.assertTrue(report['missing_primary_group']); self.assertTrue(report['missing_first_alternative'])
        self.assertEqual(report['feasible_scope_yield']['status'], 'unmeasured')
        self.assertEqual(len(check(payload(json.dumps(answers(body)), 'anthropic'), False)['verdicts']), 6)

    def test_three_completed_verifier_abstentions_retain_full_questions_without_composition(self):
        for state in c.UNCOMPOSED_STATES:
            raw = verified_wire(self.data, self.assessment); raw['state'] = state
            for answer in raw['answers']: answer.update(coverage='insufficient_information', claims=[], central=False)
            verified = old_science.verifier_resolve(raw, self.data, self.assessment)
            config = {key: self.base[key] for key in ('snapshot_id', 'registry_generation', 'roster_id')}
            graph = old_science.adapter(self.data, self.assessment, verified, config, self.scope, self.base['retrieval'], [])
            _, body, check, report = self.packet(graph=graph, selection=c.uncomposed_selection(graph))
            questions = json.loads(body['messages'][0]['content'])['items']
            self.assertEqual(len(questions), 9)
            self.assertEqual(len(graph['pair_decisions']), 12)
            self.assertFalse(any(q['task_type'] in ('group_usefulness', 'explanation_audit') for q in questions))
            self.assertEqual(report['missing_exclusion_judgments'], 21)
            self.assertTrue(report['missing_primary_group'])
            self.assertEqual(len(check(payload(json.dumps(answers(body)), 'anthropic'), False)['verdicts']), 9)


if __name__ == '__main__': unittest.main()
