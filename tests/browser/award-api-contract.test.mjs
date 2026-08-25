import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildNsfRequest,
  normalizeNsfAward,
} from "../../workers/award-api/src/adapters/nsf.js";
import {
  buildNihRequest,
  normalizeNihProject,
  searchNih,
} from "../../workers/award-api/src/adapters/nih.js";
import { resolveInstitution } from "../../workers/award-api/src/institutions.js";
import {
  ADAPTER_VERSIONS,
  createHandler,
  MAX_REQUEST_BYTES,
} from "../../workers/award-api/src/index.js";

const root = new URL("../../", import.meta.url);
const [nsfFixture, nihFixture, packageSource, phase1Evidence] = await Promise.all([
  readFile(new URL("tests/fixtures/awards/nsf_award.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/nih_project_years.json", root), "utf8").then(JSON.parse),
  readFile(new URL("package.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/funded_awards_phase1.json", root), "utf8").then(JSON.parse),
]);
const fixedNow = () => new Date("2026-08-24T20:00:00.000Z");
const env = {
  AWARD_API_ENABLED: "true",
  CACHE_TTL_SECONDS: "3600",
  MAX_SOURCE_RESULTS: "25",
};

function workerRequest(body, { origin = "http://localhost:8000", path = "/awards/search", method = "POST" } = {}) {
  return new Request(`https://award.test${path}`, {
    method,
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
}

function query(criteria, sources = ["NSF", "NIH"]) {
  return { sources, criteria, limit: 25, offset: 0 };
}

function fixtureFetch({ failNih = false, failNsf = false, calls = [] } = {}) {
  return async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("api.nsf.gov")) {
      if (failNsf) return new Response("unavailable", { status: 503 });
      return new Response(JSON.stringify(nsfFixture), { headers: { "Content-Type": "application/json" } });
    }
    if (failNih) return new Response("unavailable", { status: 503 });
    const body = JSON.parse(options.body || "{}");
    const results = body.offset > 0 ? [] : nihFixture.results;
    return new Response(JSON.stringify({
      ...nihFixture,
      meta: { ...nihFixture.meta, offset: body.offset || 0, total: nihFixture.results.length },
      results,
    }), { headers: { "Content-Type": "application/json" } });
  };
}

function nihProjectRecord(core, projectStart, index) {
  const base = nihFixture.results[0];
  const applicationId = 20_000_000 + index;
  return {
    ...base,
    appl_id: applicationId,
    core_project_num: core,
    project_num: `${core}-${index}`,
    project_start_date: projectStart,
    fiscal_year: 2020 + index % 7,
    project_detail_url: `https://reporter.nih.gov/project-details/${applicationId}`,
  };
}

function memoryCache() {
  const values = new Map();
  return {
    values,
    async match(request) {
      const value = values.get(request.url);
      return value?.clone();
    },
    async put(request, response) {
      values.set(request.url, response.clone());
    },
  };
}

test("Phase 1 uses the v1.3.0 runtime and source-specific exact query contracts", () => {
  assert.equal(packageSource.version, "1.3.0");
  const institution = resolveInstitution({ name: "University of Rochester Medical Center" });
  assert.equal(institution.id, "university-of-rochester");
  const nsf = buildNsfRequest({
    program: "168000",
    pi: "John D Kessler",
    program_officer: "Kandace Binkley",
    _institution: institution,
    year_start: 2020,
    year_end: 2026,
  }, { limit: 25, offset: 0 });
  const nsfUrl = new URL(nsf.url);
  assert.equal(nsfUrl.searchParams.get("ProgEleCode"), "168000");
  assert.equal(nsfUrl.searchParams.get("awardeeName"), '"University of Rochester"');
  assert.equal(nsfUrl.searchParams.get("pdPIName"), "John D Kessler");
  assert.equal(nsfUrl.searchParams.get("poName"), "Kandace Binkley");
  assert.equal(nsfUrl.searchParams.get("dateStart"), "01/01/2020");
  assert.equal(nsfUrl.searchParams.get("dateEnd"), "12/31/2026");
  const nsfTopic = buildNsfRequest({ topic: "warm dense matter" }, { limit: 5, offset: 0 });
  assert.equal(new URL(nsfTopic.url).searchParams.get("keyword"), "warm AND dense AND matter");
  const nsfParent = buildNsfRequest({
    program_codes: ["367Y00", "140100", "764400", "141700", "140300"],
  }, { limit: 5, offset: 0 });
  assert.equal(
    new URL(nsfParent.url).searchParams.get("ProgEleCode"),
    "367Y00,140100,764400,141700,140300",
  );

  const nih = buildNihRequest({
    core_project_number: "K12GM106997",
    opportunity_number: "PAR-19-366",
    _institution: institution,
  }, { limit: 25, offset: 0 });
  assert.deepEqual(nih.body.criteria.project_num_split, {
    activity_code: "K12",
    ic_code: "GM",
    serial_num: "106997",
  });
  assert.deepEqual(nih.body.criteria.opportunity_numbers, ["PAR-19-366"]);
  assert.deepEqual(nih.body.criteria.org_names_exact_match, ["UNIVERSITY OF ROCHESTER"]);
  assert.equal(nih.body.criteria.exclude_subprojects, true);
  assert.equal(nih.body.limit, 100);
});

test("NSF normalization preserves science, institution IDs, direct contacts, and official links", () => {
  const raw = nsfFixture.response.award[0];
  const sourceUrl = "https://api.nsf.gov/services/v1/awards/2605508.json";
  const award = normalizeNsfAward(raw, {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl,
  });
  assert.equal(award.award_id, "2605508");
  assert.match(award.title, /Warm Dense Matter/);
  assert.match(award.abstract, /plasma and materials/);
  assert.equal(award.institution.normalized_name, "University of Rochester");
  assert.equal(award.institution.identifiers.uei, "F27KDXZMF9Y8");
  assert.deepEqual(award.program_codes, ["124200", "176500", "800400", "089Z", "160Z", "8084"]);
  assert.equal(award.total_award, 686056);
  assert.equal(award.project_start, "2026-09-01");
  assert.equal(award.project_end, "2029-08-31");
  assert.equal(award.principal_investigators.length, 3);
  assert.equal(award.principal_investigators[1].email, "trickey@qtp.ufl.edu");
  assert.equal(award.program_contacts[0].email, "vlukin@nsf.gov");
  assert.equal(award.program_contacts[0].source_provenance.source_field, "poName/poEmail");
  assert.equal(award.official_award_url, "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508");

  const listedEmail = normalizeNsfAward({ ...raw, piEmail: null }, {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl,
  });
  assert.equal(listedEmail.principal_investigators[0].email, "vkarasev@lle.rochester.edu");
  assert.equal(listedEmail.principal_investigators[0].source_provenance.source_field, "pdPIName/pi");

  const noEmail = normalizeNsfAward({ ...raw, piEmail: null, pi: [raw.pdPIName], poEmail: null }, {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl,
  });
  assert.equal(noEmail.principal_investigators[0].email, null);
  assert.equal(noEmail.program_contacts[0].email, null);
});

test("NIH normalization groups annual applications under the core project without inventing email", () => {
  const award = normalizeNihProject(nihFixture.results, {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl: "https://api.reporter.nih.gov/v2/projects/search",
    completeHistory: false,
  });
  assert.equal(award.award_id, "K12GM106997");
  assert.equal(award.annual_support.length, 2);
  assert.deepEqual(award.source_record_ids, ["10273075", "10457449"]);
  assert.equal(award.total_award, 2293188);
  assert.equal(award.award_amount_basis, "returned_support_years");
  assert.equal(award.institution.normalized_name, "University of Rochester");
  assert.equal(award.institution.identifiers.ipf, "7047101");
  assert.equal(award.institution.identifiers.uei, "F27KDXZMF9Y8");
  assert.equal(award.organization_department, "MICROBIOLOGY/IMMUN/VIROLOGY");
  assert.equal(award.opportunity_numbers[0], "PAR-19-366");
  assert.equal(award.activity_code, "K12");
  assert.equal(award.principal_investigators.length, 2);
  assert.equal(award.principal_investigators.find(person => person.profile_id === 1891753).role, "Contact Principal Investigator");
  assert.ok(award.principal_investigators.every(person => person.email === null));
  assert.equal(award.program_contacts[0].email, null);
  assert.equal(award.program_contacts[0].official_contact_url, award.official_award_url);
  assert.equal(award.official_award_url, "https://reporter.nih.gov/project-details/10457449");
  const nsfAward = normalizeNsfAward(nsfFixture.response.award[0], {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl: "https://api.nsf.gov/services/v1/awards/2605508.json",
  });
  assert.deepEqual(Object.keys(award), Object.keys(nsfAward), "both sources expose one normalized contract");
});

test("NIH pagination advances through normalized core projects instead of annual records", async () => {
  const starts = {
    R01AA000001: "2026-01-01",
    R01BB000002: "2025-01-01",
    R01CC000003: "2024-01-01",
    R01DD000004: "2023-01-01",
    R01EE000005: "2022-01-01",
    R01FF000006: "2021-01-01",
  };
  const firstFour = Object.keys(starts).slice(0, 4);
  const rawRecords = Array.from({ length: 100 }, (_, index) => {
    const core = firstFour[index % firstFour.length];
    return nihProjectRecord(core, starts[core], index);
  });
  rawRecords.push(
    nihProjectRecord("R01DD000004", starts.R01DD000004, 100),
    nihProjectRecord("R01EE000005", starts.R01EE000005, 101),
    nihProjectRecord("R01EE000005", starts.R01EE000005, 102),
    nihProjectRecord("R01FF000006", starts.R01FF000006, 103),
    nihProjectRecord("R01FF000006", starts.R01FF000006, 104),
  );
  const offsets = [];
  const fetchImpl = async (_url, options) => {
    const body = JSON.parse(options.body);
    offsets.push(body.offset);
    return new Response(JSON.stringify({
      meta: { total: rawRecords.length, offset: body.offset },
      results: rawRecords.slice(body.offset, body.offset + body.limit),
    }), { headers: { "Content-Type": "application/json" } });
  };
  const criteria = { topic: "cell signaling" };
  const first = await searchNih(fetchImpl, criteria, { limit: 2, offset: 0, now: fixedNow });
  const second = await searchNih(fetchImpl, criteria, { limit: 2, offset: 2, now: fixedNow });
  const third = await searchNih(fetchImpl, criteria, { limit: 2, offset: 4, now: fixedNow });

  assert.deepEqual(first.results.map(award => award.award_id), ["R01AA000001", "R01BB000002"]);
  assert.deepEqual(second.results.map(award => award.award_id), ["R01CC000003", "R01DD000004"]);
  assert.deepEqual(third.results.map(award => award.award_id), ["R01EE000005", "R01FF000006"]);
  assert.equal(new Set([...first.results, ...second.results, ...third.results].map(award => award.award_id)).size, 6);
  assert.equal(second.results[1].annual_support.length, 26, "a core project crossing raw pages remains one project");
  assert.equal(first.has_more, true);
  assert.equal(second.has_more, true);
  assert.equal(third.has_more, false);
  assert.equal(third.total_count, 6);
  assert.deepEqual(offsets, [0, 0, 100, 0, 100]);
});

test("Worker validates bounded public requests and exposes no credential requirement", async () => {
  const handler = createHandler({ fetchImpl: fixtureFetch(), now: fixedNow });
  const health = await handler(workerRequest(null, { path: "/health", method: "GET" }), env);
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), {
    service: "available",
    schema_version: 1,
    sources: ["NSF", "NIH"],
    adapter_versions: ADAPTER_VERSIONS,
    cache_ttl_seconds: 3600,
    credentials_required: false,
  });
  assert.equal((await handler(workerRequest(query({ topic: "plasma" }), {
    origin: "https://evil.example",
  }), env)).status, 403);
  assert.equal((await handler(workerRequest({ ...query({ topic: "plasma" }), extra: true }), env)).status, 400);
  assert.equal((await handler(workerRequest(query({ topic: "plasma" }, ["DOE"])), env)).status, 400);
  assert.equal((await handler(workerRequest({ ...query({ topic: "plasma" }), limit: 26 }), env)).status, 400);
  assert.equal((await handler(workerRequest(query({ year_start: 2020 })), env)).status, 400);
  const cbetCodes = [
    "366Y00", "367Y00", "369Y00", "370Y00", "140100", "764400",
    "141700", "140300", "723600", "149100", "534200", "534500",
    "764300", "117900", "140700", "144300", "141500", "140600",
  ];
  assert.equal((await handler(workerRequest(query({ program_codes: cbetCodes }, ["NSF"])), env)).status, 200);
  const tooManyCodes = Array.from({ length: 25 }, (_, index) => String(index + 1).padStart(6, "0"));
  assert.equal((await handler(workerRequest(query({ program_codes: tooManyCodes }, ["NSF"])), env)).status, 400);
  const tooLarge = workerRequest(query({ topic: "x".repeat(MAX_REQUEST_BYTES) }));
  assert.equal((await handler(tooLarge, env)).status, 413);
});

test("Worker isolates a failed source and retains the common successful response", async () => {
  const handler = createHandler({ fetchImpl: fixtureFetch({ failNih: true }), now: fixedNow });
  const response = await handler(workerRequest(query({ topic: "warm dense matter" })), env);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.results.length, 1);
  assert.equal(payload.results[0].source, "NSF");
  assert.equal(payload.sources[0].status, "ok");
  assert.deepEqual(payload.sources[1], {
    source: "NIH",
    status: "unavailable",
    error: { code: "source_unavailable" },
  });
});

test("Worker caches only successful per-source results for the bounded TTL", async () => {
  const calls = [];
  const cache = memoryCache();
  const handler = createHandler({ fetchImpl: fixtureFetch({ calls }), cache, now: fixedNow });
  const requestBody = query({ institution_id: "university-of-rochester" });
  const first = await handler(workerRequest(requestBody), env);
  const second = await handler(workerRequest(requestBody), env);
  assert.equal(first.status, 200);
  assert.equal(second.status, 200);
  assert.equal(calls.length, 2, "one live request per source before cache hits");
  assert.equal(cache.values.size, 2);
  const secondPayload = await second.json();
  assert.ok(secondPayload.sources.every(source => source.cache === "hit"));
  for (const cached of cache.values.values()) {
    assert.equal(cached.headers.get("cache-control"), "public, max-age=3600");
  }

  const failingCache = memoryCache();
  const failingCalls = [];
  const failingHandler = createHandler({
    fetchImpl: fixtureFetch({ failNih: true, calls: failingCalls }),
    cache: failingCache,
    now: fixedNow,
  });
  await failingHandler(workerRequest(requestBody), env);
  await failingHandler(workerRequest(requestBody), env);
  assert.equal(failingCache.values.size, 1, "the failed NIH response is not cached");
  assert.equal(failingCalls.length, 3, "NSF hits cache while NIH is retried");
});

test("committed Phase 1 evidence closes only the NSF and NIH data-foundation gate", () => {
  assert.equal(phase1Evidence.authoritative_base.package_version, "1.3.0");
  assert.equal(phase1Evidence.live_truth_set.NSF.length, 7);
  assert.equal(phase1Evidence.live_truth_set.NIH.length, 7);
  assert.ok(Object.values(phase1Evidence.gate).every(Boolean));
  assert.deepEqual(phase1Evidence.scope.ranking_files_changed, []);
  assert.match(phase1Evidence.decision, /^PHASE 1 PASSED/);
  assert.ok(phase1Evidence.scope.explicitly_not_implemented.includes("Funded Awards page"));
  assert.ok(phase1Evidence.scope.explicitly_not_implemented.includes("watchlists or alerts"));
  assert.ok(phase1Evidence.scope.explicitly_not_implemented.includes("DOE award integration"));
});
