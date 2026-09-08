import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import test from 'node:test';
import { decideWorker, servingFingerprint, fingerprintFiles } from '../../tools/search_worker_checkpoint.mjs';

const read = name => readFileSync(new URL(`../../${name}`, import.meta.url), 'utf8');
const workflow = read('.github/workflows/refresh-opportunities.yml');
const pages = read('.github/workflows/pages.yml');
const validator = read('tools/validate_release_candidate.py');
const publisher = read('tools/publish_release_candidate.py');
const live = read('tools/verify_release_live.py');

test('one serialized owner persists before validation and gates Worker, publication, Pages and live verification', () => {
  const ordered = ['  generate:', 'Persist the complete immutable candidate', 'actions/upload-artifact@v4',
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
