"""Account for every reserved source without fetching, scoring or replacing it."""
from collections import Counter
from tools.team_recommender_decision_closeout import DOC, OUT, read, write, digest


def inventory():
    metadata = read(OUT/'source-metadata.json')
    context = read(DOC/'prepared/d1/context.json')
    decisions = read(DOC/'manifests/development-source-decisions-c2.json')
    dispositions = {d['scope_id']:d for d in context['dispositions']}
    # Bounded original synopses read during closeout. These are preparation
    # dispositions only, not new aspects, exclusions, embeddings or rankings.
    adequate = {
        '360946':'Analytical/clinical validation of existing cancer assays; preserve phase choice, human specimens and clinical laboratory prerequisites.',
        '357609':'Origin/evolution of solid Earth through high-temperature geochemical/petrologic processes; alternatives are not mandatory roles.',
        '362197':'Hypothesis-driven ALS drug/therapy discovery and preliminary data generation.',
        '362848':'Hypothesis-driven Duchenne muscular dystrophy research; preserve preliminary-data requirement and no-clinical-trial condition.',
        '362209':'Exploratory innovative ovarian-cancer research, not certified clinical capability; preserve blinded preapplication.',
        '340828':'Exact official DMS/NIGMS source already used for the URL-shaped sibling reservation; retain shared corrected group.',
        '363287':'Use existing invasive-species knowledge to improve prevention policies/actions; do not invent a new basic-research requirement.',
        '354573':'Safety/effectiveness studies for designated MUMS veterinary drugs; INAD, designation and FDA protocol concurrence remain prerequisites.',
        '360182':'Reduce retail food-borne illness risk through research/intervention; applicant association/SLTT restrictions remain separate.',
        '363372':'Develop/prototype safer and more accessible buses; no researcher facilities or industry access assumed.',
    }
    gaps = {
        '362455':'Required focus areas need bounded context',
        '363455':'Required FY26 RTRP focus areas absent from retained synopsis.',
        '362607':'Required FY26 RTRP focus areas absent from retained synopsis.',
        '362186':'Required FY26 VRP focus areas absent; preserve regulatory-expertise and trial limits.',
        '362180':'Retained synopsis cuts off the career partnership condition; obtain bounded continuation before representing that pathway.',
        'nasa-roses:25-D.3E-1c60503f9d':'Retained Table 3 entry contains dates/title, not the necessary scientific program text.',
        '356612':'Retained amendment/white-paper instructions omit the scientific B1–B6 topics.',
        'nsf-funding:https://www.nsf.gov/funding/opportunities/eri-engineering-research-initiation/nsf24-590':'Upcoming-dates excerpt ends with ellipsis; no coherent selected scientific project.',
        '363241':'Generic ROSES wrapper points to A.15 program element; source-only Step-1 prerequisite is already recorded, scientific element missing.',
        '359946':'Prospective observational/biomarker mechanism; bounded oral-health scientific purpose not in this short synopsis.',
    }
    nonresearch = {'362551','363818','334972','363796','363374','363559','358403','363655','328573'}
    rows=[]
    for r in metadata['rows']:
        sid=r['id']; old=dispositions.get(sid); record=r['record']; prepared=bool(old and old['numerically_preparable'])
        category='unknown-unprocessed'; reason='Existing source text is retained, but coherent-scope/necessary-condition sufficiency has not been settled; no adverse person inference.'
        if prepared:category='prepared-existing';reason=old['reason']
        elif sid in decisions['nonresearch_or_mechanism'] or sid in nonresearch:
            category='out-of-scope-mechanism';reason='Existing source identifies a broad funding/training/service/infrastructure mechanism without a selected scientific contribution for this interface.'
        elif sid in decisions['unselected_umbrella']:
            category='out-of-scope-unselected';reason='Preserved prior source-only disposition: multiple unselected scientific branches; do not combine them.'
        elif old:
            category='bounded-context-gap';reason=old['reason']
        elif sid in gaps:category='bounded-context-gap';reason=gaps[sid]
        elif sid in adequate:
            category='adequate-existing-normal-preparation';reason=adequate[sid]
        elif r['record_type']=='publishable_child':
            title=r['title'].lower()
            if 'inactive' in title:
                category='out-of-scope-inactive';reason='Native title explicitly says INACTIVE; publication flag alone cannot clear that contradiction.'
            elif 'support to' in title or 'partnerships for' in title:
                category='out-of-scope-unselected';reason='Child is a broad competency/partnership support branch without a selected scientific contribution.'
            elif record.get('subtopic_source')=='native' and record.get('source_document_hash') and record.get('evidence_anchor') and record.get('parent_id')==r['parent_id']:
                category='adequate-existing-normal-preparation';reason='Existing native child title/summary, exact parent, original document hash and locator support bounded exploratory aspect preparation. Preserve original last_verified; full notice and unstated conditions remain unverified.'
            else:
                category='bounded-context-gap';reason='Referenced child excerpt is not the retained authoritative section. Obtain only the identified branch scientific passage/necessary conditions, as for TDAC BAA-004.'
        action_current=r['parent_current'] and r['child_current'] is not False
        rows.append({'id':sid,'parent_id':r['parent_id'],'group_id':r['group_id'],'title':r['title'],'record_type':r['record_type'],'cohorts':r['cohorts'],
                     'category':category,'reason':reason,'prepared':prepared,'new_preparation_performed':False,'source_record_sha256':r['source_sha256'],
                     'source_url':record.get('source_document_url') or record.get('detail_page') or record.get('funding_opportunity_url'),
                     'original_observation':record.get('last_verified') or (old or {}).get('source_snapshot_observed_at') or context['snapshot_at'],
                     'original_document_hash':record.get('source_document_hash'),'locator':record.get('evidence_anchor'),
                     'source_text_characters':len(r['source_text']),'source_text_sha256':__import__('hashlib').sha256(r['source_text'].encode()).hexdigest(),
                     'current_at_clock':action_current,'submission':r['submission'],
                     'applicant_restrictions':record.get('eligibility_text','Inherited parent eligibility and native child conditions require inspection; no qualification inferred.'),
                     'existing_publishable_child_ids':r['existing_publishable_children'],
                     'restriction_assessment':'Submission access/eligibility retained independently of scientific coherence. No claim all listed researchers qualify.',
                     'feasible_directory_denominator':'unknown-independent-assessment'})
    summaries={}
    for cohort,ids in metadata['cohorts'].items():
        selected=[r for r in rows if cohort in r['cohorts']]
        assert len(selected)==len(ids)
        summaries[cohort]={'total':len(selected),'prepared':sum(r['prepared'] for r in selected),
                          'dispositions':dict(Counter(r['category'] for r in selected)),
                          'parents':len({r['parent_id'] for r in selected}),'children':sum(r['record_type']=='publishable_child' for r in selected),
                          'current_at_clock':sum(r['current_at_clock'] for r in selected),
                          'submission_access':dict(Counter(r['submission']['access'] for r in selected)),
                          'prepared_current':sum(r['prepared'] and r['current_at_clock'] and r['submission']['access'] in {'open','rolling','not_listed'} for r in selected)}
    union=[r for r in rows if set(r['cohorts']) & {'rollout50','rollout150','holdout_effective'}]
    existing=[r for r in union if r['category']=='adequate-existing-normal-preparation']
    result={'version':'stage2-closeout-source-accounting-v1','clock':metadata['clock'],'recommendations_loaded_or_calculated':False,
            'disposition_provenance':'Preserved C2/D1 source dispositions, deterministic native ownership/provenance checks and ordinary in-task reading of the explicitly listed official synopses. Not a separately executed model judge or a human review.',
            'policy':'Preserve original 50/150 and effective source-group overlay; no replacement, expansion or new source claim. Adequate means bounded existing scientific context supports normal preparation, not full-notice verification or application eligibility.',
            'summaries':summaries,'rows':rows,
            'unique_future_input_work':{'union_scopes':len(union),'existing_prepared':sum(r['prepared'] for r in union),
                'adequate_unprepared_scopes':len(existing),'adequate_unprepared_parents':len({r['parent_id'] for r in existing}),
                'profile_documents_reused':155,'profile_embedding_rows_new':0,'existing_E2_query_rows':95,
                'unprepared_exact_query_texts':'not yet selected/validated; exact unique changed text count unavailable without normal preparation',
                'upper_query_rows_for_adequate_scopes':10*len(existing),'upper_rule':'At most eight aspects plus core and whole per scope, exact-text dedup before embedding; ceiling, not actual missing rows.'},
            'reserve_policy':{'unchanged':True,'selected_replacements':[],
                'proposal':'For objectively ineligible rollout entries only, request owner approval to walk the existing source-based reserve order with original family/parent-child policy, exclude duplicate corrected groups, then source-audit before any recommendation inspection. Do not silently substitute children for parents or replace held-out outcomes.'},
            'split_hashes':{n:digest(DOC/'manifests'/n) for n in ['development.json','holdout.json','rollout.json','source-group-amendment-c2-f92fc5995a0a1ac0.json']},
            'new_retrievals':0,'new_vectors':0,'new_aspects':0,'private_source_snapshot_sha256':digest(OUT/'source-metadata.json')}
    write(DOC/'receipts/closeout-source-accounting.json',result)
    print(__import__('json').dumps({'summaries':summaries,'work':result['unique_future_input_work']}))


if __name__=='__main__':inventory()
