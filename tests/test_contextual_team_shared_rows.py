"""Real scientific input identities; fixture answers, never provider traffic."""
import copy
import json
import unittest
from unittest.mock import patch
import test_contextual_team_luna_repair as fixture
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_check_wire as previous
from tools import contextual_team_luna_policy as saved
from tools import contextual_team_wire_repair as historical
from tools import contextual_team_shared_rows as rows
from tools.offline_ai import validate_schema
from tools.offline_spend import identity, encoded, Incomplete, Refusal


def answer(data):
    canonical = fixture.answer(data, True)
    questions, _, owners = rows.mapping(data)
    answers = []
    for qid, q in questions.items():
        original = canonical['decisions'][q['person_id']][q['role_id']]
        addresses = {ref: address for address, ref in owners[q['person_id']].items()}
        answers.append({'question_id': qid,
            **{k: original[k] for k in ('coverage', 'verdict', 'reason', 'gap')},
            'claims': [addresses[ref] for ref in original['claim_refs'].values() if ref != pairs.NONE]})
    return {'answers': answers}


class SharedRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixture.real_data()
        blocked = patch('socket.socket.connect', side_effect=AssertionError('no_provider_traffic'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def test_actual_identity_original_evidence_and_blind_rubric(self):
        self.assertEqual(identity(self.data), saved.plan()['input_sha256'])
        original_data = copy.deepcopy(self.data)
        canonical, original = pairs.body(self.data, judge=True)
        evidence = json.loads(original['messages'][0]['content'])
        for version in (rows.STRICT_VERSION, rows.TEXT_VERSION):
            contract, body = rows.body(self.data, transport=version)
            supplied = json.loads(body['messages'][0]['content'])
            self.assertEqual({k: supplied[k] for k in evidence}, evidence)
            self.assertEqual(set(supplied)-set(evidence), {'wire_questions', 'wire_claims'})
            self.assertEqual(set(supplied), {'scope', 'interpretation', 'people', 'claim_references',
                'wire_questions', 'wire_claims'})
            self.assertEqual(contract['canonical_contract_sha256'], identity(canonical))
            self.assertEqual((len(supplied['people']), len(supplied['wire_questions'])), (12, 24))
            self.assertTrue(body['system'].startswith(original['system'] + rows.FORMAT))
            self.assertEqual((body['model'], body['thinking'], body['max_tokens']),
                ('claude-sonnet-5', {'type': 'disabled'}, 12000))
            self.assertFalse(contract['serving_approved'])
        self.assertEqual(self.data, original_data)
        for name in ('assessment', 'check'):
            c, b = pairs.body(self.data, judge=name == 'check')
            self.assertEqual(identity(c), saved.plan()['operations'][name]['contract_sha256'])
            self.assertEqual(identity(b), saved.plan()['operations'][name]['body_sha256'])
        c, b = previous.body(self.data)
        self.assertEqual(identity(c), historical.plan()['contract_sha256'])
        self.assertEqual(identity(b), historical.plan()['body_sha256'])

    def test_one_shared_native_row_and_explicit_equivalent_text_transport(self):
        strict, native = rows.body(self.data)
        text, ordinary = rows.body(self.data, transport=rows.TEXT_VERSION)
        self.assertNotEqual(identity(native), identity(ordinary))
        self.assertNotEqual(identity(strict), identity(text))
        self.assertEqual(strict['schema'], text['schema'])
        self.assertEqual(native['messages'], ordinary['messages'])
        self.assertEqual(ordinary['system'], native['system'] + rows.TEXT_FORMAT)
        self.assertNotIn('output_config', ordinary)
        schema = native['output_config']['format']['schema']
        self.assertEqual(set(schema['properties']), {'answers'})
        self.assertEqual(schema['properties']['answers']['items']['type'], 'object')
        self.assertLess(len(encoded(schema)), 2000)
        self.assertLess(len(encoded(schema)), len(encoded(previous.body(self.data)[1]['output_config']['format']['schema'])))
        validate_schema(answer(self.data), schema)
        with self.assertRaisesRegex(ValueError, 'unknown_transport'):
            rows.body(self.data, transport='unversioned')

    def test_lossless_all_people_pairs_sources_claims_revisions_and_cache(self):
        value = answer(self.data)
        expected = pairs.resolve(fixture.answer(self.data, True), self.data, judge=True)
        resolved = rows.resolve(value, self.data)
        self.assertEqual(resolved, expected)
        self.assertEqual(pairs.validate_cached(json.loads(encoded(resolved)), self.data, judge=True), resolved)
        value['answers'].reverse()
        self.assertEqual(rows.resolve(value, self.data), expected)
        self.assertEqual(len(resolved['people']), 12)
        self.assertEqual(sum(len(p['decisions']) for p in resolved['people']), 24)
        self.assertEqual(sum(p['outcome'] == 'supported' for p in resolved['people']), 7)
        self.assertEqual(resolved['people'][7]['outcome'], 'credible_transfer')

    def test_completeness_duplicate_foreign_unknown_and_extra_fields_rejected(self):
        mutations = [lambda v: v['answers'].pop(),
            lambda v: v['answers'].append(copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'].__setitem__(1, copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'][0].update(question_id='q25'),
            lambda v: v['answers'][0].update(claims=['p02c01']),
            lambda v: v['answers'][0].update(claims=['p01c99']),
            lambda v: v['answers'][0].update(claims=['p01c01@99']),
            lambda v: v['answers'][0].update(source_ref='sibling'),
            lambda v: v['answers'][0].update(person_id='sibling'),
            lambda v: v['answers'][0].pop('verdict'),
            lambda v: v.update(decisions={})]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                value = answer(self.data); mutate(value)
                with self.assertRaises(ValueError): rows.resolve(value, self.data)

    def test_claim_support_and_string_category_bounds_never_weakened(self):
        mutations = [('claims', []), ('claims', ['p01c01', 'p01c01']),
            ('claims', ['p01c01'] * 4), ('claims', [None]), ('coverage', 'strong'),
            ('verdict', 'supported'), ('reason', 'short'), ('reason', 'x' * 701),
            ('gap', 'x' * 301), ('gap', None)]
        for key, replacement in mutations:
            with self.subTest(field=key, replacement=replacement):
                value = answer(self.data); value['answers'][0][key] = replacement
                with self.assertRaises(ValueError): rows.resolve(value, self.data)
        value = answer(self.data)
        value['answers'][0]['reason'] = '\u03b1' * 700
        value['answers'][0]['gap'] = '\u03b2' * 300
        rows.resolve(value, self.data)

    def test_complete_negative_outcomes_are_results(self):
        value = answer(self.data)
        for row in value['answers']:
            row.update(coverage='insufficient_information', claims=[], verdict='insufficient-information')
        resolved = rows.resolve(value, self.data)
        self.assertTrue(all(p['outcome'] == 'insufficient_information' for p in resolved['people']))
        value['answers'][0].update(coverage='adjacent', verdict='unrelated')
        self.assertEqual(rows.resolve(value, self.data)['people'][0]['outcome'], 'adjacent')

    def test_response_completion_refusal_malformed_duplicates_and_byte_bound(self):
        value = answer(self.data)
        payload = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(value)}]}
        self.assertEqual(rows.parse(payload, self.data), rows.resolve(value, self.data))
        for stop, exception in (('max_tokens', Incomplete), ('refusal', Refusal), ('tool_use', Incomplete)):
            with self.assertRaises(exception): rows.parse(payload | {'stop_reason': stop}, self.data)
        for invalid in (None, [], {}, payload | {'content': None}, payload | {'content': [None]}):
            with self.subTest(envelope=invalid):
                with self.assertRaises((ValueError, Incomplete)): rows.parse(invalid, self.data)
        duplicate = '{"answers":' + json.dumps(value['answers']) + ',"answers":' + json.dumps(value['answers']) + '}'
        nested = json.dumps(value).replace('"question_id": "q01"', '"question_id":"q01","question_id":"q01"')
        for raw in ('{', '```json\n' + json.dumps(value) + '\n```', duplicate, nested):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(ValueError):
                    rows.parse(payload | {'content': [{'type': 'text', 'text': raw}]}, self.data)
        with self.assertRaisesRegex(ValueError, 'response_bytes'):
            rows.parse(payload | {'content': [{'type': 'text', 'text': 'x' * (pairs.MAX_FINAL_BYTES + 1)}]}, self.data)

    def test_canonical_cache_tampering_cannot_pass_local_validator(self):
        resolved = rows.resolve(answer(self.data), self.data)
        mutations = [lambda v: v['people'].pop(),
            lambda v: v['people'][0]['decisions'].pop(),
            lambda v: v['people'][0].update(outcome='supported-invented'),
            lambda v: v['people'][0]['decisions'][0]['claims'][0].update(revision=999),
            lambda v: v['people'][0]['decisions'][0]['source'].update(source_ref='sibling'),
            lambda v: v.update(input_sha256='0' * 64)]
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(resolved); mutate(value)
            with self.subTest(mutation=index):
                with self.assertRaises(ValueError): pairs.validate_cached(value, self.data, judge=True)

    def test_retired_claim_cannot_validate_a_previously_cached_decision(self):
        resolved = rows.resolve(answer(self.data), self.data)
        changed = copy.deepcopy(self.data)
        retired = resolved['people'][0]['decisions'][0]['claims'][0]['claim_id']
        changed['people'][0]['claims'] = [c for c in changed['people'][0]['claims'] if c['claim_id'] != retired]
        self.assertNotEqual(identity(changed), identity(self.data))
        with self.assertRaises(ValueError): pairs.validate_cached(resolved, changed, judge=True)


if __name__ == '__main__':
    unittest.main()
