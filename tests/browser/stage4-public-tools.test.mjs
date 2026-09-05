import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";
import { load } from "cheerio";
import { shellDom } from "../helpers/shell-dom.mjs";

const read = path => readFile(new URL(`../../${path}`, import.meta.url), "utf8");
const hash = value => createHash("sha256").update(value).digest("hex");
const [shell, script, css, team, awards, researcher, baseline, snapshots] = await Promise.all([
  read("assets/site-shell.js"), read("assets/public-tools.js"), read("assets/public-tools.css"),
  read("team_match.html"), read("funded_awards.html"), read("faculty_interests.html"),
  read("tests/fixtures/stage4-public-baseline.json").then(JSON.parse), read("assets/institutional-intelligence-snapshots.js"),
]);

function fixture(html, mobile = false) {
  const dom = shellDom(html, { deferredClose: true });
  let change;
  const media = { matches: mobile, addEventListener(type, listener) { assert.equal(type, "change"); assert.equal(change, undefined); change = listener; } };
  dom.context.matchMedia = () => media;
  vm.createContext(dom.context);
  vm.runInContext(shell, dom.context);
  vm.runInContext(script, dom.context);
  dom.get = id => dom.document.getElementById(id);
  dom.click = id => dom.dispatch("click", dom.get(id));
  dom.resize = matches => { media.matches = matches; change(); };
  dom.api = dom.context.PublicTools;
  return dom;
}

test("Stage 4 preserves every pre-existing control, form rule, source badge and governed researcher form", () => {
  for (const [page, html] of Object.entries({ "team_match.html": team, "funded_awards.html": awards, "faculty_interests.html": researcher })) {
    const $ = load(html);
    const ids = $("[id]").map((_, node) => $(node).attr("id")).get();
    assert.equal(new Set(ids).size, ids.length, page);
    for (const control of baseline.dom[page].controls) {
      const node = $(`#${control.id}`);
      assert.equal(node.length, 1, control.id);
      assert.equal(node[0].name, control.tag);
      for (const key of ["type", "name", "min", "max", "maxlength", "required"]) assert.equal(node.attr(key), control[key], `${control.id} ${key}`);
      assert.deepEqual(node.find("option").map((_, option) => ({ value: $(option).attr("value"), text: $(option).text() })).get(), control.options);
    }
    if (baseline.dom[page].form) assert.equal(hash($.html($("#researcher-request-form"))), baseline.dom[page].form);
    if (baseline.dom[page].badge) assert.equal(hash($.html($(".header-context-pill"))), baseline.dom[page].badge);
    assert.equal($(".public-page-header").length, 1);
    assert.equal($("#primary-navigation > a").length, 3);
    assert.equal($("[data-workspace-open]").length, 0, "No unsupported page-local workspace");
  }
  const $ = load(researcher);
  assert.match($("h1").text(), /^Update researcher profile$/);
  assert.match($("[data-shell-menu='navigation']").attr("aria-label"), /current page/i);
});

test("Team Match has one desktop editor, one mobile sheet, and results beside the shared capabilities", () => {
  const $ = load(team);
  assert.equal($("style").length, 0);
  assert.equal($(".team-workspace > #team-sidebar #team-editor-content").length, 1);
  for (const id of ["pi-grid", "researcher-picker", "selected-terms", "themes"]) assert.equal($(`#team-editor-content #${id}`).length, 1);
  assert.equal($(".team-results .public-results-header #count").length, 1);
  assert.equal($(".team-results #filter").length, 1);
  assert.equal($("#team-editor-sheet #pi-grid").length, 0, "No duplicate editor");
  assert.equal($("#team-status-home #external-status[aria-live='polite']").length, 1);
  assert.match(css, /\.team-sidebar \{ position: sticky;[^}]*max-height:[^}]*overflow: auto/);
  assert.match(css, /max-width: 800px/);
  assert.match(css, /team-mobile-summary[^}]*position: sticky/);
  assert.match(css, /max-height: 400px[^}]*team-mobile-summary[^}]*position: static/);
});

test("Team sheet moves the exact controls, retains values/listeners, restores focus and announces outside a closed sheet", async () => {
  const dom = fixture(team, true), editor = dom.get("team-editor-content"), input = dom.get("faculty-search");
  input.value = "catalysis";
  let actions = 0;
  dom.get("add-researcher").addEventListener("click", () => { actions += 1; });
  assert.equal(editor.parentElement.id, "team-editor-sheet-body");
  dom.click("edit-team");
  assert.equal(dom.get("team-editor-sheet").open, true);
  assert.equal(dom.get("external-status").parentElement.id, "team-editor-sheet");
  input.setAttribute("aria-expanded", "true");
  const escape = dom.dispatch("keydown", input, { key: "Escape" });
  assert.equal(escape.prevented, true, "An open combobox consumes Escape before the sheet");
  assert.equal(dom.get("team-editor-sheet").open, true);
  input.setAttribute("aria-expanded", "false");
  assert.equal(dom.dispatch("keydown", input, { key: "Escape" }).prevented, false, "Otherwise native dialog cancellation remains available");
  dom.click("add-researcher");
  dom.api.updateTeamSummary(["Ada", "Grace"], false);
  assert.equal(dom.get("team-selected-summary").textContent, "2 selected · Ada · Grace");
  dom.context.SiteShell.closeDrawer();
  assert.equal(dom.document.activeElement.id, "edit-team");
  assert.equal(dom.get("external-status").parentElement.id, "team-status-home");
  dom.resize(false);
  assert.equal(editor.parentElement.id, "team-sidebar");
  assert.equal(input.value, "catalysis");
  dom.click("add-researcher");
  assert.equal(actions, 2);
  input.focus();
  dom.resize(true);
  assert.equal(dom.get("team-editor-sheet").open, true, "Do not hide focused desktop controls at a breakpoint");
  assert.equal(dom.document.activeElement, input);
  dom.resize(false);
  assert.equal(dom.get("team-editor-sheet").open, false);
  assert.equal(dom.document.activeElement, input);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(editor.parentElement.id, "team-sidebar");
  assert.equal(dom.document.documentElement.classList.contains("shell-drawer-open"), false);
});

test("Award hierarchy keeps canonical primary/advanced criteria, counts, facets, paging and AI together", () => {
  const $ = load(awards);
  for (const id of ["ii-institution", "ii-agency", "ii-topic", "ii-program"]) assert.equal($(`#ii-form #${id}`).closest("details").length, 0);
  for (const id of ["ii-pi", "ii-program-officer", "ii-year-start", "ii-year-end"]) assert.equal($(`#awards-advanced #${id}`).length, 1);
  assert.equal($("#ii-form").attr("novalidate"), undefined);
  assert.equal($(".public-results-header #ii-result-scope").length, 1);
  assert.equal($(".public-results-header #open-awards-ai").length, 1);
  assert.deepEqual($("[data-award-view]").map((_, node) => $(node).text()).get(), ["Projects", "Investigators", "Programs", "Institution summary"]);
  for (const id of ["ii-ask", "ii-question", "ii-question-answer", "ii-provider", "ii-key", "ii-privacy-note"]) assert.equal($(`#awards-ai #${id}`).length, 1);
  assert.equal($("#award-projects #ii-card-pagination").length, 1);
  assert.equal($("#award-institutions #ii-metrics").length, 1);
  assert.equal($("[data-award-view-panel] #ii-source-status").length, 0);
});

test("Award views are presentation only and preserve canonical facet values, page controls and history focus", () => {
  const dom = fixture(awards);
  dom.get("ii-investigators").value = "all";
  dom.click("award-view-investigators");
  assert.equal(dom.get("award-projects").hidden, true);
  assert.equal(dom.get("award-investigators").hidden, false);
  assert.equal(dom.get("award-view-investigators").getAttribute("aria-pressed"), "true");
  dom.api.showAwardProjects();
  assert.equal(dom.get("award-projects").hidden, false);
  assert.equal(dom.get("ii-investigators").value, "all");
  dom.api.restoreAwardFocus("ii-programs");
  assert.equal(dom.get("award-programs").hidden, false);
  assert.equal(dom.document.activeElement.id, "ii-programs");
  dom.get("ii-result-scope").textContent = "Previously returned 144 awards";
  dom.api.resetAwardViews();
  assert.equal(dom.get("ii-result-scope").textContent, "", "Clear search cannot leave a stale visible count");
  assert.equal(dom.get("award-projects").hidden, false);
  assert.doesNotMatch(script, /fetch\(|localStorage|sessionStorage|history\.|URLSearchParams|changeFacet|buildAwardRequest|structuredResult/);
});

test("Award AI uses the shared modal lifecycle, one status owner, exact close focus and evidence routing", async () => {
  const dom = fixture(awards);
  const count = [...dom.listeners.values()].reduce((n, items) => n + items.length, 0);
  vm.runInContext(script, dom.context);
  assert.equal([...dom.listeners.values()].reduce((n, items) => n + items.length, 0), count);
  dom.click("open-awards-ai");
  assert.equal(dom.api.awardAiOpen(), true);
  assert.equal(dom.document.activeElement.id, "ii-question");
  assert.equal(dom.get("ii-results-note").parentElement.id, "awards-ai");
  dom.get("ii-question").value = "Who has NSF awards?";
  dom.context.SiteShell.closeDrawer();
  assert.equal(dom.document.activeElement.id, "open-awards-ai");
  assert.equal(dom.get("ii-results-note").parentElement.id, "awards-status-home");
  dom.click("open-awards-ai");
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(dom.api.awardAiOpen(), true, "An earlier queued close cannot clear a reopened drawer");
  assert.equal(dom.get("ii-question").value, "Who has NSF awards?");
  dom.api.showAwardProjects({ closeAi: true });
  assert.equal(dom.api.awardAiOpen(), false);
  assert.equal(dom.get("award-projects").hidden, false);
  assert.equal(dom.get("ii-results-note").parentElement.id, "awards-status-home");
  dom.api.restoreAwardFocus("ii-question");
  assert.equal(dom.document.activeElement.id, "open-awards-ai", "History focus cannot reopen or focus a closed modal");
});

test("Advanced award filters reveal native invalid fields and restored criteria without changing validation", () => {
  const dom = fixture(awards);
  assert.equal(dom.get("awards-advanced").open, false);
  dom.dispatch("invalid", dom.get("ii-year-start"));
  assert.equal(dom.get("awards-advanced").open, true);
  dom.get("awards-advanced").open = false;
  dom.get("ii-program-officer").value = "Exact Published Name";
  dom.api.syncAwardForm();
  assert.equal(dom.get("awards-advanced").open, true);
  dom.get("awards-advanced").open = false;
  dom.api.restoreAwardFocus("ii-year-end");
  assert.equal(dom.get("awards-advanced").open, true);
});

test("Search, CSV, saves, alerts, AI payloads, team and researcher identity owners remain byte identical", async () => {
  for (const [path, expected] of Object.entries(baseline.files)) assert.equal(hash(await readFile(new URL(`../../${path}`, import.meta.url))), expected, path);
  const release = JSON.parse(await read("data/search-v2-release.json"));
  delete release.source_hashes;
  assert.deepEqual(release, baseline.searchRelease, "Search corpus, vector, generation and allowlist contracts are unchanged");
});

test("All Team Match and award controller functions outside the bounded presentation hooks remain identical", () => {
  const allowed = { "team_match.html": ["renderTeam", "updateToggles"], "assets/institutional-intelligence-snapshots.js": ["applyFormState", "renderPage", "runSearch", "focusAwardEvidence", "resetResultState", "bindEvents"] };
  for (const [path, source] of Object.entries({ "team_match.html": team, "assets/institutional-intelligence-snapshots.js": snapshots })) {
    const matches = [...source.matchAll(/^  (?:async )?function (\w+)\(/gm)];
    for (let i = 0; i < matches.length; i += 1) {
      const name = matches[i][1];
      if (allowed[path].includes(name)) continue;
      const body = source.slice(matches[i].index, matches[i + 1]?.index ?? source.length);
      assert.equal(hash(body), baseline.functions[path][name], `${path}: ${name}`);
    }
  }
});

test("New served assets use exact content versions and the maintained release manifest", async () => {
  const release = JSON.parse(await read("data/search-v2-release.json"));
  for (const file of ["public-tools.js", "public-tools.css", "team-match.css", "institutional-intelligence-snapshots.js"]) {
    const expected = hash(await read(`assets/${file}`));
    for (const html of [team, awards, researcher]) {
      if (html.includes(`assets/${file}?v=`)) assert.ok(html.includes(`assets/${file}?v=${expected}`), file);
    }
    if (file !== "institutional-intelligence-snapshots.js") assert.equal(release.source_hashes[`assets/${file}`], expected);
  }
  assert.match(css, /font-size: 16px/);
  assert.match(css, /forced-colors: active/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});
