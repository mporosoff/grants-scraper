"""Fixed real scientific inputs and synthetic wire replies, no network."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_contextual_team_iteration2_contract as fixtures
from test_contextual_team_answer_rows import payload
from tools import contextual_team_iteration2_contract as original
from tools import contextual_team_iteration3_references as corrected
from tools.offline_spend import encoded, identity


class References(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixtures.selected(fixtures.fixture.real_data())
        blocker = patch('socket.socket.connect', side_effect=AssertionError('no network'))
        blocker.start(); cls.addClassCleanup(blocker.stop)

    def answers(self):
        _, body = corrected.assessment_body(self.data); evidence = json.loads(body['input'])
        return {'answers': [{'question_id': qid, 'coverage': 'method_transfer',
            'claims': q['allowed_claim_refs'][:1], 'reason': 'Documented method provides a qualified project-specific transfer.',
            'gap': 'The precise operational application is not established.'}
            for qid, q in evidence['wire_questions'].items()]}

    def test_complete_original_evidence_and_original_contracts_are_immutable(self):
        old = original.assessment_body(self.data); before = encoded(self.data)
        contract, body = corrected.assessment_body(self.data)
        old_evidence = json.loads(old[1]['input']); new = json.loads(body['input'])
        for key in old_evidence:
            if key != 'wire_questions': self.assertEqual(new[key], old_evidence[key])
        self.assertEqual(set(new['wire_questions']), set(old_evidence['wire_questions']))
        for qid, question in new['wire_questions'].items():
            self.assertEqual({k:v for k,v in question.items() if k!='allowed_claim_refs'}, old_evidence['wire_questions'][qid])
        self.assertEqual(original.assessment_body(self.data), old)
        self.assertEqual(encoded(self.data), before)
        self.assertEqual(contract['original_contract_sha256'], identity(old[0]))
        self.assertNotEqual(identity(body), identity(old[1]))
        self.assertEqual(corrected.assessment_body(json.loads(before)), (contract, body))
        self.assertEqual((body['model'], body['reasoning'], body['max_output_tokens']), ('gpt-5.6-luna', {'effort':'low'},24000))

    def test_real_owned_canonical_inventory_is_the_complete_generation_enum(self):
        contract, body = corrected.assessment_body(self.data); evidence = json.loads(body['input'])
        allowed = contract['schema']['properties']['answers']['items']['properties']['claims']['items']['enum']
        expected = {v['claim_ref'] for v in evidence['wire_claims'].values()}
        self.assertEqual(set(allowed), expected)
        for q in evidence['wire_questions'].values():
            self.assertEqual(set(q['allowed_claim_refs']), {v['claim_ref'] for v in evidence['wire_claims'].values() if v['person_id']==q['person_id']})

    def test_positive_transfer_negative_and_reordered_complete_responses_roundtrip(self):
        wire = self.answers(); wire['answers'].reverse()
        wire['answers'][0].update(coverage='insufficient_information', claims=[])
        parsed = corrected.assessment_parse(payload(json.dumps(wire),'openai'), self.data)
        self.assertEqual(corrected.assessment_validate_cached(json.loads(encoded(parsed)),self.data), parsed)
        self.assertEqual(parsed, original.assessment_parse(payload(json.dumps(wire),'openai'),self.data))

    def test_nonexistent_foreign_retired_duplicate_missing_and_stub_responses_fail(self):
        _, body = corrected.assessment_body(self.data); questions = json.loads(body['input'])['wire_questions']
        for kind in ('nonexistent','foreign','retired','duplicate','missing','placeholder'):
            wire = self.answers(); row = wire['answers'][0]
            if kind=='nonexistent': row['claims']=['urh-000007-c005@999']
            elif kind=='retired': row['claims']=[row['claims'][0].split('@')[0]+'@999']
            elif kind=='foreign':
                owner = questions[row['question_id']]['person_id']
                row['claims'] = next(q['allowed_claim_refs'][:1] for q in questions.values() if q['person_id']!=owner)
            elif kind=='duplicate': wire['answers'][-1]=deepcopy(row)
            elif kind=='missing': wire['answers'].pop()
            else: row['reason']='placeholder'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                corrected.assessment_parse(payload(json.dumps(wire),'openai'),self.data)

    def test_verifier_allowed_refs_are_pair_owned_and_cannot_upgrade_or_add_support(self):
        assessed = fixtures.assessment(self.data, 'method_transfer')
        contract, body = corrected.verifier_body(self.data, assessed)
        evidence = json.loads(body['messages'][0]['content'])
        proposed = {(p['person_id'],p['role_id']):p for p in evidence['proposed_pairs']}
        for q in evidence['wire_questions'].values():
            self.assertEqual(q['allowed_claim_refs'], proposed[(q['person_id'],q['role_id'])]['claims'])
        self.assertNotIn('Fixture assessor rationale', body['messages'][0]['content'])
        wire=fixtures.verified_wire(self.data,assessed)
        parsed=corrected.verifier_parse(payload(json.dumps(wire),'anthropic'),self.data,assessed)
        self.assertEqual(corrected.verifier_validate_cached(parsed,self.data,assessed),parsed)
        wire['answers'][0]['coverage']='direct'
        with self.assertRaises(ValueError): corrected.verifier_parse(payload(json.dumps(wire),'anthropic'),self.data,assessed)

    def test_cached_assessment_cannot_bypass_the_new_substantive_reason_guard(self):
        value=corrected.assessment_parse(payload(json.dumps(self.answers()),'openai'),self.data)
        value['people'][0]['decisions'][0]['reason']='to be completed'
        with self.assertRaisesRegex(ValueError,'substantive_reason'):
            corrected.assessment_validate_cached(value,self.data)

    def test_whitespace_padding_cannot_satisfy_either_parse_or_cache_reason_minimum(self):
        wire=self.answers();wire['answers'][0]['reason']='x'+' '*20
        with self.assertRaisesRegex(ValueError,'substantive_reason'):
            corrected.assessment_parse(payload(json.dumps(wire),'openai'),self.data)
        assessed=fixtures.assessment(self.data,'method_transfer')
        wire=fixtures.verified_wire(self.data,assessed);wire['answers'][0]['reason']='x'+' '*20
        with self.assertRaisesRegex(ValueError,'substantive_reason'):
            corrected.verifier_parse(payload(json.dumps(wire),'anthropic'),self.data,assessed)
        value=deepcopy(assessed);value['people'][0]['decisions'][0]['reason']='x'+' '*20
        with self.assertRaisesRegex(ValueError,'substantive_reason'):
            corrected.assessment_validate_cached(value,self.data)
        value=original.verifier_resolve(wire,self.data,assessed)
        with self.assertRaisesRegex(ValueError,'substantive_reason'):
            corrected.verifier_validate_cached(value,self.data,assessed)


if __name__=='__main__': unittest.main()
