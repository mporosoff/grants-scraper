#!/usr/bin/env node
// Phase 2 development-set evaluator. The sealed holdout is deliberately not read.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import { performance } from "node:perf_hooks";

import {
  loadHarness,
  makeVariantHarness,
  rankQuery,
} from "./run_search_diagnosis.mjs";
import {
  loadHarness as loadMeas5Harness,
  rank as rankMeas5,
} from "./run_meas5.mjs";

const ROOT = new URL("../", import.meta.url);
const FRAME_PATH = "evaluation/search_v2_frame.json";
const TRUTH_PATH = "evaluation/search_v2_development_truth.json";
const PHASE2_TOP10_PATH = "evaluation/search_v2_phase2_top10.json";
const RESULTS_PATH = "evaluation/search_v2_results.json";
const MOVEMENT_PATH = "evaluation/search_v2_movement_review.json";
const MOVEMENT_JUDGMENTS_PATH = "evaluation/search_v2_stabilization_movement_judgments.json";
const MEAS5_FRAME_PATH = "evaluation/meas5_query_set.json";
const MEAS5_RESULTS_PATH = "evaluation/meas5_results.json";
const REQUIRED_PRIMARY_IDS = ["360678", "361526", "362061"];

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const sorted = values.slice().sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)] || 0;
}

function reeFamily(query) {
  return /\b(?:ree|rees|lanthanide)|rare[ .-]?earth|\bR\s*\.\s*E\s*\.\s*E/i.test(query);
}

function compactResult(ranked, queryTruth) {
  return ranked.rows.slice(0, 50).map((row, index) => {
    const evidence = row.parentDirectEvidence || row.bestChild?.directEvidence || null;
    return {
      rank: index + 1,
      id: row.id,
      title: row.record.title,
      score: number(row.score),
      parent_admitted: row.parentAdmitted,
      child_drove_match: row.childDroveMatch,
      best_child_id: row.bestChild?.id || null,
      truth: queryTruth?.judgments?.[row.id] || null,
      admission_reason: evidence?.admission?.reason || null,
      admitted_by: evidence?.admission?.admittedBy || [],
      authoritative_scope: evidence?.authoritativeScope || null,
      field_contributions: evidence?.admission?.fieldContributions || [],
    };
  });
}

async function evaluate() {
  if (process.argv.some(argument => /holdout/i.test(argument))) {
    throw new Error("Development evaluation refuses every holdout argument. A separately authorized one-time acceptance runner owns holdout execution.");
  }
  const [
    frameSource,
    truthSource,
    phase2Top10Source,
    configSource,
    meas5FrameSource,
    meas5BaselineSource,
    movementJudgmentsSource,
  ] = await Promise.all([
    readFile(new URL(FRAME_PATH, ROOT), "utf8"),
    readFile(new URL(TRUTH_PATH, ROOT), "utf8"),
    readFile(new URL(PHASE2_TOP10_PATH, ROOT), "utf8"),
    readFile(new URL("config/search_v2.json", ROOT), "utf8"),
    readFile(new URL(MEAS5_FRAME_PATH, ROOT), "utf8"),
    readFile(new URL(MEAS5_RESULTS_PATH, ROOT), "utf8"),
    readFile(new URL(MOVEMENT_JUDGMENTS_PATH, ROOT), "utf8")
      .catch(() => '{"schema_version":1,"reviews":{}}'),
  ]);
  const frame = JSON.parse(frameSource);
  const truth = JSON.parse(truthSource);
  const phase2Top10 = JSON.parse(phase2Top10Source);
  const meas5Frame = JSON.parse(meas5FrameSource);
  const movementJudgments = JSON.parse(movementJudgmentsSource);
  const oldById = new Map(Object.entries(phase2Top10.queries || {}));
  const base = await loadHarness();
  const candidate = makeVariantHarness(base, { searchV2: true });
  const meas5ProductionHarness = await loadMeas5Harness();
  const meas5Harness = {
    ...meas5ProductionHarness,
    parentEngine: meas5ProductionHarness.retrievalApi.create(
      meas5ProductionHarness.catalog,
      meas5ProductionHarness.queryApi,
      {
        searchV2: true,
        searchV2Config: meas5ProductionHarness.searchV2Config,
        catalogRole: "parent",
      },
    ),
    childEngine: meas5ProductionHarness.retrievalApi.create(
      meas5ProductionHarness.childCatalog,
      meas5ProductionHarness.queryApi,
      {
        searchV2: true,
        searchV2Config: meas5ProductionHarness.searchV2Config,
        catalogRole: "child",
      },
    ),
  };
  const results = [];
  const latencies = [];

  for (const item of frame.queries) {
    const ranked = rankQuery(candidate, item.query, { evidence: true });
    latencies.push(ranked.latencyMs);
    const queryTruth = truth.queries?.[item.id] || null;
    if (queryTruth && queryTruth.query !== item.query) {
      throw new Error(`Query-specific truth mismatch for ${item.id}.`);
    }
    const rows = compactResult(ranked, queryTruth);
    const old = oldById.get(item.id);
    results.push({
      id: item.id,
      discipline: item.discipline,
      kind: item.kind,
      query: item.query,
      old_candidate_count: old?.candidate_count ?? null,
      candidate_count: ranked.rows.length,
      latency_ms: number(ranked.latencyMs),
      query_plan: ranked.diagnostics.searchV2.queryPlan,
      minimum_coverage: ranked.diagnostics.minimumCoverage,
      short_complete_coverage: ranked.diagnostics.searchV2.shortCompleteCoverage,
      scope_entailments: ranked.diagnostics.searchV2.authoritativeScopeEntailments,
      top_results: rows,
      required_primary_status: Object.fromEntries(REQUIRED_PRIMARY_IDS.map(id => {
        const rank = ranked.rows.findIndex(row => row.id === id);
        return [id, rank < 0 ? null : rank + 1];
      })),
    });
  }

  // Record warm scoring without explanation collection; this remains development-only.
  const warmLatencies = [];
  for (let pass = 0; pass < 3; pass += 1) {
    for (const item of frame.queries) {
      const started = performance.now();
      rankQuery(candidate, item.query, { evidence: false });
      warmLatencies.push(performance.now() - started);
    }
  }

  const meas5Movements = meas5Frame.queries.map(item => {
    const oldRows = rankMeas5(
      meas5ProductionHarness,
      item.query || "",
      item.profile || null,
      true,
    );
    const rows = rankMeas5(meas5Harness, item.query || "", item.profile || null, true);
    const newTop = rows.slice(0, 10).map(row => row.id);
    const oldTop = oldRows.slice(0, 10).map(row => row.id);
    return {
      id: item.id,
      discipline: item.discipline,
      kind: item.kind,
      query: item.query,
      old_top_10: oldTop,
      new_top_10: newTop,
      added_to_top_10: newTop.filter(id => !oldTop.includes(id)),
      removed_from_top_10: oldTop.filter(id => !newTop.includes(id)),
      changed: JSON.stringify(oldTop) !== JSON.stringify(newTop),
    };
  });
  const reviews = movementJudgments.reviews || {};
  const reviewedMeas5 = meas5Movements.map(item => ({
    ...item,
    review: item.changed ? (reviews[`meas5:${item.id}`] || null) : null,
  }));
  const changedMeas5 = reviewedMeas5.filter(item => item.changed);

  const movements = results.map(item => {
    const oldTop = oldById.get(item.id)?.top_10 || [];
    const newTop = item.top_results.slice(0, 10).map(row => row.id);
    const top10Changed = JSON.stringify(oldTop) !== JSON.stringify(newTop);
    return {
      id: item.id,
      discipline: item.discipline,
      query: item.query,
      old_candidate_count: oldById.get(item.id)?.candidate_count ?? null,
      new_candidate_count: item.candidate_count,
      old_top_10: oldTop,
      new_top_10: newTop,
      added_to_top_10: newTop.filter(id => !oldTop.includes(id)),
      removed_from_top_10: oldTop.filter(id => !newTop.includes(id)),
      top_10_changed: top10Changed,
      review: top10Changed ? (reviews[`development:${item.id}`] || null) : null,
    };
  });
  const changedMovements = movements.filter(item => item.top_10_changed);
  const acceptedReview = review => review?.status === "accepted" && Boolean(review?.reason);

  const resultById = new Map(results.map(item => [item.id, item]));
  const resultByQuery = new Map(results.map(item => [item.query, item]));
  const reeSeparation = resultByQuery.get("REE separations");
  const aliasQueries = ["REE", "REEs", "R.E.E.", "rare earth elements", "rare-earth elements"];
  const aliasSets = aliasQueries.map(query => (
    resultByQuery.get(query)?.top_results.map(row => row.id) || []
  ));
  const reeRows = results.filter(item => reeFamily(item.query)).flatMap(item => item.top_results);
  const unlabelledReeIds = [...new Set(reeRows
    .filter(row => !row.truth)
    .map(row => row.id))];
  const irrelevantReeIds = [...new Set(reeRows
    .filter(row => row.truth?.label !== "primary_relevant")
    .map(row => row.id))];

  const crossDomain = (truth.cross_domain_query_ids || []).map(queryId => {
    const truthEntry = truth.queries[queryId];
    const result = resultById.get(queryId);
    const top10 = result?.top_results.slice(0, 10) || [];
    const required = truthEntry.required_primary_ids || [];
    const baselineTop10 = oldById.get(queryId)?.top_10 || [];
    const baselineRequired = required.filter(id => baselineTop10.includes(id));
    const currentRequired = required.filter(id => top10.some(row => row.id === id));
    const unjudged = top10.filter(row => !truthEntry.judgments[row.id]).map(row => row.id);
    const nonPrimary = top10.filter(row => (
      truthEntry.judgments[row.id]?.label !== "primary_relevant"
    )).map(row => row.id);
    return {
      id: queryId,
      query: truthEntry.query,
      top_10: top10.map(row => row.id),
      unjudged_top_10: unjudged,
      non_primary_top_10: nonPrimary,
      required_primary_ids: required,
      baseline_required_recall: required.length ? number(baselineRequired.length / required.length) : 1,
      candidate_required_recall: required.length ? number(currentRequired.length / required.length) : 1,
      primary_precision_at_10: top10.length
        ? number(top10.filter(row => truthEntry.judgments[row.id]?.label === "primary_relevant").length / top10.length)
        : (required.length ? 0 : 1),
    };
  });
  const shortIntegrityFailures = results.filter(item => (
    item.query_plan.length >= 2
    && item.query_plan.length <= 4
    && item.query_plan.some(group => group.strictEvidence === true)
    && (
      item.minimum_coverage !== item.query_plan.length
      || item.short_complete_coverage !== true
    )
  )).map(item => item.id);
  const cfdRows = rankQuery(candidate, "CFD", { evidence: true }).rows.map(row => row.id);
  const truthKeysValid = (truth.reviewed_query_ids || []).every(queryId => {
    if (queryId === "phase3_cfd") return truth.queries[queryId]?.query === "CFD";
    const frameItem = frame.queries.find(item => item.id === queryId);
    return frameItem && frameItem.query === truth.queries[queryId]?.query;
  });
  const hardGates = {
    ree_aliases_resolve_identically: aliasSets.slice(1).every(ids => (
      JSON.stringify(ids) === JSON.stringify(aliasSets[0])
    )),
    ree_separations_required_primary_ids_present: REQUIRED_PRIMARY_IDS.every(id => (
      reeSeparation?.top_results.some(row => row.id === id)
    )),
    ree_separations_only_required_primary_results: (
      reeSeparation?.top_results.every(row => REQUIRED_PRIMARY_IDS.includes(row.id)) === true
    ),
    ree_family_non_primary_admissions: irrelevantReeIds,
    ree_family_unlabelled_admissions: unlabelledReeIds,
    query_specific_truth_keys_valid: truthKeysValid,
    cross_domain_unjudged_top_10: crossDomain.flatMap(item => item.unjudged_top_10.map(id => `${item.id}:${id}`)),
    cross_domain_non_primary_top_10: crossDomain.flatMap(item => item.non_primary_top_10.map(id => `${item.id}:${id}`)),
    cross_domain_recall_not_worse: crossDomain.every(item => (
      item.candidate_required_recall >= item.baseline_required_recall
    )),
    short_query_integrity_failures: shortIntegrityFailures,
    short_acronym_prefix_leakage: cfdRows,
    development_movements_reviewed: changedMovements.every(item => acceptedReview(item.review)),
    meas5_movements_reviewed: changedMeas5.every(item => acceptedReview(item.review)),
    holdout_status: "sealed_and_unopened",
  };
  const passed = hardGates.ree_aliases_resolve_identically
    && hardGates.ree_separations_required_primary_ids_present
    && hardGates.ree_separations_only_required_primary_results
    && !irrelevantReeIds.length
    && !unlabelledReeIds.length
    && hardGates.query_specific_truth_keys_valid
    && !hardGates.cross_domain_unjudged_top_10.length
    && !hardGates.cross_domain_non_primary_top_10.length
    && hardGates.cross_domain_recall_not_worse
    && !shortIntegrityFailures.length
    && !cfdRows.length
    && hardGates.development_movements_reviewed
    && hardGates.meas5_movements_reviewed
    && percentile(warmLatencies, .95) < 100;

  const payload = {
    schema_version: 2,
    evaluated_at: "2026-08-22",
    phase: "2.1/3.1-stabilization",
    status: passed ? "development_gates_passed" : "development_gates_failed",
    production_enabled: false,
    holdout_status: "sealed_and_unopened",
    preserved_invariants: {
      ree_architecture: true,
      authoritative_scope_entailments: true,
      global_field_weights_changed: false,
      title_bonuses_changed: false,
      explanation_contract_version: 2,
      bm25f_added: false,
      embeddings_added: false,
      query_time_ai_added: false,
      telemetry_added: false,
      broad_ontology_added: false
    },
    frame: FRAME_PATH,
    frame_sha256: sha256(frameSource),
    truth: TRUTH_PATH,
    truth_sha256: sha256(truthSource),
    phase2_top_10: PHASE2_TOP10_PATH,
    phase2_top_10_sha256: sha256(phase2Top10Source),
    movement_judgments: MOVEMENT_JUDGMENTS_PATH,
    configuration: "config/search_v2.json",
    configuration_sha256: sha256(configSource),
    query_count: results.length,
    latency_ms: {
      evidence_median: number(percentile(latencies, .5)),
      evidence_p95: number(percentile(latencies, .95)),
      warm_median: number(percentile(warmLatencies, .5)),
      warm_p95: number(percentile(warmLatencies, .95)),
      warm_maximum: number(Math.max(...warmLatencies)),
    },
    hard_gates: hardGates,
    query_specific_cross_domain_gate: {
      query_count: crossDomain.length,
      judgments_are_query_result_pairs: true,
      queries: crossDomain,
    },
    meas5_cross_domain_gate: {
      frame: MEAS5_FRAME_PATH,
      frame_sha256: sha256(meas5FrameSource),
      comparison: "current production versus stabilized search-v2 candidate on identical catalog and sidecar bytes",
      historical_results_sha256: sha256(meas5BaselineSource),
      query_count: reviewedMeas5.length,
      discipline_count: new Set(reviewedMeas5.map(item => item.discipline)).size,
      changed_top_10_queries: changedMeas5.length,
      status: hardGates.meas5_movements_reviewed ? "reviewed" : "review_required",
      movements: changedMeas5,
    },
    results,
  };

  if (process.argv.includes("--write")) {
    for (const [path, value] of [
      [RESULTS_PATH, payload],
      [MOVEMENT_PATH, {
        schema_version: 2,
        evaluated_at: "2026-08-22",
        holdout_status: "sealed_and_unopened",
        baseline: PHASE2_TOP10_PATH,
        judgments: MOVEMENT_JUDGMENTS_PATH,
        changed_top_10_queries: movements.filter(item => item.top_10_changed).length,
        unchanged_top_10_queries: movements.filter(item => !item.top_10_changed).length,
        all_material_movements_reviewed: hardGates.development_movements_reviewed,
        movements,
      }],
    ]) await writeFile(new URL(path, ROOT), `${JSON.stringify(value, null, 2)}\n`, "utf8");
    process.stdout.write(
      `Wrote Phase 2.1 development results: ${results.length} queries; `
      + `warm p95 ${payload.latency_ms.warm_p95} ms; holdout sealed.\n`,
    );
  } else {
    process.stdout.write(`${JSON.stringify({ payload, movements }, null, 2)}\n`);
  }
  if (!passed) process.exitCode = 1;
}

await evaluate();
