import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const ROOT = new URL("../../", import.meta.url);
const context = {};
context.globalThis = context;
for (const path of [
  "assets/search-v2-config.js",
  "assets/search-query.js",
  "assets/search-retrieval.js",
]) vm.runInNewContext(await readFile(new URL(path, ROOT), "utf8"), context, { filename: path });

const queryApi = context.FUNDING_SEARCH_QUERY;
const retrievalApi = context.FUNDING_RETRIEVAL;
const configuration = context.FUNDING_SEARCH_V2_CONFIG;

function record(id, title, description = "", topics = []) {
  return {
    opportunity_id: id,
    opportunity_number: `TEST-${id}`,
    title,
    agency: "Test agency",
    description,
    document_search_text: "",
    topic_areas: topics,
    disciplines: ["Chemistry"],
    funding_categories: ["Science"],
  };
}

function index(records) {
  const postings = new Map();
  const lengths = [];
  records.forEach((item, documentId) => {
    const counts = new Map();
    queryApi.tokenize([
      item.title,
      item.opportunity_number,
      item.agency,
      item.description,
      item.document_search_text,
      ...item.topic_areas,
      ...item.disciplines,
      ...item.funding_categories,
    ].join(" ")).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
    lengths.push([...counts.values()].reduce((sum, value) => sum + value, 0) || 1);
    counts.forEach((frequency, term) => {
      if (!postings.has(term)) postings.set(term, []);
      postings.get(term).push(documentId, frequency);
    });
  });
  return {
    algorithm: "bm25",
    document_count: records.length,
    average_document_length: lengths.reduce((sum, value) => sum + value, 0) / records.length,
    document_lengths: lengths,
    postings: Object.fromEntries(postings),
  };
}

function engine(records) {
  return retrievalApi.create(
    { schema_version: 3, opportunities: records, search_index: index(records) },
    queryApi,
    { searchV2: true, searchV2Config: configuration, catalogRole: "parent" },
  );
}

test("explicit fielded evidence is substantive and field-backed", () => {
  const records = [
    record(
      "explicit",
      "Rare earth separation research",
      "Fundamental chemical research on rare earth elements using solvent extraction and recovery.",
    ),
    record(
      "workshop",
      "Rare Earth Policy Workshop",
      "Training participants in advocacy and policy recommendations about mineral supply chains.",
    ),
    record(
      "nasa",
      "Earth Science Program Element",
      "Planetary and atmospheric research.",
    ),
    record(
      "topic-only",
      "Advanced engineering research",
      "General scientific research.",
      ["Rare earth elements", "Separations and membranes"],
    ),
  ];
  const result = engine(records).score("REE separations", { evidence: true });
  const admitted = [...result.scores]
    .map((score, index) => score > 0 ? records[index].opportunity_id : null)
    .filter(Boolean);
  assert.deepEqual(admitted, ["explicit"]);
  const trace = result.evidence[0];
  assert.equal(trace.admission.reason, "fielded_complete_intent");
  assert.ok(trace.admission.admittedBy.every(item => item.path === "fielded_bm25f"));
  assert.ok(trace.admission.fieldContributions.some(item => item.field === "parent_title"));
  assert.ok(trace.groups.every(group => group.evidencePath === "fielded_bm25f"));
  assert.ok(trace.groups.every(group => group.saturationApplied === false));
  assert.ok(trace.groups.every(group => group.contribution <= group.rawContribution));
});

test("fielded retrieval ignores former identifier-bound entailment maps", () => {
  const records = [
    record("360678", "Generic annual solicitation", "General program information."),
    record("unmapped", "Critical minerals separations", "Research on critical minerals recovery."),
  ];
  const scoped = engine(records).score("REE separations", { evidence: true });
  assert.equal(scoped.scores[0], 0);
  assert.equal(scoped.scores[1], 0, "generic critical-minerals metadata is not an entailment map");

  const generic = engine(records).score("critical mineral separations", { evidence: true });
  assert.ok(generic.scores[1] > 0, "complete indexed source text can match without a program map");
  assert.equal(generic.diagnostics.searchV2.configuredScientificEntailmentsUsed, false);
});
