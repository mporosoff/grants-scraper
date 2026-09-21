"""Revalidate one retained independent check without another provider request.

The original failed row, charge, response, and scientific judgments are immutable.
Only exact owned claim IDs may acquire the revision present in their original
evidence. A separate receipt and cache retain this derivation and its authority.
"""
from copy import deepcopy
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

from tools import contextual_team_iteration2_check as original
from tools import contextual_team_iteration2_policy as policy
from tools import team_recommender_executor as existing
from tools.contextual_team_executor import RecoveryRequired, scope_inputs
from tools.offline_spend import ConfigurationFailure, atomic_json, encoded, identity

VERSION = 'iteration2-owned-claim-revision-recovery-v1'
SCOPE_ID = '363302:a-1'
SELECTOR = {'iteration2_check_recovery': SCOPE_ID}
LOCK_PATH = policy.ROOT/'config/contextual_team/iteration2-check-recovery-v1.json'
ERROR = 'iteration2_check_exact_verdict_or_evidence_owner'


def owned_mapping(evidence):
    documents = evidence['profile_documents']; questions = evidence['items']
    people = {p['person_id']: p for p in documents}
    if len(people) != len(documents):
        raise ValueError('iteration2_recovery_duplicate_person')
    global_claims = set()
    for pid, person in people.items():
        for claim in person['claims']:
            cid = claim['claim_id']; revision = claim['revision']
            if (not isinstance(cid, str) or not cid.startswith(pid+'-c') or '@' in cid
                    or cid in global_claims or type(revision) is not int or revision < 1):
                raise ValueError('iteration2_recovery_ambiguous_claim_revision')
            global_claims.add(cid)
    result = {}
    for question in questions:
        qid = question['item_id']; owners = question['people']
        if qid in result or len(owners) != len(set(owners)) or not set(owners) <= set(people):
            raise ValueError('iteration2_recovery_question_ownership')
        refs = {'scope.science': 'scope.science'} | {pid: pid for pid in owners}
        for pid in owners:
            for claim in people[pid]['claims']:
                cid = claim['claim_id']; canonical = cid+'@'+str(claim['revision'])
                refs[cid] = canonical; refs[canonical] = canonical
        result[qid] = refs
    return result


def validation_contract(evidence, legacy_contract):
    if (legacy_contract['version'] != original.LEGACY_VERSION
            or legacy_contract['evidence_sha256'] != identity(evidence)):
        raise ConfigurationFailure('iteration2_recovery_legacy_contract')
    return {'version': VERSION, 'legacy_contract_sha256': identity(legacy_contract),
        'evidence_sha256': identity(evidence), 'owned_revision_map_sha256': identity(owned_mapping(evidence)),
        'rules': 'Exact complete original rows; unique exact item-owned bare claim ID to its supplied revision only; '
                 'canonical references unchanged; no verdict, reason, question, evidence, or order changes; '
                 'unchanged original strict validator; no provider replay.'}


def recover_text(text, evidence, validate):
    if not isinstance(text, str) or len(text.encode('utf8')) > original.MAX_RESPONSE_BYTES:
        raise ValueError('iteration2_recovery_response_bound')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('iteration2_recovery_duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('iteration2_recovery_non_json_constant')
    raw = json.loads(text, object_pairs_hook=unique, parse_constant=constant)
    if not isinstance(raw, dict) or set(raw) != {'answers'} or not isinstance(raw['answers'], list):
        raise ValueError('iteration2_recovery_exact_response_shape')
    mapping = owned_mapping(evidence); seen = set(); rows = deepcopy(raw['answers'])
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'item_id', 'verdict', 'evidence_ref', 'reason'}:
            raise ValueError('iteration2_recovery_exact_row_shape')
        qid = row['item_id']; ref = row['evidence_ref']
        if not isinstance(qid, str) or qid not in mapping or qid in seen:
            raise ValueError('iteration2_recovery_exact_question_set')
        seen.add(qid)
        if not isinstance(ref, str) or ref not in mapping[qid]:
            raise ValueError('iteration2_recovery_exact_owned_reference_required')
        row['evidence_ref'] = mapping[qid][ref]
    if seen != set(mapping):
        raise ValueError('iteration2_recovery_exact_question_set')
    value = {'version': original.LEGACY_VERSION, 'input_sha256': identity(evidence), 'verdicts': rows}
    # The original validator checks schema, labels, ownership, completeness and
    # canonical cache ordering. It never receives altered scientific fields.
    return validate(value, True)


def plan():
    p = json.loads(LOCK_PATH.read_bytes()); run = p['source']['run']
    required = {'id', 'run_attempt', 'event', 'path', 'head_sha', 'head_branch', 'status', 'conclusion'}
    if (p.get('version') != VERSION or p.get('authorization_id') != existing.AUTHORIZATION_ID
            or p.get('scope_id') != SCOPE_ID or set(run) != required
            or type(run['id']) is not int or run['id'] <= 0 or run['run_attempt'] != 1
            or run['event'] != 'workflow_dispatch' or run['head_branch'] != 'main'
            or run['path'] != '.github/workflows/team-recommender-offline.yml'
            or run['status'] != 'completed' or run['conclusion'] != 'failure'):
        raise ConfigurationFailure('iteration2_recovery_lock_identity')
    return p


def recovery_key(p=None):
    return identity(['exact-retained-iteration2-check', p or plan()])


def event(p=None):
    p = p or plan(); source = p['source']
    return {'kind': 'exact_retained_response_revalidated', 'authority': VERSION,
        'recovery_key': recovery_key(p), 'scope_id': p['scope_id'],
        'authenticated_source_run': source['run'], 'source_request_id': source['request_id'],
        'source_checkpoint_sha256': source['checkpoint_sha256'],
        'source_receipt_sha256': source['receipt_sha256'], 'source_diagnostic_sha256': source['diagnostic_sha256'],
        'source_response_text_sha256': source['text_sha256'], 'source_raw_text_sha256': source['raw_text_sha256'],
        'validation_contract_sha256': p['validation_contract_sha256'], 'result_sha256': p['result_sha256'],
        'original_status': 'failed', 'metered_attempts': 0, 'native_count_calls': 0,
        'new_microusd': 0, 'paid_requests_replayed': 0}


def paths(state, p=None):
    p = p or plan(); state = Path(state)
    return state/'cache'/(recovery_key(p)+'.json'), state/'receipts'/(identity(event(p))[:32]+'.json')


def source_packet(state):
    p = plan(); source = p['source']; config = original.workflow.configuration()
    scope, graph, assessment, selection = original.actual_result(state, config, p['scope_id'])
    if selection.get('composer_sha256') != source['composer_sha256']:
        raise RecoveryRequired('iteration2_recovery_original_composer_changed')
    # A preview packaging update may change only this documentary bundle ID.
    # The complete pinned selection hash still binds composer, graph, people,
    # groups, displayed assertions, gaps and statistics to the original check.
    selection = selection | {'bundle_id': source['selection_bundle_id']}
    if identity(selection) != source['selection_sha256']:
        raise RecoveryRequired('iteration2_recovery_original_selection_changed')
    contract, body, validate, report = original.packet(scope, graph, assessment, selection, config,
        version=original.LEGACY_VERSION)
    return config, scope, contract, body, validate, report, selection


def _source_checkpoint(state, ledger, source, cache_path, receipt_path, supplied=None):
    """Freeze the original checkpoint, then accept only unchanged prefix history.

    The receipt preserves the full original file inventory for later cache use,
    when other authorized scopes may have appended requests and native counts.
    """
    baseline = deepcopy(ledger)
    baseline['requests'] = baseline['requests'][:source['requests']]
    baseline['events'] = baseline['events'][:source['events']]
    if (identity(baseline['requests']) != source['requests_sha256']
            or identity(baseline['events']) != source['events_sha256']
            or existing.sha(encoded(baseline)+b'\n') != source['ledger_sha256']):
        raise RecoveryRequired('iteration2_recovery_original_history_changed')
    current = json.loads((state/'checkpoint.json').read_bytes())
    counts = current['phase2_token_preflight']
    if identity(counts['rows'][:source['native_counts']]) != source['native_counts_sha256']:
        raise RecoveryRequired('iteration2_recovery_native_history_changed')
    if supplied is not None:
        original_checkpoint = supplied
    elif receipt_path.exists():
        original_checkpoint = json.loads(receipt_path.read_bytes())['original_checkpoint']
    else:
        if len(counts['rows']) != source['native_counts']:
            raise RecoveryRequired('iteration2_recovery_missing_original_checkpoint')
        ignored = {cache_path, receipt_path}
        files = {f.relative_to(state).as_posix(): existing.sha(f.read_bytes())
            for f in state.rglob('*.json') if f.name != 'checkpoint.json' and f not in ignored}
        files['ledger.json'] = source['ledger_sha256']
        original_checkpoint = {'authorization_id': existing.AUTHORIZATION_ID,
            'run_id': str(source['run']['id']), 'attempt': str(source['run']['run_attempt']),
            'code_sha': source['run']['head_sha'], 'files': files, 'phase2_token_preflight': counts}
    if existing.sha(encoded(original_checkpoint)+b'\n') != source['checkpoint_sha256']:
        raise RecoveryRequired('iteration2_recovery_original_checkpoint_changed')
    for name, digest in original_checkpoint['files'].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise RecoveryRequired('iteration2_recovery_source_path')
        actual = source['ledger_sha256'] if name == 'ledger.json' else existing.sha((state/name).read_bytes())
        if actual != digest:
            raise RecoveryRequired('iteration2_recovery_original_file_changed')
    return original_checkpoint


def _derive(state, ledger_state=None, packet=None, source_checkpoint=None):
    state = Path(state); p = plan(); source = p['source']; expected_event = event(p)
    ledger = ledger_state if ledger_state is not None else existing.ExperimentLedger(state/'ledger.json').read()
    policy.history(ledger); policy.check_counts(state)
    found = [e for e in ledger['events'] if e.get('authority') == VERSION]
    if found not in ([], [expected_event]):
        raise RecoveryRequired('iteration2_recovery_conflicting_authority')
    rows = [r for r in ledger['requests'] if r.get('id') == source['request_id']]
    if len(rows) != 1 or identity(rows[0]) != source['request_sha256']:
        raise RecoveryRequired('iteration2_recovery_original_request_changed')
    row = rows[0]; purpose = policy.operation(p['scope_id'], 'check')
    if (row['status'] != 'failed' or row['provider'] != 'anthropic' or row['model'] != 'claude-sonnet-5'
            or row['purpose'] != purpose or row['key'] != source['request_key']
            or row['code_sha'] != source['run']['head_sha'] or row['body_sha256'] != source['body_sha256']
            or row['pair_contract_sha256'] != source['contract_sha256']
            or row['completion_transport'] != original.LEGACY_VERSION
            or row['charged_microusd'] != source['charged_microusd'] or row['charged_microusd'] <= 0
            or len([r for r in ledger['requests'] if r.get('purpose') == purpose]) != 1
            or (state/'cache'/(row['key']+'.json')).exists()):
        raise RecoveryRequired('iteration2_recovery_original_paid_identity')
    retained = {}
    for folder, name in (('receipts', 'receipt'), ('diagnostics', 'diagnostic')):
        raw = (state/folder/(row['id']+'.json')).read_bytes()
        if existing.sha(raw) != source[name+'_sha256']:
            raise RecoveryRequired('iteration2_recovery_original_evidence_changed')
        retained[name] = json.loads(raw)
    receipt = retained['receipt']; diagnostic = retained['diagnostic']
    if (identity(diagnostic) != source['diagnostic_identity']
            or receipt.get('diagnostic_sha256') != source['diagnostic_identity']
            or receipt.get('diagnostic_path') != 'diagnostics/'+row['id']+'.json'
            or receipt.get('request_id') != row['id'] or receipt.get('key') != row['key']
            or receipt.get('status') != 'failed' or receipt.get('http_status') != 200
            or receipt.get('provider_stop_reason') != 'end_turn' or receipt.get('returned_model') != row['model']
            or receipt.get('usage') != row['usage'] or receipt.get('charged_microusd') != row['charged_microusd']
            or receipt.get('semantic_diagnostic') != {'code': ERROR}
            or diagnostic.get('request_id') != row['id'] or diagnostic.get('body_sha256') != row['body_sha256']
            or diagnostic.get('provider') != 'anthropic' or diagnostic.get('returned_model') != row['model']
            or diagnostic.get('http_status') != 200 or diagnostic.get('completion_status') != 'end_turn'
            or diagnostic.get('final_answer_captured') is not True or diagnostic.get('final_answer_complete') is not True
            or diagnostic.get('final_answer_redacted') is not False or diagnostic.get('accepted_cache') is not False
            or diagnostic.get('reported_usage') != row['usage']
            or diagnostic.get('validation', {}).get('semantic_diagnostic') != {'code': ERROR}):
        raise RecoveryRequired('iteration2_recovery_complete_response_provenance')
    text = diagnostic.get('final_answer_text')
    if (not isinstance(text, str) or identity(text) != source['text_sha256']
            or existing.sha(text.encode('utf8')) != source['raw_text_sha256']
            or diagnostic.get('final_answer_sha256') != source['text_sha256']
            or diagnostic.get('retained_text_sha256') != source['text_sha256']
            or diagnostic.get('final_answer_bytes') != len(text.encode('utf8'))):
        raise RecoveryRequired('iteration2_recovery_exact_complete_text')
    prepared = packet if packet is not None else source_packet(state)
    config, scope, contract, body, validate, report, selection = prepared
    evidence = json.loads(body['messages'][0]['content'])
    if (identity(contract) != source['contract_sha256'] or identity(body) != source['body_sha256']
            or identity(evidence) != source['input_sha256'] or identity(scope_inputs(scope)) != source['source_sha256']
            or contract['graph_sha256'] != source['graph_sha256'] or identity(selection) != source['selection_sha256']
            or identity(validation_contract(evidence, contract)) != p['validation_contract_sha256']):
        raise RecoveryRequired('iteration2_recovery_original_packet_changed')
    bound = [e for e in ledger['events'] if e.get('authority') == policy.VERSION and e.get('purpose') == purpose]
    if bound != [policy.packet_event(purpose, body, contract, identity(evidence))]:
        raise RecoveryRequired('iteration2_recovery_original_operation_changed')
    value = recover_text(text, evidence, validate)
    if identity(value) != p['result_sha256']:
        raise RecoveryRequired('iteration2_recovery_result_identity')
    cache_path, receipt_path = paths(state, p)
    original_checkpoint = _source_checkpoint(state, ledger, source, cache_path, receipt_path, source_checkpoint)
    cache = {'version': VERSION, 'recovery_key': recovery_key(p), 'source_request_id': row['id'],
        'source_request_key': row['key'], 'source_body_sha256': source['body_sha256'],
        'source_diagnostic_sha256': source['diagnostic_sha256'], 'input_sha256': source['input_sha256'],
        'validation_contract_sha256': p['validation_contract_sha256'], 'value': value}
    derived_receipt = {'version': VERSION, 'event': expected_event, 'source': source,
        'original_checkpoint': original_checkpoint, 'original_status': 'failed',
        'original_charged_microusd': row['charged_microusd'], 'original_evidence_preserved': True,
        'scientific_fields_changed': False, 'selection_lineage':
            'Original documentary bundle identity restored; exact original graph, composer and complete scientific selection verified.',
        'new_metered_attempts': 0, 'new_native_count_calls': 0,
        'new_microusd': 0, 'paid_requests_replayed': 0}
    for path, expected in ((cache_path, cache), (receipt_path, derived_receipt)):
        if path.exists() and path.read_bytes() != encoded(expected)+b'\n':
            raise RecoveryRequired('iteration2_recovery_derived_artifact_conflict')
    return {'ledger': ledger, 'event': expected_event, 'cache': cache, 'receipt': derived_receipt,
        'cache_path': cache_path, 'receipt_path': receipt_path, 'value': value, 'packet': prepared,
        'cache_hit': cache_path.exists(), 'source_checkpoint': original_checkpoint}


def source_snapshot(state, api_call):
    """Read an authenticated historical artifact, never replace the active owner."""
    source = plan()['source']; expected = source['artifact']
    artifact = json.loads(api_call('actions/artifacts/'+str(expected['id'])))
    if (any(artifact.get(k) != v for k, v in expected.items()) or artifact.get('expired') is not False
            or artifact.get('workflow_run', {}).get('id') != source['run']['id']
            or artifact.get('workflow_run', {}).get('head_sha') != source['run']['head_sha']):
        raise RecoveryRequired('iteration2_recovery_source_artifact_identity')
    raw = api_call('actions/artifacts/'+str(expected['id'])+'/zip')
    if (not isinstance(raw, bytes) or len(raw) > existing.STATE_LIMIT
            or 'sha256:'+existing.sha(raw) != expected['digest']):
        raise RecoveryRequired('iteration2_recovery_source_artifact_digest')
    parent = Path(state).resolve().parent
    with tempfile.TemporaryDirectory(prefix='.i2-recovery-source-', dir=parent) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(parent) or directory == parent:
            raise RecoveryRequired('iteration2_recovery_temporary_snapshot_boundary')
        # Existing extraction bounds, member allowlist, content hashes and owner
        # validation apply to this read snapshot. Its ledger never becomes the
        # current state and cannot reserve or dispatch any request.
        existing.unpack_state(raw, directory)
        checkpoint_raw = (directory/'checkpoint.json').read_bytes()
        if existing.sha(checkpoint_raw) != source['checkpoint_sha256']:
            raise RecoveryRequired('iteration2_recovery_source_checkpoint_identity')
        return json.loads(checkpoint_raw)


def prepare_plan(state, api_call):
    expected = plan()['source']['run']
    run = json.loads(api_call('actions/runs/'+str(expected['id'])))
    if any(run.get(k) != v for k, v in expected.items()):
        raise RecoveryRequired('iteration2_recovery_source_run_not_terminal')
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))['workflow_runs']
    if any(str(r['id']) != os.environ.get('GITHUB_RUN_ID') for r in active):
        raise RecoveryRequired('iteration2_recovery_another_owner_active')
    _, receipt_path = paths(state)
    snapshot = None if receipt_path.exists() else source_snapshot(state, api_call)
    return _derive(state, source_checkpoint=snapshot)


def _result(built):
    p = plan()
    return {'version': VERSION, 'operation': VERSION, 'scope_id': p['scope_id'], 'value': built['value'],
        'request_id': p['source']['request_id'], 'original_request_status': 'failed',
        'original_charged_microusd': p['source']['charged_microusd'], 'recovery_key': recovery_key(p),
        'validation_contract_sha256': p['validation_contract_sha256'], 'source_body_sha256': p['source']['body_sha256'],
        'cache_hit': built['cache_hit'], 'provider_acceptance': 'complete_independent_result_revalidated_from_retained_response',
        'new_metered_attempts': 0, 'new_native_count_calls': 0, 'new_microusd': 0, 'automatic_retries': 0}


def recover(state, api_call, crash=lambda point: None):
    state = Path(state); prepared = prepare_plan(state, api_call)
    ledger = existing.ExperimentLedger(state/'ledger.json')
    with ledger.locked():
        # Original packet reconstruction opens its own ledger. Build outside the
        # lock, then verify every original file again inside this lock.
        built = _derive(state, ledger.read(), prepared['packet'], prepared['source_checkpoint'])
        try:
            for name in ('cache', 'receipt'):
                path = built[name+'_path']
                if not path.exists():
                    atomic_json(path, built[name])
                crash('after_'+name)
            if built['event'] not in built['ledger']['events']:
                built['ledger']['events'].append(built['event']); atomic_json(ledger.path, built['ledger'])
            crash('after_event'); crash('before_checkpoint')
        finally:
            existing.checkpoint(state)
        crash('after_checkpoint')
    return _result(built)


def read_recovered(state):
    state = Path(state)
    packet = source_packet(state)
    ledger = existing.ExperimentLedger(state/'ledger.json')
    with ledger.locked():
        built = _derive(state, ledger.read(), packet)
        if (built['event'] not in built['ledger']['events']
                or not built['cache_path'].exists() or not built['receipt_path'].exists()):
            raise RecoveryRequired('iteration2_recovery_complete_lineage_required')
        return _result(built)


def run(args):
    existing.trusted_environment()
    if (json.loads(os.environ['CONTEXTUAL_CHECK']) != SELECTOR
            or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT'))):
        raise ConfigurationFailure('iteration2_recovery_exact_selector')
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy()); recover(args.state, existing.api)
    result = read_recovered(args.state)
    record = {'version': VERSION, 'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
        'code_sha': os.environ['GITHUB_SHA'], 'recovery_key': recovery_key(),
        'source_request_id': plan()['source']['request_id'], 'maximum_new_microusd': 0,
        'maximum_new_metered_attempts': 0, 'maximum_new_native_counts': 0,
        'ledger_sha256': existing.sha((args.state/'ledger.json').read_bytes())}
    if args.action == 'prepare':
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=none\n')
        atomic_json(args.reservation, record)
        return
    if json.loads(args.reservation.read_bytes()) != record:
        raise RecoveryRequired('iteration2_recovery_prepared_identity_changed')
    atomic_json(args.result, result | {'validation_run_id': os.environ['GITHUB_RUN_ID'],
        'validation_code_sha': os.environ['GITHUB_SHA']})
    existing.checkpoint(args.state)
