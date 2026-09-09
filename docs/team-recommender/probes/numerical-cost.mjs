// Cost probe only: synthetic vectors, no real person/scope relevance outputs.
import fs from 'node:fs';import os from 'node:os';import {performance} from 'node:perf_hooks';import zlib from 'node:zlib';
const inv=JSON.parse(fs.readFileSync('docs/team-recommender/receipts/inventory.json'));
const n=inv.directory_counts.auto_proposable,p=inv.deduplicated_eligible_passages,d=1024,a=8;
const before=process.memoryUsage();
let seed=1729;function value(){seed=(Math.imul(seed,1664525)+1013904223)>>>0;return (seed/4294967296-.5)/10;}
const vectors=Float32Array.from({length:p*d},value),queries=Float32Array.from({length:(a+1)*d},value);
function matrix(){const out=new Float64Array(a*n);for(let i=0;i<a;i++)for(let row=0;row<p;row++){let dot=0;for(let k=0;k<d;k++)dot+=queries[i*d+k]*vectors[row*d+k];const j=row%n;out[i*n+j]=Math.max(out[i*n+j],Math.max(0,dot));}return out;}
// Counts full-directory anchored greedy starts and one bounded swap sweep per
// returned size. This does not implement admission, evidence, or team feasibility.
let work=0;function coverage(m,ids){work++;let f=0;for(let i=0;i<a;i++){let best=0;for(const id of ids)best=Math.max(best,m[i*n+id]);f+=best/a;}return f;}
function search(m){let best=-1;for(let anchor=0;anchor<n;anchor++){let ids=[anchor];for(let size=2;size<=4;size++){let add=-1,score=-1;for(let j=0;j<n;j++){if(ids.includes(j))continue;const f=coverage(m,[...ids,j]);if(f>score){score=f;add=j;}}ids.push(add);best=Math.max(best,score);const original=[...ids];let improved=ids;for(let k=1;k<ids.length;k++)for(let j=0;j<n;j++){if(original.includes(j))continue;const swapped=original.map((id,index)=>index===k?j:id),f=coverage(m,swapped);if(f>score){score=f;improved=swapped;}}ids=improved;best=Math.max(best,score);}}return best;}
function replacements(m){const ids=[0,1,2],base=coverage(m,ids);return Array.from({length:n},(_,j)=>coverage(m,[...ids,j])-base);}
const percentile=(xs,q)=>[...xs].sort((a,b)=>a-b)[Math.ceil(q*xs.length)-1];
const dotTimes=[],searchTimes=[],replacementTimes=[];let m;
for(let iteration=0;iteration<55;iteration++){let start=performance.now();m=matrix();const dot=performance.now()-start;start=performance.now();work=0;search(m);const elapsed=performance.now()-start;start=performance.now();replacements(m);const replacement=performance.now()-start;if(iteration>=5){dotTimes.push(dot);searchTimes.push(elapsed);replacementTimes.push(replacement);}}
const after=process.memoryUsage();
// Serialize an explicitly nonsemantic metadata envelope at the measured size.
const source=JSON.parse(fs.readFileSync('docs/team-recommender/manifests/source-groups.json'));
const rollout=JSON.parse(fs.readFileSync('docs/team-recommender/manifests/rollout.json'));
const meta={schema_version:2,status:'cost-probe-only',sources:source.records.filter(r=>rollout.cohort_150.includes(r.id)).map(r=>({...r,aspects:Array.from({length:8},(_,i)=>({aspect_id:r.id+':a'+i,description:'B'.repeat(200),source_span:'S'.repeat(400),source_hash:r.source_sha256,source_url:r.source_url}))})),registry_bytes:inv.files['data/researcher_directory.js'].bytes};
const metaBytes=Buffer.from(JSON.stringify(meta));
const raw=inv.profile_and_scope_float32_estimate.maximum_150_8_aspects;
const rawNormal=inv.profile_and_scope_float32_estimate.normal_150_6_aspects;
const summary={reference:{platform:process.platform,arch:process.arch,node:process.version,cpu:os.cpus()[0].model,logical_cpus:os.cpus().length,physical_device:false,reference_class:'available developer workstation, not a midrange mobile reference'},inputs:{researchers:n,passages:p,aspects:a,dimensions:d,synthetic:true,semantic_quality_evaluated:false},runs:50,warmup:5,dot_multiply_adds:p*a*d,coverage_evaluations_per_recompute:work,timing_ms:{matrix_p50:percentile(dotTimes,.5),matrix_p95:percentile(dotTimes,.95),group_kernel_p50:percentile(searchTimes,.5),group_kernel_p95:percentile(searchTimes,.95),replacements_p95:percentile(replacementTimes,.95)},memory:{before,after,vector_array_bytes:vectors.byteLength+queries.byteLength,matrix_bytes:m.byteLength,limitation:'Process measurements include Node/GC; not browser incremental heap'},payload:{normal_float32_bytes:rawNormal,maximum_float32_bytes:raw,metadata_shape_bytes:metaBytes.length,metadata_shape_gzip_bytes:zlib.gzipSync(metaBytes).length,measured_directory_gzip_bytes:inv.files['data/researcher_directory.js'].gzip_bytes,conservative_max_transfer_bytes:raw+metaBytes.length+inv.files['data/researcher_directory.js'].bytes,limitation:'No actual new ingredient bundle or claim/aspect vectors exists. Metadata placeholder compression is not an expected transfer claim. Uncompressed bound used.'}};
summary.payload.ideal_20mbps_150ms_seconds=summary.payload.conservative_max_transfer_bytes*8/20e6+.150;
fs.writeFileSync('docs/team-recommender/receipts/numerical-cost.json',JSON.stringify(summary,null,2)+'\n');console.log(JSON.stringify(summary,null,2));
