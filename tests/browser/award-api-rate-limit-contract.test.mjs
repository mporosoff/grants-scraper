import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { ADAPTER_VERSIONS, createHandler } from "../../workers/award-api/src/index.js";
import { AwardRateLimiter, BUCKETS } from "../../workers/award-api/src/rate-limit.js";

const root = new URL("../../", import.meta.url);
const [nsfFixture, rorFixture] = await Promise.all([
  readFile(new URL("tests/fixtures/awards/nsf_award.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/ror_aliases.json", root), "utf8").then(JSON.parse),
]);
const fixedNow = new Date("2026-08-27T12:00:00.000Z");

function context() {
  const database = new DatabaseSync(":memory:");
  return {
    database,
    storage: {
      sql: {
        exec(sql, ...values) {
          if (/^\s*CREATE\s+/i.test(sql)) {
            database.exec(sql);
            return [];
          }
          return database.prepare(sql).all(...values);
        },
      },
    },
  };
}

function durableNamespace() {
  const instances = new Map();
  return {
    instances,
    idFromName: name => String(name),
    get(id) {
      if (!instances.has(id)) {
        const ctx = context();
        instances.set(id, { ctx, limiter: new AwardRateLimiter(ctx) });
      }
      const instance = instances.get(id);
      return {
        fetch: (input, init) => instance.limiter.fetch(new Request(input, init)),
      };
    },
  };
}

function consume(limiter, { bucket = "award:NSF", now = fixedNow.getTime(), limit = 3 } = {}) {
  return limiter.fetch(new Request("https://award-rate-limit.internal/consume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bucket, now, limit, window_seconds: 60 }),
  })).then(async response => ({ response, body: await response.json() }));
}

function environment(namespace, overrides = {}) {
  return {
    AWARD_API_ENABLED: "true",
    CACHE_TTL_SECONDS: "3600",
    MAX_SOURCE_RESULTS: "25",
    AWARD_SOURCE_RATE_LIMIT: "2",
    ROR_SEARCH_RATE_LIMIT: "3",
    ROR_RESOLVE_RATE_LIMIT: "2",
    AWARD_RATE_LIMIT_SECRET: "deterministic-award-rate-limit-secret",
    AWARD_RATE_LIMITER: namespace,
    ...overrides,
  };
}

function memoryCache() {
  const values = new Map();
  return {
    async match(request) { return values.get(request.url)?.clone(); },
    async put(request, response) { values.set(request.url, response.clone()); },
  };
}

function awardRequest(topic, address = "203.0.113.17", source = "NSF") {
  return new Request("https://award.test/awards/search", {
    method: "POST",
    headers: {
      Origin: "http://localhost:8000",
      "Content-Type": "application/json",
      "cf-connecting-ip": address,
    },
    body: JSON.stringify({ sources: [source], criteria: { topic }, limit: 1, offset: 0 }),
  });
}

function rorRequest(query, address = "203.0.113.17") {
  return new Request(`https://award.test/institutions/search?query=${encodeURIComponent(query)}`, {
    headers: { Origin: "http://localhost:8000", "cf-connecting-ip": address },
  });
}

test("FF-BUG-010 Durable Object counters are atomic, source-scoped, and roll over exactly", async () => {
  const ctx = context();
  const limiter = new AwardRateLimiter(ctx);
  const health = await limiter.fetch(new Request("https://award-rate-limit.internal/health"));
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { ready: true, storage: "sqlite" });
  assert.equal(ctx.database.prepare("SELECT COUNT(*) AS count FROM counters").get().count, 0);
  const attempts = await Promise.all(Array.from({ length: 5 }, () => consume(limiter)));
  assert.equal(attempts.filter(attempt => attempt.body.success).length, 3);
  assert.ok(attempts.filter(attempt => !attempt.body.success).every(attempt => (
    attempt.body.retry_after_seconds === 60
  )));
  assert.equal(ctx.database.prepare(
    "SELECT request_count FROM counters WHERE bucket='award:NSF'",
  ).get().request_count, 3);

  assert.equal((await consume(limiter, { bucket: "award:NIH", limit: 1 })).body.success, true);
  assert.equal((await consume(limiter, { bucket: "award:NIH", limit: 1 })).body.success, false);
  const rollover = await consume(limiter, { now: fixedNow.getTime() + 60_001 });
  assert.equal(rollover.body.success, true);
  assert.equal(ctx.database.prepare(
    "SELECT request_count FROM counters WHERE bucket='award:NSF'",
  ).get().request_count, 1);
  assert.equal((await consume(limiter, { bucket: "unbounded:caller" })).response.status, 400);
});

test("every advertised award adapter has an accepted source-rate bucket", async () => {
  const expected = Object.keys(ADAPTER_VERSIONS).map(source => `award:${source}`).sort();
  const actual = [...BUCKETS].filter(bucket => bucket.startsWith("award:")).sort();
  assert.deepEqual(actual, expected);

  const limiter = new AwardRateLimiter(context());
  for (const bucket of expected) {
    const attempt = await consume(limiter, { bucket, limit: 1 });
    assert.equal(attempt.response.status, 200, `${bucket} should be accepted`);
    assert.equal(attempt.body.success, true, `${bucket} should receive its first request`);
  }
});

test("FF-BUG-010 Award and ROR limits protect only cache misses and never store a raw address", async () => {
  const namespace = durableNamespace();
  const cache = memoryCache();
  const calls = [];
  const fetchImpl = async url => {
    calls.push(String(url));
    return String(url).includes("api.ror.org")
      ? new Response(JSON.stringify(rorFixture.MIT), { headers: { "Content-Type": "application/json" } })
      : new Response(JSON.stringify(nsfFixture), { headers: { "Content-Type": "application/json" } });
  };
  const handler = createHandler({ fetchImpl, cache, now: () => fixedNow });
  const activeEnv = environment(namespace);

  assert.equal((await handler(awardRequest("catalysis"), activeEnv)).status, 200);
  assert.equal((await handler(awardRequest("catalysis"), activeEnv)).status, 200);
  assert.equal(calls.filter(url => url.includes("api.nsf.gov")).length, 1, "a cache hit consumes no upstream request");
  assert.equal((await handler(awardRequest("electrocatalysis"), activeEnv)).status, 200);
  const limitedAward = await handler(awardRequest("photocatalysis"), activeEnv);
  assert.equal(limitedAward.status, 429);
  assert.equal(limitedAward.headers.get("retry-after"), "60");
  assert.deepEqual((await limitedAward.json()).sources, [{
    source: "NSF", status: "unavailable", error: { code: "rate_limited" },
  }]);
  assert.equal((await handler(awardRequest("photocatalysis", "203.0.113.18"), activeEnv)).status, 200);

  for (const query of ["MIT", "MIT", "Massachusetts Tech", "Institute Tech"]) {
    assert.equal((await handler(rorRequest(query), activeEnv)).status, 200);
  }
  const limitedRor = await handler(rorRequest("Technology Institute"), activeEnv);
  assert.equal(limitedRor.status, 429);
  assert.equal(limitedRor.headers.get("retry-after"), "60");
  assert.equal((await limitedRor.json()).registry.error.code, "rate_limited");

  assert.ok(namespace.instances.size >= 2, "different anonymous actors receive independent objects");
  for (const [id, instance] of namespace.instances) {
    assert.match(id, /^[a-f0-9]{64}$/);
    assert.notEqual(id, "203.0.113.17");
    const rows = instance.ctx.database.prepare(
      "SELECT bucket,window_started_at,expires_at,request_count FROM counters ORDER BY bucket",
    ).all();
    assert.doesNotMatch(JSON.stringify(rows), /203\.0\.113\.(17|18)/);
  }
});

test("FF-BUG-010 health fails closed without the deployable binding or identity secret", async () => {
  const namespace = durableNamespace();
  const handler = createHandler({ fetchImpl: async () => new Response("{}"), now: () => fixedNow });
  const request = new Request("https://award.test/health", { headers: { Origin: "http://localhost:8000" } });
  const ready = await handler(request, environment(namespace));
  assert.equal(ready.status, 200);
  assert.equal((await ready.json()).abuse_control.ready, true);
  for (const missing of [
    environment(null),
    environment(namespace, { AWARD_RATE_LIMIT_SECRET: "" }),
  ]) {
    const response = await handler(request.clone(), missing);
    assert.equal(response.status, 503);
    assert.equal((await response.json()).abuse_control.ready, false);
  }
});

test("FF-BUG-010 health probes the live limiter and fails closed on rejection or timeout", async () => {
  const request = new Request("https://award.test/health", { headers: { Origin: "http://localhost:8000" } });
  for (const fetch of [
    async () => { throw new Error("durable object unavailable"); },
    async (_input, init) => new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    }),
  ]) {
    const namespace = {
      idFromName: name => name,
      get: () => ({ fetch }),
    };
    const handler = createHandler({
      fetchImpl: async () => new Response("{}"),
      now: () => fixedNow,
      rateLimitProbeTimeoutMs: 5,
    });
    const response = await handler(request.clone(), environment(namespace));
    assert.equal(response.status, 503);
    const body = await response.json();
    assert.equal(body.service, "unavailable");
    assert.equal(body.abuse_control.ready, false);
  }
});

test("FF-BUG-010 an unavailable abuse-control binding fails closed with a bounded response", async () => {
  const brokenNamespace = {
    idFromName() { throw new Error("binding unavailable"); },
    get() { throw new Error("binding unavailable"); },
  };
  const handler = createHandler({ fetchImpl: async () => new Response("{}"), now: () => fixedNow });
  const response = await handler(awardRequest("catalysis"), environment(brokenNamespace));
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: { code: "service_unavailable" } });
  assert.equal(response.headers.get("access-control-allow-origin"), "http://localhost:8000");
});
