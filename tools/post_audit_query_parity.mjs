// Exact pre-optimization shared-query reference; no provider or new selection.
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {webcrypto,createHash} from 'node:crypto';
import {buildSharedPackage} from './build_shared_team_package.mjs';
const c=vm.createContext({Date,TextEncoder,TextDecoder,crypto:webcrypto}),reference=vm.createContext({});
vm.runInContext(fs.readFileSync('tests/fixtures/frozen/post-audit-search-query.js','utf8'),reference);
for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js','assets/team-matcher.js','assets/shared-team-engine.js','data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
const scopes=new Map();for(const name of ['legacy','rollout50','rollout150','semantic'])for(const s of JSON.parse(fs.readFileSync(`docs/team-recommender/post-audit/${name}-index.json`)).scopes)scopes.set(s.id,s);
const pack=await buildSharedPackage({catalog:c.GRANT_CATALOG,sidecar:c.SUBTOPIC_CATALOG,directory:c.RESEARCHER_DIRECTORY,config:c.FACULTY_MATCHES,scopes:[...scopes.values()]}),clock='2026-09-11T12:00:00Z';
const data=await c.SharedTeamEngine.hydrate(pack.packet,pack.index,c.RESEARCHER_DIRECTORY,c.GRANT_CATALOG,c.SUBTOPIC_CATALOG),engine=c.SharedTeamEngine.create(data,{clock:()=>clock});
const children=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG),old=[c.GRANT_CATALOG,children].map(x=>c.FUNDING_TEAM_MATCHER.create(x,c.FACULTY_MATCHES,reference.FUNDING_SEARCH_QUERY,{now:new Date(clock)}));
const expected=new Map();for(const name of ['corrected-current','rollout50','rollout150','semantic'])for(const row of JSON.parse(fs.readFileSync(name==='semantic'?'outputs/team-recommender-post-audit/semantic-outputs-v2.json':`outputs/team-recommender-post-audit/${name}-inventory.json`)).rows)expected.set(row.id,row);
let comparisons=0,groupsCompared=0;const skipped=[];
for(const s of scopes.values()){
 const record=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===s.parent_id),out=engine.resolveScope({parentId:s.parent_id,scopeId:s.id,record,now:clock});
 if(!out.ok){skipped.push({id:s.id,reason:out.reason});continue;}
 const matcher=old[s.record_type==='publishable_child'?1:0],prepared=matcher.records.find(r=>r.id===s.id),actual=new Map(engine.admittedFits().map(r=>[r.id,r.fit]));
 for(const profile of c.RESEARCHER_DIRECTORY.researchers.filter(c.SharedTeamEngine.eligible)){
  assert.equal(JSON.stringify(actual.get(profile.id)||null),JSON.stringify(matcher.scoreProfile(c.FUNDING_TEAM_MATCHER.normalizeProfile(profile),prepared)),s.id+' '+profile.id);comparisons++;
 }
 const prior=expected.get(s.id),state=engine.proposal(out.opportunity),options=engine.proposalOptions(state);
 if(prior){assert.equal(JSON.stringify(state.selectedIds),JSON.stringify(prior.primary));assert.equal(JSON.stringify(options.map(o=>o.state.selectedIds)),JSON.stringify(prior.option_members));groupsCompared++;}
}
const hash=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex'),result={version:3,reference_query_sha256:hash('tests/fixtures/frozen/post-audit-search-query.js'),query_sha256:hash('assets/search-query.js'),engine_sha256:hash('assets/shared-team-engine.js'),scientific_scopes:scopes.size,comparisons,score_and_evidence_disagreements:0,prior_primary_and_all_option_lists_compared:groupsCompared,group_disagreements:0,skipped,clock,new_provider_calls:0};
fs.writeFileSync('docs/team-recommender/post-audit/query-cache-parity-v3.json',JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(result));
