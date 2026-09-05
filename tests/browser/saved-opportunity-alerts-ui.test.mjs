import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";
import { shellDom } from "../helpers/shell-dom.mjs";
import { MAX_WATCHED_OPPORTUNITIES, normalizeSubscription } from "../../workers/alerts/src/contract.js";

const root = new URL("../../", import.meta.url);
const [alertSource, appSource, page] = await Promise.all([
  readFile(new URL("assets/alerts.js", root), "utf8"),
  readFile(new URL("assets/app.js", root), "utf8"),
  readFile(new URL("match_explorer.html", root), "utf8"),
]);

function fixture() {
  const dom = shellDom('<button id="opener">Create alert</button>');
  const requests = [];
  Object.assign(dom.context, {
    structuredClone, AbortController, clearTimeout, innerWidth: 320,
    getComputedStyle: () => ({ display: "block", visibility: "visible", paddingRight: "0px" }),
    scrollTo() {},
    FUNDING_ALERTS_CONFIG: { endpoint: "https://alerts.example.test" },
    fetch: async (url, request) => {
      requests.push({ url, ...request, body: JSON.parse(request.body) });
      return { ok: true, json: async () => ({ status: "verification_required" }) };
    },
  });
  dom.context.window = dom.context;
  vm.createContext(dom.context);
  vm.runInContext(alertSource, dom.context);
  dom.get = id => dom.document.getElementById(id);
  dom.submit = () => dom.listeners.get("submit")[0].callback({ preventDefault() {} });
  return { ...dom, requests };
}

test("saved opportunity setup submits only selected public IDs with one verification request", async () => {
  const dom = fixture();
  const api = dom.context.FUNDING_ALERTS;
  api.open({ type: "saved_opportunities", definition: {}, savedOpportunities: [
    { id: "one", title: '<script>Example & title</script>', note: "PRIVATE NOTE" },
    { id: "two", title: "Second", profile_text: "PRIVATE PROFILE" },
  ] });
  assert.equal(dom.get("alert-dialog-title").textContent, "Watch saved opportunities");
  assert.equal(dom.get("alert-saved-options").querySelector("script"), null);
  assert.equal(dom.get("alert-saved-options").querySelectorAll("input:checked").length, 2);
  dom.get("alert-email").value = "researcher@example.edu";
  dom.get("alert-cadence").value = "weekly";
  await dom.submit();
  assert.equal(dom.requests.length, 1);
  assert.deepEqual(dom.requests[0].body, {
    email: "researcher@example.edu", baseline_opportunity_ids: [], subscription: {
      type: "opportunity", cadence: "weekly", definition: { opportunity_ids: ["one", "two"],
        triggers: ["deadline_changed", "amended", "closing_reminders", "status_changed"] },
    },
  });
  assert.ok(normalizeSubscription(dom.requests[0].body.subscription));
  assert.doesNotMatch(JSON.stringify(dom.requests), /PRIVATE|profile_text|Example/);
  assert.match(dom.get("alert-dialog-status").textContent, /remains inactive/);
});

test("saved group selection bounds agree with the service and empty or excessive selection sends nothing", async () => {
  const dom = fixture();
  dom.context.FUNDING_ALERTS.open({ type: "saved_opportunities", definition: {},
    savedOpportunities: Array.from({ length: MAX_WATCHED_OPPORTUNITIES + 1 }, (_, i) => ({ id: `id-${i}`, title: `Item ${i}` })),
  });
  const options = dom.get("alert-saved-options").querySelectorAll("input");
  assert.equal(options.filter(input => input.checked).length, MAX_WATCHED_OPPORTUNITIES);
  options.forEach(input => { input.checked = true; });
  await dom.submit();
  assert.equal(dom.requests.length, 0);
  options.forEach(input => { input.checked = false; });
  await dom.submit();
  assert.equal(dom.requests.length, 0);
  options.at(-1).checked = true;
  dom.get("alert-email").value = "researcher@example.edu";
  await dom.submit();
  assert.deepEqual(dom.requests[0].body.subscription.definition.opportunity_ids, [`id-${MAX_WATCHED_OPPORTUNITIES}`]);
});

test("existing opportunity and search setups hide group selection and retain their request types", async () => {
  const dom = fixture();
  dom.context.FUNDING_ALERTS.open({ type: "opportunity", definition: { opportunity_id: "one", triggers: ["amended"] } });
  assert.equal(dom.get("alert-saved-fields").classList.contains("hidden"), true);
  dom.get("alert-email").value = "researcher@example.edu";
  await dom.submit();
  assert.deepEqual(dom.requests[0].body.subscription.definition, { opportunity_id: "one", triggers: ["amended"] });
  dom.context.FUNDING_ALERTS.open({ type: "saved_search", definition: { query: "hydrogen" }, baselineOpportunityIds: ["one"] });
  assert.equal(dom.get("alert-trigger-fields").classList.contains("hidden"), true);
  await dom.submit();
  assert.equal(dom.requests[1].body.subscription.type, "saved_search");
  assert.deepEqual(dom.requests[1].body.baseline_opportunity_ids, ["one"]);
});

test("restored saved items enable alerts before catalog loading or searching and can still be watched individually", () => {
  const dom = shellDom(page);
  const calls = [];
  const state = { ready: false, searched: false, query: "", savedItems: [{ opportunity_id: "retained", title: "Retained opportunity", note: "private" }] };
  const context = { state, document: dom.document, $: id => dom.document.getElementById(id),
    SAVED_API: { idOf: item => item.opportunity_id }, ALERTS_API: { open: value => calls.push(value) },
    runCatalogAction() { throw new Error("Saved alerts must not depend on catalog loading"); },
    recordById() { throw new Error("No catalog yet"); },
  };
  vm.createContext(context);
  vm.runInContext(appSource.slice(appSource.indexOf("  function openOpportunityAlert("), appSource.indexOf("  function paginationItems(")), context);
  context.updateSavedOpportunityAlertUi(); context.updateSavedSearchAlertUi();
  assert.equal(dom.document.getElementById("alert-saved-opportunities").disabled, false);
  assert.equal(dom.document.getElementById("alert-new-matches").disabled, true);
  context.openSavedOpportunityAlert(); context.openOpportunityAlert("retained");
  assert.equal(calls[0].type, "saved_opportunities");
  assert.equal(calls[1].definition.opportunity_id, "retained");
  assert.doesNotMatch(JSON.stringify(calls[0].savedOpportunities), /private|note/);
  state.savedItems = []; context.updateSavedOpportunityAlertUi();
  assert.equal(dom.document.getElementById("alert-saved-opportunities").disabled, true);
  const savedRendering = appSource.slice(appSource.indexOf("  function renderSaved()"), appSource.indexOf("  function toggleSave("));
  assert.match(savedRendering, /updateSavedOpportunityAlertUi\(\)/);
  assert.match(appSource, /\$\("alert-saved-opportunities"\)\?\.addEventListener\("click", openSavedOpportunityAlert\)/);
});
