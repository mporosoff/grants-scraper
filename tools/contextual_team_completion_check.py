"""Iteration 1 only: complete blinded check, with one predeclared fallback."""
import json
import math
import os

from tools import team_recommender_executor as existing
from tools import contextual_team_compact_check as original
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_shared_rows as rows
from tools import contextual_team_completion_policy as policy
from tools.contextual_team_luna_repair import RepairRunner
from tools.contextual_team_executor import RecoveryRequired
from tools.contextual_team_token_preflight import Counter
from tools.offline_spend import identity, atomic_json, ConfigurationFailure, Deferred

STRICT = 'cb-fc-shared-check'
FALLBACK = 'cb-fc-json-fallback'
TRANSPORTS = {STRICT: rows.STRICT_VERSION, FALLBACK: rows.TEXT_VERSION}
FALLBACK_AUTHORITY = 'iteration1-shared-grammar-fallback-20260921-v1'
SELECTORS = {'strict': STRICT, 'json-fallback': FALLBACK}
LOCK_PATH = original.ROOT/'config/contextual_team/completion-check-v1.json'


def plan():
    value = json.loads(LOCK_PATH.read_bytes())
    if value['version'] != policy.VERSION or set(value['operations']) != set(TRANSPORTS):
        raise ConfigurationFailure('completion_check_lock_identity')
    return value


def packet(state, purpose):
    data, _, _ = original.packet(state)  # Exact saved Luna identity, never sent.
    contract, body = rows.body(data, transport=TRANSPORTS[purpose])
    lock = plan()['operations'][purpose]
    if (identity(contract) != lock['contract_sha256'] or identity(body) != lock['body_sha256']
            or identity(data) != plan()['input_sha256']):
        raise ConfigurationFailure('completion_check_frozen_packet')
    return data, contract, body


def fallback_evidence(state_path, state):
    """Only an explicit grammar rejection qualifies; silence/refusal never does."""
    claimed = [r for r in state['requests'] if r.get('purpose') == STRICT]
    if len(claimed) != 1:
        raise RecoveryRequired('completion_fallback_requires_one_strict_failure')
    row = claimed[0]
    expected = plan()['operations'][STRICT]
    rid = row['id']
    receipt_raw = (state_path/'receipts'/(rid+'.json')).read_bytes()
    diagnostic_raw = (state_path/'diagnostics'/(rid+'.json')).read_bytes()
    receipt = json.loads(receipt_raw); diagnostic = json.loads(diagnostic_raw)
    if (row['body_sha256'] != expected['body_sha256'] or row['status'] != 'reserved_unknown'
            or row['charged_microusd'] != expected['reserved_microusd'] or row['usage'] is not None
            or receipt.get('request_id') != rid or receipt.get('body_sha256') != row['body_sha256']
            or receipt.get('code_sha') != row['code_sha'] or receipt.get('key') != row['key']
            or receipt.get('status') != 'reserved_unknown' or receipt.get('http_status') != 400
            or receipt.get('diagnostic_path') != 'diagnostics/'+rid+'.json'
            or receipt.get('diagnostic_sha256') != identity(diagnostic)
            or diagnostic.get('request_id') != rid or diagnostic.get('body_sha256') != row['body_sha256']
            or diagnostic.get('provider') != 'anthropic' or diagnostic.get('http_status') != 400
            or diagnostic.get('final_answer_captured') is not False
            or 'reported_usage' in diagnostic or 'usage' in receipt
            or diagnostic.get('error', {}).get('type') != 'invalid_request_error'
            or 'compiled grammar is too large' not in diagnostic.get('error', {}).get('message', '').lower()):
        raise RecoveryRequired('completion_fallback_not_terminal_grammar_rejection')
    return row, {'kind': 'exact_terminal_http_error_quarantined', 'authority': FALLBACK_AUTHORITY,
        'operation': FALLBACK, 'request_id': rid, 'body_sha256': row['body_sha256'],
        'held_microusd': row['charged_microusd'], 'usage': 'unknown',
        'replay': 'permanently_closed', 'allowed_operations': [FALLBACK],
        'receipt_file_sha256': existing.sha(receipt_raw),
        'diagnostic_file_sha256': existing.sha(diagnostic_raw),
        'diagnostic_identity': identity(diagnostic), 'completion_lock_sha256': identity(plan())}


def _terminal_run(value, row):
    if (not isinstance(value, dict) or type(value.get('id')) is not int
            or value['id'] <= 0 or type(value.get('run_attempt')) is not int or value['run_attempt'] <= 0):
        raise RecoveryRequired('completion_strict_run_not_terminal')
    expected = {'id': value['id'], 'run_attempt': value['run_attempt'],
        'status': 'completed', 'conclusion': 'failure', 'head_branch': 'main',
        'event': 'workflow_dispatch', 'path': existing.WORKFLOW, 'head_sha': row['code_sha']}
    if value != expected:
        raise RecoveryRequired('completion_strict_run_not_terminal')
    return expected


def installed_fallback(state_path, state):
    """The ledger binds the authenticated run; its exact receipt is mandatory."""
    row, base = fallback_evidence(state_path, state)
    saved = [e for e in state['events'] if e.get('operation') == FALLBACK
             and e.get('authority') == FALLBACK_AUTHORITY]
    if len(saved) != 1:
        raise RecoveryRequired('completion_fallback_authority_conflict')
    run = _terminal_run(saved[0].get('authenticated_run'), row)
    event = base | {'authenticated_run': run}
    if saved != [event]:
        raise RecoveryRequired('completion_fallback_authority_conflict')
    target = state_path/'receipts'/(identity(base)[:32]+'.json')
    try:
        receipt = json.loads(target.read_bytes())
    except (OSError, ValueError) as error:
        raise RecoveryRequired('completion_fallback_receipt_unavailable') from error
    if receipt != {'event': event, 'authenticated_run': run}:
        raise RecoveryRequired('completion_fallback_receipt_conflict')
    return event


def install_fallback(state_path, restored_checkpoint, api_call):
    ledger = existing.ExperimentLedger(state_path/'ledger.json')
    state = ledger.read(); row, base = fallback_evidence(state_path, state)
    target = state_path/'receipts'/(identity(base)[:32]+'.json')
    if any(e.get('operation') == FALLBACK and e.get('authority') == FALLBACK_AUTHORITY for e in state['events']):
        installed_fallback(state_path, state)
        return
    run_id = restored_checkpoint['run_id']
    run = json.loads(api_call('actions/runs/'+str(run_id)))
    expected = {'id': int(run_id), 'run_attempt': int(restored_checkpoint['attempt']),
        'status': 'completed', 'conclusion': 'failure', 'head_branch': 'main',
        'event': 'workflow_dispatch', 'path': existing.WORKFLOW, 'head_sha': row['code_sha']}
    if (restored_checkpoint['code_sha'] != row['code_sha']
            or any(run.get(k) != v for k, v in expected.items())):
        raise RecoveryRequired('completion_strict_run_not_terminal')
    _terminal_run(expected, row)
    event = base | {'authenticated_run': expected}
    authority = {'event': event, 'authenticated_run': expected}
    with ledger.locked():
        state = ledger.read(); policy.history(state)
        _, checked = fallback_evidence(state_path, state)
        if checked != base:
            raise RecoveryRequired('completion_fallback_evidence_changed')
        if any(e.get('operation') == FALLBACK and e.get('authority') == FALLBACK_AUTHORITY for e in state['events']):
            raise RecoveryRequired('completion_fallback_concurrent_authority')
        if target.exists() and json.loads(target.read_bytes()) != authority:
            raise RecoveryRequired('completion_fallback_receipt_conflict')
        atomic_json(target, authority)
        state['events'].append(event); atomic_json(ledger.path, state)
    existing.checkpoint(state_path)


def allowed_uncertainty(state):
    # Each historical hold remains charged and permanently closed by exact authority.
    allowed = {r['id'] for r in state['requests'][:687] if r['status'] == 'reserved_unknown'}
    events = [e for e in state['events'] if e.get('authority') == FALLBACK_AUTHORITY and e.get('operation') == FALLBACK]
    if len(events) > 1:
        raise ConfigurationFailure('completion_duplicate_fallback_authority')
    if events:
        event = events[0]
        strict = [r for r in state['requests'][687:] if r.get('purpose') == STRICT]
        if (len(strict) != 1 or event.get('request_id') != strict[0]['id']
                or event.get('body_sha256') != plan()['operations'][STRICT]['body_sha256']
                or event.get('held_microusd') != strict[0]['charged_microusd']
                or event.get('completion_lock_sha256') != identity(plan())
                or event.get('replay') != 'permanently_closed' or event.get('allowed_operations') != [FALLBACK]):
            raise ConfigurationFailure('completion_fallback_disposition_identity')
        _terminal_run(event.get('authenticated_run'), strict[0])
        allowed.add(event['request_id'])
    return allowed


def available(state, purpose):
    policy.history(state)
    if any(r['status'] == 'reserved_unknown' and r['id'] not in allowed_uncertainty(state) for r in state['requests']):
        raise RecoveryRequired('completion_other_uncertainty')
    if any(r.get('purpose') == purpose for r in state['requests']):
        raise RecoveryRequired('completion_claimed_no_rekey')
    if purpose == STRICT and any(r.get('purpose') == FALLBACK for r in state['requests']):
        raise RecoveryRequired('completion_strict_already_closed')
    if purpose == FALLBACK and not any(e.get('operation') == FALLBACK and e.get('authority') == FALLBACK_AUTHORITY for e in state['events']):
        raise RecoveryRequired('completion_fallback_not_authorized_by_evidence')
    policy.check_pool(state, amount=plan()['operations'][purpose]['reserved_microusd'], attempts=1)


def check_reservation(state, provider, metadata, amount, input_tokens, output_tokens):
    purpose = metadata.get('purpose')
    if purpose not in TRANSPORTS:
        raise ConfigurationFailure('completion_iteration1_only')
    op = plan()['operations'][purpose]
    repair_of = policy.FAILED if purpose == STRICT else next((e['request_id'] for e in state['events']
        if e.get('operation') == FALLBACK and e.get('authority') == FALLBACK_AUTHORITY), None)
    expected = {'completion_authority': policy.VERSION, 'completion_transport': TRANSPORTS[purpose],
        'completion_lock_sha256': identity(plan()), 'body_sha256': op['body_sha256'],
        'pair_contract_sha256': op['contract_sha256'], 'repair_of': repair_of,
        'packet_sha256': original.prior.plan()['source_inputs_sha256']}
    if (provider != 'anthropic' or any(metadata.get(k) != v for k, v in expected.items())
            or (amount, input_tokens, output_tokens) != (op['reserved_microusd'], op['reserved_input_tokens'], 12000)):
        raise ConfigurationFailure('completion_exact_reservation')
    available(state, purpose)


class CompletionRunner(RepairRunner):
    def request_provider(self, purpose, body):
        if purpose not in TRANSPORTS or body['model'] != 'claude-sonnet-5':
            raise ConfigurationFailure('completion_only_fixed_checker')
        return 'anthropic'

    def has_unknown_request(self):
        try:
            state = self.ledger.read(); policy.history(state)
            return any(r['status'] == 'reserved_unknown' and r['id'] not in allowed_uncertainty(state) for r in state['requests'])
        except (Deferred, ConfigurationFailure, RecoveryRequired):
            return True

    def reservation_cost(self, purpose, body, metadata):
        available(self.ledger.read(), purpose)
        op = plan()['operations'][purpose]
        if identity(body) != op['body_sha256']:
            raise ConfigurationFailure('completion_count_packet_identity')
        native = Counter(self.state).count({'id': purpose+':complete', 'body': body})
        if math.ceil(native*1.2)+1024 > op['reserved_input_tokens']:
            raise Deferred('completion_complete_input_exceeds_reservation')
        return op['reserved_input_tokens'], op['reserved_microusd'], {}

    def perform(self, purpose):
        data, contract, body = packet(self.state, purpose)
        state = self.ledger.read()
        if purpose == FALLBACK:
            event = installed_fallback(self.state, state)
        repair_of = policy.FAILED if purpose == STRICT else event['request_id']
        value = self.request(purpose, [policy.VERSION, purpose, identity(contract), identity(data)], body,
            lambda v, cached: pairs.validate_cached(v, data, judge=True) if cached else rows.parse(v, data),
            ceiling=plan()['operations'][purpose]['reserved_input_tokens'], repair_metadata={
                'completion_authority': policy.VERSION, 'completion_transport': TRANSPORTS[purpose],
                'completion_lock_sha256': identity(plan()), 'repair_of': repair_of,
                'pair_contract_sha256': identity(contract), 'packet_sha256': original.prior.plan()['source_inputs_sha256']})
        return {'version': policy.VERSION, 'operation': purpose, 'transport': TRANSPORTS[purpose],
            'value': value, 'request_id': self.used[-1]['request_id'], 'cache_hit': self.used[-1]['cache_hit'],
            'body_sha256': identity(body), 'contract_sha256': identity(contract),
            'provider_acceptance': 'complete_valid_independent_result', 'automatic_retries': 0}


def run(args):
    existing.trusted_environment()
    requested = json.loads(os.environ['CONTEXTUAL_CHECK'])
    if (set(requested) != {'completion_iteration1'} or requested['completion_iteration1'] not in SELECTORS
            or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT'))):
        raise ConfigurationFailure('completion_exact_iteration1_selector')
    purpose = SELECTORS[requested['completion_iteration1']]
    if args.action == 'prepare':
        existing.restore(args.state, existing.policy()); packet(args.state, purpose)
        restored = json.loads((args.state/'checkpoint.json').read_bytes())
        policy.install_authority(args.state, existing.api)
        if purpose == FALLBACK:
            install_fallback(args.state, restored, existing.api)
        ledger = existing.ExperimentLedger(args.state/'ledger.json')
        claimed = [r for r in ledger.read()['requests'] if r.get('purpose') == purpose]
        if not claimed:
            available(ledger.read(), purpose)
        elif len(claimed) != 1 or claimed[0]['status'] != 'valid':
            raise RecoveryRequired('completion_claimed_requires_recovery')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=anthropic\n')
        atomic_json(args.reservation, {'authorization_id': existing.AUTHORIZATION_ID,
            'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'code_sha': os.environ['GITHUB_SHA'], 'prior_ledger_sha256': existing.sha(ledger.path.read_bytes()),
            'operation': purpose, 'completion_authority': policy.VERSION,
            'completion_lock_sha256': identity(plan()), 'maximum_new_microusd': 200000,
            'maximum_new_attempts': 1, 'native_count_calls': 1,
            'preserved_microusd': 1267862, 'preserved_attempts': 2, 'completion_contingency_microusd': 5000000})
        return
    result = None
    try:
        result = CompletionRunner(args.state, {}).perform(purpose)
    finally:
        existing.checkpoint(args.state)
        atomic_json(args.result, result or {'version': policy.VERSION, 'operation': purpose,
            'status': 'incomplete', 'automatic_retries': 0})
