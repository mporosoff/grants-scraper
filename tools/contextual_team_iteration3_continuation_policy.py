"""Six named corrections under the existing pool, with no retry authority."""
import json
import math
import os
from pathlib import Path

from tools import contextual_team_completion_policy as pool
from tools import contextual_team_iteration3_policy as original
from tools import team_recommender_executor as existing
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, encoded, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'funding-finder-iteration3-completion-20260923-v1'
PREFIX = 'cb-fc-i3c-'
START_REQUESTS = 725
START_COUNTS = 206
START_EVENTS = 65
REQUESTS_SHA = 'a91260b083e48cd98b04a0bdc05fbcf08bf13dfdc474337a51f5f2d72700c84e'
COUNTS_SHA = '380e0511fe4d72186b6fe26c0deb50ec84e9d5ee60ca2db74d2e144bd10eefbc'
EVENTS_SHA = '97b31f5b23f3e4f705f1e3a9582ba07d6b264a020467013d65158ecd4fc5ea62'
PLAN_SHA = '3bf6f75a0ac2e1e60b478129638aec606873ea24889e0be8301084361552b6bf'
OPERATIONS = {
    'ai_verify': ('363268', 'verify', 24000, '20c86e4e4caf4b5caee73802bec82906'),
    'ai_integrity': ('363268', 'integrity', 12000, None),
    'ai_check': ('363268', 'check', 12000, None),
    'ec_check': ('344592:ab-0025', 'check', 12000, '534aba746f3044978f83262b69c1d073'),
    'lqc_rejected': ('332894', 'rejected', 12000, None),
    'quantum_rejected': ('345241:tdac-baa-004', 'rejected', 12000, None),
}


def _require(ok, why):
    if not ok:
        raise ConfigurationFailure('iteration3_continuation_' + why)


def plan():
    p = json.loads((ROOT/'config/contextual_team/iteration3-continuation-v1.json').read_bytes())
    _require(identity(p) == PLAN_SHA, 'exact_plan_pin')
    _require(p.get('version') == VERSION and p.get('authorization_id') == existing.AUTHORIZATION_ID
        and p.get('release_id') == identity({k: v for k, v in p.items() if k != 'release_id'}), 'plan_identity')
    expected = {name: {'purpose': PREFIX+name, 'scope_id': scope, 'stage': stage,
        'provider': 'anthropic', 'model': 'claude-sonnet-5', 'output_tokens': output, 'repair_of': repair}
        for name, (scope, stage, output, repair) in OPERATIONS.items()}
    _require(p.get('operations') == expected and p.get('max_requests') == 6 and p.get('max_native_counts') == 6
        and p.get('input_token_ceiling') == 180000 and p.get('maximum_wire_bytes') == 524288
        and p.get('maximum_graph_bytes') == 393216 and p.get('additional_allowance') == 0
        and all(p.get(k) is False for k in ('public_activation', 'recurring_paid_usage', 'paid_builds_enabled'))
        and p.get('confirmation_outputs_sealed') is True, 'fixed_inventory')
    _require(p.get('source_inputs_sha256') == original.plan()['source_inputs_sha256']
        and p.get('original_authority_sha256') == identity(original.plan()), 'retained_source_authority')
    for name, pin in p.get('locked_packets', {}).items():
        _require(name in ('ai_verify', 'ec_check', 'lqc_rejected', 'quantum_rejected')
            and set(pin) == {'contract_sha256', 'body_sha256', 'input_sha256', 'contract_version'}
            and all(original._sha(pin[k]) for k in ('contract_sha256', 'body_sha256', 'input_sha256')),
            'fixed_packet_pin')
    _require(set(p.get('locked_packets', {})) == {'ai_verify', 'ec_check', 'lqc_rejected', 'quantum_rejected'},
        'complete_fixed_packets')
    return p


def operation(name):
    _require(name in OPERATIONS, 'unapproved_operation')
    return PREFIX+name


def name_of(purpose):
    _require(isinstance(purpose, str) and purpose.startswith(PREFIX), 'unapproved_purpose')
    name = purpose[len(PREFIX):]
    operation(name)
    return name


def event():
    return {'kind': 'iteration3_continuation_scope', 'authority': VERSION, 'plan_sha256': identity(plan()),
        'operations': plan()['operations'], 'additional_allowance': 0,
        'public_activation': False, 'recurring_paid_usage': False}


def _events(state):
    return [e for e in state['events'] if e.get('authority') == VERSION and e.get('kind') == 'iteration3_continuation_operation']


def _metadata(e):
    return {'completion_authority': VERSION, 'completion_lock_sha256': identity(plan()),
        'completion_transport': e['contract_version'], 'pair_contract_sha256': e['contract_sha256'],
        'repair_of': e['repair_of'], 'packet_sha256': plan()['source_inputs_sha256'], 'execution_capacity': VERSION}


def validate_appended_history(state):
    """Nonrecursive validator used by the historical I3 guard."""
    installed = [e for e in state['events'] if e.get('authority') == VERSION]
    from tools.catalog_correction_policy import historical_request_end
    appended = state['requests'][START_REQUESTS:historical_request_end(state)]
    if not installed and not appended:
        return
    _require(len(state['requests']) >= START_REQUESTS and identity(state['requests'][:START_REQUESTS]) == REQUESTS_SHA
        and identity(state['events'][:START_EVENTS]) == EVENTS_SHA, 'original_history_changed')
    _require([e for e in installed if e.get('kind') == 'iteration3_continuation_scope'] == [event()], 'exact_authority')
    bound = {}
    for e in installed:
        if e == event():
            continue
        _require(set(e) == {'kind', 'authority', 'purpose', 'body_sha256', 'input_sha256', 'contract_sha256',
            'contract_version', 'count_body_sha256', 'output_tokens', 'repair_of', 'plan_sha256'}
            and e.get('kind') == 'iteration3_continuation_operation', 'operation_shape')
        name = name_of(e['purpose']); op = plan()['operations'][name]
        _require(e['purpose'] not in bound and e['output_tokens'] == op['output_tokens']
            and type(e['output_tokens']) is int and e['repair_of'] == op['repair_of']
            and e['plan_sha256'] == identity(plan())
            and all(original._sha(e[k]) for k in ('body_sha256', 'input_sha256', 'contract_sha256', 'count_body_sha256')),
            'operation_identity')
        pin = plan()['locked_packets'].get(name)
        _require(not pin or all(e[k] == v for k, v in pin.items()), 'locked_packet_changed')
        expected_version = {'ai_integrity': 'contextual-production-integrity-v1',
            'ai_check': 'contextual-iteration3-independent-evaluation-v1'}.get(name)
        _require(expected_version is None or e['contract_version'] == expected_version, 'downstream_contract_version')
        bound[e['purpose']] = e
    seen = set()
    for row in appended:
        e = bound.get(row.get('purpose'))
        _require(e is not None and row['purpose'] not in seen, 'request_without_unique_operation')
        expected = _metadata(e) | {'body_sha256': e['body_sha256'], 'provider': 'anthropic',
            'model': 'claude-sonnet-5', 'attempt': 1, 'stage': 2, 'row_inputs': [], 'judge_items': []}
        _require(all(row.get(k) == v for k, v in expected.items()), 'request_identity')
        _require(row.get('key') == identity([existing.AUTHORIZATION_ID, 'contextual-v1',
            [VERSION, e['purpose'], e['contract_sha256'], e['input_sha256']]]), 'logical_identity')
        _require(row.get('reserved_output_tokens') == e['output_tokens']
            and type(row.get('native_input_tokens')) is int and row['native_input_tokens'] > 0
            and row.get('native_count_key') == e['count_body_sha256']
            and row.get('count_body_sha256') == e['count_body_sha256']
            and row.get('reserved_input_tokens') == math.ceil(row['native_input_tokens']*1.2)+1024
            and row['reserved_input_tokens'] <= plan()['input_token_ceiling']
            and row.get('reserved_microusd') == row['reserved_input_tokens']*2+e['output_tokens']*10,
            'reserved_capacity')
        seen.add(row['purpose'])
        if row.get('status') == 'reserved_unknown':
            raise Deferred('iteration3_continuation_new_uncertainty_requires_recovery')
    _require(len(appended) <= 6, 'finite_request_inventory')


def validate_appended_counts(state, rows):
    if len(rows) <= START_COUNTS:
        return
    _require(identity(rows[:START_COUNTS]) == COUNTS_SHA, 'original_counts_changed')
    validate_appended_history(state)
    bound = {e['purpose']: e for e in _events(state)}; seen = set()
    for row in rows[START_COUNTS:]:
        e = bound.get(row.get('id'))
        _require(e is not None and row['id'] not in seen and row.get('key') == e['count_body_sha256']
            and row.get('metered_inference') is False and type(row.get('charged_microusd')) is int
            and row['charged_microusd'] == 0, 'native_identity')
        if row.get('status') != 'complete':
            raise Deferred('iteration3_continuation_native_uncertainty')
        _require(type(row.get('input_tokens')) is int and 0 < row['input_tokens'] <= 200000, 'native_value')
        seen.add(row['id'])
    _require(len(rows)-START_COUNTS <= 6, 'finite_native_inventory')


def history(state):
    from tools import contextual_team_ec_disposition as recovery
    original.history(state)
    recovery.validate(state, require=True)
    _require(identity(state['requests'][:START_REQUESTS]) == REQUESTS_SHA
        and identity(state['events'][:START_EVENTS]) == EVENTS_SHA, 'starting_checkpoint_changed')
    validate_appended_history(state)


def counts(state_path):
    # Callers may already own the ledger lock. Constructing another Ledger
    # would try to acquire it again; this read is validated immediately below.
    state = json.loads((Path(state_path)/'ledger.json').read_bytes())
    history(state)
    rows = original.check_counts(state_path)
    _require(len(rows) >= START_COUNTS and identity(rows[:START_COUNTS]) == COUNTS_SHA, 'starting_native_checkpoint')
    validate_appended_counts(state, rows)
    return rows


def install_authority(state_path, *, contextual_job=None):
    """Called only after trusted restoration and the separately installed EC event."""
    existing.trusted_environment(contextual_job=contextual_job)
    ledger = existing.ExperimentLedger(Path(state_path)/'ledger.json')
    with ledger.locked():
        state = ledger.read(); history(state); counts(state_path)
        installed = [e for e in state['events'] if e.get('authority') == VERSION]
        if not installed:
            _require(len(state['requests']) == START_REQUESTS, 'exact_install_requests')
            state['events'].append(event()); validate_appended_history(state)
            atomic_json(ledger.path, state)
        existing.checkpoint(state_path)
    return ledger


def packet_event(name, body, contract, input_id):
    from tools.contextual_team_token_preflight import count_projection
    op = plan()['operations'][name]
    _require(body.get('model') == op['model'] and body.get('max_tokens') == op['output_tokens']
        and body.get('thinking') == {'type': 'disabled'} and len(encoded(body)) <= plan()['maximum_wire_bytes']
        and not any(k in body for k in ('temperature', 'top_p', 'top_k'))
        and 'effort' not in body.get('output_config', {}), 'exact_provider_transport')
    e = {'kind': 'iteration3_continuation_operation', 'authority': VERSION, 'purpose': operation(name),
        'body_sha256': identity(body), 'input_sha256': input_id, 'contract_sha256': identity(contract),
        'contract_version': contract['version'], 'count_body_sha256': identity(count_projection(body)),
        'output_tokens': op['output_tokens'], 'repair_of': op['repair_of'], 'plan_sha256': identity(plan())}
    pin = plan()['locked_packets'].get(name)
    _require(not pin or all(e[k] == v for k, v in pin.items()), 'packet_pin_changed')
    return e


def finite_envelope(state, rows):
    history(state)
    claimed = {r.get('purpose') for r in state['requests']}
    unclaimed = [o for o in plan()['operations'].values() if o['purpose'] not in claimed]
    maximum = sum(plan()['input_token_ceiling']*2+o['output_tokens']*10 for o in unclaimed)
    pool.check_pool(state, maximum, len(unclaimed))
    from tools.contextual_team_checkpoint_disposition import exposure
    held = exposure(state); p = pool.effective_plan(state)
    required = sum(not any(r.get('id') == o['purpose'] for r in rows) for o in unclaimed)
    _require(len(rows)+held['native_counts']+required <= p['lifetime']['native_counts']
        and len(rows)-p['starting_checkpoint']['native_counts']+held['native_counts']+required <= p['additional']['native_counts'],
        'complete_native_capacity')
    return {'maximum_microusd': maximum, 'metered_attempts': len(unclaimed), 'native_counts': required,
        'purposes': [o['purpose'] for o in unclaimed]}


def bind_operation(ledger, name, body, contract, input_id):
    expected = packet_event(name, body, contract, input_id)
    with ledger.locked():
        state = ledger.read(); history(state); rows = counts(ledger.path.parent)
        saved = [e for e in _events(state) if e['purpose'] == expected['purpose']]
        _require(not saved or saved == [expected], 'operation_changed_no_rekey')
        if not any(r.get('purpose') == expected['purpose'] for r in state['requests']):
            original.source_currentness(OPERATIONS[name][0]); finite_envelope(state, rows)
        if not saved:
            state['events'].append(expected); validate_appended_history(state); atomic_json(ledger.path, state)
        existing.checkpoint(ledger.path.parent)
    return _metadata(expected)


def check_native_request(state_path, item, *, claim=False):
    from tools.contextual_team_token_preflight import count_projection
    state = existing.ExperimentLedger(Path(state_path)/'ledger.json').read()
    history(state); rows = counts(state_path); name = name_of(item.get('id'))
    saved = [e for e in _events(state) if e['purpose'] == item['id']]
    _require(len(saved) == 1 and saved[0]['count_body_sha256'] == identity(count_projection(item['body']))
        and saved[0]['body_sha256'] == identity(item['body']), 'native_exact_bound_packet')
    if claim:
        _require(not any(r.get('purpose') == item['id'] for r in state['requests']), 'claimed_operation_no_new_count')
        _require(not any(r.get('id') == item['id'] for r in rows), 'count_already_claimed')
        original.source_currentness(OPERATIONS[name][0]); finite_envelope(state, rows)


def check_reservation(state, provider, metadata, amount, input_tokens, output_tokens):
    history(state); name = name_of(metadata.get('purpose'))
    e = [e for e in _events(state) if e['purpose'] == operation(name)]
    _require(len(e) == 1, 'missing_exact_packet'); e = e[0]
    expected = _metadata(e) | {'body_sha256': e['body_sha256']}
    _require(provider == 'anthropic' and all(metadata.get(k) == v for k, v in expected.items())
        and type(output_tokens) is int and output_tokens == e['output_tokens'], 'reservation_identity')
    _require(not any(r.get('purpose') == operation(name) for r in state['requests']), 'claimed_operation_no_rekey')
    native = metadata.get('native_input_tokens')
    _require(type(native) is int and native > 0 and input_tokens == math.ceil(native*1.2)+1024
        and type(input_tokens) is int and input_tokens <= plan()['input_token_ceiling']
        and metadata.get('native_count_key') == e['count_body_sha256']
        and metadata.get('count_body_sha256') == e['count_body_sha256']
        and type(amount) is int and amount == input_tokens*2+output_tokens*10, 'exact_conservative_reservation')
    original.source_currentness(OPERATIONS[name][0]); pool.check_pool(state, amount, 1)
