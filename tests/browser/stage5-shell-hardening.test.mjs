import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";
import vm from "node:vm";
import test from "node:test";
import { load } from "cheerio";
import { shellDom } from "../helpers/shell-dom.mjs";

const read = path => readFile(new URL(`../../${path}`, import.meta.url), "utf8");
const [shell, tools, shellCss, navCss, ...pages] = await Promise.all([
  read("assets/site-shell.js"), read("assets/public-tools.js"), read("assets/site-shell.css"), read("assets/site-nav.css"),
  ...["match_explorer.html", "team_match.html", "funded_awards.html", "faculty_interests.html"].map(read),
]);

test("public dialogs keep named single controls, unrestricted zoom and page-specific compact header rules", () => {
  for (const [index, html] of pages.entries()) {
    const $ = load(html);
    assert.equal($(".funding-header").length, index === 0 ? 1 : 0);
    assert.equal($("meta[name='viewport']").attr("content"), "width=device-width, initial-scale=1");
    for (const dialog of $("dialog[data-shell-drawer]").toArray()) {
      const label = $(dialog).attr("aria-labelledby");
      assert.ok(label && $(`#${label}`).text().trim(), $(dialog).attr("id"));
      assert.equal($(dialog).find("[data-shell-drawer-close], [data-workspace-close]").length, 1);
    }
    for (const button of $("[data-shell-menu]").toArray()) {
      assert.ok($(button).attr("aria-label"));
      assert.doesNotMatch($(button).text(), /[⋯…]/);
    }
  }
  assert.match(navCss, /max-width: 800px\), \(min-width: 1221px\) and \(max-width: 1440px\)[^{]*\{\s*\.site-header\.funding-header \.brand/);
  assert.match(navCss, /min-width: 541px\) and \(max-width: 700px\)[^{]*\{\s*\.funding-header \.catalog-pill/);
  assert.match(shellCss, /@media \(max-width: 700px\) \{\s*\.workspace-trigger/);
});

test("failed modal activation releases the shared shell for the next independent tool", () => {
  const dom = shellDom(pages[0], { deferredClose: true });
  vm.createContext(dom.context);
  vm.runInContext(shell, dom.context);
  const get = id => dom.document.getElementById(id);
  const opener = dom.document.querySelector("[data-workspace-open]");
  const drawer = get("personal-workspace"), status = get("saved-status");
  drawer.showModal = () => { throw new Error("Native modal unavailable"); };
  assert.throws(() => dom.context.SiteShell.openDrawer(drawer, opener), /Native modal unavailable/);
  assert.equal(dom.document.documentElement.classList.contains("shell-drawer-open"), false);
  assert.equal(drawer.contains(status), false);
  assert.equal(opener.getAttribute("aria-expanded"), "false");
  assert.equal(dom.document.activeElement, opener);
  const listenerCount = [...dom.listeners.values()].reduce((sum, items) => sum + items.length, 0);
  const windowCount = dom.windowListeners.length;
  for (let repeat = 0; repeat < 3; repeat += 1) vm.runInContext(shell, dom.context);
  assert.equal([...dom.listeners.values()].reduce((sum, items) => sum + items.length, 0), listenerCount);
  assert.equal(dom.windowListeners.length, windowCount);
  dom.context.SiteShell.openDrawer(get("result-assistant"), get("open-results-chat"), get("chat-input"));
  assert.equal(get("result-assistant").open, true);
  dom.context.SiteShell.closeDrawer();
  assert.equal(dom.document.activeElement.id, "open-results-chat");
  assert.equal(dom.document.documentElement.classList.contains("shell-drawer-open"), false);
});

test("shell adapters stay bounded and cannot create network, storage or history ownership", () => {
  assert.ok(gzipSync(shell + tools).length < 6000, "Keep both shared controllers below 6 KB combined gzip");
  assert.doesNotMatch(shell + tools, /\bfetch\(|\bimport\(|localStorage|sessionStorage|history\.|URLSearchParams/);
  assert.doesNotMatch(pages[0], /<script[^>]+src=["'][^"']*data\/opportunity_teams\.js/);
});
