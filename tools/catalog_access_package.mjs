// Source-backed access labels may change; the full scientific corpus and all
// vector bytes must remain identical. No request client or provider credentials.
import {readFile, access, mkdir} from 'node:fs/promises';
import {resolve, dirname, join, relative, isAbsolute, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';
import {corpusDateClass} from './corpus_clock.mjs';
import {digest, validateAsset} from './embedding_contract.mjs';
import {withBuildLock, writeCoherentFiles} from './coherent_files.mjs';

export const VERSION = 'catalog-access-package-20261012-v1';
export const PARENT_CANDIDATE = 'ac68ff0aef1e4aff66c06971c1500673a46bd0c7a40f2cc0cd71c9559ea402a8';
const PARENT_MANIFEST_SHA = '4112e0b47acba26977340d31c56244e5514ae1e36c5a160e187d7ec014fc752a';
const MANIFEST = 'data/search-v2-voyage-manifest.json';
const BINARY = 'data/search-v2-voyage-vectors.f16';
const CANARIES = 'data/search-v2-voyage-canaries.json';
const BUILD_RECEIPT = 'evaluation/search_v2_hybrid_vector_build.json';
const ALLOWLIST = 'workers/search-voyage-proxy/generated/corpus-allowlist.json';
const RELEASE = 'data/search-v2-release.json';
const CATALOG = 'data/opportunities.js';
const SUBTOPICS = 'data/subtopics.js';
const RUNTIME = ['assets/search-v2-config.js', 'assets/search-query.js', 'assets/search-retrieval.js', 'assets/search-hybrid.js'];
const bytes = value => Buffer.from(JSON.stringify(value, null, 2) + '\n');
const require = (ok, reason) => { if (!ok) throw Error('catalog_access_package_' + reason); };
export const corpusHash = rows => digest(rows.map(row => `${row.passage_id}\0${row.parent_id}\0${row.text}\n`).join(''));
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

function checkCorpus(corpus, manifest) {
  require(Array.isArray(corpus) && corpus.length === manifest.passage_count
    && corpusHash(corpus) === manifest.corpus_sha256, 'parent_corpus');
  corpus.forEach((row, index) => {
    const saved = manifest.passages[index];
    require(['passage_id', 'parent_id', 'record_id', 'passage_kind'].every(key => row[key] === saved[key])
      && typeof row.text === 'string' && digest(row.text) === saved.text_sha256, 'parent_passage');
  });
}

/** An access correction must not change any scientific retrieval object. */
export function verifyCorpus({originalCorpus, corpus, manifest, binary, canaries}) {
  validateAsset(manifest, binary, canaries, {requireReusable:true});
  require(manifest.reuse_permitted === false, 'fixed_nonreusable_parent');
  checkCorpus(originalCorpus, manifest);
  require(same(corpus, originalCorpus), 'exact_ordered_corpus_identity');
}

function assignment(raw) {
  const text = raw.toString('utf8');
  return JSON.parse(text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1));
}

function makeCorpus(catalog, subtopics, sources, instant) {
  const context = {globalThis:{}, Date:corpusDateClass(instant)};
  for (const name of RUNTIME) vm.runInNewContext(sources[name].toString('utf8'), context, {filename:name});
  const api = context.globalThis;
  const children = api.FUNDING_RETRIEVAL.createChildCatalog(subtopics);
  const engine = api.FUNDING_RETRIEVAL.create(catalog, api.FUNDING_SEARCH_QUERY,
    {searchV2:true, searchV2Config:api.FUNDING_SEARCH_V2_CONFIG, catalogRole:'parent'});
  return api.FUNDING_HYBRID_SEARCH.buildCorpus({parentCatalog:catalog, childCatalog:children,
    currentnessRejectedIndexes:(engine.corpusCurrentness?.()
      || engine.score('funding research', {evidence:false})).currentnessRejectedIndexes});
}

function checked(root, name) {
  require(typeof name === 'string' && name && !name.includes('\\') && !name.includes(':')
    && !isAbsolute(name) && name.split('/').every(part => part && part !== '.' && part !== '..'), 'relative_payload_path');
  return join(root, name);
}

function within(root, path) {
  const rel = relative(root, path);
  return rel === '' || (!isAbsolute(rel) && rel !== '..' && !rel.startsWith('..' + sep));
}

/** The parent orchestrator owns source evidence, catalog edits and publication. */
export async function prepareProjection(parent, root) {
  parent = resolve(parent); root = resolve(root);
  require(!within(parent, root) && !within(root, parent), 'separate_materialized_root');
  const rawCandidate = await readFile(join(parent, '..', 'candidate.json'));
  require(digest(rawCandidate) === PARENT_MANIFEST_SHA, 'pinned_parent_manifest');
  const candidate = JSON.parse(rawCandidate);
  require(candidate.candidate_id === PARENT_CANDIDATE, 'pinned_parent_candidate');
  const originals = {};
  // Authenticate the full immutable parent, not only the selected vector rows.
  for (const [name, hash] of Object.entries(candidate.files)) {
    const raw = await readFile(checked(parent, name));
    require(digest(raw) === hash, 'parent_payload_hash');
    originals[name] = raw;
  }
  const unchanged = [...new Set([...RUNTIME, SUBTOPICS, CANARIES, BUILD_RECEIPT,
    MANIFEST, BINARY, ALLOWLIST, ...Object.keys(candidate.generation_files)
      .filter(name => /^(data|config|evaluation)\//.test(name) && ![CATALOG, 'data/catalog-metadata.js'].includes(name))])];
  for (const name of unchanged)
    require((await readFile(checked(root, name))).equals(originals[name]), 'unchanged_projection_input');
  require((await readFile(checked(root, RELEASE))).equals(originals[RELEASE]), 'original_package_destination');
  const beforeCatalog = assignment(originals[CATALOG]);
  const afterCatalog = assignment(await readFile(checked(root, CATALOG)));
  require(same(afterCatalog.opportunities.map(row => row.opportunity_id),
    beforeCatalog.opportunities.map(row => row.opportunity_id)), 'unchanged_catalog_membership');
  require(beforeCatalog.generated_at === afterCatalog.generated_at, 'original_generation_clock');
  const subtopics = assignment(originals[SUBTOPICS]);
  const manifest = JSON.parse(originals[MANIFEST]);
  const originalCorpus = makeCorpus(beforeCatalog, subtopics, originals, manifest.generated_at);
  const corpus = makeCorpus(afterCatalog, subtopics, originals, manifest.generated_at);
  verifyCorpus({originalCorpus, corpus, manifest,
    binary:originals[BINARY], canaries:JSON.parse(originals[CANARIES])});
  const parentRelease = JSON.parse(originals[RELEASE]);
  const sourceHashes = {};
  const allowed = new Set([CATALOG, 'data/catalog-metadata.js', 'match_explorer.html', 'team_match.html', 'README.md', 'PROJECT.md']);
  for (const name of Object.keys(parentRelease.source_hashes)) {
    const original = originals[name];
    require(original && digest(original) === parentRelease.source_hashes[name], 'original_package_source_hash');
    const raw = await readFile(checked(root, name));
    require(allowed.has(name) || raw.equals(original), 'unchanged_package_source');
    sourceHashes[name] = digest(raw);
  }
  const release = {...parentRelease, source_hashes:sourceHashes};
  const output = new Map([[RELEASE, bytes(release)]]);
  const accounting = JSON.parse(originals[BUILD_RECEIPT]);
  require(accounting.API_request_count === 6 && accounting.usage_total_tokens === 298906
    && accounting.estimated_cost_at_published_paid_pricing_usd === 0.005978
    && accounting.reuse_reason === 'homogeneous_unstable_identity' && accounting.reuse_permitted === false,
    'original_generation_accounting');
  const proof = {version:VERSION, parent_candidate_id:PARENT_CANDIDATE, parent_manifest_sha256:PARENT_MANIFEST_SHA,
    corpus_sha256:manifest.corpus_sha256, vector_sha256:manifest.vector_sha256,
    retained_passage_count:corpus.length, reuse_permitted:false,
    model_space_fingerprint:manifest.model_space_fingerprint,
    original_vector_build:{path:BUILD_RECEIPT, sha256:digest(originals[BUILD_RECEIPT]),
      API_request_count:accounting.API_request_count, usage_total_tokens:accounting.usage_total_tokens,
      estimated_cost_at_published_paid_pricing_usd:accounting.estimated_cost_at_published_paid_pricing_usd},
    previous_corpus_sha256:parentRelease.previous_corpus_sha256,
    new_provider_requests:0, new_native_counts:0, new_embedded_passages:0, new_cost_usd:0,
    unchanged_input_hashes:Object.fromEntries(unchanged.map(name => [name, digest(originals[name])])),
    changed_files:{[RELEASE]:{before:digest(originals[RELEASE]), after:digest(output.get(RELEASE))}},
    source_hashes:sourceHashes};
  return {output, proof};
}

async function main() {
  const args = process.argv.slice(2), options = {};
  require(args.length === 6, 'arguments');
  for (let index = 0; index < args.length; index += 2) {
    require(['--parent', '--root', '--receipt'].includes(args[index]) && !options[args[index]] && args[index + 1], 'arguments');
    options[args[index]] = resolve(args[index + 1]);
  }
  const parent = options['--parent'], root = options['--root'], receipt = options['--receipt'];
  require(parent && root && receipt, 'arguments');
  require(!within(parent, receipt) && !within(root, receipt), 'external_receipt_destination');
  try { await access(receipt); throw Error('catalog_access_package_existing_receipt'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await withBuildLock(pathToFileURL(root + '/'), async () => {
    const {output, proof} = await prepareProjection(parent, root);
    await mkdir(dirname(receipt), {recursive:true});
    const entries = [...output].map(([name, raw]) => [pathToFileURL(checked(root, name)), raw]);
    entries.push([pathToFileURL(receipt), bytes(proof)]);
    await writeCoherentFiles(entries);
    for (const [name, raw] of output) require((await readFile(checked(root, name))).equals(raw), 'written_output_hash');
    console.log(JSON.stringify({version:VERSION, modified_paths:[...output.keys()], retained_passages:proof.retained_passage_count,
      corpus_sha256:proof.corpus_sha256, vector_sha256:proof.vector_sha256, new_provider_requests:0}));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(error => {
  console.error(error.message); process.exitCode = 1;
});
