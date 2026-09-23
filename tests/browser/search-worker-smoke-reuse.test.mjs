import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createHandler, SearchBudgetCoordinator } from '../../workers/search-voyage-proxy/src/index.js';
import { fingerprintFiles } from '../../tools/search_worker_checkpoint.mjs';
import { VERSION, INPUT_VERSION, byteDigest, digest, reuseSearchWorkerSmoke } from '../../tools/search_worker_smoke_reuse.mjs';
import { candidateBuild, completeSmoke } from '../../tools/catalog_smoke_receipt.mjs';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const H = n => n.toString(16).padStart(64, '0');
const ID = n => n.toString(16).padStart(32, '0');
const SHA = 'a'.repeat(40);
const ORIGIN = 'https://funding-finder-voyage-search.urochestercheme.workers.dev';
const NOW = Date.parse('2026-09-23T20:00:00Z');
const clone = structuredClone;

function proof(at) {
  const files = {'@toolchain': H(1), 'workers/search-voyage-proxy/src/index.js': H(2),
    'workers/search-voyage-proxy/generated/corpus-allowlist.json': H(3),
    'workers/search-voyage-proxy/wrangler.jsonc': H(4)};
  return {fingerprint: fingerprintFiles(files), version_id: '11111111-2222-3333-4444-555555555555',
    checkpoint: {baseSha: SHA, source: 'verified-serving-bytes',
      activeDeploymentId: '66666666-7777-8888-9999-aaaaaaaaaaaa', activeVersionId: '11111111-2222-3333-4444-555555555555'},
    reconciliation: {schema_version: 1, observed_at: at, protected_input_sha: SHA, script_etag: H(7),
      content_version_id: '11111111-2222-3333-4444-555555555555', module_hashes: {'index.js': H(8), 'manifest.js': H(9)},
      input_hashes: files, configuration_fingerprint: H(10), method: 'authenticated-serving-bytes-and-configuration', production_mutated: false}};
}
function environment() {
  const values = new Map();
  const coordinator = new SearchBudgetCoordinator({storage: {
    async get(key) { return values.get(key); }, async put(key, value) { values.set(key, clone(value)); },
  }});
  const limiter = {async limit() { return {success: true}; }};
  return {VOYAGE_API_KEY: 'synthetic-not-a-credential', ENHANCED_SEARCH_ENABLED: 'true',
    DAILY_EMBED_TOKEN_BUDGET: '50000', DAILY_RERANK_TOKEN_BUDGET: '25000000',
    PER_CLIENT_EMBED_REQUEST_LIMIT: '12', PER_CLIENT_RERANK_REQUEST_LIMIT: '8', GLOBAL_REQUEST_LIMIT: '600',
    RATE_LIMIT_RETRY_AFTER_SECONDS: '10', GLOBAL_RATE_LIMITER: limiter, EMBED_RATE_LIMITER: limiter, RERANK_RATE_LIMITER: limiter,
    BUDGET_COORDINATOR: {idFromName: x => x, get: () => ({fetch: (url, options) => coordinator.fetch(new Request(url, options))})}};
}
async function fixture() {
  const shared = {passage_id: 'parent:fixture', text: 'Public research evidence for the shared funding opportunity.'};
  shared.text_sha256 = byteDigest(shared.text);
  const current = {corpus_sha256: H(11), model_space_fingerprint: H(12)};
  const previous = {corpus_sha256: H(13), model_space_fingerprint: H(14)};
  const upstream = [], env = environment();
  const handler = createHandler({allowlist: {current: {...current, passages: [shared]}, previous: {...previous, passages: [shared]}},
    fetchImpl: async (url, options) => {
      upstream.push({url: String(url), body: options.body});
      return new Response(JSON.stringify(String(url).endsWith('/embeddings')
        ? {model: 'voyage-4-lite', data: [{embedding: Array(1024).fill(.25)}], usage: {total_tokens: 1}}
        : {model: 'rerank-2.5', data: [{index: 0, relevance_score: .9}], usage: {total_tokens: 322}}));
    }});
  const post = async (path, body) => handler(new Request(ORIGIN + path, {method: 'POST',
    headers: {Origin: 'https://mporosoff.github.io', 'Content-Type': 'application/json'}, body}), env);
  const servingBefore = proof('2026-09-23T19:00:00Z'), servingAfter = proof('2026-09-23T19:01:00Z');
  const expected = {version: INPUT_VERSION, worker_origin: ORIGIN, worker_input_fingerprint: servingBefore.fingerprint,
    query: 'catalysis', shared_passage: shared, current, previous, operations: []};
  const operations = [];
  for (const [i, purpose] of ['cb-fc-cat-smoke-embed', 'cb-fc-cat-smoke-current-rerank', 'cb-fc-cat-smoke-previous-rerank'].entries()) {
    const path = i ? '/rerank' : '/embed-query';
    const publicBody = JSON.stringify(i ? {query: 'catalysis', ...(i === 1 ? current : previous), candidates: [shared]} : {query: 'catalysis'});
    const response = await post(path, publicBody), responseText = await response.text();
    assert.equal(response.status, 200);
    const providerBody = upstream[i].body, body = JSON.parse(responseText);
    const input = {purpose, path, public_body_text: publicBody, provider_body_text: providerBody,
      provider_body_sha256: byteDigest(providerBody), external_http_body_sha256: byteDigest(publicBody)};
    expected.operations.push(input);
    operations.push({purpose, request_id: ID(i + 1), key: H(i + 40), provider: 'voyage', model: body.model,
      provider_body_sha256: input.provider_body_sha256, external_http_body_sha256: input.external_http_body_sha256,
      status: 'valid', http_status: response.status, usage: body.usage,
      charged_microusd: Math.ceil(body.usage.total_tokens / (i ? 20 : 50)), response_text: responseText,
      response_sha256: byteDigest(responseText)});
  }
  const unknownBody = JSON.stringify({query: 'catalysis', corpus_sha256: 'f'.repeat(64), candidates: [shared]});
  const unknown = await post('/rerank', unknownBody), unknownText = await unknown.text();
  assert.equal(unknown.status, 400); assert.equal(upstream.length, 3);
  const receipt = {version: VERSION, status: 'passed', completed_at: '2026-09-23T19:02:00Z',
    owner: {authorization_id: 'on-demand-team-offline-v2-20260909', run_id: 123, run_attempt: 1, code_sha: SHA},
    inputs: clone(expected), serving_before: servingBefore,
    serving_after: servingAfter, operations, unknown_corpus: {http_status: 400, public_body_text: unknownBody,
      external_http_body_sha256: byteDigest(unknownBody), response_text: unknownText,
      response_sha256: byteDigest(unknownText), provider_calls: 0}};
  return {receipt, expected, fresh: proof('2026-09-23T19:59:00Z'), upstream};
}
function anchor(bytes) {
  return {repository: 'mporosoff/grants-scraper',
    run: {id: 123, run_attempt: 1, head_sha: SHA, head_branch: 'main', event: 'workflow_dispatch',
      path: '.github/workflows/team-recommender-offline.yml', status: 'completed', conclusion: 'success'},
    artifact: {id: 124, name: 'on-demand-team-offline-v2-20260909-state-123-1', digest: `sha256:${H(65)}`, run_id: 123, head_sha: SHA},
    receipt_path: 'receipts/search-smoke.json', receipt_sha256: byteDigest(bytes), ledger_sha256: H(61), checkpoint_sha256: H(62)};
}
function args(f) {
  const bytes = Buffer.from(JSON.stringify(f.receipt));
  return {receiptBytes: bytes, expected: f.expected, authenticateOwner: async () => anchor(bytes),
    readServingProof: async () => clone(f.fresh), now: () => NOW};
}
const base = await fixture();

test('candidate proof retains artifact lineage separately from unchanged protected Git proof', async () => {
  const f = clone(base);
  const candidate = {candidate_id: H(200), artifact_id: 201, artifact_digest: `sha256:${H(202)}`,
    manifest_sha256: H(203), code_sha: SHA};
  for (const p of [f.receipt.serving_before, f.receipt.serving_after, f.fresh]) {
    p.candidate = clone(candidate); p.checkpoint.source = 'verified-candidate-serving-bytes';
    p.reconciliation.method = 'authenticated-candidate-serving-bytes-and-configuration';
  }
  assert.equal((await reuseSearchWorkerSmoke(args(f))).status, 'passed_reused');
  for (const mutate of [x => x.fresh.candidate.artifact_id++, x => x.fresh.candidate.manifest_sha256 = H(204),
    x => x.fresh.reconciliation.method = 'authenticated-serving-bytes-and-configuration',
    x => delete x.fresh.candidate, x => x.fresh.candidate.code_sha = 'b'.repeat(40)]) {
    const changed = clone(f); mutate(changed);
    await assert.rejects(reuseSearchWorkerSmoke(args(changed)));
  }
});

test('later successful owner authenticates retained aggregate origin without rewriting failed original run', async () => {
  const f = clone(base), options = args(f), old = anchor(options.receiptBytes);
  const latest = clone(old);
  latest.aggregate_origin = {run: {...old.run, conclusion: 'failure'}, artifact: old.artifact,
    ledger_sha256: old.ledger_sha256, checkpoint_sha256: old.checkpoint_sha256};
  latest.run.id = 126;
  latest.artifact = {...old.artifact, id: 128, name: 'on-demand-team-offline-v2-20260909-state-126-1', run_id: 126};
  const result = await reuseSearchWorkerSmoke({...options, authenticateOwner: async () => latest});
  assert.equal(result.original_run_id, 123); assert.equal(result.authoritative_run_id, 126);
  assert.equal(result.new_provider_calls, 0);
  for (const mutate of [a => delete a.aggregate_origin, a => a.aggregate_origin.run.head_sha = 'b'.repeat(40),
    a => a.aggregate_origin.artifact.run_id = 999, a => a.aggregate_origin.run.status = 'in_progress']) {
    const changed = clone(latest); mutate(changed);
    await assert.rejects(reuseSearchWorkerSmoke({...options, authenticateOwner: async () => changed}));
  }
});

test('candidate isolated build overlays only two authenticated artifacts and preserves all protected runtime bytes', () => {
  const names = ['workers/search-voyage-proxy/generated/corpus-allowlist.json', 'workers/search-voyage-proxy/wrangler.jsonc'];
  const runtime = 'workers/search-voyage-proxy/src/index.js';
  const overrides = {[names[0]]: '{"current":"new"}', [names[1]]: '{"name":"funding-finder-voyage-search"}'};
  const files = {[runtime]: byteDigest('export default {};'), [names[0]]: H(1), [names[1]]: H(2), '@toolchain': H(3)};
  let builds = 0;
  const adapters = {inputs: () => clone(files), git: () => Buffer.from('export default {};'), dryRun: (config, output, cwd) => {
    builds++; assert.equal(readFileSync(path.join(cwd, runtime), 'utf8'), 'export default {};');
    assert.equal(readFileSync(config, 'utf8'), overrides[names[1]]);
    assert.equal(readFileSync(path.join(cwd, names[0]), 'utf8'), overrides[names[0]]);
    mkdirSync(output); writeFileSync(path.join(output, 'index.js'), 'built exact candidate');
  }};
  const result = candidateBuild(SHA, overrides, adapters);
  assert.equal(result.files[runtime], files[runtime]); assert.equal(result.files[names[0]], byteDigest(overrides[names[0]]));
  assert.equal(result.built.modules['index.js'], byteDigest('built exact candidate')); assert.equal(builds, 1);
  assert.throws(() => candidateBuild(SHA, {...overrides, [runtime]: 'changed runtime'}, adapters));
  assert.throws(() => candidateBuild(SHA, overrides, {...adapters, git: () => Buffer.from('changed runtime')}));
  assert.equal(builds, 1);
});

test('aggregate builder issues only exact nonpaid control after complete response validation and stable full proof', async () => {
  const f = clone(base); let calls = 0;
  const draft = {owner: f.receipt.owner, inputs: f.expected, serving_before: f.receipt.serving_before,
    operations: f.receipt.operations};
  const opts = {now: () => '2026-09-23T20:01:00Z', readServingProof: async () => f.fresh, post: async (url, options) => {
    calls++; assert.equal(url, ORIGIN+'/rerank'); assert.equal(options.redirect, 'error');
    assert.equal(JSON.parse(options.body).corpus_sha256, 'f'.repeat(64));
    return new Response('{"error":{"code":"invalid_candidates"}}', {status: 400});
  }};
  assert.equal((await completeSmoke(draft, opts)).status, 'passed'); assert.equal(calls, 1);
  const bad = clone(draft); bad.operations[0].status = 'failed';
  await assert.rejects(completeSmoke(bad, opts)); assert.equal(calls, 1);
  const evidence = [];
  await assert.rejects(completeSmoke(draft, {...opts, post: async () => new Response('{}', {status: 503}),
    retain: value => evidence.push(value)}));
  assert.equal(evidence.at(-1).http_status, 503); assert.equal(evidence.at(-1).status, 'failed');
});

test('actual Worker transformation and 400 control yield three checks reusable repeatedly without new provider work', async () => {
  const f = clone(base), before = JSON.stringify(f);
  for (let i = 0; i < 2; i++) {
    const result = await reuseSearchWorkerSmoke(args(f));
    assert.equal(result.status, 'passed_reused'); assert.equal(result.original_provider_requests, 3);
    assert.equal(result.original_charged_microusd, 35);
    assert.equal(result.new_provider_calls, 0); assert.equal(result.new_metered_attempts, 0);
    assert.equal(result.new_native_counts, 0); assert.equal(result.new_paid_usage_microusd, 0);
  }
  assert.equal(f.upstream.length, 3); assert.equal(JSON.stringify(f), before);
});

test('all three distinct named successful owner operations are mandatory', async () => {
  for (const mutate of [r => r.operations.pop(), r => r.operations.reverse(), r => {r.operations[1].status = 'failed';},
    r => {r.operations[1].status = 'reserved_unknown';}, r => {r.operations[1].request_id = r.operations[0].request_id;},
    r => {r.operations[1].key = r.operations[0].key;}, r => {r.status = 'partial';}]) {
    const f = clone(base); mutate(f.receipt); await assert.rejects(reuseSearchWorkerSmoke(args(f)), /Search smoke reuse rejected/);
  }
});

test('current, previous, model-space and exact bytes cannot be substituted by a matching model name', async () => {
  for (const mutate of [e => {e.current.corpus_sha256 = H(200);}, e => {e.previous.corpus_sha256 = H(201);},
    e => {e.previous.model_space_fingerprint = H(202);}, e => {e.current.model_space_fingerprint = H(203);},
    e => {e.operations[1].public_body_text += ' ';}, e => {e.operations[0].provider_body_text += ' ';},
    e => {e.shared_passage.text += ' unrelated';}, e => {e.worker_origin = 'https://other.example';}]) {
    const f = clone(base); mutate(f.expected); await assert.rejects(reuseSearchWorkerSmoke(args(f)), /Search smoke reuse rejected/);
  }
});

test('complete transformed provider semantics are checked independently of supplied hashes', async () => {
  for (const i of [0, 1, 2]) {
    const f = clone(base), op = f.expected.operations[i], body = JSON.parse(op.provider_body_text);
    if (i === 0) body.input = ['another query']; else body.documents = ['different passage'];
    op.provider_body_text = JSON.stringify(body); op.provider_body_sha256 = byteDigest(op.provider_body_text);
    f.receipt.inputs = clone(f.expected); f.receipt.operations[i].provider_body_sha256 = op.provider_body_sha256;
    await assert.rejects(reuseSearchWorkerSmoke(args(f)), /complete supported provider transformation/);
  }
});

test('full responses require finite owned vectors/rankings, model, positive integer usage and exact charge', async () => {
  for (const [i, mutate] of [[0, b => b.embedding.pop()], [0, b => b.embedding.fill(0)],
    [0, b => {b.embedding[0] = null;}], [0, b => {b.model = 'voyage-4-large';}],
    [1, b => {b.rankings[0].index = 1;}], [1, b => {b.rankings[0].passage_id = 'foreign';}],
    [1, b => {b.rankings[0].relevance_score = 2;}], [2, b => {b.usage.total_tokens = 1.5;}],
    [2, b => {b.usage.total_tokens = true;}], [2, b => {b.usage.total_tokens = 0;}]]) {
    const f = clone(base), r = f.receipt.operations[i], body = JSON.parse(r.response_text);
    mutate(body); r.response_text = JSON.stringify(body); r.response_sha256 = byteDigest(r.response_text);
    r.usage = clone(body.usage);
    await assert.rejects(reuseSearchWorkerSmoke(args(f)), /Search smoke reuse rejected/);
  }
  const f = clone(base); f.receipt.operations[1].charged_microusd = 1;
  await assert.rejects(reuseSearchWorkerSmoke(args(f)), /actual rounded provider charge/);
});

test('raw response whitespace and float serialization stay bound to original bytes', async () => {
  const f = clone(base), r = f.receipt.operations[0];
  r.response_text = r.response_text.replace('0.25', '0.250');
  await assert.rejects(reuseSearchWorkerSmoke(args(f)), /full response identity/);
  r.response_sha256 = byteDigest(r.response_text);
  assert.equal((await reuseSearchWorkerSmoke(args(f))).status, 'passed_reused');
});

test('authenticated owner, checkpoint and artifact-file mismatches are terminal', async () => {
  for (const mutate of [a => {a.repository = 'foreign/repo';}, a => {a.run.event = 'repository_dispatch';},
    a => {a.run.head_branch = 'feature';}, a => {a.run.head_sha = 'b'.repeat(40);},
    a => {a.run.conclusion = 'failure';}, a => {a.artifact.run_id++;}, a => {a.artifact.digest = 'not-a-digest';},
    a => {a.receipt_sha256 = H(300);}, a => {a.checkpoint_sha256 = 'invalid';},
    a => {a.receipt_path = '../private.json';}, a => {a.run.path = '.github/workflows/other.yml';}]) {
    const p = args(clone(base)); p.authenticateOwner = async b => {const a = anchor(b); mutate(a); return a;};
    await assert.rejects(reuseSearchWorkerSmoke(p), /Search smoke reuse rejected/);
  }
  const p = args(clone(base)); p.authenticateOwner = async () => {throw new Error('authenticated archive missing');};
  let servingReads = 0; p.readServingProof = async () => {servingReads++; return base.fresh;};
  await assert.rejects(reuseSearchWorkerSmoke(p), /authenticated archive missing/); assert.equal(servingReads, 0);
});

test('fresh authenticated every-module/config/deployment provenance is required even with healthy endpoints', async () => {
  for (const mutate of [p => {p.reconciliation.module_hashes['manifest.js'] = H(310);},
    p => {delete p.reconciliation.module_hashes['manifest.js'];}, p => {p.reconciliation.module_hashes['extra.js'] = H(311);},
    p => {p.reconciliation.configuration_fingerprint = H(312);}, p => {p.reconciliation.script_etag = H(313);},
    p => {p.checkpoint.activeDeploymentId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';},
    p => {p.version_id = 'aaaaaaaa-bbbb-cccc-dddd-ffffffffffff';},
    p => {p.reconciliation.input_hashes['workers/search-voyage-proxy/wrangler.jsonc'] = H(314);},
    p => {p.checkpoint.source = 'active-version-message'; delete p.reconciliation;},
    p => {p.reconciliation = {service: 'available'};}]) {
    const f = clone(base); mutate(f.fresh); await assert.rejects(reuseSearchWorkerSmoke(args(f)), /Search smoke reuse rejected/);
  }
});

test('input-identical later protected commit is allowed only through complete reconstructed proof', async () => {
  const f = clone(base); f.fresh.checkpoint.baseSha = 'b'.repeat(40); f.fresh.reconciliation.protected_input_sha = 'b'.repeat(40);
  assert.equal((await reuseSearchWorkerSmoke(args(f))).status, 'passed_reused');
  f.fresh.reconciliation.module_hashes['index.js'] = H(320);
  await assert.rejects(reuseSearchWorkerSmoke(args(f)), /fresh authenticated serving identity changed/);
});

test('stale, future or out-of-order proof and incomplete unknown-corpus control reject reuse', async () => {
  for (const stamp of ['2026-09-23T19:54:59Z', '2026-09-23T20:00:01Z', 'invalid', '2026-09-23T24:00:00Z']) {
    const f = clone(base); f.fresh.reconciliation.observed_at = stamp;
    await assert.rejects(reuseSearchWorkerSmoke(args(f)), /Search smoke reuse rejected/);
  }
  for (const mutate of [r => {r.serving_before.reconciliation.observed_at = '2026-09-23T19:03:00Z';},
    r => {r.unknown_corpus.http_status = 200;}, r => {r.unknown_corpus.provider_calls = 1;},
    r => {r.unknown_corpus.response_text = JSON.stringify({error: {code: 'rate_limited'}});
      r.unknown_corpus.response_sha256 = byteDigest(r.unknown_corpus.response_text);},
    r => {delete r.unknown_corpus;}]) {
    const f = clone(base); mutate(f.receipt); await assert.rejects(reuseSearchWorkerSmoke(args(f)), /Search smoke reuse rejected/);
  }
});

test('concurrent readers preserve their captured bytes across caller mutation and have no paid fallback', async () => {
  const f = clone(base), p = args(f), original = Buffer.from(p.receiptBytes), originalInputs = clone(p.expected);
  let count = 0, release; const barrier = new Promise(resolve => {release = resolve;});
  p.authenticateOwner = async b => {count++; if (count === 2) release(); await barrier; return anchor(b);};
  const first = reuseSearchWorkerSmoke(p), second = reuseSearchWorkerSmoke(p);
  p.receiptBytes.fill(0); p.expected.query = 'mutated';
  const [a, b] = await Promise.all([first, second]);
  assert.equal(a.receipt_sha256, byteDigest(original)); assert.deepEqual(a, b); assert.equal(base.expected.query, originalInputs.query);
  await assert.rejects(reuseSearchWorkerSmoke({receiptBytes: original, expected: originalInputs}), /authenticated evidence readers required/);
  const source = await readFile(new URL('../../tools/search_worker_smoke_reuse.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /from ['"](?:.*smoke_search_worker|node:child_process)|\bfetch\s*\(/);
});
