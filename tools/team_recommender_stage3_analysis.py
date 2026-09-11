"""Locked source-group analysis of one held-out E2/A-E2 run; no fitting."""
import json
from collections import Counter,defaultdict
import numpy as np
from tools.team_recommender_real_prep import ROOT,DOC,write,sha
from tools.team_recommender_executor import policy,judge_contract,result_value
from tools.offline_spend import identity

OUT=ROOT/'outputs/team-recommender-stage3'
def read(p):return json.loads(p.read_bytes())
GOOD={'strong','plausible'}

def main():
    cloud=OUT/'cloud-judge-complete';cp=read(cloud/'checkpoint.json')
    assert cp['files']=={p.relative_to(cloud).as_posix():sha(p.read_bytes()) for p in cloud.rglob('*.json') if p.name!='checkpoint.json'}
    ledger=read(cloud/'ledger.json');start=read(OUT/'cloud-start/ledger.json');assert ledger['requests'][:475]==start['requests']
    allocation=read(DOC/'manifests/stage3-judgment-allocation-v1.json');packet=read(OUT/'judge-packet-v1.json');settings=policy();paid={r['key']:r for r in ledger['requests']};verdicts={};request_rows=[];serialization_corrections=[]
    for request,entry in zip(packet['requests'],allocation['packets']):
        contract=judge_contract(request,settings);key=identity([settings['authorization_id'],'development-judge',contract[0]]);row=paid[key]
        assert row['body_sha256']==identity(contract[0])
        from tools.team_recommender_stage3_executor import judge_items
        assert judge_items(request)==entry['keys']
        if row['body_sha256']!=entry['body_sha256']:
            original={**request,'items':[{**{k:i[k] for k in ['task_type','candidates','profile_documents']},**{k:i[k] for k in ['target_aspect','explanation'] if k in i},'item_id':i['item_id']} for i in request['items']]}
            before=judge_contract(original,settings)[0]
            assert identity(before)==entry['body_sha256']
            assert json.loads(before['messages'][0]['content'])==json.loads(contract[0]['messages'][0]['content'])
            serialization_corrections.append({'request_key':key,'pre_write_body_sha256':entry['body_sha256'],'committed_packet_body_sha256':row['body_sha256'],'scientific_item_keys_unchanged':True,'parsed_provider_content_equal':True})
        request_rows.append({k:row[k] for k in ['id','key','status','charged_microusd','usage','purpose']})
        if row['status']!='valid':continue
        cache=read(cloud/'cache'/(key+'.json'));assert cache['request_id']==row['id'] and cache['body_sha256']==row['body_sha256']
        value=result_value('development-judge',{'model':settings['judge_model'],'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(cache['value'])}]},request,contract,settings)
        for v in value['verdicts']:
            k=entry['keys'][int(v['item_id'][1:])-1];assert k not in verdicts;verdicts[k]={**v,'request_key':key,'request_id':row['id']}
    outputs=read(OUT/'heldout-outputs-v1.json');rows={r['id']:r for r in outputs['rows']};groups=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')['source_group_map']
    occurrences=[{**o,'judgment':verdicts.get(o['key']),'source_group':groups.get(o['scope_id'],o['scope_id'])} for o in allocation['occurrences']]
    def summary(items):
        counts=Counter(o['judgment']['verdict'] if o['judgment'] else 'missing' for o in items)
        return {'occurrences':len(items),'unique_items':len({o['key'] for o in items}),'labels':dict(counts),'reasonable':sum(counts[x] for x in GOOD),'missing_or_insufficient':counts['missing']+counts['insufficient-information']+counts['unresolved']}
    def clustered(items,fn):
        clusters=defaultdict(list)
        for o in items:clusters[o['source_group']].append(o)
        if not clusters:return {'source_groups':0,'point':None,'CI95':None}
        keys=sorted(clusters);values=np.array([fn(clusters[k]) for k in keys]);rng=np.random.default_rng(20260910)
        boots=values[rng.integers(0,len(keys),size=(5000,len(keys)))].mean(axis=1)
        return {'source_groups':len(keys),'point':float(values.mean()),'CI95':[float(x) for x in np.quantile(boots,[.025,.975])]}
    metrics={}
    for arm in ['E2','A-E2']:
        m={}
        for role in ['top5','primary-member','primary','alternative','alternative-member']:
            items=[o for o in occurrences if o.get('arm')==arm and o['role']==role];m[role]=summary(items)
            m[role]['reasonable_fraction_source_CI']=clustered(items,lambda os:sum(bool(o['judgment'] and o['judgment']['verdict'] in GOOD) for o in os)/len(os))
            m[role]['missing_label_bounds']=[m[role]['reasonable']/len(items),(m[role]['reasonable']+m[role]['missing_or_insufficient'])/len(items)] if items else None
            m[role]['reasonable_bounds_source_weighted']=[m[role]['reasonable_fraction_source_CI']['point'],clustered(items,lambda os:sum(not o['judgment'] or o['judgment']['verdict'] in GOOD|{'insufficient-information','unresolved'} for o in os)/len(os))['point']]
            m[role]['unrelated_fraction_source_CI']=clustered(items,lambda os:sum(bool(o['judgment'] and o['judgment']['verdict']=='unrelated') for o in os)/len(os))
            m[role]['action_eligible']=summary([o for o in items if rows[o['scope_id']]['action_allowed']])
        metrics[arm]=m
    comparisons=[]
    for o in occurrences:
        if o['role'] not in {'comparison','order-swap'}:continue
        v=o['judgment']['verdict'] if o['judgment'] else 'missing';comparisons.append({**o,'winner':o.get('mapping',{}).get(v,v)})
    primary=[o for o in comparisons if o['role']=='comparison']
    preference=clustered(primary,lambda os:sum(1 if o['winner']=='E2' else -1 if o['winner']=='A-E2' else 0 for o in os)/len(os))
    contradictions=[]
    for o in occurrences:
        if o['role']!='primary' or not o['judgment'] or o['judgment']['verdict'] not in GOOD:continue
        members=[x for x in occurrences if x['scope_id']==o['scope_id'] and x.get('arm')==o.get('arm') and x['role']=='primary-member']
        bad=[x['key'] for x in members if x['judgment'] and x['judgment']['verdict']=='unrelated']
        if bad:contradictions.append({'scope_id':o['scope_id'],'arm':o['arm'],'group_grade':o['judgment']['verdict'],'unrelated_member_keys':bad})
    new=ledger['requests'][475:];judge=ledger['requests'][481:]
    accounting={'authorization_id':settings['authorization_id'],'cloud_run':cp['run_id'],'trusted_code':cp['code_sha'],'checkpoint_sha256':sha((cloud/'checkpoint.json').read_bytes()),'ledger_sha256':sha((cloud/'ledger.json').read_bytes()),'prior_microusd':3135333,'stage3_microusd':sum(r['charged_microusd'] for r in new),'cumulative_microusd':sum(r['charged_microusd'] for r in ledger['requests']),'outstanding_microusd':sum(r['reserved_microusd'] for r in ledger['requests'] if r['status']=='reserved_unknown'),'prior_requests':475,'new_requests':len(new),'cumulative_requests':len(ledger['requests']),'remaining_slots':690-len(ledger['requests']),'remaining_microusd':10000000-sum(r['charged_microusd'] for r in ledger['requests']),'judge_requests':len(judge),'judge_valid_requests':sum(r['status']=='valid' for r in judge),'judge_failed_requests':sum(r['status']=='failed' for r in judge),'judge_input_tokens':sum(r['usage']['input_tokens'] for r in judge),'judge_output_tokens':sum(r['usage']['output_tokens'] for r in judge),'judge_microusd':sum(r['charged_microusd'] for r in judge),'embedding_tokens':sum(r['usage']['total_tokens'] for r in new if r['provider']=='voyage'),'embedding_microusd':2136,'duplicate_paid_logical_requests':len(ledger['requests'])-len({r['key'] for r in ledger['requests']}),'historical_other_task_usd':11.971342,'historical_spend_credit':0}
    result={'version':'S3-heldout-analysis-v2','supersedes':'v1 retained; adds source-weighted missing-label bounds without changing observations or analysis rule','candidate':'E2-D3-combined-v1-frozen','comparator':'A-E2','inputs_sha256':allocation['outputs_sha256'],'judge_protocol':'S3-E2-complete-v1','actual_unique_judgments':len(verdicts),'allocated_unique':allocation['accepted_unique'],'planned_unique':allocation['unique_items'],'unique_labels':dict(Counter(v['verdict'] for v in verdicts.values())),'metrics':metrics,'comparisons':summary(primary),'comparison_winners':dict(Counter(o['winner'] for o in primary)),'comparison_source_CI':preference,'group_member_disagreements':contradictions,'source_controls':summary([o for o in occurrences if o['role']=='source-control']),'explanations':summary([o for o in occurrences if o['role']=='explanation']),'order_swaps':summary([o for o in occurrences if o['role']=='order-swap']),'yield':{'scientific':90,'prepared':39,'unprepared':51,'E2_group':15,'E2_no_group':24,'action_eligible_prepared':35,'action_eligible_E2_group':14,'action_eligible_E2_no_group':21,'A_E2_group':17,'feasible_denominator':None,'feasible_yield':'UNMEASURED'},'accounting':accounting,'human_development_requested':20,'human_development_returned':0,'human_final_returned':0,'pre_serialization_receipt_corrections':len(serialization_corrections),'ordinary_in_task_analysis_is_not_independent_judging':True,'no_fit_or_retuning':True}
    write(DOC/'receipts/stage3-serialization-audit-v1.json',{'corrections':serialization_corrections,'reason':'Manifest body digest computed before canonical packet write; embedded JSON property order changed on canonical restoration. Exact committed packet and semantic item hashes remained frozen and parsed provider content is proven identical. No evidence, scorer or paid request changed; no rejudging.'});write(DOC/'receipts/stage3-heldout-analysis-v2.json',result);write(OUT/'judged-occurrences-v1.json',occurrences);write(OUT/'judge-adoption-v1.json',{'requests':request_rows,'verdicts':verdicts,'comparisons':comparisons});(DOC/'budget-ledger.json').write_bytes((cloud/'ledger.json').read_bytes())
    print(json.dumps({k:v for k,v in result.items() if k not in ['metrics','accounting','group_member_disagreements']},indent=2));print(json.dumps(metrics,indent=2));print(json.dumps(accounting,indent=2))
if __name__=='__main__':main()
