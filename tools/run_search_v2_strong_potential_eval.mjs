#!/usr/bin/env node

// Development-only product-contract evaluation for the disabled Strong +
// Potential workflow. It reads only the two spent acceptance populations.

import { createHash, webcrypto } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import vm from "node:vm";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";
import {
  createHandler,
  SearchBudgetCoordinator,
} from "../workers/search-voyage-proxy/src/index.js";

const ROOT = new URL("../", import.meta.url);
const RESULTS_PATH = "evaluation/search_v2_strong_potential_results.json";
const RECEIPT_PATH = "evaluation/search_v2_strong_potential_api_receipt.json";
const GATE_PATH = "evaluation/search_v2_strong_potential_gate_report.json";
const POTENTIAL_LIMIT = 12;
const PACING_MS = 250;
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

function ranks(ids, required) {
  const positions = new Map(ids.map((id, index) => [String(id), index + 1]));
  return Object.fromEntries(required.map(id => [String(id), positions.get(String(id)) || null]));
}

function recallAt(requiredRanks, depth) {
  const values = Object.values(requiredRanks);
  return values.length
    ? number(values.filter(rank => Number.isInteger(rank) && rank <= depth).length / values.length)
    : null;
}

function ndcgAt10(requiredRanks) {
  const values = Object.values(requiredRanks);
  if (!values.length) return null;
  const dcg = values.reduce((sum, rank) => (
    rank && rank <= 10 ? sum + 1 / Math.log2(rank + 1) : sum
  ), 0);
  const ideal = Array.from({ length: Math.min(10, values.length) }, (_value, index) => (
    1 / Math.log2(index + 2)
  )).reduce((sum, value) => sum + value, 0);
  return number(dcg / ideal);
}

function reviewedLabel(queryId, resultId, queryTruth, reviewByPair) {
  const exactTruth = queryTruth.judgments?.[resultId]?.label;
  if (exactTruth) return exactTruth;
  const review = reviewByPair.get(`${queryId}:${resultId}`);
  if (!review) return null;
  if (review.label) return review.label;
  return review.complete_intent_supported ? "primary_relevant" : "reviewed_non_primary";
}

function tierReview(ids, queryId, queryTruth, reviewByPair) {
  const rows = ids.map(id => ({
    id,
    label: reviewedLabel(queryId, id, queryTruth, reviewByPair),
  }));
  const reviewed = rows.filter(item => item.label);
  return {
    reviewed_count: reviewed.length,
    reviewed_primary_count: reviewed.filter(item => item.label === "primary_relevant").length,
    reviewed_broader_count: reviewed.filter(item => item.label === "broader_program_fit").length,
    known_irrelevant_count: reviewed.filter(item => item.label === "irrelevant").length,
    reviewed_non_primary_count: reviewed.filter(item => (
      ["irrelevant", "broader_program_fit", "reviewed_non_primary"].includes(item.label)
    )).length,
    unreviewed_count: rows.length - reviewed.length,
    precision_over_reviewed: reviewed.length
      ? number(reviewed.filter(item => item.label === "primary_relevant").length / reviewed.length)
      : null,
    known_irrelevant_ids: reviewed.filter(item => item.label === "irrelevant").map(item => item.id),
    reviewed_non_primary_ids: reviewed.filter(item => item.label === "reviewed_non_primary").map(item => item.id),
  };
}

function aggregate(rows) {
  const anchors = rows.flatMap(row => Object.values(row.combined.required_ranks));
  const requiredCount = anchors.length;
  const positiveRows = rows.filter(row => row.required_primary_ids.length);
  const strongReviews = rows.map(row => row.strong.review);
  const potentialReviews = rows.map(row => row.potential.review);
  const potentialTop10 = rows.flatMap(row => row.potential.rows.slice(0, 10));
  const strongReviewed = strongReviews.reduce((sum, value) => sum + value.reviewed_count, 0);
  const strongPrimary = strongReviews.reduce((sum, value) => sum + value.reviewed_primary_count, 0);
  return {
    query_count: rows.length,
    required_anchor_count: requiredCount,
    strong: {
      required_recall_at_10: requiredCount
        ? number(rows.reduce((sum, row) => sum + Object.values(row.strong.required_ranks)
          .filter(rank => rank && rank <= 10).length, 0) / requiredCount)
        : null,
      required_recall_at_50: requiredCount
        ? number(rows.reduce((sum, row) => sum + Object.values(row.strong.required_ranks)
          .filter(rank => rank && rank <= 50).length, 0) / requiredCount)
        : null,
      precision_at_10_over_reviewed: strongReviewed ? number(strongPrimary / strongReviewed) : null,
      reviewed_pair_count: strongReviewed,
      known_irrelevant_at_10_count: strongReviews.reduce((sum, value) => sum + value.known_irrelevant_count, 0),
      reviewed_non_primary_at_10_count: strongReviews.reduce((sum, value) => sum + value.reviewed_non_primary_count, 0),
      unreviewed_at_10_count: strongReviews.reduce((sum, value) => sum + value.unreviewed_count, 0),
      zero_anchor_visible_count: rows.filter(row => !row.required_primary_ids.length)
        .reduce((sum, row) => sum + row.strong.ids.length, 0),
      visible_count: rows.reduce((sum, row) => sum + row.strong.ids.length, 0),
      maximum_visible_count: Math.max(0, ...rows.map(row => row.strong.ids.length)),
    },
    potential: {
      displayed_count: rows.reduce((sum, row) => sum + row.potential.ids.length, 0),
      maximum_displayed_count: Math.max(0, ...rows.map(row => row.potential.ids.length)),
      top_10_pair_count: potentialTop10.length,
      top_10_reviewed_primary_count: potentialTop10
        .filter(item => item.existing_truth === "primary_relevant").length,
      top_10_known_irrelevant_count: potentialTop10
        .filter(item => item.existing_truth === "irrelevant").length,
      top_10_reviewed_non_primary_count: potentialTop10
        .filter(item => ["irrelevant", "broader_program_fit", "reviewed_non_primary"]
          .includes(item.existing_truth)).length,
      top_10_unreviewed_count: potentialTop10.filter(item => !item.existing_truth).length,
      reviewed_pair_count: potentialReviews.reduce((sum, value) => sum + value.reviewed_count, 0),
      reviewed_primary_count: potentialReviews.reduce((sum, value) => sum + value.reviewed_primary_count, 0),
      known_irrelevant_count: potentialReviews.reduce((sum, value) => sum + value.known_irrelevant_count, 0),
      reviewed_non_primary_count: potentialReviews.reduce((sum, value) => sum + value.reviewed_non_primary_count, 0),
      unreviewed_count: potentialReviews.reduce((sum, value) => sum + value.unreviewed_count, 0),
      zero_anchor_displayed_count: rows.filter(row => !row.required_primary_ids.length)
        .reduce((sum, row) => sum + row.potential.ids.length, 0),
    },
    combined: {
      required_recall_at_10: requiredCount
        ? number(anchors.filter(rank => rank && rank <= 10).length / requiredCount)
        : null,
      required_recall_at_20: requiredCount
        ? number(anchors.filter(rank => rank && rank <= 20).length / requiredCount)
        : null,
      required_recall_at_50: requiredCount
        ? number(anchors.filter(rank => rank && rank <= 50).length / requiredCount)
        : null,
      query_average_ndcg_at_10: positiveRows.length
        ? number(positiveRows.reduce((sum, row) => sum + row.combined.ndcg_at_10, 0) / positiveRows.length)
        : null,
      deduplication_failures: rows.filter(row => row.deduplication_overlap.length).length,
      required_anchor_misses_at_50: rows.flatMap(row => Object.entries(row.combined.required_ranks)
        .filter(([_id, rank]) => !rank || rank > 50)
        .map(([id]) => ({ query_id: row.id, result_id: id }))),
    },
  };
}

async function main() {
  if (!process.argv.includes("--write")) {
    throw new Error("Use --write to run this spent-data product-contract evaluation.");
  }
  if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
    throw new Error("This runner refuses sealed acceptance inputs.");
  }
  const apiKey = String(process.env.VOYAGE_API_KEY || "").trim();
  if (!apiKey) throw new Error("VOYAGE_API_KEY is required in this process environment.");

  const [hybridSource, manifestSource, vectorBuffer, review, productTruth, configuration] = await Promise.all([
    readFile(new URL("assets/search-hybrid.js", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-manifest.json", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-vectors.f16", ROOT)),
    readFile(new URL("evaluation/search_v2_hybrid_precision_review.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("evaluation/search_v2_strong_potential_truth.json", ROOT), "utf8").then(JSON.parse),
    readFile(new URL("config/search_v2.json", ROOT), "utf8").then(JSON.parse),
  ]);
  const manifest = JSON.parse(manifestSource);
  const reviewByPair = new Map(review.pairs.map(item => [`${item.query_id}:${item.result_id}`, item]));
  Object.entries(productTruth.judgments || {}).forEach(([queryId, judgments]) => {
    Object.entries(judgments).forEach(([resultId, judgment]) => {
      reviewByPair.set(`${queryId}:${resultId}`, judgment);
    });
  });
  const base = await loadHarness();
  const harness = makeVariantHarness(base, { searchV2: true });
  const api = loadHybridApi(hybridSource);
  const receipts = [];
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
    const body = String(options.body || "");
    const endpoint = new URL(String(url)).pathname;
    const started = performance.now();
    const response = await handler(request, workerEnv);
    const publicReceipt = await response.clone().json().catch(() => ({}));
    receipts.push({
      endpoint,
      status: response.status,
      payload_bytes: Buffer.byteLength(body, "utf8"),
      latency_ms: number(performance.now() - started),
      provider_latency_ms: number(publicReceipt.latency_ms || 0),
      total_tokens: Number(publicReceipt.usage?.total_tokens || 0),
      document_count: endpoint === "/rerank" ? JSON.parse(body).candidates?.length || 0 : 0,
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
  const parentById = new Map(harness.parentCatalog.opportunities.map(record => [String(record.opportunity_id), record]));
  const rows = [];
  let ordinal = 0;
  for (const population of POPULATIONS) {
    const [frame, truth] = await Promise.all([
      readFile(new URL(population.frame, ROOT), "utf8").then(JSON.parse),
      readFile(new URL(population.truth, ROOT), "utf8").then(JSON.parse),
    ]);
    for (const item of frame.queries) {
      if (ordinal > 0) await new Promise(resolve => setTimeout(resolve, PACING_MS));
      ordinal += 1;
      const queryTruth = truth.queries[item.id];
      if (!queryTruth || queryTruth.query !== item.query) {
        throw new Error(`Exact query-result truth mismatch for ${item.id}.`);
      }
      const localStarted = performance.now();
      const local = rankQuery(harness, item.query, { evidence: true });
      const localLatency = performance.now() - localStarted;
      const hybridStarted = performance.now();
      const hybrid = await client.search(item.query, { context: "" });
      const hybridLatency = performance.now() - hybridStarted;
      const strongIds = local.rows.map(row => String(row.id));
      const strongSet = new Set(strongIds);
      const hybridIds = hybrid.parents.map(parent => String(parent.parent_id));
      const potentialParents = hybrid.parents.filter(parent => !strongSet.has(String(parent.parent_id)));
      const potentialIds = potentialParents.slice(0, POTENTIAL_LIMIT).map(parent => String(parent.parent_id));
      const combinedIds = [...strongIds, ...potentialParents.map(parent => String(parent.parent_id))];
      const required = (queryTruth.required_primary_ids || []).map(String);
      const strongRanks = ranks(strongIds, required);
      const combinedRanks = ranks(combinedIds, required);
      const strongTop10 = strongIds.slice(0, 10);
      rows.push({
        population: population.id,
        id: item.id,
        query: item.query,
        discipline: item.discipline || item.domain || "unspecified",
        stratum: item.stratum || "",
        required_primary_ids: required,
        strong: {
          ids: strongTop10,
          all_visible_count: strongIds.length,
          required_ranks: strongRanks,
          review: tierReview(strongTop10, item.id, queryTruth, reviewByPair),
          rows: local.rows.slice(0, 10).map((row, index) => ({
            rank: index + 1,
            id: String(row.id),
            title: row.record?.title || "",
            evidence_tier: row.evidenceTier,
            best_child_id: row.bestChild?.id || null,
            existing_truth: reviewedLabel(item.id, String(row.id), queryTruth, reviewByPair),
          })),
        },
        potential: {
          ids: potentialIds,
          available_after_deduplication: potentialParents.length,
          review: tierReview(potentialIds, item.id, queryTruth, reviewByPair),
          rows: potentialParents.slice(0, POTENTIAL_LIMIT).map((parent, index) => ({
            rank: index + 1,
            hybrid_rank_before_deduplication: parent.hybrid_rank,
            id: String(parent.parent_id),
            title: parentById.get(String(parent.parent_id))?.title || parent.title || "",
            passage_id: parent.passage_id,
            passage_kind: parent.passage_kind,
            source_field: parent.explanation?.source_field || null,
            source_excerpt: parent.explanation?.excerpt || null,
            existing_truth: reviewedLabel(item.id, String(parent.parent_id), queryTruth, reviewByPair),
          })),
        },
        combined: {
          visible_ids: [...strongIds, ...potentialIds],
          internal_top_50: combinedIds.slice(0, 50),
          required_ranks: combinedRanks,
          required_recall_at_10: recallAt(combinedRanks, 10),
          required_recall_at_20: recallAt(combinedRanks, 20),
          required_recall_at_50: recallAt(combinedRanks, 50),
          ndcg_at_10: ndcgAt10(combinedRanks),
        },
        deduplication_overlap: potentialIds.filter(id => strongSet.has(id)),
        internal: {
          hybrid_parent_count: hybrid.parents.length,
          union_passage_count: hybrid.diagnostics.union_candidates,
          safeguard_rejections: hybrid.diagnostics.safeguard_rejections,
        },
        latency_ms: {
          strong_local: number(localLatency),
          hybrid_total: number(hybridLatency),
        },
      });
    }
  }

  const summary = aggregate(rows);
  const byDomain = Object.fromEntries([...new Set(rows.map(row => row.discipline))].sort().map(domain => [
    domain,
    aggregate(rows.filter(row => row.discipline === domain)),
  ]));
  const acronymRow = rows.find(row => row.id === "i2hold_acronym_02");
  const usage = client.usage();
  const latency = rows.map(row => row.latency_ms.hybrid_total);
  const results = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    status: "spent_development_product_contract_evaluation_complete",
    product_contract: {
      strong: "Existing conservative local deterministic evidence matcher, unchanged.",
      potential: "Hybrid BM25F plus voyage-4-lite local vector retrieval, RRF, acronym safeguards, Voyage rerank-2.5, and strongest-passage parent rollup.",
      potential_limit: POTENTIAL_LIMIT,
      deduplication: "Potential excludes every parent ID already present in Strong.",
      semantic_score_creates_primary_evidence: false,
      live_intent_judge: false,
      potential_explanation: "Extractive supporting public indexed passage only.",
    },
    quality: {
      global: summary,
      by_domain: byDomain,
      acronym_safeguard: {
        query_id: "i2hold_acronym_02",
        collision_id: "344592",
        appears_in_strong: acronymRow?.strong.ids.includes("344592") || false,
        appears_in_potential: acronymRow?.potential.ids.includes("344592") || false,
      },
      zero_anchor: {
        query_count: rows.filter(row => !row.required_primary_ids.length).length,
        strong_visible_count: summary.strong.zero_anchor_visible_count,
        potential_displayed_count: summary.potential.zero_anchor_displayed_count,
      },
    },
    architecture: {
      manual_relationship_mappings: Object.fromEntries([
        "concept_families",
        "controlled_relationships",
        "source_scope_relationships",
        "authoritative_scope_entailments",
        "broader_program_fits",
      ].map(key => [key, (configuration[key] || []).length])),
      cloudflare_workers_ai_binding_required: false,
      proxy_endpoints: ["/embed-query", "/rerank"],
      parent_rollup: "strongest matching parent or child passage; no child-count bonus",
    },
    explanation_review: {
      potential_rows_checked: rows.reduce((sum, row) => sum + row.potential.rows.length, 0),
      missing_extracts: rows.reduce((sum, row) => sum + row.potential.rows
        .filter(item => !item.source_field || !item.source_excerpt).length, 0),
      score_or_model_claims: rows.reduce((sum, row) => sum + row.potential.rows
        .filter(item => /semantic|similarity|score|voyage|rerank/i.test(item.source_excerpt || "")).length, 0),
    },
    performance: {
      query_count: rows.length,
      cold_first_query_ms: latency[0],
      warm_p50_ms: percentile(latency.slice(1), .5),
      warm_p95_ms: percentile(latency.slice(1), .95),
      maximum_ms: number(Math.max(...latency)),
      strong_local_p50_ms: percentile(rows.map(row => row.latency_ms.strong_local), .5),
      strong_local_p95_ms: percentile(rows.map(row => row.latency_ms.strong_local), .95),
      proxy_p50_ms: percentile(receipts.map(item => item.latency_ms), .5),
      proxy_p95_ms: percentile(receipts.map(item => item.latency_ms), .95),
      payload_p50_bytes: percentile(receipts.map(item => item.payload_bytes), .5),
      payload_p95_bytes: percentile(receipts.map(item => item.payload_bytes), .95),
      error_count: receipts.filter(item => item.status >= 400).length,
      timeout_count: receipts.filter(item => item.status === 504).length,
    },
    usage: {
      ...usage,
      request_count: receipts.length,
      documents_reranked: receipts.reduce((sum, item) => sum + item.document_count, 0),
      estimated_paid_cost_usd: number(
        usage.embedding_tokens / 1_000_000 * .02
        + usage.rerank_tokens / 1_000_000 * .05
      ),
      estimated_paid_cost_per_1000_searches_usd: number(
        ((usage.embedding_tokens / rows.length) / 1_000_000 * .02
          + (usage.rerank_tokens / rows.length) / 1_000_000 * .05) * 1000
      ),
    },
    safety: {
      population: "two spent holdouts only",
      sealed_acceptance_population_read_or_executed: false,
      private_profile_cv_or_orcid_sent: false,
      secret_printed_or_persisted: false,
      production_flag_enabled: false,
      main_touched: false,
    },
    static_assets: {
      passage_count: manifest.passage_count,
      corpus_sha256: manifest.corpus_sha256,
      vector_sha256: manifest.vector_sha256,
      vector_bytes: vectorBuffer.byteLength,
    },
    git_state: {
      branch: git("branch", "--show-current"),
      head: git("rev-parse", "HEAD"),
      main: git("rev-parse", "main"),
      origin_main: git("rev-parse", "origin/main"),
    },
    rows,
  };

  const gates = {
    strong_precision_at_least_0_90: Number(summary.strong.precision_at_10_over_reviewed) >= .9,
    no_known_irrelevant_strong_results: summary.strong.known_irrelevant_at_10_count === 0,
    zero_anchor_queries_have_no_strong_results: summary.strong.zero_anchor_visible_count === 0,
    short_acronym_collision_not_strong: results.quality.acronym_safeguard.appears_in_strong === false,
    combined_required_recall_at_20_at_least_0_80: Number(summary.combined.required_recall_at_20) >= .8,
    combined_required_recall_at_50_at_least_0_95: Number(summary.combined.required_recall_at_50) >= .95,
    potential_limit_enforced: summary.potential.maximum_displayed_count <= POTENTIAL_LIMIT,
    strong_potential_ids_deduplicated: summary.combined.deduplication_failures === 0,
    potential_explanations_extract_public_passages: results.explanation_review.missing_extracts === 0,
    no_semantic_score_or_model_explanation_claims: results.explanation_review.score_or_model_claims === 0,
    no_api_errors_or_timeouts: results.performance.error_count === 0 && results.performance.timeout_count === 0,
    manual_relationship_mappings_remain_zero: Object.values(results.architecture.manual_relationship_mappings)
      .every(value => value === 0),
  };
  const blocking = Object.entries(gates).filter(([_name, passed]) => !passed).map(([name]) => name);
  const gateReport = {
    schema_version: 1,
    generated_at: results.generated_at,
    decision: blocking.length
      ? "STRONG + POTENTIAL WORKFLOW BLOCKED"
      : "STRONG + POTENTIAL WORKFLOW PASSES DEVELOPMENT PRODUCT GATES",
    blocking_gates: blocking,
    gates,
    metrics: results.quality.global,
    phase4c_authorized_for_separate_session: blocking.length === 0,
    phase5_authorized: false,
    production_flag_enabled: false,
  };
  const receipt = {
    schema_version: 1,
    generated_at: results.generated_at,
    models: { embedding: "voyage-4-lite", reranking: "rerank-2.5" },
    endpoints: ["/embed-query", "/rerank"],
    requests: receipts,
    totals: results.usage,
    secret: { source: "VOYAGE_API_KEY process environment", printed: false, persisted: false, sent_to_browser: false },
  };
  const serializedResults = `${JSON.stringify(results, null, 2)}\n`;
  const serializedReceipt = `${JSON.stringify(receipt, null, 2)}\n`;
  const serializedGates = `${JSON.stringify(gateReport, null, 2)}\n`;
  if (/pa-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_-]{12,}/.test(
    serializedResults + serializedReceipt + serializedGates
  )) throw new Error("Refusing to write credential-like text.");
  await Promise.all([
    writeFile(new URL(RESULTS_PATH, ROOT), serializedResults, "utf8"),
    writeFile(new URL(RECEIPT_PATH, ROOT), serializedReceipt, "utf8"),
    writeFile(new URL(GATE_PATH, ROOT), serializedGates, "utf8"),
  ]);
  process.stdout.write(`${JSON.stringify({
    results: RESULTS_PATH,
    results_sha256: sha256(serializedResults),
    receipt: RECEIPT_PATH,
    receipt_sha256: sha256(serializedReceipt),
    gate_report: GATE_PATH,
    gate_report_sha256: sha256(serializedGates),
    decision: gateReport.decision,
    blocking_gates: blocking,
    metrics: results.quality.global,
    performance: results.performance,
    usage: results.usage,
  }, null, 2)}\n`);
}

await main();
