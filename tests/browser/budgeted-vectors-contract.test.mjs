import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {basename, dirname, join, resolve, sep} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import vm from 'node:vm';
import {restoreCompletedAsset, validateCorpusAsset} from '../../tools/run_budgeted_vectors.mjs';
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

async function coldCheckout(inspect) {
  const directory = await mkdtemp(join(tmpdir(), 'vector-completion-'));
  const names = ['data/search-v2-voyage-vectors.f16', 'data/search-v2-voyage-canaries.json',
    'evaluation/search_v2_hybrid_vector_build.json', 'data/search-v2-voyage-manifest.json'];
  const blobs = {}, outputs = {}, original = {};
  try {
    for (const name of names) {
      const target = join(directory, name); await mkdir(dirname(target), {recursive:true});
      const raw = read(name); original[name] = raw; outputs[name] = digest(raw);
      const blob = join(directory, outputs[name]); blobs[name] = blob; await writeFile(blob, raw);
      await writeFile(target, 'cold checkout protected predecessor');
    }
    await inspect({prepared:{status:'restore', outputs, blobs}, target:pathToFileURL(directory + sep), directory, original});
  } finally {
    assert.equal(dirname(directory), resolve(tmpdir())); assert.match(basename(directory), /^vector-completion-/);
    await rm(directory, {recursive:true, force:true});
  }
}

test('cold checkout restores all four exact completed bytes and timestamps through the coherent writer with zero HTTP', async () => {
  await coldCheckout(async ({prepared, target, directory, original}) => {
    const priorFetch = globalThis.fetch;
    globalThis.fetch = () => assert.fail('Restoring completed vectors must not reach HTTP');
    try { await restoreCompletedAsset(prepared, target, corpus, corpusSha, manifest.configuration_sha256); }
    finally { globalThis.fetch = priorFetch; }
    for (const [name, raw] of Object.entries(original)) assert.deepEqual(await readFile(join(directory, name)), raw);
    const restored = JSON.parse(await readFile(join(directory, 'data/search-v2-voyage-manifest.json')));
    assert.equal(restored.generated_at, manifest.generated_at);
  });
});

test('a corrupt blob or incompatible corpus is rejected before replacing any cold-checkout output', async () => {
  await coldCheckout(async ({prepared, target, directory, original}) => {
    await assert.rejects(restoreCompletedAsset(prepared, target, corpus, 'f'.repeat(64), manifest.configuration_sha256));
    const last = 'data/search-v2-voyage-manifest.json'; await writeFile(prepared.blobs[last], 'corrupt retained manifest');
    await assert.rejects(restoreCompletedAsset(prepared, target, corpus, corpusSha, manifest.configuration_sha256), /restore_hash/);
    for (const name of Object.keys(original)) assert.equal(await readFile(join(directory, name), 'utf8'), 'cold checkout protected predecessor');
  });
});
