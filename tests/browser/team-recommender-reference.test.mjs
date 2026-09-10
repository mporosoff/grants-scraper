import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {runtime,fixture} from '../fixtures/team-ingredients.mjs';
test('32 deterministic small-pool cases agree with independent Python exact optimization',()=>{
 const n=runtime().TeamRecommender;let seed=21341;const next=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return (seed%1000)/1000;};
 const cases=Array.from({length:32},()=>({group_threshold:n.PARAMETERS.group,weights:[.7,.1,.1,.1],rows:Array.from({length:8},(_,i)=>({id:String(i),anchor:i%3===0,scores:Array.from({length:4},()=>next())}))}));
 const child=spawnSync('python',['tools/team_recommender_reference.py'],{input:JSON.stringify(cases),encoding:'utf8'});assert.equal(child.status,0,child.stderr);
 const expected=JSON.parse(child.stdout);
 cases.forEach((c,i)=>{const rows=c.rows.map(r=>({id:r.id,edges:r.scores.map(score=>({score,admitted:true,core:r.anchor?.7:.1}))}));
  const got=n.optimize({weights:c.weights,rows,admitted:rows});assert.equal(got.feasibleCount,expected[i].count);assert.ok(Math.abs(got.maximum-expected[i].maximum)<1e-12);});
});
test('deliberate 2/3/4 size selection and every final marginal contribution',()=>{
 const n=runtime().TeamRecommender;
 for(let size=2;size<=4;size++){
  const weights=[.7,...Array(size-1).fill(.3/(size-1))],rows=Array.from({length:size},(_,j)=>({id:String(j),edges:weights.map((_,i)=>({score:Number(i===j),admitted:i===j,core:j===0?1:.3}))}));
  const m={weights,rows,admitted:rows},r=n.optimize(m);assert.equal(r.defaultIds.length,size);
  for(const id of r.defaultIds)assert.ok(n.coverage(m,r.defaultIds)-n.coverage(m,r.defaultIds.filter(x=>x!==id))>=.03);
 }
});
test('duplicate evidence and aspect splitting do not buy utility; matched-size A/B and MMR comparison',()=>{
 const n=runtime().TeamRecommender;
 const rows=Array.from({length:10},(_,i)=>({id:String(i),baseline:i%2===0?1:.2,edges:[0,1].map(j=>({score:i%2===j?.9:0,admitted:i%2===j,core:.7}))}));
 const m={weights:[.7,.3],rows,admitted:rows},b=n.optimize(m),a=n.baseline(m,b.defaultIds.length);
 assert.equal(a.length,b.defaultIds.length);assert.ok(n.coverage(m,b.defaultIds)>n.coverage(m,a));
 const split={weights:[.35,.35,.3],rows:rows.map(r=>({...r,edges:[r.edges[0],r.edges[0],r.edges[1]]}))};split.admitted=split.rows;
 assert.equal(n.coverage(m,b.defaultIds),n.coverage(split,b.defaultIds));
 const mmr=n.optimize(m,[],{mmr:.1});assert.deepEqual(mmr.defaultIds,b.defaultIds);assert.ok(mmr.options.every(t=>t.score>=.95*b.maximum));
});
test('155-person full-directory scoring stays within work budget and reaches everyone',async()=>{
 const f=await fixture({count:155}),{e,state}=await f.engine();const v=e.proposalView(state);
 assert.equal(v.matched_people_count,155);assert.equal(new Set([...state.selectedIds,...v.replacements.map(x=>x.profile.id)]).size,155);
 assert.equal(e.proposalOptions(state).length,8);assert.equal(e.statistics().matrices,1);
});
