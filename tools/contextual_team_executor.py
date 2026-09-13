"""Trusted, finite contextual stages using the existing serialized cloud ledger.

No branch code, caller prompts, arbitrary endpoints, team inventory or publication.
"""
import argparse
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import time
import requests
from tools import team_recommender_executor as existing
from tools.contextual_team_contract import contract, validate, verification_inputs, VERSION
from tools.contextual_team_cost import (text_reservation, generated_input_bounds, wire_bytes,
    QUERY_TOKEN_BOUND, JUDGE_BODY_BYTES)
from tools.contextual_team_policy import inputs as approved_inputs, INPUT_SHA
from tools.offline_ai import request_body, response_value, SchemaFailure, stop_reason
from tools.offline_spend import identity, encoded, atomic_json, Deferred, ConfigurationFailure
from tools.team_recommender_budget import ExperimentLedger, AUTHORIZATION_ID

HOST='https://funding-finder-researchers.urochestercheme.workers.dev'


class RecoveryRequired(Deferred):
    """A durable paid claim/result needs inspection; never an automatic retry."""


def scope_inputs(scope):
    incidental={'detail_checked_at','checked_at','retrieved_at','verified_on','reviewed_on',
                'last_verified','first_seen','last_seen','updated_at'}
    def scientific(value):
        if isinstance(value,dict):return {k:scientific(v) for k,v in value.items() if k not in incidental}
        if isinstance(value,list):return [scientific(v) for v in value]
        return value
    # Full receipt dates remain in the immutable input snapshot. They do not
    # repurchase an unchanged scientific interpretation or alter the prompt.
    return {'scope':scientific({k:scope[k] for k in ('id','parent_id','science','conditions','limitations')})}


def embedding_body(texts,role):
    return {'model':'voyage-4-large','input':texts,'input_type':role,
            'output_dimension':1024,'output_dtype':'float','truncation':False}


def embedding_value(payload,ids,model):
    if payload.get('model')!=model:raise ValueError('contextual_embedding_model_mismatch')
    rows=payload.get('data')
    if not isinstance(rows,list) or len(rows)!=len(ids):raise ValueError('contextual_embedding_count')
    if sorted(r.get('index',-1) for r in rows)!=list(range(len(ids))):raise ValueError('contextual_embedding_indices')
    result=[]
    for pid,row in zip(ids,sorted(rows,key=lambda r:r['index'])):
        vector=row.get('embedding')
        if (not isinstance(vector,list) or len(vector)!=1024
            or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector)
            or sum(v*v for v in vector)<=0):raise ValueError('contextual_invalid_vector')
        result.append({'id':pid,'embedding':vector})
    return result


class Runner:
    def __init__(self,state,configuration,post=requests.post,crash=lambda boundary:None):
        self.state=Path(state);self.configuration=configuration
        self.ledger=ExperimentLedger(self.state/'ledger.json');self.post=post;self.crash=crash
        self.deadline=time.monotonic()+2400;self.used=[]

    def has_unknown_request(self):
        return any(r.get('purpose','').startswith('cb-') and r['status']=='reserved_unknown'
                   for r in self.ledger.read()['requests'])

    def failure_state(self,error):
        # Exception text is not a dispatch receipt. Persisted uncertainty wins
        # even if a later cache/checkpoint failure obscures the first exception.
        if self.has_unknown_request() or isinstance(error,RecoveryRequired):return 'recovery_required'
        return 'budget_limited' if isinstance(error,Deferred) else 'failed'

    def request(self,purpose,logical,body,check,*,row_inputs=(),ceiling=None):
        if time.monotonic()>self.deadline:raise Deferred('contextual_finite_job_deadline')
        provider='voyage' if purpose in ('cb-documents','cb-query') else 'anthropic'
        if provider=='anthropic':bound,amount=text_reservation(body)
        else:
            bound=len(encoded(body))+1024;amount=(bound*3+24)//25
        if ceiling is not None and bound>ceiling:raise Deferred('contextual_complete_packet_bound_no_truncation')
        key=identity([AUTHORIZATION_ID,'contextual-v1',logical])
        body_id=identity(body);cache=self.state/'cache'/(key+'.json')
        rows=[r for r in self.ledger.read()['requests'] if r['key']==key]
        if rows:
            if (len(rows)!=1 or rows[0]['status']!='valid' or not cache.exists()
                or rows[0].get('body_sha256')!=body_id):
                raise RecoveryRequired('contextual_claimed_request_requires_recovery')
            try:
                retained=json.loads(cache.read_bytes())
                if (set(retained)!={'key','body_sha256','model','value','request_id'} or retained['key']!=key
                    or retained['body_sha256']!=body_id or retained['request_id']!=rows[0]['id']
                    or retained['model']!=body['model']):raise ValueError('cache_identity')
                value=check(retained['value'],cached=True)
            except (ValueError,KeyError,TypeError,OSError) as error:
                raise RecoveryRequired('contextual_cache_identity_requires_recovery') from error
            self.ledger.event(kind='exact_contextual_cache_hit',key=key)
            self.used.append({'key':key,'request_id':rows[0]['id'],'cache_hit':True})
            return value
        if cache.exists():raise RecoveryRequired('contextual_orphan_result_requires_recovery')
        if self.has_unknown_request():raise RecoveryRequired('contextual_outstanding_request_requires_recovery')
        secret=os.environ.get('VOYAGE_API_KEY' if provider=='voyage' else 'ANTHROPIC_API_KEY')
        if not secret:raise ConfigurationFailure('contextual_provider_credential_missing')
        token=self.ledger.reserve_experiment(provider,body['model'],2,key,amount,1,trusted_route=True,
            input_tokens=bound,output_tokens=body.get('max_tokens',0),
            execution_metadata={'packet_sha256':INPUT_SHA,'body_sha256':body_id,'purpose':purpose,
                'code_sha':os.environ['GITHUB_SHA'],'row_inputs':list(row_inputs),'judge_items':[]})
        receipt={'key':key,'request_id':token,'purpose':purpose,'body_sha256':body_id,
                 'reserved_microusd':amount,'status':'reserved_unknown','code_sha':os.environ['GITHUB_SHA']}
        self.crash('after_reserve')
        try:
            existing.checkpoint(self.state);self.crash('after_reservation_checkpoint')
            headers={'Content-Type':'application/json','User-Agent':'FundingFinder-ContextualValidation/1.0'}
            url='https://api.voyageai.com/v1/embeddings' if provider=='voyage' else 'https://api.anthropic.com/v1/messages'
            headers.update({'Authorization':'Bearer '+secret} if provider=='voyage' else
                           {'x-api-key':secret,'anthropic-version':'2023-06-01'})
            response=self.post(url,headers=headers,json=body,timeout=120,allow_redirects=False,stream=True)
            self.crash('after_dispatch')
            receipt['http_status']=response.status_code
            payload=json.loads(existing.bounded_response(response,existing.PACKET_LIMIT))
            if provider=='anthropic':receipt['provider_stop_reason']=stop_reason(payload)
            usage,charge=existing.usage_cost('embeddings' if provider=='voyage' else 'development-judge',payload,body['model'])
            receipt.update(usage=usage,charged_microusd=charge)
            if provider=='anthropic' and usage.get('cache_creation_input_tokens',0):
                raise ValueError('unexpected_provider_cache_creation_accounted_failure')
            if payload.get('model')!=body['model']:raise ValueError('contextual_returned_model_mismatch')
            value=check(payload,cached=False)
            self.crash('before_reconcile')
            self.ledger.reconcile(token,cost_usd=Decimal(charge)/1000000,usage=usage,status='valid')
            self.crash('after_reconcile')
            atomic_json(cache,{'key':key,'body_sha256':body_id,'model':body['model'],'value':value,'request_id':token})
            self.crash('after_cache')
            receipt['status']='valid'
        except (ValueError,KeyError,TypeError,OSError,requests.RequestException,Deferred) as error:
            row=next(r for r in self.ledger.read()['requests'] if r['id']==token)
            if 'charged_microusd' in receipt and row['status']=='reserved_unknown':
                self.ledger.reconcile(token,cost_usd=Decimal(receipt['charged_microusd'])/1000000,usage=receipt['usage'],status='failed')
            row=next(r for r in self.ledger.read()['requests'] if r['id']==token)
            recovery=row['status']=='reserved_unknown' or (row['status']=='valid' and not cache.exists())
            receipt.update(status=row['status'],error=type(error).__name__,
                           disposition='recovery_required' if recovery else 'failed')
            if isinstance(error,SchemaFailure):
                # Existing validator metadata contains bounded types/counts and
                # schema paths, never the rejected scientific text or reasoning.
                receipt['schema_diagnostic']=error.diagnostic
            # The irreversible ledger claim is authoritative even if this marker
            # or the receipt is lost. There is no attempt 2 or body re-key fallback.
            self.crash('after_failed_reconcile')
            if recovery:raise RecoveryRequired('contextual_paid_request_requires_recovery') from error
            raise
        finally:
            atomic_json(self.state/'receipts'/(token+'.json'),receipt)
            self.crash('after_receipt');existing.checkpoint(self.state)
        self.used.append({'key':key,'request_id':token,'cache_hit':False})
        return value

    def scientific(self,stage,data,scope,extension=False):
        c=contract(stage)
        if stage!='decomposition':generated_input_bounds(data['interpretation'],data.get('proposed_edges'))
        # A cache round trip sorts object keys. Keep the actual wire content
        # stable as well as its logical input identity on both sides of that trip.
        body=request_body(c['route'],c['settings'],c['prompt'],json.loads(encoded(data)),c['schema'])
        record=next(r for r in self.configuration['budget']['scope_rows'] if r['scope_id']==scope['id'])
        ceiling=next(r['input_token_reservation'] for r in record['stages'] if r['stage']==stage)
        purpose={'decomposition':'cb-interpret','adjudication':'cb-assess','verification':'cb-verify'}[stage]
        if extension:
            purpose='cb-extend-'+('assess' if stage=='adjudication' else 'verify')
            if len(data['people'])!=1:raise ValueError('one_contextual_extension_person_required')
            if stage=='verification' and wire_bytes(data['proposed_edges'])>1024:
                raise Deferred('extension_identity_packet_bound')
        logical=[purpose,scope['source_id'],identity(c),identity(data)]
        return self.request(purpose,logical,body,lambda value,cached:validate(stage,value if cached else response_value('anthropic',value),data),ceiling=ceiling)

    def vectors(self,documents,role,scope=None):
        # Reuse individual purchased rows across changed batch boundaries. A
        # claimed row without its exact trusted result is never bought again.
        requested={d['input_id'] for d in documents};available={}
        prefix='cb:'+role+':'
        for row in self.ledger.read()['requests']:
            claimed={x[len(prefix):] for x in row.get('row_inputs',[]) if x.startswith(prefix)}
            if not claimed.intersection(requested):continue
            cache=self.state/'cache'/(row['key']+'.json')
            if row['status']!='valid' or not cache.exists():raise RecoveryRequired('claimed_embedding_row_requires_recovery')
            try:
                saved=json.loads(cache.read_bytes())
                if (saved.get('key')!=row['key'] or saved.get('request_id')!=row['id']
                    or saved.get('body_sha256')!=row['body_sha256'] or saved.get('model')!='voyage-4-large'
                    or {r['id'] for r in saved['value']}!=claimed):raise ValueError('embedding_cache_identity')
                records=saved['value']
                checked=embedding_value({'model':'voyage-4-large','data':[{'index':i,'embedding':r['embedding']} for i,r in enumerate(records)]},[r['id'] for r in records],'voyage-4-large')
            except (ValueError,KeyError,TypeError,OSError) as error:
                raise RecoveryRequired('embedding_cache_row_provenance_requires_recovery') from error
            available.update({r['id']:r for r in checked})
            self.used.append({'key':row['key'],'request_id':row['id'],'cache_hit':True,'reused_vector_rows':len(claimed.intersection(requested))})
        missing=[d for d in documents if d['input_id'] not in available]
        if not missing:return [available[d['input_id']] for d in documents]
        ids=[d['input_id'] for d in missing];body=embedding_body([d['text'] for d in missing],role)
        def check(value,cached):
            if not cached:return embedding_value(value,ids,body['model'])
            return embedding_value({'model':body['model'],'data':[{'index':i,'embedding':r['embedding']} for i,r in enumerate(value)]},ids,body['model']) if [r['id'] for r in value]==ids else (_ for _ in ()).throw(ValueError('cached_vector_row_identity'))
        purpose='cb-documents' if role=='document' else 'cb-query'
        rows=self.request(purpose,[purpose,self.configuration['space'],ids],body,check,
            row_inputs=['cb:'+role+':'+i for i in ids],ceiling=QUERY_TOKEN_BOUND if role=='query' else 80000)
        available.update({r['id']:r for r in rows})
        return [available[d['input_id']] for d in documents]

    def run_scope(self,scope,extension_person=None):
        if scope['state']!='unassessed':return {'state':scope['state'],'scope_id':scope['id']}
        source=scope_inputs(scope)
        interpretation=self.scientific('decomposition',source,scope)
        if interpretation['state']!='coherent':
            return {'state':interpretation['state'],'scope_id':scope['id'],'interpretation':interpretation}
        generated_input_bounds(interpretation)
        documents=self.configuration['documents'];vectors=[]
        for start in range(0,len(documents),80):vectors.extend(self.vectors(documents[start:start+80],'document'))
        queries=[]
        for role in interpretation['roles']:
            text='\n'.join([interpretation['objective'],role['label'],role['quote']])
            queries.append({'input_id':identity({'space':self.configuration['space'],'input_type':'query','text':text}),'text':text})
        query_vectors=self.vectors(queries,'query',scope)
        rankings=[]
        for q in query_vectors:
            qv=q['embedding'];qn=math.sqrt(sum(x*x for x in qv));rank=[]
            for document,vector in zip(documents,vectors):
                v=vector['embedding'];score=sum(a*b for a,b in zip(qv,v))/(qn*math.sqrt(sum(x*x for x in v)))
                rank.append((score,document['person_id']))
            rankings.append([pid for _,pid in sorted(rank,key=lambda row:(-row[0],row[1]))[:12]])
        shortlist=[]
        for position in range(12):
            for rank in rankings:
                if position<len(rank) and rank[position] not in shortlist and len(shortlist)<12:shortlist.append(rank[position])
        people={p['person_id']:p for p in self.configuration['people']}
        supplied=[people[pid] for pid in shortlist]
        data=source|{'interpretation':interpretation,'people':supplied}
        assessment=self.scientific('adjudication',data,scope)
        verified=self.scientific('verification',verification_inputs(data,assessment),scope)
        if verified['state']!='coherent':return {'state':verified['state'],'scope_id':scope['id'],'interpretation':interpretation,'verification':verified}
        if extension_person:
            if extension_person in shortlist or extension_person not in people:raise ValueError('extension_requires_unassessed_eligible_person')
            missing=source|{'interpretation':interpretation,'people':[people[extension_person]]}
            extra=self.scientific('adjudication',missing,scope,True)
            extra=self.scientific('verification',verification_inputs(missing,extra),scope,True)
            if extra['state']!='coherent':return {'state':'failed','reason':'extension_scope_interpretation_conflict'}
            verified={'state':'coherent','people':verified['people']+extra['people'],'edges':verified['edges']+extra['edges']}
        covered={e['role_id'] for e in verified['edges'] if e['coverage'] in ('direct','method_transfer')}
        graph={'version':VERSION,'snapshot_id':self.configuration['snapshot_id'],
            'registry_generation':self.configuration['registry_generation'],'roster_id':self.configuration['roster_id'],
            'source_id':scope['source_id'],'scope':{'id':scope['id'],'parent_id':scope['parent_id'],
                'title':scope['science']['title'],'source_url':scope['science'].get('source_document_url') or scope['science'].get('primary_document_url') or scope['science'].get('detail_page')},
            'objective':interpretation['objective'],'roles':interpretation['roles'],'people':verified['people'],'edges':verified['edges'],
            'state':'ready' if len(covered)==len(interpretation['roles']) else 'ready_with_gaps',
            'limitations':interpretation['limitations']+scope['limitations'],
            'retrieval':{'eligible':len(documents),'shortlist':shortlist,'per_contribution':rankings,
                'unassessed':len(documents)-len(verified['people']),'maximum_shortlist':12},
            'contracts':self.configuration['budget']['contract_ids'],'requests':self.used}
        # Cache-hit bookkeeping cannot change the substantive graph identity.
        supported={e['person_id'] for e in verified['edges'] if e['coverage'] in ('direct','method_transfer')}
        if len(supported)<2 or not any(e['central'] and e['coverage'] in ('direct','method_transfer') for e in verified['edges']):
            graph['state']='no_supported_group_in_assessed_set'
        graph['graph_id']=identity({k:v for k,v in graph.items() if k!='requests'})
        graph_key=identity(['contextual-graph',self.configuration['snapshot_id'],scope['id'],extension_person or ''])
        atomic_json(self.state/'cache'/(graph_key+'.json'),{'kind':'contextual_graph','value':graph})
        return graph


def resolve_job(configuration,job):
    if set(job)!={'release_id','scope_id','person_id','job_id'} or job['release_id']!=configuration['snapshot_id']:
        raise ValueError('contextual_job_release_identity')
    scope=next((s for s in configuration['scopes'] if s['id']==job['scope_id']),None)
    if not scope or (job['person_id'] and job['person_id'] not in {p['person_id'] for p in configuration['people']}):
        raise ValueError('contextual_unapproved_scope_or_person')
    expected=identity([job['release_id'],job['scope_id'],job['person_id']])
    if job['job_id']!=expected:raise ValueError('contextual_job_identity')
    return scope


def prepare(state,reservation,job_path):
    configuration=approved_inputs();job=json.loads(job_path.read_bytes())
    resolve_job(configuration,job)
    existing.trusted_environment(contextual_job=job)
    ledger=existing.restore(state,existing.policy());existing.checkpoint(state)
    atomic_json(reservation,{'authorization_id':AUTHORIZATION_ID,'run_id':os.environ['GITHUB_RUN_ID'],
        'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'code_sha':os.environ['GITHUB_SHA'],
        'job_id':job['job_id'],'input_sha256':INPUT_SHA,'prior_ledger_sha256':existing.sha(ledger.path.read_bytes()),
        'maximum_logical_spend_usd':10,'contextual_task_maximum_usd':5,'contextual_attempts_maximum':40})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','execute']);parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--job',type=Path,required=True);parser.add_argument('--reservation',type=Path)
    parser.add_argument('--result',type=Path)
    args=parser.parse_args()
    job=json.loads(args.job.read_bytes());resolve_job(approved_inputs(),job)
    existing.trusted_environment(contextual_job=job)
    if args.action=='prepare':prepare(args.state,args.reservation,args.job);return
    config=approved_inputs();job=json.loads(args.job.read_bytes());scope=resolve_job(config,job)
    runner=Runner(args.state,config)
    try:
        result=runner.run_scope(scope,job['person_id'] or None) if os.environ.get('CONTEXTUAL_ACTION_CURRENT')=='true' else {'state':'action_blocked','scope_id':scope['id']}
    except (Deferred,ConfigurationFailure,ValueError,KeyError,TypeError,OSError,requests.RequestException) as error:
        result={'state':runner.failure_state(error),'reason':str(error)[:160],
                'scope_id':scope['id']}
    finally:existing.checkpoint(args.state)
    atomic_json(args.result,{'job_id':job['job_id'],'release_id':job['release_id'],'result':result,
        'run_id':os.environ['GITHUB_RUN_ID'],'code_sha':os.environ['GITHUB_SHA'],
        'charged_microusd':sum(r['charged_microusd'] for r in runner.ledger.read()['requests']),
        'attempts':len(runner.ledger.read()['requests'])})


if __name__=='__main__':main()
