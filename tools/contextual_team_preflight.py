"""Inspect the complete locked sequence with the existing conservative reservation rule.

No credentials or provider operations. Cost cases are bounds, not executed responses.
"""
import json
from pathlib import Path
from decimal import Decimal, ROUND_CEILING
from tools.contextual_team_contract import contract
from tools.offline_ai import request_body
from tools.offline_spend import encoded, identity, atomic_json

DOC=Path('docs/team-recommender/contextual-stage-b')
OUT=Path('outputs/contextual-stage-b')

def main():
    lock=json.loads((DOC/'input-lock-v1.json').read_bytes())
    snapshot=json.loads((OUT/('snapshot-'+lock['snapshot_id']+'.json')).read_bytes())
    people=json.loads((OUT/'assessment-people.json').read_bytes())
    largest=sorted(people,key=lambda p:len(encoded(p)),reverse=True)[:lock['shortlist']['maximum']]
    contracts={stage:contract(stage) for stage in ('decomposition','adjudication','verification')}
    rows=[]
    for scope in snapshot['scopes']:
        if scope['state']!='unassessed':
            rows.append({'scope_id':scope['id'],'state':scope['state'],'paid_stages':[]});continue
        source={'scope':{k:scope[k] for k in ('id','parent_id','science','conditions','limitations')}}
        stages=[]
        for stage,c in contracts.items():
            # This deliberately omits future interpretation/proposed-edge bytes:
            # even this incomplete conservative envelope already fails the task cap.
            # It is not represented as an exact future request or a token prediction.
            data=source if stage=='decomposition' else source|{'people':largest}
            body=request_body(c['route'],c['settings'],c['prompt'],data,c['schema'])
            ceiling=len(encoded(body))+1024
            reservation=int((Decimal(ceiling)*Decimal('2.5')+c['settings']['max_output_tokens']*10).to_integral_value(rounding=ROUND_CEILING))
            stages.append({'stage':stage,'known_body_bytes':len(encoded(body)),'byte_rule_input_reservation':ceiling,
                'output_token_ceiling':c['settings']['max_output_tokens'],'reservation_microusd':reservation,
                'uncached_only_price_microusd':ceiling*2+c['settings']['max_output_tokens']*10,
                'omitted_future_inputs':stage!='decomposition'})
        rows.append({'scope_id':scope['id'],'state':scope['state'],'paid_stages':stages})
    base=sum(s['reservation_microusd'] for row in rows for s in row['paid_stages'])
    # A missing-person extension still retains full legacy assessment + verification capacity.
    extension_outputs=sum(contracts[s]['settings']['max_output_tokens']*10 for s in ('adjudication','verification'))
    judge_outputs=lock['independent_check']['maximum_requests']*512*10
    lower_envelope=base+extension_outputs+judge_outputs
    total_text_output=sum(c['settings']['max_output_tokens'] for c in contracts.values())
    receipt={'version':'contextual-complete-sequence-preflight-v1','date':'2026-09-12','input_lock_id':identity(lock),
      'snapshot_id':snapshot['snapshot_id'],'provider_requests_executed':0,'charges_microusd':0,
      'prices':{'sonnet5_input_per_million':2,'sonnet5_output_per_million':10,'sonnet5_cache_write_per_million':2.5,
                'voyage4large_per_million':0.12,'official_sources':['https://platform.claude.com/docs/en/about-claude/pricing','https://docs.voyageai.com/docs/pricing']},
      'scope_rows':rows,'eligible_directory':len(people),'maximum_shortlist':12,
      'largest_12_complete_documents_bytes':sum(len(encoded(p)) for p in largest),'text_outputs_per_full_scope':total_text_output,
      'known_cold_scope_reservation_envelope_microusd':base,
      'cold_uncached_price_only_envelope_microusd':sum(s['uncached_only_price_microusd'] for r in rows for s in r['paid_stages']),
      'extension_output_only_reserve_microusd':extension_outputs,'judge_output_only_reserve_microusd':judge_outputs,
      'incomplete_sequence_reservation_envelope_microusd':lower_envelope,'task_ceiling_microusd':3000000,
      'missing_from_envelope':['Future interpretation/edge input bytes','Profile and query embeddings','Extension input tokens','Independent-check input tokens'],
      'request_plan':{'profile_batches_maximum':2,'scope_query_batches_maximum':7,'scope_text_stages_maximum':21,
                      'extension_text_stages':2,'independent_check_maximum':4,'total_maximum':36,'automatic_retries':0},
      'disposition':'BLOCKED_BEFORE_METERED_DISPATCH' if lower_envelope>3000000 else 'ADDITIONAL_COMPLETE_PACKET_BOUND_REQUIRED',
      'limitation':'This is the existing byte-based conservative reservation envelope for a permitted largest-document shortlist, not actual model token usage or a claim that expected charges necessarily exceed $3. It does not credit early semantic rejection or favorable token utilization.',
      'minimum_prerequisite':'A reviewed complete-packet token/reservation plan that fits the same $3/40 limits without reducing evidence, dropping locked cases, silently lowering effective legacy output capacities, or changing models. No increased allowance is requested.'}
    atomic_json(DOC/'preflight-budget-v1.json',receipt)
    atomic_json(DOC/'scientific-contracts-v1.json',{'contracts':contracts,'contract_ids':{k:identity(v) for k,v in contracts.items()},'status':'local candidate; unreviewed, undispatched, not activated'})
    print(json.dumps({k:receipt[k] for k in ('known_cold_scope_reservation_envelope_microusd','cold_uncached_price_only_envelope_microusd','incomplete_sequence_reservation_envelope_microusd','disposition','request_plan')}))

if __name__=='__main__':main()
