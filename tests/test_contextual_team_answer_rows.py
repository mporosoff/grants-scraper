"""Future ordinary transport: exact references, complete rows and no paid IO."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_contextual_team_luna_repair as fixture
from tools import contextual_team_answer_rows as rows
from tools import contextual_team_shared_rows as historical
from tools import contextual_team_retained_rows as recovery
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_luna_policy as saved
from tools.offline_ai import validate_schema
from tools.offline_spend import identity, encoded, Refusal, Incomplete


def answer(data, *, judge=False, form='canonical'):
    original = fixture.answer(data, judge)
    questions, _, owners = rows.mapping(data); result = []
    for qid, q in questions.items():
        value = original['decisions'][q['person_id']][q['role_id']]
        refs = [ref for ref in value['claim_refs'].values() if ref != pairs.NONE]
        inverse = {ref: alias for alias, ref in owners[q['person_id']].items()}
        claims = [inverse[ref] if form == 'alias' or form == 'mixed' and index % 2 else ref for index, ref in enumerate(refs)]
        result.append({'question_id': qid, 'claims': claims,
            **{k: value[k] for k in ('coverage', 'reason', 'gap')},
            **({'verdict': value['verdict']} if judge else {})})
    return {'answers': result}


def payload(text, provider):
    if provider == 'anthropic':
        return {'model': 'claude-sonnet-5', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}
    return {'model': 'gpt-5.6-luna', 'status': 'completed', 'output': [
        {'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}


class AnswerRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = fixture.real_data()
        blocked = patch('socket.socket.connect', side_effect=AssertionError('offline_transport_only'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def test_both_reference_forms_and_distinct_mixed_refs_are_same_complete_result(self):
        for judge in (False, True):
            expected = pairs.resolve(fixture.answer(self.data, judge), self.data, judge=judge)
            for form in ('canonical', 'alias', 'mixed'):
                original = answer(self.data, judge=judge, form=form)
                before = copy.deepcopy(original)
                actual = rows.resolve(original, self.data, judge=judge)
                self.assertEqual(actual, expected); self.assertEqual(original, before)
                self.assertEqual(rows.validate_cached(json.loads(encoded(actual)), self.data, judge=judge), expected)

    def test_duplicate_detection_happens_after_canonicalization(self):
        canonical = answer(self.data); reference = canonical['answers'][0]['claims'][0]
        for refs in ([reference, reference], ['p01c01', 'p01c01'], ['p01c01', reference], [reference, 'p01c01']):
            value = copy.deepcopy(canonical); value['answers'][0]['claims'] = refs
            with self.assertRaisesRegex(ValueError, 'duplicate_support_claim_after_canonicalization'):
                rows.resolve(value, self.data)

    def test_persisted_json_object_order_preserves_exact_provider_body(self):
        for judge in (False, True):
            self.assertEqual(rows.body(self.data, judge=judge),
                rows.body(json.loads(encoded(self.data)), judge=judge))

    def test_dynamic_supported_population_and_contribution_counts(self):
        for people_count in (1, 12):
            for roles_count in (1, 2, 6):
                data = copy.deepcopy(self.data); data['people'] = data['people'][:people_count]
                roles = data['interpretation']['roles']
                data['interpretation']['roles'] = [dict(roles[min(i, 1)], id='role-'+str(i+1)) for i in range(roles_count)]
                for judge in (False, True):
                    value = answer(data, judge=judge, form='mixed')
                    result = rows.resolve(value, data, judge=judge)
                    self.assertEqual(sum(len(p['decisions']) for p in result['people']), people_count*roles_count)
                    self.assertEqual(rows.contract(data, judge=judge)['maximum_pairs'], people_count*roles_count)
                    value['answers'].reverse()
                    self.assertEqual(rows.resolve(value, data, judge=judge), result)
        for field in ('people', 'roles'):
            data = copy.deepcopy(self.data)
            if field == 'people': data['people'] = []
            else: data['interpretation']['roles'] = []
            with self.assertRaises(ValueError): rows.schema(data)
        for field in ('people', 'roles'):
            data = copy.deepcopy(self.data)
            if field == 'people': data['people'].append(dict(data['people'][0], person_id='thirteenth-person'))
            else:
                data['interpretation']['roles'] = [dict(data['interpretation']['roles'][0], id='role-'+str(i+1)) for i in range(7)]
            with self.assertRaises(ValueError): rows.schema(data)

    def test_reference_length_bound_comes_from_exact_supplied_ids(self):
        data = copy.deepcopy(self.data)
        data['people'][0]['claims'][0]['claim_id'] += '-longer-owned-reference'
        value = answer(data, form='mixed')
        self.assertGreater(len(value['answers'][0]['claims'][0]), 20)
        self.assertEqual(rows.resolve(value, data), pairs.resolve(fixture.answer(data), data))

    def test_foreign_unknown_stale_retired_and_source_reference_tampering_rejected(self):
        valid = answer(self.data); first = valid['answers'][0]['claims'][0]
        for ref in ('p02c01', valid['answers'][2]['claims'][0], 'p01c99', first.rsplit('@', 1)[0]+'@9'):
            value = copy.deepcopy(valid); value['answers'][0]['claims'] = [ref]
            with self.assertRaises(ValueError): rows.resolve(value, self.data)
        retired = copy.deepcopy(self.data); retired['people'][0]['claims'].pop(0)
        with self.assertRaises(ValueError): rows.resolve(valid, retired)
        value = copy.deepcopy(valid); value['answers'][0]['source_ref'] = 'sibling'
        with self.assertRaises(ValueError): rows.resolve(value, self.data)
        data = copy.deepcopy(self.data); data['interpretation']['roles'][0]['source_ref'] = 'sibling'
        with self.assertRaises(ValueError): rows.resolve(valid, data)

    def test_complete_schema_fields_and_original_support_bounds(self):
        changes = [lambda v: v['answers'].pop(),
            lambda v: v['answers'].append(v['answers'][0]),
            lambda v: v['answers'].__setitem__(1, copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'][0].update(question_id='q73'),
            lambda v: v['answers'][0].pop('gap'),
            lambda v: v['answers'][0].update(person_id='foreign'),
            lambda v: v['answers'][0].update(claims=[]),
            lambda v: v['answers'][0].update(claims=['p01c01']*4),
            lambda v: v['answers'][0].update(reason='short'),
            lambda v: v['answers'][0].update(reason='x'*701),
            lambda v: v['answers'][0].update(gap='x'*301),
            lambda v: v['answers'][0].update(coverage='invented'),
            lambda v: v.update(extra=True)]
        for mutate in changes:
            value = answer(self.data); mutate(value)
            with self.assertRaises(ValueError): rows.resolve(value, self.data)
        with self.assertRaises(ValueError): rows.resolve(answer(self.data, judge=True), self.data)
        with self.assertRaises(ValueError): rows.resolve(answer(self.data), self.data, judge=True)

    def test_new_contract_and_bodies_preserve_original_science_routes_and_evidence(self):
        for judge in (False, True):
            canonical, old = pairs.body(self.data, judge=judge)
            c, new = rows.body(self.data, judge=judge)
            self.assertNotEqual(identity(old), identity(new))
            self.assertEqual(c['canonical_contract_sha256'], identity(canonical))
            self.assertTrue(c['version'].startswith(rows.VERSION)); self.assertFalse(c['serving_approved'])
            old_text = old['messages'][0]['content'] if judge else old['input']
            new_text = new['messages'][0]['content'] if judge else new['input']
            before = json.loads(old_text); after = json.loads(new_text)
            self.assertEqual({k: after[k] for k in before}, before)
            self.assertEqual(set(after)-set(before), {'wire_questions', 'wire_claims'})
            native = new['output_config']['format']['schema'] if judge else new['text']['format']['schema']
            validate_schema(answer(self.data, judge=judge), native)
            if judge:
                self.assertEqual((new['model'], new['thinking'], new['max_tokens']),
                    ('claude-sonnet-5', {'type': 'disabled'}, 12000))
                self.assertTrue(new['system'].startswith(old['system']))
            else:
                self.assertEqual((new['model'], new['reasoning'], new['max_output_tokens'], new['store']),
                    ('gpt-5.6-luna', {'effort': 'low'}, 24000, False))
                self.assertTrue(new['instructions'].startswith(old['instructions']))
                self.assertTrue(new['text']['format']['strict'])

    def test_both_providers_completion_refusal_duplicate_json_and_raw_bounds(self):
        for provider, judge in (('openai', False), ('anthropic', True)):
            value = answer(self.data, judge=judge); text = json.dumps(value)
            valid = payload(text, provider)
            self.assertEqual(rows.parse(valid, provider, self.data, judge=judge), rows.resolve(value, self.data, judge=judge))
            incomplete = valid | ({'status': 'incomplete'} if provider == 'openai' else {'stop_reason': 'max_tokens'})
            with self.assertRaises(Incomplete): rows.parse(incomplete, provider, self.data, judge=judge)
            refusal = valid | ({'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'refused'}]}]}
                if provider == 'openai' else {'stop_reason': 'refusal'})
            with self.assertRaises(Refusal): rows.parse(refusal, provider, self.data, judge=judge)
            nested = text.replace('"question_id": "q01"', '"question_id":"q01","question_id":"q01"')
            duplicate = '{"answers":[],"answers":'+json.dumps(value['answers'])+'}'
            for raw in (nested, duplicate, '{', 'NaN', '```json\n'+text+'\n```', text+' prose'):
                with self.assertRaises(ValueError): rows.parse(payload(raw, provider), provider, self.data, judge=judge)
            with self.assertRaisesRegex(ValueError, 'response_bytes'):
                rows.parse(payload('x'*(pairs.MAX_FINAL_BYTES+1), provider), provider, self.data, judge=judge)
            for invalid in (None, [], valid | ({'output': [None]} if provider == 'openai' else {'content': [None]})):
                with self.assertRaises(ValueError): rows.parse(invalid, provider, self.data, judge=judge)

    def test_exact_cache_validation_rejects_stale_revision_source_and_outcome(self):
        value = rows.resolve(answer(self.data), self.data)
        for mutate in (lambda v: v['people'].pop(),
                       lambda v: v['people'][0]['decisions'][0]['claims'][0].update(revision=9),
                       lambda v: v['people'][0]['decisions'][0]['source'].update(source_ref='sibling'),
                       lambda v: v['people'][0].update(outcome='invented')):
            changed = copy.deepcopy(value); mutate(changed)
            with self.assertRaises(ValueError): rows.validate_cached(changed, self.data)

    def test_concurrent_normalization_has_no_shared_mutation(self):
        before = copy.deepcopy(self.data)
        expected = rows.resolve(answer(self.data, judge=True), self.data, judge=True)
        def parse(index):
            return rows.resolve(answer(self.data, judge=True, form=('canonical', 'alias', 'mixed')[index % 3]), self.data, judge=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(v == expected for v in pool.map(parse, range(12))))
        self.assertEqual(self.data, before)

    def test_negative_and_uncertain_results_remain_complete_without_invented_support(self):
        value = answer(self.data, judge=True)
        for row in value['answers']: row.update(coverage='insufficient_information', claims=[], verdict='insufficient-information')
        result = rows.resolve(value, self.data, judge=True)
        self.assertTrue(all(p['outcome'] == 'insufficient_information' for p in result['people']))
        value['answers'][0].update(coverage='adjacent', verdict='plausible')
        self.assertEqual(rows.resolve(value, self.data, judge=True)['people'][0]['outcome'], 'adjacent')

    def test_historical_frozen_transports_and_recovery_identities_unchanged(self):
        self.assertEqual(identity(self.data), saved.plan()['input_sha256'])
        lock = json.loads(Path('config/contextual_team/completion-check-v1.json').read_bytes())
        for op in lock['operations'].values():
            c, b = historical.body(self.data, transport=op['transport'])
            self.assertEqual(identity(c), op['contract_sha256']); self.assertEqual(identity(b), op['body_sha256'])
        prior = json.loads(Path('config/contextual_team/retained-check-recovery-v1.json').read_bytes())
        self.assertEqual(identity(recovery.contract(self.data)), prior['validation_contract_sha256'])


if __name__ == '__main__': unittest.main()
