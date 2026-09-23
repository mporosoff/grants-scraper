// Successful smoke reuse is evidence admission only: this module has no fetch,
// provider client, subprocess, credential or fallback-to-paid execution path.
import { createHash } from 'node:crypto';
import { fingerprintFiles } from './search_worker_checkpoint.mjs';

export const VERSION = 'search-worker-successful-smoke-v1';
export const INPUT_VERSION = 'search-worker-smoke-inputs-v1';
const WORKER = 'https://funding-finder-voyage-search.urochestercheme.workers.dev';
const AUTHORIZATION = 'on-demand-team-offline-v2-20260909';
const PURPOSES = ['cb-fc-cat-smoke-embed', 'cb-fc-cat-smoke-current-rerank', 'cb-fc-cat-smoke-previous-rerank'];
const RERANK_QUERY = 'Rank public funding opportunities by whether their authoritative scientific or programmatic scope supports the complete research intent. Do not reward partial word overlap when a major query concept is absent.\n\nResearch query: catalysis';
const HEX = /^[a-f0-9]{64}$/;
const SHA = /^[a-f0-9]{40}$/;
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const fail = message => { throw new Error(`Search smoke reuse rejected: ${message}`); };
const require = (condition, message) => { if (!condition) fail(message); };
const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
function keys(value, expected, label) {
  require(plain(value) && Object.keys(value).sort().join('|') === [...expected].sort().join('|'), label);
}
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (plain(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  require(value === null || ['string', 'boolean'].includes(typeof value)
    || (typeof value === 'number' && Number.isFinite(value)), 'non-JSON value');
  return JSON.stringify(value);
}
export const digest = value => createHash('sha256').update(canonical(value), 'utf8').digest('hex');
export const byteDigest = value => createHash('sha256').update(value).digest('hex');
const same = (a, b) => canonical(a) === canonical(b);
const positive = n => Number.isSafeInteger(n) && n > 0;
function timestamp(value) {
  require(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value), 'timestamp');
  const result = Date.parse(value);
  require(Number.isFinite(result), 'timestamp');
  return result;
}
function generation(value) {
  keys(value, ['corpus_sha256', 'model_space_fingerprint'], 'generation fields');
  require(HEX.test(value.corpus_sha256) && HEX.test(value.model_space_fingerprint), 'generation identity');
}
function hashMap(value, label) {
  require(plain(value) && Object.keys(value).length > 0 && Object.keys(value).length <= 128, label);
  require(Object.entries(value).every(([name, hash]) => name.length > 0 && name.length <= 240 && HEX.test(hash)), label);
}
export function validateServingProof(proof) {
  const candidate = proof?.checkpoint?.source === 'verified-candidate-serving-bytes';
  keys(proof, ['fingerprint', 'version_id', 'checkpoint', 'reconciliation', ...(candidate ? ['candidate'] : [])], 'complete serving proof');
  keys(proof.checkpoint, ['baseSha', 'source', 'activeDeploymentId', 'activeVersionId'], 'serving checkpoint');
  const c = proof.checkpoint, r = proof.reconciliation;
  keys(r, ['schema_version', 'observed_at', 'protected_input_sha', 'script_etag', 'content_version_id',
    'module_hashes', 'input_hashes', 'configuration_fingerprint', 'method', 'production_mutated'], 'complete reconciliation');
  require(r.schema_version === 1 && r.method === (candidate ? 'authenticated-candidate-serving-bytes-and-configuration' : 'authenticated-serving-bytes-and-configuration')
    && r.production_mutated === false && c.source === (candidate ? 'verified-candidate-serving-bytes' : 'verified-serving-bytes'), 'full authenticated reconciliation required');
  if (candidate) {
    keys(proof.candidate, ['candidate_id', 'artifact_id', 'artifact_digest', 'manifest_sha256', 'code_sha'], 'candidate evidence');
    const a = proof.candidate;
    require(HEX.test(a.candidate_id) && positive(a.artifact_id) && /^sha256:[a-f0-9]{64}$/.test(a.artifact_digest)
      && HEX.test(a.manifest_sha256) && a.code_sha === c.baseSha, 'exact candidate artifact and protected code');
  }
  require(SHA.test(c.baseSha) && !/^0{40}$/.test(c.baseSha) && r.protected_input_sha === c.baseSha,
    'protected serving inputs');
  require(UUID.test(proof.version_id) && c.activeVersionId === proof.version_id && r.content_version_id === proof.version_id
    && UUID.test(c.activeDeploymentId), 'serving deployment/version');
  hashMap(r.module_hashes, 'all serving modules'); hashMap(r.input_hashes, 'all serving inputs');
  require(Object.keys(r.module_hashes).every(name => !/[\\/]/.test(name)), 'module names');
  require(Object.hasOwn(r.input_hashes, '@toolchain')
    && Object.hasOwn(r.input_hashes, 'workers/search-voyage-proxy/wrangler.jsonc')
    && Object.hasOwn(r.input_hashes, 'workers/search-voyage-proxy/generated/corpus-allowlist.json')
    && Object.hasOwn(r.input_hashes, 'workers/search-voyage-proxy/src/index.js'), 'complete protected input inventory');
  require(HEX.test(r.script_etag) && HEX.test(r.configuration_fingerprint)
    && fingerprintFiles(r.input_hashes) === proof.fingerprint, 'serving fingerprint');
  timestamp(r.observed_at);
  // The reconciler authenticates workers_dev route settings against the full
  // protected wrangler input, and brackets module/config reads by active IDs.
  return { fingerprint: proof.fingerprint, version_id: proof.version_id, deployment_id: c.activeDeploymentId,
    script_etag: r.script_etag, module_hashes: r.module_hashes, input_hashes: r.input_hashes,
    configuration_fingerprint: r.configuration_fingerprint, ...(candidate ? {candidate: proof.candidate} : {}) };
}
function inputs(value) {
  keys(value, ['version', 'worker_origin', 'worker_input_fingerprint', 'query', 'shared_passage', 'current', 'previous', 'operations'], 'input fields');
  require(value.version === INPUT_VERSION && value.worker_origin === WORKER && value.query === 'catalysis'
    && HEX.test(value.worker_input_fingerprint), 'fixed smoke inputs');
  generation(value.current); generation(value.previous);
  require(value.current.corpus_sha256 !== value.previous.corpus_sha256, 'distinct current and previous corpora');
  keys(value.shared_passage, ['passage_id', 'text_sha256', 'text'], 'shared passage');
  const shared = value.shared_passage;
  require(typeof shared.passage_id === 'string' && shared.passage_id.length > 0 && shared.passage_id.length <= 200
    && typeof shared.text === 'string' && shared.text.length > 0 && Buffer.byteLength(shared.text) <= 65536
    && byteDigest(Buffer.from(shared.text)) === shared.text_sha256, 'complete shared passage bytes');
  require(Array.isArray(value.operations) && value.operations.length === 3, 'three input operations');
  for (const [i, op] of value.operations.entries()) {
    keys(op, ['purpose', 'path', 'public_body_text', 'provider_body_text', 'provider_body_sha256', 'external_http_body_sha256'], 'operation inputs');
    const purpose = PURPOSES[i], model = i === 0 ? 'voyage-4-lite' : 'rerank-2.5';
    require(op.purpose === purpose && op.path === (i === 0 ? '/embed-query' : '/rerank'), 'distinct smoke operation');
    const publicBody = i === 0 ? {query: value.query} : {query: value.query,
      ...value[i === 1 ? 'current' : 'previous'], candidates: [shared]};
    const external = bodyText(op.public_body_text, 'external request'), provider = bodyText(op.provider_body_text, 'provider request');
    require(same(external, publicBody) && byteDigest(op.public_body_text) === op.external_http_body_sha256,
      'exact external HTTP body');
    require(plain(provider) && provider.model === model
      && byteDigest(op.provider_body_text) === op.provider_body_sha256, 'exact transformed provider body');
    const providerBody = i === 0 ? {input: ['catalysis'], model, input_type: 'query', truncation: true,
      output_dimension: 1024, output_dtype: 'float'} : {query: RERANK_QUERY, documents: [shared.text], model,
      top_k: 1, return_documents: false, truncation: true};
    require(same(provider, providerBody), 'complete supported provider transformation');
  }
}
function bodyText(text, label) {
  require(typeof text === 'string' && text.length > 0 && Buffer.byteLength(text) <= 262144, `bounded ${label} bytes`);
  try { return JSON.parse(text); } catch { fail(`invalid ${label} JSON`); }
}
function operation(row, expected, shared) {
  keys(row, ['purpose', 'request_id', 'key', 'provider', 'model', 'provider_body_sha256', 'external_http_body_sha256',
    'status', 'http_status', 'usage', 'charged_microusd', 'response_text', 'response_sha256'], 'complete operation receipt');
  require(row.purpose === expected.purpose && /^[a-f0-9]{32}$/.test(row.request_id) && HEX.test(row.key)
    && row.provider === 'voyage' && row.model === bodyText(expected.provider_body_text, 'provider request').model
    && row.provider_body_sha256 === expected.provider_body_sha256
    && row.external_http_body_sha256 === expected.external_http_body_sha256
    && row.status === 'valid' && row.http_status === 200, 'accepted operation identities');
  keys(row.usage, ['total_tokens'], 'usage fields');
  require(positive(row.usage.total_tokens)
    && row.usage.total_tokens <= Buffer.byteLength(expected.provider_body_text) + 1024, 'actual positive integer usage within exact reservation');
  const divisor = expected.purpose === PURPOSES[0] ? 50 : 20;
  require(row.charged_microusd === Math.ceil(row.usage.total_tokens / divisor)
    && positive(row.charged_microusd), 'actual rounded provider charge');
  const result = bodyText(row.response_text, 'full response');
  require(byteDigest(row.response_text) === row.response_sha256, 'full response identity');
  keys(result, ['model', expected.purpose === PURPOSES[0] ? 'embedding' : 'rankings', 'usage', 'latency_ms'], 'strict Worker response');
  require(result.model === row.model && same(result.usage, row.usage)
    && typeof result.latency_ms === 'number' && Number.isFinite(result.latency_ms) && result.latency_ms >= 0,
    'strict response model/usage/latency');
  if (expected.purpose === PURPOSES[0]) {
    require(Array.isArray(result.embedding) && result.embedding.length === 1024
      && result.embedding.every(n => typeof n === 'number' && Number.isFinite(n))
      && result.embedding.some(n => n !== 0), 'strict embedding');
  } else {
    require(Array.isArray(result.rankings) && result.rankings.length === 1, 'strict single-passage rankings');
    const ranking = result.rankings[0];
    keys(ranking, ['index', 'passage_id', 'relevance_score'], 'ranking fields');
    require(ranking.index === 0 && ranking.passage_id === shared.passage_id
      && typeof ranking.relevance_score === 'number' && Number.isFinite(ranking.relevance_score)
      && ranking.relevance_score >= 0 && ranking.relevance_score <= 1, 'ranking ownership/score');
  }
}
function owner(receipt, bytes, anchor) {
  keys(receipt.owner, ['authorization_id', 'run_id', 'run_attempt', 'code_sha'], 'owner receipt');
  const retained = Object.hasOwn(anchor, 'aggregate_origin');
  keys(anchor, ['repository', 'run', 'artifact', 'receipt_path', 'receipt_sha256', 'ledger_sha256', 'checkpoint_sha256',
    ...(retained ? ['aggregate_origin'] : [])], 'authenticated owner anchor');
  keys(anchor.run, ['id', 'run_attempt', 'head_sha', 'head_branch', 'event', 'path', 'status', 'conclusion'], 'terminal trusted run');
  keys(anchor.artifact, ['id', 'name', 'digest', 'run_id', 'head_sha'], 'authenticated state artifact');
  const o = receipt.owner, r = anchor.run, a = anchor.artifact;
  let origin = r;
  if (retained) {
    const prior = anchor.aggregate_origin;
    keys(prior, ['run', 'artifact', 'ledger_sha256', 'checkpoint_sha256'], 'authenticated aggregate origin');
    keys(prior.run, ['id', 'run_attempt', 'head_sha', 'head_branch', 'event', 'path', 'status', 'conclusion'], 'aggregate run');
    keys(prior.artifact, ['id', 'name', 'digest', 'run_id', 'head_sha'], 'aggregate artifact');
    origin = prior.run;
    require(origin.head_branch === 'main' && origin.event === 'workflow_dispatch'
      && origin.path === '.github/workflows/team-recommender-offline.yml' && origin.status === 'completed'
      && ['success', 'failure', 'cancelled', 'timed_out'].includes(origin.conclusion)
      && HEX.test(prior.ledger_sha256) && HEX.test(prior.checkpoint_sha256)
      && positive(prior.artifact.id) && /^sha256:[a-f0-9]{64}$/.test(prior.artifact.digest)
      && prior.artifact.name === `${AUTHORIZATION}-state-${origin.id}-${origin.run_attempt}`
      && prior.artifact.run_id === origin.id && prior.artifact.head_sha === origin.head_sha, 'retained aggregate origin evidence');
  }
  require(anchor.repository === 'mporosoff/grants-scraper' && r.head_branch === 'main' && r.event === 'workflow_dispatch'
    && r.path === '.github/workflows/team-recommender-offline.yml' && r.status === 'completed' && r.conclusion === 'success',
    'trusted completed manual-main execution');
  require(o.authorization_id === AUTHORIZATION && positive(o.run_id) && positive(o.run_attempt)
    && o.run_id === origin.id && o.run_attempt === origin.run_attempt && o.code_sha === origin.head_sha && SHA.test(o.code_sha)
    && positive(r.id) && positive(r.run_attempt) && SHA.test(r.head_sha)
    && HEX.test(anchor.ledger_sha256) && HEX.test(anchor.checkpoint_sha256), 'exact owner checkpoint');
  require(positive(a.id) && a.name === `${AUTHORIZATION}-state-${r.id}-${r.run_attempt}`
    && /^sha256:[a-f0-9]{64}$/.test(a.digest) && a.run_id === r.id && a.head_sha === r.head_sha,
    'exact authenticated state artifact');
  require(/^(?:receipts|cache)\/[A-Za-z0-9_.-]+\.json$/.test(anchor.receipt_path)
    && anchor.receipt_sha256 === byteDigest(bytes), 'checkpoint-owned receipt bytes');
}

/** The caller's authenticator must fetch/verify the terminal GitHub run, raw
 * artifact ZIP digest, full owner checkpoint, exact receipt file and all three
 * matching valid ledger rows/accepted caches; it must not merely return claims
 * copied from receiptBytes. Final ledger/checkpoint hashes are external anchor
 * fields so the checkpoint-owned receipt cannot refer to its own file hash.
 * readServingProof must run
 * the authenticated full module/config/route reconciler, including on an
 * annotated deployment. Neither callback may perform paid or mutating calls.
 */
export function validateSuccessfulSmokeReceipt({receiptBytes: inputBytes, expected: inputExpected}) {
  require(Buffer.isBuffer(inputBytes) && inputBytes.length > 0 && inputBytes.length <= 1024 * 1024, 'bounded receipt bytes');
  const receiptBytes = Buffer.from(inputBytes), expected = structuredClone(inputExpected);
  let receipt;
  try { receipt = JSON.parse(receiptBytes.toString('utf8')); } catch { fail('invalid receipt JSON'); }
  keys(receipt, ['version', 'status', 'completed_at', 'owner', 'inputs', 'serving_before', 'serving_after', 'operations', 'unknown_corpus'], 'aggregate receipt fields');
  require(receipt.version === VERSION && receipt.status === 'passed', 'complete successful smoke required');
  keys(receipt.owner, ['authorization_id', 'run_id', 'run_attempt', 'code_sha'], 'owner receipt');
  require(receipt.owner.authorization_id === AUTHORIZATION && positive(receipt.owner.run_id)
    && positive(receipt.owner.run_attempt) && SHA.test(receipt.owner.code_sha), 'original owner identity');
  inputs(expected); inputs(receipt.inputs);
  require(same(receipt.inputs, expected), 'all effective inputs unchanged');
  const before = validateServingProof(receipt.serving_before), after = validateServingProof(receipt.serving_after);
  require(same(before, after) && after.fingerprint === expected.worker_input_fingerprint, 'original serving identity stable');
  const completed = timestamp(receipt.completed_at);
  require(timestamp(receipt.serving_before.reconciliation.observed_at) <= timestamp(receipt.serving_after.reconciliation.observed_at)
    && timestamp(receipt.serving_after.reconciliation.observed_at) <= completed, 'original evidence ordering');
  require(Array.isArray(receipt.operations) && receipt.operations.length === 3, 'all three successful provider checks');
  for (const [i, row] of receipt.operations.entries()) operation(row, expected.operations[i], expected.shared_passage);
  require(new Set(receipt.operations.map(r => r.request_id)).size === 3
    && new Set(receipt.operations.map(r => r.key)).size === 3, 'distinct irreversible owner requests');
  keys(receipt.unknown_corpus, ['http_status', 'public_body_text', 'external_http_body_sha256', 'response_text', 'response_sha256', 'provider_calls'], 'unknown-corpus control');
  const unknownBody = {query: expected.query, corpus_sha256: 'f'.repeat(64), candidates: [expected.shared_passage]};
  require(![expected.current.corpus_sha256, expected.previous.corpus_sha256].includes(unknownBody.corpus_sha256)
    && receipt.unknown_corpus.http_status === 400 && receipt.unknown_corpus.provider_calls === 0
    && same(bodyText(receipt.unknown_corpus.public_body_text, 'unknown-corpus request'), unknownBody)
    && receipt.unknown_corpus.external_http_body_sha256 === byteDigest(receipt.unknown_corpus.public_body_text)
    && receipt.unknown_corpus.response_sha256 === byteDigest(receipt.unknown_corpus.response_text), 'original nonpaid unknown-corpus rejection');
  const unknownResponse = bodyText(receipt.unknown_corpus.response_text, 'unknown-corpus response');
  require(same(unknownResponse, {error: {code: 'invalid_candidates'}}), 'exact nonpaid unknown-corpus response');
  return {receipt, receiptBytes, expected, servingIdentity: after, completed};
}

export async function reuseSearchWorkerSmoke({receiptBytes: inputBytes, expected: inputExpected, authenticateOwner, readServingProof, now = Date.now}) {
  require(typeof authenticateOwner === 'function' && typeof readServingProof === 'function', 'authenticated evidence readers required');
  const {receipt, receiptBytes, expected, servingIdentity: after, completed} = validateSuccessfulSmokeReceipt({receiptBytes: inputBytes, expected: inputExpected});
  const anchor = await authenticateOwner(receiptBytes);
  owner(receipt, receiptBytes, anchor);
  const fresh = await readServingProof();
  require(same(after, validateServingProof(fresh)), 'fresh authenticated serving identity changed');
  const clock = now(), observed = timestamp(fresh.reconciliation.observed_at);
  require(Number.isSafeInteger(clock) && observed >= completed && clock >= observed && clock - observed <= 300000,
    'fresh post-publication serving proof required');
  return {version: 'search-worker-smoke-reuse-v1', status: 'passed_reused', receipt_sha256: byteDigest(receiptBytes),
    original_run_id: receipt.owner.run_id, authoritative_run_id: anchor.run.id,
    authoritative_state_artifact_id: anchor.artifact.id,
    authoritative_state_artifact_digest: anchor.artifact.digest, authoritative_checkpoint_sha256: anchor.checkpoint_sha256,
    authoritative_ledger_sha256: anchor.ledger_sha256,
    original_provider_requests: 3, original_charged_microusd: receipt.operations.reduce((sum, r) => sum + r.charged_microusd, 0),
    current_corpus_sha256: expected.current.corpus_sha256, previous_corpus_sha256: expected.previous.corpus_sha256,
    model_space_fingerprint: expected.current.model_space_fingerprint, previous_model_space_fingerprint: expected.previous.model_space_fingerprint,
    serving_version_id: fresh.version_id, serving_proof_sha256: digest(fresh), verified_at: new Date(clock).toISOString(),
    new_provider_calls: 0, new_native_counts: 0, new_metered_attempts: 0, new_paid_usage_microusd: 0,
    unknown_corpus_control: 'reused_exact_original_nonpaid_400'};
}
