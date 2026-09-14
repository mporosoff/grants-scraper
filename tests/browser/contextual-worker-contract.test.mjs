import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {ContextualStore,createContextualHandler} from '../../workers/researcher-intake/src/contextual.js';
import {createHandler} from '../../workers/researcher-intake/src/index.js';
const configuration=JSON.parse(fs.readFileSync(new URL('../../config/contextual_team/inputs-v1.json',import.meta.url)));
const option1=JSON.parse(fs.readFileSync(new URL('../../config/contextual_team/option1-v1.json',import.meta.url)));
const phase2=JSON.parse(fs.readFileSync(new URL('../../config/contextual_team/phase2-v1.json',import.meta.url)));
const capacity=JSON.parse(fs.readFileSync(new URL('../../config/contextual_team/phase2-output-capacity-v2.json',import.meta.url)));
const migration=fs.readFileSync(new URL('../../workers/researcher-intake/migrations/0005_contextual_validation_jobs.sql',import.meta.url),'utf8');
const hash=x=>createHash('sha256').update(JSON.stringify(x)).digest('hex');
class Statement {
  constructor(db,sql,values=[]){Object.assign(this,{db,sql,values});}
  bind(...values){return new Statement(this.db,this.sql,values);}
  async first(){return this.db.prepare(this.sql).get(...this.values)||null;}
  async run(){return {meta:{changes:this.db.prepare(this.sql).run(...this.values).changes}};}
}
const host='https://funding-finder-researchers.urochestercheme.workers.dev';
function fixture(){
  const db=new DatabaseSync(':memory:');db.exec(migration);
  db.exec(fs.readFileSync(new URL('../../workers/researcher-intake/migrations/0006_contextual_trial_controls.sql',import.meta.url),'utf8'));
  const store=new ContextualStore({prepare:s=>new Statement(db,s)}),calls=[];
  const clock={value:new Date('2026-09-12T16:00:00Z')};
  const fetchImpl=async(url,options)=>{
    calls.push({url,options});
    if(url.includes('/actions/runs/'))return Response.json({path:'.github/workflows/team-recommender-offline.yml',event:'workflow_dispatch',head_branch:'main',head_sha:'a'.repeat(40)});
    return new Response(null,{status:204});
  };
  const dependencies={storeFactory:()=>store,fetchImpl,now:()=>clock.value,
    authenticateAdmin:async req=>{if(req.headers.get('x-test-access')!=='yes')throw Object.assign(Error(),{code:'access',status:403});return 'fixture-admin';},
    authenticateInternal:async req=>{if(req.headers.get('x-test-workflow')!=='yes')throw Object.assign(Error(),{code:'internal',status:403});}};
  const handler=createContextualHandler(dependencies);
  const env={GITHUB_REPOSITORY:'mporosoff/grants-scraper',GITHUB_DISPATCH_TOKEN:'fixture-token'};
  const request=(path,data,internal=false)=>new Request(host+path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json',
    Origin:host,[internal?'x-test-workflow':'x-test-access']:'yes'},...(data?{body:JSON.stringify(data)}:{})});
  const value={release_id:option1.release_id,scope_id:'332894',person_id:''};
  return {db,store,calls,clock,env,request,value,handler,dependencies};
}

test('only the named completed mechanical failure permits one immutable corrective job; GET never dispatches',async()=>{
  const f=fixture(),value={release_id:phase2.release_id,scope_id:capacity.repair_scope_id,person_id:''};
  const first={...value,scope_id:phase2.first_scope_id};first.job_id=hash([first.release_id,first.scope_id,'']);
  await f.store.insert(first,'now');await f.store.start(first.job_id,'first','a'.repeat(40),'now');
  await f.store.finish(first.job_id,'first','a'.repeat(40),JSON.stringify({result:{state:'ready_with_gaps'}}),'now');
  const original={...value,job_id:capacity.repair_original_job_id};await f.store.insert(original,'now');
  await f.store.start(original.job_id,capacity.repair_original_run_id,capacity.repair_original_code_sha,'now');
  const result={result:{state:'failed',reason:'incomplete_response',scope_id:value.scope_id},
    attempts:capacity.prior_attempts,charged_microusd:capacity.prior_cumulative_microusd};
  await f.store.finish(original.job_id,capacity.repair_original_run_id,capacity.repair_original_code_sha,JSON.stringify(result),'now');
  const before=await f.store.byId(original.job_id);
  for(let i=0;i<3;i++){
    const response=await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(value)),f.env);
    assert.equal((await response.json()).state,'unassessed');
  }
  assert.equal(f.calls.length,0);
  const responses=await Promise.all(Array.from({length:8},()=>f.handler(f.request('/admin/api/contextual/jobs',value),f.env)));
  assert.equal(f.calls.length,1);assert.equal(responses.filter(r=>r.status===202).length,1);
  assert.deepEqual(JSON.parse(JSON.parse(f.calls[0].options.body).client_payload.contextual_job),{...value,job_id:capacity.repair_job_id});
  assert.deepEqual(await f.store.byId(original.job_id),before);
  await f.store.start(capacity.repair_job_id,'repair','b'.repeat(40),'later');
  await f.store.finish(capacity.repair_job_id,'repair','b'.repeat(40),JSON.stringify({result:{state:'failed',reason:'incomplete_response'}}),'later');
  for(let i=0;i<3;i++)assert.equal((await (await f.handler(f.request('/admin/api/contextual/jobs',value),f.env)).json()).state,'failed');
  assert.equal(f.calls.length,1);assert.deepEqual(await f.store.byId(original.job_id),before);
  const last={...value,scope_id:'351715'};
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',last),f.env)).status,202);
  assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs').get().n,4);
});

test('uncertain, unfavorable, wrong-owner and other failures never select the named repair',async()=>{
  for(const variant of ['uncertain','unfavorable','wrong-run','wrong-code','wrong-reason','wrong-attempts']){
    const f=fixture(),value={release_id:phase2.release_id,scope_id:capacity.repair_scope_id,person_id:''};
    const original={...value,job_id:capacity.repair_original_job_id};await f.store.insert(original,'now');
    const run=variant==='wrong-run'?'123':capacity.repair_original_run_id;
    const sha=variant==='wrong-code'?'a'.repeat(40):capacity.repair_original_code_sha;
    await f.store.start(original.job_id,run,sha,'now');
    const state=variant==='uncertain'?'recovery_required':variant==='unfavorable'?'no_supported_group_in_assessed_set':'failed';
    await f.store.finish(original.job_id,run,sha,JSON.stringify({result:{state,reason:variant==='wrong-reason'?'other':'incomplete_response'},
      attempts:variant==='wrong-attempts'?670:capacity.prior_attempts,charged_microusd:capacity.prior_cumulative_microusd}),'now');
    for(let n=0;n<3;n++){
      const result=await (await f.handler(f.request('/admin/api/contextual/jobs',value),f.env)).json();
      assert.equal(result.job_id,original.job_id);assert.equal(result.state,state);
    }
    assert.equal(f.calls.length,0,variant);
  }
});

test('operator control and script remain Access protected and loading them cannot claim a job',async()=>{
  const f=fixture();
  for(const path of ['/admin/contextual','/admin/contextual/app.js','/admin/contextual/access','/admin/contextual/access.js']){
    assert.equal((await f.handler(new Request(host+path),f.env)).status,403);
    const r=await f.handler(f.request(path),f.env);assert.equal(r.status,200);
    assert.match(r.headers.get('Content-Security-Policy'),/connect-src 'self'/);
    const text=await r.text();assert(!text.includes('fixture-token'));
  }
  assert.equal(f.calls.length,0);assert.equal(f.db.prepare('SELECT count(*) AS n FROM contextual_validation_jobs').get().n,0);
});

test('only the fixed local preview may use credentialed contextual CORS; administrator authentication is still mandatory',async()=>{
  const f=fixture(),url=host+'/admin/api/contextual/jobs';
  const call=(origin,access)=>new Request(url,{method:'POST',headers:{Origin:origin,'Content-Type':'text/plain;charset=UTF-8',...(access?{'x-test-access':'yes'}:{})},body:JSON.stringify(f.value)});
  assert.equal((await f.handler(call('http://127.0.0.1:8876',false),f.env)).status,403);
  assert.equal(f.calls.length,0);
  for(const origin of ['https://evil.example','http://localhost:8876','http://127.0.0.1:9999']){
    const denied=await f.handler(call(origin,true),f.env);assert.equal(denied.status,403);assert.equal(denied.headers.get('Access-Control-Allow-Origin'),null);
  }
  const accepted=await f.handler(call('http://127.0.0.1:8876',true),f.env);
  assert.equal(accepted.status,202);assert.equal(accepted.headers.get('Access-Control-Allow-Origin'),'http://127.0.0.1:8876');
  assert.equal(accepted.headers.get('Access-Control-Allow-Credentials'),'true');assert.equal(f.calls.length,1);
});

test('Access guards every contextual route; ordinary app and status do not dispatch',async()=>{
  const f=fixture();const response=await f.handler(new Request(host+'/admin/api/contextual/manifest'),f.env);
  assert.equal(response.status,403);assert.equal(f.calls.length,0);
  for(const path of ['/admin/api/contextual/manifest','/admin/api/contextual/jobs?'+new URLSearchParams(f.value)])
    assert.equal((await f.handler(f.request(path),f.env)).status,200);
  assert.equal(f.calls.length,0);
  const actual=createHandler({storeFactory:()=>({})});
  assert.equal((await actual(new Request(host+'/admin/api/contextual/manifest'),{})).status,403);
  assert.equal(await f.handler(new Request(host+'/contextual/build',{method:'POST'}),f.env),null);
});

test('concurrent requests share one durable dispatch; reads and repeats cannot repurchase',async()=>{
  const f=fixture();const results=await Promise.all(Array.from({length:10},()=>f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env)));
  assert.equal(f.calls.length,1);assert.equal(results.filter(r=>r.status===202).length,1);
  assert.ok(results.every(r=>[200,202].includes(r.status)));
  assert.equal(f.calls[0].url,'https://api.github.com/repos/mporosoff/grants-scraper/dispatches');
  const sent=JSON.parse(f.calls[0].options.body);assert.equal(sent.event_type,'contextual-team-validation');
  assert.deepEqual(Object.keys(sent.client_payload),['contextual_job']);
  assert.deepEqual(JSON.parse(sent.client_payload.contextual_job),{...f.value,job_id:hash([f.value.release_id,f.value.scope_id,''])});
  const other={...f.value,scope_id:'363069'};
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',other),f.env)).status,409);
  await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.value)),f.env);assert.equal(f.calls.length,1);
});

test('unknown remote dispatch remains recovery-required through reloads and another visitor',async()=>{
  const f=fixture();let count=0;
  const h=createContextualHandler({...f.dependencies,fetchImpl:async()=>{count++;throw Error('fixture lost response');}});
  assert.equal((await h(f.request('/admin/api/contextual/jobs',f.value),f.env)).status,503);
  for(let i=0;i<3;i++)assert.equal((await (await h(f.request('/admin/api/contextual/jobs',f.value),f.env)).json()).state,'recovery_required');
  assert.equal(count,1);assert.equal((await h(f.request('/admin/api/contextual/jobs',{...f.value,scope_id:'363069'}),f.env)).status,409);
});

test('dispatch failure exposes only bounded status while keeping the same irreversible job',async()=>{
  for(const status of [403,422,503]){
    const f=fixture();let calls=0;
    const h=createContextualHandler({...f.dependencies,fetchImpl:async()=>{calls++;return new Response('private upstream message',{status});}});
    const response=await (await h(f.request('/admin/api/contextual/jobs',f.value),f.env)).json();
    assert.deepEqual(response.dispatch_diagnostic,{http_status:status,category:'remote_rejected'});
    assert(!JSON.stringify(response).includes('private'));
    for(let i=0;i<3;i++)assert.equal((await (await h(f.request('/admin/api/contextual/jobs',f.value),f.env)).json()).state,'recovery_required');
    assert.equal(calls,1);
  }
});

test('a trusted contextual repository dispatch can recover an unowned job but never replace its owner',async()=>{
  const f=fixture();await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env);
  const id=hash([f.value.release_id,f.value.scope_id,'']);await f.store.uncertain(id,f.clock.value.toISOString());
  const h=createContextualHandler({...f.dependencies,fetchImpl:async()=>Response.json({path:'.github/workflows/team-recommender-offline.yml',event:'repository_dispatch',head_branch:'main',head_sha:'a'.repeat(40)})});
  const stamp={release_id:f.value.release_id,job_id:id,run_id:'123',code_sha:'a'.repeat(40)};
  assert.equal((await h(f.request('/internal/contextual/start',stamp,true),f.env)).status,200);
  assert.equal((await h(f.request('/internal/contextual/start',{...stamp,run_id:'124'},true),f.env)).status,409);
  assert.equal((await f.store.byId(id)).run_id,'123');
});

test('currentness, parent ownership, bad IDs, stale generations and broad parents make no dispatch',async()=>{
  const f=fixture();
  for(const value of [{...f.value,scope_id:'344592'},{...f.value,scope_id:'not-a-call'},
      {...f.value,person_id:'not-a-person'},{...f.value,release_id:'0'.repeat(64)},{...f.value,prompt:'injected'}]){
    await f.handler(f.request('/admin/api/contextual/jobs',value),f.env);
  }
  assert.equal(f.calls.length,0);
  const scope=configuration.scopes.find(s=>s.id==='344592:ab-0025');
  assert.equal(scope.parent_id,'344592');
  f.clock.value=new Date('2100-01-01T00:00:00Z');
  const result=await (await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env)).json();
  assert.equal(result.state,'action_blocked');assert.equal(f.calls.length,0);
});

test('one exact trusted run owns a job and completion is immutable before later cache reads',async()=>{
  const f=fixture();await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env);
  const stamp={release_id:f.value.release_id,job_id:hash([f.value.release_id,f.value.scope_id,'']),run_id:'123',code_sha:'a'.repeat(40)};
  assert.equal((await f.handler(f.request('/internal/contextual/start',stamp,true),f.env)).status,200);
  assert.equal((await f.handler(f.request('/internal/contextual/start',{...stamp,run_id:'124'},true),f.env)).status,409);
  const value={...stamp,result:{scope_id:f.value.scope_id,state:'no_supported_group_in_assessed_set'},charged_microusd:100,attempts:1};
  for(let i=0;i<2;i++)assert.equal((await f.handler(f.request('/internal/contextual/result',value,true),f.env)).status,200);
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...value,result:{state:'failed'}},true),f.env)).status,409);
  const before=f.calls.length;
  const cached=await (await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env)).json();
  assert.equal(cached.state,'no_supported_group_in_assessed_set');assert.equal(f.calls.length,before);
});

test('extension claim is transactional and never becomes an unrestricted second queue',async()=>{
  const f=fixture(),base={...f.value,person_id:'urh-000001'};
  const first={...base,job_id:hash([base.release_id,base.scope_id,base.person_id])};
  assert.equal(await f.store.insert(first,'now'),true);
  f.db.prepare("UPDATE contextual_validation_jobs SET active_slot=NULL,state='complete'").run();
  const second={...first,person_id:'urh-000002',job_id:'b'.repeat(64)};
  assert.equal(await f.store.insert(second,'later'),false);
  assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs').get().n,1);
});

test('checkpointed provider uncertainty remains visible and owns the sole slot across callbacks, expiry and resumption',async()=>{
  const f=fixture();await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env);
  const stamp={release_id:f.value.release_id,job_id:hash([f.value.release_id,f.value.scope_id,'']),run_id:'123',code_sha:'a'.repeat(40)};
  await f.handler(f.request('/internal/contextual/start',stamp,true),f.env);
  const value={...stamp,result:{scope_id:f.value.scope_id,state:'recovery_required',reason:'uncertain provider request'},charged_microusd:20000,attempts:1};
  for(let i=0;i<3;i++){
    assert.equal((await f.handler(f.request('/internal/contextual/result',value,true),f.env)).status,200);
    const row=await f.store.byId(stamp.job_id);assert.equal(row.state,'recovery_required');assert.equal(row.active_slot,1);
    assert.deepEqual(JSON.parse(row.result_json),value);
    const before=f.calls.length;
    for(const request of [f.request('/admin/api/contextual/jobs',f.value),f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.value))])
      assert.equal((await (await f.handler(request,f.env)).json()).state,'recovery_required');
    assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',{...f.value,scope_id:'363069'}),f.env)).status,409);
    assert.equal(f.calls.length,before);
  }
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...value,result:{state:'failed'}},true),f.env)).status,409);
  assert.equal((await f.handler(f.request('/internal/contextual/start',{...stamp,run_id:'124'},true),f.env)).status,409);
  f.clock.value=new Date('2100-01-01T00:00:00Z');
  const expired=await (await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.value)),f.env)).json();
  assert.equal(expired.state,'recovery_required');assert.equal(expired.result.reason,value.result.reason);
  assert.equal((await f.store.byId(stamp.job_id)).active_slot,1);
});

test('reconciled failure and pre-dispatch budget deferral release their slot without reopening the logical job',async()=>{
  for(const state of ['failed','budget_limited']){
    const f=fixture();await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env);
    const stamp={release_id:f.value.release_id,job_id:hash([f.value.release_id,f.value.scope_id,'']),run_id:'123',code_sha:'a'.repeat(40)};
    await f.handler(f.request('/internal/contextual/start',stamp,true),f.env);
    const value={...stamp,result:{scope_id:f.value.scope_id,state},charged_microusd:220,attempts:1};
    await f.handler(f.request('/internal/contextual/result',value,true),f.env);
    assert.equal((await f.store.byId(stamp.job_id)).active_slot,null);
    const before=f.calls.length;
    for(let i=0;i<3;i++)assert.equal((await (await f.handler(f.request('/admin/api/contextual/jobs',f.value),f.env)).json()).state,state);
    assert.equal(f.calls.length,before);
    assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',{...f.value,scope_id:'363069'}),f.env)).status,409);
  }
});

test('Phase 2 ordinary Build joins one cold workflow and the next scope waits for completion',async()=>{
  const f=fixture(),value={release_id:phase2.release_id,scope_id:phase2.first_scope_id,person_id:''};
  for(let n=0;n<3;n++)assert.equal((await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(value)),f.env)).status,200);
  assert.equal(f.calls.length,0);
  const results=await Promise.all(Array.from({length:5},()=>f.handler(f.request('/admin/api/contextual/jobs',value),f.env)));
  assert.equal(f.calls.length,1);assert.equal(results.filter(r=>r.status===202).length,1);
  for(const r of results)assert.equal((await r.json()).release_id,phase2.release_id);
  const next={...value,scope_id:'341997'};
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',next),f.env)).status,409);
  const id=hash([value.release_id,value.scope_id,'']);
  await f.store.start(id,'123','a'.repeat(40),f.clock.value.toISOString());
  await f.store.finish(id,'123','a'.repeat(40),JSON.stringify({result:{state:'no_supported_group_in_assessed_set',scope_id:value.scope_id}}),f.clock.value.toISOString());
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',value),f.env)).status,200);
  assert.equal(f.calls.length,1);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',next),f.env)).status,202);
  assert.equal(f.calls.length,2);
});

test('Phase 2 trial controls separate cached serving from new paid work and never enable expansion',async()=>{
  const f=fixture(),value={release_id:phase2.release_id,scope_id:phase2.first_scope_id,person_id:''};
  const controls='/admin/api/contextual/controls';
  const response=await f.handler(f.request(controls,{cached_enabled:true,new_paid_enabled:false}),f.env);
  assert.equal(response.status,200);assert.equal((await response.json()).public_activation,false);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',value),f.env)).status,403);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(value)),f.env)).status,200);
  assert.equal(f.calls.length,0);
  assert.equal((await f.handler(f.request(controls,{cached_enabled:true,new_paid_enabled:true,maximum_new_attempts:999}),f.env)).status,400);
  await f.handler(f.request(controls,{cached_enabled:false,new_paid_enabled:true}),f.env);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(value)),f.env)).status,503);
  await f.handler(f.request(controls,{cached_enabled:true,new_paid_enabled:true}),f.env);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',{...value,person_id:configuration.people[0].person_id}),f.env)).status,403);
  assert.equal(f.calls.length,0);
});

test('Phase 2 official deadline and rolling policy use one action clock without altering the catalog',async()=>{
  const f=fixture(),value={release_id:phase2.release_id,scope_id:phase2.first_scope_id,person_id:''};
  // Existing Search currentness is calendar-date based, not time-of-day gating.
  f.clock.value=new Date('2026-09-23T00:00:01Z');
  const closed=await f.handler(f.request('/admin/api/contextual/jobs',value),f.env);
  assert.equal((await closed.json()).state,'action_blocked');assert.equal(f.calls.length,0);
  f.clock.value=new Date('2026-10-15T12:00:00Z');
  const rolling=await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams({...value,scope_id:'341997'})),f.env);
  assert.equal((await rolling.json()).state,'unassessed');assert.equal(f.calls.length,0);
});

test('actual application preview is Access protected and serves only reviewed static assets',async()=>{
  const f=fixture(),base='/admin/contextual/preview/';
  assert.equal((await f.handler(new Request(host+base+'match_explorer.html'),f.env)).status,403);
  for(const name of ['match_explorer.html','team_match.html','assets/contextual-team-engine.js','data/researcher_directory.js']){
    const r=await f.handler(f.request(base+name),f.env);assert.equal(r.status,200);
    const raw=gunzipSync(Buffer.from(await r.arrayBuffer()));
    assert.equal(createHash('sha256').update(raw).digest('hex'),r.headers.get('X-Content-SHA256'));
    assert.match(r.headers.get('Content-Security-Policy'),/connect-src 'self'/);
    if(name==='match_explorer.html')assert.match(raw.toString(),/id="team-builder-content"/);
  }
  for(const name of ['outputs/result.json','data/opportunity_teams.js','__proto__','provider-cache.json'])
    assert.equal((await f.handler(f.request(base+name),f.env)).status,404);
  assert.equal(f.calls.length,0);assert.equal(f.db.prepare('SELECT count(*) AS n FROM contextual_validation_jobs').get().n,0);
});
