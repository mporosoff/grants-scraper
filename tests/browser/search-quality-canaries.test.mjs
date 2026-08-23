import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const ROOT = new URL("../../", import.meta.url);

async function loadRuntime() {
  const context = {};
  context.globalThis = context;
  for (const path of [
    "assets/search-v2-config.js",
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "data/opportunities.js",
    "data/subtopics.js",
  ]) vm.runInNewContext(await readFile(new URL(path, ROOT), "utf8"), context, { filename: path });
  return context;
}

const runtime = await loadRuntime();
const queryApi = runtime.FUNDING_SEARCH_QUERY;
const retrievalApi = runtime.FUNDING_RETRIEVAL;
const configuration = runtime.FUNDING_SEARCH_V2_CONFIG;
const parentCatalog = runtime.GRANT_CATALOG;
const childCatalog = retrievalApi.createChildCatalog(runtime.SUBTOPIC_CATALOG);
const parentEngine = retrievalApi.create(parentCatalog, queryApi, {
  searchV2: true,
  searchV2Config: configuration,
  catalogRole: "parent",
});
const childEngine = retrievalApi.create(childCatalog, queryApi, {
  searchV2: true,
  searchV2Config: configuration,
  catalogRole: "child",
});

function ranked(query) {
  const parentDirect = parentEngine.score(query, { evidence: true });
  const childDirect = childEngine.score(query, { evidence: true });
  const rows = retrievalApi.rollupScores({
    parentCatalog,
    childCatalog,
    parentDirect,
    parentProfile: { scores: new Float64Array(parentCatalog.opportunities.length) },
    childDirect,
    childProfile: { scores: new Float64Array(childCatalog.opportunities.length) },
    eligibilityBonuses: new Float64Array(parentCatalog.opportunities.length),
  }).rows;
  rows.sort((left, right) => (
    Number(left.evidenceTier || 99) - Number(right.evidenceTier || 99)
    || right.relevance - left.relevance
    || left.id.localeCompare(right.id)
  ));
  return Array.from(rows);
}

test("permanent REE and NASA canaries use the frozen catalog deliberately", () => {
  const aliases = ["REE", "REEs", "R.E.E.", "rare earth elements"];
  const aliasResults = aliases.map(query => ranked(query).map(row => row.id));
  aliasResults.slice(1).forEach(ids => assert.deepEqual(ids, aliasResults[0]));
  assert.deepEqual(aliasResults[0], []);
  assert.deepEqual(
    new Set(ranked("REE separations").map(row => row.id)),
    new Set(["360678", "361526", "362061"]),
  );
});

test("permanent scientific-term canaries cover catalyst, PFAS, AI, and space biology", () => {
  for (const [query, expectedLead] of [["catalysis", "344592"], ["catalyst", "361526"]]) {
    const ids = ranked(query).map(row => row.id);
    assert.equal(ids[0], expectedLead, `${query}: strongest publication-eligible evidence must lead`);
    assert.ok(ids.includes("362061"), `${query}: NSF CPS must remain discoverable`);
    assert.equal(ids.includes("359942"), false, "BioData Catalyst must not be scientific catalysis");
  }
  const pfas = ranked("PFAS").map(row => row.id);
  assert.ok(pfas.includes("363375"), "the water-purification PFAS anchor must remain discoverable");
  assert.equal(pfas.includes("360223"), false, "rare-cancer wording must not satisfy PFAS");
  assert.deepEqual(ranked("AI catalyst design").map(row => row.id), ["361526", "362061"]);

  const prohibitedSpaceNoise = new Set([
    "359996", "363224", "363241", "360003", "363240",
    "363325", "360004", "363258", "361234",
  ]);
  assert.deepEqual(
    ranked("space biology").filter(row => prohibitedSpaceNoise.has(row.id)),
    [],
  );
});

test("permanent identifier and Genesis child-evidence canaries retain precedence", () => {
  assert.equal(ranked("RFA-MD-27-001")[0]?.id, "363217");
  const genesis = ranked("Composable and Modular Foundation Models");
  assert.equal(genesis.length, 1);
  assert.equal(genesis[0].id, "361526");
  assert.equal(genesis[0].childDroveMatch, true);
  assert.match(genesis[0].bestChild?.record?.title || "", /Composable and Modular Foundation Models/i);
});

test("permanent generic-title canary requires the missing scientific concept", () => {
  const records = [
    {
      opportunity_id: "generic-title",
      opportunity_number: "TEST-GENERIC",
      title: "Critical Minerals Opportunity",
      agency: "Test agency",
      description: "Workforce policy workshops and supply-chain advocacy.",
      document_search_text: "",
      topic_areas: [],
      disciplines: [],
      funding_categories: [],
    },
    {
      opportunity_id: "rich-description",
      opportunity_number: "TEST-RICH",
      title: "Annual Research Program",
      agency: "Test agency",
      description: "Research on critical mineral extraction, chemical separation, processing, and recovery.",
      document_search_text: "",
      topic_areas: [],
      disciplines: [],
      funding_categories: [],
    },
  ];
  const postings = {};
  const lengths = [];
  records.forEach((record, documentId) => {
    const counts = new Map();
    queryApi.tokenize([
      record.title, record.opportunity_number, record.agency, record.description,
    ].join(" ")).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
    lengths.push([...counts.values()].reduce((sum, value) => sum + value, 0));
    for (const [term, frequency] of counts) {
      if (!postings[term]) postings[term] = [];
      postings[term].push(documentId, frequency);
    }
  });
  const engine = retrievalApi.create({
    schema_version: 3,
    opportunities: records,
    search_index: {
      algorithm: "bm25",
      postings,
      document_count: records.length,
      document_lengths: lengths,
      average_document_length: lengths.reduce((sum, value) => sum + value, 0) / lengths.length,
    },
  }, queryApi, {
    searchV2: true,
    searchV2Config: configuration,
    catalogRole: "parent",
  });
  const result = engine.score("critical mineral separations", { evidence: true });
  assert.equal(result.scores[0], 0);
  assert.ok(result.scores[1] > 0);
});
