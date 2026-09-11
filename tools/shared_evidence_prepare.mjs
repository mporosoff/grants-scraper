// Rebind the preserved source reservations to corrected code; zero team work.
import fs from 'node:fs';import vm from 'node:vm';import {buildSharedPackage} from './build_shared_team_package.mjs';
const c=vm.createContext({});for(const p of ['data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
const packages={};
for(const name of ['legacy','rollout50','rollout150','semantic']){
 const old=JSON.parse(fs.readFileSync(`docs/team-recommender/post-audit/${name}-index.json`,'utf8'));
 const pack=await buildSharedPackage({catalog:c.GRANT_CATALOG,sidecar:c.SUBTOPIC_CATALOG,directory:c.RESEARCHER_DIRECTORY,config:c.FACULTY_MATCHES,scopes:old.scopes});
 fs.writeFileSync(pack.path,pack.bytes);
 const index_path=`docs/team-recommender/evidence-repair/${name}-index.json`;
 fs.writeFileSync(index_path,JSON.stringify(pack.index,null,2)+'\n');
 packages[name]={index_path,generation:pack.index.generation_id,packet:pack.index.shared,scopes:old.scopes.length,previous_generation:old.generation_id,scope_changes:0};
}
fs.writeFileSync('docs/team-recommender/evidence-repair/routing-inventory-v1.json',JSON.stringify({packages,source_reservation_changes:0,profile_changes:0,provider_calls:0,teams_calculated:0},null,2)+'\n');
console.log(JSON.stringify(packages));
