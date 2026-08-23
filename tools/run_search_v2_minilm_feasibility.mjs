#!/usr/bin/env node

// Disposable development-only MiniLM cross-encoder feasibility harness.
//
// This tool intentionally reads only the two spent acceptance populations.
// It imports the unchanged production search modules for BM25F candidate
// discovery, reranks candidate passages in memory, and never changes primary
// admission or explanations. Phase 4C inputs are refused by name and are not
// imported anywhere in this file.

import { createHash } from "node:crypto";
import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const RESULTS_PATH = "evaluation/search_v2_local_minilm_results.json";
const RECEIPT_PATH = "evaluation/search_v2_local_minilm_model_receipt.json";
const RUNTIME_BENCHMARK_PATH = "evaluation/search_v2_local_minilm_runtime_benchmark.json";
const AUDIT_PATH = "evaluation/search_v2_local_field_feasibility.json";
const DEPTHS = Object.freeze([20, 30, 50]);
const MODEL = Object.freeze({
  id: "cross-encoder/ms-marco-MiniLM-L6-v2",
  revision: "233902d25c440f23af6f7d6e94d2946bac0bee0a",
  license: "apache-2.0",
  onnx_file: "onnx/model_quint8_avx2.onnx",
  model_file_name: "model_quint8_avx2",
  quantization: "dynamic UINT8 weights, AVX2-targeted ONNX export",
  maximum_sequence_length: 256,
});
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

function authoritativeSourceEvidence(record) {
  return ((record?.document_evidence?.facts || []))
    .filter(fact => fact?.type === "review_criteria")
    .flatMap(fact => [fact.value, fact.citation?.quote])
    .filter(Boolean);
}

function parentPassage(record) {
  const fields = {
    parent_title: [record.title],
    authoritative_program_area: record.program_area_labels || record.document_program_areas || [],
    parent_description: [record.description],
    bounded_source_evidence: authoritativeSourceEvidence(record),
  };
  const values = uniqueText(Object.values(fields).flat());
  return {
    fields: Object.entries(fields).flatMap(([field, fieldValues]) => (
      uniqueText(fieldValues).length ? [field] : []
    )),
    text: values.join(". "),
  };
}

function childPassage(record) {
  const fields = {
    child_title: [record.title],
    child_summary: [record.description || record.summary],
    authoritative_program_area: record.program_area_labels || [],
  };
  const values = uniqueText(Object.values(fields).flat());
  return {
    fields: Object.entries(fields).flatMap(([field, fieldValues]) => (
      uniqueText(fieldValues).length ? [field] : []
    )),
    text: values.join(". "),
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
  const parentIds = new Set(harness.parentCatalog.opportunities.map(record => (
    String(record.opportunity_id)
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
    if (!(rawScore > 0) || !parentIds.has(parentId)) return;
    const passage = childPassage(record);
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

function summarize(rows, resultKey, depth = null) {
  const entries = rows.map(row => depth === null ? row[resultKey] : row[resultKey][depth]);
  const required = entries.flatMap(entry => Object.values(entry.metrics.required_ranks));
  const top10 = entries.flatMap(entry => entry.top_10);
  const judgments = entries.flatMap(entry => entry.top_10_judgments);
  const primary = judgments.filter(label => label === "primary_relevant").length;
  const judged = judgments.filter(Boolean).length;
  const queryPrecisionConservative = entries.map(entry => (
    entry.metrics.returned_at_10
      ? entry.metrics.primary_at_10 / entry.metrics.returned_at_10
      : 1
  ));
  const queryPrecisionJudged = entries.map(entry => (
    entry.metrics.judged_at_10
      ? entry.metrics.primary_at_10 / entry.metrics.judged_at_10
      : 1
  ));
  return {
    query_count: entries.length,
    required_anchor_count: required.length,
    primary_precision_at_10_conservative: number(primary / Math.max(1, top10.length)),
    primary_precision_at_10_over_judged: judged ? number(primary / judged) : null,
    query_average_precision_at_10_conservative: number(
      queryPrecisionConservative.reduce((sum, value) => sum + value, 0)
      / Math.max(1, queryPrecisionConservative.length),
    ),
    query_average_precision_at_10_over_judged: number(
      queryPrecisionJudged.reduce((sum, value) => sum + value, 0)
      / Math.max(1, queryPrecisionJudged.length),
    ),
    unjudged_top_10_count: judgments.filter(label => !label).length,
    judged_irrelevant_top_10_count: judgments.filter(label => label === "irrelevant").length,
    judged_broader_top_10_count: judgments.filter(label => label === "broader_program_fit").length,
    required_recall_at_10: number(
      required.filter(rank => rank !== null && rank <= 10).length / Math.max(1, required.length),
    ),
    required_recall_at_50: number(
      required.filter(rank => rank !== null && rank <= 50).length / Math.max(1, required.length),
    ),
  };
}

function resultEntry(passages, queryTruth, scoreKey) {
  const strongest = strongestParents(passages, scoreKey);
  const ids = strongest.map(item => item.parent_id);
  const queryMetrics = metrics(ids, queryTruth);
  return {
    parent_count: strongest.length,
    metrics: queryMetrics,
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
    top_10_judgments: strongest.slice(0, 10).map(item => (
      queryTruth.judgments?.[item.parent_id]?.label || null
    )),
  };
}

async function recursiveFiles(directory, base = directory) {
  const entries = await readdir(directory, { withFileTypes: true }).catch(() => []);
  const rows = [];
  for (const entry of entries) {
    const full = `${directory}/${entry.name}`;
    if (entry.isDirectory()) rows.push(...await recursiveFiles(full, base));
    else if (entry.isFile()) {
      const info = await stat(full);
      rows.push({ path: full.slice(base.length + 1).replace(/\\/g, "/"), bytes: info.size, full });
    }
  }
  return rows;
}

async function sha256File(path) {
  const source = await readFile(path);
  return createHash("sha256").update(source).digest("hex");
}

async function loadCrossEncoder({ device = "cpu", localOnly = false } = {}) {
  const modulePath = process.env.FF_TRANSFORMERS_MODULE;
  const cacheDir = process.env.FF_MINILM_CACHE;
  if (!modulePath || !cacheDir) {
    throw new Error("Set FF_TRANSFORMERS_MODULE and FF_MINILM_CACHE to disposable paths outside the repository.");
  }
  const cacheBefore = await recursiveFiles(cacheDir);
  const rssBefore = process.memoryUsage().rss;
  const started = performance.now();
  const transformers = await import(pathToFileURL(modulePath).href);
  transformers.env.cacheDir = cacheDir;
  transformers.env.allowRemoteModels = !localOnly;
  transformers.env.allowLocalModels = true;
  const common = {
    revision: MODEL.revision,
    cache_dir: cacheDir,
    local_files_only: localOnly,
  };
  const tokenizer = await transformers.AutoTokenizer.from_pretrained(MODEL.id, common);
  const model = await transformers.AutoModelForSequenceClassification.from_pretrained(MODEL.id, {
    ...common,
    subfolder: "onnx",
    model_file_name: MODEL.model_file_name,
    dtype: "fp32",
    device,
  });
  const initializationMs = performance.now() - started;
  const rssAfter = process.memoryUsage().rss;
  const cacheAfter = await recursiveFiles(cacheDir);
  const beforePaths = new Set(cacheBefore.map(file => file.path));
  const newFiles = cacheAfter.filter(file => !beforePaths.has(file.path));
  return {
    transformers,
    tokenizer,
    model,
    runtime: {
      device,
      initialization_ms: number(initializationMs),
      rss_before_bytes: rssBefore,
      rss_after_initialization_bytes: rssAfter,
      rss_initialization_delta_bytes: rssAfter - rssBefore,
      cache_bytes_before: cacheBefore.reduce((sum, file) => sum + file.bytes, 0),
      cache_bytes_after: cacheAfter.reduce((sum, file) => sum + file.bytes, 0),
      downloaded_bytes_this_run: newFiles.reduce((sum, file) => sum + file.bytes, 0),
      cache_was_warm: newFiles.length === 0,
      cache_files: cacheAfter.map(file => ({ path: file.path, bytes: file.bytes })),
    },
  };
}

async function scorePassages(encoder, query, passages, batchSize = 8) {
  const scores = [];
  for (let offset = 0; offset < passages.length; offset += batchSize) {
    const batch = passages.slice(offset, offset + batchSize);
    const inputs = await encoder.tokenizer(
      batch.map(() => query),
      {
        text_pair: batch.map(item => item.text),
        padding: true,
        truncation: true,
        max_length: MODEL.maximum_sequence_length,
      },
    );
    const output = await encoder.model(inputs);
    scores.push(...Array.from(output.logits.data, value => Number(value)));
  }
  return passages.map((passage, index) => ({ ...passage, minilm_score: scores[index] }));
}

async function loadWasmCrossEncoder() {
  const transformersModule = process.env.FF_TRANSFORMERS_MODULE;
  const ortModule = process.env.FF_ORT_WEB_MODULE;
  const wasmDirectory = process.env.FF_ORT_WASM_DIR;
  const cacheDir = process.env.FF_MINILM_CACHE;
  if (!transformersModule || !ortModule || !wasmDirectory || !cacheDir) {
    throw new Error(
      "WASM benchmark requires FF_TRANSFORMERS_MODULE, FF_ORT_WEB_MODULE, FF_ORT_WASM_DIR, and FF_MINILM_CACHE.",
    );
  }
  const rssBefore = process.memoryUsage().rss;
  const started = performance.now();
  const [transformers, ort] = await Promise.all([
    import(pathToFileURL(transformersModule).href),
    import(pathToFileURL(ortModule).href),
  ]);
  transformers.env.cacheDir = cacheDir;
  transformers.env.allowRemoteModels = true;
  ort.env.wasm.wasmPaths = pathToFileURL(`${wasmDirectory}/`).href;
  ort.env.wasm.numThreads = 1;
  const tokenizer = await transformers.AutoTokenizer.from_pretrained(MODEL.id, {
    revision: MODEL.revision,
    cache_dir: cacheDir,
  });
  const modelFiles = await recursiveFiles(cacheDir);
  const modelFile = modelFiles.find(file => file.path.endsWith("model_quint8_avx2.onnx"));
  if (!modelFile) throw new Error("Pinned MiniLM ONNX file is absent from the external cache.");
  const session = await ort.InferenceSession.create(await readFile(modelFile.full), {
    executionProviders: ["wasm"],
  });
  return {
    tokenizer,
    ort,
    session,
    runtime: {
      device: "wasm_single_thread",
      initialization_ms: number(performance.now() - started),
      rss_before_bytes: rssBefore,
      rss_after_initialization_bytes: process.memoryUsage().rss,
      rss_initialization_delta_bytes: process.memoryUsage().rss - rssBefore,
    },
  };
}

async function scorePassagesWasm(encoder, query, passages, batchSize = 8) {
  const scores = [];
  for (let offset = 0; offset < passages.length; offset += batchSize) {
    const batch = passages.slice(offset, offset + batchSize);
    const inputs = await encoder.tokenizer(
      batch.map(() => query),
      {
        text_pair: batch.map(item => item.text),
        padding: true,
        truncation: true,
        max_length: MODEL.maximum_sequence_length,
      },
    );
    const feeds = Object.fromEntries(encoder.session.inputNames.map(name => {
      const value = inputs[name];
      if (!value) throw new Error(`Tokenizer did not produce required ONNX input: ${name}`);
      return [name, new encoder.ort.Tensor(value.type, value.data, value.dims)];
    }));
    const output = await encoder.session.run(feeds);
    scores.push(...Array.from(output.logits.data, value => Number(value)));
  }
  return passages.map((passage, index) => ({ ...passage, minilm_score: scores[index] }));
}

async function modelReceipt(encoder) {
  const modelFile = encoder.runtime.cache_files.find(file => (
    file.path.endsWith("model_quint8_avx2.onnx")
  ));
  const cacheRoot = process.env.FF_MINILM_CACHE;
  const modelPath = modelFile ? `${cacheRoot}/${modelFile.path}` : null;
  const tokenizerFiles = encoder.runtime.cache_files.filter(file => (
    /(?:tokenizer|special_tokens|vocab\.txt)/.test(file.path)
  ));
  return {
    schema_version: 1,
    experiment: "local_minilm_cross_encoder_reranker_feasibility",
    generated_at: new Date().toISOString(),
    model: MODEL,
    source: `https://huggingface.co/${MODEL.id}/tree/${MODEL.revision}`,
    runtime: {
      name: "Transformers.js",
      version: "4.2.0",
      onnxruntime_node_version: "1.24.3",
      node_version: process.version,
      execution_provider: encoder.runtime.device,
    },
    weights: {
      bytes: modelFile?.bytes || 0,
      sha256: modelPath ? await sha256File(modelPath) : null,
      committed_to_repository: false,
    },
    tokenizer: {
      bytes: tokenizerFiles.reduce((sum, file) => sum + file.bytes, 0),
      files: tokenizerFiles.map(({ path, bytes }) => ({ path, bytes })),
    },
    cache: encoder.runtime,
    repository_integration: false,
    production_code_changed: false,
    phase4c_read_or_executed: false,
  };
}

async function runReceipt() {
  const encoder = await loadCrossEncoder({ device: "cpu", localOnly: process.argv.includes("--local-only") });
  const prewarmStarted = performance.now();
  await scorePassages(encoder, "rare earth recycling", [{
    text: "Critical minerals extraction processing recovery and recycling research.",
  }]);
  encoder.runtime.first_inference_ms = number(performance.now() - prewarmStarted);
  const receipt = await modelReceipt(encoder);
  if (process.argv.includes("--write")) {
    await writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify(receipt, null, 2));
  await encoder.model.dispose?.();
}

async function runRuntimeBenchmark() {
  const deviceArgument = process.argv.find(argument => argument.startsWith("--device="));
  const device = deviceArgument?.split("=")[1] || "wasm";
  const [base, frame] = await Promise.all([
    loadHarness(),
    readFile(new URL(POPULATIONS[0].frame, ROOT), "utf8").then(JSON.parse),
  ]);
  const candidate = makeVariantHarness(base, { searchV2: true });
  const item = frame.queries.find(query => query.id === "hold_health_02") || frame.queries[0];
  const ranked = rankQuery(candidate, item.query, { evidence: false });
  const passages = buildCandidatePassages(candidate, ranked).slice(0, 20);
  const wasm = device === "wasm";
  const encoder = wasm
    ? await loadWasmCrossEncoder()
    : await loadCrossEncoder({ device, localOnly: false });
  const score = wasm ? scorePassagesWasm : scorePassages;
  await score(encoder, item.query, passages.slice(0, 1));
  const runs = [];
  for (let index = 0; index < 3; index += 1) {
    const started = performance.now();
    await score(encoder, item.query, passages);
    runs.push(performance.now() - started);
  }
  const benchmark = {
    schema_version: 1,
    experiment: "local_minilm_runtime_benchmark",
    generated_at: new Date().toISOString(),
    phase4c_read_or_executed: false,
    model: MODEL,
    query_id: item.id,
    candidate_passage_count: passages.length,
    maximum_sequence_length: MODEL.maximum_sequence_length,
    devices: {
      [wasm ? "wasm_single_thread" : device]: {
        initialization_ms: encoder.runtime.initialization_ms,
        rss_initialization_delta_bytes: encoder.runtime.rss_initialization_delta_bytes,
        warm_runs_ms: runs.map(number),
        warm_p50_ms: number(percentile(runs, .5)),
        warm_p95_ms: number(percentile(runs, .95)),
      },
    },
    webgpu_available_in_node_harness: typeof navigator !== "undefined" && Boolean(navigator.gpu),
  };
  if (process.argv.includes("--write")) {
    let existing = null;
    try {
      existing = JSON.parse(await readFile(new URL(RUNTIME_BENCHMARK_PATH, ROOT), "utf8"));
    } catch {
      // First device benchmark.
    }
    const output = existing ? {
      ...existing,
      generated_at: benchmark.generated_at,
      devices: { ...(existing.devices || {}), ...benchmark.devices },
    } : benchmark;
    await writeFile(new URL(RUNTIME_BENCHMARK_PATH, ROOT), `${JSON.stringify(output, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify(benchmark, null, 2));
  await encoder.model?.dispose?.();
  await encoder.session?.release?.();
}

async function runEvaluation() {
  const [base, audit, receipt] = await Promise.all([
    loadHarness(),
    readFile(new URL(AUDIT_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL(RECEIPT_PATH, ROOT), "utf8").then(JSON.parse),
  ]);
  const candidate = makeVariantHarness(base, { searchV2: true });
  const encoder = await loadCrossEncoder({
    device: "cpu",
    localOnly: process.argv.includes("--local-only"),
  });
  await scorePassages(encoder, "warmup query", [{ text: "Warmup passage for stable CPU timing." }]);
  const rows = [];
  for (const population of POPULATIONS) {
    const [frame, truth] = await Promise.all([
      readFile(new URL(population.frame, ROOT), "utf8").then(JSON.parse),
      readFile(new URL(population.truth, ROOT), "utf8").then(JSON.parse),
    ]);
    for (const item of frame.queries) {
      const queryTruth = truth.queries[item.id];
      if (!queryTruth || queryTruth.query !== item.query) {
        throw new Error(`Spent query/truth mismatch: ${item.id}`);
      }
      const bm25fStarted = performance.now();
      const ranked = rankQuery(candidate, item.query, { evidence: true });
      const passages = buildCandidatePassages(candidate, ranked);
      const bm25fMs = performance.now() - bm25fStarted;
      const baselineVisible = resultEntry(
        ranked.rows.map(row => ({
          parent_id: row.id,
          passage_id: row.bestChild?.id || `parent:${row.id}`,
          passage_kind: row.bestChild?.id ? "publication_eligible_child" : "parent",
          record_id: row.bestChild?.id || row.id,
          title: row.record?.title || "",
          fields: [],
          baseline_visible_score: row.score,
        })),
        queryTruth,
        "baseline_visible_score",
      );
      const reranked = {};
      const candidateBaseline = {};
      const timings = {};
      let scored = [];
      let priorDepth = 0;
      let cumulativeRerankMs = 0;
      for (const depth of DEPTHS) {
        const addition = passages.slice(priorDepth, depth);
        const started = performance.now();
        scored = scored.concat(await scorePassages(encoder, item.query, addition));
        const incremental = performance.now() - started;
        cumulativeRerankMs += incremental;
        const selectedBaseline = passages.slice(0, depth);
        candidateBaseline[depth] = resultEntry(selectedBaseline, queryTruth, "bm25f_candidate_score");
        reranked[depth] = resultEntry(scored, queryTruth, "minilm_score");
        timings[depth] = {
          passage_count: scored.length,
          incremental_rerank_ms: number(incremental),
          cumulative_rerank_ms: number(cumulativeRerankMs),
          total_with_bm25f_ms: number(cumulativeRerankMs + bm25fMs),
        };
        priorDepth = depth;
      }
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
        baseline_visible: baselineVisible,
        baseline_candidate: candidateBaseline,
        minilm_reranked: reranked,
        timings,
      });
    }
  }
  const vocabularyGapRows = audit.rows.filter(row => (
    row.conventional_fielded_feasibility === "INSUFFICIENT_INDEXED_TEXT_FOR_CONVENTIONAL_RANKING"
  ));
  const queryById = new Map(rows.map(row => [row.id, row]));
  const vocabularyGap = vocabularyGapRows.map(anchor => {
    const row = queryById.get(anchor.query_id);
    const atDepth = Object.fromEntries(DEPTHS.map(depth => [depth, {
      bm25f_candidate_rank: row?.baseline_candidate?.[depth]?.metrics?.required_ranks?.[
        anchor.required_result_id
      ] ?? null,
      minilm_rank: row?.minilm_reranked?.[depth]?.metrics?.required_ranks?.[
        anchor.required_result_id
      ] ?? null,
    }]));
    return {
      query_id: anchor.query_id,
      query: anchor.query,
      required_result_id: anchor.required_result_id,
      required_result_title: anchor.required_result_title,
      prior_visible_primary_rank: anchor.local_fielded_outcome.visible_primary_rank,
      inherited_candidate_discovered: anchor.inherited_iteration3_candidate_trace.parent_candidate_discovered
        || anchor.inherited_iteration3_candidate_trace.relevant_child_candidate_discovered,
      depths: atDepth,
    };
  });
  const vocabularyGapSummary = Object.fromEntries(DEPTHS.map(depth => {
    const values = vocabularyGap.map(anchor => anchor.depths[depth]);
    return [depth, {
      anchor_count: values.length,
      reachable_in_candidate_window: values.filter(value => value.bm25f_candidate_rank !== null).length,
      bm25f_candidate_top_10: values.filter(value => (
        value.bm25f_candidate_rank !== null && value.bm25f_candidate_rank <= 10
      )).length,
      minilm_top_10: values.filter(value => (
        value.minilm_rank !== null && value.minilm_rank <= 10
      )).length,
      bm25f_candidate_top_50: values.filter(value => value.bm25f_candidate_rank !== null).length,
      minilm_top_50: values.filter(value => value.minilm_rank !== null).length,
      semantic_rescues_into_top_10: values.filter(value => (
        value.minilm_rank !== null && value.minilm_rank <= 10
        && (value.bm25f_candidate_rank === null || value.bm25f_candidate_rank > 10)
      )).length,
      semantic_regressions_out_of_top_10: values.filter(value => (
        value.bm25f_candidate_rank !== null && value.bm25f_candidate_rank <= 10
        && (value.minilm_rank === null || value.minilm_rank > 10)
      )).length,
    }];
  }));
  const requiredAnchorMovement = Object.fromEntries(DEPTHS.map(depth => {
    const values = rows.flatMap(row => Object.keys(row.minilm_reranked[depth].metrics.required_ranks)
      .map(id => ({
        baseline: row.baseline_candidate[depth].metrics.required_ranks[id],
        minilm: row.minilm_reranked[depth].metrics.required_ranks[id],
      })));
    return [depth, {
      anchor_count: values.length,
      semantic_rescues_into_top_10: values.filter(value => (
        value.minilm !== null && value.minilm <= 10
        && (value.baseline === null || value.baseline > 10)
      )).length,
      semantic_regressions_out_of_top_10: values.filter(value => (
        value.baseline !== null && value.baseline <= 10
        && (value.minilm === null || value.minilm > 10)
      )).length,
      newly_reachable_at_50: values.filter(value => (
        value.minilm !== null && value.baseline === null
      )).length,
    }];
  }));
  const summary = {
    baseline_visible_primary: summarize(rows, "baseline_visible"),
    baseline_bm25f_candidate: Object.fromEntries(DEPTHS.map(depth => [
      depth,
      summarize(rows, "baseline_candidate", depth),
    ])),
    minilm_reranked_candidate: Object.fromEntries(DEPTHS.map(depth => [
      depth,
      summarize(rows, "minilm_reranked", depth),
    ])),
  };
  const byFamily = Object.fromEntries([...new Set(rows.map(row => row.family))].sort().map(id => [
    id,
    {
      query_count: rows.filter(row => row.family === id).length,
      baseline_visible_primary: summarize(rows.filter(row => row.family === id), "baseline_visible"),
      minilm_at_50: summarize(rows.filter(row => row.family === id), "minilm_reranked", 50),
    },
  ]));
  const zeroHardNegatives = rows.filter(row => row.zero_primary_hard_negative);
  const timingsByDepth = Object.fromEntries(DEPTHS.map(depth => {
    const values = rows.map(row => row.timings[depth].total_with_bm25f_ms);
    const rerank = rows.map(row => row.timings[depth].cumulative_rerank_ms);
    return [depth, {
      query_count: values.length,
      rerank_p50_ms: number(percentile(rerank, .5)),
      rerank_p95_ms: number(percentile(rerank, .95)),
      total_p50_ms: number(percentile(values, .5)),
      total_p95_ms: number(percentile(values, .95)),
    }];
  }));
  const payload = {
    schema_version: 1,
    experiment: "local_minilm_cross_encoder_reranker_feasibility",
    generated_at: new Date().toISOString(),
    status: "development_only_no_production_integration",
    model: MODEL,
    model_receipt: RECEIPT_PATH,
    architecture: {
      baseline: "unchanged local bm25f_passage_coordination",
      candidate_unit: "authoritative parent or publication-eligible child scope passage",
      candidate_depths: DEPTHS,
      reranking: "MiniLM raw cross-encoder logit",
      parent_aggregation: "single strongest reranked parent-or-child passage",
      child_count_bonus: 0,
      semantic_score_creates_primary_evidence: false,
      production_explanations_changed: false,
    },
    safety: {
      phase4c_read_or_executed: false,
      phase4c_artifacts_imported: false,
      production_search_code_changed: false,
      production_model_integration: false,
      model_weights_committed: false,
      paid_or_hosted_service: false,
      scientific_mappings_added: false,
      generated_program_metadata_added: false,
    },
    quality: {
      summary,
      by_family: byFamily,
      vocabulary_gap_anchor_count: vocabularyGap.length,
      vocabulary_gap_summary: vocabularyGapSummary,
      vocabulary_gap: vocabularyGap,
      required_anchor_movement: requiredAnchorMovement,
      zero_primary_hard_negatives: {
        query_count: zeroHardNegatives.length,
        baseline_visible_primary_count: zeroHardNegatives.reduce(
          (sum, row) => sum + row.baseline_visible.top_10.length,
          0,
        ),
        minilm_top_10_judged_primary_count_at_50: zeroHardNegatives.reduce(
          (sum, row) => sum + row.minilm_reranked[50].metrics.primary_at_10,
          0,
        ),
        minilm_top_10_judged_irrelevant_count_at_50: zeroHardNegatives.reduce(
          (sum, row) => sum + row.minilm_reranked[50].metrics.judged_irrelevant_at_10.length,
          0,
        ),
        minilm_top_10_unjudged_count_at_50: zeroHardNegatives.reduce(
          (sum, row) => sum + row.minilm_reranked[50].metrics.unjudged_at_10.length,
          0,
        ),
      },
    },
    performance: {
      cached_initialization: encoder.runtime,
      warm_query_latency_by_candidate_depth: timingsByDepth,
      rss_after_evaluation_bytes: process.memoryUsage().rss,
      rss_evaluation_delta_from_post_init_bytes: process.memoryUsage().rss
        - encoder.runtime.rss_after_initialization_bytes,
      webgpu: typeof navigator !== "undefined" && Boolean(navigator.gpu)
        ? "available_not_benchmarked_in_cpu_acceptance_run"
        : "unavailable_in_node_harness",
    },
    rows,
    receipt,
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify({
    output: process.argv.includes("--write") ? RESULTS_PATH : null,
    quality: payload.quality.summary,
    vocabulary_gap: payload.quality.vocabulary_gap,
    hard_negatives: payload.quality.zero_primary_hard_negatives,
    performance: payload.performance,
  }, null, 2));
  await encoder.model.dispose?.();
}

if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
  throw new Error("MiniLM feasibility harness refuses Phase-4C inputs.");
}
if (process.argv.includes("--receipt")) await runReceipt();
else if (process.argv.includes("--runtime-benchmark")) await runRuntimeBenchmark();
else await runEvaluation();
