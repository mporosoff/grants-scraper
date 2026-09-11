import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import {webcrypto,createHash} from 'node:crypto';
import {shellDom} from '../helpers/shell-dom.mjs';
import {realInputs,read,NOW} from '../helpers/team-real-inputs.mjs';
const f=await realInputs(),tick=()=>new Promise(r=>setTimeout(r,0));
async function panel({sid='361207',corrupt=false,delay=false}={}){
 const dom=shellDom(read('match_explorer.html')),clock={now:Date.parse(NOW)},requests=[],pending=[];let rejectedNetwork=0;
 class DecisionDate extends Date{constructor(value){super(value??clock.now);}static now(){return clock.now;}}
 const c=dom.context;Object.assign(c,{URL,location:{href:'https://example.org/match_explorer.html'},Date:DecisionDate,TextEncoder,TextDecoder,Uint8Array,Float32Array,DataView,AbortController,clearTimeout,crypto:webcrypto,btoa,
 OPPORTUNITY_TEAM_INDEX:f.pack.index,RESEARCHER_DIRECTORY:f.directory,GRANT_CATALOG:{opportunities:Object.values(f.context.parents)},
 XMLHttpRequest:class{constructor(){rejectedNetwork++;throw Error('Unexpected network client');}},WebSocket:class{constructor(){rejectedNetwork++;throw Error('Unexpected network client');}},
 FUNDING_FINDER_APP:{boundedScripts:{sidecar:{setTimeout:cb=>setTimeout(cb,1000),clearTimeout}}}});
 dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content',f.pack.generation);
 dom.document.getElementById('results').innerHTML='<article class="result-card"><button id="open-real" data-opportunity-team="'+sid+'">Build team</button></article>';
 c.fetch=async url=>{requests.push(url);if(!/^data\/team-recommender\//.test(url)){rejectedNetwork++;throw Error('Unexpected provider or external request');}
  const bytes=f.pack.files.get(url.split('?')[0]);if(!bytes)throw Error('Missing static asset');if(delay)await new Promise(r=>pending.push(r));return new Response(corrupt?bytes.slice(1):bytes);};
 dom.document.head=dom.document.querySelector('head');dom.document.head.appendChild=script=>{
  requests.push(script.src);const name=script.src.split('?')[0];assert.ok(['assets/team-recommender.js','assets/team-ingredients.js'].includes(name));
  const bytes=fs.readFileSync(name);assert.equal(script.integrity,'sha256-'+createHash('sha256').update(bytes).digest('base64'));
  vm.runInContext(bytes.toString(),c);queueMicrotask(()=>dom.dispatch('load',script));};
 vm.createContext(c);for(const p of ['assets/site-shell.js','assets/submission-schedule.js','assets/search-retrieval.js','docs/team-recommender/history/stage3-runtime/opportunity-team.js','assets/opportunity-team-panel.js'])vm.runInContext(read(p),c);
 const drawer=dom.document.getElementById('team-builder');
 return {dom,c,clock,requests,pending,drawer,networkViolations:()=>rejectedNetwork,open:()=>dom.dispatch('click',dom.document.getElementById('open-real')),
  async ready(){const deadline=performance.now()+5000;while(performance.now()<deadline){await tick();if(drawer.querySelector('.opportunity-team-next')||drawer.querySelector('[data-opportunity-team-retry]'))return;}throw Error('Real panel did not settle: '+drawer.textContent.slice(0,300));}};
}
test('real cold/warm build, eight-option switch, remove/add, full slots and cache misses have zero paid traffic',async()=>{
 const p=await panel();assert.equal(p.requests.length,0);await p.c.OpportunityTeam.loadDirectory();assert.equal(p.requests.length,0);
 p.open();await p.ready();assert.equal(p.requests.length,5);const options=p.drawer.querySelectorAll('[data-opportunity-team-variant]');
 assert.ok(options.length>=2&&options.length<=8);assert.match(p.drawer.textContent,/Coverage unconfirmed/);assert.doesNotMatch(p.drawer.textContent,/Direct evidence/);
 p.dom.dispatch('click',options[options.length-1]);assert.match(p.drawer.querySelector('.opportunity-team-next a').getAttribute('href'),/proposed=/);
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-remove]'));
 const select=p.drawer.querySelector('[data-opportunity-team-replacement]');assert.ok(select.querySelectorAll('option').length>3);
 for(let i=0;i<3;i++){
  const current=p.drawer.querySelector('[data-opportunity-team-replacement]');if(!current)break;
  const choices=current.querySelectorAll('option');current.value=choices[1].getAttribute('value');p.dom.dispatch('change',current);
  const add=p.drawer.querySelector('[data-opportunity-team-add-replacement]');if(!add||add.disabled)break;p.dom.dispatch('click',add);
 }
 assert.equal(p.drawer.querySelectorAll('[data-opportunity-team-remove]').length,4);
 const fullAdd=p.drawer.querySelector('[data-opportunity-team-add-replacement]');assert.ok(!fullAdd||fullAdd.disabled);
 assert.equal(p.requests.length,5);assert.equal(p.networkViolations(),0);
 p.drawer.close();p.open();await p.ready();assert.equal(p.requests.length,5);
});
test('real deadline passes between open and editing; cached selection is withdrawn',async()=>{
 const p=await panel();p.open();await p.ready();p.clock.now=Date.parse('2026-09-30T12:00:00Z');
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-remove]'));
 assert.match(p.drawer.textContent,/no longer current/);assert.equal(p.requests.length,5);assert.equal(p.networkViolations(),0);
});
test('real prepared no-group retains candidate/manual path; corrupt retry never contacts providers',async()=>{
 // The exact D3 E2 snapshot returns a group for the historical PINPOINT
 // fixture. Closeout supplies its frozen mesothelioma no-group scope instead.
 const p=await panel({sid:process.env.TEAM_REAL_NO_GROUP_SCOPE||'363489'});p.open();await p.ready();assert.match(p.drawer.textContent,/Insufficient internal role coverage/);
 assert.equal(p.drawer.querySelectorAll('.opportunity-team-member').length,0);assert.ok(p.drawer.querySelector('[data-opportunity-team-replacement]'));
 const bad=await panel({corrupt:true});bad.open();await bad.ready();bad.dom.dispatch('click',bad.drawer.querySelector('[data-opportunity-team-retry]'));await bad.ready();
 assert.match(bad.drawer.textContent,/temporarily unavailable/);assert.equal(bad.networkViolations(),0);
 assert.equal((await bad.c.OpportunityTeam.loadDirectory()).faculty.length,158);
});
test('real olfactory source now has groups below the removed universal coverage cutoff',async()=>{
 const p=await panel({sid:'359696'});p.open();await p.ready();
 assert.equal(p.drawer.querySelectorAll('[data-opportunity-team-remove]').length,2);
 assert.match(p.drawer.textContent,/Benjamin L. Miller/);assert.match(p.drawer.textContent,/James M. Zavislan/);
 assert.match(p.drawer.textContent,/Coverage unconfirmed/);assert.equal(p.networkViolations(),0);
});
test('real stale generation and late responses cannot restore closed panels',async()=>{
 const p=await panel();p.open();await p.ready();p.dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content','c'.repeat(64));
 p.dom.dispatch('click',p.drawer.querySelector('[data-opportunity-team-remove]'));assert.match(p.drawer.textContent,/temporarily unavailable/);assert.equal(p.networkViolations(),0);
 const late=await panel({delay:true});late.open();await tick();late.drawer.close();
 for(let i=0;i<10;i++){late.pending.splice(0).forEach(r=>r());await tick();}
 assert.equal(late.drawer.querySelectorAll('.opportunity-team-panel').length,0);assert.equal(late.networkViolations(),0);
});
