import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import {
  DOD_ADAPTER_VERSION,
  DOD_CAPABILITIES,
  DOD_DETAIL_CACHE_TIMEOUT_MS,
  DOD_DETAIL_URL,
  DOD_MAX_UPSTREAM_PAGES,
  DOD_OPERATION_BUDGET_MS,
  DOD_SEARCH_REQUEST_TIMEOUT_MS,
  DOD_SEARCH_URL,
  DOD_SOURCE_WRAPPER_TIMEOUT_MS,
  buildDodRequest,
  normalizeDodAward,
  searchDod,
} from "../../workers/award-api/src/adapters/dod.js";
import { AwardSourceError } from "../../workers/award-api/src/http.js";
import { runSource } from "../../workers/award-api/src/index.js";
import { resolveInstitution } from "../../workers/award-api/src/institutions.js";

const root = new URL("../../", import.meta.url);
const [searchFixture, detailFixture, linksSource] = await Promise.all([
  readFile(new URL("tests/fixtures/awards/dod_search_results.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/dod_award_detail.json", root), "utf8").then(JSON.parse),
  readFile(new URL("assets/award-links.js", root), "utf8"),
]);
const fixedNow = () => new Date("2026-09-03T14:00:00.000Z");

function memoryCache() {
  const values = new Map();
  return {
    values,
    async match(request) {
      return values.get(request.url)?.clone();
    },
    async put(request, response) {
      values.set(request.url, response.clone());
    },
  };
}

function fixtureFetch({ detailFails = false, calls = [], searchPayload = searchFixture, detailPayload = detailFixture } = {}) {
  return async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).startsWith(DOD_DETAIL_URL)) {
      return detailFails
        ? new Response("unavailable", { status: 503 })
        : new Response(JSON.stringify(detailPayload), { headers: { "Content-Type": "application/json" } });
    }
    assert.equal(String(url), DOD_SEARCH_URL);
    return new Response(JSON.stringify(searchPayload), { headers: { "Content-Type": "application/json" } });
  };
}

test("DoD search uses only prime 04/05 assistance awards and supported exact filters", () => {
  assert.equal(DOD_ADAPTER_VERSION, "1.0.0");
  assert.equal(DOD_SEARCH_REQUEST_TIMEOUT_MS, 20_000);
  assert.equal(DOD_OPERATION_BUDGET_MS, 100_000);
  assert.equal(DOD_DETAIL_CACHE_TIMEOUT_MS, 2_000);
  assert.equal(DOD_SOURCE_WRAPPER_TIMEOUT_MS, 2_000);
  assert.ok(DOD_OPERATION_BUDGET_MS < 120_000);
  const institution = resolveInstitution({ id: "university-of-rochester" });
  const body = buildDodRequest({
    award_id: "fa9550261b195",
    topic: "multiscale transport",
    program: "12.800",
    year_start: 2025,
    year_end: 2026,
    _institution: institution,
  }, {
    page: 2,
    cursor: { last_record_unique_id: 4201, last_record_sort_value: "FA9550261B195" },
    now: fixedNow,
  });
  assert.equal(body.subawards, false);
  assert.equal(body.spending_level, "awards");
  assert.deepEqual(body.filters.award_type_codes, ["04", "05"]);
  assert.deepEqual(body.filters.agencies, [{ type: "awarding", tier: "toptier", name: "Department of Defense" }]);
  assert.deepEqual(body.filters.award_ids, ["FA9550261B195"]);
  assert.equal(body.filters.description, "multiscale transport");
  assert.deepEqual(body.filters.program_numbers, ["12.800"]);
  assert.equal(body.filters.recipient_search_text, undefined, "exact award lookup is validated locally without an alias-sensitive recipient query");
  assert.deepEqual(body.filters.time_period, [{
    start_date: "2025-01-01",
    end_date: "2026-12-31",
    date_type: "date_signed",
  }]);
  assert.equal(body.page, 2);
  assert.equal(body.sort, "Award ID");
  assert.equal(body.last_record_unique_id, 4201);
  assert.equal(body.last_record_sort_value, "FA9550261B195");

  const institutionBody = buildDodRequest({ _institution: institution }, { now: fixedNow });
  assert.deepEqual(institutionBody.filters.recipient_search_text, ["F27KDXZMF9Y8"]);

  assert.throws(
    () => buildDodRequest({}, { page: 2, now: fixedNow }),
    error => error instanceof AwardSourceError && error.code === "source_invalid_response",
  );

  for (const criteria of [
    { pi: "Jane Doe" },
    { program_officer: "Jane Doe" },
    { opportunity_number: "NOFOAFRLAFOSR20250002" },
    { program: "Defense Research Sciences" },
  ]) {
    assert.throws(
      () => buildDodRequest(criteria, { now: fixedNow }),
      error => error instanceof AwardSourceError && error.kind === "unsupported",
    );
  }
  assert.equal(DOD_CAPABILITIES.fields.abstract, "unavailable_at_source");
});

test("DoD reapplies the remaining operation budget to every USAspending page", async () => {
  const records = Array.from({ length: 25 }, (_, index) => ({
    ...structuredClone(searchFixture.results[0]),
    "Award ID": `FA9550BUDGET${String(index + 1).padStart(2, "0")}`,
    generated_internal_id: `ASST_NON_FA9550BUDGET${String(index + 1).padStart(2, "0")}_097`,
  }));
  let searchCalls = 0;
  let finalSignal = null;
  const fetchImpl = async (url, options = {}) => {
    assert.equal(String(url), DOD_SEARCH_URL);
    searchCalls += 1;
    if (searchCalls === 1) {
      return new Response(JSON.stringify({
        results: records,
        page_metadata: {
          page: 1,
          total: 50,
          hasNext: true,
          last_record_unique_id: 9100,
          last_record_sort_value: records.at(-1)["Award ID"],
        },
      }), { headers: { "Content-Type": "application/json" } });
    }
    finalSignal = options.signal;
    return new Promise((resolve, reject) => {
      const abort = () => reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
      if (finalSignal.aborted) abort();
      else finalSignal.addEventListener("abort", abort, { once: true });
    });
  };
  const clock = [0, 0, DOD_OPERATION_BUDGET_MS - 5];
  const started = performance.now();

  await assert.rejects(
    () => searchDod(fetchImpl, {}, {
      limit: 1,
      offset: 25,
      now: fixedNow,
      monotonicNow: () => clock.shift() ?? DOD_OPERATION_BUDGET_MS - 5,
      searchRequestTimeoutMs: 500,
    }),
    error => error instanceof AwardSourceError && error.code === "source_timeout",
  );
  assert.equal(searchCalls, 2);
  assert.ok(finalSignal instanceof AbortSignal);
  assert.ok(performance.now() - started < 250, "the final page must receive only the five-millisecond remaining budget");
});

test("DoD detail enrichment shares the operation budget and retains base awards", async () => {
  let detailCalls = 0;
  const clock = [0, 0, DOD_OPERATION_BUDGET_MS + 1];
  const fetchImpl = async (url) => {
    if (String(url) === DOD_SEARCH_URL) {
      return new Response(JSON.stringify(searchFixture), { headers: { "Content-Type": "application/json" } });
    }
    detailCalls += 1;
    return new Response(JSON.stringify(detailFixture), { headers: { "Content-Type": "application/json" } });
  };
  const result = await searchDod(fetchImpl, {}, {
    limit: 1,
    offset: 0,
    now: fixedNow,
    monotonicNow: () => clock.shift() ?? DOD_OPERATION_BUDGET_MS + 1,
  });
  assert.equal(detailCalls, 0);
  assert.equal(result.results[0].award_id, "FA9550261B195");
  assert.equal(result.health.status, "degraded");
  assert.equal(result.health.detail_requests, 1);
  assert.equal(result.health.details_failed, 1);
});

test("DoD bounds slow detail-cache reads and writes without discarding live detail", async () => {
  for (const slowOperation of ["match", "put"]) {
    let delayedTimer = null;
    const cache = {
      match: slowOperation === "match"
        ? () => new Promise(resolve => { delayedTimer = setTimeout(() => resolve(null), 500); })
        : async () => null,
      put: slowOperation === "put"
        ? () => new Promise(resolve => { delayedTimer = setTimeout(resolve, 500); })
        : async () => {},
    };
    const started = performance.now();
    const result = await searchDod(fixtureFetch(), {}, {
      limit: 1,
      offset: 0,
      now: fixedNow,
      cache,
      cacheTtl: 3_600,
      detailCacheTimeoutMs: 5,
    });
    clearTimeout(delayedTimer);
    assert.ok(performance.now() - started < 250, `${slowOperation} must not outlive its cache budget`);
    assert.equal(result.results[0].opportunity_numbers[0], "NOFOAFRLAFOSR20250002");
    assert.equal(result.health.status, "available");
    assert.equal(result.health.details_loaded, 1);
  }
});

test("DoD source-cache and rate-limit wrapper I/O share the operation deadline", async () => {
  const request = {
    publicCriteria: { award_id: "FA9550261B195" },
    resolvedCriteria: { award_id: "FA9550261B195" },
    limit: 1,
    offset: 0,
    scanAll: false,
    includeAbstracts: true,
  };
  for (const slowOperation of ["source_match", "guard", "source_put"]) {
    let delayedTimer = null;
    const delayed = () => new Promise(resolve => { delayedTimer = setTimeout(resolve, 500); });
    const isSourceCacheKey = key => /\/v1\/dod\/[a-f0-9]{64}$/.test(key.url);
    const cache = {
      async match(key) {
        if (slowOperation === "source_match" && isSourceCacheKey(key)) return delayed();
        return null;
      },
      async put(key) {
        if (slowOperation === "source_put" && isSourceCacheKey(key)) await delayed();
      },
    };
    const guard = slowOperation === "guard" ? delayed : async () => true;
    const started = performance.now();
    try {
      const operation = runSource({
        source: "DOD",
        request,
        fetchImpl: fixtureFetch(),
        cache,
        cacheTtl: 3_600,
        asOf: fixedNow().toISOString(),
        guard,
        rateLimit: 12,
        sourceWrapperTimeoutMs: 5,
      });
      if (slowOperation === "guard") {
        await assert.rejects(
          operation,
          error => error instanceof AwardSourceError && error.code === "source_timeout",
        );
      } else {
        const result = await operation;
        assert.equal(result.results[0].award_id, "FA9550261B195");
      }
    } finally {
      clearTimeout(delayedTimer);
    }
    assert.ok(performance.now() - started < 250, `${slowOperation} must not outlive the source wrapper budget`);
  }
});

test("DoD normalization preserves obligations, Assistance Listing, office, and official links", () => {
  const searchRecord = searchFixture.results[0];
  const raw = {
    generated_id: searchRecord.generated_internal_id,
    award_id: searchRecord["Award ID"],
    recipient_name: searchRecord["Recipient Name"],
    recipient_uei: searchRecord["Recipient UEI"],
    project_start: searchRecord["Start Date"],
    project_end: searchRecord["End Date"],
    total_obligation: searchRecord["Award Amount"],
    agency: searchRecord["Awarding Agency"],
    subagency: searchRecord["Awarding Sub Agency"],
    description: searchRecord.Description,
    base_obligation_date: searchRecord["Base Obligation Date"],
    award_type: searchRecord["Award Type"],
  };
  const award = normalizeDodAward(raw, { detail: detailFixture, retrievedAt: fixedNow().toISOString() });
  assert.equal(award.source, "DOD");
  assert.equal(award.agency, "Department of Defense");
  assert.equal(award.subagency, "Department of the Air Force");
  assert.equal(award.program_name, "Air Force Defense Research Sciences Program");
  assert.deepEqual(award.program_codes, ["12.800"]);
  assert.deepEqual(award.opportunity_numbers, ["NOFOAFRLAFOSR20250002"]);
  assert.equal(award.organization_department, "FA9550 AFRL AFOSR");
  assert.equal(award.award_date, "2026-08-28");
  assert.equal(award.award_year, 2026);
  assert.equal(award.total_award, 3000000);
  assert.equal(award.award_amount_basis, "total_obligation");
  assert.equal(award.institution.identifiers.uei, "NPU8ULVAAS23");
  assert.equal(award.abstract, null);
  assert.deepEqual(award.principal_investigators, []);
  assert.deepEqual(award.program_contacts, []);
  assert.deepEqual(award.annual_support, []);
  assert.equal(award.official_award_url, "https://www.usaspending.gov/award/ASST_NON_FA9550261B195_097/");
});

test("DoD preserves multiple Assistance Listings and makes an exact queried listing primary", async () => {
  const detail = structuredClone(detailFixture);
  detail.cfda_info = [
    { cfda_number: "12.810", cfda_title: "Other Defense Program" },
    { cfda_number: "12.800", cfda_title: "Air Force Defense Research Sciences Program" },
    { cfda_number: "invalid", cfda_title: "Invalid Program" },
    { cfda_number: "12.810", cfda_title: "Duplicate Defense Program" },
  ];
  const raw = {
    generated_id: searchFixture.results[0].generated_internal_id,
    award_id: searchFixture.results[0]["Award ID"],
    award_type: searchFixture.results[0]["Award Type"],
  };
  const unfiltered = normalizeDodAward(raw, { detail, retrievedAt: fixedNow().toISOString() });
  assert.deepEqual(unfiltered.program_codes, ["12.810", "12.800"]);
  assert.equal(unfiltered.program_name, "Other Defense Program");

  const searched = await searchDod(fixtureFetch({ detailPayload: detail }), { program: "12.800" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
  });
  assert.deepEqual(searched.results[0].program_codes, ["12.800", "12.810"]);
  assert.equal(searched.results[0].program_name, "Air Force Defense Research Sciences Program");

  const staleDetail = structuredClone(detailFixture);
  staleDetail.cfda_info = [{ cfda_number: "12.810", cfda_title: "Other Defense Program" }];
  const stale = await searchDod(fixtureFetch({ detailPayload: staleDetail }), { program: "12.800" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
  });
  assert.deepEqual(stale.results[0].program_codes, ["12.800", "12.810"]);
  assert.equal(stale.results[0].program_name, null, "a stale detail title must not relabel the exact queried listing");

  const unavailable = await searchDod(fixtureFetch({ detailFails: true }), { program: "12.800" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
  });
  assert.deepEqual(unavailable.results[0].program_codes, ["12.800"]);
  assert.equal(unavailable.results[0].program_name, null);
});

test("DoD search enriches bounded returned records, caches details, and retains base records on detail failure", async () => {
  const cache = memoryCache();
  const calls = [];
  const first = await searchDod(fixtureFetch({ calls }), { topic: "transport" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
    cache,
    cacheTtl: 3600,
  });
  assert.equal(first.results.length, 1);
  assert.equal(first.results[0].funding_mechanism, "Project Grant");
  assert.equal(first.results[0].opportunity_numbers[0], "NOFOAFRLAFOSR20250002");
  assert.equal(first.upstream_total_count, null);
  assert.equal(first.health.status, "available");
  assert.equal(first.health.detail_requests, 1);
  assert.equal(first.health.details_loaded, 1);
  assert.equal(first.health.detail_cache_hits, 0);
  assert.equal(calls.filter(call => call.url.startsWith(DOD_DETAIL_URL)).length, 1);

  const secondCalls = [];
  const second = await searchDod(fixtureFetch({ calls: secondCalls }), { topic: "transport" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
    cache,
    cacheTtl: 3600,
  });
  assert.equal(second.health.detail_cache_hits, 1);
  assert.equal(secondCalls.filter(call => call.url.startsWith(DOD_DETAIL_URL)).length, 0);

  const degraded = await searchDod(fixtureFetch({ detailFails: true }), { topic: "transport" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
  });
  assert.equal(degraded.results.length, 1);
  assert.equal(degraded.results[0].award_id, "FA9550261B195");
  assert.equal(degraded.results[0].opportunity_numbers.length, 0);
  assert.equal(degraded.health.status, "degraded");
  assert.equal(degraded.health.details_failed, 1);
});

test("DoD excludes unexpected award types, deduplicates records, and rejects unusable opportunity numbers", async () => {
  const contractPayload = structuredClone(searchFixture);
  contractPayload.results[0]["Award Type"] = "DEFINITIVE CONTRACT (A)";
  const excluded = await searchDod(fixtureFetch({ searchPayload: contractPayload }), {}, {
    limit: 1,
    now: fixedNow,
  });
  assert.equal(excluded.results.length, 0);
  assert.equal(excluded.health.detail_requests, 0);

  const duplicatePayload = structuredClone(searchFixture);
  duplicatePayload.results.push(structuredClone(duplicatePayload.results[0]));
  const deduplicated = await searchDod(fixtureFetch({ searchPayload: duplicatePayload }), {}, {
    limit: 2,
    now: fixedNow,
  });
  assert.equal(deduplicated.results.length, 1);
  assert.equal(deduplicated.health.detail_requests, 1);

  const raw = {
    generated_id: searchFixture.results[0].generated_internal_id,
    award_id: searchFixture.results[0]["Award ID"],
    award_type: "Project Grant",
  };
  for (const number of ["NOT APPLICABLE", "N/A", "BAD VALUE", ""]) {
    const detail = structuredClone(detailFixture);
    detail.funding_opportunity = { number };
    assert.deepEqual(normalizeDodAward(raw, { detail, retrievedAt: fixedNow().toISOString() }).opportunity_numbers, []);
  }
});

test("DoD pagination crosses an upstream page boundary without exceeding the three-detail concurrency bound", async () => {
  const records = Array.from({ length: 26 }, (_, index) => ({
    ...structuredClone(searchFixture.results[0]),
    "Award ID": `FA9550PAGE${String(index + 1).padStart(2, "0")}`,
    generated_internal_id: `ASST_NON_FA9550PAGE${String(index + 1).padStart(2, "0")}_097`,
  }));
  const calls = [];
  let activeDetails = 0;
  let maximumActiveDetails = 0;
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url) === DOD_SEARCH_URL) {
      const body = JSON.parse(options.body);
      const page = body.page;
      if (page === 1) {
        assert.equal(body.last_record_unique_id, undefined);
        assert.equal(body.last_record_sort_value, undefined);
      } else {
        assert.equal(body.last_record_unique_id, 9025);
        assert.equal(body.last_record_sort_value, "FA9550PAGE25");
      }
      return new Response(JSON.stringify({
        spending_level: "awards",
        limit: 25,
        results: page === 1 ? records.slice(0, 25) : records.slice(25),
        page_metadata: {
          page,
          hasNext: page === 1,
          last_record_unique_id: page === 1 ? 9025 : null,
          last_record_sort_value: page === 1 ? "FA9550PAGE25" : "None",
        },
      }), { headers: { "Content-Type": "application/json" } });
    }
    activeDetails += 1;
    maximumActiveDetails = Math.max(maximumActiveDetails, activeDetails);
    await new Promise(resolve => setTimeout(resolve, 5));
    activeDetails -= 1;
    const generatedId = decodeURIComponent(String(url).split("/").filter(Boolean).at(-1));
    const record = records.find(item => item.generated_internal_id === generatedId);
    return new Response(JSON.stringify({
      ...detailFixture,
      generated_unique_award_id: generatedId,
      fain: record["Award ID"],
    }), { headers: { "Content-Type": "application/json" } });
  };
  const paged = await searchDod(fetchImpl, {}, {
    limit: 1,
    offset: 25,
    now: fixedNow,
  });
  assert.deepEqual(paged.results.map(award => award.award_id), ["FA9550PAGE26"]);
  assert.equal(calls.filter(call => call.url === DOD_SEARCH_URL).length, 2);
  assert.equal(paged.health.detail_requests, 1);
  assert.ok(maximumActiveDetails <= 3);

  const concurrencyPayload = {
    ...searchFixture,
    results: records.slice(0, 7),
    page_metadata: { page: 1, hasNext: false },
  };
  activeDetails = 0;
  maximumActiveDetails = 0;
  calls.length = 0;
  const concurrentFetch = async (url, options = {}) => {
    if (String(url) === DOD_SEARCH_URL) {
      return new Response(JSON.stringify(concurrencyPayload), { headers: { "Content-Type": "application/json" } });
    }
    activeDetails += 1;
    maximumActiveDetails = Math.max(maximumActiveDetails, activeDetails);
    await new Promise(resolve => setTimeout(resolve, 5));
    activeDetails -= 1;
    const generatedId = decodeURIComponent(String(url).split("/").filter(Boolean).at(-1));
    const record = records.find(item => item.generated_internal_id === generatedId);
    return new Response(JSON.stringify({
      ...detailFixture,
      generated_unique_award_id: generatedId,
      fain: record["Award ID"],
    }), { headers: { "Content-Type": "application/json" } });
  };
  const bounded = await searchDod(concurrentFetch, {}, { limit: 7, now: fixedNow });
  assert.equal(bounded.results.length, 7);
  assert.equal(bounded.health.detail_requests, 7);
  assert.equal(maximumActiveDetails, 3);
});

test("DoD offsets follow the normalized institution sequence and snapshots scan bounded later pages", async () => {
  const institution = resolveInstitution({ id: "university-of-rochester" });
  const validRecord = index => ({
    ...structuredClone(searchFixture.results[0]),
    "Award ID": `FA9550VALID${String(index).padStart(2, "0")}`,
    "Recipient Name": "UNIVERSITY OF ROCHESTER",
    "Recipient UEI": "F27KDXZMF9Y8",
    generated_internal_id: `ASST_NON_FA9550VALID${String(index).padStart(2, "0")}_097`,
  });
  const falsePositives = Array.from({ length: 24 }, (_, index) => ({
    ...structuredClone(searchFixture.results[0]),
    "Award ID": `FA9550FALSE${String(index + 1).padStart(2, "0")}`,
    "Recipient Name": "ROCHESTER INSTITUTE OF TECHNOLOGY",
    "Recipient UEI": `WRONGUEI${String(index + 1).padStart(2, "0")}`,
    generated_internal_id: `ASST_NON_FA9550FALSE${String(index + 1).padStart(2, "0")}_097`,
  }));
  const recordsByPage = [
    [validRecord(1), ...falsePositives],
    [validRecord(2), validRecord(3)],
  ];
  const makeFetch = () => {
    const calls = [];
    return {
      calls,
      fetchImpl: async (url, options = {}) => {
        calls.push({ url: String(url), options });
        if (String(url) === DOD_SEARCH_URL) {
          const body = JSON.parse(options.body);
          if (body.page === 2) {
            assert.equal(body.last_record_unique_id, 9100);
            assert.equal(body.last_record_sort_value, "FA9550FALSE24");
          }
          return new Response(JSON.stringify({
            results: recordsByPage[body.page - 1],
            page_metadata: {
              page: body.page,
              total: 27,
              hasNext: body.page === 1,
              last_record_unique_id: body.page === 1 ? 9100 : null,
              last_record_sort_value: body.page === 1 ? "FA9550FALSE24" : "None",
            },
          }), { headers: { "Content-Type": "application/json" } });
        }
        const generatedId = decodeURIComponent(String(url).split("/").filter(Boolean).at(-1));
        const record = recordsByPage.flat().find(item => item.generated_internal_id === generatedId);
        assert.ok(record, `unexpected detail request for ${generatedId}`);
        return new Response(JSON.stringify({
          ...detailFixture,
          generated_unique_award_id: generatedId,
          fain: record["Award ID"],
          recipient: {
            recipient_name: record["Recipient Name"],
            recipient_uei: record["Recipient UEI"],
          },
        }), { headers: { "Content-Type": "application/json" } });
      },
    };
  };

  const pagedFetch = makeFetch();
  const paged = await searchDod(pagedFetch.fetchImpl, { _institution: institution }, {
    limit: 1,
    offset: 1,
    now: fixedNow,
  });
  assert.deepEqual(paged.results.map(award => award.award_id), ["FA9550VALID02"]);
  assert.equal(paged.has_more, true);
  assert.equal(paged.total_count, 3);
  assert.equal(paged.raw_record_count, 27);
  assert.equal(paged.upstream_pages, 2);
  assert.equal(paged.health.detail_requests, 1);

  const snapshotFetch = makeFetch();
  const snapshot = await searchDod(snapshotFetch.fetchImpl, { _institution: institution }, {
    limit: 25,
    offset: 0,
    scanAll: true,
    now: fixedNow,
  });
  assert.deepEqual(snapshot.results.map(award => award.award_id), [
    "FA9550VALID01",
    "FA9550VALID02",
    "FA9550VALID03",
  ]);
  assert.equal(snapshot.total_count, 3);
  assert.equal(snapshot.safety_bound_reached, false);
  assert.equal(snapshot.has_more, false);
  assert.equal(snapshot.upstream_pages, 2);
  assert.equal(snapshot.health.detail_requests, 3);
});

test("DoD paging keeps current search-row identity and year authoritative over cached detail", async () => {
  const institution = resolveInstitution({ id: "university-of-rochester" });
  const searchPayload = structuredClone(searchFixture);
  searchPayload.results[0]["Recipient Name"] = "UNIVERSITY OF ROCHESTER";
  searchPayload.results[0]["Recipient UEI"] = "F27KDXZMF9Y8";
  searchPayload.results[0]["Base Obligation Date"] = "2026-02-03";
  searchPayload.results[0]["Start Date"] = "2026-03-01";
  searchPayload.results[0]["End Date"] = "2030-02-28";
  searchPayload.results[0]["Award Amount"] = 4_000_000;
  searchPayload.results[0].Description = "CURRENT SEARCH DESCRIPTION";
  const staleDetail = structuredClone(detailFixture);
  staleDetail.fain = "STALE-DETAIL-ID";
  staleDetail.date_signed = "2018-01-15";
  staleDetail.type = "05";
  staleDetail.total_obligation = 1;
  staleDetail.description = "STALE DETAIL DESCRIPTION";
  staleDetail.period_of_performance = { start_date: "2018-02-01", end_date: "2019-02-01" };
  staleDetail.recipient = {
    recipient_name: "ROCHESTER INSTITUTE OF TECHNOLOGY",
    recipient_uei: "STALEUEI123",
  };
  staleDetail.awarding_agency = {
    toptier_agency: { name: "Department of Energy" },
    subtier_agency: { name: "Office of Science" },
    office_agency_name: "FA9550 AFRL AFOSR",
  };

  const result = await searchDod(fixtureFetch({ searchPayload, detailPayload: staleDetail }), {
    _institution: institution,
    year_start: 2026,
    year_end: 2026,
  }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
  });
  assert.equal(result.results.length, 1);
  assert.equal(result.results[0].award_id, "FA9550261B195");
  assert.equal(result.results[0].award_year, 2026);
  assert.equal(result.results[0].award_date, "2026-02-03");
  assert.equal(result.results[0].institution.name, "UNIVERSITY OF ROCHESTER");
  assert.equal(result.results[0].institution.identifiers.uei, "F27KDXZMF9Y8");
  assert.equal(result.results[0].agency, "Department of Defense");
  assert.equal(result.results[0].funding_mechanism, "Project Grant");
  assert.equal(result.results[0].title, "CURRENT SEARCH DESCRIPTION");
  assert.equal(result.results[0].project_start, "2026-03-01");
  assert.equal(result.results[0].project_end, "2030-02-28");
  assert.equal(result.results[0].total_award, 4_000_000);
  assert.deepEqual(result.results[0].program_codes, ["12.800"], "detail-only enrichment remains available");
  assert.equal(result.health.detail_requests, 1);
});

test("DoD fairly queries the bounded validated ROR name set when no UEI is available", async () => {
  const canonicalName = "California Institute of Technology";
  const aliases = ["Caltech", "California Tech", "CIT"];
  const institution = {
    id: "https://ror.org/05dxps055",
    ror_id: "https://ror.org/05dxps055",
    canonical_name: canonicalName,
    aliases,
    acronyms: [],
    match_names: [canonicalName, ...aliases],
    identity_source: "ROR",
    sources: {
      DOD: {
        search_name: canonicalName,
        search_names: [canonicalName, ...aliases],
        uei: [],
      },
    },
  };
  const falsePositive = {
    ...structuredClone(searchFixture.results[0]),
    "Award ID": "FA9550CANONICALFALSE",
    "Recipient Name": "CALIFORNIA STATE UNIVERSITY",
    "Recipient UEI": "WRONGUEI123",
    generated_internal_id: "ASST_NON_FA9550CANONICALFALSE_097",
  };
  const aliasRecord = {
    ...structuredClone(searchFixture.results[0]),
    "Award ID": "FA9550CALTECH",
    "Recipient Name": "CALTECH",
    "Recipient UEI": null,
    generated_internal_id: "ASST_NON_FA9550CALTECH_097",
  };
  const aliasLookahead = {
    ...aliasRecord,
    "Award ID": "FA9550CALTECHLOOKAHEAD",
    generated_internal_id: "ASST_NON_FA9550CALTECHLOOKAHEAD_097",
  };
  const recipientQueries = [];
  let detailRequests = 0;
  const fetchImpl = async (url, options = {}) => {
    if (String(url) === DOD_SEARCH_URL) {
      const body = JSON.parse(options.body);
      const search = body.filters.recipient_search_text[0];
      recipientQueries.push(search);
      const canonical = search === canonicalName;
      const alias = search === "Caltech";
      return new Response(JSON.stringify({
        results: canonical ? [falsePositive] : alias ? [aliasRecord, aliasLookahead] : [],
        page_metadata: {
          page: 1,
          total: canonical ? 1_000 : alias ? 2 : 0,
          hasNext: canonical,
          last_record_unique_id: canonical ? 9301 : null,
          last_record_sort_value: canonical ? falsePositive["Award ID"] : "None",
        },
      }), { headers: { "Content-Type": "application/json" } });
    }
    detailRequests += 1;
    return new Response(JSON.stringify({
      ...detailFixture,
      generated_unique_award_id: aliasRecord.generated_internal_id,
      fain: aliasRecord["Award ID"],
    }), { headers: { "Content-Type": "application/json" } });
  };

  const result = await searchDod(fetchImpl, { _institution: institution }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
  });
  assert.deepEqual(recipientQueries, [canonicalName, "Caltech", "California Tech"]);
  assert.equal(recipientQueries.includes("CIT"), false, "validated name queries remain capped at three");
  assert.deepEqual(result.results.map(award => award.award_id), ["FA9550CALTECH"]);
  assert.equal(result.upstream_queries, 3);
  assert.equal(result.upstream_pages, 3);
  assert.equal(detailRequests, 1);
});

test("DoD normalized snapshot scans stop at the advertised upstream-page bound", async () => {
  const institution = resolveInstitution({ id: "university-of-rochester" });
  let pageCalls = 0;
  const fetchImpl = async (url, options = {}) => {
    assert.equal(String(url), DOD_SEARCH_URL, "rejected recipient rows must not trigger detail requests");
    pageCalls += 1;
    const body = JSON.parse(options.body);
    if (body.page > 1) {
      assert.equal(body.last_record_unique_id, 9200 + body.page - 1);
      assert.equal(body.last_record_sort_value, `FA9550BOUND${body.page - 1}`);
    }
    return new Response(JSON.stringify({
      results: Array.from({ length: 25 }, (_, index) => ({
        ...structuredClone(searchFixture.results[0]),
        "Award ID": `FA9550BOUND${body.page}-${index}`,
        "Recipient Name": "ROCHESTER INSTITUTE OF TECHNOLOGY",
        "Recipient UEI": `WRONGBOUND${body.page}-${index}`,
        generated_internal_id: `ASST_NON_FA9550BOUND${body.page}-${index}_097`,
      })),
      page_metadata: {
        page: body.page,
        total: 10_000,
        hasNext: true,
        last_record_unique_id: 9200 + body.page,
        last_record_sort_value: `FA9550BOUND${body.page}`,
      },
    }), { headers: { "Content-Type": "application/json" } });
  };
  const bounded = await searchDod(fetchImpl, { _institution: institution }, {
    limit: 25,
    offset: 0,
    scanAll: true,
    now: fixedNow,
  });
  assert.equal(pageCalls, DOD_MAX_UPSTREAM_PAGES);
  assert.equal(bounded.upstream_pages, DOD_MAX_UPSTREAM_PAGES);
  assert.equal(bounded.raw_record_count, DOD_MAX_UPSTREAM_PAGES * 25);
  assert.equal(bounded.total_count, null);
  assert.equal(bounded.safety_bound_reached, true);
  assert.equal(bounded.has_more, false);
  assert.deepEqual(bounded.results, []);
  assert.equal(bounded.health.detail_requests, 0);

  pageCalls = 0;
  const paged = await searchDod(fetchImpl, { _institution: institution }, {
    limit: 25,
    offset: 0,
    now: fixedNow,
  });
  assert.equal(pageCalls, DOD_MAX_UPSTREAM_PAGES);
  assert.equal(paged.safety_bound_reached, true);
  assert.equal(paged.has_more, false, "an upstream safety ceiling is not a reachable normalized next page");
  assert.deepEqual(paged.results, []);
  assert.equal(paged.health.detail_requests, 0);
});

test("DoD later-page search fails closed when USAspending omits or repeats its continuation cursor", async () => {
  for (const mode of ["missing", "repeated"]) {
    let pageCalls = 0;
    const fetchImpl = async (url, options = {}) => {
      if (String(url) !== DOD_SEARCH_URL) throw new Error("detail enrichment must not start");
      pageCalls += 1;
      const page = JSON.parse(options.body).page;
      const cursor = mode === "missing"
        ? {}
        : { last_record_unique_id: 77, last_record_sort_value: "FA9550CURSOR25" };
      return new Response(JSON.stringify({
        results: Array.from({ length: 25 }, (_, index) => ({
          ...structuredClone(searchFixture.results[0]),
          "Award ID": `FA9550CURSOR${page}${index}`,
          generated_internal_id: `ASST_NON_FA9550CURSOR${page}${index}_097`,
        })),
        page_metadata: { page, hasNext: true, ...cursor },
      }), { headers: { "Content-Type": "application/json" } });
    };
    await assert.rejects(
      () => searchDod(fetchImpl, {}, { limit: 1, offset: mode === "missing" ? 25 : 50, now: fixedNow }),
      error => error instanceof AwardSourceError && error.code === "source_invalid_response",
    );
    assert.equal(pageCalls, mode === "missing" ? 1 : 2);
  }
});

test("DoD award-to-opportunity links require exactly one exact current-catalog match", () => {
  const unique = {
    opportunity_id: "dod-current-1",
    opportunity_number: "NOFOAFRLAFOSR20250002",
    detail_page: "https://www.grants.gov/search-results-detail/360000",
  };
  const sandbox = { GRANT_CATALOG: { opportunities: [unique] } };
  vm.createContext(sandbox);
  vm.runInContext(linksSource, sandbox);
  const award = { source: "DOD", opportunity_numbers: ["nofoafrlafosr20250002"] };
  assert.equal(sandbox.FUNDING_AWARD_LINKS.opportunityForAward(award), unique);
  assert.equal(sandbox.FUNDING_AWARD_LINKS.opportunityHref(unique), "./match_explorer.html?q=NOFOAFRLAFOSR20250002");
  assert.equal(sandbox.FUNDING_AWARD_LINKS.opportunityForAward({ source: "DOD", opportunity_numbers: ["missing"] }), null);
  assert.equal(sandbox.FUNDING_AWARD_LINKS.opportunityForAward(award, [unique, { ...unique, opportunity_id: "duplicate" }]), null);
  assert.equal(sandbox.FUNDING_AWARD_LINKS.opportunityForAward({ source: "DOE", opportunity_numbers: [unique.opportunity_number] }), null);
});
