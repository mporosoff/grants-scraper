import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  BENCHMARK_CASES,
  PRODUCTION_PROMPTS,
  gradeBenchmarkOutput,
} from "../../evaluation/ai-model-benchmark-v1.mjs";
import {
  BENCHMARK_MODELS,
  BENCHMARK_MAX_ATTEMPTS,
  BENCHMARK_MAX_OUTPUT_TOKENS,
  BENCHMARK_RETRY_INSTRUCTIONS,
  createHandler,
} from "../../workers/ai-benchmark/src/index.js";
import { validateOperationUser } from "../../workers/ai-gateway/src/input-policy.js";
import {
  BENCHMARK_PROVIDER_OVERHEAD_TOKEN_CEILING,
  BENCHMARK_WORKER_TIMEOUT_MS,
  benchmarkFailureRecord,
  callWorker,
  estimateBenchmarkCost,
} from "../../scripts/evaluate_ai_models.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const token = "benchmark-token-for-contract-test";

function request(body, { authorization = `Bearer ${token}` } = {}) {
  return new Request("https://benchmark.example/v1/evaluate", {
    method: "POST",
    headers: {
      "Authorization": authorization,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

function validBody(overrides = {}) {
  return {
    request_id: "contract-test-1",
    operation: "institution_question_translation",
    model: "gemma",
    system: PRODUCTION_PROMPTS.institution_question_translation,
    user: JSON.stringify({ institution: "Example University", question: "How many DOE BES awards?" }),
    ...overrides,
  };
}

function validTranslation() {
  return {
    agency: "DOE",
    program: "BES",
    topic: "",
    pi: "",
    program_officer: "",
    year_start: "",
    year_end: "",
    answer_intent: "count",
    narrative_needed: false,
  };
}

function environment(overrides = {}) {
  return {
    BENCHMARK_TOKEN: token,
    OPENAI_API_KEY: "openai-test-key",
    AI: {
      async run() {
        return { response: JSON.stringify(validTranslation()), usage: { prompt_tokens: 100, completion_tokens: 40 } };
      },
    },
    BENCHMARK_RATE_LIMITER: {
      async limit() {
        return { success: true };
      },
    },
    ...overrides,
  };
}

test("benchmark covers the eight production contracts behind the five priority features", () => {
  assert.deepEqual(
    [...new Set(BENCHMARK_CASES.map(item => item.operation))].sort(),
    [
      "institution_narrative",
      "institution_question_translation",
      "notice_chat",
      "program_officer_evidence_answer",
      "program_officer_question_plan",
      "refinement_shortlist",
      "result_chat",
      "search_plan",
    ],
  );
  assert.deepEqual(
    [...new Set(BENCHMARK_CASES.map(item => item.feature))].sort(),
    ["Ask about a Program Officer snapshot", "Ask about this institution", "Chat with NOFO", "Chat with results", "Enhance with AI"],
  );
});

test("every benchmark fixture is accepted by its production gateway input contract", () => {
  for (const testCase of BENCHMARK_CASES) {
    assert.deepEqual(
      validateOperationUser(testCase.operation, testCase.user),
      JSON.parse(testCase.user),
      `${testCase.id} must use the live browser payload shape`,
    );
  }
});

test("benchmark prompt copies remain pinned to the production call sites", async () => {
  const app = (await readFile(path.join(root, "assets", "app.js"), "utf8")).replaceAll('\\"', '"');
  const institution = (await readFile(path.join(root, "assets", "institutional-intelligence.js"), "utf8")).replaceAll('\\"', '"');
  const snapshots = (await readFile(path.join(root, "assets", "institutional-intelligence-snapshots.js"), "utf8")).replaceAll('\\"', '"');
  assert.ok(app.includes(PRODUCTION_PROMPTS.search_plan));
  assert.ok(app.includes(PRODUCTION_PROMPTS.result_chat));
  assert.ok(app.includes(PRODUCTION_PROMPTS.notice_chat));
  assert.ok(app.includes(PRODUCTION_PROMPTS.refinement_shortlist.replace("at most 12 matches", "at most ${MAX_AI_MATCHES} matches")));
  assert.ok(institution.includes(PRODUCTION_PROMPTS.institution_question_translation));
  assert.ok(institution.includes(PRODUCTION_PROMPTS.institution_narrative));
  assert.ok(snapshots.includes(PRODUCTION_PROMPTS.program_officer_question_plan));
  assert.ok(snapshots.includes(PRODUCTION_PROMPTS.program_officer_evidence_answer));
});

test("private endpoint fails closed when the token is absent or wrong", async () => {
  const handler = createHandler();
  const absentSecret = await handler(request(validBody(), { authorization: "Bearer " }), environment({ BENCHMARK_TOKEN: "" }));
  assert.equal(absentSecret.status, 401);
  const wrong = await handler(request(validBody(), { authorization: "Bearer wrong" }), environment());
  assert.equal(wrong.status, 401);
  assert.equal((await wrong.json()).error.code, "unauthorized");
});

test("Gemma uses the exact Cloudflare model, disables thinking, and receives the canonical schema", async () => {
  let captured;
  const env = environment({
    AI: {
      async run(model, options) {
        captured = { model, options };
        return { response: validTranslation(), usage: { prompt_tokens: 120, completion_tokens: 30, total_tokens: 150 } };
      },
    },
  });
  const response = await createHandler()(request(validBody()), env);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.model_id, BENCHMARK_MODELS.gemma);
  assert.equal(body.attempts, 1);
  assert.deepEqual(body.output, validTranslation());
  assert.equal(captured.model, "@cf/google/gemma-4-26b-a4b-it");
  assert.deepEqual(captured.options.chat_template_kwargs, { enable_thinking: false });
  assert.equal(captured.options.response_format.type, "json_schema");
  assert.equal(captured.options.response_format.json_schema.additionalProperties, false);
  assert.equal(captured.options.store, false);
});

test("provider-facing phrase schemas omit unsupported uniqueness while canonical validation retains it", async () => {
  let captured;
  const output = {
    interpretation: "Catalysis pathways",
    search_terms: ["term one", "term two", "term three", "term four", "term five"],
    avoid_terms: [],
  };
  const env = environment({
    AI: {
      async run(_model, options) {
        captured = options;
        return { response: output };
      },
    },
  });
  const response = await createHandler()(request(validBody({
    operation: "search_plan",
    system: PRODUCTION_PROMPTS.search_plan,
    user: JSON.stringify({ topic: "catalysis" }),
  })), env);
  assert.equal(response.status, 200);
  assert.equal(captured.response_format.json_schema.properties.search_terms.uniqueItems, undefined);
  assert.match(captured.response_format.json_schema.properties.search_terms.description, /Items must be unique/);
});

test("Gemma receives one bounded retry after invalid structured output", async () => {
  let attempts = 0;
  const env = environment({
    AI: {
      async run() {
        attempts += 1;
        return attempts === 1
          ? {
              response: JSON.stringify({ agency: "DOE" }),
              usage: { prompt_tokens: 80, completion_tokens: 10, total_tokens: 90 },
            }
          : {
              response: JSON.stringify(validTranslation()),
              usage: { prompt_tokens: 120, completion_tokens: 30, total_tokens: 150 },
            };
      },
    },
  });
  const response = await createHandler()(request(validBody()), env);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.attempts, 2);
  assert.deepEqual(body.usage, { input_tokens: 200, output_tokens: 40, total_tokens: 240 });
  assert.equal(attempts, 2);
});

test("Luna retry usage includes a billed malformed first response", async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts += 1;
    const body = attempts === 1
      ? {
          status: "completed",
          output: [],
          usage: { input_tokens: 90, output_tokens: 5, total_tokens: 95 },
        }
      : {
          status: "completed",
          output: [{
            type: "message",
            status: "completed",
            role: "assistant",
            content: [{ type: "output_text", text: JSON.stringify(validTranslation()) }],
          }],
          usage: { input_tokens: 110, output_tokens: 25, total_tokens: 135 },
        };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const response = await createHandler()(request(validBody({ model: "luna" })), environment());
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.attempts, 2);
    assert.deepEqual(body.usage, { input_tokens: 200, output_tokens: 30, total_tokens: 230 });
    assert.equal(attempts, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("terminal schema failures return every billed attempt for checkpoint evidence", async () => {
  let attempts = 0;
  const env = environment({
    AI: {
      async run() {
        attempts += 1;
        return {
          response: JSON.stringify({ agency: "DOE" }),
          usage: { prompt_tokens: 70, completion_tokens: 10, total_tokens: 80 },
        };
      },
    },
  });
  const response = await createHandler()(request(validBody()), env);
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "schema_validation_failed");
  assert.equal(body.attempts, 2);
  assert.deepEqual(body.usage, { input_tokens: 140, output_tokens: 20, total_tokens: 160 });
  assert.equal(attempts, 2);
});

test("Luna request matches the production Responses API contract and does not enable storage", async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options, body: JSON.parse(options.body) };
    return new Response(JSON.stringify({
      status: "completed",
      output: [{
        type: "message",
        status: "completed",
        role: "assistant",
        content: [{ type: "output_text", text: JSON.stringify(validTranslation()) }],
      }],
      usage: { input_tokens: 110, output_tokens: 25, total_tokens: 135 },
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    const response = await createHandler()(request(validBody({ model: "luna" })), environment());
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.model_id, BENCHMARK_MODELS.luna);
    assert.equal(captured.url, "https://api.openai.com/v1/responses");
    assert.equal(captured.body.model, "gpt-5.6-luna");
    assert.deepEqual(captured.body.reasoning, { effort: "low" });
    assert.equal(captured.body.text.verbosity, "low");
    assert.equal(captured.body.text.format.type, "json_schema");
    assert.equal(captured.body.text.format.strict, true);
    assert.equal(captured.body.max_output_tokens, 5000);
    assert.equal(captured.body.store, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("the Worker rejects unknown fields and rate-limits before calling a provider", async () => {
  let called = false;
  const env = environment({
    AI: { async run() { called = true; } },
    BENCHMARK_RATE_LIMITER: { async limit() { return { success: false }; } },
  });
  const unknownField = await createHandler()(request(validBody({ secret: "do not accept" })), env);
  assert.equal(unknownField.status, 400);
  assert.equal((await unknownField.json()).error.code, "invalid_request_shape");
  const limited = await createHandler()(request(validBody()), env);
  assert.equal(limited.status, 429);
  assert.equal(called, false);

  const missingBinding = environment();
  delete missingBinding.BENCHMARK_RATE_LIMITER;
  const unavailable = await createHandler()(request(validBody()), missingBinding);
  assert.equal(unavailable.status, 503);
  assert.equal((await unavailable.json()).error.code, "rate_limit_not_configured");
});

test("automated grading detects unsupported citations and deterministic translation drift", () => {
  const narrativeCase = BENCHMARK_CASES.find(item => item.id === "institution-narrative-bounded-evidence");
  const narrativeGrade = gradeBenchmarkOutput(narrativeCase, {
    claims: [{ text: "Catalysis theme", evidence_ids: ["DOE:INVENTED"] }],
  });
  assert.equal(narrativeGrade.passed, false);
  assert.ok(narrativeGrade.problems.includes("unknown_evidence_id:DOE:INVENTED"));

  const translationCase = BENCHMARK_CASES.find(item => item.id === "institution-translate-bes-count");
  const translationGrade = gradeBenchmarkOutput(translationCase, {
    ...validTranslation(),
    agency: "NIH",
    program: "R01",
    year_start: "2021",
    year_end: "2025",
  });
  assert.equal(translationGrade.passed, false);
  assert.ok(translationGrade.problems.some(problem => problem.startsWith("field_mismatch:agency")));

  const refinementCase = BENCHMARK_CASES.find(item => item.id === "enhance-candidate-assessment");
  const ineligibleGrade = gradeBenchmarkOutput(refinementCase, {
    matches: [{ id: "GRAD-FELLOWSHIP-02", verdict: "Possible fit" }],
  });
  assert.equal(ineligibleGrade.passed, false);
  assert.ok(ineligibleGrade.problems.includes("ineligible_result_id:GRAD-FELLOWSHIP-02"));
});

test("bounded cost estimate uses a conservative byte ceiling across retries", () => {
  const estimate = estimateBenchmarkCost(
    { models: ["luna"], runs: 1 },
    [BENCHMARK_CASES[0]],
  );
  const luna = estimate.by_model.luna;
  assert.equal(BENCHMARK_MAX_ATTEMPTS, 2);
  assert.equal(estimate.calls, 1);
  assert.equal(estimate.bounded_maximum_provider_calls, 2);
  assert.equal(luna.bounded_maximum_provider_calls, 2);
  assert.ok(luna.bounded_maximum_input_tokens > luna.estimated_input_tokens * 2);
  const testCase = BENCHMARK_CASES[0];
  const schema = JSON.stringify(globalThis.FUNDING_AI.STRUCTURED_OPERATIONS[testCase.operation]);
  const firstAttemptBytes = Buffer.byteLength(testCase.system, "utf8")
    + Buffer.byteLength(testCase.user, "utf8")
    + Buffer.byteLength(schema, "utf8");
  const retryAttemptBytes = firstAttemptBytes
    + Buffer.byteLength(BENCHMARK_RETRY_INSTRUCTIONS.luna, "utf8");
  assert.equal(
    luna.bounded_maximum_input_tokens,
    firstAttemptBytes + retryAttemptBytes + BENCHMARK_PROVIDER_OVERHEAD_TOKEN_CEILING * 2,
  );
  assert.equal(
    luna.bounded_maximum_output_tokens,
    BENCHMARK_MAX_OUTPUT_TOKENS * BENCHMARK_MAX_ATTEMPTS,
  );
});

test("the runner timeout covers stalled benchmark response bodies", async () => {
  let signal;
  const fetchImpl = async (_url, options) => {
    signal = options.signal;
    return {
      ok: true,
      status: 200,
      json: () => new Promise((_, reject) => {
        signal.addEventListener("abort", () => reject(new Error("body stalled")), { once: true });
      }),
    };
  };
  const testCase = BENCHMARK_CASES.find(item => item.id === "institution-translate-bes-count");
  await assert.rejects(
    callWorker(
      { endpoint: "https://benchmark.example", token },
      { testCase, run: 1, model: "gemma" },
      { fetchImpl, timeoutMs: 10 },
    ),
    /Benchmark Worker request timed out after 10 ms/,
  );
  assert.equal(signal.aborted, true);
  assert.equal(BENCHMARK_WORKER_TIMEOUT_MS, 75_000);
});

test("one provider timeout is recorded as evidence without invalidating other benchmark jobs", () => {
  const testCase = BENCHMARK_CASES.find(item => item.id === "nofo-chat-conflicting-deadline");
  const record = benchmarkFailureRecord(
    { testCase, run: 2, model: "gemma" },
    new Error("Worker HTTP 504: provider_timeout"),
  );
  assert.equal(record.id, "ai-model-benchmark-v2:nofo-chat-conflicting-deadline:r2:gemma");
  assert.equal(record.model_id, "@cf/google/gemma-4-26b-a4b-it");
  assert.deepEqual(record.error, { code: "Worker HTTP 504: provider_timeout" });
  assert.deepEqual(record.automated_grade, { passed: false, problems: ["provider_call_failed"] });
});

test("the runner preserves terminal Worker attempts and usage in its failure record", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    error: { code: "schema_validation_failed" },
    attempts: 2,
    usage: { input_tokens: 140, output_tokens: 20, total_tokens: 160 },
  }), { status: 502, headers: { "Content-Type": "application/json" } });
  const testCase = BENCHMARK_CASES.find(item => item.id === "institution-translate-bes-count");
  const job = { testCase, run: 1, model: "gemma" };
  try {
    await assert.rejects(
      callWorker({ endpoint: "https://benchmark.example", token }, job),
      error => {
        const record = benchmarkFailureRecord(job, error);
        assert.equal(record.attempts, 2);
        assert.deepEqual(record.usage, {
          input_tokens: 140,
          output_tokens: 20,
          total_tokens: 160,
        });
        assert.deepEqual(record.error, { code: "Worker HTTP 502: schema_validation_failed" });
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
