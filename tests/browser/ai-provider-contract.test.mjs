import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../", import.meta.url);

async function loadProvider() {
  const source = await readFile(new URL("../assets/ai-provider.js", root), "utf8");
  const context = { console };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: "ai-provider.js" });
  return context.FUNDING_AI;
}

function jsonResponse(payload, { ok = true, status = 200, text = "" } = {}) {
  return {
    ok,
    status,
    async json() {
      return payload;
    },
    async text() {
      return text;
    },
  };
}

test("OpenAI adapter sends a bounded, non-persisted Responses request", async () => {
  const provider = await loadProvider();
  let request;
  const result = await provider.providerJson({
    provider: "openai",
    key: "  test-openai-key  ",
    system: "Return JSON.",
    user: "Rank these opportunities.",
    fetchImpl: async (url, options) => {
      request = { url, options };
      return jsonResponse({ output_text: '```json\n{"matches":["123"]}\n```' });
    },
  });

  const body = JSON.parse(request.options.body);
  assert.equal(request.url, "https://api.openai.com/v1/responses");
  assert.equal(request.options.headers.Authorization, "Bearer test-openai-key");
  assert.equal(body.model, provider.OPENAI_MODEL);
  assert.equal(body.store, false);
  assert.equal(body.instructions, "Return JSON.");
  assert.equal(body.input, "Rank these opportunities.");
  assert.equal(body.max_output_tokens, 5000);
  assert.equal(JSON.stringify(result), '{"matches":["123"]}');
});

test("Anthropic adapter sends the direct-browser Messages contract", async () => {
  const provider = await loadProvider();
  let request;
  const result = await provider.providerJson({
    provider: "anthropic",
    key: "test-anthropic-key",
    system: "Return JSON.",
    user: "Answer from these results.",
    fetchImpl: async (url, options) => {
      request = { url, options };
      return jsonResponse({
        content: [{ type: "text", text: 'Result: {"answer":"Use the official FOA."}' }],
      });
    },
  });

  const body = JSON.parse(request.options.body);
  assert.equal(request.url, "https://api.anthropic.com/v1/messages");
  assert.equal(request.options.headers["x-api-key"], "test-anthropic-key");
  assert.equal(
    request.options.headers["anthropic-dangerous-direct-browser-access"],
    "true",
  );
  assert.equal(body.model, provider.ANTHROPIC_MODEL);
  assert.equal(body.max_tokens, 5000);
  assert.deepEqual(body.messages, [
    { role: "user", content: "Answer from these results." },
  ]);
  assert.equal(JSON.stringify(result), '{"answer":"Use the official FOA."}');
});

test("adapter rejects missing keys and reports provider failures", async () => {
  const provider = await loadProvider();
  await assert.rejects(
    provider.providerJson({
      provider: "openai",
      key: " ",
      system: "",
      user: "",
      fetchImpl: async () => jsonResponse({}),
    }),
    /Enter an API key/,
  );
  await assert.rejects(
    provider.providerJson({
      provider: "openai",
      key: "bad-key",
      system: "",
      user: "",
      fetchImpl: async () =>
        jsonResponse({}, { ok: false, status: 401, text: "invalid credential" }),
    }),
    /OpenAI request failed \(401\).*invalid credential/,
  );
});

test("retries malformed structured data once with a smaller-output instruction", async () => {
  const provider = await loadProvider();
  const requests = [];
  let retryCount = 0;
  const result = await provider.providerJson({
    provider: "openai",
    key: "test-openai-key",
    system: "Return ranked matches as JSON.",
    user: "Rank the bounded candidate set.",
    onRetry: () => {
      retryCount += 1;
    },
    fetchImpl: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return requests.length === 1
        ? jsonResponse({ output_text: '{"matches":[{"id":"A"} {"id":"B"}]}' })
        : jsonResponse({ output_text: '{"matches":[{"id":"A"}]}' });
    },
  });

  assert.equal(requests.length, 2);
  assert.equal(retryCount, 1);
  assert.match(
    requests[1].body.instructions,
    /previous response was malformed or incomplete JSON/,
  );
  assert.equal(JSON.stringify(result), '{"matches":[{"id":"A"}]}');
});

test("returns a useful error after two malformed responses", async () => {
  const provider = await loadProvider();
  let requests = 0;
  await assert.rejects(
    provider.providerJson({
      provider: "anthropic",
      key: "test-anthropic-key",
      system: "Return JSON.",
      user: "Answer from the bounded results.",
      fetchImpl: async () => {
        requests += 1;
        return jsonResponse({
          content: [{ type: "text", text: '{"answer":["unfinished"' }],
        });
      },
    }),
    /malformed structured data twice/,
  );
  assert.equal(requests, 2);
});

test("keeps only supplied citation identifiers and rejects invented ones", async () => {
  const provider = await loadProvider();
  const citations = provider.knownEvidenceCitations(
    ["evidence-valid", "evidence-invented", "evidence-valid"],
    [
      {
        evidence_id: "evidence-valid",
        label: "FOA-123 · Deadline · page 4",
        url: "https://example.test/nofo.pdf#page=4",
      },
    ],
  );

  assert.equal(citations.length, 1);
  assert.equal(citations[0].evidence_id, "evidence-valid");
  assert.equal(
    citations[0].url,
    "https://example.test/nofo.pdf#page=4",
  );
});
