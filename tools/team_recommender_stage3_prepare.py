"""Seal source recipes and missing E2 inputs before any held-out output."""
import json
from pathlib import Path
from tools.team_recommender_real_prep import ROOT, DOC, sha, write, canonical
from tools.team_recommender_evidence_projection import person_document

OUT = ROOT/'outputs/team-recommender-stage3'
OLD = ROOT/'outputs/team-recommender-d3/assembled-E2'

def read(path): return json.loads(path.read_bytes())

def prepare():
    inputs = read(OUT/'source-inputs-v1.json')
    old = read(OLD/'bundle.json')
    directory = read(OLD/'directory.json')['researchers']
    eligible = {p['id']:p for p in directory if p['status']=='active' and p['auto_proposable']}
    assert len(eligible)==155
    contexts = {}
    for source, scope in zip(inputs['sources'], inputs['scopes']):
        assert source['id']==scope['id']
        passages=[]
        for i,e in enumerate(source['excerpts']):
            passages.append({'id':'s'+str(i),'text':e['text'],'url':source['source_url'],
                             'locator':e.get('locator') or e['id'],'sha256':e['sha256']})
        parent=inputs['parents'][scope['parent_id']]
        # Preserve parent application conditions even for a selected native child.
        conditions=parent.get('eligibility_text')
        if conditions and not any(p['text']==conditions for p in passages):
            passages.append({'id':'s'+str(len(passages)), 'text':conditions,
                'url':parent.get('detail_page') or source['source_url'],
                'locator':'Original parent eligibility_text', 'sha256':sha(conditions)})
        disposition=next(d for d in inputs['dispositions'] if d['scope_id']==scope['id'])
        validation=next((v for v in inputs['validations'] if v['scope_id']==scope['id']),None)
        limitations='Original retained public source fields, with their original observation dates; a bounded excerpt is not complete-notice certification. Unknown requirements remain unknown. No independent directory-feasibility determination is supplied.'
        if validation:
            limitations+=' '+validation.get('limitations','')
        # Dispositions never replace the original evidence with our conclusions.
        extra=disposition.get('additional_context')
        if extra:
            receipt=read(ROOT/extra['receipt_path'])
            pages=receipt.get('pages')
            if pages and scope['id']!='362607':
                for page in ([3,5,6] if 'rtrp' in extra['receipt_path'] else [3,5]):
                    t=pages[page]
                    passages.append({'id':'s'+str(len(passages)),'text':t,'url':extra['source_url'],
                                     'locator':'Official notice page '+str(page+1),'sha256':sha(t)})
            elif scope['id']=='363240':
                import re, html
                raw=(ROOT/extra['receipt_path']).parent/(receipt['document_sha256']+'.html')
                page=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]*>',' ',raw.read_text(encoding='utf-8'))))
                start=page.index('NASA’s Earth Science Division');end=page.index('Questions concerning A.14',start)
                t=page[start:end].strip()
                passages.append({'id':'s'+str(len(passages)),'text':t,'url':extra['source_url'],
                    'locator':'Official Amendment 63 scientific scope and submission paragraphs','sha256':sha(t)})
            limitations+=' Supplemental original context was retrieved at '+extra['retrieved_at']+'. This does not establish a selected project or researcher qualifications.'
        aspects=[]
        for a in scope['aspects']:
            idx=next(i for i,e in enumerate(source['excerpts']) if e['id']==a['span']['excerpt_id'])
            aspects.append({'id':a['id'],'text':a['text'],'source_ref':'s'+str(idx)})
        contexts[scope['id']]={'source_evidence':{'scope_id':scope['id'],'passages':passages,
            'limitations':limitations},'aspects':aspects,'parent_id':scope['parent_id'],
            'source_record_sha256':disposition['source_record_sha256']}
    old_queries={r['text_sha256'] for r in old['vector_rows'] if r['input_role']=='query'}
    # Purchased D3 large/query rows outside this candidate can also be reused,
    # but only when the exact endpoint/model/role/text contract matches.
    adopted=read(ROOT/'outputs/team-recommender-d3/adopted-vector-keys.json')
    compatible={key[2] for key in adopted if key[:2]==['voyage-4-large','query']}
    missing=[r for r in inputs['query_rows'] if r['id'] not in compatible]
    requests=[]; batch=[]
    def body(rows):
        return {'model':'voyage-4-large','input_type':'query','output_dimension':1024,
                'output_dtype':'float','input':[r['text'] for r in rows],'truncation':False}
    def bound(rows): return len(canonical(body(rows)).encode())+1024
    def flush():
        if batch:
            requests.append({'representation':'S3-E2-query-v1','model':'voyage-4-large',
                             'input_role':'query','rows':list(batch)})
            batch.clear()
    for row in sorted(missing,key=lambda r:r['id']):
        if bound([row])>20000:raise ValueError('indivisible_query_over_bound')
        if len(batch)>=64 or bound(batch+[row])>20000:flush()
        batch.append(row)
    flush()
    assert len(requests)<=20
    config={'version':'S3-E2-frozen-inputs-v1','registry_generation':old['registry_generation'],
        'candidate_manifest_sha256':sha((DOC/'stage2-validation-candidate.json').read_bytes()),
        'source_recipe_sha256':sha((OUT/'source-inputs-v1.json').read_bytes()),
        'profile_documents':{pid:person_document(p) for pid,p in eligible.items()},
        'contexts':contexts,'query_rows':{r['id']:r for r in inputs['query_rows']},
        'heldout_ids':inputs['cohorts']['holdout_effective'],'controls':inputs['controls']}
    config_hash=write(OUT/'trusted-inputs-stage3-v2.json',config)
    packet={'schema_version':1,'authorization_id':'on-demand-team-offline-v2-20260909',
            'registry_generation':old['registry_generation'],'operation':'embeddings','requests':requests}
    ph=write(OUT/'embedding-packet.json',packet)
    receipt={'candidate':'E2-D3-combined-v1-frozen','source_recipe_sha256':config['source_recipe_sha256'],
        'trusted_inputs_sha256':config_hash,'embedding_packet_sha256':ph,
        'all_scopes':len(inputs['scopes']),'source_prepared':sum(s['prepared'] for s in inputs['scopes']),
        'eligible_people':155,'reused_profile_vectors':155,'new_profile_vectors':0,
        'unique_query_texts':len(inputs['query_rows']),'reused_exact_query_rows':len(inputs['query_rows'])-len(missing),
        'new_query_rows':len(missing),'requests':len(requests),'input_bounds':[bound(r['rows']) for r in requests],
        'reserved_input_units':sum(bound(r['rows']) for r in requests),
        'reserved_microusd':sum((bound(r['rows'])*3+24)//25 for r in requests),
        'price_usd_per_million':.12,'price_verified_on':'2026-09-10','price_source':'https://docs.voyageai.com/docs/pricing',
        'metered_requests_dispatched':0,'heldout_recommendations_generated':False}
    receipt['supersedes_projection_only']='stage3-unique-input-plan-v1.json; removed ordinary in-task source dispositions from judge limitations before any held-out output or provider call; query packet unchanged.'
    write(DOC/'receipts/stage3-unique-input-plan-v2.json',receipt)
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':prepare()
