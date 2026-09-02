#!/usr/bin/env node

import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import { promisify } from "node:util";
import vm from "node:vm";

import { loadHarness, makeVariantHarness } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const HYBRID_SOURCE_PATH = "assets/search-hybrid.js";
const MANIFEST_PATH = "data/search-v2-voyage-manifest.json";
const VECTOR_PATH = "data/search-v2-voyage-vectors.f16";
const CANARY_PATH = "data/search-v2-voyage-canaries.json";
const ALLOWLIST_PATH = "workers/search-voyage-proxy/generated/corpus-allowlist.json";
const RELEASE_PATH = "data/search-v2-release.json";
const WORKER_SOURCE_PATH = "workers/search-voyage-proxy/src/index.js";
const REQUIRED_MODEL = "voyage-4-lite";
const REQUIRED_DIMENSION = 1024;
const execFileAsync = promisify(execFile);

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function read(path) {
  return readFile(new URL(path, ROOT));
}

async function readJson(path, fallback = null) {
  try {
    return JSON.parse(await readFile(new URL(path, ROOT), "utf8"));
  } catch (error) {
    if (fallback !== null && error?.code === "ENOENT") return fallback;
    throw error;
  }
}

function jsonBytes(value) {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
}

function corpusHash(corpus) {
  const hash = createHash("sha256");
  corpus.forEach(item => hash.update(`${item.passage_id}\0${item.parent_id}\0${item.text}\n`));
  return hash.digest("hex");
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

function assertHex(value, label) {
  if (!/^[a-f0-9]{64}$/.test(String(value || ""))) throw new Error(`${label} must be a SHA-256 hex digest.`);
}

function compactGeneration(manifest) {
  return {
    corpus_sha256: manifest.corpus_sha256,
    model: manifest.model,
    dimension: manifest.dimension,
    model_space_fingerprint: manifest.model_space_fingerprint || null,
    response_model: manifest.response_model || manifest.model,
    input_type: manifest.input_type,
    source_output_dtype: manifest.source_output_dtype,
    vector_dtype: manifest.dtype,
    published_at: manifest.generated_at,
    passage_count: manifest.passage_count,
    passages: manifest.passages.map(item => ({
      passage_id: item.passage_id,
      text_sha256: item.text_sha256,
    })),
  };
}

function validateGeneration(generation, label) {
  if (!generation || typeof generation !== "object") throw new Error(`${label} generation is missing.`);
  assertHex(generation.corpus_sha256, `${label} corpus_sha256`);
  if (generation.model !== REQUIRED_MODEL || generation.dimension !== REQUIRED_DIMENSION) {
    throw new Error(`${label} generation uses an incompatible embedding contract.`);
  }
  if (label === "current") assertHex(generation.model_space_fingerprint, `${label} model_space_fingerprint`);
  if (generation.model_space_fingerprint != null) {
    assertHex(generation.model_space_fingerprint, `${label} model_space_fingerprint`);
  }
  if (!Array.isArray(generation.passages) || generation.passages.length !== generation.passage_count) {
    throw new Error(`${label} generation passage count is inconsistent.`);
  }
  const ids = new Set();
  generation.passages.forEach((item, index) => {
    if (!item?.passage_id || ids.has(item.passage_id)) throw new Error(`${label} generation has a duplicate or empty passage ID at row ${index}.`);
    assertHex(item.text_sha256, `${label} text_sha256 at row ${index}`);
    ids.add(item.passage_id);
  });
}

function buildAllowlist(manifest, existing, bootstrapPrevious = null) {
  const current = compactGeneration(manifest);
  let previous = null;
  if (existing?.current?.corpus_sha256 && existing.current.corpus_sha256 !== current.corpus_sha256) {
    previous = existing.current;
  } else if (existing?.previous?.corpus_sha256 && existing.previous.corpus_sha256 !== current.corpus_sha256) {
    previous = existing.previous;
  }
  if (!previous && bootstrapPrevious?.corpus_sha256
    && bootstrapPrevious.corpus_sha256 !== current.corpus_sha256) {
    previous = compactGeneration(bootstrapPrevious);
  }
  const allowlist = {
    schema_version: 1,
    current,
    previous,
  };
  validateGeneration(allowlist.current, "current");
  if (allowlist.previous) validateGeneration(allowlist.previous, "previous");
  if (allowlist.previous?.corpus_sha256 === allowlist.current.corpus_sha256) {
    throw new Error("Current and previous Worker generations must be distinct.");
  }
  return allowlist;
}

async function validateCurrentPackage(manifest, vectorBuffer, canaries) {
  if (manifest.schema_version !== 1 || manifest.model !== REQUIRED_MODEL
    || manifest.dimension !== REQUIRED_DIMENSION || manifest.dtype !== "float16-le") {
    throw new Error("The current semantic manifest uses an unsupported contract.");
  }
  assertHex(manifest.corpus_sha256, "manifest corpus_sha256");
  assertHex(manifest.vector_sha256, "manifest vector_sha256");
  assertHex(manifest.model_space_fingerprint, "manifest model_space_fingerprint");
  if (canaries?.model_space_fingerprint !== manifest.model_space_fingerprint
    || canaries?.model_alias !== manifest.model
    || canaries?.response_model !== manifest.response_model
    || canaries?.dimension !== manifest.dimension
    || canaries?.input_type !== manifest.input_type
    || canaries?.source_output_dtype !== manifest.source_output_dtype
    || !Array.isArray(canaries?.canaries)
    || canaries.canaries.length !== manifest.model_space?.canary_count) {
    throw new Error("The model-space canary artifact does not match the semantic manifest.");
  }
  if (vectorBuffer.byteLength !== manifest.vector_bytes
    || vectorBuffer.byteLength !== manifest.passage_count * manifest.dimension * 2) {
    throw new Error("The vector binary size does not match the manifest shape.");
  }
  if (sha256(vectorBuffer) !== manifest.vector_sha256) {
    throw new Error("The vector binary hash does not match the manifest.");
  }

  const [base, api] = await Promise.all([loadHarness(), hybridApi()]);
  const harness = makeVariantHarness(base, { searchV2: true });
  const currentness = harness.parentEngine.score("funding research", { evidence: false });
  const corpus = api.buildCorpus({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    currentnessRejectedIndexes: currentness.currentnessRejectedIndexes,
  });
  if (corpus.length !== manifest.passage_count || corpusHash(corpus) !== manifest.corpus_sha256) {
    throw new Error("The current catalog corpus does not match the semantic manifest.");
  }
  corpus.forEach((passage, index) => {
    const row = manifest.passages?.[index];
    if (!row || row.vector_row !== index || row.passage_id !== passage.passage_id
      || row.parent_id !== passage.parent_id || row.text_sha256 !== sha256(passage.text)) {
      throw new Error(`Manifest passage row ${index} does not match the current public corpus.`);
    }
  });
}

async function run() {
  const write = process.argv.includes("--write");
  const check = process.argv.includes("--check");
  if (write === check) throw new Error("Choose exactly one of --write or --check.");

  const bootstrapIndex = process.argv.indexOf("--bootstrap-previous");
  const bootstrapRevision = bootstrapIndex >= 0 ? process.argv[bootstrapIndex + 1] : "";
  if (bootstrapIndex >= 0 && !bootstrapRevision) throw new Error("--bootstrap-previous requires a Git revision.");
  const bootstrapPromise = bootstrapRevision
    ? execFileAsync("git", ["show", `${bootstrapRevision}:${MANIFEST_PATH}`], { cwd: new URL(".", ROOT) })
      .then(({ stdout }) => JSON.parse(stdout))
    : Promise.resolve(null);
  const [manifest, vectorBuffer, canaries, existing, bootstrapPrevious] = await Promise.all([
    readJson(MANIFEST_PATH),
    read(VECTOR_PATH),
    readJson(CANARY_PATH),
    readJson(ALLOWLIST_PATH, {}),
    bootstrapPromise,
  ]);
  await validateCurrentPackage(manifest, vectorBuffer, canaries);
  const allowlist = buildAllowlist(manifest, existing, bootstrapPrevious);
  const allowlistBytes = jsonBytes(allowlist);
  const sourceHashes = {};
  for (const path of [
    "data/opportunities.js",
    "data/catalog-metadata.js",
    "data/subtopics.js",
    MANIFEST_PATH,
    VECTOR_PATH,
    CANARY_PATH,
    "assets/app-config.js",
    "assets/app.css",
    "assets/app.js",
    "assets/catalog-loader.js",
    "assets/result-workflow.js",
    "assets/search-hybrid.js",
    "assets/search-retrieval.js",
    "assets/subtopic-runtime.js",
    "assets/team-hybrid.js",
    "assets/team-matcher.js",
    "assets/team-researchers.js",
    "assets/opportunity-team.js",
    "assets/opportunity-team-panel.js",
    "data/opportunity_team_index.js",
    "data/opportunity_teams.js",
    "match_explorer.html",
    "team_match.html",
    WORKER_SOURCE_PATH,
    "workers/search-voyage-proxy/wrangler.jsonc",
  ]) sourceHashes[path] = sha256(await read(path));
  const release = {
    schema_version: 1,
    generated_at: manifest.generated_at,
    current_corpus_sha256: manifest.corpus_sha256,
    previous_corpus_sha256: allowlist.previous?.corpus_sha256 || null,
    vector_sha256: manifest.vector_sha256,
    model: manifest.model,
    dimension: manifest.dimension,
    model_space_fingerprint: manifest.model_space_fingerprint || null,
    passage_count: manifest.passage_count,
    worker_allowlist_sha256: sha256(allowlistBytes),
    source_hashes: sourceHashes,
    atomic_publication_contract: "catalog + startup metadata + subtopics + manifest + vectors + model-space canaries + Worker allowlist + content-identified opportunity-team index and projection",
  };
  const releaseBytes = jsonBytes(release);

  if (write) {
    await Promise.all([
      writeFile(new URL(ALLOWLIST_PATH, ROOT), allowlistBytes),
      writeFile(new URL(RELEASE_PATH, ROOT), releaseBytes),
    ]);
  } else {
    const [actualAllowlist, actualRelease] = await Promise.all([read(ALLOWLIST_PATH), read(RELEASE_PATH)]);
    if (!actualAllowlist.equals(allowlistBytes)) throw new Error("The Worker corpus allowlist is stale or non-deterministic.");
    if (!actualRelease.equals(releaseBytes)) throw new Error("The public search release manifest is stale or non-deterministic.");
  }

  process.stdout.write(`${JSON.stringify({
    status: write ? "written" : "verified",
    current_corpus_sha256: release.current_corpus_sha256,
    previous_corpus_sha256: release.previous_corpus_sha256,
    vector_sha256: release.vector_sha256,
    worker_allowlist_sha256: release.worker_allowlist_sha256,
    passage_count: release.passage_count,
  }, null, 2)}\n`);
}

run().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
