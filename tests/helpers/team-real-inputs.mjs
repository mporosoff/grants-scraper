import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {buildPackage} from '../../tools/build_team_ingredients.mjs';
export const ROOT='docs/team-recommender/prepared/c2';
export const read=p=>fs.readFileSync(p,'utf8');
export const json=p=>JSON.parse(read(p));
export const NOW='2026-09-10T12:00:00Z';
export async function realInputs(){
 const bundle=json(ROOT+'/bundle.json'),directory=json(ROOT+'/directory.json'),context=json(ROOT+'/context.json'),bytes=fs.readFileSync(ROOT+'/vectors.f32'),validations=json(ROOT+'/validations.json');
 const pack=await buildPackage({bundle,vectors:bytes,directory,sourceValidations:validations});
 return {bundle,directory,context,bytes,validations,pack};
}
export function runtime(overrides={}){
 const c={URL,TextEncoder,TextDecoder,crypto:webcrypto,Uint8Array,Float32Array,DataView,...overrides};vm.createContext(c);
 for(const name of ['submission-schedule','search-retrieval','team-recommender','team-ingredients'])vm.runInContext(read('assets/'+name+'.js'),c);
 return c;
}
export async function engine(f,c=runtime()){
 const manifest=JSON.parse(f.pack.files.get(f.pack.index.ingredients.path));
 const bytes=f.bytes.buffer.slice(f.bytes.byteOffset,f.bytes.byteOffset+f.bytes.byteLength);
 const data=await c.TeamIngredients.hydrate(f.bundle,bytes,manifest,f.pack.index,f.directory);
 return {c,data,manifest,e:c.TeamIngredients.create(data)};
}
export function action(f,sid,now=NOW){
 const scope=f.bundle.scopes.find(s=>s.id===sid);
 return {scopeId:sid,parentId:scope.parent_id,record:f.context.parents[scope.parent_id],
  childCatalog:{opportunities:Object.values(f.context.records).filter(r=>r.parent_id)},now};
}
