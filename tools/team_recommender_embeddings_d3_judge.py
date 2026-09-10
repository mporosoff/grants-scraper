"""Deduplicate unchanged D1F evidence tasks across the finite D3 comparison."""
import array
import copy
import json
from collections import Counter,defaultdict
from pathlib import Path
from tools.team_recommender_real_prep import ROOT,DOC,sha,canonical,write,packet
from tools.team_recommender_executor import policy,judge_contract,PURPOSES
from tools.team_recommender_evaluation_d1 import item_identity
from tools.team_recommender_items import judge_items,preflight,claimed_judge_items,historical_index
from tools.team_recommender_budget import ExperimentLedger
from tools.offline_spend import Deferred

OUT=ROOT/'outputs/team-recommender-d3'
def read(p):return json.loads(p.read_bytes())

def prepare(cloud):
    settings=policy();D1=read(ROOT/'outputs/team-recommender-d2/D1-reproduction.json');results=read(OUT/'D3-candidate-outputs.json')
    old1=read(ROOT/'outputs/team-recommender-d1/judge-item-map-d1.json');old2=read(ROOT/'outputs/team-recommender-d2/judge-item-map-d2.json');known=read(ROOT/'outputs/team-recommender-d2/analysis-34510982749.json')['labels']
    old_unique={**old1['unique'],**old2['unique']};oldpacket=read(DOC/'packets'/(old1['packet_sha256']+'.json'));contexts={r['scope_id']:(r['source_evidence'],r['aspects']) for r in oldpacket['requests']}
    directory=read(DOC/'prepared/d1/directory.json');people={p['id']:p for p in directory['researchers']};bundle=read(DOC/'prepared/d1/bundle.json');raw=(DOC/'prepared/d1/vectors.f32').read_bytes()
    vectors=[]
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
        rows=[]
        for pid in sorted(set(ids)):
            p=people[pid]
            for c in sorted(p['claims'],key=lambda c:c['claim_id']):
                if c['status']!='active' or c['claim_id'] not in selected[sid,pid]:continue
                rows.append({'id':'p'+str(len(rows)+1),'person_id':pid,'claim_id':c['claim_id'],'revision':c['revision'],'text':c['evidence'],'source_url':c['source_urls'][0],'label':c['label'],'claim_type':c['type'],'research_summary':p['research_summary']})
        return rows
    stable_old={};preserved=0
    for key,u in old_unique.items():
        sid=u['scope_id'];value=u['value']
        if sid not in contexts:continue
        if value['task_type']!='source_suitability':
            c=value['candidates'];ids=sum(c.values(),[]) if isinstance(c,dict) else c
            assert evidence(sid,ids)==value['profile_evidence'];preserved+=1
        se,aspects=contexts[sid];stable=judge_items({'protocol':'D1F','scope_id':sid,'source_evidence':se,'aspects':aspects,'items':[dict(value,item_id='i01')]})[0]
        stable_old[stable]=key
    unique={};occ=[];want={};sampling=[];comparisons=[];orders=[]
    def item(sid,kind,candidates,occurrence,purpose,priority=None,explanation=None):
        ids=sum(candidates.values(),[]) if isinstance(candidates,dict) else candidates
        value={'task_type':kind,'profile_evidence':evidence(sid,ids),'candidates':candidates}
        if explanation is not None:value['explanation']=explanation
        se,aspects=contexts[sid];key=item_identity(sid,se,aspects,value)
        stable=judge_items({'protocol':'D1F','scope_id':sid,'source_evidence':se,'aspects':aspects,'items':[dict(value,item_id='i01')]})[0]
        if stable in stable_old:key=stable_old[stable];value=old_unique[key]['value']
        unique.setdefault(key,{'scope_id':sid,'value':value,'purpose':purpose,'stable_item':stable})
        occ.append({'key':key,'scope_id':sid,**occurrence})
        if priority is not None:want[key]=min(want.get(key,priority),priority)
        return key
    for arm,result in results['arms'].items():
        for s in result['scopes']:
            if s['status']=='unprepared':continue
            sid=s['id'];buy=arm in {'E1','E2','E3'}
            for field,name in [('B5',arm),('A5','A-'+arm)]:
                for rank,pid in enumerate(s[field],1):item(sid,'call_person',[pid],{'kind':'top5','arm':name,'rank':rank},'d3-call',2 if buy else None)
            if s['status']!='group':continue
            options=s['B']['options'];ranks={1}
            if len(options)>=2:ranks.add(2)
            if len(options)>=8:ranks.add(8)
            interior=list(range(3,min(8,len(options)+1)))
            if interior:ranks.add(min(interior,key=lambda i:sha(sid+'|'+options[i-1]['key'])))
            sampling.append({'arm':arm,'scope_id':sid,'ranks':sorted(ranks),'options':len(options)})
            for rank,o in enumerate(options,1):
                priority=0 if rank==1 else 3
                selected_priority=priority if buy and rank in ranks else None
                item(sid,'group_usefulness',sorted(o['ids']),{'kind':'option-group','arm':arm,'rank':rank,'sampled':rank in ranks},'d3-group',selected_priority)
                for pid in o['ids']:item(sid,'call_person',[pid],{'kind':'option-member','arm':arm,'rank':rank,'person_id':pid},'d3-call',selected_priority)
            left,right=sorted(s['A']),sorted(s['B']['defaultIds'])
            if len(left)==len(right):
                item(sid,'group_usefulness',left,{'kind':'primary-A-matched','arm':'A-'+arm,'rank':1},'d3-group',0 if buy else None)
                for pid in left:item(sid,'call_person',[pid],{'kind':'primary-A-member','arm':'A-'+arm,'rank':1,'person_id':pid},'d3-call',0 if buy else None)
                if left!=right and buy:comparisons.append((sid,left,right,arm))
                elif left==right:occ.append({'scope_id':sid,'kind':'identical-AB','arm':arm})
            else:occ.append({'scope_id':sid,'kind':'baseline-size-abstention','arm':arm,'A_size':len(left),'B_size':len(right)})
    seen_pairs=set();pair_counts=Counter()
    for sid,left,right,arm in sorted(comparisons,key=lambda p:sha(canonical(p))):
        pair=canonical([sid,sorted([left,right])])
        if pair in seen_pairs or pair_counts[arm]>=3:continue
        pair_counts[arm]+=1
        seen_pairs.add(pair);i=len(orders);c={'A':right if i%2 else left,'B':left if i%2 else right}
        key=item(sid,'comparison',c,{'kind':'matched-AB','arm':arm},'d3-comparison',1)
        orders.append({'scope_id':sid,'key':key,'candidates':c,'A_members':left,'B_members':right,'arm':arm})
    for pair in sorted(orders,key=lambda p:sha(p['key']))[:4]:
        c=pair['candidates'];item(pair['scope_id'],'comparison',{'A':c['B'],'B':c['A']},{'kind':'order-swap','original_key':pair['key']},'d3-swap',1)
    explanations=[(arm,s) for arm,a in results['arms'].items() if arm in {'E1','E2','E3'} for s in a['scopes'] if s['status']=='group' and s['action_allowed']]
    for arm,s in sorted(explanations,key=lambda p:sha(p[1]['id']+'|'+p[0]))[:8]:
        item(s['id'],'explanation_audit',sorted(s['B']['defaultIds']),{'kind':'explanation','arm':arm},'d3-explanation',1,explanation=s['explanation'])
    ledger=ExperimentLedger(cloud/'ledger.json');state=ledger.read();history=historical_index();claimed={v for r in state['requests'] for v in claimed_judge_items(r,history)}
    missing=[];todo=defaultdict(list)
    for k,priority in want.items():
        if k in known:continue
        u=unique[k]
        if u['stable_item'] in claimed:missing.append({'key':k,'reason':'historical-paid-failed-or-unavailable; no replay'});continue
        todo[priority,u['scope_id'],u['purpose']].append(k)
    batches=[]
    for (priority,sid,purpose),keys in sorted(todo.items()):
        se,aspects=contexts[sid];batch=[];mapping=[]
        def req(items):return {'protocol':'D1F','scope_id':sid,'purpose':purpose,'source_evidence':se,'aspects':aspects,'items':items}
        def emit():
            if batch:batches.append({'priority':priority,'scope_id':sid,'request':req(copy.deepcopy(batch)),'map':{'items':copy.deepcopy(mapping)}})
        for key in sorted(keys,key=sha):
            trial=dict(unique[key]['value'],item_id='i'+str(len(batch)+1).zfill(2))
            try:judge_contract(req(batch+[trial]),settings)
            except (Deferred,ValueError):
                emit();batch=[];mapping=[];trial['item_id']='i01'
                try:judge_contract(req([trial]),settings)
                except (Deferred,ValueError) as error:missing.append({'key':key,'reason':str(error)});continue
            batch.append(trial);mapping.append({'alias':trial['item_id'],'key':key})
        emit()
    # Breadth-first within each priority: one batch per source before another.
    ordinal=Counter()
    for b in batches:b['round']=ordinal[b['priority'],b['scope_id']];ordinal[b['priority'],b['scope_id']]+=1
    batches.sort(key=lambda b:(b['priority'],b['round'],sha(b['scope_id']),sha(canonical(b['request']))))
    requests=[];maps=[];bounds=[];spent=0;counts=Counter()
    for b in batches:
        request=b['request'];bound=judge_contract(request,settings)[1];cost=(bound*5+1)//2+5120;purpose=request['purpose']
        if len(requests)>=120 or sum(bounds)+bound>1100000 or spent+cost>3364400 or counts[purpose]>=PURPOSES[purpose]:
            missing.extend({'key':m['key'],'reason':'finite-predeclared-envelope; not dispatched'} for m in b['map']['items']);continue
        requests.append(request);maps.append(b['map']);bounds.append(bound);spent+=cost;counts[purpose]+=1
    value={'schema_version':1,'authorization_id':settings['authorization_id'],'registry_generation':settings['registry_generation'],'operation':'development-judge','requests':requests}
    preflight(value,settings,ledger);result=packet(requests,'development-judge');prior=sum(r['charged_microusd'] for r in state['requests']);outstanding=sum(r['reserved_microusd'] for r in state['requests'] if r['status']=='reserved_unknown')
    assert prior+outstanding+spent<=6000000
    result.update(protocol='D1F-unchanged',preserved_old_evidence_items=preserved,unique_items=len(unique),reporting_occurrences=len(occ),requested_unique_items=len(want),exact_cached_unique=sum(k in known for k in unique),
      new_submitted_items=sum(len(r['items']) for r in requests),requests_by_purpose=dict(counts),input_token_bound=sum(bounds),output_token_bound=len(requests)*512,reserved_microusd=spent,missing=missing,
      alternative_sampling=sampling,cumulative_before_microusd=prior,maximum_cumulative_after_microusd=prior+spent,later_stage_minimum_microusd=10000000-prior-spent,
      new_human_items=0,holdout_scored=False,selection_frozen_before_new_results=True)
    result['allocation_addendum_sha256']=sha((DOC/'D3_PACKET_ALLOCATION_ADDENDUM.md').read_bytes())
    write(DOC/'receipts/d3-judge-plan-v2.json',result);write(OUT/'judge-item-map-d3-v2.json',{'unique':unique,'occurrences':occ,'request_maps':maps,'ordering':orders,'missing':missing,'packet_sha256':result['sha256'],'requested_keys':sorted(want)})
    print(json.dumps({k:v for k,v in result.items() if k not in {'alternative_sampling','missing'}},indent=2));print('missing reasons',Counter(r['reason'] for r in missing))

if __name__=='__main__':
    import sys
    prepare(Path(sys.argv[1]))
