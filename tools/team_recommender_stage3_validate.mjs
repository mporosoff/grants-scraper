/* Frozen two-arm held-out observation, never fitting or candidate selection. */
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';import {gzipSync} from 'node:zlib';import {performance} from 'node:perf_hooks';
import {buildPackage} from './build_team_ingredients.mjs';import {engine,runtime,action} from '../tests/helpers/team-real-inputs.mjs';
const root='outputs/team-recommender-stage3',doc='docs/team-recommender',read=p=>JSON.parse(fs.readFileSync(p)),sha=b=>createHash('sha256').update(b).digest('hex');
const lock=read(doc+'/manifests/stage3-validation-lock-v2.json');
for(const [p,h] of Object.entries(lock.runtime))assert.equal(sha(fs.readFileSync(p)),h);
const packages={};let heldout;
for(const cohort of ['holdout_effective','rollout50','rollout150']){
 const dir=root+'/assembled-'+cohort,f={bundle:read(dir+'/bundle.json'),directory:read(dir+'/directory.json'),context:read(dir+'/context.json'),validations:read(dir+'/validations.json'),bytes:fs.readFileSync(dir+'/vectors.f32')};
 f.pack=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations});
 const dest=root+'/package-'+cohort;fs.mkdirSync(dest);
 for(const [p,b]of f.pack.files){fs.mkdirSync(path.dirname(dest+'/'+p),{recursive:true});fs.writeFileSync(dest+'/'+p,b,{flag:'wx'});}
 const assets=[...f.pack.files].map(([p,b])=>({path:p,sha256:sha(b),bytes:b.length,gzip_bytes:gzipSync(b).length}));
 packages[cohort]={generation:f.pack.generation,assets,total_bytes:assets.reduce((s,a)=>s+a.bytes,0),gzip_bytes:assets.reduce((s,a)=>s+a.gzip_bytes,0),scopes:f.bundle.scopes.length,prepared:f.bundle.scopes.filter(s=>s.prepared).length,profile_rows:155};
 if(cohort==='holdout_effective')heldout=f;
}
// Input/package receipts are durable before the first held-out calculation.
fs.writeFileSync(doc+'/receipts/stage3-pre-scoring-packages-v1.json',JSON.stringify({lock_sha256:sha(fs.readFileSync(doc+'/manifests/stage3-validation-lock-v2.json')),packages,holdout_scored:false},null,2)+'\n',{flag:'wx'});
let network=0;const f=heldout,c=runtime({fetch:()=>{network++;throw Error('No provider or network from numerical validation');}}),start=performance.now(),{e}=await engine(f,c),hydration=performance.now()-start;
assert.equal(e.statistics().matrices,0);assert.equal(e.statistics().optimizations,0);
const vectors=f.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>f.bytes.readFloatLE(i*4096+j*4))),n=c.TeamRecommender,results=[];
for(const id of lock.source_order){
 const scope=e.opportunityById.get(id),decision=e.resolveScope(action(f,id,lock.comparison_clock)),base={id,parent_id:scope.parent_id,record_type:scope.record_type,source_disposition:f.context.dispositions.find(s=>s.scope_id===id),action_allowed:decision.ok,action_reason:decision.reason||null};
 if(!scope.prepared){assert.equal(decision.ok,false);results.push({...base,status:'unprepared'});continue;}
 const t=performance.now(),m=n.matrix(scope,f.bundle.people,vectors),mid=performance.now(),out=n.optimize(m),end=performance.now();
 const ranked=m.admitted.slice().sort((a,b)=>n.quantize(b.automatic_quality)-n.quantize(a.automatic_quality)||n.cmp(a.id,b.id));
 const whole=m.rows.filter(r=>r.baseline>=lock.candidate.simple_comparator.whole_call_member_floor).sort((a,b)=>n.quantize(b.baseline)-n.quantize(a.baseline)||n.cmp(a.id,b.id));
 const size=out.defaultIds.length||2,A=whole.length>=size?Array.from(whole.slice(0,size),r=>r.id):[];
 const options=Array.from(out.options,o=>({ids:Array.from(o.ids),key:o.key,coverage:o.score,marginals:Array.from(o.ids,id=>({id,value:o.score-n.coverage(m,o.ids.filter(x=>x!==id))}))}));
 assert(options.length<=8);assert.deepEqual(Array.from(n.optimize(m).options,o=>o.key),options.map(o=>o.key));
 let explanation=null,cached=null,edit=null;
 if(decision.ok){let state=e.proposal(decision.opportunity),view=e.proposalView(state);assert.equal(view.selected.length+view.replacements.length,m.admitted.length);explanation=view.opportunity.why_team;
  const t=performance.now();e.proposal(decision.opportunity);e.proposalView(state);e.proposalOptions(state);cached=performance.now()-t;
  if(state.selectedIds.length){const t=performance.now(),id=state.selectedIds[0];state=e.removeMember(state,id);e.proposalOptions(state);state=e.addReplacement(state,id);e.proposalView(state);edit=performance.now()-t;}
 }
 // Same frozen explanation formula for action-blocked paired quality outputs;
 // this isolated harness does not weaken authoritative live action eligibility.
 if(!explanation&&out.defaultIds.length){const sentences=Array.from(out.defaultIds,id=>{const r=m.rows.find(x=>x.id===id);let best=0;for(let i=1;i<r.edges.length;i++)if(r.edges[i].score>r.edges[best].score)best=i;return `The public passage “${r.edges[best].passage.text}” suggests a scientific conversation about “${m.aspects[best].text}”. Exact contribution and application remain to be established.`;});explanation=sentences.join(' ');}
 results.push({...base,status:options.length?'group':'no-group',full_directory:m.rows.length,admitted:Array.from(m.admitted,r=>r.id),B5:Array.from(ranked.slice(0,5),r=>r.id),A5:Array.from(whole.slice(0,5),r=>r.id),A:{ids:A,coverage:n.coverage(m,A),status:A.length?'group':'abstention'},B:{ids:Array.from(out.defaultIds),options,examined:out.examinedCoverage},explanation,
  features:Array.from(m.rows,r=>({id:r.id,whole:r.baseline,quality:r.automatic_quality,edges:Array.from(r.edges,(edge,i)=>({aspect:m.aspects[i].id,score:edge.score,admitted:edge.admitted,passage:edge.passage?.text,claim_refs:edge.passage?.claim_refs}))})),timing:{matrix_ms:mid-t,group_ms:end-mid,total_ms:end-t,cached_ms:cached,edit_ms:edit}});
}
assert.equal(network,0);assert.equal(results.length,90);
const payload={version:'S3-E2-vs-A-E2-heldout-v1',clock:lock.comparison_clock,lock_sha256:sha(fs.readFileSync(doc+'/manifests/stage3-validation-lock-v2.json')),packages,hydration_ms:hydration,rows:results,provider_calls:network,scientific_changes:0,rollout_recommendations_generated:false};
fs.writeFileSync(root+'/heldout-outputs-v1.json',JSON.stringify(payload)+'\n',{flag:'wx'});
console.log(JSON.stringify({packages,hydration,prepared:results.filter(r=>r.status!=='unprepared').length,groups:results.filter(r=>r.status==='group').length,action_prepared:results.filter(r=>r.status!=='unprepared'&&r.action_allowed).length,action_groups:results.filter(r=>r.status==='group'&&r.action_allowed).length,baseline_groups:results.filter(r=>r.A?.ids.length).length,options:results.reduce((s,r)=>s+(r.B?.options.length||0),0),provider_calls:network}));
