import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import vm from "node:vm";
import test from "node:test";
import { shellDom } from "../helpers/shell-dom.mjs";
import { buildAwardSnapshot, snapshotPage } from "../../workers/award-api/src/snapshot.js";

const read = path => readFile(new URL(`../../${path}`, import.meta.url), "utf8");
const [app, chat, shell, page] = await Promise.all([read("assets/app.js"), read("assets/chat-ui.js"), read("assets/site-shell.js"), read("match_explorer.html")]);
const chatContext = { URL }; chatContext.globalThis = chatContext;
vm.runInNewContext(chat, chatContext);
const ui = chatContext.FUNDING_CHAT_UI;
function fn(source, name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  const end = source.indexOf("\n  }", start) + 4;
  return source.slice(start, end);
}

test("question retrieval keeps scientific qualifiers and recognizes factual follow-ups", () => {
  assert.equal(ui.retrievalQuery("What opportunities fit heterogeneous catalysis? Name a few options."), "heterogeneous catalysis");
  assert.equal(ui.retrievalQuery("Find funding for non-clinical ML and CO2 electroreduction"), "non-clinical ML CO2 electroreduction");
  assert.equal(ui.retrievalQuery("Find IT research opportunities"), "IT research");
  assert.equal(ui.retrievalQuery("What are their deadlines and eligibility requirements?"), "");
  const evidence = `${"Administrative introduction. ".repeat(150)}Heterogeneous catalysis at solid catalyst interfaces. ${"Other text. ".repeat(200)}`;
  assert.match(ui.evidenceExcerpt(evidence, "heterogeneous catalysis"), /solid catalyst interfaces/);
  assert.ok(ui.evidenceExcerpt(evidence, "heterogeneous catalysis").length <= 1602);
  assert.equal(ui.retrievalQuery("Which submission stages and deadlines are actually cited?"), "");
  assert.equal(ui.resolveEvidenceLinks("See [evidence-one](evidence-one)", [{ evidence_id: "evidence-one", url: "https://example.gov/notice" }]), "See [Official notice](https://example.gov/notice)");
  assert.equal(ui.resolveEvidenceLinks("[unknown](missing)", []), "[unknown](missing)");
});

test("chat uses up to ten relevant results regardless of question wording, card sort, or previous references", async () => {
  const records = Array.from({ length: 16 }, (_, index) => ({ opportunity_id: String(index), close_date: `2027-01-${String(index + 1).padStart(2, "0")}` }));
  const matches = records.map((_, index) => ({ index, score: 100 - index, workflowTier: index < 12 ? "strong" : "potential", evidenceTier: 1 }));
  matches[15].score = 1000;
  const displayed = [...matches].reverse();
  const context = {
    CHAT_UI: ui, MAX_CHAT_RESULTS: 10, state: { query: "catalysis", profile: { active: false }, ai: { mode: "results" } },
    catalog: { opportunities: records }, APP_CONFIG: { flags: { searchV2: true } },
    currentDisplayMatches: () => displayed, recordId: record => record.opportunity_id,
    RESULT_WORKFLOW_API: { workflowTier: match => match.workflowTier },
    computeMatches: () => { throw new Error("Chat must use the full current set without another retrieval"); },
    hybridSearchClient: { search: () => { throw new Error("Chat must not substitute another subset"); } },
  };
  vm.createContext(context);
  for (const name of ["compareValues", "sortMatches", "retrieveChatContext"]) vm.runInContext(fn(app, name), context);
  const ids = records.slice(0, 10).map(record => record.opportunity_id);
  const previous = [{ role: "assistant", contextIds: ["77", "78"], resultIds: ["78"] }];
  for (const question of [
    "What opportunities fit heterogeneous catalysis?", "Which of those has more funding instead?",
    "Which of those has a 2027 deadline?", "Which one has a 2027 deadline?", "What are their deadlines?",
    "Which cannot be funded?", "Which can't be funded?", "Which have USD budgets?", "Which are due in MAY?",
    "Which opportunities support AM?", "Which opportunities support CAN?", "Which opportunities support OR?",
    "Show me other opportunities instead", "Instead, show other opportunities", "New topic: CO2 electroreduction",
  ]) {
    const result = await context.retrieveChatContext(question, ids, previous);
    assert.equal(result.mode, "complete_results");
    assert.deepEqual([...result.ids], ids, question);
  }
  const reordered = await context.retrieveChatContext("Compare their budgets", [...ids].reverse(), previous);
  assert.deepEqual([...reordered.ids], ids, "Card order must not override relevance");
  const filtered = await context.retrieveChatContext("What are their deadlines?", ids.slice(1), previous);
  assert.deepEqual([...filtered.ids], ids.slice(1), "Only the current eligible set is supplied");
  const broad = await context.retrieveChatContext("Compare the opportunities", records.map(record => record.opportunity_id), previous);
  assert.deepEqual([...broad.ids], ids, "Strong matches precede Potential matches even with a higher score");
  assert.equal(broad.mode, "top_results");
  assert.deepEqual(displayed.map(match => match.index), [...matches].reverse().map(match => match.index), "Selecting context must not reorder the cards");
  const potential = await context.retrieveChatContext("Compare these leads", ["12", "13", "14", "15"]);
  assert.deepEqual([...potential.ids], ["15", "12", "13", "14"]);
  context.state.query = "";
  const filteredBrowse = await context.retrieveChatContext("Compare deadlines", records.map(record => record.opportunity_id));
  assert.deepEqual([...filteredBrowse.ids], ids, "Filter-only searches use the usual deadline tie-break");
  context.state.ai.mode = "foa-focus";
  const single = await context.retrieveChatContext("Explain this call", ["15"]);
  assert.deepEqual([...single.ids], ["15"]);
  assert.equal(single.mode, "focused_opportunity");
  assert.match(ui.resultScopeSummary(10, 10), /all 10 current results/);
  assert.match(ui.resultScopeSummary(11, 10), /10 most relevant of your 11 current results/);
  assert.equal(ui.resultContextLabel("complete_results", 10), "All 10 current results included");
  assert.equal(ui.resultContextLabel("top_results", 10), "Top 10 relevant results included");
});

test("unfiltered browsing stays disabled until a search or any non-default filter is applied", () => {
  const controls = new Map();
  const $ = id => {
    if (!controls.has(id)) controls.set(id, { value: id === "audience-filter" ? "all" : "", checked: ["status-posted", "status-forecasted"].includes(id) });
    return controls.get(id);
  };
  const state = { query: "", profile: { active: false }, ai: { active: false }, filters: { agency: new Set(), discipline: new Set() } };
  const context = { state, $, FACETS: { agency: {}, discipline: {} }, currentChatIds: () => Array(100).fill("a"), hasNofoDocument: () => false };
  vm.createContext(context);
  for (const name of ["hybridFilterState", "hasResultChatScope", "chatHasContext"]) vm.runInContext(fn(app, name), context);
  assert.equal(context.chatHasContext(), false);
  for (const id of ["query", "sort"]) {
    $(id).value = id === "query" ? "unsubmitted query" : "award";
    assert.equal(context.chatHasContext(), false, "Draft queries and card sorting do not scope the results");
  }
  state.query = "catalysis";
  assert.equal(context.chatHasContext(), true);
  state.query = "";
  for (const [id, property, value] of [
    ["status-posted", "checked", false], ["status-forecasted", "checked", false], ["status-archived", "checked", true],
    ["deadline-from", "value", "2027-01-01"], ["deadline-to", "value", "2027-12-31"], ["award-min", "value", "100"],
    ...["flag-evidence", "flag-preliminary", "flag-limited", "flag-early-career", "flag-no-cost-share"].map(id => [id, "checked", true]),
    ["audience-filter", "value", "research"],
  ]) {
    const original = $(id)[property];
    $(id)[property] = value;
    assert.equal(context.chatHasContext(), true, id);
    $(id)[property] = original;
    assert.equal(context.chatHasContext(), false, `Restoring ${id} to default disables chat`);
  }
  $("award-min").value = "0";
  assert.equal(context.chatHasContext(), false);
  for (const values of Object.values(state.filters)) {
    values.add("one");
    assert.equal(context.chatHasContext(), true);
    values.clear();
  }
  for (const [owner, key] of [[state.profile, "active"], [state, "teamReadyOnly"]]) {
    owner[key] = true;
    assert.equal(context.chatHasContext(), true);
    owner[key] = false;
  }
  state.ai = { active: true, mode: "foa-focus" };
  context.currentChatIds = () => ["one"];
  assert.equal(context.chatHasContext(), true);
  context.currentChatIds = () => [];
  assert.equal(context.chatHasContext(), false);
  context.hasNofoDocument = () => true;
  assert.equal(context.chatHasContext(), true);
  assert.match(page, /aria-describedby="chat-scope-hint"/);
});

test("Ask AI shows its ten-opportunity limit and explains the disabled unfiltered catalog state", () => {
  const dom = shellDom(page);
  const $ = id => dom.document.getElementById(id);
  const state = { searched: true, query: "", profile: { active: false }, filters: {}, refinement: { active: false }, nofo: { text: "" }, ai: { active: false, mode: "", busy: false, messages: [], suggestions: [] } };
  let ids = Array.from({ length: 100 }, (_, i) => String(i));
  const context = Object.assign(dom.context, {
    $, state, FACETS: {}, CHAT_UI: ui, MAX_CHAT_RESULTS: 10, DEFAULT_CHAT_SUGGESTIONS: [],
    currentChatIds: () => ids, providerReady: () => true, renderNofoContext() {},
    closeExpandedChat() { $("result-assistant").open = false; },
  });
  $("status-posted").checked = $("status-forecasted").checked = true;
  $("status-archived").checked = false;
  $("audience-filter").value = "all";
  vm.createContext(context);
  for (const name of ["hybridFilterState", "hasNofoDocument", "hasResultChatScope", "chatHasContext", "renderChatProviderState", "renderChat"]) vm.runInContext(fn(app, name), context);
  context.renderChat();
  assert.equal($("open-results-chat").disabled, true);
  assert.equal($("open-results-chat").hidden, false);
  assert.equal($("chat-scope-hint").hidden, false);
  assert.match($("chat-scope-hint").textContent, /Run a search or apply a non-default filter/);
  state.query = "catalysis";
  context.renderChat();
  assert.equal($("open-results-chat").disabled, false);
  assert.equal($("chat-submit").disabled, false);
  assert.match($("chat-scope-hint").textContent, /up to the 10 most relevant opportunities/);
  assert.doesNotMatch($("chat-scope-hint").textContent, /Run a search/);
  assert.match($("chat-summary").textContent, /10 most relevant of your 100 current results/);
  state.query = "";
  $("result-assistant").open = true;
  context.renderChat();
  assert.equal($("open-results-chat").disabled, true);
  assert.equal($("result-assistant").open, false);
  ids = [];
  state.nofo.text = "Uploaded notice";
  state.ai.mode = "uploaded-nofo";
  context.renderChat();
  assert.equal($("open-results-chat").disabled, false);
  assert.equal($("chat-scope-hint").hidden, true);
});

test("a drawer follows keyboard viewport changes and cleans up its temporary geometry", () => {
  const dom = shellDom('<button id="open">Open</button><dialog id="drawer" data-shell-drawer><textarea id="input"></textarea></dialog>');
  const listeners = new Map();
  dom.context.visualViewport = { height: 680, offsetTop: 0, addEventListener: (event, handler) => listeners.set(event, [...(listeners.get(event) || []), handler]) };
  vm.createContext(dom.context); vm.runInContext(shell, dom.context);
  const drawer = dom.document.getElementById("drawer"), input = dom.document.getElementById("input");
  dom.context.SiteShell.openDrawer(drawer, dom.document.getElementById("open"), input);
  dom.context.visualViewport.height = 340;
  dom.context.visualViewport.offsetTop = 36;
  listeners.get("resize").forEach(handler => handler());
  assert.equal(drawer.style["--drawer-viewport-height"], "340px");
  assert.equal(drawer.style["--drawer-viewport-top"], "36px");
  assert.equal(input.scrolled, true);
  dom.context.SiteShell.closeDrawer(drawer);
  assert.equal(drawer.style["--drawer-viewport-height"], undefined);
});

test("award sorting covers the complete snapshot and citation positions follow the selected order", () => {
  const awards = Array.from({ length: 32 }, (_, index) => ({ source: "NSF", award_id: String(index), title: `Project ${String(31 - index).padStart(2, "0")}`, award_date: `2025-${String(index % 12 + 1).padStart(2, "0")}-01`, institution: { name: "Test" }, principal_investigators: [] }));
  awards[0].award_date = "";
  const snapshot = buildAwardSnapshot({ snapshotId: "a".repeat(64), queryId: "b".repeat(64), asOf: "2026-09-05T00:00:00Z", request: { sources: ["NSF"], criteria: { topic: "test" } }, sourcePayloads: { NSF: { source: "NSF", results: awards, has_more: false, total_count: 32 } } });
  const first = snapshotPage(snapshot, { page: 1, pageSize: 10, sort: "title" });
  const second = snapshotPage(snapshot, { page: 2, pageSize: 10, sort: "title" });
  const flatten = page => page.batches.flatMap(batch => batch.results);
  assert.equal(flatten(first)[0].title, "Project 00");
  assert.equal(flatten(second)[0].title, "Project 10");
  assert.equal(first.aggregate.ordered_refs[0].award_id, "31");
  const oldest = snapshotPage(snapshot, { page: 1, pageSize: 50, sort: "oldest" });
  assert.equal(flatten(oldest).at(-1).award_id, "0", "missing dates stay last in either direction");
  assert.equal(snapshotPage(snapshot, { sort: "random" }), null);
  assert.equal(snapshotPage(snapshot).sort, "newest", "old clients keep the existing default");
});

test("award sort is retained in shared URLs and invalid sort values return to newest", async () => {
  const context = { URL, URLSearchParams };
  context.globalThis = context;
  vm.runInNewContext(await read("assets/institutional-intelligence-core.js"), context);
  const core = context.FUNDING_INSTITUTIONAL_INTELLIGENCE;
  assert.ok(core);
  const url = core.urlForState("https://example.test/funded_awards.html", { open: true, sort: "title", page: 3, page_size: 25 });
  assert.equal(url.searchParams.get("ii_sort"), "title");
  assert.equal(core.stateFromSearch(url.search).sort, "title");
  assert.equal(core.stateFromSearch("?ii=1&ii_sort=random").sort, "newest");
});

test("award evidence navigation honors sorted positions and resets canonical evidence outside a facet", async () => {
  const source = await read("assets/institutional-intelligence-snapshots.js");
  const requests = [];
  const context = {
    state: { page: 1, pageSize: 10, sort: "title", facet: { type: "all", key: "" },
      pagePayload: { aggregate: { ordered_refs: [{ evidence_id: "NSF:example", position: 21 }] } },
      question: { snapshot: { evidencePack: { awards: [{ evidence_id: "NSF:example", snapshot_position: 12 }] } } } },
    fetchPageWithRecovery: async request => requests.push(request),
    setBusy: () => {}, requestAnimationFrame: fn => fn(), evidenceDomId: id => id, $: () => null,
  };
  vm.createContext(context); vm.runInContext(fn(source, "focusAwardEvidence"), context);
  await context.focusAwardEvidence("NSF:example");
  assert.equal(requests[0].page, 3);
  assert.equal(requests[0].sort, "title");
  context.state.facet = { type: "investigator", key: "another investigator" };
  context.state.baseAggregate = { ordered_refs: [{ evidence_id: "NSF:example", position: 47 }] };
  context.state.sort = "oldest";
  context.state.pagePayload.aggregate.ordered_refs = [];
  await context.focusAwardEvidence("NSF:example");
  assert.equal(requests[1].page, 2, "Stale full-scope position 47 must not override canonical evidence position 12 outside the active facet");
  assert.equal(requests[1].sort, "newest");
  assert.equal(requests[1].facet.type, "all");
});

test("returning browsers load the current local snapshot sorting module through both award entry points", async () => {
  const digest = source => createHash("sha256").update(source).digest("hex");
  const snapshot = await read("workers/award-api/src/snapshot.js");
  const module = await read("assets/dod-awards-browser.mjs");
  assert.ok(module.includes(`../workers/award-api/src/snapshot.js?v=${digest(snapshot)}`));
  for (const path of ["assets/funded-awards.js", "assets/institutional-intelligence-snapshots.js"]) {
    assert.ok((await read(path)).includes(`./assets/dod-awards-browser.mjs?v=${digest(module)}`), path);
  }
});

test("award scope descriptions explain each selected order", async () => {
  const source = await read("assets/institutional-intelligence-snapshots.js");
  const context = {};
  vm.createContext(context); vm.runInContext(fn(source, "awardSortDescription"), context);
  assert.match(context.awardSortDescription("newest"), /^Newest/);
  assert.match(context.awardSortDescription("oldest"), /^Oldest/);
  assert.match(context.awardSortDescription("title"), /ordered by title/);
  assert.match(context.awardSortDescription("agency"), /ordered by agency/);
  assert.match(fn(source, "renderPage"), /awardSortDescription\(payload.sort\)/);
});
