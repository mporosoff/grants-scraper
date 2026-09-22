// Actual restricted client/engine and complete public inputs. Synthetic graph;
// no providers, network, browser UI, timing thresholds or scientific fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createHash,webcrypto} from 'node:crypto';
import {gunzipSync} from 'node:zlib';

const overlay=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration2-preview-v1.json'));
const base=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const code=name=>name.startsWith('assets/contextual-')
  ?fs.readFileSync('workers/researcher-intake/iteration2-source/'+name,'utf8')
  :gunzipSync(Buffer.from((overlay.files[name]||base.files[name]).gzip_base64,'base64')).toString();
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'
  ?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const hash=v=>createHash('sha256').update(canonical(v)).digest('hex');
const NOW='2026-09-21T19:00:00Z';
class Clock extends Date{constructor(...args){super(...(args.length?args:[NOW]));}static now(){return +new Date(NOW);}}
const plain=v=>JSON.parse(JSON.stringify(v));
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};

function fixture(){
  const c=vm.createContext({URL,URLSearchParams,Date:Clock,TextEncoder,TextDecoder,Uint8Array,
    crypto:webcrypto,AbortController,Response,fetch:()=>assert.fail('real network prohibited'),
    setTimeout:()=>assert.fail('cached fixture must not poll'),clearTimeout(){}});
  for(const name of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js',
    'data/researcher_directory.js','data/opportunities.js','data/subtopics.js','data/opportunity_team_index.js',
    'assets/contextual-team-engine.js','assets/contextual-team-client.js'])vm.runInContext(code(name),c,{filename:name});
  assert.equal(c.ContextualTeamClient.VERSION,'contextual-client-v4');
  const index=c.OPPORTUNITY_TEAM_INDEX,directory=c.RESEARCHER_DIRECTORY,scope=index.scopes.find(s=>s.id==='363302:a-1');
  const parent=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===scope.parent_id);
  const childCatalog=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG),calls=[];
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
  const response=()=>Response.json({release_id:index.release_id,scope_id:scope.id,state:'ready',result:graph});
  const options={parentId:scope.parent_id,scopeId:scope.id,record:parent,childCatalog,now:NOW,
    fetcher:async(_url,o)=>{calls.push(o.method||'GET');return response();}};
  return {c,index,directory,scope,parent,childCatalog,graph,calls,options,response,
    load:more=>c.ContextualTeamClient.load(c.OPPORTUNITY_TEAM_INDEX,c.RESEARCHER_DIRECTORY,{...options,...more}),
    stats:()=>plain(c.ContextualTeamClient.statistics())};
}

test('one private hydrated engine serves independent wrappers without repeated full-directory work',async()=>{
  const f=fixture(),first=await f.load(),proposal=plain(first.engine.proposal()),wrappers=[first.engine];
  for(let n=0;n<10;n++){
    const next=await f.load();wrappers.push(next.engine);assert.deepEqual(plain(next.engine.proposal()),proposal);
  }
  assert.equal(new Set(wrappers).size,11);
  assert.equal(new Set(wrappers.map(e=>e.proposal)).size,1);
  assert.deepEqual(f.calls,['GET']);
  assert.deepEqual(f.stats(),{cached_scopes:1,pending:0,hydrations:1,hydration_hits:10,directory_checks:1,directory_hits:10,hydrated_scopes:1});
  first.engine.facultyById.clear();first.engine.opportunityById.clear();first.engine.data.faculty.length=0;
  const next=await f.load();assert.equal(next.engine.facultyById.size,f.directory.researchers.length);
  assert.equal(next.engine.data.faculty.length,f.directory.researchers.length);
  assert.deepEqual(plain(next.engine.proposal()),proposal);
  const start=next.engine.proposal(),id=next.engine.data.faculty[0].id;
  const edited=next.engine.removeMember(start,id);
  assert.deepEqual(plain(start),proposal);assert.deepEqual(plain((await f.load()).engine.proposal()),proposal);
  assert.notStrictEqual(start,edited);assert.equal(f.stats().hydrated_scopes,1);
});

test('changed source, unassessed profiles, manifest and source clock cannot reuse the old admission',async()=>{
  const f=fixture();await f.load();
  const childCatalog=structuredClone(f.childCatalog),record=childCatalog.opportunities.find(r=>r.opportunity_id===f.scope.id);
  const field=f.index.source_fields.find(k=>record[k]!==undefined);record[field]+=' changed source';
  await assert.rejects(f.load({childCatalog}),/source_version_conflict/);
  await assert.rejects(f.load({now:'2026-09-22T21:00:00Z'}),/not_current/);
  const changed=structuredClone(f.directory);changed.researchers.at(-1).name+=' changed unassessed person';
  await assert.rejects(f.c.ContextualTeamClient.load(f.index,changed,f.options),/directory_content_conflict/);
  const changedIndex=structuredClone(f.index);changedIndex.scopes[0].source_id='f'.repeat(64);
  await assert.rejects(f.c.ContextualTeamClient.load(changedIndex,f.directory,f.options),/index_content_conflict/);
  assert.throws(()=>{f.directory.researchers.at(-1).name+=' in place';},TypeError);
  assert.throws(()=>{f.scope.currentness.not_after='2100-01-01T00:00:00Z';},TypeError);
  assert.equal(f.stats().hydrations,1);assert.deepEqual(f.calls,['GET']);
});

test('byte-identical replacement snapshots and a new engine module fully validate and rehydrate',async()=>{
  const f=fixture();const original=(await f.load()).engine;
  f.c.RESEARCHER_DIRECTORY=structuredClone(f.directory);
  const replaced=(await f.load()).engine;
  assert.notStrictEqual(replaced.proposal,original.proposal);assert.equal(f.stats().directory_checks,2);
  f.c.ContextualTeamEngine=Object.freeze({...f.c.ContextualTeamEngine});
  const moduleChanged=(await f.load()).engine;
  assert.notStrictEqual(moduleChanged.proposal,replaced.proposal);assert.equal(f.stats().directory_checks,3);
  f.c.OPPORTUNITY_TEAM_INDEX=structuredClone(f.index);
  await f.load();assert.equal(f.stats().hydrations,4);assert.equal(f.stats().hydrated_scopes,1);
  assert.deepEqual(f.calls,['GET']);
});

test('caller-owned option objects and public maps cannot poison another cached wrapper',async()=>{
  const f=fixture(),options={...f.options};
  const first=await f.c.ContextualTeamClient.load(f.index,f.directory,options);
  const before=plain(first.engine.proposal());options.childCatalog={opportunities:[]};options.record={};
  const next=await f.load();assert.deepEqual(plain(next.engine.proposal()),before);
  assert.equal(f.stats().hydrations,1);
});

test('cancelled and replaced callers cannot populate hydration from a late shared graph',async()=>{
  for(const replacement of ['cancel','manifest','runtime']){
    const f=fixture(),gate=deferred(),started=deferred(),abort=new AbortController();
    const first=f.load({signal:abort.signal,fetcher:async()=>{started.resolve();return gate.promise;}});
    await started.promise;
    let error;
    if(replacement==='cancel'){error=/contextual_cancelled/;abort.abort();}
    if(replacement==='manifest'){error=/contextual_manifest_replaced/;f.c.OPPORTUNITY_TEAM_INDEX=structuredClone(f.index);}
    if(replacement==='runtime'){error=/contextual_runtime_replaced/;f.c.ContextualTeamEngine=Object.freeze({...f.c.ContextualTeamEngine});}
    const rejected=assert.rejects(first,error);gate.resolve(f.response());await rejected;
    assert.equal(f.stats().hydrations,0);
  }
});

test('optional phase callbacks never change the result, and cancelled waiters stop receiving shared phases',async()=>{
  const f=fixture(),gate=deferred(),started=deferred(),abort=new AbortController(),one=[],two=[];
  const first=f.load({signal:abort.signal,onPhase:name=>one.push(name),fetcher:async()=>{started.resolve();return gate.promise;}});
  await started.promise;
  const joined=deferred();const second=f.load({onPhase:name=>{two.push(name);if(name==='shared_join')joined.resolve();}});
  await joined.promise;const cancelled=assert.rejects(first,/contextual_cancelled/);abort.abort();await cancelled;
  const count=one.length;gate.resolve(f.response());await second;
  assert.equal(one.length,count);assert(two.includes('shared_join'));assert(two.includes('service_end'));
  assert(!two.includes('service_start'));assert.equal(f.stats().hydrations,1);
  const next=await f.load({onPhase(){throw Error('diagnostic consumer failed');}});
  assert.equal(next.graph_id,f.graph.graph_id);assert.equal(f.stats().hydration_hits,1);
  const phases=[];await f.load({onPhase:name=>phases.push(name)});
  assert.deepEqual(phases,['load_start','index_valid','directory_reused','source_current','graph_cache_hit','graph_accepted','engine_reused']);
});

test('cancellation at a supplemental hydration boundary still cannot return a proposal',async()=>{
  for(const boundary of ['engine_start','engine_ready','engine_reused']){
    const f=fixture(),abort=new AbortController();
    if(boundary==='engine_reused')await f.load();
    await assert.rejects(f.load({signal:abort.signal,onPhase:name=>{if(name===boundary)abort.abort();}}),/contextual_cancelled/);
    assert.equal(f.stats().hydrations,boundary==='engine_reused'?1:0);
    assert.equal(f.stats().hydrated_scopes,boundary==='engine_reused'?1:0);
  }
});

function checkedAbstention(f){
  const g=structuredClone(f.graph);g.roles[0].source_ref='source-1';delete g.graph_id;g.graph_id=hash(g);
  const original=structuredClone(g),eligible=f.directory.researchers.filter(f.c.ContextualTeamEngine.eligible).map(p=>p.id).sort();
  const candidates=plain(f.c.ContextualTeamEngine.candidateGroups(g,eligible)).map((ids,i)=>({candidate_id:'g'+String(i+1).padStart(2,'0'),member_ids:ids}));
  const edges=g.edges.slice().sort((a,b)=>a.person_id.localeCompare(b.person_id)||a.role_id.localeCompare(b.role_id));
  const supports=edges.map((e,i)=>({support_id:'s'+String(i+1).padStart(2,'0'),person_id:e.person_id,role_id:e.role_id,
    source_ref:'source-1',retained_claim_refs:e.supporting_claims.map(c=>c.claim_id+'@'+c.revision)}));
  const people=[...new Set(candidates.flatMap(c=>c.member_ids))].sort();
  g.version='contextual-audited-graph-v4';g.state='no_supported_group_in_checked_candidates';
  g.base_graph_id=original.graph_id;g.base_graph_sha256=hash(original);
  g.provenance.integrity_version='contextual-production-integrity-v1';g.provenance.integrity_sha256='d'.repeat(64);
  g.integrity={version:'contextual-production-integrity-v1',selection_version:'contextual-integrity-candidates-v1',
    independent_evaluation:false,human_labels_added:0,input_sha256:'d'.repeat(64),contract_sha256:'d'.repeat(64),
    base_graph_id:g.base_graph_id,base_graph_sha256:g.base_graph_sha256,source_sha256:g.source_id,
    approach_id:'d'.repeat(64),candidate_list_sha256:hash(candidates),eligible_ids:eligible,candidate_groups:candidates,supports,
    groups:candidates.map(c=>({candidate_id:c.candidate_id,status:'unsupported',source_refs:['source-1'],common_operation:'',
      coordination:'Synthetic coordinated operation not established.',limitations:'Synthetic evidence does not justify an automatic group.',
      members:c.member_ids.map(person_id=>({person_id,support_ids:supports.filter(s=>s.person_id===person_id).map(s=>s.support_id),
        contribution:'Synthetic individual contribution remains unchanged.',limits:'Synthetic shared operation remains unconfirmed.'}))})),
    explanations:people.map((person_id,i)=>{const e=edges.find(e=>e.person_id===person_id),s=supports.find(s=>s.person_id===person_id&&s.role_id===e.role_id);
      return {presentation_id:'e'+String(i+1).padStart(2,'0'),person_id,role_id:e.role_id,support_id:s.support_id,
        documented_claims:e.supporting_claims,potential_project_relevance:'Synthetic possible relevance only, not completed work.',
        unconfirmed_operation_or_limit:'Synthetic application remains unconfirmed.'};}),disposition:'complete'};
  delete g.graph_id;g.graph_id=hash(g);return g;
}

test('v4 checked-candidate abstention is strictly validated and cached without manufacturing groups',async()=>{
  const f=fixture(),graph=checkedAbstention(f);let gets=0;
  const fetcher=async()=>{gets++;return Response.json({release_id:f.index.release_id,scope_id:f.scope.id,state:graph.state,result:graph});};
  const first=await f.load({fetcher});assert.deepEqual(plain(first.engine.proposal().selectedIds),[]);
  assert.deepEqual(plain(first.engine.proposalOptions(first.engine.proposal())),[]);
  assert.equal(first.engine.proposalView(first.engine.proposal()).assessed_people_count,3);
  await f.load({fetcher});assert.equal(gets,1);assert.equal(f.stats().hydrations,1);assert.equal(f.stats().hydration_hits,1);
  for(const mutate of [g=>g.integrity.groups.pop(),g=>{g.integrity.supports[0].person_id='foreign';}]){
    const bad=fixture(),tampered=checkedAbstention(bad);mutate(tampered);delete tampered.graph_id;tampered.graph_id=hash(tampered);
    await assert.rejects(bad.load({fetcher:async()=>Response.json({release_id:bad.index.release_id,scope_id:bad.scope.id,state:tampered.state,result:tampered})}),/integrity_/);
    assert.equal(bad.stats().hydrations,0);
  }
});

test('checked-candidate envelope does not expand the historical v3 acceptance states',async()=>{
  const f=fixture(),state='no_supported_group_in_checked_candidates';
  const result=await f.load({fetcher:async()=>Response.json({release_id:f.index.release_id,scope_id:f.scope.id,state,result:f.graph})});
  assert.equal(result.engine.resolveScope().reason,'contextual_'+state);assert.equal(f.stats().hydrations,0);
});
