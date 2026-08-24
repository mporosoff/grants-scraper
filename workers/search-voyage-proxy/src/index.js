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

function generationHashes(allowlist) {
  const generations = new Map();
  [allowlist?.current, allowlist?.previous].filter(Boolean).forEach(generation => {
    if (!generation.corpus_sha256 || !Array.isArray(generation.passages)) return;
    generations.set(generation.corpus_sha256, new Map(
      generation.passages.map(item => [item.passage_id, item.text_sha256]),
    ));
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
    "Access-Control-Allow-Methods": "POST, OPTIONS",
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

function error(origin, status, code) {
  return json(origin, status, { error: { code } });
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
  if (!exactKeys(body, ["query", "corpus_sha256", "candidates"])) return null;
  const query = cleanQuery(body.query);
  const passageHashes = generations.get(body.corpus_sha256);
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

export function createHandler({ fetchImpl = fetch, allowlist = corpusAllowlist } = {}) {
  const generations = generationHashes(allowlist);
  return async function handle(request, env) {
    const origin = request.headers.get("origin") || "";
    if (!allowedOrigin(origin)) return error(PRODUCTION_ORIGIN, 403, "origin_forbidden");
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(origin) });
    if (request.method !== "POST") return error(origin, 405, "method_not_allowed");
    const path = new URL(request.url).pathname.replace(/\/+$/, "");
    let body;
    try {
      body = await parseBody(request);
      if (path === "/embed-query") {
        if (!env?.VOYAGE_API_KEY) return error(origin, 503, "service_unconfigured");
        if (!exactKeys(body, ["query"])) return error(origin, 400, "invalid_request");
        const query = cleanQuery(body.query);
        if (!query) return error(origin, 400, "invalid_query");
        const result = await voyageFetch(fetchImpl, VOYAGE_EMBED_URL, env.VOYAGE_API_KEY, {
          input: [query],
          model: EMBEDDING_MODEL,
          input_type: "query",
          truncation: true,
          output_dimension: EMBEDDING_DIMENSION,
          output_dtype: "float",
        });
        const embedding = result.payload.data?.[0]?.embedding;
        if (!Array.isArray(embedding) || embedding.length !== EMBEDDING_DIMENSION) {
          return error(origin, 502, "provider_invalid_embedding");
        }
        return json(origin, 200, {
          model: result.payload.model || EMBEDDING_MODEL,
          embedding,
          usage: { total_tokens: Number(result.payload.usage?.total_tokens || 0) },
          latency_ms: result.latency_ms,
        });
      }
      if (path === "/rerank") {
        if (!env?.VOYAGE_API_KEY) return error(origin, 503, "service_unconfigured");
        const validated = await validateCandidates(body, generations);
        if (!validated) return error(origin, 400, "invalid_candidates");
        const result = await voyageFetch(fetchImpl, VOYAGE_RERANK_URL, env.VOYAGE_API_KEY, {
          query: QUERY_INSTRUCTION.replace("<QUERY>", validated.query),
          documents: validated.candidates.map(candidate => candidate.text),
          model: RERANK_MODEL,
          top_k: validated.candidates.length,
          return_documents: false,
          truncation: true,
        });
        const rankings = result.payload.data || result.payload.results;
        if (!Array.isArray(rankings) || rankings.length !== validated.candidates.length) {
          return error(origin, 502, "provider_invalid_ranking");
        }
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
      return error(origin, Number(cause?.status || 500), cause?.code || "proxy_failure");
    }
  };
}

const handle = createHandler();

export default {
  fetch(request, env) {
    return handle(request, env);
  },
};
