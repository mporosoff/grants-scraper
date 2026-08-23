#!/usr/bin/env node

// Disposable development-only hybrid Voyage feasibility harness.
//
// The tool uses only the two spent acceptance populations. It embeds public
// indexed parent/child passages in memory, compares BM25F, semantic, and fused
// candidate recall, and conditionally reranks a bounded union. It cannot admit
// results or change production behavior. Phase 4C data is never imported.

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const RESULTS_PATH = "evaluation/search_v2_hybrid_voyage_results.json";
const RECEIPT_PATH = "evaluation/search_v2_hybrid_voyage_api_receipt.json";
const AUDIT_PATH = "evaluation/search_v2_local_field_feasibility.json";
const MINILM_PATH = "evaluation/search_v2_local_minilm_results.json";
const PRIOR_VOYAGE_PATH = "evaluation/search_v2_voyage_reranker_results.json";
const LEAVEOUT_PATH = "evaluation/search_v2_local_architecture_leaveout.json";
const EMBEDDING_URL = "https://api.voyageai.com/v1/embeddings";
const RERANK_URL = "https://api.voyageai.com/v1/rerank";
const EMBEDDING_MODEL = "voyage-4-lite";
const EMBEDDING_DIMENSION = 1024;
const RERANK_MODEL = "rerank-2.5";
const BM25_DEPTH = 200;
const SEMANTIC_DEPTH = 200;
const RERANK_DEPTH = 300;
const RRF_K = 60;
const CORPUS_BATCH_SIZE = 256;
const MAX_PASSAGE_CHARS = 3_000;
const REQUEST_TIMEOUT_MS = 120_000;
const EMBEDDING_PRICE_PER_MILLION_USD = 0.02;
const RERANK_PRICE_PER_MILLION_USD = 0.05;
const PUBLISHED_FREE_TOKENS = 200_000_000;
const CANDIDATE_RECALL_GATE = 0.90;
const FINAL_RECALL_50_GATE = 0.85;
const FINAL_RECALL_10_GATE = 0.75;
const QUERY_INSTRUCTION = "Rank public funding opportunities by whether their authoritative scientific or programmatic scope supports the complete research intent. Do not reward partial word overlap when a major query concept is absent.\n\nResearch query: <QUERY>";
const DEPTHS = Object.freeze([10, 50, 100, 200]);
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
  const ordered = values.filter(Number.isFinite).sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)] || 0;
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function uniqueText(values) {
  const seen = new Set();
  return values.flatMap(value => {
    const text = normalizeText(value);
    if (!text || seen.has(text)) return [];
    seen.add(text);
    return [text];
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
  return clipped(parts.filter(Boolean).join("\n"), MAX_PASSAGE_CHARS);
}

function authoritativeSourceEvidence(record) {
  return ((record?.document_evidence?.facts || []))
    .filter(fact => fact?.type === "review_criteria")
    .flatMap(fact => [fact.value, fact.citation?.quote])
    .filter(Boolean);
}

function parentPassage(record) {
  const values = {
    parent_title: [record.title],
    authoritative_program_area: record.program_area_labels || record.document_program_areas || [],
    parent_description: [record.description],
    bounded_source_evidence: authoritativeSourceEvidence(record),
  };
  return {
    fields: Object.entries(values).flatMap(([field, items]) => uniqueText(items).length ? [field] : []),
    text: boundedPassage([
      labeled("Parent title", values.parent_title, 500),
      labeled("Authoritative program area", values.authoritative_program_area, 600),
      labeled("Parent description", values.parent_description, 1_650),
      labeled("Public source evidence", values.bounded_source_evidence, 1_200),
    ]),
  };
}

function childPassage(record, parent) {
  const values = {
    parent_title: [parent?.title],
    child_title: [record.title],
    child_summary: [record.description || record.summary],
    authoritative_program_area: record.program_area_labels || [],
  };
  return {
    fields: Object.entries(values).flatMap(([field, items]) => uniqueText(items).length ? [field] : []),
    text: boundedPassage([
      labeled("Parent title", values.parent_title, 500),
      labeled("Publication-eligible child title", values.child_title, 700),
      labeled("Authoritative program area", values.authoritative_program_area, 600),
      labeled("Child summary", values.child_summary, 2_000),
    ]),
  };
}

function scoreScale(values) {
  const positive = values.filter(value => value > 0);
  return Math.max(1e-9, percentile(positive, .9));
}

function buildCorpus(harness) {
  const currentness = harness.parentEngine.score("funding research", { evidence: false });
  const rejected = new Set(currentness.currentnessRejectedIndexes || []);
  const parentById = new Map();
  const passages = [];
  harness.parentCatalog.opportunities.forEach((record, index) => {
    if (record.status === "archived" || rejected.has(index)) return;
    const passage = parentPassage(record);
    if (!passage.text) return;
    const parentId = String(record.opportunity_id);
    parentById.set(parentId, record);
    passages.push({
      parent_id: parentId,
      passage_id: `parent:${parentId}`,
      passage_kind: "parent",
      record_id: parentId,
      title: record.title || "",
      fields: passage.fields,
      text: passage.text,
    });
  });
  harness.childCatalog.opportunities.forEach(record => {
    const parentId = String(record.parent_id || "");
    const parent = parentById.get(parentId);
    if (!parent || record.status === "archived") return;
    const passage = childPassage(record, parent);
    if (!passage.text) return;
    const recordId = String(record.subtopic_id || record.opportunity_id);
    passages.push({
      parent_id: parentId,
      passage_id: `child:${recordId}`,
      passage_kind: "publication_eligible_child",
      record_id: recordId,
      title: record.title || "",
      fields: passage.fields,
      text: passage.text,
    });
  });
  return passages.sort((left, right) => left.passage_id.localeCompare(right.passage_id));
}

function buildBm25Candidates(harness, ranked, corpusById) {
  const parentScores = Array.from(ranked.parentDirect.discoveryScores || []);
  const childScores = Array.from(ranked.childDirect.discoveryScores || []);
  const parentScale = scoreScale(parentScores);
  const childScale = scoreScale(childScores);
  const rejected = new Set(ranked.parentDirect.currentnessRejectedIndexes || []);
  const candidates = [];
  harness.parentCatalog.opportunities.forEach((record, index) => {
    const score = Number(parentScores[index] || 0);
    const item = corpusById.get(`parent:${record.opportunity_id}`);
    if (!(score > 0) || rejected.has(index) || !item) return;
    candidates.push({ ...item, bm25f_raw_score: score, bm25f_score: score / parentScale });
  });
  harness.childCatalog.opportunities.forEach((record, index) => {
    const score = Number(childScores[index] || 0);
    const recordId = String(record.subtopic_id || record.opportunity_id);
    const item = corpusById.get(`child:${recordId}`);
    if (!(score > 0) || !item) return;
    candidates.push({ ...item, bm25f_raw_score: score, bm25f_score: score / childScale });
  });
  return candidates.sort((left, right) => (
    right.bm25f_score - left.bm25f_score
    || right.bm25f_raw_score - left.bm25f_raw_score
    || left.passage_id.localeCompare(right.passage_id)
  ));
}

function strongestParents(passages, scoreKey) {
  const parents = new Map();
  passages.forEach(passage => {
    const current = parents.get(passage.parent_id);
    if (
      !current
      || Number(passage[scoreKey]) > Number(current[scoreKey])
      || (
        Number(passage[scoreKey]) === Number(current[scoreKey])
        && passage.passage_id.localeCompare(current.passage_id) < 0
      )
    ) parents.set(passage.parent_id, passage);
  });
  return [...parents.values()].sort((left, right) => (
    Number(right[scoreKey]) - Number(left[scoreKey])
    || left.parent_id.localeCompare(right.parent_id)
  ));
}

function parentIdsAtPassageDepth(passages, scoreKey, depth) {
  return strongestParents(passages.slice(0, depth), scoreKey).map(item => item.parent_id);
}

function requiredRecall(ids, required) {
  if (!required.length) return 1;
  return number(required.filter(id => ids.includes(id)).length / required.length);
}

function candidateMetrics(passages, scoreKey, queryTruth, extraDepths = []) {
  const required = queryTruth.required_primary_ids || [];
  const depths = [...new Set([...DEPTHS, ...extraDepths])].sort((left, right) => left - right);
  const recall = Object.fromEntries(depths.map(depth => [
    depth,
    requiredRecall(parentIdsAtPassageDepth(passages, scoreKey, depth), required),
  ]));
  const fullIds = strongestParents(passages, scoreKey).map(item => item.parent_id);
  return {
    passage_count: passages.length,
    parent_count: fullIds.length,
    required_recall_by_passage_depth: recall,
    required_recall_full: requiredRecall(fullIds, required),
    required_ranks: Object.fromEntries(required.map(id => {
      const rank = passages.findIndex(item => item.parent_id === id);
      return [id, rank < 0 ? null : rank + 1];
    })),
    required_parent_ranks_after_rollup: Object.fromEntries(required.map(id => {
      const rank = fullIds.indexOf(id);
      return [id, rank < 0 ? null : rank + 1];
    })),
  };
}

function fuseCandidates(bm25, semantic) {
  const map = new Map();
  bm25.slice(0, BM25_DEPTH).forEach((item, index) => map.set(item.passage_id, {
    ...item,
    bm25f_rank: index + 1,
    semantic_rank: null,
    rrf_score: 1 / (RRF_K + index + 1),
  }));
  semantic.slice(0, SEMANTIC_DEPTH).forEach((item, index) => {
    const current = map.get(item.passage_id);
    const contribution = 1 / (RRF_K + index + 1);
    map.set(item.passage_id, current ? {
      ...current,
      semantic_score: item.semantic_score,
      semantic_rank: index + 1,
      rrf_score: current.rrf_score + contribution,
    } : {
      ...item,
      bm25f_rank: null,
      semantic_rank: index + 1,
      rrf_score: contribution,
    });
  });
  return [...map.values()].sort((left, right) => (
    right.rrf_score - left.rrf_score
    || Number(left.bm25f_rank || Number.MAX_SAFE_INTEGER) - Number(right.bm25f_rank || Number.MAX_SAFE_INTEGER)
    || Number(left.semantic_rank || Number.MAX_SAFE_INTEGER) - Number(right.semantic_rank || Number.MAX_SAFE_INTEGER)
    || left.passage_id.localeCompare(right.passage_id)
  ));
}

function norm(vector) {
  let sum = 0;
  for (let index = 0; index < vector.length; index += 1) sum += vector[index] * vector[index];
  return Math.sqrt(sum) || 1;
}

function cosine(left, leftNorm, right, rightNorm) {
  let dot = 0;
  for (let index = 0; index < left.length; index += 1) dot += left[index] * right[index];
  return dot / (leftNorm * rightNorm);
}

function semanticCandidates(corpus, corpusVectors, corpusNorms, queryVector) {
  const queryNorm = norm(queryVector);
  return corpus.map((passage, index) => ({
    ...passage,
    semantic_score: cosine(queryVector, queryNorm, corpusVectors[index], corpusNorms[index]),
  })).sort((left, right) => (
    right.semantic_score - left.semantic_score
    || left.passage_id.localeCompare(right.passage_id)
  ));
}

function gain(label) {
  if (label === "primary_relevant") return 3;
  if (label === "broader_program_fit") return 1;
  return 0;
}

function ndcgAt10(ids, queryTruth) {
  const judgments = queryTruth.judgments || {};
  const dcg = ids.slice(0, 10).reduce((sum, id, index) => (
    sum + gain(judgments[id]?.label) / Math.log2(index + 2)
  ), 0);
  const ideal = Object.values(judgments).map(item => gain(item.label)).sort((a, b) => b - a).slice(0, 10);
  const idcg = ideal.reduce((sum, value, index) => sum + value / Math.log2(index + 2), 0);
  return idcg ? number(dcg / idcg) : 1;
}

function rankedResult(passages, queryTruth, scoreKey) {
  const parents = strongestParents(passages, scoreKey);
  const ids = parents.map(item => item.parent_id);
  const top10 = parents.slice(0, 10);
  const required = queryTruth.required_primary_ids || [];
  const judgments = queryTruth.judgments || {};
  const judged = top10.filter(item => judgments[item.parent_id]);
  const primary = judged.filter(item => judgments[item.parent_id]?.label === "primary_relevant");
  return {
    parent_count: parents.length,
    required_recall_at_10: requiredRecall(ids.slice(0, 10), required),
    required_recall_at_50: requiredRecall(ids.slice(0, 50), required),
    ndcg_at_10: ndcgAt10(ids, queryTruth),
    precision_at_10_over_judged: judged.length ? number(primary.length / judged.length) : null,
    precision_at_10_conservative_lower_bound: number(primary.length / Math.max(1, top10.length)),
    known_irrelevant_at_10: top10.filter(item => judgments[item.parent_id]?.label === "irrelevant").map(item => item.parent_id),
    broader_at_10: top10.filter(item => judgments[item.parent_id]?.label === "broader_program_fit").map(item => item.parent_id),
    unjudged_at_10: top10.filter(item => !judgments[item.parent_id]).map(item => item.parent_id),
    required_ranks: Object.fromEntries(required.map(id => {
      const rank = ids.indexOf(id);
      return [id, rank < 0 ? null : rank + 1];
    })),
    top_10: top10.map(item => ({
      id: item.parent_id,
      score: number(item[scoreKey]),
      passage_id: item.passage_id,
      passage_kind: item.passage_kind,
      record_id: item.record_id,
      title: item.title,
      fields: item.fields,
      bm25f_rank: item.bm25f_rank ?? null,
      semantic_rank: item.semantic_rank ?? null,
      existing_truth: judgments[item.parent_id]?.label || null,
    })),
  };
}

function summarizeCandidateRows(rows, key) {
  const required = rows.flatMap(row => Object.values(row[key].required_ranks));
  const recallAt = depth => number(
    required.filter(rank => rank !== null && rank <= depth).length / Math.max(1, required.length),
  );
  return {
    query_count: rows.length,
    required_anchor_count: required.length,
    required_recall_at_10: recallAt(10),
    required_recall_at_50: recallAt(50),
    required_recall_at_100: recallAt(100),
    required_recall_at_200: recallAt(200),
    required_recall_full: number(required.filter(rank => rank !== null).length / Math.max(1, required.length)),
  };
}

function summarizeFinalRows(rows, key) {
  const entries = rows.map(row => row[key]).filter(Boolean);
  const requiredRanks = entries.flatMap(entry => Object.values(entry.required_ranks));
  const top10 = entries.flatMap(entry => entry.top_10);
  const judged = top10.filter(item => item.existing_truth);
  const primary = judged.filter(item => item.existing_truth === "primary_relevant");
  return {
    query_count: entries.length,
    required_anchor_count: requiredRanks.length,
    required_recall_at_10: number(requiredRanks.filter(rank => rank !== null && rank <= 10).length / Math.max(1, requiredRanks.length)),
    required_recall_at_50: number(requiredRanks.filter(rank => rank !== null && rank <= 50).length / Math.max(1, requiredRanks.length)),
    query_average_ndcg_at_10: number(entries.reduce((sum, item) => sum + item.ndcg_at_10, 0) / Math.max(1, entries.length)),
    precision_at_10_over_judged: judged.length ? number(primary.length / judged.length) : null,
    precision_at_10_conservative_lower_bound: number(primary.length / Math.max(1, top10.length)),
    known_irrelevant_top_10_count: top10.filter(item => item.existing_truth === "irrelevant").length,
    broader_top_10_count: top10.filter(item => item.existing_truth === "broader_program_fit").length,
    unjudged_top_10_count: top10.filter(item => !item.existing_truth).length,
  };
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

async function sha256File(path) {
  return createHash("sha256").update(await readFile(new URL(path, ROOT))).digest("hex");
}

async function frozenHashes() {
  return Object.fromEntries(await Promise.all(FROZEN_FILES.map(async path => [path, await sha256File(path)])));
}

function gitState() {
  const executable = process.env.FF_GIT_EXECUTABLE || "git";
  const git = (...args) => execFileSync(executable, args, {
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

function corpusHash(corpus) {
  const hash = createHash("sha256");
  corpus.forEach(item => hash.update(`${item.passage_id}\0${item.parent_id}\0${item.text}\n`));
  return hash.digest("hex");
}

async function postJson(url, apiKey, body) {
  const serialized = JSON.stringify(body);
  const started = performance.now();
  const response = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body: serialized,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  const text = await response.text();
  const latency = performance.now() - started;
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`Voyage returned non-JSON response with HTTP ${response.status}.`);
  }
  if (!response.ok) {
    const message = normalizeText(payload?.detail || payload?.message || payload?.error || "request failed");
    const error = new Error(`Voyage request failed with HTTP ${response.status}: ${message.slice(0, 300)}`);
    error.status = response.status;
    error.retryAfter = Number(response.headers.get("retry-after") || 0);
    throw error;
  }
  return {
    payload,
    receipt: {
      http_status: response.status,
      request_id: response.headers.get("request-id") || response.headers.get("x-request-id") || null,
      model: payload.model || body.model,
      usage_total_tokens: Number(payload.usage?.total_tokens || 0),
      request_payload_bytes: Buffer.byteLength(serialized, "utf8"),
      response_payload_bytes: Buffer.byteLength(text, "utf8"),
      latency_ms: number(latency),
    },
  };
}

async function embed(apiKey, inputs, inputType) {
  const result = await postJson(EMBEDDING_URL, apiKey, {
    input: inputs,
    model: EMBEDDING_MODEL,
    input_type: inputType,
    truncation: true,
    output_dimension: EMBEDDING_DIMENSION,
    output_dtype: "float",
  });
  const data = result.payload.data || [];
  if (data.length !== inputs.length) throw new Error(`Voyage returned ${data.length} embeddings for ${inputs.length} inputs.`);
  const ordered = data.slice().sort((left, right) => Number(left.index) - Number(right.index));
  const vectors = ordered.map(item => Float32Array.from(item.embedding || []));
  if (vectors.some(vector => vector.length !== EMBEDDING_DIMENSION)) {
    throw new Error("Voyage returned an unexpected embedding dimension.");
  }
  return { vectors, receipt: result.receipt };
}

function voyageQuery(query) {
  return QUERY_INSTRUCTION.replace("<QUERY>", query);
}

async function rerank(apiKey, query, passages) {
  let attempts = 0;
  while (attempts < 3) {
    attempts += 1;
    try {
      const result = await postJson(RERANK_URL, apiKey, {
        query: voyageQuery(query),
        documents: passages.map(item => item.text),
        model: RERANK_MODEL,
        top_k: passages.length,
        return_documents: false,
        truncation: true,
      });
      const rankings = result.payload.data || result.payload.results;
      if (!Array.isArray(rankings) || rankings.length !== passages.length) {
        throw new Error(`Voyage returned ${rankings?.length ?? "no"} rankings for ${passages.length} passages.`);
      }
      return {
        passages: rankings.map(item => ({
          ...passages[Number(item.index)],
          voyage_score: Number(item.relevance_score),
        })).sort((left, right) => (
          right.voyage_score - left.voyage_score || left.passage_id.localeCompare(right.passage_id)
        )),
        receipt: { ...result.receipt, attempt_count: attempts },
      };
    } catch (error) {
      if (error.status !== 429 || attempts >= 3) throw error;
      const waitMs = Math.min(55_000, Math.max(5_000, Number(error.retryAfter || 15) * 1_000));
      await new Promise(resolve => setTimeout(resolve, waitMs));
    }
  }
  throw new Error("Voyage rerank retry loop ended unexpectedly.");
}

async function loadPopulations() {
  return Promise.all(POPULATIONS.map(async population => ({
    ...population,
    frameData: JSON.parse(await readFile(new URL(population.frame, ROOT), "utf8")),
    truthData: JSON.parse(await readFile(new URL(population.truth, ROOT), "utf8")),
  })));
}

async function run() {
  const apiKey = process.env.VOYAGE_API_KEY;
  if (!apiKey) throw new Error("VOYAGE_API_KEY is required and must remain process-local.");
  const write = process.argv.includes("--write");
  const [base, populations, audit, minilm, priorVoyage, leaveout, hashesBefore] = await Promise.all([
    loadHarness(),
    loadPopulations(),
    readFile(new URL(AUDIT_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(MINILM_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(PRIOR_VOYAGE_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(LEAVEOUT_PATH, ROOT), "utf8").then(JSON.parse),
    frozenHashes(),
  ]);
  if (Object.values(leaveout.active_manual_relationship_mappings || {}).some(Number)) {
    throw new Error("Hybrid leave-out evaluation requires zero active manual relationship mappings.");
  }
  const harness = makeVariantHarness(base, { searchV2: true });
  const corpus = buildCorpus(harness);
  const corpusById = new Map(corpus.map(item => [item.passage_id, item]));
  const corpusStarted = performance.now();
  const corpusVectors = [];
  const corpusReceipts = [];
  for (let offset = 0; offset < corpus.length; offset += CORPUS_BATCH_SIZE) {
    const batch = corpus.slice(offset, offset + CORPUS_BATCH_SIZE);
    const embedded = await embed(apiKey, batch.map(item => item.text), "document");
    corpusVectors.push(...embedded.vectors);
    corpusReceipts.push({
      batch_index: corpusReceipts.length,
      passage_offset: offset,
      passage_count: batch.length,
      ...embedded.receipt,
    });
    process.stderr.write(`[corpus ${Math.min(offset + batch.length, corpus.length)}/${corpus.length}] tokens=${embedded.receipt.usage_total_tokens} latency_ms=${embedded.receipt.latency_ms}\n`);
  }
  const corpusBuildMs = performance.now() - corpusStarted;
  const corpusNorms = corpusVectors.map(vector => norm(vector));
  const items = populations.flatMap(population => population.frameData.queries.map(item => ({ population, item })));
  const rows = [];
  const workRows = [];
  const queryReceipts = [];
  for (const [index, { population, item }] of items.entries()) {
    const truth = population.truthData.queries[item.id];
    if (!truth || truth.query !== item.query) throw new Error(`Spent query/truth mismatch: ${item.id}`);
    const queryEmbedding = await embed(apiKey, [item.query], "query");
    queryReceipts.push({ population: population.id, query_id: item.id, ...queryEmbedding.receipt });
    const bm25Started = performance.now();
    const ranked = rankQuery(harness, item.query, { evidence: true });
    const bm25 = buildBm25Candidates(harness, ranked, corpusById).slice(0, BM25_DEPTH);
    const bm25Ms = performance.now() - bm25Started;
    const semanticStarted = performance.now();
    const semantic = semanticCandidates(corpus, corpusVectors, corpusNorms, queryEmbedding.vectors[0]).slice(0, SEMANTIC_DEPTH);
    const semanticMs = performance.now() - semanticStarted;
    const union = fuseCandidates(bm25, semantic);
    const bm25Metrics = candidateMetrics(bm25, "bm25f_score", truth);
    const semanticMetrics = candidateMetrics(semantic, "semantic_score", truth);
    const unionMetrics = candidateMetrics(union, "rrf_score", truth, [RERANK_DEPTH, union.length]);
    const bm25Ids = new Set(bm25.map(candidate => candidate.passage_id));
    const semanticIds = new Set(semantic.map(candidate => candidate.passage_id));
    const overlap = [...bm25Ids].filter(id => semanticIds.has(id)).length;
    const row = {
      population: population.id,
      id: item.id,
      query: item.query,
      family: family(item.id),
      discipline: item.discipline || "",
      stratum: item.stratum || "",
      required_primary_ids: truth.required_primary_ids || [],
      zero_primary_hard_negative: !(truth.required_primary_ids || []).length
        && !Object.values(truth.judgments || {}).some(value => value.label === "primary_relevant"),
      candidate_retrieval: {
        bm25f: bm25Metrics,
        semantic: semanticMetrics,
        union: unionMetrics,
        overlap_passage_count: overlap,
        overlap_jaccard: number(overlap / Math.max(1, new Set([...bm25Ids, ...semanticIds]).size)),
        union_deduplicated_passage_count: union.length,
      },
      timings: {
        query_embedding_ms: queryEmbedding.receipt.latency_ms,
        bm25f_ms: number(bm25Ms),
        semantic_retrieval_ms: number(semanticMs),
      },
      baseline_final: rankedResult(bm25, truth, "bm25f_score"),
      hybrid_final: null,
    };
    rows.push(row);
    workRows.push({ row, truth, union });
    process.stderr.write(`[candidates ${index + 1}/${items.length}] ${item.id} bm=${bm25.length} sem=${semantic.length} union=${union.length}\n`);
  }
  const candidateSummary = {
    bm25f: summarizeCandidateRows(rows.map(row => ({ candidate: row.candidate_retrieval.bm25f })), "candidate"),
    semantic: summarizeCandidateRows(rows.map(row => ({ candidate: row.candidate_retrieval.semantic })), "candidate"),
    union: summarizeCandidateRows(rows.map(row => ({ candidate: row.candidate_retrieval.union })), "candidate"),
  };
  const missingBm25 = rows.flatMap(row => Object.entries(row.candidate_retrieval.bm25f.required_ranks)
    .filter(([_id, rank]) => rank === null)
    .map(([id]) => ({ row, id })));
  const missingRecovery = missingBm25.map(({ row, id }) => ({
    population: row.population,
    query_id: row.id,
    query: row.query,
    required_result_id: id,
    semantic_rank: row.candidate_retrieval.semantic.required_ranks[id] ?? null,
    union_rank: row.candidate_retrieval.union.required_ranks[id] ?? null,
    semantic_recovered_at_200: Number(row.candidate_retrieval.semantic.required_ranks[id] || Number.MAX_SAFE_INTEGER) <= 200,
    union_recovered_at_300: Number(row.candidate_retrieval.union.required_ranks[id] || Number.MAX_SAFE_INTEGER) <= 300,
  }));
  const unionAt300Ranks = rows.flatMap(row => Object.values(row.candidate_retrieval.union.required_ranks)
    .map(rank => rank !== null && rank <= RERANK_DEPTH));
  const unionRecallAt300 = number(unionAt300Ranks.filter(Boolean).length / Math.max(1, unionAt300Ranks.length));
  const candidateGatePassed = unionRecallAt300 >= CANDIDATE_RECALL_GATE;
  const rerankReceipts = [];
  if (candidateGatePassed) {
    for (const [index, work] of workRows.entries()) {
      const selected = work.union.slice(0, RERANK_DEPTH);
      const reranked = await rerank(apiKey, work.row.query, selected);
      rerankReceipts.push({
        population: work.row.population,
        query_id: work.row.id,
        passage_count: selected.length,
        ...reranked.receipt,
      });
      work.row.hybrid_final = rankedResult(reranked.passages, work.truth, "voyage_score");
      work.row.timings.rerank_ms = reranked.receipt.latency_ms;
      work.row.timings.end_to_end_component_sum_ms = number(
        work.row.timings.query_embedding_ms
        + work.row.timings.bm25f_ms
        + work.row.timings.semantic_retrieval_ms
        + work.row.timings.rerank_ms
      );
      process.stderr.write(`[rerank ${index + 1}/${workRows.length}] ${work.row.id} passages=${selected.length} tokens=${reranked.receipt.usage_total_tokens} latency_ms=${reranked.receipt.latency_ms}\n`);
    }
  }
  const baselineFinal = summarizeFinalRows(rows, "baseline_final");
  const hybridFinal = candidateGatePassed ? summarizeFinalRows(rows, "hybrid_final") : null;
  const baselineTop10 = new Map(rows.map(row => [row.id, new Set(row.baseline_final.top_10.map(item => item.id))]));
  const knownIrrelevantPromotions = candidateGatePassed ? rows.flatMap(row => row.hybrid_final.top_10
    .filter(item => item.existing_truth === "irrelevant" && !baselineTop10.get(row.id).has(item.id))
    .map((item, index) => ({
      population: row.population,
      query_id: row.id,
      query: row.query,
      result_id: item.id,
      title: item.title,
      hybrid_rank: row.hybrid_final.top_10.findIndex(value => value.id === item.id) + 1,
    }))) : [];
  const hardRows = rows.filter(row => row.zero_primary_hard_negative);
  const acronymPromotions = knownIrrelevantPromotions.filter(item => /acronym|\b[A-Z]{2,6}\b/.test(
    `${item.query_id} ${item.query}`,
  ));
  const baselineHardNegativeKnownIrrelevant = hardRows.reduce(
    (sum, row) => sum + row.baseline_final.top_10.filter(item => item.existing_truth === "irrelevant").length,
    0,
  );
  const hybridHardNegativeKnownIrrelevant = candidateGatePassed ? hardRows.reduce(
    (sum, row) => sum + row.hybrid_final.top_10.filter(item => item.existing_truth === "irrelevant").length,
    0,
  ) : null;
  const noSystematicKnownIrrelevantPromotion = Boolean(
    candidateGatePassed
    && hybridFinal.known_irrelevant_top_10_count <= baselineFinal.known_irrelevant_top_10_count
    && hybridHardNegativeKnownIrrelevant <= baselineHardNegativeKnownIrrelevant
  );
  const requiredMovements = candidateGatePassed ? rows.flatMap(row => Object.entries(row.hybrid_final.required_ranks).map(([id, hybrid]) => ({
    population: row.population,
    query_id: row.id,
    query: row.query,
    required_result_id: id,
    bm25f_rank: row.baseline_final.required_ranks[id] ?? null,
    hybrid_rank: hybrid,
  }))) : [];
  const finalQualityPassed = Boolean(
    candidateGatePassed
    && hybridFinal.required_recall_at_50 >= FINAL_RECALL_50_GATE
    && hybridFinal.required_recall_at_10 >= FINAL_RECALL_10_GATE
    && noSystematicKnownIrrelevantPromotion
  );
  const auditIds = new Set(audit.rows.map(item => `${item.query_id}\0${item.required_result_id}`));
  const vocabularyGapIds = new Set(audit.rows.filter(item => (
    item.conventional_fielded_feasibility === "INSUFFICIENT_INDEXED_TEXT_FOR_CONVENTIONAL_RANKING"
  )).map(item => `${item.query_id}\0${item.required_result_id}`));
  const slice = ids => requiredMovements.filter(item => ids.has(`${item.query_id}\0${item.required_result_id}`));
  const sliceSummary = values => ({
    anchor_count: values.length,
    bm25f_recall_at_10: number(values.filter(item => item.bm25f_rank !== null && item.bm25f_rank <= 10).length / Math.max(1, values.length)),
    hybrid_recall_at_10: number(values.filter(item => item.hybrid_rank !== null && item.hybrid_rank <= 10).length / Math.max(1, values.length)),
    hybrid_recall_at_50: number(values.filter(item => item.hybrid_rank !== null && item.hybrid_rank <= 50).length / Math.max(1, values.length)),
    movements: values,
  });
  const embeddingTokens = corpusReceipts.reduce((sum, item) => sum + item.usage_total_tokens, 0)
    + queryReceipts.reduce((sum, item) => sum + item.usage_total_tokens, 0);
  const rerankTokens = rerankReceipts.reduce((sum, item) => sum + item.usage_total_tokens, 0);
  const estimatedEmbeddingCost = number(embeddingTokens / 1_000_000 * EMBEDDING_PRICE_PER_MILLION_USD);
  const estimatedRerankCost = number(rerankTokens / 1_000_000 * RERANK_PRICE_PER_MILLION_USD);
  const hashesAfter = await frozenHashes();
  const frozenDrift = Object.keys(hashesBefore).filter(path => hashesBefore[path] !== hashesAfter[path]);
  if (frozenDrift.length) throw new Error(`Frozen production/Phase-4C files drifted: ${frozenDrift.join(", ")}`);
  const decision = finalQualityPassed
    ? "HYBRID VOYAGE RETRIEVAL + RERANKING CLEARS THE QUALITY BAR — PRODUCTION ARCHITECTURE SHOULD BE CONSIDERED"
    : "HYBRID SEMANTIC RETRIEVAL STILL DOES NOT CLEAR THE QUALITY BAR — DISCARD THIS DIRECTION";
  const payload = {
    schema_version: 1,
    experiment: "hybrid_voyage_embedding_retrieval_plus_rerank_2_5",
    generated_at: new Date().toISOString(),
    status: "completed_development_only_no_production_integration",
    decision,
    git_state: gitState(),
    architecture: {
      lexical_candidate_source: "unchanged local BM25F",
      semantic_candidate_source: `${EMBEDDING_MODEL} cosine similarity`,
      embedding_dimension: EMBEDDING_DIMENSION,
      embedding_input_types: { corpus: "document", query: "query" },
      candidate_depths: { bm25f: BM25_DEPTH, semantic: SEMANTIC_DEPTH },
      union_fusion: `reciprocal rank fusion k=${RRF_K}`,
      rerank_union_passage_depth: RERANK_DEPTH,
      reranker: RERANK_MODEL,
      parent_aggregation: "single strongest reranked parent-or-child passage",
      semantic_scores_create_source_evidence: false,
      production_admission_changed: false,
    },
    model_choice: {
      model: EMBEDDING_MODEL,
      provider_revision: "not exposed by the real-time embedding API",
      rationale: "current Voyage general retrieval model optimized for lowest latency and cost",
      dimension: EMBEDDING_DIMENSION,
      output_dtype: "float",
    },
    corpus: {
      passage_count: corpus.length,
      parent_passage_count: corpus.filter(item => item.passage_kind === "parent").length,
      child_passage_count: corpus.filter(item => item.passage_kind === "publication_eligible_child").length,
      stable_passage_id_contract: "parent:<opportunity_id> or child:<subtopic_id>",
      sha256: corpusHash(corpus),
      passage_character_cap: MAX_PASSAGE_CHARS,
      vectors_persisted_or_committed: false,
      public_fields: [
        "parent_title",
        "parent_description",
        "authoritative_program_area",
        "publication_eligible_child_title",
        "child_summary",
        "bounded_public_source_evidence",
      ],
    },
    evaluation_population: {
      spent_only: true,
      query_count: rows.length,
      required_anchor_count: candidateSummary.bm25f.required_anchor_count,
      hard_negative_query_count: hardRows.length,
      phase4b_audit_anchor_count: audit.rows.length,
      active_manual_relationship_mappings: leaveout.active_manual_relationship_mappings,
      phase4c_read_or_executed: false,
    },
    candidate_retrieval: {
      summary: candidateSummary,
      union_recall_at_300: unionRecallAt300,
      gate: {
        threshold: CANDIDATE_RECALL_GATE,
        passed: candidateGatePassed,
      },
      missing_bm25f_anchor_count: missingRecovery.length,
      missing_bm25f_anchors_recovered_by_semantic_at_200: missingRecovery.filter(item => item.semantic_recovered_at_200).length,
      missing_bm25f_anchors_recovered_by_union_at_300: missingRecovery.filter(item => item.union_recovered_at_300).length,
      missing_anchor_recovery: missingRecovery,
      overlap: {
        passage_overlap_total: rows.reduce((sum, row) => sum + row.candidate_retrieval.overlap_passage_count, 0),
        overlap_jaccard_p50: number(percentile(rows.map(row => row.candidate_retrieval.overlap_jaccard), .5)),
        overlap_jaccard_p95: number(percentile(rows.map(row => row.candidate_retrieval.overlap_jaccard), .95)),
        union_passages_p50: number(percentile(rows.map(row => row.candidate_retrieval.union_deduplicated_passage_count), .5)),
        union_passages_p95: number(percentile(rows.map(row => row.candidate_retrieval.union_deduplicated_passage_count), .95)),
      },
    },
    final_ranking: {
      executed: candidateGatePassed,
      baseline_bm25f: baselineFinal,
      prior_local_minilm: minilm.quality.summary.minilm_reranked_candidate[50],
      prior_voyage_rerank_only: priorVoyage.quality.voyage_reranked_at_depth_200,
      hybrid_voyage: hybridFinal,
      gates: {
        required_recall_at_10_threshold: FINAL_RECALL_10_GATE,
        required_recall_at_50_threshold: FINAL_RECALL_50_GATE,
        no_systematic_known_irrelevant_promotion: noSystematicKnownIrrelevantPromotion,
        known_irrelevant_top_10_not_worse: hybridFinal.known_irrelevant_top_10_count <= baselineFinal.known_irrelevant_top_10_count,
        hard_negative_known_irrelevant_top_10_not_worse: hybridHardNegativeKnownIrrelevant <= baselineHardNegativeKnownIrrelevant,
        observed_acronym_or_identifier_collision_count: acronymPromotions.length,
        exact_acronym_identifier_safeguard_required_for_any_production_design: true,
        passed: finalQualityPassed,
      },
      required_anchor_movements: requiredMovements,
      phase4b_19_anchor_audit: candidateGatePassed ? sliceSummary(slice(auditIds)) : null,
      vocabulary_gap_16_anchor_audit: candidateGatePassed ? sliceSummary(slice(vocabularyGapIds)) : null,
      known_irrelevant_promotions_into_top_10: knownIrrelevantPromotions,
      acronym_or_identifier_known_irrelevant_promotions: acronymPromotions,
      hard_negatives: candidateGatePassed ? {
        query_count: hardRows.length,
        baseline_top_10_known_irrelevant_count: baselineHardNegativeKnownIrrelevant,
        hybrid_top_10_known_primary_count: hardRows.reduce((sum, row) => sum + row.hybrid_final.top_10.filter(item => item.existing_truth === "primary_relevant").length, 0),
        hybrid_top_10_known_irrelevant_count: hybridHardNegativeKnownIrrelevant,
        hybrid_top_10_unjudged_count: hardRows.reduce((sum, row) => sum + row.hybrid_final.top_10.filter(item => !item.existing_truth).length, 0),
        semantic_scores_create_primary_admission: false,
      } : null,
    },
    performance: {
      corpus_embedding_build_ms: number(corpusBuildMs),
      corpus_embedding_API_calls: corpusReceipts.length,
      query_embedding_API_calls: queryReceipts.length,
      rerank_API_successful_calls: rerankReceipts.length,
      rerank_API_attempts: rerankReceipts.reduce((sum, item) => sum + Number(item.attempt_count || 1), 0),
      query_embedding_latency_p50_ms: number(percentile(queryReceipts.map(item => item.latency_ms), .5)),
      query_embedding_latency_p95_ms: number(percentile(queryReceipts.map(item => item.latency_ms), .95)),
      semantic_retrieval_latency_p50_ms: number(percentile(rows.map(row => row.timings.semantic_retrieval_ms), .5)),
      semantic_retrieval_latency_p95_ms: number(percentile(rows.map(row => row.timings.semantic_retrieval_ms), .95)),
      rerank_latency_p50_ms: number(percentile(rerankReceipts.map(item => item.latency_ms), .5)),
      rerank_latency_p95_ms: number(percentile(rerankReceipts.map(item => item.latency_ms), .95)),
      end_to_end_component_sum_p50_ms: number(percentile(rows.map(row => row.timings.end_to_end_component_sum_ms || 0), .5)),
      end_to_end_component_sum_p95_ms: number(percentile(rows.map(row => row.timings.end_to_end_component_sum_ms || 0), .95)),
    },
    cost: {
      corpus_embedding_tokens: corpusReceipts.reduce((sum, item) => sum + item.usage_total_tokens, 0),
      query_embedding_tokens: queryReceipts.reduce((sum, item) => sum + item.usage_total_tokens, 0),
      reranking_tokens: rerankTokens,
      embedding_price_per_million_tokens_usd: EMBEDDING_PRICE_PER_MILLION_USD,
      reranking_price_per_million_tokens_usd: RERANK_PRICE_PER_MILLION_USD,
      estimated_embedding_cost_at_paid_pricing_usd: estimatedEmbeddingCost,
      estimated_reranking_cost_at_paid_pricing_usd: estimatedRerankCost,
      estimated_total_cost_at_paid_pricing_usd: number(estimatedEmbeddingCost + estimatedRerankCost),
      published_free_tokens_per_model_family: PUBLISHED_FREE_TOKENS,
      remaining_account_free_balance_not_exposed_by_API: true,
    },
    safety: {
      production_search_code_changed: false,
      production_search_behavior_changed: false,
      phase4c_read_or_executed: false,
      phase4c_results_created: false,
      API_key_or_auth_headers_persisted: false,
      private_researcher_data_sent: false,
      vectors_persisted_or_committed: false,
      backend_worker_vector_database_or_model_assets_added: false,
      scientific_mappings_or_generated_metadata_added: false,
      frozen_hashes_before: hashesBefore,
      frozen_hashes_after: hashesAfter,
      frozen_file_drift: frozenDrift,
    },
    rows,
  };
  const receipt = {
    schema_version: 1,
    experiment: payload.experiment,
    generated_at: payload.generated_at,
    embedding: {
      model: EMBEDDING_MODEL,
      provider_revision: payload.model_choice.provider_revision,
      dimension: EMBEDDING_DIMENSION,
      corpus_requests: corpusReceipts,
      query_requests: queryReceipts,
      total_tokens: embeddingTokens,
    },
    reranking: {
      model: RERANK_MODEL,
      requests: rerankReceipts,
      total_tokens: rerankTokens,
    },
    cost: payload.cost,
    authentication: {
      source: "VOYAGE_API_KEY process environment variable",
      key_printed_or_persisted_by_harness: false,
      raw_authorization_headers_persisted: false,
    },
    corpus_vectors_persisted: false,
  };
  if (write) {
    await writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    await writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify({
    output: write ? RESULTS_PATH : null,
    receipt: write ? RECEIPT_PATH : null,
    decision,
    corpus: payload.corpus,
    candidates: payload.candidate_retrieval,
    final_ranking: payload.final_ranking,
    performance: payload.performance,
    cost: payload.cost,
  }, null, 2));
}

if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
  throw new Error("Hybrid Voyage feasibility harness refuses Phase-4C inputs.");
}

await run();
