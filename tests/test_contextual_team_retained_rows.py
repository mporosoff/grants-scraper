"""Exact real input identities; fixture scientific results and no network."""
import copy
import json
import unittest
from unittest.mock import patch
import test_contextual_team_luna_repair as fixture
from test_contextual_team_shared_rows import answer as addressed_answer
from tools import contextual_team_retained_rows as recovery
from tools import contextual_team_shared_rows as rows
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_luna_policy as saved
from tools.offline_spend import identity, encoded


def canonical_answer(data):
    value = addressed_answer(data)
    questions, _, owners = rows.mapping(data)
    for row in value['answers']:
        owned = owners[questions[row['question_id']]['person_id']]
        row['claims'] = [owned[address] for address in row['claims']]
    return value


class RetainedRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixture.real_data()
        blocked = patch('socket.socket.connect', side_effect=AssertionError('zero_provider_recovery'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def recover(self, value, data=None):
        return recovery.recover(json.dumps(value, ensure_ascii=False), data or self.data)

    def test_complete_exact_recovery_is_lossless_and_leaves_inputs_unchanged(self):
        self.assertEqual(identity(self.data), saved.plan()['input_sha256'])
        value = canonical_answer(self.data); original = copy.deepcopy(value); data = copy.deepcopy(self.data)
        expected = pairs.resolve(fixture.answer(self.data, True), self.data, judge=True)
        resolved = self.recover(value)
        self.assertEqual(resolved, expected)
        self.assertEqual(value, original); self.assertEqual(self.data, data)
        self.assertEqual((len(resolved['people']), sum(len(p['decisions']) for p in resolved['people'])), (12, 24))
        self.assertEqual(pairs.validate_cached(json.loads(encoded(resolved)), self.data, judge=True), resolved)
        value['answers'].reverse()
        self.assertEqual(self.recover(value), resolved)

    def test_versioned_contract_binds_original_science_schema_and_mapping(self):
        contract = recovery.contract(self.data)
        self.assertEqual(contract['version'], 'iteration1-canonical-claim-alias-recovery-v1')
        self.assertEqual(contract['input_sha256'], saved.plan()['input_sha256'])
        self.assertEqual(contract['canonical_contract_sha256'], identity(pairs.contract(self.data, judge=True)))
        self.assertEqual(contract['shared_rows_schema_sha256'], identity(rows.schema(self.data)))
        self.assertFalse(contract['serving_approved'])
        changed = copy.deepcopy(self.data); changed['people'][0]['claims'].pop(0)
        self.assertNotEqual(identity(recovery.contract(changed)), identity(contract))

    def test_canonical_only_rejects_aliases_mixed_unknown_foreign_and_stale_claims(self):
        valid = canonical_answer(self.data)
        foreign = valid['answers'][2]['claims'][0]
        old = valid['answers'][0]['claims'][0].rsplit('@', 1)[0] + '@999'
        for claims in (['p01c01'], [valid['answers'][0]['claims'][0], 'p01c02'],
                       ['urh-999999-c001@2'], [foreign], [old]):
            with self.subTest(claims=claims):
                value = copy.deepcopy(valid); value['answers'][0]['claims'] = claims
                with self.assertRaises(ValueError): self.recover(value)

    def test_retired_cited_claim_cannot_be_recovered_or_substituted(self):
        value = canonical_answer(self.data); changed = copy.deepcopy(self.data)
        retired = value['answers'][0]['claims'][0].rsplit('@', 1)[0]
        changed['people'][0]['claims'] = [c for c in changed['people'][0]['claims'] if c['claim_id'] != retired]
        with self.assertRaisesRegex(ValueError, 'exact_canonical_owner_revision'): self.recover(value, changed)

    def test_missing_duplicate_extra_questions_and_changed_fields_fail_closed(self):
        mutations = [lambda v: v['answers'].pop(),
            lambda v: v['answers'].append(copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'].__setitem__(1, copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'][0].update(question_id='q25'),
            lambda v: v['answers'][0].update(source_ref='forged'),
            lambda v: v['answers'][0].update(grade='strong'),
            lambda v: v['answers'][0].pop('gap'),
            lambda v: v['answers'][0].update(reason='short'),
            lambda v: v['answers'][0].update(gap='x'*301),
            lambda v: v['answers'][0].update(verdict='supported'),
            lambda v: v['answers'][0].update(coverage='strong'),
            lambda v: v.update(extra=True)]
        for index, mutate in enumerate(mutations):
            value = canonical_answer(self.data); mutate(value)
            with self.subTest(mutation=index):
                with self.assertRaises(ValueError): self.recover(value)

    def test_duplicate_claims_and_unsupported_positive_cannot_be_salvaged(self):
        for claims in ([], ['urh-000027-c001@2']*2, ['urh-000027-c001@2']*4):
            value = canonical_answer(self.data); value['answers'][0]['claims'] = claims
            with self.subTest(claims=claims):
                with self.assertRaises(ValueError): self.recover(value)

    def test_all_scientific_grades_reasons_and_gaps_are_preserved(self):
        value = canonical_answer(self.data)
        categories = pairs.CATEGORIES
        verdicts = ('strong', 'plausible', 'unrelated', 'insufficient-information')
        for index, row in enumerate(value['answers']):
            row.update(coverage=categories[index % 4], verdict=verdicts[index % 4],
                reason='Preserve this exact reason with Unicode \u03b1\u03b2, number '+str(index)+'.',
                gap='Original limitation '+str(index)+'.')
            if index % 4 > 1: row['claims'] = []
        resolved = self.recover(value); questions, _, _ = rows.mapping(self.data)
        canonical = {(p['person_id'], d['role_id']): d for p in resolved['people'] for d in p['decisions']}
        for row in value['answers']:
            q = questions[row['question_id']]; decision = canonical[(q['person_id'], q['role_id'])]
            for key in ('coverage', 'verdict', 'reason', 'gap'): self.assertEqual(decision[key], row[key])
            self.assertEqual([r for r in decision['claim_refs'].values() if r != pairs.NONE], row['claims'])
        # Scientific negatives remain complete results, without invented support.
        for row in value['answers']: row.update(coverage='insufficient_information', verdict='insufficient-information', claims=[])
        self.assertTrue(all(p['outcome'] == 'insufficient_information' for p in self.recover(value)['people']))

    def test_duplicate_json_keys_malformed_prose_non_json_constants_and_bounds_rejected(self):
        text = json.dumps(canonical_answer(self.data))
        duplicate = '{"answers":[],"answers":'+json.dumps(canonical_answer(self.data)['answers'])+'}'
        nested = text.replace('"question_id": "q01"', '"question_id":"q01","question_id":"q01"')
        for raw in (duplicate, nested, '{', '```json\n'+text+'\n```', text+' prose', 'NaN', 'null', '[]', 123):
            with self.subTest(raw=str(raw)[:25]):
                with self.assertRaises(ValueError): recovery.recover(raw, self.data)
        with self.assertRaisesRegex(ValueError, 'final_text_bound'):
            recovery.recover('x'*(pairs.MAX_FINAL_BYTES+1), self.data)

    def test_other_population_or_question_dimensions_are_not_this_recovery(self):
        for people, roles in ((11, 2), (12, 1)):
            changed = copy.deepcopy(self.data)
            changed['people'] = changed['people'][:people]
            changed['interpretation']['roles'] = changed['interpretation']['roles'][:roles]
            with self.assertRaises(ValueError): recovery.contract(changed)
            with self.assertRaises(ValueError): recovery.recover(json.dumps(canonical_answer(self.data)), changed)


if __name__ == '__main__': unittest.main()
