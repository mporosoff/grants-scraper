import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [source, receipt, results, benchmark, decision, configuration] = await Promise.all([
  readFile(new URL("tools/run_search_v2_minilm_feasibility.mjs", root), "utf8"),
  readFile(new URL("evaluation/search_v2_local_minilm_model_receipt.json", root), "utf8")
    .then(JSON.parse),
  readFile(new URL("evaluation/search_v2_local_minilm_results.json", root), "utf8")
    .then(JSON.parse),
  readFile(new URL("evaluation/search_v2_local_minilm_runtime_benchmark.json", root), "utf8")
    .then(JSON.parse),
  readFile(new URL("evaluation/search_v2_local_minilm_decision.json", root), "utf8")
    .then(JSON.parse),
  readFile(new URL("config/search_v2.json", root), "utf8").then(JSON.parse),
]);

test("MiniLM feasibility harness is spent-data-only and cannot create admission evidence", () => {
  assert.doesNotMatch(source, /search_v2_iteration3_holdout_(?:frame|manifest|results|truth)\.json/);
  assert.match(source, /refuses Phase-4C inputs/);
  assert.equal(results.safety.phase4c_read_or_executed, false);
  assert.equal(results.safety.semantic_score_creates_primary_evidence, undefined);
  assert.equal(results.architecture.semantic_score_creates_primary_evidence, false);
  assert.equal(results.architecture.production_explanations_changed, false);
});

test("pinned model receipt excludes weights from the repository", () => {
  assert.equal(receipt.model.id, "cross-encoder/ms-marco-MiniLM-L6-v2");
  assert.equal(receipt.model.revision, "233902d25c440f23af6f7d6e94d2946bac0bee0a");
  assert.equal(receipt.model.license, "apache-2.0");
  assert.equal(receipt.weights.bytes, 23_200_716);
  assert.equal(receipt.weights.committed_to_repository, false);
  assert.equal(receipt.repository_integration, false);
});

test("MiniLM decision is based on bounded recall gain and unchanged Recall@50", () => {
  const baseline = results.quality.summary.baseline_bm25f_candidate[50];
  const reranked = results.quality.summary.minilm_reranked_candidate[50];
  const gaps = results.quality.vocabulary_gap_summary[50];

  assert.equal(baseline.required_recall_at_10, 0.476923);
  assert.equal(reranked.required_recall_at_10, 0.538462);
  assert.equal(baseline.required_recall_at_50, 0.6);
  assert.equal(reranked.required_recall_at_50, 0.6);
  assert.equal(gaps.semantic_rescues_into_top_10, 2);
  assert.equal(gaps.reachable_in_candidate_window, 9);
  assert.equal(decision.recommendation,
    "LOCAL MINILM RERANKING DOES NOT JUSTIFY ITS COST/WEIGHT — DISCARD THIS PATH");
});

test("runtime benchmark records native CPU, browser-style WASM, and no WebGPU claim", () => {
  assert.ok(benchmark.devices.cpu.warm_p50_ms > 0);
  assert.ok(benchmark.devices.wasm_single_thread.warm_p50_ms > 0);
  assert.equal(benchmark.webgpu_available_in_node_harness, false);
  assert.equal(decision.performance.same_query_20_passage_runtime_comparison
    .single_thread_wasm_warm_p50_ms, benchmark.devices.wasm_single_thread.warm_p50_ms);
});

test("experiment adds no scientific relationship configuration", () => {
  for (const key of [
    "concept_families",
    "controlled_relationships",
    "source_scope_relationships",
    "authoritative_scope_entailments",
    "broader_program_fits",
    "query_contract_cases",
  ]) assert.deepEqual(configuration[key], [], key);
  assert.equal(decision.safety.production_search_code_changed, false);
  assert.equal(decision.safety.model_integrated_into_site, false);
});
