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
  const resources = {script:{etag:'etag'}, script_runtime:{compatibility_date:config.compatibility_date,exports:config.exports,usage_model:'standard'},
    bindings:[{name:'ENHANCED_SEARCH_ENABLED',type:'plain_text',text:'true'},
      {name:'BUDGET_COORDINATOR',class_name:'SearchBudgetCoordinator',type:'durable_object_namespace',namespace_id:'d'.repeat(32)},
      {...config.ratelimits[0],type:'ratelimit'}, {name:'VOYAGE_API_KEY',type:'secret_text'}]};
  const files = {'workers/search-voyage-proxy/src/index.js':hash('source'), '@toolchain':hash('{"wrangler":"4.125.0"}\n')};
  const state = {resources, deployment:{id:'deployment',created_on:'2026-09-07T00:00:00Z',versions:[{version_id:id,percentage:100}]},
    module:'export default {};', etag:'etag', enabled:true, reads:0};
  const calls=[];
  const request = async (url, raw) => {
    calls.push([url,raw]);
    if (url === '/deployments') {state.reads++; return {deployments:[structuredClone(state.deployment)]};}
    if (url === `/versions/${id}`) return {id,resources:state.resources};
    if (url === '/subdomain') return {enabled:state.enabled};
    assert.equal(url, ''); assert.equal(raw,true);
    const form = new FormData(); form.set('index.js',state.module);
    const response = new Response(form); response.headers.set('etag',state.etag); return response;
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
  for (const mutation of ['module','etag','runtime','binding','secret','extra_binding','route','mixed']) {
    const f=fixture();
    if (mutation === 'module') f.state.module='different Worker implementation';
    if (mutation === 'etag') f.state.etag='another-version';
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
