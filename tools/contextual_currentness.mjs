// Trusted no-provider action check through the existing authoritative policy.
import fs from 'node:fs';
import vm from 'node:vm';
const inputs=JSON.parse(fs.readFileSync('config/contextual_team/inputs-v1.json','utf8'));
const job=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const scope=inputs.scopes.find(s=>s.id===job.scope_id);
if(!scope||job.release_id!==inputs.snapshot_id)throw Error('contextual_job_not_in_snapshot');
const c=vm.createContext({Date});
for(const p of ['assets/submission-schedule.js','assets/search-query.js','assets/search-retrieval.js'])
  vm.runInContext(fs.readFileSync(p,'utf8'),c,{filename:p});
const now=new Date();
const current=c.FUNDING_RETRIEVAL.recordIsCurrent(scope.currentness.record,now)&&c.FUNDING_RETRIEVAL.recordIsCurrent(scope.currentness.parent,now);
console.log(JSON.stringify({action_current:current,clock:now.toISOString(),scope_id:scope.id}));
