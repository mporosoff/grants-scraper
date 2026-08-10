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

test("recognizes PFAS families and falls back to water remediation language", () => {
  const api = loadApi();
  const forms = [
    "PFAS",
    "PFOA",
    "PFOS",
    "PFHxS",
    "PFNA",
    "PFBS",
    "PFBA",
    "PFHxA",
    "PFPeA",
    "PFHpA",
    "PFDA",
    "PFUnA",
    "PFDoA",
    "PFCA",
    "PFSA",
    "FOSA",
    "HFPO-DA",
    "AFFF",
    "perfluoroalkyl substances",
    "polyfluoroalkyl substances",
    "perfluorinated compounds",
    "polyfluorinated compounds",
    "perfluorooctanoic acid",
    "perfluorooctane sulfonate",
    "fluorochemicals",
    "fluorosurfactants",
    "forever chemicals",
  ];

  for (const form of forms) {
    const terms = termWeights(api, form);
    assert.equal(terms.remediation, 0.86, form);
    assert.equal(terms.groundwater, 0.86, form);
    assert.equal(terms.wastewater, 0.86, form);
    assert.equal(terms.purification, 0.86, form);
  }

  const indexedAfff = Object.fromEntries(
    api.expandTerms("AFFF", term => term === "afff")
      .map(({ term, weight }) => [term, weight]),
  );
  assert.equal(indexedAfff.afff, 1);
  assert.equal(indexedAfff.remediation, 0.86);
});

test("does not expand short ambiguous terms", () => {
  const api = loadApi();
  for (const term of ["ad", "am", "ar", "ms"]) {
    assert.equal(Object.hasOwn(api.aliases, term), false);
  }
});

test("groups aliases and scientific irregulars under the terms the user entered", () => {
  const api = loadApi();
  const groups = api.expandGroups("analyses CO2");
  assert.equal(groups.length, 2);
  assert.deepEqual(
    [...groups[0].terms].map(({ term, weight }) => [term, weight]),
    [["analyse", 1], ["analysi", 0.94]],
  );
  assert.ok(groups[1].terms.some(({ term }) => term === "dioxide"));

  const indexGroup = api.expandGroups("indices")[0];
  assert.ok(indexGroup.terms.some(({ term }) => term === "index"));
});
