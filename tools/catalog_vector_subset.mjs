// A fixed withdrawal from the authenticated attempt-4 corpus, never a new
// embedding generation. No request client, credentials, or vector builder.
import {readFile, access, mkdir} from 'node:fs/promises';
import {resolve, dirname, join, relative, isAbsolute, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';
import {digest, manifestDigest, validateAsset} from './embedding_contract.mjs';
import {buildAllowlist} from './build_search_release_package.mjs';
import {withBuildLock, writeCoherentFiles} from './coherent_files.mjs';

export const VERSION = 'catalog-terminal-record-subset-20261008-v1';
export const REMOVED_PARENTS = Object.freeze(['eere-exchange:DE-TA1-0003589',
  'vpr-email:NSF26-510', 'vpr-email:NSF26-512', 'vpr-email:26-514',
  'vpr-email:vpr-e4cc1ac2aa40787d', 'vpr-email:NSF25-544']);
export const PARENT_CANDIDATE = '5801e4912b642ad70e4383b0f805adc95aad7d892b85f8b7638aeca958da85e6';
const PARENT_MANIFEST_SHA = '13c34c94b4ca1fc76d67e07ee0271cdcfccd392b45f6d66786abf02d5215dee2';
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
const require = (ok, reason) => { if (!ok) throw Error('catalog_vector_subset_' + reason); };
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

/** Project only already-authenticated rows; false reuse permission stays false. */
export function projectSubset({originalCorpus, corpus, manifest, binary, canaries}) {
  validateAsset(manifest, binary, canaries, {requireReusable:true});
  require(manifest.reuse_permitted === false, 'fixed_nonreusable_parent');
  checkCorpus(originalCorpus, manifest);
  const removed = new Set(REMOVED_PARENTS);
  require(REMOVED_PARENTS.every(id => originalCorpus.some(row => row.passage_id === 'parent:' + id)),
    'all_withdrawn_parents_present');
  const retained = originalCorpus.filter(row => !removed.has(row.parent_id));
  // Full passage objects include title, field labels, values, and exact input
  // text. A changed passage is never authorized by a merely matching ID.
  require(same(corpus, retained), 'exact_ordered_corpus_subset');
  const removedRows = manifest.passages.filter(row => removed.has(row.parent_id));
  require(removedRows.length === REMOVED_PARENTS.length && removedRows.every(row => row.passage_kind === 'parent'),
    'fixed_parent_rows_without_children');
  const priorRows = manifest.passages.filter(row => !removed.has(row.parent_id));
  const width = manifest.dimension * 2;
  const projectedBinary = Buffer.concat(priorRows.map(row => binary.subarray(row.vector_row * width, (row.vector_row + 1) * width)));
  const projectedManifest = {...manifest,
    passage_count:corpus.length,
    parent_passage_count:corpus.filter(row => row.passage_kind === 'parent').length,
    child_passage_count:corpus.filter(row => row.passage_kind === 'publication_eligible_child').length,
    corpus_sha256:corpusHash(corpus), vector_sha256:digest(projectedBinary), vector_bytes:projectedBinary.length,
    passages:priorRows.map((row, vector_row) => ({...row, vector_row}))};
  projectedManifest.integrity_sha256 = manifestDigest(projectedManifest);
  validateAsset(projectedManifest, projectedBinary, canaries, {requireReusable:true});
  return {manifest:projectedManifest, binary:projectedBinary,
    removed_rows:removedRows.map(row => ({...row, vector_sha256:digest(binary.subarray(row.vector_row * width, (row.vector_row + 1) * width))})),
    retained_rows:priorRows.map((row, vector_row) => ({passage_id:row.passage_id,
      parent_vector_row:row.vector_row, vector_row,
      vector_sha256:digest(binary.subarray(row.vector_row * width, (row.vector_row + 1) * width))}))};
}

/** Keep the real published predecessor, never the unpublished withdrawn parent. */
export function projectCompatibility(manifest, existing, parentRelease) {
  const previous = existing?.previous;
  require(previous && parentRelease.previous_corpus_sha256 === previous.corpus_sha256, 'published_previous');
  const published = {schema_version:1, model:previous.model, dimension:previous.dimension,
    current_corpus_sha256:previous.corpus_sha256, model_space_fingerprint:previous.model_space_fingerprint};
  const allowlist = buildAllowlist(manifest, existing, null, published);
  require(same(allowlist.previous, previous), 'unchanged_published_previous');
  return allowlist;
}

function assignment(raw) {
  const text = raw.toString('utf8');
  return JSON.parse(text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1));
}

function makeCorpus(catalog, subtopics, sources) {
  const context = {globalThis:{}};
  for (const name of RUNTIME) vm.runInNewContext(sources[name].toString('utf8'), context, {filename:name});
  const api = context.globalThis;
  const children = api.FUNDING_RETRIEVAL.createChildCatalog(subtopics);
  const engine = api.FUNDING_RETRIEVAL.create(catalog, api.FUNDING_SEARCH_QUERY,
    {searchV2:true, searchV2Config:api.FUNDING_SEARCH_V2_CONFIG, catalogRole:'parent'});
  return api.FUNDING_HYBRID_SEARCH.buildCorpus({parentCatalog:catalog, childCatalog:children,
    currentnessRejectedIndexes:engine.score('funding research', {evidence:false}).currentnessRejectedIndexes});
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
  const unchanged = [...RUNTIME, SUBTOPICS, CANARIES, BUILD_RECEIPT];
  for (const name of unchanged) require((await readFile(checked(root, name))).equals(originals[name]), 'unchanged_projection_input');
  for (const name of [MANIFEST, BINARY, ALLOWLIST, RELEASE])
    require((await readFile(checked(root, name))).equals(originals[name]), 'original_projection_destination');
  const beforeCatalog = assignment(originals[CATALOG]);
  const afterCatalog = assignment(await readFile(checked(root, CATALOG)));
  const removed = new Set(REMOVED_PARENTS);
  require(REMOVED_PARENTS.every(id => beforeCatalog.opportunities.filter(row => row.opportunity_id === id).length === 1), 'fixed_catalog_parents');
  require(same(afterCatalog.opportunities.map(row => row.opportunity_id),
    beforeCatalog.opportunities.filter(row => !removed.has(row.opportunity_id)).map(row => row.opportunity_id)),
    'catalog_withdrawal_membership');
  const subtopics = assignment(originals[SUBTOPICS]);
  const originalCorpus = makeCorpus(beforeCatalog, subtopics, originals);
  const corpus = makeCorpus(afterCatalog, subtopics, originals);
  const sourceManifest = JSON.parse(originals[MANIFEST]);
  const projection = projectSubset({originalCorpus, corpus, manifest:sourceManifest,
    binary:originals[BINARY], canaries:JSON.parse(originals[CANARIES])});
  const parentRelease = JSON.parse(originals[RELEASE]);
  const allowlist = projectCompatibility(projection.manifest, JSON.parse(originals[ALLOWLIST]), parentRelease);
  const allowlistBytes = bytes(allowlist);
  const output = new Map([[BINARY, projection.binary], [MANIFEST, bytes(projection.manifest)], [ALLOWLIST, allowlistBytes]]);
  const sourceHashes = {};
  for (const name of Object.keys(parentRelease.source_hashes))
    sourceHashes[name] = digest(output.get(name) || await readFile(checked(root, name)));
  const release = {...parentRelease, current_corpus_sha256:projection.manifest.corpus_sha256,
    vector_sha256:projection.manifest.vector_sha256, passage_count:projection.manifest.passage_count,
    worker_allowlist_sha256:digest(allowlistBytes), source_hashes:sourceHashes};
  output.set(RELEASE, bytes(release));
  const accounting = JSON.parse(originals[BUILD_RECEIPT]);
  require(accounting.API_request_count === 6 && accounting.usage_total_tokens === 298906
    && accounting.estimated_cost_at_published_paid_pricing_usd === 0.005978
    && accounting.reuse_reason === 'homogeneous_unstable_identity' && accounting.reuse_permitted === false,
    'original_generation_accounting');
  const proof = {version:VERSION, parent_candidate_id:PARENT_CANDIDATE, parent_manifest_sha256:PARENT_MANIFEST_SHA,
    parent_corpus_sha256:sourceManifest.corpus_sha256, corpus_sha256:projection.manifest.corpus_sha256,
    parent_vector_sha256:sourceManifest.vector_sha256, vector_sha256:projection.manifest.vector_sha256,
    removed_parent_ids:[...REMOVED_PARENTS], removed_rows:projection.removed_rows, retained_rows:projection.retained_rows,
    retained_passage_count:corpus.length, reuse_permitted:false,
    model_space_fingerprint:sourceManifest.model_space_fingerprint,
    original_vector_build:{path:BUILD_RECEIPT, sha256:digest(originals[BUILD_RECEIPT]),
      API_request_count:accounting.API_request_count, usage_total_tokens:accounting.usage_total_tokens,
      estimated_cost_at_published_paid_pricing_usd:accounting.estimated_cost_at_published_paid_pricing_usd},
    canaries:{path:CANARIES, sha256:digest(originals[CANARIES])},
    previous_corpus_sha256:allowlist.previous.corpus_sha256,
    new_provider_requests:0, new_native_counts:0, new_embedded_passages:0, new_cost_usd:0,
    projected_input_hashes:{[CATALOG]:sourceHashes[CATALOG], 'data/catalog-metadata.js':sourceHashes['data/catalog-metadata.js']},
    unchanged_input_hashes:Object.fromEntries(unchanged.map(name => [name, digest(originals[name])])),
    changed_files:Object.fromEntries([...output].map(([name, raw]) => [name, {before:digest(originals[name]), after:digest(raw)}]))};
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
  try { await access(receipt); throw Error('catalog_vector_subset_existing_receipt'); }
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
