"""Deterministic public input preparation; never loads credentials or calls providers."""
import hashlib
import json
import re
import html
from datetime import datetime, timezone
from tools.team_recommender_source import translate_official_export, translate_nsf_page, validate_source
from pathlib import Path
from tools.team_recommender_executor import policy, validate_packet, embedding_contract
from tools.team_recommender_group_audit import catalog

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/team-recommender'
OUT=ROOT/'outputs/team-recommender-c2'
def sha(b):return hashlib.sha256(b if isinstance(b,bytes) else b.encode()).hexdigest()
def jsdata(path):
    s=path.read_text(encoding='utf8');return json.loads(s[s.index('{'):s.rfind('}')+1])
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    if path.exists() and path.read_bytes()!=raw:raise ValueError('immutable_file_exists:'+str(path))
    path.write_bytes(raw);return sha(raw)
def packet(requests,operation='embeddings'):
    p=policy();value={'schema_version':1,'authorization_id':p['authorization_id'],'registry_generation':p['registry_generation'],'operation':operation,'requests':requests}
    validate_packet(value,p)
    raw=(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    target=DOC/'packets'/(sha(raw)+'.json');target.parent.mkdir(exist_ok=True)
    if target.exists() and target.read_bytes()!=raw:raise ValueError('packet_conflict')
    target.write_bytes(raw)
    return {'sha256':sha(raw),'path':target.relative_to(ROOT).as_posix(),'bytes':len(raw),'requests':len(requests),'rows':sum(len(r.get('rows',[])) for r in requests),'conservative_input_bound':sum(embedding_contract(r,p)[1] for r in requests) if operation=='embeddings' else None}
def canary():
    p=policy();parents={r['opportunity_id']:r for r in catalog()}
    ids=['359696','363489','357002']
    rows=[{'owner':i,'text':parents[i]['description'].split('. ')[0]+'.'} for i in ids]
    for row in rows:row['id']=sha(row['text'])
    claims=[(person,c[0]) for person,c in sorted(p['profile_claims'].items())][:3]
    docs=[{'owner':person,'text':c['text'],'id':sha(c['text'])} for person,c in claims]
    result=packet([{'input_role':'query','rows':rows},{'input_role':'document','rows':docs}])
    result.update({'phase':'wiring-canary','source_selection':'Three preselected coherent development sources: human olfactory imaging, inertial sensor/control co-design, molecular cancer imaging. Selected before numerical outputs. Exact first source sentences; reused later as core rows.','source_ids':ids,'profile_rows':len(docs),'new_authorization':False,'ledger_owner':'GitHub main-only executor; local ledger is a read-only mirror after dispatch','prior_experiment_spend_usd':0,'prior_reservations_usd':0,'maximum_canary_usd':result['conservative_input_bound']*.02/1_000_000,'no_recommendations_generated':True})
    write(DOC/'receipts/c2-canary-input-plan.json',result)
    print(json.dumps(result))

MATERIAL=['opportunity_id','subtopic_id','parent_id','title','description','summary','source','source_url','documents','publication_state','child_type','scope','source_hash','content_hash','source_updated_date','source_document_hash','source_document_url','source_version','parent_subtopic_id','source_role']
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def record_key(record):return canonical({k:record.get(k) for k in MATERIAL})
def span(excerpt,text,id):
    pos=excerpt['text'].index(text)
    # JavaScript source offsets are UTF-16 code units, not Python code points.
    start=len(excerpt['text'][:pos].encode('utf-16le'))//2
    return {'id':id,'text':text,'span':{'excerpt_id':excerpt['id'],'start':start,'end':start+len(text.encode('utf-16le'))//2},'input_hash':sha(text)}
def excerpt(text,id,locator):return {'id':id,'text':text,'offset':0,'locator':locator,'sha256':sha(text)}
def prepare():
    raw=(ROOT/'data/opportunities.js').read_bytes();cat=jsdata(ROOT/'data/opportunities.js');parents={r['opportunity_id']:r for r in cat['opportunities']}
    subraw=(ROOT/'data/subtopics.js').read_bytes();subs=jsdata(ROOT/'data/subtopics.js');children={s['subtopic_id']:s for r in subs['records'].values() for s in r['subtopics']}
    decisions=json.loads((DOC/'manifests/development-source-decisions-c2.json').read_bytes());dev=json.loads((DOC/'manifests/development.json').read_bytes())
    scopes=[];sources=[];validations=[];dispositions=[];queries={};records={}
    for reservation in dev['scopes']:
        sid,pid=reservation['id'],reservation['parent_id'];record=children.get(sid,parents[pid]);records[sid]=record
        source_record=parents.get('340828') if sid.startswith('nsf-funding:') else record
        url=reservation['source_url'];observed=cat['generated_at'];docsha=sha(raw)
        texts=[];quotes=[];validation=None;kind='B';reason='';scope={'id':sid,'parent_id':pid,'record_type':reservation['record_type'],'scope_label':reservation['title'],'approach_id':'source-approach-v1','prepared':False,'readiness':'unsupported','aspects':[],'evidence_links':[]}
        if sid in decisions['aspect_quotes'] or sid.startswith('nsf-funding:'):
            url='https://www.grants.gov/search-results-detail/'+source_record['opportunity_id']
            texts=[excerpt(source_record[f],f,f) for f in ['title','description','eligibility_text'] if source_record.get(f)]
            validation=translate_official_export(artifact_bytes=raw,record=source_record,scope_id=sid,parent_id=pid,excerpts=texts,snapshot_at=observed,source_url=url,export_identity=cat['source']['extract_file'])
            quotes=decisions['aspect_quotes'].get(sid, ['fundamental research in mathematics and statistics necessary to answer questions in the biological and biomedical sciences','research at the interface between mathematical and life sciences'])
            if not quotes:
                sentences=re.split(r'(?<=[.!?])\s+',source_record['description'])
                quotes=[sentences[i] for i in decisions['sentence_selection'][sid]]
            kind='A';reason=decisions['coherence_limits'].get(sid,'Bounded coherent scientific contribution in original synopsis. Planning aspects do not certify all notice requirements or researcher expertise.')
        elif sid=='45810':
            texts=[excerpt(record['description'],'description','official NSF page text')]
            validation=translate_nsf_page(artifact_bytes=(ROOT/'data/opportunity_enrichment.json').read_bytes(),record=record,excerpts=texts)
            url=record['description_source_url'];docsha=validation['document_sha256'];observed=validation['retrieved_at']
            quotes=['theoretically focused empirical investigations aimed at improving the explanation of fundamental social processes','original data collection and secondary data analysis that use the full range of quantitative and qualitative methodological tools']
            kind='A';reason=validation['limitations']
        elif sid in ('344592:ab-0009','361526:f-18'):
            if record.get('subtopic_source')!='native' or record.get('parent_id')!=pid:raise ValueError('native_child_ownership')
            text=record['summary'] if sid.startswith('344592') else record['title']
            url=record['source_document_url'];docsha=record['source_document_hash'];observed=record['last_verified']+'T00:00:00Z'
            texts=[excerpt(record['title'],'title','native title'),excerpt(text,'description',record['evidence_anchor'])]
            quotes=['properties of light and the discovery of new optical effects','dynamic control of light for remote sensing, information routing, and energy transmission'] if sid.startswith('344592') else [text]
            validation={'validation':'retained-native-spans-verified','scope_id':sid,'parent_id':pid,'document_sha256':docsha,'text_sha256':sha(text),'retrieved_at':None,'observed_at':observed,'new_retrieval':False,'excerpt_count':len(texts),'excerpt_hashes':[e['sha256'] for e in texts],'semantic_judgment':False,'provenance':{'kind':'native-catalog-scope-v1','artifact_sha256':sha(subraw),'source_url':url,'parent_id':pid,'scope_id':sid,'document_sha256':docsha,'locator':record['evidence_anchor']},'limitations':'Retained deterministic native source segment/cell and original document hash. Raw historic document is not retained; last_verified is an existing catalog observation, not a new retrieval. No sibling scope or complete-notice certification.'}
            kind='A';reason=validation['limitations']
        elif sid=='345241:tdac-baa-004':
            fetch=json.loads((OUT/'source-retrieval/quantum.json').read_bytes())
            if fetch['status']=='retrieved':
                raw_html=(OUT/'source-retrieval'/(fetch['document_sha256']+'.html')).read_bytes()
                paragraphs=[html.unescape(re.sub('<[^>]+>','',s)) for s in re.findall(r'<p[^>]*>(.*?)</p>',raw_html.decode('utf8'),re.S)]
                begin=next(i for i,s in enumerate(paragraphs) if s.startswith('Quantum technology has progressed'))
                end=next(i for i in range(begin,len(paragraphs)) if paragraphs[i].startswith('Title: Artillery'))
                text='\n'.join(paragraphs[begin:end]);url=fetch['source_url'];docsha=fetch['document_sha256'];observed=fetch['retrieved_at']
                texts=[excerpt(record['title'],'title','TDAC BAA-004 title'),excerpt(text,'description','TDAC BAA-004 Description (ends before BAA-005)')]
                # The source offers multiple future technology investigations. Keep
                # only its common analytical purpose; never combine all alternatives.
                quotes=['tools for evaluating the leap-ahead gains that may be available with quantum technologies','tools for analyzing quantum systems that enable entirely new Army capabilities']
                kind='B-retrieved';reason='New bounded official page retrieval; exact BAA-004 section. Four future technology areas remain alternatives, not simultaneous sponsor requirements.'
                validation={'new_raw':raw_html,'text':record['title']+'\n'+text}
                texts[1]['offset']=len(record['title'])+1
            else:reason='Official page unavailable; retained introductory excerpt lacks the actual analytical purpose.'
        elif sid in decisions['nonresearch_or_mechanism']:reason='Source describes a general career/funding/equipment/service mechanism without a selected coherent scientific research contribution for this interface.'
        elif sid in decisions['unselected_umbrella']:reason='Multiple unselected scientific/project/program branches; no source-backed single approach selected. No automatic broad-parent group.'
        else:reason=decisions['specific_context_gaps'].get(sid,'New NASA program text readable via web, but bounded file retrieval failed; cached catalog synopsis is generic. Full current source/ownership exclusions not yet in a reproducible ingredient receipt.')
        if not texts:
            text=record.get('summary') or record.get('description') or record['title'];texts=[excerpt(text,'description','retained unprepared source field')]
            if len(text.encode())>8000:texts=[]
        source={'id':sid,'parent_id':pid,'record_key':record_key(record),'source_url':url,'document_sha256':docsha,'receipt':None,'excerpts':texts}
        if validation:
            desc=next(e for e in texts if e['id']=='description');title=next((e for e in texts if e['id']=='title'),desc)
            if len(desc['text'].encode())>4000:raise ValueError('whole_call_requires_bounded_lossless_representation:'+sid)
            scope.update({'prepared':True,'core':span(title,title['text'] if title['id']=='title' else quotes[0],'core'),'whole_call':span(desc,desc['text'],'whole'),'aspects':[],'group_budgets':[]})
            # Preserve the exact successful three core canaries as full-sentence aspects.
            if sid in ('359696','363489','357002'):
                first=desc['text'].split('. ')[0]+'.';scope['core']=span(desc,first,'core')
            for i,q in enumerate(quotes):
                a=span(desc,q,'a'+str(i));a.update({'kind':'central' if i==0 else 'supporting','group_id':'a'+str(i),'weight':1 if len(quotes)==1 else .7 if i==0 else .3/(len(quotes)-1),'requirement_kind':'planning_contribution'})
                scope['aspects'].append(a);scope['group_budgets'].append({'id':a['group_id'],'weight':a['weight']})
            source['receipt']={'id':'r'+sha(sid)[:24],'kind':'source-span-validation-v1','validation_state':'source-backed','scope_id':sid,'parent_id':pid,'approach_id':scope['approach_id'],'document_sha256':docsha,'source_record_key':source['record_key'],'checked_at':observed,'valid_until':'2026-09-17T00:00:00Z','span_hashes':[e['sha256'] for e in texts]}
            if 'new_raw' in validation:
                validation=validate_source(source,scope,original_bytes=validation['new_raw'],extracted_text=validation['text'],extraction_receipt={'scope_id':sid,'parent_id':pid,'document_sha256':docsha,'text_sha256':sha(validation['text']),'method':'native-source-structure','source_url':url,'extraction_code_sha256':sha(Path(__file__).read_bytes()),'retrieved_at':observed,'coherent_scope':True,'conditions_preserved':True})
            for item in [scope['core'],scope['whole_call'],*scope['aspects']]:queries.setdefault(item['input_hash'],{'id':item['input_hash'],'owner':sid,'text':item['text']})
            validations.append(validation)
        dispositions.append({'scope_id':sid,'parent_id':pid,'category':kind,'numerically_preparable':scope['prepared'],'reason':reason,'source_snapshot_observed_at':observed,'source_url':url,'source_record_sha256':sha(canonical(record)),'feasibility':'unknown-independent-directory-assessment','submission_access_at_catalog_snapshot':parents[pid].get('next_submission',{}).get('access'),'new_vectors_missing':scope['prepared']})
        scopes.append(scope);sources.append(source)
    assert len(scopes)==90 and len(dev['controls'])==30
    directory=jsdata(ROOT/'data/researcher_directory.js');people=[];docs={}
    for p in directory['researchers']:
        if not p.get('auto_proposable') or p['status']!='active' or p['pool_state'] not in ('main','standby'):continue
        grouped={}
        for c in p['claims']:
            if c['status']=='active':grouped.setdefault(c['evidence'],[]).append(c)
        passages=[]
        for text,claims in grouped.items():
            h=sha(text);urls=set.intersection(*(set(c['source_urls']) for c in claims))
            if not urls:raise ValueError('shared_passage_has_no_common_provenance')
            passages.append({'id':claims[0]['claim_id'],'text':text,'claim_refs':[{'claim_id':c['claim_id'],'revision':c['revision']} for c in claims],'source_urls':sorted(urls),'input_hash':h})
            docs.setdefault(h,{'id':h,'owner':p['id'],'text':text})
        people.append({'id':p['id'],'passages':passages})
    value={'sources':sources,'scopes':scopes,'people':people,'directory':directory,'validations':validations,'records':records,'controls':dev['controls'],'dispositions':dispositions,'query_rows':list(queries.values()),'document_rows':list(docs.values())}
    h=write(OUT/'real-inputs-v2.json',value)
    write(DOC/'receipts/c2-source-input-inventory-v2.json',{'input_sha256':h,'attempted':90,'prepared':len(validations),'unprepared':90-len(validations),'controls':30,'people':len(people),'active_claims':sum(sum(c['status']=='active' for c in p['claims']) for p in directory['researchers'] if p['auto_proposable']),'distinct_person_passages':sum(len(p['passages']) for p in people),'unique_document_rows':len(docs),'unique_query_rows':len(queries),'dispositions':dispositions,'whole_call_lossless':True,'profile_evidence':'Retained public claim passages; registry evidence level does not certify the new aspect relationship.','new_raw_source_count':sum(d['category']=='B-retrieved' for d in dispositions),'supersedes':'c2-source-input-inventory.json; active count corrected to exclude six retired claims; translated separate NSF page cache without refetching.'})
    can=json.loads((DOC/'packets/41b27912edd06b626ac248ee77898ecc378ad174acddf6df59b8f914a5e6a46c.json').read_bytes());known={r['input_role']+':'+row['id'] for r in can['requests'] for row in r['rows']}
    requests=[]
    for role,rows in [('query',queries.values()),('document',docs.values())]:
        rows=[r for r in rows if role+':'+r['id'] not in known]
        for i in range(0,len(rows),64):requests.append({'input_role':role,'rows':rows[i:i+64]})
    result=packet(requests);result.update({'source_inputs_sha256':h,'already_embedded_rows_reused':len(known),'prior_spend_microusd':4,'remaining_stage2_ceiling_microusd':5999996})
    write(DOC/'receipts/c2-full-input-packet-v2.json',result);print(json.dumps(result))

if __name__=='__main__':
    import sys
    prepare() if '--prepare' in sys.argv else canary()
