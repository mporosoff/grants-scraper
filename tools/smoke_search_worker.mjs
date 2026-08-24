#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { webcrypto } from "node:crypto";
import process from "node:process";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const DEFAULT_WORKER = "https://funding-finder-voyage-search.urochestercheme.workers.dev/";
const ORIGIN = "https://mporosoff.github.io";

function loadData(source, key) {
  const context = { globalThis: {} };
  vm.runInNewContext(source, context);
  if (!context.globalThis[key]) throw new Error(`${key} was not loaded.`);
  return context.globalThis[key];
}

function loadHybrid(source) {
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
  context.globalThis = { crypto: webcrypto, location: { href: ORIGIN } };
  vm.runInNewContext(source, context);
  return context.globalThis.FUNDING_HYBRID_SEARCH;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { Origin: ORIGIN, ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  return { status: response.status, body };
}

async function main() {
  const worker = new URL(process.argv[2] || DEFAULT_WORKER);
  const [parentSource, childSource, hybridSource, allowlistSource] = await Promise.all([
    readFile(new URL("data/opportunities.js", ROOT), "utf8"),
    readFile(new URL("data/subtopics.js", ROOT), "utf8"),
    readFile(new URL("assets/search-hybrid.js", ROOT), "utf8"),
    readFile(new URL("workers/search-voyage-proxy/generated/corpus-allowlist.json", ROOT), "utf8"),
  ]);
  const parentCatalog = loadData(parentSource, "GRANT_CATALOG");
  const childCatalog = loadData(childSource, "SUBTOPIC_CATALOG");
  const hybrid = loadHybrid(hybridSource);
  const allowlist = JSON.parse(allowlistSource);
  const corpus = hybrid.buildCorpus({ parentCatalog, childCatalog });
  const currentAllowed = new Map(
    allowlist.current.passages.map(item => [item.passage_id, item.text_sha256]),
  );
  const previousAllowed = new Map(
    allowlist.previous.passages.map(item => [item.passage_id, item.text_sha256]),
  );

  let shared = null;
  for (const passage of corpus) {
    const hash = await hybrid.sha256Hex(passage.text);
    if (currentAllowed.get(passage.passage_id) !== hash) continue;
    if (previousAllowed.get(passage.passage_id) !== hash) continue;
    shared = { passage_id: passage.passage_id, text_sha256: hash, text: passage.text };
    break;
  }
  if (!shared) throw new Error("No byte-identical current/previous passage was found.");

  const health = await requestJson(new URL("health", worker));
  if (health.status !== 200
    || health.body.corpus_sha256 !== allowlist.current.corpus_sha256
    || health.body.model_space_fingerprint !== allowlist.current.model_space_fingerprint
    || health.body.previous_corpus_supported !== true
    || health.body.budget_state !== "available") {
    throw new Error("Worker health does not match the release package.");
  }

  const embed = await requestJson(new URL("embed-query", worker), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "catalysis" }),
  });
  if (embed.status !== 200 || embed.body.embedding?.length !== hybrid.EMBEDDING_DIMENSION) {
    throw new Error(`Current embed smoke failed with HTTP ${embed.status}.`);
  }

  async function rerank(generation) {
    const payload = {
      query: "catalysis",
      corpus_sha256: generation.corpus_sha256,
      candidates: [shared],
    };
    if (generation.model_space_fingerprint) {
      payload.model_space_fingerprint = generation.model_space_fingerprint;
    }
    return requestJson(new URL("rerank", worker), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  const current = await rerank(allowlist.current);
  const previous = await rerank(allowlist.previous);
  if (current.status !== 200 || current.body.rankings?.length !== 1) {
    throw new Error(`Current corpus rerank smoke failed with HTTP ${current.status}.`);
  }
  if (previous.status !== 200 || previous.body.rankings?.length !== 1) {
    throw new Error(`Previous corpus rerank smoke failed with HTTP ${previous.status}.`);
  }

  const unknown = await requestJson(new URL("rerank", worker), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: "catalysis",
      corpus_sha256: "f".repeat(64),
      candidates: [shared],
    }),
  });
  if (unknown.status !== 400) {
    throw new Error(`Unknown corpus was not rejected: HTTP ${unknown.status}.`);
  }

  process.stdout.write(`${JSON.stringify({
    status: "passed",
    worker: worker.origin,
    current_corpus_sha256: allowlist.current.corpus_sha256,
    previous_corpus_sha256: allowlist.previous.corpus_sha256,
    model_space_fingerprint: allowlist.current.model_space_fingerprint,
    shared_passage_id: shared.passage_id,
    embed_model: embed.body.model,
    embed_tokens: embed.body.usage?.total_tokens || 0,
    current_rerank_status: current.status,
    previous_rerank_status: previous.status,
    unknown_corpus_status: unknown.status,
  }, null, 2)}\n`);
}

main().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
