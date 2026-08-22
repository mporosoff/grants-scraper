import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const ROOT = new URL("../../", import.meta.url);

async function loadRuntime() {
  const context = {};
  context.globalThis = context;
  for (const path of [
    "assets/search-v2-config.js",
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "data/opportunities.js",
    "data/subtopics.js",
  ]) {
    vm.runInNewContext(await readFile(new URL(path, ROOT), "utf8"), context, { filename: path });
  }
  return context;
}

const runtime = await loadRuntime();
const queryApi = runtime.FUNDING_SEARCH_QUERY;
const retrievalApi = runtime.FUNDING_RETRIEVAL;
const configuration = runtime.FUNDING_SEARCH_V2_CONFIG;
const parentCatalog = runtime.GRANT_CATALOG;
const childCatalog = retrievalApi.createChildCatalog(runtime.SUBTOPIC_CATALOG);
const parentV1 = retrievalApi.create(parentCatalog, queryApi);
const parentV2 = retrievalApi.create(parentCatalog, queryApi, {
  searchV2: true,
  searchV2Config: configuration,
  catalogRole: "parent",
});
const childV2 = retrievalApi.create(childCatalog, queryApi, {
  searchV2: true,
  searchV2Config: configuration,
  catalogRole: "child",
});

function ranked(query, { evidence = true } = {}) {
  const parentDirect = parentV2.score(query, { evidence });
  const childDirect = childV2.score(query, { evidence });
  const emptyParent = { scores: new Float64Array(parentCatalog.opportunities.length) };
  const emptyChild = { scores: new Float64Array(childCatalog.opportunities.length) };
  const rolled = retrievalApi.rollupScores({
    parentCatalog,
    childCatalog,
    parentDirect,
    parentProfile: emptyParent,
    childDirect,
    childProfile: emptyChild,
    eligibilityBonuses: new Float64Array(parentCatalog.opportunities.length),
  });
  rolled.rows.sort((left, right) => right.relevance - left.relevance || left.id.localeCompare(right.id));
  return { parentDirect, childDirect, rolled };
}

test("browser query plans obey the shared search-v2 concept contract", () => {
  assert.equal(queryApi.contractVersion, configuration.compatibility.query_api_contract_version);
  assert.equal(retrievalApi.contractVersion, configuration.compatibility.retrieval_api_contract_version);
  for (const item of configuration.query_contract_cases) {
    const groups = queryApi.expandGroups(item.query, () => false, { searchV2: true });
    assert.deepEqual(
      [...groups].map(group => group.conceptId),
      [...item.concept_ids],
      item.query,
    );
  }
});

test("REE spelling variants resolve identically without lexical noise", () => {
  const variants = ["REE", "REEs", "R.E.E.", "rare earth elements"];
  const resultSets = variants.map(query => [...ranked(query).rolled.rows].map(row => row.id));
  resultSets.slice(1).forEach((ids, index) => {
    assert.deepEqual(ids, resultSets[0], variants[index + 1]);
  });
  assert.deepEqual(resultSets[0], []);
  assert.deepEqual(
    [...parentV1.score("REE").scores]
      .map((score, index) => score > 0 ? String(parentCatalog.opportunities[index].opportunity_id) : null)
      .filter(Boolean),
    ["362900"],
    "the disabled production path remains the frozen v1 behavior",
  );
});

test("REE separations admits the three authoritative programs as primary", () => {
  const result = ranked("REE separations");
  assert.deepEqual(
    new Set(result.rolled.rows.map(row => row.id)),
    new Set(["360678", "361526", "362061"]),
  );
  for (const row of result.rolled.rows) {
    assert.equal(row.parentDirectEvidence.admission.reason, "authoritative_scope_entailment");
    assert.equal(row.parentDirectEvidence.admission.admittedBy.length, 1);
    assert.equal(
      row.parentDirectEvidence.admission.admittedBy[0].path,
      "authoritative_scope_entailment",
    );
    assert.ok(row.parentDirectEvidence.authoritativeScope.controlledRelationships.length > 0);
  }
  const prohibited = new Set([
    "362900", "359996", "363224", "363241", "360003", "363240",
    "363325", "363258", "361234", "360004", "360007", "362847", "360881", "344592",
  ]);
  assert.deepEqual([...result.rolled.rows].filter(row => prohibited.has(row.id)), []);
});

test("bounded scope entailment covers controlled REE separation variants only", () => {
  for (const query of [
    "lanthanide separation",
    "rare earth element recovery",
    "solvent extraction of REEs",
    "ionic liquids for REE extraction",
  ]) {
    assert.deepEqual(
      new Set(ranked(query).rolled.rows.map(row => row.id)),
      new Set(["360678", "361526", "362061"]),
      query,
    );
  }
  const generic = parentV2.score("critical mineral separations", { evidence: true });
  assert.deepEqual([...generic.diagnostics.searchV2.authoritativeScopeEntailments], []);
});

test("mixed search-v2 assets fail loudly", () => {
  assert.throws(() => retrievalApi.create(
    { ...parentCatalog, schema_version: 999 },
    queryApi,
    { searchV2: true, searchV2Config: configuration, catalogRole: "parent" },
  ), /incompatible parent catalog schema/);
  assert.throws(() => retrievalApi.create(
    parentCatalog,
    { ...queryApi, contractVersion: 999 },
    { searchV2: true, searchV2Config: configuration, catalogRole: "parent" },
  ), /query code is incompatible/);
});

test("frozen Phase 2 evidence records every development gate without holdout execution", async () => {
  const results = JSON.parse(await readFile(
    new URL("evaluation/search_v2_results.json", ROOT),
    "utf8",
  ));
  const movement = JSON.parse(await readFile(
    new URL("evaluation/search_v2_movement_review.json", ROOT),
    "utf8",
  ));
  assert.equal(results.status, "development_gates_passed");
  assert.equal(results.production_enabled, false);
  assert.equal(results.holdout_status, "sealed_and_unopened");
  assert.equal(results.hard_gates.ree_separations_required_primary_ids_present, true);
  assert.equal(results.hard_gates.ree_separations_only_required_primary_results, true);
  assert.deepEqual(results.hard_gates.ree_family_irrelevant_admissions, []);
  assert.deepEqual(results.hard_gates.ree_family_unlabelled_admissions, []);
  assert.equal(results.meas5_cross_domain_gate.changed_top_10_queries, 0);
  assert.equal(movement.changed_top_10_queries, 14);
  assert.equal(movement.unchanged_top_10_queries, 35);
  assert.ok(movement.movements
    .filter(item => item.top_10_changed)
    .every(item => item.id.startsWith("ree_")));
});
