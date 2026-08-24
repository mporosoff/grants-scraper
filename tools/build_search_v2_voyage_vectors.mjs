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
const CANARY_PATH = "data/search-v2-voyage-canaries.json";
const RECEIPT_PATH = "evaluation/search_v2_hybrid_vector_build.json";
const API_URL = "https://api.voyageai.com/v1/embeddings";
const MODEL = "voyage-4-lite";
const DIMENSION = 1024;
const DTYPE = "float16-le";
const BATCH_SIZE = 256;
const REQUEST_TIMEOUT_MS = 120_000;
const PRICE_PER_MILLION_TOKENS_USD = 0.02;
const CANARY_SET_VERSION = 1;
const CANARY_ROUND_DECIMALS = 4;
const CANARY_MINIMUM_COSINE = 0.95;
const CANARY_MEAN_COSINE = 0.98;
const MODEL_SPACE_CANARIES = Object.freeze([
  { id: "carbon-catalysis", text: "Catalytic conversion of captured carbon dioxide into durable fuels and chemicals using electrochemical reaction engineering." },
  { id: "critical-minerals", text: "Rare earth element separation, solvent extraction, ion exchange, recycling, and domestic critical-mineral processing research." },
  { id: "rural-health", text: "Rural maternal health care networks, obstetric access, clinical outcomes, and community health delivery research." },
  { id: "quantum-sensing", text: "Quantum sensing, precision measurement, photonics, atomic systems, and navigation technologies for scientific discovery." },
  { id: "maritime-autonomy", text: "Autonomous maritime sensing, robotics, ocean observation, resilient navigation, and marine engineering." },
  { id: "ecosystem-resilience", text: "Ecological restoration, watershed resilience, biodiversity monitoring, wildfire recovery, and environmental field science." },
]);

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

function cosine(leftVector, rightVector) {
  let dot = 0;
  let left = 0;
  let right = 0;
  for (let index = 0; index < leftVector.length; index += 1) {
    dot += leftVector[index] * rightVector[index];
    left += leftVector[index] * leftVector[index];
    right += rightVector[index] * rightVector[index];
  }
  return dot / ((Math.sqrt(left) || 1) * (Math.sqrt(right) || 1));
}

function roundedEmbedding(vector) {
  return Array.from(vector, value => Number(value.toFixed(CANARY_ROUND_DECIMALS)));
}

function canaryFingerprint(canaries) {
  return sha256(JSON.stringify({
    canary_set_version: CANARY_SET_VERSION,
    model: MODEL,
    dimension: DIMENSION,
    input_type: "document",
    output_dtype: "float",
    rounding_decimals: CANARY_ROUND_DECIMALS,
    canaries: canaries.map(item => ({ id: item.id, embedding: item.embedding })),
  }));
}

function compareCanarySpace(previous, current) {
  if (!previous?.canaries?.length) return {
    prior_fingerprint: null,
    drift_detected: null,
    minimum_cosine: null,
    mean_cosine: null,
    minimum_cosine_gate: CANARY_MINIMUM_COSINE,
    mean_cosine_gate: CANARY_MEAN_COSINE,
    gross_discontinuity: false,
    status: "baseline_established",
  };
  const previousById = new Map(previous.canaries.map(item => [item.id, item.embedding]));
  const similarities = current.map(item => {
    const prior = previousById.get(item.id);
    if (!Array.isArray(prior) || prior.length !== DIMENSION) {
      throw new Error(`Prior model-space canary ${item.id} is missing or malformed.`);
    }
    return cosine(prior, item.embedding);
  });
  const minimum = Math.min(...similarities);
  const mean = similarities.reduce((sum, value) => sum + value, 0) / similarities.length;
  const gross = minimum < CANARY_MINIMUM_COSINE || mean < CANARY_MEAN_COSINE;
  return {
    prior_fingerprint: previous.model_space_fingerprint || null,
    drift_detected: previous.model_space_fingerprint !== canaryFingerprint(current),
    minimum_cosine: number(minimum),
    mean_cosine: number(mean),
    per_canary_cosine: Object.fromEntries(current.map((item, index) => [item.id, number(similarities[index])])),
    minimum_cosine_gate: CANARY_MINIMUM_COSINE,
    mean_cosine_gate: CANARY_MEAN_COSINE,
    gross_discontinuity: gross,
    status: gross ? "blocked_gross_discontinuity" : "passed",
  };
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
    const [manifest, binary, canaries] = await Promise.all([
      readFile(new URL(MANIFEST_PATH, ROOT), "utf8").then(JSON.parse),
      readFile(new URL(VECTOR_PATH, ROOT)),
      readFile(new URL(CANARY_PATH, ROOT), "utf8").then(JSON.parse).catch(() => null),
    ]);
    const vectors = new Uint16Array(binary.buffer, binary.byteOffset, binary.byteLength / 2);
    if (manifest.model !== MODEL || manifest.dimension !== DIMENSION || manifest.dtype !== DTYPE) return null;
    if (!Array.isArray(manifest.passages) || vectors.length !== manifest.passages.length * DIMENSION) return null;
    return { manifest, vectors, canaries };
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
  const production = process.argv.includes("--production");
  const force = process.argv.includes("--force") || production;
  if (production && !write) {
    throw new Error("--production requires --write so a complete generation is published atomically.");
  }
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
  const currentPassageIds = new Set(corpus.map(item => item.passage_id));
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
  let canaryArtifact = null;
  let canaryComparison = null;
  if (production) {
    const response = await embed(
      process.env.VOYAGE_API_KEY,
      MODEL_SPACE_CANARIES.map(item => item.text),
      "model-space-canaries",
    );
    const canaries = MODEL_SPACE_CANARIES.map((item, index) => ({
      id: item.id,
      text_sha256: sha256(item.text),
      embedding: roundedEmbedding(response.vectors[index]),
    }));
    const fingerprint = canaryFingerprint(canaries);
    canaryComparison = compareCanarySpace(previous?.canaries, canaries);
    canaryArtifact = {
      schema_version: 1,
      generated_at: null,
      canary_set_version: CANARY_SET_VERSION,
      model_alias: MODEL,
      response_model: response.receipt.model,
      input_type: "document",
      source_output_dtype: "float",
      dimension: DIMENSION,
      rounding_decimals: CANARY_ROUND_DECIMALS,
      model_space_fingerprint: fingerprint,
      comparison_to_prior_generation: canaryComparison,
      canaries,
    };
    receipts.push({ ...response.receipt, request_kind: "model_space_canaries" });
  }
  for (let offset = 0; offset < changed.length; offset += BATCH_SIZE) {
    const batch = changed.slice(offset, offset + BATCH_SIZE);
    const response = await embed(process.env.VOYAGE_API_KEY, batch.map(item => item.passage.text), receipts.length);
    receipts.push({ ...response.receipt, request_kind: "corpus_passages" });
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
  if (canaryArtifact) canaryArtifact.generated_at = generatedAt;
  const responseModels = [...new Set(receipts.map(item => item.model))];
  if (production && (responseModels.length !== 1 || responseModels[0] !== MODEL)) {
    throw new Error(`Production embedding responses are not uniform: ${responseModels.join(", ") || "missing model"}.`);
  }
  const manifest = {
    schema_version: 1,
    generated_at: generatedAt,
    model: MODEL,
    provider_revision: "not exposed by the real-time embedding API",
    response_model: responseModels[0] || MODEL,
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
    model_space_fingerprint: canaryArtifact?.model_space_fingerprint || previous?.manifest?.model_space_fingerprint || null,
    model_space: canaryArtifact ? {
      canary_set_version: CANARY_SET_VERSION,
      canary_count: MODEL_SPACE_CANARIES.length,
      fingerprint_method: `sha256 of ${CANARY_ROUND_DECIMALS}-decimal rounded canary embeddings`,
      comparison_to_prior_generation: canaryComparison,
    } : previous?.manifest?.model_space || null,
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
    build_mode: production ? "production_full_rebuild" : (force ? "forced_full_rebuild" : "local_incremental"),
    model: MODEL,
    provider_revision: manifest.provider_revision,
    response_model: manifest.response_model,
    input_type: "document",
    API_key_printed_or_persisted: false,
    passage_count: corpus.length,
    reused_passage_count: reused,
    embedded_passage_count: changed.length,
    removed_prior_passage_count: (previous?.manifest?.passages || [])
      .filter(item => !currentPassageIds.has(item.passage_id)).length,
    corpus_sha256: corpusSha,
    vector_sha256: vectorSha,
    vector_format: DTYPE,
    vector_bytes: vectorBuffer.byteLength,
    build_timestamp: generatedAt,
    model_space_fingerprint: manifest.model_space_fingerprint,
    model_space: manifest.model_space,
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
    production_reused_vectors: production ? false : null,
    production_generation_uniform: production ? {
      model_alias_count: 1,
      response_model_count: responseModels.length,
      dimension_count: 1,
      output_type_count: 1,
      build_timestamp_count: 1,
      canary_fingerprint_count: canaryArtifact ? 1 : 0,
      corpus_sha_count: 1,
      vector_sha_count: 1,
    } : null,
  };

  if (production && canaryComparison?.gross_discontinuity) {
    throw new Error(
      `Gross embedding-space discontinuity: minimum cosine ${canaryComparison.minimum_cosine}, mean cosine ${canaryComparison.mean_cosine}. Publication blocked after full rebuild.`,
    );
  }

  if (write) {
    const writes = [
      writeFile(new URL(MANIFEST_PATH, ROOT), `${JSON.stringify(manifest, null, 2)}\n`),
      writeFile(new URL(VECTOR_PATH, ROOT), vectorBuffer),
      writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`),
    ];
    if (canaryArtifact) writes.push(
      writeFile(new URL(CANARY_PATH, ROOT), `${JSON.stringify(canaryArtifact, null, 2)}\n`),
    );
    await Promise.all(writes);
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
    model_space_fingerprint: manifest.model_space_fingerprint,
    model_space_comparison: canaryComparison,
    quantization: receipt.float16_quantization,
  }, null, 2)}\n`);
}

run().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
