"""Selected-approach assessment, downgrade-only production verification and graph.

Independent evaluation verdicts never become production admission evidence.
Historical contracts and their accepted judgments remain unchanged.
"""
from copy import deepcopy
import json
from tools import contextual_team_answer_rows as rows
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_requirements as requirements
from tools import contextual_team_references as references
from tools.contextual_team_demand_contract import claim_table
from tools.contextual_team_contract import obj, enum, BOOL
from tools.contextual_team_diagnostics import final_text
from tools.offline_ai import request_body, validate_schema, response_value
from tools.offline_spend import identity, encoded

VERSION = 'contextual-iteration2-science-v1'
GRAPH_VERSION = 'contextual-audited-graph-v3'
VERIFIER_VERSION = VERSION + '-production-verification'
CLARIFICATION = '''
GENERAL SCIENTIFIC CLARIFICATION V1: Separate documented scientific activity from
the narrative a new proposal must supply. Existing documented activity can
directly support an actual source-warranted contribution without a biography
already articulating the proposed project's complete challenge, cross-program
collaboration, translational narrative or societal-need statement. Missing that
proposal narrative alone does not downgrade an otherwise evidenced operation.
This does not waive scientific scope or sponsor exclusions. Judge the actual
operation in the selected approach and the complete source context. A transfer
requires an explicitly evidenced method plus a credible application bridge;
general field overlap, shared terminology or a socially useful application is
not that bridge. Do not add an absent operation, access, facility or capability.
When the source excludes technology development primarily supported by other agencies,
preserve that exclusion: technological relevance cannot convert excluded work
into a permitted contribution. Preserve all other scope, eligibility, submission
and administrative conditions. A plausible conversation is not automatically a
supported contribution, verified group, or evidence of proposal readiness.
Unresolved evidence remains uncertainty; do not infer personal incompetence.
'''
VERIFIER_FORMAT = '''
PRODUCTION COMPLETE-PAIR VERIFICATION replaces legacy sparse-output instructions.
This is the separate downgrade-only production verifier, not an independent
evaluation checker. Original source, selected approach and full original person
evidence are supplied. Proposed pairs contain only exact identities, coverage,
claims and central flags; assessor explanations and person outcomes are withheld.
Return state and answers under the supplied strict schema. State judges the
original source/selected approach; absence of capable candidates alone does not
make a coherent scientific purpose unsuitable. Return every supplied question
exactly once. Each row contains question_id, coverage, claims, central, reason,
and gap. No evaluation verdicts. Use canonical claim_id@revision references.
Retain or downgrade each proposed coverage in this order: direct, method_transfer,
adjacent, insufficient_information. Never upgrade, including from insufficient
information. Retain or remove only the claims listed for that exact proposed
person/contribution pair; never add support from another claim or person. Retain
or remove central=true; never grant it. Non-useful decisions have central=false.
Write your own complete evidence-based reason (15-700 characters) and honest gap
(0-300 characters). Read complete evidence; a permitted reference is not proof of
scientific support. Positive coverage needs at least one retained supporting
claim. An excluded or noncoherent source has only insufficient_information rows
with no retained claims and central=false. Never invent missing answers.
'''


def _inputs(data):
    if set(data) != {'scope', 'interpretation', 'people'}:
        raise ValueError('iteration2_exact_scientific_input_fields')
    policy = data['interpretation'].get('requirement_policy')
    if policy != requirements.VERSION:
        raise ValueError('iteration2_selected_approach_required')
    requirements.validate_resolved('decomposition', data['interpretation'], {'scope': data['scope']})
    active = requirements.active_data(data)
    projected = deepcopy(active)
    # The original complete-pair validator owns scientific decision invariants.
    # Extra selected-approach metadata remains in the actual provider evidence
    # and outer contract; this projection changes no evaluated role or source.
    projected['interpretation'] = {key: deepcopy(active['interpretation'][key])
        for key in ('state', 'objective', 'roles', 'limitations')}
    role_fields = ('id', 'label', 'required', 'quote', 'source_field', 'source_ref', 'central')
    projected['interpretation']['roles'] = [{key: deepcopy(role[key]) for key in role_fields}
        for role in active['interpretation']['roles']]
    pairs.schema(projected)
    return active, projected


def _evidence(active, projected):
    questions, claims, _ = rows.mapping(projected)
    return json.loads(encoded(deepcopy(active) | {'claim_references': claim_table(active),
        'wire_questions': questions, 'wire_claims': claims}))


def assessment_body(data):
    active, projected = _inputs(data)
    base, body = rows.body(projected)
    prompt = base['prompt'] + requirements.POLICY + CLARIFICATION
    contract = base | {'version': VERSION+'-assessment',
        'input_sha256': identity(data), 'active_input_sha256': identity(active),
        'pair_input_sha256': identity(projected), 'answer_row_contract_sha256': identity(base),
        'requirement_policy': requirements.VERSION, 'prompt': prompt}
    body['input'] = json.dumps(_evidence(active, projected), ensure_ascii=False)
    body['instructions'] = prompt
    body['text']['format']['name'] = contract['version']
    return contract, body


def assessment_parse(payload, data):
    _, projected = _inputs(data)
    return rows.parse(payload, 'openai', projected)


def assessment_validate_cached(value, data):
    _, projected = _inputs(data)
    return rows.validate_cached(value, projected)


def verification_inputs(data, assessment):
    active, projected = _inputs(data)
    assessment_validate_cached(assessment, data)
    role_map = {r['id']: r for r in active['interpretation']['roles']}
    proposed = []
    for person in assessment['people']:
        for decision in person['decisions']:
            proposed.append({'person_id': person['person_id'], 'role_id': decision['role_id'],
                'source_ref': decision['source_ref'], 'coverage': decision['coverage'],
                'claims': [decision['claim_refs'][slot] for slot in ('primary', 'second', 'third')
                    if decision['claim_refs'][slot] != pairs.NONE],
                'central': bool(role_map[decision['role_id']]['central'] and decision['coverage'] in pairs.CATEGORIES[:2])})
    return json.loads(encoded(_evidence(active, projected) | {'proposed_pairs': proposed}))


def verifier_body(data, assessment):
    _, projected = _inputs(data)
    evidence = verification_inputs(data, assessment)
    row_schema = deepcopy(rows.schema(projected)['properties']['answers'])
    row_schema['items']['properties']['central'] = BOOL
    row_schema['items']['required'].append('central')
    schema = obj(state=enum('coherent', 'needs_scope_selection', 'insufficient_source', 'unsuitable'), answers=row_schema)
    # Keep the existing production scientific verifier, not the evaluation rubric.
    prompt = references.contract('verification')['prompt'] + requirements.POLICY + CLARIFICATION + VERIFIER_FORMAT
    contract = {'version': VERIFIER_VERSION, 'input_sha256': identity(data),
        'verification_input_sha256': identity(evidence), 'assessment_sha256': identity(assessment),
        'schema': schema, 'prompt': prompt, 'maximum_pairs': len(evidence['wire_questions']),
        'maximum_final_bytes': pairs.MAX_FINAL_BYTES, 'serving_approved': False}
    body = request_body({'provider': 'anthropic', 'model': 'claude-sonnet-5'},
        {'schema_version': VERIFIER_VERSION, 'max_output_tokens': 24000}, prompt, evidence, schema)
    body['thinking'] = {'type': 'disabled'}
    return contract, body


def verifier_resolve(value, data, assessment):
    _, projected = _inputs(data)
    contract, _ = verifier_body(data, assessment)
    if len(encoded(value)) > pairs.MAX_FINAL_BYTES:
        raise ValueError('iteration2_verifier_response_bytes')
    validate_schema(value, contract['schema'])
    ordinary = {'answers': [{k: v for k, v in row.items() if k != 'central'} for row in value['answers']]}
    result = rows.resolve(ordinary, projected)
    questions, _, _ = rows.mapping(projected)
    central = {(questions[row['question_id']]['person_id'], questions[row['question_id']]['role_id']): row['central']
        for row in value['answers']}
    proposed = {(row['person_id'], row['role_id']): row for row in verification_inputs(data, assessment)['proposed_pairs']}
    for person in result['people']:
        for decision in person['decisions']:
            key = (person['person_id'], decision['role_id']); before = proposed[key]
            refs = {ref for ref in decision['claim_refs'].values() if ref != pairs.NONE}
            flag = central[key]
            if (pairs.STRENGTH[decision['coverage']] > pairs.STRENGTH[before['coverage']]
                    or not refs <= set(before['claims']) or flag and not before['central']):
                raise ValueError('iteration2_verifier_upgrade_or_new_claim')
            if flag and decision['coverage'] not in pairs.CATEGORIES[:2]:
                raise ValueError('iteration2_nonuseful_central')
            if value['state'] != 'coherent' and (decision['coverage'] != 'insufficient_information' or refs or flag):
                raise ValueError('iteration2_noncoherent_supported_pairs')
            decision['central'] = flag
    result.update(version=VERIFIER_VERSION, state=value['state'],
        input_sha256=identity(verification_inputs(data, assessment)))
    return result


def verifier_parse(payload, data, assessment):
    if not isinstance(payload, dict):
        raise ValueError('invalid_response_envelope')
    try:
        text = final_text('anthropic', payload)
    except (TypeError, AttributeError) as error:
        raise ValueError('invalid_response_content') from error
    if len(text.encode('utf8')) > pairs.MAX_FINAL_BYTES:
        raise ValueError('iteration2_verifier_response_bytes')
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
    _, projected = _inputs(data); questions, _, _ = rows.mapping(projected)
    addresses = {(q['person_id'], q['role_id']): qid for qid, q in questions.items()}
    try:
        wire = {'state': value['state'], 'answers': []}
        for person in value['people']:
            for decision in person['decisions']:
                wire['answers'].append({'question_id': addresses[(person['person_id'], decision['role_id'])],
                    **{k: decision[k] for k in ('coverage', 'reason', 'gap', 'central')},
                    'claims': [decision['claim_refs'][slot] for slot in ('primary', 'second', 'third')
                        if decision['claim_refs'][slot] != pairs.NONE]})
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('iteration2_verifier_cache_shape') from error
    if verifier_resolve(wire, data, assessment) != value:
        raise ValueError('iteration2_verifier_cache_not_lossless')
    return value


def adapter(data, assessment, verified, configuration, scope, retrieval, requests):
    active, projected = _inputs(data)
    assessment_validate_cached(assessment, data); verifier_validate_cached(verified, data, assessment)
    from tools.contextual_team_executor import scope_inputs
    if scope_inputs(scope)['scope'] != data['scope']:
        raise ValueError('iteration2_graph_source_identity')
    roles = active['interpretation']['roles']; edges = []
    for person in verified['people']:
        for decision in person['decisions']:
            if decision['coverage'] not in pairs.CATEGORIES[:2]:
                continue
            primary = decision['claims'][0]
            edges.append({'person_id': person['person_id'], 'role_id': decision['role_id'],
                'claim_id': primary['claim_id'], 'claim_revision': primary['revision'],
                'evidence_quote': primary['evidence'], 'supporting_claims': deepcopy(decision['claims']),
                **{k: decision[k] for k in ('coverage', 'central', 'reason', 'gap')}})
    if len(edges) > 72:
        raise ValueError('iteration2_graph_edge_bound')
    covered = {e['role_id'] for e in edges}; supported = {e['person_id'] for e in edges}
    state = 'ready' if {r['id'] for r in roles} <= covered else 'ready_with_gaps'
    if len(supported) < 2 or not any(e['central'] for e in edges):
        state = 'no_supported_group_in_assessed_set'
    if verified['state'] != 'coherent': state = verified['state']
    graph = {'version': GRAPH_VERSION,
        **{key: configuration[key] for key in ('snapshot_id', 'registry_generation', 'roster_id')},
        'source_id': scope['source_id'],
        'scope': {'id': scope['id'], 'parent_id': scope['parent_id'], 'title': scope['science']['title'],
            'source_url': scope['science'].get('source_document_url') or scope['science'].get('primary_document_url') or scope['science'].get('detail_page')},
        'objective': active['interpretation']['objective'], 'roles': deepcopy(roles),
        'considered_directions': deepcopy(active['interpretation'].get('considered_directions', [])),
        'requirement_policy': data['interpretation'].get('requirement_policy'),
        'approach': data['interpretation'].get('approach', ''),
        'people': [{k: p[k] for k in ('person_id', 'outcome')} for p in verified['people']],
        'pair_decisions': deepcopy(verified['people']), 'edges': edges, 'state': state,
        'conditions': deepcopy(data['scope']['conditions']),
        'limitations': deepcopy(data['interpretation']['limitations'] + data['scope']['limitations']),
        'retrieval': deepcopy(retrieval), 'requests': deepcopy(requests),
        'contracts': {'assessment': identity(assessment_body(data)[0]), 'verification': identity(verifier_body(data, assessment)[0])},
        'provenance': {'adapter_version': GRAPH_VERSION, 'input_sha256': identity(data),
            'active_input_sha256': identity(active), 'pair_input_sha256': identity(projected),
            'assessment_sha256': identity(assessment), 'verification_sha256': identity(verified),
            'all_pair_decisions_retained': True, 'independent_checker_used_for_admission': False}}
    graph['graph_id'] = identity({k: v for k, v in graph.items() if k != 'requests'})
    return graph
