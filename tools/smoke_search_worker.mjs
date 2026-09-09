#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { webcrypto } from "node:crypto";
import process from "node:process";
import vm from "node:vm";
import { resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const ROOT = process.env.FUNDING_RELEASE_INPUT_ROOT
  ? pathToFileURL(resolve(process.env.FUNDING_RELEASE_INPUT_ROOT) + sep)
  : new URL("../", import.meta.url);
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
    signal: AbortSignal.timeout(30000),
    redirect: "error",
    ...options,
    headers: {
      Origin: ORIGIN,
      Accept: "application/json",
      "Cache-Control": "no-cache",
      "User-Agent": "FundingFinder-ReleaseVerifier/1.0 (+https://github.com/mporosoff/grants-scraper)",
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  return { status: response.status, body, content_type: response.headers.get("content-type")?.slice(0, 160) };
}

export async function waitForHealth(worker, generation, {
  request = requestJson,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
} = {}) {
  const expected = {
    service: "available",
    corpus_sha256: generation.corpus_sha256,
    model_space_fingerprint: generation.model_space_fingerprint,
    previous_corpus_supported: true,
    budget_state: "available",
  };
  const failures = [];
  // A successful probe at one edge does not finish Worker propagation at every
  // edge. Match the handshake's bounded read-only retry window before any POST.
  for (let attempt = 1; attempt <= 12; attempt += 1) {
    try {
      const health = await request(new URL("health", worker));
      const mismatch = Object.keys(expected).filter(key => health.body?.[key] !== expected[key]);
      if (health.status === 200 && mismatch.length === 0) return;
      failures.push({ attempt, status: health.status, content_type: health.content_type, mismatch });
    } catch (error) {
      // Error messages and provider bodies may contain arbitrary remote text.
      failures.push({ attempt, transport_error: error instanceof Error ? error.name.slice(0, 80) : "Error" });
    }
    if (attempt < 12) await sleep(5000);
  }
  throw new Error(`Worker health does not match the release package: ${JSON.stringify(failures)}`);
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

  await waitForHealth(worker, allowlist.current);

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

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) main().catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
