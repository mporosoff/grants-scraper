import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createHandler, storeSnapshot } from "../../workers/award-api/src/index.js";
import {
  AWARD_ORDERING_VERSION,
  SNAPSHOT_BATCH_SIZE,
  SNAPSHOT_FACET_KEY_MAX_LENGTH,
  aggregateSnapshotAwards,
  buildAwardSnapshot,
  compareAwardsByRecency,
  programDescriptors,
  publicSnapshot,
  snapshotPage,
  snapshotSourceBatch,
} from "../../workers/award-api/src/snapshot.js";

const root = new URL("../../", import.meta.url);

function award(index, source = "NSF", overrides = {}) {
  const day = String((index % 28) + 1).padStart(2, "0");
  return {
    schema_version: 1,
    source,
    award_id: `${source}-${String(index).padStart(3, "0")}`,
    title: `${source} project ${index}`,
    award_date: `2026-08-${day}`,
    project_start: "2025-01-01",
    award_year: 2026,
    institution: { name: "Test University", normalized_name: "Test University", identifiers: { ror: "https://ror.org/012345678" } },
    principal_investigators: [{ name: `Investigator ${index % 3} Person`, source_person_id: `${source}-person-${index % 3}` }],
    program_name: `Program ${index % 2}`,
    subagency: `${source} Directorate`,
    program_codes: [`${source}-P${index % 2}`],
    ...overrides,
  };
}

function sourcePayload(source, awards, { complete = true, status = "" } = {}) {
  if (status) return { source, status, error: { code: status === "rate_limited" ? "rate_limited" : "source_unavailable" } };
  return {
    source,
    adapter_version: "test-1",
    results: awards,
    total_count: complete ? awards.length : null,
    upstream_total_count: awards.length,
    raw_record_count: awards.length,
    upstream_pages: Math.max(1, Math.ceil(awards.length / 25)),
    safety_bound_reached: !complete,
    has_more: !complete,
    retrieved_at: "2026-08-27T12:00:00.000Z",
  };
}

function snapshot(sourcePayloads, sources = Object.keys(sourcePayloads)) {
  return buildAwardSnapshot({
    snapshotId: "a".repeat(64),
    queryId: "b".repeat(64),
    asOf: "2026-08-27T12:00:00.000Z",
    request: { sources, criteria: { topic: "test" }, ordering_version: AWARD_ORDERING_VERSION },
    sourcePayloads,
  });
}

test("Unit B exact boundaries page without truncation, duplication, or empty final pages", () => {
  for (const count of [0, 1, 9, 10, 11, 25, 26, 50, 51]) {
    const awards = Array.from({ length: count }, (_, index) => award(index));
    const value = snapshot({ NSF: sourcePayload("NSF", awards) }, ["NSF"]);
    assert.equal(value.completeness, "complete", `count ${count}`);
    assert.equal(value.exact_total, count, `count ${count}`);
    assert.equal(value.at_least, count, `count ${count}`);
    const pages = Math.max(1, Math.ceil(count / 10));
    const seen = [];
    for (let page = 1; page <= pages; page += 1) {
      const payload = snapshotPage(value, { page, pageSize: 10, facet: { type: "all", key: "" } });
      assert.equal(payload.pagination.page_count, pages);
      assert.ok(payload.batches.every(batch => batch.actual_added <= SNAPSHOT_BATCH_SIZE));
      seen.push(...payload.batches.flatMap(batch => batch.results.map(item => `${item.source}:${item.award_id}`)));
    }
    assert.equal(seen.length, count);
    assert.equal(new Set(seen).size, count);
    assert.equal(snapshotPage(value, { page: pages + 1, pageSize: 10, facet: { type: "all", key: "" } }), null);
  }
});

test("Unit B hydrates each requested agency independently in batches no larger than 25", () => {
  const sourcePayloads = Object.fromEntries(["NSF", "NIH", "DOE", "DOD"].map(source => [
    source,
    sourcePayload(source, Array.from({ length: 51 }, (_, index) => award(index, source))),
  ]));
  const value = snapshot(sourcePayloads);
  const initial = publicSnapshot(value).initial_batches;
  assert.deepEqual(initial.map(batch => [batch.source, batch.actual_added]), [["NSF", 25], ["NIH", 25], ["DOE", 25], ["DOD", 25]]);
  for (const source of ["NSF", "NIH", "DOE", "DOD"]) {
    const second = snapshotSourceBatch(value, { source, offset: 25, facet: { type: "all", key: "" } });
    const final = snapshotSourceBatch(value, { source, offset: 50, facet: { type: "all", key: "" } });
    assert.equal(second.actual_added, 25);
    assert.equal(final.actual_added, 1);
    assert.equal(final.loaded_through, 51);
    assert.equal(final.source_total, 51);
    assert.equal(final.additional_available, false);
  }
});

test("Unit B ordering uses award/action date, project start, year, missing-last, then stable source and ID ties", () => {
  const values = [
    award(1, "NIH", { award_id: "Z", award_date: "", project_start: "", award_year: null }),
    award(2, "DOE", { award_id: "D", award_date: "", project_start: "2026-06-01", award_year: 2026 }),
    award(3, "NSF", { award_id: "B", award_date: "2026-07-01", project_start: "2020-01-01" }),
    award(4, "NIH", { award_id: "A", award_date: "2026-07-01", project_start: "2026-01-01" }),
    award(5, "NSF", { award_id: "A", award_date: "", project_start: "", award_year: 2025 }),
  ].sort(compareAwardsByRecency);
  assert.deepEqual(values.map(awardKey => `${awardKey.source}:${awardKey.award_id}`), ["NIH:A", "NSF:B", "DOE:D", "NSF:A", "NIH:Z"]);
});

test("Unit B aggregates and investigator/program facets are computed from the full snapshot, not the visible page", () => {
  const awards = Array.from({ length: 26 }, (_, index) => award(index));
  const value = snapshot({ NSF: sourcePayload("NSF", awards) }, ["NSF"]);
  const first = snapshotPage(value, { page: 1, pageSize: 10, facet: { type: "all", key: "" } });
  assert.equal(first.aggregate.project_count, 26);
  assert.equal(first.batches.flatMap(batch => batch.results).length, 10);
  assert.equal(first.aggregate.project_count, 26);
  assert.equal(first.base_aggregate, undefined);
  const investigator = first.aggregate.investigators[0];
  const investigatorPage = snapshotPage(value, { page: 1, pageSize: 10, facet: { type: "investigator", key: investigator.identity_key } });
  assert.equal(investigatorPage.aggregate.project_count, investigator.projects);
  assert.equal(investigatorPage.facet.label, investigator.name);
  const program = first.aggregate.programs[0];
  const programPage = snapshotPage(value, { page: 1, pageSize: 10, facet: { type: "program", key: program.key } });
  assert.equal(programPage.aggregate.project_count, program.projects);
  assert.equal(programPage.base_aggregate.project_count, 26);
});

test("Unit B exposes every retained DoD Assistance Listing as a distinct selectable program facet", () => {
  const dodAward = award(2, "DOD", {
    subagency: "Department of the Air Force",
    program_name: "Air Force Defense Research Sciences Program",
    program_codes: ["12.800", "12.810", "12.800"],
  });
  const olderTitledAward = award(1, "DOD", {
    subagency: "Department of the Air Force",
    program_name: "Other Defense Program",
    program_codes: ["12.810"],
  });
  const direct = programDescriptors(dodAward);
  assert.equal(direct.find(program => program.query === "12.810").leaf_label,
    "Assistance Listing 12.810", "a secondary listing remains explicit when that award has no title for it");

  const value = snapshot({ DOD: sourcePayload("DOD", [dodAward, olderTitledAward]) }, ["DOD"]);
  const programs = value.base_aggregate.programs;

  assert.equal(value.base_aggregate.program_count, 2);
  assert.deepEqual(programs.map(program => program.query).sort(), ["12.800", "12.810"]);
  assert.deepEqual(programs.map(program => program.source_codes), [["12.800"], ["12.810"]]);
  assert.equal(programs.find(program => program.query === "12.800").leaf_label,
    "Air Force Defense Research Sciences Program (12.800)");
  assert.equal(programs.find(program => program.query === "12.810").leaf_label,
    "Other Defense Program (12.810)", "a later available official title upgrades the shared code facet");
  assert.equal(programs.find(program => program.query === "12.800").projects, 1);
  assert.equal(programs.find(program => program.query === "12.810").projects, 2);
  assert.equal(new Set(programs.map(program => program.key)).size, 2);

  for (const program of programs) {
    const page = snapshotPage(value, {
      page: 1,
      pageSize: 10,
      facet: { type: "program", key: program.key },
    });
    assert.equal(page.facet.label, program.label);
    const expectedIds = program.query === "12.810"
      ? [dodAward.award_id, olderTitledAward.award_id]
      : [dodAward.award_id];
    assert.deepEqual(page.batches.flatMap(batch => batch.results.map(item => item.award_id)), expectedIds);
  }
});

test("Unit B preserves complete opaque program facet keys through page and batch validation", async () => {
  class MemoryCache {
    constructor() { this.values = new Map(); }
    async match(request) { return this.values.get(request.url)?.clone() || null; }
    async put(request, response) { this.values.set(request.url, response.clone()); }
  }
  const longParent = `Parent ${"a".repeat(293)}`;
  const longLeaf = `Program ${"b".repeat(292)}`;
  const value = snapshot({
    NSF: sourcePayload("NSF", [award(1, "NSF", { subagency: longParent, program_name: longLeaf })]),
  }, ["NSF"]);
  const program = value.base_aggregate.programs[0];
  assert.ok(program.key.length > 300);
  assert.ok(program.key.length <= SNAPSHOT_FACET_KEY_MAX_LENGTH);
  const facet = { type: "program", key: program.key };
  assert.equal(snapshotPage(value, { page: 1, pageSize: 10, facet }).facet.key, program.key);
  assert.equal(snapshotSourceBatch(value, { source: "NSF", offset: 0, facet }).facet.key, program.key);

  const cache = new MemoryCache();
  await storeSnapshot(cache, value, 3600);
  const handler = createHandler({ cache, fetchImpl: async () => { throw new Error("unexpected upstream request"); } });
  const env = {
    AWARD_API_ENABLED: "true",
    CACHE_TTL_SECONDS: "3600",
    MAX_SOURCE_RESULTS: "25",
    AWARD_SOURCE_RATE_LIMIT: "12",
    ROR_SEARCH_RATE_LIMIT: "60",
    ROR_RESOLVE_RATE_LIMIT: "20",
    AWARD_RATE_LIMIT_SECRET: "unit-b-facet-rate-limit-secret",
    AWARD_RATE_LIMITER: {
      idFromName: value => value,
      get: () => ({ fetch: async () => new Response(JSON.stringify({ success: true }), { headers: { "Content-Type": "application/json" } }) }),
    },
  };
  const request = (path, body) => new Request(`https://award.test${path}`, {
    method: "POST",
    headers: { Origin: "https://mporosoff.github.io", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const pageResponse = await handler(request("/awards/snapshots/page", {
    snapshot_id: value.snapshot_id, page: 1, page_size: 10, facet,
  }), env);
  assert.equal(pageResponse.status, 200);
  assert.equal((await pageResponse.json()).facet.key, program.key);
  const batchResponse = await handler(request("/awards/snapshots/batch", {
    snapshot_id: value.snapshot_id, source: "NSF", offset: 0, facet,
  }), env);
  assert.equal(batchResponse.status, 200);
  assert.equal((await batchResponse.json()).facet.key, program.key);
});

test("Unit B partial semantics never invent an exact total and a successor retains successful sources", () => {
  const nsf = sourcePayload("NSF", [award(1, "NSF")]);
  const failedNih = sourcePayload("NIH", [], { status: "unavailable" });
  const first = snapshot({ NSF: nsf, NIH: failedNih }, ["NSF", "NIH"]);
  assert.equal(first.completeness, "partial");
  assert.equal(first.exact_total, null);
  assert.equal(first.at_least, 1);
  assert.equal(first.sources.find(source => source.source === "NIH").status, "unavailable");
  const timedOutDoe = snapshot({
    NSF: nsf,
    DOE: { source: "DOE", status: "unavailable", error: { code: "source_timeout" } },
  }, ["NSF", "DOE"]);
  assert.equal(timedOutDoe.completeness, "partial");
  assert.equal(timedOutDoe.exact_total, null);
  assert.equal(timedOutDoe.at_least, 1);
  assert.deepEqual(timedOutDoe.sources.find(source => source.source === "DOE"), {
    source: "DOE",
    status: "unavailable",
    result_count: 0,
    total_count: null,
    error: { code: "source_timeout" },
  });
  const recoveredNih = sourcePayload("NIH", [award(2, "NIH")]);
  const successor = snapshot({ NSF: { ...first.source_metadata.NSF, results: first.awards.filter(item => item.source === "NSF") }, NIH: recoveredNih }, ["NSF", "NIH"]);
  assert.equal(successor.completeness, "complete");
  assert.deepEqual(successor.awards.map(item => `${item.source}:${item.award_id}`).sort(), ["NIH:NIH-002", "NSF:NSF-001"]);
  const upstreamLimited = snapshot({ DOE: { source: "DOE", status: "unavailable", error: { code: "source_rate_limited" } } }, ["DOE"]);
  assert.equal(upstreamLimited.sources[0].status, "rate_limited");
  const unverifiedTotal = snapshot({ NSF: { source: "NSF", results: [award(3, "NSF")], has_more: false } }, ["NSF"]);
  assert.equal(unverifiedTotal.completeness, "partial");
  assert.equal(unverifiedTotal.exact_total, null);
});

test("Unit B Worker serves direct pages and a failed-source retry creates a retained-source successor", async () => {
  class MemoryCache {
    constructor() { this.values = new Map(); }
    async match(request) { return this.values.get(request.url)?.clone() || null; }
    async put(request, response) { this.values.set(request.url, response.clone()); }
  }
  const cache = new MemoryCache();
  const nih = sourcePayload("NIH", [award(1, "NIH")]);
  const failedNsf = sourcePayload("NSF", [], { status: "unavailable" });
  const original = snapshot({ NSF: failedNsf, NIH: nih }, ["NSF", "NIH"]);
  original.runtime_request = {
    sources: ["NSF", "NIH"],
    publicCriteria: { topic: "test" },
    resolvedCriteria: { topic: "test" },
    limit: 25,
    offset: 0,
    scanAll: true,
    includeAbstracts: false,
  };
  await storeSnapshot(cache, original, 3600);
  const fetchImpl = async url => {
    assert.match(String(url), /api\.nsf\.gov\/services\/v1\/awards\.json/);
    return new Response(JSON.stringify({ response: { award: [{
      id: "NSF-RECOVERED",
      title: "Recovered NSF award",
      date: "08/27/2026",
      startDate: "01/01/2026",
      expDate: "12/31/2028",
      awardeeName: "Test University",
      awardeeStateCode: "NY",
      awardeeCountryCode: "US",
      pdPIName: "Recovered Person",
      fundProgramName: "Recovered Program",
    }], pagination: { totalCount: 1 } } }), { headers: { "Content-Type": "application/json" } });
  };
  const env = {
    AWARD_API_ENABLED: "true",
    CACHE_TTL_SECONDS: "3600",
    MAX_SOURCE_RESULTS: "25",
    AWARD_SOURCE_RATE_LIMIT: "12",
    ROR_SEARCH_RATE_LIMIT: "60",
    ROR_RESOLVE_RATE_LIMIT: "20",
    AWARD_RATE_LIMIT_SECRET: "unit-b-rate-limit-secret",
    AWARD_RATE_LIMITER: {
      idFromName: value => value,
      get: () => ({ fetch: async () => new Response(JSON.stringify({ success: true }), { headers: { "Content-Type": "application/json" } }) }),
    },
  };
  const handler = createHandler({ cache, fetchImpl, now: () => new Date("2026-08-27T12:05:00.000Z") });
  const request = (path, body) => new Request(`https://award.test${path}`, {
    method: "POST",
    headers: { Origin: "https://mporosoff.github.io", "Content-Type": "application/json", "CF-Connecting-IP": "192.0.2.20" },
    body: JSON.stringify(body),
  });
  const completeRetry = await handler(request("/awards/snapshots/retry", {
    snapshot_id: original.snapshot_id,
    source: "NIH",
  }), env);
  assert.equal(completeRetry.status, 409);
  assert.equal((await completeRetry.json()).error.code, "source_not_retryable");
  const direct = await handler(request("/awards/snapshots/page", {
    snapshot_id: original.snapshot_id,
    page: 1,
    page_size: 10,
    facet: { type: "all", key: "" },
  }), env);
  assert.equal(direct.status, 200);
  assert.equal((await direct.json()).at_least, 1);
  const retry = await handler(request("/awards/snapshots/retry", { snapshot_id: original.snapshot_id, source: "NSF" }), env);
  const successor = await retry.json();
  assert.equal(retry.status, 200, JSON.stringify(successor));
  assert.equal(successor.predecessor_snapshot_id, undefined, "the public response does not expose internal cache state");
  assert.notEqual(successor.snapshot_id, original.snapshot_id);
  assert.equal(successor.as_of, "2026-08-27T12:05:00.000Z");
  assert.equal(successor.retry.status, "recovered");
  assert.deepEqual(successor.retry.retained_sources, ["NIH"]);
  assert.equal(successor.exact_total, 2);
  const successorPage = await handler(request("/awards/snapshots/page", {
    snapshot_id: successor.snapshot_id,
    page: 1,
    page_size: 10,
    facet: { type: "all", key: "" },
  }), env);
  const successorPayload = await successorPage.json();
  assert.deepEqual(successorPayload.batches.flatMap(batch => batch.results).map(item => item.source).sort(), ["NIH", "NSF"]);
});

test("Unit B active page and Worker expose snapshot-only architecture and direct navigation controls", async () => {
  const [page, app, worker, config] = await Promise.all([
    readFile(new URL("funded_awards.html", root), "utf8"),
    readFile(new URL("assets/institutional-intelligence-snapshots.js", root), "utf8"),
    readFile(new URL("workers/award-api/src/index.js", root), "utf8"),
    Promise.all([
      readFile(new URL("assets/award-api-config.js", root), "utf8"),
      readFile(new URL("workers/award-api/wrangler.jsonc", root), "utf8"),
    ]).then(values => values.join("\n")),
  ]);
  assert.match(page, /institutional-intelligence-snapshots\.js/);
  assert.match(page, /id="ii-page-size"[\s\S]*value="10"[\s\S]*value="25"[\s\S]*value="50"/);
  assert.match(page, /id="ii-card-page-numbers"/);
  assert.match(page, /Clear active drill-down/);
  assert.doesNotMatch(app, /apiConfig\.searchUrl|awards\/search/);
  assert.match(app, /snapshotPageUrl/);
  assert.match(app, /data-ii-load-source/);
  assert.match(app, /data-ii-retry-source/);
  assert.match(app, /awardProduct\.enrichmentWarnings\(source\)/);
  assert.match(app, /source\.health\?\.status === "degraded"/);
  assert.match(app, /Base award records remain available when optional public details cannot be loaded/);
  const bodyRead = app.indexOf("await response.json().catch(() => null)");
  const timeoutRelease = app.indexOf("clearTimeout(timer)", bodyRead);
  assert.ok(bodyRead > -1 && timeoutRelease > bodyRead, "the bounded request timer must remain active while the response body is read");
  assert.match(worker, /failure_policy: "successful-sources-retained-retry-creates-successor"/);
  assert.match(worker, /maximum_snapshot_create_subrequests: 141/);
  assert.match(config, /snapshotBatchUrl/);
  assert.match(config, /"cpu_ms": 250/);
});

test("the integrated A-C browser release uses one fresh cache key for every changed served asset", async () => {
  const [fundedAwards, fundingFinder, teamMatch, appCss, appJs] = await Promise.all([
    readFile(new URL("funded_awards.html", root), "utf8"),
    readFile(new URL("match_explorer.html", root), "utf8"),
    readFile(new URL("team_match.html", root), "utf8"),
    readFile(new URL("assets/app.css", root)),
    readFile(new URL("assets/app.js", root)),
  ]);
  const releaseKey = "post-phase4-abc-20260829";
  const alertStylesReleaseKey = "ui-runtime-20260903";
  const dodReleaseKey = "dod-awards-20260903";
  const dodStatusReleaseKey = "dod-awards-20260904";
  const dodBrowserReleaseKey = "dod-browser-20260904-r2";
  const fundedAwardsStylesReleaseKey = "source-pill-20260904";
  const appJsHash = createHash("sha256").update(appJs).digest("hex");
  for (const asset of [
    "alerts.js",
    "award-api-config.js",
  ]) assert.match(fundedAwards, new RegExp(`${asset.replace(".", "\\.")}\\?v=${releaseKey}`));
  assert.match(fundedAwards, new RegExp(`alerts\\.css\\?v=${alertStylesReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`funded-awards-core\\.js\\?v=${dodStatusReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`funded-awards\\.js\\?v=${dodBrowserReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`institutional-intelligence-core\\.js\\?v=${dodReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`institutional-intelligence-snapshots\\.js\\?v=${dodBrowserReleaseKey}`));
  assert.match(fundedAwards, /app\.css\?v=presentation-cleanup-20260830/);
  assert.match(fundedAwards, /ai-gateway-config\.js\?v=hosted-ai-20260831/);
  assert.match(fundedAwards, new RegExp(`ai-provider\\.js\\?v=${dodReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`institutional-intelligence\\.css\\?v=${dodReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`funded-awards\\.css\\?v=${fundedAwardsStylesReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`award-links\\.js\\?v=${dodReleaseKey}`));
  assert.match(fundedAwards, new RegExp(`site-help\\.js\\?v=${dodReleaseKey}`));
  assert.match(fundingFinder, new RegExp(`alerts\\.css\\?v=${alertStylesReleaseKey}`));
  assert.match(fundingFinder, new RegExp(`alerts\\.js\\?v=${releaseKey}`));
  assert.match(fundingFinder, new RegExp(`site-help\\.js\\?v=${dodReleaseKey}`));
  assert.match(fundingFinder, new RegExp(`ai-provider\\.js\\?v=${dodReleaseKey}`));
  assert.match(fundingFinder, new RegExp(`award-links\\.js\\?v=${dodReleaseKey}`));
  const opportunityTeamGeneration = fundingFinder.match(/meta name="opportunity-team-generation" content="([a-f0-9]{64})"/)?.[1];
  assert.ok(opportunityTeamGeneration);
  const appCssHash = createHash("sha256").update(appCss).digest("hex");
  assert.match(fundingFinder, new RegExp(`app\\.css\\?v=${appCssHash}`));
  assert.match(fundingFinder, new RegExp(`app\\.js\\?v=${appJsHash}`));
  assert.match(teamMatch, new RegExp(`app\\.css\\?v=${appCssHash}`));
  assert.match(fundingFinder, /ai-gateway-config\.js\?v=hosted-ai-20260831/);
  assert.match(fundingFinder, /result-workflow\.js\?v=ai-feedback-20260901/);
});

test("Unit B aggregate helper deduplicates source plus award ID", () => {
  const duplicate = award(1);
  const aggregate = aggregateSnapshotAwards([duplicate, { ...duplicate }, award(1, "NIH")]);
  assert.equal(aggregate.project_count, 2);
  assert.deepEqual(aggregate.agency_totals, [{ source: "NSF", projects: 1 }, { source: "NIH", projects: 1 }, { source: "DOE", projects: 0 }, { source: "DOD", projects: 0 }]);
  const value = snapshot({ NSF: sourcePayload("NSF", [duplicate, { ...duplicate }]) }, ["NSF"]);
  assert.equal(value.sources[0].result_count, 1);
  const batch = snapshotSourceBatch(value, { source: "NSF", offset: 1, facet: { type: "all", key: "" } });
  assert.equal(batch.actual_added, 0);
  assert.equal(batch.additional_available, false);
});

test("Unit B 2,200-award architecture stays bounded for the deployed Workers Paid target", () => {
  const sourcePayloads = Object.fromEntries(["NSF", "NIH", "DOE", "DOD"].map(source => [
    source,
    sourcePayload(source, Array.from({ length: 550 }, (_, index) => award(index, source, {
      program_name: `Program ${index % 20}`,
      program_codes: [`${source}-P${index % 20}`],
    }))),
  ]));
  const value = snapshot(sourcePayloads);
  const createPayload = publicSnapshot(value);
  const pagePayload = snapshotPage(value, { page: 1, pageSize: 50, facet: { type: "all", key: "" } });

  assert.equal(value.exact_total, 2_200);
  assert.equal(createPayload.base_aggregate, undefined, "the create response must not duplicate the page aggregate");
  assert.ok(pagePayload.aggregate.investigators.every(item => item.award_keys === undefined));
  assert.ok(pagePayload.aggregate.programs.every(item => item.award_keys === undefined));
  assert.ok(Buffer.byteLength(JSON.stringify(value)) < 2 * 1024 * 1024);
  assert.ok(Buffer.byteLength(JSON.stringify(createPayload)) < 128 * 1024);
  assert.ok(Buffer.byteLength(JSON.stringify(pagePayload)) < 2 * 1024 * 1024);
});
