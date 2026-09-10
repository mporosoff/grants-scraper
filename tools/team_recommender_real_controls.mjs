/* Reserved derived controls on immutable real inputs; no production records. */
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {realInputs,engine,action,NOW} from '../tests/helpers/team-real-inputs.mjs';
import {buildPackage} from './build_team_ingredients.mjs';
const f=await realInputs(),{e,c}=await engine(f),results=[];
for(const control of f.context.controls){
 const scope=f.bundle.scopes.find(s=>s.id===control.origin_scope_id),request=action(f,scope.id);
 const row={...control,materialization:'derived control from retained real source/profile snapshot; never published as a solicitation',provider_calls:0};
 if(!scope.prepared){
  assert.equal(e.resolveScope(request).ok,false);assert.equal(scope.aspects.length,0);
  results.push({...row,result:'unprepared-origin',objective_observation:'Input remains unprepared; no fabricated no-group or scientific perturbation verdict',semantic_control_executed:false});continue;
 }
 let detail;
 if(control.kind==='expired-scope'){
  const expired={...request.record,close_date:'2026-09-09'};
  assert.equal(c.TeamIngredients.current(expired,new Date(NOW)).ok,false);detail='Expired copy rejected by shared currentness policy';
 }else if(control.kind==='umbrella-parent'){
  assert.equal(e.resolveScope({...request,isBroad:true}).ok,false);detail='Unselected broad-parent copy cannot acquire this specific prepared scope';
 }else{
  const x=structuredClone({bundle:f.bundle,directory:f.directory,validations:f.validations});
  const s=x.bundle.scopes.find(s=>s.id===scope.id),p=x.bundle.people[0];
  if(control.kind==='sibling-leakage')x.bundle.sources.find(v=>v.id===scope.id).parent_id='359696';
  else if(control.kind==='alternative-branch')s.approach_id='unselected-alternative';
  else if(control.kind==='conditional-exclusion')s.aspects[0].text+=' regardless of source exclusions';
  else if(control.kind==='sparse-profile')p.passages=[];
  else if(control.kind==='verbose-profile')p.passages[0].text+=' '+p.passages[0].text.repeat(20);
  else if(control.kind==='duplicate-evidence')p.passages.push({...p.passages[0]});
  else if(control.kind==='generic-language')p.passages[0].text='innovative interdisciplinary research methods';
  else if(control.kind==='unrelated-passage')p.passages[0].text='An invented unrelated passage is not current researcher evidence.';
  else throw Error('Unknown reserved control');
  await assert.rejects(()=>buildPackage({bundle:x.bundle,vectors:f.bytes,directory:x.directory,sourceValidations:x.validations}));
  detail='Changed ownership, source meaning or profile text cannot reuse the original validated vector/source snapshot';
 }
 results.push({...row,result:'objective-perturbation-rejected',objective_observation:detail,semantic_control_executed:false,
   limitation:'Rejecting a tampered numerical/source identity is deterministic evidence, not a model or human relevance label.'});
}
const report={scientific_reservations:90,derived_controls:30,attempted:results.length,
 objective_perturbations:results.filter(r=>r.result==='objective-perturbation-rejected').length,
 unprepared_origins:results.filter(r=>r.result==='unprepared-origin').length,
 semantic_control_judgments:0,provider_calls:0,results};
const dest='docs/team-recommender/receipts/'+(process.env.TEAM_RECEIPT_PREFIX||'c2')+'-real-controls.json',raw=JSON.stringify(report,null,2)+'\n';
if(fs.existsSync(dest)&&fs.readFileSync(dest,'utf8')!==raw)throw Error('Existing immutable control receipt differs');
fs.writeFileSync(dest,raw);console.log(JSON.stringify({...report,results:undefined}));
