"""Prospective, pure production-verifier transport with coupled support states.

No executor selects this transport. A future paid correction needs a distinct
purpose and complete authority; this module grants neither recovery nor replay.
Canonical scientific values and historical validators remain unchanged.
"""
from copy import deepcopy
import json

from tools import contextual_team_iteration2_contract as original
from tools import contextual_team_iteration3_references as references
from tools import contextual_team_pair_contract as pairs
from tools.contextual_team_contract import enum
from tools.contextual_team_diagnostics import final_text
from tools.offline_ai import anthropic_schema, response_value, validate_schema
from tools.offline_spend import encoded, identity

VERSION = 'contextual-production-verifier-states-v2'
SUPPORT_STATES = {
    'direct_central': ('direct', True),
    'direct_noncentral': ('direct', False),
    'method_transfer_central': ('method_transfer', True),
    'method_transfer_noncentral': ('method_transfer', False),
    'adjacent': ('adjacent', False),
    'insufficient_information': ('insufficient_information', False),
}
FORMAT = original.VERIFIER_FORMAT.replace(
    'Each row contains question_id, coverage, claims, central, reason,\nand gap.',
    'Each row contains question_id, support_state, claims, reason and gap.') + '''
COUPLED SUPPORT-STATE SERIALIZATION V2: coverage and central above describe
scientific decisions; do not return them as separate fields. Return exactly one
support_state: direct_central means direct/true; direct_noncentral direct/false;
method_transfer_central method_transfer/true; method_transfer_noncentral
method_transfer/false; adjacent adjacent/false; insufficient_information
insufficient_information/false. Only direct or method_transfer may be central.
Choose only from the exact question's allowed_support_states. The shared schema
enum does not permit upgrades or change any claim/source ownership constraint.
For noncoherent sources every row must use insufficient_information and empty
claims. Retain every supplied question; this encoding supplies no missing answer.
'''


def verifier_body(data, assessment):
    old, old_body = references.verifier_body(data, assessment)
    contract, body = deepcopy(old), deepcopy(old_body)
    evidence = json.loads(body['messages'][0]['content'])
    proposed = {(p['person_id'], p['role_id']): p for p in evidence['proposed_pairs']}
    for question in evidence['wire_questions'].values():
        before = proposed[(question['person_id'], question['role_id'])]
        question['allowed_support_states'] = [state for state, (coverage, central) in SUPPORT_STATES.items()
            if pairs.STRENGTH[coverage] <= pairs.STRENGTH[before['coverage']]
            and (not central or before['central'])]
    schema = contract['schema']['properties']['answers']['items']
    for key in ('coverage', 'central'):
        del schema['properties'][key]
        schema['required'].remove(key)
    schema['properties']['support_state'] = enum(*SUPPORT_STATES)
    schema['required'].append('support_state')
    if old['prompt'].count(original.VERIFIER_FORMAT) != 1:
        raise ValueError('verifier_states_original_format_not_unique')
    contract.update(version=VERSION, preceding_transport_contract_sha256=identity(old),
        support_state_mapping_sha256=identity(SUPPORT_STATES), wire_input_sha256=identity(evidence),
        prompt=old['prompt'].replace(original.VERIFIER_FORMAT, FORMAT))
    body['messages'][0]['content'] = json.dumps(json.loads(encoded(evidence)), ensure_ascii=False)
    body['system'] = contract['prompt']
    body['output_config']['format']['schema'] = anthropic_schema(contract['schema'])
    return contract, body


def verifier_resolve(value, data, assessment):
    contract, body = verifier_body(data, assessment)
    if len(encoded(value)) > pairs.MAX_FINAL_BYTES:
        raise ValueError('verifier_states_response_bytes')
    validate_schema(value, contract['schema'])
    questions = json.loads(body['messages'][0]['content'])['wire_questions']
    ordinary = {'state': value['state'], 'answers': []}
    for row in value['answers']:
        if row['support_state'] not in questions[row['question_id']]['allowed_support_states']:
            raise ValueError('verifier_states_upgrade')
        references._reason(row['reason'])
        coverage, central = SUPPORT_STATES[row['support_state']]
        ordinary['answers'].append({key: deepcopy(item) for key, item in row.items()
            if key != 'support_state'} | {'coverage': coverage, 'central': central})
    # This remains the sole scientific decision validator: full completeness,
    # exact source/claim ownership, downgrade-only support and source abstention.
    return original.verifier_resolve(ordinary, data, assessment)


def verifier_parse(payload, data, assessment):
    if not isinstance(payload, dict):
        raise ValueError('invalid_response_envelope')
    try:
        text = final_text('anthropic', payload)
    except (TypeError, AttributeError) as error:
        raise ValueError('invalid_response_content') from error
    if len(text.encode('utf8')) > pairs.MAX_FINAL_BYTES:
        raise ValueError('verifier_states_response_bytes')
    try:
        response_value('anthropic', payload)
    except (TypeError, AttributeError) as error:
        raise ValueError('invalid_response_content') from error

    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate_response_key')
            value[key] = item
        return value

    def non_json_constant(value):
        raise ValueError('non_json_response_constant')

    return verifier_resolve(json.loads(text, object_pairs_hook=unique,
        parse_constant=non_json_constant), data, assessment)


def verifier_validate_cached(value, data, assessment):
    # As in the preceding transport, request-envelope version/body/input pins
    # own cache identity. A canonical value alone never proves new execution.
    checked = references.verifier_validate_cached(value, data, assessment)
    _, body = verifier_body(data, assessment)
    questions = json.loads(body['messages'][0]['content'])['wire_questions']
    addresses = {(q['person_id'], q['role_id']): qid for qid, q in questions.items()}
    inverse = {decision: state for state, decision in SUPPORT_STATES.items()}
    wire = {'state': checked['state'], 'answers': []}
    for person in checked['people']:
        for decision in person['decisions']:
            wire['answers'].append({
                'question_id': addresses[(person['person_id'], decision['role_id'])],
                'support_state': inverse[(decision['coverage'], decision['central'])],
                'claims': [decision['claim_refs'][slot] for slot in ('primary', 'second', 'third')
                    if decision['claim_refs'][slot] != pairs.NONE],
                'reason': decision['reason'], 'gap': decision['gap']})
    if verifier_resolve(wire, data, assessment) != value:
        raise ValueError('verifier_states_cache_not_lossless')
    return checked
