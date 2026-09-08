import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {reconcile, verifyConfiguration, verifyModules} from '../../tools/reconcile_search_worker_provenance.mjs';
import {servingFingerprint, fingerprintFiles, decideWorker, verifyServingIdentity} from '../../tools/search_worker_checkpoint.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const sha = 'a'.repeat(40), id = '11111111-1111-4111-8111-111111111111';
function fixture() {
  const config = {name:'funding-finder-voyage-search', main:'src/index.js', compatibility_date:'2026-08-23', workers_dev:true,
    vars:{ENHANCED_SEARCH_ENABLED:'true'}, exports:{SearchBudgetCoordinator:{type:'durable-object',storage:'sqlite'}},
    durable_objects:{bindings:[{name:'BUDGET_COORDINATOR',class_name:'SearchBudgetCoordinator'}]},
    ratelimits:[{name:'EMBED_RATE_LIMITER',namespace_id:'1234',simple:{limit:12,period:60}}]};
  const resources = {script:{etag:'e'.repeat(64)}, script_runtime:{compatibility_date:config.compatibility_date,exports:config.exports,usage_model:'standard'},
    bindings:[{name:'ENHANCED_SEARCH_ENABLED',type:'plain_text',text:'true'},
      {name:'BUDGET_COORDINATOR',class_name:'SearchBudgetCoordinator',type:'durable_object_namespace',namespace_id:'d'.repeat(32)},
      {...config.ratelimits[0],type:'ratelimit'}, {name:'VOYAGE_API_KEY',type:'secret_text'}]};
  const files = {'workers/search-voyage-proxy/src/index.js':hash('source'), '@toolchain':hash('{"wrangler":"4.125.0"}\n')};
  const state = {resources, deployment:{id:'deployment',created_on:'2026-09-07T00:00:00Z',versions:[{version_id:id,percentage:100}]},
    module:'export default {};', contentId:id, enabled:true, reads:0};
  const calls=[];
  const request = async (url, api) => {
    calls.push([url,api]);
    if (url === '/deployments') {state.reads++; return {deployments:[structuredClone(state.deployment)]};}
    if (url === `/versions/${id}`) return {id,resources:state.resources};
    if (url === '/subdomain') return {enabled:state.enabled};
    assert.equal(url, `/versions/${id}?include=modules`); assert.equal(api,'workers');
    return {id:state.contentId,modules:[{name:'index.js',content_type:'application/javascript+module',
      content_base64:Buffer.from(state.module).toString('base64')}]};
  };
  return {config,state,files,calls,options:{request,inputs:() => files,build:() => ({config,modules:{'index.js':hash('export default {};')}}),
    git:(...args) => {assert.deepEqual(args,['merge-base','--is-ancestor',sha,'origin/main']);}}};
}

test('unannotated Worker is identified only by exact authenticated build and complete configuration proof',async () => {
  const f=fixture();
  const proof=await reconcile(sha,'deployment',id,f.options);
  assert.equal(proof.fingerprint,fingerprintFiles(f.files));
  assert.equal(proof.version_id,id);
  assert.equal(proof.reconciliation.production_mutated,false);
  assert.equal(f.state.reads,2);
  assert.equal(decideWorker(proof.fingerprint,proof).deploy_required,false);
  assert.equal(decideWorker('f'.repeat(64),proof).deploy_required,true);
  assert.equal(verifyServingIdentity(proof.fingerprint,decideWorker(proof.fingerprint,proof),proof).verified,true);
  assert.throws(() => verifyServingIdentity(proof.fingerprint,{...decideWorker(proof.fingerprint,proof),reconciliation:null},proof),/Missing or malformed/);
  const recovered=servingFingerprint([f.state.deployment],{id},null,() => proof);
  assert.equal(recovered,proof);
  assert.throws(() => servingFingerprint([f.state.deployment],{id,annotations:{'workers/message':`input-sha256:${'f'.repeat(64)}`}},null,() => proof),/Conflicting/);
});

test('unknown or mismatched serving modules, runtime, bindings and routes cannot acquire provenance',async () => {
  for (const mutation of ['module','version','etag','runtime','binding','secret','extra_binding','route','mixed']) {
    const f=fixture();
    if (mutation === 'module') f.state.module='different Worker implementation';
    if (mutation === 'version') f.state.contentId='22222222-2222-4222-8222-222222222222';
    if (mutation === 'etag') delete f.state.resources.script.etag;
    if (mutation === 'runtime') f.state.resources.script_runtime.compatibility_date='2025-01-01';
    if (mutation === 'binding') f.state.resources.bindings[0].text='false';
    if (mutation === 'secret') f.state.resources.bindings.pop();
    if (mutation === 'extra_binding') f.state.resources.bindings.push({name:'UNDECLARED',type:'plain_text',text:'x'});
    if (mutation === 'route') f.state.enabled=false;
    if (mutation === 'mixed') f.state.deployment.versions[0].percentage=50;
    await assert.rejects(reconcile(sha,'deployment',id,f.options),undefined,mutation);
  }
  assert.throws(() => verifyModules({'index.js':'hash'},{'index.js':'hash','extra.js':'hash'}),/module bytes differ/);
  const f=fixture(); f.config.limits={cpu_ms:300};
  assert.throws(() => verifyConfiguration(f.config,f.state.resources),/unsupported deployment configuration/);
});

test('rollback reconstruction reads active-version modules even when latest upload is different',async () => {
  const f=fixture();
  const original=f.options.request;
  f.options.request=async (url,api) => {
    // The unversioned download remains on the unsuccessful later upload.
    if(url==='') return new Response('different latest upload');
    return original(url,api);
  };
  const proof=await reconcile(sha,'deployment',id,f.options);
  assert.equal(proof.reconciliation.content_version_id,id);
  assert.deepEqual(proof.reconciliation.module_hashes,{'index.js':hash(f.state.module)});
  assert.ok(f.calls.some(([url,api]) => url===`/versions/${id}?include=modules` && api==='workers'));
  assert.ok(f.calls.every(([url]) => url!==''));
});

test('version-bound content rejects missing, duplicate, malformed and differently typed modules',async () => {
  for(const mutation of ['missing','duplicate','malformed','type']) {
    const f=fixture(), original=f.options.request;
    f.options.request=async (...args) => {
      const result=await original(...args);
      if(args[1]==='workers') {
        if(mutation==='missing') delete result.modules;
        if(mutation==='duplicate') result.modules.push({...result.modules[0]});
        if(mutation==='malformed') result.modules[0].content_base64='not valid base64!';
        if(mutation==='type') result.modules[0].content_type='text/plain';
      }
      return result;
    };
    await assert.rejects(reconcile(sha,'deployment',id,f.options),undefined,mutation);
  }
});

test('reconstruction rejects unprotected commits and a serving change during inspection',async () => {
  let f=fixture();
  f.options.git=() => {throw new Error('not protected');};
  await assert.rejects(reconcile(sha,'deployment',id,f.options),/not protected/);
  f=fixture();
  const original=f.options.request;
  f.options.request=async (...args) => {
    if(args[0]==='/deployments' && f.state.reads===1) f.state.deployment.id='new-deployment';
    return original(...args);
  };
  await assert.rejects(reconcile(sha,'deployment',id,f.options),/changed during reconciliation/);
});
