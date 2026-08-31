import "../../../assets/ai-provider.js";
import { PRODUCTION_PROMPTS } from "../../../assets/ai-prompts.mjs";

const {
  STRUCTURED_OPERATIONS,
  validateStructuredValue,
  extractJson,
  openAIResponseText,
  schemaForProvider,
} = globalThis.FUNDING_AI;

export const HOSTED_MODELS = Object.freeze({
  luna: "gpt-5.6-luna",
  gemma: "@cf/google/gemma-4-26b-a4b-it",
});

export const OPERATION_ROUTES = Object.freeze({
  search_plan: Object.freeze(["gemma"]),
  refinement_shortlist: Object.freeze(["luna"]),
  result_chat: Object.freeze(["luna"]),
  notice_chat: Object.freeze(["luna", "gemma"]),
  institution_question_translation: Object.freeze(["gemma"]),
  institution_narrative: Object.freeze(["luna"]),
});

const MAX_BODY_BYTES = 300_000;
const MAX_USER_CHARS = 180_000;
const MAX_OUTPUT_TOKENS = 5_000;
const DEFAULT_TIMEOUT_MS = 30_000;
const GEMMA_TIMEOUT_MS = 15_000;
const NOTICE_GEMMA_TIMEOUT_MS = 8_000;
const MAX_ATTEMPTS = 2;
const LOCAL_ORIGIN_PATTERN = /^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d{1,5})?$/;

class GatewayError extends Error {
  constructor(code, status = 400, { retryable = false } = {}) {
    super(code);
    this.name = "GatewayError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function allowedOrigin(origin, env) {
  const value = String(origin || "");
  if (!value) return "";
  const configured = [env.PUBLIC_APP_ORIGIN, env.PREVIEW_APP_ORIGIN]
    .map(item => String(item || "").replace(/\/$/, ""))
    .filter(Boolean);
  if (configured.includes(value) || LOCAL_ORIGIN_PATTERN.test(value)) return value;
  return "";
}

function responseHeaders(origin = "") {
  return {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    ...(origin ? {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Max-Age": "600",
      "Vary": "Origin",
    } : {}),
  };
}

function jsonResponse(value, status = 200, origin = "") {
  return new Response(JSON.stringify(value), {
    status,
    headers: responseHeaders(origin),
  });
}

function errorResponse(error, origin = "") {
  const known = error instanceof GatewayError;
  return jsonResponse(
    { error: { code: known ? error.code : "provider_unavailable" } },
    known ? error.status : 502,
    origin,
  );
}

function exactKeys(value, allowed) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const expected = [...allowed].sort();
  const actual = Object.keys(value).sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function cleanRequest(value) {
  if (!exactKeys(value, ["operation", "user"])) {
    throw new GatewayError("invalid_request_shape");
  }
  const operation = String(value.operation || "").trim();
  const user = String(value.user || "");
  if (!Object.prototype.hasOwnProperty.call(OPERATION_ROUTES, operation)
      || !Object.prototype.hasOwnProperty.call(STRUCTURED_OPERATIONS, operation)
      || !Object.prototype.hasOwnProperty.call(PRODUCTION_PROMPTS, operation)) {
    throw new GatewayError("unsupported_operation");
  }
  if (!user.trim() || user.length > MAX_USER_CHARS) {
    throw new GatewayError("invalid_user");
  }
  return { operation, user };
}

async function jsonBounded(response) {
  try {
    return await response.json();
  } catch {
    throw new GatewayError("malformed_provider_response", 502, { retryable: true });
  }
}

async function withTimeout(task, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      task(controller.signal),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          controller.abort();
          reject(new GatewayError("provider_timeout", 504));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function cloudflareResponseText(value) {
  const candidate = value?.response ?? value?.result?.response;
  if (typeof candidate === "string" && candidate.trim()) return candidate;
  if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
    return JSON.stringify(candidate);
  }
  const choice = value?.choices?.[0]?.message?.content;
  if (typeof choice === "string" && choice.trim()) return choice;
  throw new GatewayError("malformed_provider_response", 502, { retryable: true });
}

async function requestLuna({ env, system, user, contract, attempt }) {
  if (!String(env.OPENAI_API_KEY || "").trim()) {
    throw new GatewayError("openai_not_configured", 503);
  }
  const retryInstruction = attempt
    ? "\n\nReturn a smaller complete response that still matches the supplied schema. Shorten prose and include fewer optional list items."
    : "";
  return withTimeout(async signal => {
    const response = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${env.OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: HOSTED_MODELS.luna,
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
        max_output_tokens: MAX_OUTPUT_TOKENS,
        store: false,
      }),
    });
    const data = await jsonBounded(response);
    if (!response.ok) {
      if (response.status === 429) throw new GatewayError("provider_rate_limited", 429);
      if (response.status >= 500) throw new GatewayError("provider_unavailable", 502);
      throw new GatewayError("provider_rejected", 400);
    }
    try {
      return openAIResponseText(data);
    } catch (error) {
      throw new GatewayError(
        error?.category === "incomplete"
          ? "incomplete_provider_response"
          : "malformed_provider_response",
        502,
        { retryable: error?.retryable === true },
      );
    }
  });
}

async function requestGemma({ env, system, user, contract, attempt, operation }) {
  if (!env.AI?.run) throw new GatewayError("workers_ai_not_configured", 503);
  const retryInstruction = attempt
    ? "\n\nReturn a smaller complete response that still matches the supplied JSON schema."
    : "";
  const timeoutMs = operation === "notice_chat"
    ? NOTICE_GEMMA_TIMEOUT_MS
    : GEMMA_TIMEOUT_MS;
  try {
    const data = await withTimeout(() => env.AI.run(HOSTED_MODELS.gemma, {
      messages: [
        { role: "system", content: `${system}${retryInstruction}` },
        { role: "user", content: user },
      ],
      chat_template_kwargs: { enable_thinking: false },
      response_format: {
        type: "json_schema",
        json_schema: schemaForProvider(contract.schema, "openai"),
      },
      max_completion_tokens: MAX_OUTPUT_TOKENS,
      store: false,
    }), timeoutMs);
    return cloudflareResponseText(data);
  } catch (error) {
    if (error instanceof GatewayError) throw error;
    throw new GatewayError("provider_unavailable", 502);
  }
}

async function runModel(model, clean, env) {
  const contract = STRUCTURED_OPERATIONS[clean.operation];
  const system = PRODUCTION_PROMPTS[clean.operation];
  let lastError;
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
    try {
      const request = model === "luna" ? requestLuna : requestGemma;
      const text = await request({ env, ...clean, system, contract, attempt });
      try {
        return validateStructuredValue(extractJson(text), contract.schema);
      } catch {
        throw new GatewayError("schema_validation_failed", 502, { retryable: true });
      }
    } catch (error) {
      lastError = error;
      if (!(error instanceof GatewayError)
          || !error.retryable
          || attempt + 1 >= MAX_ATTEMPTS) break;
    }
  }
  throw lastError;
}

async function runRouted(clean, env) {
  const routes = OPERATION_ROUTES[clean.operation];
  let lastError;
  for (let index = 0; index < routes.length; index += 1) {
    const model = routes[index];
    try {
      return {
        output: await runModel(model, clean, env),
        route: {
          model,
          model_id: HOSTED_MODELS[model],
          fallback_used: index > 0,
        },
      };
    } catch (error) {
      lastError = error;
      if (index + 1 >= routes.length) break;
    }
  }
  throw lastError;
}

async function applyRateLimits(request, env) {
  if (!env.AI_CLIENT_RATE_LIMITER?.limit || !env.AI_GLOBAL_RATE_LIMITER?.limit) {
    throw new GatewayError("rate_limit_not_configured", 503);
  }
  const clientKey = String(request.headers.get("CF-Connecting-IP") || "unknown").slice(0, 80);
  const [client, global] = await Promise.all([
    env.AI_CLIENT_RATE_LIMITER.limit({ key: clientKey }),
    env.AI_GLOBAL_RATE_LIMITER.limit({ key: "funding-finder-ai" }),
  ]);
  if (!client?.success || !global?.success) throw new GatewayError("rate_limited", 429);
}

export function createHandler() {
  return async function handle(request, env) {
    const url = new URL(request.url);
    const requestOrigin = request.headers.get("Origin") || "";
    const origin = allowedOrigin(requestOrigin, env);

    if (request.method === "OPTIONS") {
      if (!origin) return errorResponse(new GatewayError("origin_not_allowed", 403));
      return new Response(null, { status: 204, headers: responseHeaders(origin) });
    }

    if (url.pathname === "/health" && request.method === "GET") {
      return jsonResponse({
        service: "funding-finder-ai",
        operations: Object.keys(OPERATION_ROUTES),
        openai_configured: Boolean(String(env.OPENAI_API_KEY || "").trim()),
        workers_ai_configured: Boolean(env.AI?.run),
      }, 200, origin);
    }

    if (url.pathname !== "/v1/structured" || request.method !== "POST") {
      return errorResponse(new GatewayError("not_found", 404), origin);
    }
    if (!origin) return errorResponse(new GatewayError("origin_not_allowed", 403));

    const contentLength = Number(request.headers.get("Content-Length") || 0);
    if (contentLength > MAX_BODY_BYTES) {
      return errorResponse(new GatewayError("request_too_large", 413), origin);
    }

    try {
      const text = await request.text();
      if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) {
        throw new GatewayError("request_too_large", 413);
      }
      let body;
      try {
        body = JSON.parse(text);
      } catch {
        throw new GatewayError("invalid_json");
      }
      const clean = cleanRequest(body);
      await applyRateLimits(request, env);
      return jsonResponse(await runRouted(clean, env), 200, origin);
    } catch (error) {
      return errorResponse(error, origin);
    }
  };
}

export default { fetch: createHandler() };
