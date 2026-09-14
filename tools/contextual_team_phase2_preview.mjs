// Assemble exact application bytes under the existing Access-protected host.
// No provider, graph inventory, public publication or hosting configuration.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {gzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {hash,canonical,SOURCE_FIELDS,CONDITION_FIELDS} from './contextual_team_inputs.mjs';
const helper=path.resolve(process.argv[2]),target=path.join(helper,'workers/researcher-intake/config/contextual-preview-v1.json');
const requirements=process.argv.includes('--requirements-latency');
const p=JSON.parse(fs.readFileSync(path.join(helper,'config/contextual_team/'+(requirements?'requirements-latency-v2.json':'phase2-v1.json'))));
const sources=JSON.parse(fs.readFileSync(path.join(helper,'config/contextual_team/phase2-source-inputs-v2.json')));
if(requirements)sources.scopes=sources.scopes.filter(s=>s.id===p.workflow_scope);
const c=vm.createContext({});vm.runInContext(fs.readFileSync('data/researcher_directory.js','utf8'),c);
const directory=c.RESEARCHER_DIRECTORY;
if(directory.registry_generation!==p.registry_generation)throw Error('preview_registry_conflict');
const indexBody={schema_version:4,release_id:p.release_id,registry_generation:p.registry_generation,
  roster_id:sources.roster_id,directory_id:hash(directory),public_activation:false,
  operations:{assess_person_ids:[],assessment_scope_ids:[]},
  endpoint:'https://funding-finder-researchers.urochestercheme.workers.dev/admin/api/contextual',
  source_fields:SOURCE_FIELDS,condition_fields:CONDITION_FIELDS,
  runtime:{contextual_engine:hash(fs.readFileSync('assets/contextual-team-engine.js','utf8')),
    contextual_client:hash(fs.readFileSync('assets/contextual-team-client.js','utf8'))},
  scopes:sources.scopes.map(s=>({id:s.id,parent_id:s.parent_id,scope_label:s.science.title,
    record_type:s.id===s.parent_id?'specific_parent':'publishable_child',engine:'contextual-v1',
    state:s.state,source_id:s.source_id,catalog_source_id:s.catalog_source_id,currentness:s.currentness}))};
const index={...indexBody,generation_id:hash(indexBody)},files={},originals={};
const add=(name,bytes,original=null)=>{
  if(files[name])return;
  const raw=/\.(js|css|html|svg)$/.test(name)?Buffer.from(Buffer.from(bytes).toString('utf8').replace(/\r\n/g,'\n')):Buffer.from(bytes);
  const compressed=gzipSync(raw,{level:9,mtime:0});
  files[name]={sha256:createHash('sha256').update(raw).digest('hex'),bytes:raw.length,gzip_bytes:compressed.length,
    content_type:name.endsWith('.js')?'text/javascript; charset=utf-8':name.endsWith('.css')?'text/css; charset=utf-8':name.endsWith('.html')?'text/html; charset=utf-8':name.endsWith('.png')?'image/png':name.endsWith('.ico')?'image/x-icon':name.endsWith('.jpg')?'image/jpeg':'image/svg+xml',
    gzip_base64:compressed.toString('base64')};
  if(original)originals[name]=createHash('sha256').update(original).digest('hex');
  // Keep changed application code readable in the prerequisite PR. Large public
  // data stays compressed; it is never used as executable helper code.
  const existing=path.join(helper,name);
  if(!name.startsWith('data/')&&(!fs.existsSync(existing)||!fs.readFileSync(existing).equals(raw))){
    const source=path.join(helper,'workers/researcher-intake/preview-source',name);
    fs.mkdirSync(path.dirname(source),{recursive:true});fs.writeFileSync(source,raw);
  }
};
const boundary=fs.readFileSync('outputs/contextual-stage-b/validation-boundary.js','utf8')
  .replace("url.origin===location.origin||(url.origin==='https://funding-finder-researchers.urochestercheme.workers.dev'&&url.pathname.startsWith('/admin/api/contextual/'))",
    "url.origin===location.origin&&(url.pathname.startsWith('/admin/contextual/preview/')||url.pathname.startsWith('/admin/api/contextual/'))");
add('assets/contextual-preview-observer.js',boundary);
add('data/opportunity_team_index.js','globalThis.OPPORTUNITY_TEAM_INDEX='+canonical(index)+';\n');
const needed=new Set(['assets/contextual-team-engine.js','assets/contextual-team-client.js','data/opportunities.js','data/subtopics.js']);
for(const page of ['match_explorer.html','team_match.html']){
  const original=fs.readFileSync(page,'utf8');
  let html=original.replace('<head>','<head>\n<base href="/admin/contextual/preview/">\n<script src="assets/contextual-preview-observer.js"></script>');
  html=html.replace(/(<meta name="opportunity-team-generation" content=")[a-f0-9]{64}("\s*\/?>)/,'$1'+index.generation_id+'$2');
  html=html.replace(/(data\/opportunity_team_index\.js\?v=)[a-f0-9]{64}/,'$1'+index.generation_id);
  html=html.replace(/((?:\.\/)?(assets\/[^"?]+)\?v=)[a-f0-9]{64}/g,(whole,prefix,name)=>
    prefix+hash(fs.readFileSync(name,'utf8').replace(/\r\n/g,'\n')));
  // Keep scripts and presentation. Restrict network connections for this private
  // preview so unrelated hosted services cannot spend or send subscriber mail.
  html=html.replace(/connect-src [^;]*;/,"connect-src 'self';");
  for(const m of html.matchAll(/(?:src|href)="(?:\.\/)?((?:assets|data)\/[^"?#]+)(?:[^" ]*)"/g))needed.add(m[1]);
  add(page,html,original);
}
for(const name of [...needed]){
  if(files[name])continue;
  if(!fs.existsSync(name))throw Error('missing_preview_asset:'+name);
  add(name,fs.readFileSync(name));
}
// Styles may reference the existing logo/icons. Never sweep caches or proposals.
for(const name of Object.keys(files).filter(n=>n.endsWith('.css'))){
  for(const m of fs.readFileSync(name,'utf8').matchAll(/url\(['"]?([^)'"?#]+)(?:[^)'" ]*)['"]?\)/g)){
    const ref=path.posix.normalize(path.posix.join(path.posix.dirname(name),m[1]));
    if(ref.startsWith('assets/')&&fs.existsSync(ref)&&ref.endsWith('.svg'))add(ref,fs.readFileSync(ref));
  }
}
const body={version:'contextual-restricted-preview-v1',release_id:p.release_id,index_generation:index.generation_id,
  registry_generation:p.registry_generation,public_activation:false,provider_results:0,
  base_path:'/admin/contextual/preview/',original_html_sha256:originals,files};
const bundle={...body,bundle_id:hash(body)};
fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,canonical(bundle)+'\n');
const receipt={...body,files:Object.fromEntries(Object.entries(files).map(([k,{gzip_base64,...v}])=>[k,v])),bundle_id:bundle.bundle_id,
  total_bytes:Object.values(files).reduce((n,v)=>n+v.bytes,0),total_gzip_bytes:Object.values(files).reduce((n,v)=>n+v.gzip_bytes,0)};
fs.writeFileSync('outputs/contextual-stage-b/phase2-preview-receipt.json',JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify({bundle_id:bundle.bundle_id,files:Object.keys(files).length,bytes:receipt.total_bytes,gzip_bytes:receipt.total_gzip_bytes,target}));
