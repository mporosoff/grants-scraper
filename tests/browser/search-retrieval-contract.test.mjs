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
