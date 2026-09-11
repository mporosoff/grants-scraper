"""Materialize complete, blinded proposed questions; no provider dispatch."""
import json
import hashlib
from pathlib import Path
from collections import Counter
from tools.team_recommender_evidence_projection import person_document, request_body, identity, encoded

ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/team-recommender/post-audit'
OUT=ROOT/'outputs/team-recommender-post-audit'
def read(p): return json.loads(p.read_bytes())
def write(p,v): p.write_bytes((json.dumps(v,indent=2,ensure_ascii=False)+'\n').encode())

def pack(source,aspects,keyed_items,prompt):
    """Proposed exact-input route only: complete <=24k-byte contexts, <=3 items."""
    packets=[];oversized=[];batch=[]
    def body(items):return request_body(source,aspects,[v for _,v in items],prompt)
    def flush():
        if batch:
            value=body(batch);packets.append({'keys':[k for k,_ in batch],'body':value,'input_bound':len(encoded(value))+1024});batch.clear()
    for key,item in keyed_items:
        bound=len(encoded(body([(key,item)])))+1024
        if bound>24000:flush();oversized.append({'key':key,'input_bound':bound});continue
        if batch and (len(batch)==3 or len(encoded(body(batch+[(key,item)])))+1024>24000):flush()
        batch.append((key,item))
    flush();return packets,oversized

def main():
    selection=read(DOC/'semantic-selection-v2.json');outputs=read(OUT/'semantic-outputs-v2.json')
    source_rows={r['scope']['id']:r for r in read(OUT/'semantic-canonical-sources.json')}
    registry={r['researcher_id']:{**r,'id':r['researcher_id']} for r in read(ROOT/'config/researcher_registry.json')['researchers']}
    rows={r['id']:r for r in outputs['rows']};all_items={};occurrences=[];requests=[];missing=[];contexts={}
    prompt=(ROOT/'config/team_recommender_executor/judge-d1.md').read_text(encoding='utf8')
    ordered=sorted(rows,key=lambda sid:identity('post-audit-optional-v1|'+sid))
    alternatives=[sid for sid in ordered if len(rows[sid].get('option_members',[]))>=2][:4]
    explanations=[sid for sid in ordered if rows[sid].get('primary')][:4]
    swaps=alternatives[:2]
    for reservation in selection['scopes']:
        sid=reservation['id'];row=rows[sid];original=source_rows[sid];record,parent=original['record'],original['parent'];passages=[]
        def passage(label,text,url):
            if not text:return
            passages.append({'id':'s'+str(len(passages)),'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest(),'source_url':url,'source_field':label})
        url=record.get('primary_document_url') or record.get('detail_page') or record.get('funding_opportunity_url') or parent.get('detail_page')
        for field in ['title','description','document_search_text']:passage(field,record.get(field),url)
        if reservation['id']!=reservation['parent_id']:passage('parent_description',parent.get('description'),parent.get('detail_page'))
        conditions={k:parent.get(k) for k in ['applicant_types','eligibility_text','cost_share_required','limited_submission','limited_submission_source','preliminary_required','deadlines','close_date','deadline_note','status'] if parent.get(k) is not None}
        passage('retained_structured_conditions',json.dumps(conditions,ensure_ascii=False,sort_keys=True),parent.get('detail_page') or url)
        source={'scope_id':sid,'parent_id':reservation['parent_id'],'provenance':'Complete stored canonical scientific fields and available conditions used by the shared workflow; source attribution is retained, not newly verified. A native child projection is not proof of complete notice verification. Missing restrictions remain unknown.','passages':passages}
        contexts[sid]={'source_evidence':source,'aspects':[],'original_source':parent.get('source'),'detail_enriched_at':parent.get('detail_enriched_at'),'document_evidence_checked_at':parent.get('document_evidence_checked_at')}
        queue=[]
        def add(kind,people,role,**extra):
            ids=set().union(*map(set,people.values())) if isinstance(people,dict) else set(people)
            item={'task_type':kind,'candidates':people,'profile_documents':[person_document(registry[p]) for p in sorted(ids)],**extra}
            key=identity(['post-audit-complete-v1',sid,source,item]);occurrences.append({'scope_id':sid,'key':key,'role':role})
            if key not in all_items:all_items[key]={'scope_id':sid,'item':item};queue.append((key,item))
        add('source_suitability',[],'source')
        for rank,pid in enumerate(row.get('top5',[]),1):add('call_person',[pid],'top'+str(rank))
        if row.get('primary'):
            for pid in row['primary']:add('call_person',[pid],'primary-member')
            add('group_usefulness',row['primary'],'primary-group')
        if sid in alternatives:
            group=row['option_members'][1];add('group_usefulness',group,'rank2-alternative')
            for pid in group:add('call_person',[pid],'rank2-member')
            add('comparison',{'A':row['primary'],'B':group},'alternative-comparison')
            if sid in swaps:add('comparison',{'A':group,'B':row['primary']},'order-swap')
        if sid in explanations:add('explanation_audit',row['primary'],'explanation',explanation='\n'.join(x['why_person'] for x in row['contributions']))
        packets,oversized=pack(source,[],queue,prompt)
        missing += [{'scope_id':sid,**x,'reason':'Complete packet exceeds proposed exact-input 24000-byte bound; no evidence trimmed'} for x in oversized]
        for packet in packets:
            packet['scope_id']=sid;packet['body_sha256']=identity(packet['body']);packet['conservative_microusd']=(packet['input_bound']*5+1)//2+5120;requests.append(packet)
    cost=sum(p['conservative_microusd'] for p in requests)
    if len(requests)>60 or cost>2000000:raise ValueError('Complete finite packet exceeds proposed ceiling; allocation must be reported, not dispatched')
    write(OUT/'judge-proposed-bodies-v2.json',requests);write(OUT/'judge-proposed-items-v2.json',all_items);write(OUT/'judge-source-contexts-v2.json',contexts)
    manifest={'version':'post-audit-complete-evidence-proposal-v1','dispatch_approved':False,'trusted_route':'Existing protected-main executor pins the old registry and Stage 3 IDs. Corrected profiles/new questions are rejected; a narrow exact-input policy/helper prerequisite needs explicit authority.','selection_sha256':__import__('hashlib').sha256((DOC/'semantic-selection-v2.json').read_bytes()).hexdigest(),'scope_groups':selection['source_groups'],'scopes':len(rows),'unique_items':len(all_items),'requests':len(requests),'accepted_items':sum(len(p['keys']) for p in requests),'missing':missing,'occurrences':occurrences,'roles':dict(Counter(x['role'] for x in occurrences)),'optional_selection':{'alternatives':alternatives,'explanations':explanations,'order_swaps':swaps},'input_token_bound':sum(p['input_bound'] for p in requests),'output_token_bound':512*len(requests),'conservative_usd':cost/1000000,'proposed_ceiling_usd':2,'proposed_attempt_ceiling':60,'actual_new_spend':0,'actual_new_requests':0,'prior_charged_usd':3.952987,'prior_requests':595,'remaining_after_proposed_actual_bound_usd':(6047013-cost)/1000000,'remaining_after_proposed_requests':95-len(requests),'price_checked_on':'2026-09-11','price_source':'https://platform.claude.com/docs/en/about-claude/pricing','model':'claude-sonnet-5','standard_input_usd_per_million':2,'conservative_input_usd_per_million':2.5,'output_usd_per_million':10,'no_paid_retries_planned':True,'complete_evidence':True,'algorithm_scores_sent':False,'historical_label_reuse':0,'human_requests':0,'packet_bodies_sha256':__import__('hashlib').sha256((OUT/'judge-proposed-bodies-v1.json').read_bytes()).hexdigest()}
    manifest['version']='post-audit-complete-evidence-proposal-v2';manifest['maximum_input_bound']=max(p['input_bound'] for p in requests);manifest['proposed_input_ceiling']=24000
    manifest['packet_bodies_sha256']=hashlib.sha256((OUT/'judge-proposed-bodies-v2.json').read_bytes()).hexdigest()
    manifest['prior_dry_run']='judge-proposal-v1.json: existing 12000-byte limit omitted 29 complete questions including the only primary group. Exact-input 24000-byte proposal retains all evidence and stays below $2.'
    write(DOC/'judge-proposal-v2.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ['occurrences','missing']},indent=2));print('Missing:',len(missing))

if __name__=='__main__':main()
