#!/usr/bin/env node

// Production-shaped development evaluation for the disabled hybrid search path.
// It uses only the two spent acceptance populations. It deliberately has no
// import or execution path for the sealed Phase-4C population.

import { createHash, webcrypto } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "./run_search_diagnosis.mjs";
import {
  createHandler,
  SearchBudgetCoordinator,
} from "../workers/search-voyage-proxy/src/index.js";

const ROOT = new URL("../", import.meta.url);
const RESULTS_PATH = "evaluation/search_v2_hybrid_production_results.json";
const RECEIPT_PATH = "evaluation/search_v2_hybrid_production_api_receipt.json";
const EVALUATION_PACING_MS = 1_500;
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

function git(...args) {
  return execFileSync("git", args, { cwd: new URL(".", ROOT), encoding: "utf8" }).trim();
}

function loadHybridApi(source) {
  const context = {
    AbortController,
    ArrayBuffer,
    Float32Array,
    Math,
    Map,
    Number,
    Object,
    Promise,
    RegExp,
    Response,
    Set,
    String,
    TextEncoder,
    Uint8Array,
    Uint16Array,
    URL,
    clearTimeout,
    performance,
    setTimeout,
  };
  context.globalThis = { crypto: webcrypto, location: { href: "http://localhost/" } };
  vm.runInNewContext(source, context);
  return context.globalThis.FUNDING_HYBRID_SEARCH;
}

function requiredRanks(parents, requiredIds) {
  const ranks = new Map(parents.map((item, index) => [String(item.parent_id), index + 1]));
  return Object.fromEntries(requiredIds.map(id => [id, ranks.get(String(id)) || null]));
}

function evaluationEnv(apiKey) {
  const values = new Map();
  const coordinator = new SearchBudgetCoordinator({
    storage: {
      async get(key) { return values.get(key); },
      async put(key, value) { values.set(key, structuredClone(value)); },
    },
  });
  const limiter = { async limit() { return { success: true }; } };
  return {
    VOYAGE_API_KEY: apiKey,
    ENHANCED_SEARCH_ENABLED: "true",
    DAILY_EMBED_TOKEN_BUDGET: "50000",
    DAILY_RERANK_TOKEN_BUDGET: "25000000",
    PER_CLIENT_EMBED_REQUEST_LIMIT: "12",
    PER_CLIENT_RERANK_REQUEST_LIMIT: "8",
    GLOBAL_REQUEST_LIMIT: "600",
    RATE_LIMIT_RETRY_AFTER_SECONDS: "10",
    GLOBAL_RATE_LIMITER: limiter,
    EMBED_RATE_LIMITER: limiter,
    RERANK_RATE_LIMITER: limiter,
    BUDGET_COORDINATOR: {
      idFromName(name) { return name; },
      get() {
        return { fetch(url, options) { return coordinator.fetch(new Request(url, options)); } };
      },
    },
  };
}

function queryMetrics(parents, queryTruth) {
  const required = (queryTruth.required_primary_ids || []).map(String);
  const ranks = requiredRanks(parents, required);
  const judgments = queryTruth.judgments || {};
  const top10 = parents.slice(0, 10);
  const labeled = top10.flatMap(item => judgments[item.parent_id]
    ? [{ id: item.parent_id, label: judgments[item.parent_id].label }]
    : []);
  const primary = labeled.filter(item => item.label === "primary_relevant").length;
  const dcg = required.reduce((sum, id) => {
    const rank = ranks[id];
    return rank && rank <= 10 ? sum + 1 / Math.log2(rank + 1) : sum;
  }, 0);
  const ideal = Array.from({ length: Math.min(10, required.length) }, (_value, index) => (
    1 / Math.log2(index + 2)
  )).reduce((sum, value) => sum + value, 0);
  const bestRank = Object.values(ranks).filter(Number.isInteger).sort((a, b) => a - b)[0] || null;
  return {
    required_anchor_count: required.length,
    required_recall_at_10: required.length
      ? number(Object.values(ranks).filter(rank => rank && rank <= 10).length / required.length)
      : null,
    required_recall_at_50: required.length
      ? number(Object.values(ranks).filter(rank => rank && rank <= 50).length / required.length)
      : null,
    ndcg_at_10: required.length ? number(dcg / ideal) : null,
    reciprocal_rank: bestRank ? number(1 / bestRank) : null,
    precision_at_10_over_existing_judgments: labeled.length ? number(primary / labeled.length) : null,
    judged_top_10_count: labeled.length,
    known_irrelevant_at_10: labeled.filter(item => item.label === "irrelevant").map(item => item.id),
    broader_at_10: labeled.filter(item => item.label === "broader_program_fit").map(item => item.id),
    required_ranks: ranks,
  };
}

function aggregate(rows) {
  const anchors = rows.flatMap(row => Object.values(row.metrics.required_ranks));
  const anchorCount = rows.reduce((sum, row) => sum + row.metrics.required_anchor_count, 0);
  const at10 = anchors.filter(rank => rank && rank <= 10).length;
  const at50 = anchors.filter(rank => rank && rank <= 50).length;
  const positive = rows.filter(row => row.metrics.required_anchor_count > 0);
  const judged = rows.reduce((sum, row) => sum + row.metrics.judged_top_10_count, 0);
  const primaryJudged = rows.reduce((sum, row) => {
    const irrelevant = row.metrics.known_irrelevant_at_10.length;
    const broader = row.metrics.broader_at_10.length;
    return sum + row.metrics.judged_top_10_count - irrelevant - broader;
  }, 0);
  return {
    query_count: rows.length,
    required_anchor_count: anchorCount,
    required_recall_at_10: anchorCount ? number(at10 / anchorCount) : null,
    required_recall_at_50: anchorCount ? number(at50 / anchorCount) : null,
    query_average_ndcg_at_10: positive.length
      ? number(positive.reduce((sum, row) => sum + row.metrics.ndcg_at_10, 0) / positive.length)
      : null,
    query_average_mrr: positive.length
      ? number(positive.reduce((sum, row) => sum + (row.metrics.reciprocal_rank || 0), 0) / positive.length)
      : null,
    precision_at_10_over_existing_judgments: judged ? number(primaryJudged / judged) : null,
    judged_top_10_count: judged,
    known_irrelevant_at_10_count: rows.reduce((sum, row) => sum + row.metrics.known_irrelevant_at_10.length, 0),
    broader_at_10_count: rows.reduce((sum, row) => sum + row.metrics.broader_at_10.length, 0),
    maximum_parent_count: Math.max(0, ...rows.map(row => row.parent_count)),
    maximum_union_passage_count: Math.max(0, ...rows.map(row => row.diagnostics.union_candidates || 0)),
  };
}

async function main() {
  if (!process.argv.includes("--write")) {
    throw new Error("Use --write to run the spent-data production-shaped evaluation.");
  }
  const apiKey = String(process.env.VOYAGE_API_KEY || "").trim();
  if (!apiKey) throw new Error("VOYAGE_API_KEY is required in this process environment.");

  const [hybridSource, manifestSource, vectorBuffer, priorSource, configSource] = await Promise.all([
    readFile(new URL("assets/search-hybrid.js", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-manifest.json", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-vectors.f16", ROOT)),
    readFile(new URL("evaluation/search_v2_hybrid_voyage_results.json", ROOT), "utf8"),
    readFile(new URL("config/search_v2.json", ROOT), "utf8"),
  ]);
  const manifest = JSON.parse(manifestSource);
  const prior = JSON.parse(priorSource);
  const configuration = JSON.parse(configSource);
  const base = await loadHarness();
  const harness = makeVariantHarness(base, { searchV2: true });
  const api = loadHybridApi(hybridSource);
  const providerReceipts = [];
  const handler = createHandler({ fetchImpl: globalThis.fetch.bind(globalThis) });
  const workerEnv = evaluationEnv(apiKey);
  const fetchImpl = async (url, options = {}) => {
    if (String(url) === "https://assets.local/manifest") {
      return new Response(manifestSource, { status: 200, headers: { "Content-Type": "application/json" } });
    }
    if (String(url).startsWith("https://assets.local/vectors?v=")) {
      return new Response(vectorBuffer, { status: 200 });
    }
    const request = new Request(url, {
      ...options,
      headers: { ...(options.headers || {}), Origin: "http://localhost:8000" },
    });
    const payloadBytes = Buffer.byteLength(String(options.body || ""), "utf8");
    const started = performance.now();
    const response = await handler(request, workerEnv);
    const receipt = await response.clone().json().catch(() => ({}));
    providerReceipts.push({
      endpoint: new URL(String(url)).pathname,
      status: response.status,
      payload_bytes: payloadBytes,
      provider_latency_ms: number(receipt.latency_ms || 0),
      end_to_end_proxy_ms: number(performance.now() - started),
      total_tokens: Number(receipt.usage?.total_tokens || 0),
      candidate_count: new URL(String(url)).pathname === "/rerank"
        ? JSON.parse(String(options.body || "{}")).candidates?.length || 0
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
    timeoutMs: 8_000,
    fetchImpl,
  });

  const priorById = new Map(prior.rows.map(row => [row.id, row]));
  const parentById = new Map(harness.parentCatalog.opportunities.map(record => [String(record.opportunity_id), record]));
  const rows = [];
  let queryOrdinal = 0;
  for (const population of POPULATIONS) {
    const [frame, truth] = await Promise.all([
      readFile(new URL(population.frame, ROOT), "utf8").then(JSON.parse),
      readFile(new URL(population.truth, ROOT), "utf8").then(JSON.parse),
    ]);
    for (const queryRow of frame.queries) {
      if (queryOrdinal > 0) {
        await new Promise(resolve => setTimeout(resolve, EVALUATION_PACING_MS));
      }
      queryOrdinal += 1;
      const queryTruth = truth.queries[queryRow.id];
      if (!queryTruth || queryTruth.query !== queryRow.query) {
        throw new Error(`Missing exact query-result truth for ${queryRow.id}.`);
      }
      const started = performance.now();
      const result = await client.search(queryRow.query, { context: "" });
      const elapsed = performance.now() - started;
      const metrics = queryMetrics(result.parents, queryTruth);
      const priorRow = priorById.get(queryRow.id);
      rows.push({
        population: population.id,
        id: queryRow.id,
        query: queryRow.query,
        discipline: queryRow.discipline,
        stratum: queryRow.stratum,
        required_primary_ids: queryTruth.required_primary_ids || [],
        metrics,
        prior_feasibility_required_ranks: priorRow?.hybrid_final?.required_ranks || {},
        parent_count: result.parents.length,
        diagnostics: result.diagnostics,
        latency_ms: number(elapsed),
        top_50: result.parents.slice(0, 50).map(item => ({
          id: item.parent_id,
          rank: item.hybrid_rank,
          title: parentById.get(String(item.parent_id))?.title || item.title,
          passage_id: item.passage_id,
          passage_kind: item.passage_kind,
          record_id: item.record_id,
          fields: item.fields,
          relevance_score: number(item.voyage_score),
          explanation: item.explanation,
          existing_truth: queryTruth.judgments?.[item.parent_id]?.label || null,
        })),
      });
    }
  }

  const byDiscipline = Object.fromEntries([...new Set(rows.map(row => row.discipline))].sort().map(discipline => [
    discipline,
    aggregate(rows.filter(row => row.discipline === discipline)),
  ]));
  const anchorMovements = rows.flatMap(row => row.required_primary_ids.map(id => ({
    query_id: row.id,
    query: row.query,
    required_result_id: id,
    prior_feasibility_rank: row.prior_feasibility_required_ranks[id] || null,
    production_shaped_rank: row.metrics.required_ranks[id] || null,
  })));
  const hardNegatives = rows.filter(row => row.required_primary_ids.length === 0).map(row => ({
    query_id: row.id,
    query: row.query,
    top_10: row.top_50.slice(0, 10).map(item => ({ id: item.id, title: item.title })),
    known_irrelevant_at_10: row.metrics.known_irrelevant_at_10,
  }));
  const latencies = rows.map(row => row.latency_ms);
  const usage = client.usage();
  const results = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    status: "production_shaped_development_evaluation_complete",
    architecture: {
      lexical_candidate_source: "existing local BM25F",
      semantic_candidate_source: "lazy static voyage-4-lite float16 cosine",
      candidate_depths: { bm25f: 200, semantic: 200, rerank_union: 300 },
      union: "reciprocal rank fusion k=60",
      final_ranking: "Voyage rerank-2.5 then strongest passage per parent",
      browser_query_embedding_or_rerank_secret: false,
      semantic_scores_create_relevance_evidence: false,
      explanation_source: "extractive winning public indexed passage",
      fallback: "immediate existing local BM25F on any asset/proxy/API/timeout failure",
    },
    static_assets: {
      passage_count: manifest.passage_count,
      corpus_sha256: manifest.corpus_sha256,
      vector_sha256: manifest.vector_sha256,
      vector_bytes: vectorBuffer.byteLength,
      format: manifest.dtype,
      initial_page_load: false,
    },
    quality: {
      production_shaped: aggregate(rows),
      prior_in_memory_feasibility: prior.final_ranking.hybrid_voyage,
      by_discipline: byDiscipline,
      anchor_movements: anchorMovements,
      hard_negatives: hardNegatives,
      acronym_guard: {
        query_id: "i2hold_acronym_02",
        protected_acronym: "AIM",
        former_known_collision_id: "344592",
        former_known_collision_rank: priorById.get("i2hold_acronym_02")?.hybrid_final?.top_10
          ?.findIndex(item => item.id === "344592") + 1 || null,
        production_shaped_rank: rows.find(row => row.id === "i2hold_acronym_02")?.top_50
          ?.find(item => item.id === "344592")?.rank || null,
      },
    },
    leave_out: {
      methodology: "No manual scientific relationship mapping is active; every discipline/program slice is untuned.",
      active_manual_relationship_mappings: Object.fromEntries([
        "concept_families",
        "controlled_relationships",
        "source_scope_relationships",
        "authoritative_scope_entailments",
        "broader_program_fits",
      ].map(key => [key, (configuration[key] || []).length])),
      by_discipline: byDiscipline,
    },
    explanations: {
      visible_top_10_checked: rows.reduce((sum, row) => sum + Math.min(10, row.top_50.length), 0),
      missing: rows.reduce((sum, row) => sum + row.top_50.slice(0, 10).filter(item => !item.explanation?.excerpt).length, 0),
      score_or_similarity_claims: rows.reduce((sum, row) => sum + row.top_50.slice(0, 10)
        .filter(item => /semantic|similarity|score|voyage/i.test(item.explanation?.excerpt || "")).length, 0),
    },
    performance: {
      query_count: rows.length,
      cold_first_query_ms: latencies[0],
      warm_p50_ms: percentile(latencies.slice(1), .5),
      warm_p95_ms: percentile(latencies.slice(1), .95),
      maximum_ms: number(Math.max(...latencies)),
      timeout_count: providerReceipts.filter(item => item.status === 504).length,
      error_count: providerReceipts.filter(item => item.status >= 400).length,
      proxy_provider_p50_ms: percentile(providerReceipts.map(item => item.provider_latency_ms), .5),
      proxy_provider_p95_ms: percentile(providerReceipts.map(item => item.provider_latency_ms), .95),
      payload_p50_bytes: percentile(providerReceipts.map(item => item.payload_bytes), .5),
      payload_p95_bytes: percentile(providerReceipts.map(item => item.payload_bytes), .95),
    },
    usage: {
      ...usage,
      requests: providerReceipts.length,
      documents_reranked: providerReceipts.reduce((sum, item) => sum + item.candidate_count, 0),
      estimated_paid_cost_usd: number(
        usage.embedding_tokens / 1_000_000 * .02
        + usage.rerank_tokens / 1_000_000 * .05
      ),
      estimated_paid_cost_per_1000_searches_usd: number(
        ((usage.embedding_tokens / rows.length) / 1_000_000 * .02
          + (usage.rerank_tokens / rows.length) / 1_000_000 * .05) * 1000
      ),
      evaluation_pacing_ms_between_queries: EVALUATION_PACING_MS,
      prior_aborted_transport_run: {
        count: 1,
        artifact_written: false,
        failure_code: "provider_unavailable",
        usage_not_reported_by_failed_clean_proxy_response: true,
      },
      prior_completed_pre_case_sensitive_acronym_guard_run: {
        results_sha256: "e4a8f469a24f291f30fb5a6fb80ae5dd1ae55e5b74984bb507e80007a895e789",
        request_count: 103,
        embedding_tokens: 194,
        rerank_tokens: 3_117_000,
        estimated_paid_cost_usd: 0.155854,
        superseded_reason: "The generic short-uppercase guard incorrectly treated lowercase ordinary words as exact acronym evidence.",
      },
    },
    safety: {
      evaluation_population: "two spent holdouts only",
      sealed_phase4c_read_or_executed: false,
      private_profile_cv_or_orcid_sent: false,
      API_key_printed_or_persisted: false,
      production_flag_enabled: false,
      production_search_behavior_enabled: false,
    },
    git_state: {
      branch: git("branch", "--show-current"),
      head: git("rev-parse", "HEAD"),
      main: git("rev-parse", "main"),
      origin_main: git("rev-parse", "origin/main"),
    },
    rows,
  };
  const receipt = {
    schema_version: 1,
    generated_at: results.generated_at,
    model: { embedding: "voyage-4-lite", reranking: "rerank-2.5" },
    static_document_embedding_build_receipt: "evaluation/search_v2_hybrid_vector_build.json",
    requests: providerReceipts,
    totals: results.usage,
    secret: {
      source: "VOYAGE_API_KEY process environment",
      printed: false,
      persisted: false,
      sent_to_browser: false,
    },
  };
  const serializedResults = `${JSON.stringify(results, null, 2)}\n`;
  const serializedReceipt = `${JSON.stringify(receipt, null, 2)}\n`;
  if (/pa-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_-]{12,}/.test(serializedResults + serializedReceipt)) {
    throw new Error("Refusing to write an artifact containing credential-like text.");
  }
  await writeFile(new URL(RESULTS_PATH, ROOT), serializedResults, "utf8");
  await writeFile(new URL(RECEIPT_PATH, ROOT), serializedReceipt, "utf8");
  process.stdout.write(`${JSON.stringify({
    results: RESULTS_PATH,
    results_sha256: sha256(serializedResults),
    receipt: RECEIPT_PATH,
    receipt_sha256: sha256(serializedReceipt),
    quality: results.quality.production_shaped,
    performance: results.performance,
    usage: results.usage,
  }, null, 2)}\n`);
}

await main();
