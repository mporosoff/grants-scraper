"""Blinded, finite development judgments and a pre-judge human selection."""
import json
from collections import Counter
from tools.team_recommender_real_prep import ROOT,DOC,OUT,sha,canonical,write,packet
from tools.team_recommender_executor import policy,judge_contract
from tools.offline_spend import Deferred

def prepare():
    inp=json.loads((OUT/'real-inputs-v2.json').read_bytes());out=json.loads((OUT/'development-corrected-v2.json').read_bytes());settings=policy()
    sources={s['id']:s for s in inp['sources']};people={p['id']:p for p in inp['directory']['researchers']};results={c['id']:{s['id']:s for s in c['scopes']} for c in out['results']}
    scopes=list(results['engineering-v2.1']);unique={};occurrences=[];missing=[];ordering=[]
    def evidence(ids):
        return [{'id':c['claim_id'],'person_id':pid,'claim_id':c['claim_id'],'revision':c['revision'],'text':c['evidence'],'source_url':c['source_urls'][0]} for pid in sorted(set(ids)) for c in people[pid]['claims'] if c['status']=='active']
    def item(sid,kind,candidates,occurrence,explanation=None):
        ids=[p for g in candidates.values() for p in g] if isinstance(candidates,dict) else candidates
        value={'task_type':kind,'profile_evidence':evidence(ids),'candidates':candidates}
        if explanation is not None:value['explanation']=explanation
        key=sha(canonical([sid,value]));unique.setdefault(key,{'scope_id':sid,'value':value});occurrences.append({'key':key,**occurrence});return key
    comparisons=[]
    def compare(sid,left,right,occ):
        if len(left)!=len(right) or not left:return None
        if sorted(left)==sorted(right):
            occurrences.append({'kind':'identical-comparison-no-request',**occ});return None
        canonical_groups=sorted([sorted(left),sorted(right)])
        # Alternation is balanced within the one realized source stratum. Its
        # substantive input and sequence are frozen before any verdict exists.
        flip=len(ordering)%2;A,B=canonical_groups[flip],canonical_groups[1-flip]
        key=item(sid,'comparison',{'A':A,'B':B},occ)
        ordering.append({'key':key,'A':A,'B':B,'left':left,'right':right,'source_id':sid})
        comparisons.append(key);return key
    for sid in scopes:
        item(sid,'source_control',[],{'scope_id':sid,'kind':'source-coherence'})
        eligible=[(cid,r[sid]) for cid,r in results.items() if r[sid]['status']!='unprepared']
        for cid,r in eligible:
            for arm,ids in [('whole-call',r['A5']),('coverage',r['B5'])]:
                for rank,pid in enumerate(ids):item(sid,'individual',[pid],{'scope_id':sid,'candidate':cid,'arm':arm,'rank':rank+1,'kind':'top5-individual'})
            if r['B']['defaultIds']:
                for arm,ids in [('whole-call',r['A']),('coverage',r['B']['defaultIds'])]:item(sid,'group',ids,{'scope_id':sid,'candidate':cid,'arm':arm,'kind':'primary-group'})
                compare(sid,r['A'],r['B']['defaultIds'],{'scope_id':sid,'candidate':cid,'kind':'matched-AB'})
                for mode,key in [('no-mmr','B'),('mmr','MMR')]:
                    for pos,option in enumerate(r[key]['options']):item(sid,'group',option['ids'],{'scope_id':sid,'candidate':cid,'mode':mode,'position':pos+1,'kind':'alternative-group'})
                for pos,(a,b) in enumerate(zip(r['B']['options'],r['MMR']['options'])):
                    compare(sid,a['ids'],b['ids'],{'scope_id':sid,'candidate':cid,'position':pos+1,'kind':'MMR-comparison'})
        # One source-hash-selected directory control for each prepared source.
        # This is part of relevance error assessment, not extra Bayesian labels.
        if eligible:
            pid=sorted(settings['profile_claims'],key=lambda p:sha(sid+'|directory-control|'+p))[0]
            item(sid,'individual',[pid],{'scope_id':sid,'kind':'directory-control'})
    for control in inp['controls']:
        sid=control['origin_scope_id']
        item(sid,'source_control',[],{'scope_id':sid,'kind':'derived-control-context','case_id':control['case_id'],'control_kind':control['kind']})
    # Audit actual first-member explanations for 30 source-hash-selected prepared
    # scopes. Empty selections cannot create narration; retain their denominator.
    explanations=[]
    selected=sorted([s for s in scopes if results['bounded-middle'][s]['status']!='unprepared'],key=lambda s:sha('explanation|'+s))[:30]
    for sid in selected:
        r=results['bounded-middle'][sid]
        if not r['B']['defaultIds']:missing.append({'scope_id':sid,'kind':'explanation','reason':'no generated group explanation'});continue
        for pid in r['B']['defaultIds']:
            row=next(x for x in r['rows'] if x['id']==pid);edge=max(row['edges'],key=lambda e:e['score']);claim=next(c for c in people[pid]['claims'] if c['claim_id']==edge['claim_id']);scope=next(s for s in inp['scopes'] if s['id']==sid);a=next(a for a in scope['aspects'] if a['id']==edge['aspect_id'])
            text='The public passage “'+claim['evidence']+'” suggests a scientific conversation about “'+a['text']+'”. Exact contribution and application remain to be established.'
            explanations.append(item(sid,'explanation_audit',[pid],{'scope_id':sid,'kind':'explanation'},text))
    # Predeclared source/item hash order-swap sample, independent of responses.
    for key in sorted(set(comparisons),key=lambda k:sha('swap|'+k))[:10]:
        u=unique[key];c=u['value']['candidates'];swapped=item(u['scope_id'],'comparison',{'A':c['B'],'B':c['A']},{'scope_id':u['scope_id'],'kind':'order-swap','original_key':key})
        unique[swapped]['purpose_override']='order-swap'
    # Freeze a real compact packet selection now, before any model responses.
    individual_keys=sorted([k for k,v in unique.items() if v['value']['task_type']=='individual'],key=lambda k:sha('human-dev-C2|'+k))
    human=[];used=set()
    categories=[('apparently-strong','359696',0),('apparently-strong','357002',0),('apparently-strong','344592:ab-0009',0),('method-transfer','345241:tdac-baa-004',0),('method-transfer','363489',0),('borderline','45810',0)]
    for category,sid,pos in categories:
        rr=results['bounded-middle'][sid];ids=rr.get('B5') or rr.get('A5') or []
        if ids:
            k=next(k for k,v in unique.items() if v['scope_id']==sid and v['value']['task_type']=='individual' and v['value']['candidates']==[ids[pos]])
            if k not in used:human.append({'key':k,'selection_category':category});used.add(k)
    for k in individual_keys:
        if len(human)>=12:break
        if k not in used:human.append({'key':k,'selection_category':'source-hash representative/control'});used.add(k)
    for k in sorted(set(comparisons),key=lambda k:sha('human-group|'+k)):
        if len(human)>=20:break
        if k not in used:human.append({'key':k,'selection_category':'complete-team or alternative comparison'});used.add(k)
    for k in sorted([k for k,v in unique.items() if v['value']['task_type']=='group'],key=lambda k:sha('human-group|'+k)):
        if len(human)>=20:break
        if k not in used:human.append({'key':k,'selection_category':'complete-team assessment'});used.add(k)
    write(DOC/'manifests/human-development-c2-selection.json',{'model_verdicts_exist':False,'original_human_manifest_preserved':True,'reason':'C2 explicitly asks for a real mixed compact packet. Original stage-1 positions had no produced recommendations and consumed no requested judgments. Final-audit 20 remain unchanged.','items':human,'requested_at_delivery':len(human),'returned':0,'reserved_final':20,'limits':'Group comparisons concentrate in one source because only one prepared source returned groups. Do not present this as broad multi-field group validation.'})
    requests=[];request_maps=[];by= {}
    for key,u in unique.items():
        kind=u['value']['task_type'];purpose=u.get('purpose_override') or ('source' if kind=='source_control' else 'individual' if kind=='individual' else 'explanation' if kind=='explanation_audit' else 'group')
        by.setdefault((u['scope_id'],purpose),[]).append(key)
    for (sid,purpose),keys in by.items():
        s=sources[sid]
        if not s['excerpts']:
            missing.extend({'key':k,'scope_id':sid,'reason':'complete original retained text exceeds source-span bound'} for k in keys);continue
        if sid.startswith('nasa-roses:') or sid=='363747':
            missing.extend({'key':k,'scope_id':sid,'reason':'catalog synopsis is not specific original source evidence; new PDF file retrieval unresolved'} for k in keys);continue
        se={'scope_id':sid,'limitations':'Original bounded source fields or named native section. Full notice/annex restrictions and researcher facilities, willingness, qualifications are not established. Existing retrieval/export dates are retained separately. Public profile passages are brief and their scope may be uncertain.','passages':[{'id':e['id'],'text':e['text'],'url':s['source_url'],'locator':e['locator'],'sha256':e['sha256']} for e in s['excerpts']]}
        batch=[];mapping=[]
        def request(items):return {'scope_id':sid,'purpose':purpose,'source_evidence':se,'items':items}
        def emit():
            if batch:
                r=request(batch.copy());judge_contract(r,settings);requests.append(r);request_maps.append({'request_index':len(requests)-1,'items':mapping.copy()})
        for key in sorted(keys):
            trial={**unique[key]['value'],'item_id':'i'+str(len(batch)+1).zfill(2)}
            try:judge_contract(request(batch+[trial]),settings)
            except (Deferred,ValueError) as exc:
                if batch:
                    emit();batch=[];mapping=[];trial['item_id']='i01'
                try:judge_contract(request([trial]),settings)
                except (Deferred,ValueError) as inner:missing.append({'key':key,'scope_id':sid,'reason':str(inner)});continue
            batch.append(trial);mapping.append({'alias':trial['item_id'],'key':key})
        emit()
    counts=Counter(r['purpose'] for r in requests);bounds=[judge_contract(r,settings)[1] for r in requests]
    if sum(bounds)>1433600 or any(counts[k]>v for k,v in {'source':90,'individual':90,'group':90,'explanation':30,'order-swap':10,'control':30}.items()):raise ValueError('finite_evaluation_envelope')
    result=packet(requests,'development-judge');result.update({'unique_items':len(unique),'occurrences':len(occurrences),'submitted_items':sum(len(r['items']) for r in requests),'requests_by_purpose':dict(counts),'input_token_bound':sum(bounds),'output_token_bound':len(requests)*512,'conservative_reservation_usd':sum(bounds)*2.5e-6+len(requests)*512*1e-5,'missing':missing,'source_recipe_sha256':sha((OUT/'real-inputs-v2.json').read_bytes()),'development_outputs_sha256':sha((OUT/'development-corrected-v2.json').read_bytes()),'human_items_selected_before_judge':len(human)})
    write(DOC/'receipts/c2-development-judge-plan.json',result)
    write(OUT/'judge-item-map-v1.json',{'unique':unique,'occurrences':occurrences,'request_maps':request_maps,'ordering':ordering,'missing':missing,'human_selection':human,'packet_sha256':result['sha256']})
    print(json.dumps({k:v for k,v in result.items() if k!='missing'}))
if __name__=='__main__':prepare()
