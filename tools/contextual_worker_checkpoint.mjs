// Narrow intake-Worker deployment evidence; no generalized release framework.
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import {activeDeployment} from './classify_worker_deployment.mjs';
import {verifyModules} from './reconcile_search_worker_provenance.mjs';
const hash=x=>createHash('sha256').update(x).digest('hex');
const canonical=x=>JSON.stringify(x,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
const [action,path,build]=process.argv.slice(2);
const declared=JSON.parse(fs.readFileSync('workers/researcher-intake/wrangler.jsonc','utf8'));
if(Object.keys(declared).some(k=>!['$schema','name','account_id','main','compatibility_date','workers_dev','vars','d1_databases','ratelimits','triggers'].includes(k)))
  throw Error('Unsupported intake configuration requires explicit provenance support');
const secretNames=['ADMIN_EMAILS','ACCESS_TEAM_DOMAIN','ACCESS_AUD','RECEIPT_TOKEN_SECRET','REGISTRY_WORKFLOW_TOKEN',
  'GITHUB_DISPATCH_TOKEN','RESEND_API_KEY','ADMIN_NOTIFICATION_EMAIL','NOTIFICATION_FROM'];
const token=process.env.CLOUDFLARE_API_TOKEN,account=process.env.CLOUDFLARE_ACCOUNT_ID;
if(!token||!account||!['capture','verify'].includes(action))throw Error('Existing deployment credentials and an explicit action are required');
async function api(suffix,family='scripts'){
  const target=family==='domains'?'domains':family+'/funding-finder-researchers';
  const response=await fetch(`https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(account)}/workers/${target}${suffix}`,
    {headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw Error(`Intake deployment evidence unavailable: HTTP ${response.status}`);
  const value=await response.json();if(!value.success||!value.result)throw Error('Incomplete intake deployment evidence');return value.result;
}
function configuration(resources){
  for(const binding of resources.bindings||[])if(binding.type==='secret_text'&&Object.keys(binding).some(k=>!['type','name'].includes(k)))
    throw Error('Unexpected secret metadata; it will not be recorded');
  const byName=(a,b)=>a.name.localeCompare(b.name);
  const expected={runtime:{compatibility_date:declared.compatibility_date,exports:{},usage_model:'standard'},
    bindings:[...Object.entries(declared.vars).map(([name,text])=>({name,type:'plain_text',text})),
      ...declared.d1_databases.map(d=>({name:d.binding,type:'d1',id:d.database_id})),
      ...declared.ratelimits.map(r=>({...r,type:'ratelimit'})),...secretNames.map(name=>({name,type:'secret_text'}))].sort(byName)};
  const actual={runtime:resources.script_runtime,bindings:(resources.bindings||[]).slice().sort(byName)};
  if(canonical(expected)!==canonical(actual))throw Error('Serving intake runtime/bindings differ from protected configuration');
  return actual;
}
async function routing(){
  const [subdomain,schedules,routes,domains]=await Promise.all([
    api('/subdomain'),api('/schedules'),api('/environments/production/routes?show_zonename=true','services'),
    api('/records?page=0&per_page=5&service=funding-finder-researchers&environment=production','domains')]);
  if(!Array.isArray(routes)||!Array.isArray(domains)||!Array.isArray(schedules.schedules))throw Error('Incomplete route/trigger inventory');
  // This Worker declares workers.dev only, no zone route or custom domain.
  // Fail closed on any unreviewed declaration or unexpected serving route.
  if(declared.routes||declared.route||routes.length||domains.length||subdomain.enabled!==declared.workers_dev
    ||canonical(schedules.schedules.map(s=>s.cron).sort())!==canonical((declared.triggers?.crons||[]).slice().sort()))
    throw Error('Serving intake routes/triggers differ from protected configuration');
  if(subdomain.previews_enabled!==true)throw Error('Serving preview routing differs from the protected Wrangler default');
  return {workers_dev:subdomain.enabled,previews_enabled:subdomain.previews_enabled,crons:schedules.schedules.map(s=>s.cron).sort(),routes,domains};
}
const before=activeDeployment((await api('/deployments')).deployments);
const version=await api('/versions/'+before.versionId);
const config=configuration(version.resources),routeConfig=await routing();
if(action==='capture'){
  fs.writeFileSync(path,JSON.stringify({version_id:before.versionId,deployment_id:before.deployment.id,
    configuration:config,routing:routeConfig,declared_configuration_sha256:hash(canonical(declared)),observed_at:new Date().toISOString()},null,2)+'\n');
  if(process.env.GITHUB_OUTPUT)fs.appendFileSync(process.env.GITHUB_OUTPUT,'version_id='+before.versionId+'\n');
  console.log(JSON.stringify({previous_version_id:before.versionId}));
}else{
  const old=JSON.parse(fs.readFileSync(path,'utf8'));
  if(canonical(config)!==canonical(old.configuration))throw Error('Existing intake bindings/runtime changed unexpectedly');
  if(canonical(routeConfig)!==canonical(old.routing))throw Error('Existing intake routing changed unexpectedly');
  const content=await api(`/versions/${before.versionId}?include=modules`,'workers');
  if(content.id!==before.versionId||!Array.isArray(content.modules))throw Error('Wrong serving module version');
  const actual={};
  for(const m of content.modules){
    if(typeof m.name!=='string'||m.name.includes('/')||m.name.includes('\\')||Object.hasOwn(actual,m.name)
      ||m.content_type!=='application/javascript+module'||typeof m.content_base64!=='string'
      ||Buffer.from(m.content_base64,'base64').toString('base64')!==m.content_base64)throw Error('Invalid serving module metadata');
    actual[m.name]=hash(Buffer.from(m.content_base64,'base64'));
  }
  const expected={};
  for(const name of fs.readdirSync(build))if(name!=='README.md'&&!name.endsWith('.map'))expected[name]=hash(fs.readFileSync(build+'/'+name));
  verifyModules(expected,actual);
  const after=activeDeployment((await api('/deployments')).deployments);
  if(after.versionId!==before.versionId||after.deployment.id!==before.deployment.id)throw Error('Serving Worker changed during verification');
  const proof={version_id:after.versionId,deployment_id:after.deployment.id,protected_sha:process.env.GITHUB_SHA,
    module_hashes:actual,configuration_sha256:hash(canonical(config)),routing:routeConfig,
    declared_configuration_sha256:hash(canonical(declared)),previous_version_id:old.version_id,
    method:'authenticated-active-modules-runtime-bindings-routes-and-triggers-vs-protected-inputs',public_recommender_activation:false};
  fs.writeFileSync(path.replace(/\.json$/,'-verified.json'),JSON.stringify(proof,null,2)+'\n');
  console.log(JSON.stringify(proof));
}
