// Authenticated source aliases may change; the full scientific corpus and all
// vector bytes must remain identical. No request client or provider credentials.
import {readFile, access, mkdir} from 'node:fs/promises';
import {resolve, dirname, join, relative, isAbsolute, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';
import {digest, validateAsset} from './embedding_contract.mjs';
import {withBuildLock, writeCoherentFiles} from './coherent_files.mjs';

export const VERSION = 'catalog-identity-package-20261012-v1';
export const PARENT_CANDIDATE = '75e383c2a4fe48ece7ca2e1afc4fc0a0470dfe9f3133654da9b306aefa8c41ff';
const PARENT_MANIFEST_SHA = '7c6435ad52fa90f5501ffc8edea190a0db5f529ce691fd99c78b1ccc293a0bd8';
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
const require = (ok, reason) => { if (!ok) throw Error('catalog_identity_package_' + reason); };
export const corpusHash = rows => digest(rows.map(row => `${row.passage_id}\0${row.parent_id}\0${row.text}\n`).join(''));
const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);
const POLICY = new URL('../evaluation/catalog_identity_correction_20261012.json', import.meta.url);
const URL_POLICY = new URL('../evaluation/catalog_url_correction_20261012.json', import.meta.url);
const URL_PARENT = '051d6844ea23709628b9c9209f4a947e309d2427928b0dc19e8ffb8eb8f3cfc4';
const URL_MANIFEST_SHA = 'f11c8bed90de162868348b262d6b200e2f36bb13c2601b73fbb423c5de4162c1';
const SOURCE_CACHE = 'data/source_records.json';
export function projectionProfile(kind = 'identity') {
  require(['identity', 'url'].includes(kind), 'fixed_projection_kind');
  return kind === 'url'
    ? {kind, parent:URL_PARENT, manifest:URL_MANIFEST_SHA, policy:URL_POLICY, version:'catalog-url-package-20261012-v1'}
    : {kind, parent:PARENT_CANDIDATE, manifest:PARENT_MANIFEST_SHA, policy:POLICY, version:VERSION};
}

export function verifyUrlPayload(name, before, after, policy) {
  const replacements = policy.url_replacements;
  require(Object.keys(replacements).length > 0 && Object.entries(replacements).every(([old, value]) =>
    /^https:\/\/portal\.nyserda\.ny\.gov\/CORE_Solicitation_Detail_Page\? SolicitationId=[A-Za-z0-9]{18}$/.test(old)
    && value === old.replace('? ', '?')), 'exact_url_normalization');
  const expected = structuredClone(before);
  const rows = name === CATALOG ? expected.opportunities : name === SOURCE_CACHE ? expected.sources.nyserda.records
    : name === 'feeds/changes.json' ? expected.events : null;
  require(Array.isArray(rows), 'url_payload_name');
  const changed = {};
  const ids = new Set();
  for (const row of rows) {
    const event = name === 'feeds/changes.json';
    const id = String(event ? row.id : row.opportunity_id);
    require(!ids.has(id), 'unique_payload_membership'); ids.add(id);
    const record = event ? row.record : row;
    let count = 0;
    const update = (item, key) => {
      if (item && typeof item[key] === 'string' && Object.hasOwn(replacements, item[key])) {
        item[key] = replacements[item[key]]; count += 1;
      }
    };
    update(record, 'detail_page'); update(record, 'funding_opportunity_url');
    for (const key of ['deadlines', 'contacts']) for (const item of record[key] || []) update(item, 'source_url');
    update(record.next_submission?.event, 'source_url');
    if (count) {
      require(String(record.opportunity_id || row.opportunity_id).startsWith('nyserda:'), 'nyserda_scope');
      changed[id] = count;
    }
  }
  const admitted = Object.fromEntries(Object.entries(policy.payloads[name].affected_items).map(([id, value]) => [id, value.url_leaf_count]));
  require(same(Object.entries(changed).sort(), Object.entries(admitted).sort()), 'exact_url_inventory');
  require(same(after, expected), 'exact_url_only_payload');
}


export function verifyCatalog(before, after, corrections) {
  require(corrections.length === 2 && same(corrections.map(row => row.opportunity_id).sort(), ['363829', '364039']), 'fixed_corrections');
  const expected = structuredClone(before);
  for (const correction of corrections) {
    const rows = expected.opportunities.filter(row => row.opportunity_id === correction.opportunity_id);
    require(rows.length === 1 && !rows[0].source_aliases?.length, 'original_alias_absent');
    const aliases = correction.source_aliases;
    const aliasId = correction.opportunity_id === '364039' ? 'nasa-roses:25-B.8-c9ad18a888' : 'vpr-email:vpr-a3ddeff815d159a4';
    require(aliases.length === 1 && aliases[0].opportunity_id === aliasId
      && !expected.opportunities.some(row => row.opportunity_id === aliasId
        || row.source_aliases?.some(alias => alias.opportunity_id === aliasId)), 'unique_alias_owner');
    rows[0].source_aliases = structuredClone(aliases);
  }
  require(same(after, expected), 'exact_alias_only_catalog');
}


function checkCorpus(corpus, manifest) {
  require(Array.isArray(corpus) && corpus.length === manifest.passage_count
    && corpusHash(corpus) === manifest.corpus_sha256, 'parent_corpus');
  corpus.forEach((row, index) => {
    const saved = manifest.passages[index];
    require(['passage_id', 'parent_id', 'record_id', 'passage_kind'].every(key => row[key] === saved[key])
      && typeof row.text === 'string' && digest(row.text) === saved.text_sha256, 'parent_passage');
  });
}

/** An identity correction must not change any scientific retrieval object. */
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
export async function prepareProjection(parent, root, kind = 'identity') {
  const profile = projectionProfile(kind);
  parent = resolve(parent); root = resolve(root);
  require(!within(parent, root) && !within(root, parent), 'separate_materialized_root');
  const rawCandidate = await readFile(join(parent, '..', 'candidate.json'));
  require(digest(rawCandidate) === profile.manifest, 'pinned_parent_manifest');
  const candidate = JSON.parse(rawCandidate);
  require(candidate.candidate_id === profile.parent, 'pinned_parent_candidate');
  const originals = {};
  // Authenticate the full immutable parent, not only the selected vector rows.
  for (const [name, hash] of Object.entries(candidate.files)) {
    const raw = await readFile(checked(parent, name));
    require(digest(raw) === hash, 'parent_payload_hash');
    originals[name] = raw;
  }
  const unchanged = [...new Set([...RUNTIME, SUBTOPICS, CANARIES, BUILD_RECEIPT,
    MANIFEST, BINARY, ALLOWLIST, ...Object.keys(candidate.generation_files)
      .filter(name => /^(data|config|evaluation)\//.test(name) && ![CATALOG, 'data/catalog-metadata.js', ...(kind === 'url' ? [SOURCE_CACHE] : [])].includes(name))])];
  for (const name of unchanged)
    require((await readFile(checked(root, name))).equals(originals[name]), 'unchanged_projection_input');
  require((await readFile(checked(root, RELEASE))).equals(originals[RELEASE]), 'original_package_destination');
  const beforeCatalog = assignment(originals[CATALOG]);
  const afterCatalog = assignment(await readFile(checked(root, CATALOG)));
  require(same(afterCatalog.opportunities.map(row => row.opportunity_id),
    beforeCatalog.opportunities.map(row => row.opportunity_id)), 'unchanged_catalog_membership');
  require(beforeCatalog.generated_at === afterCatalog.generated_at, 'original_generation_clock');
  const policy = JSON.parse(await readFile(profile.policy, 'utf8'));
  require(policy.candidate_id === profile.parent && policy.candidate_manifest_sha256 === profile.manifest, 'fixed_policy');
  if (kind === 'url') {
    require(policy.kind === 'url', 'fixed_policy');
    verifyUrlPayload(CATALOG, beforeCatalog, afterCatalog, policy);
    for (const name of [SOURCE_CACHE, 'feeds/changes.json'])
      verifyUrlPayload(name, JSON.parse(originals[name]), JSON.parse(await readFile(checked(root, name), 'utf8')), policy);
  } else verifyCatalog(beforeCatalog, afterCatalog, policy.corrections);
  const subtopics = assignment(originals[SUBTOPICS]);
  const originalCorpus = makeCorpus(beforeCatalog, subtopics, originals);
  const corpus = makeCorpus(afterCatalog, subtopics, originals);
  const manifest = JSON.parse(originals[MANIFEST]);
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
  require(accounting.API_request_count === 6 && accounting.usage_total_tokens === 300499
    && accounting.estimated_cost_at_published_paid_pricing_usd === 0.006010
    && accounting.reuse_reason === 'homogeneous_unstable_identity' && accounting.reuse_permitted === false,
    'original_generation_accounting');
  const proof = {version:profile.version, parent_candidate_id:profile.parent, parent_manifest_sha256:profile.manifest,
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
  require(args.length === 6 || args.length === 8, 'arguments');
  for (let index = 0; index < args.length; index += 2) {
    require(['--parent', '--root', '--receipt', '--kind'].includes(args[index]) && !options[args[index]] && args[index + 1], 'arguments');
    options[args[index]] = args[index] === '--kind' ? args[index + 1] : resolve(args[index + 1]);
  }
  const parent = options['--parent'], root = options['--root'], receipt = options['--receipt'];
  require(parent && root && receipt, 'arguments');
  const kind = options['--kind'] || 'identity';
  projectionProfile(kind);
  require(!within(parent, receipt) && !within(root, receipt), 'external_receipt_destination');
  try { await access(receipt); throw Error('catalog_identity_package_existing_receipt'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await withBuildLock(pathToFileURL(root + '/'), async () => {
    const {output, proof} = await prepareProjection(parent, root, kind);
    await mkdir(dirname(receipt), {recursive:true});
    const entries = [...output].map(([name, raw]) => [pathToFileURL(checked(root, name)), raw]);
    entries.push([pathToFileURL(receipt), bytes(proof)]);
    await writeCoherentFiles(entries);
    for (const [name, raw] of output) require((await readFile(checked(root, name))).equals(raw), 'written_output_hash');
    console.log(JSON.stringify({version:proof.version, modified_paths:[...output.keys()], retained_passages:proof.retained_passage_count,
      corpus_sha256:proof.corpus_sha256, vector_sha256:proof.vector_sha256, new_provider_requests:0}));
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(error => {
  console.error(error.message); process.exitCode = 1;
});
