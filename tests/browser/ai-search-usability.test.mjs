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

test("every bounded result is included regardless of question wording or previous references", async () => {
  const context = {
    CHAT_UI: ui, MAX_CHAT_RESULTS: 10, state: { ai: { mode: "results" } },
    computeMatches: () => { throw new Error("Chat must use the full current set without another retrieval"); },
    hybridSearchClient: { search: () => { throw new Error("Chat must not substitute another subset"); } },
  };
  vm.createContext(context); vm.runInContext(fn(app, "retrieveChatContext"), context);
  const ids = [...Array.from({ length: 9 }, (_, index) => String(index)), "75"];
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
  assert.deepEqual([...reordered.ids], [...ids].reverse());
  const filtered = await context.retrieveChatContext("What are their deadlines?", ids.slice(1), previous);
  assert.deepEqual([...filtered.ids], ids.slice(1), "Only the current eligible set is supplied");
  const broad = await context.retrieveChatContext("Compare the opportunities", [...ids, "76"], previous);
  assert.deepEqual([...broad.ids], [], "An oversized scope must never be silently truncated");
  assert.match(ui.resultScopeSummary(10, 10), /all 10 current results/);
  assert.match(ui.resultScopeSummary(11, 10), /Narrow to 10 or fewer/);
  assert.equal(ui.resultContextLabel("complete_results", 10), "All 10 current results included");
});

test("broad browsing is blocked at 11 results, while bounded and uploaded contexts remain usable", () => {
  const context = { MAX_CHAT_SCOPE: 10, currentChatIds: () => Array(10).fill("a"), hasNofoDocument: () => false };
  vm.createContext(context); vm.runInContext(fn(app, "chatHasContext"), context);
  assert.equal(context.chatHasContext(), true);
  context.currentChatIds = () => Array(11).fill("a");
  assert.equal(context.chatHasContext(), false);
  context.hasNofoDocument = () => true;
  assert.equal(context.chatHasContext(), true);
  assert.match(app, /const MAX_CHAT_SCOPE = MAX_CHAT_RESULTS/);
  assert.match(page, /aria-describedby="chat-scope-hint"/);
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
