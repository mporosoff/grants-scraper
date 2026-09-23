// Real SQLite/Worker boundaries, synthetic transport values; no provider or UI.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {ContextualStore,createContextualHandler} from '../../workers/researcher-intake/src/contextual.js';
import {previewResponse} from '../../workers/researcher-intake/src/contextual-preview.js';
const load=p=>JSON.parse(fs.readFileSync(p));
const plan=load('config/contextual_team/iteration3-continuation-v1.json');
const old=load('config/contextual_team/iteration3-authority-v1.json');
const sources=load('config/contextual_team/iteration3-source-inputs-v1.json');
const scope=sources.scopes.find(s=>s.id==='363268');
const bundle=load('workers/researcher-intake/config/contextual-iteration3-continuation-preview-v1.json');
const previous=load('workers/researcher-intake/config/contextual-iteration3-preview-v1.json');
const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;
const hash=v=>createHash('sha256').update(JSON.stringify(canonical(v))).digest('hex');
const host='https://example.test',sha='a'.repeat(40);
function fixture(){
  const db=new DatabaseSync(':memory:');
  for(const name of ['0005_contextual_validation_jobs.sql','0006_contextual_trial_controls.sql'])db.exec(fs.readFileSync('workers/researcher-intake/migrations/'+name,'utf8'));
  const statement=(sql,args=[])=>({bind:(...v)=>statement(sql,v),first:async()=>db.prepare(sql).get(...args)||null,
    run:async()=>({meta:{changes:db.prepare(sql).run(...args).changes}})});
  const store=new ContextualStore({prepare:sql=>statement(sql)}),calls=[],clock={value:new Date('2026-09-23T18:00:00Z')};
  const handler=createContextualHandler({storeFactory:()=>store,now:()=>clock.value,
    fetchImpl:async(url,o)=>{calls.push({url,o});return url.includes('/actions/runs/')?Response.json({path:'.github/workflows/team-recommender-offline.yml',event:'repository_dispatch',head_branch:'main',head_sha:sha}):new Response(null,{status:204});},
    authenticateAdmin:async r=>{if(r.headers.get('x-access')!=='yes')throw Object.assign(Error(),{code:'access',status:403});return 'fixture';},
    authenticateInternal:async r=>{if(r.headers.get('x-internal')!=='yes')throw Object.assign(Error(),{code:'internal',status:403});}});
  const request=(path,value,internal=false)=>new Request(host+path,{method:value?'POST':'GET',headers:{Origin:host,
    [internal?'x-internal':'x-access']:'yes','Content-Type':'application/json'},...(value?{body:JSON.stringify(value)}:{})});
  const job={release_id:plan.release_id,scope_id:'363268',person_id:''};
  return {db,store,calls,clock,handler,request,job,env:{GITHUB_REPOSITORY:'fixture/repo',GITHUB_DISPATCH_TOKEN:'fixture-only'},
    enable:()=>store.setControls(plan.release_id,{cached_enabled:true,new_paid_enabled:true},'now')};
}
async function owner(f,release=plan.release_id){
  const job={...f.job,release_id:release,job_id:hash([release,'363268',''])};
  assert(await f.store.insert(job,'now'));await f.store.start(job.job_id,'123',sha,'now');
  return {job_id:job.job_id,release_id:release,run_id:'123',code_sha:sha};
}
function graph(){
  const x={version:'contextual-production-integrity-v1',selection_version:'contextual-integrity-candidates-v1',
    independent_evaluation:false,human_labels_added:0,source_sha256:scope.source_id,base_graph_id:'b'.repeat(64),
    base_graph_sha256:'c'.repeat(64),candidate_groups:[],candidate_list_sha256:hash([]),groups:[],disposition:'not_applicable_no_candidates'};
  const g={version:'contextual-audited-graph-v4',state:'no_supported_group_in_assessed_set',snapshot_id:plan.release_id,
    registry_generation:sources.registry_generation,roster_id:sources.roster_id,source_id:scope.source_id,
    scope:{id:scope.id,parent_id:scope.parent_id},base_graph_id:x.base_graph_id,base_graph_sha256:x.base_graph_sha256,
    integrity:x,provenance:{integrity_version:x.version,integrity_sha256:hash(x)}};
  g.graph_id=hash(g);return g;
}
function rehash(g){g.integrity&&(g.provenance.integrity_sha256=hash(g.integrity));delete g.graph_id;g.graph_id=hash(g);return g;}

test('new continuation Access route is AI-only, paid OFF and cache ON, with no launch on loading',async()=>{
  const f=fixture();
  for(const path of ['/admin/contextual/iteration3-continuation/match_explorer.html','/admin/api/contextual/manifest?iteration=3-continuation']){
    assert.equal((await f.handler(new Request(host+path),f.env)).status,403);
    assert.equal((await f.handler(f.request(path),f.env)).status,200);
  }
  const m=await (await f.handler(f.request('/admin/api/contextual/manifest?iteration=3-continuation'),f.env)).json();
  assert.equal(m.release_id,plan.release_id);assert.deepEqual(m.scopes.map(s=>s.id),['363268']);
  const c=await (await f.handler(f.request('/admin/api/contextual/controls?release_id='+plan.release_id),f.env)).json();
  assert.equal(c.new_paid_enabled,0);assert.equal(c.cached_enabled,1);assert.equal(c.maximum_workflows,1);
  assert.equal(c.maximum_concurrency,1);assert.equal(c.public_activation,false);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).status,403);
  await f.enable();
  for(const bad of [{...f.job,scope_id:'332894'},{...f.job,scope_id:'345241:tdac-baa-004'},
    {...f.job,scope_id:'344592:ab-0025'},{...f.job,person_id:'urh-000001'},{...f.job,release_id:'f'.repeat(64)}])
    assert((await f.handler(f.request('/admin/api/contextual/jobs',bad),f.env)).status>=400);
  assert.equal(f.calls.length,0);assert.equal((await f.store.controls(old.release_id)).new_paid_enabled,0);
});

test('one new corrective AI job preserves original immutable failure; concurrent builds dispatch once',async()=>{
  const f=fixture(),prior=await owner(f,old.release_id);
  await f.store.finish(prior.job_id,'123',sha,JSON.stringify({result:{state:'failed',reason:'retained_synthetic_failure'}}),'now');
  const before=await f.store.byId(prior.job_id);await f.enable();
  const results=await Promise.all(Array.from({length:5},()=>f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)));
  assert.equal(results.filter(r=>r.status===202).length,1);assert.equal(f.calls.length,1);
  assert.deepEqual(await f.store.byId(prior.job_id),before);
  const jobId=hash([plan.release_id,'363268','']);await f.store.start(jobId,'124',sha,'now');
  await f.store.finish(jobId,'124',sha,JSON.stringify({result:{state:'failed'}}),'now');
  assert.equal((await (await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).json()).state,'failed');
  assert.equal(f.calls.length,1);
  assert.equal(await f.store.insert({...f.job,scope_id:'second',job_id:'e'.repeat(64)},'now'),false);
});

test('historical unknown active slot and source expiry still block new AI work',async()=>{
  const f=fixture(),prior=await owner(f,old.release_id);await f.store.uncertain(prior.job_id,'now');await f.enable();
  const before=await f.store.byId(prior.job_id);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).status,429);
  assert.deepEqual(await f.store.byId(prior.job_id),before);assert.equal(f.calls.length,0);
  const expired=fixture();await expired.enable();expired.clock.value=new Date('2026-09-24T17:00:00Z');
  assert.equal((await (await expired.handler(expired.request('/admin/api/contextual/jobs',expired.job),expired.env)).json()).state,'action_blocked');
  assert.equal(expired.calls.length,0);
});

test('continuation callback retains strict I3 graph, ownership and complete integrity validation',async()=>{
  const f=fixture(),stamp=await owner(f),value={...stamp,result:graph()};
  assert.equal((await f.handler(f.request('/internal/contextual/result',value,true),f.env)).status,200);
  assert.equal((await f.store.byId(stamp.job_id)).active_slot,null);
  for(const mutate of [g=>{g.snapshot_id=old.release_id;},g=>{g.scope.id='332894';},
    g=>{delete g.integrity;},g=>{g.integrity.candidate_list_sha256='f'.repeat(64);},g=>{g.integrity.human_labels_added=1;}]){
    const f=fixture(),stamp=await owner(f),g=graph();mutate(g);rehash(g);
    assert((await f.handler(f.request('/internal/contextual/result',{...stamp,result:g},true),f.env)).status>=400);
    assert.equal((await f.store.byId(stamp.job_id)).result_json,null);
  }
});

test('continuation admits exact verifier abstention and retains Unicode graph/envelope size bounds',async()=>{
  const f=fixture(),stamp=await owner(f),g=graph();
  g.state='unsuitable';g.version='contextual-audited-graph-v3';delete g.integrity;delete g.base_graph_id;delete g.base_graph_sha256;
  g.provenance={adapter_version:g.version,all_pair_decisions_retained:true,independent_checker_used_for_admission:false};rehash(g);
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...stamp,result:g},true),f.env)).status,200);
  const other=fixture(),s=await owner(other),large=graph();large.synthetic='';
  const fill=393216-Buffer.byteLength(JSON.stringify(large));large.synthetic='α'.repeat(Math.floor(fill/2))+'x'.repeat(fill%2);rehash(large);
  assert.equal(Buffer.byteLength(JSON.stringify(large)),393216);
  assert.equal((await other.handler(other.request('/internal/contextual/result',{...s,result:large},true),other.env)).status,200);
  assert.equal((await other.handler(other.request('/internal/contextual/result',{...s,result:large,padding:'x'.repeat(524288)},true),other.env)).status,413);
});

test('new preview has exact AI index and observer path; historical cohort bytes remain independently served',async()=>{
  assert.equal(bundle.release_id,plan.release_id);assert.equal(bundle.historical_iteration3_bundle_id,previous.bundle_id);
  assert.equal(bundle.provider_results,0);assert.equal(bundle.public_activation,false);
  const {bundle_id,...content}=bundle;assert.equal(hash(content),bundle_id);
  const unpack=name=>gunzipSync(Buffer.from(bundle.files[name].gzip_base64,'base64')).toString();
  const text=unpack('data/opportunity_team_index.js'),index=JSON.parse(text.slice(text.indexOf('{'),text.lastIndexOf('}')+1));
  assert.deepEqual(index.scopes.map(s=>s.id),['363268']);assert.equal(index.release_id,plan.release_id);
  assert.match(unpack('assets/contextual-preview-observer.js'),/pathname.startsWith\('\/admin\/contextual\/iteration3-continuation\/'\)/);
  for(const name of ['match_explorer.html','team_match.html']){
    assert(unpack(name).includes('<base href="'+bundle.base_path+'">'));assert(unpack(name).includes(index.generation_id));
  }
  for(const [name,file] of Object.entries(previous.files)){
    assert.equal(previewResponse(previous.base_path+name).headers.get('X-Content-SHA256'),file.sha256);
    const response=previewResponse(bundle.base_path+name),raw=gunzipSync(Buffer.from(await response.arrayBuffer()));
    assert.equal(createHash('sha256').update(raw).digest('hex'),bundle.files[name].sha256);
  }
  assert.equal(previewResponse('/admin/contextual/iteration3-continuation-extra/assets/app.js'),null);
});
