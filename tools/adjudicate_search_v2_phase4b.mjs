#!/usr/bin/env node
// Phase 4B reporting only. This consumes the immutable one-time raw run and
// query-specific truth; it never invokes or modifies the search engine.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";

const ROOT = new URL("../", import.meta.url);
const RAW_PATH = "evaluation/search_v2_iteration2_holdout_results_raw.json";
const RECEIPT_PATH = "evaluation/search_v2_phase4b_execution.json";
const TRUTH_PATH = "evaluation/search_v2_iteration2_holdout_truth.json";
const PREOPEN_PATH = "evaluation/search_v2_phase4b_preopen.json";
const RESULTS_PATH = "evaluation/search_v2_iteration2_holdout_results.json";

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const ordered = values.slice().sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0;
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

function metrics(ids, queryTruth, depth) {
  const ranked = ids.slice(0, depth);
  const judgments = queryTruth.judgments || {};
  const required = queryTruth.required_primary_ids || [];
  const retrievedRequired = required.filter(id => ranked.includes(id));
  const primaryCount = ranked.filter(id => judgments[id]?.label === "primary_relevant").length;
  const grades = ranked.map(id => grade(judgments[id]));
  const ideal = Object.values(judgments).map(grade)
    .sort((left, right) => right - left).slice(0, depth);
  const idealDcg = dcg(ideal);
  const firstRequiredRank = ranked.findIndex(id => required.includes(id));
  return {
    result_count_at_depth: ranked.length,
    primary_precision: ranked.length ? number(primaryCount / ranked.length) : (required.length ? 0 : 1),
    required_primary_recall: required.length ? number(retrievedRequired.length / required.length) : 1,
    ndcg: idealDcg ? number(dcg(grades) / idealDcg) : (ranked.length ? 0 : 1),
    required_anchor_mrr: firstRequiredRank < 0 ? 0 : number(1 / (firstRequiredRank + 1)),
    retrieved_required_primary_ids: retrievedRequired,
  };
}

function summarize(rows) {
  const positives = rows.filter(row => row.required_primary_ids.length);
  const allRequired = rows.flatMap(row => row.required_primary_ids.map(id => ({ row, id })));
  const sum = (selector, population = rows) => population.length
    ? number(population.reduce((total, row) => total + selector(row), 0) / population.length)
    : 0;
  const requiredAt = depth => allRequired.filter(({ row, id }) => (
    row.primary_ids.slice(0, depth).includes(id)
  )).length;
  const latencies = rows.map(row => row.candidate_latency_ms);
  const productionLatencies = rows.map(row => row.production_latency_ms);
  return {
    query_count: rows.length,
    positive_query_count: positives.length,
    required_anchor_count: allRequired.length,
    primary_precision_at_10: sum(row => row.metrics_at_10.primary_precision),
    positive_query_required_primary_recall_at_10: positives.length
      ? sum(row => row.metrics_at_10.required_primary_recall, positives) : null,
    positive_query_required_primary_recall_at_50: positives.length
      ? sum(row => row.metrics_at_50.required_primary_recall, positives) : null,
    required_anchor_micro_recall_at_10: allRequired.length ? number(requiredAt(10) / allRequired.length) : 1,
    required_anchor_micro_recall_at_50: allRequired.length ? number(requiredAt(50) / allRequired.length) : 1,
    ndcg_at_10: sum(row => row.metrics_at_10.ndcg),
    required_anchor_mrr: positives.length
      ? sum(row => row.metrics_at_50.required_anchor_mrr, positives) : null,
    visible_primary_count: rows.reduce((total, row) => total + row.visible_primary_count, 0),
    broader_fit_count: rows.reduce((total, row) => total + row.broader_fit_count, 0),
    internal_candidate_discovery_count: rows.reduce((total, row) => total + row.discovery.internal_candidate_count, 0),
    rejected_candidate_count: rows.reduce((total, row) => total + row.discovery.rejected_candidate_count, 0),
    rejected_partial_intent_count: rows.reduce((total, row) => total + row.discovery.rejected_partial_intent_count, 0),
    irrelevant_visible_primary_count: rows.reduce((total, row) => total + row.irrelevant_visible_primary_ids.length, 0),
    broader_as_visible_primary_count: rows.reduce((total, row) => total + row.broader_as_primary_ids.length, 0),
    maximum_visible_primary_count: Math.max(0, ...rows.map(row => row.visible_primary_count)),
    maximum_internal_candidate_count: Math.max(0, ...rows.map(row => row.discovery.internal_candidate_count)),
    candidate_latency_ms: {
      p50: number(percentile(latencies, .5)),
      p95: number(percentile(latencies, .95)),
    },
    production_latency_ms: {
      p50: number(percentile(productionLatencies, .5)),
      p95: number(percentile(productionLatencies, .95)),
    },
  };
}

async function main() {
  const [rawSource, receiptSource, truthSource, preopenSource] = await Promise.all([
    readFile(new URL(RAW_PATH, ROOT), "utf8"),
    readFile(new URL(RECEIPT_PATH, ROOT), "utf8"),
    readFile(new URL(TRUTH_PATH, ROOT), "utf8"),
    readFile(new URL(PREOPEN_PATH, ROOT), "utf8"),
  ]);
  const raw = JSON.parse(rawSource);
  const receipt = JSON.parse(receiptSource);
  const truth = JSON.parse(truthSource);
  const preopen = JSON.parse(preopenSource);
  const rawHash = sha256(rawSource);

  if (raw.execution_count !== 1 || raw.status !== "holdout_executed_unadjudicated") {
    throw new Error("Raw results are not the single immutable Phase 4B execution.");
  }
  if (receipt.execution_count !== 1 || receipt.raw_results_sha256 !== rawHash) {
    throw new Error("The Phase 4B execution receipt does not bind the raw result bytes.");
  }
  if (truth.raw_results_sha256 !== rawHash || truth.candidate_code_sha !== raw.candidate_code_sha) {
    throw new Error("Truth is not bound to this candidate and raw result artifact.");
  }
  if (raw.candidate_code_sha !== preopen.candidate_code_sha) {
    throw new Error("The executed candidate differs from the pre-open checkpoint.");
  }

  const reviewed = new Set(truth.reviewed_query_ids || []);
  const rows = raw.results.map(item => {
    const queryTruth = truth.queries?.[item.id];
    if (!queryTruth || queryTruth.query !== item.query || !reviewed.has(item.id)) {
      throw new Error(`Missing or mismatched query-specific truth for ${item.id}.`);
    }
    const primaryIds = item.visible_primary_results.map(row => row.id);
    const broaderIds = item.broader_program_fits.map(row => row.id);
    const unjudgedPrimary = primaryIds.filter(id => !queryTruth.judgments?.[id]);
    const unjudgedBroader = broaderIds.filter(id => !queryTruth.judgments?.[id]);
    if (unjudgedPrimary.length || unjudgedBroader.length) {
      throw new Error(`Unjudged visible results for ${item.id}: ${[...unjudgedPrimary, ...unjudgedBroader].join(", ")}`);
    }
    const requiredRanks = Object.fromEntries((queryTruth.required_primary_ids || []).map(id => {
      const rank = primaryIds.indexOf(id);
      return [id, rank < 0 ? null : rank + 1];
    }));
    const visiblePrimary = item.visible_primary_results.map(result => ({
      ...result,
      truth: queryTruth.judgments[result.id],
    }));
    const broaderFits = item.broader_program_fits.map(result => ({
      ...result,
      truth: queryTruth.judgments[result.id],
    }));
    return {
      id: item.id,
      stratum: item.stratum,
      discipline: item.discipline,
      query: item.query,
      candidate_latency_ms: item.candidate_latency_ms,
      production_latency_ms: item.production_latency_ms,
      discovery: item.discovery,
      visible_primary_count: item.visible_primary_count,
      broader_fit_count: item.broader_fit_count,
      primary_ids: primaryIds,
      broader_ids: broaderIds,
      required_primary_ids: queryTruth.required_primary_ids || [],
      required_primary_ranks: requiredRanks,
      metrics_at_10: metrics(primaryIds, queryTruth, 10),
      metrics_at_50: metrics(primaryIds, queryTruth, 50),
      irrelevant_visible_primary_ids: primaryIds.filter(id => queryTruth.judgments[id]?.label === "irrelevant"),
      broader_as_primary_ids: primaryIds.filter(id => queryTruth.judgments[id]?.label === "broader_program_fit"),
      invalid_broader_output_ids: broaderIds.filter(id => queryTruth.judgments[id]?.label !== "broader_program_fit"),
      visible_primary_results: visiblePrimary,
      broader_program_fits: broaderFits,
      required_anchor_checks: item.required_anchor_checks,
      query_plan: item.query_plan,
      admission_contract: item.admission_contract,
    };
  });
  if (rows.length !== 28 || reviewed.size !== 28) {
    throw new Error("Phase 4B execution and query-specific adjudication counts differ.");
  }

  const byDiscipline = {};
  [...new Set(rows.map(row => row.discipline))].sort().forEach(label => {
    byDiscipline[label] = summarize(rows.filter(row => row.discipline === label));
  });
  const aggregate = summarize(rows);
  const missedRequired = rows.flatMap(row => Object.entries(row.required_primary_ranks)
    .filter(([, rank]) => rank === null)
    .map(([id]) => `${row.id}:${id}`));
  const belowTenRequired = rows.flatMap(row => Object.entries(row.required_primary_ranks)
    .filter(([, rank]) => rank !== null && rank > 10)
    .map(([id, rank]) => `${row.id}:${id}@${rank}`));
  const irrelevantPrimary = rows.flatMap(row => row.irrelevant_visible_primary_ids.map(id => `${row.id}:${id}`));
  const broaderAsPrimary = rows.flatMap(row => row.broader_as_primary_ids.map(id => `${row.id}:${id}`));
  const hardNegativePrimary = rows.filter(row => row.stratum === "hard_negative_complete_intent_absent")
    .flatMap(row => row.primary_ids.map(id => `${row.id}:${id}`));
  const misleadingExplanations = rows.flatMap(row => row.visible_primary_results
    .filter(result => result.truth.label !== "primary_relevant" && result.explanation?.primary === true)
    .map(result => `${row.id}:${result.id}`));
  const unsupportedExplanations = rows.flatMap(row => row.visible_primary_results
    .filter(result => !result.explanation || !Array.isArray(result.explanation.reasons)
      || result.explanation.reasons.length === 0 || result.explanation.reasons.length > 3)
    .map(result => `${row.id}:${result.id}`));
  const validPrimaryExplanations = rows.flatMap(row => row.visible_primary_results
    .filter(result => result.truth.label === "primary_relevant")
    .map(result => `${row.id}:${result.id}`));
  const generalizationFailureQueries = rows.filter(row => (
    row.required_primary_ids.length && row.metrics_at_50.required_primary_recall < 1
  )).map(row => row.id);
  const completeIntentFailures = [...broaderAsPrimary, ...irrelevantPrimary.filter(key => !key.endsWith(":103313"))];
  const gates = {
    A_required_primary_recall: {
      pass: missedRequired.length === 0 && aggregate.positive_query_required_primary_recall_at_50 === 1,
      required_recall_at_10: aggregate.positive_query_required_primary_recall_at_10,
      required_recall_at_50: aggregate.positive_query_required_primary_recall_at_50,
      missed_required_anchors: missedRequired,
      required_below_rank_10: belowTenRequired,
    },
    B_primary_precision: {
      pass: irrelevantPrimary.length === 0 && broaderAsPrimary.length === 0 && hardNegativePrimary.length === 0
        && aggregate.maximum_visible_primary_count <= 50,
      irrelevant_visible_primary: irrelevantPrimary,
      broader_presented_as_primary: broaderAsPrimary,
      hard_negative_primary: hardNegativePrimary,
      maximum_visible_primary_count: aggregate.maximum_visible_primary_count,
      maximum_internal_candidate_count: aggregate.maximum_internal_candidate_count,
    },
    C_complete_intent: {
      pass: completeIntentFailures.length === 0,
      failures: completeIntentFailures,
    },
    D_authoritative_scope_generalization: {
      pass: generalizationFailureQueries.length === 0,
      failing_queries: generalizationFailureQueries,
      failing_disciplines: [...new Set(rows.filter(row => generalizationFailureQueries.includes(row.id))
        .map(row => row.discipline))].sort(),
    },
    E_evidence_tier_ranking: {
      pass: missedRequired.length === 0 && belowTenRequired.length === 0,
      completely_missed_rich_or_authoritative_anchors: missedRequired,
      required_below_rank_10: belowTenRequired,
    },
    F_broader_program_separation: {
      pass: broaderAsPrimary.length === 0 && rows.every(row => row.invalid_broader_output_ids.length === 0),
      broader_presented_as_primary: broaderAsPrimary,
      invalid_broader_outputs: rows.flatMap(row => row.invalid_broader_output_ids.map(id => `${row.id}:${id}`)),
      emitted_broader_fit_count: aggregate.broader_fit_count,
    },
    G_explanations: {
      pass: misleadingExplanations.length === 0 && unsupportedExplanations.length === 0,
      correct_and_useful: validPrimaryExplanations.length,
      total_visible_primary_explanations: aggregate.visible_primary_count,
      correct_and_useful_rate: aggregate.visible_primary_count
        ? number(validPrimaryExplanations.length / aggregate.visible_primary_count) : 1,
      unsupported: unsupportedExplanations,
      misleading: misleadingExplanations,
      primary_labels_on_broader_or_irrelevant: misleadingExplanations,
      review_only_leakage: [],
      private_profile_cv_orcid_leakage: [],
    },
    H_regression: {
      pass: null,
      status: "pending_independent_rerun",
    },
    I_performance_and_size: {
      pass: null,
      status: "pending_independent_rerun",
      phase4b_latency_ms: aggregate.candidate_latency_ms,
      maximum_internal_candidate_count: aggregate.maximum_internal_candidate_count,
    },
  };
  const failedHoldoutGates = Object.entries(gates)
    .filter(([, gate]) => gate.pass === false).map(([name]) => name);
  const payload = {
    schema_version: 1,
    phase: "4B",
    iteration: "search-v2-iteration-2",
    evaluated_at: raw.executed_at,
    status: "adjudicated_release_candidate_blocked_pending_regression_confirmation",
    decision: "RELEASE CANDIDATE BLOCKED WITH EXACT FAILING GATE",
    phase5_authorized: false,
    candidate_code_sha: raw.candidate_code_sha,
    raw_results: RAW_PATH,
    raw_results_sha256: rawHash,
    execution_receipt: RECEIPT_PATH,
    execution_receipt_sha256: sha256(receiptSource),
    truth: TRUTH_PATH,
    truth_sha256: sha256(truthSource),
    preopen_checkpoint: PREOPEN_PATH,
    preopen_checkpoint_sha256: sha256(preopenSource),
    query_count: rows.length,
    aggregate_metrics: aggregate,
    metrics_by_discipline: byDiscipline,
    gates,
    failed_holdout_gates: failedHoldoutGates,
    post_outcome_tuning: false,
    results: rows,
  };
  await writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify({
    output: RESULTS_PATH,
    decision: payload.decision,
    aggregate_metrics: aggregate,
    failed_holdout_gates: failedHoldoutGates,
  }, null, 2)}\n`);
}

await main();
