import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
export const NOW = new Date('2026-09-09T12:00:00Z');
export function runtime(extra = {}) {
  const c = {URL, TextEncoder, TextDecoder, AbortController, Date, Uint8Array, Float32Array, DataView, crypto:webcrypto, setTimeout, clearTimeout, ...extra};
  vm.createContext(c);
  for (const path of ['assets/submission-schedule.js','assets/search-retrieval.js','assets/team-recommender.js','assets/team-ingredients.js']) vm.runInContext(fs.readFileSync(path,'utf8'),c);
  return c;
}
export async function fixture({count=10, child=false}={}) {
  const c=runtime(), api=c.TeamIngredients, record={opportunity_id:'fixture-scope', title:'Optical spectroscopy and nanocrystal synthesis',
    description:'Optical spectroscopy. Nanocrystal synthesis.', status:'posted', close_date:'2026-09-09', source:'https://example.org/call'};
  const childRecord={...record, opportunity_id:'fixture-scope:child', subtopic_id:'fixture-scope:child', parent_id:record.opportunity_id, publication_state:'publishable', child_type:'subject'};
  const id=child?childRecord.opportunity_id:record.opportunity_id, sourceRecord=child?childRecord:record;
  const text='Optical spectroscopy. Nanocrystal synthesis.';
  const core={id:'core',text,span:{excerpt_id:'e',start:0,end:text.length}, vector:0};
  const aspect=(id,text,start,vector,kind,weight)=>({id,text,span:{excerpt_id:'e',start,end:start+text.length},vector,kind,group_id:id,weight,requirement_kind:'planning_contribution'});
  const space={provider:'voyage',model:'voyage-4-lite',dimension:1024,preprocessing:'exact-utf8-text-v1',normalization:'l2-v1',serialization:'f32le-v1',truncation:false,
    source_output_dtype:'float',chunking:'one-input-per-item',input_encoding:'utf8',
    roles:{scope:'query',passage:'document'},canaries:{query:'1'.repeat(64),document:'2'.repeat(64)}};
  space.fingerprint=await api.sha256(api.canonical(space));
  const rows=[],values=[];
  async function vector(text,role,components) {
    const f=new Float32Array(1024), norm=Math.hypot(...components); components.forEach((v,i)=>f[i]=v/norm);
    rows.push({id:'v'+rows.length,text_sha256:await api.sha256(text),input_role:role,space:space.fingerprint}); values.push(f); return values.length-1;
  }
  core.vector=await vector(text,'query',[1,1]);
  const whole={...core,id:'whole',text:'Optical spectroscopy',span:{excerpt_id:'e',start:0,end:20},vector:await vector('Optical spectroscopy','query',[1,0])};
  const a0=aspect('optical','Optical spectroscopy',0,await vector('Optical spectroscopy','query',[1,0]),'central',.7);
  const a1=aspect('synthesis','Nanocrystal synthesis',22,await vector('Nanocrystal synthesis','query',[0,1]),'supporting',.3);
  const researchers=[],people=[];
  for(let i=0;i<count;i++) {
    const pid='fixture-person-'+String(i).padStart(3,'0'), optical=i%2===0, evidence=optical?'Optical spectroscopy':'Nanocrystal synthesis', cid=pid+'-c1';
    const url='https://example.org/profile/'+pid;
    researchers.push({id:pid,legacy_ids:['legacy-'+i],name:'Fixture person '+i,home_unit:'Fixture unit',status:'active',auto_proposable:true,pool_state:'main',pool_visibility:'public',
      source_url:url,source_checked_date:'2026-09-01',claims:[{claim_id:cid,revision:1,label:evidence,evidence,status:'active',source_urls:[url],evidence_level:'direct'}]});
    people.push({id:pid,passages:[{id:cid,text:evidence,claim_refs:[{claim_id:cid,revision:1}],source_urls:[url],vector:await vector(evidence,'document',optical?[1,0]:[0,1])}]});
  }
  const source={id,parent_id:record.opportunity_id,record_key:api.recordKey(sourceRecord),source_url:record.source,document_sha256:await api.sha256(text),
    excerpts:[{id:'e',text,offset:0,locator:'Fixture paragraph',sha256:await api.sha256(text)}]};
  source.receipt={id:'fixture-source-receipt',kind:'source-span-validation-v1',validation_state:'source-backed',scope_id:id,parent_id:record.opportunity_id,approach_id:'approach',
    document_sha256:source.document_sha256,source_record_key:source.record_key,checked_at:'2026-09-01T00:00:00Z',valid_until:'2026-10-01T00:00:00Z',span_hashes:[source.excerpts[0].sha256]};
  const scope={id,parent_id:record.opportunity_id,record_type:child?'publishable_child':'specific_parent',scope_label:record.title,approach_id:'approach',prepared:true,
    core,whole_call:whole,aspects:[a0,a1],group_budgets:[{id:'optical',weight:.7},{id:'synthesis',weight:.3}],evidence_links:[]};
  const bytes=new Uint8Array(values.length*1024*4), view=new DataView(bytes.buffer);
  values.forEach((v,i)=>v.forEach((n,k)=>view.setFloat32((i*1024+k)*4,n,true)));
  const directory={schema_version:1,registry_generation:'a'.repeat(64),researchers};
  const bundle={schema_version:2,registry_generation:directory.registry_generation,sources:[source],people,scopes:[scope],vector_rows:rows,space};
  const index={schema_version:2,generation_id:'b'.repeat(64),scopes:[{id,parent_id:record.opportunity_id,record_type:scope.record_type,engine:'ingredients-v2',prepared:true}]};
  const manifest={schema_version:2,generation_id:index.generation_id,registry_generation:directory.registry_generation,engine_version:c.TeamRecommender.VERSION,ingredient_version:api.VERSION,
    embedding_space:space.fingerprint,vectors:{path:'data/team-recommender/fixture.f32',bytes:bytes.byteLength,sha256:await api.sha256(bytes)},reviewed_relations:[],
    source_validations:[{validation:'original-source-spans-verified',scope_id:id,parent_id:record.opportunity_id,document_sha256:source.document_sha256,
      text_sha256:source.excerpts[0].sha256,retrieved_at:source.receipt.checked_at,new_retrieval:false,excerpt_hashes:source.receipt.span_hashes}]};
  async function hydrate() {return api.hydrate(bundle,bytes.buffer,manifest,index,directory);}
  async function engine() {const data=await hydrate(), e=api.create(data); const result=e.resolveScope({parentId:record.opportunity_id,scopeId:id,record,childCatalog:{opportunities:[childRecord]},now:NOW});
    if(!result.ok)throw new Error(JSON.stringify(result)); return {data,e,state:e.proposal(result.opportunity)};}
  return {c,api,bundle,bytes,index,manifest,directory,record,childRecord,scope,source,hydrate,engine};
}
