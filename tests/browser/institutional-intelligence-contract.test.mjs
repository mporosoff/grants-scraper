import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { buildDoeSearchForm } from "../../workers/award-api/src/adapters/doe.js";
import { createHandler } from "../../workers/award-api/src/index.js";
import { institutionFromRor, resolveInstitution } from "../../workers/award-api/src/institutions.js";
import { rankRorOrganizations } from "../../workers/award-api/src/ror.js";

const root = new URL("../../", import.meta.url);
const [
  aliases, fundedCoreSource, coreSource, appSource, page, fundingPage, teamPage, styles,
  credentialsSource, doeForm, fundingAppSource, deploymentSource,
] = await Promise.all([
  readFile(new URL("tests/fixtures/awards/ror_aliases.json", root), "utf8").then(JSON.parse),
  readFile(new URL("assets/funded-awards-core.js", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence-core.js", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence-snapshots.js", root), "utf8"),
  readFile(new URL("funded_awards.html", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
  readFile(new URL("team_match.html", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence.css", root), "utf8"),
  readFile(new URL("assets/credentials.js", root), "utf8"),
  readFile(new URL("tests/fixtures/awards/doe_search_form.html", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
]);

const sandbox = { URL, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(fundedCoreSource, sandbox);
vm.runInContext(coreSource, sandbox);
const core = sandbox.FUNDING_INSTITUTIONAL_INTELLIGENCE;
const env = {
  AWARD_API_ENABLED: "true",
  CACHE_TTL_SECONDS: "3600",
  MAX_SOURCE_RESULTS: "25",
  AWARD_SOURCE_RATE_LIMIT: "12",
  ROR_SEARCH_RATE_LIMIT: "60",
  ROR_RESOLVE_RATE_LIMIT: "20",
  AWARD_RATE_LIMIT_SECRET: "deterministic-award-rate-limit-secret",
  AWARD_RATE_LIMITER: {
    idFromName: name => name,
    get: () => ({
      fetch: async () => new Response(JSON.stringify({ success: true, retry_after_seconds: 0 }), {
        headers: { "Content-Type": "application/json" },
      }),
    }),
  },
};

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function award(overrides = {}) {
  return {
    source: "NSF",
    award_id: "NSF-1",
    award_year: 2024,
    program_name: "Catalysis",
    program_codes: ["140100"],
    activity_code: null,
    subagency: "Engineering",
    principal_investigators: [{ name: "Ada Investigator" }],
    institution: { normalized_name: "University of Rochester", identifiers: { ror: "https://ror.org/022kthw22" } },
    ...overrides,
  };
}

test("ROR acronym and alias metadata deterministically resolves required institutions", () => {
  const expected = {
    MIT: ["Massachusetts Institute of Technology", "https://ror.org/042nb2s44"],
    Caltech: ["California Institute of Technology", "https://ror.org/05dxps055"],
    UVA: ["University of Virginia", "https://ror.org/0153tk833"],
    RIT: ["Rochester Institute of Technology", "https://ror.org/00v4yb702"],
    UCLA: ["University of California, Los Angeles", "https://ror.org/046rm7j60"],
  };
  for (const [query, [name, id]] of Object.entries(expected)) {
    const ranked = rankRorOrganizations(aliases[query].items, query);
    assert.equal(ranked[0].canonical_name, name);
    assert.equal(ranked[0].id, id);
    assert.equal(ranked[0].match.exact, true);
    if (query === "Caltech") assert.equal(core.chooseInstitution(query, ranked).canonical_name, name);
    else assert.equal(core.chooseInstitution(query, ranked), null, `${query} requires explicit acronym selection`);
  }
});

test("the ROR endpoint is bounded, cached, origin-protected, and independent of award credentials", async () => {
  const calls = [];
  const cacheValues = new Map();
  const cache = {
    async match(request) { return cacheValues.get(request.url)?.clone(); },
    async put(request, response) { cacheValues.set(request.url, response.clone()); },
  };
  const fetchImpl = async url => {
    calls.push(String(url));
    return new Response(JSON.stringify(aliases.MIT), { headers: { "Content-Type": "application/json" } });
  };
  const handler = createHandler({ fetchImpl, cache });
  const request = () => new Request("https://award.test/institutions/search?query=MIT", {
    headers: { Origin: "http://localhost:8765" },
  });
  const first = await handler(request(), env);
  const firstBody = await first.json();
  assert.equal(first.status, 200);
  assert.equal(firstBody.registry.source, "ROR");
  assert.equal(firstBody.registry.license, "CC0-1.0");
  assert.equal(firstBody.registry.cache, "miss");
  assert.equal(firstBody.institutions[0].canonical_name, "Massachusetts Institute of Technology");
  const second = await handler(request(), env);
  assert.equal((await second.json()).registry.cache, "hit");
  assert.equal(calls.length, 1);
  assert.equal((await handler(new Request("https://award.test/institutions/search?query=MIT", {
    headers: { Origin: "https://evil.example" },
  }), env)).status, 403);
  assert.equal((await handler(new Request("https://award.test/institutions/search?query=M"), env)).status, 400);
});

test("existing institution identities retain source-specific award query identifiers", () => {
  const rochester = resolveInstitution({ id: "https://ror.org/022kthw22" });
  assert.equal(rochester.id, "university-of-rochester");
  assert.deepEqual(rochester.sources.NSF.uei, ["F27KDXZMF9Y8"]);
  assert.deepEqual(rochester.sources.NIH.ipf, ["7047101"]);
  assert.equal(rochester.sources.DOE.search_name, "University of Rochester");
  const mit = institutionFromRor(rankRorOrganizations(aliases.MIT.items, "MIT")[0], "Massachusetts Institute of Technology");
  assert.equal(mit.ror_id, "https://ror.org/042nb2s44");
  assert.equal(mit.sources.NSF.search_name, "Massachusetts Institute of Technology");
  assert.equal(resolveInstitution({
    id: "https://ror.org/022kthw22",
    name: "Massachusetts Institute of Technology",
  }), null);
});

test("structured filters reuse the normalized cross-agency award request contract", () => {
  const request = core.buildAwardRequest({
    institution: "Massachusetts Institute of Technology",
    ror_id: "https://ror.org/042nb2s44",
    agency: "all",
    topic: "catalysis",
    pi: "Ada Investigator",
    pi_identity: false,
    program_officer: "Megan Manager",
    year_start: 2019,
    year_end: 2026,
  });
  assert.deepEqual(plain(request), {
    sources: ["NSF", "NIH", "DOE"],
    criteria: {
      institution: "Massachusetts Institute of Technology",
      institution_id: "https://ror.org/042nb2s44",
      topic: "catalysis",
      pi: "Ada Investigator",
      program_officer: "Megan Manager",
      year_start: 2019,
      year_end: 2026,
    },
    limit: 10,
    offset: 0,
  });
  assert.deepEqual(plain(core.buildAwardRequest({
    institution: "",
    agency: "NSF",
    topic: "electrocatalysis",
    program_officer: "Alex Officer",
    offset: 10,
  })), {
    sources: ["NSF"],
    criteria: { topic: "electrocatalysis", program_officer: "Alex Officer" },
    limit: 10,
    offset: 10,
  });
  assert.throws(() => core.buildAwardRequest({ agency: "all" }), /Enter an institution, topic, program, investigator, or program officer/);
  assert.deepEqual(plain(core.programCriterion("DOE", "BES")), { program_office: "SC-32" });
  assert.deepEqual(plain(core.programCriterion("NIH", "R01")), { program: "R01" });
  assert.throws(() => core.buildAwardRequest({ institution: "MIT", agency: "all", program: "Catalysis" }), /Choose NSF, NIH, or DOE/);
  assert.throws(() => core.buildAwardRequest({ topic: "catalysis", agency: "NSF", year_start: 1989, year_end: 2100 }), /50 years or fewer/);
  const form = buildDoeSearchForm(doeForm, { program_office: "SC-32" });
  assert.deepEqual(JSON.parse(form.get("ctl00_MainContent_pnlSearch_srchOrgCode_ClientState")), {
    isEnabled: true,
    logEntries: [],
    selectedIndices: [],
    checkedIndices: [1, 2],
    scrollPosition: 0,
  });
});

test("aggregates returned awards and preserves investigator and program drill-down identities", () => {
  const aggregate = core.aggregateAwards([
    award(),
    award({ source: "NIH", award_id: "NIH-1", award_year: 2025, program_name: null, program_codes: ["R01", "GM"], activity_code: "R01", principal_investigators: [{ name: "Ada Investigator" }, { name: "Grace Investigator" }] }),
    award({ source: "DOE", award_id: "DOE-1", award_year: 2022, program_name: "Catalysis Science", subagency: "Office of Basic Energy Sciences", principal_investigators: [{ name: "Lin Investigator" }] }),
    award(),
  ]);
  assert.equal(aggregate.project_count, 3);
  assert.equal(aggregate.investigator_count, 3);
  assert.equal(aggregate.year_start, 2022);
  assert.equal(aggregate.year_end, 2025);
  const ada = aggregate.investigators.find(item => item.name === "Ada Investigator");
  assert.equal(ada.projects, 2);
  assert.deepEqual(plain(ada.variants.map(item => item.source)), ["NSF", "NIH"]);
  assert.ok(aggregate.programs.some(item => item.source === "NIH" && item.query === "R01"));
  assert.ok(aggregate.programs.some(item => item.source === "DOE" && item.query === "Catalysis Science" && item.parent_label === "Office of Basic Energy Sciences"));
});

test("share URLs round-trip institution and all transparent filters", () => {
  const url = core.urlForState("https://example.test/funded_awards.html?opportunity=123&q=opportunities", {
    open: true,
    institution: "University of California, Los Angeles",
    ror_id: "https://ror.org/046rm7j60",
    agency: "DOE",
    program: "BES",
    topic: "catalysis",
    pi: "Ada Investigator",
    program_officer: "Megan Manager",
    year_start: 2020,
    year_end: 2026,
  });
  assert.equal(url.searchParams.get("q"), null, "legacy search parameters are replaced by the unified state");
  assert.equal(url.searchParams.get("opportunity"), null, "a new unified search clears an exact-opportunity selection");
  assert.deepEqual(plain(core.stateFromSearch(url.search)), {
    open: true,
    institution: "University of California, Los Angeles",
    ror_id: "https://ror.org/046rm7j60",
    agency: "DOE",
    program: "BES",
    topic: "catalysis",
    pi: "Ada Investigator",
    program_officer: "Megan Manager",
    year_start: "2020",
    year_end: "2026",
    offset: 0,
    snapshot_id: "",
    page: 1,
    page_size: 10,
    facet_type: "all",
    facet_key: "",
  });
});

test("share URLs preserve complete opaque program facet keys", () => {
  const facetKey = `NSF:${"parent ".repeat(45)}:${"child ".repeat(45)}`.trim();
  assert.ok(facetKey.length > 300);
  const url = core.urlForState("https://example.test/funded_awards.html", {
    open: true,
    snapshot_id: "a".repeat(64),
    facet_type: "program",
    facet_key: facetKey,
  });
  assert.equal(url.searchParams.get("ii_facet_key"), facetKey);
  assert.equal(core.stateFromSearch(url.search).facet_key, facetKey);
});

test("explicitly named investigators survive an incomplete question translation", () => {
  assert.equal(core.explicitInvestigator("What has Marc Porosoff been funded to do?"), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Has Marc Porosoff received NSF funding?"), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Did Marc Porosoff receive NIH funding?"), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Did Dr. Marc Porosoff receive NSF funding?"), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Show awards for investigator Marc D Porosoff."), "Marc D Porosoff");
  assert.equal(core.explicitInvestigator("Show awards for Professor Marc Porosoff."), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Show awards for Professor Marc Porosoff from NSF."), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Show awards for Investigator Named Marc Porosoff."), "Marc Porosoff");
  assert.equal(core.explicitInvestigator("Who at this institution has received awards from DOE BES?"), "");
  assert.equal(core.explicitInvestigator("Show funding for Basic Energy Sciences."), "");
  assert.equal(core.explicitInvestigator("What has Basic Energy Sciences been funded to do?"), "");
  assert.equal(core.explicitInvestigator("What has Major Research Instrumentation received?", "", "Major Research Instrumentation"), "");
  assert.equal(core.explicitInvestigator("What has Major Research Instrumentation received?", "", "MRI"), "");
  assert.equal(core.explicitInvestigator("What has CAREER Program received?", "", "CAREER"), "");
  assert.equal(core.explicitInvestigator("What has CAREER Award received?", "", "CAREER"), "");
  assert.equal(core.explicitInvestigator("What has CAREER Grant received?", "", "CAREER"), "");
  assert.equal(core.explicitInvestigator("What has Faculty Early Career Development received?", "", "CAREER"), "");
  assert.equal(core.explicitInvestigator("What has Artificial Intelligence Research received?", "", "", [], "Artificial Intelligence Research"), "");
  assert.equal(core.explicitInvestigator("What has University of Rochester been funded to do?", "University of Rochester"), "");
  assert.equal(core.explicitInvestigator("What has Cold Spring Harbor received?", "Cold Spring Harbor Laboratory", "", ["Cold Spring Harbor", "CSHL"]), "");
  assert.equal(core.explicitInvestigator("What has Cold Spring Harbor received?", "Cold Spring Harbor Laboratory"), "");
  assert.equal(core.explicitInvestigator("Which programs have catalysis awards?"), "");
});

test("snapshot URLs and replacement results have one committed owner", () => {
  const historySource = appSource.slice(appSource.indexOf("function historyViewState("), appSource.indexOf("async function postJson("));
  assert.match(historySource, /mode === "push"[\s\S]*history\.replaceState\([\s\S]*history\.pushState\([\s\S]*scheduleCurrentHistoryViewState\(\)/);
  assert.match(historySource, /requestAnimationFrame\([\s\S]*requestAnimationFrame\([\s\S]*recordCurrentHistoryViewState\(\)/);
  const syncUrlSource = appSource.slice(appSource.indexOf("function syncUrl("), appSource.indexOf("async function postJson("));
  assert.match(syncUrlSource, /state\.submitted && state\.snapshot\?\.snapshot_id[\s\S]*\{ \.\.\.state\.submitted, \.\.\.snapshotViewState\(\) \}/);
  assert.doesNotMatch(syncUrlSource, /\.\.\.formState\(\)[\s\S]*\.\.\.formState\(\)/);

  const runSearchSource = appSource.slice(appSource.indexOf("async function runSearch("), appSource.indexOf("async function changeFacet("));
  const createIndex = runSearchSource.indexOf("await postJson(api.snapshotUrl");
  const initialPageIndex = runSearchSource.indexOf("await requestSnapshotPage");
  const stageIndex = runSearchSource.indexOf("stagedSnapshotResult(");
  const commitIndex = runSearchSource.indexOf("commitSnapshotResult(");
  assert.ok(createIndex > -1 && initialPageIndex > createIndex && stageIndex > initialPageIndex && commitIndex > stageIndex);
  assert.doesNotMatch(runSearchSource, /state\.(?:submitted|snapshot|pagePayload|aggregate|residentAwards)\s*=/);

  const commitSource = appSource.slice(appSource.indexOf("function commitSnapshotResult("), appSource.indexOf("async function fetchPage("));
  for (const field of ["submitted", "snapshot", "pagePayload", "aggregate", "residentAwards", "sourceOffsets", "question"])
    assert.match(commitSource, new RegExp(`state\\.${field}`));
  assert.ok(commitSource.indexOf("renderPage(") > commitSource.indexOf("state.pagePayload ="));
  assert.ok(commitSource.indexOf("syncUrl(") > commitSource.indexOf("renderPage("));

  const hydrationSource = appSource.slice(appSource.indexOf("async function loadSourceBatch("), appSource.indexOf("async function retrySource("));
  assert.match(hydrationSource, /error\?\.code !== "snapshot_expired"[\s\S]*rebuildSubmittedSnapshotView\([\s\S]*while \(offset <= requestedOffset\)[\s\S]*requestSourceBatch\(source, offset\)/);

  const retrySource = appSource.slice(appSource.indexOf("async function stagedSourceRetry("), appSource.indexOf("function answerEvidenceSignature("));
  assert.match(retrySource, /stagedSourceRetry\(source, previous[\s\S]*error\?\.code !== "snapshot_expired"[\s\S]*rebuildSubmittedSnapshotView\([\s\S]*stagedSourceRetry\(source, previous/);
});

test("the feature is Funded Awards-only, responsive, accessible, no-key capable, and shares AI credentials", () => {
  assert.match(page, /id="institutional-intelligence"/);
  assert.match(page, /role="combobox"[\s\S]*aria-controls="ii-institution-options"/);
  assert.match(page, /id="ii-status" role="status" aria-live="polite"/);
  assert.match(page, /Funded Award Intelligence/);
  assert.match(page, /id="award-search-form"[^>]*hidden/);
  assert.match(page, /id="ii-program-officer"/);
  assert.match(page, /Structured award search and institution resolution do not require an AI key/);
  assert.match(page, /assets\/institutional-intelligence-snapshots\.js/);
  assert.match(page, /Research Organization Registry \(ROR\)/);
  assert.doesNotMatch(page, /Optional institution identity:/);
  assert.match(page, /<select id="ii-investigators"[^>]*aria-labelledby="ii-investigators-heading"/);
  assert.match(page, /<select id="ii-programs"[^>]*aria-labelledby="ii-programs-heading"/);
  assert.doesNotMatch(page, /class="ii-facet-list"/);
  assert.doesNotMatch(appSource, /data-ii-pi=|data-ii-program=/);
  assert.match(appSource, /snapshotPageUrl/);
  assert.match(appSource, /data-ii-load-source/);
  assert.match(appSource, /data-ii-retry-source/);
  assert.doesNotMatch(appSource, /searchUrl|awards\/search/);
  assert.match(page, /id="ii-card-pagination"[\s\S]*>Previous<[\s\S]*id="ii-card-page-numbers"[\s\S]*>Next</);
  assert.match(page, /id="ii-page-size"[\s\S]*value="10"[\s\S]*value="25"[\s\S]*value="50"/);
  assert.match(styles, /@media \(max-width: 780px\)[\s\S]*\.ii-shell-heading \{[\s\S]*display: none/);
  assert.ok(page.indexOf('id="ii-ask"') < page.indexOf('id="ii-output"'));
  assert.doesNotMatch(fundingPage, /id="institutional-intelligence"|assets\/institutional-intelligence-snapshots\.js/);
  assert.doesNotMatch(teamPage, /institutional-intelligence|Institutional Intelligence/);
  assert.match(styles, /@media \(max-width: 520px\)/);
  assert.match(appSource, /credentials\.loadKey\(provider\)/);
  assert.match(appSource, /credentials\.saveKey\(provider, key\)/);
  assert.match(appSource, /\$\("k-provider"\)/);
  assert.doesNotMatch(appSource, /localStorage\.(?:setItem|getItem)|funding-finder\.institutional.*key/i);
  assert.match(credentialsSource, /funding-finder\.credentials\.v1/);
  assert.match(fundingAppSource, /redirectLegacyInstitutionalIntelligenceUrl/);
  assert.match(fundingAppSource, /new URL\("\.\/funded_awards\.html"/);
  assert.match(appSource, /mailto:\$\{escapeAttribute\(email\)\}/);
  const workerHealthGate = deploymentSource.slice(
    deploymentSource.indexOf("Wait for the Award Worker health contract"),
    deploymentSource.indexOf("Run bounded exact-source smokes"),
  );
  assert.match(workerHealthGate, /institution_registry\.source[\s\S]*= "ROR"/);
  assert.match(workerHealthGate, /institution_registry\.adapter_version[\s\S]*= "1\.1\.0"/);
  assert.doesNotMatch(coreSource + appSource, /embedding|voyage|semantic|rerank/i);
  assert.match(appSource, /explicitInvestigator\(question, current\.institution, plan\.program/);
  const askQuestionSource = appSource.slice(
    appSource.indexOf("async function askQuestion()"),
    appSource.indexOf("function bindEvents()"),
  );
  assert.match(askQuestionSource, /if \(state\.questionSubmitting\) return;[\s\S]*state\.questionSubmitting = true;[\s\S]*setBusy\(true\);[\s\S]*await resolveTypedInstitution\(\)/);
  assert.match(askQuestionSource, /const questionSequence = \+\+state\.questionSequence;[\s\S]*if \(questionSequence !== state\.questionSequence\) return;/);
  assert.match(askQuestionSource, /finally \{[\s\S]*if \(questionSequence === state\.questionSequence\) \{[\s\S]*state\.questionSubmitting = false;[\s\S]*setBusy\(false\)/);
  assert.match(askQuestionSource, /const questionState = \{[\s\S]*runSearch\(\{ historyMode: "push", resolveInstitution: false, focusResults: true, questionSearch: true, questionState, searchState: next \}\)/);
  assert.match(askQuestionSource, /refreshQuestionAnswer\(\)/);
  assert.match(appSource, /\$\("ii-question"\)\.addEventListener\("keydown"[\s\S]*event\.key !== "Enter"[\s\S]*event\.repeat[\s\S]*askQuestion\(\)/);
});
