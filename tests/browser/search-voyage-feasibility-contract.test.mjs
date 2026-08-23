import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const [harness, resultsSource, receiptSource, ceilingSource, decisionSource] = await Promise.all([
  readFile(new URL("tools/run_search_v2_voyage_feasibility.mjs", root), "utf8"),
  readFile(new URL("evaluation/search_v2_voyage_reranker_results.json", root), "utf8"),
  readFile(new URL("evaluation/search_v2_voyage_api_receipt.json", root), "utf8"),
  readFile(new URL("evaluation/search_v2_voyage_candidate_ceiling.json", root), "utf8"),
  readFile(new URL("evaluation/search_v2_voyage_reranker_decision.json", root), "utf8"),
]);
const results = JSON.parse(resultsSource);
const receipt = JSON.parse(receiptSource);
const ceiling = JSON.parse(ceilingSource);
const decision = JSON.parse(decisionSource);

test("Voyage feasibility harness is spent-data-only and cannot create relevance evidence", () => {
  assert.match(harness, /search_v2_holdout_frame\.json/);
  assert.match(harness, /search_v2_iteration2_holdout_frame\.json/);
  assert.doesNotMatch(harness, /search_v2_iteration3_holdout_truth/);
  assert.match(harness, /return_documents: false/);
  assert.match(harness, /model: MODEL/);
  assert.equal(results.architecture.semantic_score_creates_primary_evidence, false);
  assert.equal(results.safety.phase4c_read_or_executed, false);
  assert.equal(results.safety.phase4c_results_created, false);
  assert.deepEqual(results.safety.frozen_file_drift, []);
});

test("Voyage artifacts contain no API key and preserve the public-text contract", () => {
  for (const source of [resultsSource, receiptSource, ceilingSource, decisionSource]) {
    assert.doesNotMatch(source, /pa-[A-Za-z0-9_-]{12,}/);
    assert.doesNotMatch(source, /Bearer\s+[A-Za-z0-9_-]{12,}/);
  }
  assert.equal(receipt.authentication.key_printed_or_persisted_by_harness, false);
  assert.equal(receipt.authentication.raw_authorization_headers_persisted, false);
  assert.deepEqual(receipt.excluded_data, [
    "researcher_profiles",
    "CVs",
    "ORCID_information",
    "user_data",
    "private_material",
  ]);
});

test("Voyage improves reachable ranking but fails the pre-registered recall screen", () => {
  const baseline = results.quality.baseline_bm25f_at_depth_200;
  const voyage = results.quality.voyage_reranked_at_depth_200;
  assert.equal(baseline.required_recall_at_10, 0.476923);
  assert.equal(voyage.required_recall_at_10, 0.615385);
  assert.equal(voyage.required_recall_at_50, 0.661538);
  assert.equal(baseline.required_candidate_recall_at_depth, 0.661538);
  assert.equal(results.quality.vocabulary_gap_16_anchor_audit.newly_recovered_at_10, 3);
  assert.equal(decision.screening_gate.required_recall_at_50_threshold, 0.85);
  assert.equal(decision.screening_gate.passed, false);
  assert.equal(
    decision.recommendation,
    "VOYAGE RERANKING DOES NOT CLEAR THE QUALITY BAR — DISCARD API RERANKING",
  );
});

test("Voyage request receipt records successful usage and pre-scoring rate-limit attempts", () => {
  assert.equal(receipt.model, "rerank-2.5");
  assert.equal(receipt.successful_request_count, 52);
  assert.equal(receipt.total_request_attempt_count, 54);
  assert.equal(receipt.prior_rejected_transport_attempts.length, 1);
  assert.equal(receipt.prior_rejected_transport_attempts[0].count, 2);
  assert.equal(receipt.total_documents_reranked, 6653);
  assert.equal(receipt.usage_total_tokens, 2055171);
  assert.equal(results.performance.timeout_count, 0);
  assert.equal(results.performance.error_count, 2);
});
