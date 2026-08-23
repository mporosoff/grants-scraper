#!/usr/bin/env node

// Single-use Phase-4C acceptance runner. This is acceptance infrastructure,
// not retrieval logic. It calls the frozen production search modules and
// refuses to overwrite or repeat an existing raw execution.

import { createHash, webcrypto } from "node:crypto";
import { execFileSync } from "node:child_process";
import { access, constants, readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import process from "node:process";
import vm from "node:vm";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";
import { createHandler } from "../workers/search-voyage-proxy/src/index.js";

const ROOT = new URL("../", import.meta.url);
const FRAME_PATH = "evaluation/search_v2_iteration3_holdout_frame.json";
const MANIFEST_PATH = "evaluation/search_v2_iteration3_holdout_manifest.json";
const PREOPEN_PATH = "evaluation/search_v2_phase4c_preopen.json";
const RAW_PATH = "evaluation/search_v2_iteration3_holdout_results_raw.json";
const EXECUTION_PATH = "evaluation/search_v2_phase4c_execution.json";
const FROZEN_CANDIDATE = "f893d43e795a7f70efdf8191e863fb33e286d148";
const FRAME_SHA256 = "7fde6b7ccbdab59331c26899f37bdbb8f9ee7e30f8f3632f257e28d27124865e";
const POTENTIAL_LIMIT = 12;
const INTERNAL_PARENT_LIMIT = 50;
const PACING_MS = 250;
const EXPECTED_HASHES = Object.freeze({
  "assets/search-query.js": "43ddabcf52c78008f1862fb3a62ab5913f1a5de29b4bf5657f6196adfb3b5376",
  "assets/search-retrieval.js": "b67b19392131ce039f928ebf435cc42be481b5e0c7d4cf9b60223b8fdd94f097",
  "assets/search-hybrid.js": "6a4ffccd34a31a6ea8c40397584560636c0238d4b8250705c2ab4a7077a7c4b3",
  "assets/match-explain.js": "640cbb7b814d9eb78d6a4d62bd56253cbfa6ca07fe330db7e3d2413ba7d3806f",
  "assets/app.js": "21d62103a41636c288eb6a6f8ab6f5cd34f320829284c2492bc66ba16272cc2a",
  "assets/app-config.js": "42c5b3d6d4e24971ead1e024d85c07545612cb1d70b21e757caf6e77e7f1a028",
  "config/search_v2.json": "e0b4c902a00b578d7d044001c72c230dbf0ce55c919091cf8730f245964d99c9",
  "data/opportunities.js": "fb5dec36f33184572a84d6d9fed76adbb415c6102e2acbed50dc2d6ba22cbff6",
  "data/subtopics.js": "e2f45ecdfab26770f2346eaa4a488bb57fcaa3cc17c5d90ed25e30d14727f40d",
  "data/search-v2-voyage-manifest.json": "56fb57090696d3f9537be6a7f092a1565866672297f98f7d255518378109021d",
  "data/search-v2-voyage-vectors.f16": "697c84f76e83107e290df9b27168cd14fe6592bff2ae657b22d8eb9ee25fb8c2",
});
const BROAD_OPPORTUNITY_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science financial assistance|long[\s-]?range|research announcement|\broses\b|omnibus|unsolicited proposal|open topic|financial assistance program|annual program statement|office[ -]wide|open[ -]scope solicitation/i;

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function git(...args) {
  return execFileSync("git", args, { cwd: new URL(".", ROOT), encoding: "utf8" }).trim();
}

async function exists(relative) {
  try {
    await access(new URL(relative, ROOT), constants.F_OK);
    return true;
  } catch {
    return false;
  }
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

function rankOf(ids, id) {
  const index = ids.map(String).indexOf(String(id));
  return index >= 0 ? index + 1 : null;
}

function strongExplanation(harness, ranked, row) {
  const directEvidence = row.childDroveMatch
    ? row.bestChild?.directEvidence || null
    : row.parentDirectEvidence || ranked.parentDirect.evidence?.[row.index] || null;
  const broad = BROAD_OPPORTUNITY_RE.test(
    `${row.record?.title || ""} ${String(row.record?.description || "").slice(0, 1500)}`,
  );
  return {
    evidence: directEvidence ? {
      admission: directEvidence.admission || null,
      highest_contributing_passage: directEvidence.highestContributingPassage || null,
      exact_phrase: directEvidence.exactPhrase === true,
      exact_title_phrase: directEvidence.exactTitlePhrase === true,
      exact_opportunity_number: directEvidence.exactOpportunityNumber === true,
    } : null,
    rendered: Array.from(harness.explanationApi.build({
      parent: { record: row.record, broad, directEvidence: row.parentDirectEvidence || null },
      bestChild: row.bestChild,
    })),
  };
}

function hybridRow(parent, parentById) {
  return {
    hybrid_rank: Number(parent.hybrid_rank),
    parent_id: String(parent.parent_id),
    title: parentById.get(String(parent.parent_id))?.title || parent.title || "",
    passage_id: parent.passage_id,
    passage_kind: parent.passage_kind,
    record_id: parent.record_id || null,
    source_field: parent.explanation?.source_field || null,
    source_excerpt: parent.explanation?.excerpt || null,
    bm25f_rank: parent.bm25f_rank || null,
    semantic_rank: parent.semantic_rank || null,
    rrf_score: number(parent.rrf_score || 0),
    rerank_score: number(parent.voyage_score || 0),
    exact_identifier: parent.exact_identifier === true,
  };
}

async function verifyFrozenInputs() {
  if (!process.argv.includes("--execute-once")) {
    throw new Error("Phase 4C requires the explicit --execute-once authorization flag.");
  }
  const candidateIndex = process.argv.indexOf("--candidate");
  if (candidateIndex < 0 || process.argv[candidateIndex + 1] !== FROZEN_CANDIDATE) {
    throw new Error(`Phase 4C must name frozen candidate ${FROZEN_CANDIDATE}.`);
  }
  if (await exists(RAW_PATH) || await exists(EXECUTION_PATH)) {
    throw new Error("Phase 4C has already been executed; the single-use runner refuses a second run.");
  }
  if (git("branch", "--show-current") !== "search-quality-v2") {
    throw new Error("Phase 4C must run on search-quality-v2.");
  }
  if (git("rev-parse", "main") !== "ef7a0642f6ce66828f01ee280bd5993f66029b2f") {
    throw new Error("main changed after Phase 4C preregistration.");
  }
  const status = git("status", "--short");
  if (status) throw new Error("Phase 4C requires a clean working tree.");
  const frameSource = await readFile(new URL(FRAME_PATH, ROOT));
  if (sha256(frameSource) !== FRAME_SHA256) throw new Error("Phase 4C frame hash mismatch.");
  for (const [path, expected] of Object.entries(EXPECTED_HASHES)) {
    const actual = sha256(await readFile(new URL(path, ROOT)));
    if (actual !== expected) throw new Error(`Frozen candidate hash mismatch: ${path}.`);
  }
  const appConfig = await readFile(new URL("assets/app-config.js", ROOT), "utf8");
  if (!/searchV2:\s*false/.test(appConfig)) throw new Error("Search v2 production flag is not OFF.");
  const preopen = await readFile(new URL(PREOPEN_PATH, ROOT), "utf8").then(JSON.parse);
  if (preopen.frozen_candidate_sha !== FROZEN_CANDIDATE || preopen.declarations.holdout_execution_count !== 0) {
    throw new Error("Phase 4C pre-open checkpoint mismatch.");
  }
  return { frameSource };
}

async function main() {
  const { frameSource } = await verifyFrozenInputs();
  const apiKey = String(process.env.VOYAGE_API_KEY || "").trim();
  if (!apiKey) throw new Error("VOYAGE_API_KEY is required in this process environment.");
  const [
    frame,
    manifestRegistration,
    hybridSource,
    vectorManifestSource,
    vectorBuffer,
    preopenSource,
  ] = await Promise.all([
    Promise.resolve(JSON.parse(frameSource)),
    readFile(new URL(MANIFEST_PATH, ROOT), "utf8").then(JSON.parse),
    readFile(new URL("assets/search-hybrid.js", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-manifest.json", ROOT), "utf8"),
    readFile(new URL("data/search-v2-voyage-vectors.f16", ROOT)),
    readFile(new URL(PREOPEN_PATH, ROOT), "utf8"),
  ]);
  if (frame.query_count !== 36 || frame.queries?.length !== 36) {
    throw new Error("Phase 4C frame must contain exactly 36 queries.");
  }
  if (manifestRegistration.candidate_execution_count !== 0) {
    throw new Error("Phase 4C manifest does not declare zero prior executions.");
  }

  const vectorManifest = JSON.parse(vectorManifestSource);
  const base = await loadHarness();
  const harness = makeVariantHarness(base, { searchV2: true });
  const api = loadHybridApi(hybridSource);
  const handler = createHandler({ fetchImpl: globalThis.fetch.bind(globalThis) });
  const receipts = [];
  const fetchImpl = async (url, options = {}) => {
    if (String(url) === "https://assets.local/manifest") {
      return new Response(vectorManifestSource, {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (String(url) === "https://assets.local/vectors") return new Response(vectorBuffer, { status: 200 });
    const request = new Request(url, {
      ...options,
      headers: { ...(options.headers || {}), Origin: "http://localhost:8000" },
    });
    const body = String(options.body || "");
    const endpoint = new URL(String(url)).pathname;
    const started = performance.now();
    const response = await handler(request, { VOYAGE_API_KEY: apiKey });
    const publicReceipt = await response.clone().json().catch(() => ({}));
    receipts.push({
      endpoint,
      status: response.status,
      payload_bytes: Buffer.byteLength(body, "utf8"),
      latency_ms: number(performance.now() - started),
      provider_latency_ms: number(publicReceipt.latency_ms || 0),
      total_tokens: Number(publicReceipt.usage?.total_tokens || 0),
      document_count: endpoint === "/rerank" ? JSON.parse(body).candidates?.length || 0 : 0,
      error_code: publicReceipt.error?.code || null,
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
  const parentById = new Map(harness.parentCatalog.opportunities.map(record => [
    String(record.opportunity_id), record,
  ]));
  const rows = [];
  for (let queryIndex = 0; queryIndex < frame.queries.length; queryIndex += 1) {
    const item = frame.queries[queryIndex];
    if (queryIndex > 0) await new Promise(resolve => setTimeout(resolve, PACING_MS));
    const localStarted = performance.now();
    const local = rankQuery(harness, item.query, { evidence: true });
    const localLatency = performance.now() - localStarted;
    const strongIds = local.rows.map(row => String(row.id));
    const strongSet = new Set(strongIds);
    let hybrid = null;
    let hybridError = null;
    const hybridStarted = performance.now();
    try {
      hybrid = await client.search(item.query, { context: "" });
    } catch (error) {
      hybridError = { code: error?.code || "hybrid_failure", message: String(error?.message || error) };
    }
    const hybridLatency = performance.now() - hybridStarted;
    const hybridParents = hybrid?.parents || [];
    const potentialParents = hybridParents.filter(parent => !strongSet.has(String(parent.parent_id)));
    const potentialDisplayed = potentialParents.slice(0, POTENTIAL_LIMIT);
    const combinedInternalIds = [
      ...strongIds,
      ...potentialParents.map(parent => String(parent.parent_id)),
    ];
    const requiredPrimaryIds = (item.expected?.primary_ids || []).map(String);
    const expectedBroaderIds = (item.expected?.broader_ids || []).map(String);
    rows.push({
      ordinal: queryIndex + 1,
      query_id: item.id,
      query: item.query,
      discipline: item.discipline,
      stratum: item.stratum,
      preregistered: {
        required_primary_ids: requiredPrimaryIds,
        expected_broader_ids: expectedBroaderIds,
      },
      strong: {
        count: strongIds.length,
        ids: strongIds,
        rows: local.rows.map((row, index) => ({
          rank: index + 1,
          id: String(row.id),
          title: row.record?.title || "",
          score: number(row.score),
          evidence_tier: row.evidenceTier,
          parent_admitted: row.parentAdmitted,
          child_drove_match: row.childDroveMatch,
          best_child_id: row.bestChild?.id || null,
          explanation: strongExplanation(harness, local, row),
        })),
      },
      potential: {
        displayed_limit: POTENTIAL_LIMIT,
        available_after_deduplication: potentialParents.length,
        displayed: potentialDisplayed.map((parent, index) => ({
          potential_rank: index + 1,
          ...hybridRow(parent, parentById),
        })),
      },
      internal_hybrid_top_50: hybridParents.slice(0, INTERNAL_PARENT_LIMIT)
        .map(parent => hybridRow(parent, parentById)),
      required_anchor_positions: Object.fromEntries(requiredPrimaryIds.map(id => [id, {
        strong_rank: rankOf(strongIds, id),
        hybrid_rank: rankOf(hybridParents.map(parent => parent.parent_id), id),
        combined_internal_rank: rankOf(combinedInternalIds, id),
        potential_display_rank: rankOf(potentialDisplayed.map(parent => parent.parent_id), id),
      }])),
      broader_anchor_positions: Object.fromEntries(expectedBroaderIds.map(id => [id, {
        strong_rank: rankOf(strongIds, id),
        hybrid_rank: rankOf(hybridParents.map(parent => parent.parent_id), id),
        potential_display_rank: rankOf(potentialDisplayed.map(parent => parent.parent_id), id),
      }])),
      diagnostics: {
        local: local.parentDirect.diagnostics?.searchV2 || null,
        hybrid: hybrid?.diagnostics || null,
        provider_error: hybridError,
        fallback_used: Boolean(hybridError),
      },
      latency_ms: {
        strong_local: number(localLatency),
        hybrid_total: number(hybridLatency),
      },
    });
  }

  const usage = client.usage();
  const generatedAt = new Date().toISOString();
  const raw = {
    schema_version: 1,
    generated_at: generatedAt,
    phase: "4C",
    status: "immutable_one_time_raw_execution",
    execution_count: 1,
    holdout_query_execution_count: rows.length,
    frozen_candidate_sha: FROZEN_CANDIDATE,
    acceptance_runner_head: git("rev-parse", "HEAD"),
    branch: git("branch", "--show-current"),
    frame: {
      path: FRAME_PATH,
      sha256: sha256(frameSource),
      query_count: frame.query_count,
      preserved_query_order: rows.every((row, index) => row.query_id === frame.queries[index].id),
    },
    candidate_hashes: EXPECTED_HASHES,
    preopen_sha256: sha256(preopenSource),
    vector_handshake: {
      manifest_sha256: sha256(vectorManifestSource),
      corpus_sha256: vectorManifest.corpus_sha256,
      vector_sha256: sha256(vectorBuffer),
      vector_bytes: vectorBuffer.byteLength,
      passage_count: vectorManifest.passage_count,
    },
    product_contract: {
      strong: "conservative atomic-evidence local matcher",
      potential: "BM25F plus voyage-4-lite, RRF, deterministic safeguards, and rerank-2.5",
      potential_display_limit: POTENTIAL_LIMIT,
      deduplicated: true,
      semantic_score_is_verification_evidence: false,
    },
    provider: {
      models: { embedding: "voyage-4-lite", reranking: "rerank-2.5" },
      requests: receipts,
      usage,
      error_count: receipts.filter(item => item.status >= 400).length,
      query_fallback_count: rows.filter(row => row.diagnostics.fallback_used).length,
    },
    safety: {
      public_indexed_text_only: true,
      private_profile_cv_or_orcid_sent: false,
      api_key_printed_or_persisted: false,
      search_v2_production_enabled: false,
      main_touched: false,
      post_holdout_tuning_permitted: false,
    },
    queries: rows,
  };
  const serializedRaw = `${JSON.stringify(raw, null, 2)}\n`;
  if (/pa-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_-]{12,}/.test(serializedRaw)) {
    throw new Error("Refusing to write credential-like text.");
  }
  await writeFile(new URL(RAW_PATH, ROOT), serializedRaw, { encoding: "utf8", flag: "wx" });
  const rawHash = sha256(serializedRaw);
  const execution = {
    schema_version: 1,
    recorded_at: generatedAt,
    phase: "4C",
    execution_count: 1,
    holdout_query_execution_count: rows.length,
    raw_results: RAW_PATH,
    raw_sha256: rawHash,
    frozen_candidate_sha: FROZEN_CANDIDATE,
    acceptance_runner_head: raw.acceptance_runner_head,
    frame_sha256: raw.frame.sha256,
    config_sha256: EXPECTED_HASHES["config/search_v2.json"],
    catalog_sha256: EXPECTED_HASHES["data/opportunities.js"],
    sidecar_sha256: EXPECTED_HASHES["data/subtopics.js"],
    corpus_sha256: vectorManifest.corpus_sha256,
    vector_sha256: raw.vector_handshake.vector_sha256,
    provider_request_count: receipts.length,
    provider_error_count: raw.provider.error_count,
    query_fallback_count: raw.provider.query_fallback_count,
    second_execution_permitted: false,
  };
  const serializedExecution = `${JSON.stringify(execution, null, 2)}\n`;
  await writeFile(new URL(EXECUTION_PATH, ROOT), serializedExecution, { encoding: "utf8", flag: "wx" });
  process.stdout.write(`${JSON.stringify({
    raw_results: RAW_PATH,
    raw_sha256: rawHash,
    execution_artifact: EXECUTION_PATH,
    execution_count: 1,
    query_count: rows.length,
    provider_request_count: receipts.length,
    provider_error_count: raw.provider.error_count,
    query_fallback_count: raw.provider.query_fallback_count,
  }, null, 2)}\n`);
}

await main();
