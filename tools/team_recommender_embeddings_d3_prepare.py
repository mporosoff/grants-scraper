"""Freeze complete D3 public inputs and finite packets before paid work."""
import json
from pathlib import Path
from tools.team_recommender_embeddings_d3 import *
from tools.team_recommender_executor import policy,validate_packet
from tools.team_recommender_real_prep import ROOT,DOC,write,sha,packet

def prepare():
    settings=policy();people=profiles(settings);sources=queries();query={};phrase={}
    for owner,scope in sorted(sources.items()):
        for t in query_texts(scope):query.setdefault(digest(t),{'id':digest(t),'owner':owner,'text':t})
    for owner,p in people.items():
        for t in p['phrases']:phrase.setdefault(digest(t),{'id':digest(t),'owner':owner,'text':t})
    shapes=[(PHRASES,'query',list(query.values())),(PHRASES,'document',list(phrase.values())),
      (COMBINED,'document',[{'id':digest(p['combined']),'owner':o,'text':p['combined']} for o,p in people.items()]),
      (CONTEXT,'query',list(query.values())),(CONTEXT,'document',[{'id':digest(canonical(p['chunks'])),'owner':o,'chunks':p['chunks']} for o,p in people.items()])]
    owners=['urh-000105','urh-000016','urh-000079'];source_ids=['359696','344592:ab-0009','nasa-roses:25-D.9-d22059cf9f']
    qsmoke={digest(sources[i]['core']) for i in source_ids};psmoke={digest(people[o]['phrases'][0]) for o in owners}
    canary=[];remaining=[]
    def request(rep,role,rows):return {'representation':rep,'model':MODELS[rep],'input_role':role,'rows':rows}
    for rep,role,rows in shapes:
        small=[r for r in rows if (r['id'] in qsmoke if role=='query' else r['id'] in psmoke if rep==PHRASES else r['owner'] in owners)]
        assert len(small)==3
        canary.append(request(rep,role,small));left=[r for r in rows if r not in small];batch=[]
        for row in left:
            try:contract(request(rep,role,batch+[row]),settings)
            except ValueError:
                assert batch;remaining.append(request(rep,role,batch));batch=[row];contract(request(rep,role,batch),settings)
            else:batch.append(row)
        if batch:remaining.append(request(rep,role,batch))
    all_requests=canary+remaining;items=[i for r in all_requests for i in paid_items(r)]
    assert len(items)==len(set(items))
    plans=[]
    for name,requests in [('wiring',canary),('complete',remaining)]:
        receipt=packet(requests);bounds=[contract(r,settings)[1] for r in requests]
        receipt.update(name=name,reserved_microusd=sum((b*3+24)//25 for b in bounds),output_rows=sum(len(expected_rows(r)) for r in requests),
          batches=[{'representation':r['representation'],'role':r['input_role'],'rows':len(r['rows']),'outputs':len(expected_rows(r)),'bound':b} for r,b in zip(requests,bounds)])
        plans.append(receipt)
    assert sum(p['requests'] for p in plans)<=28 and sum(p['reserved_microusd'] for p in plans)<=180000
    inventory={'version':'D3-exact-inputs-v1','people':people,'queries':sources,'registry_generation':settings['registry_generation'],
       'source_query_table_sha256':QUERIES_SHA256,'researcher_enrichment':False,'holdout_scored':False}
    ih=write(DOC/'manifests/d3-inputs.json',inventory)
    receipt={'protocol_sha256':sha((DOC/'EVALUATION_PROTOCOL_D3.md').read_bytes()),'input_manifest_sha256':ih,
      'scope_count':35,'directory_count':155,'unique_phrase_inputs':398,'unique_query_inputs':95,'combined_documents':155,'contextual_chunks':556,
      'new_unique_vector_rows':len(items),'existing_E0_reused_rows':493,'existing_R1_context_vectors_compatible_with_new_models':0,
      'combined_document_utf8_bytes':sum(len(p['combined'].encode()) for p in people.values()),'sources_added':0,'claims_changed':0,
      'plans':plans,'prior_cumulative_microusd':2279110,'new_embedding_reservation_microusd':sum(p['reserved_microusd'] for p in plans),
      'judge_ceiling_microusd':3364400,'before_dispatch':True,'provider_calls':0,'holdout_scored':False}
    write(DOC/'receipts/d3-input-plan.json',receipt);print(json.dumps(receipt,indent=2))

if __name__=='__main__':prepare()
