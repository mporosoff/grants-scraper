import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {runtime,fixture} from '../fixtures/team-ingredients.mjs';
import {representationEngine} from '../../tools/team_recommender_ranking_d2_representation.mjs';
const row=(id,score,quality,core=.6)=>({id,automatic_quality:quality,edges:[{score,core,admitted:true,passage:{text:id+'laboratory specific retained technique'}}]});
test('absolute member quality prevents strong-member carrying without hiding accessible candidates',()=>{
 const n=runtime().TeamRecommender,rows=[row('anchor',.44,.65),row('reasonable',.42,.63),row('weak',.9,.499)];
 const m={rows,admitted:rows,weights:[1]},out=n.optimize(m);
 assert.deepEqual(Array.from(out.defaultIds),['anchor','reasonable']);assert.equal(out.maximum,.44);
 assert.equal(m.admitted.length,3);assert.ok(out.options.every(t=>!t.ids.includes('weak')));
 assert.equal(n.coverage(m,out.defaultIds)-n.coverage(m,['anchor']),0);
 for(const r of rows)r.automatic_quality=.49;assert.equal(n.optimize(m).options.length,0);
});
test('near-best member quality matters beyond exact coverage ties and weak alternatives are not padded',()=>{
 const n=runtime().TeamRecommender,rows=[row('a',.9,.7),row('b',.87,.8),row('c',.86,.79),row('d',.88,.51)];
 const m={rows,admitted:rows,weights:[1]},out=n.optimize(m);
 assert.deepEqual(Array.from(out.defaultIds),['b','c']);assert.equal(out.options.length,1);
 assert.deepEqual(n.optimize(m,[],{mmr:.1}),out);
});
test('context is capped, cannot admit unsupported evidence, and missing summaries have one explicit rule',()=>{
 const n=representationEngine(),v=[[1,0],[.35,Math.sqrt(1-.35**2)],[1,0]],a={text:'optical spectroscopy',vector:0},core={vector:0};
 const p={id:'p',text:'financial accounting',vector:1,context_vector:2};
 assert.equal(n.edge(a,core,p,v,2).admitted,false);
 assert.ok(n.contextualDot(a,p,v,2)<=.4);assert.ok(n.contextualDot(a,p,v,undefined)<=.4);
 const noSummary={...p,vector:0};assert.ok(Math.abs(n.contextualDot(a,noSummary,v,undefined)-1)<1e-12);
 assert.equal(n.edge(a,core,{...p,text:'innovative research methods',vector:0},v,2).admitted,false);
});
test('frozen researcher directory and all D1 evidence hashes remain unchanged',()=>{
 const hash=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
 assert.equal(hash('docs/team-recommender/prepared/d1/directory.json'),'3803171442db49e888bed3a4b8c42385e4015aa4c569b92cd9c79615fd54e53a');
 assert.equal(hash('docs/team-recommender/prepared/d1/vectors.f32'),'cbc5788875e257e3a64030826623a1ec743e37b4667dfd1f0afe2863fb6c9d90');
 assert.equal(hash('docs/team-recommender/history/stage3-runtime/researcher_directory.js'),'93b95b1f5e0656fa527c313f3ae40ccfc244e73b92f20e5e870cbe570f82da69');
});
test('generic or repeated extra profile text cannot purchase automatic quality',()=>{
 const n=runtime().TeamRecommender,v=[[1,0],[.42,Math.sqrt(1-.42**2)]],a={id:'a',text:'optical spectroscopy',vector:0,weight:1};
 const s={aspects:[a],core:{vector:0},whole_call:{vector:0}},p={id:'p',passages:[{id:'evidence',text:'optical spectroscopy',vector:1}]};
 const before=n.matrix(s,[p],v).rows[0].automatic_quality;
 p.passages.push({id:'generic',text:'innovative research methods '.repeat(20),vector:0});
 assert.equal(n.matrix(s,[p],v).rows[0].automatic_quality,before);
 p.passages.push({...p.passages[0],id:'duplicate'});assert.equal(n.matrix(s,[p],v).rows[0].automatic_quality,before);
});
test('selected scorer does not promote existing summary or registry labels into confirmed roles',async()=>{
 const f=await fixture(),{e,state}=await f.engine(),v=e.proposalView(state);
 assert.equal(v.complete,false);assert.ok(v.roles.every(r=>!r.directEvidence&&!r.filled));
 assert.equal(e.proposalOptions(state).length,8);
 const removed=e.removeMember(state,state.selectedIds[0]);assert.ok(e.proposalOptions(removed).every(o=>!o.state.selectedIds.includes(state.selectedIds[0])));
});
