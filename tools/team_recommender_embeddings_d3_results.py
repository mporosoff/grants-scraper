"""Reconcile real D3 grades and preserve every development denominator."""
import json
from pathlib import Path
from collections import Counter,defaultdict
from tools.team_recommender_real_prep import ROOT,DOC,write,sha
from tools.team_recommender_executor import policy,judge_contract,result_value
from tools.team_recommender_evaluation_d1 import map_verdicts,order_audit,winner
from tools.team_recommender_ranking_d2_results import grouped_difference
from tools.team_recommender_revision_results import distribution
from tools.offline_spend import identity

OUT=ROOT/'outputs/team-recommender-d3'
def read(p):return json.loads(p.read_bytes())

def analyze(cloud):
    cp=read(cloud/'checkpoint.json');assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=read(cloud/'ledger.json');prior=read(OUT/'cloud-34537699670/ledger.json');assert ledger['requests'][:len(prior['requests'])]==prior['requests']
    paid={r['key']:r for r in ledger['requests']};assert len(paid)==len(ledger['requests']) and all(r['attempt']==1 for r in paid.values())
    mapping=read(OUT/'judge-item-map-d3-v2.json');packet=read(DOC/'packets'/(mapping['packet_sha256']+'.json'));settings=policy()
    labels=dict(read(ROOT/'outputs/team-recommender-d2/analysis-34510982749.json')['labels']);new={};failures=[];unattempted=[]
    for index,(request,aliases) in enumerate(zip(packet['requests'],mapping['request_maps'])):
        contract=judge_contract(request,settings);body=contract[0];key=identity([settings['authorization_id'],'development-judge',body]);row=paid.get(key)
        if row is None:unattempted.append({'request_index':index,'items':aliases['items']});continue
        cache=cloud/'cache'/(key+'.json')
        if row['status']!='valid' or not cache.exists():
            failures.extend({'key':m['key'],'request_id':row['id'],'status':row['status'],'reason':'paid failure or lost result; no replay'} for m in aliases['items']);continue
        retained=read(cache);assert retained['request_id']==row['id'] and retained['body_sha256']==row['body_sha256']==identity(body)
        value=result_value('development-judge',{'model':row['model'],'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(retained['value'])}]},request,contract,settings)
        for k,v in map_verdicts(value,{m['alias']:m['key'] for m in aliases['items']}).items():
            assert k not in labels
            new[k]={'label':v['verdict'],'evidence_ref':v['evidence_ref'],'reason':v['reason'],'request_id':row['id'],'request_key':key,'protocol':'D1F','provenance':'actual-offline-model-judgment'}
    labels.update(new);occ=mapping['occurrences'];outputs=read(OUT/'D3-candidate-outputs.json');groups=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map']
    scopes=[s['id'] for s in outputs['arms']['E0']['scopes'] if s['status']!='unprepared'];action={s['id'] for s in outputs['arms']['E0']['scopes'] if s.get('action_allowed')}
    by_scope=defaultdict(dict);arms={};summary={}
    for arm in sorted({o.get('arm') for o in occ if o['kind']=='top5'}):
        top=[o for o in occ if o['kind']=='top5' and o['arm']==arm];r=distribution(top,labels)
        for sid in scopes:by_scope[sid][arm]=distribution([o for o in top if o['scope_id']==sid],labels)
        rates=[by_scope[sid][arm]['reasonable_fraction'] for sid in scopes if by_scope[sid][arm]['observed']]
        r.update(macro_reasonable=sum(rates)/len(rates) if rates else None,observed_scopes=len(rates),prepared_scopes=35,possible_slots=175,
          empty_lists=sum(by_scope[sid][arm]['occurrences']==0 for sid in scopes),short_nonempty_lists=sum(0<by_scope[sid][arm]['occurrences']<5 for sid in scopes),action_admitted=distribution([o for o in top if o['scope_id'] in action],labels))
        arms[arm]=r
    for arm,a in outputs['arms'].items():
        items=[o for o in occ if o.get('arm')==arm];d={}
        for name,kind,primary in [('primary_groups','option-group',True),('primary_members','option-member',True),('all_option_groups','option-group',False),('all_option_members','option-member',False)]:
            rows=[o for o in items if o['kind']==kind and (not primary or o['rank']==1)];d[name]=distribution(rows,labels);d[name]['action_admitted']=distribution([o for o in rows if o['scope_id'] in action],labels)
        d['per_option_rank']={str(rank):{kind:distribution([o for o in items if o['kind']==kind and o['rank']==rank],labels) for kind in ['option-group','option-member']} for rank in range(1,9)}
        d['explanations']=distribution([o for o in items if o['kind']=='explanation'],labels)
        d['matched_A_groups']=distribution([o for o in occ if o['kind']=='primary-A-matched' and o['arm']=='A-'+arm],labels)
        d['matched_A_members']=distribution([o for o in occ if o['kind']=='primary-A-member' and o['arm']=='A-'+arm],labels)
        d['yield']={'prepared':35,'groups':sum(s['status']=='group' for s in a['scopes']),'no_group':sum(s['status']=='no-group' for s in a['scopes']),'unprepared':55,'action_groups':sum(s['status']=='group' and s.get('action_allowed',False) for s in a['scopes']),'action_prepared':26,'independent_feasibility':'unknown'}
        summary[arm]=d
    paired={}
    comparisons=[('E0',a) for a in ['E0-C','E1','E2','E3']]+[('E0-C','E1'),('E1','E2'),('E2','E3')]+[('A-'+a,a) for a in outputs['arms']]
    for left,right in comparisons:
        rows=[{'scope_id':sid,'group':groups.get(sid,sid),'difference':by_scope[sid][right]['reasonable_fraction']-by_scope[sid][left]['reasonable_fraction']} for sid in scopes if by_scope[sid][left]['observed'] and by_scope[sid][right]['observed']]
        paired[left+'->'+right]=grouped_difference(rows)
    audits=[];conflicted=set()
    for o in occ:
        if o['kind']!='order-swap':continue
        a=labels.get(o['original_key'],{}).get('label');b=labels.get(o['key'],{}).get('label');status=order_audit(a,b);audits.append({'scope_id':o['scope_id'],'original':a,'swapped':b,'status':status,'original_key':o['original_key']})
        if status=='conflict-unresolved':conflicted.add(o['original_key'])
    preferences=[]
    for row in mapping['ordering']:
        label=labels.get(row['key'],{}).get('label');v='missing' if label is None else 'order-conflict-unresolved' if row['key'] in conflicted else winner(label,row['candidates'],row['A_members'])
        preferences.append({'scope_id':row['scope_id'],'arm':row['arm'],'result':{'left':'whole-call','right':'coverage'}.get(v,v),'label':label})
    primary0=summary['E0']['primary_members'];group0=summary['E0']['primary_groups'];qualifiers=[];choices={}
    for arm in ['E1','E2','E3']:
        p=summary[arm]['primary_members'];g=summary[arm]['primary_groups'];top=arms[arm];delta=paired['E0->'+arm]['mean_difference']
        checks={'paired_relevance_gain_at_least_5pp':delta is not None and delta>=.05,'unrelated_no_worse':p['unrelated_fraction'] is not None and p['unrelated_fraction']<=primary0['unrelated_fraction'],
          'reasonable_primary_yield_preserved':p['reasonable_observed']>=.9*primary0['reasonable_observed'],'useful_group_yield_preserved':g['reasonable_observed']>=.9*group0['reasonable_observed'],
          'primary_grade_coverage':p['observed']>=.8*p['occurrences'] and p['occurrences']>0,'top5_grade_coverage':top['observed']>=.8*top['occurrences'] and top['occurrences']>0}
        choices[arm]=checks
        if all(checks.values()):qualifiers.append(arm)
    chosen=max(qualifiers,key=lambda a:(summary[a]['primary_groups']['reasonable_observed'],summary[a]['primary_members']['reasonable_observed'],-summary[a]['primary_members']['labels'].get('unrelated',0),-['E1','E2','E3'].index(a))) if qualifiers else None
    examples=[];names={p['id']:p['name'] for p in read(DOC/'prepared/d1/directory.json')['researchers']}
    for key,u in mapping['unique'].items():
        grade=labels.get(key)
        if grade and u['value']['task_type']=='call_person':
            pid=u['value']['candidates'][0];examples.append({'key':key,'scope_id':u['scope_id'],'name':names[pid],'person_id':pid,'label':grade['label'],'reason':grade.get('reason'),'profile_evidence':[{'text':p['text'],'label':p['label'],'research_summary':p['research_summary'],'source_url':p['source_url']} for p in u['value']['profile_evidence']],
              'occurrences':[o for o in occ if o.get('key')==key and o.get('arm') in {'E1','E2','E3'}]})
    d3=[r for r in ledger['requests'] if r.get('purpose','').startswith('d3-')];judge=[r for r in d3 if r['provider']=='anthropic'];embed=[r for r in d3 if r['provider']=='voyage'];total=sum(r['charged_microusd'] for r in ledger['requests']);reserved=sum(r['reserved_microusd'] for r in ledger['requests'] if r['status']=='reserved_unknown')
    budget={'authorization':settings['authorization_id'],'prior_D3_microusd':2279110,'D3_embedding_requests':len(embed),'D3_embedding_tokens':sum(r['usage']['total_tokens'] for r in embed),'D3_embedding_microusd':sum(r['charged_microusd'] for r in embed),
      'D3_judge_requests':len(judge),'D3_judge_input_tokens':sum((r.get('usage') or {}).get('input_tokens',0) for r in judge),'D3_judge_output_tokens':sum((r.get('usage') or {}).get('output_tokens',0) for r in judge),'D3_judge_microusd':sum(r['charged_microusd'] for r in judge),
      'D3_total_microusd':sum(r['charged_microusd'] for r in d3),'cumulative_microusd':total,'reserved_microusd':reserved,'remaining_total_microusd':10000000-total-reserved,'remaining_stage2_microusd':6000000-total-reserved,
      'lifetime_requests':len(ledger['requests']),'owner_run':cp['run_id'],'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),'historical_other_task_credit':0}
    result={'version':'D3-real-development-results','run':cp['run_id'],'arms':arms,'summary':summary,'paired':paired,'per_scope':dict(by_scope),'order_audits':audits,'preferences':preferences,'selection_checks':choices,'selected_representation':chosen,
      'labels':labels,'new_labels':new,'new_valid_items':len(new),'new_labels_by_task':{t:dict(Counter(v['label'] for k,v in new.items() if mapping['unique'][k]['value']['task_type']==t)) for t in sorted({mapping['unique'][k]['value']['task_type'] for k in new})},
      'failed_items':failures,'unattempted_requests':unattempted,'unsubmitted':mapping['missing'],'examples':examples,'budget':budget,'human_judgments':0,'new_human_items':0,'holdout_scored':False,
      'controls':{'reserved':30,'deterministic_source_controls':12,'unprepared_origins':18,'new_semantic_control_grades':0},'limits':'Development only. Machine judgments remain noisy; no human validation, independent feasible-scope yield or Stage 3 gate is established.'}
    write(OUT/('analysis-'+str(cp['run_id'])+'.json'),result);write(DOC/('receipts/d3-development-results-'+str(cp['run_id'])+'.json'),{k:v for k,v in result.items() if k not in {'labels','new_labels','examples'}})
    print(json.dumps({k:result[k] for k in ['new_valid_items','new_labels_by_task','failed_items','unattempted_requests','selection_checks','selected_representation','budget']},indent=2))
    for arm in outputs['arms']:print(json.dumps({'arm':arm,'top5':arms[arm],'primary_groups':summary[arm]['primary_groups'],'primary_members':summary[arm]['primary_members'],'yield':summary[arm]['yield']}))

if __name__=='__main__':
    import sys
    analyze(Path(sys.argv[1]))
