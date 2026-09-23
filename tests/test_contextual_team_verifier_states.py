"""Real identities/source evidence, synthetic answers, and forbidden network IO."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_contextual_team_iteration2_contract as fixtures
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration2_contract as original
from tools import contextual_team_iteration3_references as references
from tools import contextual_team_verifier_states as states
from tools.offline_spend import encoded, identity, Refusal, Incomplete


def wire(data, assessment):
    value = fixtures.verified_wire(data, assessment)
    inverse = {pair: state for state, pair in states.SUPPORT_STATES.items()}
    for row in value['answers']:
        row['support_state'] = inverse[(row.pop('coverage'), row.pop('central'))]
    return value


class VerifierStates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blocker = patch('socket.socket.connect', side_effect=AssertionError('no network'))
        blocker.start(); cls.addClassCleanup(blocker.stop)
        cls.data = fixtures.selected(fixtures.fixture.real_data())
        cls.assessment = fixtures.assessment(cls.data)

    def parse(self, value, data=None, assessment=None):
        return states.verifier_parse(payload(json.dumps(value), 'anthropic'),
            self.data if data is None else data, self.assessment if assessment is None else assessment)

    def test_original_evidence_prompts_bodies_and_assessor_blinding_are_preserved(self):
        old = references.verifier_body(self.data, self.assessment)
        old_assessment = references.assessment_body(self.data)
        before = encoded([self.data, self.assessment])
        contract, body = states.verifier_body(self.data, self.assessment)
        old_input = json.loads(old[1]['messages'][0]['content'])
        new_input = json.loads(body['messages'][0]['content'])
        for q in new_input['wire_questions'].values():
            self.assertTrue(q.pop('allowed_support_states'))
        self.assertEqual(new_input, old_input)
        self.assertNotIn('Fixture assessor rationale', body['messages'][0]['content'])
        self.assertNotIn('Fixture assessor gap', body['messages'][0]['content'])
        self.assertIn(original.CLARIFICATION, contract['prompt'])
        self.assertIn(references.POLICY, contract['prompt'])
        self.assertIn(references.REFERENCE_FORMAT, contract['prompt'])
        self.assertNotIn('Each row contains question_id, coverage', contract['prompt'])
        self.assertEqual(contract['preceding_transport_contract_sha256'], identity(old[0]))
        self.assertNotEqual(identity(contract), identity(old[0]))
        self.assertNotEqual(identity(body), identity(old[1]))
        self.assertEqual((body['model'], body['thinking'], body['max_tokens']),
            ('claude-sonnet-5', {'type': 'disabled'}, 24000))
        self.assertEqual(references.verifier_body(self.data, self.assessment), old)
        self.assertEqual(references.assessment_body(self.data), old_assessment)
        self.assertEqual(encoded([self.data, self.assessment]), before)
        self.assertEqual(states.verifier_body(*json.loads(before)), (contract, body))

    def test_all_six_states_decode_to_unchanged_scientific_results(self):
        for state, (coverage, central) in states.SUPPORT_STATES.items():
            value = wire(self.data, self.assessment)
            row = value['answers'][0]
            row['support_state'] = state
            if coverage == 'insufficient_information': row['claims'] = []
            ordinary = fixtures.verified_wire(self.data, self.assessment)
            ordinary['answers'][0].update(coverage=coverage, central=central, claims=row['claims'])
            with self.subTest(state=state):
                expected = original.verifier_resolve(ordinary, self.data, self.assessment)
                value['answers'].reverse()
                actual = self.parse(value)
                self.assertEqual(actual, expected)
                self.assertEqual(states.verifier_validate_cached(json.loads(encoded(actual)),
                    self.data, self.assessment), actual)

    def test_complete_source_abstentions_and_positive_support_constraints(self):
        for state in ('needs_scope_selection', 'insufficient_source', 'unsuitable'):
            value = wire(self.data, self.assessment)
            value['state'] = state
            for row in value['answers']:
                row.update(support_state='insufficient_information', claims=[])
            self.assertEqual(self.parse(value)['state'], state)
            value['answers'][0]['claims'] = wire(self.data, self.assessment)['answers'][0]['claims']
            with self.assertRaisesRegex(ValueError, 'noncoherent'):
                self.parse(value)
        value = wire(self.data, self.assessment)
        value['answers'][0]['claims'] = []
        with self.assertRaises(ValueError): self.parse(value)

    def test_question_specific_coverage_and_central_ceilings_are_enforced(self):
        for coverage in ('method_transfer', 'adjacent', 'insufficient_information'):
            assessed = fixtures.assessment(self.data, coverage)
            value = wire(self.data, assessed)
            value['answers'][0]['support_state'] = 'direct_central'
            with self.subTest(coverage=coverage), self.assertRaisesRegex(ValueError, 'states_upgrade'):
                self.parse(value, assessment=assessed)
        data = deepcopy(self.data)
        data['interpretation']['roles'][0]['central'] = False
        data['interpretation']['roles'][1]['central'] = True
        assessed = fixtures.assessment(data)
        value = wire(data, assessed)
        value['answers'][0]['support_state'] = 'direct_central'
        with self.assertRaisesRegex(ValueError, 'states_upgrade'):
            self.parse(value, data, assessed)

    def test_real_ownership_revisions_completeness_and_exact_wire_fields(self):
        _, body = states.verifier_body(self.data, self.assessment)
        evidence = json.loads(body['messages'][0]['content'])
        first = next(iter(evidence['wire_questions'].values()))
        foreign = next(q['allowed_claim_refs'][0] for q in evidence['wire_questions'].values()
            if q['person_id'] != first['person_id'])
        for defect in ('foreign', 'retired', 'alias', 'duplicate_claim', 'missing',
                       'duplicate_question', 'invented_question', 'coverage', 'central',
                       'contradictory_state', 'placeholder', 'padded_reason'):
            value = wire(self.data, self.assessment); row = value['answers'][0]
            if defect == 'foreign': row['claims'] = [foreign]
            elif defect == 'retired': row['claims'] = [row['claims'][0].split('@')[0]+'@999']
            elif defect == 'alias': row['claims'] = [next(iter(evidence['wire_claims']))]
            elif defect == 'duplicate_claim': row['claims'] = [row['claims'][0]]*2
            elif defect == 'missing': value['answers'].pop()
            elif defect == 'duplicate_question': value['answers'][-1] = deepcopy(row)
            elif defect == 'invented_question': row['question_id'] = 'q999'
            elif defect == 'coverage': row['coverage'] = 'direct'
            elif defect == 'central': row['central'] = True
            elif defect == 'contradictory_state': row['support_state'] = 'insufficient_information_central'
            elif defect == 'placeholder': row['reason'] = 'to be completed'
            else: row['reason'] = 'x'+' '*20
            with self.subTest(defect=defect), self.assertRaises(ValueError): self.parse(value)

    def test_cache_tampering_and_original_contradiction_remain_rejected(self):
        invalid = fixtures.verified_wire(self.data, self.assessment)
        invalid['answers'][0].update(coverage='insufficient_information', central=True, claims=[])
        with self.assertRaisesRegex(ValueError, 'nonuseful_central'):
            references.verifier_parse(payload(json.dumps(invalid), 'anthropic'), self.data, self.assessment)
        with self.assertRaises(ValueError): self.parse(invalid)
        accepted = self.parse(wire(self.data, self.assessment))
        for defect in ('central', 'source', 'reason', 'owner', 'version', 'input'):
            value = deepcopy(accepted); decision = value['people'][0]['decisions'][0]
            if defect == 'central': decision['central'] = not decision['central']
            elif defect == 'source': decision['source_ref'] = 'foreign-source'
            elif defect == 'reason': decision['reason'] = 'x'+' '*20
            elif defect == 'owner': value['people'][0]['person_id'] = 'urh-999999'
            elif defect == 'version': value['version'] = states.VERSION
            else: value['input_sha256'] = '0'*64
            # A central downgrade is scientifically valid, so exercise the invalid
            # non-useful combination instead of treating every edit as forbidden.
            if defect == 'central': decision.update(coverage='adjacent', central=True)
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                states.verifier_validate_cached(value, self.data, self.assessment)

    def test_provider_completion_duplicate_keys_and_byte_bounds(self):
        text = json.dumps(wire(self.data, self.assessment))
        for stop, error in (('max_tokens', Incomplete), ('refusal', Refusal)):
            response = payload(text, 'anthropic'); response['stop_reason'] = stop
            with self.assertRaises(error): states.verifier_parse(response, self.data, self.assessment)
        for bad in ('{"state":"coherent",'+text[1:], text.replace('"state": "coherent"', '"state": NaN'),
                    text[:-1], ' '*states.pairs.MAX_FINAL_BYTES+text):
            with self.assertRaises(ValueError):
                states.verifier_parse(payload(bad, 'anthropic'), self.data, self.assessment)

    def test_supported_frame_extremes_keep_all_people_and_questions(self):
        for people in (1, 12):
            for roles in (1, 6):
                data = fixtures.selected(fixtures.fixture.real_data(), role_count=roles)
                data['people'] = data['people'][:people]
                assessed = fixtures.assessment(data)
                value = wire(data, assessed)
                self.assertEqual(len(value['answers']), people*roles)
                parsed = self.parse(value, data, assessed)
                self.assertEqual(len(parsed['people']), people)
                self.assertEqual(sum(len(p['decisions']) for p in parsed['people']), people*roles)


if __name__ == '__main__': unittest.main()
