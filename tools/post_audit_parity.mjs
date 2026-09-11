import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {webcrypto,createHash} from 'node:crypto';
const c=vm.createContext({Date,TextEncoder,TextDecoder,crypto:webcrypto});
for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js','outputs/team-recommender-post-audit/baseline-team-matcher.js','data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
const old=c.FUNDING_TEAM_MATCHER;for(const p of ['assets/team-matcher.js','assets/shared-team-engine.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
const index=JSON.parse(fs.readFileSync('docs/team-recommender/post-audit/legacy-index.json')),packet=JSON.parse(fs.readFileSync(index.shared.path)),clock='2026-09-11T12:00:00Z';
const child=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG),m=[c.GRANT_CATALOG,child].map(x=>old.create(x,c.FACULTY_MATCHES,c.FUNDING_SEARCH_QUERY,{now:new Date(clock)}));
const data=await c.SharedTeamEngine.hydrate(packet,index,c.RESEARCHER_DIRECTORY,c.GRANT_CATALOG,c.SUBTOPIC_CATALOG),e=c.SharedTeamEngine.create(data,{clock:()=>clock});let comparisons=0;const skipped=[];
for(const s of index.scopes){const r=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===s.parent_id),out=e.resolveScope({parentId:s.parent_id,scopeId:s.id,record:r,childCatalog:s.record_type==='publishable_child'?child:null,now:clock});if(!out.ok){skipped.push({id:s.id,reason:out.reason});continue;}
 const reference=m[s.record_type==='publishable_child'?1:0],prepared=reference.records.find(r=>r.id===s.id),actual=new Map(e.admittedFits().map(r=>[r.id,r.fit]));
 for(const p of c.RESEARCHER_DIRECTORY.researchers.filter(c.SharedTeamEngine.eligible)){assert.equal(JSON.stringify(actual.get(p.id)||null),JSON.stringify(reference.scoreProfile(old.normalizeProfile(p),prepared)));comparisons++;}
}
const result={comparisons,disagreements:0,skipped,clock,registry_generation:packet.registry_generation,runtime_sha256:createHash('sha256').update(fs.readFileSync('assets/shared-team-engine.js')).digest('hex'),matcher_sha256:createHash('sha256').update(fs.readFileSync('assets/team-matcher.js')).digest('hex'),reference_commit:'272124fc7d981cf3f438de7e9d133ca00600bee8',provider_calls:0};
fs.writeFileSync('docs/team-recommender/post-audit/fit-parity.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
