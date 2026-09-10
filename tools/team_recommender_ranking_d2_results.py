"""Exact D2 receipt reconciliation and full-denominator development analysis."""
import json
import random
import sys
from collections import Counter,defaultdict
from pathlib import Path
from tools.team_recommender_revision_results import distribution
from tools.team_recommender_executor import policy,judge_contract,result_value
from tools.team_recommender_evaluation_d1 import map_verdicts,order_audit,winner
from tools.team_recommender_budget import AUTHORIZATION_ID
from tools.offline_spend import identity
from tools.team_recommender_real_prep import ROOT,DOC,sha,write

OUT=ROOT/'outputs/team-recommender-d2'
def read(p):return json.loads(p.read_bytes())
def grouped_difference(rows):
    clusters=defaultdict(list)
    for row in rows:clusters[row['group']].append(row['difference'])
    keys=sorted(clusters);rng=random.Random(20260910);boot=[]
    if keys:
        for _ in range(5000):
            draw=[v for k in rng.choices(keys,k=len(keys)) for v in clusters[k]];boot.append(sum(draw)/len(draw))
        boot.sort()
    return {'scopes':len(rows),'source_groups':len(keys),'mean_difference':sum(r['difference'] for r in rows)/len(rows) if rows else None,
            'cluster_bootstrap_95_percentile':[boot[124],boot[4874]] if boot else None,'seed':20260910,'draws':5000,
            'limitation':'Observed-label development estimate; missing labels and abstentions reported separately; no independent or human validation.'}
def analyze(run):
    cloud=OUT/('cloud-'+str(run));checkpoint=read(cloud/'checkpoint.json');ledger=read(cloud/'ledger.json')
    assert checkpoint['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    before=read(OUT/'cloud-34508950140/ledger.json');assert ledger['requests'][:len(before['requests'])]==before['requests']
    paid={r['key']:r for r in ledger['requests']};assert len(paid)==len(ledger['requests']) and all(r['attempt']==1 for r in paid.values())
    mapping=read(OUT/'judge-item-map-d2.json');packet=read(DOC/'packets'/(mapping['packet_sha256']+'.json'));settings=policy()
    labels=dict(read(ROOT/'outputs/team-recommender-d1/analysis-34497056168.json')['labels']);new={};failures=[];unattempted=[];requests=[]
    for index,(request,aliases) in enumerate(zip(packet['requests'],mapping['request_maps'])):
        contract=judge_contract(request,settings);body=contract[0];key=identity([AUTHORIZATION_ID,'development-judge',body]);row=paid.get(key)
        if row is None:unattempted.append(index);continue
        cache=cloud/'cache'/(key+'.json');requests.append({'index':index,'request_id':row['id'],'key':key,'status':row['status'],'items':len(aliases['items'])})
        if row['status']!='valid' or not cache.exists():
            failures.extend({'key':m['key'],'request_id':row['id'],'status':row['status'],'reason':'paid failure or lost result; no replay'} for m in aliases['items']);continue
        retained=read(cache);assert retained['request_id']==row['id'] and retained['body_sha256']==row['body_sha256']==identity(body)
        value=result_value('development-judge',{'model':row['model'],'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(retained['value'])}]},request,contract,settings)
        for k,v in map_verdicts(value,{m['alias']:m['key'] for m in aliases['items']}).items():
            assert k not in labels
            new[k]={'label':v['verdict'],'evidence_ref':v['evidence_ref'],'reason':v['reason'],'request_id':row['id'],'request_key':key,'protocol':'D1F','provenance':'actual-offline-model-judgment'}
    labels.update(new);occ=mapping['occurrences'];outputs=read(OUT/'D2-candidate-outputs.json');prepared=[s for s in outputs['scopes'] if s['status']!='unprepared']
    groups=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map'];scope_ids=[s['id'] for s in prepared];action={s['id'] for s in prepared if s['action_allowed']}
    arms={};by_scope=defaultdict(dict)
    for arm in ['A','D1','D2','R1-isolated']:
        top=[o for o in occ if o['kind']=='top5' and o['arm']==arm];summary=distribution(top,labels)
        for sid in scope_ids:by_scope[sid][arm]=distribution([o for o in top if o['scope_id']==sid],labels)
        rates=[by_scope[sid][arm]['reasonable_fraction'] for sid in scope_ids if by_scope[sid][arm]['observed']]
        summary.update(macro_reasonable=sum(rates)/len(rates) if rates else None,observed_scopes=len(rates),prepared_scopes=35,
           possible_slots=175,empty_lists=sum(not by_scope[sid][arm]['occurrences'] for sid in scope_ids),short_nonempty_lists=sum(0<by_scope[sid][arm]['occurrences']<5 for sid in scope_ids))
        summary['action_admitted']=distribution([o for o in top if o['scope_id'] in action],labels);arms[arm]=summary
    paired={}
    for left,right in [('A','D1'),('A','D2'),('D1','R1-isolated')]:
        rows=[{'scope_id':sid,'group':groups.get(sid,sid),'difference':by_scope[sid][right]['reasonable_fraction']-by_scope[sid][left]['reasonable_fraction']} for sid in scope_ids if by_scope[sid][left]['observed'] and by_scope[sid][right]['observed']]
        paired[left+'->'+right]=grouped_difference(rows)
    summaries={}
    for arm in ['D1','D2']:
        items=[o for o in occ if o.get('arm')==arm];d={}
        for label,kind,primary in [('primary_groups','option-group',True),('all_option_groups','option-group',False),('primary_members','option-member',True),('all_option_members','option-member',False)]:
            rows=[o for o in items if o['kind']==kind and (not primary or o['rank']==1)];d[label]=distribution(rows,labels)
            d[label]['action_admitted']=distribution([o for o in rows if o['scope_id'] in action],labels)
        d['per_option_rank']={str(rank):{kind:distribution([o for o in items if o['kind']==kind and o['rank']==rank],labels) for kind in ['option-group','option-member']} for rank in range(1,9)}
        member_keys={o['key'] for o in items if o['kind']=='option-member'}
        d['distinct_call_persons']=distribution([{'key':k} for k in sorted(member_keys)],labels)
        summaries[arm]=d
    summaries['matched_A_groups']=distribution([o for o in occ if o['kind']=='primary-A-matched'],labels)
    summaries['matched_A_members']=distribution([o for o in occ if o['kind']=='primary-A-member'],labels)
    summaries['explanations']=distribution([o for o in occ if o['kind']=='explanation'],labels)
    audits=[];conflicted=set()
    for o in occ:
        if o['kind']!='order-swap':continue
        a=labels.get(o['original_key'],{}).get('label');b=labels.get(o['key'],{}).get('label');status=order_audit(a,b)
        audits.append({'scope_id':o['scope_id'],'original_key':o['original_key'],'swapped_key':o['key'],'original':a,'swapped':b,'status':status})
        if status=='conflict-unresolved':conflicted.add(o['original_key'])
    preferences=[]
    for row in mapping['ordering']:
        label=labels.get(row['key'],{}).get('label');verdict='missing' if label is None else 'order-conflict-unresolved' if row['key'] in conflicted else winner(label,row['candidates'],row['A_members'])
        preferences.append({'scope_id':row['scope_id'],'result':{'left':'whole-call','right':'D2-coverage'}.get(verdict,verdict),'label':label})
    individual={(u['scope_id'],u['value']['candidates'][0]):labels.get(k,{}).get('label','missing') for k,u in mapping['unique'].items() if u['value']['task_type']=='call_person'}
    disagreements=[];illustrations=[];names={p['id']:p['name'] for p in read(DOC/'prepared/d1/directory.json')['researchers']}
    for o in occ:
        if o['kind']!='option-group' or o['arm']!='D2':continue
        u=mapping['unique'][o['key']];grade=labels.get(o['key'],{}).get('label','missing');members=[{'id':pid,'name':names[pid],'label':individual.get((o['scope_id'],pid),'missing')} for pid in u['value']['candidates']]
        record={'scope_id':o['scope_id'],'rank':o['rank'],'group_label':grade,'members':members}
        if grade in {'strong','plausible'} and any(m['label']=='unrelated' for m in members):disagreements.append(record)
        if o['rank']==1:illustrations.append(record)
    d2rows=[r for r in ledger['requests'] if r.get('purpose','').startswith('d2-')];judges=[r for r in d2rows if r['provider']=='anthropic'];vectors=[r for r in d2rows if r['provider']=='voyage']
    accounting={'authorization':AUTHORIZATION_ID,'prior_D1_cumulative_microusd':2138302,'D2_embedding_requests':len(vectors),'D2_embedding_rows':542,
      'D2_embedding_tokens':sum(r.get('usage',{}).get('total_tokens',0) for r in vectors),'D2_embedding_charged_microusd':sum(r['charged_microusd'] for r in vectors),
      'D2_judge_requests':len(judges),'D2_judge_input_tokens':sum((r.get('usage') or {}).get('input_tokens',0) for r in judges),'D2_judge_output_tokens':sum((r.get('usage') or {}).get('output_tokens',0) for r in judges),
      'D2_judge_reserved_input_bounds':sum(r['reserved_input_tokens'] for r in judges),'D2_judge_reserved_output_bounds':sum(r['reserved_output_tokens'] for r in judges),
      'D2_judge_charged_microusd':sum(r['charged_microusd'] for r in judges),'D2_total_microusd':sum(r['charged_microusd'] for r in d2rows),
      'cumulative_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'outstanding_reserved_microusd':sum(r['reserved_microusd'] for r in ledger['requests'] if r['status']=='reserved_unknown'),
      'lifetime_requests':len(ledger['requests']),'lifetime_request_cap':690,'cache_reused_unique_items':sum(k in labels and k not in new for k in mapping['unique']),
      'new_valid_items':len(new),'cached_occurrences':sum(o.get('key') in labels and o.get('key') not in new for o in occ),'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),
      'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),'owner_run':run,'historical_other_task_credit_microusd':0}
    accounting['remaining_total_microusd']=10000000-accounting['cumulative_microusd'];accounting['remaining_stage2_microusd']=6000000-accounting['cumulative_microusd']
    result={'run':run,'scientific':90,'controls':30,'prepared':35,'unprepared':55,'action_admitted':26,'action_blocked_prepared':9,'D2_groups':8,'D2_no_group':27,
       'D2_action_groups':sum(s['status']=='group' and s['action_allowed'] for s in prepared),'D2_action_no_group':sum(s['status']=='no-group' and s['action_allowed'] for s in prepared),
       'new_valid_items':len(new),'requests':requests,'new_failures':failures,'unattempted_request_indices':unattempted,'prior_missing':mapping['missing'],
       'new_labels_by_task':{t:dict(Counter(v['label'] for k,v in new.items() if mapping['unique'][k]['value']['task_type']==t)) for t in sorted({mapping['unique'][k]['value']['task_type'] for k in new})},
       'arms':arms,'paired':paired,'per_scope':dict(by_scope),'summaries':summaries,'order_audits':audits,'matched_preferences':preferences,'D2_group_member_disagreements':disagreements,
       'primary_examples':illustrations,'ledger':accounting,'labels':labels,'new_labels':new,'independent_feasibility':'unknown','human_judgments':0,'new_human_items':0,'holdout_scored':False,
       'analysis_limits':'D2 candidate frozen before these grades. Cached sampled machine judgments and new bounded offline judgments are development evidence, not human validation; unsampled alternatives remain unjudged.'}
    write(OUT/('analysis-'+str(run)+'.json'),result)
    public={k:v for k,v in result.items() if k not in {'labels','new_labels'}}
    write(DOC/('receipts/d2-development-results-'+str(run)+'.json'),public)
    print(json.dumps({k:result[k] for k in ['new_valid_items','new_failures','unattempted_request_indices','new_labels_by_task','arms','summaries','matched_preferences','ledger']}))
if __name__=='__main__':analyze(int(sys.argv[1]))
