"""Complete fixed-sequence cost plan following the user's $5 amendment.

Read-only inputs; writes a versioned planning receipt, never a spend ledger.
"""
import json
from pathlib import Path
from tools.contextual_team_contract import contract
from tools.contextual_team_cost import (TASK_MICROUSD, INTERPRETATION_WIRE_BYTES,
    PROPOSED_EDGES_WIRE_BYTES, JUDGE_BODY_BYTES, QUERY_TOKEN_BOUND, text_reservation)
from tools.offline_ai import request_body
from tools.offline_spend import encoded, identity, atomic_json

DOC = Path('docs/team-recommender/contextual-stage-b')
OUT = Path('outputs/contextual-stage-b')


def embedding_body(texts, role):
    return {'model':'voyage-4-large','input':texts,'input_type':role,
            'output_dimension':1024,'output_dtype':'float','truncation':False}


def build():
    lock = json.loads((DOC/'input-lock-v1.json').read_bytes())
    snapshot = json.loads((OUT/('snapshot-'+lock['snapshot_id']+'.json')).read_bytes())
    people = json.loads((OUT/'assessment-people.json').read_bytes())
    # Sum of the largest independent serialized documents bounds every possible
    # shortlist, without selecting candidates by an observed score or outcome.
    largest = sorted(people, key=lambda p:len(encoded(json.dumps(p,ensure_ascii=False))), reverse=True)[:12]
    contracts = {stage:contract(stage) for stage in ('decomposition','adjudication','verification')}
    rows=[]
    for scope in snapshot['scopes']:
        row={'scope_id':scope['id'],'initial_state':scope['state'],'stages':[]}
        if scope['state']=='unassessed':
            source={'scope':{k:scope[k] for k in ('id','parent_id','science','conditions','limitations')}}
            for stage,c in contracts.items():
                inputs=source if stage=='decomposition' else source|{'people':largest}
                body=request_body(c['route'],c['settings'],c['prompt'],inputs,c['schema'])
                bound,cost=text_reservation(body)
                extra=0 if stage=='decomposition' else INTERPRETATION_WIRE_BYTES+64
                if stage=='verification':extra+=PROPOSED_EDGES_WIRE_BYTES+64
                row['stages'].append({'stage':stage,'known_body_bytes':len(encoded(body)),
                    'future_wire_bytes_ceiling':extra,'input_token_reservation':bound+extra,
                    'output_token_ceiling':c['settings']['max_output_tokens'],'microusd':cost+2*extra})
        rows.append(row)
    # Explicit missing-person extension: one complete previously unassessed
    # person, existing full interpretation, and at most one edge per role.
    extensions=[]
    for scope in snapshot['scopes']:
        if scope['state']!='unassessed':continue
        source={'scope':{k:scope[k] for k in ('id','parent_id','science','conditions','limitations')}}
        amount=0
        for stage in ('adjudication','verification'):
            c=contracts[stage]
            body=request_body(c['route'],c['settings'],c['prompt'],source|{'people':largest[:1]},c['schema'])
            bound,cost=text_reservation(body)
            extra=INTERPRETATION_WIRE_BYTES+64+(1024+64 if stage=='verification' else 0)
            amount+=cost+extra*2
        extensions.append({'scope_id':scope['id'],'microusd':amount})
    profile_batches=[]
    for start in range(0,len(snapshot['people']),80):
        documents=snapshot['people'][start:start+80]
        body=embedding_body([p['text'] for p in documents],'document')
        bound=len(encoded(body))+1024
        profile_batches.append({'body_id':identity(body),'rows':len(documents),'body_bytes':len(encoded(body)),
            'input_token_reservation':bound,'microusd':(bound*3+24)//25})
    cold=sum(s['microusd'] for r in rows for s in r['stages'])
    query_calls=sum(bool(r['stages']) for r in rows)
    costs={'cold_text_workflows':cold,'profile_embeddings':sum(b['microusd'] for b in profile_batches),
           'query_embeddings':query_calls*((QUERY_TOKEN_BOUND*3+24)//25),
           'one_person_extension':max(e['microusd'] for e in extensions),
           'four_independent_checks':4*((JUDGE_BODY_BYTES+1024)*2+5120)}
    maximum=sum(costs.values())
    return {'version':'contextual-complete-sequence-preflight-v2','date':'2026-09-12',
        'authority':'BUDGET-AMENDMENT-5USD.md','supersedes_planning_receipt':'preflight-budget-v1.json',
        'authorization_id':'on-demand-team-offline-v2-20260909','task_ceiling_microusd':TASK_MICROUSD,
        'overall_ceiling_microusd':10000000,'task_attempt_ceiling':40,'overall_attempt_ceiling':690,
        'input_lock_id':identity(lock),'snapshot_id':snapshot['snapshot_id'],
        'contract_ids':{k:identity(v) for k,v in contracts.items()},
        'prices':{'sonnet_input_per_million_usd':2,'sonnet_output_per_million_usd':10,
                  'voyage4large_per_million_usd':0.12,'provider_prompt_cache':'disabled and rejected by contract',
                  'verified_date':'2026-09-12','sources':['https://platform.claude.com/docs/en/about-claude/pricing','https://docs.voyageai.com/docs/pricing']},
        'scope_rows':rows,'profile_batches':profile_batches,'extension_by_scope':extensions,
        'bounds':{'interpretation_wire_bytes':INTERPRETATION_WIRE_BYTES,'proposed_edges_wire_bytes':PROPOSED_EDGES_WIRE_BYTES,
                  'extension_proposed_edges_wire_bytes':1024,'judge_body_bytes':JUDGE_BODY_BYTES,
                  'query_input_token_reservation_per_batch':QUERY_TOKEN_BOUND},
        'costs_microusd':costs,'complete_sequence_reservation_microusd':maximum,
        'headroom_microusd':TASK_MICROUSD-maximum,
        'request_plan':{'profile_batches':len(profile_batches),'query_batches':query_calls,
                        'cold_text_stages':query_calls*3,'extension_text_stages':2,'judge_requests':4,
                        'maximum':len(profile_batches)+query_calls*4+6,'automatic_retries':0},
        'disposition':'FITS_PENDING_REVIEWED_EXECUTION' if maximum<=TASK_MICROUSD else 'DOES_NOT_FIT',
        'reservations_created':0,'requests_executed':0,
        'resource_rule':'Every source/profile passage is retained. Actual complete wire packets must satisfy these finite bounds before reservation/dispatch. Oversize generated context is an execution/resource failure, never clipped, paid-repaired, or labeled a scientific negative. No early rejection or cache-discount saving is assumed. Output capacities remain 8000/8000/16000.',
        'accounting_rule':'Reserve UTF-8 wire bytes +1024 as input tokens. Text rate is $2/M only after recursively rejecting provider cache directives; provider cache creation would be an accounting-contract failure, never ignored. Actual and uncertain costs stay in the single durable ledger.'}


if __name__=='__main__':
    value=build();atomic_json(DOC/'preflight-budget-v2.json',value)
    print(json.dumps({k:value[k] for k in ('costs_microusd','complete_sequence_reservation_microusd','headroom_microusd','request_plan','disposition')}))
