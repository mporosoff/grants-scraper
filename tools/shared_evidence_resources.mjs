import fs from 'node:fs';import os from 'node:os';import assert from 'node:assert/strict';import {chromium} from '@playwright/test';
const version=process.argv.find(x=>x.startsWith('--version='))?.split('=')[1]||'1';
const samples=Number(process.argv.find(x=>x.startsWith('--samples='))?.split('=')[1]||1);
const browser=await chromium.launch({headless:true,args:['--enable-precise-memory-info']}),rows=[];
const cases=[['rollout50','345241:tdac-baa-001','345241'],['rollout150','344592:ab-0025','344592'],['rollout150','359696','359696']];
for(const [cohort,scope,parent] of cases)for(let sample=0;sample<samples;sample++){
 const context=await browser.newContext({extraHTTPHeaders:{'x-post-audit-cohort':cohort}}),page=await context.newPage(),network=[];let phase='startup';
 page.on('request',r=>network.push({phase,url:r.url()}));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await page.goto('http://127.0.0.1:8771/match_explorer.html?gate4-e2e=1');await page.waitForFunction(()=>globalThis.OpportunityTeam&&globalThis.RESEARCHER_DIRECTORY);
 await page.evaluate(async()=>{await FUNDING_CATALOG_LOADER.ensureCatalogReady();await FUNDING_SUBTOPICS.loadSidecar();});
 assert(!network.some(r=>/shared-team-engine|team_ingredients/.test(r.url)));
 const cdp=await context.newCDPSession(page);await cdp.send('HeapProfiler.collectGarbage');
 const before=await cdp.send('Runtime.getHeapUsage');
 await cdp.send('Network.enable');await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:20e6/8,uploadThroughput:20e6/8});
 phase='prepared';
 const cold=await page.evaluate(async()=>{
  const points=[];const sample=label=>points.push({label,time:performance.now(),combined_js_and_backing_bytes:performance.memory.usedJSHeapSize});sample('resident inputs');
  const original=crypto.subtle.digest.bind(crypto.subtle);crypto.subtle.digest=async(...args)=>{sample('before digest '+args[1].byteLength);const value=await original(...args);sample('after digest');return value;};
  const start=performance.now();globalThis.resourceData=await OpportunityTeam.loadData();sample('hydrated');const loaded=performance.now();globalThis.resourceEngine=OpportunityTeam.create(resourceData);sample('profiles normalized');
  crypto.subtle.digest=original;return {load_ms:loaded-start,create_ms:performance.now()-loaded,points,statistics:resourceEngine.statistics()};
 });
 const adopted=await cdp.send('Runtime.getHeapUsage');assert.equal(cold.statistics.fits,0);assert.equal(cold.statistics.optimizations,0);
 await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
 const timing=await page.evaluate(({scope,parent})=>{
  const e=resourceEngine,points=[],sample=label=>points.push({label,time:performance.now(),combined_js_and_backing_bytes:performance.memory.usedJSHeapSize});
  const input={parentId:parent,scopeId:scope,record:GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===parent),now:new Date()},start=performance.now();
  const decision=e.resolveScope(input);sample('first full-directory fit');if(!decision.ok)throw Error(decision.reason);const fit=performance.now();
  let state=e.proposal(decision.opportunity);const options=e.proposalOptions(state),view=e.proposalView(state),end=performance.now();sample('group and view');const warm=[],edit=[];
  for(let i=0;i<10;i++){const t=performance.now();e.runAction(input,()=>{e.proposalOptions(state);e.proposalView(state);});warm.push(performance.now()-t);sample('warm '+i);}
  for(let i=0;i<5&&state.selectedIds.length;i++){const t=performance.now(),id=state.selectedIds[0];e.runAction(input,()=>{state=e.removeMember(state,id);state=e.addReplacement(state,id);e.proposalView(state);});edit.push(performance.now()-t);sample('edit '+i);}
  return {fit_ms:fit-start,group_view_ms:end-fit,post_input_compute_ms:end-start,options:options.length,members:view.selected.length,warm,edit,points,statistics:e.statistics()};
 },{scope,parent});
 const after=await cdp.send('Runtime.getHeapUsage');
 assert.equal(network.filter(r=>r.phase==='prepared'&&!r.url.startsWith('http://127.0.0.1:8771/')).length,0);
 const resources=await page.evaluate(()=>performance.getEntriesByType('resource').filter(r=>/team_ingredients|shared-team-engine|team-matcher/.test(r.name)).map(r=>({url:r.name,duration:r.duration,encoded:r.encodedBodySize,decoded:r.decodedBodySize,transfer:r.transferSize,responseEnd:r.responseEnd})));
 rows.push({cohort,scope,sample,before,adopted,after,cold,timing,resources,network});console.log(JSON.stringify({cohort,scope,load:cold.load_ms,fit:timing.fit_ms,js_delta:(after.usedSize-before.usedSize)/1048576,combined_sample_delta:Math.max(...cold.points.concat(timing.points).map(x=>x.combined_js_and_backing_bytes))-cold.points[0].combined_js_and_backing_bytes}));
 await context.close();
}
const receipt={version,browser:await browser.version(),os:os.release(),cpu:os.cpus()[0].model,network:'20Mbps/150ms local gzip for team input phase; no CPU throttle',baseline:'Catalog, directory and topic sidecar resident; no team runtime or calculation. One collection before baseline, no collection during/after measured actions.',sampling:'CDP pure JS/backing/embedder observations after adoption and actions, plus precise combined JS+backing observations around digest and synchronous action boundaries. These samples can miss internal peaks; no continuous peak claim.',physical_mobile:'NOT RUN',provider_calls:0,rows};
await browser.close();fs.writeFileSync(`docs/team-recommender/evidence-repair/resources-v${version}.json`,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
