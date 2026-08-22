import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../../", import.meta.url);

async function source(path) {
  return readFile(new URL(path, ROOT), "utf8");
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

test("Phase 4 binds one immutable holdout execution to query-specific truth", async () => {
  const [rawSource, truthSource, resultsSource, preopenSource] = await Promise.all([
    source("evaluation/search_v2_holdout_results_raw.json"),
    source("evaluation/search_v2_holdout_truth.json"),
    source("evaluation/search_v2_holdout_results.json"),
    source("evaluation/search_v2_phase4_preopen.json"),
  ]);
  const raw = JSON.parse(rawSource);
  const truth = JSON.parse(truthSource);
  const results = JSON.parse(resultsSource);
  const preopen = JSON.parse(preopenSource);

  assert.equal(raw.execution_count, 1);
  assert.equal(raw.query_count, 24);
  assert.equal(raw.post_outcome_tuning_permitted, false);
  assert.equal(raw.candidate_code_sha, preopen.candidate_code_sha);
  assert.equal(
    raw.holdout_frame_sha256,
    preopen.hashes["evaluation/search_v2_holdout_frame.json"],
  );
  assert.equal(truth.raw_results_sha256, sha256(rawSource));
  assert.equal(truth.protocol.post_outcome_tuning, false);
  assert.deepEqual(new Set(truth.reviewed_query_ids), new Set(raw.results.map(item => item.id)));
  assert.ok(raw.results.every(item => truth.queries[item.id]?.query === item.query));
  assert.equal(results.raw_results_sha256, sha256(rawSource));
  assert.equal(results.truth_sha256, sha256(truthSource));
  assert.deepEqual(results.holdout_gates.query_specific_truth_complete.unjudged_top_10, []);
});

test("Phase 4 blocks Phase 5 on the exact adjudicated failures", async () => {
  const [results, release] = await Promise.all([
    source("evaluation/search_v2_holdout_results.json").then(JSON.parse),
    source("evaluation/search_v2_release_candidate.json").then(JSON.parse),
  ]);
  const expected = [
    "ree_direct_anchor_recall",
    "doe_genesis_scope_recall",
    "direct_positive_precision_and_recall_at_10",
    "no_candidate_explosion",
    "no_confirmed_irrelevant_primary_admissions",
    "rich_evidence_not_buried_by_partial_or_generic_matches",
    "explanations_not_misleading",
  ];
  assert.equal(results.status, "adjudicated_release_candidate_blocked");
  assert.deepEqual(results.failed_holdout_gates, expected);
  assert.equal(results.holdout_gates.nasa_rare_earth_false_positive.pass, true);
  assert.equal(results.holdout_gates.no_candidate_explosion.failures[0].count, 213);
  assert.equal(release.status, "blocked");
  assert.equal(release.phase5_authorized, false);
  assert.equal(release.production_flag_state.search_v2_enabled, false);
  assert.deepEqual(
    release.exact_failing_gates,
    expected.map(name => `holdout:${name}`),
  );
  assert.equal(release.acceptance_gate_table.main_not_modified, "passed");
});
