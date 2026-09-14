"""Eight named operations within the existing $10 / 690 ledger, not new credit."""
import json
import math
from tools.contextual_team_policy import ROOT, INPUT_SHA
from tools.offline_spend import identity, ConfigurationFailure, Deferred

RELEASE='0d0e2c7de98bbf15b9fdfd31bb1379f41f8c0c84de992db03aec6b392c6cf8d3'


def plan():
    p=json.loads((ROOT/'config/contextual_team/requirements-latency-v1.json').read_bytes())
    rid=p.pop('release_id')
    if rid!=RELEASE or identity(p)!=RELEASE:raise ConfigurationFailure('latency_plan_identity')
    p['release_id']=rid
    return p


def operation(name):
    return next(o for o in plan()['operations'] if o['id']==name)


def history(state):
    p=plan();rows=state['requests']
    if (len(rows)<p['prior_attempts'] or identity(rows[:p['prior_attempts']])!=p['prior_rows_sha256']
        or sum(r['charged_microusd'] for r in rows[:680])!=p['prior_charged_microusd']):
        raise ConfigurationFailure('latency_prior_accounting_changed')
    if any(r['status']=='reserved_unknown' for r in rows):raise Deferred('latency_uncertain_dispatch_recovery_required')


def remaining_fits(state, proposed=None):
    p=plan();rows=state['requests'];new=[r for r in rows if r.get('latency_lock')==RELEASE]
    claimed={r['latency_operation'] for r in new}
    extra_cost=0;extra_count=0
    if proposed:
        name,amount=proposed
        if name in claimed:raise Deferred('latency_operation_claimed_no_rekey')
        claimed.add(name);extra_cost=amount;extra_count=1
    remaining=[o for o in p['operations'] if o['id'] not in claimed]
    reserve=sum(o['maximum_microusd'] for o in remaining)
    if (sum(r['charged_microusd'] for r in rows)+extra_cost+reserve>10_000_000-p['preserved_microusd']
        or sum(r['charged_microusd'] for r in new)+extra_cost+reserve>p['maximum_new_microusd']
        or len(new)+extra_count+len(remaining)>8 or len(rows)+extra_count+len(remaining)>688):
        raise Deferred('latency_complete_allocation_or_protected_reserve')


def check_reservation(state,provider,metadata,amount,input_tokens,output_tokens):
    history(state);p=plan();name=metadata.get('latency_operation')
    if name not in {o['id'] for o in p['operations']} or metadata.get('latency_lock')!=RELEASE:
        raise ConfigurationFailure('latency_named_operation_required')
    op=operation(name)
    if (metadata.get('purpose')!='cb-lr-'+name or metadata.get('packet_sha256')!=p['source_inputs_sha256']
        or provider not in ({'anthropic','openai'} if op['provider']=='selected' else {op['provider']})):
        raise ConfigurationFailure('latency_provider_or_source_mismatch')
    expected={'anthropic':('claude-sonnet-5','medium'),'openai':('gpt-5.6-luna','low'),'voyage':('voyage-4-large','query')}[provider]
    if name.endswith('check'):expected=('claude-sonnet-5','disabled')
    if (metadata.get('latency_model'),metadata.get('latency_effort'))!=expected:
        raise ConfigurationFailure('latency_model_effort_contract')
    cap=p['openai_input_token_ceiling'] if provider=='openai' else op['input_token_ceiling']
    if input_tokens>cap or output_tokens!=op['output_token_ceiling']:
        raise Deferred('latency_complete_packet_capacity_no_truncation')
    if provider=='anthropic':
        native=metadata.get('native_input_tokens')
        if (type(native) is not int or native<1 or input_tokens!=math.ceil(native*1.2)+1024
            or not metadata.get('native_count_key') or metadata['native_count_key']!=metadata.get('count_body_sha256')):
            raise ConfigurationFailure('latency_native_count_reservation_identity')
    minimum=(input_tokens*3+24)//25 if provider=='voyage' else ((input_tokens+4)//5+(output_tokens*6+4)//5
        if provider=='openai' else input_tokens*2+output_tokens*10)
    if amount<minimum or amount>op['maximum_microusd']:raise ValueError('latency_cost_reservation')
    remaining_fits(state,(name,amount))
