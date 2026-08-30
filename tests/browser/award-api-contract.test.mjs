import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildNsfRequest,
  normalizeNsfAward,
} from "../../workers/award-api/src/adapters/nsf.js";
import {
  buildDoeSearchForm,
  normalizeDoeAward,
  parseDoeAbstract,
  parseDoeSearchResults,
  searchDoe,
} from "../../workers/award-api/src/adapters/doe.js";
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

const allowRateLimits = {
  idFromName: name => name,
  get: () => ({
    fetch: async (input, init) => new Response(JSON.stringify(
      (init?.method || new Request(input).method) === "GET"
        ? { ready: true, storage: "sqlite" }
        : { success: true, retry_after_seconds: 0 },
    ), { headers: { "Content-Type": "application/json" } }),
  }),
};

const root = new URL("../../", import.meta.url);
const [
  nsfFixture, nihFixture, doeFormFixture, doeResultsPage1, doeResultsPage2,
  doeAbstractFixture, packageSource, phase1Evidence,
] = await Promise.all([
  readFile(new URL("tests/fixtures/awards/nsf_award.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/nih_project_years.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/doe_search_form.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_results_page1.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_results_page2.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_public_abstract.html", root), "utf8"),
  readFile(new URL("package.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/funded_awards_phase1.json", root), "utf8").then(JSON.parse),
]);
const fixedNow = () => new Date("2026-08-24T20:00:00.000Z");
const env = {
  AWARD_API_ENABLED: "true",
  CACHE_TTL_SECONDS: "3600",
  MAX_SOURCE_RESULTS: "25",
  AWARD_SOURCE_RATE_LIMIT: "12",
  ROR_SEARCH_RATE_LIMIT: "60",
  ROR_RESOLVE_RATE_LIMIT: "20",
  AWARD_RATE_LIMIT_SECRET: "deterministic-award-rate-limit-secret",
  AWARD_RATE_LIMITER: allowRateLimits,
};

function workerRequest(body, {
  origin = "http://localhost:8000", path = "/awards/search", method = "POST", headers = {},
} = {}) {
  return new Request(`https://award.test${path}`, {
    method,
    headers: { Origin: origin, "Content-Type": "application/json", ...headers },
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
}

function query(criteria, sources = ["NSF", "NIH"], limit = 25, offset = 0) {
  return { sources, criteria, limit, offset };
}

function fixtureFetch({ failDoe = false, failNih = false, failNsf = false, calls = [] } = {}) {
  return async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url).includes("api.nsf.gov")) {
      if (failNsf) return new Response("unavailable", { status: 503 });
      return new Response(JSON.stringify(nsfFixture), { headers: { "Content-Type": "application/json" } });
    }
    if (String(url).includes("pamspublic.science.energy.gov")) {
      if (failDoe) return new Response("unavailable", { status: 503 });
      if (String(url).includes("ViewPublicAbstract.aspx")) {
        return new Response(doeAbstractFixture, { headers: { "Content-Type": "text/html" } });
      }
      if (options.method === "POST") {
        const decoded = decodeURIComponent(String(options.body || ""));
        const body = decoded.includes("ctl00$MainContent$grdAwardsList")
          ? doeResultsPage2
          : doeResultsPage1;
        return new Response(body, { headers: { "Content-Type": "text/html" } });
      }
      return new Response(doeFormFixture, { headers: { "Content-Type": "text/html" } });
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
  assert.equal(award.institution.identifiers.ror, "https://ror.org/022kthw22");
  assert.equal(award.institution.identifiers.uei, "F27KDXZMF9Y8");
  assert.deepEqual(award.program_codes, ["124200", "176500", "800400", "089Z", "160Z", "8084"]);
  assert.equal(award.total_award, 686056);
  assert.equal(award.project_start, "2026-09-01");
  assert.equal(award.project_end, "2029-08-31");
  assert.equal(award.principal_investigators.length, 3);
  assert.equal(award.principal_investigators[1].email, "trickey@qtp.ufl.edu");
  assert.equal(award.program_contacts[0].email, "vlukin@nsf.gov");
  assert.equal(award.program_contacts[0].source_display_name, raw.poName);
  assert.equal(award.program_contacts[0].searchable_program_contact, true);
  assert.equal(award.program_contacts[0].program_contact_identity, `NSF:${award.program_contacts[0].program_contact_key}`);
  assert.equal(award.program_contacts[0].source_provenance.source_field, "poName/poEmail");
  assert.equal(award.official_award_url, "https://www.nsf.gov/awardsearch/show-award/?AWD_ID=2605508");

  const richAbstract = normalizeNsfAward({
    ...raw,
    abstractText: "This work converts CO₂ selectively.\r\n\r\nA second source paragraph remains separate.",
  }, {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl,
  });
  assert.equal(
    richAbstract.abstract,
    "This work converts CO₂ selectively.\n\nA second source paragraph remains separate.",
  );

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
  assert.equal(award.program_contacts[0].searchable_program_contact, true);
  assert.equal(award.program_contacts[0].program_contact_identity, `NIH:${award.program_contacts[0].program_contact_key}`);
  assert.equal(award.program_contacts[0].official_contact_url, award.official_award_url);
  assert.equal(award.official_award_url, "https://reporter.nih.gov/project-details/10457449");
  const richAbstract = normalizeNihProject(nihFixture.results.map(record => ({
    ...record,
    abstract_text: "A source-provided CO₂ term.\n\nA source-provided second paragraph.",
  })), {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl: "https://api.reporter.nih.gov/v2/projects/search",
    completeHistory: false,
  });
  assert.equal(
    richAbstract.abstract,
    "A source-provided CO₂ term.\n\nA source-provided second paragraph.",
  );
  const nsfAward = normalizeNsfAward(nsfFixture.response.award[0], {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl: "https://api.nsf.gov/services/v1/awards/2605508.json",
  });
  assert.deepEqual(Object.keys(award), Object.keys(nsfAward), "both sources expose one normalized contract");
});

test("DOE builds the account-free PAMS form and normalizes only labeled public fields", async () => {
  const institution = resolveInstitution({ id: "university-of-rochester" });
  const form = buildDoeSearchForm(doeFormFixture, {
    opportunity_number: "DE-FOA-0003600",
    topic: "carbon dioxide",
    _institution: institution,
    pi: "William Jones",
    program_officer: "Bradley, Christopher",
    year_start: 2020,
    year_end: 2026,
  });
  assert.equal(form.get("__EVENTTARGET"), "ctl00$MainContent$pnlSearch");
  assert.match(form.get("__EVENTARGUMENT"), /Search$/);
  assert.equal(form.get("ctl00$MainContent$pnlSearch$ddAwardStatus"), "0");
  assert.deepEqual(
    JSON.parse(form.get("ctl00_MainContent_pnlSearch_rlbCountry_ClientState")).checkedIndices,
    [],
  );
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtInstitutionName"), "University of Rochester");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtPILastName"), "Jones");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtPIFirstName"), "William");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtPMLastName"), "Bradley");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtPMFirstName"), "Christopher");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtSolNum"), "DE-FOA-0003600");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$txtAbstractKeyword"), "carbon dioxide");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$dpAwardDateFrom"), "2020-01-01");
  assert.equal(form.get("ctl00$MainContent$pnlSearch$dpAwardDateTo"), "2026-12-31");

  const firstPage = parseDoeSearchResults(doeResultsPage1);
  assert.equal(firstPage.total_count, 2);
  assert.equal(firstPage.page_size, 1);
  assert.match(firstPage.page_targets[2], /ctl07$/);
  assert.equal(firstPage.records[0].award_id, "DE-SC0020230");
  assert.equal(firstPage.records[0].program_area, "Catalysis Science");
  assert.deepEqual(firstPage.records[0].opportunity_numbers, ["DE-FOA-0001820", "DE-FOA-0003600"]);
  assert.equal(firstPage.records[0].amount_awarded_to_date, 1363185);

  const secondPage = parseDoeSearchResults(doeResultsPage2);
  const abstract = parseDoeAbstract(doeAbstractFixture, "DE-SC0024701");
  assert.match(abstract, /CO₂/);
  assert.match(abstract, /\n\nThis project/);
  const award = normalizeDoeAward(secondPage.records[0], {
    retrievedAt: fixedNow().toISOString(),
    abstract,
  });
  assert.equal(award.source, "DOE");
  assert.equal(award.award_id, "DE-SC0024701");
  assert.equal(award.subagency, "Office of Biological & Environmental Research");
  assert.equal(award.program_name, "Foundational Genomics Research");
  assert.deepEqual(award.program_codes, ["SC-33.2"]);
  assert.deepEqual(award.opportunity_numbers, ["DE-FOA-0003003"]);
  assert.equal(award.total_award, 1480000);
  assert.equal(award.award_amount_basis, "amount_awarded_to_date");
  assert.equal(award.principal_investigators[0].name, "Justin North");
  assert.equal(award.principal_investigators[0].email, null);
  assert.equal(award.program_contacts[0].name, "Dawn Adin");
  assert.equal(award.program_contacts[0].email, null);
  assert.equal(award.program_contacts[0].source_display_name, secondPage.records[0].program_manager);
  assert.equal(award.program_contacts[0].searchable_program_contact, true);
  assert.equal(award.program_contacts[0].program_contact_identity, `DOE:${award.program_contacts[0].program_contact_key}`);
  assert.match(award.official_award_url, /ViewPublicAbstract\.aspx/);
  const nsfAward = normalizeNsfAward(nsfFixture.response.award[0], {
    retrievedAt: fixedNow().toISOString(),
    sourceUrl: "https://api.nsf.gov/services/v1/awards/2605508.json",
  });
  assert.deepEqual(Object.keys(award), Object.keys(nsfAward), "DOE reuses the normalized award contract");

  const firstCalls = [];
  const firstOnly = await searchDoe(fixtureFetch({ calls: firstCalls }), { topic: "carbon dioxide" }, {
    limit: 1,
    offset: 0,
    now: fixedNow,
    sleep: async () => {},
  });
  assert.deepEqual(firstOnly.results.map(item => item.award_id), ["DE-SC0020230"]);
  assert.equal(firstOnly.has_more, true);
  assert.equal(firstCalls.length, 2, "a full source page is not postback-fetched merely to establish has_more");

  const calls = [];
  const paged = await searchDoe(fixtureFetch({ calls }), { topic: "carbon dioxide" }, {
    limit: 1,
    offset: 1,
    now: fixedNow,
    sleep: async () => {},
  });
  assert.deepEqual(paged.results.map(item => item.award_id), ["DE-SC0024701"]);
  assert.equal(paged.has_more, false);
  assert.deepEqual(paged.health, {
    status: "available",
    abstract_requests: 1,
    abstracts_loaded: 1,
    abstracts_failed: 0,
  });
  assert.equal(calls.length, 4, "one form, search, page, and public-abstract request");
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
    sources: ["NSF", "NIH", "DOE"],
    adapter_versions: ADAPTER_VERSIONS,
    institution_registry: { source: "ROR", adapter_version: "1.1.0" },
    institution_resolution: "curated-or-server-validated-ror",
    normalized_paging: {
      NSF: { upstream_pages: 12, upstream_page_size: 25, maximum_identity_queries: 3 },
      NIH: { upstream_pages: 12, upstream_page_size: 100 },
      DOE: { upstream_pages: 10, maximum_normalized_offset: 100, maximum_identity_queries: 3 },
    },
    complete_result_snapshots: {
      contract_version: 1,
      ordering_version: "award-recency-v1",
      batch_ceiling_per_agency: 25,
      page_sizes: [10, 25, 50],
      cache_ttl_seconds: 3600,
      cache_scope: "cloudflare-datacenter",
      failure_policy: "successful-sources-retained-retry-creates-successor",
      resource_budget: {
        target_plan: "workers-paid",
        configured_cpu_ms: 250,
        memory_mb: 128,
        platform_subrequests_per_request: 10_000,
        maximum_snapshot_create_subrequests: 50,
        maximum_snapshot_create_cache_api_calls: 10,
        maximum_snapshot_create_upstream_and_guard_subrequests: 40,
        maximum_snapshot_create_subrequests_without_ror_resolution: 46,
      },
      program_officer_evidence: {
        endpoint: "/awards/snapshots/evidence",
        phrase_format: "normalized-concepts-v1",
        scoring_version: "program-officer-evidence-v2",
        concept_coverage: "all_substantive_query_concepts_same_record",
        maximum_phrases: 8,
        maximum_records: 24,
        matched_facet_limit: 12,
        abstract_characters_per_record: 800,
        serialized_characters: 18000,
      },
    },
    abuse_control: {
      ready: true,
      provider: "cloudflare-durable-object",
      storage: "sqlite",
      client_identity: "hmac-derived",
      window_seconds: 60,
      limits: { award_source: 12, snapshot_evidence: 12, ror_search: 60, ror_resolution: 20 },
    },
    cache_ttl_seconds: 3600,
    credentials_required: false,
  });
  assert.equal((await handler(workerRequest(query({ topic: "plasma" }), {
    origin: "https://evil.example",
  }), env)).status, 403);
  assert.equal((await handler(workerRequest({ ...query({ topic: "plasma" }), extra: true }), env)).status, 400);
  assert.equal((await handler(workerRequest(query({ topic: "plasma" }, ["NASA"])), env)).status, 400);
  assert.equal((await handler(workerRequest({ ...query({ topic: "plasma" }), limit: 26 }), env)).status, 400);
  assert.equal((await handler(workerRequest(query({ topic: "plasma" }, ["DOE"], 25)), env)).status, 400);
  assert.equal((await handler(workerRequest(query({ award_id: "DE-SC0020230" }, ["DOE"], 1)), env)).status, 200);
  assert.equal((await handler(workerRequest(query({
    institution: "University of Rochester",
    institution_id: "university-of-rochester",
  }, ["NSF"], 10)), env)).status, 200);
  assert.equal((await handler(workerRequest(query({
    institution: "Massachusetts Institute of Technology",
    institution_id: "university-of-rochester",
  }, ["NSF"], 10)), env)).status, 400);
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

test("a PAMS failure is isolated from unchanged NSF and NIH adapters", async () => {
  const handler = createHandler({ fetchImpl: fixtureFetch({ failDoe: true }), now: fixedNow });
  const response = await handler(workerRequest(query(
    { topic: "carbon dioxide" },
    ["NSF", "NIH", "DOE"],
    10,
  )), env);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.deepEqual(payload.results.map(item => item.source).sort(), ["NIH", "NSF"]);
  assert.deepEqual(payload.sources.find(item => item.source === "DOE"), {
    source: "DOE",
    status: "unavailable",
    error: { code: "source_unavailable" },
  });
  assert.equal(payload.sources.find(item => item.source === "NSF").status, "ok");
  assert.equal(payload.sources.find(item => item.source === "NIH").status, "ok");
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

test("Worker partitions NIH start-only cache entries at the federal fiscal-year rollover", async () => {
  const cache = memoryCache();
  const upstreamBodies = [];
  const fetchImpl = async (_url, options = {}) => {
    upstreamBodies.push(JSON.parse(options.body || "{}"));
    return new Response(JSON.stringify({
      meta: { total: 0, offset: 0 },
      results: [],
    }), { headers: { "Content-Type": "application/json" } });
  };
  let current = "2026-09-30T23:59:59.998Z";
  const handler = createHandler({ fetchImpl, cache, now: () => new Date(current) });
  const requestBody = query({ topic: "catalysis", year_start: 2026 }, ["NIH"], 2);

  const search = async () => {
    const response = await handler(workerRequest(requestBody), env);
    assert.equal(response.status, 200);
    return response.json();
  };

  const before = await search();
  assert.equal(before.sources[0].cache, "miss");
  assert.deepEqual(upstreamBodies[0].criteria.fiscal_years, [2026]);

  current = "2026-09-30T23:59:59.999Z";
  const repeatedBefore = await search();
  assert.equal(repeatedBefore.sources[0].cache, "hit");
  assert.equal(upstreamBodies.length, 1, "the same federal fiscal year reuses the cache entry");

  current = "2026-10-01T00:00:00.000Z";
  const after = await search();
  assert.equal(after.sources[0].cache, "miss");
  assert.deepEqual(upstreamBodies[1].criteria.fiscal_years, [2026, 2027]);

  current = "2026-10-01T00:00:00.001Z";
  const repeatedAfter = await search();
  assert.equal(repeatedAfter.sources[0].cache, "hit");
  assert.equal(upstreamBodies.length, 2, "the post-rollover entry is reused independently");
  assert.equal(cache.values.size, 2);
  assert.equal(new Set(cache.values.keys()).size, 2, "pre- and post-rollover identities are distinct");
  for (const cached of cache.values.values()) {
    assert.equal(cached.headers.get("cache-control"), "public, max-age=3600");
  }
});

test("Worker uses one clock for NIH cache/body coherence and leaves stable source keys unpartitioned", async () => {
  const beforeRollover = new Date("2026-09-30T23:59:59.999Z");
  const afterRollover = new Date("2026-10-01T00:00:00.000Z");
  const cache = memoryCache();
  const calls = [];
  let clockCalls = 0;
  const crossingHandler = createHandler({
    fetchImpl: fixtureFetch({ calls }),
    cache,
    now: () => {
      clockCalls += 1;
      return clockCalls === 1 ? beforeRollover : afterRollover;
    },
  });
  const startOnly = query({ topic: "catalysis", year_start: 2026 }, ["NIH"], 2);
  const first = await crossingHandler(workerRequest(startOnly), env);
  assert.equal(first.status, 200);
  assert.equal((await first.json()).sources[0].cache, "miss");
  assert.equal(clockCalls, 1, "one immutable UTC value controls both the key and adapter body");
  const nihBodies = calls
    .filter(call => call.url.includes("api.reporter.nih.gov"))
    .map(call => JSON.parse(call.options.body));
  assert.deepEqual(nihBodies[0].criteria.fiscal_years, [2026]);

  const stableBeforeHandler = createHandler({
    fetchImpl: fixtureFetch({ calls }),
    cache,
    now: () => beforeRollover,
  });
  const repeated = await stableBeforeHandler(workerRequest(startOnly), env);
  assert.equal((await repeated.json()).sources[0].cache, "hit");
  assert.equal(calls.filter(call => call.url.includes("api.reporter.nih.gov")).length, 1);

  const stableCache = memoryCache();
  const stableCalls = [];
  let current = beforeRollover;
  const stableHandler = createHandler({
    fetchImpl: fixtureFetch({ calls: stableCalls }),
    cache: stableCache,
    now: () => current,
  });
  const stableRequests = [
    query({ topic: "catalysis", year_start: 2026, year_end: 2027 }, ["NIH"], 2),
    query({ topic: "catalysis", year_end: 2026 }, ["NIH"], 2),
    query({ topic: "catalysis" }, ["NIH"], 2),
    query({ topic: "warm dense matter" }, ["NSF"], 2),
    query({ award_id: "DE-SC0020230" }, ["DOE"], 1),
  ];

  for (const requestBody of stableRequests) {
    current = beforeRollover;
    const initial = await stableHandler(workerRequest(requestBody), env);
    assert.equal(initial.status, 200);
    assert.equal((await initial.json()).sources[0].cache, "miss");
    const callsAfterMiss = stableCalls.length;
    const entriesAfterMiss = stableCache.values.size;

    current = afterRollover;
    const after = await stableHandler(workerRequest(requestBody), env);
    assert.equal(after.status, 200);
    assert.equal((await after.json()).sources[0].cache, "hit");
    assert.equal(stableCalls.length, callsAfterMiss, "stable criteria do not refetch at rollover");
    assert.equal(stableCache.values.size, entriesAfterMiss, "stable criteria keep one cache identity");
  }
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
