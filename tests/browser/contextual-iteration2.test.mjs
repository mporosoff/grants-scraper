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
    fetchImpl:async(url,o)=>{calls.push({url,o});return url.includes('/actions/runs/')
      ?Response.json({path:'.github/workflows/team-recommender-offline.yml',event:'repository_dispatch',head_branch:'main',head_sha:'a'.repeat(40)})
      :new Response(null,{status:204});}});
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

test('I2 maximum graph with Unicode survives its callback envelope, persisted reload and repeat callback',async()=>{
  const f=fixture(),job={...f.job,job_id:hash([f.job.release_id,f.job.scope_id,''])};
  await f.store.insert(job,'now');await f.store.start(job.job_id,'123','a'.repeat(40),'now');
  const graph={state:'ready_with_gaps',scope_id:job.scope_id,wire_boundary_fixture:''};
  const fill=plan.maximum_graph_bytes-Buffer.byteLength(JSON.stringify(graph));
  graph.wire_boundary_fixture='α'.repeat(Math.floor(fill/2))+'x'.repeat(fill%2);
  assert.equal(Buffer.byteLength(JSON.stringify(graph)),plan.maximum_graph_bytes);
  const value={job_id:job.job_id,release_id:job.release_id,run_id:'123',code_sha:'a'.repeat(40),result:graph,
    charged_microusd:7424346,attempts:688,stage_timings:Array.from({length:20},()=>({stage:'fixture-boundary',seconds:123.45}))};
  assert(Buffer.byteLength(JSON.stringify(value))>plan.maximum_graph_bytes);
  for(let n=0;n<2;n++)assert.equal((await f.handler(f.request('/internal/contextual/result',value),f.env)).status,200);
  const stored=await f.store.byId(job.job_id);assert.equal(stored.active_slot,null);
  assert.deepEqual(JSON.parse(stored.result_json),value);
  const read=await f.handler(f.request('/admin/api/contextual/jobs?'+new URLSearchParams(f.job)),f.env);
  const raw=await read.text();assert(Buffer.byteLength(raw)>393216);assert(Buffer.byteLength(raw)<524288);
  assert.deepEqual(JSON.parse(raw).result,graph);
  const beforeRepeat=f.calls.length;
  assert.equal((await f.handler(f.request('/admin/api/contextual/jobs',f.job),f.env)).status,200);
  assert.equal(f.calls.length,beforeRepeat);
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...value,padding:'x'.repeat(524288)}),f.env)).status,413);
  assert.deepEqual(await f.store.byId(job.job_id),stored);
  const next={...f.job,scope_id:'351715',job_id:hash([f.job.release_id,'351715',''])};
  assert.equal(await f.store.insert(next,'later'),true);
  const historical=JSON.parse(fs.readFileSync('config/contextual_team/option1-v1.json')).release_id;
  assert.equal((await f.handler(f.request('/internal/contextual/result',{...value,release_id:historical}),f.env)).status,413);
  const compact=JSON.stringify({release_id:historical});
  const padded=new Request('https://example.test/internal/contextual/result',{method:'POST',
    body:compact+' '.repeat(200001-Buffer.byteLength(compact))});
  assert.equal((await f.handler(padded,f.env)).status,413,'historical bound measures raw bytes, including whitespace');
  assert(f.calls.every(c=>c.url.includes('/actions/runs/')),'no dispatch or paid work in callback/reload');
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

test('restricted bundled catalog boots through its actual loader and rejects inherited startup metadata',async()=>{
  const html=code('match_explorer.html'),team=code('team_match.html');
  const metadataPath=html.match(/<script src="([^"\n]*data\/catalog-metadata\.js\?v=[^"\n]+)"/)[1];
  const location=new URL('https://example.test'+overlay.base_path+'match_explorer.html');
  async function boot(metadataSource){
    const scripts=[],timers=new Map(),initialized=[];let nextTimer=0,context;
    const document={readyState:'loading',hidden:false,currentScript:null,
      scripts:[{src:new URL(metadataPath,location).href}],addEventListener(){},querySelectorAll:()=>[],
      createElement(tag){
        const events=new Map();
        return {tagName:tag,dataset:{},addEventListener:(name,callback)=>events.set(name,callback),
          removeEventListener:(name,callback)=>{if(events.get(name)===callback)events.delete(name);},
          remove(){},emit:name=>events.get(name)?.()};
      },
      head:{append(script){
        scripts.push(script.src);
        queueMicrotask(()=>{
          const url=new URL(script.src),name=url.pathname.slice(overlay.base_path.length);
          assert.equal(url.origin,location.origin);assert(url.pathname.startsWith(overlay.base_path));
          assert.equal(name,'data/opportunities.js');
          document.currentScript=script;
          try{vm.runInContext(code(name),context,{filename:name});}
          finally{document.currentScript=null;}
          script.emit('load');
        });
      }}};
    context=vm.createContext({URL,URLSearchParams,Date,console,document,location,navigator:{},
      performance:{getEntriesByName:()=>[],mark(){}},
      FUNDING_FINDER_SCRIPT_CLOCK:{setTimeout(callback,ms){const id=++nextTimer;timers.set(id,{callback,ms});return id;},
        clearTimeout:id=>timers.delete(id)}});
    vm.runInContext(code('assets/app-config.js'),context);
    vm.runInContext(metadataSource,context);
    vm.runInContext(code('assets/catalog-loader.js'),context);
    // Use the bundled application's real catalog validator, without booting its
    // unrelated DOM or issuing search/provider requests in this focused test.
    const app=code('assets/app.js'),start=app.indexOf('  function validateCatalog(value) {'),
      end=app.indexOf('  function markPerformance(',start);
    assert(start>=0&&end>start);
    vm.runInContext(app.slice(start,end)+'globalThis.fixtureValidateCatalog=validateCatalog;',context);
    const loader=context.FUNDING_CATALOG_LOADER;
    loader.configure({validate:context.fixtureValidateCatalog,initialize:(catalog,startup)=>initialized.push({catalog,startup})});
    return {context,loader,scripts,timers,initialized};
  }
  const stale=await boot(gunzipSync(Buffer.from(base.files['data/catalog-metadata.js'].gzip_base64,'base64')).toString());
  await assert.rejects(stale.loader.ensureCatalogReady(),/does not match its startup metadata/);
  assert.equal(stale.loader.getSnapshot().state,'failed');assert.equal(stale.initialized.length,0);
  assert.equal(stale.context.GRANT_CATALOG,undefined);assert.equal(stale.scripts.length,1);assert.equal(stale.timers.size,0);
  assert(Object.hasOwn(overlay.files,'data/catalog-metadata.js'),'current catalog must own its startup metadata');
  const ready=await boot(code('data/catalog-metadata.js'));
  const [first,second]=await Promise.all([ready.loader.ensureCatalogReady(),ready.loader.ensureCatalogReady()]);
  assert.strictEqual(first,second);assert.strictEqual(await ready.loader.ensureCatalogReady(),first);
  assert.equal(ready.loader.getSnapshot().state,'ready');assert.equal(ready.initialized.length,1);
  assert.equal(ready.scripts.length,1);assert.equal(ready.timers.size,0);
  assert.equal(ready.loader.getSnapshot().quarantinedCatalogAssignments,0);
  const metadata=ready.context.GRANT_CATALOG_METADATA;
  assert.equal(metadata.schema_version,1);assert.equal(metadata.catalog_schema_version,first.schema_version);
  assert.equal(metadata.record_count,first.record_count);assert.equal(metadata.record_count,first.opportunities.length);
  assert.equal(first.search_index.document_count,first.record_count);
  assert.equal(metadata.generated_at,first.generated_at);assert.deepEqual(metadata.status_counts,first.status_counts);
  assert.equal(metadata.release_identity,ready.loader.releaseIdentity(first));
  assert.equal(metadata.catalog_url,'./data/opportunities.js?v='+metadata.asset_version);
  assert.equal(new URL(ready.scripts[0]).searchParams.get('v'),metadata.asset_version);
  assert.equal(new URL(metadataPath,location).searchParams.get('v'),metadata.asset_version);
  const direct=team.match(/<script src="([^"\n]*data\/opportunities\.js\?v=[^"\n]+)"/)[1];
  assert.equal(new URL(direct,location).searchParams.get('v'),metadata.asset_version);
  assert([first.generated_at,first.detail_enrichment_generated_at,first.document_evidence_generated_at,
    first.catalog_audit_generated_at,first.link_health_generated_at,first.diagnostics?.additional_sources?.merged_at]
    .includes(metadata.pipeline_generated_at));
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
  const options={parentId:scope.parent_id,scopeId:scope.id,record:parent,childCatalog,now:'2026-09-21T19:00:00Z'};
  const envelope={release_id:index.release_id,scope_id:scope.id,state:'failed',wire_boundary_fixture:'x'.repeat(400000)};
  assert((await c.ContextualTeamClient.load(index,c.RESEARCHER_DIRECTORY,{...options,
    fetcher:async()=>Response.json(envelope)})).engine);
  await assert.rejects(c.ContextualTeamClient.load(index,c.RESEARCHER_DIRECTORY,{...options,
    fetcher:async()=>Response.json({...envelope,wire_boundary_fixture:'x'.repeat(524288)})}),/contextual_response_too_large/);
});

test('restricted runtime reuse preserves graph cache, coalesces loads, and retries only failed script loads',async()=>{
  const f=graphFixture(),c=f.c,scripts=[],assets=new Map();let failClient=true,gets=0,posts=0;
  Object.assign(c,{URLSearchParams,TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,setTimeout,clearTimeout,btoa});
  for(const name of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js',
    'data/opportunities.js','data/subtopics.js','data/opportunity_team_index.js'])vm.runInContext(code(name),c);
  for(const name of ['contextual-team-engine','contextual-team-client']){
    const raw=code('assets/'+name+'.js'),digest=createHash('sha256').update(raw).digest('hex');
    assets.set(name+':'+digest,raw);
  }
  c.FUNDING_FINDER_APP={boundedScripts:{sidecar:{setTimeout:cb=>setTimeout(cb,5000),clearTimeout}}};
  c.document={createElement:()=>{const listeners={};return {addEventListener:(kind,fn)=>listeners[kind]=fn,
    remove(){},emit:kind=>listeners[kind]()};},head:{appendChild(script){
      const url=new URL(script.src,'https://fixture.test'),name=url.pathname.split('/').pop().replace('.js','');
      const digest=url.searchParams.get('v'),raw=assets.get(name+':'+digest);scripts.push(name);
      assert.equal(script.integrity,'sha256-'+Buffer.from(digest,'hex').toString('base64'));
      queueMicrotask(()=>{
        if(!raw||(name==='contextual-team-client'&&failClient)){failClient=false;script.emit('error');return;}
        vm.runInContext(raw,c);script.emit('load');
      });
    }}};
  vm.runInContext(code('assets/opportunity-team.js'),c);
  const index=c.OPPORTUNITY_TEAM_INDEX,scope=index.scopes.find(s=>s.id===plan.first_scope_id);
  const parent=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===scope.parent_id);
  const graph=structuredClone(f.graph);
  Object.assign(graph,{snapshot_id:index.release_id,source_id:scope.source_id,roster_id:index.roster_id,
    scope:{id:scope.id,parent_id:scope.parent_id,title:scope.scope_label}});
  delete graph.graph_id;graph.graph_id=hash(graph);
  const options={parentId:scope.parent_id,scopeId:scope.id,record:parent,
    childCatalog:c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG),now:'2026-09-21T19:00:00Z',
    deliberate:true,fetcher:async(_url,o)=>{if(o.method==='POST')posts++;else gets++;
      return Response.json({release_id:index.release_id,scope_id:scope.id,state:'ready',result:graph});}};
  await assert.rejects(c.OpportunityTeam.loadData(index.generation_id,options),/integrity\/load failure/);
  assert.equal(gets,0);assert.deepEqual(scripts,['contextual-team-engine','contextual-team-client']);
  const [first,second]=await Promise.all([c.OpportunityTeam.loadData(index.generation_id,options),
    c.OpportunityTeam.loadData(index.generation_id,options)]);
  assert.equal(first.graph_id,graph.graph_id);assert.equal(second.graph_id,graph.graph_id);
  const client=c.ContextualTeamClient,engine=c.ContextualTeamEngine;
  for(let n=0;n<10;n++)await c.OpportunityTeam.loadData(index.generation_id,options);
  assert.strictEqual(c.ContextualTeamClient,client);assert.strictEqual(c.ContextualTeamEngine,engine);
  assert.equal(gets,1);assert.equal(posts,0);
  assert.deepEqual(scripts,['contextual-team-engine','contextual-team-client','contextual-team-client']);
  await assert.rejects(c.OpportunityTeam.loadData(index.generation_id,{...options,now:'2026-09-22T21:00:00Z'}),/not_current/);
  c.RESEARCHER_DIRECTORY=structuredClone(c.RESEARCHER_DIRECTORY);c.RESEARCHER_DIRECTORY.researchers[154].name+=' changed';
  await assert.rejects(c.OpportunityTeam.loadData(index.generation_id,options),/directory_content_conflict/);
  assert.equal(gets,1);assert.equal(posts,0);
  c.RESEARCHER_DIRECTORY=f.directory;
  const replacementRaw=code('assets/contextual-team-client.js')+'\n// New exact runtime fixture identity.\n';
  const replacementHash=createHash('sha256').update(replacementRaw).digest('hex');
  assets.set('contextual-team-client:'+replacementHash,replacementRaw);
  const replacement=structuredClone(index);replacement.runtime.contextual_client=replacementHash;
  delete replacement.generation_id;replacement.generation_id=hash(replacement);c.OPPORTUNITY_TEAM_INDEX=replacement;
  await c.OpportunityTeam.loadData(replacement.generation_id,options);
  assert.notStrictEqual(c.ContextualTeamClient,client);assert.strictEqual(c.ContextualTeamEngine,engine);
  assert.equal(scripts.length,4);assert.equal(gets,2);assert.equal(posts,0);
  const replacedClient=c.ContextualTeamClient;c.ContextualTeamClient={load(){throw Error('unexpected module');}};
  await c.OpportunityTeam.loadData(replacement.generation_id,options);
  assert.notStrictEqual(c.ContextualTeamClient,replacedClient);assert.equal(scripts.length,5);
  assert.equal(gets,3);assert.equal(posts,0);
});
