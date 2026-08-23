import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "../../tools/run_search_diagnosis.mjs";
import { createHandler } from "../../workers/search-voyage-proxy/src/index.js";

const root = new URL("../../", import.meta.url);
const hybridSource = await readFile(new URL("assets/search-hybrid.js", root), "utf8");
const workerSource = await readFile(new URL("workers/search-voyage-proxy/src/index.js", root), "utf8");
const manifest = await readFile(new URL("data/search-v2-voyage-manifest.json", root), "utf8").then(JSON.parse);

function loadHybridApi() {
  const context = { TextEncoder, URL };
  context.globalThis = {};
  vm.runInNewContext(hybridSource, context);
  return context.globalThis.FUNDING_HYBRID_SEARCH;
}

const api = loadHybridApi();
const base = await loadHarness();
const harness = makeVariantHarness(base, { searchV2: true });
const currentness = harness.parentEngine.score("funding research", { evidence: false });
const corpus = api.buildCorpus({
  parentCatalog: harness.parentCatalog,
  childCatalog: harness.childCatalog,
  currentnessRejectedIndexes: currentness.currentnessRejectedIndexes,
});
corpus.forEach((item, index) => { item.text_sha256 = manifest.passages[index].text_sha256; });
const first = corpus[0];

function request(path, body, { origin = "http://localhost:8000", method = "POST" } = {}) {
  return new Request(`http://worker.test${path}`, {
    method,
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
}

test("proxy rejects origins, methods, malformed inputs, and non-corpus passages", async () => {
  let providerCalls = 0;
  const handler = createHandler({ fetchImpl: async () => { providerCalls += 1; return new Response("{}"); } });
  assert.equal((await handler(request("/embed-query", { query: "test" }, { origin: "https://evil.example" }), { VOYAGE_API_KEY: "test" })).status, 403);
  assert.equal((await handler(request("/embed-query", {}, { method: "GET" }), { VOYAGE_API_KEY: "test" })).status, 405);
  assert.equal((await handler(request("/embed-query", { query: "", extra: true }), { VOYAGE_API_KEY: "test" })).status, 400);
  const arbitrary = await handler(request("/rerank", {
    query: "test",
    corpus_sha256: manifest.corpus_sha256,
    candidates: [{ passage_id: first.passage_id, text_sha256: first.text_sha256, text: "private text" }],
  }), { VOYAGE_API_KEY: "test" });
  assert.equal(arbitrary.status, 400);
  assert.equal(providerCalls, 0);
});

test("proxy sends only bounded allowlisted public text and exposes no credential", async () => {
  const upstream = [];
  const handler = createHandler({ fetchImpl: async (url, options) => {
    upstream.push({ url: String(url), options });
    if (String(url).endsWith("/embeddings")) {
      return new Response(JSON.stringify({
        model: "voyage-4-lite",
        data: [{ embedding: new Array(1024).fill(0) }],
        usage: { total_tokens: 2 },
      }), { status: 200 });
    }
    return new Response(JSON.stringify({
      model: "rerank-2.5",
      data: [{ index: 0, relevance_score: .9 }],
      usage: { total_tokens: 5 },
    }), { status: 200 });
  } });
  const embedded = await handler(request("/embed-query", { query: "public research query" }), { VOYAGE_API_KEY: "test-secret" });
  assert.equal(embedded.status, 200);
  const reranked = await handler(request("/rerank", {
    query: "public research query",
    corpus_sha256: manifest.corpus_sha256,
    candidates: [{ passage_id: first.passage_id, text_sha256: first.text_sha256, text: first.text }],
  }), { VOYAGE_API_KEY: "test-secret" });
  assert.equal(reranked.status, 200);
  assert.equal(upstream.length, 2);
  const rerankBody = JSON.parse(upstream[1].options.body);
  assert.equal(rerankBody.documents[0], first.text);
  assert.equal(rerankBody.return_documents, false);
  assert.match(rerankBody.query, /complete research intent/);
  assert.doesNotMatch(JSON.stringify(await reranked.json()), /test-secret|Authorization|Bearer/);
  assert.match(workerSource, /PROVIDER_TIMEOUT_MS\s*=\s*7_000/);
  assert.doesNotMatch(workerSource, /console\.(?:log|error)|researcher|ORCID|CV/);
});

test("proxy converts provider failures into clean non-secret errors", async () => {
  const handler = createHandler({ fetchImpl: async () => new Response("upstream", { status: 503 }) });
  const response = await handler(request("/embed-query", { query: "test" }), { VOYAGE_API_KEY: "test-secret" });
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.deepEqual(body, { error: { code: "provider_invalid_response" } });
  assert.doesNotMatch(JSON.stringify(body), /test-secret|upstream/);
});

test("judge validates public-only input and returns strict structured classifications", async () => {
  const calls = [];
  const AI = { run: async (model, input) => {
    calls.push({ model, input });
    return {
      response: { results: [{ id: first.parent_id, classification: "primary" }] },
      usage: { prompt_tokens: 40, completion_tokens: 8, total_tokens: 48 },
    };
  } };
  const handler = createHandler();
  const valid = {
    query: "public research query",
    results: [{
      id: first.parent_id,
      title: first.values.parent_title?.[0] || first.title,
      passage: first.text,
      field: first.fields[0],
      type: first.passage_kind,
    }],
  };
  const response = await handler(request("/judge", valid), { AI });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.results, [{ id: first.parent_id, classification: "primary" }]);
  assert.deepEqual(body.usage, { input_tokens: 40, output_tokens: 8, total_tokens: 48, neurons: 0 });
  assert.equal(calls[0].model, "@cf/meta/llama-3.1-8b-instruct-fast");
  assert.equal(calls[0].input.response_format.type, "json_schema");
  assert.match(calls[0].input.messages[0].content, /only from its supplied published passage/i);
  assert.doesNotMatch(calls[0].input.messages[0].content, /public research query/);

  const privateField = await handler(request("/judge", {
    ...valid,
    results: [{ ...valid.results[0], profile: "private researcher data" }],
  }), { AI });
  assert.equal(privateField.status, 400);
  const arbitraryPassage = await handler(request("/judge", {
    ...valid,
    results: [{ ...valid.results[0], passage: "private researcher data" }],
  }), { AI });
  assert.equal(arbitraryPassage.status, 400);
  const arbitraryTitle = await handler(request("/judge", {
    ...valid,
    results: [{ ...valid.results[0], title: "private researcher data" }],
  }), { AI });
  assert.equal(arbitraryTitle.status, 400);
  const wrongType = await handler(request("/judge", {
    ...valid,
    results: [{
      ...valid.results[0],
      type: valid.results[0].type === "parent" ? "publication_eligible_child" : "parent",
    }],
  }), { AI });
  assert.equal(wrongType.status, 400);
  const absentField = await handler(request("/judge", {
    ...valid,
    results: [{ ...valid.results[0], field: "bounded_source_evidence" }],
  }), { AI });
  assert.equal(absentField.status, 400);
  assert.equal(calls.length, 1);
});

test("judge rejects invalid classifications and converts Workers AI failures cleanly", async () => {
  const valid = {
    query: "public research query",
    results: [{
      id: first.parent_id,
      title: first.values.parent_title?.[0] || first.title,
      passage: first.text,
      field: first.fields[0],
      type: first.passage_kind,
    }],
  };
  const invalidHandler = createHandler();
  const invalid = await invalidHandler(request("/judge", valid), {
    AI: { run: async () => ({ response: { results: [{ id: first.parent_id, classification: "maybe" }] } }) },
  });
  assert.equal(invalid.status, 502);
  assert.deepEqual(await invalid.json(), { error: { code: "judge_invalid_response" } });

  const failed = await invalidHandler(request("/judge", valid), {
    AI: { run: async () => { throw new Error("private provider failure"); } },
  });
  assert.equal(failed.status, 503);
  assert.deepEqual(await failed.json(), { error: { code: "judge_unavailable" } });
});
