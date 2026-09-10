/* Real data measurements in Node, explicitly not physical-browser validation. */
import fs from 'node:fs';import assert from 'node:assert/strict';import {performance} from 'node:perf_hooks';import {gzipSync} from 'node:zlib';import {createHash} from 'node:crypto';
import {buildPackage} from './build_team_ingredients.mjs';import {engine,action} from '../tests/helpers/team-real-inputs.mjs';
const arm=process.argv[2];assert(['E0','E1','E2','E3'].includes(arm));global.gc?.();const before=process.memoryUsage();
const root=arm==='E0'?'docs/team-recommender/prepared/d1':'outputs/team-recommender-d3/assembled-'+arm,read=n=>JSON.parse(fs.readFileSync(root+'/'+n+'.json'));
const f={bundle:read('bundle'),directory:read('directory'),validations:read('validations'),context:read('context'),bytes:fs.readFileSync(root+'/vectors.f32')};
f.pack=await buildPackage({bundle:f.bundle,directory:f.directory,vectors:f.bytes,sourceValidations:f.validations});
const hydration=[],matrix=[],group=[],combined=[],cached=[],edits=[];let stateEngine;
for(let repeat=0;repeat<5;repeat++){const start=performance.now();stateEngine=await engine(f);hydration.push(performance.now()-start);assert.equal(stateEngine.e.statistics().matrices,0);}
const {c,e}=stateEngine,n=c.TeamRecommender,vectors=f.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>f.bytes.readFloatLE(i*4096+j*4)));
for(const s of f.bundle.scopes.filter(s=>s.prepared)){
 const scope=e.opportunityById.get(s.id);
 for(let repeat=0;repeat<3;repeat++){
  const start=performance.now(),m=n.matrix(scope,f.bundle.people,vectors),mid=performance.now(),b=n.optimize(m),end=performance.now();matrix.push(mid-start);group.push(end-mid);combined.push(end-start);
 }
 const resolution=e.resolveScope(action(f,s.id));if(!resolution.ok)continue;
 let state=e.proposal(resolution.opportunity);e.proposalOptions(state);
 const a=performance.now();e.proposal(resolution.opportunity);e.proposalView(state);cached.push(performance.now()-a);
 if(state.selectedIds.length){const id=state.selectedIds[0],t=performance.now();state=e.removeMember(state,id);e.proposalOptions(state);e.proposalView(state);state=e.addReplacement(state,id);e.proposalView(state);edits.push(performance.now()-t);}
}
global.gc?.();const after=process.memoryUsage(),stats=a=>{const s=a.slice().sort((a,b)=>a-b);return {n:s.length,p50_ms:s[Math.ceil(s.length*.5)-1],p95_ms:s[Math.ceil(s.length*.95)-1],max_ms:s.at(-1)}};
const files=[...f.pack.files].map(([path,bytes])=>({path,sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length,gzip_bytes:gzipSync(bytes).length}));
const result={arm,engine:n.VERSION,adapter:c.TeamIngredients.VERSION,generation:f.pack.generation,files,total_asset_bytes:files.reduce((s,f)=>s+f.bytes,0),total_gzip_bytes:files.reduce((s,f)=>s+f.gzip_bytes,0),
 hydration:stats(hydration),full_directory_matrix:stats(matrix),group:stats(group),matrix_plus_group:stats(combined),cached_build_view:stats(cached),remove_replacement_add_view:stats(edits),
 Node_memory_before:before,Node_memory_after:after,Node_heap_delta:after.heapUsed-before.heapUsed,Node_arraybuffer_delta:after.arrayBuffers-before.arrayBuffers,
 provider_calls:0,scope_count:35,people:155,holdout_scored:false,physical_browser:false,limitation:'Node v24 reference in a separate process, five hydrations and three requested-scope calculations per scope. VM/custom DOM are not device or throttled-browser measurements. Memory includes local source objects and package construction; it is not the browser heap gate.'};
const target='docs/team-recommender/receipts/d3-resources-'+arm+'.json';assert(!fs.existsSync(target));fs.writeFileSync(target,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({arm,generation:result.generation,total_asset_bytes:result.total_asset_bytes,total_gzip_bytes:result.total_gzip_bytes,hydration:result.hydration,matrix:result.full_directory_matrix,group:result.group,cached:result.cached_build_view,edit:result.remove_replacement_add_view,heap_delta:result.Node_heap_delta,arraybuffer_delta:result.Node_arraybuffer_delta}));
