import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import {webcrypto} from 'node:crypto';
import {shellDom} from '../helpers/shell-dom.mjs';
import {loadCanonicalInputs,buildSnapshot,hash,eligible,SOURCE_FIELDS,CONDITION_FIELDS} from '../../tools/contextual_team_inputs.mjs';

// Complete real audited inputs; relationships below are explicitly fabricated
// transport fixtures, never semantic assessments or publishable graph assets.
const read=p=>fs.readFileSync(p,'utf8'),tick=()=>new Promise(r=>setTimeout(r,0));
function fixture(){
  const inputs=loadCanonicalInputs(),snapshot=buildSnapshot(inputs,['361207','344592','344592:ab-0025'],'2026-09-12T16:00:00Z');
  const scope=snapshot.scopes[0],directory=inputs.directory,people=directory.researchers.filter(eligible).slice(0,5);
  const raw={version:'contextual-audited-graph-v1',snapshot_id:snapshot.snapshot_id,registry_generation:snapshot.registry_generation,
    source_id:scope.source_id,roster_id:snapshot.roster_id,state:'ready',scope:{id:scope.id,parent_id:scope.parent_id,title:scope.science.title},
    objective:'TRANSPORT FIXTURE ONLY',roles:[{id:'role-1',label:'Fixture contribution',required:true,central:true}],
    people:people.map(p=>({person_id:p.id,outcome:'supported'})),edges:people.map(p=>{
      const c=p.claims.find(c=>c.status==='active');return {person_id:p.id,role_id:'role-1',claim_id:c.claim_id,claim_revision:c.revision,
        coverage:'method_transfer',central:true,evidence_quote:c.evidence.slice(0,160),reason:'Fixture relationship; no scientific assessment occurred.',gap:'Not a scientific result.'};})};
  const graph={...raw,graph_id:hash(raw)};
  const body={schema_version:4,release_id:snapshot.snapshot_id,registry_generation:snapshot.registry_generation,
    roster_id:snapshot.roster_id,directory_id:snapshot.directory_id,public_activation:false,
    endpoint:'https://funding-finder-researchers.urochestercheme.workers.dev/admin/api/contextual',source_fields:SOURCE_FIELDS,condition_fields:CONDITION_FIELDS,
    runtime:{contextual_engine:hash(read('assets/contextual-team-engine.js')),contextual_client:hash(read('assets/contextual-team-client.js'))},
    scopes:snapshot.scopes.map(s=>({id:s.id,parent_id:s.parent_id,scope_label:s.science.title,record_type:s.kind==='parent'?'specific_parent':'publishable_child',engine:'contextual-v1',state:s.state,source_id:s.source_id}))};
  return {inputs,snapshot,scope,directory,graph,index:{...body,generation_id:hash(body)}};
}
function context(f){
  const c=vm.createContext({URL,URLSearchParams,Date,TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,setTimeout,clearTimeout,
    RESEARCHER_DIRECTORY:f.directory,GRANT_CATALOG:f.inputs.catalog});
  for(const p of ['submission-schedule','search-query','search-retrieval','contextual-team-engine','contextual-team-client'])vm.runInContext(read('assets/'+p+'.js'),c);
  return c;
}
const response=value=>new Response(JSON.stringify(value));
const options=(f,extra={})=>({parentId:f.scope.id,record:f.inputs.catalog.opportunities.find(r=>r.opportunity_id===f.scope.id),now:'2026-09-12T16:00:00Z',...extra});
test('complete audited directory: deliberate cold request, exact cached graph and all ordinary edits use no further dispatch',async()=>{
  const f=fixture(),c=context(f),requests=[];let state='unassessed';
  const fetcher=async(url,o)=>{assert(url.startsWith(f.index.endpoint+'/jobs'));requests.push({url,method:o.method||'GET'});
    assert.equal(o.credentials,'include');if(o.method==='POST'){assert.deepEqual(Object.keys(JSON.parse(o.body)).sort(),['person_id','release_id','scope_id']);state='ready';}
    return response({release_id:f.index.release_id,scope_id:f.scope.id,state,result:state==='ready'?f.graph:undefined});};
  const client=c.ContextualTeamClient;assert.equal(requests.length,0);
  const unopened=await client.load(f.index,f.directory,options(f,{fetcher}));assert.equal(unopened.engine.resolveScope().reason,'contextual_unassessed');
  assert.equal(requests.filter(r=>r.method==='POST').length,0);
  const result=await client.load(f.index,f.directory,options(f,{fetcher,deliberate:true}));let s=result.engine.proposal();
  assert.equal(s.selectedIds.length,2);assert.equal(result.engine.proposalOptions(s).length,8);
  const id=s.selectedIds[0];s=result.engine.removeMember(s,id);s=result.engine.addReplacement(s,id);
  assert.match(result.engine.proposalView(s).selected[0].evidence.why_person,/not a capability certificate/);
  const before=requests.length;await client.load(f.index,f.directory,options(f,{fetcher,deliberate:true}));assert.equal(requests.length,before);
  assert.equal(requests.filter(r=>r.method==='POST').length,1);
});
test('retry/error/cache miss, currentness, corrupt graphs, mixed registry and wrong parent fail without hidden paid work',async()=>{
  const f=fixture(),c=context(f);let posts=0;
  const fetcher=async(url,o)=>{if(o.method==='POST')posts++;return response({release_id:f.index.release_id,scope_id:f.scope.id,state:'unassessed'});};
  await c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher}));assert.equal(posts,0);
  await assert.rejects(c.ContextualTeamClient.load(f.index,{...f.directory,registry_generation:'0'.repeat(64)},options(f,{fetcher,deliberate:true})),/registry_version_conflict/);
  await assert.rejects(c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher,deliberate:true,now:'2040-01-01'})),/not_current/);
  const wrong=await c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher,deliberate:true,scopeId:'344592:ab-0025'}));
  assert.equal(wrong.engine.resolveScope().reason,'specific_scope_required');assert.equal(posts,0);
  const corrupt=async()=>response({release_id:f.index.release_id,scope_id:f.scope.id,state:'ready',result:{...f.graph,objective:'corrupt'}});
  await assert.rejects(c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher:corrupt})),/graph_content_conflict/);assert.equal(posts,0);
});
test('shared pending request has one dispatch; cancellation discards a late result; a later visitor reads completion',async()=>{
  const f=fixture(),c=context(f),abort=new AbortController();let posts=0,release;
  const pause=new Promise(r=>release=r),fetcher=async(url,o)=>{
    if(o.method==='POST'){posts++;await pause;return response({release_id:f.index.release_id,scope_id:f.scope.id,state:'ready',result:f.graph});}
    return response({release_id:f.index.release_id,scope_id:f.scope.id,state:'unassessed'});};
  const first=c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher,deliberate:true,signal:abort.signal}));
  const second=c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher,deliberate:true}));
  for(let i=0;i<100&&posts===0;i++)await tick();assert.equal(posts,1);abort.abort();release();
  await assert.rejects(first,/cancelled/);assert.equal((await second).engine.proposal().selectedIds.length,2);
  await c.ContextualTeamClient.load(f.index,f.directory,options(f,{fetcher,deliberate:true}));assert.equal(posts,1);
});
test('existing drawer uses contextual lazy adapter with real audited profiles, truthful labels, options and manual edits',async()=>{
  const f=fixture(),dom=shellDom(read('match_explorer.html')),c=dom.context,requests=[];let dispatched=false;
  Object.assign(c,{URL,URLSearchParams,Date,TextEncoder,TextDecoder,Uint8Array,AbortController,clearTimeout,crypto:webcrypto,btoa,
    location:{href:'https://example.org/match_explorer.html'},OPPORTUNITY_TEAM_INDEX:f.index,RESEARCHER_DIRECTORY:f.directory,GRANT_CATALOG:f.inputs.catalog,
    FUNDING_SUBTOPICS:{loadSidecar:async()=>f.inputs.sidecar},
    FUNDING_FINDER_APP:{boundedScripts:{sidecar:{setTimeout:cb=>setTimeout(cb,5000),clearTimeout}}}});
  dom.document.querySelector('meta[name="opportunity-team-generation"]').setAttribute('content',f.index.generation_id);
  dom.document.getElementById('results').innerHTML='<article class="result-card"><button data-opportunity-team="361207" id="open-contextual">Build team</button></article>';
  c.fetch=async(url,o)=>{assert(url.startsWith(f.index.endpoint));requests.push(o.method||'GET');if(o.method==='POST')dispatched=true;
    return response({release_id:f.index.release_id,scope_id:f.scope.id,state:dispatched?'ready':'unassessed',result:dispatched?f.graph:undefined});};
  dom.document.head=dom.document.querySelector('head');dom.document.head.appendChild=script=>{
    const name=script.src.split('?')[0];assert(['assets/contextual-team-engine.js','assets/contextual-team-client.js'].includes(name));
    vm.runInContext(read(name),c);queueMicrotask(()=>dom.dispatch('load',script));};
  vm.createContext(c);for(const p of ['site-shell','submission-schedule','search-query','search-retrieval','opportunity-team','opportunity-team-panel'])vm.runInContext(read('assets/'+p+'.js'),c);
  assert.equal(requests.length,0);dom.dispatch('click',dom.document.getElementById('open-contextual'));
  const drawer=dom.document.getElementById('team-builder');
  for(let i=0;i<100&&!drawer.querySelector('.opportunity-team-next');i++)await tick();
  assert.match(drawer.textContent,/Coverage unconfirmed/,drawer.querySelector('.opportunity-team-body')?.dataset.error);assert.equal(drawer.querySelectorAll('[data-opportunity-team-variant]').length,8);
  const before=requests.length;dom.dispatch('click',drawer.querySelector('[data-opportunity-team-remove]'));
  const select=drawer.querySelector('[data-opportunity-team-replacement]');select.value=select.querySelectorAll('option')[1].getAttribute('value');dom.dispatch('change',select);
  dom.dispatch('click',drawer.querySelector('[data-opportunity-team-add-replacement]'));assert.equal(requests.length,before);
  assert.equal(requests.filter(r=>r==='POST').length,1);assert(drawer.querySelector('.opportunity-team-next a'));
});
