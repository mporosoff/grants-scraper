import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { shellDom } from "../helpers/shell-dom.mjs";

const paths = ["match_explorer.html", "assets/site-shell.js", "data/opportunity_team_index.js", "assets/search-retrieval.js", "data/opportunity_teams.js", "data/researcher_directory.js", "assets/opportunity-team.js", "assets/opportunity-team-panel.js"];
const [page, shell, ...sources] = await Promise.all(paths.map(path => readFile(new URL(`../../${path}`, import.meta.url), "utf8")));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
function fixture({ delayed = false } = {}) {
  const dom = shellDom(page, { deferredClose: true });
  const $ = id => dom.document.getElementById(id);
  $("results").innerHTML = '<article class="result-card"><button id="first" data-opportunity-team="358021" data-opportunity-team-scope="358021">Build team</button></article><article class="result-card"><button id="second" data-opportunity-team="344592" data-opportunity-team-scope="" data-opportunity-team-broad="true">Build team</button></article>';
  Object.assign(dom.context, { URL, location: { href: "https://example.org/match_explorer.html" } });
  vm.createContext(dom.context);
  vm.runInContext(shell, dom.context);
  for (const source of sources.slice(0, -1)) vm.runInContext(source, dom.context);
  // Explicitly published child fixture; the real team engine still applies
  // its own currentness and publication-eligibility checks after lazy loading.
  dom.context.FUNDING_SUBTOPICS = { loadSidecar: async () => ({ opportunities: ["344592:ab-0019", "344592:ab-0079"].map(subtopic_id => ({ subtopic_id, parent_id: "344592", publication_state: "publishable" })) }) };
  dom.context.FUNDING_RETRIEVAL = { ...dom.context.FUNDING_RETRIEVAL, createChildCatalog: value => value };
  dom.context.GRANT_CATALOG = { opportunities: ["358021", "344592"].map(opportunity_id => ({ opportunity_id, status: "posted", title: "Public fixture", posted_date: "2026-08-01", close_date: "2030-12-31" })) };
  let resolve;
  if (delayed) {
    const api = dom.context.OpportunityTeam;
    const pending = new Promise(done => { resolve = () => done(dom.context.OPPORTUNITY_TEAM_DATA); });
    dom.context.OpportunityTeam = { ...api, loadData: () => pending };
  }
  vm.runInContext(sources.at(-1), dom.context);
  return { ...dom, $, resolve, click: id => dom.dispatch("click", $(id)) };
}

test("Team Builder consumes the existing proposal/removal/replacement API and retains exact Team Match links", async () => {
  const dom = fixture();
  dom.click("first");
  await tick();
  const drawer = dom.$("team-builder");
  assert.equal(drawer.open, true);
  assert.equal(dom.$("results").querySelectorAll(".opportunity-team-panel").length, 0);
  assert.equal(drawer.querySelectorAll(".opportunity-team-panel").length, 1);
  const link = () => drawer.querySelector('.opportunity-team-next a');
  const original = new URL(link().getAttribute("href"), "https://example.org");
  assert.equal(original.pathname, "/team_match.html");
  assert.equal(original.searchParams.get("opportunity"), "358021");
  const remove = drawer.querySelector("[data-opportunity-team-remove]");
  const removedId = remove.getAttribute("data-opportunity-team-remove");
  dom.dispatch("click", remove);
  const after = new URL(link().getAttribute("href"), "https://example.org");
  assert.equal(after.searchParams.get("proposed").split(",").includes(removedId), false);
  const select = drawer.querySelector("[data-opportunity-team-replacement]");
  assert.ok(select, "existing replacement choices remain available");
  const replacement = select.querySelectorAll("option").find(option => option.getAttribute("value"));
  select.value = replacement.getAttribute("value");
  dom.dispatch("change", select);
  const add = drawer.querySelector("[data-opportunity-team-add-replacement]");
  assert.equal(add.disabled, false);
  dom.dispatch("click", add);
  assert.ok(new URL(link().getAttribute("href"), "https://example.org").searchParams.get("proposed").split(",").includes(replacement.getAttribute("value")));
  drawer.close();
  await tick();
  assert.equal(drawer.querySelectorAll(".opportunity-team-panel").length, 0);
  assert.equal(dom.document.activeElement.id, "first");
  dom.click("second");
  await tick();
  assert.match(drawer.textContent, /Choose a specific opportunity topic/);
  const choices = drawer.querySelectorAll("[data-opportunity-team-scope]");
  assert.equal(choices.length, 2);
  const scope = choices[0].getAttribute("data-opportunity-team-scope");
  dom.dispatch("click", choices[0]);
  await tick();
  assert.equal(new URL(link().getAttribute("href"), "https://example.org").searchParams.get("opportunity"), scope);
});

test("closed and rerendered team contexts cannot be repopulated by a late shared data load", async () => {
  const dom = fixture({ delayed: true });
  dom.click("first");
  dom.$("team-builder").close();
  await tick();
  dom.click("second");
  dom.resolve();
  await tick();
  assert.equal(dom.$("team-builder").querySelectorAll(".opportunity-team-panel").length, 1);
  assert.match(dom.$("team-builder").textContent, /Choose a specific opportunity topic/);
  dom.dispatch("funding-finder:before-results-render", dom.document.body);
  assert.equal(dom.$("team-builder").open, false);
  assert.equal(dom.$("team-builder-content").textContent, "");
  await tick();
  assert.equal(dom.$("team-builder-content").textContent, "");
});
