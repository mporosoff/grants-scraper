import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, appendFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { activeDeployment, readWorkerVersionMetadata, resolveWorkerDeploymentCheckpoint,
  classifyWorkerDeployment } from './classify_worker_deployment.mjs';

const worker = 'search-voyage-proxy';
export function fingerprintFiles(files) {
  // Same canonical JSON representation as release_candidate.encoded.
  const ordered = Object.fromEntries(Object.keys(files).sort().map(path => [path, files[path]]));
  return createHash('sha256').update(`${JSON.stringify(ordered)}\n`).digest('hex');
}

export function servingFingerprint(deployments, version, readCheckpointFiles, reconcileUnannotated) {
  const active = activeDeployment(deployments);
  if (version?.id !== active.versionId) throw new Error('Active Search Worker version metadata mismatch');
  const messages = [version.annotations, active.deployment.annotations]
    .map(value => String(value?.['workers/message'] || ''));
  const hashes = messages.map(value => {
    if (value.includes('protected-main:') && (!/^protected-main:[a-f0-9]{40}(?:;|$)/.test(value)
        || value.split('protected-main:').length !== 2)) throw new Error('Malformed Search Worker Git provenance');
    if (!value.includes('input-sha256:')) return null;
    const match = /(?:^|;\s*)input-sha256:([a-f0-9]{64})(?:;|$)/.exec(value);
    if (!match || value.split('input-sha256:').length !== 2) throw new Error('Malformed Search Worker input provenance');
    return match[1];
  }).filter(Boolean);
  if (new Set(hashes).size > 1) throw new Error('Conflicting Search Worker input provenance');
  // Validate the protected-main checkpoint too, retaining PR #162 fail-closed behavior.
  let checkpoint;
  try {
    checkpoint = resolveWorkerDeploymentCheckpoint(worker, deployments, version);
  } catch (error) {
    if (error.message === 'Active Worker has no verified Git checkpoint; publication is blocked.' && reconcileUnannotated) {
      const verified = reconcileUnannotated(active.deployment.id, active.versionId);
      if (hashes[0] && hashes[0] !== verified.fingerprint) throw new Error('Conflicting Search Worker input provenance');
      return verified;
    }
    throw error;
  }
  const fingerprint = hashes[0] || fingerprintFiles(readCheckpointFiles(checkpoint.baseSha));
  return { fingerprint, version_id: active.versionId, checkpoint };
}

export function decideWorker(required, serving) {
  if (!/^[a-f0-9]{64}$/.test(required) || !/^[a-f0-9]{64}$/.test(serving?.fingerprint || '') || !serving.version_id) {
    throw new Error('Verified Worker input fingerprints and serving version are required');
  }
  return { deploy_required: required !== serving.fingerprint, required_fingerprint: required, ...serving };
}

export function checkpointFiles(sha) {
    const names = execFileSync('git', ['ls-tree', '-r', '--name-only', sha], { encoding: 'utf8' }).trim().split('\n');
    const inputs = classifyWorkerDeployment(worker, names).deploymentInputs;
    if (!inputs.includes('workers/search-voyage-proxy/generated/corpus-allowlist.json') || inputs.length < 3) {
      throw new Error('Incomplete serving Worker checkpoint inputs');
    }
    const files = Object.fromEntries(inputs.map(path => [path,
      createHash('sha256').update(execFileSync('git', ['show', `${sha}:${path}`])).digest('hex')]));
    const workflow = execFileSync('git', ['show', `${sha}:.github/workflows/refresh-opportunities.yml`], {encoding:'utf8'});
    const versions = [...new Set([...workflow.matchAll(/npx --yes wrangler@([0-9.]+) deploy/g)].map(match => match[1]))];
    if (versions.length !== 1) throw new Error('Serving deployment toolchain cannot be verified');
    files['@toolchain'] = createHash('sha256').update(`${JSON.stringify({wrangler:versions[0]})}\n`).digest('hex');
    return files;
}

export function verifyServingIdentity(required, expected, serving) {
  const validReconciliation = state => state.checkpoint.source !== 'verified-serving-bytes' || (
    state.reconciliation?.method === 'authenticated-serving-bytes-and-configuration'
    && state.reconciliation.protected_input_sha === state.checkpoint.baseSha
    && state.reconciliation.input_hashes && fingerprintFiles(state.reconciliation.input_hashes) === state.fingerprint
    && /^[a-f0-9]{64}$/.test(state.reconciliation.configuration_fingerprint || '')
    && Object.keys(state.reconciliation.module_hashes || {}).length > 0);
  const valid = state => state && /^[a-f0-9]{64}$/.test(state.fingerprint || '')
    && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(state.version_id || '')
    && /^[a-f0-9]{40}$/.test(state.checkpoint?.baseSha || '')
    && !/^0{40}$/.test(state.checkpoint.baseSha)
    && state.checkpoint.activeVersionId === state.version_id
    && typeof state.checkpoint.activeDeploymentId === 'string' && state.checkpoint.activeDeploymentId.length > 0
    && ['active-version-message', 'active-deployment-message', 'verified-serving-bytes'].includes(state.checkpoint.source)
    && validReconciliation(state);
  if (!valid(expected) || !valid(serving) || expected.deploy_required !== false
      || expected.required_fingerprint !== required || expected.fingerprint !== required) {
    throw new Error('Missing or malformed verified publication Worker checkpoint');
  }
  if (serving.fingerprint !== required || serving.version_id !== expected.version_id
      || serving.checkpoint.baseSha !== expected.checkpoint.baseSha) {
    throw new Error('Active Search Worker differs from the publication version/input checkpoint');
  }
  return { ...serving, required_fingerprint: required, expected_version_id: expected.version_id,
    verified: true, verified_at: new Date().toISOString() };
}

function readDeployments() {
  try {
    return JSON.parse(execFileSync('npx', ['--yes', 'wrangler@4.125.0', 'deployments', 'list',
      '--config', `workers/${worker}/wrangler.jsonc`, '--json'], {
      encoding: 'utf8', timeout: 60_000, maxBuffer: 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'],
    }));
  } catch {
    throw new Error('Unable to read active Search Worker deployments; verification is blocked');
  }
}

export function readLiveServing({ deployments = readDeployments,
  version = id => readWorkerVersionMetadata(worker, id), files = checkpointFiles, reconcileUnannotated } = {}) {
  const before = deployments();
  const active = activeDeployment(before);
  const metadata = version(active.versionId);
  const after = deployments();
  const current = activeDeployment(after);
  if (current.versionId !== active.versionId || current.deployment.id !== active.deployment.id) {
    throw new Error('Active Search Worker changed while reading deployment provenance');
  }
  return servingFingerprint(after, metadata, files, reconcileUnannotated);
}

function reconciliationReader(baseSha) {
  return (deploymentId, versionId) => {
    try {
      return JSON.parse(execFileSync(process.execPath, [fileURLToPath(new URL('./reconcile_search_worker_provenance.mjs', import.meta.url)),
        baseSha, deploymentId, versionId], {encoding:'utf8', timeout:300_000, maxBuffer:1024*1024, stdio:['ignore','pipe','pipe']}));
    } catch (error) {
      throw new Error(`Serving inputs could not be verified: ${String(error.stderr || 'reconciliation unavailable').trim().slice(0, 400)}`);
    }
  };
}

function run() {
  const args = process.argv.slice(2);
  if (args[0] === '--verify-live') {
    const [, bundle, expectedPath, outputPath] = args;
    try {
      const manifest = JSON.parse(readFileSync(`${bundle}/candidate.json`, 'utf8'));
      const expected = JSON.parse(readFileSync(expectedPath, 'utf8'));
      const result = verifyServingIdentity(manifest.worker_fingerprint, expected, readLiveServing({
        reconcileUnannotated:reconciliationReader(expected.checkpoint?.baseSha)}));
      writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
      console.log(JSON.stringify(result));
    } catch (error) {
      writeFileSync(outputPath, `${JSON.stringify({verified:false, error:error.message})}\n`);
      process.exitCode = 1;
    }
    return;
  }
  const [bundle, deploymentsPath, outputPath] = args;
  const manifest = JSON.parse(readFileSync(`${bundle}/candidate.json`, 'utf8'));
  const deployments = JSON.parse(readFileSync(deploymentsPath, 'utf8'));
  const { versionId } = activeDeployment(deployments);
  const version = readWorkerVersionMetadata(worker, versionId);
  let serving;
  try {
    serving = servingFingerprint(deployments, version, checkpointFiles,
      reconciliationReader(execFileSync('git', ['rev-parse', 'HEAD'], {encoding:'utf8'}).trim()));
  } catch (error) {
    writeFileSync(outputPath, `${JSON.stringify({verified:false, candidate_id:manifest.candidate_id,
      active_version:version, active_deployment:activeDeployment(deployments).deployment,
      error:error.message}, null, 2)}\n`);
    throw error;
  }
  const decision = decideWorker(manifest.worker_fingerprint, serving);
  writeFileSync(outputPath, `${JSON.stringify(decision, null, 2)}\n`);
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
    `deploy_required=${decision.deploy_required}\nversion_id=${decision.version_id}\nfingerprint=${decision.required_fingerprint}\n`);
  console.log(JSON.stringify(decision));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) run();
