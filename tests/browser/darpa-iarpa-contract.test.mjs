import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
// Exercise records emitted by the adapter, including the explicitly synthetic
// IARPA open fixture; no network, browser automation, or production mutation.
// Python contracts verify this shared catalog against the adapter's output.
const catalog = JSON.parse(await readFile(new URL("tests/fixtures/darpa_iarpa/catalog.json", root), "utf8"));
const sources = await Promise.all(["search-query", "search-retrieval", "search-hybrid", "app"].map(
  name => readFile(new URL(`assets/${name}.js`, root), "utf8"),
));
const apis = { globalThis: {} };
for (const source of sources.slice(0, 3)) vm.runInNewContext(source, apis);

test("individual calls enter lexical and semantic search with federal and sponsor facets", () => {
  const engine = apis.globalThis.FUNDING_RETRIEVAL.create(catalog, apis.globalThis.FUNDING_SEARCH_QUERY);
  const quantum = engine.score("quantum");
  for (const [index, record] of catalog.opportunities.entries()) {
    assert.ok(engine.score(record.opportunity_number).scores[index] > 0, record.opportunity_number);
    if (/QBI|quantum/.test(record.title)) assert.ok(quantum.scores[index] > 0, record.title);
    assert.equal(record.source_type, "Federal");
    assert.ok(catalog.facets.agency[record.agency]);
  }
  const corpus = apis.globalThis.FUNDING_HYBRID_SEARCH.buildCorpus({
    parentCatalog: catalog, childCatalog: { subtopics: [] }, currentnessRejectedIndexes: new Set(),
  });
  for (const record of catalog.opportunities) {
    assert.ok(corpus.some(passage => passage.parent_id === record.opportunity_id), record.title);
  }
});

function fn(name) {
  const start = sources[3].indexOf(`  function ${name}(`);
  assert.ok(start >= 0, name);
  const tail = sources[3].slice(start);
  const end = tail.slice(3).search(/\n  (?:async )?function /);
  return tail.slice(0, end + 3);
}

test("official actions, calendar, CSV and opportunity watches retain each call's identity", async () => {
  let blob, alert;
  class DownloadURL extends URL {
    static createObjectURL(value) { blob = value; return "blob:contract"; }
    static revokeObjectURL() {}
  }
  const context = {
    URL: DownloadURL, Blob, Date, Map, Set, encodeURIComponent, catalog,
    state: { ready: true, savedItems: [], refinement: { assessments: new Map() }, ai: { assessments: new Map() }, deployment: { review: {} } },
    runtimeDateIso: () => "2026-09-05", deadlineKindLabel: () => "Application",
    currentDisplayMatches: () => catalog.opportunities.map((_, index) => ({ index, workflowTier: "strong" })),
    RESULT_WORKFLOW_API: { potentialEvidence: () => null, workflowTierLabel: () => "Strong" },
    ALERTS_API: { open(value) { alert = value; } },
    recordById: id => catalog.opportunities.find(record => record.opportunity_id === id),
    hasPlaceholderAward: () => false, evidenceFacts: () => [], recordDeploymentUsage() {},
    document: { createElement: () => ({ click() {}, remove() {} }), body: { appendChild() {} } },
  };
  vm.createContext(context);
  for (const name of ["escapeHtml", "escapeAttribute", "safeUrl", "safeEmail", "recordId", "primaryContact", "officialActions", "deadlineEvidenceLabel", "fundingEvidenceLabel", "csvCell", "exportCsv", "calendarEvents", "openOpportunityAlert"]) {
    vm.runInContext(fn(name), context);
  }
  context.exportCsv();
  const csv = await blob.text();
  for (const record of catalog.opportunities) {
    assert.equal(context.officialActions(record).url, record.detail_page);
    const [event] = context.calendarEvents(record);
    assert.equal(event.date, record.close_date);
    assert.equal(event.url, record.detail_page);
    assert.ok(event.uid.startsWith(record.opportunity_id));
    assert.ok(csv.includes(record.opportunity_number));
    assert.ok(csv.includes(record.detail_page));
    context.openOpportunityAlert(record.opportunity_id, null);
    assert.ok(JSON.stringify(alert).includes(record.opportunity_id));
  }
});
