import fs from 'node:fs';import assert from 'node:assert/strict';import {performance} from 'node:perf_hooks';
import {chromium,expect} from '@playwright/test';
import {openFundingFinder,runFundingSearch} from '../tests/e2e/helpers.mjs';
const browser=await chromium.launch({headless:true}),rows=[];
for(const cohort of ['rollout50','rollout150'])for(let sample=0;sample<3;sample++){
 const context=await browser.newContext({baseURL:'http://127.0.0.1:8771',extraHTTPHeaders:{'x-post-audit-cohort':cohort}}),page=await context.newPage(),requests=[];let phase='search';
 page.on('request',r=>requests.push({phase,url:r.url()}));await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await openFundingFinder(page);await runFundingSearch(page,'W911NF-23-S-0003');await page.waitForFunction(()=>document.querySelector('#find-funding').disabled===false);await page.waitForTimeout(1800);
 assert(!requests.some(r=>/shared-team-engine|team_ingredients/.test(r.url)));
 const client=await context.newCDPSession(page);await client.send('Network.enable');await client.send('Network.emulateNetworkConditions',{offline:false,latency:150,downloadThroughput:20e6/8,uploadThroughput:20e6/8});
 const trigger=page.locator('[data-opportunity-team="345241"]:is([data-opportunity-team-scope=""],[data-opportunity-team-scope="345241"])').first(),drawer=page.locator('#team-builder'),scope='345241:tdac-baa-001';
 phase='prepared';let start=performance.now();await trigger.click();await expect(drawer).toContainText('Choose a specific opportunity topic');const chooser_ms=performance.now()-start;
 start=performance.now();await drawer.locator(`[data-opportunity-team-scope="${scope}"]`).click();await expect(drawer.locator('.opportunity-team-next')).toBeVisible();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));const selection_ms=performance.now()-start;
 const warm=await page.evaluate(async()=>{
  const click=async selector=>{const start=performance.now();document.querySelector(selector).click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return performance.now()-start;};
  const options=[];for(let i=0;i<5&&document.querySelector('#team-builder [data-opportunity-team-variant]');i++)options.push(await click('#team-builder [data-opportunity-team-variant]'));
  const id=document.querySelector('#team-builder [data-opportunity-team-remove]').getAttribute('data-opportunity-team-remove');
  const remove=await click('#team-builder [data-opportunity-team-remove]');const select=document.querySelector('#team-builder [data-opportunity-team-replacement]');select.value=id;select.dispatchEvent(new Event('change',{bubbles:true}));const add=await click('#team-builder [data-opportunity-team-add-replacement]');return {options,remove,add};
 });
 assert.equal(requests.filter(r=>r.phase==='prepared'&&!r.url.startsWith('http://127.0.0.1:8771/')).length,0);
 rows.push({cohort,scope,sample,chooser_ms,selection_ms,cold_total_ms:chooser_ms+selection_ms,warm,requests});console.log(cohort,sample,chooser_ms+selection_ms,warm);await context.close();
}
await browser.close();fs.writeFileSync('docs/team-recommender/evidence-repair/ui-resources-v1.json',JSON.stringify({version:1,clock:'Native browser and host monotonic clocks',network:'CDP 20Mbps/150ms after ordinary Search completes; no CPU throttle',measurement:'Cold first click to chooser plus automated child selection through two animation frames; excludes human deliberation. Warm timings include rendering through two frames.',new_provider_calls:0,physical_mobile:'NOT RUN',rows},null,2)+'\n',{flag:'wx'});
