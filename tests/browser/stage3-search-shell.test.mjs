import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import test from "node:test";
import vm from "node:vm";
import { load } from "cheerio";
import { shellDom } from "../helpers/shell-dom.mjs";

const read = path => readFile(new URL(`../../${path}`, import.meta.url), "utf8");
const [page, app, shell, css, baselineText] = await Promise.all([
  read("match_explorer.html"), read("assets/app.js"), read("assets/site-shell.js"),
  read("assets/app.css"), read("tests/fixtures/stage3-preserved-behavior.json"),
]);
const baseline = JSON.parse(baselineText);
function fn(name) {
  const start = app.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  const tail = app.slice(start);
  return tail.slice(0, tail.slice(3).search(/\n  (?:async )?function /) + 3);
}
function fixture() {
  const dom = shellDom(page, { deferredClose: true });
  const $ = id => dom.document.getElementById(id);
  for (const el of dom.document.querySelectorAll("*")) {
    Object.defineProperties(el, {
      tagName: { get: () => el.node.tagName.toUpperCase() },
      checked: { get: () => el.getAttribute("checked") !== null, set: value => value ? el.setAttribute("checked", "") : el.removeAttribute("checked") },
    });
  }
  const state = { ready: true, searched: false, query: "", page: 1, teamReadyOnly: false,
    profile: { active: false, admissionTerms: [], terms: [] }, refinement: { active: false },
    filters: { agency: new Set(), discipline: new Set() }, hybrid: {}, ai: { active: false, busy: false, messages: [], mode: "" },
  };
  const calls = [];
  Object.assign(dom.context, {
    $, state, PAGE_SIZE: 20, APP_CONFIG: { flags: { searchV2: true } },
    CustomEvent: class { constructor(type) { this.type = type; } },
    cardMenuActions: new Map(),
    currentWorkflowMatches: () => [], opportunityHasAvailableTeam: match => !!match.team,
    compactResultCounts: matches => `${matches.length} matches`, focusLinkedOpportunity() {},
    hasNofoDocument: () => false, renderHybridStatus() {}, updateSavedSearchAlertUi() {},
    updateAiRefineControl() {}, renderDeploymentReview() {}, renderEvaluation() {}, renderChat() {},
    closeExpandedChat() {}, renderPagination() {}, browseAllOpportunities() {},
    PROFILE_RANKING_API: { minimumCoverage: () => 0 },
    refreshProfileQuery: () => ({ terms: [] }), profileHasContent: () => false,
    hasSearchCriteria: () => !!$("query").value, recordDeploymentUsage() {}, logUsage() {}, hybridCanRun: () => false,
    runCatalogAction: action => calls.push(action), runSearch: () => dom.context.renderSearchShell(),
    resultCard: match => `<article>${match.title}</article>`, shouldShowNoStrongNotice: () => false,
  });
  dom.document.dispatchEvent = event => dom.dispatch(event.type, dom.document.body);
  vm.createContext(dom.context);
  vm.runInContext(shell, dom.context);
  for (const name of ["selectedFilterCount", "renderSearchShell", "openRefineSearch", "scrollToSearchWorkspace", "startSearch", "renderResults"])
    vm.runInContext(fn(name), dom.context);
  return { ...dom, $, state, calls };
}

test("all original profile/filter/provider controls keep their attributes, options and original form ownership", () => {
  const $ = load(page);
  const controls = $("#profile-builder, #filter-panel, #provider-setup").find("input, select, textarea, button").toArray();
  assert.deepEqual(controls.map(node => ({ tag: node.tagName, attributes: { ...node.attribs },
    ...($(node).is("select") ? { options: $(node).html() } : {}),
  })), baseline.controls);
  for (const node of controls) assert.equal($(node).closest("form").attr("id"), "search-form");
  assert.equal($("#refine-search").closest("form").attr("id"), "search-form");
  assert.equal($("#refine-search form, .workspace #refine-search").length, 0);
  assert.equal($("#search-form button[type=submit]").length, 1);
  assert.equal($("#refine-find-funding").attr("type"), "button");
  const ids = $("[id]").toArray().map(node => $(node).attr("id"));
  assert.equal(new Set(ids).size, ids.length);
  assert.equal($("#refine-search").attr("open"), undefined);
  assert.equal($("#profile-builder[open], #filter-panel[open]").length, 0);
  assert.equal($("#refine-search #ai-refine").length, 1);
  assert.equal($("#search-form #chat-form, .workflow-map, .workflow-step").length, 0);
});

test("search, profile, URL/history, reset, CSV and alert construction are byte-identical to protected main", () => {
  for (const [name, expected] of Object.entries(baseline.functions))
    assert.equal(createHash("sha256").update(fn(name)).digest("hex"), expected, name);
  for (const name of ["renderSearchShell", "openRefineSearch", "scrollToSearchWorkspace"])
    assert.doesNotMatch(fn(name), /history\.|localStorage|sessionStorage|fetch\(|URLSearchParams|addEventListener/);
});

test("initial, searched/restored and cleared states change the shell without changing input or result state", () => {
  const { context, $, state } = fixture();
  $("query").value = "inner ear";
  context.renderResults();
  assert.equal($("open-refine-search").hidden, true);
  assert.equal($("refine-ai").hidden, true);
  assert.equal($("results-toolbar").classList.contains("search-not-started"), true);
  assert.equal($("results").querySelectorAll("button").length, 1);
  assert.equal($("browse-all").textContent, "Browse all current opportunities");
  state.searched = true;
  state.query = "inner ear";
  context.renderResults();
  assert.equal($("funding-search").classList.contains("has-results"), true);
  assert.equal($("page-title").textContent, "What are you looking to fund?");
  assert.equal($("open-refine-search").hidden, false);
  assert.equal($("clear-search").hidden, false);
  assert.equal($("add-research-context").hidden, true);
  assert.equal($("refine-ai").hidden, false);
  state.profile.active = true;
  state.filters.agency.add("NSF");
  $("audience-filter").value = "faculty";
  state.refinement.active = true;
  context.renderSearchShell();
  assert.equal($("search-context-summary").textContent, "Profile active · 2 filters · AI refinement active");
  assert.equal($("query").value, "inner ear");
  state.searched = false;
  context.renderSearchShell();
  assert.equal($("clear-search").hidden, true);
  assert.equal($("add-search-filters").hidden, false);
});

test("Refine opens from either initial section or the compact header and retains entries/status with exact focus restoration", async () => {
  const { context, $, document } = fixture();
  const profile = $("research-profile"), status = $("search-status"), aiStatus = $("ai-status");
  profile.value = "Private draft, never moved into URL state";
  $("orcid-id").value = "0000-0002-1825-0097";
  $("award-min").value = "250000";
  $("k-key").value = "unsaved-test-only";
  for (const [opener, section] of [["add-research-context", "profile-builder"], ["add-search-filters", "filter-panel"], ["open-refine-search", ""]]) {
    $(opener).hidden = false;
    context.openRefineSearch($(opener), section);
    assert.equal($("refine-search").open, true);
    assert.equal(document.activeElement, section ? $(section).querySelector("summary") : $("refine-search-heading"));
    if (section) assert.equal($(section).open, true);
    assert.equal($("refine-search").contains(status), true);
    assert.equal($("refine-ai").contains(aiStatus), true);
    $("refine-search").close(); // Same native close event used by Escape.
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(document.activeElement, $(opener));
    assert.equal($("refine-search").contains(status), false);
    assert.equal($("search-ai-status-slot").contains(aiStatus), true);
    assert.equal($("research-profile"), profile);
    assert.equal(profile.value, "Private draft, never moved into URL state");
    assert.equal($("orcid-id").value, "0000-0002-1825-0097");
    assert.equal($("award-min").value, "250000");
    assert.equal($("k-key").value, "unsaved-test-only");
  }
});

test("switching drawers releases status custody immediately, without changing provider/profile ownership", () => {
  const { context, $ } = fixture();
  context.openRefineSearch($("add-search-filters"), "filter-panel");
  context.SiteShell.openDrawer($("result-assistant"), $("open-results-chat"));
  assert.equal($("refine-search").open, false);
  assert.equal($("refine-search").contains($("search-status")), false);
  assert.equal($("search-ai-status-slot").contains($("ai-status")), true);
  assert.equal($("search-provider-slot").contains($("provider-setup")), true);
  assert.equal($("refine-search").contains($("research-profile")), true);
});

test("failed Refine opening cleans up and keeps search available; a later retry succeeds", () => {
  const { context, $, document } = fixture();
  const nativeOpen = $("refine-search").showModal;
  $("refine-search").showModal = () => { throw new Error("Test failure"); };
  context.openRefineSearch($("add-search-filters"), "filter-panel");
  assert.equal(document.documentElement.classList.contains("shell-drawer-open"), false);
  assert.equal($("search-ai-status-slot").contains($("ai-status")), true);
  assert.match($("search-status").textContent, /entries are preserved/);
  $("refine-search").showModal = nativeOpen;
  context.openRefineSearch($("add-search-filters"), "filter-panel");
  assert.equal($("refine-search").open, true);
});

test("filter-driven result rerenders leave Refine and its current field intact", () => {
  const { context, $, document, state } = fixture();
  state.searched = true;
  state.query = "inner ear";
  $("open-refine-search").hidden = false;
  context.openRefineSearch($("open-refine-search"), "filter-panel", $("award-min"));
  $("award-min").value = "500000";
  context.renderResults();
  assert.equal($("refine-search").open, true);
  assert.equal(document.activeElement, $("award-min"));
  assert.equal($("award-min").value, "500000");
  assert.equal($("search-context-summary").textContent, "1 filter");
  context.SiteShell.closeDrawer($("refine-search"));
  assert.equal(document.activeElement, $("open-refine-search"));
});

test("profile validation focuses a visible Refine field; an empty search closes Refine before focusing the query", () => {
  const { context, $, document, state } = fixture();
  $("use-profile").checked = true;
  context.startSearch();
  assert.equal($("refine-search").open, true);
  assert.equal(document.activeElement, $("research-profile"));
  assert.match($("search-status").textContent, /Add profile information/);
  assert.equal($("refine-search").contains($("search-status")), true);
  context.profileHasContent = () => true;
  context.startSearch();
  assert.equal(document.activeElement, $("expertise-keywords"));
  assert.match($("search-status").textContent, /concrete expertise keywords/);
  $("use-profile").checked = false;
  context.startSearch();
  assert.equal($("refine-search").open, false);
  assert.equal(document.activeElement, $("query"));
  assert.equal(state.searched, false);
  assert.match($("search-status").textContent, /Enter a topic/);
});

test("successful search closes Refine, compacts the header and focuses its retained or replacement opener", () => {
  const { context, $, document, state } = fixture();
  $("query").value = "inner ear";
  context.openRefineSearch($("add-search-filters"), "filter-panel");
  context.startSearch();
  assert.equal(state.searched, true);
  assert.equal($("sort").value, "relevance");
  assert.equal($("refine-search").open, false);
  assert.equal(document.activeElement, $("open-refine-search"));
  assert.equal($("funding-search").scrolled, true);
  assert.match($("search-status").textContent, /Search complete/);
});

test("native invalid events reopen Refine and all nested disclosures at the first invalid field without submitting", async () => {
  const dom = fixture();
  const { context, $, document, state } = dom;
  const source = fn("bindEvents");
  const binding = source.slice(source.indexOf("    let invalidSearchField = null;"), source.indexOf('    $("query").addEventListener("input"'));
  assert.match(binding, /addEventListener\("invalid",[\s\S]*\}, true\)/);
  assert.equal((source.match(/addEventListener\("invalid"/g) || []).length, 1);
  assert.doesNotMatch(page + app, /novalidate|formnovalidate|noValidate|formNoValidate/);
  vm.runInContext(binding, context);
  const field = $("award-min");
  field.value = "500";
  field.validationMessage = "Please enter a valid value. The two nearest valid values are 0 and 1000.";
  $("find-funding").focus();
  const invalid = dom.dispatch("invalid", field);
  assert.equal(invalid.prevented, true);
  assert.equal($("refine-search").open, true);
  assert.equal($("filter-panel").open, true);
  assert.equal(field.closest("details").open, true);
  assert.equal(document.activeElement, field);
  assert.equal($("search-status").textContent, field.validationMessage);
  assert.equal($("refine-search").contains($("search-status")), true);
  assert.equal(state.searched, false);
  assert.equal(field.value, "500");
  $("orcid-id").validationMessage = "Another invalid field";
  dom.dispatch("invalid", $("orcid-id"));
  assert.equal(document.activeElement, field, "later invalid controls cannot steal the first field's focus");
  assert.equal(dom.dispatch("invalid", $("query")).prevented, false, "other form controls retain their native handling");
  context.SiteShell.closeDrawer($("refine-search"));
  assert.equal(document.activeElement, $("find-funding"));
  await new Promise(resolve => setTimeout(resolve, 0));
  dom.dispatch("invalid", $("orcid-id"));
  assert.equal(document.activeElement, $("orcid-id"));
  assert.equal($("profile-builder").open, true);
});

test("the drawer submit routes to the original form and canonical submitter through the existing delegate", () => {
  const source = fn("bindEvents");
  assert.equal((source.match(/\$\("search-form"\)\.addEventListener\("submit"/g) || []).length, 1);
  assert.match(source, /\$\("search-form"\)\.addEventListener\("submit", event => \{\s*event.preventDefault\(\);\s*startSearch\(\);/);
  assert.equal((source.match(/document\.addEventListener\("click"/g) || []).length, 2); // Existing app actions and source/citation measurement owners.
  assert.equal((source.match(/const refine = event.target.closest\("\[data-refine-open\]"\)/g) || []).length, 1);
  const routing = source.slice(source.indexOf('      const refine = event.target.closest("[data-refine-open]")'), source.indexOf('      const save = event.target.closest("[data-save]")'));
  const dom = fixture();
  const submissions = [];
  dom.$("search-form").requestSubmit = control => submissions.push(control);
  vm.runInContext(`document.addEventListener("click", event => {${routing}});`, dom.context);
  dom.dispatch("click", dom.$("refine-find-funding"));
  assert.deepEqual(submissions, [dom.$("find-funding")]);
  dom.dispatch("click", dom.$("add-search-filters"));
  assert.equal(dom.$("refine-search").open, true);
  assert.equal(submissions.length, 1);
});

test("catalog preparation leaves entries intact and keeps the drawer submit under the same busy-control owner", () => {
  const { context, $, state, calls } = fixture();
  state.ready = false;
  $("research-profile").value = "Retained draft";
  context.startSearch();
  assert.deepEqual(calls, [context.startSearch]);
  assert.equal($("research-profile").value, "Retained draft");
  assert.equal(state.searched, false);
  assert.match(fn("setCatalogControlsBusy"), /"#find-funding",\s*"#refine-find-funding"/);
});

test("empty/loading/degraded states distinguish outcomes, offer one next action and preserve search-alert availability", () => {
  const { context, $, state } = fixture();
  state.searched = true;
  state.query = "no matching fixture";
  for (const [hybrid, title, actions] of [
    [{ pending: true }, "Checking for potential matches", 0],
    [{ fallbackReason: "Unavailable" }, "Broader search is temporarily unavailable", 1],
    [{ active: true }, "No strong matches found", 1],
  ]) {
    state.hybrid = hybrid;
    context.renderResults();
    assert.equal($("results").querySelector("h3").textContent, title);
    assert.equal($("results").querySelectorAll("button").length, actions);
    assert.equal($("results-toolbar").classList.contains("results-empty"), true);
    assert.equal($("results-more-trigger").hidden, false);
    assert.equal($("export-csv").disabled, true);
  }
  state.teamReadyOnly = true;
  context.renderResults();
  assert.equal($("filter-team-ready").hidden, false);
  assert.equal($("filter-team-ready").getAttribute("aria-pressed"), "true");
  assert.equal($("results").querySelector("button").dataset.emptyAction, "team");
  state.teamReadyOnly = false;
  context.hasNofoDocument = () => true;
  context.renderResults();
  assert.equal($("results").querySelector("button").dataset.emptyAction, "chat");
  assert.match(fn("renderChat"), /\$\("open-results-chat"\)\.hidden = !canChat/);
  assert.match(css, /\.results-toolbar\.results-empty \.toolbar-controls \{ display: none; \}/);
  assert.match(fn("renderResults"), /renderHybridStatus\(\)/);
  for (const id of ["topic-layer-warning", "stale-warning", "potential-status"])
    assert.equal(load(page)(`.workspace #${id}`).length, 1);
});

test("Refine relies on the proven shared keyboard/full-screen lifecycle and adds no sticky obstruction", () => {
  assert.equal(load(page)("#refine-search[data-shell-drawer]").length, 1);
  assert.match(css, /\.refine-search-drawer \{ width: min\(660px, 100vw\)/);
  assert.match(css, /@media \(max-width: 700px\) \{\s*\.site-drawer\.refine-search-drawer \{ width: 100vw/);
  assert.match(css, /\.refine-search-drawer \.orcid-input-row \{ flex-wrap: wrap/);
  assert.match(css, /\.refine-search-drawer \.orcid-input-row > :is\(input, button\) \{ min-width: 0; width: 100%/);
  assert.doesNotMatch(css, /\.refine-search-drawer \.orcid-input-row > \*/); // An absolute sr-only label must retain its 1px width.
  const rules = css.slice(css.indexOf("/* Funding Finder keeps one search form"), css.indexOf("/* Contextual tools share"));
  assert.doesNotMatch(rules, /position:\s*(fixed|sticky)|touch-action:\s*none/);
  assert.match(page, /name="viewport" content="width=device-width, initial-scale=1"/);
  assert.doesNotMatch(page, /user-scalable=no|maximum-scale=/);
});
