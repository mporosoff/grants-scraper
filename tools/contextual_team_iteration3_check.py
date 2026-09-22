"""Complete independent I3 evaluations of authenticated production outputs.

Historical I2 questions and scientific inputs remain immutable. This version
judges the actual v4 presentations and does not consume production verdicts.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from tools import contextual_team_iteration2_check as original
from tools import contextual_team_iteration3_references as prospective
from tools import team_recommender_executor as existing
from tools.contextual_team_diagnostics import final_text
from tools.offline_ai import request_body, response_value, validate_schema
from tools.offline_spend import ConfigurationFailure, atomic_json, encoded, identity

VERSION = 'contextual-iteration3-independent-evaluation-v1'
MAX_RESPONSE_BYTES = original.MAX_RESPONSE_BYTES
MAX_WIRE_BYTES = 524288
OUTPUT_TOKENS = 12000
UNCOMPOSED_STATES = ('unsuitable', 'insufficient_source', 'needs_scope_selection')
REASON_FORMAT = '''
INDEPENDENT COMPLETE REASONS V1: Every row needs its own substantive complete
scientific explanation of 15-1000 characters after trimming outer whitespace.
Never emit a literal placeholder, TODO, TBD, unfilled template, or generic filler
in place of the reason. Do not pad a short reason. If evidence is insufficient,
say what is missing in a complete evidence-based sentence for that same item.
An unsupported or unrelated judgment is a legitimate result, never a retry cue.
The source_selected_approach was established before choosing named members. It
is neutral project context, not proof that any proposed group is coherent.
Judge joint compatibility independently: shared labels or individual relevance
alone do not prove the members can contribute to a common scientific operation.
For explanation_audit, the assertion is actual displayed text to audit, not new
profile evidence. Documentary quotations, inferred application and unresolved
operational limits must remain distinct. Qualified transfer can be legitimate;
an inferred performed operation cannot be promoted to documentary fact.
'''


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def select(graph, *, direct_source=False):
    node = shutil.which('node')
    if not node:
        raise ConfigurationFailure('iteration3_exact_composer_runtime_unavailable')
    safe_env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    raw = subprocess.check_output([node, 'tools/contextual_iteration3_selection.mjs'],
        input=encoded({'graph': graph, 'direct_source': direct_source}), env=safe_env,
        cwd=Path(__file__).resolve().parents[1], timeout=30)
    return json.loads(raw)


def _semantic_selection(selection):
    # Packaging and preflight mode are observations; exact composer bytes,
    # candidates, groups, assertions and all remaining fields are semantic pins.
    return {k: v for k, v in selection.items() if k not in ('bundle_id', 'direct_source')}


def uncomposed_selection(graph):
    _require(graph.get('version') == 'contextual-audited-graph-v3' and graph.get('state') in UNCOMPOSED_STATES,
             'iteration3_check_exact_uncomposed_state')
    return {'graph_id': graph['graph_id'], 'groups': [], 'primary_view': [], 'option_count': 0,
            'composition_not_applicable': graph['state']}


def _reason(value):
    text = value.strip()
    lowered = text.lower()
    _require(len(text) >= 15, 'iteration3_check_substantive_reason_required')
    marker = (re.fullmatch(r'(?:placeholder|todo|tbd|lorem ipsum|reason|insert reason)[\s.!?_-]*', lowered)
        or lowered.startswith(('placeholder ', 'todo:', 'tbd:', 'insert reason ', 'lorem ipsum'))
        or any(token in lowered for token in ('<reason>', '[reason]', '{reason}')))
    _require(not marker, 'iteration3_check_unfilled_reason_placeholder')


def validator(questions, schema, owned, labels, input_id, contract_id):
    def resolve(value):
        _require(len(encoded(value)) <= MAX_RESPONSE_BYTES, 'iteration3_check_response_bound')
        validate_schema(value, schema)
        answers = {r['item_id']: r for r in value['answers']}
        _require(len(answers) == len(value['answers']) == len(questions) and set(answers) == set(owned),
                 'iteration3_check_exact_question_set')
        for qid, row in answers.items():
            _require(row['verdict'] in labels[qid] and row['evidence_ref'] in owned[qid],
                     'iteration3_check_exact_verdict_or_evidence_owner')
            _reason(row['reason'])
        return {'version': VERSION, 'input_sha256': input_id, 'contract_sha256': contract_id,
                'verdicts': [deepcopy(answers[q['item_id']]) for q in questions]}
    def check(value, cached):
        if cached:
            _require(isinstance(value, dict) and set(value) == {'version', 'input_sha256', 'contract_sha256', 'verdicts'},
                     'iteration3_check_cache_shape')
            _require(resolve({'answers': value['verdicts']}) == value, 'iteration3_check_cache_not_lossless')
            return value
        _require(isinstance(value, dict), 'iteration3_check_response_envelope')
        try:
            text = final_text('anthropic', value)
            _require(len(text.encode('utf8')) <= MAX_RESPONSE_BYTES, 'iteration3_check_response_bound')
            response_value('anthropic', value)
        except (TypeError, AttributeError) as error:
            raise ValueError('iteration3_check_invalid_response') from error
        def unique(items):
            result = {}
            for key, item in items:
                _require(key not in result, 'iteration3_check_duplicate_response_key'); result[key] = item
            return result
        def constant(_): raise ValueError('iteration3_check_non_json_constant')
        return resolve(json.loads(text, object_pairs_hook=unique, parse_constant=constant))
    return check


def packet(scope, graph, assessment, selection, config, *, generation_id):
    _require(re.fullmatch(r'[a-f0-9]{64}', generation_id or '') is not None, 'iteration3_check_generation_identity')
    _require(graph is not None and graph.get('version') in ('contextual-audited-graph-v3', 'contextual-audited-graph-v4'),
             'iteration3_check_exact_production_graph_required')
    if graph.get('state') in UNCOMPOSED_STATES:
        _require(selection == uncomposed_selection(graph), 'iteration3_check_exact_uncomposed_selection')
    else:
        _require(selection.get('graph_id') == graph['graph_id'] and
                 selection.get('composer_version') == 'contextual-composition-v4' and
                 re.fullmatch(r'[a-f0-9]{64}', selection.get('composer_sha256', '')) is not None,
                 'iteration3_check_actual_composer_identity')
    _require(isinstance(selection.get('groups'), list) and len(selection['groups']) <= 8 and
             selection.get('option_count') == len(selection['groups']), 'iteration3_check_bounded_composed_options')
    narrowed = deepcopy(selection); narrowed['groups'] = narrowed['groups'][:2]
    scaffold = deepcopy(narrowed)
    if graph['version'] == 'contextual-audited-graph-v4':
        groups = graph['integrity']['groups']
        approved = [g['member_ids'] for g in graph['integrity']['candidate_groups']
                    if next(answer for answer in groups if answer['candidate_id'] == g['candidate_id'])['status'] == 'supported']
        _require(selection['groups'] == approved, 'iteration3_check_exact_integrity_approved_groups')
        # The legacy machinery validates one owned quotation. This scaffold is
        # discarded below; the new questions carry complete actual displayed text.
        for view in scaffold['primary_view']:
            pid = view['person_id']
            presentation = next((e for e in graph['integrity']['explanations'] if e['person_id'] == pid), None)
            _require(presentation is not None, 'iteration3_check_exact_integrity_presentation')
            claims = presentation['documented_claims']; shown = view['evidence']
            _require(shown.get('faculty_id') == pid and
                shown.get('evidence_phrase') == ' | '.join(c['evidence'] for c in claims) and
                shown.get('evidence_term') == '; '.join(c['label'] for c in claims) and
                shown.get('contribution') == 'Potential project relevance (inferred): '+presentation['potential_project_relevance'] and
                shown.get('why_person') == 'Retained profile activity (audited evidence): '+' '.join(c['evidence'] for c in claims)+
                    ' Potential project relevance (inferred): '+presentation['potential_project_relevance']+
                    ' Unconfirmed operation or limit: '+presentation['unconfirmed_operation_or_limit']+' This is not a capability certificate.',
                'iteration3_check_exact_displayed_integrity_assertion')
            view['evidence'] = deepcopy(shown) | {'evidence_phrase': claims[0]['evidence'], 'evidence_term': claims[0]['label']}
    legacy, old_body, _, report = original.packet(scope, graph, assessment, scaffold, config, version=original.VERSION)
    evidence = json.loads(old_body['messages'][0]['content'])
    if graph.get('approach'):
        evidence['source_selected_approach'] = graph['approach']
    for question in evidence['items']:
        if question['task_type'] == 'explanation_audit':
            view = next(v for v in narrowed['primary_view'] if v['person_id'] == question['people'][0])
            question['assertion'] = deepcopy(view['evidence'])
    owned = {q['item_id']: set(q['allowed_evidence_refs']) for q in evidence['items']}
    labels = {q['item_id']: original.SOURCE_LABELS if q['task_type'] == 'source_suitability' else
        original.EXPLANATION_LABELS if q['task_type'] == 'explanation_audit' else original.USEFUL_LABELS for q in evidence['items']}
    prompt = legacy['prompt'] + prospective.POLICY + REASON_FORMAT
    contract = {**{k: deepcopy(v) for k, v in legacy.items() if k not in ('version', 'prompt', 'evidence_sha256', 'selection_sha256')},
        'version': VERSION, 'prompt': prompt, 'evidence_sha256': identity(evidence),
        'selection_sha256': identity(_semantic_selection(selection)), 'generation_id': generation_id,
        'question_construction_version': original.VERSION,
        'reason_policy': 'trimmed minimum 15 characters; no literal or unfilled reason placeholder; no padding',
        'output_tokens': OUTPUT_TOKENS, 'new_human_labels': 0}
    body = request_body({'provider': 'anthropic', 'model': 'claude-sonnet-5'},
        {'schema_version': VERSION, 'max_output_tokens': OUTPUT_TOKENS}, prompt, json.loads(encoded(evidence)), contract['schema'])
    body['thinking'] = {'type': 'disabled'}
    _require(len(encoded(body)) <= MAX_WIRE_BYTES, 'iteration3_check_complete_evidence_wire_bound')
    report.update(observed_ui_bundle_id=selection.get('bundle_id'), direct_source_preflight=selection.get('direct_source') is True,
        generation_id=generation_id, all_composed_option_count=len(selection['groups']),
        evaluates_primary_and_first_alternative_when_present=True, production_integrity_used_as_independent_evidence=False,
        historical_scientific_results_changed=False)
    return contract, body, validator(evidence['items'], contract['schema'], owned, labels, identity(evidence), identity(contract)), report


def prepared(state, requested, *, direct_source=False):
    from tools import contextual_team_iteration3 as workflow
    from tools import contextual_team_iteration3_policy as policy
    _require(isinstance(requested, dict) and set(requested) == {'iteration3_check'} and isinstance(requested['iteration3_check'], str),
             'iteration3_exact_independent_check_request')
    scope_id = requested['iteration3_check']; policy.operation(scope_id, 'check')
    actual = workflow.actual_result(state, scope_id)
    selection = (uncomposed_selection(actual['graph']) if actual['graph'].get('state') in UNCOMPOSED_STATES
                 else select(actual['graph'], direct_source=direct_source))
    contract, body, check, report = packet(actual['scope'], actual['graph'], actual['assessment'], selection,
        actual['configuration'], generation_id=policy.plan()['release_id'])
    return actual['configuration'], actual['scope'], contract, body, check, report, selection


def run(args):
    from tools import contextual_team_iteration3 as workflow
    from tools import contextual_team_iteration3_policy as policy
    if os.environ.get('CONTEXTUAL_JOB') or os.environ.get('PACKET_HASH') or os.environ.get('PACKET_COMMIT'):
        raise ConfigurationFailure('iteration3_check_exclusive_operation')
    requested = json.loads(os.environ['CONTEXTUAL_CHECK'])
    _require(isinstance(requested, dict) and set(requested) == {'iteration3_check'} and isinstance(requested['iteration3_check'], str),
             'iteration3_exact_independent_check_request')
    policy.operation(requested['iteration3_check'], 'check')
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy()); policy.install_authority(args.state, existing.api)
    config, scope, contract, body, check, report, selection = prepared(args.state, requested)
    purpose = policy.operation(scope['id'], 'check'); input_id = contract['evidence_sha256']
    # EC's packet intentionally retains the historical source snapshot. Dispatch
    # still belongs to the current I3 authority and approved runner configuration.
    runner = workflow.Iteration3Runner(args.state, workflow.configuration()); runner.scope_id = scope['id']
    metadata = policy.bind_operation(runner.ledger, purpose, body, contract, input_id)
    admission = policy.prepare_record(args.state, {'scope_id': scope['id'], 'operation': 'check',
        'job_id': identity([VERSION, policy.plan()['release_id'], scope['id']])})
    record = admission | {'version': VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'code_sha': os.environ['GITHUB_SHA'],
        'release_id': policy.plan()['release_id'], 'scope_id': scope['id'], 'purpose': purpose,
        'contract_sha256': identity(contract), 'body_sha256': identity(body), 'input_sha256': input_id,
        'selection_sha256': identity(selection), 'graph_sha256': contract['graph_sha256'],
        'maximum_new_metered_attempts': 1, 'maximum_new_native_counts': 1, 'additional_allowance': 0,
        'automatic_retries': 0, 'maximum_output_tokens': OUTPUT_TOKENS, 'public_activation': False,
        'remaining_completion_allowance': policy.remaining(runner.ledger.read(), args.state)}
    if args.action == 'prepare':
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream: stream.write('text_provider=anthropic\n')
        atomic_json(args.reservation, record); return
    if json.loads(args.reservation.read_bytes()) != record:
        raise ConfigurationFailure('iteration3_check_prepared_packet_changed')
    value = None
    try:
        value = runner.request(purpose, [policy.VERSION, purpose, identity(contract), input_id], body, check, repair_metadata=metadata)
    finally:
        atomic_json(args.result, record | {'report': report, 'selection': selection,
            'evidence': json.loads(body['messages'][0]['content']), 'value': value, 'requests': runner.used,
            'durable_requests': [r for r in runner.ledger.read()['requests'] if r.get('purpose') == purpose]})
        existing.checkpoint(args.state)
