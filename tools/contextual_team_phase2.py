"""Normal cold demand under the existing finite authorization and graph contract.

Only protected-main code resolves the reviewed manifest and audited evidence.
Exact complete packets are counted before metered dispatch, never truncated.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
import requests
from tools.contextual_team_policy import ROOT, INPUT_SHA, inputs
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs
from tools.contextual_team_demand_contract import contract, projected_inputs, resolve, validate_resolved, VERSION
from tools.contextual_team_cost import generated_input_bounds, no_provider_cache
from tools.contextual_team_token_preflight import Counter
from tools.offline_ai import request_body, response_value
from tools.offline_spend import identity, encoded, atomic_json, Deferred, ConfigurationFailure

RELEASE='3d15781cc4c919bfe844a674f0354f5241cf5dafc03f6ef11c27f84c15f7de60'
STAGES={'decomposition':'interpret','adjudication':'assess','verification':'verify'}


def plan():
    value=json.loads((ROOT/'config/contextual_team/phase2-v1.json').read_bytes())
    release=value.pop('release_id')
    if release!=RELEASE or identity(value)!=release:raise ConfigurationFailure('phase2_plan_identity')
    value['release_id']=release
    if value['base_inputs_sha256']!=INPUT_SHA or value['scientific_contract']!=VERSION:
        raise ConfigurationFailure('phase2_fixed_contract_identity')
    return value


def configuration():
    p=plan();raw=(ROOT/'config/contextual_team/phase2-source-inputs-v2.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=p['source_inputs_sha256']:raise ConfigurationFailure('phase2_source_identity')
    sources=json.loads(raw);base=deepcopy(inputs())
    if sources['registry_generation']!=base['registry_generation'] or sources['roster_id']!=base['roster_id']:
        raise ConfigurationFailure('phase2_registry_or_roster_identity')
    if any(s['source_id']!=identity(scope_inputs(s)) for s in sources['scopes']):
        raise ConfigurationFailure('phase2_scientific_source_identity')
    base.update(scopes=sources['scopes'],snapshot_id=RELEASE,phase2=p)
    return base


def operation(scope_id,stage):
    return next((r for r in plan()['operations'] if r['scope_id']==scope_id and r['stage']==stage),None)


def check_history(state,p):
    rows=state['requests'];n=p['prior_attempts']
    if len(rows)<n or identity(rows[:n])!=p['prior_request_rows_sha256']:
        raise RecoveryRequired('phase2_original_ledger_history_not_preserved')
    if any(r['status']=='reserved_unknown' for r in rows):
        raise RecoveryRequired('phase2_outstanding_dispatch_requires_recovery')


def check_reservation(state,provider,metadata,amount,input_tokens,output_tokens):
    p=plan();op=next((r for r in p['operations'] if r['id']==metadata.get('phase2_operation')),None)
    check_history(state,p)
    if (metadata.get('phase2_lock')!=RELEASE or metadata.get('packet_sha256')!=p['source_inputs_sha256']
        or not op or metadata.get('purpose')!=op['purpose'] or provider!=op['provider']):
        raise ConfigurationFailure('phase2_unapproved_operation')
    if (input_tokens>op['input_token_ceiling'] or output_tokens>op['output_token_ceiling']
        or (op['stage'] in ('interpret','assess','verify') and output_tokens!=op['output_token_ceiling'])):
        raise Deferred('phase2_complete_packet_capacity_no_truncation')
    if provider=='anthropic':
        native=metadata.get('native_input_tokens')
        if type(native) is not int or native<1 or input_tokens!=math.ceil(native*1.2)+1024:
            raise ConfigurationFailure('phase2_native_count_reservation')
        if metadata.get('native_count_key')!=metadata.get('count_body_sha256'):
            raise ConfigurationFailure('phase2_native_count_identity')
    rows=state['requests'];phase=[r for r in rows if r.get('phase2_lock')==RELEASE]
    if any(r.get('phase2_operation')==op['id'] for r in phase):
        raise RecoveryRequired('phase2_logical_operation_already_claimed_no_rekey')
    spent=sum(r['charged_microusd'] for r in rows)
    if (spent+amount>10_000_000-p['preserved_microusd'] or len(rows)>=690-p['preserved_attempts']
        or sum(r['charged_microusd'] for r in phase)+amount>p['maximum_new_microusd']
        or len(phase)>=p['maximum_new_attempts']):
        raise Deferred('phase2_ceiling_or_protected_reserve')
    claimed={r.get('phase2_operation') for r in phase}
    remaining=[r for r in p['operations'] if r['id'] not in claimed and r['id']!=op['id']]
    # Reserve all remaining operations, including both output-check requests per
    # scope. Unneeded operations conservatively remain in this envelope.
    if (spent+amount+sum(r['maximum_microusd'] for r in remaining)>10_000_000-p['preserved_microusd']
        or len(rows)+1+len(remaining)>690-p['preserved_attempts']):
        raise Deferred('phase2_remaining_complete_inventory_does_not_fit')
    minimum=(input_tokens*3+24)//25 if provider=='voyage' else input_tokens*2+output_tokens*10
    if amount<minimum or amount>op['maximum_microusd']:raise ValueError('phase2_invalid_request_reservation')


def ensure_remaining_plan_fits(state):
    p=plan();rows=state['requests'];claimed={r.get('phase2_operation') for r in rows if r.get('phase2_lock')==RELEASE}
    check_history(state,p)
    remaining=[r for r in p['operations'] if r['id'] not in claimed]
    if (sum(r['charged_microusd'] for r in rows)+sum(r['maximum_microusd'] for r in remaining)>10_000_000-p['preserved_microusd']
        or len(rows)+len(remaining)>690-p['preserved_attempts']):
        raise Deferred('phase2_complete_inventory_or_reserve_unavailable')


def scope_result_path(state,scope_id):
    return Path(state)/'cache'/(identity(['phase2-scope-result',RELEASE,scope_id])+'.json')


class Phase2Runner(Runner):
    def __init__(self,*args,counter_post=requests.post,**kwargs):
        super().__init__(*args,**kwargs)
        if self.configuration.get('phase2',{}).get('release_id')!=RELEASE:raise ConfigurationFailure('phase2_runner_configuration')
        self.counter=Counter(self.state,post=counter_post);self.scope_id=None;self.timings=[];self.effective_contracts={}

    def request(self,purpose,logical,body,check,**kwargs):
        if purpose=='cb-documents':raise RecoveryRequired('phase2_missing_audited_document_vectors_no_repurchase')
        if purpose=='cb-query':purpose='cb-p2-query'
        if not purpose.startswith('cb-p2-'):raise ConfigurationFailure('phase2_unapproved_runner_purpose')
        op=operation(self.scope_id,purpose.removeprefix('cb-p2-'))
        if op is None:raise ConfigurationFailure('phase2_unapproved_scope_operation')
        kwargs['ceiling']=op['input_token_ceiling']
        kwargs['repair_metadata']={'phase2_lock':RELEASE,'phase2_operation':op['id'],
                                  'packet_sha256':plan()['source_inputs_sha256'],**kwargs.get('repair_metadata',{})}
        return super().request(purpose,logical,body,check,**kwargs)

    def reservation_cost(self,purpose,body,metadata):
        op=operation(self.scope_id,purpose.removeprefix('cb-p2-'));p=plan()
        if len(encoded(body))>p['maximum_wire_bytes']:raise Deferred('phase2_complete_wire_packet_too_large')
        if any(r.get('phase2_operation')==op['id'] for r in self.ledger.read()['requests']):
            raise RecoveryRequired('phase2_operation_already_claimed_no_new_count_or_paid_dispatch')
        if op['provider']=='voyage':
            bound=len(encoded(body))+1024
            return bound,(bound*3+24)//25,{}
        no_provider_cache(body)
        from tools.contextual_team_token_preflight import count_projection
        projection=count_projection(body);key=identity(projection)
        native=self.counter.count({'id':'phase2:'+op['id']+':'+identity(body),'body':body})
        bound=math.ceil(native*1.2)+1024
        return bound,bound*2+body['max_tokens']*10,{'native_count_key':key,'count_body_sha256':key,'native_input_tokens':native}

    def scientific(self,stage,data,scope,extension=False):
        if extension:raise ConfigurationFailure('phase2_new_extension_not_authorized')
        start=time.monotonic();self.scope_id=scope['id']
        if stage!='decomposition':generated_input_bounds(data['interpretation'],data.get('proposed_edges'))
        c=contract(stage,data);self.effective_contracts[stage]=identity(c)
        body=request_body(c['route'],c['settings'],c['prompt'],json.loads(encoded(projected_inputs(stage,data))),c['schema'])
        purpose='cb-p2-'+STAGES[stage]
        value=self.request(purpose,[purpose,scope['source_id'],identity(c),identity(data)],body,
            lambda value,cached:validate_resolved(stage,value,data) if cached else resolve(stage,response_value('anthropic',value),data))
        self.timings.append({'stage':stage,'cache':'exact_stage' if self.used[-1]['cache_hit'] else 'new_request','seconds':time.monotonic()-start})
        return value

    def vectors(self,documents,role,scope=None):
        start=time.monotonic();before=len(self.ledger.read()['requests'])
        result=super().vectors(documents,role,scope)
        self.timings.append({'stage':'query_embedding' if role=='query' else 'document_vector_reuse',
                             'rows':len(result),'new_attempts':len(self.ledger.read()['requests'])-before,'seconds':time.monotonic()-start})
        return result

    def graph_metadata(self,graph):
        graph['contracts']=dict(self.effective_contracts)
        scope=next(s for s in self.configuration['scopes'] if s['id']==self.scope_id)
        graph['catalog_source_id']=scope['catalog_source_id']
        graph['source_receipt_id']=identity(scope['source_receipt'])
        graph['execution_capacity']={'version':VERSION,'output_tokens':{'decomposition':8000,'adjudication':16000,'verification':24000},
            'paid_retry':'none automatically; durable logical claims remain authoritative'}
        return graph

    def run_scope(self,scope,extension_person=None):
        if extension_person:raise ConfigurationFailure('phase2_new_extension_not_authorized')
        self.scope_id=scope['id'];ensure_remaining_plan_fits(self.ledger.read())
        result=super().run_scope(scope,None)
        if len(encoded(result))>plan()['maximum_graph_bytes']:raise Deferred('phase2_complete_graph_resource_bound')
        atomic_json(scope_result_path(self.state,scope['id']),{'kind':'contextual_scope_result','snapshot_id':RELEASE,
            'source_id':scope['source_id'],'value':result})
        return result
