// Exercise whole retained packages locally; never switches a production route.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {chromium} from '@playwright/test';
const current=JSON.parse(fs.readFileSync('docs/team-recommender/post-audit/release-packages-v4.json')).packages.rollout50;
const browser=await chromium.launch({headless:true});
const context=await browser.newContext(),page=await context.newPage(),network=[],observations=[];
let phase='';
page.on('request',r=>network.push({phase,url:r.url()}));
await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
for(const cohort of ['rollout50','rollback','rollout50']){
 phase=cohort;await page.setExtraHTTPHeaders({'x-post-audit-cohort':cohort});
 await page.goto('http://127.0.0.1:8771/match_explorer.html?gate4-e2e=1');
 await page.waitForFunction(()=>globalThis.OpportunityTeam&&globalThis.RESEARCHER_DIRECTORY&&globalThis.GRANT_CATALOG_METADATA);
 await page.evaluate(()=>FUNDING_CATALOG_LOADER.ensureCatalogReady());
 const result=await page.evaluate(async()=>{
  const data=await OpportunityTeam.loadData(),engine=OpportunityTeam.create(data);
  return {schema:OPPORTUNITY_TEAM_INDEX.schema_version,scope_generation:OPPORTUNITY_TEAM_INDEX.generation_id,
   registry_generation:RESEARCHER_DIRECTORY.registry_generation,scope_count:OPPORTUNITY_TEAM_INDEX.scopes.length,
   loaded_schema:data.schema_version,owned_scopes:engine.scopesFor('344592').length,
   shared_runtime:typeof SharedTeamEngine,html_generation:document.querySelector('meta[name="opportunity-team-generation"]').content};
 });
 assert.equal(result.schema,cohort==='rollback'?1:3);assert.equal(result.scope_generation,result.html_generation);
 assert(result.owned_scopes>0);observations.push({cohort,...result});
}
assert.deepEqual(observations[0],observations[2]);
assert.notEqual(observations[0].registry_generation,observations[1].registry_generation);
assert.equal(observations[1].shared_runtime,'undefined');
assert.equal(network.filter(r=>!r.url.startsWith('http://127.0.0.1:8771/')).length,0);
await browser.close();
fs.writeFileSync('docs/team-recommender/post-audit/rollback-browser-v3.json',JSON.stringify({
 version:'post-audit-whole-package-rollback-v1',old_candidate:'5927df0f5835c5a06df60d6bedea9667c9aec76994174452e01fa15a2e1642f0',
 new_candidate:current.candidate_id,
 production_mutated:false,new_provider_requests:0,observations,network,
 limitation:'Local transport restoration and schema/data adoption; historical proposals are not scientifically revalidated.'
},null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(observations));
