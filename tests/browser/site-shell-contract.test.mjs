import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import test from "node:test";
import vm from "node:vm";
import { load } from "cheerio";
import { captureBehavior } from "../helpers/stage1-behavior.mjs";

const root = new URL("../../", import.meta.url);
const read = path => readFile(new URL(path, root), "utf8");
const [app, shell, css, nav, pages, baseline] = await Promise.all([
  read("assets/app.js"), read("assets/site-shell.js"), read("assets/site-shell.css"), read("assets/site-nav.js"),
  Promise.all(["match_explorer.html", "team_match.html", "funded_awards.html", "faculty_interests.html"].map(read)),
  read("tests/fixtures/stage1-shell-baseline.json").then(JSON.parse),
]);
const $ = load(pages[0]);
function fn(name) {
  const tail = app.slice(app.indexOf(`  function ${name}(`));
  const end = tail.slice(3).search(/\n  (?:async )?function /);
  return tail.slice(0, end + 3);
}

test("Workspace owns canonical utilities, outside the result stream and existing workspace layout", () => {
  assert.equal($(".workspace").length, 1);
  assert.equal($("#workspace").length, 0);
  assert.equal($("dialog#personal-workspace.workspace-drawer[data-shell-drawer]").length, 1);
  assert.equal($(".results-column #personal-workspace, .results-column #saved-panel, .results-column #saved-list, .results-column #alert-new-matches").length, 0);
  for (const id of ["saved-list", "saved-count", "clear-saved", "alert-new-matches", "profile-search-alert-status"]) {
    assert.equal($(`#${id}`).length, 1, id);
    assert.equal($(`#personal-workspace #${id}`).length, 1, id);
  }
  assert.equal($("#saved-status").length, 1);
  assert.equal($("#personal-workspace #saved-status").length, 0);
  assert.equal($("#saved-status").attr("aria-live"), "polite");
  assert.equal($("[data-workspace-badge]").attr("aria-hidden"), "true");
  assert.equal($("[data-workspace-badge][hidden]").length, 1);
  assert.match($("#workspace-email-alerts").text(), /secure links in your alert emails/);
  assert.doesNotMatch(app + css, /saved-panel|alert-panel-summary/);
  assert.match(fn("renderSaved"), /badge.hidden = !items.length/);
  assert.match(fn("renderSaved"), /Workspace, \$\{items.length\} saved/);
  assert.match(fn("toggleSave"), /setSavedStatus\(result.saved/);
  assert.match(shell, /if \(status\) dialog.append\(status\)/);
  assert.match(shell, /if \(status\) dialog.after\(status\)/);
});

test("results hierarchy routes Export and alert commands without duplicating product state", () => {
  assert.equal($("#results-toolbar > #result-tier-counts").length, 1);
  const controls = $("#results-toolbar .toolbar-actions").children().toArray();
  assert.equal($(controls[0]).attr("id"), "filter-team-ready");
  assert.equal($(controls[1]).find("#sort").length, 1);
  assert.equal($(controls[2]).attr("id"), "open-results-chat");
  assert.equal($(controls[3]).attr("data-shell-menu"), "results");
  assert.equal($("#filter-team-ready").text(), "Team options only");
  assert.equal($("#filter-team-ready").attr("aria-pressed"), "false");
  assert.equal($("#open-results-chat").text(), "Ask AI");
  assert.equal($("#results-more-actions #export-csv").length, 1);
  const alert = $("#results-more-actions [data-shell-mirror]");
  assert.equal(alert.attr("data-shell-mirror"), "alert-new-matches");
  assert.equal(alert.attr("data-shell-focus"), "alert-new-matches");
  assert.equal(alert.attr("data-workspace-open"), "");
  assert.match(fn("updateSavedSearchAlertUi"), /command.disabled = !button \|\| button.disabled/);
  assert.match(fn("renderResults"), /const availableTeamCount = workflowDisplay.filter\(opportunityHasAvailableTeam\).length/);
  assert.match(fn("renderResults"), /hidden = !state.teamReadyOnly && !availableTeamCount/);
  for (const id of ["export-csv", "filter-team-ready", "alert-new-matches", "open-results-chat"]) {
    assert.equal(app.split(`$("${id}")`).filter(part => /^\??\.addEventListener\("click"/.test(part)).length, 1, id);
  }
  assert.doesNotMatch(shell, /history|location|pushState|replaceState/);
});

test("all four public pages share one utility disclosure, active location and exact asset bindings", async () => {
  const paths = ["assets/site-shell.js", "assets/site-shell.css", "assets/site-nav.js", "assets/site-nav.css", "assets/app.css"];
  const hashes = new Map(await Promise.all(paths.map(async path => [path, createHash("sha256").update(await read(path)).digest("hex")])));
  for (const [index, page] of pages.entries()) {
    const dom = load(page);
    const ids = dom("[id]").map((_, el) => dom(el).attr("id")).get();
    assert.equal(ids.length, new Set(ids).size, `page ${index}: unique IDs`);
    assert.deepEqual(dom("#primary-navigation > a").map((_, el) => dom(el).attr("href")).get(), ["./match_explorer.html", "./team_match.html", "./funded_awards.html"]);
    assert.equal(dom('#primary-navigation [data-shell-menu="navigation"]').length, 1);
    assert.equal(dom('#navigation-more > a[href="./faculty_interests.html"]').text(), "Update researcher profile");
    assert.equal(dom(".workspace-trigger").length, index === 0 ? 1 : 0);
    assert.equal(dom('script[src*="assets/site-shell.js"]').length, 1);
    assert.equal(dom('#primary-navigation button[aria-current="page"]').length, index === 3 ? 1 : 0);
    for (const [path, hash] of hashes) {
      const asset = dom(`script[src*="${path}"], link[href*="${path}"]`);
      if (asset.length) assert.ok((asset.attr("src") || asset.attr("href")).endsWith(`?v=${hash}`), path);
    }
  }
  assert.match(nav, /if \(event.target.closest\("\[data-shell-menu\]"\)\) return/);
  assert.match(nav, /if \(event.target.closest\("a, button"\)\) setOpen\(false\)/);
  assert.match(nav, /min-width: 1221px/);
  const awards = load(pages[2]);
  assert.equal(awards('.header-context-pill[role="group"]').attr("aria-label"), "NSF, NIH, DOE, and DoD award sources available");
  assert.deepEqual(awards(".header-context-agency").map((_, el) => awards(el).text()).get(), ["NSF", "NIH", "DOE", "DoD"]);
  assert.equal(awards(".header-context-row-break").text(), "·");
  assert.match(css, /width: min\(480px, 100vw\)/);
  assert.match(css, /@media \(max-width: 540px\)[\s\S]*?width: 100vw/);
  assert.match(css, /font-size: 16px/);
  assert.match(css, /forced-colors: active/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});

test("pre-change CSV, public URL, source selection and alert payloads remain identical", async () => {
  assert.deepEqual(JSON.parse(JSON.stringify(await captureBehavior(app))), baseline);
});

test("team filter remains reachable when active with no remaining team options", () => {
  const render = fn("renderResults");
  const fragment = render.slice(render.indexOf("    const workflowDisplay"), render.indexOf("    focusLinkedOpportunity(display)"));
  for (const active of [false, true]) for (const hasTeam of [false, true]) {
    const controls = new Map();
    const context = {
      state: { teamReadyOnly: active },
      $: id => { if (!controls.has(id)) controls.set(id, { setAttribute(key, value) { this[key] = value; } }); return controls.get(id); },
      currentWorkflowMatches: () => [{ team: hasTeam }], opportunityHasAvailableTeam: match => match.team,
      compactResultCounts: matches => String(matches.length),
    };
    vm.runInNewContext(fragment, context);
    assert.equal(controls.get("filter-team-ready").hidden, !active && !hasTeam);
    assert.equal(controls.get("filter-team-ready")["aria-pressed"], String(active));
    assert.equal(controls.get("filter-team-ready").disabled, !active && !hasTeam);
  }
});

test("card actions preserve every prior route in one lazily materialized grouped menu", () => {
  const cardMenuActions = new Map();
  const record = { ...baseline.record };
  let teamAvailable = true;
  const context = {
    URL, Set, Map, encodeURIComponent, cardMenuActions,
    catalog: { opportunities: [record] }, APP_CONFIG: { flags: {} }, EVALUATION_MODE: false,
    state: { query: "", savedIds: new Set(), refinement: { assessments: new Map() }, ai: { assessments: new Map() } },
    AWARD_LINKS_API: { fundedAwardsHref: () => "./funded_awards.html?opportunity=stage1-fixture", programIdentityForOpportunity: () => ({ id: "program-1", label: "Program 1" }) },
    opportunityHasAvailableTeam: () => teamAvailable, isBroadOpportunity: () => false,
    daysUntil: () => null, deadlineOverview: () => ({}),
  };
  for (const name of ["perAwardLabel", "programFundingLabel", "eligibilityOverview", "formatDate", "amendmentNotice", "matchedTopics", "truncate", "structuredDescription", "fundingEvidenceLabel", "deadlineEvidenceLabel", "deadlineRows", "pageFieldProvenance", "matchExplanation"]) context[name] = () => "";
  vm.createContext(context);
  for (const name of ["escapeHtml", "escapeAttribute", "safeUrl", "safeEmail", "recordId", "primaryContact", "contactOverview", "programContactAction", "officialActions", "opportunityTeamScopeId", "resultCard"]) vm.runInContext(fn(name), context);
  const html = context.resultCard({ index: 0 }, 1);
  const card = load(html);
  assert.equal(card(".card-actions > a").length, 1);
  assert.equal(card(".card-actions > button").length, 2);
  assert.equal(card(".card-actions .primary").attr("href"), record.primary_document_url);
  assert.equal(card("[data-opportunity-team]").attr("data-opportunity-team-scope"), record.opportunity_id);
  assert.equal(card(".card-topline [data-save]").length, 1);
  assert.equal(card("[data-watch-opportunity], [data-chat-record], [data-calendar]").length, 0);
  const groups = cardMenuActions.get(record.opportunity_id);
  assert.deepEqual(Array.from(groups, group => group.label), ["Analyze", "Track", "Sources", "Contact"]);
  const more = load(groups.map(group => group.html).join(""));
  assert.equal(more("[data-watch-opportunity]").attr("data-watch-opportunity"), record.opportunity_id);
  assert.equal(more("[data-watch-program]").attr("data-watch-program"), "program-1");
  assert.equal(more("[data-watch-program]").attr("data-watch-program-label"), "Program 1");
  assert.equal(more("[data-chat-record]").attr("data-chat-record"), record.opportunity_id);
  assert.equal(more("[data-funded-awards]").attr("href"), "./funded_awards.html?opportunity=stage1-fixture");
  assert.equal(more("[data-calendar]").attr("disabled"), undefined);
  assert.equal(more('[data-source-open="grants"]').attr("href"), record.detail_page);
  assert.equal(more('[data-source-open="agency"]').attr("href"), record.funding_opportunity_url);
  assert.equal(more('a[href^="mailto:"]').attr("href"), "mailto:public@example.org?subject=Question%20about%20STAGE-1");
  teamAvailable = false; record.close_date = "";
  assert.equal(load(context.resultCard({ index: 0 }, 1))("[data-opportunity-team]").length, 0);
  assert.equal(load(cardMenuActions.get(record.opportunity_id).map(group => group.html).join(""))("[data-calendar][disabled]").length, 1);
  assert.equal((app.match(/registerMenu\("card"/g) || []).length, 1);
  assert.match(fn("renderResults"), /cardMenuActions.clear\(\)/);
  assert.doesNotMatch(fn("resultCard"), /addEventListener|<template|\shidden[\s=>]/);
  assert.match(shell, /opener.after\(cardMenu\)/);
  assert.match(shell, /event.stopImmediatePropagation\(\)/);
  assert.doesNotMatch(shell, /role.*["']menu["']/);
});
