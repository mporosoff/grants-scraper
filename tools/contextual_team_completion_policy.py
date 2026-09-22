"""One pooled completion amendment in the existing authoritative ledger.

This grants no generic dispatch permission. Each completion operation still
needs its own exact packet, validator and recovery policy in the trusted route.
"""
import json
import os
from pathlib import Path

from tools.offline_spend import atomic_json, identity, ConfigurationFailure, Deferred

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'funding-finder-completion-20260921-v1'
PREFIX = 'cb-fc-'
FAILED = 'c1d338226c57473ea464d002121b0167'
HISTORICAL_UNKNOWN_IDS = frozenset({
    'fc618603458249348c6834d258264520', 'd24a0654d72e486793519bead019b064',
    '6a6e93add95848dcb02f9ccaf158a2eb', FAILED})


def plan():
    value = json.loads((ROOT/'config/contextual_team/completion-authority-v1.json').read_bytes())
    if (value['version'] != VERSION
        or value['authorization_id'] != 'on-demand-team-offline-v2-20260909'):
        raise ConfigurationFailure('completion_authority_identity')
    return value


def events():
    p = plan()
    amendment = {'kind': 'pooled_completion_allowance', 'authority': VERSION,
        'plan_sha256': identity(p), 'starting_checkpoint': p['starting_checkpoint'],
        'lifetime': p['lifetime'], 'additional': p['additional'],
        'protected': p['protected'], 'scope': 'iteration_1_only',
        'public_activation': False, 'recurring_paid_usage': False}
    recovery = {'kind': 'exact_terminal_http_error_quarantined', 'authority': VERSION,
        'request_id': FAILED, 'body_sha256': p['failed']['body_sha256'],
        'held_microusd': 200000, 'usage': 'unknown', 'replay': 'permanently_closed',
        'original_run': p['terminal_run']['id'],
        'original_artifact': p['starting_checkpoint']['artifact'],
        'original_receipt_sha256': p['failed']['receipt_sha256'],
        'original_diagnostic_sha256': p['failed']['diagnostic_sha256'],
        'authenticated_run': p['terminal_run'],
        'allowed_operations': ['cb-fc-shared-check', 'cb-fc-json-fallback']}
    return [amendment, recovery]


def history(state, *, require_authority=True):
    """Validate immutable history; the exact route owns later uncertain rows."""
    p = plan(); start = p['starting_checkpoint']; rows = state['requests']
    if (len(rows) < start['requests']
        or identity(rows[:start['requests']]) != start['requests_sha256']
        or identity(state['events'][:start['events']]) != start['events_sha256']):
        raise ConfigurationFailure('completion_original_history_changed')
    installed = [e for e in state['events'] if e.get('authority') == VERSION]
    if installed != events() and (require_authority or installed):
        raise ConfigurationFailure('completion_exact_authority_missing_or_conflicting')
    expected = effective_plan(state)['lifetime'] if installed else {'microusd': 10000000, 'attempts': 690}
    if (state['limit_microusd'], state['max_requests']) != (expected['microusd'], expected['attempts']):
        raise ConfigurationFailure('completion_interacting_ledger_caps')
    from tools.contextual_team_checkpoint_disposition import validate
    validate(state)


def amended_limits(state):
    """Only this exact recorded amendment can change base Ledger identity."""
    history(state)
    p = effective_plan(state)
    return p['lifetime']['microusd'], p['lifetime']['attempts']


def effective_plan(state):
    """Original dollar/baseline identity plus an exact installed capacity event."""
    from tools.contextual_team_iteration3_capacity import effective_plan as capacity_plan
    return capacity_plan(state, plan())


def check_pool(state, amount=0, attempts=0):
    history(state)
    if type(amount) is not int or amount < 0 or type(attempts) is not int or attempts < 0:
        raise ValueError('completion_invalid_budget_request')
    if state.get('reservation_overrun') or state['blocked_providers']:
        raise Deferred('completion_existing_accounting_stop')
    p = effective_plan(state); start = p['starting_checkpoint']; protected = p['protected']
    from tools.contextual_team_checkpoint_disposition import exposure
    held = exposure(state)
    rows = state['requests']; used = sum(r['charged_microusd'] for r in rows) + held['microusd']
    # Count ALL additions to the one ledger, not merely labelled task rows.
    incremental = sum(r['charged_microusd'] for r in rows[start['requests']:]) + held['microusd']
    if (used + amount > p['lifetime']['microusd'] - protected['historical_microusd'] - protected['contingency_microusd']
        or len(rows) + held['attempts'] + attempts > p['lifetime']['attempts'] - protected['historical_attempts']
        or incremental + amount > p['additional']['microusd'] - protected['contingency_microusd']
        or len(rows) - start['requests'] + held['attempts'] + attempts > p['additional']['attempts']):
        raise Deferred('completion_pool_or_protected_reserve_exhausted')


def remaining_fits(state, amount):
    check_pool(state, amount, 1)


def check_count_budget(state, saved, item):
    """Bound every native attempt before its durable irreversible claim."""
    history(state)
    from tools.contextual_team_checkpoint_disposition import exposure, assert_operation_open, validate_counts
    assert_operation_open(state, item.get('id'))
    p = effective_plan(state); start = p['starting_checkpoint']; rows = saved['rows']
    from tools.contextual_team_iteration3_capacity import validate_counts as validate_capacity_counts
    validate_capacity_counts(state, rows)
    validate_counts(state, rows); held = exposure(state)
    if (len(rows) < start['native_counts']
        or identity(rows[:start['native_counts']]) != start['native_counts_sha256']):
        raise ConfigurationFailure('completion_original_native_counts_changed')
    if not item.get('id', '').startswith(PREFIX):
        raise ConfigurationFailure('completion_native_count_scope')
    check_pool(state)
    if (len(rows) + held['native_counts'] + 1 > p['lifetime']['native_counts']
        or len(rows) - start['native_counts'] + held['native_counts'] + 1 > p['additional']['native_counts']):
        raise Deferred('completion_native_count_allowance_exhausted')


def _validate_evidence(state_path):
    from tools import team_recommender_executor as existing
    p = plan(); docs = {}
    for folder, key in (('receipts', 'receipt_sha256'), ('diagnostics', 'diagnostic_sha256')):
        raw = (state_path/folder/(FAILED+'.json')).read_bytes()
        if existing.sha(raw) != p['failed'][key]:
            raise ConfigurationFailure('completion_terminal_evidence_hash')
        docs[folder] = json.loads(raw)
    receipt, diagnostic = docs['receipts'], docs['diagnostics']
    if (receipt.get('diagnostic_sha256') != identity(diagnostic)
        or receipt.get('request_id') != FAILED or diagnostic.get('request_id') != FAILED
        or receipt.get('body_sha256') != p['failed']['body_sha256']
        or diagnostic.get('body_sha256') != p['failed']['body_sha256']
        or receipt.get('status') != 'reserved_unknown' or diagnostic.get('http_status') != 400):
        raise ConfigurationFailure('completion_terminal_evidence_link')


def install_authority(state_path, api_call):
    """Atomically amend caps and quarantine exactly the terminal failed check."""
    from tools import team_recommender_executor as existing
    from tools.contextual_team_executor import RecoveryRequired
    state_path = Path(state_path); p = plan(); _validate_evidence(state_path)
    run = json.loads(api_call('actions/runs/'+str(p['terminal_run']['id'])))
    if any(run.get(k) != v for k, v in p['terminal_run'].items()):
        raise RecoveryRequired('completion_failed_owner_not_terminal')
    active = json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))['workflow_runs']
    if any(str(r['id']) != os.environ['GITHUB_RUN_ID'] for r in active):
        raise RecoveryRequired('completion_another_spending_owner_active')
    ledger = existing.ExperimentLedger(state_path/'ledger.json')
    with ledger.locked():
        state = ledger.read(); history(state, require_authority=False)
        checkpoint = json.loads((state_path/'checkpoint.json').read_bytes())
        counts = checkpoint['phase2_token_preflight']['rows']; start = p['starting_checkpoint']
        if (len(counts) < start['native_counts']
            or identity(counts[:start['native_counts']]) != start['native_counts_sha256']):
            raise ConfigurationFailure('completion_verified_starting_native_counts')
        if not any(e.get('authority') == VERSION for e in state['events']):
            # Install only from the verified owner checkpoint, never an older
            # mirror, reset ledger or a partly understood intervening request.
            if (existing.sha(ledger.path.read_bytes()) != start['ledger_sha256']
                or existing.sha((state_path/'checkpoint.json').read_bytes()) != start['checkpoint_sha256']
                or len(state['requests']) != start['requests'] or len(counts) != start['native_counts']):
                raise ConfigurationFailure('completion_verified_starting_checkpoint')
            actual = {f.relative_to(state_path).as_posix(): existing.sha(f.read_bytes())
                for f in state_path.rglob('*.json') if f.name != 'checkpoint.json'}
            if actual != checkpoint['files']:
                raise ConfigurationFailure('completion_starting_checkpoint_files')
            state.update(limit_microusd=p['lifetime']['microusd'], max_requests=p['lifetime']['attempts'])
            state['events'].extend(events())
            history(state)
            atomic_json(ledger.path, state)
        existing.checkpoint(state_path)
    return ledger
