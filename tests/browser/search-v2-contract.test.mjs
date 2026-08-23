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
  rolled.rows.sort((left, right) => (
    Number(left.evidenceTier || 99) - Number(right.evidenceTier || 99)
    || right.relevance - left.relevance
    || left.id.localeCompare(right.id)
  ));
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

test("local search v2 uses fielded retrieval without scientific relationship mappings", () => {
  assert.equal(configuration.fielded_ranking.architecture, "bm25f_passage_coordination");
  assert.equal(configuration.fielded_ranking.use_configured_scientific_entailments, false);
  assert.deepEqual([...configuration.concept_families], []);
  assert.deepEqual([...configuration.source_scope_relationships], []);
  assert.deepEqual([...configuration.authoritative_scope_entailments], []);
  const result = parentV2.score("upper atmosphere radiation belt dynamics", { evidence: true });
  assert.equal(result.diagnostics.searchV2.rankingArchitecture, "fielded_bm25f");
  assert.equal(result.diagnostics.searchV2.configuredScientificEntailmentsUsed, false);
  assert.ok(result.scores[parentCatalog.opportunities.findIndex(record => (
    String(record.opportunity_id) === "356536"
  ))] > 0);
});

test("rich matching child carries its umbrella parent through one strongest passage", () => {
  const result = ranked("trustworthy AI research software");
  const genesis = result.rolled.rows.find(row => row.id === "361526");
  assert.ok(genesis);
  assert.equal(genesis.childDroveMatch, true);
  assert.equal(genesis.bestChild.id, "361526:e-18");
  assert.equal(genesis.bestChild.directEvidence.admission.reason, "fielded_complete_intent");
  assert.equal(genesis.bestChild.directEvidence.admission.admittedBy[0].path, "fielded_bm25f");
  assert.equal(result.rolled.cardinalityBonus, 0);
});

test("ordinary indexed evidence does not recreate configured REE entailments", () => {
  const result = ranked("rare earth solvent extraction");
  assert.equal(
    result.rolled.rows.length,
    0,
    "fielded scoring must not manufacture missing material/method evidence",
  );
  assert.deepEqual(
    [...parentV1.score("REE").scores]
      .map((score, index) => score > 0 ? String(parentCatalog.opportunities[index].opportunity_id) : null)
      .filter(Boolean),
    ["362900"],
    "the disabled production path remains the frozen v1 behavior",
  );
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

test("stabilized Phase 2/3 evidence records every development gate without holdout execution", async () => {
  const results = JSON.parse(await readFile(
    new URL("evaluation/search_v2_results.json", ROOT),
    "utf8",
  ));
  const movement = JSON.parse(await readFile(
    new URL("evaluation/search_v2_movement_review.json", ROOT),
    "utf8",
  ));
  const truth = JSON.parse(await readFile(
    new URL("evaluation/search_v2_development_truth.json", ROOT),
    "utf8",
  ));
  assert.equal(results.status, "development_gates_passed");
  assert.equal(results.phase, "2.1/3.1-stabilization");
  assert.equal(results.production_enabled, false);
  assert.equal(results.holdout_status, "sealed_and_unopened");
  assert.equal(results.hard_gates.ree_separations_required_primary_ids_present, true);
  assert.equal(results.hard_gates.ree_separations_only_required_primary_results, true);
  assert.deepEqual(results.hard_gates.ree_family_non_primary_admissions, []);
  assert.deepEqual(results.hard_gates.ree_family_unlabelled_admissions, []);
  assert.equal(results.hard_gates.query_specific_truth_keys_valid, true);
  assert.deepEqual(results.hard_gates.cross_domain_unjudged_top_10, []);
  assert.deepEqual(results.hard_gates.cross_domain_non_primary_top_10, []);
  assert.deepEqual(results.hard_gates.short_query_integrity_failures, []);
  assert.deepEqual(results.hard_gates.short_acronym_prefix_leakage, []);
  assert.equal(results.hard_gates.development_movements_reviewed, true);
  assert.equal(results.hard_gates.meas5_movements_reviewed, true);
  assert.equal(results.meas5_cross_domain_gate.changed_top_10_queries, 38);
  assert.equal(results.meas5_cross_domain_gate.status, "reviewed");
  assert.equal(movement.changed_top_10_queries, 25);
  assert.equal(movement.unchanged_top_10_queries, 24);
  assert.ok(movement.movements
    .filter(item => item.top_10_changed)
    .every(item => item.review?.status === "accepted" && item.review.reason));
  assert.equal(truth.sealed_holdout_inspected, false);
  assert.match(
    truth.queries.adv_chem_02.judgments["362061"].evidence,
    /artificial intelligence|AI|machine learning/i,
  );
  assert.doesNotMatch(
    truth.queries.adv_chem_02.judgments["362061"].evidence,
    /rare-earth|rare earth/i,
  );
});
