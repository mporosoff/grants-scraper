"""Close the actual automatic-member denominator, without repeating paid items."""
import json
from tools.team_recommender_real_prep import DOC,OUT,sha,canonical,write,packet
from tools.team_recommender_executor import judge_contract,policy

def prepare():
    m=json.loads((OUT/'judge-item-map-v2.json').read_bytes());old=json.loads((DOC/'packets'/(m['packet_sha256']+'.json')).read_bytes())
    outcomes=json.loads((OUT/'development-corrected-v2.json').read_bytes());seen={(u['scope_id'],u['value']['candidates'][0]) for u in m['unique'].values() if u['value']['task_type']=='individual'}
    people={p['id']:p for p in json.loads((DOC/'prepared/c2/directory.json').read_bytes())['researchers']};auto=set();occ=[]
    for c in outcomes['results']:
        for s in c['scopes']:
            if not s.get('B',{}).get('defaultIds'):continue
            for arm in ['B','MMR']:
                for pos,t in enumerate(s[arm]['options']):
                    for pid in t['ids']:
                        auto.add((s['id'],pid));occ.append({'candidate':c['id'],'scope_id':s['id'],'person_id':pid,'mode':arm,'position':pos+1})
    missing=sorted(auto-seen);assert len(missing)==10 and {s for s,p in missing}=={'361207'}
    evidence=next(r['source_evidence'] for r in old['requests'] if r['scope_id']=='361207');requests=[];maps=[];batch=[];mapping=[];settings=policy()
    def request(items):return {'scope_id':'361207','purpose':'individual','source_evidence':evidence,'items':items}
    def emit():requests.append(request(batch.copy()));maps.append({'request_index':len(old['requests'])+len(requests)-1,'items':mapping.copy()})
    for sid,pid in missing:
        value={'task_type':'individual','candidates':[pid],'profile_evidence':[{'id':c['claim_id'],'person_id':pid,'claim_id':c['claim_id'],'revision':c['revision'],'text':c['evidence'],'source_url':c['source_urls'][0]} for c in people[pid]['claims'] if c['status']=='active']}
        key=sha(canonical([sid,value]));assert key not in m['unique'];m['unique'][key]={'scope_id':sid,'value':value}
        trial={**value,'item_id':f'i{len(batch)+1:02}'}
        try:
            if len(batch)>=5:raise ValueError()
            judge_contract(request(batch+[trial]),settings)
        except (ValueError,RuntimeError):
            if batch:emit()
            batch=[];mapping=[];trial={**value,'item_id':'i01'}
        judge_contract(request([trial]),settings);batch.append(trial);mapping.append({'key':key,'alias':trial['item_id']})
    if batch:emit()
    assert len(requests)<=5
    for o in occ:
        key=next(k for k,u in m['unique'].items() if u['scope_id']==o['scope_id'] and u['value']['task_type']=='individual' and u['value']['candidates']==[o['person_id']])
        m['occurrences'].append({'kind':'automatic-member',**o,'key':key})
    ledger=json.loads((OUT/'cloud-34471762013/ledger.json').read_bytes());actual=sum(r['charged_microusd'] for r in ledger['requests']);bounds=[judge_contract(r,settings)[1] for r in requests]
    reserve=sum((b*5+1)//2+5120 for b in bounds)
    assert sum(r.get('purpose')=='individual' for r in ledger['requests'])+len(requests)<=90
    assert sum(r.get('reserved_input_tokens',0) for r in ledger['requests'] if r['provider']=='anthropic')+sum(bounds)<=1433600
    assert actual+reserve<=6000000 and 10000000-actual-reserve>=4000000 and not any(r['status']=='reserved_unknown' for r in ledger['requests'])
    result=packet(requests,'development-judge');result.update(reason='Ten automatic alternative members were absent from the initial individual top-five sample. This closes the requested member-level audit, not a new training campaign. Existing source/profile evidence, rubric, model and selected outputs are unchanged. Every previously planned individual item, including failures, is excluded.',new_unique_items=10,all_auto_people=13,prior_actual_usd=actual/1e6,maximum_additional_usd=reserve/1e6,worst_cumulative_usd=(actual+reserve)/1e6,input_bound=sum(bounds),output_bound=len(requests)*512,all_source_denominators_unchanged=True)
    write(DOC/'receipts/c2-automatic-member-audit-plan.json',result)
    m['additional_requests']=requests;m['request_maps']+=maps;m['initial_unique_items']=398;m['member_audit_added']=10
    write(OUT/'judge-item-map-v3.json',m)
    print(json.dumps({k:v for k,v in result.items() if k!='reason'}))
if __name__=='__main__':prepare()
