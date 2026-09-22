"""Pure contracts and actual composer VM; all new scientific answers are synthetic."""
import copy
import gzip
import json
from pathlib import Path
import subprocess
import shutil
import unittest
from unittest.mock import patch

import test_contextual_team_luna_repair as fixture
from test_contextual_team_answer_rows import payload
from test_contextual_team_iteration2_contract import selected, assessment, verified_wire
from tools import contextual_team_iteration2_contract as old
from tools import contextual_team_iteration3_integrity as c
from tools.offline_spend import encoded, identity, Incomplete, Refusal

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'workers/researcher-intake/iteration2-source/assets/contextual-team-engine.js'


def setup(coverage='direct', role_count=2, disjoint=False):
    data = selected(fixture.real_data(), role_count=role_count)
    a = assessment(data, coverage)
    raw = verified_wire(data, a)
    if disjoint:
        for index, answer in enumerate(raw['answers']):
            if index // role_count != index % role_count:
                answer.update(coverage='adjacent', central=False)
    v = old.verifier_resolve(raw, data, a)
    configuration = {key: identity(key) for key in ('snapshot_id', 'registry_generation', 'roster_id')}
    scope = copy.deepcopy(data['scope']) | {'source_id': identity({'scope': data['scope']})}
    retrieval = {'eligible': 155, 'shortlist': [p['person_id'] for p in data['people']],
        'per_contribution': [], 'unassessed': 143, 'maximum_shortlist': 12}
    graph = old.adapter(data, a, v, configuration, scope, retrieval, [])
    return data, graph, [p['person_id'] for p in data['people']]


def wire(data, graph, eligible, status='supported'):
    evidence = c.inputs(data, graph, eligible)
    return {'groups': [{'candidate_id': g['candidate_id'], 'status': status,
        'source_refs': sorted({r['source_ref'] for r in graph['roles']}),
        'common_operation': 'Synthetic coordinated modeling within the source-selected approach.',
        'coordination': 'Synthetic methods contribute distinct parts of the same modeled operation.',
        'limitations': 'Synthetic qualification: the exact proposed operation remains unperformed.',
        'members': [{'person_id': pid,
            'support_ids': [s['support_id'] for s in evidence['supports'] if s['person_id'] == pid],
            'contribution': 'Synthetic credible transfer of the documented modeling activity.',
            'limits': 'Synthetic specific project implementation remains unconfirmed.'} for pid in g['member_ids']]}
        for g in evidence['candidates']],
        'explanations': [{'presentation_id': p['presentation_id'],
            'potential_project_relevance': 'Synthetic inference: the documented method may inform this project.',
            'unconfirmed_operation_or_limit': 'Synthetic limitation: the proposed application has not been demonstrated.'}
            for p in evidence['presentations']]}


def directory(data, graph):
    return {'registry_generation': graph['registry_generation'], 'researchers': [
        {'id': p['person_id'], 'name': p['person_id'], 'status': 'active', 'auto_proposable': True,
         'pool_state': 'main', 'pool_visibility': 'visible', 'source_url': 'https://example.org/profile',
         'claims': [copy.deepcopy(claim) | {'status': 'active'} for claim in p['claims']]}
        for p in data['people']]}


NODE = r'''
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8')),ctx=vm.createContext({URL,Date});
vm.runInContext(input.source,ctx,{timeout:5000});
const api=ctx.ContextualTeamEngine,g=input.graph,d=input.directory,record={};
const e=api.create(g,d,{...g,scope_id:g.scope.id,parent_id:g.scope.parent_id,
  directory_content:api.canonical(d.researchers)},{record,parentRecord:record,currentness:()=>true});
const state=e.proposal(),options=e.proposalOptions(state),view=e.proposalView(state);
let manual=null,excluded=null;
if(state.selectedIds.length){
  const extra=d.researchers.find(p=>!state.selectedIds.includes(p.id));
  if(extra)manual=e.proposalView(e.addReplacement(state,extra.id));
  const removed=e.removeMember(state,state.selectedIds[0]);excluded=e.proposalOptions(removed);
}
console.log(JSON.stringify({state,options,view,manual,excluded,statistics:e.statistics(),
  candidates:api.candidateGroups?api.candidateGroups(g,d.researchers.filter(api.eligible).map(p=>p.id)):null}));
'''


def browser(data, graph, source=None):
    result = subprocess.run([shutil.which('node'), '-e', NODE], input=json.dumps({'source': source or ENGINE.read_text(encoding='utf8'),
        'graph': graph, 'directory': directory(data, graph)}), text=True, encoding='utf8', capture_output=True, timeout=30, cwd=ROOT)
    if result.returncode:
        raise ValueError(result.stderr)
    return json.loads(result.stdout)


class Integrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.graph, cls.eligible = setup()
        blocked = patch('socket.socket.connect', side_effect=AssertionError('zero_provider'))
        blocked.start(); cls.addClassCleanup(blocked.stop)

    def test_complete_evidence_preselected_approach_fixed_bounded_candidates_and_blinding(self):
        evidence = c.inputs(self.data, self.graph, self.eligible)
        self.assertEqual(evidence['source'], self.data['scope'])
        self.assertEqual(evidence['original_people'], self.data['people'])
        self.assertEqual(evidence['interpretation']['approach'], self.data['interpretation']['approach'])
        self.assertEqual(len(evidence['candidates']), 8)
        self.assertEqual(evidence['candidates'][0]['member_ids'], sorted(self.eligible)[:2])
        self.assertTrue(all(2 <= len(g['member_ids']) <= 4 for g in evidence['candidates']))
        text = json.dumps(evidence)
        for forbidden in ('Fixture assessor rationale', 'Independent fixture verification', '"coverage"', '"outcome"'):
            self.assertNotIn(forbidden, text)
        contract, body = c.body(self.data, self.graph, self.eligible)
        self.assertEqual((body['model'], body['max_tokens'], body['thinking']), ('claude-sonnet-5', 12000, {'type': 'disabled'}))
        self.assertFalse(contract['independent_evaluation']); self.assertFalse(contract['public_activation'])
        self.assertEqual(contract['candidate_list_sha256'], identity(evidence['candidates']))

    def test_method_transfer_is_eligible_and_does_not_need_every_member_direct(self):
        data, graph, eligible = setup('method_transfer')
        result = c.resolve(wire(data, graph, eligible), data, graph, eligible)
        value = c.adapter(data, graph, result, eligible)
        self.assertEqual(len(result['groups']), 8)
        self.assertEqual(value['edges'], graph['edges'])
        self.assertTrue(all(e['coverage'] == 'method_transfer' for e in value['edges']))

    def test_complementary_three_member_group_and_complete_six_role_bound(self):
        data, graph, eligible = setup('method_transfer', role_count=3, disjoint=True)
        self.assertEqual(c.candidate_groups(graph, eligible), [eligible[:3]])
        result = c.resolve(wire(data, graph, eligible), data, graph, eligible)
        composed = browser(data, c.adapter(data, graph, result, eligible))
        self.assertEqual(composed['state']['selectedIds'], eligible[:3])
        self.assertEqual(composed['view']['opportunity']['gate_state'], 'conditional')
        self.assertEqual(composed['manual']['opportunity']['gate_state'], 'fail')
        data, graph, eligible = setup(role_count=6)
        self.assertEqual(len(graph['edges']), 72)
        value = c.resolve(wire(data, graph, eligible), data, graph, eligible)
        self.assertEqual(len(value['supports']), 72)
        self.assertEqual(len(c.adapter(data, graph, value, eligible)['pair_decisions']), 12)

    def test_all_negative_groups_are_results_and_original_pair_layer_is_unchanged(self):
        before = encoded(self.graph)
        result = c.resolve(wire(self.data, self.graph, self.eligible, 'unsupported'), self.data, self.graph, self.eligible)
        graph = c.adapter(self.data, self.graph, result, self.eligible)
        self.assertEqual(graph['state'], 'no_supported_group_in_checked_candidates')
        self.assertEqual(len(graph['integrity']['groups']), 8)
        for field in ('pair_decisions', 'edges', 'people', 'roles', 'source_id', 'approach', 'requests'):
            self.assertEqual(graph[field], self.graph[field])
        self.assertEqual(graph['base_graph_id'], self.graph['graph_id'])
        self.assertEqual(graph['base_graph_sha256'], identity(self.graph))
        self.assertEqual(encoded(self.graph), before)
        self.assertEqual(c.validate_cached(result, self.data, self.graph, self.eligible), result)

    def test_no_candidate_abstention_has_no_request_and_no_directory_infeasibility(self):
        data, graph, eligible = setup('adjacent')
        with self.assertRaisesRegex(ValueError, 'no_provider_request'): c.body(data, graph, eligible)
        result = c.empty_result(data, graph, eligible)
        self.assertEqual(result['groups'], [])
        self.assertEqual(result['disposition'], 'not_applicable_no_candidates')
        value = c.adapter(data, graph, result, eligible)
        self.assertEqual(value['state'], 'no_supported_group_in_assessed_set')
        self.assertEqual(browser(data, value)['options'], [])
        with self.assertRaisesRegex(ValueError, 'requires_no_candidates'):
            c.empty_result(self.data, self.graph, self.eligible)

    def test_strict_group_completeness_ownership_sources_and_no_manual_replacement(self):
        valid = wire(self.data, self.graph, self.eligible)
        evidence = c.inputs(self.data, self.graph, self.eligible)
        foreign = next(s['support_id'] for s in evidence['supports'] if s['person_id'] != valid['groups'][0]['members'][0]['person_id'])
        mutations = [lambda v: v['groups'].pop(), lambda v: v['explanations'].pop(),
            lambda v: v['groups'].__setitem__(1, copy.deepcopy(v['groups'][0])),
            lambda v: v['groups'][0]['members'][0].update(support_ids=[foreign]),
            lambda v: v['groups'][0]['members'][0].update(support_ids=[]),
            lambda v: v['groups'][0]['members'][0].update(person_id=self.eligible[-1]),
            lambda v: v['groups'][0].update(source_refs=[]),
            lambda v: v['groups'][0].update(source_refs=['invented']),
            lambda v: v['groups'][0].update(common_operation='   '),
            lambda v: v['groups'][0].update(coverage='direct'),
            lambda v: v['explanations'][0].update(documented_claims=[]),
            lambda v: v['explanations'][0].update(potential_project_relevance='x'*351)]
        for mutate in mutations:
            changed = copy.deepcopy(valid); mutate(changed)
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError):
                c.resolve(changed, self.data, self.graph, self.eligible)

    def test_retired_changed_or_foreign_claims_and_changed_sources_reject_before_request(self):
        for change in (lambda d: d['people'][0]['claims'].pop(0),
                       lambda d: d['people'][0]['claims'][0].update(revision=99),
                       lambda d: d['people'][0]['claims'][0].update(evidence='Altered retained evidence'),
                       lambda d: d['scope'].update(title='Different source title')):
            data = copy.deepcopy(self.data); change(data)
            with self.assertRaises(ValueError): c.body(data, self.graph, self.eligible)
        graph = copy.deepcopy(self.graph); graph['edges'][0]['coverage'] = 'method_transfer'
        with self.assertRaisesRegex(ValueError, 'base_graph_hash'): c.body(self.data, graph, self.eligible)

    def test_response_envelope_duplicate_json_bounds_and_immutable_cache(self):
        raw = json.dumps(wire(self.data, self.graph, self.eligible))
        response = payload(raw, 'anthropic')
        result = c.parse(response, self.data, self.graph, self.eligible)
        self.assertEqual(c.validate_cached(json.loads(encoded(result)), self.data, self.graph, self.eligible), result)
        for stop, exception in (('max_tokens', Incomplete), ('refusal', Refusal)):
            with self.assertRaises(exception): c.parse(response | {'stop_reason': stop}, self.data, self.graph, self.eligible)
        duplicate = raw.replace('"status": "supported"', '"status":"supported","status":"supported"', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'): c.parse(payload(duplicate, 'anthropic'), self.data, self.graph, self.eligible)
        with self.assertRaisesRegex(ValueError, 'response_bytes'): c.parse(payload('x'*(c.MAX_FINAL_BYTES+1), 'anthropic'), self.data, self.graph, self.eligible)
        for mutate in (lambda v: v.update(base_graph_id='0'*64),
                       lambda v: v['explanations'][0]['documented_claims'][0].update(evidence='Invented performed operation'),
                       lambda v: v['groups'][0].update(status='unsupported')):
            changed = copy.deepcopy(result); mutate(changed)
            if changed['groups'][0]['status'] == 'unsupported':
                # A coherent revalidated negative is allowed, but its derived v4 identity must change.
                self.assertNotEqual(identity(c.adapter(self.data, self.graph, changed, self.eligible)), identity(c.adapter(self.data, self.graph, result, self.eligible)))
            else:
                with self.assertRaises(ValueError): c.validate_cached(changed, self.data, self.graph, self.eligible)

    def test_roundtrip_and_permutation_are_lossless_and_do_not_change_body_identity(self):
        data, graph = json.loads(encoded(self.data)), json.loads(encoded(self.graph))
        self.assertEqual(c.body(self.data, self.graph, self.eligible), c.body(data, graph, self.eligible[::-1]))
        original = wire(data, graph, self.eligible); permuted = copy.deepcopy(original)
        permuted['groups'].reverse(); permuted['explanations'].reverse()
        for group in permuted['groups']: group['members'].reverse()
        self.assertEqual(c.resolve(original, data, graph, self.eligible), c.resolve(permuted, data, graph, self.eligible))

    def test_actual_v4_composer_accepts_only_exact_positive_groups_and_separates_evidence(self):
        raw = wire(self.data, self.graph, self.eligible)
        for g in raw['groups'][1:]: g['status'] = 'unsupported'
        value = c.resolve(raw, self.data, self.graph, self.eligible)
        graph = c.adapter(self.data, self.graph, value, self.eligible)
        result = browser(self.data, graph)
        self.assertEqual(result['candidates'], c.candidate_groups(self.graph, self.eligible))
        self.assertEqual(len(result['options']), 1)
        self.assertEqual(result['view']['opportunity']['gate_state'], 'conditional')
        self.assertEqual(result['manual']['opportunity']['gate_state'], 'fail')
        self.assertEqual(result['excluded'], [])
        for person in result['view']['selected']:
            explanation = person['evidence']['why_person']
            self.assertIn('Retained profile activity (audited evidence):', explanation)
            self.assertIn('Potential project relevance (inferred):', explanation)
            self.assertIn('Unconfirmed operation or limit:', explanation)
            self.assertNotIn('Independent fixture verification', explanation)
        altered = copy.deepcopy(graph); altered['integrity']['explanations'][0]['documented_claims'][0]['revision'] = 99
        with self.assertRaisesRegex(ValueError, 'integrity_exact_explanation'): browser(self.data, altered)
        altered = copy.deepcopy(graph); altered['integrity']['candidate_groups'][0]['member_ids'][-1] = self.eligible[-1]
        with self.assertRaisesRegex(ValueError, 'integrity_candidate_equality'): browser(self.data, altered)

    def test_historical_v3_actual_composer_outputs_unchanged(self):
        config = json.loads((ROOT / 'workers/researcher-intake/config/contextual-iteration2-preview-v1.json').read_text())
        source = gzip.decompress(__import__('base64').b64decode(config['files']['assets/contextual-team-engine.js']['gzip_base64'])).decode()
        previous = browser(self.data, self.graph, source)
        current = browser(self.data, self.graph)
        current['candidates'] = previous['candidates']
        self.assertEqual(current, previous)


if __name__ == '__main__': unittest.main()
