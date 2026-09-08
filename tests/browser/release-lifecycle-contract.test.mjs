import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import test from 'node:test';
import { decideWorker, servingFingerprint, fingerprintFiles, readLiveServing, verifyServingIdentity } from '../../tools/search_worker_checkpoint.mjs';

const read = name => readFileSync(new URL(`../../${name}`, import.meta.url), 'utf8');
const workflow = read('.github/workflows/refresh-opportunities.yml');
const pages = read('.github/workflows/pages.yml');
const validator = read('tools/validate_release_candidate.py');
const publisher = read('tools/publish_release_candidate.py');
const live = read('tools/verify_release_live.py');

test('one serialized owner persists before validation and gates Worker, publication, Pages and live verification', () => {
  const ordered = ['  generate:', 'Persist the complete immutable candidate', 'Retain authoritative candidate even if later stages fail',
    '  validate:', 'tools.validate_release_candidate', '  publish:', 'Verify receipt before materializing the candidate',
    'Deploy changed Worker inputs', 'tools.publish_release_candidate', 'actions/upload-pages-artifact@v5',
    '\n  pages:\n', '  verify-live:'].map(s => workflow.indexOf(s));
  assert.ok(ordered.every(n => n >= 0));
  assert.deepEqual(ordered, [...ordered].sort((a,b) => a-b));
  assert.match(workflow, /group: funding-finder-coordinated-release\n  cancel-in-progress: false/);
  assert.match(pages, /workflow_call:/);
  assert.doesNotMatch(pages, /^  (?:push|workflow_dispatch):/m);
  assert.doesNotMatch(pages, /actions\/checkout|group: pages/);
  assert.equal(existsSync(new URL('../../.github/workflows/deploy-search-package.yml', import.meta.url)), false);
  assert.match(workflow, /needs: publish/);
  assert.match(workflow, /needs\.publish\.result == 'success'/);
  assert.doesNotMatch(workflow, /gh workflow run pages/);
});

test('resume stages load candidates and never collect data or call generation providers', () => {
  const validation = workflow.slice(workflow.indexOf('  validate:'));
  for (const source of [validation, validator, publisher, live]) {
    assert.doesNotMatch(source, /python -m scripts\.(?:build_catalog|sources|enrich_catalog|extract_document_evidence)|--generate|build_search_v2_voyage_vectors\.mjs --production/);
  }
  assert.match(workflow, /stage:|options: \[generate, reuse, validate, publish, verify\]/);
  assert.match(validator, /verify_receipt/);
  assert.match(validator, /candidate\.load\(bundle\)/);
  assert.match(validator, /candidate\.verify_files\(root, manifest\['files'\]\)/);
  assert.match(publisher, /Protected merge changed candidate bytes/);
  assert.match(live, /public_path\(name\)/);
});

test('failed validation reports are retained with candidate and exact field diagnostics', () => {
  assert.match(workflow, /Retain safe reports and receipt on success or failure\n        if: always\(\)/);
  assert.match(validator, /validation-report\.json/);
  const notice = read('tools/verify_notice_publication.py');
  assert.match(notice, /'before': bounded_public_value/);
  assert.match(notice, /'after': bounded_public_value/);
  assert.match(notice, /'candidate_id': candidate_id/);
  assert.match(notice, /print\(json\.dumps\(report,/);
  assert.doesNotMatch(notice, /if key != 'changes'/);
});

const id = '11111111-1111-4111-8111-111111111111';
const sha = 'a'.repeat(40), fp = 'b'.repeat(64);
const deployment = { id: 'deployment', created_on: '2026-09-08T00:00:00Z', versions: [{version_id:id,percentage:100}] };
const version = { id, annotations: {'workers/message':`protected-main:${sha}; input-sha256:${fp}; candidate:example`} };

test('unchanged verified Search inputs retain serving Worker; changed code/config/allowlist deploy', () => {
  const serving = servingFingerprint([deployment], version, () => {throw Error('Should use exact deployed fingerprint');});
  assert.equal(decideWorker(fp, serving).deploy_required, false);
  assert.equal(decideWorker('c'.repeat(64), serving).deploy_required, true);
  assert.equal(serving.version_id, id);
  assert.match(workflow, /if: steps\.worker-inputs\.outputs\.deploy_required == 'true'/);
  assert.match(workflow, /PRIOR_VERSION: \$\{\{ steps\.worker-inputs\.outputs\.version_id \}\}/);
  assert.match(workflow, /rollback "\$PRIOR_VERSION"/);
});

test('missing/conflicting/mixed serving provenance fails closed and never trusts health alone', () => {
  assert.throws(() => servingFingerprint([deployment], {id}, () => ({})), /no verified Git checkpoint/);
  assert.throws(() => servingFingerprint([{...deployment, annotations:{'workers/message':`protected-main:${sha}; input-sha256:${'c'.repeat(64)}`}}], version), /Conflicting/);
  assert.throws(() => servingFingerprint([{...deployment, versions:[{version_id:id,percentage:50}]}], version), /single fully active/);
  assert.throws(() => decideWorker(fp, {service:'available'}), /Verified Worker/);
});

test('verified historical upload checkpoint fingerprints actual input bytes without a hardcoded fallback', () => {
  const files = {'workers/search-voyage-proxy/src/index.js':'1', 'workers/search-voyage-proxy/generated/corpus-allowlist.json':'2'};
  let observed;
  const value = servingFingerprint([deployment], {id, annotations:{'workers/message':`protected-main:${sha}`}}, checkpoint => {observed=checkpoint; return files;});
  assert.equal(observed, sha);
  assert.equal(value.fingerprint, fingerprintFiles(files));
  assert.equal(value.version_id, id);
});

test('automatic deployment summary requires exact full active-version provenance', () => {
  const message=version.annotations['workers/message'];
  const summarized={...deployment,source:'wrangler',annotations:{
    'workers/triggered_by':'upload','workers/message':`${message.slice(0,47)}...`}};
  const serving=servingFingerprint([summarized],version);
  assert.equal(serving.fingerprint,fp);
  assert.equal(serving.checkpoint.baseSha,sha);
  assert.equal(serving.checkpoint.source,'active-version-message');
  assert.equal(decideWorker(fp,serving).deploy_required,false);
  assert.equal(verifyServingIdentity(fp,decideWorker(fp,serving),serving).verified,true);
  for(const change of ['different_prefix','non_upload','missing_version_message','malformed_full_message']) {
    const d=structuredClone(summarized),v=structuredClone(version);
    if(change==='different_prefix') d.annotations['workers/message']=`protected-main:${'c'.repeat(33)}...`;
    if(change==='non_upload') d.annotations['workers/triggered_by']='deployment';
    if(change==='missing_version_message') v.annotations={};
    if(change==='malformed_full_message') v.annotations['workers/message']=`${message}; input-sha256:bad`;
    assert.throws(() => servingFingerprint([d],v),undefined,change);
  }
});

test('live retries verify freshly read active version and complete inputs against retained publication', () => {
  const expected = decideWorker(fp, servingFingerprint([deployment], version));
  let reads = 0;
  const live = readLiveServing({deployments: () => { reads++; return [deployment]; }, version: actual => {
    assert.equal(actual, id); return version;
  }});
  assert.equal(reads, 2);
  assert.equal(verifyServingIdentity(fp, expected, live).version_id, id);
  // Same /health corpus/model/provider behavior cannot establish input equivalence.
  const otherId = '22222222-2222-4222-8222-222222222222';
  const otherVersion = {...version, id:otherId, annotations:{'workers/message':`protected-main:${sha}; input-sha256:${'c'.repeat(64)}`}};
  const changed = readLiveServing({deployments:() => [{...deployment, versions:[{version_id:otherId, percentage:100}]}], version:() => otherVersion});
  assert.throws(() => verifyServingIdentity(fp, expected, changed), /differs from the publication/);
  assert.throws(() => verifyServingIdentity(fp, expected, {...live, version_id:otherId,
    checkpoint:{...live.checkpoint, activeVersionId:otherId}}), /differs from the publication/);
  assert.throws(() => verifyServingIdentity(fp, {}, live), /Missing or malformed/);
  assert.throws(() => verifyServingIdentity(fp, {...expected, fingerprint:'c'.repeat(64)}, live), /Missing or malformed/);
});

test('live metadata reads fail closed on mixed, conflicting, malformed or changing serving provenance', () => {
  const readVersion = () => version;
  assert.throws(() => readLiveServing({deployments:() => [{...deployment, versions:[{version_id:id,percentage:50}]}], version:readVersion}), /single fully active/);
  assert.throws(() => readLiveServing({deployments:() => [deployment], version:() => ({id})}), /no verified Git checkpoint/);
  for (const message of [`protected-main:${sha}; input-sha256:broken`,
    `protected-main:${sha}; input-sha256:${fp}; input-sha256:${'c'.repeat(64)}`,
    `protected-main:broken; input-sha256:${fp}`]) {
    assert.throws(() => readLiveServing({deployments:() => [deployment], version:() => ({id, annotations:{'workers/message':message}})}), /Malformed/);
  }
  assert.throws(() => readLiveServing({deployments:() => [{...deployment, annotations:{'workers/message':`protected-main:${'d'.repeat(40)}; input-sha256:${fp}`}}], version:readVersion}), /checkpoints conflict/);
  let reads = 0;
  assert.throws(() => readLiveServing({deployments:() => [{...deployment, id:++reads === 1 ? 'old' : 'new'}], version:readVersion}), /changed while reading/);
});

test('Pages staging and live closeout re-read Worker provenance, including after provider smoke', () => {
  const staging = workflow.slice(workflow.indexOf('      - name: Package verified candidate'), workflow.indexOf('\n  pages:\n'));
  const verification = workflow.slice(workflow.indexOf('  verify-live:'), workflow.indexOf('  closeout:'));
  assert.match(staging, /CLOUDFLARE_API_TOKEN/);
  assert.equal((verification.match(/CLOUDFLARE_API_TOKEN:/g) || []).length, 2);
  assert.ok(verification.indexOf('tools.verify_release_live complete') > verification.indexOf('node tools/smoke_search_worker.mjs'));
  assert.match(live, /def stage_site[\s\S]*?worker_provenance\(bundle, reports\)/);
});
