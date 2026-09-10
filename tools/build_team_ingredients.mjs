#!/usr/bin/env node
/* Offline packager for already validated PUBLIC recipes and compatible vectors.
   No extraction, embedding, judging, deployment, or provider fallback. */
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import {webcrypto,createHash} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
const ROOT=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const hash=b=>createHash('sha256').update(b).digest('hex');
const encode=o=>Buffer.from(JSON.stringify(o)+'\n');
export async function buildPackage({bundle,vectors,directory,legacyIndex=null,sourceValidations=[]}) {
 const c={URL,TextEncoder,TextDecoder,crypto:webcrypto,Uint8Array,Float32Array,DataView};vm.createContext(c);
 const runtime={};
 for(const [name,key] of [['team-recommender','recommender'],['team-ingredients','ingredients']]) {
  const bytes=await fs.readFile(path.join(ROOT,'assets',name+'.js'));runtime[key]=hash(bytes);vm.runInContext(bytes.toString(),c);
 }
 const bytes=encode(bundle),vectorBytes=Buffer.from(vectors);
 const descriptor=(bytes,ext)=>({path:'data/team-recommender/'+hash(bytes)+'.'+ext,sha256:hash(bytes),bytes:bytes.length});
 const metadata=descriptor(bytes,'json'),vectorDescriptor=descriptor(vectorBytes,'f32');
 const generation=hash(c.TeamIngredients.canonical([metadata,vectorDescriptor,directory.registry_generation,runtime,legacyIndex,sourceValidations]));
 const own=new Set(bundle.scopes.map(s=>s.id));
 const manifest={schema_version:2,generation_id:generation,registry_generation:directory.registry_generation,engine_version:c.TeamRecommender.VERSION,
    ingredient_version:c.TeamIngredients.VERSION,embedding_space:bundle.space.fingerprint,metadata,vectors:vectorDescriptor,reviewed_relations:[],source_validations:sourceValidations};
 // Reviewed relation receipts must be deliberately preserved by a separate audited input.
 if(bundle.scopes.some(s=>s.evidence_links?.length))throw Error('Supply independently validated relation receipts through an audited preparation path; this packager defaults to unconfirmed.');
 const index={schema_version:2,generation_id:generation,runtime,
  scopes:[...(legacyIndex?.scopes||[]).filter(s=>!own.has(s.id)).map(s=>({...s,engine:'legacy-v1'})),
   ...bundle.scopes.map(s=>({id:s.id,parent_id:s.parent_id,record_type:s.record_type,engine:'ingredients-v2',prepared:s.prepared}))]};
 if(legacyIndex){index.legacy_generation=legacyIndex.generation_id;index.legacy_index=legacyIndex;}
 index.scope_count=index.scopes.length;
 const view=vectorBytes.buffer.slice(vectorBytes.byteOffset,vectorBytes.byteOffset+vectorBytes.byteLength);
 await c.TeamIngredients.hydrate(bundle,view,manifest,index,directory);
 const manifestBytes=encode(manifest);index.ingredients=descriptor(manifestBytes,'json');
 if(bytes.length+vectorBytes.length+manifestBytes.length>8*1024*1024)throw Error('Ingredient package exceeds the fixed byte bound.');
 return {generation,index,files:new Map([[metadata.path,bytes],[vectorDescriptor.path,vectorBytes],[index.ingredients.path,manifestBytes],
  ['data/opportunity_team_index.js',Buffer.from('globalThis.OPPORTUNITY_TEAM_INDEX = '+JSON.stringify(index)+';\n')]])};
}
async function main(){
 const [inputPath,vectorPath,directoryPath,validationPath,outputPath]=process.argv.slice(2);
 if(!outputPath)throw Error('Usage: node tools/build_team_ingredients.mjs PUBLIC_RECIPE.json VECTORS.f32 DIRECTORY.json ORIGINAL_SOURCE_VALIDATIONS.json NEW_OUTPUT_DIRECTORY');
 const output=path.resolve(outputPath);
 if(output===ROOT||!output.startsWith(path.join(ROOT,'outputs')+path.sep))throw Error('Output must be a new isolated directory under outputs.');
 try{await fs.access(output);throw Error('Refusing to overwrite an existing package.');}catch(e){if(e.code!=='ENOENT')throw e;}
 const result=await buildPackage({bundle:JSON.parse(await fs.readFile(inputPath,'utf8')),vectors:await fs.readFile(vectorPath),directory:JSON.parse(await fs.readFile(directoryPath,'utf8')),
  sourceValidations:JSON.parse(await fs.readFile(validationPath,'utf8'))});
 const temp=output+'.partial';await fs.mkdir(temp,{recursive:false});
 for(const [name,bytes]of result.files){const target=path.join(temp,name);await fs.mkdir(path.dirname(target),{recursive:true});await fs.writeFile(target,bytes,{flag:'wx'});}
 // The index is committed with all content-addressed assets by one directory adoption.
 await fs.rename(temp,output);console.log(JSON.stringify({generation:result.generation,files:result.files.size,output,provider_calls:0}));
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(e=>{console.error(e.message);process.exitCode=1;});
