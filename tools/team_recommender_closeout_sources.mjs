/* Metadata/source-only inventory. Intentionally imports no team runtime. */
import fs from 'node:fs';import vm from 'node:vm';import {createHash} from 'node:crypto';
const read=p=>JSON.parse(fs.readFileSync(p,'utf8')), hash=x=>createHash('sha256').update(x).digest('hex');
const d='docs/team-recommender/',ctx={};vm.createContext(ctx);
for(const p of ['assets/search-retrieval.js','assets/submission-schedule.js','data/opportunities.js','data/subtopics.js'])vm.runInContext(fs.readFileSync(p,'utf8'),ctx);
const clock='2026-09-10T12:00:00Z',now=new Date(clock),roll=read(d+'manifests/rollout.json'),groups=read(d+'manifests/source-groups.json'),overlay=read(d+'manifests/source-group-amendment-c2-f92fc5995a0a1ac0.json');
const original=new Map(groups.records.map(s=>[s.id,s])),parents=new Map(ctx.GRANT_CATALOG.opportunities.map(r=>[r.opportunity_id,r])),children=new Map(ctx.FUNDING_RETRIEVAL.createChildCatalog(ctx.SUBTOPIC_CATALOG).opportunities.map(r=>[r.subtopic_id,r]));
const native=new Map(Object.values(ctx.SUBTOPIC_CATALOG.records).flatMap(r=>r.subtopics).map(s=>[s.subtopic_id,s]));
const cohorts={rollout50:roll.cohort_50,rollout150:roll.cohort_150,holdout_effective:overlay.holdout_scopes.map(s=>s.id),holdout_original:read(d+'manifests/holdout.json').scopes.map(s=>s.id)};
const rows=[...new Set(Object.values(cohorts).flat())].map(id=>{
 const s=original.get(id)||overlay.holdout_scopes.find(s=>s.id===id);if(!s)throw Error('Missing source reservation '+id);
 const p=parents.get(s.parent_id),n=native.get(id),c=children.get(id),r=c||p,status=ctx.FUNDING_SUBMISSION_SCHEDULE.nextSubmission(p,clock.slice(0,10));
 return {id,parent_id:s.parent_id,group_id:overlay.source_group_map[s.parent_id],family:s.family,record_type:s.record_type,title:s.title,
  cohorts:Object.keys(cohorts).filter(k=>cohorts[k].includes(id)),parent_current:ctx.FUNDING_RETRIEVAL.recordIsCurrent(p,now),child_current:c?ctx.FUNDING_RETRIEVAL.recordIsCurrent(c,now):null,
  submission:status,source_reservation:s,record:n||p,source_text:(n?.summary||p?.description||''),source_sha256:hash(JSON.stringify(n||p)),
  existing_publishable_children:[...children.values()].filter(x=>x.parent_id===s.parent_id).map(x=>x.subtopic_id)};
});
fs.writeFileSync('outputs/team-recommender-closeout/source-metadata.json',JSON.stringify({clock,cohorts,rows},null,2)+'\n');
console.log(JSON.stringify({metadata_scopes:rows.length,cohorts:Object.fromEntries(Object.entries(cohorts).map(([k,v])=>[k,v.length])),recommender_loaded:false,holdout_recommendations:0}));
