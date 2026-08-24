import corpusAllowlist from "../generated/corpus-allowlist.json" with { type: "json" };

const VOYAGE_EMBED_URL = "https://api.voyageai.com/v1/embeddings";
const VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank";
const EMBEDDING_MODEL = "voyage-4-lite";
const RERANK_MODEL = "rerank-2.5";
const EMBEDDING_DIMENSION = 1024;
const MAX_QUERY_CHARS = 500;
const MAX_CANDIDATES = 300;
const MAX_PASSAGE_CHARS = 3_000;
const MAX_REQUEST_BYTES = 1_100_000;
const PROVIDER_TIMEOUT_MS = 7_000;
const QUERY_INSTRUCTION = "Rank public funding opportunities by whether their authoritative scientific or programmatic scope supports the complete research intent. Do not reward partial word overlap when a major query concept is absent.\n\nResearch query: <QUERY>";
const PRODUCTION_ORIGIN = "https://mporosoff.github.io";
const BUDGET_COORDINATOR_NAME = "funding-finder-global-budget";
const LATENCY_BUCKETS_MS = [100, 250, 500, 1_000, 2_000, 5_000, 10_000];

function generationHashes(allowlist) {
  const generations = new Map();
  [allowlist?.current, allowlist?.previous].filter(Boolean).forEach(generation => {
    if (!generation.corpus_sha256 || !Array.isArray(generation.passages)) return;
    generations.set(generation.corpus_sha256, {
      model_space_fingerprint: generation.model_space_fingerprint || null,
      passage_hashes: new Map(
        generation.passages.map(item => [item.passage_id, item.text_sha256]),
      ),
    });
  });
  return generations;
}

function allowedOrigin(value) {
  if (value === PRODUCTION_ORIGIN) return true;
  try {
    const url = new URL(value);
    return url.protocol === "http:"
      && /^(localhost|127\.0\.0\.1|\[::1\])$/.test(url.hostname);
  } catch {
    return false;
  }
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Vary": "Origin",
  };
}

function json(origin, status, payload, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { ...corsHeaders(origin), ...extraHeaders },
  });
}

function error(origin, status, code, extraHeaders = {}) {
  return json(origin, status, { error: { code } }, extraHeaders);
}

function boundedInteger(value, { minimum = 1, maximum = Number.MAX_SAFE_INTEGER } = {}) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum && parsed <= maximum ? parsed : null;
}

function serviceConfig(env) {
  const config = {
    enabled: String(env?.ENHANCED_SEARCH_ENABLED || "").toLowerCase() === "true",
    embedBudget: boundedInteger(env?.DAILY_EMBED_TOKEN_BUDGET),
    rerankBudget: boundedInteger(env?.DAILY_RERANK_TOKEN_BUDGET),
    clientEmbedLimit: boundedInteger(env?.PER_CLIENT_EMBED_REQUEST_LIMIT),
    clientRerankLimit: boundedInteger(env?.PER_CLIENT_RERANK_REQUEST_LIMIT),
    globalRequestLimit: boundedInteger(env?.GLOBAL_REQUEST_LIMIT),
    retryAfter: boundedInteger(env?.RATE_LIMIT_RETRY_AFTER_SECONDS, { maximum: 60 }),
  };
  config.valid = Boolean(
    config.enabled
    && config.embedBudget
    && config.rerankBudget
    && config.clientEmbedLimit
    && config.clientRerankLimit
    && config.globalRequestLimit
    && config.retryAfter
    && env?.VOYAGE_API_KEY
    && env?.BUDGET_COORDINATOR
    && env?.GLOBAL_RATE_LIMITER
    && env?.EMBED_RATE_LIMITER
    && env?.RERANK_RATE_LIMITER
  );
  return config;
}

function utf8Bytes(value) {
  return new TextEncoder().encode(String(value || "")).byteLength;
}

function reservationEstimate(kind, query, candidates = []) {
  if (kind === "embed") return utf8Bytes(query);
  const instructionBytes = utf8Bytes(QUERY_INSTRUCTION.replace("<QUERY>", query));
  return candidates.reduce((sum, candidate) => sum + utf8Bytes(candidate.text), 0)
    + instructionBytes * candidates.length;
}

function dayUtc(timestamp = Date.now()) {
  return new Date(timestamp).toISOString().slice(0, 10);
}

function exactKeys(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function cleanQuery(value) {
  if (typeof value !== "string") return "";
  const query = value.replace(/\s+/g, " ").trim();
  return query.length > 0 && query.length <= MAX_QUERY_CHARS ? query : "";
}

async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...digest].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function parseBody(request) {
  if (!String(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) {
    throw Object.assign(new Error("content type"), { status: 415, code: "json_required" });
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_REQUEST_BYTES) {
    throw Object.assign(new Error("payload too large"), { status: 413, code: "request_too_large" });
  }
  const source = await request.text();
  if (new TextEncoder().encode(source).byteLength > MAX_REQUEST_BYTES) {
    throw Object.assign(new Error("payload too large"), { status: 413, code: "request_too_large" });
  }
  try {
    return JSON.parse(source);
  } catch {
    throw Object.assign(new Error("invalid json"), { status: 400, code: "invalid_json" });
  }
}

async function voyageFetch(fetchImpl, url, apiKey, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROVIDER_TIMEOUT_MS);
  const started = performance.now();
  try {
    const response = await fetchImpl(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const source = await response.text();
    let payload;
    try {
      payload = JSON.parse(source);
    } catch {
      throw Object.assign(new Error("provider response"), { status: 502, code: "provider_invalid_response" });
    }
    if (!response.ok) {
      const status = response.status === 429 || response.status >= 500 ? 503 : 502;
      throw Object.assign(new Error("provider error"), { status, code: "provider_unavailable" });
    }
    return { payload, latency_ms: Number((performance.now() - started).toFixed(3)) };
  } catch (cause) {
    if (cause?.name === "AbortError") {
      throw Object.assign(new Error("provider timeout"), { status: 504, code: "provider_timeout" });
    }
    throw cause;
  } finally {
    clearTimeout(timer);
  }
}

async function validateCandidates(body, generations) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const query = cleanQuery(body.query);
  const generation = generations.get(body.corpus_sha256);
  const expectedKeys = generation?.model_space_fingerprint
    ? ["query", "corpus_sha256", "model_space_fingerprint", "candidates"]
    : ["query", "corpus_sha256", "candidates"];
  if (!exactKeys(body, expectedKeys)) return null;
  if (generation?.model_space_fingerprint
    && body.model_space_fingerprint !== generation.model_space_fingerprint) return null;
  const passageHashes = generation?.passage_hashes;
  if (!query || !passageHashes || !Array.isArray(body.candidates) || body.candidates.length < 1
    || body.candidates.length > MAX_CANDIDATES) return null;
  const seen = new Set();
  for (const candidate of body.candidates) {
    if (!exactKeys(candidate, ["passage_id", "text_sha256", "text"])) return null;
    if (typeof candidate.passage_id !== "string" || seen.has(candidate.passage_id)) return null;
    if (typeof candidate.text !== "string" || candidate.text.length < 1
      || candidate.text.length > MAX_PASSAGE_CHARS) return null;
    const allowedHash = passageHashes.get(candidate.passage_id);
    if (!allowedHash || candidate.text_sha256 !== allowedHash) return null;
    seen.add(candidate.passage_id);
  }
  const hashes = await Promise.all(body.candidates.map(candidate => sha256Hex(candidate.text)));
  if (hashes.some((hash, index) => hash !== body.candidates[index].text_sha256)) return null;
  return { query, candidates: body.candidates };
}

function emptyEndpointMetrics() {
  return {
    requests: 0,
    provider_input_tokens: 0,
    provider_failures: 0,
    rate_limit_rejections: 0,
    budget_rejections: 0,
    latency_histogram: new Array(LATENCY_BUCKETS_MS.length + 1).fill(0),
  };
}

function emptyBudgetState(day) {
  return {
    day,
    embed: emptyEndpointMetrics(),
    rerank: emptyEndpointMetrics(),
    reservations: {},
  };
}

function latencyBucket(latencyMs) {
  const index = LATENCY_BUCKETS_MS.findIndex(limit => latencyMs <= limit);
  return index < 0 ? LATENCY_BUCKETS_MS.length : index;
}

function percentileFromHistogram(histogram, fraction) {
  const total = histogram.reduce((sum, count) => sum + count, 0);
  if (!total) return null;
  const target = Math.ceil(total * fraction);
  let seen = 0;
  for (let index = 0; index < histogram.length; index += 1) {
    seen += histogram[index];
    if (seen >= target) return LATENCY_BUCKETS_MS[index] || LATENCY_BUCKETS_MS[LATENCY_BUCKETS_MS.length - 1] + 1;
  }
  return null;
}

function internalJson(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export class SearchBudgetCoordinator {
  constructor(ctx) {
    this.ctx = ctx;
  }

  async fetch(request) {
    if (request.method !== "POST") return internalJson(405, { error: "method_not_allowed" });
    let body;
    try {
      body = await request.json();
    } catch {
      return internalJson(400, { error: "invalid_json" });
    }
    const kind = body?.kind === "embed" || body?.kind === "rerank" ? body.kind : "";
    if (!kind) return internalJson(400, { error: "invalid_kind" });
    const budgets = {
      embed: boundedInteger(body?.budgets?.embed),
      rerank: boundedInteger(body?.budgets?.rerank),
    };
    if (!budgets.embed || !budgets.rerank) return internalJson(503, { error: "invalid_budget" });

    const today = dayUtc();
    let state = await this.ctx.storage.get("daily");
    if (!state || state.day !== today) state = emptyBudgetState(today);
    const metrics = state[kind];
    if (body.action === "rate_rejection") {
      metrics.rate_limit_rejections += 1;
      await this.ctx.storage.put("daily", state);
      return internalJson(200, { recorded: true });
    }
    if (body.action === "status") {
      const exhausted = ["embed", "rerank"].some(endpoint => (
        state[endpoint].provider_input_tokens >= budgets[endpoint]
      ));
      return internalJson(200, {
        budget_state: exhausted ? "exhausted" : "available",
        latency_ms: {
          embed: {
            p50: percentileFromHistogram(state.embed.latency_histogram, .5),
            p95: percentileFromHistogram(state.embed.latency_histogram, .95),
          },
          rerank: {
            p50: percentileFromHistogram(state.rerank.latency_histogram, .5),
            p95: percentileFromHistogram(state.rerank.latency_histogram, .95),
          },
        },
      });
    }
    if (body.action === "reserve") {
      const amount = boundedInteger(body.amount);
      const reservationId = typeof body.reservation_id === "string" && body.reservation_id.length <= 80
        ? body.reservation_id : "";
      if (!amount || !reservationId || state.reservations[reservationId]) {
        return internalJson(400, { error: "invalid_reservation" });
      }
      const outstanding = Object.values(state.reservations)
        .filter(item => item.kind === kind)
        .reduce((sum, item) => sum + item.amount, 0);
      if (metrics.provider_input_tokens + outstanding + amount > budgets[kind]) {
        metrics.budget_rejections += 1;
        await this.ctx.storage.put("daily", state);
        return internalJson(429, { error: "budget_exhausted" });
      }
      state.reservations[reservationId] = { kind, amount };
      await this.ctx.storage.put("daily", state);
      return internalJson(200, { reserved: true });
    }
    const reservation = state.reservations[body.reservation_id];
    if (!reservation || reservation.kind !== kind) return internalJson(409, { error: "unknown_reservation" });
    delete state.reservations[body.reservation_id];
    if (body.action === "provider_failure") {
      metrics.provider_failures += 1;
      await this.ctx.storage.put("daily", state);
      return internalJson(200, { recorded: true });
    }
    if (body.action !== "settle") return internalJson(400, { error: "invalid_action" });
    const actualTokens = boundedInteger(body.actual_tokens, { minimum: 0 }) ?? 0;
    const latencyMs = Math.max(0, Number(body.latency_ms) || 0);
    metrics.requests += 1;
    metrics.provider_input_tokens += actualTokens;
    metrics.latency_histogram[latencyBucket(latencyMs)] += 1;
    await this.ctx.storage.put("daily", state);
    return internalJson(200, {
      recorded: true,
      budget_state: metrics.provider_input_tokens >= budgets[kind] ? "exhausted" : "available",
    });
  }
}

async function budgetCall(env, payload) {
  const id = env.BUDGET_COORDINATOR.idFromName(BUDGET_COORDINATOR_NAME);
  const stub = env.BUDGET_COORDINATOR.get(id);
  const response = await stub.fetch("https://budget.internal/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  return { ok: response.ok, status: response.status, body };
}

function budgetPayload(config, values) {
  return {
    ...values,
    budgets: { embed: config.embedBudget, rerank: config.rerankBudget },
  };
}

async function enforceRateLimits(request, env, config, kind) {
  const clientKey = request.headers.get("cf-connecting-ip") || "unknown-client";
  const endpointLimiter = kind === "embed" ? env.EMBED_RATE_LIMITER : env.RERANK_RATE_LIMITER;
  let globalResult;
  let endpointResult;
  try {
    [globalResult, endpointResult] = await Promise.all([
      env.GLOBAL_RATE_LIMITER.limit({ key: "all-hosted-search" }),
      endpointLimiter.limit({ key: clientKey }),
    ]);
  } catch {
    throw Object.assign(new Error("rate limit unavailable"), { status: 503, code: "service_unconfigured" });
  }
  if (globalResult?.success && endpointResult?.success) return;
  await budgetCall(env, budgetPayload(config, { action: "rate_rejection", kind })).catch(() => null);
  throw Object.assign(new Error("rate limited"), {
    status: 429,
    code: "rate_limited",
    retryAfter: config.retryAfter,
  });
}

async function reserveBudget(env, config, kind, amount) {
  const reservationId = crypto.randomUUID();
  let result;
  try {
    result = await budgetCall(env, budgetPayload(config, {
      action: "reserve",
      kind,
      amount,
      reservation_id: reservationId,
    }));
  } catch {
    throw Object.assign(new Error("budget unavailable"), { status: 503, code: "service_unconfigured" });
  }
  if (!result.ok) {
    const limited = result.status === 429;
    throw Object.assign(new Error(limited ? "budget exhausted" : "budget unavailable"), {
      status: limited ? 429 : 503,
      code: limited ? "budget_limited" : "service_unconfigured",
      retryAfter: limited ? config.retryAfter : null,
    });
  }
  return reservationId;
}

async function settleBudget(env, config, values) {
  const result = await budgetCall(env, budgetPayload(config, { action: "settle", ...values }));
  if (!result.ok) throw Object.assign(new Error("budget settlement failed"), { status: 503, code: "service_unconfigured" });
}

async function releaseFailedBudget(env, config, values) {
  await budgetCall(env, budgetPayload(config, { action: "provider_failure", ...values })).catch(() => null);
}

export function createHandler({ fetchImpl = fetch, allowlist = corpusAllowlist } = {}) {
  const generations = generationHashes(allowlist);
  return async function handle(request, env) {
    const origin = request.headers.get("origin") || "";
    if (!allowedOrigin(origin)) return error(PRODUCTION_ORIGIN, 403, "origin_forbidden");
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(origin) });
    const path = new URL(request.url).pathname.replace(/\/+$/, "");
    const config = serviceConfig(env);
    if (request.method === "GET" && path === "/health") {
      if (!config.valid) {
        return json(origin, 200, {
          service: "unavailable",
          corpus_sha256: allowlist?.current?.corpus_sha256 || "",
          model_space_fingerprint: allowlist?.current?.model_space_fingerprint || "",
          previous_corpus_supported: Boolean(allowlist?.previous),
          budget_state: "unavailable",
        });
      }
      const status = await budgetCall(env, budgetPayload(config, { action: "status", kind: "embed" }))
        .catch(() => ({ ok: false, body: {} }));
      return json(origin, 200, {
        service: status.ok ? "available" : "unavailable",
        corpus_sha256: allowlist.current.corpus_sha256,
        model_space_fingerprint: allowlist.current.model_space_fingerprint || "",
        previous_corpus_supported: Boolean(allowlist.previous),
        budget_state: status.ok ? status.body.budget_state : "unavailable",
      });
    }
    if (request.method !== "POST") return error(origin, 405, "method_not_allowed");
    if (!config.enabled) return error(origin, 503, "service_disabled");
    if (!config.valid) return error(origin, 503, "service_unconfigured");
    let body;
    try {
      body = await parseBody(request);
      if (path === "/embed-query") {
        if (!exactKeys(body, ["query"])) return error(origin, 400, "invalid_request");
        const query = cleanQuery(body.query);
        if (!query) return error(origin, 400, "invalid_query");
        await enforceRateLimits(request, env, config, "embed");
        const reservationId = await reserveBudget(
          env, config, "embed", reservationEstimate("embed", query),
        );
        let result;
        try {
          result = await voyageFetch(fetchImpl, VOYAGE_EMBED_URL, env.VOYAGE_API_KEY, {
            input: [query],
            model: EMBEDDING_MODEL,
            input_type: "query",
            truncation: true,
            output_dimension: EMBEDDING_DIMENSION,
            output_dtype: "float",
          });
        } catch (cause) {
          await releaseFailedBudget(env, config, {
            kind: "embed", reservation_id: reservationId,
          });
          throw cause;
        }
        const embedding = result.payload.data?.[0]?.embedding;
        if (!Array.isArray(embedding) || embedding.length !== EMBEDDING_DIMENSION) {
          await releaseFailedBudget(env, config, {
            kind: "embed", reservation_id: reservationId,
          });
          return error(origin, 502, "provider_invalid_embedding");
        }
        await settleBudget(env, config, {
          kind: "embed",
          reservation_id: reservationId,
          actual_tokens: Number(result.payload.usage?.total_tokens || 0),
          latency_ms: result.latency_ms,
        });
        return json(origin, 200, {
          model: result.payload.model || EMBEDDING_MODEL,
          embedding,
          usage: { total_tokens: Number(result.payload.usage?.total_tokens || 0) },
          latency_ms: result.latency_ms,
        });
      }
      if (path === "/rerank") {
        const validated = await validateCandidates(body, generations);
        if (!validated) return error(origin, 400, "invalid_candidates");
        await enforceRateLimits(request, env, config, "rerank");
        const reservationId = await reserveBudget(
          env, config, "rerank",
          reservationEstimate("rerank", validated.query, validated.candidates),
        );
        let result;
        try {
          result = await voyageFetch(fetchImpl, VOYAGE_RERANK_URL, env.VOYAGE_API_KEY, {
            query: QUERY_INSTRUCTION.replace("<QUERY>", validated.query),
            documents: validated.candidates.map(candidate => candidate.text),
            model: RERANK_MODEL,
            top_k: validated.candidates.length,
            return_documents: false,
            truncation: true,
          });
        } catch (cause) {
          await releaseFailedBudget(env, config, {
            kind: "rerank", reservation_id: reservationId,
          });
          throw cause;
        }
        const rankings = result.payload.data || result.payload.results;
        if (!Array.isArray(rankings) || rankings.length !== validated.candidates.length) {
          await releaseFailedBudget(env, config, {
            kind: "rerank", reservation_id: reservationId,
          });
          return error(origin, 502, "provider_invalid_ranking");
        }
        await settleBudget(env, config, {
          kind: "rerank",
          reservation_id: reservationId,
          actual_tokens: Number(result.payload.usage?.total_tokens || 0),
          latency_ms: result.latency_ms,
        });
        return json(origin, 200, {
          model: result.payload.model || RERANK_MODEL,
          rankings: rankings.map(item => ({
            index: Number(item.index),
            passage_id: validated.candidates[Number(item.index)]?.passage_id || "",
            relevance_score: Number(item.relevance_score),
          })),
          usage: { total_tokens: Number(result.payload.usage?.total_tokens || 0) },
          latency_ms: result.latency_ms,
        });
      }
      return error(origin, 404, "not_found");
    } catch (cause) {
      const retryAfter = boundedInteger(cause?.retryAfter, { maximum: 60 });
      return error(
        origin,
        Number(cause?.status || 500),
        cause?.code || "proxy_failure",
        retryAfter ? { "Retry-After": String(retryAfter) } : {},
      );
    }
  };
}

const handle = createHandler();

export default {
  fetch(request, env) {
    return handle(request, env);
  },
};
