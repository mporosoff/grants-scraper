"""D1 bounded source corrections, frozen researcher contents, exact vector reuse."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from pypdf import PdfReader
from tools.team_recommender_real_prep import ROOT, DOC, sha, write, span, excerpt, packet, canonical
from tools.team_recommender_source import validate_source

OLD=ROOT/'outputs/team-recommender-c2'
OUT=ROOT/'outputs/team-recommender-d1'


def read(p):return json.loads(p.read_bytes())


def prepare():
    inp=read(OLD/'real-inputs-v2.json');before_people=sha(canonical(inp['people']));before_directory=sha(canonical(inp['directory']))
    original=copy.deepcopy(inp);sources={s['id']:s for s in inp['sources']};scopes={s['id']:s for s in inp['scopes']}
    dispositions={d['scope_id']:d for d in inp['dispositions']};changes=[]
    def replace_aspects(sid,quotes):
        s=scopes[sid];source=sources[sid];desc=next(e for e in source['excerpts'] if e['id']=='description')
        old=[a['text'] for a in s['aspects']];s['aspects']=[];s['group_budgets']=[]
        for i,q in enumerate(quotes):
            a=span(desc,q,'a'+str(i));a.update(kind='central' if i==0 else 'supporting',group_id='a'+str(i),
                weight=1 if len(quotes)==1 else .7 if i==0 else .3/(len(quotes)-1),requirement_kind='planning_contribution')
            s['aspects'].append(a);s['group_budgets'].append({'id':a['id'],'weight':a['weight']})
        changes.append({'id':sid,'before_aspects':old,'after_aspects':quotes})
    replace_aspects('359696',[scopes['359696']['aspects'][0]['text'],
        'multimodal approaches including leveraging existing advanced tools and technologies and developing new tools tailored for the olfactory system'])
    replace_aspects('362218',[scopes['362218']['aspects'][0]['text']])
    replace_aspects('363489',[scopes['363489']['aspects'][0]['text'],
        'tight co-design of the physical sensor package with advanced, real-time adaptive control systems necessary to stabilize and harness these complex dynamics'])
    # All cores use the source's declared central scientific contribution,
    # not an administrative award title. Most exact query vectors already exist.
    core_changes=[]
    for s in inp['scopes']:
        if s['prepared']:
            old=s['core']['text'];a=s['aspects'][0]
            s['core']={k:copy.deepcopy(a[k]) for k in ('text','span','input_hash')};s['core']['id']='core'
            if old!=s['core']['text']:core_changes.append({'id':s['id'],'before':old,'after':s['core']['text']})
    # The official amended PDF establishes the common instrument-assessment
    # activity and explicit exclusions. No instrument-type alternative is
    # promoted to a simultaneously required coverage target.
    sid='nasa-roses:25-D.9-d22059cf9f';s=scopes[sid];source=sources[sid]
    path=OUT/'source-retrieval/nasa-d9-notice.pdf';raw=path.read_bytes();pdf=PdfReader(path)
    pages=[re.sub(r'\s+',' ',p.extract_text()).strip() for p in pdf.pages]
    text='\n'.join(pages);url='https://nspires.nasaprs.com/external/viewrepositorydocument/cmdocumentid=1162128/solicitationId=%7BBE2AA4DC-81E7-2AF3-B465-8AA6478270A4%7D/viewSolicitationDocument=1/D.09_HWO-ICA_090326.pdf'
    retrieved=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()
    excerpts=[]
    for i in (0,3,4,5):
        e=excerpt(pages[i],'page'+str(i+1),'Amended D.9 PDF page '+str(i+1));e['offset']=text.index(pages[i]);excerpts.append(e)
    science=excerpts[0];q='developing and/or analyzing innovative instrument concepts and their scientific opportunity and performance, engineering feasibility and footprint, technology maturity and gaps, and associated risks'
    a=span(science,q,'a0');a.update(kind='central',group_id='a0',weight=1,requirement_kind='planning_contribution')
    s.update(prepared=True,readiness='unsupported',approach_id='d1-common-instrument-assessment',core=span(science,q,'core'),
        whole_call=span(excerpts[1],excerpts[1]['text'],'whole'),aspects=[a],group_budgets=[{'id':'a0','weight':1}])
    source.update(source_url=url,document_sha256=sha(raw),excerpts=excerpts)
    source['receipt']={'id':'d1-nasa-d9-source','kind':'source-span-validation-v1','validation_state':'source-backed','scope_id':sid,
        'parent_id':s['parent_id'],'approach_id':s['approach_id'],'document_sha256':sha(raw),'source_record_key':source['record_key'],
        'checked_at':retrieved,'valid_until':'2026-09-17T00:00:00Z','span_hashes':[e['sha256'] for e in excerpts]}
    validation=validate_source(source,s,original_bytes=raw,extracted_text=text,extraction_receipt={'scope_id':sid,'parent_id':s['parent_id'],
        'document_sha256':sha(raw),'text_sha256':sha(text),'method':'retained-document-extraction','extraction_code_sha256':sha(Path(__file__).read_bytes()),
        'source_url':url,'retrieved_at':retrieved,'coherent_scope':True,'conditions_preserved':True})
    validation['limitations']='Common exploratory instrument assessment only. Instrument types remain alternatives. Visible coronagraphy, flight hardware and support systems excluded. Category 2 funds only the US PI; other US collaborators are unfunded. No eligibility or full-proposal certification.'
    inp['validations'].append(validation)
    dispositions[sid].update(category='B-retrieved',numerically_preparable=True,source_url=url,source_snapshot_observed_at=retrieved,
        reason=validation['limitations'],new_vectors_missing=True)
    write(OUT/'source-retrieval/nasa-d9-extracted.json',{'raw_sha256':sha(raw),'source_url':url,'retrieved_at':retrieved,'text':text,'pages':len(pdf.pages),'normalization':'pypdf 6.16.1 extraction, whitespace collapse within each page; no semantic rewriting'})
    # Read the missing linked Parkinson focus areas without choosing a branch
    # or manufacturing a disease-wide conjunction. The reservation is retained.
    sid='362868';meta=read(OUT/'source-retrieval/parkinson-notice.json');path=OUT/'source-retrieval'/(meta['sha256']+'.bin')
    pdf=PdfReader(path);pages=[re.sub(r'\s+',' ',p.extract_text()).strip() for p in pdf.pages]
    text='\n'.join(pages);source=sources[sid]
    texts=[pages[i] for i in (3,5,6,7)];source.update(source_url=meta['url'],document_sha256=meta['sha256'],excerpts=[])
    for i,t in zip((4,6,7,8),texts):
        e=excerpt(t,'page'+str(i),'Official Parkinson IIRA PDF page '+str(i));e['offset']=text.index(t);source['excerpts'].append(e)
    dispositions[sid].update(category='B-retrieved-unselected',reason='The linked original notice now establishes four alternative focus areas, preliminary data and military-benefit conditions. No scientific branch was selected; do not combine all four into one team.',source_url=meta['url'],source_snapshot_observed_at=meta['retrieved_at'])
    write(OUT/'source-retrieval/parkinson-extracted.json',{'raw_sha256':meta['sha256'],'source_url':meta['url'],'retrieved_at':meta['retrieved_at'],'text':text,'normalization':'pypdf 6.16.1 extraction, whitespace collapse within each page; no semantic rewriting'})
    dispositions['243973'].update(category='A-restricted-existing-award',reason='Authoritative retained synopsis describes coherent aviation noise/emissions/modeling research, but new grants are restricted to members of the existing ASCENT award. No selected current member grant or institutional eligibility is established; retained unprepared. This is not a nonresearch classification.')
    queries={}
    for s in inp['scopes']:
        if s['prepared']:
            for item in [s['core'],s['whole_call'],*s['aspects']]:queries.setdefault(item['input_hash'],{'id':item['input_hash'],'owner':s['id'],'text':item['text']})
    inp['query_rows']=list(queries.values())
    assert sha(canonical(inp['people']))==before_people and sha(canonical(inp['directory']))==before_directory
    recipe=write(OUT/'real-inputs-d1.json',inp)
    prior={r['input_role']+':'+r['text_sha256'] for r in read(DOC/'prepared/c2/bundle.json')['vector_rows']}
    missing=[r for r in inp['query_rows'] if 'query:'+r['id'] not in prior]
    result=packet([{'input_role':'query','rows':missing}]) if missing else None
    write(DOC/'receipts/d1-source-corrections.json',{'recipe_sha256':recipe,'attempted':90,'prepared':sum(s['prepared'] for s in inp['scopes']),
        'controls':30,'source_aspects':sum(len(s['aspects']) for s in inp['scopes']),'core_changes':core_changes,'aspect_changes':changes,
        'dispositions':inp['dispositions'],'people_projection_unchanged':True,'people_projection_sha256':before_people,'directory_fields_sha256':before_directory,
        'reused_document_rows':len(inp['document_rows']),'reused_query_rows':len(queries)-len(missing),'new_query_rows':len(missing),'embedding_packet':result,
        'raw_source_retrievals':{'NASA_article':True,'NASA_amendment_article':True,'NASA_index_native_TLS':True,'NASA_amended_notice':True,'Parkinson_index':True,'Parkinson_notice':True},
        'full_notice_revalidation':False,'historical_receipt_dates_preserved':True,'no_scientific_source_model':True})
    print(json.dumps({'recipe':recipe,'prepared':sum(s['prepared'] for s in inp['scopes']),'missing_vectors':len(missing),'packet':result}))


if __name__=='__main__':prepare()
