import fs from 'node:fs';
import os from 'node:os';
import {performance} from 'node:perf_hooks';
import {gzipSync} from 'node:zlib';
import {fixture,runtime} from '../tests/fixtures/team-ingredients.mjs';
import {buildPackage} from './build_team_ingredients.mjs';
const quantile=(a,p)=>a.slice().sort((x,y)=>x-y)[Math.ceil(p*a.length)-1];
const f=await fixture({count:155}),pack=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.manifest.source_validations});
const t=performance.now(),heap=process.memoryUsage(),{e,state}=await f.engine(),cold=performance.now()-t;
const times=[];for(let i=0;i<55;i++){const start=performance.now();e.proposalView(state);e.proposalOptions(state);if(i>=5)times.push(performance.now()-start);}
const n=runtime().TeamRecommender, vectors=[],row=(values)=>{const v=new Float32Array(1024),norm=Math.hypot(...values);values.forEach((x,i)=>v[i]=x/norm);vectors.push(v);return vectors.length-1;};
let seed=17;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return(seed%10000)/10000;};
const aspects=Array.from({length:8},(_,i)=>({id:'a'+i,text:'nanocrystal optical spectroscopy assay'+i,weight:i===0?.7:.3/7,vector:row(Array.from({length:8},(_,k)=>k===i?1:0))}));
const core={text:'nanocrystal optical spectroscopy',vector:row(Array(8).fill(1))};const scope={semantic_key:'synthetic-scope',aspects,core,whole_call:core};
const people=Array.from({length:155},(_,i)=>({id:'p'+String(i).padStart(3,'0'),semantic_key:'synthetic-'+i,passages:[]}));
for(let i=0;i<402;i++)people[i%155].passages.push({id:'claim'+i,text:'nanocrystal optical spectroscopy assay'+i%8,vector:row(Array.from({length:8},()=>random()))});
const matrixTimes=[],groupTimes=[],work=[];let sample;
for(let i=0;i<35;i++){
 let start=performance.now();const m=n.matrix(scope,people,vectors);const matrixMs=performance.now()-start;
 start=performance.now();const result=n.optimize(m);const groupMs=performance.now()-start;
 if(i>=5){matrixTimes.push(matrixMs);groupTimes.push(groupMs);work.push(result.examinedCoverage);}sample={m,result};
}
const totalBytes=[...pack.files.values()].reduce((s,b)=>s+b.length,0),gzipBytes=[...pack.files.values()].reduce((s,b)=>s+gzipSync(b).length,0);
const report={reference:{node:process.version,platform:process.platform,arch:process.arch,cpu:os.cpus()[0].model,logical_processors:os.cpus().length},
 fixture_only:true,real_semantic_measurements:false,provider_calls:0,real_browser:false,
 hydrated_fixture:{people:155,passages:155,scopes:1,raw_package_bytes:totalBytes,local_gzip_bytes:gzipBytes,cold_hydrate_matrix_and_group_ms:cold,
 warm_view_options_p95_ms:quantile(times,.95),warm_samples:50,heap_delta_bytes:process.memoryUsage().heapUsed-heap.heapUsed,byte_delta_includes_later_harness:true},
 full_shape:{people:155,passages:402,aspects:8,dimensions:1024,samples:30,warmups:5,matrix_p95_ms:quantile(matrixTimes,.95),group_p95_ms:quantile(groupTimes,.95),
  maximum_coverage_work:Math.max(...work),declared_work_limit:n.PARAMETERS.workLimit,options:sample.result.options.length,
  typed_vector_bytes:vectors.length*4096},
 candidate_parameters:n.PARAMETERS,measured_assets:Object.fromEntries(['assets/team-recommender.js','assets/team-ingredients.js','assets/opportunity-team.js','assets/opportunity-team-panel.js'].map(p=>[p,fs.statSync(p).size])),
 unmeasured:['real 150-scope ingredient payload','real browser wire transfer/decode/heap/long tasks','physical device timings','real recommendation quality','semantic threshold calibration']};
fs.writeFileSync('docs/team-recommender/receipts/stage2-resource-measurements.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
