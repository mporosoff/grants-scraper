/* Correct older native receipt representation using the existing catalog adapter.
   Rollout only: no held-out input, source text, vector or scientific rule change. */
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';import {gzipSync} from 'node:zlib';import vm from 'node:vm';
import {runtime} from '../tests/helpers/team-real-inputs.mjs';import {buildPackage} from './build_team_ingredients.mjs';
const root='outputs/team-recommender-stage3',read=p=>JSON.parse(fs.readFileSync(p)),sha=b=>createHash('sha256').update(b).digest('hex'),c=runtime();
vm.runInContext(fs.readFileSync('data/subtopics.js','utf8'),c);const children=new Map(c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG).opportunities.map(r=>[r.subtopic_id,r]));
const first=read('docs/team-recommender/receipts/stage3-pre-scoring-packages-v1.json'),packages={...first.packages},changes=[];
for(const cohort of ['rollout50','rollout150']){
 const original=root+'/assembled-'+cohort,dest=original+'-v3';fs.mkdirSync(dest);
 const bundle=read(original+'/bundle.json'),context=read(original+'/context.json'),validations=read(original+'/validations.json');
 for(const s of bundle.scopes.filter(s=>s.record_type==='publishable_child')){
  const child=children.get(s.id),source=bundle.sources.find(x=>x.id===s.id);assert(child);assert.equal(child.parent_id,s.parent_id);
  const before=JSON.parse(source.record_key),key=c.TeamIngredients.recordKey(child),after=JSON.parse(key),different=Object.keys(before).filter(k=>JSON.stringify(before[k])!==JSON.stringify(after[k]));
  if(!different.length)continue;assert.deepEqual(different,['description']);assert.equal(before.description,null);assert.equal(after.description,before.summary);
  const originalReceipt=source.receipt?.id;source.record_key=key;
  if(source.receipt){source.receipt.source_record_key=key;source.receipt.id='r'+sha(c.TeamIngredients.canonical(source.receipt)).slice(0,22);}
  context.records[s.id]=JSON.parse(JSON.stringify(child));changes.push({cohort,scope_id:s.id,parent_id:s.parent_id,prepared:s.prepared,different_material_fields:different,description_is_exact_existing_summary:true,original_receipt_id:originalReceipt||null,projected_receipt_id:source.receipt?.id||null,source_hash:source.document_sha256,source_retrieval_date_unchanged:true});
 }
 for(const [name,value]of Object.entries({bundle,context,validations}))fs.writeFileSync(dest+'/'+name+'.json',JSON.stringify(value)+'\n');
 for(const name of ['directory.json','vectors.f32'])fs.copyFileSync(original+'/'+name,dest+'/'+name);
 const pack=await buildPackage({bundle,vectors:fs.readFileSync(dest+'/vectors.f32'),directory:read(dest+'/directory.json'),sourceValidations:validations}),out=root+'/package-'+cohort+'-v3';fs.mkdirSync(out);
 for(const [p,b]of pack.files){fs.mkdirSync(path.dirname(out+'/'+p),{recursive:true});fs.writeFileSync(out+'/'+p,b,{flag:'wx'});}
 const assets=[...pack.files].map(([p,b])=>({path:p,sha256:sha(b),bytes:b.length,gzip_bytes:gzipSync(b).length}));
 packages[cohort]={generation:pack.generation,assets,total_bytes:assets.reduce((n,x)=>n+x.bytes,0),gzip_bytes:assets.reduce((n,x)=>n+x.gzip_bytes,0),scopes:bundle.scopes.length,prepared:bundle.scopes.filter(s=>s.prepared).length,profile_rows:155,input_directory:dest,package_directory:out};
}
fs.writeFileSync('docs/team-recommender/receipts/stage3-routing-packages-v3.json',JSON.stringify({packages,changes,heldout_input_changes:0,source_text_changes:0,vector_changes:0,profile_changes:0,provider_calls:0,production_activation:false},null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({changed:changes.length,prepared_changed:changes.filter(c=>c.prepared).length,cohorts:Object.fromEntries(Object.entries(packages).map(([k,v])=>[k,v.generation])),holdout_changes:0,science_changes:0}));
