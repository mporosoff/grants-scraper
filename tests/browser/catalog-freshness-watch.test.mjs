import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";
import { sha256Hex } from "../../workers/alerts/src/crypto.js";
import { createHandler } from "../../workers/alerts/src/index.js";
import {
  catalogWatchHealth, isCatalogWatchSlot, observeCatalog, runCatalogWatch,
} from "../../workers/alerts/src/catalog-watch.js";

const RELEASE = "a".repeat(40);
const CANDIDATE = "b".repeat(64);

function localD1() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../../workers/alerts/migrations/0008_catalog_watch.sql", import.meta.url), "utf8"));
  return { prepare: sql => ({
    async first() { return db.prepare(sql).get() ?? null; },
    bind(...args) {
      return { async first() {
        const bindings = Object.fromEntries(args.map((value, i) => [String(i + 1), value]));
        return db.prepare(sql).get(bindings) ?? null;
      } };
    },
  }) };
}

async function publicAssets(sourceTime, { hash = null, stamp = RELEASE, fail = false, pipelineTime = "2026-11-16T23:00:00Z" } = {}) {
  const metadata = "/* Generated with data/opportunities.js. Do not edit by hand. */\n"
    + "globalThis.GRANT_CATALOG_METADATA=" + JSON.stringify({
      schema_version: 1, generated_at: sourceTime, pipeline_generated_at: pipelineTime, record_count: 1250,
    }) + ";\n";
  const receipt = { schema_version: 1, publication_sha: RELEASE, candidate_id: CANDIDATE,
    candidate_hashes: { "data/catalog-metadata.js": hash ?? await sha256Hex(metadata) } };
  const assets = new Map([
    ["/grants-scraper/pages-release-sha.txt", stamp + "\n"],
    ["/grants-scraper/release/publication.json", JSON.stringify(receipt)],
    ["/grants-scraper/data/catalog-metadata.js", metadata],
  ]);
  return async (url, options) => {
    assert.equal(url.hostname, "mporosoff.github.io");
    assert.equal(options.redirect, "error");
    assert.ok(assets.has(url.pathname));
    return fail ? new Response("", { status: 503 }) : new Response(assets.get(url.pathname));
  };
}

test("the watchdog verifies exact served metadata and judges the original source clock", async () => {
  const earlier = await publicAssets("2026-11-15T19:54:40.772589Z");
  assert.equal((await observeCatalog(new Date("2026-11-16T22:59:00Z"), earlier)).freshness, "current");
  const result = await observeCatalog(new Date("2026-11-16T23:00:00Z"), earlier);
  assert.equal(result.availability, "verified");
  assert.equal(result.freshness, "stale");
  assert.equal(result.publication_sha, RELEASE);
  assert.equal(result.record_count, 1250);
  const priorWindow = await publicAssets("2026-11-16T10:16:00Z");
  assert.equal((await observeCatalog(new Date("2026-11-16T23:00:00Z"), priorWindow)).freshness, "stale");
  const newWindow = await publicAssets("2026-11-16T10:17:00Z");
  assert.equal((await observeCatalog(new Date("2026-11-16T23:00:00Z"), newWindow)).freshness, "current");
  const summerBefore = await publicAssets("2026-07-10T10:17:00Z");
  assert.equal((await observeCatalog(new Date("2026-07-11T21:59:00Z"), summerBefore)).freshness, "current");
  assert.equal((await observeCatalog(new Date("2026-07-11T22:00:00Z"), summerBefore)).freshness, "stale");
});

test("mixed public releases and HTTP failures cannot establish freshness", async () => {
  for (const options of [{ stamp: "c".repeat(40) }, { hash: "d".repeat(64) }, { fail: true }]) {
    const reader = await publicAssets("2026-11-16T20:00:00Z", options);
    const result = await observeCatalog(new Date("2026-11-16T23:00:00Z"), reader);
    assert.equal(result.availability, options.fail ? "unavailable" : "unverified");
    assert.equal(result.freshness, "unknown");
    assert.equal(result.candidate_id, null);
  }
});

test("independent cron observations alert once per open problem and reject out-of-order writes", async () => {
  const db = localD1();
  const stale = await publicAssets("2026-11-15T19:54:40Z");
  const down = await publicAssets("2026-11-15T19:54:40Z", { fail: true });
  const current = await publicAssets("2026-11-16T20:00:00Z");
  const alerts = [];
  const observe = async (stamp, reader) => {
    const now = new Date(stamp);
    const event = { cron: "2-57/5 * * * *", scheduledTime: now.getTime() };
    assert.equal(isCatalogWatchSlot(event), true);
    await runCatalogWatch(event, db, { now, fetchImpl: reader, log: msg => alerts.push(JSON.parse(msg)) });
  };

  await observe("2026-11-16T23:52:00Z", stale);
  await observe("2026-11-17T00:52:00Z", down);
  await observe("2026-11-17T00:52:00Z", current);
  await observe("2026-11-17T01:52:00Z", stale);
  assert.deepEqual(alerts.map(alert => alert.event), ["catalog_freshness_missed", "catalog_publication_unverified"]);
  assert.equal((await catalogWatchHealth(db, new Date("2026-11-17T02:00:00Z"))).stale_since, "2026-11-16T23:52:00.000Z");
  await observe("2026-11-17T02:52:00Z", current);
  await observe("2026-11-17T01:52:00Z", stale);
  const recovered = await catalogWatchHealth(db, new Date("2026-11-17T03:00:00Z"));
  assert.equal(recovered.stale_since, null);
  assert.equal(recovered.publication_problem_since, null);
  assert.equal(recovered.freshness, "current");
  assert.equal((await catalogWatchHealth(db, new Date("2026-11-17T05:30:00Z"))).status, "observation_overdue");
  assert.equal(isCatalogWatchSlot({ cron: "15 13 * * *", scheduledTime: Date.parse("2026-11-16T23:52:00Z") }), false);
});

test("the public health route exposes independent monitor state before and after its first verified observation", async () => {
  const db = localD1();
  const now = new Date("2026-11-16T23:52:00Z");
  const handler = createHandler({ now: () => now });
  const endpoint = "https://funding-finder-alerts.urochestercheme.workers.dev/catalog-health";
  async function check() {
    return handler(new Request(endpoint), { ALERTS_DB: db });
  }
  assert.equal((await check()).status, 503);
  await runCatalogWatch({ scheduledTime: now.getTime() }, db, {
    now, fetchImpl: await publicAssets("2026-11-16T23:30:00Z"),
  });
  const response = await check();
  assert.equal(response.status, 200);
  assert.equal((await response.json()).freshness, "current");
});
