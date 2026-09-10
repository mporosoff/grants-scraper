import assert from 'node:assert/strict';
import test from 'node:test';
import {realInputs,engine,action,runtime,NOW,ROOT} from '../helpers/team-real-inputs.mjs';
import {buildPackage} from '../../tools/build_team_ingredients.mjs';

const inputs=await realInputs();
const build=f=>buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations});
test('real 90-source snapshot, 155 people and exact versioned vectors hydrate without startup calculation',async()=>{
 const {e}=await engine(inputs);assert.equal(inputs.bundle.people.length,155);assert.equal(e.data.faculty.length,158);
 assert.equal(inputs.bundle.vector_rows.length,ROOT.endsWith('/d1')?493:526);assert.equal(inputs.bundle.scopes.length,90);
 assert.equal(inputs.bundle.scopes.filter(s=>s.prepared).length,ROOT.endsWith('/d1')?35:34);
 assert.equal(e.statistics().matrices,0);assert.equal(e.statistics().optimizations,0);
});
test('every real actionable prepared scope preserves reachability, unconfirmed evidence and stable options',async()=>{
 const {e}=await engine(inputs);let prepared=0,blocked=0;
 for(const scope of inputs.bundle.scopes){
  const outcome=e.resolveScope(action(inputs,scope.id));
  if(!outcome.ok){blocked++;continue;}
  assert.equal(scope.prepared,true);prepared++;
  const state=e.proposal(outcome.opportunity),v=e.proposalView(state),options=e.proposalOptions(state);
  assert.equal(new Set([...state.selectedIds,...v.replacements.map(r=>r.profile.id)]).size,v.matched_people_count);
  assert.ok(options.length<=8);assert.equal(JSON.stringify(options),JSON.stringify(e.proposalOptions(state)));
  assert.ok(v.roles.every(r=>!r.directEvidence&&!r.filled));assert.equal(v.complete,false);
  for(const m of v.selected)assert.ok(m.evidence?.evidence_phrase&&m.evidence?.source_url);
  if(v.replacements.length){const added=e.addReplacement(state,v.replacements[0].profile.id);assert.ok(added.selectedIds.includes(v.replacements[0].profile.id));}
 }
 assert.equal(prepared+blocked,90);assert.ok(prepared>=20);assert.ok(blocked>=inputs.bundle.scopes.filter(s=>!s.prepared).length);
 assert.ok(e.statistics().matricesCached<=8&&e.statistics().optionsCached<=32&&e.statistics().rowsCached<=1600);
});
test('real forecast, rolling, child ownership and successive action clocks use the authoritative policy',async()=>{
 const {e,c}=await engine(inputs);
 const a=action(inputs,'361207');assert.equal(a.record.status,'forecasted');assert.equal(e.resolveScope(a).ok,true);
 const s=e.proposal(e.opportunityById.get('361207'));
 assert.equal(e.resolveScope({...a,now:'2026-09-30T12:00:00Z'}).ok,false);
 assert.throws(()=>e.proposalView(s),/Stale|current/);
 assert.equal(e.resolveScope(a).ok,true);
 assert.equal(e.resolveScope({...a,record:{...a.record,close_date:'2026-09-09'}}).reason,'not_current');
 const rolling=inputs.bundle.scopes.find(s=>s.prepared&&inputs.context.parents[s.parent_id]?.rolling&&c.TeamIngredients.current(inputs.context.parents[s.parent_id],new Date(NOW)).ok);
 assert.ok(rolling);assert.equal(e.resolveScope(action(inputs,rolling.id)).ok,true);
 const child=action(inputs,'344592:ab-0009');assert.equal(e.resolveScope(child).ok,true);
 assert.equal(e.resolveScope({...child,parentId:'345241'}).ok,false);
 assert.equal(e.resolveScope({...child,childCatalog:{opportunities:child.childCatalog.opportunities.filter(r=>r.subtopic_id!=='344592:ab-0009')}}).ok,false);
 assert.equal(e.resolveScope({...child,record:{...child.record,status:'withdrawn'}}).ok,false);
});
test('real source, profile and vector mutations never inherit trusted readiness',async()=>{
 for(const mutate of [
  f=>{f.bundle.people[0].passages[0].text+=' unsupported expertise';},
  f=>{f.directory.researchers[0].claims[0].status='retired';},
  f=>{f.bundle.space.roles.passage='query';},
  f=>{f.bundle.sources.find(s=>s.id==='344592:ab-0009').parent_id='345241';},
  f=>{f.bundle.scopes.find(s=>s.prepared).aspects[0].text+=' fabricated requirement';},
  f=>{f.bundle.scopes[1].prepared=true;},
  f=>{f.bundle.people[0].passages.push({...f.bundle.people[0].passages[0]});},
  f=>{f.bundle.registry_generation='0'.repeat(64);}
 ]){const f=structuredClone({...inputs,pack:undefined});mutate(f);await assert.rejects(()=>build(f));}
});
test('real best-pair regression uses independent pair enumeration over the full admitted directory',()=>{
 const c=runtime();const n=c.TeamRecommender;
 const scope=inputs.bundle.scopes.find(s=>s.id==='361207');
 const vectors=inputs.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,k)=>inputs.bytes.readFloatLE((i*1024+k)*4)));
 const m=n.matrix(scope,inputs.bundle.people,vectors);const got=n.optimize(m);
 // Use the shipped candidate's fixed thresholds, not a presumed winning team.
 const feasible=[];for(let i=0;i<m.admitted.length;i++)for(let j=i+1;j<m.admitted.length;j++){
  const rows=[m.admitted[i],m.admitted[j]],scores=m.weights.map((w,k)=>w*Math.max(rows[0].edges[k].score,rows[1].edges[k].score));
  const value=scores.reduce((a,b)=>a+b,0),single=rows.map(r=>m.weights.reduce((v,w,k)=>v+w*r.edges[k].score,0));
  if(rows.some(r=>r.edges.some(e=>e.admitted&&e.core>=n.PARAMETERS.anchor))&&n.quantize(value)>=n.quantize(n.PARAMETERS.group)&&rows.every(r=>r.edges.some(e=>e.admitted&&e.score>0))&&!n.redundantEvidence(...rows))feasible.push(value);
 }
 if(feasible.length)assert.ok(got.maximum>=Math.max(...feasible)-1e-12);
 assert.ok(got.examinedCoverage<=n.PARAMETERS.workLimit);
});
