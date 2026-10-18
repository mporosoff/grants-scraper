import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {validateCorpusAsset} from '../../tools/run_budgeted_vectors.mjs';
import {loadHarness, makeVariantHarness} from '../../tools/run_search_diagnosis.mjs';

const read = path => readFileSync(new URL('../../' + path, import.meta.url));
const digest = value => createHash('sha256').update(value).digest('hex');
const manifest = JSON.parse(read('data/search-v2-voyage-manifest.json'));
const canaries = JSON.parse(read('data/search-v2-voyage-canaries.json'));
const binary = read('data/search-v2-voyage-vectors.f16');
const context = {globalThis: {}, URL, TextEncoder, Uint8Array, Uint16Array, Float32Array, ArrayBuffer};
vm.runInNewContext(read('assets/search-hybrid.js').toString(), context);
const base = await loadHarness(), harness = makeVariantHarness(base, {searchV2:true});
const corpus = context.globalThis.FUNDING_HYBRID_SEARCH.buildCorpus({parentCatalog:harness.parentCatalog,
  childCatalog:harness.childCatalog,
  currentnessRejectedIndexes:harness.parentEngine.corpusCurrentness().currentnessRejectedIndexes});
const corpusSha = digest(corpus.map(row => `${row.passage_id}\0${row.parent_id}\0${row.text}\n`).join(''));

test('intact protected corpus accepts a homogeneous asset when row mixing is prohibited', () => {
  const before = [JSON.stringify(manifest), JSON.stringify(canaries), digest(binary)];
  assert.equal(validateCorpusAsset(manifest, binary, canaries, corpus, corpusSha, manifest.configuration_sha256), true);
  assert.deepEqual([JSON.stringify(manifest), JSON.stringify(canaries), digest(binary)], before);
});

test('whole-asset retention rejects changed order, ownership, text, configuration, or corpus', () => {
  for (const mutate of [rows => rows.reverse(), rows => {rows[0].parent_id += '-changed';},
    rows => {rows[0].record_id += '-changed';}, rows => {rows[0].passage_kind += '-changed';},
    rows => {rows[0].text += ' changed';}]) {
    const rows = Array.from(corpus, row => ({...row})); mutate(rows);
    assert.throws(() => validateCorpusAsset(manifest, binary, canaries, rows, corpusSha, manifest.configuration_sha256));
  }
  assert.throws(() => validateCorpusAsset(manifest, binary, canaries, corpus, 'f'.repeat(64), manifest.configuration_sha256));
  assert.throws(() => validateCorpusAsset(manifest, binary, canaries, corpus, corpusSha, 'f'.repeat(64)));
});
