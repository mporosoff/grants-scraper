"""One separately authorized compact check; historical requests stay closed.

The allowance is a sublimit of the existing cloud ledger, not a new ledger.
No source, profile, assessment, service graph or production asset is written.
"""
import json
import os
from tools import team_recommender_executor as existing
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_luna_policy as prior
from tools.contextual_team_luna_repair import RepairRunner, locked_packets
from tools.contextual_team_executor import RecoveryRequired
from tools.contextual_team_policy import ROOT
from tools.offline_spend import identity, encoded, atomic_json, ConfigurationFailure, Deferred

VERSION = 'compact-check-continuation-20260919-v1'
PURPOSE = 'cb-cc-independent-check'
OLD_ID = 'd24a0654d72e486793519bead019b064'
PRIOR_ROWS = 'c12c5470aee336d41cf87d6bb4c96f97683f86c9649d3e0c07430677979127af'
OLD_RECEIPT = '6c237d6db06aeaf48df9896505c74e6836a7fea9d00116f6c3ed2727af993723'
OLD_DIAGNOSTIC = '30cd6ebf824c14c3267e0aea79071c056bb9f67ae5b5c24bd37c572dceea191c'
EVENT = {'kind': 'exact_terminal_http_error_quarantined', 'authority': VERSION,
    'request_id': OLD_ID, 'body_sha256': prior.plan()['operations']['check']['body_sha256'],
    'held_microusd': 205254, 'usage': 'unknown', 'replay': 'permanently_closed',
    'original_run': 34967272858, 'original_artifact': 10394804222,
    'original_receipt_sha256': OLD_RECEIPT, 'allowed_operations': [PURPOSE]}


def plan():
    p = json.loads((ROOT/'config/contextual_team/compact-check-continuation-v1.json').read_bytes())
    if p['version'] != VERSION or p['authorization_id'] != existing.AUTHORIZATION_ID:
        raise ConfigurationFailure('compact_continuation_identity')
    return p


def history(state, *, require_authority=True):
    rows = state['requests']
    if len(rows) < 685 or identity(rows[:685]) != PRIOR_ROWS or prior.EVENT not in state['events']:
        raise ConfigurationFailure('compact_original_history_changed')
    # The two exact old holds remain full charges, with no generalized waiver.
    if any(r['status'] == 'reserved_unknown' and r['id'] not in (prior.OLD_ID, OLD_ID) for r in rows):
        raise RecoveryRequired('compact_other_uncertain_request_requires_recovery')
    events = [e for e in state['events'] if e.get('authority') == VERSION]
    if events != [EVENT] and (require_authority or events):
        raise ConfigurationFailure('compact_exact_authority_missing_or_conflicting')
    if state.get('reservation_overrun') or state['blocked_providers']:
        raise Deferred('compact_existing_accounting_stop')


def install_authority(state_path, api_call):
    ledger = existing.ExperimentLedger(state_path/'ledger.json')
    history(ledger.read(), require_authority=False)
    for folder, expected in (('receipts', OLD_RECEIPT), ('diagnostics', OLD_DIAGNOSTIC)):
        if existing.sha((state_path/folder/(OLD_ID+'.json')).read_bytes()) != expected:
            raise ConfigurationFailure('compact_terminal_evidence_hash')
    run = json.loads(api_call('actions/runs/34967272858'))
    expected = {'id': 34967272858, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'failure',
        'path': existing.WORKFLOW, 'head_branch': 'main', 'event': 'workflow_dispatch',
        'head_sha': 'ef44f981803e2cde77a8d1a6659115e722c66e02'}
    if any(run.get(k) != v for k, v in expected.items()):
        raise RecoveryRequired('compact_original_run_not_terminal')
    # GitHub concurrency serializes owners; additionally refuse another active run.
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))['workflow_runs']
    if any(str(r['id']) != os.environ['GITHUB_RUN_ID'] for r in active):
        raise RecoveryRequired('compact_another_spending_owner_active')
    authority = EVENT | {'authenticated_run': expected, 'prior_rows_sha256': PRIOR_ROWS,
        'continuation_lock_sha256': identity(plan())}
    target = state_path/'receipts'/(identity(EVENT)[:32]+'.json')
    with ledger.locked():
        state = ledger.read(); history(state, require_authority=False)
        if target.exists() and json.loads(target.read_bytes()) != authority:
            raise RecoveryRequired('compact_authority_receipt_conflict')
        atomic_json(target, authority)
        if EVENT not in state['events']:
            state['events'].append(EVENT); atomic_json(ledger.path, state)
    existing.checkpoint(state_path)


def remaining_fits(state, amount):
    history(state)
    if any(r.get('purpose') == PURPOSE or r.get('compact_continuation') == VERSION for r in state['requests']):
        raise RecoveryRequired('compact_operation_claimed_no_rekey')
    if (amount > 500000 or amount <= 0
        or sum(r['charged_microusd'] for r in state['requests'])+amount > 10000000-1267862
        or len(state['requests'])+1 > 690-2):
        raise Deferred('compact_continuation_or_protected_reserve')


def check_reservation(state, provider, metadata, amount, input_tokens, output_tokens):
    p = plan()
    expected = {'purpose': PURPOSE, 'compact_continuation': VERSION,
        'continuation_lock_sha256': identity(p), 'body_sha256': p['body_sha256'],
        'pair_contract_sha256': p['contract_sha256'], 'repair_of': OLD_ID,
        'packet_sha256': prior.plan()['source_inputs_sha256']}
    if provider != 'anthropic' or any(metadata.get(k) != v for k, v in expected.items()):
        raise ConfigurationFailure('compact_exact_named_operation_required')
    if (input_tokens != p['reserved_input_tokens'] or output_tokens != 12000
        or amount != input_tokens*2+output_tokens*10 or amount != p['reserved_microusd']):
        raise ConfigurationFailure('compact_complete_conservative_reservation')
    remaining_fits(state, amount)


def packet(state):
    data, historical = locked_packets(state)
    assessment = RepairRunner(state, {}).accepted_assessment(data, historical['assessment'])
    p = plan()
    if identity(assessment) != p['retained_assessment_sha256']:
        raise RecoveryRequired('compact_saved_assessment_identity')
    contract, body = pairs.compact_check_body(data)
    bound = (len(encoded(body))*6+4)//5+1024  # one token/UTF-8 byte, plus 20% and framing
    if (identity(contract) != p['contract_sha256'] or identity(body) != p['body_sha256']
        or identity(data) != p['input_sha256'] or len(encoded(body)) != p['wire_bytes']
        or bound != p['reserved_input_tokens']):
        raise ConfigurationFailure('compact_frozen_complete_packet_changed')
    return data, contract, body


class CompactRunner(RepairRunner):
    def request_provider(self, purpose, body):
        if purpose != PURPOSE or body['model'] != 'claude-sonnet-5':
            raise ConfigurationFailure('compact_only_independent_check')
        return 'anthropic'

    def has_unknown_request(self):
        try:
            history(self.ledger.read())
        except (Deferred, ConfigurationFailure, RecoveryRequired):
            return True
        return False

    def reservation_cost(self, purpose, body, metadata):
        p = plan()
        if identity(body) != p['body_sha256']:
            raise ConfigurationFailure('compact_reservation_packet_changed')
        check_reservation(self.ledger.read(), 'anthropic', metadata | {'purpose': purpose,
            'body_sha256': identity(body)}, p['reserved_microusd'], p['reserved_input_tokens'], 12000)
        return p['reserved_input_tokens'], p['reserved_microusd'], {}

    def perform(self):
        data, contract, body = packet(self.state); p = plan()
        value = self.request(PURPOSE, [VERSION, PURPOSE, identity(contract), identity(data)], body,
            lambda v, cached: pairs.validate_cached(v, data, judge=True) if cached else
                pairs.parse(v, 'anthropic', data, judge=True), ceiling=p['reserved_input_tokens'],
            repair_metadata={'compact_continuation': VERSION, 'continuation_lock_sha256': identity(p),
                'repair_of': OLD_ID, 'pair_contract_sha256': identity(contract),
                'packet_sha256': prior.plan()['source_inputs_sha256']})
        return {'version': VERSION, 'operation': PURPOSE, 'value': value,
            'request_id': self.used[-1]['request_id'], 'cache_hit': self.used[-1]['cache_hit'],
            'body_sha256': identity(body), 'automatic_retries': 0}


def run(args):
    existing.trusted_environment()
    if (json.loads(os.environ['CONTEXTUAL_CHECK']) != {'compact_check_continuation': VERSION}
        or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB', 'PACKET_HASH', 'PACKET_COMMIT'))):
        raise ConfigurationFailure('compact_exact_manual_continuation')
    if args.action == 'prepare':
        ledger = existing.restore(args.state, existing.policy())
        packet(args.state)
        install_authority(args.state, existing.api)
        # A completed exact result may be retrieved, but a lost/failed result never retried.
        claimed = [r for r in ledger.read()['requests'] if r.get('purpose') == PURPOSE]
        if not claimed:
            remaining_fits(ledger.read(), plan()['reserved_microusd'])
        elif len(claimed) != 1 or claimed[0]['status'] != 'valid':
            raise RecoveryRequired('compact_claimed_request_requires_recovery')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('text_provider=anthropic\n')
        atomic_json(args.reservation, {'authorization_id': existing.AUTHORIZATION_ID,
            'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'code_sha': os.environ['GITHUB_SHA'], 'prior_ledger_sha256': existing.sha(ledger.path.read_bytes()),
            'continuation_lock_sha256': identity(plan()), 'operation': PURPOSE,
            'maximum_new_microusd': 500000, 'maximum_new_attempts': 1, 'native_count_calls': 0,
            'retained_unknown_hold_microusd': 351328, 'preserved_microusd': 1267862,
            'preserved_attempts': 2})
        return
    result = None
    try:
        result = CompactRunner(args.state, {}).perform()
    finally:
        existing.checkpoint(args.state)
        atomic_json(args.result, result or {'version': VERSION, 'operation': PURPOSE,
            'status': 'incomplete', 'automatic_retries': 0})
