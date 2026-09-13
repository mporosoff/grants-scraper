// Local public-input preparation only. No networking, assessments or team output.
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash} from 'node:crypto';

export const INPUT_VERSION = 'audited-contextual-inputs-v1';
export const SPACE = Object.freeze({model:'voyage-4-large',dimensions:1024,
  document_role:'document',query_role:'query',preprocessing:'audited-summary-active-claims-v1',output_dtype:'float'});
export const compareIds = (a,b) => a<b?-1:a>b?1:0;
export const canonical = v => Array.isArray(v) ? '['+v.map(canonical).join(',')+']' : v && typeof v==='object'
  ? '{'+Object.keys(v).sort(compareIds).map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}' : JSON.stringify(v);
export const hash = v => createHash('sha256').update(typeof v==='string'?v:canonical(v)).digest('hex');
const copy = v => JSON.parse(JSON.stringify(v));
export const eligible = p => p.status==='active' && p.auto_proposable===true
  && ['main','standby'].includes(p.pool_state) && !['hidden','reference_only'].includes(p.pool_visibility);

export function assessmentPerson(document) {
  const p=document.evidence;
  const forms=records=>[...new Set((records||[]).map(r=>r.form))].sort(compareIds);
  return {person_id:p.person_id,summary:p.summary,summary_forms:forms(p.summary_evidence),
    claims:p.claims.map(c=>({claim_id:c.claim_id,revision:c.revision,label:c.label,evidence:c.evidence,
      type:c.type,evidence_level:c.evidence_level,forms:forms(c.evidence_records),source_urls:c.source_urls}))};
}

export function researcherDocument(person) {
  const claims=person.claims.filter(c=>c.status==='active').sort((a,b)=>compareIds(a.claim_id,b.claim_id));
  const seen=new Set(); const statements=[];
  for(const claim of claims) {
    const value=claim.label+'\n'+claim.evidence;
    if(!seen.has(value)){seen.add(value);statements.push(value);}
  }
  // No incidental names, departments, claim IDs, revision dates or popularity in relevance text.
  // Full summary and every distinct active statement are preserved without character clipping.
  const text=[person.research_summary,...statements].filter(Boolean).join('\n\n');
  const evidence={person_id:person.id,summary:person.research_summary,
    summary_evidence:copy(person.summary_evidence||[]),claims:copy(claims)};
  const document={person_id:person.id,text,input_id:hash({space:SPACE,input_type:'document',text}),evidence};
  return {...document,evidence_id:hash(assessmentPerson(document))};
}

export function loadCanonicalInputs(root='.') {
  const c=vm.createContext({Date});
  const paths=['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js',
    'assets/team-matcher.js','data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js'];
  for(const path of paths) vm.runInContext(fs.readFileSync(root+'/'+path,'utf8'),c,{filename:path});
  const registry=JSON.parse(fs.readFileSync(root+'/config/researcher_registry.json'));
  const directory=c.RESEARCHER_DIRECTORY;
  const {registry_generation,...registryBody}=registry;
  if(hash(registryBody)!==registry_generation)throw Error('registry_content_hash_conflict');
  if(registry.registry_generation!==directory.registry_generation) throw Error('registry_directory_generation_conflict');
  const byId=new Map(registry.researchers.map(p=>[p.researcher_id,p]));
  for(const person of directory.researchers) {
    const original=byId.get(person.id);
    if(!original || original.research_summary!==person.research_summary || original.auto_proposable!==person.auto_proposable
      || canonical(original.claims.map(c=>({id:c.claim_id,revision:c.revision,status:c.status,label:c.label,evidence:c.evidence})))
      !==canonical(person.claims.map(c=>({id:c.claim_id,revision:c.revision,status:c.status,label:c.label,evidence:c.evidence}))))
      throw Error('registry_projection_content_conflict');
    for(const field of ['summary_evidence','source_urls','source_checked_date','status','pool_visibility'])
      if(canonical(original[field]??null)!==canonical(person[field]??null))throw Error('registry_projection_provenance_conflict');
    for(const claim of person.claims){
      const source=original.claims.find(c=>c.claim_id===claim.claim_id);
      for(const field of ['category','categories','type','source_urls','evidence_level','verified_on','evidence_records'])
        if(canonical(source[field]??null)!==canonical(claim[field]??null))throw Error('registry_projection_claim_provenance_conflict');
    }
  }
  if(byId.size!==directory.researchers.length)throw Error('registry_projection_population_conflict');
  return {api:c,catalog:c.GRANT_CATALOG,sidecar:c.SUBTOPIC_CATALOG,directory,
    children:c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG),config:c.FACULTY_MATCHES,
    registry,files:Object.fromEntries([...paths,'config/researcher_registry.json'].map(p=>[p,hash(fs.readFileSync(root+'/'+p,'utf8'))]))};
}

// These are existing structured governing fields, not a second scientific synopsis.
export const CONDITION_FIELDS=['eligibility_text','applicant_types','eligibility_codes','submission_requirements',
  'limited_submission','limited_submission_source','limited_submission_review','career_stage_signal',
  'cost_share_required','deadlines','deadline_source','close_date','close_date_note','status',
  'rolling','actionability_status','document_status_signals','has_preliminary_stage','preliminary_required','preliminary_stage_type'];
export const SOURCE_FIELDS=['title','description','document_search_text','topic_areas','disciplines',
  'source','source_type','detail_page','funding_opportunity_url','primary_document_url','document_urls',
  'document_evidence_status','document_evidence','source_url','source_locator','evidence','summary',
  'parent_id','subtopic_id','validation','publication','verification','source_evidence',
  'source_document_url','source_document_hash','source_role','evidence_anchor','page_start','page_end',
  'publication_state','publication_reason','own_deadline','own_deadline_is_advisory'];
const pick=(record,keys)=>Object.fromEntries(keys.filter(k=>record[k]!==undefined).map(k=>[k,copy(record[k])]));
const incidental=new Set(['detail_checked_at','checked_at','retrieved_at','verified_on','reviewed_on','last_verified','first_seen','last_seen','updated_at']);
export const substantiveIdentity = v => Array.isArray(v)?v.map(substantiveIdentity):v&&typeof v==='object'
  ? Object.fromEntries(Object.entries(v).filter(([k])=>!incidental.has(k)).map(([k,w])=>[k,substantiveIdentity(w)])):v;

export function resolveCanonicalScope(inputs,id,clock) {
  const {catalog,children,api,config}=inputs;
  const parent=catalog.opportunities.find(r=>String(r.opportunity_id)===id);
  const child=parent?null:children.opportunities.find(r=>String(r.opportunity_id)===id);
  const record=parent||child;
  if(!record)return {id,state:'unmapped'};
  const owner=parent||catalog.opportunities.find(r=>String(r.opportunity_id)===child.parent_id);
  if(!owner)return {id,state:'unmapped',reason:'parent_missing'};
  const now=new Date(clock);
  if(!Number.isFinite(+now))throw Error('invalid_action_clock');
  const actionCurrent=api.FUNDING_RETRIEVAL.recordIsCurrent(owner,now)&&api.FUNDING_RETRIEVAL.recordIsCurrent(record,now);
  // Shared matcher owns the existing broad-scope presentation decision. Its profile gate/scores are not called.
  const prepared=api.FUNDING_TEAM_MATCHER.create({opportunities:[record]},config,api.FUNDING_SEARCH_QUERY,{now,sourceCacheLimit:1}).records[0];
  const hasChildren=children.opportunities.some(r=>r.parent_id===id);
  const broad=!!parent&&(hasChildren||prepared?.isBroad===true);
  const science=pick(record,SOURCE_FIELDS),conditions=pick(owner,CONDITION_FIELDS);
  const substantive=String(record.description||'').trim();
  const sourceIdentity={id,parent_id:String(owner.opportunity_id),kind:child?'publishable_child':'parent',science,conditions};
  return {...sourceIdentity,source_id:hash(substantiveIdentity(sourceIdentity)),action_current:actionCurrent,
    state:!actionCurrent?'action_blocked':broad?'needs_scope_selection':substantive.length<100?'insufficient_source':'unassessed',
    limitations:['Retained canonical catalog/child evidence; not newly retrieved or universally full-notice verified.',
      ...(child?['Parent structured conditions accompany child science; sibling science is excluded.']:[])],
    currentness:{record:pick(record,CONDITION_FIELDS),parent:pick(owner,CONDITION_FIELDS)},
    // Full original projection retained privately for reproducibility, outside scientific embedding text.
    canonical_record:copy(record)};
}

export function buildSnapshot(inputs,ids,clock) {
  const people=inputs.directory.researchers.filter(eligible).sort((a,b)=>compareIds(a.id,b.id)).map(researcherDocument);
  const roster_id=hash(people.map(p=>({id:p.person_id,input_id:p.input_id,evidence_id:p.evidence_id})));
  const scopes=ids.map(id=>resolveCanonicalScope(inputs,id,clock));
  const snapshot={schema_version:1,version:INPUT_VERSION,registry_generation:inputs.directory.registry_generation,
    directory_id:hash(inputs.directory),roster_id,space:SPACE,people,scopes};
  return {...snapshot,snapshot_id:hash(snapshot)};
}

export function balancedShortlist(rankings,maximum=12) {
  if(!Number.isInteger(maximum)||maximum<1||maximum>12||!Array.isArray(rankings)||rankings.length>6)
    throw Error('invalid_shortlist_bound');
  const lists=rankings.map(rows=>rows.slice().sort((a,b)=>b.score-a.score||compareIds(a.id,b.id)).slice(0,12));
  const selected=[],seen=new Set();
  for(let rank=0;rank<12&&selected.length<maximum;rank++)for(const list of lists){
    const row=list[rank];if(row&&!seen.has(row.id)&&selected.length<maximum){seen.add(row.id);selected.push(row.id);}
  }
  return {selected,per_contribution:lists.map(rows=>rows.map(r=>r.id)),
    omitted:[...new Set(lists.flatMap(r=>r.map(p=>p.id)))].filter(id=>!seen.has(id)),
    rule:'top12-per-contribution; contribution-order round robin by rank; canonical-ID ties; maximum12 people'};
}
