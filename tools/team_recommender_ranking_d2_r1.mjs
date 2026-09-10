import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {representationEngine} from './team_recommender_ranking_d2_representation.mjs';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),root='outputs/team-recommender-d2',n=representationEngine();
const bundle=read(root+'/assembled-r1/bundle.json'),bytes=fs.readFileSync(root+'/assembled-r1/vectors.f32');
const vectors=bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>bytes.readFloatLE(i*4096+j*4)));
const old=read(root+'/D1-reproduction.json'),scopes=[];
for(const scope of bundle.scopes){
 if(!scope.prepared){scopes.push({id:scope.id,status:'unprepared'});continue;}
 const m=n.matrix(scope,bundle.people,vectors),prior=old.scopes.find(s=>s.id===scope.id);
 assert.equal(JSON.stringify(m.admitted.map(r=>r.id)),JSON.stringify(prior.admitted));
 for(const row of m.rows){
  const person=bundle.people.find(p=>p.id===row.id);
  const best=m.aspects.map(aspect=>person.passages.map(p=>n.edge(aspect,scope.core,p,vectors,person.summary_vector))
   .sort((a,b)=>b.features[0]-a.features[0]||b.features[1]-a.features[1]||n.cmp(a.passage.id,b.passage.id))[0]);
  const chosen=best.slice().sort((a,b)=>b.features[0]-a.features[0]||b.features[1]-a.features[1]||n.cmp(a.passage.id,b.passage.id))[0];
  const two=best.map(e=>e.features[0]).sort((a,b)=>b-a).slice(0,2),whole=Math.max(...person.passages.map(p=>n.contextualDot(scope.whole_call,p,vectors,person.summary_vector)));
  row.call_features=[chosen.features[0],chosen.features[1],chosen.features[4],whole,two.reduce((a,b)=>a+b,0)/two.length];
  row.automatic_quality=.7*row.call_features[0]+.3*whole;
 }
 const B=n.optimize(m),rank=m.admitted.slice().sort((a,b)=>n.quantize(Math.max(...b.edges.map(e=>e.score)))-n.quantize(Math.max(...a.edges.map(e=>e.score)))||n.cmp(a.id,b.id));
 scopes.push({id:scope.id,status:B.options.length?'group':'no-group',aspects:m.aspects,weights:m.weights,rows:m.rows,admitted:m.admitted.map(r=>r.id),B,B5:rank.slice(0,5).map(r=>r.id),A:n.baseline(m,B.defaultIds.length||2),A5:n.baseline(m,5)});
}
const path=root+'/R1-D1-selection.json';assert(!fs.existsSync(path));fs.writeFileSync(path,JSON.stringify({representation:'R1',selection:'unchanged D1',provider_calls:0,holdout_scored:false,scopes})+'\n');
console.log(JSON.stringify({path,sha256:createHash('sha256').update(fs.readFileSync(path)).digest('hex'),groups:scopes.filter(s=>s.status==='group').map(s=>s.id),options:scopes.reduce((a,s)=>a+(s.B?.options.length||0),0)}));
