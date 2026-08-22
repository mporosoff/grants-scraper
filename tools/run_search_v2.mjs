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
const TRUTH_PATH = "evaluation/search_v2_truth.json";
const BASELINE_PATH = "evaluation/search_v2_baseline.json";
const RESULTS_PATH = "evaluation/search_v2_results.json";
const MOVEMENT_PATH = "evaluation/search_v2_movement_review.json";
const CALIBRATION_PATH = "evaluation/search_v2_field_calibration.json";
const ABLATION_PATH = "evaluation/search_v2_field_ablation_final.json";
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

function compactResult(ranked, truth) {
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
      truth: truth.adjudications[row.id] || null,
      admission_reason: evidence?.admission?.reason || null,
      admitted_by: evidence?.admission?.admittedBy || [],
      authoritative_scope: evidence?.authoritativeScope || null,
      field_contributions: evidence?.admission?.fieldContributions || [],
    };
  });
}

async function evaluate() {
  if (process.argv.includes("--holdout")) {
    throw new Error("Phase 2 refuses to open the sealed holdout. Phase 4 owns first execution and adjudication.");
  }
  const [
    frameSource,
    truthSource,
    baselineSource,
    configSource,
    meas5FrameSource,
    meas5BaselineSource,
  ] = await Promise.all([
    readFile(new URL(FRAME_PATH, ROOT), "utf8"),
    readFile(new URL(TRUTH_PATH, ROOT), "utf8"),
    readFile(new URL(BASELINE_PATH, ROOT), "utf8"),
    readFile(new URL("config/search_v2.json", ROOT), "utf8"),
    readFile(new URL(MEAS5_FRAME_PATH, ROOT), "utf8"),
    readFile(new URL(MEAS5_RESULTS_PATH, ROOT), "utf8"),
  ]);
  const frame = JSON.parse(frameSource);
  const truth = JSON.parse(truthSource);
  const baseline = JSON.parse(baselineSource);
  const meas5Frame = JSON.parse(meas5FrameSource);
  const oldById = new Map(baseline.results.map(item => [item.id, item]));
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
    const rows = compactResult(ranked, truth);
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
  const changedMeas5 = meas5Movements.filter(item => item.changed);

  const resultByQuery = new Map(results.map(item => [item.query, item]));
  const reeSeparation = resultByQuery.get("REE separations");
  const aliasQueries = ["REE", "REEs", "R.E.E.", "rare earth elements", "rare-earth elements"];
  const aliasSets = aliasQueries.map(query => (
    resultByQuery.get(query)?.top_results.map(row => row.id) || []
  ));
  const reeRows = results.filter(item => reeFamily(item.query)).flatMap(item => item.top_results);
  const unlabelledReeIds = [...new Set(reeRows
    .filter(row => !truth.adjudications[row.id])
    .map(row => row.id))];
  const irrelevantReeIds = [...new Set(reeRows
    .filter(row => row.truth?.label === "irrelevant")
    .map(row => row.id))];
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
    ree_family_irrelevant_admissions: irrelevantReeIds,
    ree_family_unlabelled_admissions: unlabelledReeIds,
    holdout_status: "sealed_and_unopened",
  };
  const passed = hardGates.ree_aliases_resolve_identically
    && hardGates.ree_separations_required_primary_ids_present
    && hardGates.ree_separations_only_required_primary_results
    && !irrelevantReeIds.length
    && !unlabelledReeIds.length
    && !changedMeas5.length
    && percentile(warmLatencies, .95) < 100;

  const payload = {
    schema_version: 1,
    evaluated_at: "2026-08-22",
    phase: 2,
    status: passed ? "development_gates_passed" : "development_gates_failed",
    production_enabled: false,
    holdout_status: "sealed_and_unopened",
    frame: FRAME_PATH,
    frame_sha256: sha256(frameSource),
    truth: TRUTH_PATH,
    truth_sha256: sha256(truthSource),
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
    meas5_cross_domain_gate: {
      frame: MEAS5_FRAME_PATH,
      frame_sha256: sha256(meas5FrameSource),
      comparison: "current production versus search-v2 candidate on identical catalog and sidecar bytes",
      historical_results_sha256: sha256(meas5BaselineSource),
      query_count: meas5Movements.length,
      discipline_count: new Set(meas5Movements.map(item => item.discipline)).size,
      changed_top_10_queries: changedMeas5.length,
      status: changedMeas5.length ? "review_required" : "zero_top_10_movement",
      movements: changedMeas5,
    },
    results,
  };

  const movements = results.map(item => {
    const oldTop = (oldById.get(item.id)?.top_results || []).slice(0, 10).map(row => row.id);
    const newTop = item.top_results.slice(0, 10).map(row => row.id);
    return {
      id: item.id,
      discipline: item.discipline,
      query: item.query,
      old_candidate_count: item.old_candidate_count,
      new_candidate_count: item.candidate_count,
      old_top_10: oldTop,
      new_top_10: newTop,
      added_to_top_10: newTop.filter(id => !oldTop.includes(id)),
      removed_from_top_10: oldTop.filter(id => !newTop.includes(id)),
      top_10_changed: JSON.stringify(oldTop) !== JSON.stringify(newTop),
      review: reeFamily(item.query)
        ? "REE-family movement is governed by the corrected truth rubric."
        : "No search-v2 concept rule applies unless the query plan says otherwise.",
    };
  });

  const calibration = {
    schema_version: 1,
    evaluated_at: "2026-08-22",
    phase_1_authorized_track: "B",
    status: "not_required_by_phase_1_evidence",
    selected_design: "compact first-stage retrieval plus protected field-local verification and identifier-bound authoritative scope entailment",
    global_field_weights_changed: false,
    title_bonuses_changed: false,
    scope_entailment_score: JSON.parse(configSource).scope_entailment_score,
    selection_rule: "Use the smallest positive bounded score because authoritative scope controls admission; existing lexical evidence may rank an already-admitted program.",
    rejected_work: [
      "BM25F fielded-postings rewrite",
      "global title/description weight search",
      "embedding or query-time model layer",
    ],
  };
  const finalAblation = {
    schema_version: 1,
    evaluated_at: "2026-08-22",
    status: "not_required_by_phase_1_evidence",
    inherited_measurement: "evaluation/search_v2_field_ablation.json",
    reason: "Track B retained production field weights and bonuses. Phase 2 added field-local causal verification, not a new field-scoring model.",
    replacement_gates: [
      "explicit protected evidence identifies substantive parent/child fields",
      "generic topic, discipline, agency, and category fields cannot establish scope entailment",
      "protected concept contribution saturates at the top two term contributions",
      "parent/child rollup remains cardinality-neutral",
    ],
  };

  if (process.argv.includes("--write")) {
    for (const [path, value] of [
      [RESULTS_PATH, payload],
      [MOVEMENT_PATH, {
        schema_version: 1,
        evaluated_at: "2026-08-22",
        holdout_status: "sealed_and_unopened",
        changed_top_10_queries: movements.filter(item => item.top_10_changed).length,
        unchanged_top_10_queries: movements.filter(item => !item.top_10_changed).length,
        movements,
      }],
      [CALIBRATION_PATH, calibration],
      [ABLATION_PATH, finalAblation],
    ]) await writeFile(new URL(path, ROOT), `${JSON.stringify(value, null, 2)}\n`, "utf8");
    process.stdout.write(
      `Wrote Phase 2 development results: ${results.length} queries; `
      + `warm p95 ${payload.latency_ms.warm_p95} ms; holdout sealed.\n`,
    );
  } else {
    process.stdout.write(`${JSON.stringify({ payload, movements, calibration, finalAblation }, null, 2)}\n`);
  }
  if (!passed) process.exitCode = 1;
}

await evaluate();
