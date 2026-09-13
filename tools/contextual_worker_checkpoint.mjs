// Narrow intake-Worker deployment evidence; no generalized release framework.
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import {activeDeployment} from './classify_worker_deployment.mjs';
import {verifyModules} from './reconcile_search_worker_provenance.mjs';
const hash=x=>createHash('sha256').update(x).digest('hex');
const canonical=x=>JSON.stringify(x,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
const [action,path,build]=process.argv.slice(2);
const token=process.env.CLOUDFLARE_API_TOKEN,account=process.env.CLOUDFLARE_ACCOUNT_ID;
if(!token||!account||!['capture','verify'].includes(action))throw Error('Existing deployment credentials and an explicit action are required');
async function api(suffix,family='scripts'){
  const response=await fetch(`https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(account)}/workers/${family}/funding-finder-researchers${suffix}`,
    {headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.timeout(30000)});
  if(!response.ok)throw Error(`Intake deployment evidence unavailable: HTTP ${response.status}`);
  const value=await response.json();if(!value.success||!value.result)throw Error('Incomplete intake deployment evidence');return value.result;
}
function configuration(resources){
  for(const binding of resources.bindings||[])if(binding.type==='secret_text'&&Object.keys(binding).some(k=>!['type','name'].includes(k)))
    throw Error('Unexpected secret metadata; it will not be recorded');
  return {runtime:resources.script_runtime,bindings:(resources.bindings||[]).slice().sort((a,b)=>a.name.localeCompare(b.name))};
}
const before=activeDeployment((await api('/deployments')).deployments);
const version=await api('/versions/'+before.versionId);
const config=configuration(version.resources);
if(action==='capture'){
  fs.writeFileSync(path,JSON.stringify({version_id:before.versionId,deployment_id:before.deployment.id,
    configuration:config,observed_at:new Date().toISOString()},null,2)+'\n');
  if(process.env.GITHUB_OUTPUT)fs.appendFileSync(process.env.GITHUB_OUTPUT,'version_id='+before.versionId+'\n');
  console.log(JSON.stringify({previous_version_id:before.versionId}));
}else{
  const old=JSON.parse(fs.readFileSync(path,'utf8'));
  if(canonical(config)!==canonical(old.configuration))throw Error('Existing intake bindings/runtime changed unexpectedly');
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
    module_hashes:actual,configuration_sha256:hash(canonical(config)),previous_version_id:old.version_id,
    method:'authenticated-active-modules-and-preserved-bindings',public_recommender_activation:false};
  fs.writeFileSync(path.replace(/\.json$/,'-verified.json'),JSON.stringify(proof,null,2)+'\n');
  console.log(JSON.stringify(proof));
}
