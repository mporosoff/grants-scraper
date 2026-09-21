"""Zero-provider, exact-response recovery after a serialization-only failure.

The original paid row remains failed. A separate validation identity, receipt
and derived cache record the complete independent result without a new answer.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

from tools import team_recommender_executor as existing
from tools import contextual_team_completion_check as original
from tools import contextual_team_completion_policy as budget
from tools import contextual_team_retained_rows as retained
from tools.offline_spend import atomic_json, encoded, identity, ConfigurationFailure
from tools.contextual_team_executor import RecoveryRequired

VERSION = 'iteration1-canonical-claim-alias-recovery-v1'
SELECTOR = {'completion_iteration1': 'retained-response'}
LOCK_PATH = original.original.ROOT/'config/contextual_team/retained-check-recovery-v1.json'


def plan():
    p = json.loads(LOCK_PATH.read_bytes())
    if p['version'] != VERSION or p['authorization_id'] != existing.AUTHORIZATION_ID:
        raise ConfigurationFailure('retained_check_lock_identity')
    return p


def recovery_key(p=None):
    return identity(['exact-retained-check', p or plan()])


def event(p=None):
    p = p or plan(); s = p['source']
    return {'kind': 'exact_retained_response_revalidated', 'authority': VERSION,
        'recovery_key': recovery_key(p), 'source_request_id': s['request_id'],
        'source_run': s['run']['id'], 'source_checkpoint_sha256': s['checkpoint_sha256'],
        'source_receipt_sha256': s['receipt_sha256'],
        'source_diagnostic_sha256': s['diagnostic_sha256'],
        'source_response_text_sha256': s['text_sha256'],
        'original_status': 'failed', 'validation_contract_sha256': p['validation_contract_sha256'],
        'result_sha256': p['result_sha256'], 'metered_attempts': 0,
        'native_count_calls': 0, 'new_microusd': 0, 'paid_requests_replayed': 0}


def paths(state, p=None):
    p = p or plan(); state = Path(state)
    return state/'cache'/(recovery_key(p)+'.json'), state/'receipts'/(identity(event(p))[:32]+'.json')


def _derive(state, ledger_state=None, packet=None):
    """Reconstruct and verify EVERY original byte before accepting a recovery."""
    state = Path(state); p = plan(); s = p['source']; expected_event = event(p)
    ledger = ledger_state if ledger_state is not None else existing.ExperimentLedger(state/'ledger.json').read()
    budget.history(ledger)
    found = [e for e in ledger['events'] if e.get('authority') == VERSION]
    if found not in ([], [expected_event]):
        raise RecoveryRequired('retained_check_conflicting_recovery_event')
    original_ledger = deepcopy(ledger)
    if found:
        original_ledger['events'].remove(expected_event)
    # Exact canonical serialization was verified against the original artifact.
    # Removing our one event only in memory never rewrites original paid history.
    if (identity(original_ledger['requests']) != s['requests_sha256']
        or existing.sha(encoded(original_ledger)+b'\n') != s['ledger_sha256']):
        raise RecoveryRequired('retained_check_original_ledger_changed')
    matches = [r for r in original_ledger['requests'] if r['id'] == s['request_id']]
    if len(matches) != 1 or identity(matches[0]) != s['request_sha256']:
        raise RecoveryRequired('retained_check_original_request_changed')
    row = matches[0]
    if (row['status'] != 'failed' or row['provider'] != 'anthropic'
        or row['model'] != 'claude-sonnet-5' or row['purpose'] != original.STRICT
        or row['code_sha'] != s['run']['head_sha']
        or row['body_sha256'] != s['body_sha256']
        or row['pair_contract_sha256'] != s['contract_sha256']):
        raise RecoveryRequired('retained_check_original_paid_identity')
    source_receipt = json.loads((state/'receipts'/(s['request_id']+'.json')).read_bytes())
    diagnostic = json.loads((state/'diagnostics'/(s['request_id']+'.json')).read_bytes())
    for folder, field in (('receipts', 'receipt_sha256'), ('diagnostics', 'diagnostic_sha256')):
        if existing.sha((state/folder/(s['request_id']+'.json')).read_bytes()) != s[field]:
            raise RecoveryRequired('retained_check_original_evidence_changed')
    if (identity(diagnostic) != s['diagnostic_identity']
        or source_receipt.get('diagnostic_sha256') != s['diagnostic_identity']
        or source_receipt.get('diagnostic_path') != 'diagnostics/'+s['request_id']+'.json'
        or source_receipt.get('request_id') != row['id'] or source_receipt.get('key') != row['key']
        or source_receipt.get('status') != 'failed' or source_receipt.get('http_status') != 200
        or source_receipt.get('provider_stop_reason') != 'end_turn'
        or source_receipt.get('returned_model') != row['model']
        or source_receipt.get('usage') != row['usage']
        or source_receipt.get('charged_microusd') != row['charged_microusd']
        or source_receipt.get('semantic_diagnostic') != {'code': 'answer_claim_owner_or_revision'}
        or diagnostic.get('request_id') != row['id'] or diagnostic.get('body_sha256') != row['body_sha256']
        or diagnostic.get('provider') != 'anthropic' or diagnostic.get('http_status') != 200
        or diagnostic.get('completion_status') != 'end_turn' or diagnostic.get('returned_model') != row['model']
        or diagnostic.get('final_answer_captured') is not True
        or diagnostic.get('final_answer_complete') is not True
        or diagnostic.get('final_answer_redacted') is not False
        or diagnostic.get('reported_usage') != row['usage']):
        raise RecoveryRequired('retained_check_complete_response_provenance')
    text = diagnostic.get('final_answer_text')
    if (not isinstance(text, str) or identity(text) != s['text_sha256']
        or diagnostic.get('final_answer_sha256') != s['text_sha256']
        or diagnostic.get('retained_text_sha256') != s['text_sha256']
        or diagnostic.get('final_answer_bytes') != len(text.encode('utf8'))):
        raise RecoveryRequired('retained_check_exact_complete_text')
    data, source_contract, source_body = packet if packet is not None else original.packet(state, original.STRICT)
    if (identity(data) != s['input_sha256'] or identity(source_contract) != s['contract_sha256']
        or identity(source_body) != s['body_sha256']
        or retained.VERSION != VERSION or identity(retained.contract(data)) != p['validation_contract_sha256']):
        raise ConfigurationFailure('retained_check_validation_identity')
    value = retained.recover(text, data)
    if identity(value) != p['result_sha256']:
        raise RecoveryRequired('retained_check_result_identity')
    key = recovery_key(p)
    cache = {'version': VERSION, 'recovery_key': key,
        'validation_contract_sha256': p['validation_contract_sha256'],
        'source_request_id': row['id'], 'source_request_key': row['key'],
        'source_body_sha256': s['body_sha256'], 'source_diagnostic_sha256': s['diagnostic_sha256'],
        'source_response_text_sha256': s['text_sha256'], 'input_sha256': s['input_sha256'], 'value': value}
    receipt = {'version': VERSION, 'kind': 'retained_complete_response_revalidation',
        'recovery_key': key, 'authenticated_source_run': s['run'],
        'source': s, 'validation_contract_sha256': p['validation_contract_sha256'],
        'result_sha256': p['result_sha256'], 'original_status': row['status'],
        'original_charged_microusd': row['charged_microusd'],
        'original_evidence_preserved': True, 'scientific_fields_changed': False,
        'metered_attempts': 0, 'native_count_calls': 0, 'new_microusd': 0,
        'paid_requests_replayed': 0}
    cache_path, receipt_path = paths(state, p)
    for path, expected in ((cache_path, cache), (receipt_path, receipt)):
        if path.exists() and path.read_bytes() != encoded(expected)+b'\n':
            raise RecoveryRequired('retained_check_derived_artifact_conflict')
    checkpoint = json.loads((state/'checkpoint.json').read_bytes())
    counts = checkpoint['phase2_token_preflight']
    if identity(counts['rows']) != s['native_counts_sha256']:
        raise RecoveryRequired('retained_check_native_count_history_changed')
    ignored = {cache_path, receipt_path}
    source_files = {f.relative_to(state).as_posix(): existing.sha(f.read_bytes())
        for f in state.rglob('*.json') if f.name != 'checkpoint.json' and f not in ignored}
    source_files['ledger.json'] = s['ledger_sha256']
    original_checkpoint = {'authorization_id': existing.AUTHORIZATION_ID,
        'run_id': str(s['run']['id']), 'attempt': str(s['run']['run_attempt']),
        'code_sha': s['run']['head_sha'], 'files': source_files, 'phase2_token_preflight': counts}
    if existing.sha(encoded(original_checkpoint)+b'\n') != s['checkpoint_sha256']:
        raise RecoveryRequired('retained_check_original_checkpoint_changed')
    return {'ledger': ledger, 'event': expected_event, 'cache': cache, 'receipt': receipt,
        'cache_path': cache_path, 'receipt_path': receipt_path, 'value': value,
        'original_charge': row['charged_microusd'], 'cache_hit': cache_path.exists(),
        'packet': (data, source_contract, source_body)}


def prepare_plan(state, api_call):
    """Read-only exact source validation and authenticated terminal-run proof."""
    p = plan(); source_run = p['source']['run']
    run = json.loads(api_call('actions/runs/'+str(source_run['id'])))
    if any(run.get(k) != v for k, v in source_run.items()):
        raise RecoveryRequired('retained_check_source_run_not_terminal')
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))['workflow_runs']
    if any(str(r['id']) != os.environ['GITHUB_RUN_ID'] for r in active):
        raise RecoveryRequired('retained_check_another_owner_active')
    return _derive(state)


def recover(state, api_call, crash=lambda point: None):
    """Persist only exact derived artifacts; partial writes safely resume."""
    state = Path(state); prepared = prepare_plan(state, api_call)
    ledger = existing.ExperimentLedger(state/'ledger.json')
    with ledger.locked():
        # Legacy packet readers instantiate their own ledger. Reuse the pinned
        # packet assembled before this lock; the full original-file hash check
        # below still detects any intervening cache/evidence change.
        built = _derive(state, ledger.read(), prepared['packet'])
        try:
            for name in ('cache', 'receipt'):
                target = built[name+'_path']
                if not target.exists():
                    atomic_json(target, built[name])
                crash('after_'+name)
            if built['event'] not in built['ledger']['events']:
                built['ledger']['events'].append(built['event'])
                atomic_json(ledger.path, built['ledger'])
            crash('after_event'); crash('before_checkpoint')
        finally:
            existing.checkpoint(state)
        crash('after_checkpoint')
    p = plan()
    return {'version': VERSION, 'operation': 'retained-response', 'value': built['value'],
        'request_id': p['source']['request_id'], 'original_request_status': 'failed',
        'original_charged_microusd': built['original_charge'],
        'recovery_key': recovery_key(p), 'validation_contract_sha256': p['validation_contract_sha256'],
        'source_body_sha256': p['source']['body_sha256'], 'cache_hit': built['cache_hit'],
        'provider_acceptance': 'complete_independent_result_revalidated_from_retained_response',
        'new_metered_attempts': 0, 'new_native_count_calls': 0, 'new_microusd': 0,
        'automatic_retries': 0}


def run(args):
    existing.trusted_environment()
    if (json.loads(os.environ['CONTEXTUAL_CHECK']) != SELECTOR
        or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT'))):
        raise ConfigurationFailure('retained_check_exact_selector')
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy())
        recover(args.state, existing.api)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=none\n')
        atomic_json(args.reservation, {'authorization_id': existing.AUTHORIZATION_ID,
            'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'code_sha': os.environ['GITHUB_SHA'], 'operation': VERSION,
            'recovery_key': recovery_key(), 'source_request_id': plan()['source']['request_id'],
            'prior_ledger_sha256': existing.sha((args.state/'ledger.json').read_bytes()),
            'maximum_new_microusd': 0, 'maximum_new_attempts': 0, 'native_count_calls': 0})
        return
    result = None
    try:
        # The prepare phase already authenticated and saved this zero-cost
        # result. Revalidate all original evidence without needing credentials.
        built = _derive(args.state)
        if (built['event'] not in built['ledger']['events']
            or not built['cache_path'].exists() or not built['receipt_path'].exists()):
            raise RecoveryRequired('retained_check_prepared_artifacts_required')
        p = plan()
        result = {'version': VERSION, 'operation': 'retained-response', 'value': built['value'],
            'request_id': p['source']['request_id'], 'original_request_status': 'failed',
            'original_charged_microusd': built['original_charge'],
            'recovery_key': recovery_key(p), 'validation_contract_sha256': p['validation_contract_sha256'],
            'validation_code_sha': os.environ['GITHUB_SHA'], 'validation_run_id': os.environ['GITHUB_RUN_ID'],
            'source_body_sha256': p['source']['body_sha256'], 'cache_hit': True,
            'provider_acceptance': 'complete_independent_result_revalidated_from_retained_response',
            'new_metered_attempts': 0, 'new_native_count_calls': 0, 'new_microusd': 0,
            'automatic_retries': 0}
    finally:
        existing.checkpoint(args.state)
        atomic_json(args.result, result or {'version': VERSION, 'operation': 'retained-response',
            'status': 'incomplete', 'new_metered_attempts': 0, 'new_native_count_calls': 0, 'new_microusd': 0})
