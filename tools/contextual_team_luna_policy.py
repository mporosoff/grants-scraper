"""One exact terminal-error authority and two operations, in the existing ledger."""
import json
from tools.offline_spend import identity, atomic_json, ConfigurationFailure, Deferred
from tools.contextual_team_policy import ROOT

VERSION = 'luna-complete-pair-repair-v1'
OLD_ID = 'fc618603458249348c6834d258264520'
OLD_BODY = '7f13d7aa21ccbdfc7b976c30db0e77fcd9f4f2cb206203172c1ab03cf0847405'
OLD_RECEIPT = '6646896c908cc5c5e53983658998c3f653b368a2befd2c2c64009e5ca4635e10'
PRIOR_ROWS = '9b0f4844a9cdf9a48bf8e106de3acefe955b7e4eccfa92b6bdc2bbbf00ad1aa2'
PRIOR_COUNT_ROWS = 'e6b5804ea47b8159cddbc18b5f2ef786d17db5aaece6eb0581a0fbc3ffbb4d59'
EVENT = {'kind': 'exact_terminal_http_error_quarantined', 'authority': VERSION,
         'request_id': OLD_ID, 'body_sha256': OLD_BODY, 'held_microusd': 146074,
         'usage': 'unknown', 'replay': 'permanently_closed',
         'original_run': 34852296018, 'original_artifact': 10350533860,
         'original_receipt_sha256': OLD_RECEIPT,
         'allowed_operations': ['assessment', 'check']}
AUTHORITY_RECEIPT_ID = identity(EVENT)[:32]


def plan():
    p = json.loads((ROOT/'config/contextual_team/luna-contract-repair-v1.json').read_bytes())
    if p['version'] != VERSION or p['authorization_id'] != 'on-demand-team-offline-v2-20260909':
        raise ConfigurationFailure('luna_repair_authorization_identity')
    return p


def history(state, *, require_authority=True):
    rows = state['requests']
    if len(rows) < 683 or identity(rows[:683]) != PRIOR_ROWS:
        raise ConfigurationFailure('luna_repair_original_history_changed')
    if any(r['status'] == 'reserved_unknown' and r['id'] != OLD_ID for r in rows):
        raise Deferred('luna_other_uncertain_request_requires_recovery')
    events = [e for e in state['events'] if e.get('authority') == VERSION]
    if events != [EVENT] and (require_authority or events):
        raise ConfigurationFailure('luna_exact_terminal_authority_missing_or_conflicting')
    if state.get('reservation_overrun') or state['blocked_providers']:
        raise Deferred('luna_existing_accounting_stop')


def install_authority(state_path, api_call):
    from tools import team_recommender_executor as ex
    ledger = ex.ExperimentLedger(state_path/'ledger.json')
    history(ledger.read(), require_authority=False)
    original = state_path/'receipts'/(OLD_ID+'.json')
    if ex.sha(original.read_bytes()) != OLD_RECEIPT:
        raise ConfigurationFailure('luna_terminal_receipt_hash')
    receipt = json.loads(original.read_bytes())
    if (receipt.get('http_status') != 400 or receipt.get('request_id') != OLD_ID
            or receipt.get('body_sha256') != OLD_BODY or receipt.get('status') != 'reserved_unknown'):
        raise ConfigurationFailure('luna_completed_http400_not_established')
    run = json.loads(api_call('actions/runs/34852296018'))
    expected = {'id':34852296018, 'run_attempt':1, 'status':'completed', 'conclusion':'failure',
        'path':ex.WORKFLOW, 'head_branch':'main', 'event':'workflow_dispatch',
        'head_sha':'31b69b0772c759d9d8f7651a02aef924c7bab7e5'}
    if any(run.get(k) != v for k,v in expected.items()):
        raise Deferred('luna_original_run_terminality_not_proven')
    # No ledger row, status, charge or unknown-usage field is rewritten.
    authority = EVENT | {'authenticated_run':expected, 'prior_rows_sha256':PRIOR_ROWS}
    target = state_path/'receipts'/(AUTHORITY_RECEIPT_ID+'.json')
    with ledger.locked():
        state = ledger.read(); history(state, require_authority=False)
        if target.exists() and json.loads(target.read_bytes()) != authority:
            raise Deferred('luna_authority_receipt_conflict')
        atomic_json(target, authority)
        if EVENT not in state['events']:
            state['events'].append(EVENT); atomic_json(ledger.path, state)
    ex.checkpoint(state_path)


def remaining_fits(state, proposed=None):
    history(state); p=plan()
    new=[r for r in state['requests'] if r.get('luna_repair') == VERSION]
    claimed=[r['luna_operation'] for r in new]
    if len(claimed) != len(set(claimed)) or set(claimed)-set(p['operations']):
        raise Deferred('luna_operation_history_conflict')
    cost=0; count=0
    if proposed:
        name,cost=proposed
        if name in claimed:
            raise Deferred('luna_operation_claimed_no_rekey')
        claimed.append(name); count=1
    remaining=[o for n,o in p['operations'].items() if n not in claimed]
    reserve=sum(o['maximum_microusd'] for o in remaining)
    if (sum(r['charged_microusd'] for r in new)+cost+reserve > 500000
        or sum(r['charged_microusd'] for r in state['requests'])+cost+reserve > 10000000-1267862
        or len(new)+count+len(remaining)>2
        or len(state['requests'])+count+len(remaining)>688):
        raise Deferred('luna_complete_two_operation_budget_or_protected_reserve')


def check_reservation(state, provider, metadata, amount, input_tokens, output_tokens):
    name=metadata.get('luna_operation'); p=plan(); op=p['operations'].get(name)
    if (op is None or metadata.get('luna_repair') != VERSION
        or metadata.get('purpose') != 'cb-lc-'+name or provider != op['provider']
        or metadata.get('body_sha256') != op['body_sha256']
        or metadata.get('pair_contract_sha256') != op['contract_sha256']
        or metadata.get('repair_of') != op['repair_of']
        or metadata.get('packet_sha256') != p['source_inputs_sha256']):
        raise ConfigurationFailure('luna_exact_named_operation_required')
    if input_tokens > op['input_token_ceiling'] or output_tokens != op['output_token_ceiling']:
        raise Deferred('luna_complete_packet_capacity')
    minimum = (input_tokens+4)//5+(output_tokens*6+4)//5 if provider=='openai' else input_tokens*2+output_tokens*10
    if amount < minimum or amount > op['maximum_microusd']:
        raise ValueError('luna_conservative_cost_bound')
    remaining_fits(state,(name,amount))
