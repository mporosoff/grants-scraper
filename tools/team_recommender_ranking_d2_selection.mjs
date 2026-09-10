import fs from 'node:fs';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {ruleEngine} from './team_recommender_ranking_d2_rules.mjs';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')),n=ruleEngine(),root='outputs/team-recommender-d2';
const input=read(root+'/D1-reproduction.json'),fit=read(root+'/fit-R0.json');
const known=read(root+'/D1-judgment-audit.json').call_person_keys,labels=new Map(known.map(r=>[r.scope_id+'|'+r.person_id,r.label]));
const scored=new Map(fit.all_rows.map(r=>[r.scope_id+'|'+r.person_id,r]));
const results=[];
for(const family of ['fixed','regularized'])for(const rho of [.90,.95]){
 const threshold=(family==='fixed'?fit.final_fixed_operating:fit.final_learned_operating).operating.threshold;
 const scopes=[];
 for(const source of input.scopes){
  if(source.status==='unprepared'){scopes.push({id:source.id,status:'unprepared'});continue;}
  const rows=source.rows.map(r=>({...r,automatic_quality:scored.get(source.id+'|'+r.id)[family==='fixed'?'fixed_quality':'learned_outer_fold_quality']}));
  const m={rows,weights:source.weights,aspects:source.aspects,admitted:rows.filter(r=>source.admitted.includes(r.id))};
  const b=n.optimize(m,[],{memberFloor:threshold,rho});
  scopes.push({id:source.id,status:b.options.length?'group':'no-group',B:b,admitted:source.admitted.length,
   options:b.options.map((t,i)=>({...t,rank:i+1,members:t.ids.map(id=>({id,quality:rows.find(r=>r.id===id).automatic_quality,label:labels.get(source.id+'|'+id)||'missing'}))}))});
 }
 const members=scopes.flatMap(s=>(s.options||[]).flatMap(o=>o.members)),counts={};for(const m of members)counts[m.label]=(counts[m.label]||0)+1;
 results.push({family,rho,threshold,learned_score_provenance:family==='regularized'?'outer fold prediction, global OOF operating threshold; exploratory selection ablation, not nested independent estimate':null,
  groups:scopes.filter(s=>s.status==='group').length,options:scopes.reduce((s,r)=>s+(r.options?.length||0),0),member_labels:counts,scopes});
 console.log(JSON.stringify({family,rho,threshold,groups:results.at(-1).groups,options:results.at(-1).options,member_labels:counts,group_ids:scopes.filter(s=>s.status==='group').map(s=>s.id)}));
}
const filename=root+'/fixed-D1-selection.json';assert(!fs.existsSync(filename));fs.writeFileSync(filename,JSON.stringify({protocol:'D2-fixed-D1-matrix-selection',provider_calls:0,holdout_scored:false,results})+'\n');
fs.writeFileSync('docs/team-recommender/receipts/d2-fixed-matrix-selection.json',JSON.stringify({private_output_sha256:createHash('sha256').update(fs.readFileSync(filename)).digest('hex'),results:results.map(({scopes,...r})=>({...r,scope_dispositions:scopes.map(s=>({scope_id:s.id,status:s.status,options:s.options?.length||0}))})),all_admitted_candidates_preserved:true,provider_calls:0,holdout_scored:false},null,2)+'\n');
