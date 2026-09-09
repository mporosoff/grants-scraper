// Stage 1 source-only inventory. Never calculates recommendation results.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
const dir = 'docs/team-recommender';
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
const write = (path, x) => fs.writeFileSync(`${dir}/${path}`, JSON.stringify(x, null, 2) + '\n');
const c = { Date }; vm.createContext(c);
const inputs = ['data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/opportunity_team_index.js','data/opportunity_teams.js','assets/search-retrieval.js'];
for (const p of inputs) vm.runInContext(fs.readFileSync(p,'utf8'),c);
const now = '2026-09-09T22:44:26.317Z'; // Observed UTC inventory clock; recheck at release.
const parents = c.GRANT_CATALOG.opportunities;
const parentMap = new Map(parents.map(r=>[r.opportunity_id,r]));
const children = c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG).opportunities;
const eligible = c.RESEARCHER_DIRECTORY.researchers.filter(r=>r.status==='active' && r.auto_proposable===true && ['main','standby'].includes(r.pool_state) && !['hidden','reference_only'].includes(r.pool_visibility));
const passages = eligible.flatMap(r=>r.claims.filter(q=>q.status==='active').map(q=>({researcher_id:r.id,claim_id:q.claim_id,revision:q.revision,text:q.evidence,label:q.label,source_urls:q.source_urls,evidence_level:q.evidence_level})));
const norm = x => String(x||'').normalize('NFKC').toLowerCase().replace(/\b(?:19|20)\d{2}\b/g,' ').replace(/[^a-z0-9]+/g,' ').trim();
const passageKey = x => String(x||'').normalize('NFKC').toLowerCase().replace(/\s+/g,' ').trim();
const dedup = [...new Map(passages.map(p=>[p.researcher_id+'|'+passageKey(p.text),p])).values()];
const counts = a => a.reduce((o,k)=>(o[k]=(o[k]||0)+1,o),{});
const current = p => c.FUNDING_RETRIEVAL.recordIsCurrent(p, now);
// Preserve old confirmations as exposed. Read identity fields, not evaluation outputs.
const old = JSON.parse(fs.readFileSync('evaluation/sonnet_team_scope_repair_4_20260909.json'));
const legacy = c.OPPORTUNITY_TEAM_INDEX.scopes;
const exposed = new Set([...old.confirmation_selection.ids,...old.confirmation_selection.excluded_previously_exposed_ids,...Object.keys(old.confirmation_selection.screened_not_selected||{}),...legacy.map(s=>s.id)].map(id=>id.split(':')[0]));
const families = [
 ['health-neuroscience',/health|disease|clinical|biomed|neural|neuro|cancer|patient/i],
 ['energy-environment',/energy|environment|climate|water|ecosystem|carbon|sustainab/i],
 ['computing-information',/comput|cyber|artificial intelligence|information|data science|software/i],
 ['physical-materials',/quantum|material|physics|photon|optic|chemistry|cataly|manufactur/i],
 ['bio-agriculture',/biolog|agricultur|plant|genom|food|animal/i],
 ['social-education',/social|education|behavior|workforce|economic|learning/i],
 ['engineering-other',/engineer|robot|sensor|transport|aerospace|mechanic/i],
];
function family(p,r){const t=[r.title,...r.topic_areas||[],...r.program_area_labels||[],...p.topic_areas||[]].join(' ');return families.find(([,rx])=>rx.test(t))?.[0]||'other-research';}
// Parent/successor grouping BEFORE splitting. Conservatively union equal URL,
// sponsor+solicitation, year-neutral titles and >=.85 title-token Jaccard.
const uf = new Map(parents.map(p=>[p.opportunity_id,p.opportunity_id]));
function root(x){while(uf.get(x)!==x)x=uf.get(x);return x;}
function union(a,b){a=root(a);b=root(b);if(a!==b)uf.set(a<b?b:a,a<b?a:b);}
const seen = new Map(); const links=[];
function sourceUrlKey(value){try{const u=new URL(value);u.hash='';for(const k of [...u.searchParams.keys()])if(k.startsWith('utm_'))u.searchParams.delete(k);u.searchParams.sort();return u.href;}catch{return value;}}
for(const p of parents){
 const keys=['title:'+norm(p.title),p.funding_opportunity_url && 'url:'+sourceUrlKey(p.funding_opportunity_url),p.opportunity_number && 'sol:'+norm(p.agency)+'|'+norm(p.opportunity_number)];
 for(const key of keys.filter(Boolean)){if(seen.has(key)){union(p.opportunity_id,seen.get(key));links.push({a:p.opportunity_id,b:seen.get(key),reason:key.split(':')[0]});}else seen.set(key,p.opportunity_id);}
}
const titleTokens=parents.map(p=>new Set(norm(p.title).split(' ').filter(t=>t.length>2)));
for(let i=0;i<parents.length;i++)for(let j=0;j<i;j++){
 if(norm(parents[i].agency)!==norm(parents[j].agency))continue;
 const a=titleTokens[i],b=titleTokens[j];if(Math.min(a.size,b.size)<4)continue;
 const n=[...a].filter(t=>b.has(t)).length;
 if(n/(a.size+b.size-n)>=.85){union(parents[i].opportunity_id,parents[j].opportunity_id);links.push({a:parents[i].opportunity_id,b:parents[j].opportunity_id,reason:'title-jaccard>=0.85'});}
}
const exposedGroups=new Set([...exposed].filter(p=>uf.has(p)).map(root));
const childParents=new Set(children.map(c=>c.parent_id));
const records=[];
for(const r of [...parents,...children]){
 const id=r.subtopic_id||r.opportunity_id,p=parentMap.get(r.parent_id||id);if(!p)continue;
 const child=Boolean(r.subtopic_id), text=String(child?r.summary:p.description||'');
 const source=r.source_document_url||p.funding_opportunity_url||p.detail_page;
 const science=/research|scientific|science|investigat/i.test(text);
 const sourceCandidate=current(p)&&science&&text.length>=150&&(child||!childParents.has(id));
 records.push({id,parent_id:p.opportunity_id,group_id:root(p.opportunity_id),title:r.title||r.subtopic_title||p.title,record_type:child?'publishable_child':'specific_parent',source_url:source,source_sha256:r.source_document_hash||hash(text),text_sha256:hash(text),source_chars:text.length,current:current(p),close_date:p.close_date||null,source_review:'pending-coherence-and-conditions-audit',source_candidate:sourceCandidate,family:family(p,r),historically_exposed:exposedGroups.has(root(p.opportunity_id))});
}
const ordered=records.filter(r=>r.source_candidate).sort((a,b)=>hash('team-stage1-v2|'+a.id).localeCompare(hash('team-stage1-v2|'+b.id)));
const splitFor=r=>r.historically_exposed?'development':parseInt(hash('team-stage1-split-v2|'+r.group_id).slice(0,8),16)%2?'holdout':'development';
function balanced(pool,n,maxPerGroup=1){const out=[],groups=new Map();let names=[...new Set(pool.map(r=>r.family))].sort();while(out.length<n){let progress=false;for(const f of names){const row=pool.find(r=>r.family===f&&!out.includes(r)&&(groups.get(r.group_id)||0)<maxPerGroup);if(row){out.push(row);groups.set(row.group_id,(groups.get(row.group_id)||0)+1);progress=true;if(out.length===n)break;}}if(!progress)break;}return out;}
const controlTypes=['expired-scope','umbrella-parent','sibling-leakage','alternative-branch','conditional-exclusion','sparse-profile','verbose-profile','duplicate-evidence','generic-language','unrelated-passage'];
for(const split of ['development','holdout']){
 const scopes=balanced(ordered.filter(r=>splitFor(r)===split),90);
 const controls=scopes.slice(0,30).map((r,i)=>({case_id:r.id+'#control-'+controlTypes[i%10],origin_scope_id:r.id,parent_id:r.parent_id,group_id:r.group_id,kind:controlTypes[i%10],materialization:'planned-fixture; not independent real solicitation',expected_semantic_label:null}));
 write(`manifests/${split}.json`,{version:'source-reservation-1',split,results_exposed:false,label_status:'none',eligibility_status:'provisional source-screened; bounded offline source coherence/feasibility audit pending',scopes,controls});
}
const rolloutChildren=balanced(ordered.filter(r=>r.record_type==='publishable_child'),50,50);
const childGroups=new Set(rolloutChildren.map(r=>r.group_id));
const rolloutParents=balanced(ordered.filter(r=>r.record_type==='specific_parent'&&!childGroups.has(r.group_id)),100);
const rollout=[...rolloutParents,...rolloutChildren];
const first=[...balanced(rolloutParents,30),...balanced(rolloutChildren,20,50)];
write('manifests/rollout.json',{version:'source-reservation-1',status:'not-prepared-or-authorized',selection_uses_recommendations:false,cohort_50:first.map(r=>r.id),cohort_150:rollout.map(r=>r.id),unique_parents:new Set(rollout.map(r=>r.parent_id)).size,children:rolloutChildren.length,families:counts(rollout.map(r=>r.family)),reserve:ordered.filter(r=>!rollout.some(x=>x.id===r.id)).map(r=>r.id),policy:'family round-robin, SHA256 team-stage1-v2|id order, 100 distinct parent groups plus 50 children; first 30+20; currentness and coherent source review required; no success-based substitution'});
write('manifests/source-groups.json',{decision_clock:now,near_duplicate_audit:'automatic conservative grouping; bounded source successor/near-duplicate audit required before freeze',links,records});
write('manifests/historical-exposure.json',{preserved_confirmation_ids:old.confirmation_selection.ids,excluded_parent_ids:[...exposed].sort(),policy:'Known/legacy source groups may enter development/regression only. Historical artifacts unmodified; no old quality result promoted.'});
const files={};for(const p of [...inputs,'data/search-v2-voyage-manifest.json','data/search-v2-voyage-vectors.f16','config/sonnet_production_qualification.json']){const b=fs.readFileSync(p);files[p]={sha256:hash(b),bytes:b.length,gzip_bytes:zlib.gzipSync(b).length};}
const v=JSON.parse(fs.readFileSync('data/search-v2-voyage-manifest.json'));
const claimCounts=eligible.map(r=>r.claims.filter(c=>c.status==='active').length).sort((a,b)=>a-b);
const r={decision_clock:now,files,parents:parents.length,current_parents:parents.filter(current).length,publishable_children:children.length,current_children:children.filter(r=>current(parentMap.get(r.parent_id))).length,source_screened_candidates:ordered.length,source_screened_groups:new Set(ordered.map(r=>r.group_id)).size,registry_generation:c.RESEARCHER_DIRECTORY.registry_generation,directory_counts:c.RESEARCHER_DIRECTORY.counts,active_eligible_claims:passages.length,deduplicated_eligible_passages:dedup.length,claim_counts:{min:claimCounts[0],median:claimCounts[Math.floor(claimCounts.length/2)],max:claimCounts.at(-1)},claim_text_chars:dedup.reduce((n,p)=>n+p.text.length,0),evidence_levels:counts(passages.map(p=>p.evidence_level)),missing_source_links:passages.filter(p=>!p.source_urls?.length).length,legacy_scope_count:legacy.length,legacy_parents:new Set(legacy.map(r=>r.parent_id)).size,legacy_review_states:counts(legacy.map(r=>r.review_state||'available')),legacy_generation:c.OPPORTUNITY_TEAM_INDEX.generation_id,legacy_roles:c.OPPORTUNITY_TEAM_DATA.opportunities.reduce((n,o)=>n+o.roles.length,0),search_vectors:{model:v.model,dimension:v.dimension,passages:v.passage_count,input_type:v.input_type,dtype:v.dtype,fingerprint:v.model_space_fingerprint,reuse_permitted:v.reuse_permitted,claim_rows:v.passages.filter(p=>String(p.passage_id).includes('claim')).length},compatible_aspect_vectors:0,compatible_claim_vectors:0,profile_and_scope_float32_estimate:{normal_150_6_aspects:(dedup.length+150*7)*1024*4,maximum_150_8_aspects:(dedup.length+150*9)*1024*4},rollout:{selected:rollout.length,unique_parents:new Set(rollout.map(r=>r.parent_id)).size,children:rolloutChildren.length,first:first.length}};
write('receipts/inventory.json',r);console.log(JSON.stringify({...r,files:undefined},null,2));
