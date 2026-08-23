import passageManifest from "../../../data/search-v2-voyage-manifest.json" with { type: "json" };

const VOYAGE_EMBED_URL = "https://api.voyageai.com/v1/embeddings";
const VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank";
const EMBEDDING_MODEL = "voyage-4-lite";
const RERANK_MODEL = "rerank-2.5";
const JUDGE_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast";
const EMBEDDING_DIMENSION = 1024;
const MAX_QUERY_CHARS = 500;
const MAX_CANDIDATES = 300;
const MAX_PASSAGE_CHARS = 3_000;
const MAX_REQUEST_BYTES = 1_100_000;
const PROVIDER_TIMEOUT_MS = 7_000;
const JUDGE_TIMEOUT_MS = 10_000;
const QUERY_INSTRUCTION = "Rank public funding opportunities by whether their authoritative scientific or programmatic scope supports the complete research intent. Do not reward partial word overlap when a major query concept is absent.\n\nResearch query: <QUERY>";
const JUDGE_SYSTEM_PROMPT = `You are a strict relevance classifier for public funding opportunities.
Judge every supplied result only from its supplied published passage. Do not use outside knowledge and do not manufacture funding scope. Paraphrase is allowed; literal wording is not required.

PRIMARY: The supplied published passage supports the complete substantive research or programmatic intent of the query.
BROADER: The passage is genuinely adjacent or useful, but one important query dimension is not established.
REJECT: The passage is incidental, partial-intent, acronymically wrong, administratively related, or otherwise does not support the complete query.

Return exactly one classification for every supplied result ID and no additional claims.`;
const PRODUCTION_ORIGIN = "https://mporosoff.github.io";
const PASSAGE_HASHES = new Map(passageManifest.passages.map(item => [item.passage_id, item.text_sha256]));
const PASSAGE_REFS_BY_HASH = new Map();
passageManifest.passages.forEach(item => {
  const refs = PASSAGE_REFS_BY_HASH.get(item.text_sha256) || [];
  refs.push({ parent_id: String(item.parent_id), passage_kind: item.passage_kind });
  PASSAGE_REFS_BY_HASH.set(item.text_sha256, refs);
});
const JUDGE_FIELDS = new Set([
  "parent_title",
  "parent_description",
  "authoritative_program_area",
  "bounded_source_evidence",
  "child_title",
  "child_summary",
]);
const JUDGE_TYPES = new Set(["parent", "publication_eligible_child"]);
const JUDGE_FIELD_LABELS = new Map([
  ["parent_title", "Parent title"],
  ["parent_description", "Parent description"],
  ["authoritative_program_area", "Authoritative program area"],
  ["bounded_source_evidence", "Public source evidence"],
  ["child_title", "Publication-eligible child title"],
  ["child_summary", "Child summary"],
]);
const JUDGE_CLASSIFICATIONS = new Set(["primary", "broader", "reject"]);
const JUDGE_SCHEMA = Object.freeze({
  type: "object",
  additionalProperties: false,
  properties: {
    results: {
      type: "array",
      minItems: 1,
      maxItems: 10,
      items: {
        type: "object",
        additionalProperties: false,
        properties: {
          id: { type: "string" },
          classification: { type: "string", enum: ["primary", "broader", "reject"] },
        },
        required: ["id", "classification"],
      },
    },
  },
  required: ["results"],
});

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

async function validateCandidates(body) {
  if (!exactKeys(body, ["query", "corpus_sha256", "candidates"])) return null;
  const query = cleanQuery(body.query);
  if (!query || body.corpus_sha256 !== passageManifest.corpus_sha256
    || !Array.isArray(body.candidates) || body.candidates.length < 1
    || body.candidates.length > MAX_CANDIDATES) return null;
  const seen = new Set();
  for (const candidate of body.candidates) {
    if (!exactKeys(candidate, ["passage_id", "text_sha256", "text"])) return null;
    if (typeof candidate.passage_id !== "string" || seen.has(candidate.passage_id)) return null;
    if (typeof candidate.text !== "string" || candidate.text.length < 1
      || candidate.text.length > MAX_PASSAGE_CHARS) return null;
    const allowedHash = PASSAGE_HASHES.get(candidate.passage_id);
    if (!allowedHash || candidate.text_sha256 !== allowedHash) return null;
    seen.add(candidate.passage_id);
  }
  const hashes = await Promise.all(body.candidates.map(candidate => sha256Hex(candidate.text)));
  if (hashes.some((hash, index) => hash !== body.candidates[index].text_sha256)) return null;
  return { query, candidates: body.candidates };
}

async function validateJudgeInput(body) {
  if (!exactKeys(body, ["query", "results"])) return null;
  const query = cleanQuery(body.query);
  if (!query || !Array.isArray(body.results) || body.results.length < 1 || body.results.length > 10) return null;
  const seen = new Set();
  for (const result of body.results) {
    if (!exactKeys(result, ["id", "title", "passage", "field", "type"])) return null;
    if (typeof result.id !== "string" || !result.id || result.id.length > 200 || seen.has(result.id)) return null;
    if (typeof result.title !== "string" || !result.title || result.title.length > 500) return null;
    if (typeof result.passage !== "string" || !result.passage || result.passage.length > MAX_PASSAGE_CHARS) return null;
    if (!JUDGE_FIELDS.has(result.field) || !JUDGE_TYPES.has(result.type)) return null;
    seen.add(result.id);
  }
  const hashes = await Promise.all(body.results.map(result => sha256Hex(result.passage)));
  if (hashes.some((hash, index) => {
    const result = body.results[index];
    const refs = PASSAGE_REFS_BY_HASH.get(hash) || [];
    const exactPublicPassage = refs.some(ref => (
      ref.parent_id === result.id && ref.passage_kind === result.type
    ));
    const exactPublicTitle = parentTitleFromPassage(result.passage) === result.title;
    const fieldLabel = JUDGE_FIELD_LABELS.get(result.field);
    const fieldPresent = result.passage.startsWith(`${fieldLabel}: `)
      || result.passage.includes(` ${fieldLabel}: `);
    return !exactPublicPassage || !exactPublicTitle || !fieldPresent;
  })) return null;
  return { query, results: body.results };
}

function validateJudgeOutput(payload, expectedIds) {
  const response = payload?.response ?? payload;
  let parsed = response;
  if (typeof response === "string") {
    try {
      parsed = JSON.parse(response);
    } catch {
      return null;
    }
  }
  if (!exactKeys(parsed, ["results"]) || !Array.isArray(parsed.results)
    || parsed.results.length !== expectedIds.length) return null;
  const seen = new Set();
  for (const result of parsed.results) {
    if (!exactKeys(result, ["id", "classification"])
      || typeof result.id !== "string" || seen.has(result.id)
      || !JUDGE_CLASSIFICATIONS.has(result.classification)) return null;
    seen.add(result.id);
  }
  if (expectedIds.some(id => !seen.has(id))) return null;
  return parsed.results;
}

function parentTitleFromPassage(passage) {
  const prefix = "Parent title: ";
  if (!passage.startsWith(prefix)) return "";
  const rest = passage.slice(prefix.length);
  const boundaries = [
    " Publication-eligible child title: ",
    " Authoritative program area: ",
    " Parent description: ",
    " Public source evidence: ",
    " Child summary: ",
  ].map(marker => rest.indexOf(marker)).filter(index => index >= 0);
  return rest.slice(0, boundaries.length ? Math.min(...boundaries) : rest.length);
}

async function withTimeout(operation, milliseconds) {
  let timer;
  try {
    return await Promise.race([
      operation,
      new Promise((_resolve, reject) => {
        timer = setTimeout(() => reject(Object.assign(
          new Error("judge timeout"),
          { status: 504, code: "judge_timeout" },
        )), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export function createHandler({ fetchImpl = fetch, judgeTimeoutMs = JUDGE_TIMEOUT_MS } = {}) {
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
        const validated = await validateCandidates(body);
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
      if (path === "/judge") {
        if (!env?.AI?.run) return error(origin, 503, "judge_unconfigured");
        const validated = await validateJudgeInput(body);
        if (!validated) return error(origin, 400, "invalid_judge_request");
        const started = performance.now();
        let result;
        try {
          result = await withTimeout(env.AI.run(JUDGE_MODEL, {
            messages: [
              { role: "system", content: JUDGE_SYSTEM_PROMPT },
              { role: "user", content: JSON.stringify(validated) },
            ],
            response_format: {
              type: "json_schema",
              json_schema: JUDGE_SCHEMA,
            },
            max_tokens: 600,
          }), Math.max(250, Number(judgeTimeoutMs) || JUDGE_TIMEOUT_MS));
        } catch (cause) {
          if (cause?.code === "judge_timeout") throw cause;
          throw Object.assign(new Error("judge unavailable"), { status: 503, code: "judge_unavailable" });
        }
        const classifications = validateJudgeOutput(result, validated.results.map(item => item.id));
        if (!classifications) return error(origin, 502, "judge_invalid_response");
        const usage = result?.usage || {};
        return json(origin, 200, {
          model: JUDGE_MODEL,
          results: classifications,
          usage: {
            input_tokens: Number(usage.prompt_tokens || usage.input_tokens || 0),
            output_tokens: Number(usage.completion_tokens || usage.output_tokens || 0),
            total_tokens: Number(usage.total_tokens || 0),
            neurons: Number(usage.neurons || 0),
          },
          latency_ms: Number((performance.now() - started).toFixed(3)),
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
