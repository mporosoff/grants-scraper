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

test("v1.2 production feature flags enable topics, explanations, and hybrid search", () => {
  const production = loadConfig("https://mporosoff.github.io/?ff-subtopics=1&ff-explain=1");
  assert.deepEqual(
    { ...production.productionFlags },
    { subtopics: true, matchExplanations: true, searchV2: true },
  );
  assert.deepEqual(
    { ...production.flags },
    { subtopics: true, matchExplanations: true, searchV2: true },
  );

  const local = loadConfig("http://127.0.0.1:8765/?ff-subtopics=1&ff-explain=1&ff-search-v2=1");
  assert.deepEqual(
    { ...local.flags },
    { subtopics: true, matchExplanations: true, searchV2: true },
  );
  assert.equal(local.release.version, "1.2.0");
  assert.equal(local.release.updated, "2026-08-23");
  assert.equal(
    production.hybridSearch.proxyUrl,
    "https://funding-finder-voyage-search.urochestercheme.workers.dev/",
  );
});

test("sidecar is lazy and normal pages share one app release source", () => {
  assert.match(runtimeSource, /function loadSidecar\(\)/);
  assert.match(runtimeSource, /document\.head\.append\(script\)/);
  assert.match(runtimeSource, /GRANT_CATALOG\?\.generated_at/);
  assert.match(runtimeSource, /subtopics\.js\?v=\$\{catalogVersion\}/);
  assert.doesNotMatch(mainHtml, /<script src="\.\/data\/subtopics\.js/);
  assert.doesNotMatch(teamHtml, /<script src="(?:\.\/)?data\/subtopics\.js/);
  assert.match(mainHtml, /assets\/app-config\.js\?v=app-1\.2\.0/);
  assert.match(teamHtml, /assets\/app-config\.js\?v=app-1\.2\.0/);
  assert.match(mainHtml, /connect-src 'self'/);
  assert.match(teamHtml, /connect-src 'self'/);
  for (const page of [mainHtml, teamHtml]) assert.match(page, /data-app-version/);
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

test("broad-call explanations prefer a matched sub-program or notice program area", () => {
  const context = { globalThis: {} };
  vm.runInNewContext(explainSource, context);
  const explain = context.globalThis.FUNDING_MATCH_EXPLAIN;
  const parent = {
    broad: true,
    record: {
      title: "DOE Office of Science umbrella",
      document_program_areas: ["catalysis", "chemical sciences"],
    },
    directEvidence: {
      groups: [{
        source: "catalyst",
        contribution: 2,
        matchedTerms: ["catalysi"],
        matchedDisplayTerms: ["Catalysis"],
      }],
    },
  };

  assert.equal(
    explain.build({ parent })[0],
    "Matched notice program area: Catalysis.",
  );
  assert.equal(
    explain.build({
      parent,
      bestChild: {
        record: { title: "(q) Catalysis Science" },
        directEvidence: parent.directEvidence,
      },
    })[0],
    "Matched sub-program: (q) Catalysis Science (Catalysis).",
  );
  assert.deepEqual(
    Array.from(explain.matchedProgramAreas({
      groups: [{ source: "science", matchedTerms: ["science"] }],
    }, parent.record)),
    [],
    "a generic word must not invent a specific program-area explanation",
  );
});

test("match explanations render at the bottom of each result card", () => {
  const cardStart = appSource.indexOf("function resultCard(match, resultPosition)");
  const cardEnd = appSource.indexOf("function currentModel()", cardStart);
  const cardSource = appSource.slice(cardStart, cardEnd);
  assert.match(appSource, /Why this matched/);
  assert.doesNotMatch(appSource, /Why this match<\/summary>/);
  assert.ok(
    cardSource.indexOf("matchExplanation(match, record)")
      > cardSource.indexOf("class=\"card-actions\""),
    "the explanation belongs after the card actions",
  );
  assert.match(appSource, /bestChild: displayBestChild/);
  assert.match(appSource, /matchingChildren: row\.matchingChildren/);
  assert.doesNotMatch(
    appSource,
    /matchingChildren: row\.childDroveMatch \? row\.matchingChildren : \[\]/,
  );
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
  assert.match(teamHtml, /teamChips\(entry\.fits, d\.themeLabels\)/);
  assert.match(teamHtml, /APP_CONFIG\.flags\.subtopics/);
});

test("Team Matcher links focus the corresponding Funding Finder card", () => {
  assert.match(teamHtml, /&amp;focus=' \+ encodeURIComponent\(d\.id\)/);
  assert.match(teamHtml, /target="_blank" rel="noopener">Open in Funding Finder/);
  assert.match(appSource, /INITIAL_URL_PARAMS\.get\("focus"\)/);
  assert.match(appSource, /state\.page = Math\.floor\(targetIndex \/ PAGE_SIZE\) \+ 1/);
  assert.match(appSource, /card\.scrollIntoView\(\{ behavior: "smooth", block: "center" \}\)/);
  assert.match(appSource, /card\.focus\(\{ preventScroll: true \}\)/);
});
