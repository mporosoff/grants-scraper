"""Prospective exact-reference generation; historical contracts stay unchanged.

This module grants no dispatch permission. All scientific acceptance still goes
through the existing complete-pair and downgrade-only validators.
"""
from copy import deepcopy
import json

from tools import contextual_team_iteration2_contract as original
from tools import contextual_team_answer_rows as rows
from tools.contextual_team_contract import enum
from tools.contextual_team_diagnostics import final_text
from tools.offline_ai import anthropic_schema, validate_schema
from tools.offline_spend import encoded, identity

VERSION = 'contextual-iteration3-exact-references-v1'
POLICY = '''
PROSPECTIVE SCIENTIFIC POLICY: Judge the proposed activity under the exact source
conditions. A researcher's field does not establish other-agency support or make
the researcher personally ineligible. A biography need not contain the future
proposal narrative. Positive support still requires documented activity and an
explicit credible method/material/process bridge to this selected contribution.
Legitimate transfer does not require identical prior application. Social value,
lasers, shared vocabulary, or a broad field label alone do not supply a bridge.
Respect source-permitted computational contributions without adding an unstated
experimental-only rule. A team-level laboratory requirement does not mean every
collaborator personally performs every operation. Conversely, general AI or
simulation activity does not prove a particular design or validation operation.
Judge each role separately: one supported role or overall person outcome does
not cover a different central role. Conversation relevance, supported coverage,
selected membership and complete-team feasibility are distinct. An assessed-set
abstention does not establish directory-wide infeasibility. No missing operation,
facility, access, scientific result or claim may be inferred into existence.
'''
REFERENCE_FORMAT = '''
EXACT REFERENCE GENERATION V1: Each wire_question now carries a complete explicit
allowed_claim_refs list. Copy only canonical claim_id@revision strings from that
question's list. The response schema's shared enum is the union for compact
transport; it does NOT grant cross-person or cross-question ownership. Never
construct a claim ID or revision from a pattern, guess a nearby number, substitute
another person's claim, or cite a claim omitted from that question's list.
An empty allowed list requires empty claims. If evidence cannot support the role,
return the appropriate negative/insufficient answer for that same question; do
not omit it. Reference validity alone does not establish scientific support.
Provide a substantive complete evidence-based reason of at least 15 characters
for every row; never use placeholder text or an unfilled response template.
'''


def _allowed(evidence, *, verifier):
    if verifier:
        proposed = {(p['person_id'], p['role_id']): p for p in evidence['proposed_pairs']}
        return {qid: list(proposed[(q['person_id'], q['role_id'])]['claims'])
            for qid, q in evidence['wire_questions'].items()}
    return {qid: sorted({c['claim_ref'] for c in evidence['wire_claims'].values()
        if c['person_id'] == q['person_id']}) for qid, q in evidence['wire_questions'].items()}


def _body(data, assessment=None):
    verifier = assessment is not None
    old, body = (original.verifier_body(data, assessment) if verifier else original.assessment_body(data))
    contract = deepcopy(old); body = deepcopy(body)
    evidence = json.loads(body['messages'][0]['content'] if verifier else body['input'])
    allowed = _allowed(evidence, verifier=verifier)
    for qid, question in evidence['wire_questions'].items():
        question['allowed_claim_refs'] = allowed[qid]
    refs = sorted({ref for values in allowed.values() for ref in values})
    claim_schema = contract['schema']['properties']['answers']['items']['properties']['claims']
    claim_schema['items'] = enum(*(refs or ['NO_ALLOWED_CLAIMS']))
    if not refs: claim_schema['maxItems'] = 0
    contract.update(version=VERSION + ('-production-verification' if verifier else '-assessment'),
        original_contract_sha256=identity(old), owned_question_claims_sha256=identity(allowed),
        generation_reference_policy='exact-canonical-enum-and-question-owned-list',
        scientific_validator_version=original.VERIFIER_VERSION if verifier else rows.VERSION)
    contract['prompt'] = old['prompt'] + POLICY + REFERENCE_FORMAT
    text = json.dumps(json.loads(encoded(evidence)), ensure_ascii=False)
    if verifier:
        body['messages'][0]['content'] = text; body['system'] = contract['prompt']
        body['output_config']['format']['schema'] = anthropic_schema(contract['schema'])
    else:
        body['input'] = text; body['instructions'] = contract['prompt']
        body['text']['format'].update(name=contract['version'], schema=contract['schema'])
    return contract, body


def assessment_body(data): return _body(data)
def verifier_body(data, assessment): return _body(data, assessment)


def _parse(payload, data, assessment=None):
    verifier = assessment is not None
    # The original parser also rejects incomplete envelopes, duplicate JSON keys,
    # non-JSON constants, foreign/retired claims and missing/duplicate questions.
    value = (original.verifier_parse(payload, data, assessment) if verifier else original.assessment_parse(payload, data))
    contract, _ = _body(data, assessment)
    wire = json.loads(final_text('anthropic' if verifier else 'openai', payload))
    validate_schema(wire, contract['schema'])
    for row in wire['answers']: _reason(row['reason'])
    return value


def assessment_parse(payload, data): return _parse(payload, data)
def verifier_parse(payload, data, assessment): return _parse(payload, data, assessment)


def assessment_validate_cached(value, data):
    # Canonical output contains owned canonical references, so the original exact
    # validator is stronger than the shared wire enum. No historical key is reused.
    checked = original.assessment_validate_cached(value, data)
    _substantive_cached(checked)
    return checked


def verifier_validate_cached(value, data, assessment):
    checked = original.verifier_validate_cached(value, data, assessment)
    _substantive_cached(checked)
    return checked


def _substantive_cached(value):
    for person in value['people']:
        for decision in person['decisions']: _reason(decision['reason'])


def _reason(reason):
    if len(reason.strip()) < 15 or reason.strip().casefold() in {'placeholder', 'n/a', 'todo', 'to be completed'}:
        raise ValueError('iteration3_complete_substantive_reason_required')
