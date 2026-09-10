/* D1 controlled real development comparisons. Never imports provider code. */
import fs from 'node:fs';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),root='outputs/team-recommender-d1';
const oldCode=execFileSync('git',['show','08838e91ab6ff72c051ced53477ba6b3332a7788:assets/team-recommender.js'],{encoding:'utf8'});
const newCode=fs.readFileSync('assets/team-recommender.js','utf8');
const load=dir=>{const bundle=read(dir+'/bundle.json'),bytes=fs.readFileSync(dir+'/vectors.f32');
 return {bundle,vectors:bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,k)=>bytes.readFloatLE(i*4096+k*4)))};};
const old=load('docs/team-recommender/prepared/c2'),current=load(root+'/assembled-d1');
const dev=read('docs/team-recommender/manifests/development.json'),allowed=new Set(dev.scopes.map(s=>s.id));
for(const x of [old,current])if(x.bundle.scopes.length!==90||x.bundle.scopes.some(s=>!allowed.has(s.id)))throw Error('Preserved development boundary required');
const path=root+'/'+(process.argv[2]||'controlled-v1.json');
if(!/^outputs\/team-recommender-d1\/controlled-[a-z0-9-]+\.json$/.test(path)||fs.existsSync(path))throw Error('Preserve outcomes; use explicit version');
const results=[];
for(const [id,code,input] of [['C2-reproduction',oldCode,old],['source-only',oldCode,current],['selection-only',newCode,old],['combined',newCode,current]]){
 const c={};vm.createContext(c);vm.runInContext(code,c);const n=c.TeamRecommender;
 const out={id,parameters:n.PARAMETERS,code_sha256:createHash('sha256').update(code).digest('hex'),scopes:[]};
 for(const s of input.bundle.scopes){
  if(!s.prepared){out.scopes.push({id:s.id,status:'unprepared'});continue;}
  const start=performance.now(),m=n.matrix(s,input.bundle.people,input.vectors),matrix_ms=performance.now()-start;
  const then=performance.now(),b=n.optimize(m),optimize_ms=performance.now()-then;
  const rank=m.admitted.slice().sort((a,b)=>n.quantize(Math.max(...b.edges.map(e=>e.score)))-n.quantize(Math.max(...a.edges.map(e=>e.score)))||n.cmp(a.id,b.id));
  const A=n.baseline(m,b.defaultIds.length||2),A5=n.baseline(m,5);
  out.scopes.push({id:s.id,status:b.defaultIds.length?'group':'no-group',matrix_ms,optimize_ms,directory_scored:m.rows.length,admitted:m.admitted.length,
   B:b,A,A5,B5:rank.slice(0,5).map(r=>r.id),A_coverage:n.coverage(m,A),B_coverage:n.coverage(m,b.defaultIds),
   B_marginals:b.defaultIds.map(id=>({id,value:n.coverage(m,b.defaultIds)-n.coverage(m,b.defaultIds.filter(x=>x!==id))})),
   alternatives_baseline:b.options.map(o=>({ids:n.baseline(m,o.ids.length),size:o.ids.length})),
   rows:m.rows.map(r=>({id:r.id,baseline:r.baseline,core:r.core,edges:r.edges.map((e,i)=>({aspect_id:m.aspects[i].id,score:e.score,admitted:e.admitted,features:e.features,claim_id:e.passage?.id,route:e.route}))}))});
 }
 results.push(out);console.log(JSON.stringify({variant:id,prepared:out.scopes.filter(s=>s.status!=='unprepared').length,groups:out.scopes.filter(s=>s.status==='group').length,
  options:out.scopes.reduce((s,r)=>s+(r.B?.options.length||0),0),B5:out.scopes.reduce((s,r)=>s+(r.B5?.length||0),0),group_ids:out.scopes.filter(s=>s.status==='group').map(s=>s.id)}));
}
const raw=JSON.stringify({version:'D1-controlled-v1',scientific:90,derived_controls:30,provider_calls:0,holdout_scored:false,results})+'\n';
fs.writeFileSync(path,raw);console.log(JSON.stringify({path,sha256:createHash('sha256').update(raw).digest('hex')}));
