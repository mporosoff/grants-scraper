import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import {
  childRecords as frozenChildRecords,
  parentRecords as frozenParentRecords,
} from "../fixtures/frozen/search-regression-records.mjs";
import { buildCatalog, buildChildCatalog } from "./search-fixture-helpers.mjs";

const ROOT = new URL("../../", import.meta.url);

async function loadRuntime() {
  const context = {};
  context.globalThis = context;
  for (const path of [
    "assets/search-v2-config.js",
    "assets/search-query.js",
    "assets/search-retrieval.js",
  ]) vm.runInNewContext(await readFile(new URL(path, ROOT), "utf8"), context, { filename: path });
  return context;
}

const runtime = await loadRuntime();
const queryApi = runtime.FUNDING_SEARCH_QUERY;
const retrievalApi = runtime.FUNDING_RETRIEVAL;
const configuration = runtime.FUNDING_SEARCH_V2_CONFIG;
const parentCatalog = buildCatalog(frozenParentRecords, queryApi);
const childCatalog = buildChildCatalog(frozenChildRecords, queryApi, retrievalApi);
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

test("permanent REE and NASA canaries do not recreate configured entailments", () => {
  assert.equal(
    ranked("REE separations").some(row => row.id === "fixture-policy-workshop"),
    false,
  );
  assert.equal(
    ranked("rare earth solvent extraction").some(row => row.id === "fixture-policy-workshop"),
    false,
  );
});

test("permanent scientific-term canaries enforce complete indexed intent", () => {
  const catalysis = ranked("catalysis").map(row => row.id);
  assert.ok(["fixture-cps", "fixture-bes"].includes(catalysis[0]));
  assert.ok(catalysis.includes("fixture-cps"));
  assert.ok(catalysis.includes("fixture-army-baa"));
  assert.deepEqual(ranked("AI catalyst design"), []);
  assert.deepEqual(ranked("PFAS"), []);
  assert.equal(ranked("space biology")[0]?.id, "fixture-space-biology");
});

test("permanent identifier and child-evidence canaries retain precedence", () => {
  assert.equal(ranked("RFA-TEST-27-001")[0]?.id, "fixture-identifier");
  const genesis = ranked("Composable and Modular Foundation Models");
  assert.equal(genesis.length, 1);
  assert.equal(genesis[0].id, "fixture-genesis");
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
