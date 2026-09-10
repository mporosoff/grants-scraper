"""Finite missing D2 judgments; evidence policy and rubric stay exactly D1F."""
import array
import copy
import json
from collections import Counter
from tools.team_recommender_real_prep import ROOT,DOC,sha,canonical,write,packet
from tools.team_recommender_executor import policy,judge_contract
from tools.team_recommender_evaluation_d1 import item_identity
from tools.team_recommender_items import judge_items,preflight
from tools.team_recommender_budget import ExperimentLedger
from tools.offline_spend import Deferred

OUT=ROOT/'outputs/team-recommender-d2'
def read(p):return json.loads(p.read_bytes())
def prepare():
    settings=policy();old=read(ROOT/'outputs/team-recommender-d1/judge-item-map-d1.json');analysis=read(ROOT/'outputs/team-recommender-d1/analysis-34497056168.json')
    oldpacket=read(DOC/'packets'/(old['packet_sha256']+'.json'));contexts={r['scope_id']:(r['source_evidence'],r['aspects']) for r in oldpacket['requests']}
    D1=read(OUT/'D1-reproduction.json');D2=read(OUT/'D2-candidate-outputs.json');R1=read(OUT/'R1-D1-selection.json')
    directory=read(DOC/'prepared/d1/directory.json');people={p['id']:p for p in directory['researchers']}
    bundle=read(DOC/'prepared/d1/bundle.json');raw=(DOC/'prepared/d1/vectors.f32').read_bytes();vectors=[]
    for i in range(len(bundle['vector_rows'])):
        v=array.array('f');v.frombytes(raw[i*4096:(i+1)*4096]);vectors.append(v)
    owned={p['id']:p for p in bundle['people']};scopes={s['id']:s for s in bundle['scopes']};selected={}
    for s in D1['scopes']:
        if s['status']=='unprepared':continue
        q=vectors[scopes[s['id']]['whole_call']['vector']]
        for row in s['rows']:
            whole=max(owned[row['id']]['passages'],key=lambda p:sum(a*b for a,b in zip(q,vectors[p['vector']])))
            selected[s['id'],row['id']]={whole['id']}|{e['passage']['id'] for e in row['edges'] if e['admitted']}
    def evidence(sid,ids):
        result=[]
        for pid in sorted(set(ids)):
            p=people[pid]
            for c in sorted(p['claims'],key=lambda c:c['claim_id']):
                if c['status']!='active' or c['claim_id'] not in selected[sid,pid]:continue
                result.append({'id':'p'+str(len(result)+1),'person_id':pid,'claim_id':c['claim_id'],'revision':c['revision'],'text':c['evidence'],'source_url':c['source_urls'][0],'label':c['label'],'claim_type':c['type'],'research_summary':p['research_summary']})
        return result
    # Reproduce the old evidence projection before preparing new groups.
    preserved=0;stable_old={}
    for key,u in old['unique'].items():
        sid=u['scope_id'];value=u['value']
        if sid not in contexts:continue
        if value['task_type']!='source_suitability':
            candidates=value['candidates'];ids=sum(candidates.values(),[]) if isinstance(candidates,dict) else candidates
            assert evidence(sid,ids)==value['profile_evidence'];preserved+=1
        se,aspects=contexts[sid]
        stable=judge_items({'protocol':'D1F','scope_id':sid,'source_evidence':se,'aspects':aspects,'items':[dict(value,item_id='i01')]})[0]
        stable_old[stable]=key
    unique={};occurrences=[];want=set();sample=[];order=[]
    def item(sid,kind,candidates,occ,purpose,request=False,explanation=None):
        ids=sum(candidates.values(),[]) if isinstance(candidates,dict) else candidates
        value={'task_type':kind,'profile_evidence':evidence(sid,ids),'candidates':candidates}
        if explanation is not None:value['explanation']=explanation
        se,aspects=contexts[sid];key=item_identity(sid,se,aspects,value)
        stable=judge_items({'protocol':'D1F','scope_id':sid,'source_evidence':se,'aspects':aspects,'items':[dict(value,item_id='i01')]})[0]
        if stable in stable_old:key=stable_old[stable];value=old['unique'][key]['value']
        unique.setdefault(key,{'scope_id':sid,'value':value,'purpose':purpose,'stable_item':stable})
        occurrences.append({'key':key,'scope_id':sid,**occ})
        if request:want.add(key)
        return key
    # Every returned list remains visible; A and D1 are exact historical outputs.
    for arm,outputs,field in [('A',D1,'A5'),('D1',D1,'B5'),('D2',D2,'B5'),('R1-isolated',R1,'B5')]:
        for s in outputs['scopes']:
            if s['status']=='unprepared':continue
            for rank,pid in enumerate(s[field],1):item(s['id'],'call_person',[pid],{'kind':'top5','arm':arm,'rank':rank},'d2-call',request=arm=='D2')
    comparisons=[]
    for arm,outputs in [('D1',D1),('D2',D2)]:
        for s in outputs['scopes']:
            if s['status']!='group':continue
            sid=s['id'];options=s['B']['options'];ranks={1}
            if arm=='D2':
                if len(options)>=2:ranks.add(2)
                if len(options)>=8:ranks.add(8)
                interior=[i for i in range(3,min(8,len(options)+1))]
                if interior:ranks.add(min(interior,key=lambda i:sha(sid+'|'+options[i-1]['key'])))
                sample.append({'scope_id':sid,'option_count':len(options),'sampled_ranks':sorted(ranks)})
            for rank,option in enumerate(options,1):
                ids=sorted(option['ids']);buy=arm=='D2' and rank in ranks
                item(sid,'group_usefulness',ids,{'kind':'option-group','arm':arm,'rank':rank,'sampled':buy},'d2-group',request=buy)
                for pid in ids:item(sid,'call_person',[pid],{'kind':'option-member','arm':arm,'rank':rank,'person_id':pid,'sampled':buy},'d2-call',request=buy)
            if arm=='D2':
                left,right=sorted(s['A']),sorted(s['B']['defaultIds'])
                if len(left)==len(right):
                    item(sid,'group_usefulness',left,{'kind':'primary-A-matched','arm':'A','rank':1},'d2-group',request=True)
                    for pid in left:item(sid,'call_person',[pid],{'kind':'primary-A-member','arm':'A','rank':1,'person_id':pid},'d2-call',request=True)
                    if left!=right:comparisons.append((sid,left,right))
                    else:occurrences.append({'scope_id':sid,'kind':'identical-AB','arm':'D2'})
    for i,(sid,left,right) in enumerate(sorted(comparisons,key=lambda p:sha(canonical(p)))):
        candidates={'A':right if i%2 else left,'B':left if i%2 else right}
        key=item(sid,'comparison',candidates,{'kind':'matched-AB','arm':'D2'},'d2-comparison',request=True)
        order.append({'scope_id':sid,'key':key,'candidates':candidates,'A_members':left,'D2_members':right})
    for pair in sorted(order,key=lambda p:sha(p['key']))[:4]:
        c=pair['candidates'];item(pair['scope_id'],'comparison',{'A':c['B'],'B':c['A']},{'kind':'order-swap','original_key':pair['key']},'d2-swap',request=True)
    for s in sorted([s for s in D2['scopes'] if s['status']=='group' and s['action_allowed']],key=lambda s:sha(s['id']))[:6]:
        item(s['id'],'explanation_audit',sorted(s['B']['defaultIds']),{'kind':'explanation','arm':'D2'},'d2-explanation',request=True,explanation=s['explanation'])
    claimed={v for r in read(OUT/'cloud-34508950140/ledger.json')['requests'] for v in r.get('judge_items',[])}
    from tools.team_recommender_items import claimed_judge_items,historical_index
    history=historical_index()
    claimed|={v for r in read(OUT/'cloud-34508950140/ledger.json')['requests'] for v in claimed_judge_items(r,history)}
    known=analysis['labels'];missing=[];todo={}
    for key in sorted(want):
        if key in known:continue
        u=unique[key]
        if u['stable_item'] in claimed:missing.append({'key':key,'scope_id':u['scope_id'],'reason':'historical-paid-failed-or-unavailable; no replay'});continue
        todo.setdefault((u['scope_id'],u['purpose']),[]).append(key)
    requests=[];maps=[]
    for (sid,purpose),keys in sorted(todo.items(),key=lambda p:({'d2-call':0,'d2-group':1,'d2-explanation':2}.get(p[0][1],3),p[0])):
        se,aspects=contexts[sid];batch=[];mapping=[]
        def request(items):return {'protocol':'D1F','scope_id':sid,'purpose':purpose,'source_evidence':se,'aspects':aspects,'items':items}
        def emit():
            if batch:requests.append(request(copy.deepcopy(batch)));maps.append({'items':copy.deepcopy(mapping)})
        for key in keys:
            trial=dict(unique[key]['value'],item_id='i'+str(len(batch)+1).zfill(2))
            try:judge_contract(request(batch+[trial]),settings)
            except (Deferred,ValueError):
                emit();batch=[];mapping=[];trial['item_id']='i01'
                try:judge_contract(request([trial]),settings)
                except (Deferred,ValueError) as error:missing.append({'key':key,'scope_id':sid,'reason':str(error)});continue
            batch.append(trial);mapping.append({'alias':trial['item_id'],'key':key})
        emit()
    bounds=[judge_contract(r,settings)[1] for r in requests];reserved=sum((b*5+1)//2+5120 for b in bounds)
    assert len(requests)<=120 and sum(bounds)<=1100000 and reserved<=3364400
    value={'schema_version':1,'authorization_id':settings['authorization_id'],'registry_generation':settings['registry_generation'],'operation':'development-judge','requests':requests}
    preflight(value,settings,ExperimentLedger(OUT/'cloud-34508950140/ledger.json'))
    receipt=packet(requests,'development-judge');receipt.update(protocol='D1F-unchanged',preserved_old_evidence_items=preserved,
        unique_items=len(unique),reporting_occurrences=len(occurrences),requested_unique_items=len(want),exact_cached_unique=sum(k in known for k in unique),
        new_submitted_items=sum(len(r['items']) for r in requests),requests_by_purpose=dict(Counter(r['purpose'] for r in requests)),
        input_token_bound=sum(bounds),output_token_bound=len(requests)*512,reserved_microusd=reserved,missing=missing,
        alternative_sampling=sample,unjudged_items=sum(k not in known and k not in want for k in unique),
        cumulative_before_microusd=2138620,maximum_cumulative_after_microusd=2138620+reserved,later_stage_minimum_balance_microusd=10000000-2138620-reserved,
        profile_enrichment=False,new_human_items=0,holdout_scored=False,selection_frozen_before_new_results=True)
    write(DOC/'receipts/d2-judge-plan.json',receipt)
    write(OUT/'judge-item-map-d2.json',{'unique':unique,'occurrences':occurrences,'request_maps':maps,'ordering':order,'missing':missing,'packet_sha256':receipt['sha256'],'requested_keys':sorted(want)})
    print(json.dumps(receipt))
if __name__=='__main__':prepare()
