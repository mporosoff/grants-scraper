import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [harness, resultsSource, receiptSource, decisionSource, appConfig] = await Promise.all([
  readFile(new URL("tools/run_search_v2_hybrid_voyage_feasibility.mjs", root), "utf8"),
  readFile(new URL("evaluation/search_v2_hybrid_voyage_results.json", root), "utf8"),
  readFile(new URL("evaluation/search_v2_hybrid_voyage_api_receipt.json", root), "utf8"),
  readFile(new URL("evaluation/search_v2_hybrid_voyage_decision.json", root), "utf8"),
  readFile(new URL("assets/app-config.js", root), "utf8"),
]);
const results = JSON.parse(resultsSource);
const receipt = JSON.parse(receiptSource);
const decision = JSON.parse(decisionSource);

test("hybrid harness uses only spent evidence and public indexed passages", () => {
  assert.match(harness, /search_v2_holdout_frame\.json/);
  assert.match(harness, /search_v2_iteration2_holdout_frame\.json/);
  assert.doesNotMatch(harness, /search_v2_iteration3_holdout_(?:results|truth)/);
  assert.equal(results.evaluation_population.spent_only, true);
  assert.equal(results.evaluation_population.phase4c_read_or_executed, false);
  assert.deepEqual(results.safety.frozen_file_drift, []);
  assert.equal(results.safety.private_researcher_data_sent, false);
  assert.equal(results.safety.vectors_persisted_or_committed, false);
});

test("embedding and reranking contracts are bounded and non-causal", () => {
  assert.equal(results.model_choice.model, "voyage-4-lite");
  assert.equal(results.model_choice.dimension, 1024);
  assert.deepEqual(results.architecture.embedding_input_types, { corpus: "document", query: "query" });
  assert.equal(results.architecture.reranker, "rerank-2.5");
  assert.equal(results.architecture.semantic_scores_create_source_evidence, false);
  assert.equal(results.architecture.production_admission_changed, false);
  assert.equal(results.corpus.passage_count, 1659);
  assert.equal(results.corpus.vectors_persisted_or_committed, false);
});

test("candidate recall and hybrid ranking clear the feasibility thresholds", () => {
  assert.equal(results.candidate_retrieval.summary.bm25f.required_recall_at_200, 0.661538);
  assert.equal(results.candidate_retrieval.summary.semantic.required_recall_at_200, 0.984615);
  assert.equal(results.candidate_retrieval.summary.union.required_recall_at_200, 0.984615);
  assert.equal(results.candidate_retrieval.missing_bm25f_anchors_recovered_by_semantic_at_200, 21);
  assert.equal(results.final_ranking.hybrid_voyage.required_recall_at_10, 0.876923);
  assert.equal(results.final_ranking.hybrid_voyage.required_recall_at_50, 0.984615);
  assert.equal(results.final_ranking.gates.no_systematic_known_irrelevant_promotion, true);
  assert.equal(results.final_ranking.gates.observed_acronym_or_identifier_collision_count, 1);
  assert.equal(results.final_ranking.gates.exact_acronym_identifier_safeguard_required_for_any_production_design, true);
  assert.equal(results.final_ranking.gates.passed, true);
  assert.equal(decision.decision, "HYBRID VOYAGE RETRIEVAL + RERANKING CLEARS THE QUALITY BAR — PRODUCTION ARCHITECTURE SHOULD BE CONSIDERED");
});

test("receipt contains usage but no credential or stored vector data", () => {
  for (const source of [resultsSource, receiptSource, decisionSource]) {
    assert.doesNotMatch(source, /pa-[A-Za-z0-9_-]{12,}/);
    assert.doesNotMatch(source, /Bearer\s+[A-Za-z0-9_-]{12,}/);
  }
  assert.equal(receipt.embedding.model, "voyage-4-lite");
  assert.equal(receipt.embedding.corpus_requests.length, 7);
  assert.equal(receipt.embedding.query_requests.length, 52);
  assert.equal(receipt.reranking.requests.length, 52);
  assert.equal(receipt.reranking.total_tokens, 3349932);
  assert.equal(receipt.authentication.key_printed_or_persisted_by_harness, false);
  assert.equal(receipt.corpus_vectors_persisted, false);
  assert.match(appConfig, /searchV2:\s*false/);
});
