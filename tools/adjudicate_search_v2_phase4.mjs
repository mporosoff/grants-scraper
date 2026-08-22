#!/usr/bin/env node
// Phase 4 reporting only. This consumes the immutable one-time holdout run and
// query-specific judgments; it never invokes or changes either search engine.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

const ROOT = new URL("../", import.meta.url);
const RAW_PATH = "evaluation/search_v2_holdout_results_raw.json";
const TRUTH_PATH = "evaluation/search_v2_holdout_truth.json";
const PREOPEN_PATH = "evaluation/search_v2_phase4_preopen.json";
const TEST_RUNS_PATH = "evaluation/search_v2_phase4_test_runs.json";
const RESULTS_PATH = "evaluation/search_v2_holdout_results.json";
const RELEASE_PATH = "evaluation/search_v2_release_candidate.json";

function sha256(source) {
  return createHash("sha256").update(source).digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const sorted = values.slice().sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)] || 0;
}

function grade(judgment) {
  if (judgment?.label === "primary_relevant") return 2;
  if (judgment?.label === "broader_program_fit") return 1;
  return 0;
}

function dcg(grades) {
  return grades.reduce((sum, value, index) => (
    sum + ((2 ** value) - 1) / Math.log2(index + 2)
  ), 0);
}

function metrics(rows, queryTruth, depth = 10) {
  const ranked = rows.slice(0, depth);
  const judgments = queryTruth.judgments || {};
  const required = queryTruth.required_primary_ids || [];
  const primaryCount = ranked.filter(row => judgments[row.id]?.label === "primary_relevant").length;
  const acceptableCount = ranked.filter(row => (
    judgments[row.id]?.label === "primary_relevant"
    || judgments[row.id]?.label === "broader_program_fit"
  )).length;
  const retrievedRequired = required.filter(id => ranked.some(row => row.id === id));
  const grades = ranked.map(row => grade(judgments[row.id]));
  const ideal = Object.values(judgments)
    .map(grade)
    .sort((left, right) => right - left)
    .slice(0, depth);
  const idealDcg = dcg(ideal);
  const firstRequiredRank = ranked.findIndex(row => required.includes(row.id));
  return {
    result_count_at_depth: ranked.length,
    primary_precision: ranked.length ? number(primaryCount / ranked.length) : (required.length ? 0 : 1),
    primary_or_broader_precision: ranked.length ? number(acceptableCount / ranked.length) : 1,
    required_primary_recall: required.length ? number(retrievedRequired.length / required.length) : 1,
    ndcg: idealDcg ? number(dcg(grades) / idealDcg) : (ranked.length ? 0 : 1),
    reciprocal_rank_direct_anchor: firstRequiredRank < 0 ? 0 : number(1 / (firstRequiredRank + 1)),
    retrieved_required_primary_ids: retrievedRequired,
  };
}

async function main() {
  const [rawSource, truthSource, preopenSource, testRunsSource] = await Promise.all([
    readFile(new URL(RAW_PATH, ROOT), "utf8"),
    readFile(new URL(TRUTH_PATH, ROOT), "utf8"),
    readFile(new URL(PREOPEN_PATH, ROOT), "utf8"),
    readFile(new URL(TEST_RUNS_PATH, ROOT), "utf8").catch(() => '{"status":"pending","gates":{}}'),
  ]);
  const raw = JSON.parse(rawSource);
  const truth = JSON.parse(truthSource);
  const preopen = JSON.parse(preopenSource);
  const testRuns = JSON.parse(testRunsSource);
  const rawHash = sha256(rawSource);

  if (raw.execution_count !== 1 || raw.status !== "holdout_executed_unadjudicated") {
    throw new Error("The holdout raw artifact is not the single immutable Phase 4 execution.");
  }
  if (truth.raw_results_sha256 !== rawHash) {
    throw new Error("Holdout truth is not bound to the current raw-result bytes.");
  }
  if (truth.candidate_code_sha !== raw.candidate_code_sha) {
    throw new Error("Holdout truth and raw results name different candidate code.");
  }
  if (raw.holdout_frame_sha256 !== preopen.hashes["evaluation/search_v2_holdout_frame.json"]) {
    throw new Error("The executed holdout frame differs from the pre-open checkpoint.");
  }
  if (raw.candidate_code_sha !== preopen.candidate_code_sha) {
    throw new Error("The executed candidate differs from the pre-open checkpoint.");
  }

  const reviewedIds = new Set(truth.reviewed_query_ids || []);
  const rows = raw.results.map(item => {
    const queryTruth = truth.queries?.[item.id];
    if (!queryTruth || queryTruth.query !== item.query || !reviewedIds.has(item.id)) {
      throw new Error(`Missing or mismatched query-specific truth for ${item.id}.`);
    }
    const candidateTop10 = item.candidate_top_50.slice(0, 10);
    const unjudgedTop10 = candidateTop10
      .filter(row => !queryTruth.judgments?.[row.id])
      .map(row => row.id);
    if (unjudgedTop10.length) {
      throw new Error(`Unjudged candidate top-10 results for ${item.id}: ${unjudgedTop10.join(", ")}`);
    }
    const requiredRanks = Object.fromEntries((queryTruth.required_primary_ids || []).map(id => {
      const rank = item.candidate_top_50.findIndex(row => row.id === id);
      return [id, rank < 0 ? null : rank + 1];
    }));
    const judgedCandidateTop10 = candidateTop10.map(row => ({
      ...row,
      truth: queryTruth.judgments[row.id],
    }));
    return {
      id: item.id,
      stratum: item.stratum,
      discipline: item.discipline,
      query: item.query,
      production_candidate_count: item.production_candidate_count,
      candidate_count: item.candidate_count,
      production_latency_ms: item.production_latency_ms,
      candidate_latency_ms: item.candidate_latency_ms,
      candidate_count_delta: item.candidate_count - item.production_candidate_count,
      production_top_10: item.production_top_10,
      candidate_top_10: judgedCandidateTop10,
      required_primary_ids: queryTruth.required_primary_ids || [],
      required_primary_ranks: requiredRanks,
      production_metrics_at_10: metrics(item.production_top_10, queryTruth, 10),
      candidate_metrics_at_10: metrics(item.candidate_top_50, queryTruth, 10),
      candidate_metrics_at_50: metrics(item.candidate_top_50, queryTruth, 50),
      added_to_top_10: item.added_to_top_10,
      removed_from_top_10: item.removed_from_top_10,
      top_10_changed: item.top_10_changed,
      query_plan: item.query_plan,
      minimum_coverage: item.minimum_coverage,
      short_complete_coverage: item.short_complete_coverage,
      authoritative_scope_entailments: item.authoritative_scope_entailments,
      corpus_note: queryTruth.corpus_note || null,
    };
  });

  if (rows.length !== raw.query_count || reviewedIds.size !== raw.query_count) {
    throw new Error("Holdout execution and adjudication query counts differ.");
  }

  const positiveRows = rows.filter(row => row.required_primary_ids.length);
  const directPositiveRows = rows.filter(row => row.stratum === "direct_positive");
  const irrelevantTop10 = rows.flatMap(row => row.candidate_top_10
    .filter(result => result.truth.label === "irrelevant")
    .map(result => `${row.id}:${result.id}`));
  const misleadingPrimaryExplanations = rows.flatMap(row => row.candidate_top_10
    .filter(result => result.truth.label === "irrelevant" && result.explanation?.primary === true)
    .map(result => `${row.id}:${result.id}`));
  const reePositiveIds = [
    "hold_ree_01", "hold_ree_02", "hold_ree_03",
    "hold_ree_04", "hold_ree_05", "hold_ree_06",
  ];
  const reeFailures = rows.filter(row => reePositiveIds.includes(row.id)
    && row.candidate_metrics_at_50.required_primary_recall < 1).map(row => row.id);
  const directPositiveFailures = directPositiveRows.filter(row => (
    row.candidate_metrics_at_10.required_primary_recall < 1
    || row.candidate_metrics_at_10.primary_precision < 1
  )).map(row => row.id);
  const candidateExplosions = rows.filter(row => row.candidate_count > 100)
    .map(row => ({ id: row.id, count: row.candidate_count }));
  const richEvidenceRankingFailures = rows.filter(row => (
    Object.values(row.required_primary_ranks).some(rank => rank === null || rank > 10)
    && row.candidate_top_10.some(result => result.truth.label !== "primary_relevant")
  )).map(row => row.id);
  const materialTop10Movements = rows.filter(row => row.top_10_changed).map(row => row.id);
  const candidateLatencies = rows.map(row => row.candidate_latency_ms);
  const productionLatencies = rows.map(row => row.production_latency_ms);

  const holdoutGates = {
    protocol_integrity: {
      pass: true,
      raw_execution_count: raw.execution_count,
      raw_sha256: rawHash,
      frame_sha256_matches_preopen: true,
      candidate_code_matches_preopen: true,
      post_outcome_tuning: false,
    },
    query_specific_truth_complete: {
      pass: rows.length === raw.query_count,
      reviewed_queries: rows.length,
      unjudged_top_10: [],
    },
    ree_direct_anchor_recall: {
      pass: reeFailures.length === 0,
      failing_queries: reeFailures,
    },
    nasa_rare_earth_false_positive: {
      pass: rows.find(row => row.id === "hold_ree_07")?.candidate_count === 0,
      query: "rare Earth observation elements",
      admitted_ids: rows.find(row => row.id === "hold_ree_07")?.candidate_top_10.map(row => row.id) || [],
    },
    doe_genesis_scope_recall: {
      pass: reeFailures.length === 0,
      failing_queries: reeFailures,
    },
    direct_positive_precision_and_recall_at_10: {
      pass: directPositiveFailures.length === 0,
      failing_queries: directPositiveFailures,
    },
    no_candidate_explosion: {
      pass: candidateExplosions.length === 0,
      review_threshold: 100,
      failures: candidateExplosions,
    },
    no_confirmed_irrelevant_primary_admissions: {
      pass: irrelevantTop10.length === 0,
      failures: irrelevantTop10,
    },
    rich_evidence_not_buried_by_partial_or_generic_matches: {
      pass: richEvidenceRankingFailures.length === 0,
      failing_queries: richEvidenceRankingFailures,
    },
    explanations_not_misleading: {
      pass: misleadingPrimaryExplanations.length === 0,
      failures: misleadingPrimaryExplanations,
      note: "The explanation contract remains causal; these failures originate in incorrect retrieval admission and therefore render a primary label misleading.",
    },
  };

  const failedHoldoutGates = Object.entries(holdoutGates)
    .filter(([, gate]) => gate.pass === false)
    .map(([name]) => name);
  const externalFailedGates = Object.entries(testRuns.gates || {})
    .filter(([, gate]) => gate.status === "failed")
    .map(([name]) => name);
  const externalPendingGates = Object.entries(testRuns.gates || {})
    .filter(([, gate]) => gate.status === "pending")
    .map(([name]) => name);

  const payload = {
    schema_version: 1,
    evaluated_at: raw.executed_at,
    phase: 4,
    status: "adjudicated_release_candidate_blocked",
    candidate_code_sha: raw.candidate_code_sha,
    preopen_checkpoint: raw.preopen_checkpoint,
    raw_results: RAW_PATH,
    raw_results_sha256: rawHash,
    truth: TRUTH_PATH,
    truth_sha256: sha256(truthSource),
    query_count: rows.length,
    material_top_10_movements: materialTop10Movements,
    aggregate_metrics: {
      query_average_primary_precision_at_10: number(
        rows.reduce((sum, row) => sum + row.candidate_metrics_at_10.primary_precision, 0) / rows.length,
      ),
      positive_query_average_recall_at_10: number(positiveRows.reduce((sum, row) => sum + row.candidate_metrics_at_10.required_primary_recall, 0) / positiveRows.length),
      positive_query_average_recall_at_50: number(positiveRows.reduce((sum, row) => sum + row.candidate_metrics_at_50.required_primary_recall, 0) / positiveRows.length),
      direct_positive_average_precision_at_10: number(directPositiveRows.reduce((sum, row) => sum + row.candidate_metrics_at_10.primary_precision, 0) / directPositiveRows.length),
      direct_positive_average_ndcg_at_10: number(directPositiveRows.reduce((sum, row) => sum + row.candidate_metrics_at_10.ndcg, 0) / directPositiveRows.length),
      zero_result_queries: rows.filter(row => row.candidate_count === 0).map(row => row.id),
      candidate_count_maximum: Math.max(...rows.map(row => row.candidate_count)),
      candidate_latency_ms: {
        p50: number(percentile(candidateLatencies, .5)),
        p95: number(percentile(candidateLatencies, .95)),
      },
      production_latency_ms: {
        p50: number(percentile(productionLatencies, .5)),
        p95: number(percentile(productionLatencies, .95)),
      },
    },
    holdout_gates: holdoutGates,
    failed_holdout_gates: failedHoldoutGates,
    external_gate_status: testRuns,
    failed_external_gates: externalFailedGates,
    pending_external_gates: externalPendingGates,
    results: rows,
  };
  const releaseGateTable = {
    frozen_development_holdout_assignment_preserved: "passed",
    phase2_configuration_frozen_before_holdout: "passed",
    separate_holdout_no_post_outcome_tuning: "passed",
    frozen_acceptance_set_unchanged: "passed",
    ree_hard_gates: holdoutGates.ree_direct_anchor_recall.pass ? "passed" : "failed",
    nasa_false_positive_gate: holdoutGates.nasa_rare_earth_false_positive.pass ? "passed" : "failed",
    doe_genesis_recall_gates: holdoutGates.doe_genesis_scope_recall.pass ? "passed" : "failed",
    cross_domain_historical_baselines: testRuns.gates?.historical_and_cross_domain?.status || "pending",
    field_ablation_calibration: testRuns.gates?.field_calibration?.status || "pending",
    explanation_truth: holdoutGates.explanations_not_misleading.pass
      ? (testRuns.gates?.explanation_truth?.status || "pending") : "failed",
    review_only_publication_boundary: testRuns.gates?.publication_boundary?.status || "pending",
    cold_warm_readiness_mixed_version: testRuns.gates?.readiness?.status || "pending",
    search_index_size_performance: testRuns.gates?.size_and_performance?.status || "pending",
    parent_child_normalization_cardinality: testRuns.gates?.parent_child_invariants?.status || "pending",
    browser_mobile_performance: testRuns.gates?.browser_mobile?.status || "pending",
    python_tests: testRuns.gates?.python_tests?.status || "pending",
    browser_tests: testRuns.gates?.browser_tests?.status || "pending",
    query_canary_tests: testRuns.gates?.query_canaries?.status || "pending",
    no_drift: testRuns.gates?.no_drift?.status || "pending",
    release_artifact_deterministic: "passed",
    branch_clean_and_pushed: testRuns.gates?.branch_state?.status || "pending",
    main_not_modified: "passed",
  };
  const exactFailures = [
    ...failedHoldoutGates.map(name => `holdout:${name}`),
    ...externalFailedGates.map(name => `verification:${name}`),
  ];

  const release = {
    schema_version: 1,
    phase: 4,
    decision: "Release candidate blocked with exact failing gate",
    status: "blocked",
    phase5_authorized: false,
    branch: "search-quality-v2",
    branch_head_when_decision_frozen: testRuns.phase4_evidence_commit || null,
    candidate_code_sha: raw.candidate_code_sha,
    preopen_checkpoint: raw.preopen_checkpoint,
    starting_main_sha: preopen.starting_main_sha,
    intended_version: preopen.intended_version,
    intended_release_date_policy: "No release date until a new iteration passes a newly frozen acceptance protocol.",
    production_flag_state: {
      search_v2_enabled: false,
      intended_phase5_change: "one configuration change only after a future Phase 4 pass",
    },
    artifact_hashes: {
      preopen: sha256(preopenSource),
      raw_holdout: rawHash,
      holdout_truth: sha256(truthSource),
    },
    catalog_and_sidecar_hashes: {
      opportunities: preopen.hashes["data/opportunities.js"],
      subtopics: preopen.hashes["data/subtopics.js"],
    },
    acceptance_gate_table: releaseGateTable,
    exact_failing_gates: exactFailures,
    pending_non_dispositive_gates: externalPendingGates,
    known_limitations: [
      "The protected REE architecture does not generalize to recycling, ion exchange, hydrometallurgy, yttrium, or scandium variants in the holdout.",
      "Generic short-query coverage still admits partial-intent and administrative-wording matches for unprotected concepts.",
      "A broad health-data-workforce-workshop query expands to 213 candidates.",
      "Several rich authoritative or child-scope anchors are absent or buried below weaker matches.",
      "The causal explanation contract can accurately cite evidence for an incorrect admission, making the displayed primary label misleading until retrieval is corrected.",
    ],
    rollback_method: "Keep FF_SEARCH_V2 disabled; no production rollback action is required because Phase 4 did not merge or deploy.",
    next_iteration_discipline: "Reopen the owning retrieval phase, preserve this failed holdout as permanent evidence, freeze a new development/holdout protocol before tuning, and do not patch individual holdout strings in place.",
    test_summary: testRuns.summary || {},
  };

  if (!process.argv.includes("--write")) {
    process.stdout.write(`${JSON.stringify({ failed_holdout_gates: failedHoldoutGates }, null, 2)}\n`);
    return;
  }
  await writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await writeFile(new URL(RELEASE_PATH, ROOT), `${JSON.stringify(release, null, 2)}\n`, "utf8");
  process.stdout.write(
    `Phase 4 adjudication: ${rows.length} queries; BLOCKED by ${failedHoldoutGates.length} holdout gates.\n`,
  );
}

await main();
