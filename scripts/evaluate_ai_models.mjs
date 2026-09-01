#!/usr/bin/env node
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import "../assets/ai-provider.js";
import {
  BENCHMARK_CASES,
  BENCHMARK_VERSION,
  MODEL_CONFIG,
  gradeBenchmarkOutput,
} from "../evaluation/ai-model-benchmark-v1.mjs";
import {
  BENCHMARK_MAX_ATTEMPTS,
  BENCHMARK_MAX_OUTPUT_TOKENS,
  BENCHMARK_RETRY_INSTRUCTIONS,
} from "../workers/ai-benchmark/src/index.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const contracts = globalThis.FUNDING_AI.STRUCTURED_OPERATIONS;

function parseArgs(values) {
  const options = {
    run: false,
    runs: 3,
    seed: 20260831,
    endpoint: process.env.BENCHMARK_ENDPOINT || "",
    token: process.env.BENCHMARK_TOKEN || "",
    models: ["luna", "gemma"],
    caseIds: [],
    output: path.join(repoRoot, "evaluation", "ai-model-results", "latest"),
  };
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index];
    if (value === "--run") options.run = true;
    else if (value === "--runs") options.runs = Number(values[++index]);
    else if (value === "--seed") options.seed = Number(values[++index]);
    else if (value === "--endpoint") options.endpoint = String(values[++index] || "");
    else if (value === "--models") options.models = String(values[++index] || "").split(",").filter(Boolean);
    else if (value === "--cases") options.caseIds = String(values[++index] || "").split(",").filter(Boolean);
    else if (value === "--output") options.output = path.resolve(values[++index]);
    else if (value === "--help" || value === "-h") options.help = true;
    else throw new Error(`Unknown option: ${value}`);
  }
  if (!Number.isInteger(options.runs) || options.runs < 1 || options.runs > 10) {
    throw new Error("--runs must be an integer from 1 to 10.");
  }
  if (!Number.isInteger(options.seed)) throw new Error("--seed must be an integer.");
  for (const model of options.models) {
    if (!Object.prototype.hasOwnProperty.call(MODEL_CONFIG, model)) throw new Error(`Unknown model: ${model}`);
  }
  return options;
}

function usage() {
  return [
    "Funding Finder private AI benchmark",
    "",
    "Cost estimate only (default):",
    "  node scripts/evaluate_ai_models.mjs",
    "",
    "Make model calls after reviewing the estimate:",
    "  node scripts/evaluate_ai_models.mjs --run --endpoint https://WORKER.workers.dev",
    "",
    "BENCHMARK_TOKEN must be set in the process environment for --run.",
    "Optional: --runs 3 --models luna,gemma --cases case-a,case-b --seed 20260831 --output PATH",
  ].join("\n");
}

function mulberry32(seed) {
  return function random() {
    let value = seed += 0x6D2B79F5;
    value = Math.imul(value ^ value >>> 15, value | 1);
    value ^= value + Math.imul(value ^ value >>> 7, value | 61);
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}

function shuffled(values, random) {
  const result = [...values];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [result[index], result[target]] = [result[target], result[index]];
  }
  return result;
}

function selectedCases(options) {
  const cases = options.caseIds.length
    ? BENCHMARK_CASES.filter(testCase => options.caseIds.includes(testCase.id))
    : [...BENCHMARK_CASES];
  if (!cases.length) throw new Error("No benchmark cases matched --cases.");
  const missing = options.caseIds.filter(id => !cases.some(testCase => testCase.id === id));
  if (missing.length) throw new Error(`Unknown cases: ${missing.join(", ")}`);
  return cases;
}

export function estimateBenchmarkCost(options, cases) {
  const byModel = {};
  let calls = 0;
  for (const model of options.models) {
    const pricing = MODEL_CONFIG[model];
    let inputTokens = 0;
    let outputTokens = 0;
    for (const testCase of cases) {
      const schemaChars = JSON.stringify(contracts[testCase.operation]).length;
      inputTokens += Math.ceil((testCase.system.length + testCase.user.length + schemaChars) / 4) * options.runs;
      outputTokens += testCase.estimated_output_tokens * options.runs;
      calls += options.runs;
    }
    const estimatedCost = inputTokens / 1_000_000 * pricing.input_usd_per_million_tokens
      + outputTokens / 1_000_000 * pricing.output_usd_per_million_tokens;
    const retryInputTokens = Math.ceil(BENCHMARK_RETRY_INSTRUCTIONS[model].length / 4)
      * cases.length
      * options.runs
      * (BENCHMARK_MAX_ATTEMPTS - 1);
    const boundedMaximumInputTokens = inputTokens * BENCHMARK_MAX_ATTEMPTS + retryInputTokens;
    const maximumOutputTokens = cases.length
      * options.runs
      * BENCHMARK_MAX_OUTPUT_TOKENS
      * BENCHMARK_MAX_ATTEMPTS;
    const boundedMaximumCost = boundedMaximumInputTokens / 1_000_000 * pricing.input_usd_per_million_tokens
      + maximumOutputTokens / 1_000_000 * pricing.output_usd_per_million_tokens;
    byModel[model] = {
      calls: cases.length * options.runs,
      bounded_maximum_provider_calls: cases.length * options.runs * BENCHMARK_MAX_ATTEMPTS,
      estimated_input_tokens: inputTokens,
      estimated_output_tokens: outputTokens,
      estimated_usage_cost_usd_before_free_allowances: Number(estimatedCost.toFixed(6)),
      bounded_maximum_input_tokens: boundedMaximumInputTokens,
      bounded_maximum_output_tokens: maximumOutputTokens,
      bounded_maximum_usage_cost_usd_before_free_allowances: Number(boundedMaximumCost.toFixed(6)),
    };
  }
  return {
    calls,
    bounded_maximum_provider_calls: calls * BENCHMARK_MAX_ATTEMPTS,
    by_model: byModel,
  };
}

async function writeJsonAtomic(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temporary, filePath);
}

async function loadCheckpoint(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function jobsFor(options, cases) {
  const jobs = [];
  for (let run = 1; run <= options.runs; run += 1) {
    for (const testCase of cases) {
      for (const model of options.models) jobs.push({ run, testCase, model });
    }
  }
  return shuffled(jobs, mulberry32(options.seed));
}

async function callWorker(options, job) {
  const requestId = `${BENCHMARK_VERSION}:${job.testCase.id}:r${job.run}:${job.model}`;
  const startedAt = Date.now();
  const response = await fetch(new URL("/v1/evaluate", options.endpoint), {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${options.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      request_id: requestId,
      operation: job.testCase.operation,
      model: job.model,
      system: job.testCase.system,
      user: job.testCase.user,
    }),
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`Worker returned non-JSON HTTP ${response.status}.`);
  }
  if (!response.ok) throw new Error(`Worker HTTP ${response.status}: ${body?.error?.code || "unknown_error"}`);
  return {
    id: requestId,
    case_id: job.testCase.id,
    feature: job.testCase.feature,
    operation: job.testCase.operation,
    run: job.run,
    model: job.model,
    model_id: body.model_id,
    wall_latency_ms: Date.now() - startedAt,
    provider_latency_ms: body.latency_ms,
    attempts: body.attempts,
    usage: body.usage,
    output: body.output,
    automated_grade: gradeBenchmarkOutput(job.testCase, body.output),
  };
}

export function benchmarkFailureRecord(job, error) {
  return {
    id: `${BENCHMARK_VERSION}:${job.testCase.id}:r${job.run}:${job.model}`,
    case_id: job.testCase.id,
    feature: job.testCase.feature,
    operation: job.testCase.operation,
    run: job.run,
    model: job.model,
    model_id: MODEL_CONFIG[job.model].id,
    error: { code: String(error?.message || "provider_call_failed").slice(0, 240) },
    automated_grade: { passed: false, problems: ["provider_call_failed"] },
  };
}

function blindArtifacts(records, cases, seed) {
  const random = mulberry32(seed ^ 0xA5A5A5A5);
  const review = [];
  const key = [];
  const groups = new Map();
  for (const record of records) {
    if (record.run !== 1) continue;
    const groupKey = `${record.case_id}:r${record.run}`;
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push(record);
  }
  for (const [pairId, pair] of groups) {
    if (pair.length !== 2) continue;
    const ordered = random() < 0.5 ? pair : [...pair].reverse();
    const testCase = cases.find(item => item.id === ordered[0].case_id);
    review.push({
      pair_id: pairId,
      feature: testCase.feature,
      scenario: testCase.title,
      response_a: ordered[0].output || ordered[0].error,
      response_b: ordered[1].output || ordered[1].error,
      reviewer: {
        preferred: "",
        factual_grounding_a_1_to_5: null,
        factual_grounding_b_1_to_5: null,
        usefulness_a_1_to_5: null,
        usefulness_b_1_to_5: null,
        notes: "",
      },
    });
    key.push({ pair_id: pairId, response_a: ordered[0].model, response_b: ordered[1].model });
  }
  return { review, key };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  const cases = selectedCases(options);
  const costEstimate = estimateBenchmarkCost(options, cases);
  process.stdout.write(`${JSON.stringify({
    mode: options.run ? "run" : "estimate_only",
    benchmark: BENCHMARK_VERSION,
    cases: cases.length,
    runs: options.runs,
    ...costEstimate,
  }, null, 2)}\n`);
  if (!options.run) {
    process.stdout.write("\nNo model calls were made. Add --run only after reviewing this estimate.\n");
    return;
  }
  if (!options.endpoint) throw new Error("--endpoint or BENCHMARK_ENDPOINT is required with --run.");
  if (!options.token) throw new Error("BENCHMARK_TOKEN is required with --run; do not put it on the command line.");
  const checkpointPath = path.join(options.output, "results.json");
  const existing = await loadCheckpoint(checkpointPath);
  const runConfig = {
    runs: options.runs,
    models: [...options.models].sort(),
    cases: cases.map(testCase => testCase.id).sort(),
  };
  if (existing && (
    existing.benchmark !== BENCHMARK_VERSION
    || existing.seed !== options.seed
    || JSON.stringify(existing.run_config) !== JSON.stringify(runConfig)
  )) {
    throw new Error("Existing checkpoint belongs to a different benchmark configuration. Choose another --output directory.");
  }
  const records = existing?.records || [];
  const completed = new Set(records.map(record => record.id));
  for (const job of jobsFor(options, cases)) {
    const id = `${BENCHMARK_VERSION}:${job.testCase.id}:r${job.run}:${job.model}`;
    if (completed.has(id)) continue;
    let record;
    try {
      record = await callWorker(options, job);
    } catch (error) {
      record = benchmarkFailureRecord(job, error);
    }
    records.push(record);
    completed.add(id);
    await writeJsonAtomic(checkpointPath, {
      benchmark: BENCHMARK_VERSION,
      seed: options.seed,
      run_config: runConfig,
      estimate: costEstimate,
      records,
    });
    const outcome = record.error ? `failed (${record.error.code})` : "completed";
    process.stdout.write(`${records.length}/${costEstimate.calls}: ${job.testCase.id} · run ${job.run} · ${job.model} · ${outcome}\n`);
  }
  const blind = blindArtifacts(records, cases, options.seed);
  await writeJsonAtomic(path.join(options.output, "blind-review.json"), {
    benchmark: BENCHMARK_VERSION,
    instructions: "Review response A and B without opening blind-key.json. Fill in the reviewer fields for each pair.",
    pairs: blind.review,
  });
  await writeJsonAtomic(path.join(options.output, "blind-key.json"), {
    benchmark: BENCHMARK_VERSION,
    warning: "Open only after the anonymized review is complete.",
    pairs: blind.key,
  });
  process.stdout.write(`\nSaved resumable results and anonymized review files in ${options.output}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    process.stderr.write(`${error?.message || String(error)}\n`);
    process.exitCode = 1;
  });
}
