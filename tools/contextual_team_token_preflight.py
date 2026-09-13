"""Bounded free tokenization, never Messages inference or embedding generation.

The native endpoint reports an estimate, so costs include a 20% cushion plus
structural/future-text byte bounds. All input is approved protected-main data.
This shares checkpoint ownership but cannot reserve or spend a provider dollar.
"""
import hashlib
import json
import math
import os
import threading
from pathlib import Path
import requests
from tools import team_recommender_executor as existing
from tools.contextual_team_policy import inputs, ROOT
from tools.contextual_team_executor import scope_inputs, RecoveryRequired
from tools.contextual_team_demand_contract import contract, projected_inputs
from tools.offline_ai import request_body
from tools.offline_spend import identity, encoded, atomic_json, ConfigurationFailure

SOURCE_SHA='56a102550e8a231ad893bfe97dc94810c66fe2a6a20c433b4a75be00d0a24e9d'
VERSION='contextual-phase2-token-preflight-v1'
ENDPOINT='https://api.anthropic.com/v1/messages/count_tokens'
MAX_COUNT_HTTP_ATTEMPTS=190


def source_inputs():
    raw=(ROOT/'config/contextual_team/phase2-source-inputs-v1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA:raise ConfigurationFailure('phase2_source_bytes_changed')
    value=json.loads(raw);base=inputs()
    if value['registry_generation']!=base['registry_generation'] or value['roster_id']!=base['roster_id']:
        raise ConfigurationFailure('phase2_audited_profile_identity')
    return value


def count_projection(body):
    if body.get('model')!='claude-sonnet-5' or set(body)-{'model','system','messages','output_config','max_tokens','thinking'}:
        raise ConfigurationFailure('phase2_unapproved_counter_shape')
    return {k:v for k,v in body.items() if k in ('model','system','messages','output_config')}


def count_body(text):
    return {'model':'claude-sonnet-5','messages':[{'role':'user','content':text}]}


def inventory():
    base=inputs();sources=source_inputs();result=[]
    # Individual token counts permit a true maximum over any 12-person retrieval
    # set. This is deterministic sizing, not 155 researcher assessments.
    for person in base['people']:
        result.append({'id':'profile:'+person['person_id'],'body':count_body(json.dumps(person,ensure_ascii=False))})
    for scope in sources['scopes']:
        source=scope_inputs(scope)
        c=contract('decomposition',source)
        full=request_body(c['route'],c['settings'],c['prompt'],projected_inputs('decomposition',source),c['schema'])
        result.append({'id':scope['id']+':decomposition','body':count_projection(full)})
        for stage in ('adjudication','verification'):
            # Unknown future interpretation, people and wire references are
            # excluded here and separately bounded, never guessed or truncated.
            from tools.contextual_team_references import contract as scientific
            c=scientific(stage)
            result.append({'id':scope['id']+':'+stage,'body':{
                'model':'claude-sonnet-5','system':c['prompt'],
                'messages':[{'role':'user','content':json.dumps(source,ensure_ascii=False)}]}})
    if len(result)>MAX_COUNT_HTTP_ATTEMPTS:raise ValueError('phase2_counter_inventory_bound')
    return result


class Counter:
    _guard=threading.RLock()

    def __init__(self,state,post=requests.post):
        self.state=Path(state);self.path=self.state/'checkpoint.json';self.post=post

    def count(self,item):
        # Cloud processes are serialized by the existing authorization workflow.
        # Also serialize any local callers before inspecting the durable row.
        with self._guard:return self._count(item)

    def _count(self,item):
        body=count_projection(item['body']);key=identity(body)
        checkpoint=json.loads(self.path.read_bytes())
        if checkpoint['authorization_id']!=existing.AUTHORIZATION_ID:raise ValueError('counter_authorization_identity')
        saved=checkpoint.get('phase2_token_preflight',{'version':VERSION,'source_sha256':SOURCE_SHA,'rows':[]})
        if saved['version']!=VERSION or saved['source_sha256']!=SOURCE_SHA:raise ValueError('counter_checkpoint_identity')
        rows=[r for r in saved['rows'] if r['key']==key]
        if rows:
            if len(rows)!=1 or rows[0]['status']!='complete':raise RecoveryRequired('counter_prior_incomplete_no_automatic_repeat')
            return rows[0]['input_tokens']
        if len(saved['rows'])>=MAX_COUNT_HTTP_ATTEMPTS:raise ValueError('counter_finite_http_limit')
        secret=os.environ.get('ANTHROPIC_API_KEY')
        if not secret:raise ConfigurationFailure('counter_credential_missing')
        row={'id':item['id'],'key':key,'status':'dispatched_or_uncertain','metered_inference':False,'charged_microusd':0}
        saved['rows'].append(row);existing.checkpoint(self.state,token_preflight=saved)
        response=self.post(ENDPOINT,headers={'Content-Type':'application/json','x-api-key':secret,
            'anthropic-version':'2023-06-01','User-Agent':'FundingFinder-TokenSizing/1.0'},json=body,
            timeout=(10,30),allow_redirects=False,stream=True)
        payload=json.loads(existing.bounded_response(response,2048))
        if set(payload)!={'input_tokens'} or type(payload['input_tokens']) is not int or not 0<payload['input_tokens']<=200000:
            raise ValueError('invalid_native_token_count')
        row.update(status='complete',input_tokens=payload['input_tokens']);existing.checkpoint(self.state,token_preflight=saved)
        return payload['input_tokens']


def run(args):
    existing.trusted_environment()
    requested=json.loads(os.environ['CONTEXTUAL_CHECK'])
    if requested!={'phase2_token_preflight':SOURCE_SHA} or any(os.environ.get(k) for k in ('CONTEXTUAL_JOB','PACKET_HASH','PACKET_COMMIT')):
        raise ConfigurationFailure('phase2_exact_token_inventory_required')
    items=inventory()
    if args.action=='prepare':
        ledger=existing.restore(args.state,existing.policy());rows=ledger.read()['requests']
        if len(rows)<662 or any(r['status']=='reserved_unknown' for r in rows):raise RecoveryRequired('phase2_starting_accounting_unavailable')
        existing.checkpoint(args.state)
        atomic_json(args.reservation,{'authorization_id':existing.AUTHORIZATION_ID,'run_id':os.environ['GITHUB_RUN_ID'],
            'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'code_sha':os.environ['GITHUB_SHA'],
            'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),'source_sha256':SOURCE_SHA,
            'operation':VERSION,'inventory_sha256':identity(items),'count_http_maximum':MAX_COUNT_HTTP_ATTEMPTS,
            'maximum_new_metered_attempts':0,'maximum_new_microusd':0})
        return
    before=(args.state/'ledger.json').read_bytes();counter=Counter(args.state);values={}
    try:
        for item in items:values[item['id']]=counter.count(item)
    finally:
        if (args.state/'ledger.json').read_bytes()!=before:raise ValueError('token_preflight_changed_paid_ledger')
        atomic_json(args.result,{'version':VERSION,'source_sha256':SOURCE_SHA,'inventory_sha256':identity(items),
            'native_counts':values,'completed':len(values),'expected':len(items),'metered_attempts':0,'charged_microusd':0,
            'count_is_estimate':True,'required_cost_cushion':'20% plus separate structural/future-input byte bounds; not yet a paid execution lock'})
        existing.checkpoint(args.state)
