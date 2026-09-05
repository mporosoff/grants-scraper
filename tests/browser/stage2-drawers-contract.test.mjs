import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import test from "node:test";
import vm from "node:vm";
import { validateOperationUser } from "../../workers/ai-gateway/src/input-policy.js";
import { load } from "cheerio";
import { shellDom } from "../helpers/shell-dom.mjs";

const read = path => readFile(new URL(`../../${path}`, import.meta.url), "utf8");
const [page, app, shell, teamPanel, css] = await Promise.all([
  read("match_explorer.html"), read("assets/app.js"), read("assets/site-shell.js"), read("assets/opportunity-team-panel.js"), read("assets/site-shell.css"),
]);
function fn(source, name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  const tail = source.slice(start);
  const end = tail.slice(3).search(/\n  (?:async )?function /);
  return tail.slice(0, end + 3);
}
function appFixture() {
  const dom = shellDom(page, { deferredClose: true });
  const $ = id => dom.document.getElementById(id);
  const state = { searched: true, ai: { mode: "", busy: false, messages: [] } };
  const errors = [];
  Object.assign(dom.context, {
    $, state, catalog: { opportunities: [{ opportunity_id: "one", title: "One opportunity" }] },
    chatHasContext: () => true,
    providerReady: () => $("k-provider").value === "hosted" || !!$("k-key").value,
    clearNofoState() {}, renderChat() {}, setAiBusy(value) { state.ai.busy = value; },
    recordId: record => record.opportunity_id,
    setAiStatus: message => errors.push(message),
    renderResults() {},
  });
  vm.createContext(dom.context);
  vm.runInContext(shell + "\nlet providerSetupWasOpen = false;", dom.context);
  for (const name of ["chatOpener", "openExpandedChat", "closeExpandedChat", "renderChatProviderState", "focusChatOnRecord"]) vm.runInContext(fn(app, name), dom.context);
  return { ...dom, $, state, errors };
}

test("AI and team dialogs live outside results with singular controls and chevrons", () => {
  const $ = load(page);
  assert.equal($("dialog[data-shell-drawer]").length, 4);
  assert.equal($(".workspace #result-assistant, .workspace #team-builder, .workspace .opportunity-team-panel").length, 0);
  assert.equal($("#result-assistant #chat-form").length, 1);
  for (const id of ["provider-setup", "k-provider", "k-key", "save-key", "clear-key", "saved-status"]) assert.equal($(`[id="${id}"]`).length, 1, id);
  assert.equal($("#chat-k-provider, #chat-k-key, #chat-save-key, #connect-chat-key").length, 0);
  const ids = $("[id]").toArray().map(node => $(node).attr("id"));
  assert.equal(new Set(ids).size, ids.length);
  assert.match(app, /More <span aria-hidden="true">▾<\/span>/);
  assert.doesNotMatch(app + page, /More[\s\S]{0,30}[⋯…]|chat-expanded/);
  assert.doesNotMatch(teamPanel, /showModal\(|addEventListener\("keydown"|card.appendChild\(panel\)/);
  assert.match(css, /\.site-drawer-wide/);
  assert.match(css, /\.site-drawer :is\(input, select, textarea\) \{ font-size: 16px/);
});

test("one provider form moves into chat, preserves unsaved credentials, and returns after every close", async () => {
  const dom = appFixture();
  const { $, context } = dom;
  const setup = $("provider-setup");
  $("k-provider").value = "openai";
  $("k-key").value = "unsaved-fixture-only";
  setup.open = true;
  context.openExpandedChat($("open-results-chat"));
  assert.equal($("result-assistant").open, true);
  assert.equal($("chat-provider-slot").contains(setup), true);
  assert.equal($("search-provider-slot").contains(setup), false);
  assert.equal(dom.document.activeElement.id, "chat-input");
  assert.equal($("result-assistant").contains($("saved-status")), true);
  $("result-assistant").close();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal($("search-provider-slot").contains(setup), true);
  assert.equal(setup.open, true);
  assert.equal($("k-key").value, "unsaved-fixture-only");
  assert.equal(dom.document.activeElement.id, "open-results-chat");
  assert.equal($("result-assistant").contains($("saved-status")), false);
  $("k-key").value = "";
  context.openExpandedChat($("open-results-chat"));
  assert.equal(dom.document.activeElement.id, "k-provider");
  assert.equal(setup.open, true);
  context.SiteShell.openDrawer($("personal-workspace"), $("open-results-chat"));
  assert.equal($("search-provider-slot").contains(setup), true);
  assert.equal($("result-assistant").open, false);
  assert.equal($("personal-workspace").contains($("saved-status")), true);
});

test("card context clears the previous conversation and returns to the replacement More opener", async () => {
  const dom = appFixture();
  const { $, context, state } = dom;
  const opener = dom.document.createElement("button");
  opener.id = "card-more";
  opener.setAttribute("data-card-more", "one");
  $("results").append(opener);
  state.ai.messages = [{ role: "assistant", text: "Prior opportunity" }];
  state.ai.busy = true;
  $("chat-input").value = "Prior question";
  context.renderResults = () => {
    const replacement = dom.document.createElement("button");
    replacement.id = "replacement";
    replacement.setAttribute("data-card-more", "one");
    $("results").replaceChildren(replacement);
  };
  context.focusChatOnRecord("one", opener);
  assert.equal(state.ai.messages.length, 0);
  assert.equal(state.ai.busy, false);
  assert.equal($("chat-input").value, "");
  assert.equal($("result-assistant").getAttribute("data-shell-context"), "opportunity");
  context.closeExpandedChat();
  await Promise.resolve();
  assert.equal(dom.document.activeElement.id, "replacement");
});

test("a failed drawer open releases provider ownership and leaves ordinary search available", () => {
  const dom = appFixture();
  dom.$("result-assistant").showModal = () => { throw new Error("fixture failure"); };
  dom.context.openExpandedChat(dom.$("open-results-chat"));
  assert.equal(dom.$("search-provider-slot").contains(dom.$("provider-setup")), true);
  assert.equal(dom.document.documentElement.classList.contains("shell-drawer-open"), false);
  assert.match(dom.errors[0], /search results remain available/);
});

test("uploaded notice extraction opens the same shell context and remembers its original opener", async () => {
  const dom = appFixture();
  const { $, state, context } = dom;
  state.ready = true;
  state.profile = { active: true };
  let finishExtraction;
  Object.assign(context, {
    NOFO_API: {
      extract: () => new Promise(resolve => { finishExtraction = resolve; }),
      matchCatalog: () => ({ record: context.catalog.opportunities[0], confidence: "exact", reason: "Fixture identity" }),
      suggestedQuery: () => "public notice",
    },
    resetFilterControls() {}, runSearch() {}, setNofoUploadStatus() {},
    currentModel: () => "unchanged-fixture", recordDeploymentUsage() {},
  });
  vm.runInContext(fn(app, "openNofoFromFile"), context);
  $("nofo-file").focus();
  const pending = context.openNofoFromFile({ name: "public-fixture.pdf" });
  $("query").focus(); // Extraction is asynchronous; this is not the opener.
  finishExtraction({ name: "public-fixture.pdf", text: "Public notice", pageCount: 1, pagesRead: 1, wordCount: 2, truncated: false });
  await pending;
  assert.equal($("result-assistant").getAttribute("data-shell-context"), "notice");
  assert.equal(state.nofo.matchedId, "one");
  assert.equal($("chat-provider-slot").contains($("provider-setup")), true);
  context.closeExpandedChat();
  assert.equal(dom.document.activeElement.id, "nofo-file");
});

test("protected algorithms, team output and AI request construction remain byte-identical", async () => {
  const baseline = JSON.parse(await read("tests/fixtures/stage2-preserved-behavior.json"));
  for (const [path, expected] of Object.entries(baseline.files)) {
    // Optional institution normalization is authorized; the user-fixes function
    // baseline freezes every other function in this module.
    if (path === "assets/team-researchers.js") continue;
    assert.equal(createHash("sha256").update(await readFile(new URL(`../../${path}`, import.meta.url))).digest("hex"), expected, path);
  }
  for (const [key, expected] of Object.entries(baseline.functions)) {
    const [path, name] = key.split("#");
    assert.equal(createHash("sha256").update(fn(await read(path), name)).digest("hex"), expected, key);
  }
  for (const [name, expected] of Object.entries(baseline.requests)) {
    const source = fn(app, name);
    const start = source.indexOf("      const answer = await providerStructured(");
    const request = source.slice(start, source.indexOf("\n      );", start) + 9);
    assert.equal(createHash("sha256").update(request).digest("hex"), expected, name);
  }
});

function requestFixture(mode) {
  const controls = new Map();
  const $ = id => {
    if (!controls.has(id)) controls.set(id, { value: "", blur() {} });
    return controls.get(id);
  };
  const state = {
    ready: true, ordinarySearchSignature: "search-one", refinement: { active: false },
    ai: { mode, active: !!mode, messages: [], busy: false },
    nofo: { fileName: "fixture.pdf", text: "[Page 1] Public fixture notice", pageCount: 1, pagesRead: 1, matchedId: "one" },
  };
  const record = { opportunity_id: "one", title: "Public fixture" };
  const requests = [];
  const sandbox = {
    state, $, catalog: { opportunities: [record] }, MAX_AI_MESSAGE_CHARS: 3000, MAX_NOFO_AI_CHARS: 2000, MAX_CHAT_RESULTS: 10, MAX_CHAT_SCOPE: 100, PROMPT_VERSION: "fixture",
    hasNofoDocument: () => mode === "uploaded-nofo", providerReady: () => true,
    currentChatIds: () => ["one"], currentDisplayMatches: () => [{ index: 0 }],
    recordId: item => item.opportunity_id, compactRecord: item => item, compactResultRecord: item => ({ id: item.opportunity_id, title: item.title }), boundRecordPayload: item => item,
    retrieveChatContext: async () => ({ ids: ["one"], query: "fixture", mode: "local_retrieval", matches: new Map() }),
    evidenceFacts: () => [], refinementProfileContext: () => null, boundedConversationHistory: value => value.slice(-4).map(({ role, text }) => ({ role, text })),
    setAiBusy: value => { state.ai.busy = value; }, renderChat() {}, setAiStatus() {}, recordDeploymentUsage() {}, currentModel: () => "fixture",
    applyChatFocus: () => false,
    CHAT_UI: { retrievalQuery: value => value, resultContextLabel: () => "One opportunity from the current results", resolveEvidenceLinks: value => value, knownResultIds: (ids = []) => ids.filter(id => id === "one"), evidenceExcerpt: value => String(value || "") },
    FUNDING_AI: { knownEvidenceCitations: () => [] },
    providerStructured(operation, system, json) {
      if (operation === "result_chat") assert.ok(validateOperationUser(operation, json), "the actual chat payload must satisfy the hosted provider boundary");
      return new Promise((resolve, reject) => requests.push({ operation, system, payload: JSON.parse(json), resolve, reject }));
    },
  };
  vm.createContext(sandbox);
  for (const name of ["askNofo", "askResults"]) vm.runInContext(fn(app, name), sandbox);
  return { sandbox, state, requests };
}

for (const mode of ["", "uploaded-nofo"]) {
  test(`${mode || "results"} chat discards old-context completions and errors without clearing the new request's busy state`, async () => {
    for (const reject of [false, true]) {
      const { sandbox, state, requests } = requestFixture(mode);
      const pending = sandbox.askResults("What does the public notice establish?");
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(requests.length, 1);
      assert.equal(requests[0].operation, mode ? "notice_chat" : "result_chat");
      state.ai.messages = [{ role: "user", text: "New opportunity question" }];
      state.ai.mode = "foa-focus";
      state.ai.busy = true;
      reject ? requests[0].reject(new Error("Old failure")) : requests[0].resolve({ answer: "Old answer" });
      await pending;
      assert.deepEqual(state.ai.messages, [{ role: "user", text: "New opportunity question" }]);
      assert.equal(state.ai.busy, true);
    }
  });
  test(`${mode || "results"} chat still completes, displays failures, and allows a retry in its own context`, async () => {
    const { sandbox, state, requests } = requestFixture(mode);
    const failure = sandbox.askResults("First question");
    await new Promise(resolve => setImmediate(resolve));
    requests[0].reject(new Error("Provider unavailable"));
    await failure;
    assert.match(state.ai.messages.at(-1).text, /Provider unavailable/);
    assert.equal(state.ai.busy, false);
    const retry = sandbox.askResults("Retry the question");
    await new Promise(resolve => setImmediate(resolve));
    requests[1].resolve({ answer: "Public evidence", page_references: [1], referenced_result_ids: ["one"] });
    await retry;
    assert.equal(state.ai.messages.at(-1).text, "Public evidence");
    assert.equal(state.ai.busy, false);
    if (!mode) {
      assert.deepEqual([...state.ai.messages.at(-1).contextIds], ["one"]);
      const followUp = sandbox.askResults("What are its deadlines?");
      await new Promise(resolve => setImmediate(resolve));
      assert.ok(requests[2].payload.conversation.every(message => !Object.hasOwn(message, "contextIds")), "Local evidence scope metadata must not leak through the provider conversation boundary");
      requests[2].resolve({ answer: "Deadline not listed", referenced_result_ids: ["one"] });
      await followUp;
      sandbox.retrieveChatContext = async () => ({ ids: [], mode: "unavailable_follow_up", matches: new Map() });
      await sandbox.askResults("Which of those has a 2027 deadline?");
      assert.match(state.ai.messages.at(-1).text, /previous answer has no opportunities available/);
      assert.equal(requests.length, 3, "An unavailable prior comparison must not send a new set to the provider");
      assert.equal(state.ai.busy, false);
      sandbox.retrieveChatContext = async () => ({ ids: [], mode: "needs_topic", matches: new Map() });
      await sandbox.askResults("Instead, show other opportunities");
      assert.match(state.ai.messages.at(-1).text, /What research topic should I search for/);
      assert.equal(requests.length, 3, "A topic-free restart must not send the previous comparison to the provider");
      assert.equal(state.ai.busy, false);
    }
  });
}

test("a changed search cannot receive an old response even when its conversation is intentionally retained", async () => {
  const { sandbox, state, requests } = requestFixture("");
  const pending = sandbox.askResults("Old search question");
  await new Promise(resolve => setImmediate(resolve));
  state.ordinarySearchSignature = "new-search";
  requests[0].resolve({ answer: "Old search answer", result_action: "focus", focus_result_ids: ["one"] });
  await pending;
  assert.equal(state.ai.messages.length, 1);
  assert.equal(state.ai.messages[0].role, "user");
});
