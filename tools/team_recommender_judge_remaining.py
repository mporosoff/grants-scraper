"""Repack only never-dispatched development items; no providers or new labels."""
import json
from collections import Counter
from tools.team_recommender_real_prep import DOC, OUT, write, packet, sha
from tools.team_recommender_executor import policy, legacy_judge_key, judge_contract

def prepare():
    settings=policy()
    old=json.loads((OUT/'judge-item-map-v1.json').read_bytes())
    original=json.loads((DOC/'packets'/(old['packet_sha256']+'.json')).read_bytes())
    cloud=OUT/'cloud-34465998056'
    checkpoint=json.loads((cloud/'checkpoint.json').read_bytes())
    assert checkpoint['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=json.loads((cloud/'ledger.json').read_bytes()); paid={r['key'] for r in ledger['requests']}
    assert sum(r['charged_microusd'] for r in ledger['requests'])==22444
    prepared={s['id'] for s in json.loads((OUT/'real-inputs-v2.json').read_bytes())['scopes'] if s['prepared']}
    failed=[]; omitted=[]; grouped={}
    for request,mapping in zip(original['requests'],old['request_maps']):
        if legacy_judge_key(request,settings) in paid:
            failed.extend(mapping['items']);continue
        if request['purpose']=='source' and request['scope_id'] not in prepared:
            omitted.extend(mapping['items']);continue
        row=grouped.setdefault((request['scope_id'],request['purpose']),{'request':request,'items':[]})
        row['items'].extend(zip(request['items'],mapping['items']))
    requests=[]; maps=[]
    for row in grouped.values():
        request=row['request']; batch=[]; mapping=[]
        def emit():
            requests.append({**request,'items':batch.copy()});maps.append({'request_index':len(requests)-1,'items':mapping.copy()})
        for item,m in row['items']:
            trial={**item,'item_id':f'i{len(batch)+1:02}'}
            try:
                if len(batch)>=5:raise ValueError('compact_output_batch_limit')
                judge_contract({**request,'items':batch+[trial]},settings)
            except (ValueError,RuntimeError):
                if batch:emit()
                batch=[];mapping=[];trial={**item,'item_id':'i01'}
            judge_contract({**request,'items':[trial]},settings)
            batch.append(trial);mapping.append({'alias':trial['item_id'],'key':m['key']})
        if batch:emit()
    # No failed item may re-enter by changing its alias, formatting or batching.
    submitted={m['key'] for r in maps for m in r['items']}
    assert not submitted.intersection(m['key'] for m in failed)
    counts=Counter(r['purpose'] for r in requests)
    prior=[r for r in ledger['requests'] if r['provider']=='anthropic']
    bounds=[judge_contract(r,settings)[1] for r in requests]
    assert sum(bounds)+sum(r['reserved_input_tokens'] for r in prior)<=1433600
    assert all(counts[k]+sum(r['purpose']==k for r in prior)<=v for k,v in {'source':90,'individual':90,'group':90,'explanation':30,'order-swap':10}.items())
    result=packet(requests,'development-judge')
    result.update(unique_submitted=len(submitted),requests_by_purpose=dict(counts),input_bound=sum(bounds),output_bound=len(requests)*512,
                  conservative_reservation_usd=sum(bounds)*2.5e-6+len(requests)*.00512,prior_actual_usd=.022444,
                  prior_reserved_input=sum(r['reserved_input_tokens'] for r in prior),failed_items_never_repeated=failed,
                  omitted_source_only_items=omitted,original_unique_denominator=len(old['unique']),original_occurrences=len(old['occurrences']),
                  reason='Complete scientific/profile evidence retained. Optional source-only model grades on unprepared sources are omitted to preserve every unfailed real match/team comparison within the original finite token envelope; deterministic source dispositions remain for all 90 scientific reservations and 30 derived controls. Seven charged failed items remain unresolved, never rebought.',
                  prices_verified='2026-09-10',price_sources=['https://platform.claude.com/docs/en/models/sonnet-5/whats-new-sonnet-5','https://docs.voyageai.com/docs/pricing'],
                  prices_usd_per_million={'judge_input':2,'judge_output':10,'embedding':.02},thinking='disabled',max_items_per_request=5,
                  trusted_merge='8e5101931222bc6b1f7cd00971441b8a2c55db5d',review_head='d079a734ad80f82e363a0748282e232eab79ae9f',review_comment=5617383016)
    write(DOC/'receipts/c2-remaining-judge-plan-v2.json',result)
    write(OUT/'judge-item-map-v2.json',{**old,'request_maps':maps,'packet_sha256':result['sha256'],'failed_items':failed,'omitted_source_only_items':omitted})
    chosen=[min((i for i,r in enumerate(requests) if r['purpose']==purpose),key=lambda i:len(requests[i]['items'])) for purpose in ['individual','group','explanation','source']]
    canary=packet([requests[i] for i in chosen],'development-judge');canary['full_request_indices']=chosen
    write(DOC/'receipts/c2-remaining-judge-wiring-v2.json',canary)
    print(json.dumps({'full':result['sha256'],'wiring':canary['sha256'],'requests':len(requests),'items':len(submitted),'counts':dict(counts),'input_bound':sum(bounds),'reserve':result['conservative_reservation_usd']}))

if __name__=='__main__':prepare()
