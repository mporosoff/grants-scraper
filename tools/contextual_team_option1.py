"""Narrow reviewed continuation: two repairs, one extension, two possible checks.

No new ledger, models, retrieval, source interpretation or failed-request replay.
"""
from copy import deepcopy
import json
from pathlib import Path
import time
from tools.contextual_team_policy import inputs, ROOT, INPUT_SHA
from tools.contextual_team_executor import Runner, RecoveryRequired
from tools.contextual_team_references import contract, projected_inputs, resolve, validate_resolved
from tools.contextual_team_cost import generated_input_bounds
from tools.offline_ai import request_body, response_value
from tools.offline_spend import identity, encoded, Deferred, ConfigurationFailure


def plan():
    value=json.loads((ROOT/'config/contextual_team/option1-v1.json').read_bytes())
    release=value.pop('release_id')
    if release!=identity(value):raise ConfigurationFailure('option1_plan_identity_conflict')
    value['release_id']=release
    if value['input_sha256']!=INPUT_SHA or any(identity(contract(s))!=cid for s,cid in value['contract_ids'].items()):
        raise ConfigurationFailure('option1_contract_or_input_conflict')
    return value


def configuration_for_job(job):
    from tools.contextual_team_phase2 import RELEASE as phase2_release, configuration as phase2_configuration
    if job['release_id']==phase2_release:
        config=phase2_configuration()
        if job.get('person_id') or job['scope_id'] not in {s['id'] for s in config['scopes']}:
            raise ValueError('outside_locked_phase2_jobs')
        return config
    config=inputs();p=plan()
    if job['release_id']==config['snapshot_id']:return config
    if job['release_id']!=p['release_id']:raise ValueError('unapproved_option1_release')
    if job['scope_id'] not in {s['id'] for s in p['scopes']} or (job['person_id'] and
       (job['scope_id']!='332894' or job['person_id']!=p['extension']['person_id'])):
        raise ValueError('outside_locked_option1_jobs')
    config=deepcopy(config);config['snapshot_id']=p['release_id'];config['option1']=p
    config['budget']['contract_ids']={**p['contract_ids'],'decomposition':inputs()['budget']['contract_ids']['decomposition']}
    return config


def check_reservation(state,provider,metadata,amount,input_tokens,output_tokens):
    p=plan();rows=state['requests'];purpose=metadata.get('purpose')
    operation=next((x for x in p['operations'] if x['purpose']==purpose),None)
    if not operation or provider!='anthropic' or metadata.get('option1_release')!=p['release_id'] or metadata.get('repair_of')!=operation['repair_of']:
        raise ConfigurationFailure('unapproved_option1_operation')
    if metadata.get('packet_sha256')!=INPUT_SHA or output_tokens!=operation['max_output_tokens']:
        raise ConfigurationFailure('option1_packet_or_capacity_conflict')
    if input_tokens>operation['input_token_bound'] or amount>operation['maximum_microusd'] or amount<input_tokens*2+output_tokens*10:
        raise Deferred('option1_complete_packet_does_not_fit')
    task=[r for r in rows if r.get('purpose','').startswith('cb-o1-')]
    if any(r.get('purpose')==purpose for r in task):raise Deferred('option1_operation_already_claimed_no_rekey')
    if operation['repair_of']:
        original=[r for r in rows if r['id']==operation['repair_of']]
        if len(original)!=1 or original[0]['status']!='failed' or not original[0].get('usage'):
            raise RecoveryRequired('option1_original_response_not_confirmed_terminal')
        if metadata['body_sha256']==original[0].get('body_sha256'):
            raise ConfigurationFailure('option1_reexecution_requires_actual_contract_change')
    if any(r['status']=='reserved_unknown' for r in rows):raise RecoveryRequired('option1_uncertain_request_preserved')
    if len(rows)<p['starting_attempts'] or sum(r['charged_microusd'] for r in rows)<p['starting_spend_microusd']:
        raise RecoveryRequired('option1_checkpoint_precedes_authorization')
    if (len(rows)>=690-p['preserved_attempts'] or len(task)>=p['maximum_new_attempts'] or
        sum(r['charged_microusd'] for r in rows)+amount>10_000_000-p['preserved_microusd'] or
        sum(r['charged_microusd'] for r in task)+amount>p['maximum_new_microusd']):
        raise Deferred('option1_continuation_or_preserved_reserve_exhausted')


def ensure_remaining_plan_fits(state,p):
    rows=state['requests'];claimed={r.get('purpose') for r in rows}
    remaining=[o for o in p['operations'] if o['purpose'] not in claimed]
    if (sum(r['charged_microusd'] for r in rows)+sum(o['maximum_microusd'] for o in remaining)>10_000_000-p['preserved_microusd'] or
        len(rows)+len(remaining)>690-p['preserved_attempts']):
        raise Deferred('option1_complete_remaining_inventory_does_not_fit_preserved_balance')


class Option1Runner(Runner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.timings=[]

    def request(self,purpose,logical,body,check,**kwargs):
        if not purpose.startswith('cb-o1-'):
            from tools.team_recommender_budget import AUTHORIZATION_ID
            key=identity([AUTHORIZATION_ID,'contextual-v1',logical])
            if not any(r['key']==key and r['status']=='valid' for r in self.ledger.read()['requests']):
                raise RecoveryRequired('option1_legacy_stage_or_vector_miss_no_purchase')
        return super().request(purpose,logical,body,check,**kwargs)

    def graph_metadata(self,graph):
        p=self.configuration['option1']
        graph['execution_capacity']={'version':p['contract_version'],
            'scope_output_tokens':{'adjudication':16000,'verification':24000},
            'extension_output_tokens':{'adjudication':8000,'verification':16000},
            'repair_policy':'one linked reexecution of the two named confirmed failed stages; uncertain requests never replay'}
        if graph['scope']['id']=='332894':
            graph['contracts']['adjudication']=inputs()['budget']['contract_ids']['adjudication']
        if len(graph['people'])>len(graph['retrieval']['shortlist']):
            graph['contracts']['extension']={}
            for stage,output in [('adjudication',8000),('verification',16000)]:
                c=contract(stage);c['settings']['max_output_tokens']=output
                graph['contracts']['extension'][stage]=identity(c)
        return graph

    def scientific(self,stage,data,scope,extension=False):
        p=self.configuration['option1'];start=time.monotonic()
        retained=None if extension else p['reuse'].get(scope['id'],{}).get(stage)
        if retained:
            rows=[r for r in self.ledger.read()['requests'] if r['key']==retained['key']]
            if len(rows)!=1 or rows[0]['id']!=retained['request_id'] or rows[0]['status']!='valid' or rows[0]['body_sha256']!=retained['body_sha256']:
                raise RecoveryRequired('option1_exact_legacy_stage_unavailable')
            # The original implementation reconstructs its exact body and checks
            # original schema/semantics/cache identity. It cannot purchase a miss.
            value=super().scientific(stage,data,scope)
            self.timings.append({'stage':stage,'cache':'exact_legacy_stage','seconds':time.monotonic()-start})
            return value
        if stage=='decomposition':raise RecoveryRequired('option1_missing_interpretation_no_new_source_run')
        generated_input_bounds(data['interpretation'],data.get('proposed_edges'))
        suffix='assess' if stage=='adjudication' else 'verify'
        purpose='cb-o1-'+('extension' if extension else 'lps' if scope['id']=='332894' else 'veterans')+'-'+suffix
        operation=next((x for x in p['operations'] if x['purpose']==purpose),None)
        if not operation:raise ConfigurationFailure('option1_stage_not_in_locked_inventory')
        if extension and [x['person_id'] for x in data['people']]!=[p['extension']['person_id']]:raise ValueError('option1_extension_identity')
        c=contract(stage);c['settings']['max_output_tokens']=operation['max_output_tokens']
        body=request_body(c['route'],c['settings'],c['prompt'],json.loads(encoded(projected_inputs(data))),c['schema'])
        value=self.request(purpose,[p['release_id'],purpose,scope['source_id'],identity(data),identity(c)],body,
            lambda value,cached:validate_resolved(stage,value,data) if cached else resolve(stage,response_value('anthropic',value),data),
            ceiling=operation['input_token_bound'],repair_metadata={'option1_release':p['release_id'],'repair_of':operation['repair_of']})
        self.timings.append({'stage':purpose,'cache':'exact_stage' if self.used[-1]['cache_hit'] else 'new_request','seconds':time.monotonic()-start})
        return value
