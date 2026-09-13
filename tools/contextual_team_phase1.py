"""Two explicitly authorized retrospective checks, never a new scientific run.

The existing ledger owns dispatch irreversibility and exact-result persistence.
This module only narrows the named purposes, fixed packets and remaining budget.
"""
import json
import os
from tools import team_recommender_executor as existing
from tools.contextual_team_check import graphs, packet, RESPONSE_CONTRACT, OWNED_RESPONSE_CONTRACT
from tools.contextual_team_cost import text_reservation
from tools.contextual_team_executor import Runner, RecoveryRequired
from tools.contextual_team_option1 import configuration_for_job
from tools.contextual_team_policy import ROOT, INPUT_SHA
from tools.offline_spend import identity, atomic_json, Deferred, ConfigurationFailure


def plan(version=2):
    value=json.loads((ROOT/f'config/contextual_team/phase1-checks-v{version}.json').read_bytes())
    lock_id=value.pop('lock_id')
    if identity(value)!=lock_id:raise ConfigurationFailure('phase1_lock_identity')
    value['lock_id']=lock_id
    if (value['authorization_id']!=existing.AUTHORIZATION_ID or value['input_sha256']!=INPUT_SHA
        or value['response_contract_sha256']!=identity(OWNED_RESPONSE_CONTRACT if version==2 else RESPONSE_CONTRACT)):
        raise ConfigurationFailure('phase1_contract_identity')
    return value


def check_history(state,p):
    rows=state['requests'];start=p['starting_attempts']
    if len(rows)<start or identity(rows[:start])!=p['starting_request_rows_sha256']:
        raise RecoveryRequired('phase1_original_accounting_not_preserved')
    original=next((r for r in rows if r['id']==p['repair_of']['id']),None)
    if not original or any(original.get(k)!=v for k,v in p['repair_of'].items()):
        raise RecoveryRequired('phase1_original_schema_failure_not_confirmed')
    if any(r['status']=='reserved_unknown' for r in rows):
        raise RecoveryRequired('phase1_uncertain_dispatch_preserved')
    if any(r.get('purpose')=='cb-o1-check-explanation' for r in rows):
        raise RecoveryRequired('phase1_original_explanation_already_claimed')
    if p.get('owned_references') and any(r.get('purpose')=='cb-p1-check-explanation' for r in rows):
        raise RecoveryRequired('phase1_v2_explanation_already_claimed')


def ensure_remaining_plan_fits(state,p):
    check_history(state,p)
    rows=state['requests'];claimed={r.get('purpose') for r in rows}
    remaining=[o for o in p['operations'] if o['purpose'] not in claimed]
    purposes={o['purpose'] for o in p['operations']}
    task=[r for r in rows if r.get('purpose') in purposes]
    future=sum(o['maximum_microusd'] for o in remaining)
    if (len(rows)+len(remaining)>690-p['preserved_attempts']
        or sum(r['charged_microusd'] for r in rows)+future>10_000_000-p['preserved_microusd']
        or len(task)+len(remaining)>p['maximum_new_attempts']
        or sum(r['charged_microusd'] for r in task)+future>p['maximum_new_microusd']):
        raise Deferred('phase1_complete_two_check_envelope_does_not_fit')
    return remaining


def check_reservation(state,provider,metadata,amount,input_tokens,output_tokens):
    p=plan();purpose=metadata.get('purpose')
    op=next((o for o in p['operations'] if o['purpose']==purpose),None)
    if (not op or provider!='anthropic' or metadata.get('phase1_lock')!=p['lock_id']
        or metadata.get('response_contract_sha256')!=p['response_contract_sha256']
        or metadata.get('repair_of')!=op['repair_of'] or metadata.get('packet_sha256')!=INPUT_SHA
        or metadata.get('body_sha256')!=op['body_sha256']
        or input_tokens!=op['input_token_bound'] or output_tokens!=op['max_output_tokens']
        or amount!=op['maximum_microusd'] or amount!=input_tokens*2+output_tokens*10):
        raise ConfigurationFailure('phase1_exact_approved_request_required')
    if any(r.get('purpose')==purpose for r in state['requests']):
        raise RecoveryRequired('phase1_once_per_purpose_no_rekey')
    ensure_remaining_plan_fits(state,p)  # Called under the existing ledger lock.


def prepared_packets(state,requested,p):
    config=configuration_for_job({'release_id':p['release_id'],'scope_id':p['scope_id'],'person_id':''})
    if config['registry_generation']!=p['registry_generation']:
        raise ConfigurationFailure('phase1_registry_identity')
    if requested!=[{'scope_id':p['scope_id'],'graph_id':p['graph_id'],'members':p['members']}]:
        raise ConfigurationFailure('phase1_exact_original_primary_required')
    selected=graphs(state,config)
    if not selected or selected[0][0]['id']!=p['scope_id'] or selected[0][1]['graph_id']!=p['graph_id']:
        raise RecoveryRequired('phase1_original_base_graph_unavailable')
    scope,graph=selected[0];packets=[]
    for op in p['operations']:
        original,_=packet(scope,graph,p['members'],op['kind'],config)
        body,check=packet(scope,graph,p['members'],op['kind'],config,revised=True,owned_references=p.get('owned_references',False))
        if (identity(original)!=op['original_body_sha256'] or identity(body)!=op['body_sha256']
            or original['messages']!=body['messages']
            or identity(body['messages'])!=op['question_evidence_sha256']
            or text_reservation(body)!=(op['input_token_bound'],op['maximum_microusd'])):
            raise ConfigurationFailure('phase1_original_questions_or_revised_packet_changed')
        packets.append((op,body,check))
    return config,packets


def execute(runner,packets,p,result_path):
    results=[]
    contract=OWNED_RESPONSE_CONTRACT if p.get('owned_references') else RESPONSE_CONTRACT
    try:
        for op,body,check in packets:
            purpose=op['purpose']
            value=runner.request(purpose,[purpose,p['release_id'],p['scope_id'],op['kind']],body,check,
                ceiling=op['input_token_bound'],repair_metadata={'phase1_lock':p['lock_id'],
                    'response_contract_sha256':p['response_contract_sha256'],'repair_of':op['repair_of']})
            results.append({'kind':op['kind'],'scope_id':p['scope_id'],'body_sha256':identity(body),'value':value})
            # Durable request/cache already exist. Keep each accepted batch even
            # if the following provider, parser, or convenience-file write fails.
            atomic_json(result_path,{'version':contract['version'],'results':results,'requests':runner.used})
    finally:
        # Do not confuse an empty convenience array with zero paid dispatches.
        rows=[r for r in runner.ledger.read()['requests'] if r.get('purpose') in {o['purpose'] for o in p['operations']}]
        atomic_json(result_path,{'version':contract['version'],'lock_id':p['lock_id'],
            'results':results,'requests':runner.used,'durable_requests':rows,
            'maximum_requests':p['maximum_new_attempts'],'maximum_new_microusd':p['maximum_new_microusd'],'human_judgments':0,
            'same_model_family_limitation':True})
        existing.checkpoint(runner.state)


def run(args):
    p=plan();requested=json.loads(os.environ['CONTEXTUAL_CHECK'])
    if os.environ.get('CONTEXTUAL_JOB') or os.environ.get('PACKET_HASH') or os.environ.get('PACKET_COMMIT'):
        raise ConfigurationFailure('phase1_mutually_exclusive_operation')
    if args.action=='prepare':
        ledger=existing.restore(args.state,existing.policy());existing.checkpoint(args.state)
    else:
        from tools.team_recommender_budget import ExperimentLedger
        ledger=ExperimentLedger(args.state/'ledger.json')
    config,packets=prepared_packets(args.state,requested,p)
    remaining=ensure_remaining_plan_fits(ledger.read(),p)
    if args.action=='prepare':
        # The workflow durably uploads this complete envelope before credentials
        # reach execute. Per-request irreversible claims use the same ledger.
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,
            'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
            'code_sha':os.environ['GITHUB_SHA'],'input_sha256':INPUT_SHA,'phase1_lock':p['lock_id'],
            'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),
            'maximum_new_microusd':p['maximum_new_microusd'],'maximum_new_attempts':2,
            'remaining_operations':remaining,'reserved_envelope_microusd':sum(o['maximum_microusd'] for o in remaining),
            'repair_of':p['repair_of'],'response_contract':OWNED_RESPONSE_CONTRACT if p.get('owned_references') else RESPONSE_CONTRACT,
            'response_contract_sha256':p['response_contract_sha256']})
        return
    execute(Runner(args.state,config),packets,p,args.result)
