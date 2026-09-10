/* Offline C/D optimizer comparison on grouped-fold predictions; no providers. */
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
import {runtime} from '../tests/helpers/team-real-inputs.mjs';
const run=process.argv[2];if(!/^\d+$/.test(run))throw Error('Exact judge run required');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),out='outputs/team-recommender-c2',doc='docs/team-recommender';
const m=read(`${out}/component-matrices-${run}.json`),map=read(`${out}/judge-item-map-v3.json`),judgments=read(`${out}/analysis-private/c2-judge-results-${run}.json`),n=runtime().TeamRecommender;
const groups=new Map(),people=new Map();
for(const [key,value]of Object.entries(judgments.labels)){
 const u=map.unique[key];if(u.value.task_type==='group')groups.set(u.scope_id+'|'+u.value.candidates.slice().sort().join('|'),value.label);
 if(u.value.task_type==='individual')people.set(u.scope_id+'|'+u.value.candidates[0],value.label);
}
const results=[];
for(const model of m.models){
 const start=performance.now(),rows=[];
 for(const scope of model.scopes){
  if(scope.status!=='scored'){rows.push({id:scope.id,status:scope.status});continue;}
  const input={weights:scope.weights,rows:scope.rows,admitted:scope.rows.filter(r=>r.edges.some(e=>e.admitted))};
  const t=performance.now(),result=n.optimize(input);
  rows.push({id:scope.id,fold:scope.fold,scored_people:scope.rows.length,status:result.defaultIds.length?'group':'no-group',primary:result.defaultIds,
   options:result.options,work:result.examinedCoverage,optimize_ms:performance.now()-t,
   cached_primary_grade:groups.get(scope.id+'|'+result.defaultIds.slice().sort().join('|'))||null,
   primary_member_grades:result.defaultIds.map(id=>({id,grade:people.get(scope.id+'|'+id)||null}))});
 }
 const selected=rows.flatMap(r=>r.primary_member_grades||[]),counts={};selected.forEach(r=>{const k=r.grade||'unjudged';counts[k]=(counts[k]||0)+1;});
 results.push({kind:model.kind,value:model.value,scientific_scopes:90,prepared:34,unprepared:56,
  groups:rows.filter(r=>r.status==='group').length,no_group:rows.filter(r=>r.status==='no-group').length,
  cached_group_grades:rows.filter(r=>r.cached_primary_grade).length,primary_member_grade_occurrences:counts,
  seconds:(performance.now()-start)/1000,rows});
}
const path=`${out}/analysis-private/c2-component-groups-${run}.json`;if(fs.existsSync(path))throw Error('Preserve prior component outcomes');
fs.writeFileSync(path,JSON.stringify({provider_calls:0,results,limits:m.limits,decision:'No new paid group-label campaign. New group yield is numerical only; unknown member/group grades are not successes.'},null,2)+'\n');
console.log(JSON.stringify(results.map(r=>({...r,rows:undefined}))));
