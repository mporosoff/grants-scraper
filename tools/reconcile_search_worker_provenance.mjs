// Read-only reconciliation for an unannotated serving version. A Git SHA is
// evidence only after its complete built bytes and declared configuration match.
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { activeDeployment } from './classify_worker_deployment.mjs';
import { checkpointFiles, fingerprintFiles } from './search_worker_checkpoint.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const canonical = value => JSON.stringify(value, (_, v) => v && typeof v === 'object' && !Array.isArray(v)
  ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b))) : v);

function supportedConfiguration(config) {
  const supported = ['$schema', 'name', 'main', 'compatibility_date', 'workers_dev', 'vars', 'durable_objects', 'exports', 'ratelimits'];
  if (Object.keys(config).some(key => !supported.includes(key)) || config.name !== 'funding-finder-voyage-search') {
    throw new Error('Unannotated Worker has an unsupported deployment configuration; provenance cannot be reconstructed');
  }
}

export function verifyConfiguration(config, resources) {
  supportedConfiguration(config);
  const runtime = resources.script_runtime;
  const expectedRuntime = {compatibility_date:config.compatibility_date, exports:config.exports || {}, usage_model:'standard'};
  if (canonical(runtime) !== canonical(expectedRuntime)) throw new Error('Serving Worker runtime differs from protected inputs');
  const expected = Object.entries(config.vars || {}).map(([name, text]) => ({name, type:'plain_text', text}));
  for (const binding of config.durable_objects?.bindings || []) {
    expected.push({...binding, type:'durable_object_namespace'});
  }
  for (const binding of config.ratelimits || []) expected.push({...binding, type:'ratelimit'});
  expected.push({name:'VOYAGE_API_KEY', type:'secret_text'});
  const actual = (resources.bindings || []).map(binding => {
    if (binding.type === 'secret_text') {
      if (Object.keys(binding).some(key => !['name','type'].includes(key))) throw new Error('Unexpected secret binding metadata');
      return binding;
    }
    if (binding.type === 'durable_object_namespace') {
      // Namespace IDs are assigned by Cloudflare, not supplied by this config.
      // The complete local class binding still has to match (including no
      // external script/environment override). Retain the assigned ID in proof.
      if (!/^[a-f0-9]{32}$/.test(binding.namespace_id || '')) throw new Error('Missing serving Durable Object namespace');
      const {namespace_id, ...declared} = binding;
      return declared;
    }
    return binding;
  });
  const byName = (a,b) => a.name.localeCompare(b.name);
  if (canonical(actual.sort(byName)) !== canonical(expected.sort(byName))) {
    throw new Error('Serving Worker bindings differ from protected inputs');
  }
  return hash(canonical({script_runtime:runtime, bindings:resources.bindings}));
}

export function verifyModules(expected, actual) {
  if (!Object.keys(expected).length || canonical(expected) !== canonical(actual)) {
    throw new Error('Serving Worker module bytes differ from protected build inputs');
  }
}

function buildProtected(baseSha, files) {
  const parent = realpathSync(tmpdir());
  const directory = mkdtempSync(path.join(parent, 'funding-worker-proof-'));
  try {
    for (const name of Object.keys(files).filter(name => name !== '@toolchain')) {
      if (!name.startsWith('workers/search-voyage-proxy/') || name.split('/').includes('..')) throw new Error('Unsafe Worker input path');
      const target = path.join(directory, name);
      mkdirSync(path.dirname(target), {recursive:true});
      const bytes = execFileSync('git', ['show', `${baseSha}:${name}`]);
      if (hash(bytes) !== files[name]) throw new Error('Protected Worker input changed during reconstruction');
      writeFileSync(target, bytes);
    }
    const configPath = path.join(directory, 'workers/search-voyage-proxy/wrangler.jsonc');
    const config = JSON.parse(readFileSync(configPath, 'utf8'));
    supportedConfiguration(config);
    const output = path.join(directory, 'build');
    try {
      execFileSync('npx', ['--yes', 'wrangler@4.125.0', 'deploy', '--dry-run', '--config', configPath, '--outdir', output],
        {cwd:directory, stdio:['ignore','pipe','pipe'], timeout:120_000, maxBuffer:1024*1024});
    } catch {
      throw new Error('Unable to reproduce protected Worker build; no deployment was attempted');
    }
    const modules = {};
    for (const file of readdirSync(output, {withFileTypes:true})) {
      if (file.name === 'README.md' || file.name.endsWith('.map')) continue;
      if (!file.isFile()) throw new Error('Unsupported Worker build module layout');
      modules[file.name] = hash(readFileSync(path.join(output, file.name)));
    }
    return {config, modules};
  } finally {
    const resolved = realpathSync(directory);
    if (path.dirname(resolved) !== parent || !path.basename(resolved).startsWith('funding-worker-proof-')) {
      throw new Error('Unsafe temporary build cleanup path');
    }
    rmSync(resolved, {recursive:true});
  }
}

export async function reconcile(baseSha, expectedDeployment, expectedVersion, {request, build=buildProtected, inputs=checkpointFiles,
  git=(...args) => execFileSync('git', args, {encoding:'utf8'}).trim()} = {}) {
  if (!/^[a-f0-9]{40}$/.test(baseSha) || /^0{40}$/.test(baseSha)) throw new Error('A complete protected input SHA is required');
  git('merge-base', '--is-ancestor', baseSha, 'origin/main');
  const files = inputs(baseSha);
  if (files['@toolchain'] !== hash('{"wrangler":"4.125.0"}\n')) throw new Error('Unsupported protected Worker build toolchain');
  const built = build(baseSha, files);
  const before = activeDeployment((await request('/deployments')).deployments);
  if (before.versionId !== expectedVersion || before.deployment.id !== expectedDeployment) throw new Error('Serving Worker changed before reconciliation');
  const version = await request(`/versions/${expectedVersion}`);
  if (version.id !== expectedVersion) throw new Error('Serving version metadata mismatch');
  const response = await request('', true);
  const etag = response.headers.get('etag')?.replaceAll('"', '');
  if (!etag || etag !== version.resources?.script?.etag) throw new Error('Downloaded Worker is not the inspected serving version');
  const modules = {};
  for (const [name, file] of await response.formData()) {
    if (Object.hasOwn(modules, name) || name.includes('/') || name.includes('\\')) {
      throw new Error('Unsupported or ambiguous serving Worker module');
    }
    // Cloudflare returns JavaScript parts without a filename parameter; native
    // FormData exposes those UTF-8 parts as strings. Binary/file parts retain
    // their raw bytes. Either form must hash exactly to the protected build.
    modules[name] = hash(typeof file === 'string' ? Buffer.from(file, 'utf8') : Buffer.from(await file.arrayBuffer()));
  }
  verifyModules(built.modules, modules);
  const configurationFingerprint = verifyConfiguration(built.config, version.resources);
  const subdomain = await request('/subdomain');
  if (subdomain.enabled !== built.config.workers_dev) throw new Error('Serving Worker route configuration differs from protected inputs');
  const after = activeDeployment((await request('/deployments')).deployments);
  if (after.versionId !== before.versionId || after.deployment.id !== before.deployment.id) throw new Error('Serving Worker changed during reconciliation');
  return {fingerprint:fingerprintFiles(files), version_id:expectedVersion,
    checkpoint:{baseSha, source:'verified-serving-bytes', activeDeploymentId:expectedDeployment, activeVersionId:expectedVersion},
    reconciliation:{schema_version:1, observed_at:new Date().toISOString(), protected_input_sha:baseSha,
      script_etag:etag, module_hashes:modules, input_hashes:files, configuration_fingerprint:configurationFingerprint,
      method:'authenticated-serving-bytes-and-configuration', production_mutated:false}};
}

async function run() {
  const [baseSha, deployment, version] = process.argv.slice(2);
  const account = process.env.CLOUDFLARE_ACCOUNT_ID, token = process.env.CLOUDFLARE_API_TOKEN;
  if (!account || !token) throw new Error('Existing Cloudflare credentials are required for read-only provenance reconciliation');
  const prefix = `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(account)}/workers/scripts/funding-finder-voyage-search`;
  const request = async (suffix, raw=false) => {
    const response = await fetch(prefix + suffix, {headers:{Authorization:`Bearer ${token}`}, signal:AbortSignal.timeout(30_000)});
    if (!response.ok) throw new Error(`Serving provenance read failed (HTTP ${response.status})`);
    if (raw) return response;
    const value = await response.json();
    if (!value.success || !value.result) throw new Error('Serving provenance API response was incomplete');
    return value.result;
  };
  console.log(JSON.stringify(await reconcile(baseSha, deployment, version, {request})));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run().catch(error => {console.error(error.message); process.exitCode=1;});
}
