"""The two named repaired operations; never a normal service or graph publisher."""
import json
import math
import os
from tools import team_recommender_executor as existing
from tools import contextual_team_pair_contract as pairs
from tools import contextual_team_luna_policy as policy
from tools import contextual_team_diagnostics as diagnostics
from tools.contextual_team_executor import Runner, RecoveryRequired
from tools.contextual_team_latency import eclipse_data
from tools.contextual_team_token_preflight import Counter, count_projection
from tools.offline_spend import (identity, encoded, atomic_json, normalize_usage,
    cost_microusd, ConfigurationFailure, Deferred)


def result_path(state,name):
    return state/'cache'/(identity([policy.VERSION,name])+'.json')


def locked_packets(state):
    data,_=eclipse_data(state); p=policy.plan(); result={}
    if identity(data)!=p['input_sha256']:
        raise ConfigurationFailure('luna_original_input_changed')
    for name in ('assessment','check'):
        c,body=pairs.body(data,judge=name=='check'); op=p['operations'][name]
        if identity(c)!=op['contract_sha256'] or identity(body)!=op['body_sha256']:
            raise ConfigurationFailure('luna_locked_prompt_schema_or_input_changed')
        if len(encoded(body))>p['maximum_wire_bytes']:
            raise Deferred('luna_complete_wire_bound_no_truncation')
        result[name]=(c,body)
    return data,result


def preflight(state,counter=None):
    from tools.team_recommender_budget import ExperimentLedger
    policy.remaining_fits(ExperimentLedger(state/'ledger.json').read())
    data,packets=locked_packets(state)
    checkpoint=json.loads((state/'checkpoint.json').read_bytes())
    rows=checkpoint['phase2_token_preflight']['rows']
    if len(rows)<186 or identity(rows[:186])!=policy.PRIOR_COUNT_ROWS:
        raise ConfigurationFailure('luna_prior_native_count_history')
    body=packets['check'][1]; key=identity(count_projection(body))
    if not any(r['key']==key for r in rows) and (len(rows)>=190 or
            sum(r['id'].startswith(policy.VERSION+':') for r in rows)>=2):
        raise Deferred('luna_native_count_authority_exhausted')
    native=(counter or Counter(state)).count({'id':policy.VERSION+':check','body':body})
    values={}
    for name,(_,body) in packets.items():
        op=policy.plan()['operations'][name]
        n=math.ceil(native*1.2)+1024 if name=='check' else len(encoded(body))+1024
        amount=n*2+12000*10 if name=='check' else (n+4)//5+(24000*6+4)//5
        if n>op['input_token_ceiling'] or amount>op['maximum_microusd']:
            raise Deferred('luna_complete_two_packet_sizing_failure')
        values[name]={'body_sha256':identity(body),'wire_bytes':len(encoded(body)),
            'reserved_input_tokens':n,'reserved_output_tokens':op['output_token_ceiling'],
            'reserved_microusd':amount,
            **({'native_input_tokens':native,'native_count_key':key} if name=='check' else {})}
    if sum(v['reserved_microusd'] for v in values.values())>500000:
        raise Deferred('luna_both_operations_do_not_fit')
    result={'version':policy.VERSION,'kind':'complete_two_operation_preflight',
            'input_sha256':identity(data),'packets':values,'paid_dispatches':0}
    target=result_path(state,'preflight')
    if target.exists() and json.loads(target.read_bytes())!=result:
        raise ConfigurationFailure('luna_preflight_changed')
    atomic_json(target,result);existing.checkpoint(state)
    return result


class RepairRunner(Runner):
    def request_provider(self,purpose,body):
        if purpose not in ('cb-lc-assessment','cb-lc-check'):
            raise ConfigurationFailure('luna_only_two_named_operations')
        return policy.plan()['operations'][purpose.removeprefix('cb-lc-')]['provider']

    def has_unknown_request(self):
        try:
            policy.history(self.ledger.read())
        except (Deferred,ConfigurationFailure):
            return True
        return False

    def request_usage(self,provider,payload,model):
        payload={**payload,'usage':diagnostics.safe_usage(payload.get('usage'))}
        if provider=='openai':
            usage=normalize_usage(provider,payload)
            if usage is None:
                raise ValueError('luna_usage_missing')
            return usage,cost_microusd(usage,{'input':.2,'cached':.02,'cache_write':.25,'output':1.2})
        return super().request_usage(provider,payload,model)

    def read_provider_response(self,response,provider,body,receipt):
        return diagnostics.read_response(self,response,provider,body,receipt)

    def finish_diagnostics(self,receipt):
        diagnostics.finish(self.state,receipt)

    def failure_diagnostics(self,error,receipt):
        import re
        code=str(error)
        if re.fullmatch(r'[a-z][a-z0-9_]{0,99}',code):
            receipt['semantic_diagnostic']={'code':code}

    def reservation_cost(self,purpose,body,metadata):
        policy.remaining_fits(self.ledger.read())
        name=metadata['luna_operation']
        prior=json.loads(result_path(self.state,'preflight').read_bytes())
        row=prior['packets'][name]
        if prior['version']!=policy.VERSION or row['body_sha256']!=identity(body):
            raise ConfigurationFailure('luna_preflight_identity')
        n=row['reserved_input_tokens']
        if name=='assessment':
            if n!=len(encoded(body))+1024:
                raise ConfigurationFailure('luna_byte_reservation_mismatch')
            amount=(n+4)//5+(24000*6+4)//5
        else:
            checkpoint=json.loads((self.state/'checkpoint.json').read_bytes())
            counts=[r for r in checkpoint['phase2_token_preflight']['rows']
                if r['key']==identity(count_projection(body))]
            if len(counts)!=1 or counts[0]['status']!='complete' or n!=math.ceil(counts[0]['input_tokens']*1.2)+1024:
                raise ConfigurationFailure('luna_exact_native_count_missing')
            amount=n*2+12000*10
        if amount!=row['reserved_microusd']:
            raise ConfigurationFailure('luna_preflight_cost_mismatch')
        return n,amount,{}

    def perform(self,name):
        data,packets=locked_packets(self.state); c,body=packets[name]
        if name=='check':
            # Reuse the complete exact cache only; this call can never create a
            # new assessment. Failed, missing or uncertain assessments stop it.
            self.accepted_assessment(data,packets['assessment'])
        op=policy.plan()['operations'][name]
        logical=[policy.VERSION,name,identity(c),identity(data)]
        result=self.request('cb-lc-'+name,logical,body,
            lambda v,cached:pairs.validate_cached(v,data,judge=name=='check') if cached else
                pairs.parse(v,op['provider'],data,judge=name=='check'),
            ceiling=op['input_token_ceiling'],repair_metadata={
                'luna_repair':policy.VERSION,'luna_operation':name,'repair_of':op['repair_of'],
                'pair_contract_sha256':identity(c),'packet_sha256':policy.plan()['source_inputs_sha256']})
        return {'version':policy.VERSION,'operation':name,'request_id':self.used[-1]['request_id'],
            'body_sha256':identity(body),'value':result,'cache_hit':self.used[-1]['cache_hit']}

    def accepted_assessment(self,data,packet):
        from tools.contextual_team_executor import validate_cache_identity
        c,body=packet
        key=identity([existing.AUTHORIZATION_ID,'contextual-v1',
            [policy.VERSION,'assessment',identity(c),identity(data)]])
        rows=[r for r in self.ledger.read()['requests'] if r['key']==key]
        target=self.state/'cache'/(key+'.json')
        if len(rows)!=1 or rows[0]['status']!='valid' or not target.exists():
            raise RecoveryRequired('luna_complete_assessment_unavailable_skip_check')
        cached=json.loads(target.read_bytes())
        validate_cache_identity(cached,rows[0],body,'openai')
        return pairs.validate_cached(cached['value'],data)


def run(args):
    existing.trusted_environment()
    requested=json.loads(os.environ['CONTEXTUAL_CHECK'])
    name=requested.get('luna_contract_repair')
    if (set(requested)!={'luna_contract_repair'} or name not in ('preflight','assessment','check')
        or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB','PACKET_HASH','PACKET_COMMIT'))):
        raise ConfigurationFailure('luna_exact_manual_operation')
    if args.action=='prepare':
        ledger=existing.restore(args.state,existing.policy())
        policy.install_authority(args.state,existing.api)
        policy.remaining_fits(ledger.read());locked_packets(args.state)
        if name=='check':
            data,packets=locked_packets(args.state)
            RepairRunner(args.state,{}).accepted_assessment(data,packets['assessment'])
        existing.checkpoint(args.state)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
                stream.write('text_provider='+('openai' if name=='assessment' else 'anthropic')+'\n')
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,
            'run_id':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],
            'code_sha':os.environ['GITHUB_SHA'],'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),
            'luna_repair':policy.VERSION,'operation':name,'maximum_new_microusd':500000,
            'maximum_new_attempts':2,'retained_unknown_hold_microusd':146074,
            'preserved_microusd':1267862,'preserved_attempts':2})
        return
    result=None
    try:
        result=preflight(args.state) if name=='preflight' else RepairRunner(args.state,{}).perform(name)
    finally:
        existing.checkpoint(args.state)
        atomic_json(args.result,result or {'version':policy.VERSION,'operation':name,
            'status':'incomplete','automatic_retries':0})
