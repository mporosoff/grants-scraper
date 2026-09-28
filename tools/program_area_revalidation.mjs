// Read-only counterpart to the production vector builder. No provider client.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import {validateAsset} from './embedding_contract.mjs';
import {makeVariantHarness} from './run_search_diagnosis.mjs';

const root = process.argv[2];
const raw = name => readFile(path.join(root, name));
const json = async name => JSON.parse(await raw(name));
const sha = value => createHash('sha256').update(value).digest('hex');
const assignment = source => JSON.parse(source.slice(source.indexOf('{'), source.lastIndexOf(';')).trim());
const sources = {};
const context = {globalThis: {}, URL, TextEncoder, TextDecoder, Uint8Array, Uint16Array, Float32Array, ArrayBuffer};
for (const name of ['assets/search-v2-config.js', 'assets/search-query.js', 'assets/search-retrieval.js',
  'assets/match-explain.js', 'assets/search-hybrid.js']) {
  sources[name] = (await raw(name)).toString();
  vm.runInNewContext(sources[name], context, {filename: name});
}
const api = context.globalThis;
const base = {sources, catalog: assignment((await raw('data/opportunities.js')).toString()),
  childCatalog: api.FUNDING_RETRIEVAL.createChildCatalog(assignment((await raw('data/subtopics.js')).toString())),
  queryApi: api.FUNDING_SEARCH_QUERY, retrievalApi: api.FUNDING_RETRIEVAL,
  explanationApi: api.FUNDING_MATCH_EXPLAIN, searchV2Config: api.FUNDING_SEARCH_V2_CONFIG};
const harness = makeVariantHarness(base, {searchV2: true});
const currentness = harness.parentEngine.score('funding research', {evidence: false});
const corpus = api.FUNDING_HYBRID_SEARCH.buildCorpus({parentCatalog: harness.parentCatalog,
  childCatalog: harness.childCatalog, currentnessRejectedIndexes: currentness.currentnessRejectedIndexes});
const manifest = await json('data/search-v2-voyage-manifest.json');
const canaries = await json('data/search-v2-voyage-canaries.json');
validateAsset(manifest, await raw('data/search-v2-voyage-vectors.f16'), canaries, {requireReusable: true});
assert.equal(manifest.corpus_sha256, sha(corpus.map(row => `${row.passage_id}\0${row.parent_id}\0${row.text}\n`).join('')));
assert.equal(manifest.passages.length, corpus.length);
for (const [index, row] of corpus.entries()) {
  const persisted = manifest.passages[index];
  for (const key of ['passage_id', 'parent_id', 'passage_kind', 'record_id']) assert.equal(persisted[key], row[key]);
  assert.equal(persisted.text_sha256, sha(row.text));
  assert.equal(persisted.vector_row, index);
}
process.stdout.write(JSON.stringify({validated: true, passages: corpus.length}) + '\n');
