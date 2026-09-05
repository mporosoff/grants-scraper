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

test("question retrieval finds records beyond the first page without escaping the filtered set", async () => {
  const catalog = { opportunities: Array.from({ length: 80 }, (_, index) => ({ opportunity_id: String(index) })) };
  let remoteScope;
  const context = {
    CHAT_UI: ui, catalog, MAX_CHAT_RESULTS: 10, state: { ai: { mode: "results" } },
    recordId: record => record.opportunity_id,
    computeMatches: query => { assert.equal(query, "heterogeneous catalysis"); return { matches: [{ index: 70 }, { index: 79 }] }; },
    hybridCanRun: () => true,
    hybridSearchClient: { search: async (_query, options) => { remoteScope = options.eligibleParentIds; return { parents: [{ index: 75 }, { index: 79 }] }; } },
    hybridMatches: parents => parents,
  };
  vm.createContext(context); vm.runInContext(fn(app, "retrieveChatContext"), context);
  const ids = Array.from({ length: 78 }, (_, index) => String(index));
  const result = await context.retrieveChatContext("What opportunities fit heterogeneous catalysis?", ids, []);
  assert.deepEqual([...result.ids], ["70", "75"]);
  assert.equal(remoteScope.size, 78);
  assert.equal(remoteScope.has("79"), false);
  context.hybridSearchClient.search = async () => { throw new Error("offline"); };
  const fallback = await context.retrieveChatContext("heterogeneous catalysis", ids, []);
  assert.deepEqual([...fallback.ids], ["70"]);
  assert.equal(fallback.mode, "local_retrieval");
  const followUp = await context.retrieveChatContext("What are their deadlines?", ids, [{ role: "assistant", resultIds: ["75", "79"] }]);
  assert.deepEqual([...followUp.ids], ["75"]);

  const initial = await context.retrieveChatContext("Compare the cited award amounts and project durations.", ids, []);
  assert.equal(initial.mode, "initial_comparison");
  assert.deepEqual([...initial.ids], ids.slice(0, 10));
  assert.match(ui.resultScopeSummary(ids.length, 10), /General comparisons start with the first 10 results in the current order/);
  assert.match(ui.resultContextLabel(initial.mode, initial.ids.length, ids.length), /other 68 results are outside this comparison/);
  const compared = [{ role: "assistant", contextIds: initial.ids, resultIds: initial.ids.slice(0, 2) }];
  const reorderedFollowUp = await context.retrieveChatContext("What are their deadlines?", [...ids].reverse(), compared);
  assert.equal(reorderedFollowUp.mode, "connected_follow_up");
  assert.deepEqual([...reorderedFollowUp.ids], [...initial.ids], "Follow-ups preserve every supplied record, independently of model references and result ordering");
  const filteredFollowUp = await context.retrieveChatContext("What are their deadlines?", ids.slice(1), compared);
  assert.deepEqual([...filteredFollowUp.ids], [...initial.ids].slice(1), "Changed eligibility still excludes records outside the current search");
  for (const question of [
    "Which of those has a 2027 deadline?",
    "Which one has a 2027 deadline?",
    "What's the deadline?",
    "Does that one require an industry partner?",
    "Can either one support an early-career investigator?",
    "Which of those has a 2028 deadline instead?",
    "Which has a deadline after January 2027?",
    "Which awards offer over $500,000 per year?",
    "Are any of these eligible for early-career investigators?",
    "Does it require an industry partner?",
    "Which of those fit heterogeneous catalysis?",
    "Compare the previous opportunities by application effort.",
  ]) {
    const followUp = await context.retrieveChatContext(question, [...ids].reverse(), compared);
    assert.equal(followUp.mode, "connected_follow_up", question);
    assert.deepEqual([...followUp.ids], [...initial.ids], question);
  }
  for (const question of ["heterogeneous catalysis", "Instead, find heterogeneous catalysis.", "New topic: heterogeneous catalysis"]) {
    const changedTopic = await context.retrieveChatContext(question, ids, compared);
    assert.deepEqual([...changedTopic.ids], ["70"], "A new topic must retrieve across the eligible set despite prior comparison records");
    assert.equal(changedTopic.mode, "local_retrieval");
  }
  for (const forms of [
    ["cannot", "can't", "can’t", "can not"], ["couldn't", "could not"],
    ["won't", "will not"], ["wouldn't", "would not"], ["shouldn't", "should not"],
    ["mustn't", "must not"], ["needn't", "need not"], ["shan't", "shall not"],
    ["oughtn't", "ought not"], ["daren't", "dare not"],
  ]) {
    for (const form of forms) {
      const question = `Which ${form} be funded?`;
      const followUp = await context.retrieveChatContext(question, ids, compared);
      assert.equal(followUp.mode, "connected_follow_up", question);
      assert.deepEqual([...followUp.ids], [...initial.ids], question);
    }
  }
  assert.equal(ui.retrievalQuery("Which cannot be funded?"), ui.retrievalQuery("Which can't be funded?"));
  assert.equal(ui.isResultFollowUp("Which cannot support heterogeneous catalysis?"), false, "Normalizing negation must not discard a new scientific topic");
  assert.equal(ui.isResultFollowUp("Instead of those, find homogeneous catalysis"), false);
  assert.equal(ui.isResultFollowUp("New topic: CO2 electroreduction"), false);
  assert.equal(ui.isResultFollowUp("What are the deadlines for homogeneous catalysis?"), false);
  assert.equal(ui.isResultFollowUp("Find IT research opportunities"), false, "The IT abbreviation must not be treated as a pronoun");
  assert.equal(ui.isResultFollowUp("Find catalysis opportunities with budgets above $500,000"), false);
  assert.equal(ui.isResultFollowUp("Which one-carbon metabolism opportunities are available?"), false);
  assert.equal(ui.retrievalQuery("What's available for heterogeneous catalysis?"), "heterogeneous catalysis");
  for (const question of ["Instead, show other opportunities", "New search: other opportunities", "Start over"]) {
    for (const history of [[], compared, [...compared, { role: "assistant", resultIds: [] }]]) {
      const restart = await context.retrieveChatContext(question, ids, history);
      assert.equal(restart.mode, "needs_topic", question);
      assert.deepEqual([...restart.ids], [], "A restart without a topic must not reuse or substitute comparison records");
    }
  }
  for (const [eligible, history] of [[ids.slice(10), compared], [ids, [...compared, { role: "assistant", resultIds: [] }]]]) {
    const unavailable = await context.retrieveChatContext("Which of those has a 2027 deadline?", eligible, history);
    assert.equal(unavailable.mode, "unavailable_follow_up");
    assert.deepEqual([...unavailable.ids], [], "An unavailable or empty previous answer must never silently use another comparison");
  }
  const small = await context.retrieveChatContext("What are their deadlines?", ids.slice(0, 8), []);
  assert.equal(ui.resultContextLabel(small.mode, small.ids.length, 8), "Comparison of all 8 current results");
});

test("broad browsing is blocked at 101 results, while bounded and uploaded contexts remain usable", () => {
  const context = { MAX_CHAT_SCOPE: 100, currentChatIds: () => Array(100).fill("a"), hasNofoDocument: () => false };
  vm.createContext(context); vm.runInContext(fn(app, "chatHasContext"), context);
  assert.equal(context.chatHasContext(), true);
  context.currentChatIds = () => Array(101).fill("a");
  assert.equal(context.chatHasContext(), false);
  context.hasNofoDocument = () => true;
  assert.equal(context.chatHasContext(), true);
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
