#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const HYBRID_SOURCE_PATH = "assets/search-hybrid.js";
const MANIFEST_PATH = "data/search-v2-voyage-manifest.json";
const VECTOR_PATH = "data/search-v2-voyage-vectors.f16";
const RECEIPT_PATH = "evaluation/search_v2_hybrid_vector_build.json";
const API_URL = "https://api.voyageai.com/v1/embeddings";
const MODEL = "voyage-4-lite";
const DIMENSION = 1024;
const DTYPE = "float16-le";
const BATCH_SIZE = 256;
const REQUEST_TIMEOUT_MS = 120_000;
const PRICE_PER_MILLION_TOKENS_USD = 0.02;

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function sha256File(path) {
  return sha256(await readFile(new URL(path, ROOT)));
}

function corpusHash(corpus) {
  const hash = createHash("sha256");
  corpus.forEach(item => hash.update(`${item.passage_id}\0${item.parent_id}\0${item.text}\n`));
  return hash.digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function floatToHalf(value) {
  if (Number.isNaN(value)) return 0x7e00;
  if (value === Number.POSITIVE_INFINITY) return 0x7c00;
  if (value === Number.NEGATIVE_INFINITY) return 0xfc00;
  const float = new Float32Array(1);
  const bits = new Uint32Array(float.buffer);
  float[0] = value;
  const sign = (bits[0] >>> 16) & 0x8000;
  let exponent = ((bits[0] >>> 23) & 0xff) - 127 + 15;
  let mantissa = bits[0] & 0x7fffff;
  if (exponent <= 0) {
    if (exponent < -10) return sign;
    mantissa = (mantissa | 0x800000) >>> (1 - exponent);
    return sign | ((mantissa + 0x1000) >>> 13);
  }
  if (exponent >= 31) return sign | 0x7c00;
  mantissa += 0x1000;
  if (mantissa & 0x800000) {
    mantissa = 0;
    exponent += 1;
    if (exponent >= 31) return sign | 0x7c00;
  }
  return sign | (exponent << 10) | (mantissa >>> 13);
}

function halfToFloat(value) {
  const sign = (value & 0x8000) ? -1 : 1;
  const exponent = (value >>> 10) & 0x1f;
  const fraction = value & 0x03ff;
  if (exponent === 0) return sign * Math.pow(2, -14) * (fraction / 1024);
  if (exponent === 31) return fraction ? Number.NaN : sign * Number.POSITIVE_INFINITY;
  return sign * Math.pow(2, exponent - 15) * (1 + fraction / 1024);
}

function quantize(vector) {
  const values = new Uint16Array(vector.length);
  for (let index = 0; index < vector.length; index += 1) values[index] = floatToHalf(vector[index]);
  return values;
}

function quantizationCosine(vector, half) {
  let dot = 0;
  let left = 0;
  let right = 0;
  for (let index = 0; index < vector.length; index += 1) {
    const quantized = halfToFloat(half[index]);
    dot += vector[index] * quantized;
    left += vector[index] * vector[index];
    right += quantized * quantized;
  }
  return dot / ((Math.sqrt(left) || 1) * (Math.sqrt(right) || 1));
}

async function hybridApi() {
  const source = await readFile(new URL(HYBRID_SOURCE_PATH, ROOT), "utf8");
  const context = {
    globalThis: {},
    URL,
    TextEncoder,
    TextDecoder,
    Uint8Array,
    Uint16Array,
    Float32Array,
    ArrayBuffer,
  };
  vm.runInNewContext(source, context, { filename: HYBRID_SOURCE_PATH });
  return context.globalThis.FUNDING_HYBRID_SEARCH;
}

async function existingAsset() {
  try {
    const manifest = JSON.parse(await readFile(new URL(MANIFEST_PATH, ROOT), "utf8"));
    const binary = await readFile(new URL(VECTOR_PATH, ROOT));
    const vectors = new Uint16Array(binary.buffer, binary.byteOffset, binary.byteLength / 2);
    if (manifest.model !== MODEL || manifest.dimension !== DIMENSION || manifest.dtype !== DTYPE) return null;
    if (!Array.isArray(manifest.passages) || vectors.length !== manifest.passages.length * DIMENSION) return null;
    return { manifest, vectors };
  } catch {
    return null;
  }
}

async function embed(apiKey, texts, batchIndex) {
  const body = JSON.stringify({
    input: texts,
    model: MODEL,
    input_type: "document",
    truncation: true,
    output_dimension: DIMENSION,
    output_dtype: "float",
  });
  const started = performance.now();
  const response = await fetch(API_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
    body,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  const responseText = await response.text();
  let payload;
  try {
    payload = JSON.parse(responseText);
  } catch {
    throw new Error(`Voyage returned non-JSON with HTTP ${response.status}.`);
  }
  if (!response.ok) throw new Error(`Voyage document embedding failed with HTTP ${response.status}.`);
  const data = (payload.data || []).slice().sort((left, right) => Number(left.index) - Number(right.index));
  if (data.length !== texts.length) throw new Error(`Voyage returned ${data.length} vectors for ${texts.length} passages.`);
  const vectors = data.map(item => Float32Array.from(item.embedding || []));
  if (vectors.some(vector => vector.length !== DIMENSION)) throw new Error("Voyage returned an unexpected embedding dimension.");
  return {
    vectors,
    receipt: {
      batch_index: batchIndex,
      passage_count: texts.length,
      http_status: response.status,
      request_id: response.headers.get("request-id") || response.headers.get("x-request-id") || null,
      model: payload.model || MODEL,
      usage_total_tokens: Number(payload.usage?.total_tokens || 0),
      request_payload_bytes: Buffer.byteLength(body),
      response_payload_bytes: Buffer.byteLength(responseText),
      latency_ms: number(performance.now() - started),
    },
  };
}

async function run() {
  const write = process.argv.includes("--write");
  const force = process.argv.includes("--force");
  const [base, api, previous] = await Promise.all([loadHarness(), hybridApi(), existingAsset()]);
  const harness = makeVariantHarness(base, { searchV2: true });
  const currentness = harness.parentEngine.score("funding research", { evidence: false });
  const corpus = api.buildCorpus({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    currentnessRejectedIndexes: currentness.currentnessRejectedIndexes,
  });
  const corpusSha = corpusHash(corpus);
  const priorById = new Map((previous?.manifest?.passages || []).map((item, index) => [item.passage_id, { ...item, index }]));
  const vectorWords = new Uint16Array(corpus.length * DIMENSION);
  const changed = [];
  let reused = 0;
  corpus.forEach((passage, index) => {
    const textSha = sha256(passage.text);
    passage.text_sha256 = textSha;
    const prior = priorById.get(passage.passage_id);
    if (!force && prior?.text_sha256 === textSha && previous) {
      const source = previous.vectors.subarray(prior.index * DIMENSION, (prior.index + 1) * DIMENSION);
      vectorWords.set(source, index * DIMENSION);
      reused += 1;
    } else {
      changed.push({ passage, index });
    }
  });

  if (!force && changed.length === 0 && previous?.manifest?.corpus_sha256 === corpusSha) {
    const priorBuffer = Buffer.from(
      previous.vectors.buffer,
      previous.vectors.byteOffset,
      previous.vectors.byteLength,
    );
    const priorVectorSha = sha256(priorBuffer);
    if (priorVectorSha !== previous.manifest.vector_sha256) {
      throw new Error("The existing vector asset does not match its manifest hash.");
    }
    if (write) {
      let receipt = {};
      try {
        receipt = JSON.parse(await readFile(new URL(RECEIPT_PATH, ROOT), "utf8"));
      } catch {
        receipt = { schema_version: 1, status: "previous_receipt_unavailable" };
      }
      receipt.last_validated_at = new Date().toISOString();
      receipt.last_validation = {
        status: "unchanged_corpus_and_vector_reused",
        passage_count: corpus.length,
        corpus_sha256: corpusSha,
        vector_sha256: priorVectorSha,
        API_request_count: 0,
        source_hashes: {
          "assets/search-hybrid.js": await sha256File("assets/search-hybrid.js"),
          "data/opportunities.js": await sha256File("data/opportunities.js"),
          "data/subtopics.js": await sha256File("data/subtopics.js"),
        },
      };
      await writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`);
    }
    process.stdout.write(`${JSON.stringify({
      write,
      unchanged: true,
      passage_count: corpus.length,
      reused_passage_count: reused,
      embedded_passage_count: 0,
      API_request_count: 0,
      usage_total_tokens: 0,
      vector_bytes: priorBuffer.byteLength,
      corpus_sha256: corpusSha,
      vector_sha256: priorVectorSha,
    }, null, 2)}\n`);
    return;
  }

  if (changed.length && !process.env.VOYAGE_API_KEY) {
    throw new Error(`VOYAGE_API_KEY is required to embed ${changed.length} changed passages.`);
  }
  const receipts = [];
  const quantizationCosines = [];
  for (let offset = 0; offset < changed.length; offset += BATCH_SIZE) {
    const batch = changed.slice(offset, offset + BATCH_SIZE);
    const response = await embed(process.env.VOYAGE_API_KEY, batch.map(item => item.passage.text), receipts.length);
    receipts.push(response.receipt);
    response.vectors.forEach((vector, localIndex) => {
      const half = quantize(vector);
      quantizationCosines.push(quantizationCosine(vector, half));
      vectorWords.set(half, batch[localIndex].index * DIMENSION);
    });
    process.stderr.write(`[document embeddings ${Math.min(offset + batch.length, changed.length)}/${changed.length}] tokens=${response.receipt.usage_total_tokens} latency_ms=${response.receipt.latency_ms}\n`);
  }

  const vectorBuffer = Buffer.from(vectorWords.buffer, vectorWords.byteOffset, vectorWords.byteLength);
  const vectorSha = sha256(vectorBuffer);
  const generatedAt = new Date().toISOString();
  const manifest = {
    schema_version: 1,
    generated_at: generatedAt,
    model: MODEL,
    provider_revision: "not exposed by the real-time embedding API",
    input_type: "document",
    source_output_dtype: "float",
    dimension: DIMENSION,
    dtype: DTYPE,
    byte_order: "little-endian",
    passage_count: corpus.length,
    parent_passage_count: corpus.filter(item => item.passage_kind === "parent").length,
    child_passage_count: corpus.filter(item => item.passage_kind === "publication_eligible_child").length,
    corpus_sha256: corpusSha,
    vector_sha256: vectorSha,
    vector_bytes: vectorBuffer.byteLength,
    stable_passage_id_contract: "parent:<opportunity_id> or child:<subtopic_id>",
    passages: corpus.map((passage, vector_row) => ({
      passage_id: passage.passage_id,
      parent_id: passage.parent_id,
      passage_kind: passage.passage_kind,
      record_id: passage.record_id,
      text_sha256: passage.text_sha256,
      vector_row,
    })),
  };
  const totalTokens = receipts.reduce((sum, item) => sum + item.usage_total_tokens, 0);
  const receipt = {
    schema_version: 1,
    generated_at: generatedAt,
    status: write ? "written" : "dry_run",
    model: MODEL,
    provider_revision: manifest.provider_revision,
    input_type: "document",
    API_key_printed_or_persisted: false,
    passage_count: corpus.length,
    reused_passage_count: reused,
    embedded_passage_count: changed.length,
    removed_prior_passage_count: Math.max(0, (previous?.manifest?.passage_count || 0) - reused),
    corpus_sha256: corpusSha,
    vector_sha256: vectorSha,
    vector_format: DTYPE,
    vector_bytes: vectorBuffer.byteLength,
    source_hashes: {
      "assets/search-hybrid.js": await sha256File("assets/search-hybrid.js"),
      "data/opportunities.js": await sha256File("data/opportunities.js"),
      "data/subtopics.js": await sha256File("data/subtopics.js"),
    },
    API_requests: receipts,
    API_request_count: receipts.length,
    usage_total_tokens: totalTokens,
    estimated_cost_at_published_paid_pricing_usd: number(totalTokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD),
    float16_quantization: {
      vectors_checked: quantizationCosines.length,
      minimum_cosine_to_float32: quantizationCosines.length ? number(Math.min(...quantizationCosines)) : null,
      mean_cosine_to_float32: quantizationCosines.length
        ? number(quantizationCosines.reduce((sum, value) => sum + value, 0) / quantizationCosines.length)
        : null,
      spent_set_candidate_recall_validation_required: true,
    },
    vectors_contain_public_passages_only: true,
    vectors_persist_private_profile_or_researcher_data: false,
  };

  if (write) {
    await Promise.all([
      writeFile(new URL(MANIFEST_PATH, ROOT), `${JSON.stringify(manifest, null, 2)}\n`),
      writeFile(new URL(VECTOR_PATH, ROOT), vectorBuffer),
      writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`),
    ]);
  }
  process.stdout.write(`${JSON.stringify({
    write,
    passage_count: corpus.length,
    reused_passage_count: reused,
    embedded_passage_count: changed.length,
    API_request_count: receipts.length,
    usage_total_tokens: totalTokens,
    vector_bytes: vectorBuffer.byteLength,
    corpus_sha256: corpusSha,
    vector_sha256: vectorSha,
    quantization: receipt.float16_quantization,
  }, null, 2)}\n`);
}

run().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
