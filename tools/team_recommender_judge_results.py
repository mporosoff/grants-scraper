"""Reconcile exact cached judge results, preserving every failed/missing item."""
import json,sys
from collections import Counter
from tools.team_recommender_real_prep import DOC,OUT,sha,write
from tools.team_recommender_executor import judge_contract,policy
from tools.team_recommender_budget import AUTHORIZATION_ID
from tools.offline_spend import identity
from tools.team_recommender_learning import compare

def analyze(run,mapping_name='judge-item-map-v2.json'):
    cloud=OUT/('cloud-'+str(run));cp=json.loads((cloud/'checkpoint.json').read_bytes())
    assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=json.loads((cloud/'ledger.json').read_bytes());paid={r['key']:r for r in ledger['requests']}
    mapping=json.loads((OUT/mapping_name).read_bytes());packet=json.loads((DOC/'packets'/(mapping['packet_sha256']+'.json')).read_bytes());packet['requests']+=mapping.get('additional_requests',[])
    labels={};failures=[];unattempted=[];request_results=[];settings=policy()
    for request,rm in zip(packet['requests'],mapping['request_maps']):
        body=judge_contract(request,settings)[0];key=identity([AUTHORIZATION_ID,'development-judge',body]);row=paid.get(key)
        cache=cloud/'cache'/(key+'.json')
        if row and row['status']=='valid' and cache.exists():
            value=json.loads(cache.read_bytes());assert value['request_id']==row['id'] and value['body_sha256']==row['body_sha256']==identity(body)
            verdicts={v['item_id']:v for v in value['value']['verdicts']}
            for m in rm['items']:
                v=verdicts[m['alias']];labels[m['key']]={'label':v['verdict'],'evidence_ref':v['evidence_ref'],'shared_request_note':value['value']['note'],
                  'request_id':row['id'],'request_key':key,'model':row['model'],'provenance':'actual-offline-model-judgment'}
            request_results.append({'request_id':row['id'],'purpose':request['purpose'],'items':len(rm['items']),'status':'valid'})
        elif row:
            failures.extend({'key':m['key'],'request_id':row['id'],'status':row['status'],'reason':'terminal paid response unavailable; no replay'} for m in rm['items'])
        else:unattempted.extend(m['key'] for m in rm['items'])
    outcomes=json.loads((OUT/'development-corrected-v2.json').read_bytes());grouping=json.loads((DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json').read_bytes())
    summaries=[]
    for candidate in outcomes['results']:
        result={'candidate':candidate['id'],'scientific_reservations':90,'prepared':34,'unprepared':56,'groups':sum(s['status']=='group' for s in candidate['scopes']),'no_group_prepared':sum(s['status']=='no-group' for s in candidate['scopes']),'arms':{}}
        for arm in ['whole-call','coverage']:
            occurrences=[o for o in mapping['occurrences'] if o.get('candidate')==candidate['id'] and o.get('arm')==arm and o['kind']=='top5-individual']
            observed=[labels[o['key']]['label'] for o in occurrences if o['key'] in labels];counts=Counter(observed)
            result['arms'][arm]={'occurrences':len(occurrences),'unique_items':len({o['key'] for o in occurrences}),'valid_judgments':len(observed),'missing':len(occurrences)-len(observed),'labels':dict(counts),
              'reasonable_observed':counts['strong']+counts['plausible'],'reasonable_fraction_observed':(counts['strong']+counts['plausible'])/len(observed) if observed else None,
              'unrelated_fraction_observed':counts['unrelated']/len(observed) if observed else None,'possible_top5_slots_all_prepared':170}
        for kind in ['primary-group','matched-AB','alternative-group','MMR-comparison']:
            occ=[o for o in mapping['occurrences'] if o.get('candidate')==candidate['id'] and o['kind']==kind]
            result[kind]={'occurrences':len(occ),'identical_no_request':sum('key' not in o for o in occ),'unique_items':len({o['key'] for o in occ if 'key' in o}),'valid':sum(o.get('key') in labels for o in occ),'labels':dict(Counter(labels[o['key']]['label'] for o in occ if o.get('key') in labels))}
        summaries.append(result)
    swaps=[]
    for o in mapping['occurrences']:
        if o['kind']!='order-swap':continue
        a=labels.get(o['original_key']);b=labels.get(o['key']);expected={'A':'B','B':'A','tie':'tie','unresolved':'unresolved'}
        swaps.append({'original_key':o['original_key'],'swapped_key':o['key'],'original':a['label'] if a else None,'swapped':b['label'] if b else None,
          'status':'missing' if not a or not b else 'unresolved' if a['label']=='unresolved' or b['label']=='unresolved' else 'consistent' if expected[a['label']]==b['label'] else 'conflict-unresolved'})
    conflicts={k for s in swaps if s['status']=='conflict-unresolved' for k in [s['original_key'],s['swapped_key']]}
    for result,candidate in zip(summaries,outcomes['results']):
        by_scope={s['id']:s for s in candidate['scopes']}
        for kind in ['matched-AB','MMR-comparison']:
            interpreted=[]
            for o in mapping['occurrences']:
                if o.get('candidate')!=candidate['id'] or o['kind']!=kind:continue
                if 'key' not in o:interpreted.append('identical-no-paid-comparison');continue
                key=o['key'];label=labels.get(key)
                if not label:interpreted.append('missing');continue
                if key in conflicts:interpreted.append('order-conflict-unresolved');continue
                verdict=label['label']
                if verdict not in ('A','B'):interpreted.append(verdict);continue
                winners=sorted(mapping['unique'][key]['value']['candidates'][verdict]);r=by_scope[o['scope_id']]
                improved=r['B']['defaultIds'] if kind=='matched-AB' else r['MMR']['options'][o['position']-1]['ids']
                interpreted.append(('coverage' if kind=='matched-AB' else 'mmr') if winners==sorted(improved) else ('whole-call' if kind=='matched-AB' else 'no-mmr'))
            result[kind]['interpreted_with_order_audit']=dict(Counter(interpreted))
    middle={s['id']:s for c in outcomes['results'] if c['id']=='bounded-middle' for s in c['scopes']};examples=[]
    for key,label in labels.items():
        u=mapping['unique'][key]
        if u['value']['task_type']!='individual':continue
        sid=u['scope_id'];pid=u['value']['candidates'][0];row=next(r for r in middle[sid]['rows'] if r['id']==pid)
        edge=max(row['edges'],key=lambda e:e['score'])
        examples.append({'key':key,'scope_id':sid,'person_id':pid,'group_id':grouping['source_group_map'].get(sid,sid),'label':label['label'],
          'features':edge['features'],'fixed_score':edge['score'],'whole_call':row['baseline']})
    report={'run':run,'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'original_unique_items':len(mapping['unique']),'original_occurrences':len(mapping['occurrences']),
      'planned_v2_items':sum(len(r['items']) for r in packet['requests']),'valid_unique_items':len(labels),'new_failed_items':failures,'prior_failed_items':mapping['failed_items'],
      'omitted_optional_source_items':len(mapping['omitted_source_only_items']),'unattempted':unattempted,'valid_requests':request_results,
      'labels_by_task':{kind:dict(Counter(v['label'] for k,v in labels.items() if mapping['unique'][k]['value']['task_type']==kind)) for kind in ['individual','group','comparison','source_control','explanation_audit']},
      'candidates':summaries,'order_swap':swaps,'labels':labels,'human_judgments':0,'human_model_agreement':'unmeasured; no returned human judgments',
      'uncertainty':'Repeated algorithm occurrences reuse exact labels and are not independent observations. Group and MMR evidence comes from one scientific source; no population-level precision claim. Missing and insufficient labels remain separate. Order conflicts are unresolved, never rerun.',
      'spend_usd':sum(r['charged_microusd'] for r in ledger['requests'])/1e6,'calls':len(ledger['requests'])}
    private=OUT/'analysis-private'
    private.mkdir(exist_ok=True)
    write(private/('c2-judge-results-'+str(run)+'.json'),report)
    learning=compare(examples);write(private/('c2-learning-'+str(run)+'.json'),learning)
    write(OUT/('learning-examples-'+str(run)+'.json'),examples)
    print(json.dumps({k:report[k] for k in ['run','valid_unique_items','labels_by_task','spend_usd','calls']}))
    print(json.dumps({'learning':learning['status'],'usable':learning['binary_usable'],'groups':learning['groups']}))
if __name__=='__main__':analyze(int(sys.argv[1]),sys.argv[2] if len(sys.argv)>2 else 'judge-item-map-v2.json')
