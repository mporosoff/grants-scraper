import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {ContextualStore,createContextualHandler} from '../../workers/researcher-intake/src/contextual.js';

const read=path=>fs.readFileSync(new URL('../../'+path,import.meta.url),'utf8');
const disposition=JSON.parse(read('config/contextual_team/iteration2-checkpoint-disposition-v1.json'));
const RELEASE='f8e9e544e08db863f79eb72737cb5434ea71b150c7ebbc00f5314452207074a2';
const MATH_JOB='816dd6d3cb281f5c7ebb1a1f7d166a5a7b37eb7c76885ab4e87e219217e67591';
const MATH_RUN='35655451108',MATH_SHA='43c109c7616ccefb63122aaf73d3c12f69748901';
const DOE_RUN='35647295615',DOE_SHA='e2fff7edad074c304ca6e04f1c77c1519730532e';
const host='https://funding-finder-researchers.urochestercheme.workers.dev';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const job=scope_id=>({release_id:RELEASE,scope_id,person_id:''});
const callback=(scope_id='341997',run_id=MATH_RUN,code_sha=MATH_SHA)=>({
  job_id:hash([RELEASE,scope_id,'']),release_id:RELEASE,run_id,code_sha});

function fixture(t,{activeSlot=null,state='recovery_required'}={}){
  const db=new DatabaseSync(':memory:');t.after(()=>db.close());
  for(const name of ['0005_contextual_validation_jobs.sql','0006_contextual_trial_controls.sql'])
    db.exec(read('workers/researcher-intake/migrations/'+name));
  // D1's adapter executes the actual Worker SQL against SQLite; no store method
  // or conditional UPDATE result is mocked. The separate disposition contracts
  // own archive/CAS installation; this fixture represents its exact row result.
  const query=(sql,values=[])=>({bind:(...args)=>query(sql,args),
    first:async()=>db.prepare(sql).get(...values)||null,
    run:async()=>({meta:{changes:db.prepare(sql).run(...values).changes}})});
  const store=new ContextualStore({prepare:sql=>query(sql)}),calls=[];
  const clock={value:new Date('2026-09-22T14:00:00Z')},hooks={provenance:null};
  const seed=(scope_id,{slot=null,rowState='complete',run=DOE_RUN,sha=DOE_SHA,result=null}={})=>{
    const id=hash([RELEASE,scope_id,'']);
    db.prepare(`INSERT INTO contextual_validation_jobs
      (job_id,release_id,scope_id,person_id,state,active_slot,run_id,code_sha,result_json,created_at,updated_at)
      VALUES(?,?,?,'',?,?,?,?,?,'2026-09-21T21:08:00Z','2026-09-22T13:00:00Z')`)
      .run(id,RELEASE,scope_id,rowState,slot,run,sha,result);
    return id;
  };
  seed('341997',{slot:activeSlot,rowState:state,run:MATH_RUN,sha:MATH_SHA});
  const handler=createContextualHandler({storeFactory:()=>store,now:()=>clock.value,
    authenticateAdmin:async()=> 'fixture-admin',authenticateInternal:async()=> 'fixture-workflow',
    fetchImpl:async(url,options)=>{
      calls.push({url,options});
      const match=url.match(/\/actions\/runs\/(\d+)$/);
      if(match){
        const run=match[1],sha=run===MATH_RUN?MATH_SHA:run===DOE_RUN?DOE_SHA:null;
        assert(sha,'Only pinned historical provenance reads are allowed');
        if(hooks.provenance)await hooks.provenance();
        return Response.json({id:Number(run),path:'.github/workflows/team-recommender-offline.yml',
          head_branch:'main',event:'repository_dispatch',head_sha:sha});
      }
      assert.equal(url,'https://api.github.com/repos/mporosoff/grants-scraper/dispatches');
      assert.equal(options.method,'POST');
      return new Response(null,{status:204});
    }});
  const env={GITHUB_REPOSITORY:'mporosoff/grants-scraper',GITHUB_DISPATCH_TOKEN:'fixture-only-token'};
  const request=(path,value)=>new Request(host+path,{method:value?'POST':'GET',
    headers:{Origin:host,'Content-Type':'application/json'},...(value?{body:JSON.stringify(value)}:{})});
  const send=(path,value)=>handler(request(path,value),env);
  const dispatches=()=>calls.filter(c=>c.url.endsWith('/dispatches'));
  const allow=()=>store.setControls(RELEASE,{cached_enabled:true,new_paid_enabled:true},clock.value.toISOString());
  const seedFirst=()=>seed('363302:a-1',{result:JSON.stringify({result:{state:'ready_with_gaps',fixture:true}})});
  return {db,store,calls,clock,hooks,send,dispatches,allow,seedFirst};
}

test('service tombstone fixture keeps the exact Math authority and deterministic job identity',()=>{
  assert.equal(disposition.failed.job_id,MATH_JOB);
  assert.equal(disposition.failed.release_id,RELEASE);
  assert.equal(disposition.failed.scope_id,'341997');
  assert.equal(String(disposition.failed.run.id),MATH_RUN);
  assert.equal(disposition.failed.run.head_sha,MATH_SHA);
  assert.equal(hash([RELEASE,'341997','']),MATH_JOB);
  assert.deepEqual(disposition.hold,{microusd:713400,attempts:4,native_counts:1});
});

test('released Math cannot restart, accept late success or recovery, or reclaim its slot',async t=>{
  const f=fixture(t),before=await f.store.byId(MATH_JOB);
  assert.equal(before.result_json,null);assert.equal(before.active_slot,null);
  const start=await f.send('/internal/contextual/start',callback());
  assert.equal(start.status,409);assert.equal((await start.json()).error,'contextual_job_already_owned');
  for(const state of ['ready','ready_with_gaps','recovery_required']){
    const value={...callback(),result:{state,scope_id:'341997',reason:'fixture callback, no scientific output'}};
    for(let n=0;n<2;n++){
      const response=await f.send('/internal/contextual/result',value);
      assert.equal(response.status,409,state);
      assert.equal((await response.json()).error,'contextual_result_not_persisted');
      assert.deepEqual(await f.store.byId(MATH_JOB),before);
    }
  }
  assert.equal(f.dispatches().length,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs WHERE active_slot=1').get().n,0);
});

test('repeated Math GET and POST preserve the disposition and never redispatch even with paid work enabled',async t=>{
  const f=fixture(t),before=await f.store.byId(MATH_JOB);await f.allow();
  for(const when of ['2026-09-22T14:00:00Z','2027-01-01T00:00:00Z']){
    f.clock.value=new Date(when);
    for(let n=0;n<3;n++)for(const method of ['GET','POST']){
      const response=await f.send(method==='GET'?'/admin/api/contextual/jobs?'+new URLSearchParams(job('341997')):
        '/admin/api/contextual/jobs',method==='POST'?job('341997'):undefined);
      assert.equal(response.status,200);
      assert.deepEqual(await response.json(),{release_id:RELEASE,scope_id:'341997',job_id:MATH_JOB,
        state:'recovery_required',public_activation:false});
    }
  }
  assert.deepEqual(await f.store.byId(MATH_JOB),before);assert.equal(f.calls.length,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs').get().n,1);
});

test('late Math callbacks cannot disturb an unrelated job that owns the released slot',async t=>{
  const f=fixture(t);f.seedFirst();await f.allow();
  const first=await f.send('/admin/api/contextual/jobs',job('362856'));
  assert.equal(first.status,202);assert.equal(f.dispatches().length,1);
  const nextId=hash([RELEASE,'362856','']),active=await f.store.byId(nextId),math=await f.store.byId(MATH_JOB);
  assert.equal(active.active_slot,1);assert.equal(active.state,'dispatch_claimed');
  assert.deepEqual(JSON.parse(JSON.parse(f.dispatches()[0].options.body).client_payload.contextual_job),
    {...job('362856'),job_id:nextId});
  for(const state of ['ready','recovery_required']){
    const response=await f.send('/internal/contextual/result',{...callback(),result:{state,scope_id:'341997'}});
    assert.equal(response.status,409);assert.equal((await response.json()).error,'contextual_result_not_persisted');
  }
  for(let n=0;n<3;n++)assert.equal((await f.send('/admin/api/contextual/jobs',job('362856'))).status,200);
  assert.deepEqual(await f.store.byId(nextId),active);assert.deepEqual(await f.store.byId(MATH_JOB),math);
  assert.equal(f.dispatches().length,1);
  assert.equal(f.db.prepare('SELECT count(*) n FROM contextual_validation_jobs WHERE active_slot=1').get().n,1);
});

test('finish atomically checks ownership when disposition releases Math after callback provenance was read',async t=>{
  for(const state of ['ready','recovery_required']){
    const f=fixture(t,{activeSlot:1,state:'in_progress'});let released;
    f.hooks.provenance=async()=>{
      const result=f.db.prepare(`UPDATE contextual_validation_jobs SET state='recovery_required',active_slot=NULL,
        updated_at='2026-09-22T14:00:01Z' WHERE job_id=? AND run_id=? AND code_sha=? AND active_slot=1 AND result_json IS NULL`)
        .run(MATH_JOB,MATH_RUN,MATH_SHA);
      assert.equal(result.changes,1);released=await f.store.byId(MATH_JOB);f.hooks.provenance=null;
    };
    const response=await f.send('/internal/contextual/result',{...callback(),result:{state,scope_id:'341997'}});
    assert.equal(response.status,409);assert.equal((await response.json()).error,'contextual_result_not_persisted');
    assert.deepEqual(await f.store.byId(MATH_JOB),released);assert.equal(f.dispatches().length,0);
  }
});

test('undisposed unknown exposure keeps the sole slot and its immutable recovery callback',async t=>{
  const f=fixture(t,{activeSlot:1});f.seedFirst();await f.allow();
  assert.equal((await f.send('/admin/api/contextual/jobs',job('362856'))).status,429);
  const value={...callback(),result:{state:'recovery_required',scope_id:'341997',reason:'fixture unknown exposure'}};
  assert.equal((await f.send('/internal/contextual/result',value)).status,200);
  const held=await f.store.byId(MATH_JOB);assert.equal(held.active_slot,1);
  assert.equal(held.result_json,JSON.stringify(value));
  f.clock.value=new Date('2026-09-22T15:00:00Z');
  assert.equal((await f.send('/internal/contextual/result',value)).status,200);
  const conflict=await f.send('/internal/contextual/result',{...value,result:{state:'ready',scope_id:'341997'}});
  assert.equal(conflict.status,409);assert.equal((await conflict.json()).error,'contextual_terminal_result_conflict');
  assert.equal((await f.send('/admin/api/contextual/jobs',job('362856'))).status,429);
  assert.deepEqual(await f.store.byId(MATH_JOB),held);assert.equal(f.dispatches().length,0);
});

test('an active normal callback still completes once and identical retries preserve its original receipt',async t=>{
  const f=fixture(t),id=hash([RELEASE,'363302:a-1','']);
  assert.equal(await f.store.insert({...job('363302:a-1'),job_id:id},'2026-09-22T14:00:00Z'),true);
  const identity=callback('363302:a-1',DOE_RUN,DOE_SHA);
  assert.equal((await f.send('/internal/contextual/start',identity)).status,200);
  const value={...identity,result:{state:'ready_with_gaps',scope_id:'363302:a-1',fixture:true}};
  assert.equal((await f.send('/internal/contextual/result',value)).status,200);
  const complete=await f.store.byId(id);assert.equal(complete.active_slot,null);assert.equal(complete.state,'complete');
  assert.equal(complete.result_json,JSON.stringify(value));f.clock.value=new Date('2026-09-22T15:00:00Z');
  assert.equal((await f.send('/internal/contextual/result',value)).status,200);
  assert.deepEqual(await f.store.byId(id),complete);
  const conflict=await f.send('/internal/contextual/result',{...value,result:{state:'recovery_required'}});
  assert.equal(conflict.status,409);assert.equal((await conflict.json()).error,'contextual_terminal_result_conflict');
  assert.equal((await f.send('/internal/contextual/start',identity)).status,409);
  assert.deepEqual(await f.store.byId(id),complete);assert.equal(f.dispatches().length,0);
});
