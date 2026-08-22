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

test("keeps deterministic abbreviation handling network-free", () => {
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /api\.openai|api\.anthropic/i);
});

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

test("keeps AI long-form alternatives inside one guarded concept", () => {
  const api = loadApi();
  const group = api.expandGroups("AI", term => term === "ai")[0];
  assert.equal(group.source, "ai");
  assert.ok(group.terms.some(({ term }) => term === "artificial"));
  assert.ok(group.terms.some(({ term }) => term === "intelligence"));
  assert.ok(group.terms.some(({ term }) => term === "learn"));
  assert.ok(group.evidenceAlternatives.some(items => items.join(" ") === "artificial intelligence"));
});

test("guards the scientific catalyst word family against metaphorical uses", () => {
  const api = loadApi();
  const groups = api.expandGroups("catalysts for AI");

  assert.equal(groups.length, 2);
  assert.equal(groups[0].expansion.phrase, "scientific catalysis");
  assert.equal(groups[0].evidenceMode, "any");
  assert.ok(groups[0].terms.some(({ term }) => term === "catalysi"));
  assert.ok(groups[0].terms.some(({ term }) => term === "catalytic"));
  assert.ok(groups[0].evidenceWindows.some(item => item.terms.join(" ") === "catalyst reaction"));
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

test("expands REE and ionic-liquid extraction language even when abbreviations are indexed", () => {
  const api = loadApi();
  for (const form of ["REE", "REEs", "lanthanides"]) {
    const terms = termWeights(api, form);
    assert.equal(terms.rare, 0.86, form);
    assert.equal(terms.earth, 0.86, form);
    assert.equal(terms.lanthanide, form.toLowerCase().startsWith("lanthanide") ? 1 : 0.86, form);
    assert.equal(terms.mineral, undefined, form);
    assert.equal(terms.processing, undefined, form);
  }

  const indexed = Object.fromEntries(
    api.expandTerms("REE ionic liquid extraction", term => ["ree", "ionic", "liquid", "extraction"].includes(term))
      .map(({ term, weight }) => [term, weight]),
  );
  assert.equal(indexed.ree, 1);
  assert.equal(indexed.rare, 0.86);
  assert.equal(indexed.solvent, 0.86);
  assert.equal(indexed.separation, 0.86);
  assert.equal(indexed.recovery, 0.86);

  const abbreviated = api.expandGroups("REE extraction with ILs");
  assert.equal(abbreviated.length, 3);
  assert.equal(abbreviated[2].expansion.phrase, "ionic liquids");
  assert.equal(abbreviated[2].requiredAlways, true);
  assert.equal(abbreviated[2].minimumEvidence, 2);
  assert.ok(abbreviated[2].terms.some(item => item.term === "solvent"));
});

test("does not expand short ambiguous terms", () => {
  const api = loadApi();
  for (const term of ["ad", "am", "ar", "ms"]) {
    assert.equal(Object.hasOwn(api.aliases, term), false);
  }
});

test("treats broad-agency wording as one scoped concept", () => {
  const api = loadApi();
  const groups = api.expandGroups("broad agency announcement chemical separations");
  assert.equal(groups.length, 3);
  assert.equal(groups[0].expansion.phrase, "broad agency announcement");
  assert.equal(groups[0].requiredAlways, true);
  assert.ok(groups[0].evidenceAlternatives.some(items => items.join(" ") === "broad agency announcement"));
});

test("treats Basic Energy Sciences as one required DOE program concept", () => {
  const api = loadApi();
  const groups = api.expandGroups("DOE Basic Energy Sciences separations");
  assert.equal(groups.length, 3);
  assert.equal(groups[1].expansion.phrase, "basic energy sciences");
  assert.equal(groups[1].requiredAlways, true);
  assert.equal(groups[1].minimumEvidence, 1);
  assert.ok(groups[1].evidenceAlternatives.some(items => items.join(" ") === "basic energy science"));
  assert.deepEqual([...groups[1].evidencePhrases], ["basic energy science", "bes"]);
});

test("learns an unknown acronym from catalog wording and researcher context", () => {
  const api = loadApi();
  const resolver = api.createAcronymResolver([
    {
      title: "Hypersonic flow methods",
      description: "Acceleration of computational fluid dynamics using advanced numerics.",
    },
    {
      title: "Food access",
      description: "Community food distribution for rural households.",
    },
  ]);
  const groups = api.expandGroups(
    "cfd",
    term => term === "cfd",
    {
      acronymResolver: resolver,
      context: "Transport phenomena and computational fluid dynamics for reacting flows.",
    },
  );

  assert.equal(groups.length, 1);
  assert.equal(groups[0].expansion.phrase, "computational fluid dynamics");
  assert.equal(groups[0].expansion.basis, "researcher context");
  assert.equal(groups[0].minimumEvidence, 2);
  assert.ok(groups[0].terms.some(item => item.term === "computational"));
  assert.ok(groups[0].terms.some(item => item.term === "fluid"));
  assert.ok(groups[0].terms.some(item => item.term === "dynamic"));
});

test("learns an unknown acronym directly from local researcher context", () => {
  const api = loadApi();
  const resolver = api.createAcronymResolver([]);
  const groups = api.expandGroups("CFD", () => false, {
    acronymResolver: resolver,
    context: "Recent publications apply computational fluid dynamics to turbulent reactors.",
  });

  assert.equal(groups[0].expansion?.phrase, "computational fluid dynamics");
  assert.equal(groups[0].expansion?.basis, "researcher context");
  assert.equal(groups[0].minimumEvidence, 2);
});

test("refuses an ambiguous catalog acronym until context disambiguates it", () => {
  const api = loadApi();
  const records = [];
  for (let index = 0; index < 3; index += 1) {
    records.push({ description: "Computational fluid dynamics for aerospace systems." });
    records.push({ description: "Community food distribution for neighborhood programs." });
  }
  const resolver = api.createAcronymResolver(records);
  const unresolved = api.expandGroups("CFD", () => false, { acronymResolver: resolver });
  assert.equal(unresolved[0].expansion, null);
  assert.deepEqual(
    [...unresolved[0].terms].map(item => item.term),
    ["cfd"],
  );

  const resolved = api.expandGroups("CFD", () => false, {
    acronymResolver: resolver,
    context: "Computational fluid dynamics and turbulent transport.",
  });
  assert.equal(resolved[0].expansion.phrase, "computational fluid dynamics");
});

test("search v2 marks short uppercase acronyms exact-only unless deterministically resolved", () => {
  const api = loadApi();
  const unresolved = api.expandGroups("CFD", term => term === "cfda", { searchV2: true });
  assert.equal(unresolved.length, 1);
  assert.equal(unresolved[0].source, "cfd");
  assert.equal(unresolved[0].exactIndexedAcronym, true);
  assert.deepEqual([...unresolved[0].terms].map(item => item.term), ["cfd"]);

  const technical = api.expandGroups(
    "critical mineral separations",
    () => true,
    { searchV2: true },
  );
  assert.deepEqual(
    [...technical].map(group => group.conceptId),
    ["critical-minerals", "separations"],
  );
  assert.equal(technical[0].evidencePolicy, "controlled_compound");
  assert.ok(technical[1].terms.some(item => item.term === "process"));
  assert.ok(technical[1].terms.some(item => item.term === "recovery"));

  const maritime = api.expandGroups("autonomous maritime sensing", () => true, { searchV2: true });
  assert.ok(maritime[1].terms.some(item => item.term === "marine"));
  assert.ok(maritime[1].terms.some(item => item.term === "navy"));

  const navigation = api.expandGroups("quantum navigation", () => true, { searchV2: true });
  assert.ok(navigation[1].terms.some(item => item.term === "pnt"));
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
