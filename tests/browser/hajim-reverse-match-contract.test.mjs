import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [apiSource, reverseSource, appSource, directorySource, graphSource, catalogSource, finderPage, teamPage, refreshWorkflow] = await Promise.all([
  readFile(new URL("../../assets/hajim-faculty.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/hajim-reverse-match.js", import.meta.url), "utf8"),
  readFile(new URL("../../assets/app.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/hajim_faculty_directory.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/faculty_matches.js", import.meta.url), "utf8"),
  readFile(new URL("../../data/opportunities.js", import.meta.url), "utf8"),
  readFile(new URL("../../match_explorer.html", import.meta.url), "utf8"),
  readFile(new URL("../../team_match.html", import.meta.url), "utf8"),
  readFile(new URL("../../.github/workflows/refresh-opportunities.yml", import.meta.url), "utf8"),
]);

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{"), source.lastIndexOf(";")).trim());
}

function loadApi() {
  const context = { globalThis: {} };
  vm.runInNewContext(apiSource, context);
  return context.globalThis.HajimFaculty;
}

const directory = assignmentJson(directorySource);
const graph = assignmentJson(graphSource);
const catalog = assignmentJson(catalogSource);

test("validates the shared schema, fingerprint, and reviewed roster counts", () => {
  const api = loadApi();
  assert.equal(api.validateDirectory(directory, catalog, directory.generation_id), directory);
  assert.equal(api.validateGraph(graph, directory, catalog, directory.generation_id), graph);
  assert.equal(directory.faculty_source.workbook.record_count, 156);
  assert.equal(directory.faculty_source.workbook.rankable_record_count, 145);
  assert.equal(directory.faculty_source.workbook.unlisted_interest_count, 11);
  assert.equal(directory.faculty_source.union_record_count, 158);
  assert.equal(directory.faculty_source.union_rankable_record_count, 148);
  assert.equal(directory.faculty_source.union_unrankable_count, 10);
  assert.equal(directory.generation_id, graph.generation_id);
  assert.equal(directory.asset_version, directory.generation_id);
  assert.deepEqual(directory.projection_fingerprints, graph.projection_fingerprints);
  assert.equal(directory.catalog.fingerprint, graph.catalog.fingerprint);
  assert.throws(() => api.validateDirectory(directory, catalog, "a".repeat(64)), /page generation/);
  assert.throws(() => api.validateGraph({ ...graph, generation_id: "a".repeat(64), asset_version: "a".repeat(64) }, directory, catalog), /out of sync/);
});

test("uses one content-derived generation in page markers, URLs, runtime validation, and publication", () => {
  const generation = directory.generation_id;
  const finderMarker = finderPage.match(/<meta name="hajim-match-generation" content="([a-f0-9]{64})"/);
  const teamMarker = teamPage.match(/<meta name="hajim-match-generation" content="([a-f0-9]{64})"/);
  assert.equal(finderMarker?.[1], generation);
  assert.equal(teamMarker?.[1], generation);
  assert.match(teamPage, new RegExp(`data/hajim_faculty_directory\\.js\\?v=${generation}`));
  assert.equal(loadApi().versionedAssetUrl("data/faculty_matches.js", generation), `data/faculty_matches.js?v=${generation}`);
  assert.match(reverseSource, /pageGenerationId\(\)/);
  assert.match(reverseSource, /versionedAssetUrl\("data\/hajim_faculty_directory\.js"/);
  assert.match(reverseSource, /versionedAssetUrl\("data\/faculty_matches\.js"/);
  assert.match(refreshWorkflow, /--version-target match_explorer\.html/);
  assert.match(refreshWorkflow, /--version-target team_match\.html/);
  assert.match(refreshWorkflow, /hajim_faculty_directory\.js\?v=\$\{faculty_generation\}/);
  assert.match(refreshWorkflow, /faculty_matches\.js\?v=\$\{faculty_generation\}/);
  assert.doesNotMatch([finderPage, teamPage, apiSource, reverseSource, refreshWorkflow].join("\n"), /hajim-pr1/);
});

test("applies independent bounded indexes for the full and 126-person scopes", () => {
  const api = loadApi();
  const all = api.opportunityMatches(graph, directory, "356055", false);
  const primary = api.opportunityMatches(graph, directory, "356055", true);
  assert.equal(all.length, 12);
  assert.equal(primary.length, 12);
  assert.ok(primary.every(item => ["hajim_primary_core", "hajim_research"].includes(item.profile.relationship)));
  assert.equal(new Set(all.map(item => `${item.edge.faculty_id}:${item.edge.opportunity_id}`)).size, all.length);
  assert.equal(primary.filter(item => !all.some(other => other.edge.faculty_id === item.edge.faculty_id)).length, 4);
  assert.ok(Object.values(graph.by_opportunity_primary).every(indexes => indexes.length <= 12));
});

test("keeps directory search local, ordered, and bounded to twelve results", () => {
  const api = loadApi();
  const target = directory.profiles.find(profile => profile.name === "Marc D. Porosoff");
  assert.equal(api.search(directory, "Marc D. Porosoff")[0].faculty_id, target.faculty_id);
  assert.equal(api.search(directory, "Marc D")[0].faculty_id, target.faculty_id);
  const unitResults = api.search(directory, "Chemical and Sustainability Engineering");
  assert.ok(unitResults.length > 0 && unitResults.length <= 12);
  assert.ok(unitResults.every(profile => api.normalize([profile.home_unit, ...profile.rosters].join(" ")).includes("chemical and sustainability engineering")));
  assert.ok(api.search(directory, "carbon dioxide capture").some(profile => profile.faculty_id === target.faculty_id));
  assert.ok(api.search(directory, "computational fluid dynamics").some(profile => profile.faculty_id === "david-g-foster"));
  assert.ok(api.search(directory, "controlled drug delivery").some(profile => profile.faculty_id === "melodie-i-lawton"));
  assert.ok(api.search(directory, "flexible electronics").some(profile => profile.faculty_id === "darren-lipomi"));
  assert.deepEqual(Array.from(api.search(directory, "Astrid M Muller"), profile => profile.faculty_id), ["astrid-m-muller"]);
  assert.equal(api.search(directory, "m").length, 0);
  assert.ok(api.search(directory, "", { showAll: true }).length <= 12);
  assert.doesNotMatch(apiSource, /fetch\(|XMLHttpRequest|sendBeacon|analytics/i);
});

test("Funding Finder lazy-loads both projections and isolates a failed faculty load", () => {
  assert.match(finderPage, /assets\/hajim-faculty\.js/);
  assert.match(finderPage, /assets\/hajim-reverse-match\.js/);
  assert.doesNotMatch(finderPage, /<script[^>]+(?:hajim_faculty_directory|faculty_matches)\.js/);
  assert.match(reverseSource, /data\/hajim_faculty_directory\.js/);
  assert.match(reverseSource, /data\/faculty_matches\.js/);
  assert.match(reverseSource, /Ordinary Funding Finder search and actions still work/);
  assert.match(reverseSource, /data-hajim-retry/);
  assert.doesNotMatch(reverseSource, /OpenAI|Anthropic|model provider|fetch\(/i);
  assert.match(apiSource, /script\.dataset\.hajimState = "loading"/);
  assert.match(apiSource, /script\.remove\(\)/);
  assert.match(apiSource, /existing\.dataset\.hajimState !== "loading"/);
  assert.match(apiSource, /discardAsset\("HAJIM_FACULTY_DIRECTORY"\)/);
  assert.match(apiSource, /discardAsset\("FACULTY_MATCHES"\)/);
});

test("reverse matching is offered only under Funding Finder's authoritative currentness gate", () => {
  assert.match(appSource, /\$\{recordIsCurrent\(record\) \? `<button class="source-action hajim-match-trigger"/);
  assert.match(appSource, /function recordIsCurrent\(record, asOf = runtimeDateIso\(\)\)/);
  assert.match(appSource, /RETRIEVAL_API\?\.recordIsCurrent\?\.\(record, asOf\)/);
  assert.match(appSource, /recordIsArchived\(record\)[\s\S]+status-archived/);
});

test("validation failures discard stale globals so a clean retry can load the current assets", async () => {
  const scope = { HAJIM_FACULTY_DIRECTORY: { schema_family: "stale" } };
  const removed = [];
  const staleScripts = {
    HAJIM_FACULTY_DIRECTORY: { remove() { removed.push("HAJIM_FACULTY_DIRECTORY"); } },
    FACULTY_MATCHES: { remove() { removed.push("FACULTY_MATCHES"); } },
  };
  const document = {
    querySelectorAll(selector) {
      const match = selector.match(/data-hajim-asset="([A-Z_]+)"/);
      return match && staleScripts[match[1]] ? [staleScripts[match[1]]] : [];
    },
  };
  const context = { globalThis: scope, document };
  vm.runInNewContext(apiSource, context);
  await assert.rejects(
    scope.HajimFaculty.loadDirectory(catalog, "unused-directory.js", directory.generation_id),
    /incompatible schema/,
  );
  assert.equal(scope.HAJIM_FACULTY_DIRECTORY, undefined);
  assert.ok(removed.includes("HAJIM_FACULTY_DIRECTORY"));
  scope.HAJIM_FACULTY_DIRECTORY = directory;
  const reloadedDirectory = await scope.HajimFaculty.loadDirectory(
    catalog, "unused-directory.js", directory.generation_id,
  );
  assert.equal(reloadedDirectory, directory);

  scope.FACULTY_MATCHES = { schema_family: "stale" };
  await assert.rejects(
    scope.HajimFaculty.loadGraph(directory, catalog, "unused-graph.js", directory.generation_id),
    /incompatible schema/,
  );
  assert.equal(scope.FACULTY_MATCHES, undefined);
  assert.ok(removed.includes("FACULTY_MATCHES"));
  scope.FACULTY_MATCHES = graph;
  const reloadedGraph = await scope.HajimFaculty.loadGraph(
    directory, catalog, "unused-graph.js", directory.generation_id,
  );
  assert.equal(reloadedGraph, graph);
});

test("stalled directory and graph scripts time out, detach, and allow a clean retry", async () => {
  const timers = [];
  let timerSequence = 0;
  const cleared = [];
  const removed = [];
  const listeners = [];
  const scope = {
    FUNDING_FINDER_APP: {
      boundedScripts: {
        sidecar: {
          setTimeout(callback) {
            timerSequence += 1;
            timers.push({ id: timerSequence, callback });
            return timerSequence;
          },
          clearTimeout(timer) { cleared.push(timer); },
        },
      },
    },
  };
  const document = {
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() {
      const handlers = {};
      const script = {
        dataset: {},
        addEventListener(type, callback) { handlers[type] = callback; },
        removeEventListener(type) { delete handlers[type]; },
        remove() { removed.push(script.dataset.hajimAsset); },
      };
      listeners.push(handlers);
      return script;
    },
    head: { appendChild() {} },
  };
  vm.runInNewContext(apiSource, { globalThis: scope, document });

  const directoryLoad = scope.HajimFaculty.loadDirectory(catalog, "stalled-directory.js", directory.generation_id);
  await new Promise(resolve => setImmediate(resolve));
  timers.shift().callback();
  await assert.rejects(directoryLoad, /Timed out loading HAJIM_FACULTY_DIRECTORY/);
  assert.deepEqual(removed, ["HAJIM_FACULTY_DIRECTORY"]);
  assert.equal(Object.keys(listeners[0]).length, 0);
  scope.HAJIM_FACULTY_DIRECTORY = directory;
  assert.equal(await scope.HajimFaculty.loadDirectory(catalog, "retry-directory.js", directory.generation_id), directory);

  const graphLoad = scope.HajimFaculty.loadGraph(directory, catalog, "stalled-graph.js", directory.generation_id);
  await new Promise(resolve => setImmediate(resolve));
  timers.shift().callback();
  await assert.rejects(graphLoad, /Timed out loading FACULTY_MATCHES/);
  assert.deepEqual(removed, ["HAJIM_FACULTY_DIRECTORY", "FACULTY_MATCHES"]);
  assert.equal(Object.keys(listeners[1]).length, 0);
  scope.FACULTY_MATCHES = graph;
  assert.equal(await scope.HajimFaculty.loadGraph(directory, catalog, "retry-graph.js", directory.generation_id), graph);
  assert.deepEqual(cleared, [1, 2]);
});

test("Team Match loads the directory initially but graph only after Hajim selection", () => {
  assert.match(teamPage, /<script src="data\/hajim_faculty_directory\.js/);
  assert.doesNotMatch(teamPage, /<script src="data\/faculty_matches\.js/);
  assert.match(teamPage, /function ensureFacultyGraph\(\)/);
  assert.match(teamPage, /ensureFacultyGraph\(\)\.then/);
  assert.match(teamPage, /Search Hajim faculty at the University of Rochester/);
  assert.match(teamPage, /role="combobox"/);
  assert.match(teamPage, /aria-activedescendant/);
  assert.match(teamPage, /Add a researcher manually/);
  assert.match(teamPage, /For collaborators outside Hajim or anyone not listed/);
  assert.doesNotMatch(teamPage, /<select id="researcher-choice"/);
});

test("browser code never requests the workbook or canonical JSON", () => {
  const browserSources = [apiSource, reverseSource, finderPage, teamPage].join("\n");
  assert.doesNotMatch(browserSources, /\.xlsx/i);
  assert.doesNotMatch(browserSources, /config\/hajim_faculty\.json/i);
});

test("reverse-match explanations and accessible one-panel behavior are deterministic", () => {
  assert.match(reverseSource, /Matched faculty interest:/);
  assert.match(reverseSource, /Opportunity evidence/);
  assert.match(reverseSource, /Derived corroboration:/);
  assert.match(reverseSource, /Source checked/);
  assert.match(reverseSource, /Likely relevant/);
  assert.match(reverseSource, /Possible relevance/);
  assert.match(reverseSource, /closeCurrent\(\{ restoreFocus: false \}\)/);
  assert.match(reverseSource, /trigger\.setAttribute\("aria-expanded", "true"\)/);
  assert.match(reverseSource, /heading\.focus\(\)/);
  assert.match(reverseSource, /closeCurrent\(\{ restoreFocus: true \}\)/);
  assert.match(reverseSource, /function panelIsOwned\(current\)/);
  assert.match(reverseSource, /function reconcileOpenPanel\(\)/);
  assert.match(reverseSource, /openPanel\.trigger === trigger/);
  assert.match(reverseSource, /funding-finder:before-results-render/);
  assert.match(appSource, /document\.dispatchEvent\(new CustomEvent\("funding-finder:before-results-render"\)\)/);
});
