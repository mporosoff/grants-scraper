// Access-protected finite job coordination. Provider credentials and budget stay
// in the existing serialized protected-main workflow, never in this Worker.
import inputs from '../../../config/contextual_team/inputs-v1.json' with {type:'json'};
import {CONSOLE_HTML,CONSOLE_JS} from './contextual-console.js';
import '../../../assets/submission-schedule.js';
import '../../../assets/search-query.js';
import '../../../assets/search-retrieval.js';

const RELEASE=inputs.snapshot_id;
const VALIDATION_ORIGIN='http://127.0.0.1:8876';
const WORKFLOW='.github/workflows/team-recommender-offline.yml';
const states=new Set(['ready','ready_with_gaps','no_supported_group_in_assessed_set','needs_scope_selection',
  'insufficient_source','unsuitable','action_blocked','budget_limited','failed','recovery_required']);
const headers={'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
const jsonResponse=(status,value)=>new Response(JSON.stringify(value),{status,headers});
function fail(code,status=400){throw Object.assign(Error(code),{code,status});}
async function hash(value){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value))))).map(x=>x.toString(16).padStart(2,'0')).join('');}
async function body(request,maximum=1024){
  if(Number(request.headers.get('content-length')||0)>maximum)fail('contextual_request_too_large',413);
  const value=await request.text();if(new TextEncoder().encode(value).length>maximum)fail('contextual_request_too_large',413);
  try{return JSON.parse(value);}catch{fail('contextual_invalid_json');}
}
function current(scope,now){
  const check=globalThis.FUNDING_RETRIEVAL.recordIsCurrent;
  return check(scope.currentness.record,now)&&check(scope.currentness.parent,now);
}
function publicJob(row,scope,now){
  const result=row?.result_json?JSON.parse(row.result_json):null;
  const recovery=row?.state==='recovery_required'||result?.result?.state==='recovery_required';
  return {release_id:RELEASE,scope_id:scope.id,job_id:row?.job_id||null,
    state:recovery?'recovery_required':!current(scope,now)?'action_blocked':result?.result?.state||row?.state||scope.state,
    ...(result&&(recovery||current(scope,now))?{result:result.result,run_id:row.run_id,code_sha:row.code_sha}:{}),
    public_activation:false};
}

export class ContextualStore {
  constructor(db){this.db=db;}
  byId(id){return this.db.prepare('SELECT * FROM contextual_validation_jobs WHERE job_id=?').bind(id).first();}
  async insert(job,now){
    const result=await this.db.prepare(`INSERT INTO contextual_validation_jobs
      (job_id,release_id,scope_id,person_id,state,active_slot,created_at,updated_at)
      SELECT ?,?,?,?,'dispatch_claimed',1,?,? WHERE NOT EXISTS
      (SELECT 1 FROM contextual_validation_jobs WHERE active_slot=1)
      AND (SELECT count(*) FROM contextual_validation_jobs)<9
      AND (?='' OR NOT EXISTS (SELECT 1 FROM contextual_validation_jobs WHERE person_id<>''))
      ON CONFLICT(job_id) DO NOTHING`).bind(job.job_id,job.release_id,job.scope_id,job.person_id,now,now,job.person_id).run();
    return Number(result.meta?.changes||0)===1;
  }
  async start(id,run,sha,now){
    await this.db.prepare(`UPDATE contextual_validation_jobs SET state='in_progress',run_id=?,code_sha=?,updated_at=?
      WHERE job_id=? AND active_slot=1 AND (run_id IS NULL OR (run_id=? AND code_sha=?))`)
      .bind(run,sha,now,id,run,sha).run();return this.byId(id);
  }
  async uncertain(id,now){
    // Retain the active slot: an unknown remote dispatch must not start another
    // coordinator with an independently restored spend checkpoint.
    await this.db.prepare("UPDATE contextual_validation_jobs SET state='recovery_required',updated_at=? WHERE job_id=? AND result_json IS NULL")
      .bind(now,id).run();
  }
  async finish(id,run,sha,value,now){
    const recovery=JSON.parse(value).result.state==='recovery_required';
    // A checkpointed uncertain request still owns the sole spending slot.
    // Preserve its immutable receipt; no expiry/repeated callback clears it.
    await this.db.prepare(`UPDATE contextual_validation_jobs SET state=?,active_slot=?,result_json=?,updated_at=?
      WHERE job_id=? AND run_id=? AND code_sha=? AND result_json IS NULL`)
      .bind(recovery?'recovery_required':'complete',recovery?1:null,value,now,id,run,sha).run();return this.byId(id);
  }
}

export function createContextualHandler({storeFactory=env=>new ContextualStore(env.SUBMISSIONS_DB),
  fetchImpl=(...args)=>fetch(...args),now=()=>new Date(),authenticateAdmin,authenticateInternal}={}){
  return async function handle(request,env){
    const url=new URL(request.url),path=url.pathname;
    if(!path.startsWith('/admin/api/contextual')&&!path.startsWith('/internal/contextual')&&!path.startsWith('/admin/contextual'))return null;
    const origin=request.headers.get('origin');
    const json=(status,value)=>{
      const result=jsonResponse(status,value);
      if(path.startsWith('/admin/api/contextual')&&origin===VALIDATION_ORIGIN){
        result.headers.set('Access-Control-Allow-Origin',VALIDATION_ORIGIN);
        result.headers.set('Access-Control-Allow-Credentials','true');result.headers.set('Vary','Origin');
      }
      return result;
    };
    try{
      const internal=path.startsWith('/internal/');
      const actor=internal?await authenticateInternal(request,env):await authenticateAdmin(request,env,fetchImpl);
      if(request.method==='GET'&&['/admin/contextual','/admin/contextual/app.js'].includes(path))return new Response(path.endsWith('.js')?CONSOLE_JS:CONSOLE_HTML,
        {headers:{...headers,'Content-Type':path.endsWith('.js')?'text/javascript; charset=utf-8':'text/html; charset=utf-8',
          'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",'Referrer-Policy':'no-referrer'}});
      if(request.method==='POST'&&!internal&&origin&&origin!==url.origin&&!(path.startsWith('/admin/api/contextual')&&origin===VALIDATION_ORIGIN))
        fail('contextual_admin_origin_required',403);
      if(path==='/admin/api/contextual/manifest'&&request.method==='GET')
        return json(200,{release_id:RELEASE,registry_generation:inputs.registry_generation,public_activation:false,
          scopes:inputs.scopes.map(s=>({id:s.id,parent_id:s.parent_id,title:s.science.title,state:current(s,now())?s.state:'action_blocked'}))});
      const store=storeFactory(env);
      if(internal){
        if(request.method!=='POST'||!['/internal/contextual/start','/internal/contextual/result'].includes(path))fail('contextual_not_found',404);
        const value=await body(request,200000);
        const {job_id,release_id,run_id,code_sha}=value;
        if(!/^[a-f0-9]{64}$/.test(job_id||'')||release_id!==RELEASE||!/^\d+$/.test(run_id||'')||!/^[a-f0-9]{40}$/.test(code_sha||''))fail('contextual_callback_identity');
        const row=await store.byId(job_id);if(!row||row.release_id!==release_id)fail('contextual_job_not_found',404);
        const response=await fetchImpl(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/runs/${run_id}`,{headers:{
          Authorization:`Bearer ${env.GITHUB_DISPATCH_TOKEN}`,Accept:'application/vnd.github+json','User-Agent':'FundingFinder-ContextualValidation/1.0'}});
        if(!response.ok)fail('contextual_run_provenance_unavailable',503);
        const run=await response.json();
        if(run.path!==WORKFLOW||run.head_branch!=='main'||run.event!=='workflow_dispatch'||run.head_sha!==code_sha)fail('contextual_untrusted_workflow',403);
        if(path.endsWith('/start')){
          if(Object.keys(value).sort().join(',')!=='code_sha,job_id,release_id,run_id')fail('contextual_extra_start_fields');
          const claimed=await store.start(job_id,run_id,code_sha,now().toISOString());
          if(claimed.run_id!==run_id||claimed.code_sha!==code_sha||claimed.active_slot!==1)fail('contextual_job_already_owned',409);
          return json(200,{accepted:true,scope_id:row.scope_id,person_id:row.person_id,job_id,release_id});
        }
        if(row.run_id!==run_id||row.code_sha!==code_sha)fail('contextual_wrong_result_owner',409);
        if(!states.has(value.result?.state))fail('contextual_invalid_result_state');
        if(value.result.scope_id&&value.result.scope_id!==row.scope_id)fail('contextual_result_scope_conflict');
        if(value.result.graph_id&&(value.result.snapshot_id!==RELEASE||value.result.registry_generation!==inputs.registry_generation||value.result.scope?.id!==row.scope_id))fail('contextual_result_generation_conflict');
        const serialized=JSON.stringify(value);
        if(row.result_json&&row.result_json!==serialized)fail('contextual_terminal_result_conflict',409);
        const done=await store.finish(job_id,run_id,code_sha,serialized,now().toISOString());
        if(done.result_json!==serialized)fail('contextual_result_not_persisted',409);
        return json(200,{accepted:true});
      }
      if(path!=='/admin/api/contextual/jobs'||!['GET','POST'].includes(request.method))fail('contextual_not_found',404);
      const value=request.method==='POST'?await body(request):Object.fromEntries(url.searchParams);
      if(Object.keys(value).sort().join(',')!=='person_id,release_id,scope_id'||value.release_id!==RELEASE)fail('contextual_version_conflict',409);
      const scope=inputs.scopes.find(s=>s.id===value.scope_id);
      if(!scope||typeof value.person_id!=='string'||value.person_id&&!inputs.people.some(p=>p.person_id===value.person_id))fail('contextual_unapproved_identity');
      const job={...value,job_id:await hash([value.release_id,value.scope_id,value.person_id])};
      let row=await store.byId(job.job_id);
      if(request.method==='GET'||row)return json(200,publicJob(row,scope,now()));
      if(!current(scope,now())||scope.state!=='unassessed')return json(200,publicJob(null,scope,now()));
      if(value.person_id){
        const initial=await store.byId(await hash([value.release_id,value.scope_id,'']));
        const graph=initial?.result_json?JSON.parse(initial.result_json).result:null;
        if(!graph?.graph_id||graph.people.some(p=>p.person_id===value.person_id))fail('contextual_extension_requires_unassessed_person',409);
        const prior=await store.db.prepare("SELECT count(*) AS n FROM contextual_validation_jobs WHERE person_id<>''").first();
        if(prior.n)fail('contextual_trial_extension_already_claimed',409);
      }
      if(!env.GITHUB_DISPATCH_TOKEN)fail('contextual_dispatch_not_configured',503);
      if(env.SUBMISSION_RATE_LIMITER&&!(await env.SUBMISSION_RATE_LIMITER.limit({key:'contextual:'+await hash(actor)})).success)fail('contextual_rate_limited',429);
      const inserted=await store.insert(job,now().toISOString());
      if(!inserted){row=await store.byId(job.job_id);if(row)return json(200,publicJob(row,scope,now()));fail('contextual_busy_or_finite_job_limit',429);}
      try{
        const response=await fetchImpl(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/team-recommender-offline.yml/dispatches`,{
          method:'POST',headers:{Authorization:`Bearer ${env.GITHUB_DISPATCH_TOKEN}`,'Content-Type':'application/json',
            Accept:'application/vnd.github+json','User-Agent':'FundingFinder-ContextualValidation/1.0'},
          body:JSON.stringify({ref:'main',inputs:{contextual_job:JSON.stringify(job)}})});
        if(!response.ok)throw Error('remote_dispatch_not_confirmed');
      }catch{
        await store.uncertain(job.job_id,now().toISOString());
        return json(503,{state:'recovery_required',job_id:job.job_id,release_id:RELEASE});
      }
      return json(202,publicJob(await store.byId(job.job_id),scope,now()));
    }catch(error){return json(error.status||500,{state:'failed',error:error.code||'contextual_internal_failure'});}
  };
}
