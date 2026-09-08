import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, appendFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { activeDeployment, readWorkerVersionMetadata, resolveWorkerDeploymentCheckpoint,
  classifyWorkerDeployment } from './classify_worker_deployment.mjs';

const worker = 'search-voyage-proxy';
export function fingerprintFiles(files) {
  // Same canonical JSON representation as release_candidate.encoded.
  const ordered = Object.fromEntries(Object.keys(files).sort().map(path => [path, files[path]]));
  return createHash('sha256').update(`${JSON.stringify(ordered)}\n`).digest('hex');
}

export function servingFingerprint(deployments, version, readCheckpointFiles) {
  const active = activeDeployment(deployments);
  if (version?.id !== active.versionId) throw new Error('Active Search Worker version metadata mismatch');
  const messages = [version.annotations, active.deployment.annotations]
    .map(value => String(value?.['workers/message'] || ''));
  const hashes = messages.map(value => /(?:^|;\s*)input-sha256:([a-f0-9]{64})(?:;|$)/.exec(value)?.[1]).filter(Boolean);
  if (new Set(hashes).size > 1) throw new Error('Conflicting Search Worker input provenance');
  // Validate the protected-main checkpoint too, retaining PR #162 fail-closed behavior.
  const checkpoint = resolveWorkerDeploymentCheckpoint(worker, deployments, version);
  const fingerprint = hashes[0] || fingerprintFiles(readCheckpointFiles(checkpoint.baseSha));
  return { fingerprint, version_id: active.versionId, checkpoint };
}

export function decideWorker(required, serving) {
  if (!/^[a-f0-9]{64}$/.test(required) || !/^[a-f0-9]{64}$/.test(serving?.fingerprint || '') || !serving.version_id) {
    throw new Error('Verified Worker input fingerprints and serving version are required');
  }
  return { deploy_required: required !== serving.fingerprint, required_fingerprint: required, ...serving };
}

function run() {
  const [bundle, deploymentsPath, outputPath] = process.argv.slice(2);
  const manifest = JSON.parse(readFileSync(`${bundle}/candidate.json`, 'utf8'));
  const deployments = JSON.parse(readFileSync(deploymentsPath, 'utf8'));
  const { versionId } = activeDeployment(deployments);
  const version = readWorkerVersionMetadata(worker, versionId);
  const serving = servingFingerprint(deployments, version, sha => {
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
  });
  const decision = decideWorker(manifest.worker_fingerprint, serving);
  writeFileSync(outputPath, `${JSON.stringify(decision, null, 2)}\n`);
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
    `deploy_required=${decision.deploy_required}\nversion_id=${decision.version_id}\nfingerprint=${decision.required_fingerprint}\n`);
  console.log(JSON.stringify(decision));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) run();
