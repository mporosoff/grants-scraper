// The only public request here is the locked, nonpaid unknown-corpus control.
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, readdirSync, rmSync, realpathSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { reconcile } from './reconcile_search_worker_provenance.mjs';
import { VERSION, byteDigest, canonical, validateSuccessfulSmokeReceipt,
  reuseSearchWorkerSmoke, validateServingProof } from './search_worker_smoke_reuse.mjs';
import { checkpointFiles } from './search_worker_checkpoint.mjs';

export function candidateBuild(baseSha, overrides, {git = (...args) => execFileSync('git', args),
  dryRun = (config, output, cwd) => execFileSync('npx', ['--yes', 'wrangler@4.125.0', 'deploy', '--dry-run', '--config', config, '--outdir', output],
    {cwd, stdio: ['ignore', 'pipe', 'pipe'], timeout: 120000, maxBuffer: 1024 * 1024}), inputs = checkpointFiles} = {}) {
  const allowed = ['workers/search-voyage-proxy/generated/corpus-allowlist.json', 'workers/search-voyage-proxy/wrangler.jsonc'];
  if (canonical(Object.keys(overrides).sort()) !== canonical(allowed.sort()) || allowed.some(n => typeof overrides[n] !== 'string')) {
    throw new Error('Only exact authenticated candidate generated Worker inputs are permitted');
  }
  const files = inputs(baseSha), bytes = {};
  for (const name of Object.keys(files).filter(n => n !== '@toolchain')) {
    if (!name.startsWith('workers/search-voyage-proxy/') || name.split('/').includes('..')) throw new Error('Unsafe Worker input');
    bytes[name] = Object.hasOwn(overrides, name) ? Buffer.from(overrides[name]) : git('show', `${baseSha}:${name}`);
    if (!Object.hasOwn(overrides, name) && byteDigest(bytes[name]) !== files[name]) throw new Error('Protected runtime input changed');
    files[name] = byteDigest(bytes[name]);
  }
  if (allowed.some(n => !Object.hasOwn(bytes, n))) throw new Error('Incomplete candidate Worker inputs');
  const parent = realpathSync(tmpdir()), directory = mkdtempSync(path.join(parent, 'catalog-worker-proof-'));
  try {
    for (const [name, raw] of Object.entries(bytes)) {
      const target = path.join(directory, name); mkdirSync(path.dirname(target), {recursive: true}); writeFileSync(target, raw);
    }
    const configPath = path.join(directory, 'workers/search-voyage-proxy/wrangler.jsonc'), output = path.join(directory, 'build');
    dryRun(configPath, output, directory);
    const modules = {};
    for (const f of readdirSync(output, {withFileTypes: true})) {
      if (f.name === 'README.md' || f.name.endsWith('.map')) continue;
      if (!f.isFile()) throw new Error('Unsupported build output');
      modules[f.name] = byteDigest(readFileSync(path.join(output, f.name)));
    }
    return {files, built: {config: JSON.parse(readFileSync(configPath, 'utf8')), modules}};
  } finally {
    const actual = realpathSync(directory);
    if (path.dirname(actual) !== parent || !path.basename(actual).startsWith('catalog-worker-proof-')) throw new Error('Unsafe build cleanup');
    rmSync(actual, {recursive: true});
  }
}

export async function freshServingProof(original, {request, candidateInputs, buildCandidate = candidateBuild, initialCandidate = false} = {}) {
  if (!initialCandidate) validateServingProof(original);
  if (!request) {
    const account = process.env.CLOUDFLARE_ACCOUNT_ID, token = process.env.CLOUDFLARE_API_TOKEN;
    if (!account || !token) throw new Error('Existing read-only serving credentials required');
    request = async (suffix, api = 'scripts') => {
      if (!['scripts', 'workers'].includes(api)) throw new Error('Unsupported provenance API');
      const response = await fetch(`https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(account)}/workers/${api}/funding-finder-voyage-search${suffix}`,
        {headers: {Authorization: `Bearer ${token}`}, redirect: 'error', signal: AbortSignal.timeout(30000)});
      if (!response.ok) throw new Error(`Serving proof HTTP ${response.status}`);
      const value = await response.json();
      if (value.success !== true || !value.result) throw new Error('Incomplete serving proof');
      return value.result;
    };
  }
  const isCandidate = original.checkpoint.source === 'verified-candidate-serving-bytes';
  const built = isCandidate ? buildCandidate(original.checkpoint.baseSha, candidateInputs) : null;
  const result = await reconcile(original.checkpoint.baseSha, original.checkpoint.activeDeploymentId,
    original.version_id, {request, ...(built ? {inputs: () => built.files, build: () => built.built} : {})});
  if (isCandidate) {
    result.candidate = structuredClone(original.candidate);
    result.checkpoint.source = 'verified-candidate-serving-bytes';
    result.reconciliation.method = 'authenticated-candidate-serving-bytes-and-configuration';
  }
  validateServingProof(result);
  return result;
}

// Used by the authenticated refresh context producer after exact candidate
// deployment. Its artifact bytes are separate inputs, never fictitious Git
// blobs. The same full Cloudflare reconciliation runs on initial proof/reuse.
export async function candidateServingProof({candidate, deployment, version, candidateInputs}, adapters = {}) {
  const original = {candidate, version_id: version, checkpoint: {baseSha: candidate.code_sha,
    source: 'verified-candidate-serving-bytes', activeDeploymentId: deployment, activeVersionId: version}};
  return freshServingProof(original, {...adapters, candidateInputs, initialCandidate: true});
}

async function boundedText(response) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Missing unknown-corpus response body');
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const {done, value} = await reader.read(); if (done) break;
      size += value.length;
      if (size > 65536) throw new Error('Unknown-corpus response exceeds bound');
      chunks.push(Buffer.from(value));
    }
    return new TextDecoder('utf-8', {fatal: true}).decode(Buffer.concat(chunks));
  } finally { await reader.cancel(); }
}

export async function completeSmoke(draft, {readServingProof = freshServingProof, post = fetch,
  now = () => new Date().toISOString(), retain = () => {}} = {}) {
  // Validate all three real accepted responses before any public request. This
  // provisional control is never persisted or returned as execution evidence.
  const body = canonical({query: draft.inputs.query, corpus_sha256: 'f'.repeat(64),
    candidates: [draft.inputs.shared_passage]});
  const placeholder = {http_status: 400, public_body_text: body, external_http_body_sha256: byteDigest(body),
    response_text: '{"error":{"code":"invalid_candidates"}}',
    response_sha256: byteDigest('{"error":{"code":"invalid_candidates"}}'), provider_calls: 0};
  const initial = {...draft, version: VERSION, status: 'passed', completed_at: now(),
    serving_after: draft.serving_before, unknown_corpus: placeholder};
  validateSuccessfulSmokeReceipt({receiptBytes: Buffer.from(canonical(initial)), expected: draft.inputs});
  const before = await readServingProof(draft.serving_before);
  const check = {...initial, serving_after: before, completed_at: now()};
  validateSuccessfulSmokeReceipt({receiptBytes: Buffer.from(canonical(check)), expected: draft.inputs});
  const evidence = {serving_before: before, public_body_text: body,
    external_http_body_sha256: byteDigest(body), status: 'before_nonpaid_probe'};
  retain(structuredClone(evidence));
  try {
    const response = await post(draft.inputs.worker_origin + '/rerank', {method: 'POST', body,
      headers: {'Content-Type': 'application/json', Accept: 'application/json', Origin: 'https://mporosoff.github.io',
        'User-Agent': 'FundingFinder-CatalogSmokeReceipt/1.0 (+https://github.com/mporosoff/grants-scraper)'},
      redirect: 'error', signal: AbortSignal.timeout(30000)});
    evidence.http_status = response.status;
    evidence.response_text = await boundedText(response);
    evidence.response_sha256 = byteDigest(evidence.response_text);
    evidence.status = 'nonpaid_probe_returned'; retain(structuredClone(evidence));
    if (response.status !== 400 || canonical(JSON.parse(evidence.response_text)) !== canonical({error: {code: 'invalid_candidates'}})) {
      throw new Error('Expected exact nonpaid unknown-corpus rejection');
    }
    const after = await readServingProof(before);
    const receipt = {...initial, completed_at: now(), serving_before: before, serving_after: after,
      unknown_corpus: {...placeholder, response_text: evidence.response_text, response_sha256: evidence.response_sha256}};
    validateSuccessfulSmokeReceipt({receiptBytes: Buffer.from(canonical(receipt)), expected: draft.inputs});
    return receipt;
  } catch (error) {
    evidence.status = 'failed'; evidence.error = error.message; retain(structuredClone(evidence)); throw error;
  }
}

async function main() {
  const [action] = process.argv.slice(2);
  const value = JSON.parse(readFileSync(0, 'utf8'));
  if (action === 'proof') return freshServingProof(value.proof, {candidateInputs: value.candidate_inputs});
  if (action === 'candidate-proof') return candidateServingProof(value);
  if (action === 'same-proof') {
    if (canonical(validateServingProof(value.before)) !== canonical(validateServingProof(value.after))) throw new Error('Serving evidence changed');
    return {status: 'passed'};
  }
  if (action === 'validate') {
    validateSuccessfulSmokeReceipt({receiptBytes: Buffer.from(value.receipt_text), expected: value.expected});
    return {status: 'passed', receipt_sha256: byteDigest(value.receipt_text)};
  }
  if (action === 'complete') {
    // JSON-line diagnostics are flushed to the parent process before the next
    // boundary; the parent durably retains them under the existing owner.
    return completeSmoke(value.draft, {readServingProof: proof => freshServingProof(proof, {candidateInputs: value.candidate_inputs}),
      retain: evidence => process.stdout.write(JSON.stringify({evidence}) + '\n')});
  }
  if (action === 'reuse') {
    return reuseSearchWorkerSmoke({receiptBytes: Buffer.from(value.receipt_text), expected: value.expected,
      authenticateOwner: async () => value.anchor,
      readServingProof: () => freshServingProof(value.serving_proof, {candidateInputs: value.candidate_inputs})});
  }
  throw new Error('Unsupported catalog smoke receipt command');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then(result => process.stdout.write(JSON.stringify({result}) + '\n'))
    .catch(error => {process.stderr.write(error.message + '\n'); process.exitCode = 1;});
}
