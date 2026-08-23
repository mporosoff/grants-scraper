#!/usr/bin/env node
// Summarize the local fielded architecture on spent evidence only. Phase 4C
// is neither read nor executed by this tool.

import { readFile, writeFile } from "node:fs/promises";

const ROOT = new URL("../", import.meta.url);
const RAW_PATH = "evaluation/search_v2_local_architecture_spent_results.json";
const RESULTS_PATH = "evaluation/search_v2_local_architecture_results.json";
const LEAVEOUT_PATH = "evaluation/search_v2_local_architecture_leaveout.json";

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function family(queryId) {
  if (/ree|material/.test(queryId)) return "materials";
  if (/health/.test(queryId)) return "health";
  if (/_ag_/.test(queryId)) return "agriculture";
  if (/energy/.test(queryId)) return "energy";
  if (/_ai_|child/.test(queryId)) return "ai_computing";
  if (/defense/.test(queryId)) return "defense";
  if (/space/.test(queryId)) return "space";
  if (/env/.test(queryId)) return "environment";
  if (/negative|hard/.test(queryId)) return "hard_negative";
  if (/chem/.test(queryId)) return "chemistry";
  if (/bio/.test(queryId)) return "biology";
  return "other";
}

function grade(label) {
  return label === "primary_relevant" ? 2 : label === "broader_program_fit" ? 1 : 0;
}

function dcg(values) {
  return values.reduce((sum, value, index) => (
    sum + ((2 ** value) - 1) / Math.log2(index + 2)
  ), 0);
}

function summarizeRows(rows) {
  const required = rows.flatMap(row => Object.entries(row.required_primary_ranks).map(([id, rank]) => ({
    id,
    rank,
    queryId: row.id,
  })));
  const queryScores = rows.map(row => {
    const visible = row.top_10 || [];
    const relevant = visible.filter(item => item.existing_truth?.label === "primary_relevant").length;
    const truthGrades = visible.map(item => grade(item.existing_truth?.label));
    return {
      precision: visible.length ? relevant / visible.length : 1,
      ndcg: Number(row.metrics?.ndcg_at_10_over_current_truth ?? (
        truthGrades.length ? 0 : 1
      )),
    };
  });
  const visible = rows.flatMap(row => row.top_10 || []);
  return {
    query_count: rows.length,
    required_anchor_count: required.length,
    primary_precision_at_10: number(
      queryScores.reduce((sum, item) => sum + item.precision, 0) / Math.max(1, queryScores.length),
    ),
    required_primary_recall_at_10: number(
      required.filter(item => item.rank !== null && item.rank <= 10).length / Math.max(1, required.length),
    ),
    required_primary_recall_at_50: number(
      required.filter(item => item.rank !== null && item.rank <= 50).length / Math.max(1, required.length),
    ),
    ndcg_at_10: number(
      queryScores.reduce((sum, item) => sum + item.ndcg, 0) / Math.max(1, queryScores.length),
    ),
    visible_primary_count: rows.reduce((sum, row) => sum + row.visible_primary_count, 0),
    maximum_visible_primary_count: Math.max(0, ...rows.map(row => row.visible_primary_count)),
    internal_candidate_count: rows.reduce((sum, row) => sum + row.internal_candidate_count, 0),
    maximum_internal_candidate_count: Math.max(0, ...rows.map(row => row.internal_candidate_count)),
    broader_fit_count: rows.reduce((sum, row) => sum + row.broader_fit_count, 0),
    rejected_partial_intent_count: rows.reduce((sum, row) => sum + row.rejected_partial_intent_count, 0),
    irrelevant_or_unjudged_visible_primary_count: visible.filter(item => (
      item.existing_truth?.label !== "primary_relevant"
    )).length,
    required_anchor_misses_at_50: required.filter(item => item.rank === null || item.rank > 50),
  };
}

async function main() {
  if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
    throw new Error("Local architecture summarizer refuses the sealed Phase-4C population.");
  }
  const [raw, configuration, iteration1Results, iteration2] = await Promise.all([
    readFile(new URL(RAW_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL("config/search_v2.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("evaluation/search_v2_holdout_results.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("evaluation/search_v2_release_candidate_v2.json", ROOT), "utf8").then(JSON.parse),
  ]);
  if (raw.sealed_phase4c_read_or_executed !== false) throw new Error("Unsafe spent-set input.");
  const rows = raw.populations.flatMap(population => (
    population.results.map(row => ({ ...row, population: population.id }))
  ));
  const byPopulation = Object.fromEntries(raw.populations.map(population => [
    population.id,
    summarizeRows(population.results),
  ]));
  const byFamily = Object.fromEntries([...new Set(rows.map(row => family(row.id)))].sort().map(id => [
    id,
    summarizeRows(rows.filter(row => family(row.id) === id)),
  ]));
  const requiredPrograms = new Map();
  rows.forEach(row => Object.entries(row.required_primary_ranks).forEach(([id, rank]) => {
    if (!requiredPrograms.has(id)) requiredPrograms.set(id, []);
    requiredPrograms.get(id).push({ query_id: row.id, query: row.query, rank });
  }));
  const byProgram = Object.fromEntries([...requiredPrograms].sort(([left], [right]) => (
    left.localeCompare(right)
  )).map(([id, checks]) => [id, {
    required_anchor_checks: checks.length,
    recall_at_10: number(checks.filter(item => item.rank !== null && item.rank <= 10).length / checks.length),
    recall_at_50: number(checks.filter(item => item.rank !== null && item.rank <= 50).length / checks.length),
    checks,
  }]));
  const mappings = {
    concept_families: configuration.concept_families?.length || 0,
    controlled_relationships: configuration.controlled_relationships?.length || 0,
    source_scope_relationships: configuration.source_scope_relationships?.length || 0,
    authoritative_scope_entailments: configuration.authoritative_scope_entailments?.length || 0,
    broader_program_fits: configuration.broader_program_fits?.length || 0,
  };
  const output = {
    schema_version: 1,
    architecture_reset: "local_fielded_ir",
    status: "development_measurement_complete_not_phase4c_acceptance",
    sealed_phase4c_read_or_executed: false,
    architecture: {
      ranking: configuration.fielded_ranking?.architecture,
      configured_scientific_relationships_used: false,
      active_manual_relationship_mappings: mappings,
      fields: Object.keys(configuration.fielded_ranking?.field_weights || {}),
      parent_rollup: configuration.fielded_ranking?.parent_rollup,
      child_count_bonus: configuration.fielded_ranking?.child_count_bonus,
    },
    combined: summarizeRows(rows),
    by_population: byPopulation,
    by_family: byFamily,
    by_required_program: byProgram,
    latency_ms: raw.query_time_ms,
    comparison: {
      phase4_iteration1_before: iteration1Results.aggregate_metrics,
      phase4b_iteration2_before: iteration2.phase4b_metrics,
    },
  };
  const leaveout = {
    schema_version: 1,
    architecture_reset: "local_fielded_ir",
    status: "leave_program_and_family_out_development_evidence",
    sealed_phase4c_read_or_executed: false,
    methodology: "Every scientific relationship family and program-specific scope contract is withheld globally: all active mapping counts are zero, and the scorer reports configuredScientificEntailmentsUsed=false. Family and program slices therefore measure the same untuned fielded architecture without per-slice rules.",
    active_manual_relationship_mappings: mappings,
    invariant_verified: Object.values(mappings).every(value => value === 0),
    family_out_metrics: byFamily,
    program_out_metrics: byProgram,
  };
  await Promise.all([
    writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(output, null, 2)}\n`, "utf8"),
    writeFile(new URL(LEAVEOUT_PATH, ROOT), `${JSON.stringify(leaveout, null, 2)}\n`, "utf8"),
  ]);
  console.log(JSON.stringify({
    results: RESULTS_PATH,
    leaveout: LEAVEOUT_PATH,
    combined: output.combined,
    by_family: byFamily,
    invariant_verified: leaveout.invariant_verified,
  }, null, 2));
}

await main();
