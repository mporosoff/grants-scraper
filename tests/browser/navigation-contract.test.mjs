import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [mainPage, teamPage, navigationScript, helpScript, navigationStyles] = await Promise.all([
  readFile(new URL("../../match_explorer.html", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
  readFile(new URL("../../assets/site-nav.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/site-help.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/site-nav.css", import.meta.url), "utf8"),
]);

test("links the public and team matchers through shared navigation", () => {
  for (const page of [mainPage, teamPage]) {
    assert.match(page, /id="primary-navigation"/);
    assert.match(page, /href="\.\/match_explorer\.html"/);
    assert.match(page, /href="\.\/team_match\.html"/);
    assert.match(page, /data-nav-toggle/);
    assert.match(page, /data-help-open/);
    assert.match(page, /assets\/site-nav\.css/);
    assert.match(page, /assets\/site-nav\.js/);
    assert.match(page, /assets\/site-help\.js/);
  }
  assert.match(mainPage, /href="\.\/match_explorer\.html" aria-current="page"/);
  assert.match(teamPage, /href="\.\/team_match\.html" aria-current="page"/);
});

test("mobile navigation is accessible and safely dismissible", () => {
  assert.doesNotThrow(() => new Function(navigationScript));
  assert.match(navigationScript, /aria-expanded/);
  assert.match(navigationScript, /event\.key === "Escape"/);
  assert.match(navigationScript, /pointerdown/);
  assert.match(navigationStyles, /@media \(max-width: 820px\)/);
  assert.match(navigationStyles, /\.nav-toggle\s*\{[\s\S]*?display:\s*none/);
  assert.match(navigationStyles, /\.site-nav\.is-open\s*\{[\s\S]*?display:\s*flex/);
  assert.match(navigationStyles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(navigationStyles, /@media \(forced-colors: active\)/);
});

test("shared Help explains the full workflow and optional provider keys", () => {
  assert.doesNotThrow(() => new Function(helpScript));
  assert.match(helpScript, /Search is free\. AI is optional\./);
  assert.match(helpScript, /Normal catalog search and the Team matcher do not need a key/);
  assert.match(helpScript, /Upload and chat with a NOFO/);
  assert.match(helpScript, /Create an OpenAI API key/);
  assert.match(helpScript, /https:\/\/platform\.openai\.com\/api-keys/);
  assert.match(helpScript, /https:\/\/developers\.openai\.com\/api\/docs\/quickstart/);
  assert.match(helpScript, /Create an Anthropic API key/);
  assert.match(helpScript, /https:\/\/platform\.claude\.com\/settings\/keys/);
  assert.match(helpScript, /https:\/\/platform\.claude\.com\/docs\/en\/manage-claude\/authentication/);
  assert.match(helpScript, /showModal/);
  assert.match(helpScript, /data-help-close/);
  assert.match(navigationStyles, /\.help-dialog::backdrop/);
  assert.match(navigationStyles, /\.help-provider-grid/);
  assert.match(navigationStyles, /max-height:\s*calc\(100dvh - 16px\)/);
});
