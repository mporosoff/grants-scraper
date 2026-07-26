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

test("keeps only unique result ids from the bounded context", async () => {
  const chatUi = await loadChatUi();
  const ids = chatUi.knownResultIds(
    ["A", "outside", "B", "A", "C"],
    ["A", "B", "C"],
    2,
  );

  assert.deepEqual([...ids], ["A", "B"]);
});
