"""One blinded development evaluation per scope, using the existing I2 owner.

This is never production verification or evidence of directory-wide feasibility.
Every question comes from a completed, reconstructed graph or the fixed source
control; no caller can provide people, prose, grades, groups, or another body.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools import team_recommender_executor as existing
from tools import contextual_team_iteration2 as workflow
from tools import contextual_team_iteration2_policy as policy
from tools import contextual_team_iteration2_contract as science
from tools import contextual_team_latency_contract as interpretation_wire
from tools.contextual_team_check import judge_prompt, OWNED_FORMAT
from tools.contextual_team_contract import obj, array, enum, string
from tools.contextual_team_diagnostics import final_text
from tools.contextual_team_executor import scope_inputs, validate_cache_identity, RecoveryRequired
from tools.offline_ai import request_body, response_value, validate_schema
from tools.offline_spend import identity, encoded, atomic_json, ConfigurationFailure

VERSION = 'contextual-iteration2-independent-evaluation-v1'
MAX_RESPONSE_BYTES = 131072
CONTROL_SCOPE = '363069'
CONTROL_PERSON = 'urh-000027'
CONTROL_PERSON_SHA256 = 'ca40bcaa65bc16af27aca7970d8168d40b6b2de14198ad193e251a979586e644'
SOURCE_LABELS = ('coherent-research-scope', 'unselected-broad-program', 'nonresearch-activity', 'insufficient-source-information')
USEFUL_LABELS = ('strong', 'plausible', 'unrelated', 'insufficient-information')
EXPLANATION_LABELS = ('faithful', 'unsupported', 'insufficient-information')
FORMAT = '''Return exactly one answers array row per supplied item_id, in any order.
Each row has item_id, verdict, evidence_ref and a complete reason (15-1000
characters). Source suitability uses coherent-research-scope,
unselected-broad-program, nonresearch-activity or insufficient-source-information.
Explanation audit uses faithful, unsupported or insufficient-information. All
other questions use strong, plausible, unrelated or insufficient-information.
Cite exactly scope.science, an item-owned person_id, or an item-owned canonical
claim_id@revision from the supplied documents. No composite citations or aliases.
Question labels, order and inclusion convey no prior judgment. Only explicit
explanation_audit assertions expose text to audit; do not treat those assertions
as independent evidence. Source suitability is not directory feasibility, and
the bounded people shown cannot establish directory-wide feasibility or yield.
Scientific disagreement is a result; do not seek a rerun or consensus.
'''


def select(graph):
    node = shutil.which('node')
    if not node:
        raise ConfigurationFailure('iteration2_exact_composer_runtime_unavailable')
    safe_env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    raw = subprocess.check_output([node, 'tools/contextual_iteration2_selection.mjs'],
        input=encoded({'graph': graph}), env=safe_env, cwd=policy.ROOT, timeout=30)
    return json.loads(raw)


def _cached_stage(state, ledger_state, scope, stage, contract, body, input_id, validator):
    purpose = policy.operation(scope['id'], stage)
    key = identity([existing.AUTHORIZATION_ID, 'contextual-v1', [policy.VERSION, purpose, identity(contract), input_id]])
    rows = [r for r in ledger_state['requests'] if r.get('purpose') == purpose]
    events = [e for e in ledger_state['events'] if e.get('authority') == policy.VERSION and e.get('purpose') == purpose]
    if (len(rows) != 1 or rows[0]['status'] != 'valid' or rows[0]['key'] != key
            or events != [policy.packet_event(purpose, body, contract, input_id)]):
        raise RecoveryRequired('iteration2_check_requires_exact_successful_stage')
    saved = json.loads((Path(state)/'cache'/(key+'.json')).read_bytes())
    validate_cache_identity(saved, rows[0], body, policy.STAGES[stage][0])
    return validator(saved['value'])


def actual_result(state, config, scope_id):
    scope = next((s for s in config['scopes'] if s['id'] == scope_id), None)
    if scope is None:
        raise ConfigurationFailure('iteration2_check_development_scope_only')
    ledger_state = existing.ExperimentLedger(Path(state)/'ledger.json').read()
    policy.history(ledger_state)
    # This one fixed historical control is not a production action or a claim
    # that a blocked source was assessed through the normal serving workflow.
    if scope_id == CONTROL_SCOPE and scope['state'] != 'unassessed':
        return scope, None, None, {'groups': [], 'primary_view': [], 'option_count': 0}
    path = workflow.result_path(state, scope_id)
    if not path.exists():
        raise RecoveryRequired('iteration2_check_completed_result_required')
    saved = json.loads(path.read_bytes()); graph = saved['value']
    if (set(saved) != {'kind', 'snapshot_id', 'source_id', 'value'} or saved['kind'] != 'contextual_scope_result'
            or saved['snapshot_id'] != config['snapshot_id'] or saved['source_id'] != scope['source_id']):
        raise ConfigurationFailure('iteration2_check_result_wrapper_identity')
    source = scope_inputs(scope)
    ic, ib = interpretation_wire.body('decomposition', source, 'L', 8000, repaired=True)
    interpretation = _cached_stage(state, ledger_state, scope, 'interpret', ic, ib, identity(source),
        lambda v: interpretation_wire.validate_resolved('decomposition', v, source, repaired=True))
    if interpretation['state'] != 'coherent':
        if graph != {'state': interpretation['state'], 'scope_id': scope_id, 'interpretation': interpretation}:
            raise ConfigurationFailure('iteration2_check_noncoherent_result_identity')
        return scope, graph, None, {'groups': [], 'primary_view': [], 'option_count': 0}
    people = {p['person_id']: p for p in config['people']}
    retrieval = graph['retrieval']; shortlist = retrieval['shortlist']
    if (not 1 <= len(shortlist) <= 12 or len(shortlist) != len(set(shortlist))
            or not set(shortlist) <= set(people) or retrieval['eligible'] != len(config['documents'])
            or retrieval['unassessed'] != len(config['documents'])-len(shortlist)
            or retrieval['maximum_shortlist'] != 12):
        raise ConfigurationFailure('iteration2_check_retrieval_identity')
    data = source | {'interpretation': interpretation, 'people': [people[pid] for pid in shortlist]}
    ac, ab = science.assessment_body(data)
    assessment = _cached_stage(state, ledger_state, scope, 'assess', ac, ab, identity(data),
        lambda v: science.assessment_validate_cached(v, data))
    vc, vb = science.verifier_body(data, assessment)
    verified = _cached_stage(state, ledger_state, scope, 'verify', vc, vb, identity(science.verification_inputs(data, assessment)),
        lambda v: science.verifier_validate_cached(v, data, assessment))
    expected = science.adapter(data, assessment, verified, config, scope, retrieval, graph['requests'])
    expected.update(contracts={'decomposition': identity(ic), 'adjudication': identity(ac), 'verification': identity(vc)},
        catalog_source_id=scope.get('catalog_source_id'),
        source_receipt_id=identity(scope['source_receipt']) if 'source_receipt' in scope else None,
        execution_capacity={'version': policy.VERSION, 'output_tokens': {k: v[2] for k, v in policy.STAGES.items() if k != 'check'},
            'models': {k: v[1] for k, v in policy.STAGES.items() if k != 'check'}, 'automatic_retries': 0, 'new_document_purchases': False})
    expected['graph_id'] = identity({k: v for k, v in expected.items() if k not in ('requests', 'graph_id')})
    if graph != expected:
        raise ConfigurationFailure('iteration2_check_graph_not_exact_production_result')
    # Complete verifier abstentions remain independently evaluable, but the
    # serving composer accepts only coherent graphs. Preserve their exact graph
    # identity without manufacturing a group or dropping their person questions.
    selection = ({'graph_id': graph['graph_id'], 'groups': [], 'primary_view': [], 'option_count': 0}
        if verified['state'] in ('unsuitable', 'insufficient_source', 'needs_scope_selection') else select(graph))
    return scope, graph, assessment, selection


def packet(scope, graph, assessment, selection, config):
    documents = {p['person_id']: p for p in config['people']}
    groups = selection['groups']; questions = [{'item_id': 'source', 'task_type': 'source_suitability', 'people': []}]
    shortlist = graph.get('retrieval', {}).get('shortlist', []) if graph else []
    if len(shortlist) != len(set(shortlist)):
        raise ValueError('iteration2_check_duplicate_shortlist')
    top = shortlist[:5]; control = graph is None
    if control:
        if scope['id'] != CONTROL_SCOPE or scope['state'] == 'unassessed' or groups:
            raise ConfigurationFailure('iteration2_check_fixed_source_control_only')
        if identity(documents.get(CONTROL_PERSON)) != CONTROL_PERSON_SHA256:
            raise ConfigurationFailure('iteration2_check_fixed_control_person_changed')
        questions.append({'item_id': 'control-person', 'task_type': 'call_person', 'people': [CONTROL_PERSON]})
    useful = [e for e in (graph or {}).get('edges', []) if e['coverage'] in ('direct', 'method_transfer')]
    if (len(groups) > 2 or any(not 2 <= len(g) <= 4 or len(set(g)) != len(g) for g in groups)
            or any(not set(g) <= set(shortlist) for g in groups)
            or any(not any(e['person_id'] in g and e['central'] for e in useful) for g in groups)
            or any(not any(e['person_id'] == pid for e in useful) for g in groups for pid in g)
            or (graph and graph.get('graph_id') and selection.get('graph_id') != graph['graph_id'])):
        raise ValueError('iteration2_check_exact_composed_group_required')
    for index, pid in enumerate(top):
        questions.append({'item_id': 'top-'+str(index+1), 'task_type': 'call_person', 'people': [pid]})
    for index, group in enumerate(groups):
        questions.append({'item_id': 'group-'+str(index+1), 'task_type': 'group_usefulness', 'people': group})
    primary = groups[0] if groups else []
    for pid in primary:
        if pid not in top:
            questions.append({'item_id': 'member-'+str(primary.index(pid)+1), 'task_type': 'call_person', 'people': [pid]})
    views = selection['primary_view']
    if [v['person_id'] for v in views] != primary:
        raise ValueError('iteration2_check_exact_displayed_primary_required')
    for index, view in enumerate(views):
        shown = view['evidence']; person = documents[view['person_id']]
        if (not isinstance(shown.get('evidence_phrase'), str) or len(shown['evidence_phrase']) < 8
                or not any(shown['evidence_phrase'] in claim['evidence'] and shown['evidence_term'] == claim['label']
                           for claim in person['claims'])):
            raise ValueError('iteration2_check_displayed_evidence_not_owned')
        questions.append({'item_id': 'explanation-'+str(index+1), 'task_type': 'explanation_audit',
            'people': [view['person_id']], 'assertion': deepcopy(shown)})
    exclusions = []
    if assessment is not None:
        after = {(p['person_id'], d['role_id']): d for p in graph['pair_decisions'] for d in p['decisions']}
        roles = {r['id']: r for r in graph['roles']}
        for person in assessment['people']:
            for decision in person['decisions']:
                key = person['person_id'], decision['role_id']
                if decision['coverage'] in ('direct', 'method_transfer') and after[key]['coverage'] not in ('direct', 'method_transfer'):
                    exclusions.append(key)
        for index, (pid, rid) in enumerate(exclusions[:3]):
            role = roles[rid]
            questions.append({'item_id': 'aspect-'+str(index+1), 'task_type': 'aspect_person', 'people': [pid],
                'target_aspect': {k: role[k] for k in ('label', 'quote', 'source_ref')}})
    ids = list(dict.fromkeys(pid for q in questions for pid in q['people']))
    if not set(ids) <= set(documents) or len(questions) > 19:
        raise ValueError('iteration2_check_complete_question_bound')
    evidence = scope_inputs(scope) | {'profile_documents': [documents[pid] for pid in ids], 'items': questions}
    owned = {q['item_id']: {'scope.science'} | set(q['people']) | {
        c['claim_id']+'@'+str(c['revision']) for pid in q['people'] for c in documents[pid]['claims']} for q in questions}
    labels = {q['item_id']: SOURCE_LABELS if q['task_type'] == 'source_suitability' else
        EXPLANATION_LABELS if q['task_type'] == 'explanation_audit' else USEFUL_LABELS for q in questions}
    row = obj(item_id=enum(*(q['item_id'] for q in questions)), verdict=enum(*dict.fromkeys(SOURCE_LABELS+USEFUL_LABELS+EXPLANATION_LABELS)),
        evidence_ref=string(max(len(v) for refs in owned.values() for v in refs)), reason=string(1000, 15))
    answers = array(row, len(questions)); answers['minItems'] = len(questions); schema = obj(answers=answers)
    prompt = judge_prompt(owned_references=True)
    if prompt.count(OWNED_FORMAT) != 1:
        raise ValueError('iteration2_check_original_judge_format_changed')
    prompt = prompt.replace(OWNED_FORMAT, FORMAT) + science.CLARIFICATION
    contract = {'version': VERSION, 'schema': schema, 'prompt': prompt, 'evidence_sha256': identity(evidence),
        'owned_references_sha256': identity({k: sorted(v) for k, v in owned.items()}),
        'labels_sha256': identity(labels), 'source_id': scope['source_id'], 'snapshot_id': config['snapshot_id'],
        'graph_sha256': identity(graph), 'selection_sha256': identity(selection),
        'assessment_sha256': identity(assessment), 'maximum_response_bytes': MAX_RESPONSE_BYTES,
        'source_only_control': control, 'production_admission': False}
    body = request_body({'provider': 'anthropic', 'model': 'claude-sonnet-5'},
        {'schema_version': VERSION, 'max_output_tokens': 12000}, prompt, json.loads(encoded(evidence)), schema)
    body['thinking'] = {'type': 'disabled'}
    if len(encoded(body)) > policy.plan()['maximum_wire_bytes']:
        raise ValueError('iteration2_check_complete_evidence_wire_bound')
    report = {'top_five_people': top, 'missing_top_five': 5-len(top), 'groups': deepcopy(groups),
        'missing_primary_group': not bool(groups), 'missing_first_alternative': len(groups) < 2,
        'exclusion_pair_count': len(exclusions), 'exclusion_pairs_audited': [list(v) for v in exclusions[:3]],
        'missing_exclusion_judgments': max(0, len(exclusions)-3),
        'feasible_scope_yield': {'status': 'unmeasured', 'denominator': None,
            'reason': 'A retrieval shortlist cannot establish directory-wide feasibility.'},
        'source_only_control': control, 'independent_evaluation_not_production_verification': True,
        'human_judgments': 0, 'same_model_family_limitation': True}
    return contract, body, validator(questions, schema, owned, labels, identity(evidence)), report


def validator(questions, schema, owned, labels, input_id):
    def resolve(value):
        if len(encoded(value)) > MAX_RESPONSE_BYTES:
            raise ValueError('iteration2_check_response_bound')
        validate_schema(value, schema)
        answers = {r['item_id']: r for r in value['answers']}
        if len(answers) != len(questions) or set(answers) != set(owned):
            raise ValueError('iteration2_check_exact_question_set')
        for qid, row in answers.items():
            if row['verdict'] not in labels[qid] or row['evidence_ref'] not in owned[qid]:
                raise ValueError('iteration2_check_exact_verdict_or_evidence_owner')
        return {'version': VERSION, 'input_sha256': input_id,
            'verdicts': [deepcopy(answers[q['item_id']]) for q in questions]}
    def check(value, cached):
        if cached:
            if not isinstance(value, dict) or set(value) != {'version', 'input_sha256', 'verdicts'}:
                raise ValueError('iteration2_check_cache_shape')
            if resolve({'answers': value['verdicts']}) != value:
                raise ValueError('iteration2_check_cache_not_lossless')
            return value
        try:
            text = final_text('anthropic', value)
        except (TypeError, AttributeError) as error:
            raise ValueError('iteration2_check_invalid_response') from error
        if len(text.encode('utf8')) > MAX_RESPONSE_BYTES:
            raise ValueError('iteration2_check_response_bound')
        response_value('anthropic', value)
        def unique(items):
            result = {}
            for key, item in items:
                if key in result: raise ValueError('duplicate_response_key')
                result[key] = item
            return result
        def constant(_): raise ValueError('non_json_response_constant')
        return resolve(json.loads(text, object_pairs_hook=unique, parse_constant=constant))
    return check


def prepared(state, requested):
    if not isinstance(requested, dict) or set(requested) != {'iteration2_check'} or not isinstance(requested['iteration2_check'], str):
        raise ConfigurationFailure('iteration2_exact_development_check_request')
    config = workflow.configuration(); scope_id = requested['iteration2_check']
    policy.operation(scope_id, 'check')
    scope, graph, assessment, selection = actual_result(state, config, scope_id)
    contract, body, check, report = packet(scope, graph, assessment, selection, config)
    return config, scope, contract, body, check, report, selection


def run(args):
    if os.environ.get('CONTEXTUAL_JOB') or os.environ.get('PACKET_HASH') or os.environ.get('PACKET_COMMIT'):
        raise ConfigurationFailure('iteration2_check_exclusive_operation')
    requested = json.loads(os.environ['CONTEXTUAL_CHECK'])
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy())
        policy.install_authority(args.state, existing.api)
    config, scope, contract, body, check, report, selection = prepared(args.state, requested)
    runner = workflow.Iteration2Runner(args.state, config); runner.scope_id = scope['id']
    purpose = policy.operation(scope['id'], 'check'); input_id = contract['evidence_sha256']
    metadata = policy.bind_operation(runner.ledger, purpose, body, contract, input_id)
    record = {'version': VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'code_sha': os.environ['GITHUB_SHA'],
        'release_id': policy.plan()['release_id'], 'scope_id': scope['id'], 'purpose': purpose,
        'contract_sha256': identity(contract), 'body_sha256': identity(body), 'input_sha256': input_id,
        'selection_sha256': identity(selection), 'graph_sha256': contract['graph_sha256'],
        'maximum_new_metered_attempts': 1, 'maximum_new_native_counts': 1, 'additional_allowance': 0,
        'automatic_retries': 0, 'maximum_output_tokens': 12000, 'public_activation': False,
        'remaining_completion_allowance': policy.remaining(runner.ledger.read(), args.state),
        'protected': policy.pool.plan()['protected']}
    if args.action == 'prepare':
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=anthropic\n')
        atomic_json(args.reservation, record)
        return
    if json.loads(args.reservation.read_bytes()) != record:
        raise ConfigurationFailure('iteration2_check_prepared_packet_changed')
    value = None
    try:
        value = runner.request(purpose, [policy.VERSION, purpose, identity(contract), input_id], body, check, repair_metadata=metadata)
    finally:
        atomic_json(args.result, record | {'report': report, 'selection': selection,
            'evidence': json.loads(body['messages'][0]['content']), 'value': value, 'requests': runner.used,
            'durable_requests': [r for r in runner.ledger.read()['requests'] if r.get('purpose') == purpose]})
        existing.checkpoint(args.state)
