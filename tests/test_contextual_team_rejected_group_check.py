"""Pure fixed-group evidence/response boundaries; all judgments are synthetic."""
import copy
import json
import unittest
from unittest.mock import patch

from test_contextual_team_answer_rows import payload
from test_contextual_team_iteration3_integrity import setup, wire
from tools import contextual_team_iteration3_integrity as integrity
from tools import contextual_team_rejected_group_check as c
from tools.offline_spend import encoded, identity, Incomplete, Refusal, ConfigurationFailure


def fixture(accepted=2):
    data, base, eligible = setup()
    value = wire(data, base, eligible, status='unsupported')
    for group in value['groups'][:accepted]:
        group['status'] = 'supported'
    graph = integrity.adapter(data, base, integrity.resolve(value, data, base, eligible), eligible)
    scope = copy.deepcopy(data['scope']) | {'source_id': base['source_id']}
    actual = {'configuration': {'people': data['people'], 'snapshot_id': base['snapshot_id']},
        'scope': scope, 'data': data, 'graph': graph,
        'assessment': {'private': 'ASSessor grade must stay blinded'},
        'verified': {'private': 'VERifier rationale must stay blinded'}}
    lock = {'generation_run': 123, 'source_id': scope['source_id'],
        'data_sha256': identity(data), 'profiles_sha256': identity(data['people']),
        'graph_sha256': identity(graph), 'integrity_sha256': identity(graph['integrity']),
        'assessment_sha256': identity(actual['assessment']), 'verified_sha256': identity(actual['verified']),
        'rejected_candidate_ids': [g['candidate_id'] for g in value['groups'][accepted:]]}
    return actual, lock


def answers(body):
    return {'answers': [{'item_id': q['item_id'], 'verdict': 'insufficient-information',
        'evidence_ref': 'scope.science', 'reason': 'Synthetic evidence does not establish the proposed joint operation.'}
        for q in json.loads(body['messages'][0]['content'])['items']]}


class FixedCandidateCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual, cls.lock = fixture()
        cls.scope_id = cls.actual['scope']['id']
        block = patch('socket.socket.connect', side_effect=AssertionError('no_network'))
        block.start(); cls.addClassCleanup(block.stop)

    def packet(self, actual=None, lock=None):
        with patch.object(c, 'LOCKS', {self.scope_id: lock or self.lock}), \
             patch.object(c.workflow, 'actual_result', return_value=actual or self.actual):
            return c.packet('unused-local-state', self.scope_id)

    def test_complete_original_source_profiles_and_six_or_eight_groups_without_positive_replay(self):
        for accepted in (0, 2):
            actual, lock = fixture(accepted)
            before = encoded(actual)
            _, scope, contract, body, _, report = self.packet(actual, lock)
            evidence = json.loads(body['messages'][0]['content'])
            self.assertEqual(evidence['scope'], actual['data']['scope'])
            self.assertEqual(evidence['profile_documents'], actual['data']['people'])
            self.assertEqual(len(evidence['profile_documents']), 12)
            self.assertEqual(evidence['source_selected_approach'], actual['graph']['approach'])
            self.assertEqual([q['item_id'] for q in evidence['items']], lock['rejected_candidate_ids'])
            self.assertEqual(len(evidence['items']), 8-accepted)
            self.assertTrue(all(q['task_type'] == 'group_usefulness' for q in evidence['items']))
            self.assertEqual(report['already_accepted_groups_not_reasked'], accepted)
            self.assertEqual(report['full_directory_feasibility']['denominator'], None)
            self.assertEqual(report['individual_exclusion_questions'], 0)
            self.assertEqual((body['model'], body['max_tokens'], body['thinking']),
                ('claude-sonnet-5', 12000, {'type': 'disabled'}))
            self.assertEqual(contract['version'], c.VERSION)
            self.assertEqual(encoded(actual), before)

    def test_assessment_verifier_integrity_decisions_and_explanations_are_not_provider_evidence(self):
        _, _, _, body, _, _ = self.packet()
        evidence = json.loads(body['messages'][0]['content'])
        self.assertEqual(set(evidence), {'scope', 'profile_documents', 'source_selected_approach', 'items'})
        text = json.dumps(evidence)
        for forbidden in ('ASSessor', 'VERifier', 'Synthetic coordinated modeling',
                          'Synthetic methods contribute distinct', '"coverage"', '"outcome"'):
            self.assertNotIn(forbidden, text)

    def test_full_source_profile_graph_and_original_judgment_tampering_rejected(self):
        mutations = [lambda a: a['data']['scope'].update(title='changed'),
            lambda a: a['data']['people'][0]['claims'][0].update(evidence='changed'),
            lambda a: a['graph']['integrity']['candidate_groups'][0]['member_ids'].reverse(),
            lambda a: a['graph']['integrity']['groups'][0].update(status='unsupported'),
            lambda a: a['assessment'].update(private='changed'),
            lambda a: a['verified'].update(private='changed'),
            lambda a: a['scope'].update(source_id='0'*64)]
        for mutate in mutations:
            actual = copy.deepcopy(self.actual); mutate(actual)
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, ConfigurationFailure)): self.packet(actual)

    def test_configuration_profile_replacement_rejected_and_unknown_scope_has_no_reconstruction(self):
        actual = copy.deepcopy(self.actual)
        actual['configuration']['people'] = copy.deepcopy(actual['configuration']['people'])
        actual['configuration']['people'][0]['summary'] += ' Changed.'
        with self.assertRaises((ValueError, ConfigurationFailure)): self.packet(actual)
        with patch.object(c.workflow, 'actual_result') as read:
            for bad in (None, {}, '341997', '363268'):
                with self.assertRaises((ValueError, ConfigurationFailure)): c.packet('unused', bad)
            read.assert_not_called()

    def test_complete_canonical_negative_results_and_distinct_cache_version(self):
        _, _, contract, body, check, _ = self.packet()
        wire = answers(body); wire['answers'].reverse()
        result = check(payload(json.dumps(wire), 'anthropic'), False)
        self.assertEqual([r['item_id'] for r in result['verdicts']], self.lock['rejected_candidate_ids'])
        self.assertEqual(result['contract_sha256'], identity(contract))
        self.assertEqual(result['version'], c.VERSION)
        self.assertEqual(check(json.loads(encoded(result)), True), result)
        for change in ({'version': c.complete.VERSION}, {'contract_sha256': '0'*64},
                       {'input_sha256': '0'*64}, {'extra': True}):
            with self.assertRaises((ValueError, ConfigurationFailure)): check(result | change, True)

    def test_missing_duplicate_extra_wrong_label_and_foreign_revision_rejected(self):
        _, _, _, body, check, _ = self.packet()
        evidence = json.loads(body['messages'][0]['content']); q = evidence['items'][0]
        foreign = next(ref for later in evidence['items'][1:] for ref in later['allowed_evidence_refs']
                       if ref not in q['allowed_evidence_refs'])
        claim = next(ref for ref in q['allowed_evidence_refs'] if '@' in ref)
        mutations = [lambda v: v['answers'].pop(),
            lambda v: v['answers'].__setitem__(1, copy.deepcopy(v['answers'][0])),
            lambda v: v['answers'][0].update(verdict='faithful'),
            lambda v: v['answers'][0].update(evidence_ref=foreign),
            lambda v: v['answers'][0].update(evidence_ref=claim.split('@')[0]),
            lambda v: v['answers'][0].update(evidence_ref=claim.split('@')[0]+'@999'),
            lambda v: v['answers'][0].update(evidence_ref='scope.science; '+claim),
            lambda v: v['answers'][0].update(extra=True)]
        for mutate in mutations:
            value = answers(body); mutate(value)
            with self.assertRaises((ValueError, ConfigurationFailure)): check(payload(json.dumps(value), 'anthropic'), False)

    def test_complete_reasons_refusal_truncation_duplicate_json_and_cache_tamper(self):
        _, _, _, body, check, _ = self.packet()
        for reason in ('placeholder for a later reason', 'short'+' '*50, 'x'*1001):
            value = answers(body); value['answers'][0]['reason'] = reason
            with self.assertRaises((ValueError, ConfigurationFailure)): check(payload(json.dumps(value), 'anthropic'), False)
        raw = json.dumps(answers(body)); response = payload(raw, 'anthropic')
        response['stop_reason'] = 'max_tokens'
        with self.assertRaises(Incomplete): check(response, False)
        response['stop_reason'] = 'refusal'
        with self.assertRaises(Refusal): check(response, False)
        duplicate = raw.replace('"answers":', '"answers": [], "answers":', 1)
        with self.assertRaises((ValueError, ConfigurationFailure)): check(payload(duplicate, 'anthropic'), False)
        with self.assertRaises((ValueError, ConfigurationFailure)): check(payload(' '*c.complete.MAX_RESPONSE_BYTES+raw, 'anthropic'), False)
        value = check(payload(raw, 'anthropic'), False)
        value['verdicts'].pop()
        with self.assertRaises((ValueError, ConfigurationFailure)): check(value, True)


if __name__ == '__main__':
    unittest.main()
