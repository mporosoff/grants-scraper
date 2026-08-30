import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import test from "node:test";
import vm from "node:vm";

import { loadHarness, makeVariantHarness, rankQuery } from "../../tools/run_search_diagnosis.mjs";

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
  assert.ok(corpus.length >= 1_000);
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

test("non-expandable public passage explanations use complete sentences or phrases", () => {
  const longSentence = `The program supports transport research that connects momentum, heat, and mass transfer across ${"multiscale experimental and computational systems ".repeat(8).trim()}.`;
  const explanation = api.explanationFromPassage({
    passage_id: "parent:complete-excerpt",
    passage_kind: "parent",
    title: "Complete excerpt fixture",
    values: {
      parent_description: [`${longSentence} A second complete sentence should not be needed for the card.`],
    },
  });
  assert.equal(explanation.excerpt, longSentence);
  assert.doesNotMatch(explanation.excerpt, /…|\.{3}$/);

  const phrase = "Transport phenomena across porous media and reactive interfaces without a terminal punctuation mark";
  assert.equal(api.explanationFromPassage({
    passage_id: "parent:complete-phrase",
    passage_kind: "parent",
    title: "Complete phrase fixture",
    values: { parent_description: [phrase] },
  }).excerpt, phrase);
});

test("Potential explanations select the complete source span that supports the canonical query", () => {
  const sourceText = "This program supports general workforce coordination. It funds rare earth recycling and separations research across the supply chain.";
  const explanation = api.explanationFromPassage({
    passage_id: "parent:query-aware-excerpt",
    passage_kind: "parent",
    title: "Query-aware excerpt fixture",
    values: { parent_description: [sourceText] },
  }, "rare earth recycling");

  assert.equal(
    explanation.excerpt,
    "It funds rare earth recycling and separations research across the supply chain.",
  );
  assert.equal(explanation.source_field, "parent_description");
  assert.ok(sourceText.includes(explanation.excerpt));
  assert.doesNotMatch(explanation.excerpt, /score|similarity|semantic/i);
});

test("Potential explanations preserve initialisms at the start of a source sentence", () => {
  const sourceText = "The U.S. National Science Foundation supports carbon capture research. A separate sentence discusses workforce development.";
  const explanation = api.explanationFromPassage({
    passage_id: "parent:initialism-excerpt",
    passage_kind: "parent",
    title: "Initialism excerpt fixture",
    values: { parent_description: [sourceText] },
  }, "carbon capture");

  assert.equal(
    explanation.excerpt,
    "The U.S. National Science Foundation supports carbon capture research.",
  );
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

  const reeDirect = { diagnostics: { acronymExpansions: [{
    source: "ree",
    phrase: "rare earth element",
    confidence: 1,
  }] } };
  const reesDirect = { diagnostics: { acronymExpansions: [{
    source: "rees",
    phrase: "rare earth elements",
    confidence: 1,
  }] } };
  assert.equal(
    api.canonicalSemanticQuery("REE separations", reeDirect, null),
    "rare earth element separations",
  );
  assert.match(
    api.canonicalSemanticQuery("REE", reeDirect, null),
    /^rare earth element\. Prioritize scientific research/,
  );
  assert.match(
    api.canonicalSemanticQuery("REEs", reesDirect, null),
    /^rare earth elements\. Prioritize scientific research/,
  );
  assert.equal(api.canonicalSemanticQuery("AIM", null, null), "AIM");
  assert.equal(api.deterministicSafeguard(
    "REEs",
    { text: "rare earth elements" },
    new Set(["REES"]),
  ).allowed, true);
  assert.match(source, /post\("embed-query", \{ query: semanticQuery \}, signal\)/);
  assert.match(source, /query: semanticQuery,[\s\S]*?corpus_sha256/);

  const parents = api.strongestParents([
    { parent_id: "p", passage_id: "parent:p", voyage_score: .4 },
    { parent_id: "p", passage_id: "child:c", voyage_score: .8 },
    { parent_id: "q", passage_id: "parent:q", voyage_score: .7 },
  ]);
  assert.equal(Array.from(parents, item => item.passage_id).join(","), "child:c,parent:q");
});

test("a cross-track result removed from Strong remains eligible for Potential", () => {
  const query = "health data workforce workshop";
  const local = rankQuery(harness, query, { evidence: true });
  assert.equal(local.rows.some(row => row.id === "334326"), false);

  const parentDirect = harness.parentEngine.score(query, { evidence: true });
  const childDirect = harness.childEngine.score(query, { evidence: true });
  const candidates = api.buildBm25Candidates({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentDirect,
    childDirect,
    corpusById: new Map(corpus.map(item => [item.passage_id, item])),
  });
  const blocker = candidates.find(item => item.parent_id === "334326");

  assert.ok(blocker);
  assert.equal(blocker.passage_id, "parent:334326");
  assert.ok(parentDirect.discoveryScores[harness.parentCatalog.opportunities.findIndex(record => (
    String(record.opportunity_id) === "334326"
  ))] > 0);
});

test("active parent eligibility constrains BM25, semantic top-k, child passages, and reranking", async () => {
  const eligibleParentIds = ["361526"];
  const vectors = api.decodeFloat16(
    vectorBuffer.buffer.slice(vectorBuffer.byteOffset, vectorBuffer.byteOffset + vectorBuffer.byteLength),
    corpus.length,
    api.EMBEDDING_DIMENSION,
  );
  const targetRow = corpus.findIndex(item => item.parent_id === eligibleParentIds[0]);
  assert.ok(targetRow >= 0);
  const queryVector = vectors.slice(
    targetRow * api.EMBEDDING_DIMENSION,
    (targetRow + 1) * api.EMBEDDING_DIMENSION,
  );
  const semantic = api.semanticCandidates(corpus, vectors, queryVector, 200, eligibleParentIds);
  assert.ok(semantic.length > 0);
  assert.ok(semantic.every(item => item.parent_id === eligibleParentIds[0]));

  const query = "rare earth recycling";
  const parentDirect = harness.parentEngine.score(query, { evidence: true });
  const childDirect = harness.childEngine.score(query, { evidence: true });
  const bm25 = api.buildBm25Candidates({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentDirect,
    childDirect,
    corpusById: new Map(corpus.map(item => [item.passage_id, item])),
    eligibleParentIds,
  });
  assert.ok(bm25.every(item => item.parent_id === eligibleParentIds[0]));

  let rerankCandidates = [];
  let embedRequests = 0;
  let rerankRequests = 0;
  const client = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
    fetchImpl: async (url, options = {}) => {
      if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
      if (String(url).startsWith("/vectors?v=")) return new Response(vectorBuffer, { status: 200 });
      if (String(url).endsWith("/embed-query")) {
        embedRequests += 1;
        return new Response(JSON.stringify({ embedding: Array.from(queryVector) }), { status: 200 });
      }
      if (String(url).endsWith("/rerank")) {
        rerankRequests += 1;
        const body = JSON.parse(options.body);
        rerankCandidates = body.candidates;
        return new Response(JSON.stringify({ rankings: body.candidates.map((item, index) => ({
          index,
          passage_id: item.passage_id,
          relevance_score: 1 - index / Math.max(1, body.candidates.length),
        })) }), { status: 200 });
      }
      return new Response("", { status: 404 });
    },
  });
  const outcome = await client.search(query, { eligibleParentIds });
  const corpusByPassage = new Map(corpus.map(item => [item.passage_id, item]));
  assert.ok(rerankCandidates.length > 0);
  assert.ok(rerankCandidates.every(item => corpusByPassage.get(item.passage_id)?.parent_id === "361526"));
  assert.ok(outcome.parents.every(item => item.parent_id === "361526"));
  assert.equal(outcome.diagnostics.eligible_parent_count, 1);
  assert.match(outcome.diagnostics.request_signature, /^[a-f0-9]{64}$/);
  const cached = await client.search(query, { eligibleParentIds });
  assert.equal(cached.diagnostics.cache_hit, true);
  assert.equal(embedRequests, 1, "an unchanged retrieval signature causes no paid request");
  assert.equal(rerankRequests, 1, "an unchanged retrieval signature causes no paid request");
  await client.search(query, { eligibleParentIds: [...eligibleParentIds, "362061"] });
  assert.equal(embedRequests, 2, "a substantive eligibility change causes one new embed");
  assert.equal(rerankRequests, 2, "a substantive eligibility change causes one new rerank");
});

test("identical in-flight searches share one paid semantic cycle", async () => {
  const vectors = api.decodeFloat16(
    vectorBuffer.buffer.slice(vectorBuffer.byteOffset, vectorBuffer.byteOffset + vectorBuffer.byteLength),
    corpus.length,
    api.EMBEDDING_DIMENSION,
  );
  const queryVector = vectors.slice(0, api.EMBEDDING_DIMENSION);
  let releaseEmbedding;
  const embeddingGate = new Promise(resolve => { releaseEmbedding = resolve; });
  let embedRequests = 0;
  let rerankRequests = 0;
  const client = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
    fetchImpl: async (url, options = {}) => {
      if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
      if (String(url).startsWith("/vectors?v=")) return new Response(vectorBuffer, { status: 200 });
      if (String(url).endsWith("/embed-query")) {
        embedRequests += 1;
        await embeddingGate;
        return new Response(JSON.stringify({ embedding: Array.from(queryVector) }), { status: 200 });
      }
      if (String(url).endsWith("/rerank")) {
        rerankRequests += 1;
        const body = JSON.parse(options.body);
        return new Response(JSON.stringify({ rankings: body.candidates.map((item, index) => ({
          index,
          passage_id: item.passage_id,
          relevance_score: 1 - index / Math.max(1, body.candidates.length),
        })) }), { status: 200 });
      }
      return new Response("", { status: 404 });
    },
  });

  const first = client.search("rare earth recycling", { eligibleParentIds: ["361526", "362061"] });
  const repeated = client.search("rare earth recycling", { eligibleParentIds: ["362061", "361526"] });
  releaseEmbedding();
  const [firstResult, repeatedResult] = await Promise.all([first, repeated]);

  assert.equal(embedRequests, 1);
  assert.equal(rerankRequests, 1);
  assert.deepEqual(
    Array.from(firstResult.parents, item => item.parent_id),
    Array.from(repeatedResult.parents, item => item.parent_id),
  );
});

test("a superseded browser request is aborted without recording a service fallback", async () => {
  const controller = new AbortController();
  const client = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
    fetchImpl: async (url, options = {}) => {
      if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
      if (String(url).startsWith("/vectors?v=")) return new Response(vectorBuffer, { status: 200 });
      if (String(url).endsWith("/embed-query")) {
        return new Promise((_resolve, reject) => {
          const rejectAbort = () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          };
          if (options.signal.aborted) rejectAbort();
          else options.signal.addEventListener("abort", rejectAbort, { once: true });
        });
      }
      return new Response("", { status: 404 });
    },
  });

  const pending = client.search("rare earth recycling", { signal: controller.signal });
  setTimeout(() => controller.abort(), 0);
  await assert.rejects(pending, error => error.code === "request_aborted");
  assert.equal(client.usage().fallbacks, 0);
  assert.equal(client.usage().failures, 0);
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
    if (String(url).startsWith("/vectors?v=")) return new Response(vectorBuffer, { status: 200 });
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
  assert.ok(result.parents.length > 10);
  assert.ok(result.parents.every(item => !Object.hasOwn(item, "intent_classification")));
  assert.equal(result.diagnostics.judge, undefined);
  const posts = requests.filter(item => item.options?.method === "POST");
  assert.equal(posts.length, 2);
  assert.ok(posts.every(item => !Object.keys(item.options.headers).some(name => /authorization|api.key/i.test(name))));
  assert.ok(result.parents.every(item => item.explanation?.excerpt && !/score|similarity/i.test(item.explanation.excerpt)));
});

test("missing or mismatched vector assets fail closed to the existing local-result fallback", async () => {
  const baseOptions = {
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "/manifest",
    vectorUrl: "/vectors",
  };
  const missing = api.createClient({
    ...baseOptions,
    fetchImpl: async url => String(url) === "/manifest"
      ? new Response(JSON.stringify(manifest), { status: 200 })
      : new Response("", { status: 404 }),
  });
  await assert.rejects(missing.search("rare earth recycling"), error => error.code === "vector_asset_missing");
  assert.equal(missing.usage().fallbacks, 1);

  const mismatched = api.createClient({
    ...baseOptions,
    fetchImpl: async url => String(url) === "/manifest"
      ? new Response(JSON.stringify(manifest), { status: 200 })
      : new Response(new Uint8Array(vectorBuffer.byteLength), { status: 200 }),
  });
  await assert.rejects(mismatched.search("rare earth recycling"), error => error.code === "vector_hash_mismatch");
  assert.equal(mismatched.usage().fallbacks, 1);
});

test("hybrid results remain ranked leads without fabricated relevance labels", async () => {
  const fetchImpl = async (url, options = {}) => {
    if (String(url) === "/manifest") return new Response(JSON.stringify(manifest), { status: 200 });
    if (String(url).startsWith("/vectors?v=")) return new Response(vectorBuffer, { status: 200 });
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
  assert.equal(result.diagnostics.judge, undefined);
  assert.ok(result.parents.every(item => item.explanation?.excerpt));
  assert.equal(result.usage.embedding_requests, 1);
  assert.equal(result.usage.rerank_requests, 1);
  assert.equal(result.usage.judge_requests, undefined);
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
    if (String(url).startsWith("/vectors?v=")) return new Response(vectorBuffer, { status: 200 });
    return null;
  };
  const failed = api.createClient({
    ...baseOptions,
    fetchImpl: async url => assetResponse(url)
      || new Response(JSON.stringify({ error: { code: "provider_unavailable" } }), { status: 503 }),
  });
  await assert.rejects(failed.search("rare earth recycling"), error => error.code === "provider_unavailable");
  assert.equal(failed.usage().fallbacks, 1);

  const rateLimited = api.createClient({
    ...baseOptions,
    fetchImpl: async url => assetResponse(url)
      || new Response(JSON.stringify({ error: { code: "rate_limited" } }), {
        status: 429,
        headers: { "Retry-After": "10" },
      }),
  });
  await assert.rejects(
    rateLimited.search("rare earth recycling"),
    error => error.code === "rate_limited" && error.retryAfter === 10,
  );
  assert.equal(rateLimited.usage().fallbacks, 1);

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

test("Funding Finder shows Potential progress and failures while successful completion stays silent", () => {
  assert.match(htmlSource, /id="potential-status"[^>]*role="status"/);
  assert.match(appSource, /Finding broader Potential matches from public opportunity text/);
  assert.doesNotMatch(appSource, /"Potential matching completed\./);
  assert.match(appSource, /applyHybridParents\(state\.hybrid\.parents\);[\s\S]*?\$\("search-status"\)\.textContent = "";[\s\S]*?renderResults\(\);/);
  assert.match(appSource, /Broader Potential matching is temporarily unavailable\./);
  assert.match(appSource, /Broader Potential matching is temporarily limited\./);
  assert.match(appSource, /unavailable while the search package updates/);
  assert.match(appSource, /Retry potential matches/);
  assert.doesNotMatch(appSource, /Voyage (?:failed|error)|corpus_sha256.*potential-status|stack trace/i);
});

test("production integration is enabled, lazy, extractive, and fail-closed", () => {
  assert.match(configSource, /searchV2:\s*true/);
  assert.match(
    configSource,
    /productionHybridProxy\s*=\s*"https:\/\/funding-finder-voyage-search\.urochestercheme\.workers\.dev\/"/,
  );
  assert.match(htmlSource, /assets\/search-hybrid\.js/);
  assert.doesNotMatch(htmlSource, /search-v2-voyage-vectors\.f16|search-v2-voyage-manifest\.json/);
  assert.match(appSource, /hybridSearchClient\.search\(normalizedQuery, \{[\s\S]*?context: "",[\s\S]*?eligibleParentIds,[\s\S]*?signal: controller\.signal/);
  assert.match(appSource, /No strong matches were found\. Broader Potential matching is temporarily unavailable/);
  assert.ok(appSource.indexOf("state.strongMatches = search.matches") < appSource.indexOf("scheduleHybridSearch(state.query"));
  assert.match(appSource, /Why this may be relevant/);
  assert.match(appSource, /Strong match/);
  assert.match(appSource, /Potential match/);
  assert.doesNotMatch(appSource, /Strong \+ potential catalog/);
  assert.match(appSource, /const POTENTIAL_MATCH_LIMIT = 12/);
  assert.match(appSource, /\.filter\(match => !strongIds\.has/);
  assert.match(appSource, /Strong matches/);
  assert.match(appSource, /Potential matches/);
  assert.doesNotMatch(appSource, /No strong matches found\.<\/h3><p>The broader search found potential matches below/);
  assert.doesNotMatch(appSource, /confirm fit in the official opportunity/i);
  assert.doesNotMatch(appSource, /intent classification is temporarily unavailable/i);
  assert.doesNotMatch(source, /\/judge|JUDGE_MODEL|intent_classification/);
  assert.doesNotMatch(appSource, /Matched because semantic similarity|Voyage score/);
  assert.doesNotMatch(appSource, /VOYAGE_API_KEY|Authorization:\s*`Bearer/);
});

test("cold search overlaps independent work and vectors use an immutable generation URL", () => {
  const searchBody = source.slice(source.indexOf("async function search"));
  const ordered = [
    "const assetsTask = loadAssets()",
    "const parentDirect = parentEngine.score",
    "const embeddedTask = post(\"embed-query\"",
    "Promise.all([assetsTask, embeddedTask])",
    "semanticCandidates(",
    "post(\"rerank\"",
  ].map(fragment => searchBody.indexOf(fragment));
  ordered.forEach(index => assert.ok(index >= 0, "cold-path stage is present"));
  assert.deepEqual(ordered, ordered.slice().sort((left, right) => left - right));
  assert.match(source, /versionedVectorUrl[\s\S]*?v=\$\{manifest\.vector_sha256\}/);
  assert.match(source, /fetchImpl\(versionedVectorUrl, \{ cache: "force-cache"/);
  assert.doesNotMatch(htmlSource, /search-v2-voyage-vectors\.f16/);
});
