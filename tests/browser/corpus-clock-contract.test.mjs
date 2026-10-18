import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { makeVariantHarness } from "../../tools/run_search_diagnosis.mjs";
import { corpusDateClass } from "../../tools/corpus_clock.mjs";
import { buildCatalog } from "./search-fixture-helpers.mjs";

const root = new URL("../../", import.meta.url);
const paths = ["assets/search-v2-config.js", "assets/search-query.js", "assets/search-retrieval.js",
  "assets/match-explain.js", "assets/search-hybrid.js"];
const sources = await Promise.all(paths.map(path => readFile(new URL(path, root), "utf8")));
// Public Grants.gov record 336244, captured from the Oct 16 catalog. Its real
// five-year undated cutoff is Nov 7; this fixture does not require a live ID.
const record = JSON.parse(await readFile(new URL("tests/fixtures/frozen/undated-corpus-boundary.json", root), "utf8"));
const FRAME = "2026-11-06T12:00:00Z";

function harnessAt(now, generatedAt = FRAME) {
  const context = { Date: corpusDateClass(now), TextEncoder, Uint8Array, Uint16Array, Float32Array,
    ArrayBuffer, URL, setTimeout, clearTimeout, AbortController, globalThis: { crypto: webcrypto } };
  sources.forEach((source, index) => vm.runInNewContext(source, context, { filename: paths[index] }));
  const apis = context.globalThis;
  const catalog = buildCatalog([record], apis.FUNDING_SEARCH_QUERY, { generatedAt });
  const base = { catalog, childCatalog: buildCatalog([], apis.FUNDING_SEARCH_QUERY, { schemaVersion: 1, generatedAt }), queryApi: apis.FUNDING_SEARCH_QUERY,
    retrievalApi: apis.FUNDING_RETRIEVAL, searchV2Config: apis.FUNDING_SEARCH_V2_CONFIG };
  return { ...makeVariantHarness(base, { searchV2: true }), hybrid: apis.FUNDING_HYBRID_SEARCH };
}

function corpus(harness) {
  return harness.hybrid.buildCorpus({ parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    currentnessRejectedIndexes: harness.parentEngine.corpusCurrentness().currentnessRejectedIndexes });
}

test("the actual undated cutoff changes runtime admission without changing immutable corpus rows", () => {
  const before = harnessAt(FRAME), after = harnessAt("2026-11-07T12:00:00Z");
  assert.deepEqual(Array.from(before.parentEngine.score("funding research").currentnessRejectedIndexes), []);
  assert.deepEqual(Array.from(after.parentEngine.score("funding research").currentnessRejectedIndexes), [0]);
  const first = JSON.parse(JSON.stringify(corpus(before))), second = JSON.parse(JSON.stringify(corpus(after)));
  assert.equal(first[0].passage_id, "parent:336244");
  assert.deepEqual(second, first);
  assert.equal(corpus(harnessAt("2026-11-08T12:00:00Z", "2026-11-07T12:00:00Z")).length, 0);
});

test("browser assets remain loadable after the cutoff while query expiry remains active", async () => {
  const before = harnessAt(FRAME), after = harnessAt("2026-11-07T12:00:00Z");
  const rows = corpus(before), binary = Buffer.alloc(2048);
  for (let offset = 0; offset < binary.length; offset += 2) binary.writeUInt16LE(0x3c00, offset);
  const sha = input => createHash("sha256").update(input).digest("hex");
  const manifest = { schema_version: 1, model: "voyage-4-lite", dimension: 1024, dtype: "float16-le",
    model_space_fingerprint: "a".repeat(64), model_space: { canary_set_version: 1, canary_count: 6 },
    passage_count: rows.length, corpus_sha256: await before.hybrid.corpusHash(rows), vector_sha256: sha(binary),
    passages: rows.map(row => ({ passage_id: row.passage_id, text_sha256: sha(row.text) })) };
  const requested = [];
  const client = after.hybrid.createClient({ parentCatalog: after.parentCatalog, childCatalog: after.childCatalog,
    parentEngine: after.parentEngine, childEngine: after.childEngine, manifestUrl: "/manifest", vectorUrl: "/vectors",
    fetchImpl: async url => {
      requested.push(String(url));
      if (String(url) === "/manifest") return new Response(JSON.stringify(manifest));
      assert.equal(String(url), "/vectors?v=" + manifest.vector_sha256);
      return new Response(binary);
    } });
  const loaded = await client.loadAssets();
  assert.equal(loaded.manifest.corpus_sha256, manifest.corpus_sha256);
  assert.equal(loaded.corpus[0].passage_id, "parent:336244");
  assert.equal(requested.length, 2);
  assert.deepEqual(Array.from(after.parentEngine.score("funding research").currentnessRejectedIndexes), [0]);
});

test("missing or invalid corpus timestamps fail closed instead of using the test or browser clock", () => {
  for (const stamp of [undefined, "", "not-a-date", "2026-11-06", "2026-13-06T12:00:00Z"]) {
    const harness = harnessAt(FRAME);
    harness.parentCatalog.generated_at = stamp;
    assert.throws(() => harness.parentEngine.corpusCurrentness(), /valid generated_at timestamp/);
    assert.throws(() => corpusDateClass(stamp), /valid authenticated corpus timestamp/);
  }
});

test("archived runtime fallback evaluates Date.now at its authenticated frame", () => {
  const DateAtFrame = corpusDateClass(FRAME);
  const legacy = vm.runInNewContext("({ now: () => Date.now(), date: () => new Date().toISOString() })", { Date: DateAtFrame });
  assert.equal(legacy.now(), Date.parse(FRAME));
  assert.equal(legacy.date(), "2026-11-06T12:00:00.000Z");
});
