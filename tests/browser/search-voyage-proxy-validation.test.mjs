import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "../../tools/run_search_diagnosis.mjs";
import {
  createHandler,
  SearchBudgetCoordinator,
} from "../../workers/search-voyage-proxy/src/index.js";

const root = new URL("../../", import.meta.url);
const hybridSource = await readFile(new URL("assets/search-hybrid.js", root), "utf8");
const [workerSource, wranglerSource] = await Promise.all([
  readFile(new URL("workers/search-voyage-proxy/src/index.js", root), "utf8"),
  readFile(new URL("workers/search-voyage-proxy/wrangler.jsonc", root), "utf8"),
]);
const manifest = await readFile(new URL("data/search-v2-voyage-manifest.json", root), "utf8").then(JSON.parse);
const allowlist = await readFile(
  new URL("workers/search-voyage-proxy/generated/corpus-allowlist.json", root),
  "utf8",
).then(JSON.parse);

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

function testEnv(overrides = {}) {
  const values = new Map();
  const coordinator = new SearchBudgetCoordinator({
    storage: {
      async get(key) { return values.get(key); },
      async put(key, value) { values.set(key, structuredClone(value)); },
    },
  });
  const limiter = { async limit() { return { success: true }; } };
  return {
    VOYAGE_API_KEY: "test-secret",
    ENHANCED_SEARCH_ENABLED: "true",
    DAILY_EMBED_TOKEN_BUDGET: "50000",
    DAILY_RERANK_TOKEN_BUDGET: "25000000",
    PER_CLIENT_EMBED_REQUEST_LIMIT: "12",
    PER_CLIENT_RERANK_REQUEST_LIMIT: "8",
    GLOBAL_REQUEST_LIMIT: "600",
    RATE_LIMIT_RETRY_AFTER_SECONDS: "10",
    GLOBAL_RATE_LIMITER: limiter,
    EMBED_RATE_LIMITER: limiter,
    RERANK_RATE_LIMITER: limiter,
    BUDGET_COORDINATOR: {
      idFromName(name) { return name; },
      get() {
        return { fetch(url, options) { return coordinator.fetch(new Request(url, options)); } };
      },
    },
    __budgetValues: values,
    ...overrides,
  };
}

test("proxy rejects origins, methods, malformed inputs, and non-corpus passages", async () => {
  let providerCalls = 0;
  const handler = createHandler({ fetchImpl: async () => { providerCalls += 1; return new Response("{}"); } });
  const env = testEnv();
  assert.equal((await handler(request("/embed-query", { query: "test" }, { origin: "https://evil.example" }), env)).status, 403);
  assert.equal((await handler(request("/embed-query", {}, { method: "GET" }), env)).status, 405);
  assert.equal((await handler(request("/embed-query", { query: "", extra: true }), env)).status, 400);
  const arbitrary = await handler(request("/rerank", {
    query: "test",
    corpus_sha256: manifest.corpus_sha256,
    model_space_fingerprint: manifest.model_space_fingerprint,
    candidates: [{ passage_id: first.passage_id, text_sha256: first.text_sha256, text: "private text" }],
  }), env);
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
  const env = testEnv();
  const embedded = await handler(request("/embed-query", { query: "public research query" }), env);
  assert.equal(embedded.status, 200);
  const reranked = await handler(request("/rerank", {
    query: "public research query",
    corpus_sha256: manifest.corpus_sha256,
    model_space_fingerprint: manifest.model_space_fingerprint,
    candidates: [{ passage_id: first.passage_id, text_sha256: first.text_sha256, text: first.text }],
  }), env);
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

test("proxy accepts exactly the current and immediately previous corpus generations", async () => {
  assert.equal(allowlist.current.corpus_sha256, manifest.corpus_sha256);
  assert.ok(allowlist.previous?.corpus_sha256);
  assert.notEqual(allowlist.previous.corpus_sha256, allowlist.current.corpus_sha256);
  const currentById = new Map(corpus.map(item => [item.passage_id, item]));
  const compatible = allowlist.previous.passages.find(item => {
    const current = currentById.get(item.passage_id);
    return current && current.text_sha256 === item.text_sha256;
  });
  assert.ok(compatible, "the compatibility window needs one unchanged public passage canary");
  const candidate = currentById.get(compatible.passage_id);
  let providerCalls = 0;
  const handler = createHandler({ fetchImpl: async () => {
    providerCalls += 1;
    return new Response(JSON.stringify({
      model: "rerank-2.5",
      data: [{ index: 0, relevance_score: .9 }],
      usage: { total_tokens: 3 },
    }), { status: 200 });
  } });
  const body = generation => ({
    query: "public compatibility test",
    corpus_sha256: generation.corpus_sha256,
    ...(generation.model_space_fingerprint
      ? { model_space_fingerprint: generation.model_space_fingerprint }
      : {}),
    candidates: [{
      passage_id: candidate.passage_id,
      text_sha256: compatible.text_sha256,
      text: candidate.text,
    }],
  });
  const env = testEnv();
  const current = await handler(request("/rerank", body(allowlist.current)), env);
  assert.equal(current.status, 200);
  const mismatchedFingerprint = body(allowlist.current);
  mismatchedFingerprint.model_space_fingerprint = "0".repeat(64);
  assert.equal(
    (await handler(request("/rerank", mismatchedFingerprint), env)).status,
    400,
  );
  const missingFingerprint = body(allowlist.current);
  delete missingFingerprint.model_space_fingerprint;
  assert.equal(
    (await handler(request("/rerank", missingFingerprint), env)).status,
    400,
  );
  const previous = await handler(request("/rerank", body(allowlist.previous)), env);
  assert.equal(previous.status, 200);
  const unknown = await handler(request("/rerank", body({ corpus_sha256: "f".repeat(64) })), env);
  assert.equal(unknown.status, 400);
  assert.equal(providerCalls, 2);
});

test("proxy converts provider failures into clean non-secret errors", async () => {
  const handler = createHandler({ fetchImpl: async () => new Response("upstream", { status: 503 }) });
  const response = await handler(request("/embed-query", { query: "test" }), testEnv());
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.deepEqual(body, { error: { code: "provider_invalid_response" } });
  assert.doesNotMatch(JSON.stringify(body), /test-secret|upstream/);
});

test("missing or invalid budget configuration disables hosted search before provider calls", async () => {
  let providerCalls = 0;
  const handler = createHandler({ fetchImpl: async () => {
    providerCalls += 1;
    return new Response("{}");
  } });
  const missing = await handler(request("/embed-query", { query: "test" }), {
    VOYAGE_API_KEY: "test",
    ENHANCED_SEARCH_ENABLED: "true",
  });
  assert.equal(missing.status, 503);
  assert.deepEqual(await missing.json(), { error: { code: "service_unconfigured" } });
  const disabled = await handler(
    request("/embed-query", { query: "test" }),
    testEnv({ ENHANCED_SEARCH_ENABLED: "false" }),
  );
  assert.equal(disabled.status, 503);
  assert.deepEqual(await disabled.json(), { error: { code: "service_disabled" } });
  assert.equal(providerCalls, 0);
});

test("forged CORS headers cannot bypass endpoint rate limits", async () => {
  let providerCalls = 0;
  const denied = { async limit() { return { success: false }; } };
  const env = testEnv({ EMBED_RATE_LIMITER: denied });
  const handler = createHandler({ fetchImpl: async () => {
    providerCalls += 1;
    return new Response("{}");
  } });
  const response = await handler(request("/embed-query", { query: "test" }, {
    origin: "https://mporosoff.github.io",
  }), env);
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("Retry-After"), "10");
  assert.deepEqual(await response.json(), { error: { code: "rate_limited" } });
  assert.equal(providerCalls, 0);
});

test("daily token exhaustion fails closed before calling Voyage", async () => {
  let providerCalls = 0;
  const env = testEnv({ DAILY_EMBED_TOKEN_BUDGET: "2" });
  const handler = createHandler({ fetchImpl: async () => {
    providerCalls += 1;
    return new Response("{}");
  } });
  const response = await handler(request("/embed-query", { query: "test" }), env);
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("Retry-After"), "10");
  assert.deepEqual(await response.json(), { error: { code: "budget_limited" } });
  assert.equal(providerCalls, 0);
});

test("budget reservations expire, are pruned, and agree with bounded status", async () => {
  let now = Date.UTC(2026, 7, 24, 12, 0, 0);
  const values = new Map();
  const coordinator = new SearchBudgetCoordinator({
    storage: {
      async get(key) { return values.get(key); },
      async put(key, value) { values.set(key, structuredClone(value)); },
    },
  }, { now: () => now });
  const budgets = { embed: 10, rerank: 20 };
  const call = payload => coordinator.fetch(new Request("https://budget.internal/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "embed", budgets, ...payload }),
  }));

  assert.equal((await call({ action: "reserve", amount: 10, reservation_id: "held" })).status, 200);
  let status = await call({ action: "status" });
  assert.deepEqual(await status.json(), {
    budget_state: "exhausted",
    reserved_tokens: { embed: 10, rerank: 0 },
    latency_ms: {
      embed: { p50: null, p95: null },
      rerank: { p50: null, p95: null },
    },
  });

  now += 30_001;
  status = await call({ action: "status" });
  assert.equal((await status.json()).budget_state, "available");
  assert.deepEqual(values.get("daily").reservations, {});
  assert.equal((await call({ action: "reserve", amount: 10, reservation_id: "replacement" })).status, 200);
  const reservation = values.get("daily").reservations.replacement;
  assert.equal(reservation.created_at, now);
  assert.equal(reservation.expires_at - reservation.created_at, 30_000);
});

test("public health counts outstanding reservations without exposing histories", async () => {
  let providerCalls = 0;
  const env = testEnv({ DAILY_EMBED_TOKEN_BUDGET: "10" });
  const coordinator = env.BUDGET_COORDINATOR.get();
  const reserved = await coordinator.fetch("https://budget.internal/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "reserve",
      kind: "embed",
      amount: 10,
      reservation_id: "health-canary",
      budgets: { embed: 10, rerank: 25000000 },
    }),
  });
  assert.equal(reserved.status, 200);
  const handler = createHandler({ fetchImpl: async () => {
    providerCalls += 1;
    return new Response("{}");
  } });
  const health = await handler(request("/health", null, { method: "GET" }), env);
  assert.equal(health.status, 200);
  const healthBody = await health.json();
  assert.equal(healthBody.budget_state, "exhausted");
  assert.deepEqual(healthBody.reserved_tokens, { embed: 10, rerank: 0 });
  assert.equal(Object.hasOwn(healthBody, "reservations"), false);
  const rejected = await handler(request("/embed-query", { query: "test" }), env);
  assert.equal(rejected.status, 429);
  assert.equal(providerCalls, 0);
});

test("health metadata is bounded and operational storage contains counters, never query text", async () => {
  const env = testEnv();
  const handler = createHandler({ fetchImpl: async () => new Response(JSON.stringify({
    model: "voyage-4-lite",
    data: [{ embedding: new Array(1024).fill(0) }],
    usage: { total_tokens: 2 },
  }), { status: 200 }) });
  const query = "private-looking but unstored research phrase";
  assert.equal((await handler(request("/embed-query", { query }), env)).status, 200);
  const health = await handler(request("/health", null, { method: "GET" }), env);
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), {
    service: "available",
    corpus_sha256: allowlist.current.corpus_sha256,
    model_space_fingerprint: allowlist.current.model_space_fingerprint,
    previous_corpus_supported: true,
    budget_state: "available",
    reserved_tokens: { embed: 0, rerank: 0 },
  });
  const stored = JSON.stringify(env.__budgetValues.get("daily"));
  assert.doesNotMatch(stored, new RegExp(query));
  assert.match(stored, /provider_input_tokens|latency_histogram|requests/);
  assert.doesNotMatch(stored, /cf-connecting-ip|candidate|passage|researcher|orcid|cv/i);
});

test("Cloudflare configuration separates endpoint limits and uses one exact global counter", () => {
  assert.match(wranglerSource, /"EMBED_RATE_LIMITER"[\s\S]*?"limit": 12/);
  assert.match(wranglerSource, /"RERANK_RATE_LIMITER"[\s\S]*?"limit": 8/);
  assert.match(wranglerSource, /"GLOBAL_RATE_LIMITER"[\s\S]*?"limit": 600/);
  assert.match(wranglerSource, /"BUDGET_COORDINATOR"[\s\S]*?"SearchBudgetCoordinator"/);
  assert.match(wranglerSource, /"storage": "sqlite"/);
  assert.match(workerSource, /DAILY_EMBED_TOKEN_BUDGET|DAILY_RERANK_TOKEN_BUDGET|ENHANCED_SEARCH_ENABLED/);
  assert.match(workerSource, /RESERVATION_TTL_MS\s*=\s*30_000/);
  assert.match(workerSource, /created_at: now[\s\S]*?expires_at: now \+ RESERVATION_TTL_MS/);
});

test("proxy exposes no live intent-judge endpoint or Workers AI dependency", async () => {
  const handler = createHandler();
  const response = await handler(request("/judge", {
    query: "public research query",
    results: [{
      id: first.parent_id,
      title: first.values.parent_title?.[0] || first.title,
      passage: first.text,
      field: first.fields[0],
      type: first.passage_kind,
    }],
  }), testEnv({ AI: { run: async () => { throw new Error("must not run"); } } }));
  assert.equal(response.status, 404);
  assert.deepEqual(await response.json(), { error: { code: "not_found" } });
  assert.doesNotMatch(workerSource, /JUDGE_MODEL|env\?\.AI|AI\.run|judge_/);
  assert.doesNotMatch(wranglerSource, /"ai"|"binding"\s*:\s*"AI"/i);
});
