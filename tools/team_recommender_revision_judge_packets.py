"""Finite D1 packets from real outputs; no new human packet or provider dispatch."""
import copy
import json
import array
from collections import Counter
from tools.team_recommender_real_prep import ROOT,DOC,sha,canonical,write,packet
from tools.team_recommender_executor import policy,judge_contract
from tools.team_recommender_evaluation_d1 import item_identity
from tools.offline_spend import Deferred

OUT=ROOT/'outputs/team-recommender-d1'


def read(p):return json.loads(p.read_bytes())


def prepare():
    inp=read(OUT/'real-inputs-d1.json');out=read(OUT/'controlled-v1.json');settings=policy()
    result=next(r for r in out['results'] if r['id']=='combined');results={s['id']:s for s in result['scopes']}
    sources={s['id']:s for s in inp['sources']};scopes={s['id']:s for s in inp['scopes']};people={p['id']:p for p in inp['directory']['researchers']}
    diagnostic={r['scope_id'] for r in read(DOC/'manifests/diagnostic-cases-d1.json')['cases']}
    bundle=read(OUT/'assembled-d1/bundle.json');raw=(OUT/'assembled-d1/vectors.f32').read_bytes()
    vectors=[]
    for i in range(len(bundle['vector_rows'])):
        a=array.array('f');a.frombytes(raw[i*4096:(i+1)*4096]);vectors.append(a)
    bundle_scopes={s['id']:s for s in bundle['scopes']};bundle_people={p['id']:p for p in bundle['people']}
    selected_claims={}
    for sid,r in results.items():
        if r['status']=='unprepared':continue
        q=vectors[bundle_scopes[sid]['whole_call']['vector']]
        for person in r['rows']:
            passages=bundle_people[person['id']]['passages']
            whole=max(passages,key=lambda p:sum(a*b for a,b in zip(q,vectors[p['vector']])))
            selected_claims[sid,person['id']]={whole['id']}|{e['claim_id'] for e in person['edges'] if e['admitted']}
    unique={};occurrences=[];missing=[];ordering=[];comparisons=[]
    def source_context(sid):
        source=sources[sid];entries=copy.deepcopy(source['excerpts'])
        if sid.startswith('nasa-roses:'):
            by={e['id']:e for e in entries};p1=by['page1']['text'];p6=by['page6']['text']
            overview=p1[p1.index('NASA’s Habitable Worlds'):p1.index('HWO-ICA supports two categories')]
            eligibility=p1[p1.index('Only U.S. organizations'):p1.index('A Proposer’s Information Package')]
            category2=p6[p6.index('[Amended September 3, 2026]'):p6.index('d) Statements of Commitment')]
            entries=[{'id':'science','text':by['page4']['text'],'locator':'Complete scientific scope and exclusions, amended PDF page 4'},
                     {'id':'overview','text':overview,'locator':'Program overview, page 1'},
                     {'id':'eligibility','text':eligibility,'locator':'Eligibility notice, page 1'},
                     {'id':'category2','text':category2,'locator':'Amended category 2 funded/unfunded personnel, page 6'}]
        if sid=='362868':
            by={e['id']:e['text'] for e in entries};p6=by['page6'];p7=by['page7'];p8=by['page8']
            focus=p6[p6.index('3.1. PRP Focus Areas'):]+ '\n'+p7[:p7.index('3.2. Intent')]
            context=by['page4'][by['page4'].index('Summary:'):by['page4'].index('Funding Details:')]
            restrictions=p8[p8.index('3.2.2. Other Important Considerations'):p8.index('3.3. Funding Instrument')]
            entries=[{'id':'focus','text':focus,'locator':'Complete focus-area alternatives, PDF pages 6-7'},
                     {'id':'summary','text':context,'locator':'Summary and preliminary-data conditions, PDF page 4'},
                     {'id':'conditions','text':restrictions,'locator':'Scientific restrictions and access conditions, PDF page 8'}]
        passages=[{'id':'s'+str(i+1),'text':e['text'],'url':source['source_url'],'locator':e['locator'],'sha256':sha(e['text'])} for i,e in enumerate(entries)]
        se={'scope_id':sid,'passages':passages,'limitations':'Retained official text; unread restrictions unknown. Frozen registry descriptions are not capability certificates.'}
        aspects=[]
        for a in scopes[sid]['aspects']:
            ref=next((p['id'] for p in passages if a['text'] in p['text']),None)
            if ref is None:raise ValueError('target_aspect_lost_original_context')
            aspects.append({'id':a['id'],'text':a['text'],'source_ref':ref})
        return se,aspects
    contexts={sid:source_context(sid) for sid in scopes}
    def evidence(sid,ids):
        rows=[]
        for pid in sorted(set(ids)):
            p=people[pid]
            for c in sorted(p['claims'],key=lambda c:c['claim_id']):
                if c['status']!='active':continue
                if c['claim_id'] not in selected_claims.get((sid,pid),{c['claim_id']}):continue
                rows.append({'id':'p'+str(len(rows)+1),'person_id':pid,'claim_id':c['claim_id'],'revision':c['revision'],
                    'text':c['evidence'],'source_url':c['source_urls'][0],'label':c['label'],'claim_type':c['type'],'research_summary':p['research_summary']})
        return rows
    def item(sid,kind,candidates,occ,purpose,target=None,explanation=None):
        groups=list(candidates.values()) if isinstance(candidates,dict) else [candidates]
        ids=[p for g in groups for p in g]
        value={'task_type':kind,'profile_evidence':evidence(sid,ids),'candidates':candidates}
        if target is not None:value['target_aspect']=target
        if explanation is not None:value['explanation']=explanation
        se,aspects=contexts[sid];key=item_identity(sid,se,aspects,value)
        unique.setdefault(key,{'scope_id':sid,'value':value,'purpose':purpose})
        occurrences.append({'key':key,'scope_id':sid,**occ});return key
    for sid,r in results.items():
        if sid in diagnostic:item(sid,'source_suitability',[],{'kind':'source-suitability'},'d1-source')
        if r['status']=='unprepared':continue
        for arm,ids in [('A',r['A5']),('B',r['B5'])]:
            for rank,pid in enumerate(ids):item(sid,'call_person',[pid],{'kind':'top5','arm':arm,'rank':rank+1},'d1-call')
        if sid in diagnostic:
            ids=r['B']['defaultIds'] or r['B5'][:1]
            for pid in ids:
                row=next(p for p in r['rows'] if p['id']==pid);edge=max(row['edges'],key=lambda e:e['score'])
                item(sid,'aspect_person',[pid],{'kind':'diagnostic-aspect','person':pid,'aspect':edge['aspect_id']},'d1-aspect',target=edge['aspect_id'])
        if not r['B']['defaultIds']:continue
        for arm,ids in [('A',r['A']),('B',r['B']['defaultIds'])]:
            if len(ids)>=2:item(sid,'group_usefulness',sorted(ids),{'kind':'primary-group','arm':arm},'d1-group')
        for position,option in enumerate(r['B']['options']):
            ids=sorted(option['ids']);item(sid,'group_usefulness',ids,{'kind':'alternative','arm':'B','position':position+1},'d1-group')
            a=r['alternatives_baseline'][position]['ids']
            if len(a)==len(ids):item(sid,'group_usefulness',sorted(a),{'kind':'alternative','arm':'A','position':position+1},'d1-group')
            for pid in ids:item(sid,'call_person',[pid],{'kind':'automatic-member','position':position+1,'arm':'B'},'d1-call')
        left,right=sorted(r['A']),sorted(r['B']['defaultIds'])
        if len(left)==len(right) and left!=right:comparisons.append((sid,left,right))
        elif left==right:occurrences.append({'scope_id':sid,'kind':'matched-AB-identical'})
    for control in inp['controls']:
        item(control['origin_scope_id'],'source_suitability',[],{'kind':'derived-control-context','control':control['case_id'],'control_kind':control['kind']},'d1-control')
    for index,(sid,left,right) in enumerate(sorted(comparisons,key=lambda p:sha(canonical(p)))):
        groups={'A':right if index%2 else left,'B':left if index%2 else right}
        key=item(sid,'comparison',groups,{'kind':'matched-AB','left_arm':'A','right_arm':'B'},'d1-comparison')
        ordering.append({'key':key,'left':left,'right':right,'candidates':groups,'scope_id':sid})
    for pair in sorted(ordering,key=lambda p:sha(p['key']))[:4]:
        c=pair['candidates'];key=item(pair['scope_id'],'comparison',{'A':c['B'],'B':c['A']},
            {'kind':'order-swap','original_key':pair['key']},'d1-swap')
    for sid in [s['id'] for s in inp['scopes'] if results[s['id']]['status']=='group'][:12]:
        r=results[sid];sentences=[]
        for pid in r['B']['defaultIds']:
            row=next(x for x in r['rows'] if x['id']==pid);edge=max(row['edges'],key=lambda e:e['score']);c=next(c for c in people[pid]['claims'] if c['claim_id']==edge['claim_id']);a=next(a for a in scopes[sid]['aspects'] if a['id']==edge['aspect_id'])
            sentences.append('The public passage “'+c['evidence']+'” suggests a scientific conversation about “'+a['text']+'”. Exact contribution and application remain to be established.')
        item(sid,'explanation_audit',sorted(r['B']['defaultIds']),{'kind':'explanation'},'d1-explanation',explanation=' '.join(sentences))
    requests=[];request_maps=[];by={}
    for key,u in unique.items():by.setdefault((u['scope_id'],u['purpose']),[]).append(key)
    for (sid,purpose),keys in by.items():
        se,aspects=contexts[sid];batch=[];maps=[]
        def req(items):return {'protocol':'D1','scope_id':sid,'purpose':purpose,'source_evidence':se,'aspects':aspects,'items':items}
        def emit():
            if batch:
                r=req(copy.deepcopy(batch));judge_contract(r,settings);requests.append(r);request_maps.append({'items':copy.deepcopy(maps)})
        for key in sorted(keys):
            trial={**unique[key]['value'],'item_id':'i'+str(len(batch)+1).zfill(2)}
            try:judge_contract(req(batch+[trial]),settings)
            except (Deferred,ValueError) as error:
                if batch:emit();batch=[];maps=[];trial['item_id']='i01'
                try:judge_contract(req([trial]),settings)
                except (Deferred,ValueError) as failure:missing.append({'key':key,'scope_id':sid,'reason':str(failure)});continue
            batch.append(trial);maps.append({'alias':trial['item_id'],'key':key})
        emit()
    bounds=[judge_contract(r,settings)[1] for r in requests]
    counts=Counter(r['purpose'] for r in requests)
    if len(requests)>200 or sum(bounds)>1360000:
        write(OUT/('over-bound-judge-plan-'+str(len(requests))+'-'+str(sum(bounds))+'.json'),
            {'requests':len(requests),'input_bound':sum(bounds),'purposes':dict(counts),'unique_items':len(unique),
             'submitted_items':sum(len(r['items']) for r in requests),'missing':missing,'provider_calls':0})
        raise ValueError('finite_D1_envelope_exceeded:'+str((len(requests),sum(bounds))))
    result=packet(requests,'development-judge')
    sanity=[]
    for sid,purpose in [('nasa-roses:25-D.9-d22059cf9f','d1-source'),('357002','d1-call'),('361208','d1-group')]:
        sanity.append(next(i for i,r in enumerate(requests) if r['scope_id']==sid and r['purpose']==purpose))
    canary=packet([requests[i] for i in sanity],'development-judge')
    result.update(unique_items=len(unique),occurrences=len(occurrences),submitted_items=sum(len(r['items']) for r in requests),
        requests_by_purpose=dict(counts),input_token_bound=sum(bounds),output_token_bound=len(requests)*512,
        conservative_reservation_usd=sum((b*5+1)//2+5120 for b in bounds)/1e6,missing=missing,
        source_recipe_sha256=sha((OUT/'real-inputs-d1.json').read_bytes()),outputs_sha256=sha((OUT/'controlled-v1.json').read_bytes()),
        sanity_packet=canary,sanity_request_indices=sanity,human_packet_created=False,profile_enrichment=False,
        controls='All 30 retain objective perturbation dispositions. These source-context judgments do not claim semantic validation of tampered-profile controls.',
        historical_relation='D1 materially replaces the question and includes frozen registry labels/types/summaries. Old C2 verdicts and failed requests are preserved, never replayed as equivalent tasks.')
    write(DOC/'receipts/d1-judge-plan.json',result)
    write(OUT/'judge-item-map-d1.json',{'unique':unique,'occurrences':occurrences,'ordering':ordering,'request_maps':request_maps,
        'missing':missing,'packet_sha256':result['sha256'],'sanity_indices':sanity})
    print(json.dumps({k:v for k,v in result.items() if k not in {'missing'}}));print('missing items',len(missing))


if __name__=='__main__':prepare()
