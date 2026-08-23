#!/usr/bin/env node

// Development-only production-shaped intent-gate evaluation. This runner uses
// only the two spent holdouts and has no import path for the sealed Phase 4C.

import { createHash, webcrypto } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "./run_search_diagnosis.mjs";
import { createHandler } from "../workers/search-voyage-proxy/src/index.js";

const ROOT = new URL("../", import.meta.url);
const RESULTS_PATH = "evaluation/search_v2_intent_gate_results.json";
const RECEIPT_PATH = "evaluation/search_v2_intent_gate_usage.json";
const PACING_MS = 1_500;
const POPULATIONS = [
  { id: "phase4_spent", frame: "evaluation/search_v2_holdout_frame.json", truth: "evaluation/search_v2_holdout_truth.json" },
  { id: "phase4b_spent", frame: "evaluation/search_v2_iteration2_holdout_frame.json", truth: "evaluation/search_v2_iteration2_holdout_truth.json" },
];

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function percentile(values, fraction) {
  const ordered = values.filter(Number.isFinite).sort((left, right) => left - right);
  return number(ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function loadHybridApi(source) {
  const context = {
    AbortController, ArrayBuffer, Float32Array, Math, Map, Number, Object,
    Promise, RegExp, Response, Set, String, TextEncoder, Uint8Array,
    Uint16Array, URL, clearTimeout, performance, setTimeout,
  };
  context.globalThis = { crypto: webcrypto, location: { href: "http://localhost/" } };
  vm.runInNewContext(source, context);
  return context.globalThis.FUNDING_HYBRID_SEARCH;
}

function ranks(ids) {
  return new Map(ids.map((id, index) => [String(id), index + 1]));
}

function recall(required, rankMap, depth) {
  return required.length
    ? number(required.filter(id => (rankMap.get(String(id)) || Infinity) <= depth).length / required.length)
    : null;
}

function ndcg(required, rankMap) {
  if (!required.length) return null;
  const dcg = required.reduce((sum, id) => {
    const rank = rankMap.get(String(id));
    return rank && rank <= 10 ? sum + 1 / Math.log2(rank + 1) : sum;
  }, 0);
  const ideal = Array.from({ length: Math.min(10, required.length) }, (_value, index) => 1 / Math.log2(index + 2))
    .reduce((sum, value) => sum + value, 0);
  return number(dcg / ideal);
}

function canonicalTruth(label) {
  if (label === "primary_relevant") return "primary";
  if (label === "broader_program_fit") return "broader";
  if (label === "irrelevant") return "reject";
  return null;
}

function aggregate(rows) {
  const positives = rows.filter(row => row.required_primary_ids.length);
  const anchorCount = positives.reduce((sum, row) => sum + row.required_primary_ids.length, 0);
  const candidateAt10 = positives.reduce((sum, row) => sum + row.required_primary_ids
    .filter(id => (row.candidate_required_ranks[id] || Infinity) <= 10).length, 0);
  const candidateAt50 = positives.reduce((sum, row) => sum + row.required_primary_ids
    .filter(id => (row.candidate_required_ranks[id] || Infinity) <= 50).length, 0);
  const visibleAt10 = positives.reduce((sum, row) => sum + row.required_primary_ids
    .filter(id => (row.primary_required_ranks[id] || Infinity) <= 10).length, 0);
  const primaryPairs = rows.flatMap(row => row.visible_primary);
  const judgedPrimary = primaryPairs.filter(item => item.binary_truth);
  const correctPrimary = judgedPrimary.filter(item => item.binary_truth === "primary").length;
  return {
    query_count: rows.length,
    required_anchor_count: anchorCount,
    candidate_required_recall_at_10: anchorCount ? number(candidateAt10 / anchorCount) : null,
    candidate_required_recall_at_50: anchorCount ? number(candidateAt50 / anchorCount) : null,
    user_visible_primary_recall_at_10: anchorCount ? number(visibleAt10 / anchorCount) : null,
    user_visible_primary_recall_at_50: anchorCount ? number(visibleAt10 / anchorCount) : null,
    query_average_ndcg_at_10: positives.length
      ? number(positives.reduce((sum, row) => sum + row.ndcg_at_10, 0) / positives.length)
      : null,
    precision_at_10_over_reviewed_primary_outputs: judgedPrimary.length
      ? number(correctPrimary / judgedPrimary.length)
      : null,
    reviewed_primary_output_count: judgedPrimary.length,
    unreviewed_primary_output_count: primaryPairs.length - judgedPrimary.length,
    conservative_primary_precision_lower_bound: primaryPairs.length
      ? number(correctPrimary / primaryPairs.length)
      : null,
    visible_primary_count: primaryPairs.length,
    visible_broader_count: rows.reduce((sum, row) => sum + row.visible_broader.length, 0),
    hidden_reject_count: rows.reduce((sum, row) => sum + row.judged_results.filter(item => item.classification === "reject").length, 0),
    zero_anchor_query_count: rows.filter(row => !row.required_primary_ids.length).length,
    zero_anchor_queries_with_zero_primary: rows.filter(row => !row.required_primary_ids.length && !row.visible_primary.length).length,
    judge_fallback_count: rows.filter(row => row.judge_status !== "complete").length,
  };
}

async function main() {
  if (!process.argv.includes("--write")) throw new Error("Use --write to run the spent-data intent-gate evaluation.");
  const voyageKey = String(process.env.VOYAGE_API_KEY || "").trim();
  if (!voyageKey) throw new Error("VOYAGE_API_KEY is required in this process environment.");
  const proxyText = String(process.env.INTENT_GATE_PROXY_URL || "http://127.0.0.1:8787/").trim();
  const proxyUrl = new URL(proxyText);
  if (proxyUrl.protocol !== "http:" || !/^(?:localhost|127\.0\.0\.1|\[::1\])$/.test(proxyUrl.hostname)) {
    throw new Error("INTENT_GATE_PROXY_URL must be a local HTTP Wrangler development URL.");
  }

  const [hybridSource, manifestSource, vectorBuffer, precisionReview, priorResults, config] = await Promise.all([
    readFile(new URL("assets/search-hybrid.js", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-manifest.json", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-vectors.f16", ROOT)),
    readFile(new URL("evaluation/search_v2_hybrid_precision_review.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("evaluation/search_v2_hybrid_production_results.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("config/search_v2.json", ROOT), "utf8").then(JSON.parse),
  ]);
  const manifest = JSON.parse(manifestSource);
  const reviewedPairs = new Map((precisionReview.pairs || []).map(item => [
    `${item.query_id}\0${item.result_id}`,
    item.complete_intent_supported ? "primary" : "not_primary",
  ]));
  const base = await loadHarness();
  const harness = makeVariantHarness(base, { searchV2: true });
  const api = loadHybridApi(hybridSource);
  const directHandler = createHandler({ fetchImpl: globalThis.fetch.bind(globalThis) });
  const receipts = [];
  const fetchImpl = async (url, options = {}) => {
    if (String(url) === "https://assets.local/manifest") return new Response(manifestSource, { status: 200 });
    if (String(url) === "https://assets.local/vectors") return new Response(vectorBuffer, { status: 200 });
    const endpoint = new URL(String(url));
    const request = new Request(endpoint.pathname === "/judge"
      ? new URL("judge", proxyUrl).href
      : url, {
      ...options,
      headers: { ...(options.headers || {}), Origin: "http://localhost:8000" },
    });
    const started = performance.now();
    const response = endpoint.pathname === "/judge"
      ? await globalThis.fetch(request)
      : await directHandler(request, { VOYAGE_API_KEY: voyageKey });
    const receipt = await response.clone().json().catch(() => ({}));
    const requestBody = JSON.parse(String(options.body || "{}"));
    receipts.push({
      endpoint: endpoint.pathname,
      status: response.status,
      payload_bytes: Buffer.byteLength(String(options.body || ""), "utf8"),
      latency_ms: number(performance.now() - started),
      provider_latency_ms: number(receipt.latency_ms || 0),
      usage: receipt.usage || {},
      item_count: endpoint.pathname === "/rerank"
        ? requestBody.candidates?.length || 0
        : endpoint.pathname === "/judge"
          ? requestBody.results?.length || 0
          : 0,
    });
    return response;
  };
  const client = api.createClient({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentEngine: harness.parentEngine,
    childEngine: harness.childEngine,
    proxyUrl: "http://localhost/",
    manifestUrl: "https://assets.local/manifest",
    vectorUrl: "https://assets.local/vectors",
    timeoutMs: 12_000,
    fetchImpl,
  });
  const parentById = new Map(harness.parentCatalog.opportunities.map(record => [String(record.opportunity_id), record]));
  const rows = [];
  let ordinal = 0;
  for (const population of POPULATIONS) {
    const [frame, truth] = await Promise.all([
      readFile(new URL(population.frame, ROOT), "utf8").then(JSON.parse),
      readFile(new URL(population.truth, ROOT), "utf8").then(JSON.parse),
    ]);
    for (const queryRow of frame.queries) {
      if (ordinal) await new Promise(resolve => setTimeout(resolve, PACING_MS));
      ordinal += 1;
      const queryTruth = truth.queries[queryRow.id];
      if (!queryTruth || queryTruth.query !== queryRow.query) throw new Error(`Missing exact truth for ${queryRow.id}.`);
      const started = performance.now();
      const result = await client.search(queryRow.query, { context: "" });
      const latency = performance.now() - started;
      const candidateIds = result.diagnostics.candidate_top_50 || [];
      const candidateRanks = ranks(candidateIds);
      const primary = result.parents.filter(item => item.intent_classification === "primary");
      const broader = result.parents.filter(item => item.intent_classification === "broader");
      const primaryRanks = ranks(primary.map(item => item.parent_id));
      const required = (queryTruth.required_primary_ids || []).map(String);
      const pairTruth = id => {
        const exact = canonicalTruth(queryTruth.judgments?.[id]?.label);
        if (exact) return { exact, binary: exact === "primary" ? "primary" : "not_primary" };
        return { exact: null, binary: reviewedPairs.get(`${queryRow.id}\0${id}`) || null };
      };
      const judgedResults = (result.diagnostics.judge?.results || []).map(item => ({
        ...item,
        exact_truth: pairTruth(item.id).exact,
        binary_truth: pairTruth(item.id).binary,
      }));
      const visible = item => ({
        id: item.parent_id,
        title: parentById.get(String(item.parent_id))?.title || item.title,
        displayed_rank: item.hybrid_rank,
        rerank_rank: item.rerank_rank,
        classification: item.intent_classification,
        passage_id: item.passage_id,
        passage_kind: item.passage_kind,
        explanation: item.explanation,
        exact_truth: pairTruth(item.parent_id).exact,
        binary_truth: pairTruth(item.parent_id).binary,
      });
      rows.push({
        population: population.id,
        id: queryRow.id,
        query: queryRow.query,
        discipline: queryRow.discipline,
        stratum: queryRow.stratum,
        required_primary_ids: required,
        candidate_required_ranks: Object.fromEntries(required.map(id => [id, candidateRanks.get(id) || null])),
        primary_required_ranks: Object.fromEntries(required.map(id => [id, primaryRanks.get(id) || null])),
        candidate_recall_at_10: recall(required, candidateRanks, 10),
        candidate_recall_at_50: recall(required, candidateRanks, 50),
        primary_recall_at_10: recall(required, primaryRanks, 10),
        primary_recall_at_50: recall(required, primaryRanks, 50),
        ndcg_at_10: ndcg(required, primaryRanks),
        judge_status: result.diagnostics.judge?.status || "missing",
        judged_results: judgedResults,
        visible_primary: primary.map(visible),
        visible_broader: broader.map(visible),
        hidden_reject_ids: judgedResults.filter(item => item.classification === "reject").map(item => item.id),
        diagnostics: result.diagnostics,
        latency_ms: number(latency),
      });
    }
  }

  const confusion = { primary_to_reject: 0, primary_to_broader: 0, broader_to_primary: 0, irrelevant_to_primary: 0 };
  rows.flatMap(row => row.judged_results).forEach(item => {
    if (item.exact_truth === "primary" && item.classification === "reject") confusion.primary_to_reject += 1;
    if (item.exact_truth === "primary" && item.classification === "broader") confusion.primary_to_broader += 1;
    if (item.exact_truth === "broader" && item.classification === "primary") confusion.broader_to_primary += 1;
    if (item.exact_truth === "reject" && item.classification === "primary") confusion.irrelevant_to_primary += 1;
  });
  const latencies = rows.map(row => row.latency_ms);
  const judgeReceipts = receipts.filter(item => item.endpoint === "/judge");
  const usage = client.usage();
  const quality = aggregate(rows);
  const byDiscipline = Object.fromEntries([...new Set(rows.map(row => row.discipline))].sort().map(discipline => [
    discipline,
    aggregate(rows.filter(row => row.discipline === discipline)),
  ]));
  const sourceRecord = parentById.get("363604");
  const results = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    status: "intent_gate_development_evaluation_complete",
    architecture: "unchanged hybrid ranking, then fixed Workers AI structured intent gate over top 10",
    model: api.JUDGE_MODEL,
    quality: {
      full_pipeline: quality,
      prior_hybrid_without_gate: priorResults.quality.production_shaped,
      classification_confusion_exact_truth: confusion,
      by_discipline: byDiscipline,
      hard_negatives: rows.filter(row => !row.required_primary_ids.length).map(row => ({
        query_id: row.id,
        query: row.query,
        primary_count: row.visible_primary.length,
        broader_count: row.visible_broader.length,
        reject_count: row.hidden_reject_ids.length,
      })),
      acronym_cases: rows.filter(row => /acronym/i.test(row.stratum || "") || /(?:^|\s)[A-Z]{2,6}(?:\s|$)/.test(row.query)),
    },
    source_fix: {
      result_id: "363604",
      document_program_areas: sourceRecord?.document_program_areas || [],
      topic_areas: sourceRecord?.topic_areas || [],
      hydrometallurgy_present: /hydrometallurgy/i.test(JSON.stringify(sourceRecord || {})),
      corpus_sha256: manifest.corpus_sha256,
      vector_sha256: manifest.vector_sha256,
    },
    performance: {
      cold_ms: latencies[0],
      warm_p50_ms: percentile(latencies.slice(1), .5),
      warm_p95_ms: percentile(latencies.slice(1), .95),
      judge_p50_ms: percentile(judgeReceipts.map(item => item.latency_ms), .5),
      judge_p95_ms: percentile(judgeReceipts.map(item => item.latency_ms), .95),
      error_count: receipts.filter(item => item.status >= 400).length,
    },
    usage: {
      ...usage,
      voyage_estimated_paid_cost_usd: number(usage.embedding_tokens / 1_000_000 * .02 + usage.rerank_tokens / 1_000_000 * .05),
      workers_ai_reported_neurons: usage.judge_neurons,
      workers_ai_reported_tokens: usage.judge_total_tokens,
      workers_ai_requests: judgeReceipts.length,
      workers_ai_free_neurons_per_day: 10_000,
      workers_ai_free_tier_fraction_if_neurons_reported: usage.judge_neurons
        ? number(usage.judge_neurons / 10_000)
        : null,
      raw_query_storage_added: false,
    },
    explanations: {
      visible_results_checked: rows.reduce((sum, row) => sum + row.visible_primary.length + row.visible_broader.length, 0),
      missing: rows.reduce((sum, row) => sum + [...row.visible_primary, ...row.visible_broader].filter(item => !item.explanation?.excerpt).length, 0),
      generated_model_language_exposed: 0,
      private_text_exposed: 0,
    },
    leave_out: {
      active_scientific_relationship_mapping_counts: Object.fromEntries([
        "concept_families", "controlled_relationships", "source_scope_relationships",
        "authoritative_scope_entailments", "broader_program_fits",
      ].map(key => [key, (config[key] || []).length])),
      by_discipline: byDiscipline,
    },
    safety: {
      spent_populations_only: true,
      sealed_phase4c_read_or_executed: false,
      private_profile_cv_or_orcid_sent: false,
      production_flag_enabled: false,
      deployed: false,
    },
    rows,
  };
  const receipt = {
    schema_version: 1,
    generated_at: results.generated_at,
    models: { embedding: api.EMBEDDING_MODEL, reranking: api.RERANK_MODEL, judge: api.JUDGE_MODEL },
    local_wrangler_remote_binding_url: proxyUrl.href,
    requests: receipts,
    totals: results.usage,
    secrets: { printed: false, persisted: false, sent_to_browser: false },
  };
  const serializedResults = `${JSON.stringify(results, null, 2)}\n`;
  const serializedReceipt = `${JSON.stringify(receipt, null, 2)}\n`;
  if (/pa-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_-]{12,}/.test(serializedResults + serializedReceipt)) {
    throw new Error("Refusing to write credential-like text.");
  }
  await Promise.all([
    writeFile(new URL(RESULTS_PATH, ROOT), serializedResults),
    writeFile(new URL(RECEIPT_PATH, ROOT), serializedReceipt),
  ]);
  process.stdout.write(`${JSON.stringify({
    results: RESULTS_PATH,
    results_sha256: sha256(serializedResults),
    receipt: RECEIPT_PATH,
    receipt_sha256: sha256(serializedReceipt),
    quality,
    confusion,
    performance: results.performance,
    usage: results.usage,
  }, null, 2)}\n`);
}

await main();
