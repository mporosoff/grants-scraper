import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const configSource = await readFile(new URL("assets/app-config.js", root), "utf8");
const explainSource = await readFile(new URL("assets/match-explain.js", root), "utf8");
const mainHtml = await readFile(new URL("match_explorer.html", root), "utf8");
const teamHtml = await readFile(new URL("team_match.html", root), "utf8");
const appSource = await readFile(new URL("assets/app.js", root), "utf8");
const runtimeSource = await readFile(new URL("assets/subtopic-runtime.js", root), "utf8");

function loadConfig(url) {
  const parsed = new URL(url);
  const context = {
    Date,
    Intl,
    URLSearchParams,
    globalThis: {
      location: { hostname: parsed.hostname, search: parsed.search },
    },
  };
  vm.runInNewContext(configSource, context);
  return context.globalThis.FUNDING_FINDER_APP;
}

test("P11 production feature flags enable topics and explanations", () => {
  const production = loadConfig("https://mporosoff.github.io/?ff-subtopics=1&ff-explain=1");
  assert.deepEqual(
    { ...production.productionFlags },
    { subtopics: true, matchExplanations: true },
  );
  assert.deepEqual(
    { ...production.flags },
    { subtopics: true, matchExplanations: true },
  );

  const local = loadConfig("http://127.0.0.1:8765/?ff-subtopics=1&ff-explain=1");
  assert.deepEqual(
    { ...local.flags },
    { subtopics: true, matchExplanations: true },
  );
  assert.equal(local.release.version, "1.1.0");
  assert.equal(local.release.updated, "2026-08-21");
});

test("sidecar is lazy and normal pages share one app release source", () => {
  assert.match(runtimeSource, /function loadSidecar\(\)/);
  assert.match(runtimeSource, /document\.head\.append\(script\)/);
  assert.doesNotMatch(mainHtml, /<script src="\.\/data\/subtopics\.js/);
  assert.doesNotMatch(teamHtml, /<script src="(?:\.\/)?data\/subtopics\.js/);
  for (const page of [mainHtml, teamHtml]) {
    assert.match(page, /assets\/app-config\.js\?v=app-1\.1\.0/);
    assert.match(page, /data-app-version/);
  }
});

test("explanations are evidence-only, source-aware, and capped at three", () => {
  const context = { globalThis: {} };
  vm.runInNewContext(explainSource, context);
  const explain = context.globalThis.FUNDING_MATCH_EXPLAIN;
  const reasons = explain.build({
    parent: {
      record: { title: "Parent" },
      directEvidence: {
        exactOpportunityNumber: false,
        exactTitlePhrase: false,
        groups: [{ source: "capture", contribution: 2, matchedTerms: ["capture"] }],
      },
    },
    bestChild: {
      record: {
        title: "Direct Air Capture",
        term_display: { capture: "capture" },
      },
      directEvidence: {
        groups: [{ source: "capture", contribution: 3, matchedTerms: ["capture"] }],
      },
    },
    profileSources: {
      manual: {
        score: 1,
        record: { term_display: { membrane: "membranes" } },
        evidence: {
          groups: [{ source: "membrane", contribution: 1, matchedTerms: ["membrane"] }],
        },
      },
      cv: { score: 0 },
      orcid: { score: 0 },
    },
    eligibility: 1,
  });

  assert.equal(reasons.length, 3);
  assert.match(reasons[0], /Matched topic: Direct Air Capture/);
  assert.match(reasons[1], /Search terms matched: capture/);
  assert.match(reasons[2], /research profile matched: membranes/);
  assert.doesNotMatch(reasons.join(" "), /CV|ORCID|career-stage/);
});

test("normal UI has no compare or rating surface and reviewer mode stays dedicated", () => {
  assert.doesNotMatch(mainHtml, /id="compare-panel"|data-compare=|Help improve Funding Finder/);
  assert.doesNotMatch(mainHtml, /id="use-preferences"|assets\/preferences\.js/);
  assert.match(mainHtml, /id="evaluation-tools" hidden/);
  assert.match(appSource, /EVALUATION_MODE \? `<details class="result-feedback-toggle">/);
  assert.match(appSource, /EVALUATION_MODE \? sourceReviewControls\(record\)/);
  assert.doesNotMatch(appSource, /renderComparePanel|toggleCompare|FUNDING_PREFERENCES/);
});

test("ORCID provenance and profile-only fallback remain source truthful", () => {
  const importStart = appSource.indexOf("async function importOrcidProfile()");
  const importEnd = appSource.indexOf("function removeOrcidProfile()", importStart);
  const importSource = appSource.slice(importStart, importEnd);
  assert.match(importSource, /orcid_text: imported\.publicationText/);
  assert.doesNotMatch(importSource, /expertise-keywords.*imported\.keywords/s);

  assert.match(appSource, /manualParentAdmission\.terms\.length/);
  assert.match(appSource, /: profileTermQuery\(state\.profile\.value\)/);
  assert.match(appSource, /manualChildAdmission\.terms\.length/);
  assert.match(appSource, /: childProfileQuery/);
});

test("Team Matcher uses the shared rollup and a restrained default view", () => {
  assert.match(teamHtml, /RETRIEVAL_API\.rollupRankedRecords/);
  assert.match(teamHtml, /fits\.slice\(0, 3\)/);
  assert.match(teamHtml, /parts\.slice\(0, maximum \|\| 2\)/);
  assert.match(teamHtml, /teamTopicSummary\(d\.topicMatches\)/);
  assert.match(teamHtml, /APP_CONFIG\.flags\.subtopics/);
});
