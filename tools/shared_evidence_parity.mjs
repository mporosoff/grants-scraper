import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';
const c=vm.createContext({Date});for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js','assets/team-matcher.js','data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
const scopes=new Map();for(const name of ['semantic','legacy','rollout50','rollout150'])for(const s of JSON.parse(fs.readFileSync(`docs/team-recommender/evidence-repair/${name}-index.json`)).scopes)scopes.set(s.id,s);
const people=c.RESEARCHER_DIRECTORY.researchers.filter(p=>p.status==='active'&&p.auto_proposable&&['main','standby'].includes(p.pool_state)&&!['hidden','reference_only'].includes(p.pool_visibility)).map(p=>c.FUNDING_TEAM_MATCHER.normalizeProfile(p));
let comparisons=0;const skipped=[];
for(const [type,catalog] of [['specific_parent',c.GRANT_CATALOG],['publishable_child',c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG)]]){
 const original=c.FUNDING_TEAM_MATCHER.create(catalog,c.FACULTY_MATCHES,c.FUNDING_SEARCH_QUERY,{now:new Date('2026-09-11T12:00:00Z')});
 const bounded=c.FUNDING_TEAM_MATCHER.create(catalog,c.FACULTY_MATCHES,c.FUNDING_SEARCH_QUERY,{now:new Date('2026-09-11T12:00:00Z'),sourceCacheLimit:8});
 for(const scope of scopes.values())if(scope.record_type===type){
  const a=original.records.find(r=>r.id===scope.id),b=bounded.records.find(r=>r.id===scope.id);assert.equal(Boolean(a),Boolean(b));
  if(!a){skipped.push(scope.id);continue;}
  for(const p of people){assert.equal(JSON.stringify(original.scoreProfile(p,a)),JSON.stringify(bounded.scoreProfile(p,b)),scope.id+' '+p.researcher_id);comparisons++;}
 }
}
const result={clock:'2026-09-11T12:00:00Z',scopes:scopes.size,profiles:people.length,comparisons,disagreements:0,skipped,meaning:'Full score/evidence identity between the default full-catalog preparation and bounded source retention; not scientific quality.',provider_calls:0,matcher_sha256:createHash('sha256').update(fs.readFileSync('assets/team-matcher.js')).digest('hex')};
fs.writeFileSync('docs/team-recommender/evidence-repair/bounded-source-parity.json',JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
