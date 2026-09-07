#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import vm from "node:vm";

import { withBuildLock, writeCoherentFiles } from "./coherent_files.mjs";
import { pathToFileURL } from "node:url";
import { configuration, exactSpaceIdentity, validateAsset, validateFloatVectors, reusableRows, manifestDigest } from "./embedding_contract.mjs";

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
    validateAsset(manifest, binary, canaries);
    const vectors = new Uint16Array(binary.buffer, binary.byteOffset, binary.byteLength / 2);
    if (manifest.model !== MODEL || manifest.dimension !== DIMENSION || manifest.dtype !== DTYPE) return null;
    if (!Array.isArray(manifest.passages) || vectors.length !== manifest.passages.length * DIMENSION) return null;
    return { manifest, vectors, binary, canaries };
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
  if (payload.model !== MODEL || !Array.isArray(payload.data)) throw new Error("Voyage response identity mismatch.");
  const data = payload.data.slice().sort((left, right) => Number(left.index) - Number(right.index));
  if (data.some((row, index) => row.index !== index)) throw new Error("Voyage response index mismatch.");
  validateFloatVectors(data.map(row => row.embedding), texts.length);
  if (data.length !== texts.length) throw new Error(`Voyage returned ${data.length} vectors for ${texts.length} passages.`);
  const vectors = data.map(item => Float32Array.from(item.embedding || []));
  validateFloatVectors(vectors, texts.length);
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

// The CLI and deterministic acceptance tests exercise this same production path.
export async function buildGeneration({corpus, previous, config, force = false, embedBatch,
  deadline = performance.now() + REQUEST_TIMEOUT_MS * (Math.ceil(corpus.length / BATCH_SIZE) + 1),
  maxRequests = Math.ceil(corpus.length / BATCH_SIZE) + 1}) {
  let requests = 0;
  const request = async (texts, index) => {
    if (performance.now() >= deadline || requests >= maxRequests) throw new Error("Vector work budget exhausted; prior release retained.");
    requests += 1;
    const response = await embedBatch(texts, index);
    validateFloatVectors(response.vectors, texts.length);
    if (response.receipt.model !== MODEL) throw new Error("Embedding response identity mismatch.");
    if (performance.now() >= deadline) throw new Error("Vector work budget exhausted; prior release retained.");
    return response;
  };
  // Validate the complete old package before using any of its rows. Corruption
  // is a cold cache, never a reason to combine unchecked bytes with fresh rows.
  try { if (previous) validateAsset(previous.manifest, previous.binary, previous.canaries); }
  catch { previous = null; }
  const capacity = BATCH_SIZE - MODEL_SPACE_CANARIES.length;
  // Pack known misses into the identity request, within the existing request
  // ceiling. This also lets a cold rebuild fit without increasing its budget.
  // No old row is read until the canaries below establish compatibility.
  const priorRows = new Map((previous?.manifest?.passages || []).map(row => [row.passage_id, row]));
  const configMatches = !force && previous?.manifest?.reuse_permitted === true && previous?.manifest?.reuse_contract
    && previous.manifest.configuration_sha256 === sha256(JSON.stringify(config));
  const initialMisses = corpus.map((passage, index) => ({passage, index})).filter(({passage}) => {
    const prior = priorRows.get(passage.passage_id);
    return !configMatches || !prior || prior.text_sha256 !== sha256(passage.text)
      || ["parent_id", "record_id", "passage_kind"].some(key => prior[key] !== passage[key]);
  }).slice(0, capacity);
  const response = await request([...initialMisses.map(row => row.passage.text), ...MODEL_SPACE_CANARIES.map(row => row.text)], "model-space-canaries");
  const canaries = MODEL_SPACE_CANARIES.map((row, index) => ({id: row.id, text_sha256: sha256(row.text),
    embedding: roundedEmbedding(response.vectors[initialMisses.length + index]),
    exact_embedding: Array.from(response.vectors[initialMisses.length + index])}));
  const canaryComparison = compareCanarySpace(previous?.canaries, canaries);
  if (canaryComparison.gross_discontinuity) throw new Error("Gross embedding-space discontinuity: publication blocked; prior release retained.");
  const canaryArtifact = {schema_version: 1, generated_at: null, canary_set_version: CANARY_SET_VERSION,
    model_alias: MODEL, response_model: response.receipt.model, input_type: "document", source_output_dtype: "float",
    dimension: DIMENSION, rounding_decimals: CANARY_ROUND_DECIMALS,
    model_space_fingerprint: exactSpaceIdentity(config, canaries, response.receipt.model),
    rounded_fingerprint: canaryFingerprint(canaries),
    reuse_space_identity: exactSpaceIdentity(config, canaries, response.receipt.model),
    reuse_permitted: true,
    batch_space_checks: [],
    comparison_to_prior_generation: canaryComparison, canaries};
  canaryComparison.drift_detected = previous?.canaries?.reuse_space_identity
    ? previous.canaries.reuse_space_identity !== canaryArtifact.reuse_space_identity : null;
  const indexes = reusableRows(corpus, previous, config, canaryArtifact.reuse_space_identity, force);
  const vectorWords = new Uint16Array(corpus.length * DIMENSION);
  const changed = [];
  let reused = 0;
  corpus.forEach((passage, index) => {
    passage.text_sha256 = sha256(passage.text);
    const prior = indexes[index];
    if (prior === null) changed.push({passage, index});
    else {
      for (let column = 0; column < DIMENSION; column++) {
        vectorWords[index * DIMENSION + column] = previous.binary.readUInt16LE((prior * DIMENSION + column) * 2);
      }
      reused++;
    }
  });
  const receipts = [{...response.receipt, request_kind: "model_space_canaries", canary_input_count: MODEL_SPACE_CANARIES.length,
    corpus_passage_count: initialMisses.length}];
  const quantizationCosines = [];
  const storeVector = (vector, index) => {
    const half = quantize(vector);
    if (Array.from(half).some(word => (word & 0x7c00) === 0x7c00)) throw new Error("Non-finite quantized vector.");
    quantizationCosines.push(quantizationCosine(vector, half));
    vectorWords.set(half, index * DIMENSION);
  };
  initialMisses.forEach((row, index) => storeVector(response.vectors[index], row.index));
  const fetched = new Set(initialMisses.map(row => row.index));
  const remaining = changed.filter(row => !fetched.has(row.index));
  for (let offset = 0; offset < remaining.length; offset += capacity) {
    const batch = remaining.slice(offset, offset + capacity);
    const result = await request([...batch.map(item => item.passage.text), ...MODEL_SPACE_CANARIES.map(item => item.text)], receipts.length);
    const anchors = canaries.map((row, index) => ({...row, exact_embedding: Array.from(result.vectors[batch.length + index])}));
    const exactMatch = exactSpaceIdentity(config, anchors, result.receipt.model) === canaryArtifact.reuse_space_identity;
    const comparison = compareCanarySpace(canaryArtifact, anchors.map(row => ({...row, embedding: roundedEmbedding(row.exact_embedding)})));
    canaryArtifact.batch_space_checks.push({exact_match: exactMatch, minimum_cosine: comparison.minimum_cosine,
      mean_cosine: comparison.mean_cosine, gross_discontinuity: comparison.gross_discontinuity});
    if (comparison.gross_discontinuity || (!exactMatch && reused > 0)) {
      throw new Error("Embedding space changed during generation; prior coherent release retained.");
    }
    // Independent floating outputs need not be bit-identical for a fresh,
    // homogeneous generation. Such a build NEVER certifies reusable rows.
    // Coarse canary gates only guard fresh builds; they never authorize mixing.
    if (!exactMatch) canaryArtifact.reuse_permitted = false;
    receipts.push({...result.receipt, request_kind: "corpus_passages", corpus_passage_count: batch.length, canary_input_count: MODEL_SPACE_CANARIES.length});
    result.vectors.slice(0, batch.length).forEach((vector, index) => {
      storeVector(vector, batch[index].index);
    });
  }
  return {config, vectorWords, changed, reused, receipts, quantizationCosines, canaryArtifact, canaryComparison,
    reuseReason: !canaryArtifact.reuse_permitted ? "homogeneous_unstable_identity" : force ? "explicit_full_rebuild" : !previous?.manifest.reuse_contract ? "unknown_or_invalid_prior_identity"
      : indexes.some(index => index !== null) ? "exact_configuration_and_space_match" : "no_compatible_rows"};
}

async function run() {
  const write = process.argv.includes("--write");
  const production = process.argv.includes("--production");
  const force = process.argv.includes("--force");
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
  const built = await buildGeneration({corpus, previous, config: configuration(await sha256File(HYBRID_SOURCE_PATH)),
    force, embedBatch: (texts, index) => embed(process.env.VOYAGE_API_KEY, texts, index)});
  const {vectorWords, changed, reused, receipts, quantizationCosines, canaryArtifact, canaryComparison} = built;
  const corpusSha = corpusHash(corpus);
  const currentPassageIds = new Set(corpus.map(item => item.passage_id));
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
      fingerprint_method: "sha256 of exact unrounded canaries and complete embedding configuration",
      comparison_to_prior_generation: canaryComparison,
    } : previous?.manifest?.model_space || null,
    reuse_permitted: canaryArtifact.reuse_permitted,
    reuse_contract: built.config,
    configuration_sha256: sha256(JSON.stringify(built.config)),
    reuse_space_identity: canaryArtifact.reuse_space_identity,
    canary_sha256: sha256(JSON.stringify(canaryArtifact)),
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
  manifest.integrity_sha256 = manifestDigest(manifest);
  validateAsset(manifest, vectorBuffer, canaryArtifact, {requireReusable: true});
  const totalTokens = receipts.reduce((sum, item) => sum + item.usage_total_tokens, 0);
  const receipt = {
    schema_version: 1,
    generated_at: generatedAt,
    status: write ? "written" : "dry_run",
    build_mode: force ? "forced_full_rebuild" : (reused ? "compatible_incremental" : "production_full_rebuild"),
    reuse_reason: built.reuseReason,
    reuse_permitted: canaryArtifact.reuse_permitted,
    batch_space_checks: canaryArtifact.batch_space_checks,
    canary_request_count: receipts.filter(row => row.request_kind === "model_space_canaries").length,
    corpus_request_count: receipts.filter(row => row.corpus_passage_count > 0).length,
    canary_only_request_count: receipts.filter(row => !row.corpus_passage_count).length,
    canary_input_count: receipts.reduce((sum, row) => sum + row.canary_input_count, 0),
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
    production_reused_vectors: production ? reused > 0 : null,
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


  if (write) {
    await writeCoherentFiles([
      [new URL(VECTOR_PATH, ROOT), vectorBuffer],
      [new URL(CANARY_PATH, ROOT), `${JSON.stringify(canaryArtifact, null, 2)}\n`],
      [new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`],
      [new URL(MANIFEST_PATH, ROOT), `${JSON.stringify(manifest, null, 2)}\n`],
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
    model_space_fingerprint: manifest.model_space_fingerprint,
    model_space_comparison: canaryComparison,
    quantization: receipt.float16_quantization,
  }, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) withBuildLock(new URL(".cache/", ROOT), run).catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
