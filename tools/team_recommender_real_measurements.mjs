/* Real prepared package and requested-action measurements; no provider imports. */
import fs from 'node:fs';
import vm from 'node:vm';
import zlib from 'node:zlib';
import {performance} from 'node:perf_hooks';
import {createHash} from 'node:crypto';
import {realInputs,engine,action,runtime,read,NOW} from '../tests/helpers/team-real-inputs.mjs';
const hash=b=>createHash('sha256').update(b).digest('hex'),label=process.argv[2]||'development';
const f=await realInputs();global.gc?.();const before=process.memoryUsage(),t=performance.now();
const loaded=await engine(f),hydration=performance.now()-t;global.gc?.();const after=process.memoryUsage(),e=loaded.e;
const initial=e.statistics(),runtimeRequests=[];let forbidden=0;
// The engine has no transport. Trap every available client and allow no fetches.
Object.assign(loaded.c,{fetch(){forbidden++;throw Error('Forbidden paid/runtime network');},XMLHttpRequest:class{constructor(){forbidden++;throw Error('Forbidden network');}},WebSocket:class{constructor(){forbidden++;throw Error('Forbidden network');}}});
const bytes=f.bytes,vectors=f.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,k)=>bytes.readFloatLE((i*1024+k)*4)));
const numeric=runtime().TeamRecommender,rows=[];
for(const scope of f.bundle.scopes){
 const resolution=e.resolveScope(action(f,scope.id));
 if(!scope.prepared){rows.push({scope_id:scope.id,status:'unprepared',action:resolution.reason});continue;}
 const mt=performance.now(),m=numeric.matrix(scope,f.bundle.people,vectors),matrix_ms=performance.now()-mt;
 const gt=performance.now(),group=numeric.optimize(m),group_ms=performance.now()-gt;
 const row={scope_id:scope.id,prepared:true,action_allowed:resolution.ok,action_reason:resolution.reason||null,scored_people:m.rows.length,admitted_people:m.admitted.length,
  matrix_ms,group_ms,group_size:group.defaultIds.length,option_count:group.options.length,coverage:group.maximum,work:group.examinedCoverage};
 if(resolution.ok){
  const cold=performance.now(),state=e.proposal(resolution.opportunity),view=e.proposalView(state),options=e.proposalOptions(state);row.cold_build_view_options_ms=performance.now()-cold;
  const warm=performance.now();e.proposal(resolution.opportunity);e.proposalView(state);e.proposalOptions(state);row.cached_build_view_options_ms=performance.now()-warm;
  const all=new Set([...state.selectedIds,...view.replacements.map(r=>r.profile.id)]);row.reachable=all.size;row.reachability_complete=all.size===m.admitted.length;
  const edit=performance.now();let edited=state;
  if(state.selectedIds.length)edited=e.removeMember(state,state.selectedIds[0]);
  const candidates=e.proposalView(edited).replacements;if(candidates.length&&edited.selectedIds.length<4)edited=e.addReplacement(edited,candidates[0].profile.id);
  e.proposalView(edited);e.proposalOptions(edited);row.edit_replacement_ms=performance.now()-edit;
  row.option_order_stable=JSON.stringify(options)===JSON.stringify(e.proposalOptions(state));
 }
 rows.push(row);
}
const stats=key=>{const x=rows.map(r=>r[key]).filter(Number.isFinite).sort((a,b)=>a-b);return {n:x.length,median_ms:x[Math.floor(x.length*.5)]??null,p95_ms:x[Math.min(x.length-1,Math.floor(x.length*.95))]??null,max_ms:x.at(-1)??null};};
const assets=[...f.pack.files].map(([path,bytes])=>({path,bytes:bytes.length,gzip_bytes:zlib.gzipSync(bytes).length,brotli_bytes:zlib.brotliCompressSync(bytes).length,sha256:hash(bytes)}));
const lazyRuntime=['assets/team-recommender.js','assets/team-ingredients.js'].map(path=>{const b=fs.readFileSync(path);return {path,bytes:b.length,gzip_bytes:zlib.gzipSync(b).length,sha256:hash(b)};});
global.gc?.();const end=process.memoryUsage();
const report={kind:'Node/VM observation, not physical browser/device validation',node:process.version,platform:process.platform,decision_clock:NOW,
 generation:f.pack.generation,assets,lazy_runtime:lazyRuntime,package_bytes:assets.reduce((s,a)=>s+a.bytes,0),package_gzip_bytes:assets.reduce((s,a)=>s+a.gzip_bytes,0),package_brotli_bytes:assets.reduce((s,a)=>s+a.brotli_bytes,0),
 lazy_first_interaction_gzip_bytes:assets.filter(a=>a.path!=='data/opportunity_team_index.js').reduce((s,a)=>s+a.gzip_bytes,0)+lazyRuntime.reduce((s,a)=>s+a.gzip_bytes,0),
 first_click_note:'Directory/catalog and lightweight routing index already belong to the existing loading contract. First interaction transfers the manifest, metadata, numerical vectors and two nonvisual runtime scripts. No all-scope team calculation occurs on startup.',
 hydration_ms:hydration,hydration_observations:1,gc_available:Boolean(global.gc),memory_before_hydration:before,memory_after_hydration:after,memory_after_all_requested_actions:end,
 memory_limits:'Incremental Node process observations with raw inputs already resident. RSS includes allocator effects; not a phone heap cap or browser peak-memory measurement.',
 initial_statistics:initial,final_statistics:e.statistics(),scientific_scopes:90,prepared:34,unprepared:56,action_admitted:rows.filter(r=>r.action_allowed).length,
 no_group_numerical:rows.filter(r=>r.prepared&&!r.group_size).length,with_group_numerical:rows.filter(r=>r.group_size).length,
 measurements:Object.fromEntries(['matrix_ms','group_ms','cold_build_view_options_ms','cached_build_view_options_ms','edit_replacement_ms'].map(k=>[k,stats(k)])),provider_requests:forbidden,rows};
const path='docs/team-recommender/receipts/c2-real-measurements-'+label+'.json';if(fs.existsSync(path))throw Error('Preserve previous measurements; select a new receipt version');
fs.writeFileSync(path,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,assets:undefined,rows:undefined,lazy_runtime:undefined}));
