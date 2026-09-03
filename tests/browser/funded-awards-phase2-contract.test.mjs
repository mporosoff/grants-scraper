import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [
  page, linksSource, coreSource, appSource, styles, fundingApp,
  phase1Evidence, phase2Evidence, deployWorkflow, workerSmoke,
] = await Promise.all([
  readFile(new URL("funded_awards.html", root), "utf8"),
  readFile(new URL("assets/award-links.js", root), "utf8"),
  readFile(new URL("assets/funded-awards-core.js", root), "utf8"),
  readFile(new URL("assets/funded-awards.js", root), "utf8"),
  readFile(new URL("assets/funded-awards.css", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("evaluation/funded_awards_phase1.json", root), "utf8").then(JSON.parse),
  readFile(new URL("evaluation/funded_awards_phase2.json", root), "utf8").then(JSON.parse),
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
  readFile(new URL("tools/smoke_award_worker.mjs", root), "utf8"),
]);

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(linksSource, sandbox);
vm.runInContext(coreSource, sandbox);
const links = sandbox.FUNDING_AWARD_LINKS;
const product = sandbox.FUNDING_AWARD_PRODUCT;

test("eligible Funding Finder records use exact identifiers or reviewed NSF parent mappings", () => {
  const cps = links.lookupForOpportunity({
    opportunity_id: "362061",
    opportunity_number: "PD-26-367Y",
    agency_code: "NSF",
  });
  assert.equal(cps.source, "NSF");
  assert.equal(cps.mapping_basis, "reviewed_parent_program");
  assert.deepEqual(Array.from(cps.criteria.program_codes), ["367Y00", "140100", "764400", "141700", "140300"]);

  const cbet = links.lookupForOpportunity({
    opportunity_id: "363616",
    opportunity_number: "26-518",
    agency_code: "NSF",
  });
  assert.equal(cbet.mapping_basis, "reviewed_parent_program");
  assert.deepEqual(Array.from(cbet.criteria.program_codes).slice(0, 4), ["366Y00", "367Y00", "369Y00", "370Y00"]);
  assert.equal(cbet.criteria.program_codes.length, 18);

  const probability = links.lookupForOpportunity({
    opportunity_id: "353353",
    opportunity_number: "PD-18-1263",
    agency_code: "NSF",
  });
  assert.equal(probability.mapping_basis, "exact_nsf_program_element");
  assert.deepEqual(Array.from(probability.criteria.program_codes), ["126300"]);

  const nih = links.lookupForOpportunity({
    opportunity_id: "361187",
    opportunity_number: "PAR-26-114",
    agency_code: "HHS-NIH11",
  });
  assert.equal(nih.mapping_basis, "exact_nih_opportunity_number");
  assert.equal(nih.criteria.opportunity_number, "PAR-26-114");
  assert.equal(links.fundedAwardsHref({
    opportunity_id: "361187",
    opportunity_number: "PAR-26-114",
    agency_code: "HHS-NIH11",
  }), "./funded_awards.html?opportunity=361187");

  const doe = links.lookupForOpportunity({
    opportunity_id: "361526",
    opportunity_number: "DE-FOA-0003612",
    agency_code: "PAMS-SC",
    agency: "Office of Science",
  });
  assert.equal(doe.source, "DOE");
  assert.equal(doe.mapping_basis, "exact_doe_foa_number");
  assert.equal(doe.criteria.opportunity_number, "DE-FOA-0003612");
  assert.equal(links.lookupForOpportunity({
    opportunity_id: "outside-office-of-science",
    opportunity_number: "DE-FOA-0003612",
    agency_code: "DOE-NETL",
    agency: "National Energy Technology Laboratory",
  }), null, "the same FOA syntax outside DOE Office of Science is not claimed as a PAMS mapping");

  assert.equal(links.lookupForOpportunity({
    opportunity_id: "361333",
    opportunity_number: "26-506",
    agency_code: "NSF",
  }), null, "an NSF solicitation without an exact reviewed award mapping is not eligible");
});

test("standalone searches use source-native criteria and never opportunity semantic vectors", () => {
  const topic = product.buildRequest({
    mode: "topic",
    agency: "all",
    query: "CO2 hydrogenation methanol catalyst",
    institution: "University of Rochester",
    year_start: "2020",
    year_end: "2026",
    offset: 0,
  }, null, 25);
  assert.deepEqual(Array.from(topic.sources), ["NSF", "NIH", "DOE"]);
  assert.equal(topic.limit, 10, "a mixed-source request honors the polite DOE page bound");
  assert.equal(topic.criteria.topic, "CO2 hydrogenation methanol catalyst");
  assert.equal(topic.criteria.institution, "University of Rochester");
  assert.equal(topic.criteria.year_start, 2020);
  assert.equal(topic.criteria.year_end, 2026);

  const selected = product.buildRequest({
    institution: "University of Rochester",
    offset: 0,
  }, links.reviewedMappings["362061"], 25);
  assert.deepEqual(Array.from(selected.sources), ["NSF"]);
  assert.deepEqual(Array.from(selected.criteria.program_codes), ["367Y00", "140100", "764400", "141700", "140300"]);
  assert.equal(selected.criteria.topic, undefined);
  const doeProgram = product.buildRequest({
    mode: "program",
    agency: "DOE",
    query: "Catalysis",
    offset: 0,
  }, null, 25);
  assert.deepEqual(Array.from(doeProgram.sources), ["DOE"]);
  assert.deepEqual(JSON.parse(JSON.stringify(doeProgram.criteria)), { program: "Catalysis" });
  assert.equal(doeProgram.limit, 10);
  assert.deepEqual(JSON.parse(JSON.stringify(product.buildRequest({
    mode: "pi", agency: "NSF", query: "Ada Investigator", offset: 0,
  }, null, 25).criteria)), { pi: "Ada Investigator" });
  assert.deepEqual(JSON.parse(JSON.stringify(product.buildRequest({
    mode: "program_officer", agency: "NSF", query: "Alex Officer", offset: 0,
  }, null, 25).criteria)), { program_officer: "Alex Officer" });
  assert.equal(product.canPageForward({
    sources: [{ status: "ok", has_more: false, total_count: 500, raw_record_count: 25 }],
    pagination: { offset: 25, limit: 25 },
  }), false, "raw-record totals cannot advance normalized pagination");
  assert.equal(product.canPageForward({
    sources: [{ status: "ok", has_more: true, result_count: 24, total_count: null, raw_record_count: 100 }],
    pagination: { offset: 25, limit: 25 },
  }), true, "truthful normalized has_more remains usable even when validation underfills the visible page");
  assert.equal(product.canPageForward({
    sources: [{ status: "ok", has_more: true, result_count: 25, total_count: null, raw_record_count: 100 }],
    pagination: { offset: 25, limit: 25 },
  }), true);
  assert.doesNotMatch(coreSource + appSource, /FUNDING_HYBRID_SEARCH|voyage|embedding|vectorUrl/i);
});

test("investigator names use consistent display capitalization without changing source queries", () => {
  assert.equal(product.displayInvestigatorName("GERARD J. BUCKLEY"), "Gerard J. Buckley");
  assert.equal(product.displayInvestigatorName("anissa f brown"), "Anissa F Brown");
  assert.equal(product.displayInvestigatorName("ANNE-MARIE O’NEILL"), "Anne-Marie O’Neill");
  assert.equal(product.displayInvestigatorName("MCDONALD, SIOBHAN III"), "McDonald, Siobhan III");
  assert.equal(product.displayInvestigatorName("de Vries, Anna"), "de Vries, Anna");
  for (const [published, display] of [
    ["JANE DOE JR", "Jane Doe Jr"],
    ["JANE DOE SR.", "Jane Doe Sr."],
    ["JANE DOE II", "Jane Doe II"],
    ["JANE DOE MD", "Jane Doe MD"],
    ["jane doe phd", "Jane Doe PhD"],
    ["JANE DOE PH.D.", "Jane Doe Ph.D."],
    ["JANE DOE DDS", "Jane Doe DDS"],
    ["JANE DOE DVM", "Jane Doe DVM"],
    ["JANE DOE ESQ", "Jane Doe Esq"],
  ]) assert.equal(product.displayInvestigatorName(published), display);

  const summary = product.institutionSummary([
    {
      institution: { normalized_name: "University of Rochester" },
      principal_investigators: [{ name: "GERARD J. BUCKLEY" }],
    },
    {
      institution: { normalized_name: "University of Rochester" },
      principal_investigators: [{ name: "gerard j. buckley" }],
    },
  ], "University of Rochester");
  assert.deepEqual(JSON.parse(JSON.stringify(summary.investigators)), [{
    name: "Gerard J. Buckley",
    query: "GERARD J. BUCKLEY",
    projects: 2,
  }]);

  assert.match(appSource, /primaryNames = investigators\.map\(person => productApi\.displayInvestigatorName/);
  assert.match(appSource, /data-award-pi="\$\{escapeAttribute\(person\.query \|\| person\.name\)\}"/);
  assert.match(appSource, /new Set\(results\.flatMap[\s\S]*productApi\.displayInvestigatorName/);
});

test("the standalone product exposes the Phase 2 controls, state, provenance, and source isolation", () => {
  assert.match(page, /<h1 id="page-title">See what NSF, NIH, and DOE have funded<\/h1>/);
  for (const id of [
    "selected-opportunity", "award-search-form", "award-query", "search-mode",
    "award-institution", "award-agency", "year-start", "year-end",
    "award-status", "award-source-status",
    "institution-summary", "award-result-list", "award-pagination",
  ]) assert.match(page, new RegExp(`id="${id}"`));
  assert.match(page, /role="search"/);
  assert.match(page, /id="award-search-form"[^>]*hidden/);
  assert.match(page, /id="ii-form"[^>]*role="search"/);
  assert.match(page, /<option value="pi">Principal investigator<\/option>/);
  assert.match(page, /<option value="program_officer">Program officer<\/option>/);
  assert.doesNotMatch(page, /Advanced: investigator or program officer/);
  assert.match(page, /role="status" aria-live="polite"/);
  assert.match(page, /funding-finder-award-api\.urochestercheme\.workers\.dev/);
  assert.match(page, /assets\/award-links\.js/);
  assert.match(page, /data\/opportunities\.js/);
  assert.match(appSource, /Direct \$\{escapeHtml\(source\)\} source field/);
  assert.match(appSource, /View contact on official award page/);
  assert.match(appSource, /Official \$\{escapeHtml\(source\)\} record/);
  assert.match(appSource, /source-native order; no cross-source reranking/i);
  assert.match(appSource, /history\[mode === "push" \? "pushState" : "replaceState"\]/);
  assert.match(appSource, /addEventListener\("popstate"/);
  assert.match(appSource, /params\.get\("institution"\)/);
  assert.match(appSource, /funding-finder\.awards\.institution\.v1/);
  assert.match(appSource, /other sources remain usable/i);
  assert.match(appSource, /scrollIntoView\(\{ block: "start" \}\)/);
  assert.match(fundingApp, /data-funded-awards=/);
  assert.match(fundingApp, /target="_blank" rel="noopener">View funded awards/);
});

test("cards remain title and abstract centric with responsive and accessible layouts", () => {
  assert.ok(appSource.indexOf("<h4 id=\"award-title") < appSource.indexOf("award-abstract"));
  assert.ok(appSource.indexOf("award-abstract") < appSource.indexOf("award-contacts"));
  assert.match(appSource, /View official award/);
  assert.match(appSource, /function renderAbstract/);
  assert.match(appSource, /split\(\/\\n\\s\*\\n\+\//);
  assert.doesNotMatch(appSource, /View source query/);
  assert.match(styles, /\.award-abstract p \+ p/);
  assert.match(styles, /\.header-context-pill \{[\s\S]*max-width: none/);
  assert.doesNotMatch(appSource, /invent|generated interpretation|success rate/i);
  assert.doesNotMatch(appSource, /\.at\(/);
  assert.match(styles, /@media \(max-width: 390px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /@media \(forced-colors: active\)/);
  assert.match(page, /<a class="skip-link" href="#institutional-intelligence">/);
  assert.match(page, /id="award-results"[^>]*tabindex="-1"/);
  assert.match(page, /tabindex="-1">Funded projects/);
});

test("the historical Phase 2 evidence remains authoritative while Phase 4 extends its adapter boundary", () => {
  assert.match(phase1Evidence.decision, /^PHASE 1 PASSED/);
  assert.equal(phase1Evidence.authoritative_base.package_version, "1.3.0");
  assert.equal(phase2Evidence.authoritative_base.main_sha, "2f2aa714577441362626c6a6a41edd55fc105abb");
  assert.equal(phase2Evidence.decision, "PHASE 2 PASSED — FUNDED AWARDS IS USABLE AND INTEGRATED");
  assert.equal(phase2Evidence.bounded_search_quality_check.ranking_or_vector_followup_performed, false);
  assert.equal(phase2Evidence.gate.unmapped_opportunities_do_not_guess, true);
  assert.equal(phase2Evidence.gate.alerts_doe_analytics_and_award_vectors_absent, true);
  assert.doesNotMatch(coreSource + appSource, /FUNDING_HYBRID_SEARCH|voyage|embedding|vectorUrl/i);
});

test("Award service delivery follows the protected main and rollback pattern", () => {
  assert.match(deployWorkflow, /push:\s*\n\s*branches:\s*\n\s*- main/);
  assert.doesNotMatch(deployWorkflow, /workflow_dispatch|pull_request:/);
  assert.match(deployWorkflow, /git ls-remote origin refs\/heads\/main/);
  assert.match(deployWorkflow, /Main changed while the Funded Awards release was being verified/);
  assert.match(deployWorkflow, /Capture the active Award Worker version for rollback/);
  assert.match(deployWorkflow, /sort_by\(\[\(\.created_on \/\/ ""\), \(\.id \/\/ ""\)\]\)\s*\| last/);
  assert.doesNotMatch(deployWorkflow, /\.\[0\]\.versions/);
  assert.match(deployWorkflow, /\.credentials_required \| tostring/);
  assert.doesNotMatch(deployWorkflow, /\.credentials_required \/\/ empty/);
  assert.match(deployWorkflow, /wrangler@4\.125\.0 rollback/);
  assert.match(deployWorkflow, /Run bounded exact-source smokes/);
  assert.match(deployWorkflow, /Verify Pages serves the committed Funded Awards page/);
  assert.match(workerSmoke, /award_id: "2605508"/);
  assert.match(workerSmoke, /core_project_number: "K12GM106997"/);
  assert.match(workerSmoke, /award_id: "DE-SC0020230"/);
  assert.doesNotMatch(deployWorkflow + workerSmoke, /query_baseline|p9_scoring|vector|semantic/i);
});
