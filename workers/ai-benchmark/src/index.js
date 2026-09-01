import "../../../assets/ai-provider.js";

const {
  STRUCTURED_OPERATIONS,
  validateStructuredValue,
  extractJson,
  openAIResponseText,
  schemaForProvider,
} = globalThis.FUNDING_AI;

export const BENCHMARK_MODELS = Object.freeze({
  luna: "gpt-5.6-luna",
  gemma: "@cf/google/gemma-4-26b-a4b-it",
});

const MAX_BODY_BYTES = 900_000;
const MAX_SYSTEM_CHARS = 12_000;
const MAX_USER_CHARS = 750_000;
export const BENCHMARK_MAX_OUTPUT_TOKENS = 5_000;
const REQUEST_TIMEOUT_MS = 60_000;
export const BENCHMARK_MAX_ATTEMPTS = 2;
export const BENCHMARK_RETRY_INSTRUCTIONS = Object.freeze({
  luna: "\n\nReturn a smaller complete response that still matches the supplied schema. Shorten prose and include fewer optional list items.",
  gemma: "\n\nReturn a smaller complete response that still matches the supplied JSON schema.",
});
const REQUEST_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;

class BenchmarkError extends Error {
  constructor(code, status = 400, { retryable = false } = {}) {
    super(code);
    this.name = "BenchmarkError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function jsonResponse(value, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders,
    },
  });
}

function errorResponse(error) {
  const known = error instanceof BenchmarkError;
  return jsonResponse(
    { error: { code: known ? error.code : "provider_unavailable" } },
    known ? error.status : 502,
  );
}

function secureEqual(left, right) {
  const leftBytes = new TextEncoder().encode(String(left || ""));
  const rightBytes = new TextEncoder().encode(String(right || ""));
  if (!leftBytes.length || leftBytes.length !== rightBytes.length) return false;
  let difference = 0;
  for (let index = 0; index < leftBytes.length; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

function authorized(request, env) {
  const header = request.headers.get("Authorization") || "";
  const token = String(env.BENCHMARK_TOKEN || "").trim();
  return Boolean(token) && secureEqual(header, `Bearer ${token}`);
}

function exactKeys(value, allowed) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value).sort();
  return keys.length === allowed.length && keys.every((key, index) => key === [...allowed].sort()[index]);
}

function cleanRequest(value) {
  const allowed = ["model", "operation", "request_id", "system", "user"];
  if (!exactKeys(value, allowed)) throw new BenchmarkError("invalid_request_shape");
  const requestId = String(value.request_id || "").trim();
  const model = String(value.model || "").trim();
  const operation = String(value.operation || "").trim();
  const system = String(value.system || "");
  const user = String(value.user || "");
  if (!REQUEST_ID_PATTERN.test(requestId)) throw new BenchmarkError("invalid_request_id");
  if (!Object.prototype.hasOwnProperty.call(BENCHMARK_MODELS, model)) {
    throw new BenchmarkError("unsupported_model");
  }
  if (!Object.prototype.hasOwnProperty.call(STRUCTURED_OPERATIONS, operation)) {
    throw new BenchmarkError("unsupported_operation");
  }
  if (!system.trim() || system.length > MAX_SYSTEM_CHARS) throw new BenchmarkError("invalid_system");
  if (!user.trim() || user.length > MAX_USER_CHARS) throw new BenchmarkError("invalid_user");
  return { requestId, model, operation, system, user };
}

async function jsonBounded(response) {
  try {
    return await response.json();
  } catch {
    throw new BenchmarkError("malformed_provider_response", 502, { retryable: true });
  }
}

async function withTimeout(task, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      task(controller.signal),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          controller.abort();
          reject(new BenchmarkError("provider_timeout", 504));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function normalizeUsage(value) {
  const usage = value?.usage || value?.result?.usage || {};
  const input = Number(usage.input_tokens ?? usage.prompt_tokens ?? 0);
  const output = Number(usage.output_tokens ?? usage.completion_tokens ?? 0);
  const total = Number(usage.total_tokens ?? input + output);
  return {
    input_tokens: Number.isFinite(input) ? input : 0,
    output_tokens: Number.isFinite(output) ? output : 0,
    total_tokens: Number.isFinite(total) ? total : 0,
  };
}

function cloudflareResponseText(value) {
  const candidate = value?.response ?? value?.result?.response;
  if (typeof candidate === "string" && candidate.trim()) return candidate;
  if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
    return JSON.stringify(candidate);
  }
  const choice = value?.choices?.[0]?.message?.content;
  if (typeof choice === "string" && choice.trim()) return choice;
  throw new BenchmarkError("malformed_provider_response", 502, { retryable: true });
}

async function requestLuna({ env, system, user, contract, attempt }) {
  if (!String(env.OPENAI_API_KEY || "").trim()) throw new BenchmarkError("openai_not_configured", 503);
  const retryInstruction = attempt ? BENCHMARK_RETRY_INSTRUCTIONS.luna : "";
  return withTimeout(async signal => {
    const response = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: BENCHMARK_MODELS.luna,
        instructions: `${system}${retryInstruction}`,
        input: user,
        reasoning: { effort: "low" },
        text: {
          verbosity: "low",
          format: {
            type: "json_schema",
            name: contract.name,
            description: contract.description,
            schema: schemaForProvider(contract.schema, "openai"),
            strict: true,
          },
        },
        max_output_tokens: BENCHMARK_MAX_OUTPUT_TOKENS,
        store: false,
      }),
    });
    const data = await jsonBounded(response);
    if (!response.ok) {
      const status = response.status === 429 ? 429 : response.status >= 500 ? 502 : 400;
      throw new BenchmarkError(response.status === 429 ? "provider_rate_limited" : "provider_rejected", status);
    }
    let text;
    try {
      text = openAIResponseText(data);
    } catch (error) {
      throw new BenchmarkError(error?.category === "incomplete" ? "incomplete_provider_response" : "malformed_provider_response", 502, {
        retryable: error?.retryable === true,
      });
    }
    return { text, usage: normalizeUsage(data) };
  });
}

async function requestGemma({ env, system, user, contract, attempt }) {
  if (!env.AI?.run) throw new BenchmarkError("workers_ai_not_configured", 503);
  const retryInstruction = attempt ? BENCHMARK_RETRY_INSTRUCTIONS.gemma : "";
  let data;
  try {
    data = await withTimeout(() => env.AI.run(BENCHMARK_MODELS.gemma, {
      messages: [
        { role: "system", content: `${system}${retryInstruction}` },
        { role: "user", content: user },
      ],
      chat_template_kwargs: { enable_thinking: false },
      response_format: {
        type: "json_schema",
        json_schema: schemaForProvider(contract.schema, "openai"),
      },
      max_completion_tokens: BENCHMARK_MAX_OUTPUT_TOKENS,
      store: false,
    }));
  } catch (error) {
    if (error instanceof BenchmarkError) throw error;
    throw new BenchmarkError("provider_unavailable", 502);
  }
  return { text: cloudflareResponseText(data), usage: normalizeUsage(data) };
}

async function runModel(clean, env) {
  const contract = STRUCTURED_OPERATIONS[clean.operation];
  const startedAt = Date.now();
  let lastError;
  for (let attempt = 0; attempt < BENCHMARK_MAX_ATTEMPTS; attempt += 1) {
    try {
      const provider = clean.model === "luna" ? requestLuna : requestGemma;
      const result = await provider({ env, ...clean, contract, attempt });
      let output;
      try {
        output = validateStructuredValue(extractJson(result.text), contract.schema);
      } catch {
        throw new BenchmarkError("schema_validation_failed", 502, { retryable: true });
      }
      return {
        request_id: clean.requestId,
        operation: clean.operation,
        model: clean.model,
        model_id: BENCHMARK_MODELS[clean.model],
        attempts: attempt + 1,
        latency_ms: Date.now() - startedAt,
        usage: result.usage,
        output,
      };
    } catch (error) {
      lastError = error;
      if (!(error instanceof BenchmarkError) || !error.retryable || attempt + 1 >= BENCHMARK_MAX_ATTEMPTS) break;
    }
  }
  throw lastError;
}

async function applyRateLimit(env) {
  if (!env.BENCHMARK_RATE_LIMITER?.limit) throw new BenchmarkError("rate_limit_not_configured", 503);
  const result = await env.BENCHMARK_RATE_LIMITER.limit({ key: "private-benchmark" });
  if (!result?.success) throw new BenchmarkError("rate_limited", 429);
}

export function createHandler() {
  return async function handle(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      if (!authorized(request, env)) return errorResponse(new BenchmarkError("unauthorized", 401));
      return jsonResponse({
        service: "funding-finder-ai-benchmark",
        models: BENCHMARK_MODELS,
        operations: Object.keys(STRUCTURED_OPERATIONS),
        openai_configured: Boolean(String(env.OPENAI_API_KEY || "").trim()),
        workers_ai_configured: Boolean(env.AI?.run),
      });
    }
    if (url.pathname !== "/v1/evaluate" || request.method !== "POST") {
      return errorResponse(new BenchmarkError("not_found", 404));
    }
    if (!authorized(request, env)) return errorResponse(new BenchmarkError("unauthorized", 401));
    const contentLength = Number(request.headers.get("Content-Length") || 0);
    if (contentLength > MAX_BODY_BYTES) return errorResponse(new BenchmarkError("request_too_large", 413));
    try {
      const text = await request.text();
      if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) throw new BenchmarkError("request_too_large", 413);
      let body;
      try {
        body = JSON.parse(text);
      } catch {
        throw new BenchmarkError("invalid_json");
      }
      const clean = cleanRequest(body);
      await applyRateLimit(env);
      return jsonResponse(await runModel(clean, env));
    } catch (error) {
      return errorResponse(error);
    }
  };
}

export default { fetch: createHandler() };
