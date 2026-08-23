import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import test from "node:test";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "../../tools/run_search_diagnosis.mjs";

const root = new URL("../../", import.meta.url);
const [source, manifest, vectorBuffer, appSource, configSource, htmlSource] = await Promise.all([
  readFile(new URL("assets/search-hybrid.js", root), "utf8"),
  readFile(new URL("data/search-v2-voyage-manifest.json", root), "utf8").then(JSON.parse),
  readFile(new URL("data/search-v2-voyage-vectors.f16", root)),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("assets/app-config.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
]);

function loadApi() {
  const context = {
    AbortController,
    ArrayBuffer,
    Float32Array,
    Math,
    Map,
    Number,
    Object,
    Promise,
    RegExp,
    Response,
    Set,
    String,
    TextEncoder,
    Uint8Array,
    Uint16Array,
    URL,
    clearTimeout,
    performance,
    setTimeout,
  };
  context.globalThis = { crypto: webcrypto, location: { href: "http://localhost/" } };
  vm.runInNewContext(source, context);
  return context.globalThis.FUNDING_HYBRID_SEARCH;
}

const api = loadApi();
const base = await loadHarness();
const harness = makeVariantHarness(base, { searchV2: true });
const currentness = harness.parentEngine.score("funding research", { evidence: false });
const corpus = api.buildCorpus({
  parentCatalog: harness.parentCatalog,
  childCatalog: harness.childCatalog,
  currentnessRejectedIndexes: currentness.currentnessRejectedIndexes,
});

test("static public passage asset has an exact corpus/order/hash handshake", async () => {
  assert.equal(corpus.length, 1659);
  assert.equal(manifest.passage_count, corpus.length);
  assert.equal(await api.corpusHash(corpus), manifest.corpus_sha256);
  assert.equal(
    manifest.passages.map(item => item.passage_id).join("\n"),
    Array.from(corpus, item => item.passage_id).join("\n"),
  );
  assert.equal(
    createHash("sha256").update(vectorBuffer).digest("hex"),
    manifest.vector_sha256,
  );
  assert.equal(vectorBuffer.byteLength, corpus.length * api.EMBEDDING_DIMENSION * 2);
});

test("semantic retrieval, RRF union, acronym guard, and strongest-child rollup are generic", () => {
  const vectors = api.decodeFloat16(
    vectorBuffer.buffer.slice(vectorBuffer.byteOffset, vectorBuffer.byteOffset + vectorBuffer.byteLength),
    corpus.length,
    api.EMBEDDING_DIMENSION,
  );
  const queryVector = vectors.slice(0, api.EMBEDDING_DIMENSION);
  const semantic = api.semanticCandidates(corpus, vectors, queryVector, 3);
  assert.equal(semantic[0].passage_id, corpus[0].passage_id);

  const fused = api.fuseCandidates(
    [{ ...corpus[0], bm25f_score: 2 }, { ...corpus[1], bm25f_score: 1 }],
    [{ ...corpus[1], semantic_score: .9 }, { ...corpus[2], semantic_score: .8 }],
  );
  assert.equal(fused[0].passage_id, corpus[1].passage_id);
  assert.equal(api.deterministicSafeguard("AIM materials", { text: "advanced materials" }).allowed, false);
  assert.equal(api.deterministicSafeguard("AIM materials", { text: "we aim to study materials" }).allowed, false);
  assert.equal(api.deterministicSafeguard("AIM materials", { text: "AIM advanced materials" }).allowed, true);
  assert.equal(api.deterministicSafeguard("AIM materials intelligence", { text: "AIM maternal health" }).allowed, false);
  assert.equal(api.deterministicSafeguard(
    "AI materials",
    { text: "artificial intelligence materials" },
    new Set(["AI"]),
  ).allowed, true);

  const parents = api.strongestParents([
    { parent_id: "p", passage_id: "parent:p", voyage_score: .4 },
    { parent_id: "p", passage_id: "child:c", voyage_score: .8 },
    { parent_id: "q", passage_id: "parent:q", voyage_score: .7 },
  ]);
  assert.equal(Array.from(parents, item => item.passage_id).join(","), "child:c,parent:q");
});

test("hybrid client is lazy, rejects a stale manifest, and sends no browser credential", async () => {
  let requests = [];
  const stale = { ...manifest, corpus_sha256: "0".repeat(64) };
  const staleClient = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
    fetchImpl: async url => {
      requests.push(String(url));
      return new Response(JSON.stringify(stale), { status: 200 });
    },
  });
  assert.deepEqual(requests, []);
  await assert.rejects(staleClient.loadAssets(), error => error.code === "manifest_corpus_mismatch");
  assert.deepEqual(requests, ["/manifest"]);

  requests = [];
  const fetchImpl = async (url, options = {}) => {
    requests.push({ url: String(url), options });
    if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
    if (String(url) === "/vectors") return new Response(vectorBuffer, { status: 200 });
    if (String(url).endsWith("/embed-query")) {
      const vectors = api.decodeFloat16(
        vectorBuffer.buffer.slice(vectorBuffer.byteOffset, vectorBuffer.byteOffset + vectorBuffer.byteLength),
        corpus.length,
        api.EMBEDDING_DIMENSION,
      );
      return new Response(JSON.stringify({
        embedding: Array.from(vectors.slice(0, api.EMBEDDING_DIMENSION)),
        usage: { total_tokens: 3 },
      }), { status: 200 });
    }
    if (String(url).endsWith("/rerank")) {
      const body = JSON.parse(options.body);
      return new Response(JSON.stringify({
        rankings: body.candidates.map((item, index) => ({
          index,
          passage_id: item.passage_id,
          relevance_score: 1 - index / Math.max(1, body.candidates.length),
        })),
        usage: { total_tokens: 10 },
      }), { status: 200 });
    }
    if (String(url).endsWith("/judge")) {
      const body = JSON.parse(options.body);
      return new Response(JSON.stringify({
        model: api.JUDGE_MODEL,
        results: body.results.map((item, index) => ({
          id: item.id,
          classification: index === 0 ? "primary" : index === 1 ? "broader" : "reject",
        })),
        usage: { input_tokens: 50, output_tokens: 20, total_tokens: 70, neurons: 2 },
        latency_ms: 10,
      }), { status: 200 });
    }
    return new Response("", { status: 404 });
  };
  const client = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
    fetchImpl,
  });
  assert.deepEqual(requests, []);
  const result = await client.search("rare earth recycling");
  assert.equal(result.parents.length, 2);
  assert.deepEqual(Array.from(result.parents, item => item.intent_classification), ["primary", "broader"]);
  assert.equal(result.diagnostics.judge.reject_count, 8);
  const posts = requests.filter(item => item.options?.method === "POST");
  assert.equal(posts.length, 3);
  assert.ok(posts.every(item => !Object.keys(item.options.headers).some(name => /authorization|api.key/i.test(name))));
  assert.ok(result.parents.every(item => item.explanation?.excerpt && !/score|similarity/i.test(item.explanation.excerpt)));
});

test("intent-gate failure preserves neutral hybrid ranking without fabricated labels", async () => {
  const fetchImpl = async (url, options = {}) => {
    if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
    if (String(url) === "/vectors") return new Response(vectorBuffer, { status: 200 });
    if (String(url).endsWith("/embed-query")) {
      const vectors = api.decodeFloat16(
        vectorBuffer.buffer.slice(vectorBuffer.byteOffset, vectorBuffer.byteOffset + vectorBuffer.byteLength),
        corpus.length,
        api.EMBEDDING_DIMENSION,
      );
      return new Response(JSON.stringify({ embedding: Array.from(vectors.slice(0, api.EMBEDDING_DIMENSION)) }), { status: 200 });
    }
    if (String(url).endsWith("/rerank")) {
      const body = JSON.parse(options.body);
      return new Response(JSON.stringify({ rankings: body.candidates.map((item, index) => ({
        index,
        passage_id: item.passage_id,
        relevance_score: 1 - index / Math.max(1, body.candidates.length),
      })) }), { status: 200 });
    }
    if (String(url).endsWith("/judge")) {
      return new Response(JSON.stringify({ error: { code: "judge_unavailable" } }), { status: 503 });
    }
    return new Response("", { status: 404 });
  };
  const client = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
    fetchImpl,
  });
  const result = await client.search("rare earth recycling");
  assert.ok(result.parents.length > 10);
  assert.equal(result.diagnostics.judge.status, "fallback");
  assert.ok(result.parents.every(item => item.intent_classification === null && item.judge_fallback));
  assert.equal(result.usage.judge_fallbacks, 1);
});

test("provider errors and client timeouts fail closed for the existing local-result fallback", async () => {
  const baseOptions = {
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
  };
  const assetResponse = url => {
    if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
    if (String(url) === "/vectors") return new Response(vectorBuffer, { status: 200 });
    return null;
  };
  const failed = api.createClient({
    ...baseOptions,
    fetchImpl: async url => assetResponse(url)
      || new Response(JSON.stringify({ error: { code: "provider_unavailable" } }), { status: 503 }),
  });
  await assert.rejects(failed.search("rare earth recycling"), error => error.code === "provider_unavailable");
  assert.equal(failed.usage().fallbacks, 1);

  const timedOut = api.createClient({
    ...baseOptions,
    timeoutMs: 1,
    fetchImpl: async (url, options = {}) => assetResponse(url) || new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      }, { once: true });
    }),
  });
  await assert.rejects(timedOut.search("rare earth recycling"), error => error.code === "proxy_timeout");
  assert.equal(timedOut.usage().fallbacks, 1);
});

test("site integration remains disabled, lazy, extractive, and fail-closed", () => {
  assert.match(configSource, /searchV2:\s*false/);
  assert.match(configSource, /productionHybridProxy\s*=\s*""/);
  assert.match(htmlSource, /assets\/search-hybrid\.js/);
  assert.doesNotMatch(htmlSource, /search-v2-voyage-vectors\.f16|search-v2-voyage-manifest\.json/);
  assert.match(appSource, /hybridSearchClient\.search\(normalizedQuery, \{ context: "" \}\)/);
  assert.match(appSource, /Enhanced ranking is temporarily unavailable, so local ranking is shown/);
  assert.ok(appSource.indexOf("state.matches = search.matches") < appSource.indexOf("scheduleHybridSearch(state.query)"));
  assert.match(appSource, /Public source passage/);
  assert.match(appSource, /Primary match/);
  assert.match(appSource, /Broader program fit/);
  assert.match(appSource, /Intent-gated hybrid catalog/);
  assert.match(appSource, /intent classification is temporarily unavailable/i);
  assert.doesNotMatch(appSource, /Matched because semantic similarity|Voyage score/);
  assert.doesNotMatch(appSource, /VOYAGE_API_KEY|Authorization:\s*`Bearer/);
});
