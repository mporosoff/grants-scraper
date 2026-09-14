import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
import {researcherDocument,assessmentPerson,balancedShortlist,loadCanonicalInputs,resolveCanonicalScope,hash} from '../../tools/contextual_team_inputs.mjs';
const ctx=vm.createContext({URL,fetch:()=>{throw Error('provider/network forbidden');}});
vm.runInContext(fs.readFileSync('assets/contextual-team-engine.js','utf8'),ctx);
const api=ctx.ContextualTeamEngine,H='a'.repeat(64);
const person=(id,evidence='Measures a distinct material property '+id)=>({id,name:id,status:'active',auto_proposable:true,pool_state:'main',pool_visibility:'institution',
 research_summary:'Research summary '+id,summary_evidence:[{form:'paraphrase'}],claims:[{claim_id:id+'-c1',revision:1,status:'active',label:'Material measurement',evidence,type:'Method',evidence_level:'direct',source_urls:['https://example.edu/'+id],evidence_records:[{form:'paraphrase'}]}]});
function fixture(n=4){
 const directory={registry_generation:H,researchers:Array.from({length:n},(_,i)=>person('p'+i))};
 const graph={version:'contextual-audited-graph-v1',graph_id:H,snapshot_id:H,registry_generation:H,source_id:H,roster_id:H,state:'ready',
  scope:{id:'call',parent_id:'call',source_url:'https://example.gov/call'},objective:'Investigate material properties',
  roles:[{id:'role-1',label:'Measure materials',required:true,central:true},{id:'role-2',label:'Model response',required:false,central:false}],
  people:directory.researchers.slice(0,3).map(p=>({person_id:p.id,outcome:'supported'})),edges:directory.researchers.slice(0,3).map((p,i)=>({person_id:p.id,role_id:i===2?'role-2':'role-1',claim_id:p.id+'-c1',claim_revision:1,coverage:'direct',central:i!==2,evidence_quote:p.claims[0].evidence,reason:'Contribute the documented measurement.',gap:'Application transfer remains unconfirmed.'}))};
 const expected={...Object.fromEntries(['graph_id','snapshot_id','registry_generation','source_id','roster_id'].map(k=>[k,H])),scope_id:'call',parent_id:'call',directory_content:api.canonical(directory.researchers)};
 const record={id:'call',close:'2026-09-13'},parentRecord=record;
 let now=new Date('2026-09-12T16:00:00Z'),current={directory,record,parentRecord};
 return {directory,graph,expected,record,parentRecord,setDate:v=>now=new Date(v),replace:v=>{current=v;},
  engine:()=>api.create(graph,directory,expected,{record,parentRecord,clock:()=>now,currentness:(r,d)=>d<new Date(r.close),currentSnapshot:()=>current})};
}
test('complete audited text, no administrative relevance, exact row identity',()=>{
 const p=person('p');p.claims.push({...p.claims[0],claim_id:'duplicate'});
 const d=researcherDocument(p);assert.equal(d.text.split(p.claims[0].evidence).length,2);
 assert.equal(assessmentPerson(d).claims.length,2);assert.deepEqual(assessmentPerson(d).claims[0].forms,['paraphrase']);
 const renamed=researcherDocument({...p,name:'Changed',home_unit:'Prestigious department'});assert.equal(renamed.input_id,d.input_id);
 const changed=researcherDocument({...p,research_summary:p.research_summary+' A new supported direction.'});assert.notEqual(changed.input_id,d.input_id);
 p.claims[0].status='retired';assert.equal(assessmentPerson(researcherDocument(p)).claims.length,1);
});
test('balanced per-contribution retrieval is deterministic and bounded',()=>{
 const rankings=Array.from({length:6},(_,i)=>Array.from({length:20},(_,j)=>({id:i+'-'+j,score:20-j})));
 const result=balancedShortlist(rankings);assert.equal(result.selected.length,12);
 for(let i=0;i<6;i++)assert.equal(result.selected.filter(id=>id.startsWith(i+'-')).length,2);
 assert.equal(result.omitted.length,60);assert.equal(hash(result),hash(balancedShortlist(rankings)));
 assert.equal(balancedShortlist([[{id:'z',score:1},{id:'a',score:1}]]).selected[0],'a');
});
test('real registry projection and native child ownership remain exact',()=>{
 const i=loadCanonicalInputs();assert.equal(i.directory.registry_generation,'60169651eaff43c75e0eccd12167371d8131b76ed67592eaed18d3689d188126');
 const s=resolveCanonicalScope(i,'344592:ab-0025','2026-09-12T16:00:00Z');assert.equal(s.parent_id,'344592');
 assert.equal(s.science.source_document_hash,'c9ab5dd5a95c0f40f68fa4af8b4600c4534e26a15f09a16662e53fb795ba8b24');
 assert.equal(s.science.description,i.children.opportunities.find(r=>r.opportunity_id===s.id).description);
 assert.equal(resolveCanonicalScope(i,'344592','2026-09-12T16:00:00Z').state,'needs_scope_selection');
 assert.equal(resolveCanonicalScope(i,'missing','2026-09-12T16:00:00Z').state,'unmapped');
});
test('two independently useful overlapping contributors allowed; third needs contribution',()=>{
 const f=fixture(),e=f.engine(),state=e.proposal();assert.equal(state.selectedIds.length,2);
 const options=e.proposalOptions(state);assert.equal(options.length,2);assert.ok(options.every(o=>o.state.selectedIds.includes('p2')));
 assert.deepEqual(e.proposalOptions(state),options);assert.ok(e.statistics().cache_hits>0);
 const g=fixture();g.graph.edges=g.graph.edges.slice(0,2);g.graph.people=g.graph.people.slice(0,2);assert.equal(g.engine().proposal().selectedIds.length,2);
});
test('adjacency cannot become automatic coverage; all people remain manually reachable',()=>{
 const f=fixture();f.graph.edges.forEach(e=>{e.coverage='adjacent';e.central=false;});const e=f.engine();let state=e.proposal();
 assert.equal(state.selectedIds.length,0);assert.equal(e.proposalView(state).replacements.length,4);
 assert.equal(e.proposalView(state).opportunity.gate_state,'fail');
 state=e.addReplacement(state,'p3');assert.match(e.proposalView(state).selected[0].evidence.why_person,/not been contextually assessed/);
 assert.equal(e.proposalView(state).opportunity.gate_state,'fail');assert.equal(e.statistics().provider_calls,0);
});
test('edits, exclusions, full slots and re-add use no transport',()=>{
 const f=fixture(5),e=f.engine();let state=e.proposal();assert.equal(e.proposalView(state).opportunity.gate_state,'conditional');
 const id=state.selectedIds[0];state=e.removeMember(state,id);assert.equal(e.proposalView(state).opportunity.gate_state,'fail');
 assert.ok(e.proposalOptions(state).every(o=>!o.state.selectedIds.includes(id)));state=e.addReplacement(state,id);
 for(const p of ['p3','p4'])state=e.addReplacement(state,p);assert.equal(state.selectedIds.length,4);
 assert.throws(()=>e.addReplacement(state,'p2'),/invalid_addition/);assert.equal(e.proposalView(state).complete,false);
 assert.ok(e.proposalView(state).roles.every(r=>!r.directEvidence&&!r.filled));assert.equal(e.statistics().provider_calls,0);
});
test('no anchor, duplicate evidence, stale graph and retired claims fail honestly',()=>{
 const f=fixture();f.graph.edges.forEach(e=>{e.central=false;});assert.equal(f.engine().proposal().selectedIds.length,0);
 const g=fixture();g.graph.edges[0].claim_revision=2;assert.throws(()=>g.engine(),/retired_or_changed_evidence/);
 const h=fixture();h.expected.graph_id='b'.repeat(64);assert.throws(()=>h.engine(),/graph_identity_conflict/);
 const j=fixture();j.graph.state='failed';assert.throws(()=>j.engine(),/graph_not_ready/);
});
test('fresh action clock and entire roster replacement invalidate cached selections',()=>{
 const f=fixture(),e=f.engine(),state=e.proposal();f.setDate('2026-09-14T00:00:00Z');assert.throws(()=>e.removeMember(state,state.selectedIds[0]),/not_current/);
 const g=fixture(),engine=g.engine(),old=engine.proposal();g.replace({directory:{...g.directory,registry_generation:'b'.repeat(64)},record:g.record,parentRecord:g.parentRecord});
 assert.throws(()=>engine.proposalView(old),/source_or_profile_pool_changed/);
});
test('one action shares one clock',()=>{
 const f=fixture(),e=f.engine();e.runAction({parentId:'call',now:'2026-09-12T16:00:00Z'},result=>{
  assert.equal(result.ok,true);f.setDate('2026-09-14T00:00:00Z');const state=e.proposal();assert.ok(e.proposalView(state));
 });assert.throws(()=>e.proposal(),/not_current/);
});
function selectedApproachFixture(){
 const f=fixture();f.graph.version='contextual-audited-graph-v2';
 f.graph.requirement_policy='contextual-selected-approach-v2';f.graph.approach='Laboratory measurement of the documented materials';
 f.graph.roles.forEach(r=>Object.assign(r,{kind:'approach_necessary',applicability:'applies',condition:'',required:true}));
 return f;
}
test('optional directions are not gaps, complementary rewards or admission evidence',()=>{
 const f=selectedApproachFixture();Object.assign(f.graph.roles[1],{kind:'optional_direction',required:false});
 assert.throws(()=>f.engine(),/inactive_direction_has_relationship/);
 f.graph.edges=f.graph.edges.filter(e=>e.role_id==='role-1');
 const e=f.engine(),s=e.proposal(),v=e.proposalView(s);
 assert.deepEqual(Array.from(s.selectedIds),['p0','p1']);assert.equal(v.roles.length,1);
 assert.equal(v.unfilledRoles.length,0);assert.equal(v.opportunity.missing_skills.length,0);
 assert.equal(v.replacements.find(r=>r.profile.id==='p2').assessment_state,'assessed_uncertain');
 assert.match(v.opportunity.why_team,/Selected scientific approach/);assert.equal(e.statistics().provider_calls,0);
});
test('applicable conjunctions and nonexclusive methods retain genuine gaps',()=>{
 const f=selectedApproachFixture();f.graph.roles[1].kind='sponsor_requirement';
 f.graph.edges=f.graph.edges.filter(e=>e.role_id==='role-1');const e=f.engine(),v=e.proposalView(e.proposal());
 assert.equal(v.unfilledRoles.length,1);assert.deepEqual(Array.from(v.opportunity.missing_skills),['Model response']);
 assert.match(v.roles[1].rationale,/Model-interpreted scientific source constraint/);
});
test('conditional requirements cannot be silently upgraded or waive unknown context',()=>{
 const f=selectedApproachFixture();Object.assign(f.graph.roles[1],{kind:'sponsor_requirement',applicability:'unknown',condition:'Only if an unresolved source condition applies.',required:false});
 f.graph.edges=f.graph.edges.filter(e=>e.role_id==='role-1');f.graph.limitations=['Source condition remains unresolved.'];
 const e=f.engine();assert.match(e.proposalView(e.proposal()).opportunity.why_team,/remains unresolved/);
 const g=selectedApproachFixture();g.graph.roles[1].required=false;assert.throws(()=>g.engine(),/derived_requirement_conflict/);
});
test('eight useful distinct options are capped without hiding other assessed candidates',()=>{
 const f=fixture(10);f.graph.people=f.directory.researchers.slice(0,8).map(p=>({person_id:p.id,outcome:'supported'}));
 f.graph.edges=f.directory.researchers.slice(0,8).map((p,i)=>({...f.graph.edges[0],person_id:p.id,claim_id:p.id+'-c1',
  evidence_quote:p.claims[0].evidence,role_id:i<4?'role-1':'role-2',central:i<4}));
 const e=f.engine(),s=e.proposal(),options=e.proposalOptions(s);
 assert.equal(options.length,8);assert.equal(new Set(options.map(o=>o.id)).size,8);
 assert.equal(e.proposalView(s).matched_people_count,8);assert.equal(e.proposalView(s).replacements.length,8);
 assert.ok(e.proposalView(s).replacements.some(r=>r.profile.id==='p9'&&r.assessment_state==='unassessed'));
});
test('exact duplicated evidence does not pad two people',()=>{
 const f=fixture(2);f.directory.researchers[1].claims[0].evidence=f.directory.researchers[0].claims[0].evidence;
 f.graph.edges[1].evidence_quote=f.graph.edges[0].evidence_quote;
 f.expected.directory_content=api.canonical(f.directory.researchers);assert.equal(f.engine().proposal().selectedIds.length,0);
});
