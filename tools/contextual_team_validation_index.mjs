// Build an unactivated validation index; no generated team inventory or provider.
import fs from 'node:fs';
import {hash,SOURCE_FIELDS,CONDITION_FIELDS} from './contextual_team_inputs.mjs';
const folder='docs/team-recommender/contextual-stage-b';
const lock=JSON.parse(fs.readFileSync(folder+'/input-lock-v1.json'));
const snapshot=JSON.parse(fs.readFileSync('outputs/contextual-stage-b/snapshot-'+lock.snapshot_id+'.json'));
const body={schema_version:4,release_id:snapshot.snapshot_id,registry_generation:snapshot.registry_generation,
  roster_id:snapshot.roster_id,directory_id:snapshot.directory_id,public_activation:false,
  endpoint:'https://funding-finder-researchers.urochestercheme.workers.dev/admin/api/contextual',
  source_fields:SOURCE_FIELDS,condition_fields:CONDITION_FIELDS,
  runtime:{contextual_engine:hash(fs.readFileSync('assets/contextual-team-engine.js','utf8')),
    contextual_client:hash(fs.readFileSync('assets/contextual-team-client.js','utf8'))},
  scopes:snapshot.scopes.map(s=>({id:s.id,parent_id:s.parent_id,scope_label:s.science.title,
    record_type:s.id===s.parent_id?'specific_parent':'publishable_child',engine:'contextual-v1',
    state:s.state,source_id:s.source_id}))};
const index={...body,generation_id:hash(body)};
const target='outputs/contextual-stage-b/validation-index-'+index.generation_id+'.json';
fs.writeFileSync(target,JSON.stringify(index,null,2)+'\n');
const script=target.replace(/\.json$/,'.js');
fs.writeFileSync(script,'globalThis.OPPORTUNITY_TEAM_INDEX='+JSON.stringify(index)+';\n');
const preview='outputs/contextual-stage-b/validation-app.html';
const original=fs.readFileSync('match_explorer.html','utf8');
let html=original.replace('<head>','<head>\n  <base href="/">\n  <script src="/outputs/contextual-stage-b/validation-boundary.js"></script>');
html=html.replace(/(<meta name="opportunity-team-generation" content=")[a-f0-9]{64}("\s*\/?>)/,'$1'+index.generation_id+'$2');
html=html.replace(/\.\/data\/opportunity_team_index\.js\?v=[a-f0-9]{64}/,'/'+script);
fs.writeFileSync(preview,html);
// Instrument this private preview only. Other hosted services are blocked so
// the validation cannot borrow an unrelated provider allowance or send mail.
fs.writeFileSync('outputs/contextual-stage-b/validation-boundary.js',`(()=>{
  const original=globalThis.fetch.bind(globalThis),calls=[];let initial=null;
  const output=()=>{if(!document.body)return;let node=document.getElementById('contextual-validation-boundary');if(!node){node=document.createElement('output');node.id='contextual-validation-boundary';node.hidden=true;document.body.appendChild(node);}
    node.textContent=JSON.stringify({calls,initial,heap:performance.memory?.usedJSHeapSize??null});};
  globalThis.fetch=async(input,options={})=>{const url=new URL(typeof input==='string'?input:input.url,location.href),method=options.method||'GET';
    const allowed=url.origin===location.origin||(url.origin==='https://funding-finder-researchers.urochestercheme.workers.dev'&&url.pathname.startsWith('/admin/api/contextual/'));
    const row={origin:url.origin,path:url.pathname,method,allowed,started:performance.now()};calls.push(row);
    if(!allowed){output();throw Error('Private validation blocks unrelated service traffic.');}
    try{const response=await original(input,options);row.status=response.status;return response;}finally{row.duration=performance.now()-row.started;output();}};
  document.addEventListener('click',event=>{if(event.target.closest('[data-opportunity-team]')&&!initial){initial={time:performance.now(),heap:performance.memory?.usedJSHeapSize??null};output();}},true);
  addEventListener('DOMContentLoaded',output);
})();\n`);
console.log(JSON.stringify({index:target,preview,generation_id:index.generation_id,release_id:index.release_id,scopes:index.scopes.length,public_activation:false}));
