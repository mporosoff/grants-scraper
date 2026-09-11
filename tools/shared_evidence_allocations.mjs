import fs from 'node:fs';
import {chromium} from '@playwright/test';
// Allocation sampling of the preserved package, before the repair. No provider access.
const b=await chromium.launch({headless:true,args:['--enable-precise-memory-info']});
const context=await b.newContext({extraHTTPHeaders:{'x-post-audit-cohort':'rollout150'}}),page=await context.newPage();
await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
await page.goto('http://127.0.0.1:8771/match_explorer.html?gate4-e2e=1');
await page.waitForFunction(()=>globalThis.OpportunityTeam&&globalThis.RESEARCHER_DIRECTORY);
await page.evaluate(async()=>{await FUNDING_CATALOG_LOADER.ensureCatalogReady();await FUNDING_SUBTOPICS.loadSidecar();});
const cdp=await context.newCDPSession(page);
await cdp.send('HeapProfiler.collectGarbage'); // Identical pre-action baseline only.
const before=await cdp.send('Runtime.getHeapUsage');
await cdp.send('HeapProfiler.startSampling',{samplingInterval:32768,includeObjectsCollectedByMajorGC:true,includeObjectsCollectedByMinorGC:true});
const points=await page.evaluate(async()=>{
 const points=[],sample=label=>points.push({label,t:performance.now(),used:performance.memory.usedJSHeapSize});
 sample('resident catalog/directory/sidecar');globalThis.allocData=await OpportunityTeam.loadData();sample('hydrated');
 globalThis.allocEngine=OpportunityTeam.create(allocData);sample('normalized profiles');
 for(const [scope,parent] of [['359696','359696'],['344592:ab-0035','344592']]) {
  const input={scopeId:scope,parentId:parent,record:GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===parent),now:new Date()};
  const d=allocEngine.resolveScope(input);sample('fit '+scope);if(d.ok){let s=allocEngine.proposal(d.opportunity);allocEngine.proposalView(s);sample('group '+scope);}
 }
 return points;
});
const high=await cdp.send('Runtime.getHeapUsage'),profile=await cdp.send('HeapProfiler.stopSampling');
const totals=new Map();function walk(n){const key=n.callFrame.functionName+' '+n.callFrame.url+':'+n.callFrame.lineNumber;totals.set(key,(totals.get(key)||0)+n.selfSize);for(const child of n.children||[])walk(child);}walk(profile.profile.head);
const result={before,high,points,allocations:[...totals].sort((a,b)=>b[1]-a[1]),limits:'Statistical allocations include collected objects, not simultaneous peak. Step samples can miss synchronous peaks.',provider_calls:0};
fs.writeFileSync('outputs/team-recommender-evidence-repair/baseline-allocation-profile.json',JSON.stringify(profile,null,2));
fs.writeFileSync('docs/team-recommender/evidence-repair/baseline-allocations.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({...result,allocations:result.allocations.slice(0,15)}));await b.close();
