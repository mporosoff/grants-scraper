"""Prepare D2's one predeclared representation, no provider or source access."""
import hashlib
import json
from pathlib import Path
from tools.team_recommender_context_d2 import VERSION, context_inventory, canonical
from tools.team_recommender_executor import policy, embedding_contract, validate_packet

ROOT=Path(__file__).resolve().parents[1];DOC=ROOT/'docs/team-recommender'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):
    raw=(canonical(value)+'\n').encode('utf-8');path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=raw:raise ValueError('immutable_D2_input_conflict')
    path.write_bytes(raw);return sha(raw)
def prepare():
    settings=policy();inventory=context_inventory(settings);unique={}
    for owner,rows in sorted(inventory.items()):
        for key,text in sorted(rows.items()):unique.setdefault(key,{'id':key,'owner':owner,'text':text})
    rows=list(unique.values());requests=[{'input_role':'document','representation':VERSION,'rows':rows[i:i+128]} for i in range(0,len(rows),128)]
    bounds=[embedding_contract(r,settings)[1] for r in requests]
    assert len(requests)<=5 and sum((n+49)//50 for n in bounds)<=20000
    packet={'schema_version':1,'authorization_id':settings['authorization_id'],'registry_generation':settings['registry_generation'],'operation':'embeddings','requests':requests}
    validate_packet(packet,settings);raw=(canonical(packet)+'\n').encode();h=sha(raw)
    write(DOC/'packets'/(h+'.json'),packet)
    old=json.loads((DOC/'prepared/d1/bundle.json').read_bytes())
    receipt={'protocol':'D2-context-v1','packet_sha256':h,'packet_bytes':len(raw),'request_count':len(requests),'rows':len(rows),
      'batches':[{'rows':len(r['rows']),'conservative_input_bound':b,'reserved_microusd':(b+49)//50} for r,b in zip(requests,bounds)],
      'input_token_bound':sum(bounds),'reserved_microusd':sum((b+49)//50 for b in bounds),'reused_D1_vector_rows':len(old['vector_rows']),
      'serialized_context_utf8_bytes':sum(len(r['text'].encode()) for r in rows),'registry_generation':settings['registry_generation'],
      'source_changes':0,'researcher_enrichment':False,'before_dispatch':True,'provider_calls':0,
      'ledger_owner_before_dispatch':34497056168,'prior_charged_microusd':2138302,'prior_outstanding_microusd':0,
      'price_verified_date':'2026-09-10','price_usd_per_million_input_tokens':.02,'price_source':'https://docs.voyageai.com/docs/pricing',
      'D2_judge_remaining_plan':{'requests_max':120,'input_bound_max':1100000,'output_tokens_max':61440,'reservation_microusd_max':3364400},
      'worst_case_cumulative_microusd':2138302+sum((b+49)//50 for b in bounds)+3364400,
      'later_stage_minimum_remaining_microusd':10000000-2138302-sum((b+49)//50 for b in bounds)-3364400}
    write(DOC/'receipts/d2-context-input-plan.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':prepare()
