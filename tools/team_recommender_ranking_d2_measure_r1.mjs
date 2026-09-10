/* Actual unused R1 resource cost, measured without providers or browser claims. */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {gzipSync,brotliCompressSync} from 'node:zlib';
import {performance} from 'node:perf_hooks';
import {representationEngine} from './team_recommender_ranking_d2_representation.mjs';
const root='docs/team-recommender/prepared/d2-context',n=representationEngine();
const files=['bundle.json','vectors.f32','directory.json','context.json','validations.json'].map(name=>{
 const bytes=fs.readFileSync(root+'/'+name);
 return {name,sha256:createHash('sha256').update(bytes).digest('hex'),raw:bytes.length,gzip:gzipSync(bytes).length,brotli:brotliCompressSync(bytes).length};
});
const memoryBefore=process.memoryUsage(),start=performance.now();
const bundle=JSON.parse(fs.readFileSync(root+'/bundle.json','utf8')),bytes=fs.readFileSync(root+'/vectors.f32');
const vectors=bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>bytes.readFloatLE(i*4096+j*4)));
const decodeMs=performance.now()-start,memoryDecoded=process.memoryUsage();
const expected=JSON.parse(fs.readFileSync('outputs/team-recommender-d2/R1-D1-selection.json','utf8')),matrices=[],groups=[];
for(const scope of bundle.scopes.filter(s=>s.prepared)){
 let t=performance.now();const matrix=n.matrix(scope,bundle.people,vectors);matrices.push(performance.now()-t);
 t=performance.now();const result=n.optimize(matrix);groups.push(performance.now()-t);
 assert.equal(JSON.stringify(result.options),JSON.stringify(expected.scopes.find(s=>s.id===scope.id).B.options));
}
const stats=a=>{a.sort((a,b)=>a-b);return {n:a.length,median:a[Math.floor(a.length/2)],p95:a[Math.ceil(a.length*.95)-1],max:a.at(-1)};};
const receipt={environment:{node:process.version,platform:process.platform},representation:'R1 diagnostic only; not selected',files,
 total:Object.fromEntries(['raw','gzip','brotli'].map(k=>[k,files.reduce((s,f)=>s+f[k],0)])),
 decode_ms:decodeMs,full_directory_matrix_ms:stats(matrices),group_ms:stats(groups),
 memory_before:memoryBefore,memory_after_decode:memoryDecoded,memory_after_calculation:process.memoryUsage(),
 unchanged_isolated_outputs:true,prepared_scopes:35,people:155,rows:1035,provider_calls:0,holdout_scored:false,
 limitation:'Node prototype decode/calculation only. Includes input file reads; not adapter hydration, first-click transfer, physical-browser memory or validation of R1 adoption.'};
const path='docs/team-recommender/receipts/d2-r1-resource-measurements.json';
assert(!fs.existsSync(path));fs.writeFileSync(path,JSON.stringify(receipt,null,2)+'\n');console.log(JSON.stringify(receipt));
