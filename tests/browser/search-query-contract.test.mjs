import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
  new URL("../../assets/search-query.js", import.meta.url),
  "utf8",
);

function loadApi() {
  const context = { globalThis: {} };
  vm.runInNewContext(source, context);
  return context.globalThis.FUNDING_SEARCH_QUERY;
}

function termWeights(api, query) {
  return Object.fromEntries(
    [...api.expandTerms(query)].map(({ term, weight }) => [term, weight]),
  );
}

test("normalizes pasted scientific subscripts", () => {
  const api = loadApi();
  assert.deepEqual(
    [...api.tokenize("CO₂, H₂, and PM₂.₅")],
    ["co2", "h2", "pm2.5"],
  );
});

test("expands common, unambiguous research abbreviations", () => {
  const api = loadApi();

  assert.deepEqual(termWeights(api, "CO2"), {
    co2: 1,
    carbon: 0.86,
    dioxide: 0.86,
  });
  assert.equal(termWeights(api, "AI/ML").artificial, 0.86);
  assert.equal(termWeights(api, "AI/ML").intelligence, 0.86);
  assert.equal(termWeights(api, "AI/ML").machine, 0.86);
  assert.equal(termWeights(api, "AI/ML").learn, 0.86);
  assert.equal(termWeights(api, "CCUS").capture, 0.86);
  assert.equal(termWeights(api, "PTSD")["post-traumatic"], 0.86);
});

test("prefers an indexed literal abbreviation over broadening it", () => {
  const api = loadApi();
  const terms = api.expandTerms("AI", term => term === "ai");
  assert.deepEqual(
    [...terms].map(({ term, weight }) => [term, weight]),
    [["ai", 1]],
  );
});

test("does not expand short ambiguous terms", () => {
  const api = loadApi();
  for (const term of ["ad", "am", "ar", "ms"]) {
    assert.equal(Object.hasOwn(api.aliases, term), false);
  }
});
