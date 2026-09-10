import assert from 'node:assert/strict';
import test from 'node:test';
import {runtime,fixture} from '../fixtures/team-ingredients.mjs';

const row=(id,score,text,core=.7)=>({id,automatic_quality:score,edges:[{score,admitted:score>0,core,passage:{text,id:id+'-claim'}}]});
test('one max-covered aspect proves the old universal positive removal rule impossible',()=>{
 const n=runtime().TeamRecommender,rows=[row('a',.8,'peripheral auditory neurobiology'),row('b',.7,'inner ear sensory cell biophysics'),row('c',.6,'cochlear mechanics')];
 const m={weights:[1],rows,admitted:rows};
 for(const ids of [['a','b'],['a','b','c']]){
  const f=n.coverage(m,ids),marginals=ids.map(id=>f-n.coverage(m,ids.filter(x=>x!==id)));
  assert.ok(marginals.some(x=>x===0));assert.equal(marginals.every(x=>x>=.03),false);
 }
 const out=n.optimize(m);assert.deepEqual(Array.from(out.defaultIds),['a','b']);
 assert.ok(out.options.every(o=>o.ids.length===2));assert.equal(out.options.length,1);
 assert.equal(n.coverage(m,out.defaultIds)-n.coverage(m,['a']),0);
});
test('scoped duplicate evidence is rejected while unrelated and low-anchor pools stay empty',()=>{
 const n=runtime().TeamRecommender,a=row('a',.8,'organ of Corti micromechanics'),b=row('b',.8,'organ of Corti micromechanics');
 let m={weights:[1],rows:[a,b],admitted:[a,b]};assert.equal(n.optimize(m).options.length,0);
 const low=row('c',.8,'optical coherence tomography',.2);m={weights:[1],rows:[low],admitted:[low]};assert.equal(n.optimize(m).options.length,0);
 const unrelated=row('d',0,'financial accounting');m={weights:[1],rows:[a,unrelated],admitted:[a]};assert.equal(n.optimize(m).options.length,0);
});
test('existing frozen labels and summaries are context, not manufactured direct evidence',async()=>{
 const f=await fixture(),p=f.directory.researchers[0];p.research_summary='Retained original interest statement.';p.claims[0].type='Method';
 const {state,e}=await f.engine();assert.equal(e.proposalView(state).complete,false);
 assert.ok(e.proposalView(state).roles.every(r=>!r.directEvidence&&!r.filled));
 assert.equal(f.bundle.people[0].passages[0].text,p.claims[0].evidence);
 assert.equal(f.directory.researchers[0].research_summary,p.research_summary);
});
