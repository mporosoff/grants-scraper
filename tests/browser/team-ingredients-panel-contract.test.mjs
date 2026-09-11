import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import {webcrypto,createHash} from 'node:crypto';
import {shellDom} from '../helpers/shell-dom.mjs';
import {fixture,NOW} from '../fixtures/team-ingredients.mjs';
import {buildPackage} from '../../tools/build_team_ingredients.mjs';
const read=p=>fs.readFileSync(p,'utf8'),tick=()=>new Promise(r=>setTimeout(r,0));
async function panel({count=10,corrupt=false,delay=false}={}){
 const f=await fixture({count}),pack=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.manifest.source_validations});
 const dom=shellDom(read('match_explorer.html')), clock={now:NOW.getTime()}, requests=[], pending=[];
 class DecisionDate extends Date{constructor(value){super(value??clock.now);}static now(){return clock.now;}}
 const c=dom.context;Object.assign(c,{URL,location:{href:'https://example.org/match_explorer.html'},Date:DecisionDate,TextEncoder,TextDecoder,Uint8Array,Float32Array,DataView,AbortController,clearTimeout,crypto:webcrypto,btoa,
  OPPORTUNITY_TEAM_INDEX:pack.index,RESEARCHER_DIRECTORY:f.directory,GRANT_CATALOG:{opportunities:[f.record]},
  XMLHttpRequest:class{constructor(){throw Error('provider/client blocked');}},WebSocket:class{constructor(){throw Error('provider/client blocked');}},
  FUNDING_FINDER_APP:{boundedScripts:{sidecar:{setTimeout:cb=>setTimeout(cb,1000),clearTimeout}}}});
 dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content',pack.generation);
 dom.document.getElementById('results').innerHTML='<article class="result-card"><button id="open-fixture" data-opportunity-team="fixture-scope">Build team</button></article>';
 c.fetch=async url=>{requests.push(url);assert.match(url,/^data\/team-recommender\//);const bytes=pack.files.get(url.split('?')[0]);if(!bytes)throw Error('unknown static asset');
  if(delay)await new Promise(r=>pending.push(r));return new Response(corrupt?bytes.slice(1):bytes);};
 dom.document.head=dom.document.querySelector('head');
 dom.document.head.appendChild=script=>{
  requests.push(script.src);const name=script.src.split('?')[0];assert.ok(['assets/team-recommender.js','assets/team-ingredients.js'].includes(name));
  const bytes=fs.readFileSync(name);assert.equal(script.integrity,'sha256-'+createHash('sha256').update(bytes).digest('base64'));
  vm.runInContext(bytes.toString(),c);queueMicrotask(()=>dom.dispatch('load',script));
 };
 vm.createContext(c);for(const p of ['assets/site-shell.js','assets/submission-schedule.js','assets/search-retrieval.js','docs/team-recommender/history/stage3-runtime/opportunity-team.js','assets/opportunity-team-panel.js'])vm.runInContext(read(p),c);
 const drawer=dom.document.getElementById('team-builder');
 return {dom,c,f,clock,requests,pending,drawer,pack,open:()=>dom.dispatch('click',dom.document.getElementById('open-fixture')),async ready(){const deadline=Date.now()+5000;while(Date.now()<deadline){await tick();if(drawer.querySelector('.opportunity-team-next')||drawer.querySelector('[data-opportunity-team-retry]'))return;}throw Error('fixture did not settle: '+drawer.textContent);}};
}
test('actual lazy loader and renderer: cold eight options, unconfirmed evidence, add/remove and zero provider requests',async()=>{
 const p=await panel();assert.equal(p.requests.length,0);await p.c.OpportunityTeam.loadDirectory();assert.equal(p.requests.length,0);
 p.open();await p.ready();assert.equal(p.requests.length,5);assert.equal(p.drawer.querySelectorAll('[data-opportunity-team-variant]').length,8);
 assert.match(p.drawer.textContent,/Coverage unconfirmed/);assert.doesNotMatch(p.drawer.textContent,/Direct evidence/);
 const last=p.drawer.querySelectorAll('[data-opportunity-team-variant]')[7];p.dom.dispatch('click',last);
 assert.match(p.drawer.querySelector('.opportunity-team-next a').getAttribute('href'),/proposed=/);
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-remove]'));
 const select=p.drawer.querySelector('[data-opportunity-team-replacement]');assert.equal(select.querySelectorAll('option').length,10);
 select.value=select.querySelectorAll('option')[1].getAttribute('value');p.dom.dispatch('change',select);p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-add-replacement]'));
 assert.equal(p.requests.length,5);
});
test('expiry between open and edit withdraws cached recommendations at a refreshed action clock',async()=>{
 const p=await panel();p.open();await p.ready();p.clock.now=new Date('2026-09-10T00:00:01Z').getTime();
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-remove]'));
 assert.match(p.drawer.textContent,/no longer current/);assert.equal(p.drawer.querySelector('[data-opportunity-team-remove]'),null);assert.equal(p.requests.length,5);
});
test('prepared no-group preserves individual and manual/Team Match paths without a fabricated team',async()=>{
 const p=await panel({count:1});p.open();await p.ready();assert.match(p.drawer.textContent,/Insufficient internal role coverage/);
 assert.equal(p.drawer.querySelectorAll('.opportunity-team-member').length,0);assert.ok(p.drawer.querySelector('[data-opportunity-team-replacement]'));
 assert.match(p.drawer.querySelector('.opportunity-team-next a').getAttribute('href'),/opportunity=fixture-scope/);
});
test('corrupt cold assets and retry fail safely while the directory remains available',async()=>{
 const p=await panel({corrupt:true});p.open();await p.ready();assert.match(p.drawer.textContent,/temporarily unavailable/);
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-retry]'));await p.ready();
 assert.equal((await p.c.OpportunityTeam.loadDirectory()).faculty.length,10);assert.ok(p.requests.every(url=>/^(assets\/team-|data\/team-recommender\/)/.test(url)));
});
test('package generation changes reject actions and late loads; closure keeps late results out',async()=>{
 const p=await panel();p.open();await p.ready();p.dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content','c'.repeat(64));
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-remove]'));assert.match(p.drawer.textContent,/temporarily unavailable/);
 const late=await panel({delay:true});late.open();await tick();late.drawer.close();
 for(let i=0;i<6;i++){late.pending.splice(0).forEach(r=>r());await tick();}
 assert.equal(late.drawer.querySelectorAll('.opportunity-team-panel').length,0);
});
test('a new atomic package changes identity; corrupt package cannot replace a good snapshot',async()=>{
 const f=await fixture(),a=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.manifest.source_validations});
 f.scope.scope_label+=' updated';const b=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.manifest.source_validations});assert.notEqual(a.generation,b.generation);
 f.bundle.people[0].passages[0].text='private or stale replacement';await assert.rejects(()=>buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.manifest.source_validations}),/altered claim/);
 assert.ok(a.files.get(a.index.ingredients.path));
});
