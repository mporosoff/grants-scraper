/* All prepared development scopes; existing optimizer, no transport or paid calls. */
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import {performance} from 'node:perf_hooks';import {createHash} from 'node:crypto';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),root='outputs/team-recommender-d3',doc='docs/team-recommender';
const data=read(root+'/matrices-calibration.json'),bundle=read(doc+'/prepared/d1/bundle.json'),prior=read('outputs/team-recommender-d2/D2-candidate-outputs.json');
const old=new Map(prior.scopes.map(s=>[s.id,s])),source=new Map(bundle.scopes.map(s=>[s.id,s])),people=new Map(bundle.people.map(p=>[p.id,p]));
const code=fs.readFileSync('assets/team-recommender.js','utf8');const output={protocol:'D3-frozen-development-outputs',provider_calls:0,holdout_scored:false,scientific:90,controls:30,arms:{E0:prior}};
for(const [arm,input] of Object.entries(data.arms)){
 const parameters=input.fit.final,base=input.baseline_fit.final;const ctx={};vm.createContext(ctx);
 let scoped=code;for(const [from,to] of [['anchor: .4, memberQuality: .5',`anchor: ${parameters.anchor}, memberQuality: ${parameters.member}`]]){assert.equal(scoped.split(from).length,2);scoped=scoped.replace(from,to);}
 vm.runInContext(scoped,ctx);const n=ctx.TeamRecommender;const scopes=[],timings=[];
 for(const s of input.scopes){
  if(s.status==='unprepared'){scopes.push({id:s.id,status:s.status});continue;}
  const begin=performance.now(),science=source.get(s.id),aspects=science.aspects.slice().sort((a,b)=>n.cmp(a.id,b.id));
  const rows=s.rows.map(raw=>{
   const p=people.get(raw.id),edges=aspects.map((a,i)=>p.passages.map((passage,j)=>{
    const specific=n.tokens(a.text).size>0&&n.tokens(passage.text).size>0;
    const admitted=specific&&raw.quality>=parameters.broad&&raw.aspect_passages[i][j]>=parameters.aspect;
    const lexical=n.overlap(a.text,passage.text),core=raw.passage_core[j];
    return {admitted,score:admitted?.5*raw.aspect_passages[i][j]+.3*core+.2*lexical:0,core,passage,
      route:admitted?'suggested-scientific-applicability':'unrelated-or-insufficient',representation:arm,
      features:[raw.aspect_passages[i][j],core,0,0,lexical,1,1,Number(!specific)]};
   }).sort((a,b)=>n.quantize(b.score)-n.quantize(a.score)||n.cmp(a.passage.id,b.passage.id))[0]);
   return {id:raw.id,edges,core:raw.core,baseline:raw.baseline,automatic_quality:raw.quality};
  });
  const m={rows,aspects,weights:aspects.map(a=>a.weight),admitted:rows.filter(r=>r.edges.some(e=>e.admitted&&e.score>0))};
  const matrixEnd=performance.now(),B=n.optimize(m),groupEnd=performance.now();
  const baserank=rows.filter(r=>r.baseline>=base.member).sort((a,b)=>n.quantize(b.baseline)-n.quantize(a.baseline)||n.cmp(a.id,b.id));
  const rank=m.admitted.slice().sort((a,b)=>n.quantize(b.automatic_quality)-n.quantize(a.automatic_quality)||n.cmp(a.id,b.id));
  const size=B.defaultIds.length||2,A=baserank.slice(0,size).map(r=>r.id);
  const explanation=B.defaultIds.map(id=>{const r=rows.find(r=>r.id===id),best=r.edges.map((e,i)=>({e,i})).filter(x=>x.e.admitted&&x.e.score>0).sort((a,b)=>n.quantize(b.e.score)-n.quantize(a.e.score)||a.i-b.i)[0];
   return best?'The public passage “'+best.e.passage.text+'” suggests a scientific conversation about “'+aspects[best.i].text+'”. Exact contribution and application remain to be established.':'No current scoped contribution is attributed.';}).join(' ')||'No adequate complementary group was found in the prepared directory.';
  scopes.push({id:s.id,status:B.defaultIds.length?'group':'no-group',action_allowed:old.get(s.id).action_allowed,action_reason:old.get(s.id).action_reason,A,A5:baserank.slice(0,5).map(r=>r.id),B5:rank.slice(0,5).map(r=>r.id),B,admitted:m.admitted.map(r=>r.id),rows,aspects,weights:m.weights,explanation,
   marginals:B.options.map(t=>({key:t.key,members:t.ids.map(id=>({id,value:n.coverage(m,t.ids)-n.coverage(m,t.ids.filter(x=>x!==id))}))}))});
  const again=n.optimize(m);assert.equal(JSON.stringify(B),JSON.stringify(again));const editStart=performance.now();const edit=n.optimize(m,B.defaultIds.slice(0,1));assert(!edit.options.some(t=>B.defaultIds.length&&t.ids.includes(B.defaultIds[0])));
  timings.push({scope_id:s.id,matrix_from_adopted_scores_ms:matrixEnd-begin,group_ms:groupEnd-matrixEnd,edited_optimization_ms:performance.now()-editStart});
 }
 output.arms[arm]={parameters,baseline_parameters:base,scopes,timings,model:arm==='E0-C'?'voyage-4-lite':arm==='E3'?'voyage-context-4':'voyage-4-large',MMR:0};
 console.log(JSON.stringify({arm,groups:scopes.filter(s=>s.status==='group').length,options:scopes.reduce((n,s)=>n+(s.B?.options.length||0),0),top5:scopes.reduce((n,s)=>n+(s.B5?.length||0),0),action_groups:scopes.filter(s=>s.status==='group'&&s.action_allowed).length,parameters:{member:parameters.member,aspect:parameters.aspect,anchor:parameters.anchor}}));
}
const file=root+'/D3-candidate-outputs.json';assert(!fs.existsSync(file));fs.writeFileSync(file,JSON.stringify(output)+'\n');
const receipt={protocol_sha256:createHash('sha256').update(fs.readFileSync(doc+'/EVALUATION_PROTOCOL_D3.md')).digest('hex'),outputs_sha256:createHash('sha256').update(fs.readFileSync(file)).digest('hex'),arms:Object.fromEntries(Object.entries(output.arms).map(([arm,a])=>[arm,{parameters:a.parameters||'exact D2',scopes:a.scopes.map(s=>({scope_id:s.id,status:s.status,options:s.B?.options.length||0,top5:s.B5?.length||0,action_allowed:s.action_allowed??false})),timings:a.timings||null}])),provider_calls:0,holdout_scored:false,new_human_items:0};
const target=doc+'/receipts/d3-prejudge-outputs.json';assert(!fs.existsSync(target));fs.writeFileSync(target,JSON.stringify(receipt,null,2)+'\n');
