import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [
  adapter, contract, worker, institutions, linksSource, coreSource, appSource,
  page, recon, readme, workflow, smoke, packageJson, evidence,
] = await Promise.all([
  readFile(new URL("workers/award-api/src/adapters/doe.js", root), "utf8"),
  readFile(new URL("workers/award-api/src/contract.js", root), "utf8"),
  readFile(new URL("workers/award-api/src/index.js", root), "utf8"),
  readFile(new URL("workers/award-api/src/institutions.js", root), "utf8"),
  readFile(new URL("assets/award-links.js", root), "utf8"),
  readFile(new URL("assets/funded-awards-core.js", root), "utf8"),
  readFile(new URL("assets/funded-awards.js", root), "utf8"),
  readFile(new URL("funded_awards.html", root), "utf8"),
  readFile(new URL("docs/DOE_PAMS_PUBLIC_AWARD_RECONNAISSANCE.md", root), "utf8"),
  readFile(new URL("workers/award-api/README.md", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
  readFile(new URL("tools/smoke_award_worker.mjs", root), "utf8"),
  readFile(new URL("package.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/doe_awards_phase4.json", root), "utf8").then(JSON.parse),
]);

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(linksSource, sandbox);
vm.runInContext(coreSource, sandbox);
const links = sandbox.FUNDING_AWARD_LINKS;
const product = sandbox.FUNDING_AWARD_PRODUCT;

test("PAMS reconnaissance records the stable account-free public contract before extraction", () => {
  for (const phrase of [
    "ASP.NET WebForms",
    "AwardSearchExternal.aspx",
    "ViewPublicAbstract.aspx",
    "__VIEWSTATE",
    "ctl00_MainContent_grdAwardsList",
    "15",
    "University of Rochester",
    "William Jones",
    "Catalysis",
    "personal PAMS account",
  ]) assert.match(recon, new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  assert.match(recon, /does not expose a documented JSON award API/i);
  assert.match(recon, /did not expose.*email/i);
  assert.match(recon, /does not infer structured co-PI/i);
});

test("DOE remains an isolated, bounded, fail-closed PAMS adapter", () => {
  assert.equal(packageJson.dependencies.cheerio, "1.0.0");
  assert.match(adapter, /from "cheerio\/slim"/);
  assert.match(adapter, /DOE_MAX_RESULTS = 10/);
  assert.match(adapter, /DOE_MAX_OFFSET = 100/);
  assert.match(adapter, /DOE_ABSTRACT_CONCURRENCY = 2/);
  assert.match(adapter, /DOE_ABSTRACT_PAUSE_MS = 125/);
  assert.match(adapter, /sourceInvalid\(\)/);
  assert.match(adapter, /source_rate_limited|fetchSourceText/);
  assert.match(adapter, /email: null/g);
  assert.doesNotMatch(adapter, /@[A-Za-z0-9.-]+|login|password|api[_-]?key|bearer/i);
  assert.match(adapter, /amount_awarded_to_date/);
  assert.match(adapter, /program_manager/);
  assert.match(adapter, /opportunity_numbers/);
  assert.match(adapter, /recordMatchesInstitution/);
  assert.match(adapter, /status: abstracts\.failed \? "degraded" : "available"/);
  assert.match(worker, /adapters = \{ NSF: searchNsf, NIH: searchNih, DOE: searchDoe, DOD: searchDod \}/);
  assert.match(worker, /Promise\.all\(normalized\.sources\.map/);
  assert.match(worker, /sourceSummary/);
  assert.match(institutions, /DOE: \{ search_name: cleanName, uei: \[\] \}/);
  assert.match(contract, /cleanSourceText/);
});

test("Funded Awards exposes source-native DOE searches without award vectors or reranking", () => {
  assert.deepEqual(Array.from(product.sourcesForAgency("all")), ["NSF", "NIH", "DOE", "DOD"]);
  const searches = [
    { state: { mode: "topic", agency: "DOE", query: "carbon dioxide" }, criterion: "topic" },
    { state: { mode: "program", agency: "DOE", query: "Catalysis" }, criterion: "program" },
    { state: { mode: "program", agency: "DOE", query: "DE-FOA-0003612" }, criterion: "opportunity_number" },
    { state: { agency: "DOE", institution: "University of Rochester" }, criterion: "institution" },
    { state: { agency: "DOE", pi: "William Jones" }, criterion: "pi" },
  ];
  for (const { state, criterion } of searches) {
    const request = product.buildRequest({ ...state, offset: 0 }, null, 25);
    assert.deepEqual(Array.from(request.sources), ["DOE"]);
    assert.equal(request.limit, 10);
    assert.ok(request.criteria[criterion]);
  }
  assert.match(page, /DOE Office of Science/);
  assert.match(appSource, /Direct \$\{escapeHtml\(source\)\} source field/);
  assert.match(appSource, /Official \$\{escapeHtml\(source\)\} record/);
  assert.match(appSource, /Source-native order; no cross-source reranking/);
  assert.doesNotMatch(coreSource + appSource + adapter, /FUNDING_HYBRID_SEARCH|voyage|embedding|vectorUrl/i);
});

test("Funding Finder claims only exact Office of Science FOA mappings", () => {
  const exact = links.lookupForOpportunity({
    opportunity_id: "361526",
    opportunity_number: "DE-FOA-0003612",
    agency_code: "PAMS-SC",
    agency: "Office of Science",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(exact)), {
    source: "DOE",
    label: "DE-FOA-0003612",
    criteria: { opportunity_number: "DE-FOA-0003612" },
    mapping_basis: "exact_doe_foa_number",
    mapping_source_url: "",
  });
  assert.equal(links.lookupForOpportunity({
    opportunity_number: "DE-FOA-0003612",
    agency_code: "DOE-NETL",
    agency: "National Energy Technology Laboratory",
  }), null);
  assert.equal(links.lookupForOpportunity({
    opportunity_number: "DOE SCIENCE PROGRAM",
    agency_code: "PAMS-SC",
    agency: "Office of Science",
  }), null);
  assert.equal(links.programIdentityForOpportunity({
    opportunity_number: "DE-FOA-0003612",
    agency_code: "PAMS-SC",
  }), null, "Phase 4 does not broaden Phase 3 controlled program watches");
});

test("release validation uses fixtures in PR checks and one bounded DOE production smoke", () => {
  assert.match(workflow, /funded-awards-phase4-contract\.test\.mjs/);
  assert.match(workflow, /push:\s*\n\s*branches:\s*\n\s*- main/);
  assert.doesNotMatch(workflow, /pull_request:/);
  assert.match(smoke, /sources: \["DOE"\].*award_id: "DE-SC0020230"/s);
  assert.match(smoke, /AbortSignal\.timeout\(45_000\)/);
  assert.match(readme, /pull-request CI uses[\s\S]*deterministic fixtures and does not call PAMS/i);
  assert.match(workflow, /Capture the active Award Worker version for rollback/);
  assert.match(workflow, /sort_by\(\[\(\.created_on \/\/ ""\), \(\.id \/\/ ""\)\]\)\s*\| last/);
  assert.doesNotMatch(workflow, /\.\[0\]\.versions/);
});

test("Phase 4 evaluation closes only the DOE gate", () => {
  assert.equal(evidence.phase, 4);
  assert.match(evidence.decision, /^PHASE 4 PASSED/);
  assert.equal(evidence.gate.public_account_free_access_documented, true);
  assert.equal(evidence.gate.institution_pi_and_program_search_verified, true);
  assert.equal(evidence.gate.public_abstracts_and_official_links_verified, true);
  assert.equal(evidence.gate.no_contact_inference, true);
  assert.equal(evidence.gate.nsf_nih_unaffected_by_doe_failure, true);
  assert.equal(evidence.gate.exact_or_controlled_mapping_only, true);
  assert.equal(evidence.gate.phase5_not_started, true);
  assert.deepEqual(evidence.scope.ranking_files_changed, []);
  assert.equal(evidence.scope.award_vectors_built, false);
});
