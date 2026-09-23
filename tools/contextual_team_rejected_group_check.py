"""Two fixed, blinded group evaluations; no execution or spending authority.

The fourteen candidates are selected once from authenticated original results.
Reconstruction retains those original scientific inputs and all twelve profiles;
the request does not expose production grades, rationales, or accepted judgments.
"""
from copy import deepcopy
import json

from tools import contextual_team_iteration2_check as original
from tools import contextual_team_iteration3 as workflow
from tools import contextual_team_iteration3_check as complete
from tools import contextual_team_iteration3_references as references
from tools.contextual_team_check import judge_prompt, OWNED_FORMAT
from tools.contextual_team_contract import obj, array, enum, string
from tools.contextual_team_executor import scope_inputs
from tools.offline_ai import request_body
from tools.offline_spend import ConfigurationFailure, encoded, identity

VERSION = 'contextual-iteration3-fixed-candidate-evaluation-v1'
OUTPUT_TOKENS = complete.OUTPUT_TOKENS
LOCKS = {
    '332894': {
        'generation_run': 35771270107,
        'source_id': '86b7fc643df1d82ad7d82033604cb19a23a0b29cbae07df754c0e7238030d69d',
        'data_sha256': '6d659b9705bb2e8d98d4134a9817feae80d25b1e7643689cf2ce5acdde2ad21f',
        'profiles_sha256': '0327d62f77fef70c06d6547a6354f713db5568e92899ea3fef222acee52c4b6d',
        'graph_sha256': '9eb61cbb08575c638f7fb7dff98bfe700819825045ef5575838ae0529ad741eb',
        'integrity_sha256': '4d3f9cf4067f4034e381c2e841568d267f7e782db424fc3ee6c56d81e7d7edfa',
        'assessment_sha256': 'ff5ac6c1d56ce4c715c211806736fefd0b227054470397c5a5fb7375f7f64085',
        'verified_sha256': '10ad47b2c295a73ffac0163b033332835c741ef6bbbd5fadbc29c1ef11f0079a',
        'rejected_candidate_ids': ['g01', 'g02', 'g05', 'g06', 'g07', 'g08'],
    },
    '345241:tdac-baa-004': {
        'generation_run': 35772600547,
        'source_id': 'fd85842d14807cab0c574bff6d30655b3325eb21c478ec528e0dc28de75e355c',
        'data_sha256': 'e5f8f88d666c1402bb6b50fb751c5edceeb522ed9ca22980c14bf36862773b02',
        'profiles_sha256': '876c63eb211273ab320673005959d6a1ef5e35f4ebd95ad3b1064a3d39d0b5b3',
        'graph_sha256': '5762eade5c8affeaeb568bf5b1736e8872e8b38d39aafaf7d331bbb4e92bf9d3',
        'integrity_sha256': '22b5756f85c2d7ba8ea502627baf2ea623031f59eed23cbd24b0e115b662c11d',
        'assessment_sha256': '3b1399c0d47d97f0cb1366cdadccb8ed83c82bee9e03e8070cbfab4f12c1d920',
        'verified_sha256': 'f39acd6a73b314df61ef09d2c0c41208e07d5c6175d8a9f690f4199c59fc57b6',
        'rejected_candidate_ids': ['g01', 'g02', 'g03', 'g04', 'g05', 'g06', 'g07', 'g08'],
    },
}


def _require(ok, reason):
    if not ok:
        raise ConfigurationFailure(reason)


def _validator(questions, schema, owned, labels, input_id, contract_id):
    original_check = complete.validator(questions, schema, owned, labels, input_id, contract_id)

    def check(value, cached):
        if cached:
            _require(isinstance(value, dict) and value.get('version') == VERSION,
                     'fixed_candidate_cache_version')
            translated = deepcopy(value) | {'version': complete.VERSION}
            checked = original_check(translated, True)
        else:
            checked = original_check(value, False)
        return checked | {'version': VERSION}
    return check


def _packet(actual, scope_id):
    lock = LOCKS[scope_id]
    config, scope, data, graph = (actual[k] for k in ('configuration', 'scope', 'data', 'graph'))
    _require(scope['id'] == scope_id and scope['source_id'] == lock['source_id']
             and identity(scope_inputs(scope)) == lock['source_id']
             and identity(data) == lock['data_sha256']
             and identity(data['people']) == lock['profiles_sha256']
             and identity(graph) == lock['graph_sha256']
             and identity(graph['integrity']) == lock['integrity_sha256']
             and identity(actual['assessment']) == lock['assessment_sha256']
             and identity(actual['verified']) == lock['verified_sha256'],
             'fixed_candidate_original_scientific_identity')
    people = data['people']; documents = {p['person_id']: p for p in people}
    configured = {p['person_id']: p for p in config['people']}
    _require(len(people) == len(documents) == 12
             and all(configured.get(pid) == person for pid, person in documents.items()),
             'fixed_candidate_complete_original_profiles')
    integrity = graph['integrity']
    statuses = {g['candidate_id']: g['status'] for g in integrity['groups']}
    rejected = [g for g in integrity['candidate_groups'] if statuses[g['candidate_id']] != 'supported']
    _require([g['candidate_id'] for g in rejected] == lock['rejected_candidate_ids'],
             'fixed_candidate_complete_original_selection')
    questions = []
    for group in rejected:
        members = group['member_ids']
        _require(2 <= len(members) <= 4 and len(members) == len(set(members))
                 and set(members) <= set(documents), 'fixed_candidate_original_members')
        owned = {'scope.science'} | set(members) | {
            c['claim_id']+'@'+str(c['revision']) for pid in members for c in documents[pid]['claims']}
        questions.append({'item_id': group['candidate_id'], 'task_type': 'group_usefulness',
                          'people': deepcopy(members), 'allowed_evidence_refs': sorted(owned)})
    evidence = scope_inputs(scope) | {'profile_documents': deepcopy(people),
        'source_selected_approach': deepcopy(graph['approach']), 'items': questions}
    owned = {q['item_id']: set(q['allowed_evidence_refs']) for q in questions}
    labels = {qid: original.USEFUL_LABELS for qid in owned}
    row = obj(item_id=enum(*owned), verdict=enum(*original.USEFUL_LABELS),
        evidence_ref=enum(*sorted(set().union(*owned.values()))), reason=string(1000, 15))
    answers = array(row, len(questions)) | {'minItems': len(questions)}
    schema = obj(answers=answers)
    prompt = judge_prompt(owned_references=True)
    _require(prompt.count(OWNED_FORMAT) == 1, 'fixed_candidate_original_judge_format')
    prompt = (prompt.replace(OWNED_FORMAT, original.FORMAT) + original.science.CLARIFICATION
        + references.POLICY + complete.REASON_FORMAT
        + "\nJudge every fixed group independently under the supplied source and approach. "
          "No prior group judgment or rationale is supplied. A group judgment must not be "
          "converted into an individual-person rejection or a full-directory feasibility claim. "
          "Copy evidence_ref exactly from that item's allowed_evidence_refs, including @revision.\n")
    contract = {'version': VERSION, 'schema': schema, 'prompt': prompt,
        'evidence_sha256': identity(evidence), 'owned_references_sha256': identity({k: sorted(v) for k, v in owned.items()}),
        'labels_sha256': identity(labels), 'source_id': scope['source_id'], 'snapshot_id': config['snapshot_id'],
        'graph_sha256': identity(graph), 'original_input_lock_sha256': identity(lock),
        'candidate_groups_sha256': identity(rejected), 'original_generation_run': lock['generation_run'],
        'original_assessment_sha256': lock['assessment_sha256'],
        'original_integrity_sha256': lock['integrity_sha256'],
        'maximum_response_bytes': complete.MAX_RESPONSE_BYTES, 'output_tokens': OUTPUT_TOKENS,
        'complete_validator_version': complete.VERSION, 'production_admission': False, 'new_human_labels': 0}
    body = request_body({'provider': 'anthropic', 'model': 'claude-sonnet-5'},
        {'schema_version': VERSION, 'max_output_tokens': OUTPUT_TOKENS}, prompt, evidence, schema)
    body['thinking'] = {'type': 'disabled'}
    _require(len(encoded(body)) <= complete.MAX_WIRE_BYTES, 'fixed_candidate_complete_evidence_wire_bound')
    report = {'scope_id': scope_id, 'original_generation_run': lock['generation_run'],
        'groups': deepcopy(rejected), 'group_question_denominator': len(rejected),
        'original_candidate_denominator': len(integrity['candidate_groups']),
        'already_accepted_groups_not_reasked': sum(g['status'] == 'supported' for g in integrity['groups']),
        'original_profile_count': len(people), 'original_claim_count': sum(len(p['claims']) for p in people),
        'complete_original_source_and_profiles': True, 'production_grades_or_rationales_supplied': False,
        'source_or_top_five_questions_reasked': 0, 'individual_exclusion_questions': 0,
        'full_directory_feasibility': {'status': 'unmeasured', 'denominator': None},
        'production_admission': False, 'human_labels': 0, 'same_model_family_limitation': True,
        'historical_scientific_results_changed': False, 'body_bytes': len(encoded(body))}
    return config, scope, contract, body, _validator(questions, schema, owned, labels,
        identity(evidence), identity(contract)), report


def packet(state, scope_id):
    _require(isinstance(scope_id, str) and scope_id in LOCKS, 'fixed_candidate_scope_only')
    return _packet(workflow.actual_result(state, scope_id), scope_id)
