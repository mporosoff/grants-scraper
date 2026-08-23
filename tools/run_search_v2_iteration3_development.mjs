#!/usr/bin/env node
// Iteration-3 development runner. Both prior acceptance populations are spent
// challenge evidence. This runner never imports, reads, or executes Phase 4C.

import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const POPULATIONS = [
  {
    id: "phase4_iteration1_spent",
    frame: "evaluation/search_v2_holdout_frame.json",
    truth: "evaluation/search_v2_holdout_truth.json",
  },
  {
    id: "phase4b_iteration2_spent",
    frame: "evaluation/search_v2_iteration2_holdout_frame.json",
    truth: "evaluation/search_v2_iteration2_holdout_truth.json",
  },
];
const OUTPUT = "evaluation/search_v2_iteration3_spent_challenge_raw.json";

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const ordered = values.slice().sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0;
}

function grade(label) {
  return label === "primary_relevant" ? 2 : label === "broader_program_fit" ? 1 : 0;
}

function dcg(values) {
  return values.reduce((sum, value, index) => (
    sum + ((2 ** value) - 1) / Math.log2(index + 2)
  ), 0);
}

function queryMetrics(ids, queryTruth) {
  const top10 = ids.slice(0, 10);
  const required = queryTruth.required_primary_ids || [];
  const judgments = queryTruth.judgments || {};
  const judgedTop10 = top10.filter(id => judgments[id]);
  const primary = judgedTop10.filter(id => judgments[id].label === "primary_relevant").length;
  const ideal = Object.values(judgments).map(item => grade(item.label))
    .sort((left, right) => right - left).slice(0, 10);
  const idealDcg = dcg(ideal);
  return {
    precision_at_10_over_judged: judgedTop10.length ? number(primary / judgedTop10.length) : null,
    required_recall_at_10: required.length
      ? number(required.filter(id => top10.includes(id)).length / required.length)
      : 1,
    required_recall_at_50: required.length
      ? number(required.filter(id => ids.slice(0, 50).includes(id)).length / required.length)
      : 1,
    ndcg_at_10_over_current_truth: idealDcg
      ? number(dcg(top10.map(id => grade(judgments[id]?.label))) / idealDcg)
      : (top10.length ? 0 : 1),
    unjudged_top_10: top10.filter(id => !judgments[id]),
  };
}

function alternativeRows(harness, ranked, scoreKey) {
  const parentDirect = { ...ranked.parentDirect, scores: ranked.parentDirect[scoreKey] };
  const childDirect = { ...ranked.childDirect, scores: ranked.childDirect[scoreKey] };
  const rolled = harness.retrievalApi.rollupScores({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentDirect,
    parentProfile: { scores: new Float64Array(harness.parentCatalog.opportunities.length) },
    childDirect,
    childProfile: { scores: new Float64Array(harness.childCatalog.opportunities.length) },
    eligibilityBonuses: new Float64Array(harness.parentCatalog.opportunities.length),
  });
  return rolled.rows.filter(row => row.record?.status !== "archived").sort((left, right) => (
    Number(left.evidenceTier || 99) - Number(right.evidenceTier || 99)
    || right.score - left.score
    || left.id.localeCompare(right.id)
  ));
}

function explanationFor(harness, query, row) {
  return harness.explanationApi.buildV2({
    query,
    parent: {
      record: row.record,
      broad: /\b(?:broad agency announcement|umbrella|open announcement)\b/i.test(
        `${row.record?.title || ""} ${String(row.record?.description || "").slice(0, 1_500)}`,
      ),
      directEvidence: row.parentDirectEvidence || null,
      parentAdmitted: row.parentAdmitted,
    },
    bestChild: row.bestChild || null,
    childDroveMatch: row.childDroveMatch,
    parentAdmitted: row.parentAdmitted,
  });
}

async function main() {
  if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
    throw new Error("Iteration-3 development refuses the sealed Phase-4C population.");
  }
  const base = await loadHarness();
  const candidate = makeVariantHarness(base, { searchV2: true });
  const populations = [];
  const latencies = [];
  for (const population of POPULATIONS) {
    const [frame, truth] = await Promise.all([
      readFile(new URL(population.frame, ROOT), "utf8").then(JSON.parse),
      readFile(new URL(population.truth, ROOT), "utf8").then(JSON.parse),
    ]);
    const rows = [];
    for (const item of frame.queries) {
      const queryTruth = truth.queries[item.id];
      if (!queryTruth || queryTruth.query !== item.query) {
        throw new Error(`Query-specific truth mismatch for ${item.id}.`);
      }
      const started = performance.now();
      const ranked = rankQuery(candidate, item.query, { evidence: true });
      const latency = performance.now() - started;
      latencies.push(latency);
      const ids = ranked.rows.map(row => row.id);
      const primaryIds = new Set(ids);
      const broaderRows = alternativeRows(candidate, ranked, "broaderScores")
        .filter(row => !primaryIds.has(row.id));
      const parentDiscovery = ranked.parentDirect.diagnostics.searchV2.discovery;
      const childDiscovery = ranked.childDirect.diagnostics.searchV2.discovery;
      rows.push({
        id: item.id,
        query: item.query,
        discipline: item.discipline || "",
        stratum: item.stratum || "",
        latency_ms: number(latency),
        visible_primary_count: ranked.rows.length,
        internal_candidate_count: Number(parentDiscovery.internalCandidateCount || 0)
          + Number(childDiscovery.internalCandidateCount || 0),
        internal_parent_candidate_count: Number(parentDiscovery.internalCandidateCount || 0),
        internal_child_candidate_count: Number(childDiscovery.internalCandidateCount || 0),
        broader_fit_count: Number(parentDiscovery.broaderFitCount || 0)
          + Number(childDiscovery.broaderFitCount || 0),
        rejected_partial_intent_count: Number(parentDiscovery.rejectedPartialIntentCount || 0)
          + Number(childDiscovery.rejectedPartialIntentCount || 0),
        required_primary_ids: queryTruth.required_primary_ids || [],
        required_primary_ranks: Object.fromEntries((queryTruth.required_primary_ids || []).map(id => {
          const rank = ids.indexOf(id);
          return [id, rank < 0 ? null : rank + 1];
        })),
        metrics: queryMetrics(ids, queryTruth),
        query_plan: ranked.queryPlan.map(group => ({
          source: group.source,
          concept_id: group.conceptId,
          role: group.role,
          evidence_policy: group.evidencePolicy,
        })),
        top_10: ranked.rows.slice(0, 10).map((row, index) => {
          const activeEvidence = row.bestChild?.directEvidence?.admission?.admitted
            ? row.bestChild.directEvidence
            : row.parentDirectEvidence;
          return {
            rank: index + 1,
            id: row.id,
            title: row.record.title,
            evidence_tier: row.evidenceTier,
            best_child_id: row.bestChild?.id || null,
            best_child_title: row.bestChild?.record?.title || null,
            admission_reason: activeEvidence?.admission?.reason || null,
            admitted_by: activeEvidence?.admission?.admittedBy || [],
            explanation: explanationFor(candidate, item.query, row),
            existing_truth: queryTruth.judgments?.[row.id] || null,
          };
        }),
        broader_program_fits: broaderRows.slice(0, 10).map((row, index) => ({
          rank: index + 1,
          id: row.id,
          title: row.record.title,
          evidence_tier: row.evidenceTier,
          best_child_id: row.bestChild?.id || null,
          admission_reason: (row.parentDirectEvidence
            || row.bestChild?.directEvidence)?.admission?.reason || null,
          explanation: explanationFor(candidate, item.query, row),
          existing_truth: queryTruth.judgments?.[row.id] || null,
        })),
      });
    }
    populations.push({ ...population, query_count: rows.length, results: rows });
  }
  const payload = {
    schema_version: 1,
    iteration: 3,
    status: "spent_challenge_development_output_not_acceptance",
    generated_at: new Date().toISOString(),
    sealed_phase4c_read_or_executed: false,
    populations,
    query_time_ms: {
      p50: number(percentile(latencies, .5)),
      p95: number(percentile(latencies, .95)),
      maximum: number(Math.max(0, ...latencies)),
    },
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(OUTPUT, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  const summary = Object.fromEntries(populations.map(population => [
    population.id,
    {
      query_count: population.query_count,
      unjudged_top_10_pairs: population.results.reduce(
        (sum, row) => sum + row.metrics.unjudged_top_10.length,
        0,
      ),
      required_anchor_misses_at_50: population.results.flatMap(row => (
        Object.entries(row.required_primary_ranks)
          .filter(([_id, rank]) => rank === null || rank > 50)
          .map(([id]) => `${row.id}:${id}`)
      )),
      maximum_visible_primary_count: Math.max(0, ...population.results.map(row => row.visible_primary_count)),
    },
  ]));
  console.log(JSON.stringify({ output: process.argv.includes("--write") ? OUTPUT : null, summary }, null, 2));
}

await main();
