import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  createHybridSnapshot,
  isLocalDodSnapshotId,
  loadLocalSnapshot,
  localSnapshotPage,
  mergeSearchPayload,
  persistLocalSnapshot,
  replaceHybridSnapshotSource,
  searchDodFromBrowser,
} from "../../assets/dod-awards-browser.mjs";
import { buildAwardSnapshot, publicSnapshot } from "../../workers/award-api/src/snapshot.js";

const root = new URL("../../", import.meta.url);
const [searchFixture, detailFixture, rorFixture] = await Promise.all([
  readFile(new URL("tests/fixtures/awards/dod_search_results.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/dod_award_detail.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/ror_aliases.json", root), "utf8").then(JSON.parse),
]);

function fixtureFetch(calls = []) {
  return async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("/search/spending_by_award/")) {
      return new Response(JSON.stringify(searchFixture), {
        status: 200,
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    }
    if (String(url).includes("/api/v2/awards/ASST_NON_FA9550261B195_097/")) {
      return new Response(JSON.stringify(detailFixture), {
        status: 200,
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    }
    throw new Error(`Unexpected browser-side request: ${url}`);
  };
}

function fixedNow() {
  return new Date("2026-09-04T12:00:00.000Z");
}

function memoryCache() {
  const values = new Map();
  return {
    values,
    async match(request) {
      return values.get(request.url || String(request))?.clone() || undefined;
    },
    async put(request, response) {
      values.set(request.url || String(request), response.clone());
    },
    async delete(request) {
      return values.delete(request.url || String(request));
    },
  };
}

function nsfAward() {
  return {
    schema_version: 1,
    award_id: "2605508",
    source_record_ids: ["2605508"],
    source: "NSF",
    agency: "National Science Foundation",
    subagency: "Directorate for Engineering",
    program_name: "Chemical, Bioengineering, Environmental and Transport Systems",
    program_codes: ["764300"],
    opportunity_numbers: [],
    activity_code: null,
    funding_mechanism: "Standard Grant",
    title: "Earlier NSF project",
    abstract: "Public abstract",
    award_date: "2025-01-15",
    project_start: "2025-01-15",
    project_end: "2028-01-14",
    award_year: 2025,
    total_award: 500000,
    award_amount_basis: "award_amount",
    institution: { name: "University of Rochester", normalized_name: "University of Rochester", identifiers: {} },
    organization_department: null,
    principal_investigators: [],
    program_contacts: [],
    official_award_url: "https://www.nsf.gov/awardsearch/showAward?AWD_ID=2605508",
    annual_support: [],
    source_provenance: {
      source_url: "https://www.nsf.gov/awardsearch/showAward?AWD_ID=2605508",
      retrieved_at: "2026-09-04T12:00:00.000Z",
      source_record_id: "2605508",
      adapter_version: "1.0.0",
    },
  };
}

test("browser DoD transport reuses the normalized adapter over official CORS requests", async () => {
  const calls = [];
  const payload = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
    limit: 1,
    fetchImpl: fixtureFetch(calls),
    now: fixedNow,
  });
  assert.equal(payload.source, "DOD");
  assert.equal(payload.results.length, 1);
  assert.equal(payload.results[0].award_id, "FA9550261B195");
  assert.deepEqual(payload.results[0].program_codes, ["12.800"]);
  assert.deepEqual(payload.results[0].opportunity_numbers, ["NOFOAFRLAFOSR20250002"]);
  assert.equal(payload.results[0].award_amount_basis, "total_obligation");
  assert.equal(calls.length, 2);
  assert.ok(calls.every(call => call.options.credentials === "omit"));
  assert.ok(calls.every(call => call.options.referrerPolicy === "no-referrer"));
});

test("browser DoD transport preserves unsupported and unavailable source isolation", async () => {
  const unsupported = await searchDodFromBrowser({ pi: "Researcher Name" }, {
    fetchImpl: fixtureFetch(),
    now: fixedNow,
  });
  assert.deepEqual(unsupported, {
    source: "DOD",
    status: "unsupported",
    error: { code: "source_query_unsupported" },
  });

  const unavailable = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
    fetchImpl: async () => { throw new Error("offline"); },
    now: fixedNow,
  });
  assert.deepEqual(unavailable, {
    source: "DOD",
    status: "unavailable",
    error: { code: "source_unavailable" },
  });
});

test("restored ROR identities are revalidated from the official record before a DoD institution search", async () => {
  const calls = [];
  const rorOrganization = rorFixture.Caltech.items[0];
  const caltechSearch = structuredClone(searchFixture);
  caltechSearch.results[0]["Recipient Name"] = "CALIFORNIA INSTITUTE OF TECHNOLOGY";
  caltechSearch.results[0]["Recipient UEI"] = "";
  const payload = await searchDodFromBrowser({
    institution: "California Institute of Technology",
    institution_id: rorOrganization.id,
  }, {
    limit: 1,
    selectedInstitution: {
      id: rorOrganization.id,
      canonical_name: "Untrusted restored label",
      aliases: ["Untrusted alias"],
      acronyms: [],
      registryMetadataLoaded: false,
    },
    fetchImpl: async (url, options = {}) => {
      calls.push({ url: String(url), options });
      if (String(url) === "https://api.ror.org/v2/organizations/05dxps055") {
        return new Response(JSON.stringify(rorOrganization), {
          status: 200,
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }
      if (String(url).includes("/search/spending_by_award/")) {
        return new Response(JSON.stringify(caltechSearch), {
          status: 200,
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }
      if (String(url).includes("/api/v2/awards/ASST_NON_FA9550261B195_097/")) {
        return new Response(JSON.stringify(detailFixture), {
          status: 200,
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }
      throw new Error(`Unexpected browser-side request: ${url}`);
    },
    now: fixedNow,
  });
  assert.equal(calls[0].url, "https://api.ror.org/v2/organizations/05dxps055");
  assert.equal(payload.results.length, 1);
  assert.equal(payload.results[0].institution.normalized_name, "California Institute of Technology");
  assert.equal(payload.results[0].institution.identifiers.ror, rorOrganization.id);
});

test("browser DoD transport caches successful source and detail payloads for repeat views", async () => {
  const cache = memoryCache();
  const prior = globalThis.caches;
  Object.defineProperty(globalThis, "caches", {
    configurable: true,
    value: { open: async () => cache },
  });
  try {
    const calls = [];
    const options = { limit: 1, fetchImpl: fixtureFetch(calls), now: fixedNow };
    const first = await searchDodFromBrowser({ award_id: "FA9550261B195" }, options);
    const second = await searchDodFromBrowser({ award_id: "FA9550261B195" }, options);
    assert.equal(first.cache, "miss");
    assert.equal(second.cache, "hit");
    assert.equal(calls.length, 2, "the repeat view should reuse both normalized source and detail cache entries");
    assert.equal(cache.values.size, 2);
    assert.ok([...cache.values.values()].every(response => Number.isFinite(Number(response.headers.get("x-funding-finder-cached-at")))));

    for (const [key, response] of cache.values) {
      const headers = new Headers(response.headers);
      headers.set("X-Funding-Finder-Cached-At", String(Date.now() - 3_600_001));
      cache.values.set(key, new Response(await response.clone().arrayBuffer(), { headers }));
    }
    const afterExpiry = await searchDodFromBrowser({ award_id: "FA9550261B195" }, options);
    assert.equal(afterExpiry.cache, "miss");
    assert.equal(calls.length, 4, "expired source and detail entries must both be refreshed");
  } finally {
    if (prior === undefined) delete globalThis.caches;
    else Object.defineProperty(globalThis, "caches", { configurable: true, value: prior });
  }
});

test("standalone search merges browser DoD and Worker sources in requested source order", async () => {
  const dod = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
    limit: 1,
    fetchImpl: fixtureFetch(),
    now: fixedNow,
  });
  const request = { sources: ["NSF", "DOD"], criteria: { topic: "light" }, limit: 10, offset: 0 };
  const payload = mergeSearchPayload({
    request,
    workerPayload: {
      schema_version: 1,
      request: { ...request, sources: ["NSF"] },
      results: [nsfAward()],
      sources: [{ source: "NSF", status: "ok", result_count: 1, has_more: false }],
      pagination: { limit: 10, offset: 0 },
    },
    dodPayload: dod,
  });
  assert.deepEqual(payload.results.map(award => award.source), ["NSF", "DOD"]);
  assert.deepEqual(payload.sources.map(source => [source.source, source.status]), [["NSF", "ok"], ["DOD", "ok"]]);
  assert.equal(payload.sources[1].transport, "browser_direct_cors");
});

test("hybrid snapshots retain exact paging, source totals, recency, and DoD program facets", async () => {
  const workerFull = buildAwardSnapshot({
    snapshotId: "a".repeat(64),
    queryId: "b".repeat(64),
    asOf: "2026-09-04T12:00:00.000Z",
    request: { sources: ["NSF"], criteria: { topic: "light" } },
    sourcePayloads: {
      NSF: {
        source: "NSF",
        adapter_version: "1.0.0",
        retrieved_at: "2026-09-04T12:00:00.000Z",
        total_count: 1,
        has_more: false,
        safety_bound_reached: false,
        results: [nsfAward()],
      },
    },
  });
  const dod = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
    limit: 25,
    scanAll: true,
    fetchImpl: fixtureFetch(),
    now: fixedNow,
  });
  const hybrid = await createHybridSnapshot({
    request: { sources: ["NSF", "DOD"], criteria: { topic: "light" } },
    workerSnapshot: publicSnapshot(workerFull),
    dodPayload: dod,
  });
  assert.ok(isLocalDodSnapshotId(hybrid.snapshot.snapshot_id));
  assert.equal(hybrid.public.completeness, "complete");
  assert.equal(hybrid.public.exact_total, 2);
  assert.deepEqual(hybrid.public.sources.map(source => [source.source, source.result_count]), [["NSF", 1], ["DOD", 1]]);
  const page = localSnapshotPage(hybrid.snapshot, { page: 1, pageSize: 10, facet: { type: "all", key: "" } });
  assert.deepEqual(page.batches.flatMap(batch => batch.results)
    .sort((left, right) => left.snapshot_position - right.snapshot_position)
    .map(award => award.source), ["DOD", "NSF"]);
  const dodProgram = page.aggregate.programs.find(program => program.source === "DOD");
  assert.equal(dodProgram.query, "12.800");
  const facet = localSnapshotPage(hybrid.snapshot, {
    page: 1,
    pageSize: 10,
    facet: { type: "program", key: dodProgram.key },
  });
  assert.equal(facet.exact_total, 1);
  assert.equal(facet.batches.flatMap(batch => batch.results)[0].source, "DOD");
});

test("hybrid source replacement changes only the retried source and retains successful awards", async () => {
  const originalNsf = nsfAward();
  const workerFull = buildAwardSnapshot({
    snapshotId: "c".repeat(64),
    queryId: "d".repeat(64),
    asOf: "2026-09-04T12:00:00.000Z",
    request: { sources: ["NSF"], criteria: { topic: "light" } },
    sourcePayloads: {
      NSF: {
        source: "NSF",
        adapter_version: "1.0.0",
        retrieved_at: "2026-09-04T12:00:00.000Z",
        total_count: 1,
        has_more: false,
        safety_bound_reached: false,
        results: [originalNsf],
      },
    },
  });
  const dod = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
    limit: 25,
    scanAll: true,
    fetchImpl: fixtureFetch(),
    now: fixedNow,
  });
  const original = await createHybridSnapshot({
    request: { sources: ["NSF", "DOD"], criteria: { topic: "light" } },
    workerSnapshot: publicSnapshot(workerFull),
    dodPayload: dod,
  });
  const replacementNsf = {
    ...originalNsf,
    award_id: "2605509",
    source_record_ids: ["2605509"],
    title: "Replacement NSF project",
    source_provenance: { ...originalNsf.source_provenance, source_record_id: "2605509" },
  };
  const replacementFull = buildAwardSnapshot({
    snapshotId: "e".repeat(64),
    queryId: "f".repeat(64),
    asOf: "2026-09-04T12:05:00.000Z",
    request: { sources: ["NSF"], criteria: { topic: "light" } },
    sourcePayloads: {
      NSF: {
        source: "NSF",
        adapter_version: "1.0.0",
        retrieved_at: "2026-09-04T12:05:00.000Z",
        total_count: 1,
        has_more: false,
        safety_bound_reached: false,
        results: [replacementNsf],
      },
    },
  });
  const successor = await replaceHybridSnapshotSource({
    snapshot: original.snapshot,
    source: "NSF",
    sourceSnapshot: publicSnapshot(replacementFull),
  });
  assert.notEqual(successor.snapshot.snapshot_id, original.snapshot.snapshot_id);
  assert.deepEqual(successor.snapshot.awards.map(award => `${award.source}:${award.award_id}`).sort(), [
    "DOD:FA9550261B195",
    "NSF:2605509",
  ]);
  assert.equal(successor.snapshot.awards.some(award => award.award_id === "2605508"), false);
  assert.equal(successor.snapshot.sources.find(source => source.source === "DOD").status, "complete");
});

test("hybrid snapshots are session-restorable without becoming shared server snapshots", async () => {
  const values = new Map();
  const prior = globalThis.sessionStorage;
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    value: {
      getItem: key => values.get(key) || null,
      setItem: (key, value) => values.set(key, value),
      removeItem: key => values.delete(key),
    },
  });
  try {
    const dod = await searchDodFromBrowser({ award_id: "FA9550261B195" }, {
      limit: 25,
      scanAll: true,
      fetchImpl: fixtureFetch(),
      now: fixedNow,
    });
    const hybrid = await createHybridSnapshot({
      request: { sources: ["DOD"], criteria: { award_id: "FA9550261B195" } },
      dodPayload: dod,
    });
    assert.equal(persistLocalSnapshot(hybrid.snapshot), true);
    assert.equal(loadLocalSnapshot(hybrid.snapshot.snapshot_id)?.awards[0].award_id, "FA9550261B195");
  } finally {
    if (prior === undefined) delete globalThis.sessionStorage;
    else Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: prior });
  }
});
