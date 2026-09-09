import assert from "node:assert/strict";
import test from "node:test";
import { waitForHealth } from "../../tools/smoke_search_worker.mjs";

const worker = new URL("https://worker.example/");
const generation = { corpus_sha256: "a".repeat(64), model_space_fingerprint: "b".repeat(64) };
const healthy = { status: 200, body: { ...generation, service: "available",
  budget_state: "available", previous_corpus_supported: true } };

test("smoke waits for the matching edge after a prior handshake succeeded elsewhere", async () => {
  const calls = [], waits = [];
  await waitForHealth(worker, generation, {
    request: async url => {
      calls.push(url.pathname);
      return calls.length === 1 ? { ...healthy, body: { ...healthy.body, corpus_sha256: "c".repeat(64) } } : healthy;
    },
    sleep: async ms => waits.push(ms),
  });
  assert.deepEqual(calls, ["/health", "/health"]);
  assert.deepEqual(waits, [5000]);
});

test("transport and non-JSON edge failures receive bounded health retries", async () => {
  let calls = 0;
  await waitForHealth(worker, generation, {
    request: async () => {
      calls += 1;
      if (calls === 1) throw new TypeError("private response text");
      return calls === 2 ? { status: 503, content_type: "text/html", body: {} } : healthy;
    }, sleep: async () => {},
  });
  assert.equal(calls, 3);
});

test("persistent mismatch or denial terminates without provider dispatch or raw bodies", async () => {
  for (const response of [
    { ...healthy, body: { ...healthy.body, previous_corpus_supported: false } },
    { status: 403, content_type: "application/json", body: { private: "do not persist" } },
  ]) {
    let calls = 0, waits = 0;
    await assert.rejects(waitForHealth(worker, generation, {
      request: async url => { assert.equal(url.pathname, "/health"); calls += 1; return response; },
      sleep: async () => { waits += 1; },
    }), error => {
      assert.match(error.message, /"attempt":12/);
      assert.match(error.message, /"mismatch":/);
      assert.doesNotMatch(error.message, /do not persist/);
      return true;
    });
    assert.equal(calls, 12);
    assert.equal(waits, 11);
  }
});
