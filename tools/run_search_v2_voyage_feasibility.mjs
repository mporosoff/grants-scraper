#!/usr/bin/env node

// Disposable development-only Voyage reranker feasibility harness.
//
// This tool reads only the two spent acceptance populations. It imports the
// unchanged production search modules for BM25F candidate discovery, sends
// compact passages made only from public indexed fields to Voyage, and never
// changes primary admission or explanations. Phase 4C inputs are refused by
// name and are not imported anywhere in this file.

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const RESULTS_PATH = "evaluation/search_v2_voyage_reranker_results.json";
const RECEIPT_PATH = "evaluation/search_v2_voyage_api_receipt.json";
const CANDIDATE_CEILING_PATH = "evaluation/search_v2_voyage_candidate_ceiling.json";
const AUDIT_PATH = "evaluation/search_v2_local_field_feasibility.json";
const MINILM_PATH = "evaluation/search_v2_local_minilm_results.json";
const LEAVEOUT_PATH = "evaluation/search_v2_local_architecture_leaveout.json";
const API_URL = "https://api.voyageai.com/v1/rerank";
const MODEL = "rerank-2.5";
const CANDIDATE_DEPTH = 200;
const MAX_PASSAGE_CHARS = 3_000;
const REQUEST_TIMEOUT_MS = 120_000;
const PRICE_PER_MILLION_TOKENS_USD = 0.05;
const PUBLISHED_FREE_TOKENS = 200_000_000;
const QUERY_INSTRUCTION = "Rank public funding opportunities by whether their authoritative scientific or programmatic scope supports the complete research intent. Do not reward partial word overlap when a major query concept is absent.\n\nResearch query: <QUERY>";
const POPULATIONS = Object.freeze([
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
]);
const FROZEN_FILES = Object.freeze([
  "assets/search-query.js",
  "assets/search-retrieval.js",
  "assets/match-explain.js",
  "assets/app.js",
  "assets/app-config.js",
  "config/search_v2.json",
  "evaluation/search_v2_iteration3_holdout_frame.json",
  "evaluation/search_v2_iteration3_holdout_manifest.json",
]);

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const ordered = values.filter(value => Number.isFinite(value)).sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0;
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

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function uniqueText(values) {
  const seen = new Set();
  return values.flatMap(value => {
    const normalized = normalizeText(value);
    if (!normalized || seen.has(normalized)) return [];
    seen.add(normalized);
    return [normalized];
  });
}

function clipped(value, limit) {
  const text = normalizeText(value);
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit);
  const boundary = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("; "), cut.lastIndexOf(" "));
  return `${cut.slice(0, Math.max(Math.floor(limit * .8), boundary))}…`;
}

function labeled(label, values, limit) {
  const text = clipped(uniqueText(values).join("; "), limit);
  return text ? `${label}: ${text}` : "";
}

function boundedPassage(parts) {
  const text = parts.filter(Boolean).join("\n");
  return clipped(text, MAX_PASSAGE_CHARS);
}

function authoritativeSourceEvidence(record) {
  return ((record?.document_evidence?.facts || []))
    .filter(fact => fact?.type === "review_criteria")
    .flatMap(fact => [fact.value, fact.citation?.quote])
    .filter(Boolean);
}

function parentPassage(record) {
  const fieldValues = {
    parent_title: [record.title],
    authoritative_program_area: record.program_area_labels || record.document_program_areas || [],
    parent_description: [record.description],
    bounded_source_evidence: authoritativeSourceEvidence(record),
  };
  return {
    fields: Object.entries(fieldValues).flatMap(([field, values]) => (
      uniqueText(values).length ? [field] : []
    )),
    text: boundedPassage([
      labeled("Parent title", fieldValues.parent_title, 500),
      labeled("Authoritative program area", fieldValues.authoritative_program_area, 600),
      labeled("Parent description", fieldValues.parent_description, 1_650),
      labeled("Public source evidence", fieldValues.bounded_source_evidence, 1_200),
    ]),
  };
}

function childPassage(record, parent) {
  const fieldValues = {
    parent_title: [parent?.title],
    child_title: [record.title],
    child_summary: [record.description || record.summary],
    authoritative_program_area: record.program_area_labels || [],
  };
  return {
    fields: Object.entries(fieldValues).flatMap(([field, values]) => (
      uniqueText(values).length ? [field] : []
    )),
    text: boundedPassage([
      labeled("Parent title", fieldValues.parent_title, 500),
      labeled("Publication-eligible child title", fieldValues.child_title, 700),
      labeled("Authoritative program area", fieldValues.authoritative_program_area, 600),
      labeled("Child summary", fieldValues.child_summary, 2_000),
    ]),
  };
}

function scoreScale(values) {
  const positive = values.filter(value => value > 0);
  return Math.max(1e-9, percentile(positive, .9));
}

function buildCandidatePassages(harness, ranked) {
  const parentScores = Array.from(ranked.parentDirect.discoveryScores || []);
  const childScores = Array.from(ranked.childDirect.discoveryScores || []);
  const parentScale = scoreScale(parentScores);
  const childScale = scoreScale(childScores);
  const rejectedParentIndexes = new Set(ranked.parentDirect.currentnessRejectedIndexes || []);
  const parentById = new Map(harness.parentCatalog.opportunities.map(record => (
    [String(record.opportunity_id), record]
  )));
  const candidates = [];
  harness.parentCatalog.opportunities.forEach((record, index) => {
    const rawScore = Number(parentScores[index] || 0);
    if (!(rawScore > 0) || rejectedParentIndexes.has(index) || record.status === "archived") return;
    const passage = parentPassage(record);
    if (!passage.text) return;
    candidates.push({
      parent_id: String(record.opportunity_id),
      passage_id: `parent:${record.opportunity_id}`,
      passage_kind: "parent",
      record_id: String(record.opportunity_id),
      title: record.title || "",
      fields: passage.fields,
      text: passage.text,
      bm25f_raw_score: rawScore,
      bm25f_candidate_score: rawScore / parentScale,
    });
  });
  harness.childCatalog.opportunities.forEach((record, index) => {
    const rawScore = Number(childScores[index] || 0);
    const parentId = String(record.parent_id || "");
    const parent = parentById.get(parentId);
    if (!(rawScore > 0) || !parent) return;
    const passage = childPassage(record, parent);
    if (!passage.text) return;
    candidates.push({
      parent_id: parentId,
      passage_id: `child:${record.subtopic_id || record.opportunity_id}`,
      passage_kind: "publication_eligible_child",
      record_id: String(record.subtopic_id || record.opportunity_id),
      title: record.title || "",
      fields: passage.fields,
      text: passage.text,
      bm25f_raw_score: rawScore,
      bm25f_candidate_score: rawScore / childScale,
    });
  });
  return candidates.sort((left, right) => (
    right.bm25f_candidate_score - left.bm25f_candidate_score
    || right.bm25f_raw_score - left.bm25f_raw_score
    || left.passage_id.localeCompare(right.passage_id)
  ));
}

function strongestParents(passages, scoreKey) {
  const byParent = new Map();
  passages.forEach(passage => {
    const current = byParent.get(passage.parent_id);
    if (
      !current
      || Number(passage[scoreKey]) > Number(current[scoreKey])
      || (
        Number(passage[scoreKey]) === Number(current[scoreKey])
        && passage.passage_id.localeCompare(current.passage_id) < 0
      )
    ) byParent.set(passage.parent_id, passage);
  });
  return [...byParent.values()].sort((left, right) => (
    Number(right[scoreKey]) - Number(left[scoreKey])
    || right.bm25f_candidate_score - left.bm25f_candidate_score
    || left.parent_id.localeCompare(right.parent_id)
  ));
}

function metrics(ids, queryTruth) {
  const top10 = ids.slice(0, 10);
  const required = queryTruth.required_primary_ids || [];
  const judgments = queryTruth.judgments || {};
  const judged = top10.filter(id => judgments[id]);
  const primary = top10.filter(id => judgments[id]?.label === "primary_relevant");
  return {
    returned_at_10: top10.length,
    judged_at_10: judged.length,
    primary_at_10: primary.length,
    precision_at_10_conservative: top10.length ? number(primary.length / top10.length) : 1,
    precision_at_10_over_judged: judged.length ? number(primary.length / judged.length) : null,
    unjudged_at_10: top10.filter(id => !judgments[id]),
    judged_irrelevant_at_10: top10.filter(id => judgments[id]?.label === "irrelevant"),
    judged_broader_at_10: top10.filter(id => judgments[id]?.label === "broader_program_fit"),
    required_recall_at_10: required.length
      ? number(required.filter(id => top10.includes(id)).length / required.length)
      : 1,
    required_recall_at_50: required.length
      ? number(required.filter(id => ids.slice(0, 50).includes(id)).length / required.length)
      : 1,
    required_ranks: Object.fromEntries(required.map(id => {
      const rank = ids.indexOf(id);
      return [id, rank < 0 ? null : rank + 1];
    })),
  };
}

function resultEntry(passages, queryTruth, scoreKey) {
  const strongest = strongestParents(passages, scoreKey);
  const ids = strongest.map(item => item.parent_id);
  return {
    parent_count: strongest.length,
    metrics: metrics(ids, queryTruth),
    top_10: strongest.slice(0, 10).map(item => ({
      id: item.parent_id,
      score: number(item[scoreKey]),
      passage_id: item.passage_id,
      passage_kind: item.passage_kind,
      record_id: item.record_id,
      title: item.title,
      fields: item.fields,
      existing_truth: queryTruth.judgments?.[item.parent_id]?.label || null,
    })),
  };
}

function summarize(rows, resultKey) {
  const entries = rows.map(row => row[resultKey]);
  const requiredRanks = entries.flatMap(entry => Object.values(entry.metrics.required_ranks));
  const top10 = entries.flatMap(entry => entry.top_10);
  const judged = top10.filter(entry => entry.existing_truth);
  const primary = judged.filter(entry => entry.existing_truth === "primary_relevant");
  return {
    query_count: entries.length,
    required_anchor_count: requiredRanks.length,
    required_recall_at_10: number(
      requiredRanks.filter(rank => rank !== null && rank <= 10).length / Math.max(1, requiredRanks.length),
    ),
    required_recall_at_50: number(
      requiredRanks.filter(rank => rank !== null && rank <= 50).length / Math.max(1, requiredRanks.length),
    ),
    required_candidate_recall_at_depth: number(
      requiredRanks.filter(rank => rank !== null).length / Math.max(1, requiredRanks.length),
    ),
    precision_at_10_conservative_lower_bound: number(primary.length / Math.max(1, top10.length)),
    precision_at_10_over_judged: judged.length ? number(primary.length / judged.length) : null,
    judged_primary_top_10_count: primary.length,
    judged_irrelevant_top_10_count: judged.filter(entry => entry.existing_truth === "irrelevant").length,
    judged_broader_top_10_count: judged.filter(entry => entry.existing_truth === "broader_program_fit").length,
    unjudged_top_10_count: top10.filter(entry => !entry.existing_truth).length,
  };
}

function rankMovements(rows) {
  return rows.flatMap(row => Object.entries(row.voyage_reranked.metrics.required_ranks).map(([id, voyage]) => ({
    population: row.population,
    query_id: row.id,
    query: row.query,
    required_result_id: id,
    bm25f_rank: row.baseline_candidate.metrics.required_ranks[id] ?? null,
    voyage_rank: voyage,
    movement: voyage === null || row.baseline_candidate.metrics.required_ranks[id] === null
      ? null
      : row.baseline_candidate.metrics.required_ranks[id] - voyage,
  })));
}

function summarizeAnchorSlice(anchors, rowById) {
  const movements = anchors.map(anchor => {
    const row = rowById.get(anchor.query_id);
    return {
      query_id: anchor.query_id,
      required_result_id: anchor.required_result_id,
      bm25f_rank: row?.baseline_candidate.metrics.required_ranks[anchor.required_result_id] ?? null,
      voyage_rank: row?.voyage_reranked.metrics.required_ranks[anchor.required_result_id] ?? null,
    };
  });
  return {
    anchor_count: movements.length,
    bm25f_recall_at_10: number(movements.filter(item => item.bm25f_rank !== null && item.bm25f_rank <= 10).length / Math.max(1, movements.length)),
    bm25f_recall_at_50: number(movements.filter(item => item.bm25f_rank !== null && item.bm25f_rank <= 50).length / Math.max(1, movements.length)),
    voyage_recall_at_10: number(movements.filter(item => item.voyage_rank !== null && item.voyage_rank <= 10).length / Math.max(1, movements.length)),
    voyage_recall_at_50: number(movements.filter(item => item.voyage_rank !== null && item.voyage_rank <= 50).length / Math.max(1, movements.length)),
    candidate_recall_at_depth: number(movements.filter(item => item.bm25f_rank !== null).length / Math.max(1, movements.length)),
    newly_recovered_at_10: movements.filter(item => (
      item.voyage_rank !== null && item.voyage_rank <= 10
      && (item.bm25f_rank === null || item.bm25f_rank > 10)
    )).length,
    regressions_from_top_10: movements.filter(item => (
      item.bm25f_rank !== null && item.bm25f_rank <= 10
      && (item.voyage_rank === null || item.voyage_rank > 10)
    )).length,
    movements,
  };
}

function aggregateBy(anchors, rowById, keyFunction) {
  const groups = new Map();
  anchors.forEach(anchor => {
    const key = keyFunction(anchor);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(anchor);
  });
  return Object.fromEntries([...groups.entries()].sort(([left], [right]) => left.localeCompare(right)).map(
    ([key, values]) => [key, summarizeAnchorSlice(values, rowById)],
  ));
}

async function sha256File(path) {
  return createHash("sha256").update(await readFile(new URL(path, ROOT))).digest("hex");
}

function currentGitState() {
  const executable = process.env.FF_GIT_EXECUTABLE || "git";
  const git = (...arguments_) => execFileSync(executable, arguments_, {
    cwd: fileURLToPath(ROOT),
    encoding: "utf8",
  }).trim();
  return {
    branch: git("branch", "--show-current"),
    head: git("rev-parse", "HEAD"),
    origin_branch: git("rev-parse", "origin/search-quality-v2"),
    main: git("rev-parse", "main"),
    origin_main: git("rev-parse", "origin/main"),
  };
}

async function frozenHashes() {
  return Object.fromEntries(await Promise.all(FROZEN_FILES.map(async path => [path, await sha256File(path)])));
}

function voyageQuery(query) {
  return QUERY_INSTRUCTION.replace("<QUERY>", query);
}

async function rerankVoyage(apiKey, query, passages) {
  const body = {
    query: voyageQuery(query),
    documents: passages.map(item => item.text),
    model: MODEL,
    top_k: passages.length,
    return_documents: false,
    truncation: true,
  };
  const serialized = JSON.stringify(body);
  const started = performance.now();
  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: serialized,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  const responseText = await response.text();
  const latencyMs = performance.now() - started;
  let payload;
  try {
    payload = JSON.parse(responseText);
  } catch {
    throw new Error(`Voyage returned non-JSON response with HTTP ${response.status}.`);
  }
  if (!response.ok) {
    const message = normalizeText(payload?.detail || payload?.message || payload?.error || "request failed");
    throw new Error(`Voyage rerank failed with HTTP ${response.status}: ${message.slice(0, 300)}`);
  }
  const rankings = payload.data || payload.results;
  if (!Array.isArray(rankings) || rankings.length !== passages.length) {
    throw new Error(`Voyage returned ${rankings?.length ?? "no"} rankings for ${passages.length} passages.`);
  }
  const scored = rankings.map(result => {
    const passage = passages[Number(result.index)];
    if (!passage) throw new Error(`Voyage returned invalid document index: ${result.index}`);
    return { ...passage, voyage_score: Number(result.relevance_score) };
  });
  return {
    scored,
    receipt: {
      http_status: response.status,
      request_id: response.headers.get("request-id") || response.headers.get("x-request-id") || null,
      model: payload.model || MODEL,
      usage_total_tokens: Number(payload.usage?.total_tokens || 0),
      request_payload_bytes: Buffer.byteLength(serialized, "utf8"),
      response_payload_bytes: Buffer.byteLength(responseText, "utf8"),
      latency_ms: number(latencyMs),
    },
  };
}

async function loadPopulationInputs() {
  return Promise.all(POPULATIONS.map(async population => ({
    ...population,
    frameData: JSON.parse(await readFile(new URL(population.frame, ROOT), "utf8")),
    truthData: JSON.parse(await readFile(new URL(population.truth, ROOT), "utf8")),
  })));
}

async function run() {
  const dryRun = process.argv.includes("--dry-run");
  const write = process.argv.includes("--write");
  const priorRateLimitAttempts = Number(
    process.argv.find(argument => argument.startsWith("--prior-rate-limit-attempts="))?.split("=")[1] || 0,
  );
  const apiKey = process.env.VOYAGE_API_KEY;
  if (!dryRun && !apiKey) throw new Error("VOYAGE_API_KEY is required and must remain process-local.");
  const [base, populations, audit, minilm, leaveout, hashesBefore] = await Promise.all([
    loadHarness(),
    loadPopulationInputs(),
    readFile(new URL(AUDIT_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(MINILM_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(LEAVEOUT_PATH, ROOT), "utf8").then(JSON.parse),
    frozenHashes(),
  ]);
  const activeMappings = Object.values(leaveout.active_manual_relationship_mappings || {});
  if (activeMappings.some(Number)) {
    throw new Error("Voyage leave-out comparison requires zero active manual relationship mappings.");
  }
  const candidate = makeVariantHarness(base, { searchV2: true });
  const items = populations.flatMap(population => population.frameData.queries.map(item => ({
    population,
    item,
  })));
  const rows = [];
  const receipts = [];
  for (const [index, { population, item }] of items.entries()) {
    const queryTruth = population.truthData.queries[item.id];
    if (!queryTruth || queryTruth.query !== item.query) {
      throw new Error(`Spent query/truth mismatch: ${item.id}`);
    }
    const bm25fStarted = performance.now();
    const ranked = rankQuery(candidate, item.query, { evidence: true });
    const passages = buildCandidatePassages(candidate, ranked).slice(0, CANDIDATE_DEPTH);
    const bm25fMs = performance.now() - bm25fStarted;
    if (!passages.length) throw new Error(`No BM25F candidate passages for ${item.id}.`);
    const baseline = resultEntry(passages, queryTruth, "bm25f_candidate_score");
    let voyage = null;
    if (!dryRun) voyage = await rerankVoyage(apiKey, item.query, passages);
    const reranked = voyage
      ? resultEntry(voyage.scored, queryTruth, "voyage_score")
      : baseline;
    if (voyage) receipts.push({ population: population.id, query_id: item.id, ...voyage.receipt });
    rows.push({
      population: population.id,
      id: item.id,
      query: item.query,
      family: family(item.id),
      discipline: item.discipline || "",
      stratum: item.stratum || "",
      required_primary_ids: queryTruth.required_primary_ids || [],
      zero_primary_hard_negative: !(queryTruth.required_primary_ids || []).length
        && !Object.values(queryTruth.judgments || {}).some(value => value.label === "primary_relevant"),
      bm25f_ms: number(bm25fMs),
      discovered_candidate_passage_count: passages.length,
      candidate_payload_text_bytes: passages.reduce(
        (sum, passage) => sum + Buffer.byteLength(passage.text, "utf8"),
        0,
      ),
      baseline_candidate: baseline,
      voyage_reranked: reranked,
      api: voyage?.receipt || null,
    });
    process.stderr.write(
      `[${index + 1}/${items.length}] ${item.id} passages=${passages.length}`
      + `${voyage ? ` latency_ms=${voyage.receipt.latency_ms} tokens=${voyage.receipt.usage_total_tokens}` : " dry-run"}\n`,
    );
  }
  const rowById = new Map(rows.map(row => [row.id, row]));
  const requiredMovements = rankMovements(rows);
  const auditAnchors = audit.rows;
  const vocabularyGapAnchors = audit.rows.filter(row => (
    row.conventional_fielded_feasibility === "INSUFFICIENT_INDEXED_TEXT_FOR_CONVENTIONAL_RANKING"
  ));
  const baselineTop10ByQuery = new Map(rows.map(row => [
    row.id,
    new Set(row.baseline_candidate.top_10.map(item => item.id)),
  ]));
  const knownIrrelevantPromotions = rows.flatMap(row => row.voyage_reranked.top_10
    .filter(item => item.existing_truth === "irrelevant" && !baselineTop10ByQuery.get(row.id).has(item.id))
    .map(item => ({
      population: row.population,
      query_id: row.id,
      query: row.query,
      result_id: item.id,
      title: item.title,
      voyage_rank: row.voyage_reranked.top_10.findIndex(value => value.id === item.id) + 1,
    })));
  const hardNegativeRows = rows.filter(row => row.zero_primary_hard_negative);
  const totalTokens = receipts.reduce((sum, receipt) => sum + receipt.usage_total_tokens, 0);
  const apiLatencies = receipts.map(receipt => receipt.latency_ms);
  const totalLatencies = rows.map(row => row.bm25f_ms + Number(row.api?.latency_ms || 0));
  const payloadSizes = receipts.map(receipt => receipt.request_payload_bytes);
  const hashesAfter = await frozenHashes();
  const frozenDrift = Object.keys(hashesBefore).filter(path => hashesBefore[path] !== hashesAfter[path]);
  if (frozenDrift.length) throw new Error(`Frozen production/Phase-4C files drifted: ${frozenDrift.join(", ")}`);
  const summary = {
    baseline_bm25f_at_depth_200: summarize(rows, "baseline_candidate"),
    voyage_reranked_at_depth_200: summarize(rows, "voyage_reranked"),
    minilm_at_depth_50: minilm.quality.summary.minilm_reranked_candidate[50],
    required_anchor_movements: requiredMovements,
    phase4b_19_anchor_audit: summarizeAnchorSlice(auditAnchors, rowById),
    vocabulary_gap_16_anchor_audit: summarizeAnchorSlice(vocabularyGapAnchors, rowById),
    leave_family_out: aggregateBy(auditAnchors, rowById, anchor => family(anchor.query_id)),
    leave_program_out: aggregateBy(auditAnchors, rowById, anchor => anchor.required_result_id),
    known_irrelevant_promotions_into_top_10: knownIrrelevantPromotions,
    zero_primary_hard_negatives: {
      query_count: hardNegativeRows.length,
      voyage_top_10_known_primary_count: hardNegativeRows.reduce(
        (sum, row) => sum + row.voyage_reranked.top_10.filter(item => item.existing_truth === "primary_relevant").length,
        0,
      ),
      voyage_top_10_known_irrelevant_count: hardNegativeRows.reduce(
        (sum, row) => sum + row.voyage_reranked.top_10.filter(item => item.existing_truth === "irrelevant").length,
        0,
      ),
      voyage_top_10_unjudged_count: hardNegativeRows.reduce(
        (sum, row) => sum + row.voyage_reranked.top_10.filter(item => !item.existing_truth).length,
        0,
      ),
      known_irrelevant_promotions_into_top_10: knownIrrelevantPromotions.filter(item => (
        hardNegativeRows.some(row => row.id === item.query_id)
      )),
      semantic_scores_create_primary_admission: false,
    },
  };
  const outputQuality = dryRun ? {
    baseline_bm25f_at_depth_200: summary.baseline_bm25f_at_depth_200,
    minilm_at_depth_50: summary.minilm_at_depth_50,
    theoretical_voyage_recall_ceiling: {
      all_65_required_anchors: summary.baseline_bm25f_at_depth_200.required_candidate_recall_at_depth,
      phase4b_19_anchor_audit: summary.phase4b_19_anchor_audit.candidate_recall_at_depth,
      vocabulary_gap_16_anchor_audit: summary.vocabulary_gap_16_anchor_audit.candidate_recall_at_depth,
      screening_threshold_recall_at_50: .85,
      threshold_reachable_from_frozen_candidate_pool: (
        summary.baseline_bm25f_at_depth_200.required_candidate_recall_at_depth >= .85
      ),
      invariant: "A reranker cannot recover an anchor absent from its candidate passages.",
      all_required_anchor_candidate_ranks: requiredMovements.map(item => ({
        population: item.population,
        query_id: item.query_id,
        query: item.query,
        required_result_id: item.required_result_id,
        bm25f_candidate_rank: item.bm25f_rank,
        voyage_rank: null,
        voyage_rank_reason: "API request rejected before scoring; no Voyage rank exists",
      })),
      phase4b_19_anchor_candidate_ranks: summary.phase4b_19_anchor_audit.movements.map(item => ({
        ...item,
        voyage_rank: null,
      })),
      vocabulary_gap_16_anchor_candidate_ranks: summary.vocabulary_gap_16_anchor_audit.movements.map(item => ({
        ...item,
        voyage_rank: null,
      })),
    },
  } : summary;
  const gitState = currentGitState();
  const receipt = {
    schema_version: 1,
    experiment: "voyage_rerank_2_5_realtime_feasibility",
    generated_at: new Date().toISOString(),
    mode: dryRun ? "dry_run_no_api_calls" : "ordinary_realtime_api",
    provider: "Voyage AI",
    endpoint: API_URL,
    model: MODEL,
    provider_model_revision: "not exposed by the real-time rerank API",
    return_documents: false,
    truncation: true,
    candidate_depth: CANDIDATE_DEPTH,
    passage_character_cap: MAX_PASSAGE_CHARS,
    fixed_query_instruction: QUERY_INSTRUCTION,
    successful_request_count: receipts.length,
    total_request_attempt_count: receipts.length + priorRateLimitAttempts,
    prior_rejected_transport_attempts: priorRateLimitAttempts ? [{
      count: priorRateLimitAttempts,
      query_id: "hold_ree_01",
      http_status: 429,
      cause: "provider no-payment rate limit before the user added a payment method",
      documents_scored: 0,
      usage_tokens_returned: 0,
    }] : [],
    total_documents_reranked: receipts.reduce((sum, value) => sum + (rows.find(row => row.id === value.query_id)?.discovered_candidate_passage_count || 0), 0),
    usage_total_tokens: totalTokens,
    published_pricing_usd_per_million_tokens: PRICE_PER_MILLION_TOKENS_USD,
    estimated_cost_at_published_paid_pricing_usd: number(totalTokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD),
    published_free_tokens_per_account: PUBLISHED_FREE_TOKENS,
    run_tokens_below_published_free_allocation: totalTokens <= PUBLISHED_FREE_TOKENS,
    remaining_account_free_credit_not_exposed_by_rerank_response: true,
    authentication: {
      source: "VOYAGE_API_KEY process environment variable",
      key_present: Boolean(apiKey),
      key_printed_or_persisted_by_harness: false,
      raw_authorization_headers_persisted: false,
    },
    public_text_contract: [
      "parent_title",
      "parent_description",
      "authoritative_program_area",
      "publication_eligible_child_title",
      "child_summary",
      "bounded_public_source_evidence",
    ],
    excluded_data: [
      "researcher_profiles",
      "CVs",
      "ORCID_information",
      "user_data",
      "private_material",
    ],
    requests: receipts,
  };
  const payload = {
    schema_version: 1,
    experiment: "voyage_rerank_2_5_realtime_feasibility",
    generated_at: new Date().toISOString(),
    status: dryRun ? "dry_run_no_api_calls" : "completed_development_only_no_production_integration",
    git_state: gitState,
    architecture: {
      baseline: "unchanged local BM25F candidate discovery",
      candidate_unit: "bounded authoritative parent or publication-eligible child passage",
      candidate_depth: CANDIDATE_DEPTH,
      reranking: "Voyage rerank-2.5 relevance score",
      parent_aggregation: "single strongest Voyage-scored parent-or-child passage",
      child_count_bonus: 0,
      fixed_generic_instruction: QUERY_INSTRUCTION,
      semantic_score_creates_primary_evidence: false,
      production_explanations_changed: false,
    },
    safety: {
      phase4c_read_or_executed: false,
      phase4c_artifacts_imported: false,
      phase4c_results_created: false,
      production_search_code_changed: false,
      production_model_integration: false,
      backend_or_worker_added: false,
      API_key_committed_or_persisted: false,
      vector_database_or_embeddings_added: false,
      scientific_mappings_added: false,
      generated_program_metadata_added: false,
      frozen_file_hashes_before: hashesBefore,
      frozen_file_hashes_after: hashesAfter,
      frozen_file_drift: frozenDrift,
    },
    evaluation_population: {
      spent_only: true,
      populations: POPULATIONS,
      query_count: rows.length,
      required_anchor_count: requiredMovements.length,
      phase4b_audit_anchor_count: auditAnchors.length,
      vocabulary_gap_anchor_count: vocabularyGapAnchors.length,
      leaveout_invariant: leaveout.invariant_verified,
      active_manual_relationship_mappings: leaveout.active_manual_relationship_mappings,
    },
    quality: outputQuality,
    performance: {
      successful_request_count: receipts.length,
      total_request_attempt_count: receipts.length + priorRateLimitAttempts,
      error_count: priorRateLimitAttempts,
      timeout_count: 0,
      API_latency_p50_ms: number(percentile(apiLatencies, .5)),
      API_latency_p95_ms: number(percentile(apiLatencies, .95)),
      end_to_end_latency_p50_ms: number(percentile(totalLatencies, .5)),
      end_to_end_latency_p95_ms: number(percentile(totalLatencies, .95)),
      BM25F_latency_p50_ms: number(percentile(rows.map(row => row.bm25f_ms), .5)),
      BM25F_latency_p95_ms: number(percentile(rows.map(row => row.bm25f_ms), .95)),
      request_payload_bytes_total: payloadSizes.reduce((sum, value) => sum + value, 0),
      request_payload_bytes_p50: number(percentile(payloadSizes, .5)),
      request_payload_bytes_p95: number(percentile(payloadSizes, .95)),
      candidate_passage_count_total: rows.reduce((sum, row) => sum + row.discovered_candidate_passage_count, 0),
      maximum_candidate_passages_per_query: Math.max(...rows.map(row => row.discovered_candidate_passage_count)),
    },
    API_receipt: RECEIPT_PATH,
    rows: dryRun ? rows.map(row => ({ ...row, voyage_reranked: null, api: null })) : rows,
  };
  if (write) {
    if (dryRun) {
      await writeFile(new URL(CANDIDATE_CEILING_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    } else {
      await writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
      await writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
    }
  }
  const consolePayload = {
    output: write ? (dryRun ? CANDIDATE_CEILING_PATH : RESULTS_PATH) : null,
    receipt: write && !dryRun ? RECEIPT_PATH : null,
    status: payload.status,
    quality: dryRun ? payload.quality : process.argv.includes("--summary-only") ? {
      baseline: payload.quality.baseline_bm25f_at_depth_200,
      voyage: payload.quality.voyage_reranked_at_depth_200,
      minilm: payload.quality.minilm_at_depth_50,
      phase4b_19_anchor_audit: {
        ...payload.quality.phase4b_19_anchor_audit,
        movements: undefined,
      },
      vocabulary_gap_16_anchor_audit: {
        ...payload.quality.vocabulary_gap_16_anchor_audit,
        movements: undefined,
      },
    } : payload.quality,
    performance: payload.performance,
    API_usage: {
      successful_requests: receipt.successful_request_count,
      total_request_attempts: receipt.total_request_attempt_count,
      documents: receipt.total_documents_reranked,
      tokens: receipt.usage_total_tokens,
      estimated_paid_cost_usd: receipt.estimated_cost_at_published_paid_pricing_usd,
    },
  };
  console.log(JSON.stringify(consolePayload, null, 2));
}

if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
  throw new Error("Voyage feasibility harness refuses Phase-4C inputs.");
}

await run();
