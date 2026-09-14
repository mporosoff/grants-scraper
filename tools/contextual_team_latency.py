"""Finite comparison and one explicitly selected normal DOE demand workflow."""
import json
import math
import time
from pathlib import Path
from tools.contextual_team_executor import Runner, RecoveryRequired, scope_inputs
from tools.contextual_team_latency_policy import RELEASE, plan, operation, history, remaining_fits
from tools import contextual_team_latency_contract as wire
from tools import contextual_team_requirements as requirements
from tools.contextual_team_token_preflight import Counter, count_projection
from tools.offline_spend import (identity, encoded, atomic_json, ConfigurationFailure,
                                Deferred, normalize_usage, cost_microusd)
from tools.offline_ai import response_value


def configuration():
    from tools.contextual_team_phase2 import configuration as prior
    c=prior();c.pop('phase2');c['snapshot_id']=RELEASE;c['latency']=plan()
    c['scopes']=[s for s in c['scopes'] if s['id']==plan()['workflow_scope']]
    return c


def result_path(state,name):
    return Path(state)/'cache'/(identity(['requirements-latency',RELEASE,name])+'.json')


def exact_prior(state,operation_id):
    from tools.team_recommender_budget import ExperimentLedger
    rows=[r for r in ExperimentLedger(Path(state)/'ledger.json').read()['requests']
          if r.get('phase2_operation')==operation_id]
    if len(rows)!=1 or rows[0]['status']!='valid':raise RecoveryRequired('latency_required_prior_not_valid')
    row=rows[0];p=Path(state)/'cache'/(row['key']+'.json')
    value=json.loads(p.read_bytes())
    if any(value.get(k)!=v for k,v in {'key':row['key'],'body_sha256':row['body_sha256'],
                                      'model':row['model'],'request_id':row['id']}.items()):
        raise RecoveryRequired('latency_prior_cache_identity')
    return row,value['value']


def eclipse_data(state):
    from tools.contextual_team_phase2 import configuration as prior, scope_result_path
    from tools.contextual_team_demand_contract import contract, projected_inputs, validate_resolved
    from tools.offline_ai import request_body
    config=prior();scope=next(s for s in config['scopes'] if s['id']=='351715')
    _,interpretation=exact_prior(state,'351715:interpret')
    validate_resolved('decomposition',interpretation,scope_inputs(scope))
    graph=json.loads(scope_result_path(state,'351715').read_bytes())['value']
    if graph['graph_id']!='8bf6b1e43cf8ffbe7c175eca7c58f939ff32ec053c6b75ac350918377b808ff0':
        raise ConfigurationFailure('latency_retained_retrieval_identity')
    people={p['person_id']:p for p in config['people']}
    data=scope_inputs(scope)|{'interpretation':interpretation,
        'people':[people[pid] for pid in graph['retrieval']['shortlist']]}
    if len(data['people'])!=12 or identity(data)!='e13acb65364347fdd5e94da992105833d7d3cb7d6bdb2764f15d28674c8c58f8':
        raise ConfigurationFailure('latency_identical_complete_eclipse_input')
    row,assessment=exact_prior(state,'351715:assess');c=contract('adjudication',data)
    original=request_body(c['route'],c['settings'],c['prompt'],json.loads(encoded(projected_inputs('adjudication',data))),c['schema'])
    original['max_tokens']=24000
    if identity(original)!=row['body_sha256']:raise ConfigurationFailure('latency_original_wire_reproduction')
    validate_resolved('adjudication',assessment,data)
    return data,assessment


class LatencyRunner(Runner):
    def __init__(self,*args,counter_post=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.counter=Counter(self.state,**({'post':counter_post} if counter_post else {}))
        self.timings=[];self.effective_contracts={};self.interpretation=None

    def request_provider(self,purpose,body):
        if not purpose.startswith('cb-lr-'):raise ConfigurationFailure('latency_only_named_purpose')
        return {'claude-sonnet-5':'anthropic','gpt-5.6-luna':'openai','voyage-4-large':'voyage'}[body['model']]

    def request_usage(self,provider,payload,model):
        if provider!='openai':return super().request_usage(provider,payload,model)
        usage=normalize_usage(provider,payload)
        if usage is None:raise ValueError('latency_openai_usage_missing')
        return usage,cost_microusd(usage,{'input':.2,'cached':.02,'cache_write':.25,'output':1.2})

    def request(self,purpose,logical,body,check,**kwargs):
        if purpose=='cb-documents':raise RecoveryRequired('latency_missing_document_vector_no_repurchase')
        if purpose=='cb-query':purpose='cb-lr-query'
        name=purpose.removeprefix('cb-lr-');op=operation(name)
        provider=self.request_provider(purpose,body)
        output=body.get('max_tokens',body.get('max_output_tokens',0))
        if output!=op['output_token_ceiling']:raise ConfigurationFailure('latency_exact_output_capacity')
        if provider=='anthropic':
            check_mode=name.endswith('check')
            if body.get('thinking')!=({'type':'disabled'} if check_mode else {'type':'adaptive'}):
                raise ConfigurationFailure('latency_explicit_thinking_mode')
            if not check_mode and body['output_config'].get('effort')!='medium':
                raise ConfigurationFailure('latency_explicit_medium_required')
            if any(k in body for k in ('temperature','top_p','top_k')):raise ConfigurationFailure('latency_unapproved_sampling')
        elif provider=='openai':
            if (body.get('reasoning')!={'effort':'low'} or body.get('store') is not False
                or body['text'].get('verbosity')!='low' or body['text']['format'].get('strict') is not True):
                raise ConfigurationFailure('latency_exact_openai_settings')
        kwargs['ceiling']=plan()['openai_input_token_ceiling'] if provider=='openai' else op['input_token_ceiling']
        kwargs['repair_metadata']={'latency_lock':RELEASE,'latency_operation':name,'latency_model':body['model'],
            'latency_effort':'query' if provider=='voyage' else 'low' if provider=='openai' else 'disabled' if name.endswith('check') else 'medium',
            'packet_sha256':plan()['source_inputs_sha256']}
        return super().request(purpose,logical,body,check,**kwargs)

    def reservation_cost(self,purpose,body,metadata):
        if len(encoded(body))>plan()['maximum_wire_bytes']:raise Deferred('latency_complete_wire_capacity')
        history(self.ledger.read());remaining_fits(self.ledger.read())
        if any(r.get('latency_operation')==metadata['latency_operation'] for r in self.ledger.read()['requests']):
            raise RecoveryRequired('latency_claimed_operation_no_count_or_paid_repeat')
        provider=self.request_provider(purpose,body)
        if provider=='voyage':
            n=len(encoded(body))+1024;return n,(n*3+24)//25,{}
        if provider=='openai':
            # UTF-8 bytes plus framing is a conservative tokenizer-independent
            # bound for this text-only packet, not an asserted measured count.
            n=len(encoded(body))+1024
            return n,(n+4)//5+(body['max_output_tokens']*6+4)//5,{}
        from tools.contextual_team_cost import no_provider_cache
        no_provider_cache(body);projection=count_projection(body);key=identity(projection)
        native=self.counter.count({'id':'latency:'+metadata['latency_operation'],'body':body})
        n=math.ceil(native*1.2)+1024
        return n,n*2+body['max_tokens']*10,{'native_count_key':key,'count_body_sha256':key,'native_input_tokens':native}

    def scientific_request(self,stage,data,name,route,repaired=False):
        if stage!='decomposition':
            from tools.contextual_team_cost import generated_input_bounds
            generated_input_bounds(data['interpretation'],data.get('proposed_edges'))
        start=time.monotonic();c,body=wire.body(stage,data,route,operation(name)['output_token_ceiling'],repaired)
        self.effective_contracts[stage]=identity(c)
        value=self.request('cb-lr-'+name,[RELEASE,name,identity(c),identity(data)],body,
            lambda value,cached:wire.validate_resolved(stage,value,data,repaired) if cached
            else wire.resolve(stage,response_value(c['route']['provider'],value),data,repaired))
        self.timings.append({'stage':name,'elapsed_seconds':round(time.monotonic()-start,6),
                             'cache_hit':self.used[-1]['cache_hit'],'request_id':self.used[-1]['request_id']})
        return value

    def selected_route(self):
        value=json.loads(result_path(self.state,'selection').read_bytes())
        if value.get('release_id')!=RELEASE or value.get('route') not in ('S','L'):
            raise ConfigurationFailure('latency_route_selection_required')
        from tools.contextual_team_latency_check import validate_selection
        validate_selection(self.state,value)
        return value['route']

    def scientific(self,stage,data,scope,extension=False):
        if extension or scope['id']!='363302:a-1':raise ConfigurationFailure('latency_only_one_doe_workflow')
        name={'decomposition':'interpret','adjudication':'assess','verification':'verify'}[stage]
        value=self.scientific_request(stage,data,name,self.selected_route(),True)
        if stage=='decomposition':self.interpretation=value
        return value

    def retrieval_roles(self,interpretation):return requirements.active_roles(interpretation)

    def graph_metadata(self,graph):
        requirements.graph_metadata(graph,self.interpretation)
        graph['contracts']=self.effective_contracts
        graph['execution_capacity']={'version':RELEASE,'model_route':self.selected_route(),
                                    'automatic_retries':0,'separate_verifier':True}
        return graph

    def run_scope(self,scope,extension_person=None):
        if extension_person:raise ConfigurationFailure('latency_no_paid_extension')
        history(self.ledger.read());remaining_fits(self.ledger.read());self.selected_route()
        value=super().run_scope(scope)
        if len(encoded(value))>190000:raise Deferred('latency_complete_graph_delivery_bound')
        atomic_json(result_path(self.state,'DOE'),{'release_id':RELEASE,'value':value})
        return value
