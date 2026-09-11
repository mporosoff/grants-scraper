"""Frozen-policy source preparation. No recommendation or provider imports.

Existing public snapshots supply the evidence. This writes ingredient recipes,
not vectors or teams; every missing representation remains explicitly missing.
"""
import copy
import json
import re
from html import unescape
from collections import Counter
from pathlib import Path
from tools.team_recommender_real_prep import ROOT, DOC, sha, canonical, span, excerpt, record_key, jsdata, write
from tools.team_recommender_source import translate_official_export, translate_nsf_page, validate_source

OUT = ROOT / 'outputs/team-recommender-stage3'
OLD = ROOT / 'outputs/team-recommender-d3/assembled-E2'


def read(path):
    return json.loads(path.read_bytes())


def prepare(write_results=False):
    metadata = read(ROOT/'outputs/team-recommender-closeout/source-metadata.json')
    audited = read(DOC/'receipts/closeout-source-accounting.json')
    decisions = read(DOC/'manifests/stage3-source-decisions-v1.json')
    rows = {r['id']: r for r in metadata['rows']}
    old_rows = {r['id']: r for r in audited['rows']}
    original = read(OLD/'bundle.json')
    old_sources = {r['id']: r for r in original['sources']}
    old_scopes = {r['id']: r for r in original['scopes']}
    old_validations = {r['scope_id']: r for r in read(OLD/'validations.json')}
    raw = (ROOT/'data/opportunities.js').read_bytes()
    cat = jsdata(ROOT/'data/opportunities.js')
    parents = {r['opportunity_id']: r for r in cat['opportunities']}
    native_raw = (ROOT/'data/subtopics.js').read_bytes()
    native = jsdata(ROOT/'data/subtopics.js')
    children = {s['subtopic_id']: s for r in native['records'].values() for s in r['subtopics']}
    selected_ids = sorted(set(metadata['cohorts']['holdout_effective']) | set(metadata['cohorts']['rollout150']))
    sources, scopes, validations, dispositions, queries, records = [], [], [], [], {}, {}
    for sid in selected_ids:
        r, old = rows[sid], old_rows[sid]
        pid = r['parent_id']; record = children.get(sid, parents[pid]); records[sid] = record
        if old['prepared']:
            scope = copy.deepcopy(old_scopes[sid]); source = copy.deepcopy(old_sources[sid])
            validation = copy.deepcopy(old_validations[sid]); category = 'reused-prepared-source'
            reason = old['reason']; observed = source['receipt']['checked_at']
        else:
            category, reason = old['category'], old['reason']
            if sid in decisions['unselected']:
                category, reason = 'out-of-scope-unselected', 'Original synopsis has multiple unselected scientific branches or a general program rather than one declared contribution; no branch silently selected.'
            elif sid in decisions['mechanisms']:
                category, reason = 'out-of-scope-mechanism', 'Original source describes a training, service, support, partnership or infrastructure mechanism without a selected scientific project.'
            elif sid in decisions['missing_context']:
                category, reason = 'bounded-context-gap', decisions['missing_context'][sid]
            quotes = decisions['adequate_quotes'].get(sid)
            observed = cat['generated_at']; docsha = sha(raw)
            url = old['source_url'] or r['source_reservation']['source_url']
            texts, validation = [], None
            if record.get('source') == 'Grants.gov':
                texts = [excerpt(record[f], f, f) for f in ('title', 'description', 'eligibility_text') if record.get(f)]
                if quotes and record.get('description_source') == 'Official NSF funding page':
                    texts = [excerpt(record['description'],'description','official NSF page text')]
                    validation = translate_nsf_page(artifact_bytes=(ROOT/'data/opportunity_enrichment.json').read_bytes(),record=record,excerpts=texts)
                    url=record['description_source_url'];docsha=validation['document_sha256'];observed=validation['retrieved_at']
                elif quotes:
                    validation = translate_official_export(artifact_bytes=raw, record=record, scope_id=sid, parent_id=pid,
                        excerpts=texts, snapshot_at=observed, source_url=url, export_identity=cat['source']['extract_file'])
            elif category == 'adequate-existing-normal-preparation' and sid in children:
                if not (record.get('subtopic_source') == 'native' and record['parent_id'] == pid
                        and record.get('source_document_hash') and record.get('evidence_anchor')):
                    raise ValueError('native_parent_or_document_mismatch:'+sid)
                description = record.get('summary') or record['title']
                texts = [excerpt(record['title'], 'title', 'native title'),
                         excerpt(description, 'description', record['evidence_anchor'][:200])]
                # A native named scientific child is already the selected unit.
                # Its title is the central scientific contribution; the full
                # original child description stays in the whole-scope input.
                quotes = [record['title']]
                docsha, url = record['source_document_hash'], record['source_document_url']
                observed = record['last_verified'] + 'T00:00:00Z'
                validation = {'validation':'retained-native-spans-verified','scope_id':sid,'parent_id':pid,
                    'document_sha256':docsha,'text_sha256':sha(description),'retrieved_at':None,'observed_at':observed,
                    'new_retrieval':False,'excerpt_count':len(texts),'excerpt_hashes':[e['sha256'] for e in texts],
                    'semantic_judgment':False,'provenance':{'kind':'native-catalog-scope-v1','artifact_sha256':sha(native_raw),
                    'source_url':url,'parent_id':pid,'scope_id':sid,'document_sha256':docsha,'locator':record['evidence_anchor']},
                    'limitations':'Original native child title/summary and exact parent/document/locator. Original last_verified has day precision, encoded at midnight; no new retrieval or full-annex verification. Unstated conditions remain unknown.'}
            elif sid.startswith('345241:tdac-baa-') and category == 'bounded-context-gap':
                retained_dir = ROOT/'outputs/team-recommender-c2/source-retrieval'
                fetch = read(retained_dir/'quantum.json')
                original_bytes = (retained_dir/(fetch['document_sha256']+'.html')).read_bytes()
                if sha(original_bytes) != fetch['document_sha256'] or record['parent_id'] != pid:
                    raise ValueError('retained_TDAC_document_or_parent_mismatch')
                # Include lists as well as paragraphs; the C2 quantum receipt
                # remains unchanged and no sibling section enters this scope.
                page = re.sub(r'\s+', ' ', unescape(re.sub('<[^>]+>', ' ', original_bytes.decode('utf8'))))
                marker = 'Announcement ID: TDAC BAA-'+sid.rsplit('-',1)[1]
                begin = page.rfind(marker); end = page.find('Title:',begin)
                if begin < 0 or end < begin: raise ValueError('TDAC_scope_section_missing')
                section = page[begin:end]
                description = section[section.index('Description:')+len('Description:'):].strip()
                texts = [excerpt(record['title'],'title',marker+' native title'),
                         excerpt(description,'description',marker+' complete Description; ends before next title')]
                texts[1]['offset'] = len(record['title'])+1
                quotes = [record['title']]
                url, docsha, observed = fetch['source_url'], fetch['document_sha256'], fetch['retrieved_at']
                validation = {'raw':original_bytes,'text':record['title']+'\n'+description,
                    'limits':'Reuse of original dated official Army page. Exact announcement section, including lists; no sibling science. Common analytical purpose only; alternative investigations are not conjunctive requirements. General BAA conditions remain in the original parent record, not newly verified.'}
            elif sid.startswith('darpa-iarpa:') and quotes:
                from scripts.sources.adapters.darpa_iarpa import darpa_description, darpa_inventory, plain, darpa_opportunity_block, confirmed_notice_action, _LINK
                fixtures = ROOT/'tests/fixtures/darpa_iarpa'
                file = fixtures/('resilient.html' if sid.endswith('250704') else 'qbi.html')
                html = file.read_text(encoding='utf-8')
                listing = next(x for x in darpa_inventory(read(fixtures/'darpa.json')) if x['field_opportunity_number']==record['opportunity_number'])
                block = darpa_opportunity_block(html, record['opportunity_number'])
                confirmed_notice_action([u for u,_ in _LINK.findall(block)], 'DARPA', record['opportunity_number'], record['detail_page'])
                body = plain(listing.get('field_body_with_summary') or listing.get('field_body_with_summary_1'))
                topics = plain(listing.get('field_research_topics','')).replace('|','; ')
                description = body + ' ' + darpa_description(html, '') + ' Research topics: ' + topics
                if description.strip() != record['description']:
                    raise ValueError('retained_DARPA_description_mismatch:'+sid)
                url = 'https://www.darpa.mil/research/programs/' + ('resilient' if sid.endswith('250704') else 'quantum-benchmarking-initiative')
                observed = '2026-09-05T00:00:00Z'
                # These are documented ORIGINAL official excerpts, not synthetic
                # fixture records. Bind both the listing and page source bytes.
                original_bytes = (fixtures/'darpa.json').read_bytes()+b'\n'+file.read_bytes()
                docsha = sha(original_bytes)
                text = record['title']+'\n'+description
                texts = [excerpt(record['title'],'title','official listing title'), excerpt(description,'description','official listing and program body')]
                texts[1]['offset'] = len(record['title'])+1
                validation = {'raw':original_bytes,'text':text,'limits':'Original official DARPA listing/program excerpts documented as retrieved September 5, 2026; day precision encoded at midnight, not newly fetched. Exact PA child action checked. Program-stage alternatives remain separate; full SAM attachment restrictions remain unknown.'}
            if quotes and validation:
                category = 'translated-existing-provenance'
                reason = 'Bounded common scientific purpose from retained official evidence; alternatives are not conjunctive sponsor requirements. Conditions retained; independent directory feasibility unknown.'
            supplement = decisions.get('retrieved_dispositions',{}).get(sid)
            if supplement:
                category, reason = supplement['category'], supplement['reason']
            if not texts:
                # Unsupported source metadata is still an explicit reservation.
                description = record.get('summary') or record.get('description') or record['title']
                texts = [excerpt(description,'description','retained unprepared source field')] if len(description)<=8000 else []
            source = {'id':sid,'parent_id':pid,'record_key':record_key(record),'source_url':url,
                      'document_sha256':docsha,'receipt':None,'excerpts':texts}
            scope = {'id':sid,'parent_id':pid,'record_type':r['record_type'],'scope_label':r['title'],
                     'approach_id':'source-approach-v1','prepared':False,'readiness':'unsupported','aspects':[],'evidence_links':[]}
            if validation:
                description = next(e for e in texts if e['id']=='description')
                whole = description['text']
                if sid in decisions.get('whole_science_spans',{}):
                    cut = decisions['whole_science_spans'][sid]
                    whole = whole[whole.index(cut['start']):whole.index(cut['end'])].strip()
                if len(whole.encode('utf-16-le'))//2 > 4000:
                    validation = None; category = 'bounded-representation-gap'
                    reason = 'Complete scoped scientific text exceeds frozen 4000-unit ingredient field; no source text cropped or scoring rule changed.'
                else:
                    scope.update(prepared=True,whole_call=span(description,whole,'whole'),aspects=[],group_budgets=[])
                    for i,q in enumerate(quotes):
                        source_excerpt = next((e for e in texts if q in e['text']),None)
                        if source_excerpt is None:raise ValueError('exact_quote_missing:'+sid+':'+q)
                        a=span(source_excerpt,q,'a'+str(i));a.update(kind='central' if i==0 else 'supporting',group_id='a'+str(i),
                            weight=1 if len(quotes)==1 else .7 if i==0 else .3/(len(quotes)-1),requirement_kind='planning_contribution')
                        scope['aspects'].append(a);scope['group_budgets'].append({'id':a['id'],'weight':a['weight']})
                    first=scope['aspects'][0];scope['core']={k:copy.deepcopy(first[k]) for k in ('text','span','input_hash')};scope['core']['id']='core'
                    source['receipt']={'id':'s3r'+sha(sid)[:24],'kind':'source-span-validation-v1','validation_state':'source-backed',
                        'scope_id':sid,'parent_id':pid,'approach_id':scope['approach_id'],'document_sha256':docsha,'source_record_key':source['record_key'],
                        'checked_at':observed,'valid_until':'2026-09-17T00:00:00Z','span_hashes':[e['sha256'] for e in texts]}
                    if 'raw' in validation:
                        retained=validation
                        validation=validate_source(source,scope,original_bytes=retained['raw'],extracted_text=retained['text'],extraction_receipt={
                            'scope_id':sid,'parent_id':pid,'document_sha256':docsha,'text_sha256':sha(retained['text']),
                            'method':'retained-document-extraction','extraction_code_sha256':sha(Path(__file__).read_bytes()),
                            'source_url':url,'retrieved_at':observed,'coherent_scope':True,'conditions_preserved':True})
                        validation['limitations']=retained['limits']
        if validation:
            validations.append(validation)
            for item in [scope['core'],scope['whole_call'],*scope['aspects']]:
                key=sha(item['text']);queries.setdefault(key,{'id':key,'owner':sid,'text':item['text']})
                item.pop('vector',None);item.pop('input_hash',None)
        sources.append(source);scopes.append(scope)
        dispositions.append({'scope_id':sid,'parent_id':pid,'group_id':r['group_id'],'family':r['family'],'cohorts':r['cohorts'],
            'category':category,'reason':reason,'source_prepared':scope['prepared'],'numerically_preparable':scope['prepared'],
            'vectors_present':False,'source_snapshot_observed_at':observed,'source_record_sha256':sha(canonical(record)),
            'source_url':source['source_url'],'submission':r['submission'],'current_at_comparison_clock':r['parent_current'] and r['child_current'] is not False,
            'feasibility':'unknown-independent-directory-assessment','new_source_retrieval':sid in decisions.get('retrieved_dispositions',{}),
            'additional_context':decisions.get('retrieved_dispositions',{}).get(sid)})
    overlay=read(DOC/'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json')
    controls=overlay['holdout_controls']
    result={'sources':sources,'scopes':scopes,'validations':validations,'records':records,'parents':parents,
            'dispositions':dispositions,'query_rows':list(queries.values()),'controls':controls,
            'snapshot_at':cat['generated_at'],'scope_denominator':90,'control_denominator':30,
            'cohorts':metadata['cohorts'],'recommendations_generated':False,'profile_inputs_unchanged':True}
    summary={name:{'reserved':len(ids),'source_prepared':sum(s['prepared'] for s in scopes if s['id'] in ids),
                   'categories':dict(Counter(d['category'] for d in dispositions if d['scope_id'] in ids))}
             for name,ids in metadata['cohorts'].items() if name!='holdout_original'}
    summary['unique_query_rows']=len(queries)
    if write_results:
        digest=write(OUT/'source-inputs-v1.json',result)
        write(DOC/'receipts/stage3-source-preparation-v1.json',{'recipe_sha256':digest,'summaries':summary,'dispositions':dispositions,
            'code_sha256':sha(Path(__file__).read_bytes()),'new_retrievals':4,'new_vectors':0,'recommendations_generated':False})
    return result,summary


if __name__=='__main__':
    import sys
    _,summary=prepare('--write' in sys.argv)
    print(json.dumps(summary,indent=2))
