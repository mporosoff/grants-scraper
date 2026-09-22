// Real Worker/SQLite coordination; synthetic callback envelopes test transport,
// never scientific acceptance. No provider, external network or browser UI.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {ContextualStore,createContextualHandler} from '../../workers/researcher-intake/src/contextual.js';
import {previewResponse} from '../../workers/researcher-intake/src/contextual-preview.js';
import {ITERATION3_JS} from '../../workers/researcher-intake/src/contextual-iteration3-console.js';
import {shellDom} from '../helpers/shell-dom.mjs';
const plan=JSON.parse(fs.readFileSync('config/contextual_team/iteration3-authority-v1.json'));
const source=JSON.parse(fs.readFileSync('config/contextual_team/iteration3-source-inputs-v1.json'));
const i2=JSON.parse(fs.readFileSync('config/contextual_team/iteration2-authority-v1.json'));
const oldBundle=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration2-preview-v1.json'));
const overlay=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration3-preview-v1.json'));
const host='https://example.test',sha='a'.repeat(40);
const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
const hash=v=>createHash('sha256').update(JSON.stringify(canonical(v))).digest('hex');
function fixture(){
  const db=new DatabaseSync(':memory:');
  for(const p of ['0005_contextual_validation_jobs.sql','0006_contextual_trial_controls.sql'])db.exec(fs.readFileSync('workers/researcher-intake/migrations/'+p,'utf8'));
  const statement=(sql,args=[])=>({bind:(...values)=>statement(sql,values),first:async()=>db.prepare(sql).get(...args)||null,
    run:async()=>({meta:{changes:db.prepare(sql).run(...args).changes}})});
  const store=new ContextualStore({prepare:sql=>statement(sql)}),calls=[],clock={value:new Date('2026-09-22T17:00:00Z')};
  const fetchImpl=async(url,o)=>{calls.push({url,o});return url.includes('/actions/runs/')
    ?Response.json({path:'.github/workflows/team-recommender-offline.yml',event:'repository_dispatch',head_branch:'main',head_sha:sha})
    :new Response(null,{status:204});};
  const handler=createContextualHandler({storeFactory:()=>store,now:()=>clock.value,fetchImpl,
    authenticateAdmin:async r=>{if(r.headers.get('x-access')!=='yes')throw Object.assign(Error(),{code:'access',status:403});return 'fixture';},
    authenticateInternal:async r=>{if(r.headers.get('x-internal')!=='yes')throw Object.assign(Error(),{code:'internal',status:403});}});
  const request=(path,value,internal=false)=>new Request(host+path,{method:value?'POST':'GET',headers:{Origin:host,
    [internal?'x-internal':'x-access']:'yes','Content-Type':'application/json'},...(value?{body:JSON.stringify(value)}:{})});
  const job={release_id:plan.release_id,scope_id:plan.first_scope_id,person_id:''};
  const scope=source.scopes.find(s=>s.id===job.scope_id);
  return {db,store,calls,clock,handler,request,job,scope,env:{GITHUB_REPOSITORY:'fixture/repo',GITHUB_DISPATCH_TOKEN:'fixture-only'},
    enable:()=>store.setControls(plan.release_id,{cached_enabled:true,new_paid_enabled:true},'now')};
}
function graphFor(f,state='no_supported_group_in_assessed_set'){
  const candidates=state==='no_supported_group_in_checked_candidates'?[{candidate_id:'g01',member_ids:['synthetic-one','synthetic-two']}]:[];
  const integrity={version:'contextual-production-integrity-v1',selection_version:'contextual-integrity-candidates-v1',
    independent_evaluation:false,human_labels_added:0,source_sha256:f.scope.source_id,base_graph_id:'b'.repeat(64),
    base_graph_sha256:'c'.repeat(64),candidate_groups:candidates,candidate_list_sha256:hash(candidates),
    groups:candidates.map(c=>({candidate_id:c.candidate_id,status:'unsupported',members:c.member_ids.map(person_id=>({person_id}))})),
    disposition:candidates.length?'complete':'not_applicable_no_candidates'};
  const g={version:'contextual-audited-graph-v4',state,snapshot_id:plan.release_id,
    registry_generation:source.registry_generation,roster_id:source.roster_id,source_id:f.scope.source_id,
    scope:{id:f.scope.id,parent_id:f.scope.parent_id},base_graph_id:integrity.base_graph_id,base_graph_sha256:integrity.base_graph_sha256,
    integrity,provenance:{integrity_version:integrity.version,integrity_sha256:hash(integrity)}};
  g.graph_id=hash(g);return g;
}
function rehash(g){g.integrity&&(g.provenance.integrity_sha256=hash(g.integrity));delete g.graph_id;g.graph_id=hash(g);return g;}
async function owner(f){
  const job={...f.job,job_id:hash([f.job.release_id,f.job.scope_id,''])};
  assert(await f.store.insert(job,'now'));await f.store.start(job.job_id,'123',sha,'now');
  return {job_id:job.job_id,release_id:job.release_id,run_id:'123',code_sha:sha};
}
function trustedCurrent(job,clock,inputs=source){
  const output=[];
  class FixedDate extends Date {constructor(...args){super(...(args.length?args:[clock]));} static now(){return +new Date(clock);}}
  const context=vm.createContext({Date:FixedDate,vm,process:{argv:['node','check','fixture-job']},console:{log:v=>output.push(JSON.parse(v))},
    fs:{readFileSync:(path,...args)=>path==='fixture-job'?JSON.stringify(job):path==='config/contextual_team/iteration3-source-inputs-v1.json'
      ?JSON.stringify(inputs):fs.readFileSync(path,...args)}});
  vm.runInContext(fs.readFileSync('tools/contextual_currentness.mjs','utf8').replace(/^import .+;\r?\n/gm,''),context);
  assert.equal(output.length,1);return output[0];
}

test('trusted currentness and Worker agree at the refreshed receipt boundary for all three scopes',async()=>{
  for(const scope of source.scopes){
    assert.equal(scope.currentness.not_after,'2026-09-24T17:00:00Z');
    for(const [clock,expected] of [['2026-09-22T17:00:00Z',true],['2026-09-24T16:59:59.999Z',true],['2026-09-24T17:00:00Z',false]]){
      const f=fixture(),job={...f.job,scope_id:scope.id};f.clock.value=new Date(clock);
      const result=trustedCurrent(job,clock);
      assert.equal(result.action_current,expected);assert.equal(result.scope_id,scope.id);assert.equal(result.clock,f.clock.value.toISOString());
      const read=await (await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(job)),f.env)).json();
      assert.equal(read.state,expected?'unassessed':'action_blocked');assert.equal(f.calls.length,0);
    }
  }
});

test('trusted check rejects extra scope, person and invalidated or withdrawn source without provider activity',()=>{
  const job={release_id:plan.release_id,scope_id:'332894',person_id:''},clock='2026-09-22T17:00:00Z';
  for(const wrong of [{...job,scope_id:'341997'},{...job,scope_id:'344592:ab-0025'},{...job,person_id:'extension'},
    {...job,release_id:'f'.repeat(64)}])assert.throws(()=>trustedCurrent(wrong,clock));
  for(const change of [s=>{s.currentness.not_after='invalid';},s=>{s.currentness.record.status='withdrawn';},
    s=>{s.currentness.parent.status='withdrawn';}]){
    const copy=structuredClone(source);change(copy.scopes.find(s=>s.id===job.scope_id));
    assert.equal(trustedCurrent(job,clock,copy).action_current,false);
  }
  for(const change of [s=>{s.action_current=false;},s=>{s.state='forecasted';}]){
    const copy=structuredClone(source);change(copy.scopes.find(s=>s.id===job.scope_id));
    assert.throws(()=>trustedCurrent(job,clock,copy),/iteration3_only_named_corrective_build/);
  }
});

test('I3 routes require Access, load without dispatch and expose only three named scopes with paid OFF',async()=>{
  const f=fixture();
  for(const p of ['/admin/contextual/iteration3-control','/admin/contextual/iteration3-control.js',
    '/admin/contextual/iteration3/match_explorer.html','/admin/api/contextual/manifest?iteration=3']){
    assert.equal((await f.handler(new Request(host+p),f.env)).status,403);
    const r=await f.handler(f.request(p),f.env);assert.equal(r.status,200);assert.equal(r.headers.get('Cache-Control'),'no-store');
  }
  const manifest=await (await f.handler(f.request('/admin/api/contextual/manifest?iteration=3'),f.env)).json();
  assert.deepEqual(manifest.scopes.map(s=>s.id),['332894','345241:tdac-baa-004','363268']);
  assert.equal(manifest.release_id,plan.release_id);assert.equal(manifest.public_activation,false);
  const c=await (await f.handler(f.request('/admin/api/contextual/controls?release_id='+plan.release_id),f.env)).json();
  assert.equal(c.new_paid_enabled,0);assert.equal(c.cached_enabled,1);assert.equal(c.maximum_workflows,3);assert.equal(c.maximum_concurrency,1);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).status,403);
  assert.equal(f.calls.length,0);assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs').get().n,0);
});

test('finite I3 controls cannot enable other cases, extensions, legacy controls or public activation',async()=>{
  const f=fixture();await f.enable();
  for(const bad of [{...f.job,scope_id:'341997'},{...f.job,scope_id:'344592:ab-0025'},
    {...f.job,scope_id:'not-selected'},{...f.job,person_id:'urh-000001'},{...f.job,prompt:'extra'}])
    assert((await f.handler(f.request('/admin/api/contextual/jobs',bad),f.env)).status>=400);
  assert.equal((await f.store.controls(i2.release_id)).new_paid_enabled,0);
  assert.equal(f.calls.length,0);
  const response=await f.handler(new Request(host+'/admin/api/contextual/controls?release_id='+plan.release_id,{method:'POST',
    headers:{'x-access':'yes',Origin:'https://foreign.test','Content-Type':'application/json'},body:JSON.stringify({cached_enabled:true,new_paid_enabled:true})}),f.env);
  assert.equal(response.status,403);
});

test('concurrent I3 requests dispatch once; a completed failure cannot be replayed or rekeyed',async()=>{
  const f=fixture();await f.enable();
  const results=await Promise.all(Array.from({length:6},()=>f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)));
  assert.equal(results.filter(r=>r.status===202).length,1);assert.equal(f.calls.length,1);
  const row=f.db.prepare('SELECT * FROM contextual_validation_jobs').get();
  await f.store.start(row.job_id,'123',sha,'now');await f.store.finish(row.job_id,'123',sha,JSON.stringify({result:{state:'failed'}}),'now');
  const before=await f.store.byId(row.job_id);
  for(let i=0;i<3;i++)assert.equal((await (await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).json()).state,'failed');
  assert.equal(f.calls.length,1);assert.deepEqual(await f.store.byId(row.job_id),before);
  const next={...f.job,scope_id:'345241:tdac-baa-004'};
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',next),f.env)).status,409);
});

test('all releases share the active slot; unknown historical exposure stays protected',async()=>{
  const f=fixture();await f.enable();
  const old={release_id:i2.release_id,scope_id:'341997',person_id:'',job_id:hash([i2.release_id,'341997',''])};
  assert(await f.store.insert(old,'prior'));await f.store.start(old.job_id,'35655451108','43c109c7616ccefb63122aaf73d3c12f69748901','prior');
  await f.store.uncertain(old.job_id,'prior');const before=await f.store.byId(old.job_id);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).status,429);
  assert.deepEqual(await f.store.byId(old.job_id),before);assert.equal(f.calls.length,0);
});

test('exact checked-candidate abstention is durable and opens the next finite scope without a result retry',async()=>{
  const f=fixture(),stamp=await owner(f),value={...stamp,result:graphFor(f,'no_supported_group_in_checked_candidates')};
  for(let i=0;i<2;i++)assert.equal((await f.handler(f.request('/internal/contextual/result',value,true),f.env)).status,200);
  const row=await f.store.byId(stamp.job_id);assert.equal(row.active_slot,null);assert.deepEqual(JSON.parse(row.result_json),value);
  const read=await (await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.job)),f.env)).json();
  assert.equal(read.state,'no_supported_group_in_checked_candidates');assert.deepEqual(read.result,value.result);
  await f.enable();assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',{...f.job,scope_id:'345241:tdac-baa-004'}),f.env)).status,202);
  assert.equal(f.calls.filter(c=>c.url.endsWith('/dispatches')).length,1);
});

test('I3 graph identity, provenance, incomplete negatives and old v3 fallback are rejected before persistence',async()=>{
  const mutations=[g=>{g.version='contextual-audited-graph-v3';},g=>{delete g.integrity;},
    g=>{g.integrity.groups=[];},g=>{g.integrity.groups[0].members.pop();},g=>{g.integrity.groups[0].status='supported';},
    g=>{g.integrity.candidate_groups[0].candidate_id='missing';},g=>{g.source_id='f'.repeat(64);},g=>{g.scope.id='363268';}];
  for(const mutate of mutations){
    const f=fixture(),stamp=await owner(f),g=graphFor(f,'no_supported_group_in_checked_candidates');mutate(g);rehash(g);
    const before=await f.store.byId(stamp.job_id);
    assert((await f.handler(f.request('/internal/contextual/result',{...stamp,result:g},true),f.env)).status>=400);
    assert.deepEqual(await f.store.byId(stamp.job_id),before);
  }
  const f=fixture(),stamp=await owner(f),g=graphFor(f);g.graph_id='f'.repeat(64);
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...stamp,result:g},true),f.env)).status,400);
  assert.equal((await f.store.byId(stamp.job_id)).result_json,null);
});

test('explicit complete verifier abstentions retain their v3 identity without an integrity certificate or composition',async()=>{
  for(const state of ['unsuitable','insufficient_source','needs_scope_selection']){
    const f=fixture(),stamp=await owner(f),g=graphFor(f);
    g.state=state;g.version='contextual-audited-graph-v3';delete g.integrity;delete g.base_graph_id;delete g.base_graph_sha256;
    g.provenance={adapter_version:g.version,all_pair_decisions_retained:true,independent_checker_used_for_admission:false};rehash(g);
    const value={...stamp,result:g};
    assert.equal((await f.handler(f.request('/internal/contextual/result',value,true),f.env)).status,200);
    const read=await (await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.job)),f.env)).json();
    assert.equal(read.state,state);assert.deepEqual(read.result,g);assert.equal(read.result.integrity,undefined);
    assert.equal((await f.store.byId(stamp.job_id)).active_slot,null);
    const bad=fixture(),badStamp=await owner(bad);g.provenance.all_pair_decisions_retained=false;rehash(g);
    assert.equal((await bad.handler(bad.request('/internal/contextual/result',{...badStamp,result:g},true),bad.env)).status,400);
    assert.equal((await bad.store.byId(badStamp.job_id)).result_json,null);
    assert.equal((await bad.handler(bad.request('/internal/contextual/result',{...badStamp,result:{state}},true),bad.env)).status,400);
  }
});

test('I3 Unicode callback uses existing 384 KiB graph and 524288-byte envelope limits without changing I2',async()=>{
  const f=fixture(),stamp=await owner(f),g=graphFor(f);g.wire_boundary_fixture='';
  const fill=393216-Buffer.byteLength(JSON.stringify(g));g.wire_boundary_fixture='α'.repeat(Math.floor(fill/2))+'x'.repeat(fill%2);rehash(g);
  assert.equal(Buffer.byteLength(JSON.stringify(g)),393216);
  const value={...stamp,result:g,stage_timings:[{stage:'synthetic',seconds:123.4}]};
  assert.equal((await f.handler(f.request('/internal/contextual/result',value,true),f.env)).status,200);
  const stored=await f.store.byId(stamp.job_id);
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...value,padding:'x'.repeat(524288)},true),f.env)).status,413);
  assert.deepEqual(await f.store.byId(stamp.job_id),stored);
  const over=fixture(),other=await owner(over),oversize=graphFor(over);oversize.wire_boundary_fixture='x'.repeat(393216);rehash(oversize);
  assert.equal((await over.handler(over.request('/internal/contextual/result',{...other,result:oversize},true),over.env)).status,413);
});

test('SQL enforces at most three immutable I3 jobs and source currentness blocks future builds',async()=>{
  const f=fixture();
  for(const [i,scope] of source.scopes.entries()){
    const job={...f.job,scope_id:scope.id,job_id:hash([plan.release_id,scope.id,''])};
    assert(await f.store.insert(job,'now'));await f.store.start(job.job_id,String(i+1),sha,'now');
    await f.store.finish(job.job_id,String(i+1),sha,JSON.stringify({result:{state:'failed'}}),'now');
  }
  assert.equal(await f.store.insert({...f.job,scope_id:'fourth',job_id:hash([plan.release_id,'fourth',''])},'now'),false);
  assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs WHERE release_id=?').get(plan.release_id).n,3);
  const future=fixture();await future.enable();future.clock.value=new Date('2100-01-01T00:00:00Z');
  assert.equal((await (await future.handler(future.request('/admin/api/contextual/jobs',future.job),future.env)).json()).state,'action_blocked');
  assert.equal(future.calls.length,0);
});

test('new overlay serves exact I3 runtime identities while historical I2 assets remain separate',()=>{
  assert.equal(overlay.base_path,'/admin/contextual/iteration3/');assert.equal(overlay.historical_iteration2_bundle_id,oldBundle.bundle_id);
  assert.equal(overlay.release_id,plan.release_id);assert.equal(overlay.provider_results,0);assert.equal(overlay.public_activation,false);
  const {bundle_id,...content}=overlay;assert.equal(hash(content),bundle_id);
  for(const name of ['contextual-team-client.js','contextual-team-engine.js','contextual-preview-observer.js','opportunity-team-panel.js']){
    const file=overlay.files['assets/'+name],raw=gunzipSync(Buffer.from(file.gzip_base64,'base64'));
    assert.equal(raw.toString(),fs.readFileSync('workers/researcher-intake/iteration2-source/assets/'+name,'utf8'));
    assert.equal(createHash('sha256').update(raw).digest('hex'),file.sha256);
    assert.equal(previewResponse('/admin/contextual/iteration3/assets/'+name).headers.get('X-Content-SHA256'),file.sha256);
    assert.equal(previewResponse('/admin/contextual/iteration2/assets/'+name).headers.get('X-Content-SHA256'),oldBundle.files['assets/'+name].sha256);
  }
  assert.equal(previewResponse('/admin/contextual/iteration30/assets/contextual-team-client.js'),null);
});

test('control page load performs only manifest and control reads, never a build',async()=>{
  const d=shellDom('<html><body><p id="status"></p><button id="enable"></button><button id="disable"></button><ul id="cases"></ul></body></html>'),calls=[];
  d.context.fetch=async(url,o)=>{calls.push({url,o});return Response.json(url.includes('manifest')?
    {release_id:plan.release_id,public_activation:false,scopes:source.scopes.map(s=>({id:s.id,title:s.science.title,state:s.state}))}:
    {new_paid_enabled:0,cached_enabled:1});};
  vm.createContext(d.context);vm.runInContext(ITERATION3_JS,d.context);
  for(let i=0;i<20;i++)await Promise.resolve();
  assert.equal(calls.length,2);assert(calls.every(c=>!c.o.method));assert(!calls.some(c=>c.url.includes('/jobs')));
  assert.match(d.document.getElementById('status').textContent,/New paid builds disabled/);
  assert.equal(d.document.getElementById('cases').querySelectorAll('li').length,3);
});
