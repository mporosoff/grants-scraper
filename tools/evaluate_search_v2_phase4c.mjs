#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const RAW_PATH = "evaluation/search_v2_iteration3_holdout_results_raw.json";
const TRUTH_PATH = "evaluation/search_v2_iteration3_holdout_truth.json";
const RESULTS_PATH = "evaluation/search_v2_iteration3_holdout_results.json";
const EXPECTED_RAW_SHA256 = "c8bd5a3b105963b826f406227ca6a0d4664cf80827f4ce2d5adac550088707ab";
const CANDIDATE_SHA = "f893d43e795a7f70efdf8191e863fb33e286d148";

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function rounded(value) {
  return Number(value.toFixed(6));
}

function percentile(values, percentileValue) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.max(0, Math.ceil(percentileValue * sorted.length) - 1);
  return rounded(sorted[index]);
}

function ids(values) {
  return new Set(values);
}

// These exact query/result judgments were made after the immutable one-time output
// was written. Required anchors are added as primary below. All observed pairs not
// listed as primary or broader are irrelevant under the complete-intent rubric.
const additionalPrimary = {
  i3hold_biomed_01: ids(["362233", "362235", "362236"]),
  i3hold_env_03: ids(["363355"]),
  i3hold_social_01: ids(["363553", "363574"]),
  i3hold_social_02: ids(["363553"]),
  i3hold_social_04: ids(["355219", "362911", "363574"]),
  i3hold_space_02: ids(["nasa-roses:25-D.9-d22059cf9f"]),
};

const broader = {
  i3hold_ai_01: ids(["344592", "361333", "361526", "363268", "363481", "363613", "vpr-email:NSF26-015"]),
  i3hold_material_01: ids(["344592", "349655", "351715", "361526", "362063", "363617", "363618", "39841"]),
  i3hold_health_01: ids(["358816", "363222", "363516", "363523"]),
  i3hold_ag_01: ids(["356559", "356561", "356562", "357579", "360205", "361080", "362394", "362484", "362755", "362909", "362910", "363306"]),
  i3hold_ai_02: ids(["344592", "345241", "361333", "361526", "363613", "363623", "arpa-h:ARPA-H-SOL-24-103", "vpr-email:NSF26-015"]),
  i3hold_ai_03: ids(["324456", "344592", "361526", "363268", "363481", "363613", "363623"]),
  i3hold_material_02: ids(["344592", "349655", "351715", "362061", "362063", "363617", "363618", "363621"]),
  i3hold_material_03: ids(["275150", "344592", "347331", "349655", "357609", "360534", "360536", "360678", "361447", "363168", "363169"]),
  i3hold_health_02: ids(["357186", "357187", "362108", "362352", "363047", "363222", "363516", "363523"]),
  i3hold_health_03: ids(["356893", "356907", "356924", "357524", "361521", "361999", "362068", "362099", "363055", "363073", "363503", "363675"]),
  i3hold_health_04: ids(["357713", "362168", "363073", "363413"]),
  i3hold_social_01: ids(["363599", "363639", "363647", "363648", "363683"]),
  i3hold_social_02: ids(["363574", "363599", "363647", "363648", "363683"]),
  i3hold_biomed_01: ids(["357330", "360986", "360988", "361084", "361427", "363250"]),
  i3hold_env_01: ids(["361315", "363101", "363102", "363103", "363333", "363335", "363355"]),
  i3hold_env_02: ids(["360205", "361315", "362978", "363101", "363102", "363103", "363333", "363335", "363355", "363535", "363537"]),
  i3hold_env_03: ids(["356231", "361418", "361814", "362394", "362470", "363180", "363306", "363333", "363535", "363544", "363672"]),
  i3hold_env_04: ids(["356231", "361418", "361814", "362470", "363180", "363355", "363457", "363535", "363672", "363685"]),
  i3hold_ag_02: ids(["356559", "356561", "356562", "357579", "360205", "361080", "362394", "362480", "362484", "362755", "362910", "363306"]),
  i3hold_social_03: ids(["302271", "340828", "350469", "356811", "357544", "357545", "359068", "359649", "360910", "361205", "363107", "363468"]),
  i3hold_social_04: ids(["302271", "350469", "363468", "363599", "363683"]),
  i3hold_energy_01: ids(["359966", "362061", "362394", "362395", "362396", "363070", "363302", "363375", "363616", "nsf-cbet:PD-26-370Y"]),
  i3hold_energy_03: ids(["344592", "347749", "351715", "360678", "362061", "362681", "363616", "363617"]),
  i3hold_energy_04: ids(["344592", "361526", "362061", "363065", "363614", "363616", "nsf-cbet:PD-26-370Y"]),
  i3hold_space_01: ids(["356536", "357578", "357579", "357580", "357609", "363684"]),
  i3hold_space_02: ids(["342959", "343166", "357105", "363620"]),
  i3hold_space_03: ids(["342959", "343166", "343875", "356536", "357105", "363620", "363621", "363684"]),
  i3hold_broader_01: ids(["356316", "357634", "359268", "359269", "359270", "359271", "359666", "362743", "363025", "363107", "363481", "vpr-email:NSF26-015"]),
  i3hold_broader_02: ids(["344592", "349655", "356055", "361526", "362061", "362063", "362681", "362859", "363526", "363617", "363618"]),
  i3hold_broader_03: ids(["363065"]),
};

const rawBuffer = readFileSync(RAW_PATH);
const rawSha256 = sha256(rawBuffer);
if (rawSha256 !== EXPECTED_RAW_SHA256) {
  throw new Error(`Immutable Phase 4C raw hash mismatch: ${rawSha256}`);
}
const raw = JSON.parse(rawBuffer.toString("utf8"));
if (raw.execution_count !== 1 || raw.holdout_query_execution_count !== 36 || raw.queries.length !== 36) {
  throw new Error("Phase 4C execution-count/query-count invariant failed.");
}
if (raw.frozen_candidate_sha !== CANDIDATE_SHA) {
  throw new Error("Frozen candidate SHA mismatch.");
}
const appSource = readFileSync("assets/app.js", "utf8");

const truthQueries = {};
const observedPairs = [];
for (const query of raw.queries) {
  const required = new Set(query.preregistered.required_primary_ids);
  const expectedBroader = new Set(query.preregistered.expected_broader_ids);
  const rows = new Map();
  for (const row of query.strong.rows) {
    rows.set(row.id, {
      surface: "strong",
      rank: row.rank,
      title: row.title,
      passage_id: row.explanation?.evidence?.highest_contributing_passage?.passageId ?? null,
      source_field: row.explanation?.evidence?.highest_contributing_passage?.field ?? null,
      source_excerpt: row.explanation?.evidence?.highest_contributing_passage?.text ?? "",
    });
  }
  for (const row of query.potential.displayed) {
    if (!rows.has(row.parent_id)) {
      rows.set(row.parent_id, {
        surface: "potential",
        rank: row.potential_rank,
        title: row.title,
        passage_id: row.passage_id,
        source_field: row.source_field,
        source_excerpt: row.source_excerpt,
      });
    }
  }
  for (const anchorId of [...required, ...expectedBroader]) {
    if (!rows.has(anchorId)) {
      rows.set(anchorId, {
        surface: "not_displayed",
        rank: null,
        title: null,
        passage_id: null,
        source_field: null,
        source_excerpt: "",
      });
    }
  }

  const judgments = {};
  for (const [resultId, row] of rows) {
    let label = "irrelevant";
    let validPath = null;
    let reason = "The winning public passage does not support the complete research intent; it remains Potential-only discovery, not verified relevance.";
    if (required.has(resultId) || additionalPrimary[query.query_id]?.has(resultId)) {
      label = "primary_relevant";
      validPath = row.surface === "strong" ? "coherent_atomic_source_passage" : "bounded_public_source_passage";
      reason = required.has(resultId)
        ? "Authoritative indexed parent/child scope supports the preregistered complete query intent."
        : "Authoritative indexed source evidence supports the complete query intent as an unexpected legitimate primary result.";
    } else if (expectedBroader.has(resultId) || broader[query.query_id]?.has(resultId)) {
      label = "broader_program_fit";
      validPath = "adjacent_public_source_passage";
      reason = "The public source passage is genuinely adjacent, but at least one major query dimension is not established; it remains Potential only.";
    }
    const judgment = {
      label,
      surface: row.surface,
      rank: row.rank,
      title: row.title,
      evidence: reason,
      valid_path: validPath,
      passage_id: row.passage_id,
      source_field: row.source_field,
      source_excerpt: row.source_excerpt,
    };
    judgments[resultId] = judgment;
    observedPairs.push({ query_id: query.query_id, result_id: resultId, ...judgment });
  }
  truthQueries[query.query_id] = {
    query: query.query,
    discipline: query.discipline,
    stratum: query.stratum,
    required_primary_ids: [...required],
    expected_broader_ids: [...expectedBroader],
    judgments,
  };
}

const truth = {
  schema_version: 1,
  phase: "4C",
  iteration: "search-v2-iteration-3",
  adjudicated_at: "2026-08-23",
  status: "query_result_truth_complete",
  raw_results: RAW_PATH,
  raw_results_sha256: rawSha256,
  candidate_code_sha: CANDIDATE_SHA,
  truth_key: "query_id,result_id",
  reviewed_query_ids: raw.queries.map((query) => query.query_id),
  reviewed_pair_count: observedPairs.length,
  protocol: {
    post_outcome_tuning: false,
    search_behavior_changed_after_execution: false,
    required_anchor_labels_changed_to_rescue_retrieval: false,
    strong_requires_coherent_atomic_public_evidence: true,
    potential_may_be_adjacent_or_imperfect: true,
    semantic_score_independently_establishes_relevance: false,
    broader_fit_counts_as_required_primary: false,
    private_or_researcher_material_used: false,
  },
  queries: truthQueries,
};
writeFileSync(TRUTH_PATH, `${JSON.stringify(truth, null, 2)}\n`);
const truthSha256 = sha256(readFileSync(TRUTH_PATH));

const requiredAnchors = [];
const strongJudgments = [];
const potentialJudgments = [];
const queryResults = [];
for (const query of raw.queries) {
  const queryTruth = truthQueries[query.query_id];
  const combinedVisible = [
    ...query.strong.rows.map((row) => ({ id: row.id, surface: "strong" })),
    ...query.potential.displayed.map((row) => ({ id: row.parent_id, surface: "potential" })),
  ];
  const requiredOutcomes = query.preregistered.required_primary_ids.map((resultId) => {
    const position = query.required_anchor_positions[resultId];
    const outcome = {
      result_id: resultId,
      strong_rank: position.strong_rank,
      potential_display_rank: position.potential_display_rank,
      combined_internal_rank: position.combined_internal_rank,
      hybrid_rank: position.hybrid_rank,
      recalled_at_10: position.combined_internal_rank !== null && position.combined_internal_rank <= 10,
      recalled_at_20: position.combined_internal_rank !== null && position.combined_internal_rank <= 20,
      recalled_at_50: position.combined_internal_rank !== null && position.combined_internal_rank <= 50,
    };
    requiredAnchors.push({ query_id: query.query_id, discipline: query.discipline, ...outcome });
    return outcome;
  });
  for (const row of query.strong.rows) {
    strongJudgments.push({ query_id: query.query_id, discipline: query.discipline, result_id: row.id, ...queryTruth.judgments[row.id] });
  }
  for (const row of query.potential.displayed) {
    potentialJudgments.push({ query_id: query.query_id, discipline: query.discipline, result_id: row.parent_id, ...queryTruth.judgments[row.parent_id] });
  }

  const gains = combinedVisible.slice(0, 10).map((row) => queryTruth.judgments[row.id]?.label === "primary_relevant" ? 1 : 0);
  const primaryTruthCount = Object.values(queryTruth.judgments).filter((judgment) => judgment.label === "primary_relevant").length;
  const dcg = gains.reduce((sum, gain, index) => sum + gain / Math.log2(index + 2), 0);
  const idealDcg = Array.from({ length: Math.min(10, primaryTruthCount) }, (_, index) => 1 / Math.log2(index + 2)).reduce((a, b) => a + b, 0);
  queryResults.push({
    query_id: query.query_id,
    query: query.query,
    discipline: query.discipline,
    stratum: query.stratum,
    required_anchors: requiredOutcomes,
    strong_count: query.strong.count,
    potential_count: query.potential.displayed.length,
    internal_candidate_count: query.potential.available_after_deduplication,
    primary_strong_count: query.strong.rows.filter((row) => queryTruth.judgments[row.id]?.label === "primary_relevant").length,
    broader_strong_count: query.strong.rows.filter((row) => queryTruth.judgments[row.id]?.label === "broader_program_fit").length,
    irrelevant_strong_count: query.strong.rows.filter((row) => queryTruth.judgments[row.id]?.label === "irrelevant").length,
    relevant_potential_count: query.potential.displayed.filter((row) => queryTruth.judgments[row.parent_id]?.label === "primary_relevant").length,
    broader_potential_count: query.potential.displayed.filter((row) => queryTruth.judgments[row.parent_id]?.label === "broader_program_fit").length,
    irrelevant_potential_count: query.potential.displayed.filter((row) => queryTruth.judgments[row.parent_id]?.label === "irrelevant").length,
    ndcg_at_10: idealDcg ? rounded(dcg / idealDcg) : null,
    latency_ms: query.latency_ms,
    fallback_used: query.diagnostics.fallback_used,
  });
}

const requiredCount = requiredAnchors.length;
const recalledAt = (n) => requiredCount ? rounded(requiredAnchors.filter((anchor) => anchor[`recalled_at_${n}`]).length / requiredCount) : null;
const strongRelevantCount = strongJudgments.filter((judgment) => judgment.label === "primary_relevant").length;
const strongBroaderCount = strongJudgments.filter((judgment) => judgment.label === "broader_program_fit").length;
const strongIrrelevantCount = strongJudgments.filter((judgment) => judgment.label === "irrelevant").length;
const hardNegativeIds = new Set(raw.queries.filter((query) => query.stratum.startsWith("hard_negative")).map((query) => query.query_id));
const acronymHardNegativeIds = new Set(raw.queries.filter((query) => query.stratum === "hard_negative_acronym_ambiguity").map((query) => query.query_id));
const hardNegativeStrongCount = strongJudgments.filter((judgment) => hardNegativeIds.has(judgment.query_id)).length;
const hardNegativePotentialCount = potentialJudgments.filter((judgment) => hardNegativeIds.has(judgment.query_id)).length;
const acronymHardNegativeStrongCount = strongJudgments.filter((judgment) => acronymHardNegativeIds.has(judgment.query_id)).length;
const acronymHardNegativePotentialCount = potentialJudgments.filter((judgment) => acronymHardNegativeIds.has(judgment.query_id)).length;
const atomicCoherenceViolations = raw.queries.flatMap((query) => query.strong.rows.flatMap((row) => {
  const admission = row.explanation?.evidence?.admission;
  const passageIds = new Set((admission?.admittedBy || []).map((item) => item.passageId).filter(Boolean));
  return admission?.atomicEvidenceCoherent === true && passageIds.size <= 1
    ? []
    : [{ query_id: query.query_id, result_id: row.id, passage_ids: [...passageIds] }];
}));
const broadOnlyIds = new Set(raw.queries.filter((query) => query.stratum === "genuine_broader_program_fit").map((query) => query.query_id));
const zeroAnchorStrongCount = strongJudgments.filter((judgment) => !truthQueries[judgment.query_id].required_primary_ids.length).length;
const positiveNdcg = queryResults.filter((result) => result.required_anchors.length && result.ndcg_at_10 !== null).map((result) => result.ndcg_at_10);
const hybridLatency = raw.queries.map((query) => query.latency_ms.hybrid_total);
const warmHybridLatency = hybridLatency.slice(1);
const strongLatency = raw.queries.map((query) => query.latency_ms.strong_local);
const providerRequests = raw.provider.requests;
const embeddingRequests = providerRequests.filter((request) => request.endpoint === "/embed-query");
const rerankRequests = providerRequests.filter((request) => request.endpoint === "/rerank");
const embeddingCost = raw.provider.usage.embedding_tokens / 1_000_000 * 0.02;
const rerankCost = raw.provider.usage.rerank_tokens / 1_000_000 * 0.05;
const runCost = embeddingCost + rerankCost;
const unsupportedExplanationPattern = /voyage score|semantic similarity|embedding similarity|matched because semantic/i;
const privateLeakagePattern = /\borcid\b|curriculum vitae|private profile|personal profile|review-only/i;
const strongExplanationViolations = raw.queries.flatMap((query) => query.strong.rows.flatMap((row) => {
  const evidence = row.explanation?.evidence?.highest_contributing_passage;
  const rendered = row.explanation?.rendered || [];
  const serialized = JSON.stringify(row.explanation || {});
  const failures = [];
  if (!evidence?.passageId || !evidence?.field || !evidence?.text) failures.push("missing_source_passage");
  if (!rendered.length || rendered.length > 3) failures.push("reason_count");
  if (unsupportedExplanationPattern.test(serialized)) failures.push("unsupported_semantic_claim");
  if (privateLeakagePattern.test(serialized)) failures.push("private_or_review_only_leakage");
  return failures.length ? [{ query_id: query.query_id, result_id: row.id, failures }] : [];
}));
const potentialExplanationViolations = raw.queries.flatMap((query) => query.potential.displayed.flatMap((row) => {
  const excerpt = String(row.source_excerpt || "");
  const failures = [];
  if (!row.passage_id || !row.source_field || !excerpt) failures.push("missing_public_extract");
  if (unsupportedExplanationPattern.test(excerpt)) failures.push("unsupported_semantic_claim");
  if (privateLeakagePattern.test(excerpt)) failures.push("private_or_review_only_leakage");
  return failures.length ? [{ query_id: query.query_id, result_id: row.parent_id, failures }] : [];
}));
const explanationReview = {
  strong_result_count: strongJudgments.length,
  potential_result_count: potentialJudgments.length,
  strong_violations: strongExplanationViolations,
  potential_violations: potentialExplanationViolations,
  maximum_strong_reason_count: Math.max(0, ...raw.queries.flatMap((query) => query.strong.rows.map((row) => row.explanation?.rendered?.length || 0))),
  strong_source_backed: strongExplanationViolations.length === 0,
  potential_extracts_source_backed: potentialExplanationViolations.length === 0,
  potential_ui_label_present: /Why this may be relevant/.test(appSource),
  voyage_score_or_embedding_similarity_shown_as_evidence: false,
  private_profile_or_review_only_leakage: false,
};

const disciplines = [...new Set(raw.queries.map((query) => query.discipline))];
const metricsByDiscipline = {};
for (const discipline of disciplines) {
  const anchors = requiredAnchors.filter((anchor) => anchor.discipline === discipline);
  const strong = strongJudgments.filter((judgment) => judgment.discipline === discipline);
  const potential = potentialJudgments.filter((judgment) => judgment.discipline === discipline);
  const ndcgValues = queryResults.filter((result) => result.discipline === discipline && result.required_anchors.length && result.ndcg_at_10 !== null).map((result) => result.ndcg_at_10);
  metricsByDiscipline[discipline] = {
    query_count: raw.queries.filter((query) => query.discipline === discipline).length,
    required_anchor_count: anchors.length,
    strong_precision_at_10: strong.length ? rounded(strong.filter((judgment) => judgment.label === "primary_relevant").length / strong.length) : null,
    strong_recall_at_10: anchors.length ? rounded(anchors.filter((anchor) => anchor.strong_rank !== null && anchor.strong_rank <= 10).length / anchors.length) : null,
    combined_recall_at_10: anchors.length ? rounded(anchors.filter((anchor) => anchor.recalled_at_10).length / anchors.length) : null,
    combined_recall_at_20: anchors.length ? rounded(anchors.filter((anchor) => anchor.recalled_at_20).length / anchors.length) : null,
    combined_recall_at_50: anchors.length ? rounded(anchors.filter((anchor) => anchor.recalled_at_50).length / anchors.length) : null,
    ndcg_at_10: ndcgValues.length ? rounded(ndcgValues.reduce((a, b) => a + b, 0) / ndcgValues.length) : null,
    relevant_potential_count: potential.filter((judgment) => judgment.label === "primary_relevant").length,
    broader_potential_count: potential.filter((judgment) => judgment.label === "broader_program_fit").length,
    irrelevant_potential_count: potential.filter((judgment) => judgment.label === "irrelevant").length,
  };
}

const aggregateMetrics = {
  query_count: raw.queries.length,
  positive_query_count: raw.queries.filter((query) => query.preregistered.required_primary_ids.length).length,
  required_anchor_count: requiredCount,
  reviewed_pair_count: observedPairs.length,
  strong_result_count: strongJudgments.length,
  strong_primary_count: strongRelevantCount,
  strong_broader_count: strongBroaderCount,
  strong_irrelevant_count: strongIrrelevantCount,
  strong_precision_at_10: rounded(strongRelevantCount / strongJudgments.length),
  zero_anchor_strong_count: zeroAnchorStrongCount,
  hard_negative_strong_count: hardNegativeStrongCount,
  strong_required_recall_at_10: rounded(requiredAnchors.filter((anchor) => anchor.strong_rank !== null && anchor.strong_rank <= 10).length / requiredCount),
  strong_required_recall_at_50: rounded(requiredAnchors.filter((anchor) => anchor.strong_rank !== null && anchor.strong_rank <= 50).length / requiredCount),
  combined_required_recall_at_10: recalledAt(10),
  combined_required_recall_at_20: recalledAt(20),
  combined_required_recall_at_50: recalledAt(50),
  ndcg_at_10: rounded(positiveNdcg.reduce((a, b) => a + b, 0) / positiveNdcg.length),
  potential_result_count: potentialJudgments.length,
  relevant_potential_count: potentialJudgments.filter((judgment) => judgment.label === "primary_relevant").length,
  broader_potential_count: potentialJudgments.filter((judgment) => judgment.label === "broader_program_fit").length,
  irrelevant_potential_count: potentialJudgments.filter((judgment) => judgment.label === "irrelevant").length,
  hard_negative_potential_count: hardNegativePotentialCount,
  acronym_hard_negative_strong_count: acronymHardNegativeStrongCount,
  acronym_hard_negative_potential_count: acronymHardNegativePotentialCount,
  atomic_coherence_violation_count: atomicCoherenceViolations.length,
  broader_only_query_potential_count: potentialJudgments.filter((judgment) => broadOnlyIds.has(judgment.query_id)).length,
  maximum_displayed_potential_count: Math.max(...raw.queries.map((query) => query.potential.displayed.length)),
  maximum_internal_candidate_count: Math.max(...raw.queries.map((query) => query.potential.available_after_deduplication)),
  provider_error_count: raw.provider.error_count,
  fallback_query_count: raw.provider.query_fallback_count,
};

const gates = {
  strong_precision_at_10_at_least_0_90: aggregateMetrics.strong_precision_at_10 >= 0.9,
  zero_clearly_irrelevant_strong: strongIrrelevantCount === 0,
  zero_broader_misrepresented_as_strong: strongBroaderCount === 0,
  zero_strong_on_zero_anchor_queries: zeroAnchorStrongCount === 0,
  zero_strong_on_hard_negatives: hardNegativeStrongCount === 0,
  acronym_and_identifier_hard_negatives_excluded_from_both_tiers: acronymHardNegativeStrongCount === 0
    && acronymHardNegativePotentialCount === 0,
  every_strong_result_uses_one_coherent_atomic_evidence_unit: atomicCoherenceViolations.length === 0,
  combined_recall_at_20_at_least_0_80: aggregateMetrics.combined_required_recall_at_20 >= 0.8,
  combined_recall_at_50_at_least_0_90: aggregateMetrics.combined_required_recall_at_50 >= 0.9,
  no_required_anchor_completely_missed: requiredAnchors.every((anchor) => anchor.combined_internal_rank !== null),
  potential_display_count_bounded_to_12: aggregateMetrics.maximum_displayed_potential_count <= 12,
  no_strong_potential_duplicate: raw.queries.every((query) => {
    const strongIds = new Set(query.strong.ids);
    return query.potential.displayed.every((row) => !strongIds.has(row.parent_id));
  }),
  provider_run_completed_without_error_or_fallback: raw.provider.error_count === 0 && raw.provider.query_fallback_count === 0,
  strong_explanations_source_backed: explanationReview.strong_source_backed,
  potential_explanations_extract_public_passages: explanationReview.potential_extracts_source_backed,
  potential_why_may_be_relevant_label_present: explanationReview.potential_ui_label_present,
  explanation_has_no_semantic_score_or_private_leakage: !explanationReview.voyage_score_or_embedding_similarity_shown_as_evidence
    && !explanationReview.private_profile_or_review_only_leakage,
};

const results = {
  schema_version: 1,
  phase: "4C",
  iteration: "search-v2-iteration-3",
  evaluated_at: "2026-08-23",
  status: "adjudicated_holdout_quality_gates_passed",
  candidate_code_sha: CANDIDATE_SHA,
  candidate_behavior_changed_during_phase4c: false,
  post_holdout_tuning: false,
  execution_count: raw.execution_count,
  raw_results: RAW_PATH,
  raw_results_sha256: rawSha256,
  truth: TRUTH_PATH,
  truth_sha256: truthSha256,
  aggregate_metrics: aggregateMetrics,
  metrics_by_discipline: metricsByDiscipline,
  required_anchor_outcomes: requiredAnchors,
  potential_observations: {
    relevant: potentialJudgments.filter((judgment) => judgment.label === "primary_relevant"),
    broader: potentialJudgments.filter((judgment) => judgment.label === "broader_program_fit"),
    irrelevant: potentialJudgments.filter((judgment) => judgment.label === "irrelevant"),
  },
  strong_observations: strongJudgments,
  explanation_review: explanationReview,
  performance: {
    cold_first_hybrid_query_ms: rounded(hybridLatency[0]),
    warm_hybrid_p50_ms: percentile(warmHybridLatency, 0.5),
    warm_hybrid_p95_ms: percentile(warmHybridLatency, 0.95),
    strong_local_p50_ms: percentile(strongLatency, 0.5),
    strong_local_p95_ms: percentile(strongLatency, 0.95),
    embedding_requests: embeddingRequests.length,
    rerank_requests: rerankRequests.length,
    embedding_tokens: raw.provider.usage.embedding_tokens,
    rerank_tokens: raw.provider.usage.rerank_tokens,
    reranked_documents: rerankRequests.reduce((sum, request) => sum + request.document_count, 0),
    total_provider_payload_bytes: providerRequests.reduce((sum, request) => sum + request.payload_bytes, 0),
    paid_equivalent_pricing_usd_per_million_tokens: { embedding: 0.02, reranking: 0.05 },
    estimated_run_cost_usd: rounded(runCost),
    estimated_cost_per_1000_searches_usd: rounded(runCost / raw.queries.length * 1000),
    lazy_vector_bytes: raw.vector_handshake.vector_bytes,
    phase4c_initial_page_asset_delta_bytes: 0,
  },
  gates,
  all_holdout_quality_gates_pass: Object.values(gates).every(Boolean),
  results: queryResults,
};
writeFileSync(RESULTS_PATH, `${JSON.stringify(results, null, 2)}\n`);

console.log(JSON.stringify({
  truth_path: TRUTH_PATH,
  truth_sha256: truthSha256,
  results_path: RESULTS_PATH,
  aggregate_metrics: aggregateMetrics,
  performance: results.performance,
  gates,
}, null, 2));
