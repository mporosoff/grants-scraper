import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const querySource = await readFile(
  new URL("../../assets/search-query.js", import.meta.url),
  "utf8",
);
const retrievalSource = await readFile(
  new URL("../../assets/search-retrieval.js", import.meta.url),
  "utf8",
);
const productionCatalogSource = await readFile(
  new URL("../../data/opportunities.js", import.meta.url),
  "utf8",
);

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{"), source.lastIndexOf(";")).trim());
}

function loadApis() {
  const context = { globalThis: {} };
  vm.runInNewContext(querySource, context);
  vm.runInNewContext(retrievalSource, context);
  return {
    query: context.globalThis.FUNDING_SEARCH_QUERY,
    retrieval: context.globalThis.FUNDING_RETRIEVAL,
  };
}

function catalogFor(records, queryApi) {
  const postings = {};
  const documentLengths = [];
  records.forEach((record, documentId) => {
    const values = [
      record.title,
      record.opportunity_number,
      record.description,
      ...(record.topic_areas || []),
      ...(record.disciplines || []),
    ].filter(Boolean).join(" ");
    const counts = new Map();
    queryApi.tokenize(values).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
    documentLengths.push([...counts.values()].reduce((sum, value) => sum + value, 0));
    for (const [term, frequency] of counts) {
      if (!postings[term]) postings[term] = [];
      postings[term].push(documentId, frequency);
    }
  });
  return {
    opportunities: records,
    record_count: records.length,
    search_index: {
      postings,
      document_count: records.length,
      document_lengths: documentLengths,
      average_document_length: documentLengths.reduce((sum, value) => sum + value, 0) / records.length,
    },
  };
}

function record(id, title, description = "", topics = []) {
  return {
    opportunity_id: id,
    opportunity_number: `OPP-${id}`,
    title,
    description,
    topic_areas: topics,
    disciplines: [],
  };
}

test("recovers scientific typos and irregular word forms", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("cat", "Catalysis and reaction engineering"),
    record("stats", "Statistical analysis methods"),
    record("other", "Arts education"),
  ], apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);

  const typo = engine.score("catalyis");
  assert.ok(typo.scores[0] > 0);
  assert.equal(typo.scores[2], 0);
  assert.deepEqual(
    [...typo.diagnostics.fuzzyTerms[0].matches],
    ["catalysi"],
  );

  const irregular = engine.score("analyses");
  assert.ok(irregular.scores[1] > 0);
  assert.equal(irregular.scores[2], 0);
});

test("requires meaningful coverage for longer searches", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("complete", "Water contamination membrane treatment"),
    record("partial", "Water infrastructure planning"),
    record("other", "Arts education"),
  ], apis.query);
  const result = apis.retrieval.create(catalog, apis.query)
    .score("water contamination membrane treatment", { semantic: false });

  assert.ok(result.scores[0] > 0);
  assert.equal(result.scores[1], 0);
  assert.equal(result.diagnostics.minimumCoverage, 2);
});

test("uses catalog topics as a semantic bridge beyond literal summary terms", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("seed-1", "Carbon dioxide capture", "industrial emissions", ["Carbon management"]),
    record("seed-2", "Carbon dioxide storage", "industrial emissions and geologic sequestration", ["Carbon management"]),
    record("related", "Direct air removal demonstration", "durable atmospheric removal", ["Carbon management"]),
    record("water", "Drinking water systems", "utility resilience", ["Water"]),
    record("health", "Community health", "clinical services", ["Public health"]),
    record("arts", "Arts education", "museum training", ["Arts and culture"]),
  ], apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);
  const result = engine.score("industrial emissions");

  assert.ok(result.semanticScores[2] > 0);
  assert.ok(result.scores[2] > 0);
  assert.equal(result.lexicalScores[2], 0);
  assert.ok(result.diagnostics.inferredTopics.includes("Carbon management"));
});

test("preserves exact opportunity-number priority", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("exact", "Broad water program"),
    record("text", "OPP exact methods", "OPP-exact"),
  ], apis.query);
  catalog.opportunities[0].opportunity_number = "DE-FOA-123";
  const rebuilt = catalogFor(catalog.opportunities, apis.query);
  const scores = apis.retrieval.create(rebuilt, apis.query).score("DE-FOA-123").scores;
  assert.ok(scores[0] > scores[1]);
});

test("retrieves rare-earth extraction opportunities from REE and ionic-liquid wording", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record(
      "ree",
      "Critical minerals recovery and recycling",
      "Solvent separation and processing of rare earth elements and lanthanides.",
      ["Separations and membranes", "Materials science"],
    ),
    record("battery", "Battery electrolyte manufacturing", "Ionic conductivity in energy storage."),
    record("arts", "Arts education", "Museum and cultural programming."),
  ], apis.query);
  const scores = apis.retrieval.create(catalog, apis.query)
    .score("ionic liquids for REE extraction", { semantic: false }).scores;

  assert.ok(scores[0] > 0);
  assert.equal(scores[2], 0);
  assert.ok(scores[0] > scores[1]);
});

test("uses researcher context to resolve an unknown acronym without AI", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record(
      "cfd",
      "Hypersonic flow simulation",
      "Computational fluid dynamics using advanced numerics for high-enthalpy flows.",
      ["Space and aeronautics"],
    ),
    record("fluid", "Fluid film behavior", "Experimental fluid mechanics measurements."),
    record("food", "Community food distribution", "Regional nutrition access."),
  ], apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);
  const withoutContext = engine.score("CFD", { semantic: false });
  const withContext = engine.score("CFD", {
    semantic: false,
    context: "Transport phenomena and computational fluid dynamics for reacting flows.",
  });

  assert.equal(withoutContext.scores[0], 0);
  assert.ok(withContext.scores[0] > 0);
  assert.equal(withContext.scores[1], 0, "one shared word must not satisfy an acronym expansion");
  assert.equal(withContext.scores[2], 0);
  assert.deepEqual(
    Array.from(
      withContext.diagnostics.acronymExpansions,
      item => [item.source, item.phrase],
    ),
    [["cfd", "computational fluid dynamics"]],
  );
});

test("resolves CFD with the production retrieval engine from researcher context", () => {
  const apis = loadApis();
  const catalog = assignmentJson(productionCatalogSource);
  const groups = apis.retrieval.create(catalog, apis.query).expandGroups("CFD", {
    context: "Transport phenomena and computational fluid dynamics for reacting flows.",
  });

  assert.equal(groups.length, 1);
  assert.equal(groups[0].expansion.phrase, "computational fluid dynamics");
  assert.equal(groups[0].expansion.basis, "researcher context");
  assert.ok(groups[0].terms.some(item => item.term === "computational"));
  assert.ok(groups[0].terms.some(item => item.term === "fluid"));
  assert.ok(groups[0].terms.some(item => item.term === "dynamic"));
});

test("production separation searches surface focused programs and the DOE umbrella call without policy noise", () => {
  const apis = loadApis();
  const catalog = assignmentJson(productionCatalogSource);
  const engine = apis.retrieval.create(catalog, apis.query);
  const ids = Object.fromEntries(
    catalog.opportunities.map((record, index) => [record.opportunity_id, index]),
  );

  for (const query of ["separations with ionic liquids", "REE extraction with ILs"]) {
    const result = engine.score(query);
    for (const id of ["362061", "362063", "360678"]) {
      assert.ok(result.scores[ids[id]] > 0, `${query}: ${id}`);
    }
    const workshop = catalog.opportunities.findIndex(record =>
      /YSEALI Regional Workshop/i.test(record.title || "")
    );
    assert.ok(workshop >= 0);
    assert.equal(result.scores[workshop], 0, `${query}: policy workshop noise`);
  }
});

test("exact Basic Energy Sciences wording outranks generic new DOE notices", () => {
  const apis = loadApis();
  const catalog = assignmentJson(productionCatalogSource);
  const result = apis.retrieval.create(catalog, apis.query)
    .score("DOE Basic Energy Sciences separations");
  const bes = catalog.opportunities.findIndex(record => record.opportunity_id === "360678");
  const prospect = catalog.opportunities.findIndex(record => record.opportunity_id === "363510");

  assert.ok(bes >= 0);
  assert.ok(result.scores[bes] > 0);
  if (prospect >= 0) assert.ok(result.scores[bes] > result.scores[prospect]);
});
