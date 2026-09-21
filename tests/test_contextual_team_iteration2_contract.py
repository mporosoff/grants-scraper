"""Production pair verification and grouped graphs; all provider replies are fixtures."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_contextual_team_luna_repair as fixture
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration2_contract as c
from tools import contextual_team_requirements as requirements
from tools import contextual_team_shared_rows as historical
from tools import contextual_team_pair_contract as pairs
from tools.offline_spend import identity, encoded, Refusal, Incomplete


def selected(data, optional=False, role_count=2):
    value = copy.deepcopy(data)
    wire = copy.deepcopy(value['interpretation'])
    wire['approach'] = 'Investigate one source-warranted plasma-science approach before selecting people.'
    original = wire['roles']
    wire['roles'] = []
    for index in range(role_count):
        role = copy.deepcopy(original[min(index, 1)])
        for key in ('required', 'quote', 'source_field'): role.pop(key)
        role.update(id='role-'+str(index+1), kind='optional_direction' if optional and index else 'approach_necessary',
            applicability='applies', condition='')
        wire['roles'].append(role)
    value['interpretation'] = requirements.resolve('decomposition', wire, {'scope': value['scope']})
    return value


def assessment(data, coverage='direct'):
    _, body = c.assessment_body(data); evidence = json.loads(body['input']); answers = []
    for qid, question in evidence['wire_questions'].items():
        refs = [v['claim_ref'] for v in evidence['wire_claims'].values() if v['person_id'] == question['person_id']]
        answers.append({'question_id': qid, 'coverage': coverage, 'claims': refs[:2],
            'reason': 'Fixture assessor rationale must be withheld from verification.',
            'gap': 'Fixture assessor gap must also be withheld.'})
    return c.assessment_parse(payload(json.dumps({'answers': answers}), 'openai'), data)


def verified_wire(data, value):
    evidence = c.verification_inputs(data, value)
    qids = {(q['person_id'], q['role_id']): qid for qid, q in evidence['wire_questions'].items()}
    return {'state': 'coherent', 'answers': [{'question_id': qids[(p['person_id'], p['role_id'])],
        **{k: p[k] for k in ('coverage', 'claims', 'central')},
        'reason': 'Independent fixture verification of the exact documented scientific operation.',
        'gap': 'Independent fixture limitation.'} for p in evidence['proposed_pairs']]}


class Iteration2Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture.real_data()
        blocked = patch('socket.socket.connect', side_effect=AssertionError('no_provider_traffic'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def setUp(self):
        self.data = selected(self.original)
        self.config = {'snapshot_id': 'fixture-snapshot', 'registry_generation': 'fixture-registry', 'roster_id': 'fixture-roster'}
        self.scope = copy.deepcopy(self.data['scope']) | {'source_id': 'fixture-source'}
        self.retrieval = {'eligible': 155, 'shortlist': [p['person_id'] for p in self.data['people']],
            'per_contribution': [], 'unassessed': 143, 'maximum_shortlist': 12}

    def test_selected_metadata_and_full_original_evidence_remain_in_assessment(self):
        data = selected(self.original, optional=True)
        contract, body = c.assessment_body(data); evidence = json.loads(body['input'])
        self.assertEqual(evidence['scope'], data['scope']); self.assertEqual(evidence['people'], data['people'])
        self.assertEqual(len(evidence['interpretation']['roles']), 1)
        self.assertEqual(evidence['interpretation']['considered_directions'], [data['interpretation']['roles'][1]])
        self.assertEqual(evidence['interpretation']['approach'], data['interpretation']['approach'])
        self.assertEqual(contract['input_sha256'], identity(data))
        self.assertNotEqual(contract['pair_input_sha256'], identity(data))
        self.assertEqual((body['model'], body['reasoning'], body['max_output_tokens']), ('gpt-5.6-luna', {'effort': 'low'}, 24000))
        value = assessment(data)
        self.assertEqual(sum(len(p['decisions']) for p in value['people']), 12)
        self.assertEqual(c.assessment_validate_cached(value, data), value)

    def test_persisted_json_roundtrip_keeps_exact_request_body_and_contract_identities(self):
        data = json.loads(encoded(self.data)); value = assessment(self.data)
        persisted = json.loads(encoded(value))
        self.assertEqual(c.assessment_body(self.data), c.assessment_body(data))
        self.assertEqual(c.verification_inputs(self.data, value), c.verification_inputs(data, persisted))
        self.assertEqual(c.verifier_body(self.data, value), c.verifier_body(data, persisted))
        self.assertEqual(c.verifier_resolve(verified_wire(self.data, value), self.data, value),
            c.verifier_resolve(verified_wire(data, persisted), data, persisted))

    def test_versioned_clarification_preserves_source_restrictions_and_evidence_standard(self):
        contract, _ = c.assessment_body(self.data)
        self.assertIn(c.CLARIFICATION, contract['prompt'])
        self.assertIn('Missing that\nproposal narrative alone does not downgrade', contract['prompt'])
        self.assertIn('transfer\nrequires an explicitly evidenced method plus a credible application bridge', contract['prompt'])
        self.assertIn('technology development primarily supported by other agencies', contract['prompt'])
        self.assertIn('not automatically a\nsupported contribution', contract['prompt'])
        value = assessment(self.data)
        self.assertTrue(all(p['outcome'] == 'supported' for p in value['people']))
        negative = assessment(self.data, 'adjacent')
        self.assertTrue(all(p['outcome'] == 'adjacent' for p in negative['people']))
        with self.assertRaisesRegex(ValueError, 'selected_approach_required'):
            c.assessment_body(self.original)

    def test_verifier_is_production_only_and_blind_to_assessor_explanations_outcomes(self):
        value = assessment(self.data); evidence = c.verification_inputs(self.data, value)
        self.assertEqual(evidence['scope'], self.data['scope']); self.assertEqual(evidence['people'], self.data['people'])
        text = json.dumps(evidence)
        self.assertNotIn('Fixture assessor rationale', text); self.assertNotIn('Fixture assessor gap', text)
        self.assertNotIn('"outcome"', text); self.assertNotIn('"verdict"', text)
        self.assertTrue(all(set(p) == {'person_id', 'role_id', 'source_ref', 'coverage', 'claims', 'central'} for p in evidence['proposed_pairs']))
        contract, body = c.verifier_body(self.data, value)
        self.assertNotIn('verdict', contract['schema']['properties']['answers']['items']['properties'])
        self.assertEqual((body['model'], body['thinking'], body['max_tokens']), ('claude-sonnet-5', {'type': 'disabled'}, 24000))
        self.assertIn('separate downgrade-only production verifier', body['system'])

    def test_coverage_can_only_downgrade_including_insufficient_information(self):
        for before, after, accepted in (('direct', 'method_transfer', True), ('method_transfer', 'adjacent', True),
                ('adjacent', 'insufficient_information', True), ('method_transfer', 'direct', False),
                ('adjacent', 'method_transfer', False), ('insufficient_information', 'adjacent', False)):
            with self.subTest(before=before, after=after):
                value = assessment(self.data, before); wire = verified_wire(self.data, value)
                wire['answers'][0]['coverage'] = after
                if after not in pairs.CATEGORIES[:2]: wire['answers'][0]['central'] = False
                if accepted: c.verifier_resolve(wire, self.data, value)
                else:
                    with self.assertRaisesRegex(ValueError, 'upgrade_or_new_claim'): c.verifier_resolve(wire, self.data, value)

    def test_no_new_claims_person_source_or_central_upgrade(self):
        value = assessment(self.data); wire = verified_wire(self.data, value)
        first = self.data['people'][0]
        new_owned = first['claims'][2]['claim_id']+'@'+str(first['claims'][2]['revision'])
        for change in (lambda w: w['answers'][0].update(claims=[new_owned]),
                       lambda w: w['answers'][0].update(claims=['p02c01']),
                       lambda w: w['answers'][1].update(central=True),
                       lambda w: w['answers'][0].update(source_ref='sibling')):
            changed = copy.deepcopy(wire); change(changed)
            with self.assertRaises(ValueError): c.verifier_resolve(changed, self.data, value)
        wire['answers'][0]['central'] = False
        c.verifier_resolve(wire, self.data, value)
        wire['answers'][0].update(coverage='adjacent', central=True)
        with self.assertRaisesRegex(ValueError, 'nonuseful_central'): c.verifier_resolve(wire, self.data, value)

    def test_all_pairs_and_strict_schema_are_required(self):
        value = assessment(self.data); wire = verified_wire(self.data, value)
        for change in (lambda w: w['answers'].pop(),
                       lambda w: w['answers'].__setitem__(1, copy.deepcopy(w['answers'][0])),
                       lambda w: w['answers'][0].pop('central'),
                       lambda w: w['answers'][0].update(claims=[]),
                       lambda w: w['answers'][0].update(reason='short'),
                       lambda w: w['answers'][0].update(verdict='strong')):
            changed = copy.deepcopy(wire); change(changed)
            with self.assertRaises(ValueError): c.verifier_resolve(changed, self.data, value)

    def test_response_and_cache_require_exact_complete_verified_results(self):
        value = assessment(self.data); wire = verified_wire(self.data, value)
        raw = json.dumps(wire); response = payload(raw, 'anthropic')
        verified = c.verifier_parse(response, self.data, value)
        self.assertEqual(c.verifier_validate_cached(json.loads(encoded(verified)), self.data, value), verified)
        for stop, exception in (('max_tokens', Incomplete), ('refusal', Refusal)):
            with self.assertRaises(exception): c.verifier_parse(response | {'stop_reason': stop}, self.data, value)
        duplicate = raw.replace('"state": "coherent"', '"state":"coherent","state":"coherent"')
        with self.assertRaisesRegex(ValueError, 'duplicate_response_key'): c.verifier_parse(payload(duplicate, 'anthropic'), self.data, value)
        for change in (lambda v: v['people'].pop(), lambda v: v['people'][0].update(outcome='adjacent'),
                       lambda v: v['people'][0]['decisions'][0]['claims'][0].update(revision=99),
                       lambda v: v['people'][0]['decisions'][1].update(central=True)):
            changed = copy.deepcopy(verified); change(changed)
            with self.assertRaises(ValueError): c.verifier_validate_cached(changed, self.data, value)

    def test_graph_groups_all_claims_once_per_useful_pair_and_retains_all_decisions(self):
        value = assessment(self.data); verified = c.verifier_resolve(verified_wire(self.data, value), self.data, value)
        graph = c.adapter(self.data, value, verified, self.config, self.scope, self.retrieval, [{'cache_hit': False}])
        self.assertEqual(graph['version'], 'contextual-audited-graph-v3')
        self.assertEqual(len(graph['edges']), 24)
        self.assertEqual(sum(len(e['supporting_claims']) for e in graph['edges']), 48)
        self.assertEqual(graph['pair_decisions'], verified['people'])
        for edge in graph['edges']:
            primary = edge['supporting_claims'][0]
            self.assertEqual((edge['claim_id'], edge['claim_revision'], edge['evidence_quote']),
                (primary['claim_id'], primary['revision'], primary['evidence']))
        self.assertEqual(graph['state'], 'ready'); self.assertEqual(graph['conditions'], self.data['scope']['conditions'])
        self.assertFalse(graph['provenance']['independent_checker_used_for_admission'])
        again = c.adapter(self.data, value, verified, self.config, self.scope, self.retrieval, [{'cache_hit': True}])
        self.assertEqual(graph['graph_id'], again['graph_id'])
        changed_scope = copy.deepcopy(self.scope); changed_scope['science']['title'] += ' tampered'
        with self.assertRaisesRegex(ValueError, 'source_identity'):
            c.adapter(self.data, value, verified, self.config, changed_scope, self.retrieval, [])

    def test_malformed_bounded_response_and_cache_shapes_fail_closed(self):
        value = assessment(self.data); wire = verified_wire(self.data, value)
        for response in (None, {'content': None}, {'content': [None]},
                         payload('NaN', 'anthropic')):
            with self.assertRaises(ValueError): c.verifier_parse(response, self.data, value)
        oversized = payload(' ' * (pairs.MAX_FINAL_BYTES + 1), 'anthropic')
        with patch.object(c, 'response_value', side_effect=AssertionError('must_bound_before_parse')):
            with self.assertRaisesRegex(ValueError, 'response_bytes'):
                c.verifier_parse(oversized, self.data, value)
        verified = c.verifier_resolve(wire, self.data, value)
        unknown = copy.deepcopy(verified); unknown['people'][0]['person_id'] = 'unknown'
        malformed = copy.deepcopy(verified); malformed['people'][0]['decisions'][0]['claim_refs'] = None
        for cached in (None, {}, unknown, malformed):
            with self.assertRaisesRegex(ValueError, 'cache_shape'):
                c.verifier_validate_cached(cached, self.data, value)

    def test_optional_directions_are_preserved_but_never_edges_or_gaps(self):
        data = selected(self.original, optional=True); value = assessment(data)
        verified = c.verifier_resolve(verified_wire(data, value), data, value)
        graph = c.adapter(data, value, verified, self.config, self.scope, self.retrieval, [])
        self.assertEqual([r['id'] for r in graph['roles']], ['role-1'])
        self.assertEqual([r['id'] for r in graph['considered_directions']], ['role-2'])
        self.assertEqual({e['role_id'] for e in graph['edges']}, {'role-1'})
        self.assertEqual(graph['state'], 'ready'); self.assertEqual(len(graph['edges']), 12)

    def test_six_roles_allow_72_grouped_edges_without_claim_expansion(self):
        data = selected(self.original, role_count=6); value = assessment(data)
        verified = c.verifier_resolve(verified_wire(data, value), data, value)
        graph = c.adapter(data, value, verified, self.config, self.scope, self.retrieval, [])
        self.assertEqual(len(graph['edges']), 72)
        self.assertEqual(sum(len(p['decisions']) for p in graph['pair_decisions']), 72)

    def test_no_supported_group_and_noncoherent_source_abstain_without_losing_pairs(self):
        value = assessment(self.data, 'adjacent'); wire = verified_wire(self.data, value)
        verified = c.verifier_resolve(wire, self.data, value)
        graph = c.adapter(self.data, value, verified, self.config, self.scope, self.retrieval, [])
        self.assertEqual(graph['state'], 'no_supported_group_in_assessed_set'); self.assertEqual(graph['edges'], [])
        self.assertEqual(sum(len(p['decisions']) for p in graph['pair_decisions']), 24)
        wire['state'] = 'unsuitable'
        with self.assertRaises(ValueError): c.verifier_resolve(wire, self.data, value)
        for row in wire['answers']: row.update(coverage='insufficient_information', claims=[], central=False)
        verified = c.verifier_resolve(wire, self.data, value)
        graph = c.adapter(self.data, value, verified, self.config, self.scope, self.retrieval, [])
        self.assertEqual(graph['state'], 'unsuitable'); self.assertEqual(graph['edges'], [])

    def test_historical_iteration_one_transport_identity_is_unchanged(self):
        lock = json.loads(Path('config/contextual_team/completion-check-v1.json').read_bytes())
        for op in lock['operations'].values():
            contract, body = historical.body(self.original, transport=op['transport'])
            self.assertEqual(identity(contract), op['contract_sha256']); self.assertEqual(identity(body), op['body_sha256'])


if __name__ == '__main__': unittest.main()
