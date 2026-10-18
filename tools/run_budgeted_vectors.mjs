// Ordinary generation keeps the production builder and the existing logical
// allowance; the same private response bridge also serves explicit repairs.
import {createHash} from 'node:crypto';
import {execFileSync, spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath, pathToFileURL} from 'node:url';
import vm from 'node:vm';
import {loadHarness, makeVariantHarness} from './run_search_diagnosis.mjs';
import {configuration, validateAsset} from './embedding_contract.mjs';
import {withBuildLock, writeCoherentFiles} from './coherent_files.mjs';

const root = new URL('../', import.meta.url);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const outputNames = ['data/search-v2-voyage-vectors.f16', 'data/search-v2-voyage-canaries.json',
  'evaluation/search_v2_hybrid_vector_build.json', 'data/search-v2-voyage-manifest.json'];

export function validateCorpusAsset(manifest, binary, canaries, corpus, corpusSha, configSha) {
  validateAsset(manifest, binary, canaries);
  if (manifest.configuration_sha256 !== configSha || manifest.corpus_sha256 !== corpusSha
    || manifest.passages.length !== corpus.length || manifest.passages.some((row, i) =>
      ['passage_id', 'parent_id', 'record_id', 'passage_kind'].some(key => row[key] !== corpus[i][key])
      || row.vector_row !== i || row.text_sha256 !== digest(corpus[i].text))) {
    throw Error('budgeted_vectors_completed_corpus_mismatch');
  }
  return true;
}

export async function restoreCompletedAsset(prepared, target, corpus, corpusSha, configSha) {
  if (prepared.status !== 'restore' || JSON.stringify(Object.keys(prepared.outputs).sort()) !== JSON.stringify([...outputNames].sort())
    || JSON.stringify(Object.keys(prepared.blobs).sort()) !== JSON.stringify([...outputNames].sort())) {
    throw Error('budgeted_vectors_restore_inventory');
  }
  const raw = Object.fromEntries(outputNames.map(name => [name, readFileSync(prepared.blobs[name])]));
  if (outputNames.some(name => digest(raw[name]) !== prepared.outputs[name])) throw Error('budgeted_vectors_restore_hash');
  validateCorpusAsset(JSON.parse(raw['data/search-v2-voyage-manifest.json']), raw['data/search-v2-voyage-vectors.f16'],
    JSON.parse(raw['data/search-v2-voyage-canaries.json']), corpus, corpusSha, configSha);
  await withBuildLock(new URL('.cache/', target), () => writeCoherentFiles(outputNames.map(name => [new URL(name, target), raw[name]])));
}

async function main() {
const args = process.argv.slice(2);
if (JSON.stringify(args) !== JSON.stringify(['--production', '--write'])) throw Error('budgeted_vectors_exact_production_command');
const generation = process.env.CATALOG_VECTOR_OPERATION !== 'reconciliation';
const state = generation ? process.env.OFFLINE_AI_STATE : process.env.CATALOG_RECONCILE_STATE;
if (!state) throw Error('budgeted_vectors_existing_state_required');
const inputs = ['tools/run_budgeted_vectors.mjs', 'tools/catalog_reconcile_vectors.mjs', 'tools/catalog_reconcile_spend.py',
  'tools/offline_spend.py', 'tools/build_search_v2_voyage_vectors.mjs', 'tools/embedding_contract.mjs',
  'tools/coherent_files.mjs',
  'tools/run_search_diagnosis.mjs', 'assets/search-hybrid.js', 'assets/search-retrieval.js',
  'assets/search-query.js', 'assets/search-v2-config.js', 'assets/match-explain.js',
  'config/offline_ai.json', 'data/opportunities.js', 'data/subtopics.js'];
const read = name => readFileSync(new URL(name, root));
const sourceHashes = Object.fromEntries(inputs.map(name => [name, digest(read(name))]));
const context = {globalThis: {}, URL, TextEncoder, Uint8Array, Uint16Array, Float32Array, ArrayBuffer};
vm.runInNewContext(read('assets/search-hybrid.js').toString(), context);
const api = context.globalThis.FUNDING_HYBRID_SEARCH;
const base = await loadHarness(), harness = makeVariantHarness(base, {searchV2:true});
const corpus = api.buildCorpus({parentCatalog:harness.parentCatalog, childCatalog:harness.childCatalog,
  currentnessRejectedIndexes:harness.parentEngine.corpusCurrentness().currentnessRejectedIndexes});
const corpusSha = digest(corpus.map(row => `${row.passage_id}\0${row.parent_id}\0${row.text}\n`).join(''));
const configSha = digest(JSON.stringify(configuration(sourceHashes['assets/search-hybrid.js'])));
const checkAsset = () => validateCorpusAsset(JSON.parse(read('data/search-v2-voyage-manifest.json')),
  read('data/search-v2-voyage-vectors.f16'), JSON.parse(read('data/search-v2-voyage-canaries.json')),
  corpus, corpusSha, configSha);
let eligible = false;
try { eligible = checkAsset(); } catch { /* A changed corpus/configuration needs the ordinary bounded builder. */ }
function bridge(action, packet) {
  return JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-m', 'tools.catalog_reconcile_spend', action,
    '--state', state, ...(generation ? ['--generation'] : [])], {cwd:fileURLToPath(root), input:JSON.stringify(packet), encoding:'utf8', maxBuffer:1024 * 1024}));
}
const prepared = bridge('prepare', {run_id:process.env.GITHUB_RUN_ID, mode:process.env.TEAM_MODE,
  source_hashes:sourceHashes, corpus_sha256:corpusSha,
  configuration_sha256:configSha, passage_count:corpus.length, retained_asset_eligible:eligible});
if (prepared.status === 'restore') {
  await restoreCompletedAsset(prepared, root, corpus, corpusSha, configSha);
  checkAsset();
  bridge('checkpoint', {operation_sha256:prepared.operation_sha256, outputs:prepared.outputs, restored:true});
} else if (prepared.status !== 'complete') {
  const result = spawnSync(process.execPath, ['--import', './tools/catalog_reconcile_vectors.mjs',
    'tools/build_search_v2_voyage_vectors.mjs', ...args], {cwd:fileURLToPath(root), stdio:'inherit',
    env:{...process.env, CATALOG_VECTOR_OPERATION:generation ? 'generation' : 'reconciliation'}});
  if (result.error) throw Error('budgeted_vectors_builder_start_failed');
  if (result.status !== 0) process.exit(result.status || 1);
  checkAsset();
  const outputs = Object.fromEntries(['data/search-v2-voyage-manifest.json','data/search-v2-voyage-vectors.f16',
    'data/search-v2-voyage-canaries.json','evaluation/search_v2_hybrid_vector_build.json'].map(name => [name,digest(read(name))]));
  bridge('checkpoint', {operation_sha256:prepared.operation_sha256, outputs});
}
checkAsset();
console.log(JSON.stringify({status:'complete', operation_sha256:prepared.operation_sha256, repeated_paid_work:false}));
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) await main();
