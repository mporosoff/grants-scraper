import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {buildPackage} from '../../tools/build_team_ingredients.mjs';
import {engine,runtime,action} from '../helpers/team-real-inputs.mjs';
const base='outputs/team-recommender-d3',available=fs.existsSync(base+'/D3-candidate-outputs.json');
const clone=v=>JSON.parse(JSON.stringify(v));
async function inputs(arm){const root=base+'/assembled-'+arm,read=n=>JSON.parse(fs.readFileSync(root+'/'+n+'.json'));const f={bundle:read('bundle'),directory:read('directory'),validations:read('validations'),context:read('context'),bytes:fs.readFileSync(root+'/vectors.f32')};f.pack=await buildPackage({bundle:f.bundle,directory:f.directory,vectors:f.bytes,sourceValidations:f.validations});return f;}
for(const arm of ['E1','E2','E3']){
 test(arm+' real prepared actions preserve frozen numerical outputs and make zero paid calls',{skip:!available},async()=>{
  const f=await inputs(arm),reference=JSON.parse(fs.readFileSync(base+'/D3-candidate-outputs.json')).arms[arm];let network=0;
  const c=runtime({fetch:()=>{network++;throw Error('Unexpected runtime network');}}),{e}=await engine(f,c);assert.equal(e.statistics().matrices,0);assert.equal(e.statistics().optimizations,0);
  let prepared=0,allowed=0,groups=0,full=0;
  for(const s of reference.scopes){if(s.status==='unprepared')continue;prepared++;const resolution=e.resolveScope(action(f,s.id));assert.equal(resolution.ok,s.action_allowed);
   if(!resolution.ok)continue;allowed++;let state=e.proposal(resolution.opportunity),options=e.proposalOptions(state);assert.deepEqual(Array.from(state.selectedIds),s.B.defaultIds);assert.deepEqual(Array.from(options,o=>Array.from(o.state.selectedIds)),s.B.options.map(o=>o.ids));
   assert(options.length<=8);const view=e.proposalView(state);assert.equal(view.opportunity.why_team,s.explanation);assert(view.roles.every(r=>!r.directEvidence&&!r.filled));
   assert.deepEqual(Array.from(view.replacements,r=>r.profile.id).sort(),s.admitted.filter(id=>!state.selectedIds.includes(id)).sort());
   const work=e.statistics().optimizations;e.proposal(resolution.opportunity);e.proposalOptions(state);assert.equal(e.statistics().optimizations,work);
   for(const option of options){assert.equal(e.proposalView(option.state).selected.length,option.state.selectedIds.length);}
   if(state.selectedIds.length){groups++;const removed=state.selectedIds[0];state=e.removeMember(state,removed);assert(!state.selectedIds.includes(removed));assert(e.proposalOptions(state).every(o=>!o.state.selectedIds.includes(removed)));assert(e.proposalView(state).replacements.some(r=>r.profile.id===removed));state=e.addReplacement(state,removed);assert(state.selectedIds.includes(removed));assert(!state.excludedIds.includes(removed));}
   while(state.selectedIds.length<4){const v=e.proposalView(state);if(!v.replacements.length)break;state=e.addReplacement(state,v.replacements[0].profile.id);}
   if(state.selectedIds.length===4){full++;const r=e.proposalView(state).replacements[0];if(r)assert.throws(()=>e.addReplacement(state,r.profile.id),/not an admitted/);}
   e.resolveScope(action(f,s.id,'2036-09-10T12:00:00Z'));assert.throws(()=>e.proposalView(state),/Stale or unresolved|no longer current/);
  }
  assert.equal(prepared,35);assert.equal(allowed,26);assert(groups>0&&full>0);assert.equal(network,0);
  const fresh=await engine(f,c);assert.equal(fresh.e.statistics().matrices,0);const sid=reference.scopes.find(s=>s.action_allowed).id;const resolution=fresh.e.resolveScope(action(f,sid));fresh.e.proposal(resolution.opportunity);assert.equal(network,0);
 });
 test(arm+' rejects corrupt, mixed, retired and stale ingredient states',{skip:!available},async()=>{
  const f=await inputs(arm),c=runtime({fetch:()=>{throw Error('Provider fallback forbidden');}});const manifest=JSON.parse(f.pack.files.get(f.pack.index.ingredients.path));
  const bytes=f.bytes.buffer.slice(f.bytes.byteOffset,f.bytes.byteOffset+f.bytes.byteLength),bad=bytes.slice(0);new Uint8Array(bad)[0]^=1;
  await assert.rejects(c.TeamIngredients.hydrate(f.bundle,bad,manifest,f.pack.index,f.directory),/Corrupt vector/);
  const mixed=clone(f.bundle);mixed.space.model=arm==='E3'?'voyage-4-large':'voyage-context-4';await assert.rejects(buildPackage({bundle:mixed,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}),/space mismatch/);
  const retired=clone(f.directory),id=f.bundle.people[0].id;retired.researchers.find(p=>p.id===id).claims[0].status='retired';await assert.rejects(buildPackage({bundle:f.bundle,vectors:f.bytes,directory:retired,sourceValidations:f.validations}),/claim passage|document context/);
  const {e}=await engine(f,c),sid=f.bundle.scopes.find(s=>s.prepared&&e.resolveScope(action(f,s.id)).ok).id,r=e.resolveScope(action(f,sid)),state=e.proposal(r.opportunity);assert.throws(()=>e.proposalView({...state,generation:'0'.repeat(64)}),/Stale or unresolved/);
  const corrupt=clone(f.bundle);corrupt.vector_rows[0].input_role='query';await assert.rejects(buildPackage({bundle:corrupt,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}),/input-role|document\/vector/);
 });
}
test('richer context is exactly one frozen person and invalidates the whole document',{skip:!available},async()=>{
 for(const arm of ['E2','E3']){
  const f=await inputs(arm),cross=clone(f.bundle);cross.people[0].document=clone(cross.people[1].document);await assert.rejects(buildPackage({bundle:cross,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}),/cross-person document/);
  const d=clone(f.directory),b=clone(f.bundle),person=b.people.find(p=>p.document.chunks[0].startsWith('Research summary:')),profile=d.researchers.find(p=>p.id===person.id);profile.research_summary+=' Existing context changed in an isolated fixture.';person.document.chunks[0]='Research summary:\n'+profile.research_summary;
  await assert.rejects(buildPackage({bundle:b,vectors:f.bytes,directory:d,sourceValidations:f.validations}),/Complete document\/vector identity mismatch/);
  const cosmetic=clone(f.directory);cosmetic.researchers.find(p=>p.id===person.id).name='Cosmetic fixture display name';await buildPackage({bundle:f.bundle,vectors:f.bytes,directory:cosmetic,sourceValidations:f.validations});
 }
});
test('context chunk ownership and scorer/space identity cannot be silently mixed',{skip:!available},async()=>{
 const f=await inputs('E3'),b=clone(f.bundle);b.people[0].passages[0].chunk_index+=1;await assert.rejects(buildPackage({bundle:b,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}),/chunk\/claim ownership/);
 const bad=clone(f.bundle);bad.scorer.member=0;await assert.rejects(buildPackage({bundle:bad,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}),/absolute scorer/);
 const no=clone(f.bundle);delete no.representation;await assert.rejects(buildPackage({bundle:no,vectors:f.bytes,directory:f.directory,sourceValidations:f.validations}),/Scorer requires/);
});
