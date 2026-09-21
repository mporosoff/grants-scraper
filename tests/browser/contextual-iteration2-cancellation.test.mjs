// Actual restricted scripts and public inputs; synthetic graphs and no network.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash,webcrypto} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {shellDom} from '../helpers/shell-dom.mjs';

const overlay=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration2-preview-v1.json'));
const base=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const code=name=>gunzipSync(Buffer.from((overlay.files[name]||base.files[name]).gzip_base64,'base64')).toString();
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'
  ?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const hash=v=>createHash('sha256').update(canonical(v)).digest('hex');
const NOW='2026-09-21T19:00:00Z';
class Clock extends Date{constructor(...args){super(...(args.length?args:[NOW]));}static now(){return +new Date(NOW);}}
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function until(predicate,message){for(let n=0;n<1000;n++){if(predicate())return;await tick();}assert.fail(message);}

function fixture(){
  const c=vm.createContext({URL,URLSearchParams,Date:Clock,TextEncoder,TextDecoder,Uint8Array,
    crypto:webcrypto,AbortController,setTimeout,clearTimeout,Response});
  for(const name of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js',
    'data/researcher_directory.js','data/opportunities.js','data/subtopics.js','data/opportunity_team_index.js',
    'assets/contextual-team-engine.js','assets/contextual-team-client.js'])vm.runInContext(code(name),c,{filename:name});
  const index=c.OPPORTUNITY_TEAM_INDEX,directory=c.RESEARCHER_DIRECTORY;
  const scope=index.scopes.find(s=>s.id==='363302:a-1');
  const parent=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===scope.parent_id);
  const childCatalog=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG);
  const role={id:'role-1',label:'Synthetic contribution',required:true,central:true,
    kind:'approach_necessary',applicability:'applies',condition:''};
  const people=directory.researchers.filter(c.ContextualTeamEngine.eligible).slice(0,3);
  const graph={version:'contextual-audited-graph-v3',snapshot_id:index.release_id,
    registry_generation:index.registry_generation,source_id:scope.source_id,roster_id:index.roster_id,
    scope:{id:scope.id,parent_id:scope.parent_id,title:scope.scope_label},state:'ready',roles:[role],
    requirement_policy:'contextual-selected-approach-v2',approach:'Synthetic transport fixture only.',
    people:people.map(p=>({person_id:p.id,outcome:'supported'})),pair_decisions:[],edges:[],
    provenance:{all_pair_decisions_retained:true,independent_checker_used_for_admission:false,
      ...Object.fromEntries(['input_sha256','active_input_sha256','pair_input_sha256','assessment_sha256','verification_sha256'].map(k=>[k,'d'.repeat(64)]))}};
  for(const p of people){
    const claim=p.claims.find(c=>c.status==='active');
    const decision={role_id:role.id,coverage:'direct',central:true,claims:[claim],reason:'Synthetic transport fixture only.',gap:''};
    graph.pair_decisions.push({person_id:p.id,outcome:'supported',decisions:[decision]});
    graph.edges.push({person_id:p.id,role_id:role.id,claim_id:claim.claim_id,claim_revision:claim.revision,
      evidence_quote:claim.evidence,supporting_claims:[claim],coverage:'direct',central:true,reason:decision.reason,gap:''});
  }
  graph.graph_id=hash(graph);
  const options={parentId:scope.parent_id,scopeId:scope.id,record:parent,childCatalog,now:NOW};
  return {c,index,directory,scope,parent,childCatalog,graph,options,
    response:(state='ready')=>Response.json({release_id:index.release_id,scope_id:scope.id,state,...(state==='ready'?{result:graph}:{})}),
    load:more=>c.ContextualTeamClient.load(index,directory,{...options,...more})};
}

// The public decision-clock read occurs after the content hashes have resolved.
// This gives concurrent callers a deterministic join barrier without real sleeps.
function joined(f,more){
  const ready=deferred(),options={...f.options,...more};
  Object.defineProperty(options,'now',{get(){ready.resolve();return NOW;}});
  const result=f.c.ContextualTeamClient.load(f.index,f.directory,options);
  return {ready:ready.promise,result};
}

test('a live deliberate joiner authorizes one POST after the originating caller cancels',async()=>{
  const f=fixture(),gate=deferred(),calls=[],firstAbort=new AbortController(),secondAbort=new AbortController();
  const fetcher=async(_url,o)=>{calls.push(o.method||'GET');return o.method==='POST'?f.response():gate.promise;};
  const first=joined(f,{fetcher,signal:firstAbort.signal,deliberate:true});
  const cancelled=assert.rejects(first.result,/contextual_cancelled/);
  await until(()=>calls.length===1,'first GET started');
  const second=joined(f,{fetcher,signal:secondAbort.signal,deliberate:true});await second.ready;
  firstAbort.abort();await cancelled;gate.resolve(f.response('unassessed'));
  assert.equal((await second.result).graph_id,f.graph.graph_id);
  assert.deepEqual(calls,['GET','POST']);assert.equal(f.c.ContextualTeamClient.statistics().pending,0);
});

test('cancelled deliberate callers cannot authorize a later POST for no waiter or an incidental waiter',async()=>{
  for(const incidental of [false,true]){
    const f=fixture(),gate=deferred(),calls=[],abort=new AbortController();
    const fetcher=async(_url,o)=>{calls.push(o.method||'GET');return gate.promise;};
    const first=joined(f,{fetcher,signal:abort.signal,deliberate:true});
    const cancelled=assert.rejects(first.result,/contextual_cancelled/);
    await until(()=>calls.length===1,'first GET started');
    const second=incidental?joined(f,{fetcher,deliberate:false}):null;if(second)await second.ready;
    abort.abort();await cancelled;gate.resolve(f.response('unassessed'));
    if(second)assert.equal((await second.result).engine.resolveScope().reason,'contextual_unassessed');
    await until(()=>f.c.ContextualTeamClient.statistics().pending===0,'detached task settled');
    assert.deepEqual(calls,['GET']);assert.equal(f.c.ContextualTeamClient.statistics().cached_scopes,0);
  }
});

test('an entirely detached poll completes within the unchanged finite budget and populates the cache',async()=>{
  const f=fixture(),firstWait=deferred(),abort=new AbortController(),delays=[];let gets=0,statuses=0;
  const fetcher=async(_url,o)=>{assert.notEqual(o.method,'POST');assert.equal(o.signal,undefined);
    return f.response(++gets===169?'ready':'in_progress');};
  const result=f.load({fetcher,signal:abort.signal,onStatus:()=>statuses++,wait:ms=>{
    delays.push(ms);return delays.length===1?firstWait.promise:Promise.resolve();}});
  const cancelled=assert.rejects(result,/contextual_cancelled/);
  await until(()=>delays.length===1,'first poll is waiting');abort.abort();await cancelled;firstWait.resolve();
  await until(()=>f.c.ContextualTeamClient.statistics().pending===0,'finite detached poll completed');
  assert.equal(gets,169);assert.equal(delays.length,168);assert.equal(delays.reduce((a,b)=>a+b,0),600000);
  assert.equal(delays.filter(ms=>ms===1000).length,60);assert.equal(delays.filter(ms=>ms===5000).length,108);
  assert.equal(statuses,1);assert.equal(f.c.ContextualTeamClient.statistics().cached_scopes,1);
  assert.equal((await f.load({fetcher})).graph_id,f.graph.graph_id);assert.equal(gets,169);
});

test('a waiter callback failure does not interrupt another waiter or the shared poll',async()=>{
  const f=fixture(),gate=deferred(),poll=deferred(),calls=[],statuses=[];
  const fetcher=async(_url,o)=>{calls.push(o.method||'GET');return calls.length===1?gate.promise:f.response();};
  const first=joined(f,{fetcher,wait:()=>poll.promise,onStatus:()=>{throw Error('fixture_display_error');}});
  const rejected=assert.rejects(first.result,/fixture_display_error/);
  await until(()=>calls.length===1,'initial GET');
  const second=joined(f,{fetcher,onStatus:state=>statuses.push(state)});await second.ready;
  gate.resolve(f.response('in_progress'));await rejected;poll.resolve();
  assert.equal((await second.result).graph_id,f.graph.graph_id);
  assert.deepEqual(statuses,['in_progress']);assert.deepEqual(calls,['GET','GET']);
});

test('a genuine shared read error rejects active waiters, clears pending, and permits a read-only retry',async()=>{
  const f=fixture(),gate=deferred(),poll=deferred(),calls=[];let fail=true;
  const fetcher=async(_url,o)=>{calls.push(o.method||'GET');
    if(calls.length===1)return gate.promise;if(fail)throw Error('fixture_shared_read_failure');return f.response();};
  const first=joined(f,{fetcher,wait:()=>poll.promise});const firstError=assert.rejects(first.result,/fixture_shared_read_failure/);
  await until(()=>calls.length===1,'initial GET');
  const second=joined(f,{fetcher});const secondError=assert.rejects(second.result,/fixture_shared_read_failure/);await second.ready;
  gate.resolve(f.response('in_progress'));poll.resolve();await Promise.all([firstError,secondError]);
  assert.equal(f.c.ContextualTeamClient.statistics().pending,0);assert.equal(f.c.ContextualTeamClient.statistics().cached_scopes,0);
  fail=false;assert.equal((await f.load({fetcher})).graph_id,f.graph.graph_id);
  assert.deepEqual(calls,['GET','GET','GET']);
});

test('cancelled cache reads and changed source, profile, or decision clock never reuse invalid results',async()=>{
  const f=fixture();let gets=0;const fetcher=async()=>{gets++;return f.response();};
  await f.load({fetcher});const abort=new AbortController();abort.abort();
  await assert.rejects(f.load({fetcher,signal:abort.signal}),/contextual_cancelled/);
  const childCatalog=structuredClone(f.childCatalog),record=childCatalog.opportunities.find(r=>r.opportunity_id===f.scope.id);
  const field=f.index.source_fields.find(k=>record[k]!==undefined);assert(field);
  record[field]=String(record[field])+' changed scientific input';
  await assert.rejects(f.load({fetcher,childCatalog}),/source_version_conflict/);
  await assert.rejects(f.load({fetcher,now:'2026-09-22T21:00:00Z'}),/not_current/);
  const changed=structuredClone(f.directory);changed.researchers[0].name+=' changed';
  await assert.rejects(f.c.ContextualTeamClient.load(f.index,changed,{...f.options,fetcher}),/directory_content_conflict/);
  assert.equal((await f.load({fetcher})).graph_id,f.graph.graph_id);assert.equal(gets,1);
});

test('source or profile replacement while a shared read is pending cannot display the old proposal',async()=>{
  for(const replace of ['source','profile']){
    const f=fixture(),gate=deferred();let gets=0;
    const result=f.load({fetcher:async()=>{gets++;return gate.promise;}});
    await until(()=>gets===1,'initial read is held');
    if(replace==='profile'){
      f.c.RESEARCHER_DIRECTORY=structuredClone(f.directory);
      const rejected=assert.rejects(result,/contextual_profile_pool_replaced/);gate.resolve(f.response());await rejected;
    }else{
      const catalog=structuredClone(f.c.GRANT_CATALOG);
      catalog.opportunities.find(r=>r.opportunity_id===f.scope.parent_id).title+=' changed';
      f.c.GRANT_CATALOG=catalog;gate.resolve(f.response());
      const loaded=await result;
      assert.throws(()=>loaded.engine.proposal(),/source_or_profile_pool_changed/);
    }
    assert.equal(f.c.ContextualTeamClient.statistics().pending,0);assert.equal(gets,1);
  }
});

test('real panel close/reopen shares the dispatched poll and runtime without stale display or another POST',async()=>{
  const f=fixture(),dom=shellDom(code('match_explorer.html')),c=dom.context,calls=[],waits=[],scripts=[];
  let complete=false;
  const fetcher=async(_url,o)=>{calls.push(o.method||'GET');return f.response(
    o.method==='POST'?'in_progress':calls.length===1?'unassessed':complete?'ready':'in_progress');};
  Object.assign(c,{URL,URLSearchParams,Date:Clock,TextEncoder,TextDecoder,Uint8Array,AbortController,
    crypto:webcrypto,clearTimeout,btoa,Response,
    setTimeout:(callback,ms)=>{if(ms===1000||ms===5000){waits.push(callback);return waits.length;}return setTimeout(callback,ms);},
    location:{href:'https://funding-finder-researchers.urochestercheme.workers.dev/admin/contextual/preview/match_explorer.html'},
    OPPORTUNITY_TEAM_INDEX:f.index,RESEARCHER_DIRECTORY:f.directory,GRANT_CATALOG:f.c.GRANT_CATALOG,
    ContextualTeamAccess:{fetch:fetcher},fetch:fetcher,
    FUNDING_SUBTOPICS:{loadSidecar:async()=>f.c.SUBTOPIC_CATALOG},
    FUNDING_FINDER_APP:{boundedScripts:{sidecar:{setTimeout:callback=>setTimeout(callback,5000),clearTimeout}}}});
  dom.document.getElementById('results').innerHTML='<article class="result-card"><button id="open-fixture" data-opportunity-team="'+
    f.scope.parent_id+'" data-opportunity-team-scope="'+f.scope.id+'">Build team</button></article>';
  dom.document.head=dom.document.querySelector('head');dom.document.head.appendChild=script=>{
    const name=script.src.split('?')[0];scripts.push(name);vm.runInContext(code(name),c);queueMicrotask(()=>dom.dispatch('load',script));};
  vm.createContext(c);
  for(const name of ['site-shell','submission-schedule','search-query','search-retrieval','opportunity-team','opportunity-team-panel'])
    vm.runInContext(code('assets/'+name+'.js'),c);
  const trigger=dom.document.getElementById('open-fixture'),drawer=dom.document.getElementById('team-builder');
  dom.dispatch('click',trigger);await until(()=>waits.length===1,'panel dispatched and started polling');
  const oldPanel=drawer.querySelector('.opportunity-team-panel'),client=c.ContextualTeamClient;
  dom.dispatch('click',trigger);assert.equal(oldPanel.isConnected,false);
  dom.dispatch('click',trigger);await until(()=>drawer.querySelector('.opportunity-team-panel'),'new panel opened');
  const newPanel=drawer.querySelector('.opportunity-team-panel');assert.notEqual(newPanel.id,oldPanel.id);
  for(let n=0;n<10&&!/Assessing the call/.test(newPanel.textContent);n++){
    await until(()=>waits.length>0,'shared poll remained alive');waits.shift()();await tick();
  }
  assert.match(newPanel.textContent,/Assessing the call/);
  complete=true;await until(()=>waits.length>0,'final shared read');waits.shift()();
  await until(()=>drawer.querySelector('.opportunity-team-next'),'reopened panel displays complete proposal');
  assert.equal(c.ContextualTeamClient,client);assert.equal(calls.filter(v=>v==='POST').length,1);
  assert.deepEqual(scripts,['assets/contextual-team-engine.js','assets/contextual-team-client.js']);
  assert.equal(oldPanel.isConnected,false);assert.equal(drawer.querySelector('.opportunity-team-body').dataset.error,undefined);
  const before=calls.length;dom.dispatch('click',trigger);dom.dispatch('click',trigger);
  await until(()=>drawer.querySelector('.opportunity-team-next'),'cached reopen displays proposal');
  assert.equal(calls.length,before);assert.equal(c.ContextualTeamClient,client);
});
