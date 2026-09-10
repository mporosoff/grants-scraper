/* D2 read-only numerical diagnosis of the exact D1 snapshot. No providers. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const root='docs/team-recommender',out='outputs/team-recommender-d2';
const bundle=read(root+'/prepared/d1/bundle.json'),bytes=fs.readFileSync(root+'/prepared/d1/vectors.f32');
const source=fs.readFileSync('assets/team-recommender.js','utf8');
assert.equal(createHash('sha256').update(source).digest('hex'),'4db90706d6ce347877dd77dd99d453b8cb7bca9d30a2b6730d828603fde6c1ce');
const ctx={};vm.createContext(ctx);vm.runInContext(source,ctx);const n=ctx.TeamRecommender;
const vectors=bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>bytes.readFloatLE(i*4096+j*4)));
const old=read('outputs/team-recommender-d1/controlled-v1.json').results.find(r=>r.id==='combined');
const dev=new Set(read(root+'/manifests/development.json').scopes.map(s=>s.id));
assert.equal(bundle.scopes.length,90);assert(bundle.scopes.every(s=>dev.has(s.id)));
const rows=[];
for(const scope of bundle.scopes){
 if(!scope.prepared){rows.push({id:scope.id,status:'unprepared'});continue;}
 const matrix=n.matrix(scope,bundle.people,vectors),result=n.optimize(matrix),prior=old.scopes.find(s=>s.id===scope.id);
 assert.equal(JSON.stringify(result),JSON.stringify(prior.B));
 const ranked=matrix.admitted.slice().sort((a,b)=>n.quantize(Math.max(...b.edges.map(e=>e.score)))-n.quantize(Math.max(...a.edges.map(e=>e.score)))||n.cmp(a.id,b.id));
 assert.equal(JSON.stringify(ranked.slice(0,5).map(r=>r.id)),JSON.stringify(prior.B5));
 const raw=matrix.rows.map(row=>{
   const person=bundle.people.find(p=>p.id===row.id);
   const aspectFeatures=matrix.aspects.map(a=>person.passages.map(p=>{
    const e=n.edge(a,scope.core,p,vectors);
    return {claim_id:p.id,evidence:p.text,features:e.features,admitted:e.admitted,score:e.score,raw_score:.5*e.features[0]+.3*e.features[1]+.2*e.features[4]};
   }).sort((a,b)=>n.quantize(b.raw_score)-n.quantize(a.raw_score)||n.cmp(a.claim_id,b.claim_id)));
   return {...row,raw_aspects:aspectFeatures,
    strength:Math.max(0,...row.edges.map(e=>e.score)),passage_count:person.passages.length};
 });
 const automatic=result.options.map((team,index)=>{
   const members=team.ids.map(id=>{
    const r=raw.find(x=>x.id===id);
    return {id,strength:r.strength,core:r.core,baseline:r.baseline,
     marginal:n.coverage(matrix,team.ids)-n.coverage(matrix,team.ids.filter(x=>x!==id)),
     edges:r.edges.map(e=>({score:e.score,admitted:e.admitted,features:e.features,claim_id:e.passage?.id,evidence:e.passage?.text}))};
   });
   return {...team,rank:index+1,members,min_strength:Math.min(...members.map(m=>m.strength)),mean_strength:members.reduce((s,m)=>s+m.strength,0)/members.length};
 });
 const upper=matrix.weights.reduce((s,w,i)=>s+w*Math.max(0,...matrix.rows.map(r=>r.edges[i].score)),0);
 rows.push({id:scope.id,status:result.options.length?'group':'no-group',aspects:matrix.aspects,weights:matrix.weights,rows:raw,
  admitted:matrix.admitted.map(r=>r.id),upper_coverage:upper,has_anchor:matrix.admitted.some(r=>r.edges.some(e=>e.admitted&&e.core>=.4)),
  B:result,B5:prior.B5,A:prior.A,A5:prior.A5,alternatives:automatic});
}
const result={protocol:'D2-before-edit',decision_clock:'2026-09-10T12:00:00Z',source_head:'ec9c717cf1943ac68be4b1a4ba453bbb29dbd931',
 scientific:90,controls:30,prepared:rows.filter(s=>s.status!=='unprepared').length,provider_calls:0,holdout_scored:false,D1_exact_output_parity:true,scopes:rows};
const dest=out+'/D1-reproduction.json';assert(!fs.existsSync(dest));fs.mkdirSync(out,{recursive:true});fs.writeFileSync(dest,JSON.stringify(result)+'\n');
console.log(JSON.stringify({path:dest,sha256:createHash('sha256').update(fs.readFileSync(dest)).digest('hex'),prepared:result.prepared,groups:rows.filter(s=>s.status==='group').length,D1_exact_output_parity:true}));
