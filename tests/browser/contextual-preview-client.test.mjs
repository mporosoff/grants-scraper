// Actual restricted application bytes with fixture relationships, zero network.
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import {gunzipSync} from 'node:zlib';
import {createHash,webcrypto} from 'node:crypto';
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
  await c.ContextualTeamClient.load(index,directory,options);assert.equal(posts,0);
  const loaded=await c.ContextualTeamClient.load(index,directory,{...options,deliberate:true});
  let state=loaded.engine.proposal(),id=state.selectedIds[0];
  state=loaded.engine.removeMember(state,id);state=loaded.engine.addReplacement(state,id);
  assert.equal(state.selectedIds.length,2);assert.equal(posts,1);
  const before=gets;await c.ContextualTeamClient.load(index,directory,{...options,deliberate:true});assert.equal(gets,before);
  assert.throws(()=>loaded.engine.runAction({parentId:s.parent_id,scopeId:s.id,now:'2026-09-23T12:00:00Z'},()=>loaded.engine.proposal()),/not_current/);
  assert.equal(posts,1);
});
