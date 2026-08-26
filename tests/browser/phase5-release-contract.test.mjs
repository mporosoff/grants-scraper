import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { ALERT_EMAIL_TEMPLATE_VERSION } from "../../workers/alerts/src/email.js";

const root = new URL("../../", import.meta.url);
const [evidence, alertWorkflow, awardWorkflow, searchWorkflow, refreshWorkflow, ...pages] = await Promise.all([
  readFile(new URL("evaluation/funded_awards_alerts_release_closeout.json", root), "utf8").then(JSON.parse),
  readFile(new URL(".github/workflows/deploy-alerts.yml", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-award-api.yml", root), "utf8"),
  readFile(new URL(".github/workflows/deploy-search-package.yml", root), "utf8"),
  readFile(new URL(".github/workflows/refresh-opportunities.yml", root), "utf8"),
  ...["index.html", "match_explorer.html", "funded_awards.html", "team_match.html"]
    .map(path => readFile(new URL(path, root), "utf8")),
]);

test("Phase 5 closeout records the integrated release and its explicit boundaries", () => {
  assert.equal(evidence.phase, 5);
  assert.match(evidence.decision, /RELEASE CANDIDATE PASSED/);
  assert.equal(evidence.source_contracts.award_vectors_used, false);
  assert.equal(evidence.source_contracts.cross_source_reranking, false);
  assert.equal(evidence.privacy.llm_used_for_alerts, false);
  assert.deepEqual(evidence.privacy.queued_alert_payload_allowlist, [
    "title", "agency", "program", "close_date", "detail", "why_matched", "funding_finder_url", "official_url",
  ]);
  assert.equal(evidence.validation.python_live_product_gate.failed, 0);
  assert.equal(evidence.validation.real_browser_product_and_accessibility_gate.failed, 0);
  assert.ok(evidence.known_limitations.length >= 5);
});

test("the current alert template is a protected deployment health contract", () => {
  assert.equal(ALERT_EMAIL_TEMPLATE_VERSION, "phase2-lifecycle-20260825");
  assert.match(alertWorkflow, /email_template_version \/\/ empty/);
  assert.match(alertWorkflow, /= "phase2-lifecycle-20260825"/);
  assert.match(alertWorkflow, /assets\/match-explain\.js/);
  assert.match(alertWorkflow, /tools\/smoke_alerts_worker\.mjs/);
});

test("parameterized product pages keep one canonical and the shared existing image without collapsing og:url", () => {
  for (const page of pages) {
    assert.match(page, /<link rel="canonical" href="https:\/\/mporosoff\.github\.io\/grants-scraper\//);
    assert.match(page, /<meta property="og:image" content="https:\/\/mporosoff\.github\.io\/grants-scraper\/assets\/social\/funding-finder-link-preview\.jpg"\s*\/?>/);
    assert.match(page, /<meta property="og:image:url" content="https:\/\/mporosoff\.github\.io\/grants-scraper\/assets\/social\/funding-finder-link-preview\.jpg"\s*\/?>/);
    assert.doesNotMatch(page, /<meta property="og:url"/);
  }
});

test("every release workflow selects the newest active deployment instead of trusting list order", () => {
  for (const workflow of [alertWorkflow, awardWorkflow, searchWorkflow, refreshWorkflow]) {
    assert.match(workflow, /sort_by\(\[\(\.created_on \/\/ ""\), \(\.id \/\/ ""\)\]\)/);
    assert.match(workflow, /map\(select\(\(\.percentage \/\/ 0\) == 100\)\)/);
    assert.match(workflow, /max_by\(\.percentage\)/);
    assert.doesNotMatch(workflow, /\.\[0\]\.versions/);
  }
});
