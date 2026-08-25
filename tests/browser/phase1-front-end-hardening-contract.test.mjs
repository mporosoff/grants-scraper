import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const [awardCoreSource, intelligenceCoreSource, fundedAwardsSource, alertsSource, appSource, page] = await Promise.all([
  readFile(new URL("assets/funded-awards-core.js", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence-core.js", root), "utf8"),
  readFile(new URL("assets/funded-awards.js", root), "utf8"),
  readFile(new URL("assets/alerts.js", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
]);

const sandbox = { URL, URLSearchParams };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(awardCoreSource, sandbox);
vm.runInContext(intelligenceCoreSource, sandbox);
vm.runInContext(alertsSource, sandbox);
const awards = sandbox.FUNDING_AWARD_PRODUCT;
const intelligence = sandbox.FUNDING_INSTITUTIONAL_INTELLIGENCE;
const alerts = sandbox.FUNDING_ALERTS;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("FF-BUG-001 keeps absent numeric values distinct from explicit zero", () => {
  for (const value of [null, undefined, "", "   "]) {
    assert.equal(awards.presentFiniteNumber(value), null);
    assert.equal(awards.awardYear(value), null);
  }
  assert.equal(awards.presentFiniteNumber(0), 0);
  assert.equal(awards.presentFiniteNumber("0"), 0);
  assert.equal(awards.presentFiniteNumber(125000), 125000);
  assert.equal(awards.awardYear(0), null);
  assert.equal(awards.awardYear(2025), 2025);
  assert.equal(awards.awardYear("2026"), 2026);
  assert.equal(awards.awardYearRange([
    { award_year: null }, { award_year: "" }, { award_year: "  " },
    { award_year: 2022 }, { award_year: "2025" },
  ]), "2022–2025");
  assert.equal(awards.awardYearRange([
    { award_year: null }, { award_year: undefined }, { award_year: "" },
  ]), null);

  const aggregate = intelligence.aggregateAwards([
    { source: "NSF", award_id: "1", award_year: null },
    { source: "NIH", award_id: "2", award_year: "" },
  ]);
  assert.equal(aggregate.year_start, null);
  assert.equal(aggregate.year_end, null);
});

test("FF-BUG-011 exposes an accessible saved-storage failure channel for every UI mutation", () => {
  assert.match(page, /id="saved-status" role="status" aria-live="polite"/);
  const mutationUi = appSource.slice(
    appSource.indexOf("function savedMutationFailed"),
    appSource.indexOf("function openOpportunityAlert"),
  );
  assert.match(mutationUi, /result\?\.ok/);
  assert.match(mutationUi, /last saved version is still shown/);
  const failureBranch = mutationUi.slice(mutationUi.indexOf("if (result?.ok)"), mutationUi.indexOf("return true"));
  assert.ok(failureBranch.indexOf("refreshSavedState(result?.items)") < failureBranch.indexOf("renderSaved()"));
  assert.match(mutationUi, /SAVED_API\.toggle/);
  assert.match(mutationUi, /SAVED_API\.remove/);
  assert.match(mutationUi, /SAVED_API\.clear/);
  assert.match(mutationUi, /SAVED_API\.updatePursuit/);
});

test("FF-BUG-014 investigator drill-down clears exact-opportunity state and records standalone PI URL state", () => {
  const handler = fundedAwardsSource.slice(
    fundedAwardsSource.indexOf('$("institution-summary").addEventListener'),
    fundedAwardsSource.indexOf('window.addEventListener("popstate"'),
  );
  assert.ok(handler.indexOf("state.selectedRecord = null") < handler.indexOf('$("ii-form").requestSubmit()'));
  assert.ok(handler.indexOf("state.selectedLookup = null") < handler.indexOf('$("ii-form").requestSubmit()'));
  assert.match(handler, /renderSelectedOpportunity\(\)/);
  assert.match(handler, /\$\("ii-pi"\)\.value = investigator/);
  assert.match(handler, /\$\("ii-form"\)\.requestSubmit\(\)/);

  const url = intelligence.urlForState("https://example.test/funded_awards.html?opportunity=361187", {
    open: true,
    agency: "NIH",
    institution: "University of Rochester",
    pi: "Stephen Dewhurst",
    year_start: 2020,
    year_end: 2026,
  });
  assert.equal(url.searchParams.get("opportunity"), null);
  assert.equal(url.searchParams.get("ii_pi"), "Stephen Dewhurst");
  assert.deepEqual(plain(intelligence.stateFromSearch(url.search)), {
    open: true,
    institution: "University of Rochester",
    ror_id: "",
    agency: "NIH",
    program: "",
    topic: "",
    pi: "Stephen Dewhurst",
    program_officer: "",
    year_start: "2020",
    year_end: "2026",
    offset: 0,
  });
});

test("FF-BUG-015 uses truthful source-scoped paging labels", () => {
  const multiSource = {
    request: { sources: ["NSF", "NIH", "DOE"] },
    results: Array.from({ length: 6 }, (_, index) => ({ source: index < 2 ? "NSF" : index < 3 ? "NIH" : "DOE" })),
    sources: [
      { source: "NSF", result_count: 2 },
      { source: "NIH", result_count: 1 },
      { source: "DOE", result_count: 3 },
    ],
    pagination: { offset: 10, limit: 10 },
  };
  const label = awards.paginationLabel(multiSource);
  assert.equal(label, "6 results on this page · each source is paged independently after its first 10 results");
  assert.doesNotMatch(label, /Results 11–16|Results 11-16/);
  assert.equal(awards.paginationLabel({
    request: { sources: ["NSF"] }, results: [{}, {}, {}], pagination: { offset: 10, limit: 10 },
  }), "Results 11–13");
});

test("FF-BUG-016 maps bounded recovery classes without exposing backend detail", () => {
  assert.equal(awards.sourceIssueText({ source: "NSF", status: "unsupported" }), "NSF does not support this filter combination.");
  assert.equal(awards.sourceIssueText({ source: "NIH", status: "unavailable", error: { code: "source_rate_limited" } }), "NIH is rate limited. Wait before retrying.");
  assert.equal(awards.sourceIssueText({ source: "DOE", status: "unavailable", error: { code: "source_unavailable" } }), "DOE is temporarily unavailable. Retry later.");
  assert.equal(awards.sourceIssueText({ source: "NSF", status: "unavailable", error: { code: "source_invalid_response" } }), "NSF returned an invalid service response. Retry later.");
  assert.equal(awards.serviceIssueText({ error: { code: "invalid_request" } }), "Check the submitted award filters and try again.");
  assert.equal(awards.serviceIssueText({ error: { code: "rate_limited" } }), "Award search is rate limited. Wait before retrying.");
  assert.equal(awards.serviceIssueText({ error: { code: "service_unavailable" } }), "The award service is unavailable. Retry later.");

  assert.equal(alerts.errorMessage("rate_limited"), "Too many alert requests. Wait before trying again.");
  assert.equal(alerts.errorMessage("invalid_request"), "Check the alert details and try again.");
  assert.match(alerts.errorMessage("alerts_unavailable"), /delivery is unavailable\. Retry later/);
  assert.match(alerts.errorMessage("invalid_response"), /invalid response\. Retry later/);
  assert.equal(alerts.boundedErrorCode({ error: { code: "rate_limited", detail: "researcher@example.edu private provider body" } }), "rate_limited");
  assert.equal(alerts.boundedErrorCode({ error: { code: "private_provider_failure" } }), "");
  assert.doesNotMatch([
    alerts.errorMessage("rate_limited"), alerts.errorMessage("invalid_request"),
    alerts.errorMessage("alerts_unavailable"), alerts.errorMessage("invalid_response"),
  ].join(" "), /email address|exists|suppressed|provider body|secret/i);
});
