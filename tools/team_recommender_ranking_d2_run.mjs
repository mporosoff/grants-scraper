/* Freeze actual D2 outputs before any new judge results. Development only. */
import fs from 'node:fs';import assert from 'node:assert/strict';import vm from 'node:vm';import {createHash} from 'node:crypto';
import {realInputs,engine,action} from '../tests/helpers/team-real-inputs.mjs';
const root='outputs/team-recommender-d2',read=p=>JSON.parse(fs.readFileSync(p,'utf8')),hash=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const f=await realInputs(),{e}=await engine(f),c={};vm.createContext(c);vm.runInContext(fs.readFileSync('assets/team-recommender.js','utf8'),c);const n=c.TeamRecommender;
const v=f.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>f.bytes.readFloatLE(i*4096+j*4)));
const prior=read(root+'/fixed-D1-selection.json').results[0],fit=new Map(read(root+'/fit-R0.json').all_rows.map(r=>[r.scope_id+'|'+r.person_id,r.fixed_quality])),scopes=[];
for(const s of f.bundle.scopes){
 if(!s.prepared){scopes.push({id:s.id,status:'unprepared'});continue;}
 const m=n.matrix(s,f.bundle.people,v),B=n.optimize(m),resolution=e.resolveScope(action(f,s.id));
 for(const row of m.rows)assert.equal(row.automatic_quality,fit.get(s.id+'|'+row.id));
 assert.equal(JSON.stringify(B),JSON.stringify(prior.scopes.find(r=>r.id===s.id).B));
 const rank=m.admitted.slice().sort((a,b)=>n.quantize(Math.max(...b.edges.map(e=>e.score)))-n.quantize(Math.max(...a.edges.map(e=>e.score)))||n.cmp(a.id,b.id));
 let explanation=null;if(resolution.ok){const state=e.proposal(resolution.opportunity);explanation=e.proposalView(state).opportunity.why_team;}
 scopes.push({id:s.id,status:B.defaultIds.length?'group':'no-group',action_allowed:resolution.ok,action_reason:resolution.reason||null,
  A:n.baseline(m,B.defaultIds.length||2),A5:n.baseline(m,5),B5:rank.slice(0,5).map(r=>r.id),B,
  admitted:m.admitted.map(r=>r.id),rows:m.rows,aspects:m.aspects,weights:m.weights,
  marginals:B.options.map(t=>({key:t.key,members:t.ids.map(id=>({id,value:n.coverage(m,t.ids)-n.coverage(m,t.ids.filter(x=>x!==id))}))})),explanation});
}
const path=root+'/D2-candidate-outputs.json';assert(!fs.existsSync(path));fs.writeFileSync(path,JSON.stringify({representation:'R0',scientific:90,controls:30,provider_calls:0,holdout_scored:false,scopes})+'\n');
const receipt={version:'D2-prejudge-freeze',decision:'R0 fixed member quality; no quality-qualified winner yet',engine_version:n.VERSION,adapter_version:'ingredients-v2.4',
 parameters:n.PARAMETERS,scorer:{name:'fixed-call-person',formula:'.7 maximum scientific aspect cosine + .3 maximum scientific whole-call cosine',threshold:.5,probability:false},
 representation:'R0 evidence-only',R1:'Evaluated isolated and combined; not selected: one extra judged unrelated primary member and fewer reasonable option-member occurrences; top-five missing labels prevent a complete isolated semantic estimate.',
 regularized:'Not selected by predeclared nested rule under either representation',Bayesian:'Not evaluated; optional, no numerical ambiguity requiring another fit',MMR:'off',
 grouping:'unchanged source-group-amendment-c2-f92fc5995a0a1ac0.json',judge_protocol:'D1F unchanged',
 code:{'assets/team-recommender.js':hash('assets/team-recommender.js'),'assets/team-ingredients.js':hash('assets/team-ingredients.js')},
 data:{bundle:hash('docs/team-recommender/prepared/d1/bundle.json'),vectors:hash('docs/team-recommender/prepared/d1/vectors.f32'),directory:hash('docs/team-recommender/prepared/d1/directory.json')},
 generation:f.pack.generation,outputs_sha256:hash(path),prepared:35,unprepared:55,groups:scopes.filter(s=>s.status==='group').length,
 options:scopes.reduce((n,s)=>n+(s.B?.options.length||0),0),action_admitted:scopes.filter(s=>s.action_allowed).length,
 automatic_candidate_access:'Unchanged D1 evidence-admitted pool; quality gate affects automatic groups only',positive_removal_floor:false,
 rho_selection:'.90 retained: .95 loses 16.39% of already-judged reasonable member occurrences on R0, exceeding the predeclared 10% limit',
 scientific_generic_guard:'Generic-token-only passages cannot increase automatic quality; identical values on all 5425 real call-person rows',
 new_judgments_received:0,new_human_items:0,holdout_scored:false};
const target='docs/team-recommender/receipts/d2-prejudge-candidate.json';assert(!fs.existsSync(target));fs.writeFileSync(target,JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt));
