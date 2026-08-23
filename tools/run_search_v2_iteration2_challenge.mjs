#!/usr/bin/env node
// Development-only Iteration-2 runner. It executes the former Phase-4 holdout,
// now a permanent challenge set. It never imports or reads the new sealed holdout.

import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const FRAME_PATH = "evaluation/search_v2_holdout_frame.json";
const BASE_TRUTH_PATH = "evaluation/search_v2_holdout_truth.json";
const TRUTH_DELTA_PATH = "evaluation/search_v2_iteration2_challenge_truth_delta.json";
const ITERATION3_TRUTH_SUPPLEMENT_PATH = "evaluation/search_v2_iteration3_truth_supplement.json";
const OLD_RAW_PATH = "evaluation/search_v2_holdout_results_raw.json";
const OUTPUT_PATH = "evaluation/search_v2_iteration2_results.json";

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const ordered = values.slice().sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0;
}

function grade(judgment) {
  return judgment?.label === "primary_relevant" ? 2
    : judgment?.label === "broader_program_fit" ? 1 : 0;
}

function dcg(grades) {
  return grades.reduce((sum, value, index) => (
    sum + ((2 ** value) - 1) / Math.log2(index + 2)
  ), 0);
}

function metrics(ids, truth, depth) {
  const ranked = ids.slice(0, depth);
  const required = truth.required_primary_ids || [];
  const judgments = truth.judgments || {};
  const primary = ranked.filter(id => judgments[id]?.label === "primary_relevant").length;
  const requiredFound = required.filter(id => ranked.includes(id));
  const grades = ranked.map(id => grade(judgments[id]));
  const ideal = Object.values(judgments).map(grade)
    .sort((left, right) => right - left).slice(0, depth);
  const idealDcg = dcg(ideal);
  return {
    primary_precision: ranked.length ? number(primary / ranked.length) : (required.length ? 0 : 1),
    required_primary_recall: required.length ? number(requiredFound.length / required.length) : 1,
    ndcg: idealDcg ? number(dcg(grades) / idealDcg) : (ranked.length ? 0 : 1),
    retrieved_required_primary_ids: requiredFound,
  };
}

function queryClass(item) {
  if (["hold_ree_07", "hold_bio_02", "hold_health_02", "hold_space_01"].includes(item.id)) return "hard negatives";
  if (item.id.startsWith("hold_ree")) return "REE/material hierarchy";
  if (item.id.startsWith("hold_health")) return "health";
  if (item.id.startsWith("hold_ag")) return "agriculture";
  if (item.id.startsWith("hold_energy")) return "energy";
  if (item.id.startsWith("hold_ai")) return "AI/computing";
  if (item.id.startsWith("hold_defense")) return "defense";
  if (item.id.startsWith("hold_space")) return "space";
  if (item.id.startsWith("hold_env")) return "environment";
  return item.discipline || "other";
}

function admissionCounts(rows) {
  const counts = { direct: 0, child: 0, authoritative_scope: 0 };
  rows.forEach(row => {
    if (row.parentDirectEvidence?.admission?.reason === "authoritative_scope_entailment") {
      counts.authoritative_scope += 1;
    } else if (row.bestChild && row.childDroveMatch) {
      counts.child += 1;
    } else {
      counts.direct += 1;
    }
  });
  return counts;
}

function summarize(rows) {
  const positive = rows.filter(row => row.required_primary_ids.length);
  const directPositive = rows.filter(row => row.stratum === "direct_positive");
  const latencies = rows.map(row => row.latency_ms);
  const sum = (selector, population = rows) => population.length
    ? number(population.reduce((total, row) => total + selector(row), 0) / population.length)
    : 0;
  return {
    query_count: rows.length,
    primary_precision_at_10: sum(row => row.metrics_at_10.primary_precision),
    required_primary_recall_at_10: sum(row => row.metrics_at_10.required_primary_recall, positive),
    required_primary_recall_at_50: sum(row => row.metrics_at_50.required_primary_recall, positive),
    ndcg_at_10: sum(row => row.metrics_at_10.ndcg),
    direct_positive_ndcg_at_10: sum(row => row.metrics_at_10.ndcg, directPositive),
    visible_primary_count: rows.reduce((total, row) => total + row.visible_primary_count, 0),
    internal_candidate_discovery_count: rows.reduce((total, row) => total + row.internal_candidate_count, 0),
    broader_fit_count: rows.reduce((total, row) => total + row.broader_fit_count, 0),
    rejected_partial_intent_count: rows.reduce((total, row) => total + row.rejected_partial_intent_count, 0),
    admission_counts: rows.reduce((totals, row) => {
      Object.keys(totals).forEach(key => { totals[key] += row.admission_counts[key]; });
      return totals;
    }, { direct: 0, child: 0, authoritative_scope: 0 }),
    maximum_visible_primary_count: Math.max(0, ...rows.map(row => row.visible_primary_count)),
    maximum_internal_candidate_count: Math.max(0, ...rows.map(row => row.internal_candidate_count)),
    query_time_ms: {
      p50: number(percentile(latencies, .5)),
      p95: number(percentile(latencies, .95)),
    },
  };
}

async function main() {
  const [frame, baseTruth, delta, iteration3Supplement, oldRaw] = await Promise.all([
    readFile(new URL(FRAME_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(BASE_TRUTH_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(TRUTH_DELTA_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(ITERATION3_TRUTH_SUPPLEMENT_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(OLD_RAW_PATH, ROOT), "utf8").then(JSON.parse),
  ]);
  const truth = structuredClone(baseTruth);
  Object.entries(delta.additions || {}).forEach(([queryId, addition]) => {
    if (truth.queries[queryId]?.query !== addition.query) {
      throw new Error(`Query-specific truth mismatch for ${queryId}.`);
    }
    Object.assign(truth.queries[queryId].judgments, addition.judgments || {});
  });
  (iteration3Supplement.judgments || [])
    .filter(item => item.population === "phase4_iteration1_spent")
    .forEach(item => {
      if (truth.queries[item.query_id]?.query !== item.query) {
        throw new Error(`Iteration-3 query-specific truth mismatch for ${item.query_id}.`);
      }
      truth.queries[item.query_id].judgments[item.result_id] = {
        label: item.label,
        evidence: item.evidence,
      };
    });

  const base = await loadHarness();
  const candidate = makeVariantHarness(base, { searchV2: true });
  const rows = [];
  for (const item of frame.queries) {
    const queryTruth = truth.queries[item.id];
    if (!queryTruth || queryTruth.query !== item.query) throw new Error(`Missing truth for ${item.id}.`);
    const ranked = rankQuery(candidate, item.query, { evidence: true });
    const ids = ranked.rows.map(row => row.id);
    const unjudged = ids.slice(0, 10).filter(id => !queryTruth.judgments[id]);
    if (unjudged.length) throw new Error(`Unjudged top-ten rows for ${item.id}: ${unjudged.join(", ")}`);
    const parentDiscovery = ranked.parentDirect.diagnostics.searchV2.discovery;
    const childDiscovery = ranked.childDirect.diagnostics.searchV2.discovery;
    const top = ranked.rows.slice(0, 50);
    rows.push({
      id: item.id,
      query: item.query,
      stratum: item.stratum,
      discipline: item.discipline,
      query_class: queryClass(item),
      latency_ms: number(ranked.latencyMs),
      visible_primary_count: ranked.rows.length,
      internal_candidate_count: parentDiscovery.internalCandidateCount + childDiscovery.internalCandidateCount,
      broader_fit_count: parentDiscovery.broaderFitCount + childDiscovery.broaderFitCount,
      rejected_partial_intent_count: parentDiscovery.rejectedPartialIntentCount + childDiscovery.rejectedPartialIntentCount,
      admission_counts: admissionCounts(ranked.rows),
      required_primary_ids: queryTruth.required_primary_ids || [],
      required_primary_ranks: Object.fromEntries((queryTruth.required_primary_ids || []).map(id => {
        const rank = ids.indexOf(id);
        return [id, rank < 0 ? null : rank + 1];
      })),
      metrics_at_10: metrics(ids, queryTruth, 10),
      metrics_at_50: metrics(ids, queryTruth, 50),
      query_plan: ranked.queryPlan.map(group => ({
        concept_id: group.conceptId,
        role: group.role,
        evidence_policy: group.evidencePolicy,
      })),
      top_10: top.slice(0, 10).map((row, index) => ({
        rank: index + 1,
        id: row.id,
        title: row.record.title,
        evidence_tier: row.evidenceTier,
        truth: queryTruth.judgments[row.id],
        admission_reason: row.parentDirectEvidence?.admission?.reason
          || row.bestChild?.directEvidence?.admission?.reason || null,
      })),
    });
  }

  const byClass = {};
  [...new Set(rows.map(row => row.query_class))].sort().forEach(label => {
    byClass[label] = summarize(rows.filter(row => row.query_class === label));
  });
  const oldById = new Map(oldRaw.results.map(row => [row.id, row]));
  const payload = {
    schema_version: 1,
    iteration: "2R-iteration-2",
    generated_at: new Date().toISOString(),
    status: "development_challenge_executed",
    frame: FRAME_PATH,
    base_truth: BASE_TRUTH_PATH,
    truth_delta: TRUTH_DELTA_PATH,
    iteration3_truth_supplement: ITERATION3_TRUTH_SUPPLEMENT_PATH,
    sealed_iteration2_holdout_read_or_executed: false,
    before_metrics_from_immutable_phase4: {
      primary_precision_at_10: 0.373,
      required_primary_recall_at_10: 0.633,
      required_primary_recall_at_50: 0.65,
      direct_positive_ndcg_at_10: 0.586,
      maximum_visible_primary_count: 213,
      confirmed_irrelevant_top_ten_admissions: 43,
    },
    after_metrics: summarize(rows),
    metrics_by_query_class: byClass,
    gates: {
      all_required_ree_anchors_at_10: rows.filter(row => /^hold_ree_0[1-6]$/.test(row.id))
        .every(row => row.metrics_at_10.required_primary_recall === 1),
      hard_negatives_zero_primary: ["hold_ree_07", "hold_bio_02", "hold_health_02", "hold_space_01"]
        .every(id => rows.find(row => row.id === id)?.visible_primary_count === 0),
      rural_moms_recovered: rows.find(row => row.id === "hold_health_01")?.required_primary_ranks["363582"] <= 10,
      afri_recovered: rows.find(row => row.id === "hold_ag_01")?.required_primary_ranks["360205"] <= 10,
      scaleup_not_buried: rows.find(row => row.id === "hold_energy_01")?.required_primary_ranks["356623"] <= 3,
      genesis_useful_window: rows.find(row => row.id === "hold_ai_01")?.required_primary_ranks["361526"] <= 10,
      no_visible_primary_explosion: Math.max(...rows.map(row => row.visible_primary_count)) <= 50,
      no_confirmed_irrelevant_top_ten: rows.every(row => row.top_10.every(result => result.truth.label !== "irrelevant")),
    },
    movement_from_failed_phase4: rows.map(row => {
      const before = oldById.get(row.id);
      const oldIds = (before?.candidate_top_50 || []).slice(0, 10).map(item => item.id);
      const newIds = row.top_10.map(item => item.id);
      return {
        id: row.id,
        before_visible_primary_count: before?.candidate_count ?? null,
        after_visible_primary_count: row.visible_primary_count,
        added_to_top_10: newIds.filter(id => !oldIds.includes(id)),
        removed_from_top_10: oldIds.filter(id => !newIds.includes(id)),
      };
    }),
    results: rows,
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(OUTPUT_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify({
    output: process.argv.includes("--write") ? OUTPUT_PATH : null,
    after_metrics: payload.after_metrics,
    gates: payload.gates,
  }, null, 2));
  if (Object.values(payload.gates).some(value => value !== true)) process.exitCode = 1;
}

await main();
