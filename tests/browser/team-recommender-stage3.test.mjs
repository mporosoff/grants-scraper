import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {buildPackage} from '../../tools/build_team_ingredients.mjs';import {engine,action,runtime} from '../helpers/team-real-inputs.mjs';
const root='outputs/team-recommender-stage3',available=fs.existsSync(root+'/heldout-outputs-v1.json');
async function input(cohort='holdout_effective'){const d=root+'/assembled-'+cohort+(cohort==='rollout150'?'-v3':''),j=n=>JSON.parse(fs.readFileSync(d+'/'+n+'.json')),f={bundle:j('bundle'),directory:j('directory'),context:j('context'),validations:j('validations'),bytes:fs.readFileSync(d+'/vectors.f32')};f.pack=await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations});return f;}
test('Stage3 real frozen numerical identities, weighted reference, reachability and exact small-pool optimization',{skip:!available},async()=>{
 const f=await input(),{c,e}=await engine(f),n=c.TeamRecommender,ref=JSON.parse(fs.readFileSync(root+'/heldout-outputs-v1.json'));let exact=0;
 const vectors=f.bundle.vector_rows.map((_,i)=>Float32Array.from({length:1024},(_,j)=>f.bytes.readFloatLE(i*4096+j*4)));
 for(const r of ref.rows){if(r.status==='unprepared')continue;const scope=e.opportunityById.get(r.id),m=n.matrix(scope,f.bundle.people,vectors),out=n.optimize(m);assert.deepEqual(Array.from(out.defaultIds),r.B.ids);assert.deepEqual(Array.from(out.options,o=>o.key),r.B.options.map(o=>o.key));
  for(const option of out.options){let independent=0;for(let i=0;i<m.weights.length;i++)independent+=m.weights[i]*Math.max(0,...option.ids.map(id=>m.rows.find(r=>r.id===id).edges[i].score));assert(Math.abs(independent-option.score)<1e-12);assert(option.ids.length>=2&&option.ids.length<=4);assert.equal(new Set(option.ids).size,option.ids.length);}
  const automatic=m.admitted.filter(r=>r.automatic_quality>=m.parameters.memberQuality);
  if(automatic.length<=12){assert.deepEqual(Array.from(n.optimize(m,[],{exact:true}).options,o=>o.key),r.B.options.map(o=>o.key));exact++;}
  const decision=e.resolveScope(action(f,r.id));if(decision.ok){let s=e.proposal(decision.opportunity),v=e.proposalView(s);assert.equal(new Set([...s.selectedIds,...v.replacements.map(p=>p.profile.id)]).size,m.admitted.length);assert(v.roles.every(r=>!r.directEvidence&&!r.filled));}
 }assert(exact>0);
});
test('Stage3 exact real claims, source snapshots, spaces and ownership fail closed when altered',{skip:!available},async()=>{
 const original=await input('rollout150');
 for(const mutate of [f=>f.bundle.people[0].document.chunks.push('Invented capability'),f=>f.directory.researchers.find(p=>p.id===f.bundle.people[0].id).claims[0].status='retired',f=>f.bundle.space.model='voyage-4-lite',f=>f.bundle.scopes.find(s=>s.prepared).aspects[0].span.start++,f=>f.bundle.sources.find(s=>s.id==='344592:ab-0009').parent_id='345241',f=>f.bundle.registry_generation='f'.repeat(64),f=>f.bytes.writeFloatLE(NaN,0)]){
  const f={bundle:structuredClone(original.bundle),directory:structuredClone(original.directory),validations:structuredClone(original.validations),bytes:Buffer.from(original.bytes)};mutate(f);await assert.rejects(buildPackage({bundle:f.bundle,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}));
 }
});
test('Stage3 all thirty derived-control reservations retain origins and unavailable denominators',{skip:!available},async()=>{
 const f=await input(),{e}=await engine(f),controls=f.context.controls,results=[];assert.equal(controls.length,30);
 for(const control of controls){const scope=f.bundle.scopes.find(s=>s.id===control.origin_scope_id);assert(scope);if(!scope.prepared){results.push({...control,status:'origin-unprepared',objective_test:'not runnable without altering the frozen source input'});continue;}
  const a=action(f,scope.id);let passed=false;
  if(control.kind==='expired-scope'){assert.equal(e.resolveScope({...a,record:{...a.record,close_date:'2020-01-01',status:'closed'},now:'2026-09-10T12:00:00Z'}).ok,false);passed=true;}
  else if(control.kind==='umbrella-parent'){assert.equal(e.resolveScope({...a,isBroad:true}).ok,false);passed=true;}
  else if(control.kind==='sibling-leakage'){assert.equal(e.resolveScope({...a,parentId:'another-parent'}).ok,false);passed=true;}
  else if(control.kind==='conditional-exclusion'){assert.equal(e.resolveScope({...a,record:{...a.record,status:'withdrawn'}}).ok,false);passed=true;}
  else if(control.kind==='alternative-branch'){const b=structuredClone(f.bundle);b.scopes.find(s=>s.id===scope.id).aspects[0].text='Unowned sibling requirement';await assert.rejects(buildPackage({bundle:b,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}));passed=true;}
  else if(control.kind==='verbose-profile'){const b=structuredClone(f.bundle);b.people[0].document.chunks[0]+=' Repeated generic words. '.repeat(100);await assert.rejects(buildPackage({bundle:b,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}));passed=true;}
  else if(control.kind==='unrelated-outsider'){assert.equal(e.resolveScope({...a,scopeId:'unknown-unprepared-scope'}).ok,false);passed=true;}
  results.push({...control,status:passed?'objective-boundary-tested':'semantic-control-not-run',limitation:'Objective boundary only; no newly embedded altered profile or machine relevance verdict is inferred.'});
 }
 fs.writeFileSync('docs/team-recommender/receipts/stage3-derived-controls-v1.json',JSON.stringify({reservations:30,results,semantic_control_verdicts_are_separate:true,real_source_inputs_mutated:false},null,2)+'\n');
});
test('Stage3 rollout receipt projection preserves exact science, profiles and vectors and admits authoritative child records',{skip:!available},async()=>{
 const f=await input('rollout150'),{e,c}=await engine(f),old=JSON.parse(fs.readFileSync(root+'/assembled-rollout150/bundle.json'));
 assert.deepEqual(f.bundle.scopes,old.scopes);assert.deepEqual(f.bundle.people,old.people);assert.deepEqual(f.bundle.vector_rows,old.vector_rows);assert.deepEqual(f.bytes,fs.readFileSync(root+'/assembled-rollout150/vectors.f32'));
 let ready=0;for(const s of f.bundle.scopes.filter(s=>s.record_type==='publishable_child'&&s.prepared)){
  const original=old.sources.find(x=>x.id===s.id),source=f.bundle.sources.find(x=>x.id===s.id);assert.deepEqual(source.excerpts,original.excerpts);assert.equal(source.document_sha256,original.document_sha256);assert.equal(source.receipt.checked_at,original.receipt.checked_at);
  const a=action(f,s.id),child=a.childCatalog.opportunities.find(r=>r.subtopic_id===s.id);assert.equal(source.record_key,c.TeamIngredients.recordKey(child));
  if(c.TeamIngredients.current(a.record,new Date(a.now)).ok&&c.TeamIngredients.current(child,new Date(a.now)).ok){assert.equal(e.resolveScope(a).ok,true,s.id);ready++;}
 }assert.equal(f.bundle.scopes.filter(s=>s.prepared&&s.record_type==="publishable_child").length,44);assert.equal(ready,41);
});
