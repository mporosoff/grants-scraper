/* Full development-only numerical comparison. No network or provider clients. */
import fs from 'node:fs';
import vm from 'node:vm';
import {performance} from 'node:perf_hooks';
import {createHash} from 'node:crypto';
const root='outputs/team-recommender-c2',read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const bundle=read(root+'/assembled-v2/bundle.json'),inp=read(root+'/real-inputs-v2.json');
const dev=read('docs/team-recommender/manifests/development.json'),grid=read('docs/team-recommender/manifests/development-parameter-grid-c2.json');
const permitted=new Set(dev.scopes.map(s=>s.id));
if(bundle.scopes.some(s=>!permitted.has(s.id)))throw Error('Only reserved development may be scored');
const bytes=fs.readFileSync(root+'/assembled-v2/vectors.f32'),vectors=bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,k)=>bytes.readFloatLE((i*1024+k)*4)));
const original=fs.readFileSync('assets/team-recommender.js','utf8');
const results=[];
for(const candidate of grid.candidates){
 const c={};vm.createContext(c);
 const code=original.replace('const PARAMETERS = Object.freeze({','const PARAMETERS = Object.freeze({...{').replace('lexicalWeight: .2, mmr: 0 });','lexicalWeight: .2, mmr: 0 },...'+JSON.stringify(candidate.overrides)+' });');
 vm.runInContext(code,c);const n=c.TeamRecommender;
 const out={id:candidate.id,parameters:n.PARAMETERS,code_sha256:createHash('sha256').update(code).digest('hex'),scopes:[]};
 for(const s of bundle.scopes){
  if(!s.prepared){out.scopes.push({id:s.id,status:'unprepared'});continue;}
  const t=performance.now(),m=n.matrix(s,bundle.people,vectors);const matrix_ms=performance.now()-t;
  const start=performance.now(),b=n.optimize(m),mmr=n.optimize(m,[],{mmr:.1});
  const rank=m.admitted.slice().sort((x,y)=>n.quantize(Math.max(...y.edges.map(e=>e.score)))-n.quantize(Math.max(...x.edges.map(e=>e.score)))||n.cmp(x.id,y.id));
  const A=n.baseline(m,b.defaultIds.length || 2),A5=n.baseline(m,5);
  out.scopes.push({id:s.id,status:b.defaultIds.length?'group':'no-group',matrix_ms,optimize_pair_ms:performance.now()-start,
   directory_scored:m.rows.length,admitted:m.admitted.length,B:b,A,A5,B5:rank.slice(0,5).map(r=>r.id),MMR:mmr,
   A_coverage:n.coverage(m,A),B_coverage:n.coverage(m,b.defaultIds),
   B_marginals:b.defaultIds.map(id=>({id,value:n.coverage(m,b.defaultIds)-n.coverage(m,b.defaultIds.filter(x=>x!==id))})),
   rows:m.rows.map(r=>({id:r.id,baseline:r.baseline,core:r.core,edges:r.edges.map((e,i)=>({aspect_id:m.aspects[i].id,admitted:e.admitted,score:e.score,features:e.features,claim_id:e.passage?.id,route:e.route}))}))});
 }
 results.push(out);console.log(JSON.stringify({candidate:out.id,prepared:out.scopes.filter(s=>s.status!='unprepared').length,groups:out.scopes.filter(s=>s.status=='group').length,options:out.scopes.reduce((a,s)=>a+(s.B?.options.length||0),0),top5:out.scopes.reduce((a,s)=>a+(s.B5?.length||0),0)}));
}
const output={source_recipe:grid.source_recipe,scopes:90,controls_reserved:30,provider_calls:0,baseline:'Full 155-person directory, fixed whole-call floor .3 and core floor .25, top-k at each B size. Two-person descriptive baseline for B-empty cases is not a matched-size team comparison.',results};
const raw=JSON.stringify(output)+'\n',path=root+'/development-corrected-v2.json';
if(fs.existsSync(path))throw Error('Preserve existing outcomes; use an explicit version after a justified correction');
fs.writeFileSync(path,raw);
console.log(JSON.stringify({path,sha256:createHash('sha256').update(raw).digest('hex')}));
