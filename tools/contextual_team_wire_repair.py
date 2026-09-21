"""Exact owner-authorized grammar repair; one replacement inside the same cap."""
import json
import math
import os
from tools import team_recommender_executor as existing
from tools import contextual_team_compact_check as old
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_check_wire as wire
from tools.contextual_team_luna_repair import RepairRunner
from tools.contextual_team_executor import RecoveryRequired
from tools.contextual_team_token_preflight import Counter, count_projection
from tools.offline_spend import identity, atomic_json, ConfigurationFailure, Deferred

VERSION='compact-wire-repair-20260921-v1'
PURPOSE='cb-cc-wire-repair'
FAILED='6a6e93add95848dcb02f9ccaf158a2eb'
PRIOR_ROWS='3d37d8175881f4766a7f2692de2d92438a4190bb67618c6726829613d097cbe4'
PRIOR_COUNTS='4d6b4ddac6b8680ec532657bf1bea5a70165b78ec328a7843632cadec31733c7'
EVENT={'kind':'exact_terminal_http_error_quarantined','authority':VERSION,
    'request_id':FAILED,'body_sha256':old.plan()['body_sha256'],
    'held_microusd':263282,'usage':'unknown','replay':'permanently_closed',
    'original_run':35613118796,'original_artifact':10644862881,
    'allowed_operations':[PURPOSE]}


def plan():
    p=json.loads((old.ROOT/'config/contextual_team/compact-wire-repair-v1.json').read_bytes())
    if p['version']!=VERSION or p['authorization_id']!=existing.AUTHORIZATION_ID:
        raise ConfigurationFailure('wire_repair_authority_identity')
    return p


def history(state,require_authority=True):
    if len(state['requests'])<686 or identity(state['requests'][:686])!=PRIOR_ROWS:
        raise ConfigurationFailure('wire_repair_original_history')
    if old.EVENT not in state['events'] or old.prior.EVENT not in state['events']:
        raise ConfigurationFailure('wire_repair_prior_authorities')
    if any(r['status']=='reserved_unknown' and r['id'] not in (old.prior.OLD_ID,old.OLD_ID,FAILED)
           for r in state['requests']):
        raise RecoveryRequired('wire_repair_other_uncertainty')
    events=[e for e in state['events'] if e.get('authority')==VERSION]
    if events!=[EVENT] and (require_authority or events):
        raise ConfigurationFailure('wire_repair_exact_authority')
    if state.get('reservation_overrun') or state['blocked_providers']:
        raise Deferred('wire_repair_accounting_stop')


def install_authority(state_path,api_call):
    ledger=existing.ExperimentLedger(state_path/'ledger.json')
    history(ledger.read(),False)
    old.validate_terminal_evidence(state_path)
    for folder,key in (('receipts','failed_receipt_file_sha256'),('diagnostics','failed_diagnostic_file_sha256')):
        if existing.sha((state_path/folder/(FAILED+'.json')).read_bytes())!=plan()[key]:
            raise ConfigurationFailure('wire_repair_terminal_evidence')
    receipt=json.loads((state_path/'receipts'/(FAILED+'.json')).read_bytes())
    diagnostic=json.loads((state_path/'diagnostics'/(FAILED+'.json')).read_bytes())
    if receipt['diagnostic_sha256']!=identity(diagnostic):
        raise ConfigurationFailure('wire_repair_diagnostic_link')
    run=json.loads(api_call('actions/runs/35613118796'))
    expected={'id':35613118796,'run_attempt':1,'status':'completed','conclusion':'failure',
        'path':existing.WORKFLOW,'head_branch':'main','event':'workflow_dispatch',
        'head_sha':'c4e0ac136c6ff528c97eace81ddb0aecae23f0c9'}
    if any(run.get(k)!=v for k,v in expected.items()):
        raise RecoveryRequired('wire_repair_failed_run_not_terminal')
    active=json.loads(api_call('actions/workflows/team-recommender-offline.yml/runs?status=in_progress&per_page=100'))['workflow_runs']
    if any(str(r['id'])!=os.environ['GITHUB_RUN_ID'] for r in active):
        raise RecoveryRequired('wire_repair_other_owner')
    authority=EVENT|{'authenticated_run':expected,'prior_rows_sha256':PRIOR_ROWS,
        'continuation_lock_sha256':identity(plan())}
    target=state_path/'receipts'/(identity(EVENT)[:32]+'.json')
    with ledger.locked():
        state=ledger.read();history(state,False)
        if target.exists() and json.loads(target.read_bytes())!=authority:
            raise RecoveryRequired('wire_repair_authority_conflict')
        atomic_json(target,authority)
        if EVENT not in state['events']:
            state['events'].append(EVENT);atomic_json(ledger.path,state)
    existing.checkpoint(state_path)


def remaining_fits(state):
    history(state)
    if any(r.get('purpose')==PURPOSE or r.get('compact_continuation')==VERSION for r in state['requests']):
        raise RecoveryRequired('wire_repair_claimed_no_rekey')
    # The preceding failed check's full hold counts toward the SAME $0.50.
    if (sum(r['charged_microusd'] for r in state['requests'][685:])+200000>500000
        or sum(r['charged_microusd'] for r in state['requests'])+200000>10000000-1267862
        or len(state['requests'])+1>688):
        raise Deferred('wire_repair_existing_budget_or_reserve')


def check_reservation(state,provider,metadata,amount,input_tokens,output_tokens):
    p=plan()
    expected={'purpose':PURPOSE,'compact_continuation':VERSION,
        'continuation_lock_sha256':identity(p),'body_sha256':p['body_sha256'],
        'pair_contract_sha256':p['contract_sha256'],'repair_of':FAILED,
        'packet_sha256':old.prior.plan()['source_inputs_sha256']}
    if (provider!='anthropic' or any(metadata.get(k)!=v for k,v in expected.items())
        or (amount,input_tokens,output_tokens)!=(200000,40000,12000)):
        raise ConfigurationFailure('wire_repair_exact_reservation')
    remaining_fits(state)


def packet(state):
    data,_,_=old.packet(state)  # Includes exact saved Luna cache validation.
    contract,body=wire.body(data);p=plan()
    if identity(contract)!=p['contract_sha256'] or identity(body)!=p['body_sha256']:
        raise ConfigurationFailure('wire_repair_frozen_packet')
    return data,contract,body


class WireRunner(RepairRunner):
    def request_provider(self,purpose,body):
        if purpose!=PURPOSE or body['model']!='claude-sonnet-5':
            raise ConfigurationFailure('wire_repair_only_fixed_check')
        return 'anthropic'

    def has_unknown_request(self):
        try:history(self.ledger.read())
        except (Deferred,ConfigurationFailure,RecoveryRequired):return True
        return False

    def reservation_cost(self,purpose,body,metadata):
        remaining_fits(self.ledger.read())
        p=plan()
        if identity(body)!=p['body_sha256']:
            raise ConfigurationFailure('wire_repair_count_packet')
        cp=json.loads((self.state/'checkpoint.json').read_bytes())
        rows=cp['phase2_token_preflight']['rows'];key=identity(count_projection(body))
        if (len(rows)<187 or identity(rows[:187])!=PRIOR_COUNTS or len(rows)>188
            or any(r['key']!=key for r in rows[187:])):
            raise ConfigurationFailure('wire_repair_one_native_count')
        # Exact cached count is reused; uncertain counts cannot be repeated.
        native=Counter(self.state).count({'id':VERSION+':complete','body':body})
        if math.ceil(native*1.2)+1024>40000:
            raise Deferred('wire_repair_complete_input_exceeds_budget')
        return 40000,200000,{}

    def perform(self):
        data,c,body=packet(self.state)
        value=self.request(PURPOSE,[VERSION,PURPOSE,identity(c),identity(data)],body,
            lambda v,cached:pairs.validate_cached(v,data,judge=True) if cached else wire.parse(v,data),
            ceiling=40000,repair_metadata={'compact_continuation':VERSION,
                'continuation_lock_sha256':identity(plan()),'repair_of':FAILED,
                'pair_contract_sha256':identity(c),'packet_sha256':old.prior.plan()['source_inputs_sha256']})
        return {'version':VERSION,'operation':PURPOSE,'value':value,
            'request_id':self.used[-1]['request_id'],'cache_hit':self.used[-1]['cache_hit'],
            'body_sha256':identity(body)}


def run(args):
    existing.trusted_environment()
    if (json.loads(os.environ['CONTEXTUAL_CHECK'])!={'compact_wire_repair':VERSION}
        or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB','PACKET_HASH','PACKET_COMMIT'))):
        raise ConfigurationFailure('wire_repair_exact_selector')
    if args.action=='prepare':
        ledger=existing.restore(args.state,existing.policy());packet(args.state)
        install_authority(args.state,existing.api)
        claimed=[r for r in ledger.read()['requests'] if r.get('purpose')==PURPOSE]
        if not claimed:remaining_fits(ledger.read())
        elif len(claimed)!=1 or claimed[0]['status']!='valid':
            raise RecoveryRequired('wire_repair_claimed_requires_recovery')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('text_provider=anthropic\n')
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,
            'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
            'code_sha':os.environ['GITHUB_SHA'],'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),
            'operation':PURPOSE,'continuation_lock_sha256':identity(plan()),
            'maximum_new_microusd':200000,'maximum_new_attempts':1,
            'native_count_calls':1,'retained_unknown_hold_microusd':614610,
            'preserved_microusd':1267862,'preserved_attempts':2})
        return
    result=None
    try:result=WireRunner(args.state,{}).perform()
    finally:
        existing.checkpoint(args.state)
        atomic_json(args.result,result or {'version':VERSION,'status':'incomplete'})
