#!/usr/bin/env node
// Phase 4 one-time holdout executor. This file does not tune or adjudicate.

import { createHash } from "node:crypto";
import { access, readFile, writeFile } from "node:fs/promises";
import process from "node:process";

import {
  loadHarness,
  makeVariantHarness,
  rankQuery,
} from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const PREOPEN_PATH = "evaluation/search_v2_phase4_preopen.json";
const HOLDOUT_PATH = "evaluation/search_v2_holdout_frame.json";
const RAW_RESULTS_PATH = "evaluation/search_v2_holdout_results_raw.json";
const BROAD_OPPORTUNITY_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science financial assistance|long[\s-]?range|research announcement|research interests of|established program to stimulate competitive research|research collaboration|\broses\b|omnibus|unsolicited proposal|open topic|financial assistance program|annual program statement|office[ -]wide|open[ -]scope solicitation/i;

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

async function source(path) {
  return readFile(new URL(path, ROOT), "utf8");
}

async function assertAbsent(path) {
  try {
    await access(new URL(path, ROOT));
    throw new Error(`${path} already exists; the holdout executor is single-use.`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function compactEvidence(evidence) {
  if (!evidence) return null;
  return {
    admission: evidence.admission || null,
    authoritative_scope: evidence.authoritativeScope || null,
    exact_title_phrase: evidence.exactTitlePhrase === true,
    exact_opportunity_number: evidence.exactOpportunityNumber === true,
    trigrams: Array.from(evidence.trigrams || []),
    groups: (evidence.groups || []).map(group => ({
      source: group.source,
      contribution: number(group.contribution),
      matched_terms: (group.matchedTermContributions || []).map(item => ({
        term: item.term,
        contribution: number(item.contribution),
      })),
    })),
  };
}

function compactRow(harness, row, rank, query, includeExplanation) {
  const parentEvidence = row.parentDirectEvidence || null;
  const bestChild = row.bestChild || null;
  const broad = BROAD_OPPORTUNITY_RE.test(
    `${row.record.title || ""} ${String(row.record.description || "").slice(0, 1_500)}`,
  );
  const explanation = includeExplanation
    ? harness.explanationApi.buildV2({
      query,
      parent: { record: row.record, broad, directEvidence: parentEvidence },
      bestChild,
      childDroveMatch: row.childDroveMatch,
      parentAdmitted: row.parentAdmitted,
    })
    : null;
  return {
    rank,
    id: row.id,
    number: row.record.opportunity_number || "",
    title: row.record.title || "",
    agency: row.record.agency || "",
    status: row.record.status || "",
    source_type: row.record.source_type || "",
    official_url: row.record.official_url || row.record.url || "",
    topic_areas: row.record.topic_areas || [],
    description_excerpt: String(row.record.description || "").slice(0, 1_200),
    score: number(row.score),
    parent_admitted: row.parentAdmitted,
    parent_score: number(row.parentRaw),
    child_score: number(bestChild?.raw || 0),
    child_drove_match: row.childDroveMatch,
    best_child: bestChild ? {
      id: bestChild.id,
      title: bestChild.record.title || "",
      summary_excerpt: String(bestChild.record.summary || "").slice(0, 1_200),
      publication_state: bestChild.record.publication_state || "",
      program_area_labels: bestChild.record.program_area_labels || [],
      evidence: compactEvidence(bestChild.directEvidence),
    } : null,
    parent_evidence: compactEvidence(parentEvidence),
    explanation,
  };
}

async function execute() {
  if (!process.argv.includes("--execute-once")) {
    throw new Error("Phase 4 holdout execution requires the explicit --execute-once flag.");
  }
  await assertAbsent(RAW_RESULTS_PATH);

  const preopenSource = await source(PREOPEN_PATH);
  const preopen = JSON.parse(preopenSource);
  if (preopen.status !== "candidate_frozen_before_holdout_open") {
    throw new Error("The Phase 4 pre-open checkpoint is not frozen.");
  }
  if (preopen.holdout_status !== "sealed_and_unopened") {
    throw new Error("The pre-open checkpoint does not certify a sealed holdout.");
  }
  for (const [path, expected] of Object.entries(preopen.hashes || {})) {
    const current = sha256(await source(path));
    if (current !== expected) throw new Error(`Frozen input hash mismatch: ${path}`);
  }

  const holdoutSource = await source(HOLDOUT_PATH);
  const holdout = JSON.parse(holdoutSource);
  if (holdout.status !== "sealed" || holdout.unlock_phase !== 4) {
    throw new Error("The registered holdout is not eligible for Phase 4 execution.");
  }
  if (holdout.queries?.length !== 24) {
    throw new Error("The registered holdout must contain exactly 24 queries.");
  }
  const queryIds = holdout.queries.map(item => item.id);
  const queryText = holdout.queries.map(item => item.query.toLowerCase());
  if (new Set(queryIds).size !== queryIds.length || new Set(queryText).size !== queryText.length) {
    throw new Error("The registered holdout contains duplicate query IDs or text.");
  }

  const production = await loadHarness();
  const candidate = makeVariantHarness(production, { searchV2: true });
  const results = [];
  for (const item of holdout.queries) {
    const oldRanked = rankQuery(production, item.query, { evidence: true });
    const newRanked = rankQuery(candidate, item.query, { evidence: true });
    const oldTop10 = oldRanked.rows.slice(0, 10).map((row, index) => (
      compactRow(production, row, index + 1, item.query, false)
    ));
    const newTop50 = newRanked.rows.slice(0, 50).map((row, index) => (
      compactRow(candidate, row, index + 1, item.query, true)
    ));
    const newTop10Ids = newTop50.slice(0, 10).map(row => row.id);
    const oldTop10Ids = oldTop10.map(row => row.id);
    results.push({
      id: item.id,
      stratum: item.stratum,
      discipline: item.discipline,
      query: item.query,
      production_candidate_count: oldRanked.rows.length,
      candidate_count: newRanked.rows.length,
      production_latency_ms: number(oldRanked.latencyMs),
      candidate_latency_ms: number(newRanked.latencyMs),
      query_plan: newRanked.diagnostics.searchV2.queryPlan,
      minimum_coverage: newRanked.diagnostics.minimumCoverage,
      short_complete_coverage: newRanked.diagnostics.searchV2.shortCompleteCoverage,
      authoritative_scope_entailments: newRanked.diagnostics.searchV2.authoritativeScopeEntailments,
      production_top_10: oldTop10,
      candidate_top_50: newTop50,
      added_to_top_10: newTop10Ids.filter(id => !oldTop10Ids.includes(id)),
      removed_from_top_10: oldTop10Ids.filter(id => !newTop10Ids.includes(id)),
      top_10_changed: JSON.stringify(oldTop10Ids) !== JSON.stringify(newTop10Ids),
    });
  }

  const payload = {
    schema_version: 1,
    executed_at: new Date().toISOString(),
    phase: 4,
    status: "holdout_executed_unadjudicated",
    execution_count: 1,
    post_outcome_tuning_permitted: false,
    candidate_code_sha: preopen.candidate_code_sha,
    preopen_checkpoint: PREOPEN_PATH,
    preopen_checkpoint_sha256: sha256(preopenSource),
    holdout_frame: HOLDOUT_PATH,
    holdout_frame_sha256: sha256(holdoutSource),
    query_count: results.length,
    production_enabled: false,
    results,
  };
  await writeFile(
    new URL(RAW_RESULTS_PATH, ROOT),
    `${JSON.stringify(payload, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(
    `Phase 4 holdout executed once: ${results.length} queries; results unadjudicated.\n`,
  );
}

await execute();
