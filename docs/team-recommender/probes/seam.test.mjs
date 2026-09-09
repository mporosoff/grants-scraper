// Zero-provider Stage 1 diagnostic fixtures; not the Stage 2 engine.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import {shellDom} from '../../../tests/helpers/shell-dom.mjs';
import {opportunityTeamFixture} from '../../../tests/fixtures/opportunity-team-model.mjs';
const read=p=>fs.readFileSync(p,'utf8');
const tick=()=>new Promise(r=>setTimeout(r,0));
function legacy(mutate=()=>{}){
 const f=opportunityTeamFixture();mutate(f);
 const c={OPPORTUNITY_TEAM_INDEX:f.index,OPPORTUNITY_TEAM_DATA:f.data,RESEARCHER_DIRECTORY:f.directory};
 vm.createContext(c);vm.runInContext(read('assets/opportunity-team.js'),c);
 return {...f,api:c.OpportunityTeam};
}
test('v1 rejects prepared/no-group members; this is a recorded migration boundary',()=>{
 const x=legacy(f=>{f.data.opportunities[0].members=[];});
 assert.throws(()=>x.api.create(x.data),/role model is invalid/);
});
test('v1 suppresses adjacent/gap candidates despite an available slot',()=>{
 const x=legacy(f=>{f.data.opportunities[0].roles.forEach(r=>r.coverage='adjacent');});
 const engine=x.api.create(x.data),state={opportunityId:x.data.opportunities[0].id,selectedIds:['fixture-alpha'],excludedIds:[]};
 assert.equal(engine.proposalView(state).replacements.length,0);
});
test('v1 suppresses candidates when every modeled role is filled',()=>{
 const x=legacy(f=>{f.data.opportunities[0].roles=f.data.opportunities[0].roles.slice(0,1);});
 const engine=x.api.create(x.data),state={opportunityId:x.data.opportunities[0].id,selectedIds:['fixture-alpha'],excludedIds:[]};
 assert.equal(engine.proposalView(state).complete,true);
 assert.equal(engine.proposalView(state).replacements.length,0);
});
test('v1 limits an otherwise feasible option pool to three and enforces four slots',()=>{
 const x=legacy(f=>{const o=f.data.opportunities[0];o.roles=o.roles.slice(0,1);o.roles[0].candidate_ids=f.directory.researchers.map(r=>r.id);o.variants=[['fixture-alpha','fixture-beta'],['fixture-alpha','fixture-gamma'],['fixture-alpha','fixture-delta'],['fixture-alpha','fixture-alternative']].map(member_ids=>({member_ids}));});
 const e=x.api.create(x.data),s=e.proposal(x.data.opportunities[0]);
 assert.equal(e.proposalOptions(s).length,3);assert.throws(()=>e.addReplacement(s,'fixture-alternative'),/not eligible/);
});
async function render({count=2,confirmed=false,transfer=false,options=0,allCovered=false,failLoad=false}={}){
 const dom=shellDom(read('match_explorer.html'));let paidAttempts=0,loads=0;
 const profiles=Array.from({length:10},(_,i)=>({id:'person-'+i,name:'Fixture person '+i,home_unit:'Fixture unit',source_url:'https://example.org/profile/'+i,source_checked_date:'2026-09-01'}));
 const opportunity={id:'scope-fixture',parent_id:'scope-fixture',record_type:'specific_parent',scope_label:'Scientific fixture',objective:'Measure a specified signal.',gate_state:count===0?'fail':confirmed?'pass':'conditional',members:profiles.slice(0,count).map(p=>({faculty_id:p.id})),why_team:count?'Source-backed possible contributors; exact application remains unconfirmed.':'No adequate two-person group meets the scientific contribution floors.',missing_skills:[]};
 const state={opportunityId:opportunity.id,selectedIds:profiles.slice(0,count).map(p=>p.id),excludedIds:[]};
 const engine={facultyById:new Map(profiles.map(p=>[p.id,p])),opportunityById:new Map([[opportunity.id,opportunity]]),scopesFor:()=>[opportunity],resolveScope:()=>({ok:true,opportunity}),proposal:()=>state,
  proposalView(s){const filled=confirmed||allCovered;const role={id:'aspect',label:'Signal measurement',source_url:'https://example.org/call',rationale:'Source-defined contribution; no facility claim.',required:true,coverage:filled?'direct':'adjacent',filled,directEvidence:confirmed&&!transfer,selected_candidate_ids:filled?s.selectedIds:[],selected_alternative_ids:filled?[]:s.selectedIds};return {opportunity,selectedIds:s.selectedIds,excludedIds:s.excludedIds,complete:filled,roles:[role],unfilledRoles:filled?[]:[role],selected:s.selectedIds.map(id=>({profile:this.facultyById.get(id),roles:[role],evidence:{why_person:'A possible method transfer; application is unconfirmed.',evidence_term:'Synthetic public passage',evidence_phrase:'We measure optical signals.',contribution:'Discuss signal measurement',source_url:'https://example.org/profile'},relevantTerms:[]})),replacements:profiles.filter(p=>!s.selectedIds.includes(p.id)).map(profile=>({profile,roles:[role],reviewed:false,previouslySelected:s.excludedIds.includes(profile.id)}))};},
  proposalOptions(s){return Array.from({length:options},(_,i)=>({state:{...s,selectedIds:[profiles[i].id,profiles[i+1].id]},label:'Fixture alternative '+i}));},
  removeMember(s,id){return {...s,selectedIds:s.selectedIds.filter(x=>x!==id),excludedIds:[...s.excludedIds,id]};},
  addReplacement(s,id){assert.ok(s.selectedIds.length<4);return {...s,selectedIds:[...s.selectedIds,id],excludedIds:s.excludedIds.filter(x=>x!==id)};}};
 dom.document.getElementById('results').innerHTML='<article class="result-card"><button id="fixture-open" data-opportunity-team="scope-fixture">Build team</button></article>';
 Object.assign(dom.context,{URL,location:{href:'https://example.org/match_explorer.html'},fetch:()=>{paidAttempts++;throw new Error('all external requests forbidden');},XMLHttpRequest:class{constructor(){paidAttempts++;throw new Error('forbidden');}},WebSocket:class{constructor(){paidAttempts++;throw new Error('forbidden');}},GRANT_CATALOG:{opportunities:[{opportunity_id:opportunity.id}]},OpportunityTeam:{pageGenerationId:()=> 'a'.repeat(64),loadData:async()=>{loads++;if(failLoad)throw new Error('fixture unavailable');return {};},create:()=>engine}});
 vm.createContext(dom.context);vm.runInContext(read('assets/site-shell.js'),dom.context);vm.runInContext(read('assets/opportunity-team-panel.js'),dom.context);
 assert.equal(loads,0,'ordinary startup does not load ingredients');
 dom.dispatch('click',dom.document.getElementById('fixture-open'));await tick();
 return {dom,drawer:dom.document.getElementById('team-builder'),paid:()=>paidAttempts,loads:()=>loads};
}
test('unchanged renderer truthfully distinguishes direct, method transfer, unconfirmed, and empty group',async()=>{
 for(const [args,label] of [[{confirmed:true},'Direct evidence'],[{confirmed:true,transfer:true},'Supported by method transfer'],[{},'Coverage unconfirmed'],[{count:0},'Insufficient internal role coverage']]){
  const {drawer,paid}=await render(args);assert.match(drawer.textContent,new RegExp(label));
  if(!args.confirmed)assert.doesNotMatch(drawer.textContent,/Direct evidence/);
  assert.equal(drawer.querySelectorAll('.opportunity-team-member').length,args.count??2);assert.equal(paid(),0);
 }
});
test('eight buttons render and clicked index resolves the same displayed member IDs',async()=>{
 const {dom,drawer,paid}=await render({options:8});const buttons=drawer.querySelectorAll('[data-opportunity-team-variant]');assert.equal(buttons.length,8);
 dom.dispatch('click',buttons[7]);const href=drawer.querySelector('.opportunity-team-next a').getAttribute('href');assert.match(href,/proposed=person-7%2Cperson-8/);assert.equal(paid(),0);
});
test('all modeled roles supported still allows every other admitted person through the existing dropdown',async()=>{
 const {dom,drawer}=await render({allCovered:true});const select=drawer.querySelector('[data-opportunity-team-replacement]');assert.equal(select.querySelectorAll('option').length,9);
 select.value='person-9';dom.dispatch('change',select);dom.dispatch('click',drawer.querySelector('[data-opportunity-team-add-replacement]'));assert.match(drawer.textContent,/Fixture person 9/);
});
test('four occupied slots hide additions; removal exposes all seven other IDs including restore',async()=>{
 const {dom,drawer,paid}=await render({count:4});assert.equal(drawer.querySelector('[data-opportunity-team-replacement]'),null);
 dom.dispatch('click',drawer.querySelector('[data-opportunity-team-remove]'));const select=drawer.querySelector('[data-opportunity-team-replacement]');assert.equal(select.querySelectorAll('option').length,8);assert.match(select.textContent,/Previously selected/);assert.equal(paid(),0);
});
test('zero members retains individual additions and handoff; failures and retry invoke no providers',async()=>{
 const x=await render({count:0});assert.ok(x.drawer.querySelector('[data-opportunity-team-replacement]'));assert.match(x.drawer.querySelector('.opportunity-team-next a').getAttribute('href'),/opportunity=scope-fixture/);
 const y=await render({failLoad:true});y.dom.dispatch('click',y.drawer.querySelector('[data-opportunity-team-retry]'));await tick();assert.equal(y.loads(),2);assert.equal(y.paid(),0);
});
test('record currentness conflict: legacy proposal actions never consult a clock',()=>{
 const x=legacy();const e=x.api.create(x.data);const s=e.proposal(x.data.opportunities[0]);assert.ok(e.proposalView(e.removeMember(s,s.selectedIds[0])));
 assert.match(read('assets/opportunity-team-panel.js'),/now: current\.now/);
 // Diagnostic only. Action-time enforcement and its error boundary remain Stage 2.
});
