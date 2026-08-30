import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { load } from "cheerio";

const root = new URL("../../", import.meta.url);
const [page, app, styles, help, institution] = await Promise.all([
  readFile(new URL("match_explorer.html", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("assets/app.css", root), "utf8"),
  readFile(new URL("assets/site-help.js", root), "utf8"),
  readFile(new URL("assets/institutional-intelligence.js", root), "utf8"),
]);

test("primary search owns the only Find funding control and the optional AI section is distinct", () => {
  const $ = load(page);
  assert.equal($("#find-funding").length, 1);
  assert.equal($(".primary-step #nofo-drop-zone #find-funding").length, 1);
  const children = $("#nofo-drop-zone").children().toArray();
  const queryIndex = children.findIndex(node => $(node).attr("id") === "query");
  const findIndex = children.findIndex(node => $(node).attr("id") === "find-funding");
  assert.equal(findIndex, queryIndex + 1, "the submit control stays immediately beside the main query field");
  assert.equal($("#launch-step-heading").text().trim(), "Expand and refine your search with AI");
  assert.equal($(".provider-setup #ai-refine").length, 0);
  assert.equal($(".launch-step > .ai-refine-actions #ai-refine").length, 1);
  assert.equal($("#ai-refine").attr("aria-describedby"), "ai-refine-requirement");
  assert.equal($("#ai-refine-requirement").attr("aria-live"), "polite");
  assert.equal($(".results-column").attr("aria-label"), "Funding opportunities");
  assert.equal($("#results").attr("aria-live"), "polite");
});

test("provider setup retains key, cost, help, and privacy details without repeating full privacy copy", () => {
  const $ = load(page);
  const details = $(".provider-setup").text();
  assert.match(details, /Provider/);
  assert.match(details, /API key/);
  assert.match(details, /spending controls/);
  assert.match(details, /saved key stays in this browser/);
  assert.match(details, /two bounded calls/);
  assert.doesNotMatch(page, /<strong>What leaves this page:<\/strong>/);
  assert.doesNotMatch(page, /<strong>URLs and anonymous usage:<\/strong>/);
  assert.match(help, /Hosted Potential matching/);
  assert.match(help, /User-connected AI tools/);
  assert.match(help, /URLs and anonymous measurement/);
});

test("every AI consumer names one shared structured-result operation", () => {
  for (const operation of [
    "search_plan",
    "refinement_shortlist",
    "result_chat",
    "notice_chat",
  ]) {
    assert.match(app, new RegExp(`providerStructured\\(\\s*"${operation}"`));
  }
  for (const operation of ["institution_question_translation", "institution_narrative"]) {
    assert.match(institution, new RegExp(`operation: "${operation}"`));
  }
  assert.doesNotMatch(`${app}\n${institution}`, /providerJson/);
  assert.doesNotMatch(`${app}\n${institution}`, /output_schema/);
});

test("AI refinement requires both a usable result context and an entered or saved key", () => {
  const control = app.slice(
    app.indexOf("function updateAiRefineControl"),
    app.indexOf("function setAiBusy"),
  );
  assert.match(control, /const hasContext = aiRefineHasContext\(\)/);
  assert.match(control, /const searchIsCurrent = aiRefineSearchIsCurrent\(\)/);
  assert.match(control, /const hasKey = Boolean\(\$\("k-key"\)\.value\.trim\(\)\)/);
  for (const guard of [
    /state\.ai\.busy/,
    /state\.refinement\.busy/,
    /state\.refinement\.active/,
    /uploadedNofoActive/,
    /!hasContext/,
    /!searchIsCurrent/,
    /!hasKey/,
  ]) assert.match(control, guard);
  assert.match(control, /aria-disabled/);
  assert.match(control, /ai-refine-requirement/);
  const providerState = app.slice(
    app.indexOf("function updateProviderState"),
    app.indexOf("function loadProviderKey"),
  );
  assert.match(providerState, /updateAiRefineControl\(\)/);
});

test("one compact live tier count replaces the redundant result summary and tier explanations", () => {
  const $ = load(page);
  for (const id of ["results-heading", "result-count", "result-label", "results-mode", "result-range"]) {
    assert.equal(page.includes(`id="${id}"`), false, id);
  }
  for (const className of ["results-summary", "toolbar-lower-row"]) {
    assert.equal(page.includes(`class="${className}"`), false, className);
  }
  assert.equal($("#result-tier-counts").length, 1);
  assert.equal($("#result-tier-counts").attr("role"), "status");
  assert.equal($("#result-tier-counts").attr("aria-live"), "polite");
  assert.equal($("#result-tier-counts").attr("aria-atomic"), "true");
  assert.equal($("#results-toolbar > #result-tier-counts").length, 1);
  assert.match(page, /class="results-toolbar[^>]*" id="results-toolbar"[\s\S]*?id="result-tier-counts"[\s\S]*?class="toolbar-actions"/);
  assert.match(page, /class="toolbar-controls"[\s\S]*?id="sort"/);
  assert.doesNotMatch(app, /updateResultHeading|results-heading|result-count|result-label|results-mode|result-range/);
  assert.match(styles, /\.results-toolbar\.search-not-started\s*\{[^}]*display:\s*none/);
  assert.doesNotMatch(app, /\$\("search-status"\)\.textContent = `\$\{state\.strongMatches\.length/);
  const countSource = app.slice(
    app.indexOf("function compactResultCounts"),
    app.indexOf("function syncStateToUrl"),
  );
  const context = {
    RESULT_WORKFLOW_API: {
      workflowTier(match) { return match.workflowTier === "potential" ? "potential" : "strong"; },
    },
  };
  vm.runInNewContext(`${countSource}\nthis.compactResultCounts = compactResultCounts;`, context);
  const nineStrong = Array.from({ length: 9 }, () => ({ workflowTier: "strong" }));
  const twelvePotential = Array.from({ length: 12 }, () => ({ workflowTier: "potential" }));
  assert.equal(
    context.compactResultCounts([...nineStrong, ...twelvePotential]),
    "9 strong matches · 12 potential matches",
  );
  assert.equal(
    context.compactResultCounts([
      { workflowTier: "strong", aiIdentified: true },
      { workflowTier: "potential" },
    ]),
    "1 strong match · 1 potential match · 1 AI-identified match",
  );
  assert.equal(context.compactResultCounts([]), "0 strong matches · 0 potential matches");
  const render = app.slice(app.indexOf("function renderResults"), app.indexOf("function renderActiveFilters"));
  assert.match(render, /result-tier-counts"\)\.textContent = compactResultCounts\(display\)/);
  assert.doesNotMatch(render, /result-tier-heading|result-tier-empty|Supported by conservative local evidence|Additional leads from the broader hybrid search/);
});

test("desktop aligns query, submit, and upload while tablet and smaller widths stack safely", () => {
  assert.match(styles, /\.search-workflow \.search-form \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\) auto auto;/);
  const tablet = styles.slice(styles.lastIndexOf("@media (max-width: 820px)"));
  assert.match(tablet, /\.search-workflow \.search-form \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(tablet, /\.nofo-upload-button \{[\s\S]*?order: 1;[\s\S]*?width: 100%;/);
  assert.match(tablet, /\.find-button \{[\s\S]*?order: 2;[\s\S]*?width: 100%;/);
  const mobile = styles.slice(styles.lastIndexOf("@media (max-width: 540px)"));
  assert.match(mobile, /\.ai-refine-actions \{[\s\S]*?flex-direction: column;/);
});

test("mobile email alerts start collapsed without changing the desktop auto-open path", () => {
  assert.match(page, /<details class="context-card alerts-panel" id="alerts-panel">/);
  assert.match(app, /if \(!globalThis\.matchMedia\?\.\("\(max-width: 820px\)"\)\.matches\) panel\.open = true/);
  assert.match(app, /savedSearchAlertIntroduced = true/);
});
