"""One fixed catalog repair charged to the existing completion owner.

This is a finite inventory, not a recurring release allowance. Original requests,
native counts, the Math closure and the EC disposition remain immutable.
"""
import json
from pathlib import Path
import re

from tools import contextual_team_completion_policy as pool
from tools import team_recommender_executor as existing
from tools.offline_spend import ConfigurationFailure, Deferred, atomic_json, identity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'funding-finder-catalog-correction-20260923-v1'
PREFIX = 'cb-fc-cat-'
PLAN_SHA = '045b201236550bebf336630e1193d9bd80705766a29e652b9dd7d28be4736fc5'
CONFIG = ROOT/'config/catalog_correction_20260923.json'


def require(ok, why):
    if not ok:
        raise ConfigurationFailure('catalog_correction_' + why)


def plan():
    value = json.loads(CONFIG.read_bytes())
    require(identity(value) == PLAN_SHA and value['version'] == VERSION
        and value['authorization_id'] == existing.AUTHORIZATION_ID, 'exact_plan')
    require(value['additional_allowance'] == 0 and value['automatic_retries'] == 0
        and value['native_counts'] == 0 and value['public_team_coverage_changed'] is False,
        'unchanged_authority')
    operations = value['operations']
    require(set(operations) == {f'embedding-{i}' for i in range(1, 8)} |
        {'smoke-embed', 'smoke-current-rerank', 'smoke-previous-rerank'}, 'fixed_inventory')
    for name, op in operations.items():
        expected = 'rerank-2.5' if name.endswith('rerank') else 'voyage-4-lite'
        require(op['model'] == expected and op['provider'] == 'voyage'
            and op['purpose'] == PREFIX+name and type(op['input_tokens']) is int
            and op['input_tokens'] > 0 and op['output_tokens'] == 0
            and op['maximum_microusd'] == (op['input_tokens']+(19 if expected == 'rerank-2.5' else 49)) //
                (20 if expected == 'rerank-2.5' else 50), 'fixed_operation')
    require(value['maximum_microusd'] == sum(o['maximum_microusd'] for o in operations.values())
        and value['maximum_microusd'] <= 34845 and value['maximum_metered_attempts'] == 10, 'complete_envelope')
    inputs = [i for o in operations.values() for i in o['row_inputs']]
    require(len(inputs) == len(set(inputs)) and len(inputs) <= 1581
        and all(isinstance(i, str) and re.fullmatch('[a-f0-9]{64}', i) for i in inputs), 'approved_input_inventory')
    return value


def operation(name):
    require(name in plan()['operations'], 'unnamed_operation')
    return plan()['operations'][name]


def scope_event():
    return {'kind': 'finite_catalog_correction', 'authority': VERSION,
        'plan_sha256': PLAN_SHA, 'additional_allowance': 0,
        'maximum_metered_attempts': 10, 'native_counts': 0,
        'maximum_microusd': plan()['maximum_microusd'],
        'row_input_capacity': {'previous_total_ceiling': 3840, 'catalog_total_ceiling': 4343,
            'maximum_new_catalog_inputs': 1581,
            'exact_new_catalog_inputs': sum(len(o['row_inputs']) for o in plan()['operations'].values()),
            'increase_above_previous_ceiling': 503,
            'older_routes_total_ceiling': 3840},
        'authority_basis': 'Explicit owner approval of the exact catalog input amendment on 2026-09-23'}


def metadata(name):
    op = operation(name)
    return {'purpose': op['purpose'], 'body_sha256': op['body_sha256'],
        'packet_sha256': plan()['corpus_sha256'], 'row_inputs': op['row_inputs'],
        'judge_items': [], 'execution_capacity': VERSION,
        'completion_authority': VERSION, 'completion_transport': VERSION,
        'completion_lock_sha256': PLAN_SHA, 'pair_contract_sha256': identity(op), 'repair_of': None}


def logical_key(name):
    return identity([existing.AUTHORIZATION_ID, VERSION, PLAN_SHA, name])


def present(state):
    return any(r.get('purpose', '').startswith(PREFIX) for r in state['requests']) or any(
        e.get('authority') == VERSION for e in state['events'])


def validate_appended_history(state):
    """Nonrecursive proof for older guards; no unknown row is excused."""
    if not present(state):
        return
    p = plan(); start = p['starting_checkpoint']
    require(len(state['requests']) >= start['requests']
        and identity(state['requests'][:start['requests']]) == start['requests_sha256']
        and identity(state['events'][:start['events']]) == start['events_sha256'], 'historical_prefix')
    require(identity(state['events'][start['events']:]) == identity([scope_event()]), 'immutable_scope_event')
    seen = set()
    for row in state['requests'][start['requests']:]:
        require(isinstance(row.get('purpose'), str) and row['purpose'].startswith(PREFIX), 'foreign_tail')
        name = row['purpose'][len(PREFIX):]; op = operation(name)
        require(name not in seen, 'no_replay_or_rekey'); seen.add(name)
        expected = metadata(name) | {'provider': 'voyage', 'model': op['model'],
            'key': logical_key(name), 'attempt': 1, 'stage': 2,
            'reserved_input_tokens': op['input_tokens'], 'reserved_output_tokens': 0,
            'reserved_microusd': op['maximum_microusd'], 'dispatch_claim': 'irreversible-v1'}
        require(identity({k: row.get(k) for k in expected}) == identity(expected), 'request_identity')
        if row.get('status') == 'reserved_unknown':
            raise Deferred('catalog_correction_new_uncertainty_requires_recovery')
        require(row.get('status') in ('valid', 'failed'), 'terminal_status')
        tokens = row.get('usage', {}).get('total_tokens') if isinstance(row.get('usage'), dict) else None
        divisor = 20 if op['model'] == 'rerank-2.5' else 50
        require(type(tokens) is int and tokens > 0 and row['usage'] == {'total_tokens': tokens}
            and type(row.get('charged_microusd')) is int
            and row['charged_microusd'] == (tokens+divisor-1)//divisor
            and row['charged_microusd'] <= row['reserved_microusd']
            and bool(re.fullmatch('[a-f0-9]{40}', row.get('code_sha', '')))
            and bool(re.fullmatch('[a-f0-9]{32}', row.get('id', ''))), 'exact_terminal_accounting')
    require(len(seen) <= 10, 'finite_inventory')


def historical_request_end(state):
    if not present(state):
        return len(state['requests'])
    validate_appended_history(state)
    return plan()['starting_checkpoint']['requests']


def history(state):
    from tools import contextual_team_iteration3_continuation_policy as prior
    prior.history(state)
    p = plan(); start = p['starting_checkpoint']
    require(len(state['requests']) >= start['requests']
        and identity(state['requests'][:start['requests']]) == start['requests_sha256']
        and identity(state['events'][:start['events']]) == start['events_sha256'], 'complete_scientific_checkpoint')
    validate_appended_history(state)
    if not present(state):
        require(len(state['requests']) == start['requests'] and len(state['events']) == start['events'], 'exact_start')


def counts(state_path):
    from tools import contextual_team_iteration3_continuation_policy as prior
    rows = prior.counts(state_path); start = plan()['starting_checkpoint']
    require(len(rows) == start['native_counts'] and identity(rows) == start['native_counts_sha256'],
        'native_counts_unchanged')
    return rows


def envelope(state):
    history(state)
    claimed = {r['purpose'] for r in state['requests']}
    remaining = [o for o in plan()['operations'].values() if o['purpose'] not in claimed]
    amount = sum(o['maximum_microusd'] for o in remaining)
    pool.check_pool(state, amount, len(remaining))
    purchased = {i for r in state['requests'] for i in r.get('row_inputs', [])}
    pending = [i for o in remaining for i in o['row_inputs']]
    require(len(pending) == len(set(pending)) and not purchased.intersection(pending)
        and len(purchased | set(pending)) <= (4343 if present(state) else 3840), 'complete_embedding_inventory')
    return {'maximum_microusd': amount, 'metered_attempts': len(remaining), 'native_counts': 0}


def unique_input_limit(state):
    history(state)
    require(present(state), 'explicit_input_amendment_required')
    return 4343


def install(state_path):
    existing.trusted_environment()
    ledger = existing.ExperimentLedger(Path(state_path)/'ledger.json')
    with ledger.locked():
        state = ledger.read(); history(state); counts(state_path)
        if not present(state):
            state['events'].append(scope_event()); validate_appended_history(state)
            envelope(state)
            atomic_json(ledger.path, state)
        else:
            envelope(state)
        existing.checkpoint(state_path)
    return ledger


def check_reservation(state, provider, supplied, amount, input_tokens, output_tokens):
    history(state)
    require(present(state), 'scope_not_installed')
    purpose = supplied.get('purpose', '')
    require(purpose.startswith(PREFIX), 'exact_purpose')
    name = purpose[len(PREFIX):]; op = operation(name)
    require(not any(r.get('purpose') == purpose for r in state['requests']), 'claimed_operation_no_retry')
    order = [f'embedding-{i}' for i in range(1, 8)] + ['smoke-embed', 'smoke-current-rerank', 'smoke-previous-rerank']
    rows = {r['purpose']: r for r in state['requests'] if r.get('purpose', '').startswith(PREFIX)}
    require(set(rows) == {PREFIX+n for n in order[:order.index(name)]}
        and all(r['status'] == 'valid' for r in rows.values()), 'complete_accepted_predecessors')
    expected = metadata(name)
    require(provider == 'voyage' and identity({k: supplied.get(k) for k in expected}) == identity(expected)
        and type(amount) is int and amount == op['maximum_microusd']
        and type(input_tokens) is int and input_tokens == op['input_tokens']
        and type(output_tokens) is int and output_tokens == 0,
        'reservation_identity')
    envelope(state)
