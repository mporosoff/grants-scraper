// Actual restricted application bytes with fixture relationships, zero network.
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import {gunzipSync} from 'node:zlib';
import {createHash,webcrypto} from 'node:crypto';
import {shellDom} from '../helpers/shell-dom.mjs';
const bundle=JSON.parse(fs.readFileSync('workers/researcher-intake/config/contextual-preview-v1.json'));
const code=name=>gunzipSync(Buffer.from(bundle.files[name].gzip_base64,'base64')).toString('utf8');
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const hash=v=>createHash('sha256').update(canonical(v)).digest('hex');
function context(){
  const c=vm.createContext({URL,URLSearchParams,Date,TextEncoder,TextDecoder,Uint8Array,crypto:webcrypto,setTimeout,clearTimeout});
  for(const name of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js',
    'data/researcher_directory.js','data/opportunities.js','data/subtopics.js','data/opportunity_team_index.js',
    'assets/contextual-team-engine.js','assets/contextual-team-client.js'])vm.runInContext(code(name),c,{filename:name});
  return c;
}
function fixtureGraph(c){
  const index=c.OPPORTUNITY_TEAM_INDEX,s=index.scopes[0],directory=c.RESEARCHER_DIRECTORY;
  const ids=directory.researchers.filter(c.ContextualTeamEngine.eligible).slice(0,3),raw={
    version:'contextual-audited-graph-v1',snapshot_id:index.release_id,registry_generation:index.registry_generation,
    source_id:s.source_id,roster_id:index.roster_id,state:'ready',scope:{id:s.id,parent_id:s.parent_id,title:s.scope_label},
    objective:'Synthetic transport fixture only',roles:[{id:'role-1',label:'Fixture',central:true,required:false}],
    people:ids.map(p=>({person_id:p.id,outcome:'supported'})),edges:ids.map(p=>{
      const cl=p.claims.find(v=>v.status==='active');return {person_id:p.id,role_id:'role-1',claim_id:cl.claim_id,
        claim_revision:cl.revision,evidence_quote:cl.evidence,coverage:'method_transfer',central:true,
        reason:'Transport fixture, not scientific validation.',gap:'Fixture only.'};})};
  return {...raw,graph_id:hash(raw)};
}
test('compressed changed scripts have exact readable review copies',()=>{
  for(const [name,file] of Object.entries(bundle.files)){
    const raw=gunzipSync(Buffer.from(file.gzip_base64,'base64'));assert.equal(createHash('sha256').update(raw).digest('hex'),file.sha256);
    const copied='workers/researcher-intake/preview-source/'+name;
    if(fs.existsSync(copied))assert.equal(fs.readFileSync(copied,'utf8'),raw.toString());
  }
});
test('real canonical child and official supplement adopt one graph; edits and repeats stay local',async()=>{
  const c=context(),index=c.OPPORTUNITY_TEAM_INDEX,s=index.scopes[0],directory=c.RESEARCHER_DIRECTORY;
  const parent=c.GRANT_CATALOG.opportunities.find(r=>r.opportunity_id===s.parent_id);
  const childCatalog=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG);
  assert(childCatalog,'real native child catalog');
  const ids=directory.researchers.filter(c.ContextualTeamEngine.eligible).slice(0,3),raw={
    version:'contextual-audited-graph-v1',snapshot_id:index.release_id,registry_generation:index.registry_generation,
    source_id:s.source_id,roster_id:index.roster_id,state:'ready',scope:{id:s.id,parent_id:s.parent_id,title:s.scope_label},
    objective:'Synthetic transport fixture only',roles:[{id:'role-1',label:'Fixture',central:true,required:false}],
    people:ids.map(p=>({person_id:p.id,outcome:'supported'})),edges:ids.map(p=>{
      const cl=p.claims.find(v=>v.status==='active');return {person_id:p.id,role_id:'role-1',claim_id:cl.claim_id,
        claim_revision:cl.revision,evidence_quote:cl.evidence,coverage:'method_transfer',central:true,
        reason:'Transport fixture, not scientific validation.',gap:'Fixture only.'};})};
  const graph={...raw,graph_id:hash(raw)};let posts=0,gets=0,ready=false;
  const fetcher=async(url,o)=>{if(o.method==='POST'){posts++;ready=true;}else gets++;
    return new Response(JSON.stringify({release_id:index.release_id,scope_id:s.id,state:ready?'ready':'unassessed',result:ready?graph:undefined}));};
  const options={parentId:s.parent_id,scopeId:s.id,record:parent,childCatalog,now:'2026-09-13T12:00:00Z',fetcher};
  const unassessed=directory.researchers.filter(c.ContextualTeamEngine.eligible)[5].id;
  await assert.rejects(c.ContextualTeamClient.load(index,directory,{...options,personId:unassessed,deliberate:true}),/person_assessment_not_enabled/);
  assert.equal(posts,0);assert.equal(gets,0);
  await c.ContextualTeamClient.load(index,directory,options);assert.equal(posts,0);
  const loaded=await c.ContextualTeamClient.load(index,directory,{...options,deliberate:true});
  let state=loaded.engine.proposal(),id=state.selectedIds[0];
  state=loaded.engine.removeMember(state,id);state=loaded.engine.addReplacement(state,id);
  assert.equal(state.selectedIds.length,2);assert.equal(posts,1);
  const before=gets;await c.ContextualTeamClient.load(index,directory,{...options,deliberate:true});assert.equal(gets,before);
  assert.throws(()=>loaded.engine.runAction({parentId:s.parent_id,scopeId:s.id,now:'2026-09-23T12:00:00Z'},()=>loaded.engine.proposal()),/not_current/);
  assert.equal(posts,1);
});

test('disabled extension has no button or dispatch; unassessed people remain manually editable',async()=>{
  const data=context(),dom=shellDom(code('match_explorer.html')),c=dom.context,index=data.OPPORTUNITY_TEAM_INDEX;
  const s=index.scopes[0],graph=fixtureGraph(data),requests=[];
  Object.assign(c,{URL,URLSearchParams,Date,TextEncoder,TextDecoder,Uint8Array,AbortController,clearTimeout,crypto:webcrypto,btoa,
    location:{href:'https://funding-finder-researchers.urochestercheme.workers.dev/admin/contextual/preview/match_explorer.html'},
    OPPORTUNITY_TEAM_INDEX:index,RESEARCHER_DIRECTORY:data.RESEARCHER_DIRECTORY,GRANT_CATALOG:data.GRANT_CATALOG,
    FUNDING_SUBTOPICS:{loadSidecar:async()=>data.SUBTOPIC_CATALOG},
    FUNDING_FINDER_APP:{boundedScripts:{sidecar:{setTimeout:cb=>setTimeout(cb,5000),clearTimeout}}}});
  dom.document.getElementById('results').innerHTML='<article class="result-card"><button id="open-test" data-opportunity-team="'+s.parent_id+'" data-opportunity-team-scope="'+s.id+'">Build team</button></article>';
  c.fetch=async(url,o)=>{requests.push(o.method||'GET');return new Response(JSON.stringify({release_id:index.release_id,scope_id:s.id,state:'ready',result:graph}));};
  dom.document.head=dom.document.querySelector('head');dom.document.head.appendChild=script=>{
    const name=script.src.split('?')[0];vm.runInContext(code(name),c);queueMicrotask(()=>dom.dispatch('load',script));};
  vm.createContext(c);
  for(const name of ['site-shell','submission-schedule','search-query','search-retrieval','opportunity-team','opportunity-team-panel'])vm.runInContext(code('assets/'+name+'.js'),c);
  dom.dispatch('click',dom.document.getElementById('open-test'));
  const drawer=dom.document.getElementById('team-builder');
  for(let i=0;i<100&&!drawer.querySelector('.opportunity-team-next');i++)await new Promise(r=>setTimeout(r,0));
  assert(drawer.querySelector('.opportunity-team-next'),drawer.querySelector('.opportunity-team-body')?.dataset.error);
  assert.equal(drawer.querySelector('[data-contextual-assess]'),null);
  const select=drawer.querySelector('[data-opportunity-team-replacement]');
  const unassessed=data.RESEARCHER_DIRECTORY.researchers.find(p=>data.ContextualTeamEngine.eligible(p)&&!graph.people.some(v=>v.person_id===p.id));
  select.value=unassessed.id;dom.dispatch('change',select);
  assert.equal(drawer.querySelector('[data-contextual-assess]'),null);
  const before=requests.length;
  // A stale or injected control cannot bypass the same manifest capability.
  const stale=dom.document.createElement('button');stale.setAttribute('data-contextual-assess','');drawer.querySelector('.opportunity-team-body').appendChild(stale);
  dom.dispatch('click',stale);assert.equal(requests.length,before);
  dom.dispatch('click',drawer.querySelector('[data-opportunity-team-add-replacement]'));
  assert.equal(requests.length,before);assert.match(drawer.textContent,/has not been contextually assessed/);
  assert.equal(requests.filter(v=>v==='POST').length,0);
});
