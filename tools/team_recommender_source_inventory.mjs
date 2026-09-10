import fs from 'node:fs';
import vm from 'node:vm';
import {createHash} from 'node:crypto';
const read=p=>fs.readFileSync(p,'utf8'),parse=p=>JSON.parse(read(p));
const hash=s=>createHash('sha256').update(s).digest('hex');
const c={};vm.createContext(c);
for(const p of ['assets/search-retrieval.js','assets/submission-schedule.js','data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/opportunity_teams.js'])vm.runInContext(read(p),c);
const now=new Date(),doc='docs/team-recommender/',dev=parse(doc+'manifests/development.json'),hold=parse(doc+'manifests/holdout.json'),roll=parse(doc+'manifests/rollout.json');
const parents=new Map(c.GRANT_CATALOG.opportunities.map(r=>[String(r.opportunity_id),r]));
const children=new Map(c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG).opportunities.map(r=>[r.subtopic_id,r]));
// Source-only identities and text statistics; never initialize or call a recommender.
const reservationRecords=new Map(parse(doc+'manifests/source-groups.json').records.map(s=>[s.id,s]));
const cohort=(roll.cohort_150||[]).map(id=>reservationRecords.get(id));
if(cohort.some(s=>!s))throw Error('Unresolved source reservation ID.');
if(!cohort)throw Error('Inspect actual rollout schema before adapting it.');
const sourceScopes=new Map([...dev.scopes,...hold.scopes,...cohort].map(s=>[s.id,s]));
const rows=[...sourceScopes.values()].map(s=>{
 const p=parents.get(s.parent_id),child=children.get(s.id),record=child||p;
 const text=String(child?.summary||p?.description||'');
 const status=p&&c.FUNDING_SUBMISSION_SCHEDULE.nextSubmission(p,now.toISOString().slice(0,10));
 return {id:s.id,parent_id:s.parent_id,record_type:s.record_type,source_text_chars:text.length,source_text_sha256:hash(text),
  original_public_text_available:Boolean(text),parent_current:c.FUNDING_RETRIEVAL.recordIsCurrent(p,now),
  child_current:child?c.FUNDING_RETRIEVAL.recordIsCurrent(child,now):null,submission_access:status?.access||'missing',
  coherent_scope_audit:'not-independent-reviewed',exact_v2_source_receipt:false,compatible_vectors:false,prepared:false};
});
const eligible=c.RESEARCHER_DIRECTORY.researchers.filter(p=>p.status==='active'&&p.auto_proposable&&['main','standby'].includes(p.pool_state)&&!['hidden','reference_only'].includes(p.pool_visibility));
const uniqueClaims=new Set(),claimRefs=[];for(const p of eligible)for(const claim of p.claims.filter(c=>c.status==='active')){
 uniqueClaims.add(p.id+'|'+claim.evidence.normalize('NFKC').toLowerCase().replace(/\s+/g,' ').trim());claimRefs.push([p.id,claim.claim_id,claim.revision]);}
const roles=c.OPPORTUNITY_TEAM_DATA.opportunities.flatMap(s=>s.roles.map(r=>({scope:s.id,role:r})));
const sourceMatch=roles.filter(({scope,role})=>{const s=children.get(scope)||parents.get(scope);return role.source_quote&&String(s?.summary||s?.description||'').includes(role.source_quote);});
const report={observed_at:now.toISOString(),recommendations_calculated:0,holdout_results_exposed:false,
  counts:{catalog_parents:parents.size,published_children:children.size,eligible_people:eligible.length,active_claims:claimRefs.length,deduplicated_passages:uniqueClaims.size,
   reserved_source_union:rows.length,development_scopes:dev.scopes.length,holdout_scopes:hold.scopes.length,rollout_scopes:cohort.length,
   original_public_text_available:rows.filter(r=>r.original_public_text_available).length,parent_current:rows.filter(r=>r.parent_current).length,
   open_rolling_or_undated_submission:rows.filter(r=>['open','rolling','not_listed'].includes(r.submission_access)).length,
   legacy_role_candidates:roles.length,legacy_role_quotes:roles.filter(r=>r.role.source_quote).length,legacy_quotes_exact_in_current_public_summary:sourceMatch.length,
   exact_v2_source_receipts:0,compatible_vectors:0,new_ready_rollout_scopes:0},
  source_rows:rows,claim_identity_sha256:hash(JSON.stringify(claimRefs)),
  reuse_policy:'Public sources/claims reused as preparation evidence; historical roles are candidates only. An exact summary quote alone does not prove coherent scope/conditions or current source verification.',
  unresolved:'Source and successor/coherence audit remains necessary before scientific-readiness certification. Existing grouped split is preserved; no replacement or redraw.',
  per_scope_preparation_missing:['source/coherence/conditions receipt','exact source-owned aspects','compatible query/profile vectors'],
  known_cross_split_group_overlap:dev.scopes.filter(s=>hold.scopes.some(h=>h.group_id===s.group_id)).length};
fs.writeFileSync(doc+'receipts/stage2-source-inventory.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report.counts));
