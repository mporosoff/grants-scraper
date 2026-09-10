import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import {fixture,runtime,NOW} from '../fixtures/team-ingredients.mjs';
const plain=v=>JSON.parse(JSON.stringify(v));

test('weighted coverage improves complementarity at matched size; exact small-pool result',async()=>{
 const f=await fixture(),{e,state}=await f.engine();
 assert.equal(state.selectedIds.length,2);const v=e.proposalView(state);
 assert.equal(v.matched_people_count,10);assert.equal(v.feasible_team_count,25);assert.equal(e.proposalOptions(state).length,8);
 assert.equal(v.complete,false);assert.ok(v.roles.every(r=>!r.directEvidence&&!r.filled));
 assert.equal(v.opportunity.gate_state,'conditional');assert.match(v.selected[0].evidence.why_person,/remain to be established/);
 const options=e.proposalOptions(state);assert.deepEqual(plain(options),plain(e.proposalOptions(state)));
 assert.equal(new Set(options.map(o=>o.id)).size,8);
 for(const option of options) assert.equal(option.state.selectedIds.length,2);
});
test('all admitted people reachable with supported or unconfirmed roles; restore and full slots',async()=>{
 const f=await fixture(),{e,state}=await f.engine();let s=state;
 const reachable=new Set([...s.selectedIds,...e.proposalView(s).replacements.map(r=>r.profile.id)]);assert.equal(reachable.size,10);
 const removed=s.selectedIds[0];s=e.removeMember(s,removed);
 assert.ok(e.proposalOptions(s).every(o=>!o.state.selectedIds.includes(removed)));
 assert.ok(e.proposalView(s).replacements.some(r=>r.profile.id===removed&&r.previouslySelected));
 s=e.addReplacement(s,removed);assert.equal(s.excludedIds.length,0);
 while(s.selectedIds.length<4)s=e.addReplacement(s,e.proposalView(s).replacements[0].profile.id);
 assert.throws(()=>e.addReplacement(s,e.proposalView(s).replacements[0].profile.id),/not an admitted/);
 for(const id of [...s.selectedIds])s=e.removeMember(s,id);
 assert.equal(e.proposalView(s).selected.length,0);assert.equal(e.proposalView(s).opportunity.gate_state,'fail');
});
test('single researcher yields a valid prepared no-group with individual suggestions',async()=>{
 const f=await fixture({count:1}),{e,state}=await f.engine(),v=e.proposalView(state);
 assert.equal(v.prepared,true);assert.equal(v.matched_people_count,1);assert.equal(v.feasible_team_count,0);assert.equal(v.selected.length,0);
 assert.equal(e.proposalOptions(state).length,0);assert.equal(v.replacements.length,1);assert.equal(v.complete,false);
});
test('one source-backed direct link never confirms a different contribution',async()=>{
 const f=await fixture();const link={aspect_id:'optical',researcher_id:f.directory.researchers[0].id,claim_id:f.directory.researchers[0].claims[0].claim_id,revision:1,status:'direct',source_text:'Optical spectroscopy',claim_text:'Optical spectroscopy',receipt_id:'retained-exact-relation',reviewed_relation:'exact-source-claim-v1'};
 f.scope.evidence_links=[link];f.manifest.reviewed_relations=[{...link,scope_id:f.scope.id,document_sha256:f.source.document_sha256}];
 const {e,state}=await f.engine(),v=e.proposalView(state);assert.equal(v.roles[0].directEvidence,true);assert.equal(v.roles[1].filled,false);assert.equal(v.complete,false);
});
test('matching words, direct registry evidence and cached model approval cannot create proof',async()=>{
 const f=await fixture(),{e,state}=await f.engine();assert.ok(e.proposalView(state).roles.every(r=>r.selected_candidate_ids.length===0));
 f.source.receipt.kind='model-approval';await assert.rejects(f.hydrate,/lacks validation/);
});
test('source change and receipt expiry are different from valid no-group',async()=>{
 const f=await fixture(),{e}=await f.engine();f.record.description+=' Amendment';
 let r=e.resolveScope({record:f.record,scopeId:f.scope.id,now:NOW});assert.equal(r.readiness,'source-changed');
 f.record.description='Optical spectroscopy. Nanocrystal synthesis.';
 f.record.close_date='2027-01-01';r=e.resolveScope({record:f.record,scopeId:f.scope.id,now:new Date('2026-10-02')});assert.equal(r.readiness,'stale-receipt');
});
test('deadline expiration, rolling, forecast and closed prerequisite reuse authoritative policy',async()=>{
 const f=await fixture(),{e,state}=await f.engine();
 assert.equal(e.resolveScope({record:f.record,scopeId:f.scope.id,now:new Date('2026-09-10')}).reason,'not_current');
 f.record.rolling=true;f.record.close_date=null;f.record.status='forecasted';
 assert.equal(e.resolveScope({record:f.record,scopeId:f.scope.id,now:new Date('2026-09-10')}).ok,true);
 f.record.deadlines=[{kind:'letter_of_intent',required:true,date:'2026-09-08'},{kind:'application',date:'2026-09-20'}];
 assert.equal(e.resolveScope({record:f.record,scopeId:f.scope.id,now:NOW}).reason,'not_current');
 assert.throws(()=>e.proposalView(state),/Stale|no longer current/);
});
test('child identity, parent policy, sibling isolation and child publication/currentness',async()=>{
 const f=await fixture({child:true}),{e}=await f.engine();const ctx={record:f.record,parentId:f.record.opportunity_id,scopeId:f.scope.id,childCatalog:{opportunities:[f.childRecord]},now:NOW};
 assert.equal(e.resolveScope(ctx).ok,true);
 assert.equal(e.resolveScope({...ctx,childCatalog:{opportunities:[{...f.childRecord,parent_id:'sibling'}]}}).reason,'child_not_publication_eligible');
 f.childRecord.close_date='2026-09-08';assert.equal(e.resolveScope(ctx).reason,'not_current');f.childRecord.close_date='2026-09-30';
 f.record.status='closed';assert.equal(e.resolveScope(ctx).reason,'not_current');
});
for(const [name,mutate,pattern] of [
 ['retired claim',f=>f.directory.researchers[0].claims[0].status='retired',/Stale|drops/],
 ['claim revision',f=>f.directory.researchers[0].claims[0].revision=2,/Stale/],
 ['profile omitted',f=>f.bundle.people.pop(),/omits/],
 ['source sibling',f=>f.source.receipt.parent_id='sibling',/ownership/],
 ['source span truncation',f=>f.scope.aspects[0].span.end--,/span/],
 ['source descriptor fabrication',f=>f.scope.aspects[0].operation='clinical trial',/descriptor/],
 ['method composed from another claim',f=>f.bundle.people[0].passages[0].context='clinical trial',/descriptor/],
 ['mixed space',f=>f.bundle.vector_rows[0].space='0'.repeat(64),/provenance/],
 ['same dimension different role',f=>f.bundle.vector_rows[0].input_role='document',/input-role/],
 ['private surplus field',f=>f.bundle.people[0].private_cv='private',/Unexpected/],
 ['unsafe evidence URL',f=>f.bundle.people[0].passages[0].source_urls=['javascript:alert(1)'],/provenance/],
 ['changed query text',f=>f.scope.core.text='invented source',/span/],
 ['weight inflation',f=>f.scope.aspects[0].weight=.9,/budget/],
 ['mixed registry',f=>f.manifest.registry_generation='0'.repeat(64),/Mixed/],
 ['unknown source state',f=>{f.scope.prepared=false;f.scope.readiness='ready';f.scope.aspects=[];f.manifest.source_validations=[];},/Unprepared/]
]) test('rejects '+name,async()=>{const f=await fixture();mutate(f);await assert.rejects(f.hydrate,pattern);});
test('corrupt vector bytes and nonfinite/norm values fail closed',async()=>{
 for(const value of [NaN,Infinity,0,2]){const f=await fixture();new DataView(f.bytes.buffer).setFloat32(0,value,true);f.manifest.vectors.sha256=await f.api.sha256(f.bytes);await assert.rejects(f.hydrate,/Nonfinite|Unnormalized/);}
 const f=await fixture();f.bytes[100]^=1;await assert.rejects(f.hydrate,/Corrupt/);
});
test('snapshot is immutable, state generation fails closed and cached reads do not recompute',async()=>{
 const f=await fixture(),{e,state}=await f.engine();const before=e.statistics();
 for(let i=0;i<20;i++){e.proposalView(state);e.proposalOptions(state);}assert.deepEqual(e.statistics(),before);
 f.bundle.people[0].passages[0].text='changed outside validated snapshot';assert.match(e.proposalView(state).selected[0].evidence.evidence_phrase,/Optical/);
 assert.throws(()=>e.proposalView({...state,generation:'c'.repeat(64)}),/Stale/);
});
test('topic and evidenced method gates reject generic and unrelated passages; no metadata diversity reward',()=>{
 const c=runtime(),n=c.TeamRecommender,v=[[1,0],[0,1]],a={text:'Optical spectroscopy',vector:0,operation:'spectroscopy',context:'nanocrystal'},core={vector:0};
 assert.equal(n.edge(a,core,{id:'x',text:'Tourism history',vector:1},v).admitted,false);
 assert.equal(n.edge(a,core,{id:'x',text:'innovative research methods',vector:0},v).admitted,false);
 const p={id:'x',text:'spectroscopy of nanocrystal materials',vector:1,operation:'spectroscopy',context:'nanocrystal'};
 assert.equal(n.edge(a,core,p,v).route,'method');assert.equal(n.edge(a,core,{...p,context:null},v).admitted,false);
 assert.equal(n.edge(a,core,{...p,department:'novel unrelated department'},v).score,n.edge(a,core,p,v).score);
});
test('poor pools, redundant members and near-best size selection match exhaustive reference',()=>{
 const n=runtime().TeamRecommender;
 const make=(scores)=>({weights:[.7,.3],rows:scores.map((r,i)=>({id:String(i),edges:r.map(score=>({score,admitted:score>0,core:score})),baseline:r[0]}))});
 for(const scores of [[[.95,0],[0,.9],[.95,0],[.5,.5]],[[.1,.1],[.2,.2]],[[.9,.7],[.8,.8],[.1,.1]]]){
   const m=make(scores);m.admitted=m.rows.filter(r=>r.edges.some(e=>e.admitted));const got=n.optimize(m);let best=0,count=0;
   for(let mask=1;mask<(1<<scores.length);mask++){const ids=scores.map((_,i)=>i).filter(i=>mask&(1<<i));if(ids.length<2||ids.length>4)continue;
     const f=members=>[.7,.3].reduce((s,w,a)=>s+w*Math.max(0,...members.map(i=>scores[i][a])),0),val=f(ids);
     if(val<.45||!ids.some(i=>scores[i].some(s=>s>=.4))||ids.some(i=>Math.max(...scores[i])<=0))continue;
     count++;best=Math.max(best,val);
   }
   assert.equal(got.feasibleCount,count);assert.equal(got.maximum,best);
 }
});
test('asset loader is bounded same-origin static only; cold, repeat and corruption never reach providers',async()=>{
 const f=await fixture();const encode=o=>new TextEncoder().encode(JSON.stringify(o));const meta=encode(f.bundle);
 f.manifest.metadata={path:'data/team-recommender/fixture.json',bytes:meta.length,sha256:await f.api.sha256(meta)};
 const manifest=encode(f.manifest);f.index.ingredients={path:'data/team-recommender/manifest.json',bytes:manifest.length,sha256:await f.api.sha256(manifest)};
 let calls=[],paid=0,corrupt=false;
 f.c.fetch=async url=>{calls.push(url);if(!url.startsWith('data/team-recommender/')){paid++;throw Error('provider blocked');}
 const bytes=url.includes('/manifest.json')?manifest:url.includes('/fixture.json')?meta:f.bytes;
 return new Response(corrupt?bytes.slice(1):bytes);};
 for(let i=0;i<2;i++)await f.api.loadData(f.index,f.directory);assert.equal(calls.length,6);assert.equal(paid,0);
 corrupt=true;await assert.rejects(()=>f.api.loadData(f.index,f.directory),/integrity/);assert.equal(paid,0);
 f.index.ingredients.path='https://api.voyageai.com/v1/embeddings';await assert.rejects(()=>f.api.loadData(f.index,f.directory),/bounded asset/);assert.equal(paid,0);
});
test('exact unchanged row computations survive a cosmetic profile update; changed vectors cannot reuse them',async()=>{
 const n=runtime().TeamRecommender, cache=new n.LRU(2),vectors=[[1,0],[0,1]],aspect={id:'a',text:'optical spectroscopy',vector:0,weight:1};
 const scope={semantic_key:'exact-scope',aspects:[aspect],core:{vector:0},whole_call:{vector:0}};
 const person={id:'p',semantic_key:'exact-profile-vector-1',passages:[{id:'c',text:'optical spectroscopy',vector:0}]};
 const a=n.matrix(scope,[person],vectors,cache),b=n.matrix(scope,[{...person,name:'Cosmetic name',department:'Another unit'}],vectors,cache);
 assert.equal(a.rows[0],b.rows[0]);
 const changed=n.matrix(scope,[{...person,semantic_key:'changed-profile-vector-2',passages:[{id:'c2',text:'tourism history',vector:1}]}],vectors,cache);
 assert.notEqual(a.rows[0],changed.rows[0]);assert.equal(changed.admitted.length,0);
 cache.set('three',{});assert.equal(cache.values.size,2);assert.equal(cache.get('missing'),undefined);
});
test('duplicate/verbose profiles and generic extra passages do not gain arbitrary credit',async()=>{
 const f=await fixture();f.bundle.people[0].passages.push({...f.bundle.people[0].passages[0],id:'duplicate'});await assert.rejects(f.hydrate,/Duplicate/);
 const n=runtime().TeamRecommender,v=[[1,0],[0,1]],a={id:'a',text:'Optical spectroscopy',vector:0,weight:1},s={semantic_key:'s',aspects:[a],core:{vector:0},whole_call:{vector:0}};
 const p={id:'p',semantic_key:'p',passages:[{id:'one',text:'Optical spectroscopy',vector:0}]};
 const base=n.matrix(s,[p],v).rows[0].edges[0].score;
 p.passages.push({id:'two',text:'innovative interdisciplinary research methods '.repeat(30),vector:0},{id:'three',text:'Tourism history',vector:1});
 assert.equal(n.matrix(s,[p],v).rows[0].edges[0].score,base);
});
test('oversized, repeated-group, private source-span and mixed-vector contracts fail before ranking',async()=>{
 const f=await fixture();f.scope.core.span.private_note='not-public';await assert.rejects(f.hydrate,/Unexpected source span/);
 const g=await fixture();g.bundle.people[0].passages[0].text='x'.repeat(2001);await assert.rejects(g.hydrate,/over-bound/);
 const h=await fixture();h.bundle.vector_rows[5].text_sha256=h.bundle.vector_rows[4].text_sha256;await assert.rejects(h.hydrate,/Conflicting vectors/);
});
