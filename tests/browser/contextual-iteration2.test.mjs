import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {DatabaseSync} from 'node:sqlite';
import {createHash,webcrypto} from 'node:crypto';
import {gunzipSync} from 'node:zlib';
import {ContextualStore,createContextualHandler} from '../../workers/researcher-intake/src/contextual.js';
import {previewResponse} from '../../workers/researcher-intake/src/contextual-preview.js';
const plan=JSON.parse(fs.readFileSync('config/contextual_team/iteration2-authority-v1.json'));
const source=JSON.parse(fs.readFileSync('config/contextual_team/iteration2-source-inputs-v1.json'));
const overlay=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-iteration2-preview-v1.json'));
const base=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const hash=x=>createHash('sha256').update(canonical(x)).digest('hex');
const code=name=>gunzipSync(Buffer.from((overlay.files[name]||base.files[name]).gzip_base64,'base64')).toString();
function fixture(){
  const db=new DatabaseSync(':memory:');
  for(const p of ['0005_contextual_validation_jobs.sql','0006_contextual_trial_controls.sql'])db.exec(fs.readFileSync('workers/researcher-intake/migrations/'+p,'utf8'));
  const query=(sql,args=[])=>({bind:(...values)=>query(sql,values),first:async()=>db.prepare(sql).get(...args)||null,
    run:async()=>({meta:{changes:db.prepare(sql).run(...args).changes}})});
  const store=new ContextualStore({prepare:sql=>query(sql)}),calls=[],clock={value:new Date('2026-09-21T19:00:00Z')};
  const handler=createContextualHandler({storeFactory:()=>store,now:()=>clock.value,
    authenticateAdmin:async()=> 'fixture-admin',authenticateInternal:async()=> 'fixture-internal',
    fetchImpl:async(url,o)=>{calls.push({url,o});return new Response(null,{status:204});}});
  const request=(path,value)=>new Request('https://example.test'+path,{method:value?'POST':'GET',
    headers:{Origin:'https://example.test','Content-Type':'application/json'},...(value?{body:JSON.stringify(value)}:{})});
  return {db,store,calls,clock,handler,request,env:{GITHUB_REPOSITORY:'fixture/repo',GITHUB_DISPATCH_TOKEN:'fixture-token'},
    job:{release_id:plan.release_id,scope_id:plan.first_scope_id,person_id:''}};
}

test('I2 is opt-in, finite and shares concurrent first builds without repeat purchase',async()=>{
  const f=fixture();
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).status,403);
  assert.equal(f.calls.length,0);
  await f.handler(f.request('/admin/api/contextual/controls?release_id='+plan.release_id,{cached_enabled:true,new_paid_enabled:true}),f.env);
  const results=await Promise.all(Array.from({length:5},()=>f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)));
  assert.equal(results.filter(r=>r.status===202).length,1);assert.equal(f.calls.length,1);
  for(let i=0;i<4;i++)await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.job)),f.env);
  assert.equal(f.calls.length,1);
  const row=f.db.prepare('SELECT * FROM contextual_validation_jobs').get();
  await f.store.start(row.job_id,'123','a'.repeat(40),'now');
  await f.store.finish(row.job_id,'123','a'.repeat(40),JSON.stringify({result:{state:'failed',reason:'provider_fixture'}}),'now');
  assert.equal((await (await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).json()).state,'failed');
  assert.equal(f.calls.length,1);
});

test('I2 controls cannot activate confirmation, extra people or forecasted source cases',async()=>{
  const f=fixture();await f.store.setControls(plan.release_id,{cached_enabled:true,new_paid_enabled:true},'now');
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',{...f.job,scope_id:'not-in-development'}),f.env)).status,400);
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',{...f.job,person_id:'urh-000001'}),f.env)).status>=400,true);
  for(const s of source.scopes.filter(s=>s.state==='action_blocked')){
    const r=await (await f.handler(f.request('/admin/api/contextual/jobs',{...f.job,scope_id:s.id}),f.env)).json();
    assert.equal(r.state,'action_blocked');
  }
  assert.equal(f.calls.length,0);
  const manifest=await (await f.handler(f.request('/admin/api/contextual/manifest?iteration=2'),f.env)).json();
  assert.equal(manifest.scopes.length,12);assert.equal(manifest.public_activation,false);
});

test('DOE official time cutoff blocks new jobs at 17:00 Eastern',async()=>{
  const f=fixture();await f.store.setControls(plan.release_id,{cached_enabled:true,new_paid_enabled:true},'now');
  const s=source.scopes.find(s=>s.id===f.job.scope_id);assert.equal(s.currentness.not_after,'2026-09-22T21:00:00Z');
  f.clock.value=new Date('2026-09-22T21:00:00Z');
  const result=await (await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).json();
  assert.equal(result.state,'action_blocked');assert.equal(f.calls.length,0);
});

test('restricted overlay has exact readable assets and preserves old preview bytes',async()=>{
  assert.equal(overlay.base_bundle_id,base.bundle_id);assert.equal(overlay.provider_results,0);assert.equal(overlay.public_activation,false);
  const {bundle_id,...content}=overlay;assert.equal(hash(content),bundle_id);
  for(const [name,file] of Object.entries(overlay.files)){
    const raw=gunzipSync(Buffer.from(file.gzip_base64,'base64'));assert.equal(createHash('sha256').update(raw).digest('hex'),file.sha256);
    if(name.startsWith('assets/'))assert.equal(fs.readFileSync('workers/researcher-intake/iteration2-source/'+name,'utf8'),raw.toString());
  }
  assert.equal(previewResponse('/admin/contextual/preview/assets/contextual-team-engine.js').headers.get('X-Content-SHA256'),base.files['assets/contextual-team-engine.js'].sha256);
  assert.equal(previewResponse('/admin/contextual/iteration2/assets/contextual-team-engine.js').headers.get('X-Content-SHA256'),overlay.files['assets/contextual-team-engine.js'].sha256);
  for(const name of ['match_explorer.html','team_match.html']){
    assert.match(code(name),/<base href="\/admin\/contextual\/iteration2\/">/);
    assert(code(name).includes(overlay.index_generation));assert(!code(name).includes(base.index_generation));
  }
  const ui=vm.createContext({URL,URLSearchParams,console});
  vm.runInContext(code('data/opportunity_team_index.js'),ui);
  vm.runInContext(code('assets/opportunity-team.js'),ui);
  assert.equal(ui.OpportunityTeam.validateIndex(ui.OPPORTUNITY_TEAM_INDEX,overlay.index_generation).scopes.length,12);
});

function graphFixture(){
  const c=vm.createContext({URL,Date});
  for(const name of ['data/researcher_directory.js','assets/contextual-team-engine.js'])vm.runInContext(code(name),c);
  const directory=c.RESEARCHER_DIRECTORY,people=directory.researchers.filter(c.ContextualTeamEngine.eligible).slice(0,3);
  const role={id:'role-1',label:'Fixture contribution',required:true,central:true,kind:'approach_necessary',applicability:'applies',condition:''};
  const graph={version:'contextual-audited-graph-v3',graph_id:'a'.repeat(64),snapshot_id:plan.release_id,registry_generation:directory.registry_generation,
    source_id:'b'.repeat(64),roster_id:'c'.repeat(64),scope:{id:'fixture',parent_id:'fixture'},state:'ready',roles:[role],
    requirement_policy:'contextual-selected-approach-v2',approach:'Fixture source-warranted approach',
    people:people.map(p=>({person_id:p.id,outcome:'supported'})),pair_decisions:[],edges:[],
    provenance:{all_pair_decisions_retained:true,independent_checker_used_for_admission:false,
      ...Object.fromEntries(['input_sha256','active_input_sha256','pair_input_sha256','assessment_sha256','verification_sha256'].map(k=>[k,'d'.repeat(64)]))}};
  for(const p of people){const claim=p.claims.find(c=>c.status==='active'),d={role_id:role.id,coverage:'direct',central:true,claims:[claim],reason:'Fixture scientific support only.',gap:''};
    graph.pair_decisions.push({person_id:p.id,outcome:'supported',decisions:[d]});
    graph.edges.push({person_id:p.id,role_id:role.id,claim_id:claim.claim_id,claim_revision:claim.revision,evidence_quote:claim.evidence,
      supporting_claims:[claim],coverage:d.coverage,central:true,reason:d.reason,gap:''});}
  const expected={...graph,scope_id:'fixture',parent_id:'fixture'};return {c,graph,directory,expected};
}

test('v3 renderer requires complete decisions and exact useful-edge equality',()=>{
  const f=graphFixture();f.c.ContextualTeamEngine.validateGraph(f.graph,f.directory,f.expected);
  for(const mutate of [g=>g.pair_decisions.pop(),g=>g.pair_decisions[0].decisions.pop(),g=>g.edges.pop(),
    g=>g.edges[0].supporting_claims[0].revision++,g=>g.pair_decisions[0].decisions[0].claims.push(g.pair_decisions[0].decisions[0].claims[0]),
    g=>g.edges[0].coverage='method_transfer',g=>g.people[0].outcome='adjacent',g=>g.registry_generation='f'.repeat(64)]){
    const graph=structuredClone(f.graph);mutate(graph);assert.throws(()=>f.c.ContextualTeamEngine.validateGraph(graph,f.directory,f.expected));
  }
});

test('all locked current catalog projections resolve without a paid dispatch',async()=>{
  const c=vm.createContext({URL,URLSearchParams,Date,TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,setTimeout,clearTimeout});
  for(const name of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js',
    'data/researcher_directory.js','data/opportunities.js','data/subtopics.js','data/opportunity_team_index.js',
    'assets/contextual-team-engine.js','assets/contextual-team-client.js'])vm.runInContext(code(name),c,{filename:name});
  const index=c.OPPORTUNITY_TEAM_INDEX,childCatalog=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG);let calls=0;
  for(const scope of index.scopes){
    const parent=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===scope.parent_id);
    const loaded=await c.ContextualTeamClient.load(index,c.RESEARCHER_DIRECTORY,{parentId:scope.parent_id,scopeId:scope.id,
      record:parent,childCatalog,now:'2026-09-21T19:00:00Z',fetcher:async(_url,options)=>{
        assert.notEqual(options.method,'POST');calls++;return Response.json({release_id:index.release_id,scope_id:scope.id,state:'unassessed'});
      }});
    assert(loaded.engine);
  }
  assert.equal(calls,8);
  const scope=index.scopes.find(s=>s.id===plan.first_scope_id),parent=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===scope.parent_id);
  await assert.rejects(c.ContextualTeamClient.load(index,c.RESEARCHER_DIRECTORY,{parentId:scope.parent_id,scopeId:scope.id,
    record:parent,childCatalog,now:'2026-09-22T21:00:00Z',fetcher:async()=>{throw Error('must not fetch after cutoff');}}),/not_current/);
});
