// Trusted no-provider action check through the existing authoritative policy.
import fs from 'node:fs';
import vm from 'node:vm';
const inputs=JSON.parse(fs.readFileSync('config/contextual_team/inputs-v1.json','utf8'));
const job=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const option1=JSON.parse(fs.readFileSync('config/contextual_team/option1-v1.json','utf8'));
const phase2=JSON.parse(fs.readFileSync('config/contextual_team/phase2-v1.json','utf8'));
const latency=JSON.parse(fs.readFileSync('config/contextual_team/requirements-latency-v2.json','utf8'));
const iteration2=JSON.parse(fs.readFileSync('config/contextual_team/iteration2-authority-v1.json','utf8'));
const iteration3=JSON.parse(fs.readFileSync('config/contextual_team/iteration3-authority-v1.json','utf8'));
const continuation=JSON.parse(fs.readFileSync('config/contextual_team/iteration3-continuation-v1.json','utf8'));
const sources=[iteration3.release_id,continuation.release_id].includes(job.release_id)?JSON.parse(fs.readFileSync('config/contextual_team/iteration3-source-inputs-v1.json','utf8')):job.release_id===iteration2.release_id?JSON.parse(fs.readFileSync('config/contextual_team/iteration2-source-inputs-v1.json','utf8')):[phase2.release_id,latency.release_id].includes(job.release_id)?JSON.parse(fs.readFileSync('config/contextual_team/phase2-source-inputs-v2.json','utf8')):inputs;
const scope=sources.scopes.find(s=>s.id===job.scope_id);
if(!scope||![inputs.snapshot_id,option1.release_id,phase2.release_id,latency.release_id,iteration2.release_id,iteration3.release_id,continuation.release_id].includes(job.release_id))throw Error('contextual_job_not_in_snapshot');
if(job.release_id===continuation.release_id&&(job.person_id||scope.id!=='363268'||scope.state!=='unassessed'||scope.action_current!==true))throw Error('iteration3_only_exact_ai_continuation');
if(job.release_id===iteration3.release_id&&(job.person_id||scope.state!=='unassessed'||scope.action_current!==true))throw Error('iteration3_only_named_corrective_build');
if(job.release_id===iteration2.release_id&&(job.person_id||scope.state!=='unassessed'||scope.action_current!==true))throw Error('iteration2_only_actionable_development_build');
if(job.release_id===latency.release_id&&(job.person_id||job.scope_id!==latency.workflow_scope))throw Error('latency_only_named_doe_workflow');
if(job.release_id===phase2.release_id&&job.person_id)throw Error('phase2_extension_not_authorized');
if(job.release_id===option1.release_id&&(!option1.scopes.some(s=>s.id===job.scope_id)||job.person_id&&(job.scope_id!=='332894'||job.person_id!==option1.extension.person_id)))throw Error('outside_option1_inventory');
const c=vm.createContext({Date});
for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js'])
  vm.runInContext(fs.readFileSync(p,'utf8'),c,{filename:p});
const now=new Date();
const cutoff=scope.currentness.not_after;
const current=(cutoff===undefined||typeof cutoff==='string'&&Number.isFinite(+new Date(cutoff))&&+now<+new Date(cutoff))&&
  c.FUNDING_RETRIEVAL.recordIsCurrent(scope.currentness.record,now)&&c.FUNDING_RETRIEVAL.recordIsCurrent(scope.currentness.parent,now);
console.log(JSON.stringify({action_current:current,clock:now.toISOString(),scope_id:scope.id}));
