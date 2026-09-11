/* Exact E2 native reconstruction only; no all-arm comparison or tuning. */
import fs from 'node:fs';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';import {gzipSync} from 'node:zlib';import {performance} from 'node:perf_hooks';
import {buildPackage} from './build_team_ingredients.mjs';import {engine,runtime,action} from '../tests/helpers/team-real-inputs.mjs';
const root='outputs/team-recommender-d3/assembled-E2',read=n=>JSON.parse(fs.readFileSync(root+'/'+n+'.json')),sha=b=>createHash('sha256').update(b).digest('hex');
const f={bundle:read('bundle'),directory:read('directory'),context:read('context'),validations:read('validations'),bytes:fs.readFileSync(root+'/vectors.f32')};
f.pack=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations});
assert.equal(f.pack.generation,'42b9af6d68f171f5ee47f004b4f0529af11e174a8bec35f2cb34bb01cb2f6e8a');
// Only this outer verification harness reads saved outputs. The isolated VM
// receives no fs, require, process, evaluation records, labels or provider API.
const reference=JSON.parse(fs.readFileSync('outputs/team-recommender-d3/D3-candidate-outputs.json')).arms.E2;
let network=0;const c=runtime({fetch:()=>{network++;throw Error('External request forbidden');}});
assert.equal(c.process,undefined);assert.equal(c.require,undefined);assert.equal(c.fs,undefined);
global.gc?.();const memoryBefore=process.memoryUsage(),start=performance.now(),{e}=await engine(f,c),hydration=performance.now()-start;
assert.equal(e.statistics().matrices,0);assert.equal(e.statistics().optimizations,0);
const vectors=f.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>f.bytes.readFloatLE(i*4096+j*4))),n=c.TeamRecommender;
const rows=[];
for(const s of reference.scopes){
 if(s.status==='unprepared'){const before=e.statistics();assert.equal(e.resolveScope(action(f,s.id)).ok,false);assert.equal(e.statistics().matrices,before.matrices);rows.push({id:s.id,status:s.status});continue;}
 const scope=e.opportunityById.get(s.id),t=performance.now(),m=n.matrix(scope,f.bundle.people,vectors),mid=performance.now(),out=n.optimize(m),end=performance.now();
 assert.deepEqual(Array.from(out.defaultIds),s.B.defaultIds);assert.deepEqual(Array.from(out.options,x=>Array.from(x.ids)),s.B.options.map(x=>x.ids));
 const ranked=m.admitted.slice().sort((a,b)=>n.quantize(b.automatic_quality)-n.quantize(a.automatic_quality)||n.cmp(a.id,b.id));assert.deepEqual(Array.from(ranked.slice(0,5),r=>r.id),s.B5);
 assert.deepEqual(Array.from(m.admitted,r=>r.id),s.admitted);
 for(let i=0;i<out.options.length;i++)assert(Math.abs(out.options[i].score-s.B.options[i].score)<1e-12);
 const allowed=e.resolveScope(action(f,s.id));assert.equal(allowed.ok,s.action_allowed);
 let cached=null,edit=null;
 if(allowed.ok){const before=e.statistics().matrices;let state=e.proposal(allowed.opportunity);assert.equal(e.statistics().matrices,before+1);
  const view=e.proposalView(state);assert.equal(view.opportunity.why_team,s.explanation);assert.equal(view.selected.length+view.replacements.length,s.admitted.length);
  const t=performance.now();e.proposal(allowed.opportunity);e.proposalView(state);e.proposalOptions(state);cached=performance.now()-t;
  if(state.selectedIds.length){const t=performance.now(),id=state.selectedIds[0];state=e.removeMember(state,id);e.proposalOptions(state);state=e.addReplacement(state,id);e.proposalView(state);edit=performance.now()-t;}
 }
 rows.push({id:s.id,status:s.status,action_allowed:allowed.ok,people:m.rows.length,admitted:m.admitted.length,groups:out.options.length,
  membership_order_hash:sha(JSON.stringify(Array.from(out.options,o=>Array.from(o.ids)))),matrix_ms:mid-t,group_ms:end-mid,combined_ms:end-t,cached_ms:cached,edit_ms:edit});
}
assert.equal(network,0);assert.equal(rows.filter(r=>r.status==='group').length,17);assert.equal(rows.filter(r=>r.action_allowed).length,26);
assert.equal(rows.filter(r=>r.status==='group').reduce((s,r)=>s+r.groups,0),82);
const assets=[...f.pack.files].map(([path,bytes])=>({path,sha256:sha(bytes),bytes:bytes.length,gzip_bytes:gzipSync(bytes).length}));
const stats=key=>{const v=rows.map(r=>r[key]).filter(v=>v!=null).sort((a,b)=>a-b);return {n:v.length,p50_ms:v[Math.ceil(v.length*.5)-1],p95_ms:v[Math.ceil(v.length*.95)-1]};};
global.gc?.();const result={version:'closeout-E2-exact-native-reproduction',generation:f.pack.generation,representation:'D3-combined-v1',engine:n.VERSION,adapter:c.TeamIngredients.VERSION,
 original_runtime_commit:'3c13291a052da298f45db77e974ea3624141cdd5',code_hashes:Object.fromEntries(['team-recommender','team-ingredients'].map(n=>['assets/'+n+'.js',sha(fs.readFileSync('assets/'+n+'.js'))])),
 source_input_hashes:Object.fromEntries(['bundle.json','directory.json','validations.json','context.json','vectors.f32'].map(n=>[n,sha(fs.readFileSync(root+'/'+n))])),
 assets,total_asset_bytes:assets.reduce((n,x)=>n+x.bytes,0),total_gzip_bytes:assets.reduce((n,x)=>n+x.gzip_bytes,0),
 hydration_ms:hydration,hydration_observations:1,matrix:stats('matrix_ms'),group:stats('group_ms'),combined:stats('combined_ms'),cached:stats('cached_ms'),edit:stats('edit_ms'),
 memory_before:memoryBefore,memory_after:process.memoryUsage(),scope_clock:'2026-09-10T12:00:00Z',scientific:90,prepared:35,unprepared:55,groups:17,no_group:18,action_allowed:26,action_groups:10,rows,
 serving_VM_has_no_experiment_outputs_or_filesystem:true,hydration_matrix_and_group_count:0,zero_paid_requests:network,holdout_scored:false,physical_browser:false,
 limitation:'One Node/isolated-VM local reproduction per prepared development scope; timings are observations, not device gates. Historical D3 five-hydration/105-scope measurements remain separate.'};
fs.writeFileSync('docs/team-recommender/receipts/stage3-E2-identity-check.json',JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({...result,assets:undefined,rows:undefined,memory_before:undefined,memory_after:undefined}));
