import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [indexSource, dataSource, directorySource, teamSource, retrievalSource, panelSource, appSource, page, teamPage] = await Promise.all([
  readFile(new URL("../../data/opportunity_team_index.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/opportunity_teams.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/researcher_directory.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/opportunity-team.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/search-retrieval.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/opportunity-team-panel.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/app.js", import.meta.url), "utf8"),
  readFile(new URL("../../match_explorer.html", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
]);

function loadApi() {
  const context = {
    globalThis: {},
    document: {
      querySelector(selector) {
        return selector === 'meta[name="opportunity-team-generation"]'
          ? { getAttribute: () => loadIndex().generation_id }
          : null;
      },
    },
  };
  vm.runInNewContext(indexSource, context);
  vm.runInNewContext(retrievalSource, context);
  vm.runInNewContext(dataSource, context);
  vm.runInNewContext(directorySource, context);
  vm.runInNewContext(teamSource, context);
  return {
    api: context.globalThis.OpportunityTeam,
    data: context.globalThis.OPPORTUNITY_TEAM_DATA,
    directory: context.globalThis.RESEARCHER_DIRECTORY,
  };
}

function loadIndex() {
  const context = { globalThis: {} };
  vm.runInNewContext(indexSource, context);
  return context.globalThis.OPPORTUNITY_TEAM_INDEX;
}

function record(id, overrides = {}) {
  return {
    opportunity_id: id,
    status: "posted",
    title: "Specific scientific opportunity",
    description: "A bounded research objective.",
    posted_date: "2026-08-01",
    close_date: "2026-12-31",
    ...overrides,
  };
}

test("validates the registry-identified staged directory without fixed counts", () => {
  const { api, data } = loadApi();
  assert.equal(api.validateData(data, data.generation_id), data);
  assert.equal(data.source_roster_counts.total, data.faculty.length);
  assert.equal(Object.values(data.pool_counts).reduce((sum, value) => sum + value, 0), data.faculty.length);
  assert.equal(api.searchFaculty(data, "Porosoff")[0].name, "Marc D. Porosoff");
  assert.ok(api.searchFaculty(data, "optical", { limit: 12 }).length > 1);
  assert.equal(api.searchFaculty(data, "x").length, 0);
  assert.equal(api.searchFaculty(data, "", { showAll: true }).length, 12);
});

test("admits only current specific parents, eligible children, and declared branches", () => {
  const { api, data } = loadApi();
  const engine = api.create(data);
  const now = new Date("2026-09-01T12:00:00Z");
  const specific = engine.resolveScope({
    parentId: "358021",
    scopeId: "358021",
    record: record("358021"),
    isBroad: false,
    now,
  });
  assert.equal(specific.ok, true);

  const broad = engine.resolveScope({
    parentId: "344592",
    record: record("344592"),
    isBroad: true,
    now,
  });
  assert.equal(broad.ok, false);
  assert.equal(broad.reason, "specific_scope_required");
  assert.equal(broad.scopes.length, 2);

  const missingChild = engine.resolveScope({
    parentId: "361526",
    scopeId: "361526:g-12",
    record: record("361526"),
    childCatalog: { opportunities: [] },
    isBroad: true,
    now,
  });
  assert.equal(missingChild.reason, "child_not_publication_eligible");

  const eligibleChild = engine.resolveScope({
    parentId: "361526",
    scopeId: "361526:g-12",
    record: record("361526"),
    childCatalog: { opportunities: [{
      subtopic_id: "361526:g-12",
      parent_id: "361526",
      publication_state: "publishable",
    }] },
    isBroad: true,
    now,
  });
  assert.equal(eligibleChild.ok, true);

  const branch = engine.resolveScope({
    parentId: "332894",
    scopeId: "332894:superconducting-qubits",
    record: record("332894"),
    isBroad: true,
    now,
  });
  assert.equal(branch.ok, true);
  assert.equal(branch.opportunity.record_type, "declared_branch");
});

test("runtime catalog state overrides a generated proposal at one immutable clock", () => {
  const { api, data } = loadApi();
  const engine = api.create(data);
  const before = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { close_date: "2026-09-01" }),
    isBroad: false, now: new Date("2026-09-01T23:59:59Z"),
  });
  assert.equal(before.ok, true);
  const after = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { close_date: "2026-09-01" }),
    isBroad: false, now: new Date("2026-09-02T00:00:01Z"),
  });
  assert.equal(after.reason, "not_current");
  const rolling = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { close_date: "2020-01-01", rolling: true }),
    isBroad: false, now: new Date("2026-09-02T00:00:01Z"),
  });
  assert.equal(rolling.reason, "not_current");
  const forecasted = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { status: "forecasted", close_date: "2026-12-31" }),
    isBroad: false, now: new Date("2026-09-02T00:00:01Z"),
  });
  assert.equal(forecasted.ok, true);
  const archived = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { status: "archived" }),
    isBroad: false, now: new Date("2026-09-01T00:00:00Z"),
  });
  assert.equal(archived.reason, "not_current");
  const staleUndated = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { close_date: "", posted_date: "2018-01-01" }),
    isBroad: false, now: new Date("2026-09-01T00:00:00Z"),
  });
  assert.equal(staleUndated.reason, "not_current");
  const informational = engine.resolveScope({
    parentId: "358021", scopeId: "358021",
    record: record("358021", { title: "Request for Information: imaging methods" }),
    isBroad: false, now: new Date("2026-09-01T00:00:00Z"),
  });
  assert.equal(informational.reason, "not_current");
});

test("removal exposes missing roles and replacements cannot silently claim unaudited coverage", () => {
  const { api, data } = loadApi();
  const engine = api.create(data);
  const opportunity = engine.opportunityById.get("361526:g-12");
  let state = engine.proposal(opportunity);
  const initial = engine.proposalView(state);
  assert.equal(initial.complete, true);
  assert.equal(initial.selected.length, 4);
  const removedId = opportunity.members.find(member => member.contribution.includes("Catalyst/material"))?.faculty_id
    || opportunity.members[1].faculty_id;
  state = engine.removeMember(state, removedId);
  const afterRemoval = engine.proposalView(state);
  assert.equal(afterRemoval.complete, false);
  assert.equal(afterRemoval.selected.length, 3);
  assert.ok(afterRemoval.unfilledRoles.length >= 1);
  assert.ok(afterRemoval.replacements.length >= 1);
  const alternative = afterRemoval.replacements.find(item => !item.reviewed);
  assert.ok(alternative, "expected an evidence-backed alternative requiring role review");
  state = engine.addReplacement(state, alternative.profile.id);
  const afterAlternative = engine.proposalView(state);
  assert.equal(afterAlternative.selected.length, 4);
  assert.equal(afterAlternative.complete, false, "a provisional alternative cannot fill an audited role");
  assert.ok(afterAlternative.roles.some(role => role.selected_alternative_ids.includes(alternative.profile.id)));
});

test("Funding Finder team proposals are lazy, rerender-safe and use the shared drawer", () => {
  assert.match(page, /meta name="opportunity-team-generation" content="[a-f0-9]{64}"/);
  assert.match(page, /assets\/opportunity-team\.js\?v=[a-f0-9]{64}/);
  assert.match(page, /assets\/opportunity-team-panel\.js\?v=[a-f0-9]{64}/);
  assert.match(page, /id="filter-team-ready"[^>]+aria-pressed="false"/);
  assert.match(page, /data\/researcher_directory\.js\?v=[a-f0-9]{64}/);
  assert.match(page, /data\/opportunity_team_index\.js\?v=[a-f0-9]{64}/);
  assert.ok(
    page.indexOf("data/researcher_directory.js") < page.indexOf("assets/opportunity-team.js"),
    "the canonical researcher directory must load before the opportunity-team validator",
  );
  assert.match(appSource, /teamAvailable \? `<button class="source-action opportunity-team-trigger"/);
  assert.match(appSource, /data-opportunity-team="\$\{escapeAttribute\(id\)\}"/);
  assert.match(appSource, /data-opportunity-team-broad="\$\{isBroadOpportunity\(record\)\}"/);
  assert.match(appSource, /state\.teamReadyOnly[\s\S]*?matches\.filter\(opportunityHasAvailableTeam\)/);
  const availabilityStart = appSource.indexOf("  function opportunityHasAvailableTeam(match) {");
  const availabilityEnd = appSource.indexOf("  function currentDisplayMatches() {", availabilityStart);
  const availabilitySource = appSource.slice(availabilityStart, availabilityEnd);
  assert.match(availabilitySource, /if \(!recordIsCurrent\(record\)\) return false/);
  assert.ok(
    availabilitySource.indexOf("recordIsCurrent(record)") < availabilitySource.indexOf(".hasAvailableScope({"),
    "runtime currentness must be checked before advertising generated team availability",
  );
  assert.match(appSource, /Team-building opportunities only/);
  assert.match(appSource, /document\.dispatchEvent\(new CustomEvent\("funding-finder:before-results-render"\)\)/);
  assert.match(panelSource, /var openPanels = new Map\(\)/);
  assert.match(panelSource, /function panelOwned\(current\)/);
  assert.match(panelSource, /function currentForElement\(element\)/);
  assert.match(panelSource, /openPanels\.set\(panel, current\)/);
  assert.match(panelSource, /function closeAll\(\)/);
  assert.match(panelSource, /SiteShell.openDrawer\(drawer, trigger/);
  assert.match(panelSource, /onClose: closeAll/);
  assert.match(panelSource, /funding-finder:before-results-render/);
  assert.doesNotMatch(panelSource, /addEventListener\("keydown"/);
  assert.match(panelSource, /aria-labelledby/);
  assert.match(panelSource, /aria-live/);
  assert.match(panelSource, /Add a missing researcher/);
  assert.match(panelSource, /faculty_interests\.html\?mode=add&return=team_match&opportunity=/);
  assert.match(panelSource, /No additional internal faculty member has source-backed evidence/);
  assert.doesNotMatch([page, teamPage, teamSource, panelSource].join("\n"), /\.xlsx|config\/opportunity_team_model\.json/i);
});

test("the eager availability index is exact, bounded, and omits the full team graph", () => {
  const index = loadIndex();
  const { api, data } = loadApi();
  assert.equal(index.generation_id, data.generation_id);
  assert.deepEqual(
    Array.from(index.scopes, scope => [scope.id, scope.parent_id, scope.record_type]),
    Array.from(data.opportunities, scope => [scope.id, scope.parent_id, scope.record_type]),
  );
  const specific = data.opportunities.find(scope => scope.record_type === "specific_parent");
  const branch = data.opportunities.find(scope => scope.record_type === "declared_branch");
  assert.equal(api.hasAvailableScope({ parentId: specific.parent_id, scopeId: specific.id }), true);
  assert.equal(api.hasAvailableScope({ parentId: branch.parent_id }), true);
  assert.equal(api.hasAvailableScope({ parentId: "unsupported" }), false);
  assert.doesNotMatch(indexSource, /faculty|why_team|why_person|missing_skills/);
});

test("a stale or stalled lazy projection is discarded and retryable", async () => {
  const removed = [];
  const loaded = loadApi();
  const scope = {
    OPPORTUNITY_TEAM_DATA: { schema_version: 99 },
    OPPORTUNITY_TEAM_INDEX: loadIndex(),
    RESEARCHER_DIRECTORY: loaded.directory,
  };
  const staleScript = { remove() { removed.push("stale"); } };
  const document = {
    querySelectorAll() { return [staleScript]; },
  };
  vm.runInNewContext(teamSource, { globalThis: scope, document });
  const { data } = loaded;
  await assert.rejects(
    scope.OpportunityTeam.loadData(data.generation_id),
    /incompatible identity or roster contract/,
  );
  assert.equal(scope.OPPORTUNITY_TEAM_DATA, undefined);
  assert.deepEqual(removed, ["stale"]);
  scope.OPPORTUNITY_TEAM_DATA = data;
  assert.equal(await scope.OpportunityTeam.loadData(data.generation_id), data);

  const timers = [];
  const detached = [];
  const timeoutScope = {
    OPPORTUNITY_TEAM_INDEX: loadIndex(),
    RESEARCHER_DIRECTORY: loaded.directory,
    FUNDING_FINDER_APP: {
      boundedScripts: {
        sidecar: {
          setTimeout(callback) { timers.push(callback); return timers.length; },
          clearTimeout() {},
        },
      },
    },
  };
  const timeoutDocument = {
    querySelectorAll() { return []; },
    createElement() {
      const listeners = {};
      return {
        dataset: {},
        addEventListener(type, callback) { listeners[type] = callback; },
        removeEventListener(type) { delete listeners[type]; },
        remove() { detached.push(true); },
      };
    },
    head: { appendChild() {} },
  };
  vm.runInNewContext(teamSource, { globalThis: timeoutScope, document: timeoutDocument });
  const stalled = timeoutScope.OpportunityTeam.loadData(data.generation_id);
  await new Promise(resolve => setImmediate(resolve));
  timers[0]();
  await assert.rejects(stalled, /timed out/);
  assert.deepEqual(detached, [true]);
  timeoutScope.OPPORTUNITY_TEAM_DATA = data;
  assert.equal(await timeoutScope.OpportunityTeam.loadData(data.generation_id), data);
});

test("Team Match exposes directory and governed missing-researcher paths", () => {
  assert.match(teamPage, /id="faculty-search"[^>]+role="combobox"/);
  assert.match(teamPage, /id="faculty-suggestions" role="listbox"/);
  assert.match(teamPage, /Search Hajim faculty at the University of Rochester/);
  assert.match(teamPage, /id="missing-researcher" type="button"/);
  assert.match(teamPage, /location\.assign\("\.\/faculty_interests\.html\?mode=add&return=team_match&handoff=" \+ encodeURIComponent\(result\.handoff\.token\)\)/);
  assert.match(teamPage, /OPPORTUNITY_TEAM_API\.searchFaculty/);
  assert.match(teamPage, /pool_state === "unadmitted"/);
  assert.match(teamPage, /Standby - one retained capability/);
  assert.doesNotMatch(teamPage, /ORCID_API|external-researcher-form|researcher-intake\.js/);
  assert.match(teamPage, /selected\.length >= MAX/);
  assert.match(teamPage, /applyProposedTeamFromUrl/);
  assert.match(teamPage, /params\.get\("handoff"\)/);
  assert.doesNotMatch(teamPage, /params\.get\("locals?"\)|[?&]locals?=/);
});
