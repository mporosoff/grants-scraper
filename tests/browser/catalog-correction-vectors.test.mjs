import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {assembleVectors, validateVectorPrefix} from '../../tools/catalog_correction_vectors.mjs';
import {validateAsset} from '../../tools/embedding_contract.mjs';

const source = await readFile(new URL('../../tools/build_search_v2_voyage_vectors.mjs', import.meta.url), 'utf8');
const canaries = vm.runInNewContext(source.match(/const MODEL_SPACE_CANARIES = Object.freeze\(([\s\S]*?)\);/)[1]);
const corpus = Array.from({length:1501}, (_, i) => ({passage_id:`parent:${i}`, parent_id:String(i),
  record_id:String(i), passage_kind:'parent', text:`Public source record ${i}`}));
const vector = Array.from({length:1024}, (_, i) => i === 0 ? 1 : 0);
function packet() {
  const responses = [];
  for (let n = 0; n < corpus.length; n += 250) {
    const texts = [...corpus.slice(n, n + 250).map(r => r.text), ...canaries.map(r => r.text)];
    responses.push({body:{input:texts}, payload:{model:'voyage-4-lite', usage:{total_tokens:100},
      data:texts.map((_, index) => ({index, embedding:vector}))}, request_id:'owned-request-' + n,
      wire_bytes:1000, response_bytes:2000, elapsed_seconds:.1});
  }
  return {corpus, previous:{manifest:{passages:[]}}, responses,
    generatedAt:'2026-09-23T19:00:00.000Z', preprocessingSha:'a'.repeat(64), sourceHashes:{}};
}

test('seven owned batches produce a complete deterministic standard asset with no request calls', async () => {
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = () => { calls++; throw Error('No provider allowed'); };
  try {
    const a = await assembleVectors(packet()), b = await assembleVectors(packet());
    for (const [name, value] of a) assert.deepEqual(value, b.get(name));
    const manifest = JSON.parse(a.get('data/search-v2-voyage-manifest.json'));
    const anchors = JSON.parse(a.get('data/search-v2-voyage-canaries.json'));
    validateAsset(manifest, a.get('data/search-v2-voyage-vectors.f16'), anchors, {requireReusable:true});
    assert.equal(manifest.passage_count, 1501);
    assert.equal(JSON.parse(a.get('evaluation/search_v2_hybrid_vector_build.json')).API_request_count, 7);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test('missing batch and changed owned text never create an incomplete generation', async () => {
  const incomplete = packet(); incomplete.responses.pop();
  await assert.rejects(assembleVectors(incomplete), /complete_owned_packet/);
  const changed = packet(); changed.responses[2].body.input[0] += ' changed';
  await assert.rejects(assembleVectors(changed), /request_order_and_texts/);
});

test('cross-batch canary discontinuity keeps the existing production rejection', async () => {
  const changed = packet();
  changed.responses[1].payload.data = changed.responses[1].payload.data.map((r, i, rows) =>
    i >= rows.length - 6 ? {...r, embedding:vector.map(x => -x)} : r);
  await assert.rejects(assembleVectors(changed), /Embedding space changed during generation/);
});

test('prefix stops only at the next missing batch after production quantization gates', async () => {
  const one = packet(); one.responses = one.responses.slice(0, 1);
  assert.deepEqual(await validateVectorPrefix(one), {accepted_prefix:1, complete:false, provider_requests:0});
  const reordered = packet(); reordered.responses = [reordered.responses[0], reordered.responses[2]];
  await assert.rejects(validateVectorPrefix(reordered), /request_order_and_texts/);
  const overflow = packet(); overflow.responses = overflow.responses.slice(0, 1);
  overflow.responses[0].payload.data[0] = {index:0, embedding:vector.map(v => v * 1e9)};
  await assert.rejects(validateVectorPrefix(overflow), /Non-finite quantized vector/);
});

test('first-prefix comparison to an actual validated previous generation rejects gross drift', async () => {
  const files = await assembleVectors(packet());
  const value = packet(); value.previous = {manifest:JSON.parse(files.get('data/search-v2-voyage-manifest.json')),
    canaries:JSON.parse(files.get('data/search-v2-voyage-canaries.json')), binary:files.get('data/search-v2-voyage-vectors.f16')};
  value.responses = value.responses.slice(0, 1);
  value.responses[0].payload.data = value.responses[0].payload.data.map((r, i, rows) =>
    i >= rows.length - 6 ? {...r, embedding:vector.map(x => -x)} : r);
  await assert.rejects(validateVectorPrefix(value), /Gross embedding-space discontinuity/);
});
