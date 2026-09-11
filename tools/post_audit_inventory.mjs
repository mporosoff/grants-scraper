// Private diagnostic outcomes; never an input to the serving runtime.
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto, createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
const args=Object.fromEntries(process.argv.slice(2).map(x=>x.split('='))), clock='2026-09-11T12:00:00Z';
const engine=args['--engine']||'assets/shared-team-engine.js', output=args['--output'];
if(!output)throw Error('--output is required');
const c=vm.createContext({Date,TextEncoder,TextDecoder,crypto:webcrypto,performance});
for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js','assets/team-matcher.js',engine,'data/opportunities.js','data/subtopics.js','data/researcher_directory.js','data/faculty_matches.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
const index=JSON.parse(fs.readFileSync(args['--index']||'docs/team-recommender/profile-repair/shared-candidate-index.json'));
const packet=JSON.parse(fs.readFileSync(index.shared.path)), start=performance.now();
const data=await c.SharedTeamEngine.hydrate(packet,index,c.RESEARCHER_DIRECTORY,c.GRANT_CATALOG,c.SUBTOPIC_CATALOG);
const hydration_ms=performance.now()-start,e=c.SharedTeamEngine.create(data,{clock:()=>clock});
const child=c.FUNDING_RETRIEVAL.createChildCatalog(c.SUBTOPIC_CATALOG),records=new Map(c.GRANT_CATALOG.opportunities.map(r=>[r.opportunity_id,r])),rows=[];
for(const s of index.scopes){
 const t=performance.now(),action={parentId:s.parent_id,scopeId:s.id,record:records.get(s.parent_id),childCatalog:s.record_type==='publishable_child'?child:null,now:clock};
 const resolved=e.resolveScope(action),fit_ms=performance.now()-t;
 if(!resolved.ok){rows.push({id:s.id,parent_id:s.parent_id,kind:s.record_type,boundary:resolved.reason,fit_ms});continue;}
 const fits=e.admittedFits(),t2=performance.now(),state=e.proposal(resolved.opportunity),options=e.proposalOptions(state),view=e.proposalView(state);
 const groups_ms=performance.now()-t2,trace=e.diagnoseScope?.()||null;
 const boundary=options.length?'group_produced':!fits.length?'no_admitted_person':fits.length===1?'only_one_admitted_person':!fits.some(r=>r.fit.strong)?'absent_scientific_anchor':'redundancy_contribution_restriction';
 rows.push({id:s.id,parent_id:s.parent_id,kind:s.record_type,boundary,admitted:fits.length,strong:fits.filter(r=>r.fit.strong).length,options:options.length,primary:state.selectedIds,option_members:options.map(o=>o.state.selectedIds),top5:fits.sort((a,b)=>b.fit.score-a.fit.score||a.id.localeCompare(b.id)).slice(0,5).map(r=>r.id),fit_ms,groups_ms,trace,contributions:view.selected.map(m=>m.evidence)});
}
const counts={};for(const r of rows)counts[r.boundary]=(counts[r.boundary]||0)+1;
const result={clock,engine_sha256:createHash('sha256').update(fs.readFileSync(engine)).digest('hex'),registry_generation:packet.registry_generation,package_generation:index.generation_id,scopes:rows.length,counts,hydration_ms,elapsed_ms:performance.now()-start,statistics:e.statistics(),rows,provider_calls:0,kind:'diagnostic; not untouched semantic validation'};
fs.writeFileSync(output,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({...result,rows:undefined}));
