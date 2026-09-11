"""Materialize the predeclared finite held-out questions before any verdict."""
import copy
import json
from collections import Counter
from tools.team_recommender_real_prep import ROOT,DOC,write,sha
from tools.team_recommender_stage3_executor import PROTOCOL,judge_contract,judge_items
from tools.team_recommender_executor import policy,validate_packet
from tools.offline_spend import identity,Deferred

OUT=ROOT/'outputs/team-recommender-stage3'
def read(p):return json.loads(p.read_bytes())

def main():
    lock=read(DOC/'manifests/stage3-validation-lock-v2.json');config=read(ROOT/'config/team_recommender_executor/inputs-stage3.json')
    outputs=read(OUT/'heldout-outputs-v1.json');rows={r['id']:r for r in outputs['rows']};settings=policy()
    occurrences=[];unique={};queues=[{}, {}, {}];optional={};slots=[]
    def request(sid,purpose,items):
        ctx=config['contexts'][sid]
        return {'protocol':PROTOCOL,'scope_id':sid,'purpose':purpose,'source_evidence':ctx['source_evidence'],'aspects':ctx['aspects'],'items':[{**v,'item_id':'i%02d'%i} for i,v in enumerate(items,1)]}
    def add(sid,kind,candidates,occurrence,queue,**extra):
        people=set().union(*map(set,candidates.values())) if isinstance(candidates,dict) else set(candidates)
        item={'task_type':kind,'candidates':candidates,'profile_documents':[config['profile_documents'][p] for p in sorted(people)],**extra}
        key=judge_items(request(sid,'s3-primary',[item]))[0]
        occurrences.append({'scope_id':sid,'key':key,**occurrence})
        if key not in unique:
            unique[key]={'scope_id':sid,'item':item};queue.setdefault(sid,[]).append(key)
        return key
    mappings={}
    for sid in lock['source_order']:
        r=rows[sid]
        if r['status']=='unprepared':continue
        B,A=r['B']['ids'],r['A']['ids'];swapped=bool(int(sha('stage3-e2-AB-v1|'+sid),16)&1);mappings[sid]={'A':'E2' if swapped else 'A-E2','B':'A-E2' if swapped else 'E2'}
        if B:
            add(sid,'group_usefulness',B,{'arm':'E2','role':'primary'},queues[0])
            for rank,p in enumerate(B,1):add(sid,'call_person',[p],{'arm':'E2','role':'primary-member','rank':rank},queues[0])
        elif r['B5']:add(sid,'call_person',[r['B5'][0]],{'arm':'E2','role':'no-group-top1'},queues[0])
        if A:
            add(sid,'group_usefulness',A,{'arm':'A-E2','role':'primary'},queues[1])
            for rank,p in enumerate(A,1):add(sid,'call_person',[p],{'arm':'A-E2','role':'primary-member','rank':rank},queues[1])
        if A and B:
            add(sid,'comparison',{'A':B if swapped else A,'B':A if swapped else B},{'role':'comparison','mapping':mappings[sid]},queues[1])
        for arm,key in [('E2','B5'),('A-E2','A5')]:
            for rank,p in enumerate(r[key],1):add(sid,'call_person',[p],{'arm':arm,'role':'top5','rank':rank},queues[2])
    for purpose,cap in [('s3-alternative',12),('s3-explanation',6),('s3-swap',6)]:
        queue=optional.setdefault(purpose,{})
        for sid in lock['source_order'][:cap]:
            r=rows[sid];B=r.get('B',{}).get('ids',[]);A=r.get('A',{}).get('ids',[]);opts=r.get('B',{}).get('options',[])
            available=len(opts)>=2 if purpose=='s3-alternative' else bool(B) if purpose=='s3-explanation' else bool(A and B)
            slots.append({'scope_id':sid,'purpose':purpose,'available':available})
            if not available:continue
            if purpose=='s3-alternative':
                add(sid,'group_usefulness',opts[1]['ids'],{'arm':'E2','role':'alternative','rank':2},queue)
                for p in opts[1]['ids']:add(sid,'call_person',[p],{'arm':'E2','role':'alternative-member','rank':2},queue)
            elif purpose=='s3-explanation':add(sid,'explanation_audit',B,{'arm':'E2','role':'explanation'},queue,explanation=r['explanation'])
            else:
                m=mappings[sid];add(sid,'comparison',{'A':A if m['A']=='E2' else B,'B':B if m['B']=='A-E2' else A},{'role':'order-swap','mapping':{a:('E2' if v=='A-E2' else 'A-E2') for a,v in m.items()}},queue)
    controls=sorted(config['controls'],key=lambda x:lock['source_order'].index(x['origin_scope_id']))
    for control in controls[:6]:
        sid=control['origin_scope_id'];add(sid,'source_suitability',[],{'role':'source-control','control_id':control['case_id']},optional.setdefault('s3-control',{}))
    packets=[];missing=[];accepted=set();bound_sum=0;purpose_count=Counter()
    def pack_queue(queue,purpose,round_number):
        nonlocal bound_sum
        pending={s:list(ks) for s,ks in queue.items()}
        while any(pending.values()):
            for sid in lock['source_order']:
                batch=[]
                while pending.get(sid) and len(batch)<3:
                    k=pending[sid][0]
                    if k in accepted:pending[sid].pop(0);continue
                    try:
                        req=request(sid,purpose,[unique[x]['item'] for x in batch+[k]]);contract=judge_contract(req,settings)
                    except (Deferred,ValueError) as exc:
                        if batch:break
                        pending[sid].pop(0);missing.append({'key':k,'scope_id':sid,'reason':str(exc),'stage':'complete-evidence-dry-run'});continue
                    batch.append(k);pending[sid].pop(0)
                if not batch:continue
                req=request(sid,purpose,[unique[x]['item'] for x in batch]);body,bound,*_=judge_contract(req,settings)
                cap=134 if purpose=='s3-primary' else dict(lock['judge_plan']['optional_caps']).get({'s3-alternative':'rank2_alternatives','s3-explanation':'explanations','s3-swap':'order_swaps','s3-control':'semantic_controls'}[purpose])
                if purpose_count[purpose]>=cap or len(packets)>=164 or bound_sum+bound>1064960:
                    missing.extend({'key':k,'scope_id':sid,'reason':'fixed_request_or_complete_input_budget','stage':'allocation'} for k in batch);continue
                accepted.update(batch);bound_sum+=bound;purpose_count[purpose]+=1
                packets.append({'request':req,'keys':batch,'input_bound':bound,'body_sha256':identity(body),'round':round_number,'purpose':purpose})
    # Preserve finite optional capacity first in accounting; dispatch/order remains
    # primary rounds first. Selection has no access to any model result.
    for purpose,q in optional.items():pack_queue(q,purpose,'optional')
    for i,q in enumerate(queues,1):pack_queue(q,'s3-primary',i)
    packets.sort(key=lambda p: (4 if p['round']=='optional' else p['round']))
    packet={'schema_version':1,'authorization_id':settings['authorization_id'],'registry_generation':settings['registry_generation'],'operation':'development-judge','requests':[p['request'] for p in packets]}
    validate_packet(packet,settings)
    ph=write(OUT/'judge-packet-v1.json',packet)
    write(DOC/'packets'/(ph+'.json'),packet)
    manifest={'version':'S3-E2-complete-judgment-allocation-v1','lock_sha256':sha((DOC/'manifests/stage3-validation-lock-v2.json').read_bytes()),'outputs_sha256':sha((OUT/'heldout-outputs-v1.json').read_bytes()),'packet_sha256':ph,'requests':len(packets),'input_bound':bound_sum,'output_bound':len(packets)*512,'conservative_microusd':sum((p['input_bound']*5+1)//2+5120 for p in packets),'purpose_counts':dict(purpose_count),'unique_items':len(unique),'accepted_unique':len(accepted),'occurrences':occurrences,'optional_slots':slots,'missing':missing,'packets':[{k:v for k,v in p.items() if k!='request'} for p in packets],'judge_responses_observed':0,'complete_people_projection':True,'algorithm_identities_and_scores_sent':False,'historical_labels_reused':0,'mapping':mappings}
    write(DOC/'manifests/stage3-judgment-allocation-v1.json',manifest)
    write(OUT/'judge-unique-items-v1.json',unique)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['occurrences','optional_slots','missing','packets','mapping']},indent=2));print('missing',Counter(x['reason'] for x in missing))

if __name__=='__main__':main()
