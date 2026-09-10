"""D1 exact paid-result reconciliation and grouped development summaries. No dispatch."""
import copy
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from tools.team_recommender_executor import judge_contract, policy, result_value
from tools.team_recommender_budget import AUTHORIZATION_ID
from tools.offline_spend import identity
from tools.team_recommender_evaluation_d1 import map_verdicts, order_audit, winner

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT/'docs/team-recommender'
OUT = ROOT/'outputs/team-recommender-d1'


def read(path):
    return json.loads(path.read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    if path.exists() and path.read_bytes()!=raw:
        raise ValueError('preserve prior analysis: '+str(path))
    path.write_bytes(raw)


def distribution(occurrences, labels):
    observed=[labels[o['key']]['label'] for o in occurrences if o.get('key') in labels]
    counts=Counter(observed)
    return {'occurrences':len(occurrences),'unique_items':len({o['key'] for o in occurrences if 'key' in o}),
            'observed':len(observed),'missing':len(occurrences)-len(observed),'labels':dict(counts),
            'reasonable_observed':counts['strong']+counts['plausible'],
            'reasonable_fraction':(counts['strong']+counts['plausible'])/len(observed) if observed else None,
            'unrelated_fraction':counts['unrelated']/len(observed) if observed else None}


def analyze(run):
    cloud=OUT/('cloud-'+str(run));checkpoint=read(cloud/'checkpoint.json')
    assert checkpoint['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=read(cloud/'ledger.json');paid={r['key']:r for r in ledger['requests']}
    assert len(paid)==len(ledger['requests']) and all(r['attempt']==1 for r in ledger['requests'])
    mapping=read(OUT/'judge-item-map-d1.json');packet=read(DOC/'packets'/(mapping['packet_sha256']+'.json'));settings=policy()
    labels={};requests=[];failures=[];unattempted=[]
    for index,(original,rm) in enumerate(zip(packet['requests'],mapping['request_maps'])):
        old_key=identity([AUTHORIZATION_ID,'development-judge',judge_contract(original,settings)[0]])
        request=original if old_key in paid else dict(original,protocol='D1F')
        contract=judge_contract(request,settings);body=contract[0];key=identity([AUTHORIZATION_ID,'development-judge',body]);row=paid.get(key)
        if row is None:
            unattempted.extend(m['key'] for m in rm['items']);continue
        cache=cloud/'cache'/(key+'.json')
        requests.append({'index':index,'request_id':row['id'],'protocol':request['protocol'],'purpose':row['purpose'],'status':row['status'],'items':len(rm['items'])})
        if row['status']!='valid' or not cache.exists():
            failures.extend({'key':m['key'],'request_id':row['id'],'status':row['status'],'reason':'paid result unavailable; no replay'} for m in rm['items']);continue
        retained=read(cache)
        assert retained['request_id']==row['id'] and retained['body_sha256']==row['body_sha256']==identity(body) and retained['key']==key
        payload={'model':row['model'],'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(retained['value'])}]}
        value=result_value('development-judge',payload,request,contract,settings)
        for k,v in map_verdicts(value,{m['alias']:m['key'] for m in rm['items']}).items():
            labels[k]={'label':v['verdict'],'evidence_ref':v['evidence_ref'],'reason':v['reason'],
                       'request_id':row['id'],'request_key':key,'protocol':request['protocol'],'provenance':'actual-offline-model-judgment'}
    occ=mapping['occurrences'];arms={};per_scope=defaultdict(dict)
    outcomes=next(r for r in read(OUT/'controlled-v1.json')['results'] if r['id']=='combined')
    prepared={s['id'] for s in outcomes['scopes'] if s['status']!='unprepared'}
    for arm in ['A','B']:
        selected=[o for o in occ if o['kind']=='top5' and o['arm']==arm]
        arms[arm]=distribution(selected,labels)
        for sid in sorted(prepared):
            d=distribution([o for o in selected if o['scope_id']==sid],labels);per_scope[sid][arm]=d
        rates=[v[arm]['reasonable_fraction'] for v in per_scope.values() if v[arm]['observed']]
        arms[arm].update(macro_scope_reasonable=sum(rates)/len(rates) if rates else None,observed_scope_denominator=len(rates),
                        prepared_scopes=35,possible_top5_slots=175,empty_lists=sum(not v[arm]['occurrences'] for v in per_scope.values()),
                        short_nonempty_lists=sum(0<v[arm]['occurrences']<5 for v in per_scope.values()))
    grouping=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map']
    paired=[{'scope_id':sid,'group':grouping.get(sid,sid),'A':v['A']['reasonable_fraction'],'B':v['B']['reasonable_fraction'],
             'difference':v['B']['reasonable_fraction']-v['A']['reasonable_fraction']} for sid,v in per_scope.items() if v['A']['observed'] and v['B']['observed']]
    clusters=defaultdict(list)
    for row in paired:clusters[row['group']].append(row['difference'])
    rng=random.Random(20260910);keys=sorted(clusters);boot=[]
    if keys:
        for _ in range(5000):
            values=[v for k in rng.choices(keys,k=len(keys)) for v in clusters[k]];boot.append(sum(values)/len(values))
        boot.sort()
    paired_summary={'scopes':len(paired),'source_groups':len(keys),'mean_difference':sum(p['difference'] for p in paired)/len(paired) if paired else None,
                    'cluster_bootstrap_95_percentile':[boot[124],boot[4874]] if boot else None,'draws':5000,'seed':20260910,
                    'limitations':'Observed-label macro rates only. Missing and insufficient remain visible; no independent human calibration.'}
    summaries={}
    for kind in ['primary-group','alternative','automatic-member']:
        summaries[kind]={arm:distribution([o for o in occ if o['kind']==kind and o.get('arm')==arm],labels) for arm in ['A','B']}
    summaries['explanation']=distribution([o for o in occ if o['kind']=='explanation'],labels)
    summaries['aspect']=distribution([o for o in occ if o['kind']=='diagnostic-aspect'],labels)
    individual_keys={(u['scope_id'],u['value']['candidates'][0]):k for k,u in mapping['unique'].items() if u['value']['task_type']=='call_person'}
    member_occurrences={arm:{kind:[] for kind in ['primary','all_options']} for arm in ['A','B']}
    for s in outcomes['scopes']:
        if s['status']!='group':continue
        for arm in ['A','B']:
            primary=s['A'] if arm=='A' else s['B']['defaultIds']
            options=s['alternatives_baseline'] if arm=='A' else s['B']['options']
            for kind,groups in [('primary',[primary]),('all_options',[o['ids'] for o in options])]:
                for ids in groups:
                    for pid in ids:
                        key=individual_keys.get((s['id'],pid))
                        member_occurrences[arm][kind].append({'scope_id':s['id'],'person_id':pid,**({'key':key} if key else {})})
    summaries['members']={arm:{kind:distribution(items,labels) for kind,items in rows.items()} for arm,rows in member_occurrences.items()}
    summaries['control_source_context']=distribution([o for o in occ if o['kind']=='derived-control-context'],labels)
    audits=[];conflicted=set()
    for o in occ:
        if o['kind']!='order-swap':continue
        a=labels.get(o['original_key'],{}).get('label');b=labels.get(o['key'],{}).get('label');status=order_audit(a,b)
        audits.append({'scope_id':o['scope_id'],'original_key':o['original_key'],'swapped_key':o['key'],'original':a,'swapped':b,'status':status})
        if status=='conflict-unresolved':conflicted.update([o['original_key'],o['key']])
    preferences=[]
    by_scope={s['id']:s for s in outcomes['scopes']}
    for o in occ:
        if o['kind']=='matched-AB-identical':preferences.append({'scope_id':o['scope_id'],'result':'identical-no-paid-comparison'})
        if o['kind']!='matched-AB':continue
        key=o['key'];label=labels.get(key,{}).get('label')
        verdict='missing' if label is None else 'order-conflict-unresolved' if key in conflicted else winner(label,mapping['unique'][key]['value']['candidates'],by_scope[o['scope_id']]['A'])
        preferences.append({'scope_id':o['scope_id'],'result':{'left':'whole-call','right':'coverage'}.get(verdict,verdict)})
    useful_sources={o['scope_id'] for o in occ if o['kind']=='primary-group' and o.get('arm')=='B' and labels.get(o['key'],{}).get('label') in {'strong','plausible'}}
    d1rows=[r for r in ledger['requests'] if r.get('purpose','').startswith('d1-')]
    byprovider={}
    for provider in ['voyage','anthropic']:
        rows=[r for r in ledger['requests'] if r['provider']==provider]
        byprovider[provider]={'requests':len(rows),'charged_microusd':sum(r['charged_microusd'] for r in rows),
          'input_tokens':sum(r.get('usage',{}).get('input_tokens',r.get('usage',{}).get('total_tokens',0)) for r in rows),
          'output_tokens':sum(r.get('usage',{}).get('output_tokens',0) for r in rows)}
    report={'run':run,'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),
      'scientific':90,'prepared':35,'unprepared':55,'numerical_groups':5,'numerical_no_group':30,'controls':30,
      'planned_unique_items':len(mapping['unique']),'planned_occurrences':len(occ),'valid_unique_items':len(labels),'paid_failed_items':failures,
      'unattempted_items':unattempted,'pre_dispatch_missing':mapping['missing'],'requests':requests,
      'labels_by_task':{kind:dict(Counter(v['label'] for k,v in labels.items() if mapping['unique'][k]['value']['task_type']==kind)) for kind in sorted({u['value']['task_type'] for u in mapping['unique'].values()})},
      'arms':arms,'paired':paired_summary,'paired_rows':paired,'per_scope':dict(per_scope),'summaries':summaries,'order_audits':audits,'matched_preferences':preferences,
      'model_useful_primary_sources':sorted(useful_sources),'independently_feasible_scopes':'unknown, never defined from returned output',
      'labels':labels,'human_judgments':0,'new_human_items':0,
      'ledger':{'authorization':AUTHORIZATION_ID,'requests':len(ledger['requests']),'charged_microusd':sum(r['charged_microusd'] for r in ledger['requests']),
        'outstanding_reserved_microusd':sum(r['reserved_microusd'] for r in ledger['requests'] if r['status']=='reserved_unknown'),
        'D1_judge_requests':len(d1rows),'D1_judge_charged_microusd':sum(r['charged_microusd'] for r in d1rows),
        'D1_judge_input_tokens':sum(r.get('usage',{}).get('input_tokens',0) for r in d1rows),'D1_judge_output_tokens':sum(r.get('usage',{}).get('output_tokens',0) for r in d1rows),
        'D1_reserved_input_bounds':sum(r['reserved_input_tokens'] for r in d1rows),'providers':byprovider,
        'exact_cache_hits':sum(e.get('kind')=='exact_cache_hit' for e in ledger.get('events',[]))},
      'holdout_scored':False,'model_human_agreement':'Unmeasured: no returned human judgments.'}
    write(OUT/('analysis-'+str(run)+'.json'),report)
    print(json.dumps({k:report[k] for k in ['run','valid_unique_items','labels_by_task','arms','paired','summaries','matched_preferences','model_useful_primary_sources','ledger']}))
    return report


if __name__=='__main__':
    analyze(int(sys.argv[1]))
