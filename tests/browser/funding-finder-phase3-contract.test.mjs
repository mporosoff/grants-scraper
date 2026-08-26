import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { searchDoe } from "../../workers/award-api/src/adapters/doe.js";
import { searchNih } from "../../workers/award-api/src/adapters/nih.js";
import { searchNsf } from "../../workers/award-api/src/adapters/nsf.js";
import { createHandler } from "../../workers/award-api/src/index.js";
import { institutionFromRor, resolveInstitution } from "../../workers/award-api/src/institutions.js";
import { rankRorOrganizations } from "../../workers/award-api/src/ror.js";

const root = new URL("../../", import.meta.url);
const [
  coreSource, fundedCoreSource, appSource, providerSource, pageSource,
  nsfFixture, nihFixture, aliases, doeForm, doePage1, doePage2, doeAbstract,
] = await Promise.all([
  readFile(new URL("assets/institutional-intelligence-core.js", root), "utf8"),
  readFile(new URL("assets/funded-awards-core.js", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence.js", root), "utf8"),
  readFile(new URL("assets/ai-provider.js", root), "utf8"),
  readFile(new URL("funded_awards.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/nsf_award.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/nih_project_years.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/ror_aliases.json", root), "utf8").then(JSON.parse),
  readFile(new URL("tests/fixtures/awards/doe_search_form.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_results_page1.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_results_page2.html", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_public_abstract.html", root), "utf8"),
]);

const sandbox = { URL, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(fundedCoreSource, sandbox);
vm.runInContext(coreSource, sandbox);
vm.runInContext(providerSource, sandbox);
const core = sandbox.FUNDING_INSTITUTIONAL_INTELLIGENCE;
const ai = sandbox.FUNDING_AI;
const fixedNow = () => new Date("2026-08-26T12:00:00.000Z");
const env = { AWARD_API_ENABLED: "true", CACHE_TTL_SECONDS: "3600", MAX_SOURCE_RESULTS: "25" };

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function memoryCache() {
  const values = new Map();
  return {
    values,
    async match(request) { return values.get(request.url)?.clone(); },
    async put(request, response) { values.set(request.url, response.clone()); },
  };
}

function workerRequest(criteria) {
  return new Request("https://award.test/awards/search", {
    method: "POST",
    headers: { Origin: "http://localhost:8765", "Content-Type": "application/json" },
    body: JSON.stringify({ sources: ["NSF"], criteria, limit: 2, offset: 0 }),
  });
}

function nsfRaw(id, institution, pi = "Marc Porosoff") {
  return {
    ...nsfFixture.response.award[0],
    id,
    awardeeName: institution,
    ueiNumber: institution === "University of Rochester" ? "F27KDXZMF9Y8" : "OTHER-UEI",
    pdPIName: pi,
    pi: [pi],
    piEmail: null,
    title: `Award ${id}`,
  };
}

function normalizedAward({ source = "NSF", id, name, institution = "University of Rochester", ror = "https://ror.org/022kthw22", email = null, personId = null, year = 2024, title = "Catalysis award", program = "Catalysis Science", subagency = "Office of Basic Energy Sciences" }) {
  return {
    source,
    award_id: id,
    award_year: year,
    title,
    program_name: program,
    program_codes: source === "NIH" ? ["R01"] : [],
    activity_code: source === "NIH" ? "R01" : null,
    subagency,
    institution: { name: institution, normalized_name: institution, identifiers: { ror } },
    principal_investigators: [{
      name,
      email,
      ...(personId ? { source_person_id: personId } : {}),
      source_provenance: { source_field: "fixture", source_url: "https://example.test/award" },
    }],
  };
}

test("NSF and DOE page the normalized post-validation sequence and expose bounded diagnostics", async () => {
  const rochester = resolveInstitution({ id: "university-of-rochester" });
  const raw = [
    ...Array.from({ length: 25 }, (_, index) => nsfRaw(`W${String(index).padStart(3, "0")}`, "Another University")),
    nsfRaw("R001", "University of Rochester"),
    nsfRaw("R002", "University of Rochester"),
    nsfRaw("R003", "University of Rochester"),
  ];
  const offsets = [];
  const fetchNsf = async url => {
    const parsed = new URL(url);
    const offset = Number(parsed.searchParams.get("offset"));
    const limit = Number(parsed.searchParams.get("rpp"));
    offsets.push(offset);
    return new Response(JSON.stringify({
      response: {
        award: raw.slice(offset, offset + limit),
        metadata: { totalCount: raw.length },
      },
    }), { headers: { "Content-Type": "application/json" } });
  };
  const first = await searchNsf(fetchNsf, { topic: "catalysis", _institution: rochester }, { limit: 2, offset: 0, now: fixedNow });
  const second = await searchNsf(fetchNsf, { topic: "catalysis", _institution: rochester }, { limit: 2, offset: 2, now: fixedNow });
  assert.deepEqual(first.results.map(item => item.award_id), ["R001", "R002"]);
  assert.equal(first.has_more, true);
  assert.deepEqual(second.results.map(item => item.award_id), ["R003"]);
  assert.equal(second.has_more, false);
  assert.equal(second.total_count, 3);
  assert.equal(second.raw_record_count, 28);
  assert.equal(second.upstream_pages, 2);
  assert.equal(second.safety_bound_reached, false);
  assert.deepEqual(offsets, [0, 25, 0, 25]);

  const wrongFirst = doePage1
    .replace("University of Rochester, Rochester, NY", "The Ohio State University, Columbus, OH")
    .replaceAll("F27KDXZMF9Y8", "OTHERUEI0001");
  const validSecond = doePage2.replace("The Ohio State University, Columbus, OH", "University of Rochester, Rochester, NY");
  const calls = [];
  const fetchDoe = async (url, options = {}) => {
    calls.push(String(url));
    if (String(url).includes("ViewPublicAbstract.aspx")) return new Response(doeAbstract);
    if (options.method === "POST") {
      return new Response(decodeURIComponent(String(options.body || "")).includes("grdAwardsList") ? validSecond : wrongFirst);
    }
    return new Response(doeForm);
  };
  const doe = await searchDoe(fetchDoe, { topic: "catalysis", _institution: rochester }, { limit: 1, offset: 0, now: fixedNow, sleep: async () => {} });
  assert.deepEqual(doe.results.map(item => item.award_id), ["DE-SC0024701"]);
  assert.equal(doe.total_count, 1);
  assert.equal(doe.raw_record_count, 2);
  assert.equal(doe.upstream_pages, 2);
  assert.equal(doe.has_more, false);
  assert.equal(calls.length, 4);
});

test("NIH fills normalized pages after sparse institution validation and NSF stops truthfully at its safety bound", async () => {
  const rochester = resolveInstitution({ id: "university-of-rochester" });
  const nihRaw = Array.from({ length: 100 }, (_, index) => {
    const coreProject = "R01ZZ" + String(index).padStart(6, "0");
    const applicationId = 30_000_000 + index;
    return {
      ...nihFixture.results[0],
      appl_id: applicationId,
      core_project_num: coreProject,
      project_num: coreProject + "-01",
      project_detail_url: "https://reporter.nih.gov/project-details/" + applicationId,
      organization: {
        ...nihFixture.results[0].organization,
        org_name: "Another University",
        primary_uei: "OTHERUEI0001",
        org_ipf_code: "9999999",
      },
    };
  });
  nihRaw.push(
    {
      ...nihFixture.results[0],
      appl_id: 40_000_001,
      core_project_num: "R01GM000001",
      project_num: "R01GM000001-01",
      project_start_date: "2026-01-01",
      project_detail_url: "https://reporter.nih.gov/project-details/40000001",
    },
    {
      ...nihFixture.results[0],
      appl_id: 40_000_002,
      core_project_num: "R01GM000002",
      project_num: "R01GM000002-01",
      project_start_date: "2025-01-01",
      project_detail_url: "https://reporter.nih.gov/project-details/40000002",
    },
  );
  const fetchNih = async (_url, options) => {
    const body = JSON.parse(options.body);
    return new Response(JSON.stringify({
      meta: { total: nihRaw.length, offset: body.offset },
      results: nihRaw.slice(body.offset, body.offset + body.limit),
    }), { headers: { "Content-Type": "application/json" } });
  };
  const first = await searchNih(fetchNih, { topic: "catalysis", _institution: rochester }, { limit: 1, offset: 0, now: fixedNow });
  const second = await searchNih(fetchNih, { topic: "catalysis", _institution: rochester }, { limit: 1, offset: 1, now: fixedNow });
  assert.deepEqual(first.results.map(item => item.award_id), ["R01GM000001"]);
  assert.equal(first.has_more, true);
  assert.deepEqual(second.results.map(item => item.award_id), ["R01GM000002"]);
  assert.equal(second.has_more, false);
  assert.equal(second.total_count, 2);
  assert.equal(second.raw_record_count, 102);
  assert.equal(second.upstream_pages, 2);

  const fetchBoundedNih = async (_url, options) => {
    const body = JSON.parse(options.body);
    const rows = Array.from({ length: 100 }, (_, index) => {
      const recordIndex = body.offset + index;
      const coreProject = "R01BX" + String(recordIndex).padStart(6, "0");
      return {
        ...nihFixture.results[0],
        appl_id: 50_000_000 + recordIndex,
        core_project_num: coreProject,
        project_num: coreProject + "-01",
        project_detail_url: "https://reporter.nih.gov/project-details/" + (50_000_000 + recordIndex),
        organization: {
          ...nihFixture.results[0].organization,
          org_name: "Another University",
          primary_uei: "OTHERUEI0001",
          org_ipf_code: "9999999",
        },
      };
    });
    if (body.offset === 1_100) {
      rows[0] = {
        ...nihFixture.results[0],
        appl_id: 60_000_001,
        core_project_num: "R01GMBOUND01",
        project_num: "R01GMBOUND01-01",
        project_detail_url: "https://reporter.nih.gov/project-details/60000001",
      };
      rows[1] = {
        ...nihFixture.results[0],
        appl_id: 60_000_002,
        core_project_num: "R01GMBOUND02",
        project_num: "R01GMBOUND02-01",
        project_detail_url: "https://reporter.nih.gov/project-details/60000002",
      };
    }
    return new Response(JSON.stringify({ meta: { total: 2_000, offset: body.offset }, results: rows }), {
      headers: { "Content-Type": "application/json" },
    });
  };
  const boundedNih = await searchNih(fetchBoundedNih, { topic: "catalysis", _institution: rochester }, { limit: 1, offset: 0, now: fixedNow });
  assert.deepEqual(boundedNih.results.map(item => item.award_id), ["R01GMBOUND01"]);
  assert.equal(boundedNih.upstream_pages, 12);
  assert.equal(boundedNih.safety_bound_reached, true, "filling the target on the final bounded page does not imply upstream exhaustion");
  assert.equal(boundedNih.has_more, true);

  let nsfPages = 0;
  const fetchBoundedNsf = async url => {
    const parsed = new URL(url);
    const offset = Number(parsed.searchParams.get("offset"));
    nsfPages += 1;
    return new Response(JSON.stringify({
      response: {
        award: Array.from({ length: 25 }, (_, index) => nsfRaw("B" + (offset + index), "Another University")),
        metadata: { totalCount: 1_000 },
      },
    }), { headers: { "Content-Type": "application/json" } });
  };
  const bounded = await searchNsf(fetchBoundedNsf, { topic: "catalysis", _institution: rochester }, { limit: 1, offset: 0, now: fixedNow });
  assert.equal(bounded.results.length, 0);
  assert.equal(bounded.has_more, false);
  assert.equal(bounded.safety_bound_reached, true);
  assert.equal(bounded.raw_record_count, 300);
  assert.equal(nsfPages, 12);
  const fetchBoundedExtra = async url => {
    const parsed = new URL(url);
    const offset = Number(parsed.searchParams.get("offset"));
    const rows = Array.from({ length: 25 }, (_, index) => nsfRaw("E" + (offset + index), "Another University"));
    if (offset === 275) {
      rows[0] = nsfRaw("BOUND-1", "University of Rochester");
      rows[1] = nsfRaw("BOUND-2", "University of Rochester");
    }
    return new Response(JSON.stringify({ response: { award: rows, metadata: { totalCount: 1_000 } } }), {
      headers: { "Content-Type": "application/json" },
    });
  };
  const boundedExtra = await searchNsf(fetchBoundedExtra, { topic: "catalysis", _institution: rochester }, { limit: 1, offset: 0, now: fixedNow });
  assert.deepEqual(boundedExtra.results.map(item => item.award_id), ["BOUND-1"]);
  assert.equal(boundedExtra.safety_bound_reached, true);
  assert.equal(boundedExtra.has_more, true, "a normalized match already collected beyond the slice remains reachable at the safety bound");
  assert.match(sandbox.FUNDING_AWARD_PRODUCT.paginationLabel({
    request: { sources: ["NSF"] },
    results: [],
    sources: [{ source: "NSF", status: "ok", safety_bound_reached: true }],
    pagination: { limit: 1, offset: 0 },
  }), /upstream scan bound reached for NSF/);
  assert.match(appSource, /upstream scan bound reached/);
});

test("ambiguous acronyms require selection while unique canonical names and aliases may resolve", () => {
  assert.equal(core.requiresExplicitInstitutionSelection("MIT"), true);
  assert.equal(core.requiresExplicitInstitutionSelection("mit"), true);
  assert.equal(core.requiresExplicitInstitutionSelection("University of Rochester"), false);
  const mit = rankRorOrganizations(aliases.MIT.items, "MIT");
  assert.equal(core.chooseInstitution("MIT", mit), null);
  const uva = rankRorOrganizations(aliases.UVA.items, "UVA");
  assert.equal(core.chooseInstitution("UVA", uva), null);
  const caltech = rankRorOrganizations(aliases.Caltech.items, "Caltech");
  assert.equal(core.chooseInstitution("Caltech", caltech)?.canonical_name, "California Institute of Technology");
  const canonical = rankRorOrganizations(aliases.Caltech.items, "California Institute of Technology");
  assert.equal(core.chooseInstitution("California Institute of Technology", canonical)?.id, "https://ror.org/05dxps055");
});

test("the Worker validates and caches uncurated ROR identity without trusting the submitted name", async () => {
  const mitRecord = aliases.MIT.items.find(item => item.id === "https://ror.org/042nb2s44");
  const cache = memoryCache();
  const calls = [];
  const fetchImpl = async url => {
    calls.push(String(url));
    if (String(url).includes("api.ror.org/v2/organizations/042nb2s44")) {
      return new Response(JSON.stringify(mitRecord), { headers: { "Content-Type": "application/json" } });
    }
    if (String(url).includes("api.nsf.gov")) {
      const raw = nsfRaw("MIT-1", "Massachusetts Institute of Technology", "Ada Researcher");
      return new Response(JSON.stringify({ response: { award: [raw], metadata: { totalCount: 1 } } }), { headers: { "Content-Type": "application/json" } });
    }
    throw new Error(`unexpected URL ${url}`);
  };
  const handler = createHandler({ fetchImpl, cache, now: fixedNow });
  const uncontrolledAcronym = await handler(workerRequest({ institution: "MIT" }), env);
  assert.equal(uncontrolledAcronym.status, 400);
  assert.equal((await uncontrolledAcronym.json()).error.code, "invalid_request");
  assert.equal(calls.length, 0, "an unselected short acronym never reaches ROR or an award source");
  const criteria = { institution: "Massachusetts Institute of Technology", institution_id: "https://ror.org/042nb2s44" };
  const first = await handler(workerRequest(criteria), env);
  const firstPayload = await first.json();
  assert.equal(first.status, 200);
  assert.equal(firstPayload.results[0].institution.name, "Massachusetts Institute of Technology");
  assert.equal(firstPayload.results[0].institution.identifiers.ror, "https://ror.org/042nb2s44");
  assert.equal(firstPayload.results[0].institution.identity_source, "ROR");
  assert.match(calls.find(url => url.includes("api.nsf.gov")), /awardeeName=%22Massachusetts\+Institute\+of\+Technology%22/);
  const firstCallCount = calls.length;
  const second = await handler(workerRequest(criteria), env);
  assert.equal(second.status, 200);
  assert.equal(calls.length, firstCallCount, "both exact ROR identity and successful source response use the existing bounded cache");

  const mismatch = await handler(workerRequest({
    institution: "University of Rochester",
    institution_id: "https://ror.org/042nb2s44",
  }), env);
  assert.equal(mismatch.status, 400);
  assert.equal((await mismatch.json()).error.code, "invalid_request");

  const trustedAlias = institutionFromRor(rankRorOrganizations(aliases.Caltech.items, "Caltech")[0], "Caltech");
  assert.equal(trustedAlias.sources.NSF.search_name, "California Institute of Technology");
  assert.ok(trustedAlias.match_names.includes("Caltech"));
  assert.deepEqual(trustedAlias.sources.NSF.search_names, ["California Institute of Technology", "Caltech"]);
  assert.deepEqual(trustedAlias.sources.DOE.search_names, ["California Institute of Technology", "Caltech"]);
  assert.ok(!trustedAlias.sources.NIH.search_names.includes("CIT"), "short acronyms never become uncontrolled source queries");

  const nsfAliasQueries = [];
  const aliasNsf = await searchNsf(async url => {
    const parsed = new URL(url);
    nsfAliasQueries.push(parsed.searchParams.get("awardeeName"));
    const isAlias = decodeURIComponent(String(url)).includes("Caltech");
    const offset = Number(parsed.searchParams.get("offset"));
    const award = isAlias
      ? [nsfRaw("CALTECH-1", "Caltech", "Ada Researcher")]
      : Array.from({ length: 25 }, (_, index) => nsfRaw(`OTHER-${offset + index}`, "Another University", "Ada Researcher"));
    return new Response(JSON.stringify({ response: { award, metadata: { totalCount: isAlias ? 1 : 1_000 } } }), {
      headers: { "Content-Type": "application/json" },
    });
  }, { topic: "catalysis", _institution: trustedAlias }, { limit: 1, offset: 0, now: fixedNow });
  assert.deepEqual(aliasNsf.results.map(item => item.award_id), ["CALTECH-1"]);
  assert.equal(aliasNsf.upstream_queries, 2);
  assert.equal(aliasNsf.upstream_pages, 12);
  assert.equal(aliasNsf.safety_bound_reached, true);
  assert.ok(nsfAliasQueries.some(name => name?.includes("Caltech")), "the canonical query cannot monopolize the shared page budget");

  const onePage = html => html.replace("2</strong> items in <strong>2", "1</strong> items in <strong>1");
  const pagerLinks = Array.from({ length: 8 }, (_, index) => {
    const page = index + 3;
    return `<a href="javascript:__doPostBack('ctl00$MainContent$grdAwardsList$page${page}','')">${page}</a>`;
  }).join("");
  const canonicalDoe = doePage1
    .replace("2</strong> items in <strong>2", "10</strong> items in <strong>10")
    .replace("</table>", `${pagerLinks}</table>`)
    .replace("University of Rochester, Rochester, NY", "Another University, Elsewhere, NY")
    .replaceAll("F27KDXZMF9Y8", "OTHERUEI0001");
  const aliasDoe = onePage(doePage1)
    .replace("University of Rochester, Rochester, NY", "Caltech, Pasadena, CA")
    .replaceAll("F27KDXZMF9Y8", "OTHERUEI0002");
  const doeAliasQueries = [];
  const aliasDoeResult = await searchDoe(async (url, options = {}) => {
    if (String(url).includes("ViewPublicAbstract.aspx")) return new Response(doeAbstract);
    if (options.method === "POST") {
      const body = decodeURIComponent(String(options.body || ""));
      doeAliasQueries.push(body);
      return new Response(body.includes("Caltech") ? aliasDoe : canonicalDoe);
    }
    return new Response(doeForm);
  }, { topic: "catalysis", _institution: trustedAlias }, { limit: 1, offset: 0, now: fixedNow, sleep: async () => {} });
  assert.deepEqual(aliasDoeResult.results.map(item => item.award_id), ["DE-SC0020230"]);
  assert.equal(aliasDoeResult.upstream_queries, 2);
  assert.equal(aliasDoeResult.upstream_pages, 10);
  assert.equal(aliasDoeResult.safety_bound_reached, true);
  assert.equal(doeAliasQueries.filter(body => body.includes("Caltech")).length, 1);
});

test("investigator identities conservatively unify Marc variants and preserve conflicts", () => {
  const marcAwards = [
    normalizedAward({ source: "NSF", id: "NSF-1", name: "Marc Porosoff" }),
    normalizedAward({ source: "NSF", id: "NSF-2", name: "Marc Porosoff" }),
    normalizedAward({ source: "DOE", id: "DOE-1", name: "Marc D Porosoff" }),
  ];
  const marc = core.aggregateAwards(marcAwards);
  assert.equal(marc.investigator_count, 1);
  assert.equal(marc.investigators[0].name, "Marc D Porosoff");
  assert.equal(marc.investigators[0].projects, 3);
  assert.deepEqual(new Set(marc.investigators[0].variants.map(item => item.name)), new Set(["Marc Porosoff", "Marc D Porosoff"]));
  assert.deepEqual(plain(core.investigatorQueryVariants(marc.investigators[0], "NSF")), ["Marc Porosoff", "Marc D Porosoff", "Porosoff, Marc D"]);
  assert.equal(core.awardMatchesInvestigator(normalizedAward({ source: "DOE", id: "DOE-2", name: "Porosoff, Marc D" }), marc.investigators[0]), true);
  assert.equal(core.awardMatchesInvestigator(normalizedAward({ source: "DOE", id: "DOE-3", name: "Marc K Porosoff" }), marc.investigators[0]), false);

  const formatVariants = core.groupInvestigators([
    normalizedAward({ id: "F1", name: "Marc D. Porosoff" }),
    normalizedAward({ id: "F2", name: "Porosoff, Marc D" }),
    normalizedAward({ id: "F3", name: "Dr. Marc D. Porosoff" }),
    normalizedAward({ id: "F4", name: "Marc David Porosoff" }),
  ]);
  assert.equal(formatVariants.length, 1);
  assert.equal(formatVariants[0].projects, 4);

  const conflicts = core.groupInvestigators([
    normalizedAward({ id: "C1", name: "Marc D Porosoff", email: "marc.d@example.edu" }),
    normalizedAward({ id: "C2", name: "Marc K Porosoff", email: "marc.k@example.edu" }),
    normalizedAward({ id: "C3", name: "Alex Kim", email: "alex.one@example.edu" }),
    normalizedAward({ id: "C4", name: "Alex Kim", email: "alex.two@example.edu" }),
    normalizedAward({ id: "C5", name: "Taylor Smith", personId: "person-1" }),
    normalizedAward({ id: "C6", name: "Taylor Smith", personId: "person-2" }),
    normalizedAward({ id: "C7", name: "Jordan Lee", institution: "Other University", ror: "https://ror.org/012345678" }),
    normalizedAward({ id: "C8", name: "Jordan Lee" }),
  ]);
  assert.equal(conflicts.filter(group => group.name.includes("Porosoff")).length, 2);
  assert.equal(conflicts.filter(group => group.name === "Alex Kim").length, 2);
  assert.equal(conflicts.filter(group => group.name === "Taylor Smith").length, 2);
  assert.equal(conflicts.filter(group => group.name === "Jordan Lee").length, 2);
  assert.equal(core.normalizedInvestigatorName("Dr. Anne-Marie O’Neill Jr.").complete_key, "anne-marie||o'neill");
});

test("shared investigator identity state round-trips without exposing unbounded variants", () => {
  const url = core.urlForState("https://example.test/funded_awards.html", {
    open: true,
    institution: "University of Rochester",
    ror_id: "https://ror.org/022kthw22",
    agency: "all",
    pi: "Marc D Porosoff",
    pi_identity: true,
  });
  assert.equal(url.searchParams.get("ii_pi_identity"), "1");
  const restored = core.stateFromSearch(url.search);
  assert.equal(restored.pi, "Marc D Porosoff");
  assert.equal(restored.pi_identity, true);
  assert.equal([...url.searchParams.keys()].some(key => /variant|email|profile/i.test(key)), false);
});

test("deterministic institutional answers and bounded narrative citations use only loaded awards", () => {
  const awards = [
    normalizedAward({ source: "DOE", id: "DOE-1", name: "Marc D Porosoff", title: "Catalysis for carbon conversion", year: 2021 }),
    normalizedAward({ source: "DOE", id: "DOE-2", name: "Ada Researcher", title: "Selective catalysis", year: 2024 }),
  ];
  const aggregate = core.aggregateAwards(awards);
  const sources = [{ source: "DOE", status: "ok", has_more: true }, { source: "NIH", status: "unavailable", has_more: false }];
  const who = core.deterministicInstitutionAnswer({ question: "Who has DOE BES awards?", intent: "investigators", aggregate, sources });
  assert.match(who.answer, /Marc D Porosoff/);
  assert.match(who.answer, /Ada Researcher/);
  assert.deepEqual(who.has_more, ["DOE"]);
  assert.deepEqual(who.unavailable, ["NIH"]);
  const programs = core.deterministicInstitutionAnswer({ question: "Which programs funded catalysis?", intent: "programs", aggregate, sources });
  assert.match(programs.answer, /Office of Basic Energy Sciences/);
  const count = core.deterministicInstitutionAnswer({ question: "How many projects?", intent: "count", aggregate, sources });
  assert.match(count.answer, /^2 normalized matching awards/);
  const years = core.deterministicInstitutionAnswer({ question: "Which years?", intent: "years", aggregate, sources });
  assert.match(years.answer, /2021 through 2024/);

  const pack = core.questionEvidencePack(awards);
  assert.equal(pack.awards.length, 2);
  const valid = core.validateNarrativeAnswer({ claims: [{ text: "Both returned titles concern catalysis.", evidence_ids: ["DOE:DOE-1", "DOE:DOE-2"] }] }, pack.awards);
  assert.equal(valid.claims.length, 1);
  assert.equal(core.validateNarrativeAnswer({ claims: [{ text: "Fabricated claim", evidence_ids: ["DOE:UNKNOWN"] }] }, pack.awards), null);
  assert.equal(core.validateNarrativeAnswer({ claims: [{ text: "<img src=x onerror=alert(1)>", evidence_ids: ["DOE:DOE-1"] }] }, pack.awards).claims[0].text.includes("<img"), true);
  assert.match(appSource, /escapeHtml\(claim\.text\)/, "model text is escaped at the only rendering boundary");

  const many = Array.from({ length: 30 }, (_, index) => normalizedAward({ source: "NSF", id: `N-${index}`, name: `Person ${index}`, title: `Title ${index}` }));
  const bounded = core.questionEvidencePack(many);
  assert.equal(bounded.awards.length, 24);
  assert.equal(bounded.truncated, true);
  assert.ok(bounded.serialized_characters <= bounded.limits.serialized_characters);
});

test("question-provider payloads enforce privacy boundaries and malformed responses fall back", () => {
  const award = normalizedAward({ source: "NSF", id: "NSF-9", name: "Ada Researcher" });
  award.abstract = "A".repeat(2_000);
  const evidencePack = core.questionEvidencePack([award]);
  const payload = core.questionProviderPayload({
    question: "Summarize the returned catalysis work",
    institution: { id: "https://ror.org/022kthw22", canonical_name: "University of Rochester", aliases: ["UR"] },
    filters: { agency: "NSF", topic: "catalysis", profile: "secret", saved_notes: "secret" },
    intent: "narrative",
    evidencePack,
    provider_key: "never",
  });
  assert.deepEqual(Object.keys(payload), ["question", "institution", "visible_filters", "answer_intent", "public_award_evidence", "evidence_truncated"]);
  const serialized = JSON.stringify(payload);
  for (const forbidden of ["profile", "cv", "orcid", "saved_notes", "pursuit", "alert", "provider_key", "never"]) {
    assert.equal(serialized.toLowerCase().includes(forbidden), false, forbidden);
  }
  assert.equal(payload.public_award_evidence[0].abstract_excerpt.length, 800);
  assert.throws(() => ai.extractJson("not valid JSON"), /malformed or incomplete/);
  assert.match(pageSource, /Structured award search and institution resolution do not require an AI key/);
  assert.match(pageSource, /Update answer using loaded records/);
  assert.match(appSource, /snapshot\.signature === answerEvidenceSignature\(\)/);
  const loadMoreSource = appSource.slice(appSource.indexOf("async function loadMoreSource"), appSource.indexOf("function clearSearch"));
  assert.doesNotMatch(loadMoreSource, /providerJson|refreshQuestionAnswer/, "Load more retains the answer without a paid provider call");
  assert.match(pageSource, /profiles, CVs, ORCID publication text, uploaded documents, saved notes, pursuit state, alert data, unrelated chat, or provider keys/);
});
