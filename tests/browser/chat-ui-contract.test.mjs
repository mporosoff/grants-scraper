import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../", import.meta.url);

async function loadChatUi() {
  const source = await readFile(new URL("../assets/chat-ui.js", root), "utf8");
  const context = { URL };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: "chat-ui.js" });
  return context.FUNDING_CHAT_UI;
}

test("renders readable limited Markdown without allowing raw HTML", async () => {
  const chatUi = await loadChatUi();
  const rendered = chatUi.renderRichText([
    "### Best options",
    "",
    "1. **Strong fit:** University pilot",
    "2. _Possible fit:_ Needs verification",
    "",
    "<img src=x onerror=alert(1)>",
  ].join("\n"));

  assert.match(rendered, /<h5>Best options<\/h5>/);
  assert.match(rendered, /<ol>/);
  assert.match(rendered, /<strong>Strong fit:<\/strong>/);
  assert.match(rendered, /<em>Possible fit:<\/em>/);
  assert.match(rendered, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(rendered, /<img/);
});

test("allows safe Markdown links and rejects script links", async () => {
  const chatUi = await loadChatUi();
  const rendered = chatUi.renderRichText(
    "[Official notice](https://example.gov/foa) [unsafe](javascript:alert(1))",
  );

  assert.match(rendered, /href="https:\/\/example\.gov\/foa"/);
  assert.match(rendered, /target="_blank"/);
  assert.doesNotMatch(rendered, /href="javascript:/);
});

test("turns plain email addresses into safe mail links", async () => {
  const chatUi = await loadChatUi();
  const rendered = chatUi.renderRichText(
    "Contact viviane.schwartz@science.doe.gov or chris.bradley@science.doe.gov.",
  );

  assert.match(rendered, /href="mailto:viviane\.schwartz@science\.doe\.gov"/);
  assert.match(rendered, />viviane\.schwartz@science\.doe\.gov<\/a>/);
  assert.match(rendered, /href="mailto:chris\.bradley@science\.doe\.gov"/);
  assert.doesNotMatch(rendered, /mailto:chris\.bradley@science\.doe\.gov\./);
});

test("renders Markdown contact tables without flattening their rows", async () => {
  const chatUi = await loadChatUi();
  const rendered = chatUi.renderRichText([
    "### Program Officers and Email Addresses [Page 47]",
    "",
    "| Name | Email |",
    "|:-----|:------|",
    "| Viviane Schwartz | viviane.schwartz@science.doe.gov |",
    "| Chris Bradley | chris.bradley@science.doe.gov |",
  ].join("\n"));

  assert.match(rendered, /<div class="chat-table-wrap" tabindex="0">/);
  assert.match(rendered, /<table class="chat-table">/);
  assert.match(rendered, /<th scope="col" class="chat-table-align-left">Name<\/th>/);
  assert.match(rendered, /<td class="chat-table-align-left">Viviane Schwartz<\/td>/);
  assert.match(rendered, /href="mailto:chris\.bradley@science\.doe\.gov"/);
  assert.doesNotMatch(rendered, /\|:-----\|/);
});

test("keeps only unique result ids from the bounded context", async () => {
  const chatUi = await loadChatUi();
  const ids = chatUi.knownResultIds(
    ["A", "outside", "B", "A", "C"],
    ["A", "B", "C"],
    2,
  );

  assert.deepEqual([...ids], ["A", "B"]);
});

test("labels optional result narrowing clearly for singular and plural sets", async () => {
  const chatUi = await loadChatUi();

  assert.equal(
    chatUi.focusActionLabel(1),
    "Narrow results to this opportunity",
  );
  assert.equal(
    chatUi.focusActionLabel(3),
    "Narrow results to these 3 opportunities",
  );
  assert.equal(chatUi.focusActionLabel(0), "");
});
