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
  assert.equal(result.diagnostics.minimumCoverage, 3);
});

test("uses catalog topics only to rerank lexical candidates", () => {
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
  assert.equal(result.scores[2], 0, "a coarse topic must not create a candidate");
  assert.equal(result.lexicalScores[2], 0);
  assert.ok(result.scores[0] > result.lexicalScores[0]);
  assert.ok(result.diagnostics.inferredTopics.includes("Carbon management"));
});

test("requires both concepts in a two-concept search", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("both", "AI for catalyst design", "Artificial intelligence for chemical catalyst design."),
    record("ai-only", "AI journalism training", "Artificial intelligence for newsrooms."),
    record("cat-only", "Catalysis research", "Chemical catalysis and reactor design."),
  ], apis.query);
  const result = apis.retrieval.create(catalog, apis.query)
    .score("catalysts for AI");

  assert.ok(result.scores[0] > 0);
  assert.equal(result.scores[1], 0);
  assert.equal(result.scores[2], 0);
  assert.equal(result.diagnostics.minimumCoverage, 2);
});

test("reported catalyst and AI search is narrow without losing chemistry programs", () => {
  const apis = loadApis();
  const catalog = assignmentJson(productionCatalogSource);
  const result = apis.retrieval.create(catalog, apis.query).score(
    "catalysts for AI",
    { context: "Electrochemistry, colloids, catalysis, AI, and chemical engineering." },
  );
  const matches = catalog.opportunities.filter((_record, index) => result.scores[index] > 0);
  const matchedIds = new Set(matches.map(record => record.opportunity_id));

  assert.ok(matchedIds.has("362061"), "Chemical Process Systems should remain retrievable");
  assert.ok(matchedIds.has("360678"), "the evidence-backed DOE umbrella should remain retrievable");
  assert.ok(matchedIds.has("356605"), "the evidence-backed ONR BAA should remain retrievable");
  assert.ok(matchedIds.has("347749"), "the NSF chemistry program should remain retrievable");
  assert.ok(matches.length >= 3 && matches.length <= 20, `unexpected candidate count: ${matches.length}`);
  assert.equal(matchedIds.has("363440"), false, "AI journalism must not leak through");
  assert.equal(matchedIds.has("363547"), false, "EducationUSA AI outreach must not leak through");
  assert.equal(matchedIds.has("359949"), false, "metaphorical catalyst wording must not leak through");
  assert.equal(matchedIds.has("359942"), false, "BioData Catalyst is not chemical catalysis");
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

test("topic catalog admits only search-indexed publishable subject children", () => {
  const { retrieval } = loadApis();
  const sidecar = {
    schema_version: 1,
    records: {
      parent: {
        subtopics: [
          {
            subtopic_id: "p:public",
            parent_id: "p",
            child_type: "subject",
            publication_state: "publishable",
            title: "Public topic",
            summary: "Catalysis",
          },
          {
            subtopic_id: "p:review",
            parent_id: "p",
            child_type: "subject",
            publication_state: "review",
            title: "Review topic",
          },
        ],
      },
    },
    search_index: {
      document_count: 1,
      record_ids: ["p:public"],
      document_lengths: [1],
      average_document_length: 1,
      postings: { catalysi: [0, 1] },
    },
  };
  const childCatalog = retrieval.createChildCatalog(sidecar);
  assert.deepEqual(
    Array.from(childCatalog.opportunities, record => record.opportunity_id),
    ["p:public"],
  );

  sidecar.search_index = { ...sidecar.search_index, record_ids: ["p:review"] };
  assert.throws(
    () => retrieval.createChildCatalog(sidecar),
    /not a publishable subject/,
  );
});

test("P9 rollup uses anchored P90 max scoring with zero cardinality bonus", () => {
  const { retrieval } = loadApis();
  const parentCatalog = {
    opportunities: [record("p1", "Parent one"), record("p2", "Parent two")],
  };
  const childCatalog = {
    opportunities: [
      { subtopic_id: "p1:c1", parent_id: "p1", title: "Child one" },
      { subtopic_id: "p1:c2", parent_id: "p1", title: "Child two" },
      { subtopic_id: "p2:c1", parent_id: "p2", title: "Child three" },
    ],
  };
  const scored = retrieval.rollupScores({
    parentCatalog,
    childCatalog,
    parentDirect: { scores: Float64Array.from([10, 0]) },
    parentProfile: { scores: Float64Array.from([2, 0]) },
    childDirect: { scores: Float64Array.from([15, 12, 4]) },
    childProfile: { scores: Float64Array.from([3, 0, 0]) },
    eligibilityBonuses: [2, 0],
  });

  assert.equal(scored.scales.parent, 22);
  assert.equal(scored.scales.childNative, 33);
  assert.equal(scored.scales.child, 33);
  assert.equal(scored.cardinalityBonus, 0);
  assert.equal(scored.rows.length, 2, "a direct child may admit its parent");
  assert.equal(scored.rows[0].matchingChildCount, 2);
  assert.equal(scored.rows[0].bestChild.id, "p1:c1");
  assert.equal(scored.rows[0].childDroveMatch, false, "equal normalized maxima do not need child display evidence");
  assert.equal(scored.rows[0].relevance, 1);
  assert.equal(scored.rows[0].eligibility, 2 / 22);
  assert.equal(scored.rows[1].parentAdmitted, false);

  const one = retrieval.rollupScores({
    parentCatalog: { opportunities: [parentCatalog.opportunities[0]] },
    childCatalog: { opportunities: [childCatalog.opportunities[0]] },
    parentDirect: { scores: Float64Array.from([10]) },
    childDirect: { scores: Float64Array.from([15]) },
  });
  assert.equal(one.rows[0].relevance, 1);
  assert.equal(scored.rows[0].relevance, one.rows[0].relevance);
});

test("explanation evidence reports only terms that contributed", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("fit", "Carbon capture membranes"),
    record("other", "Arts education"),
  ], apis.query);
  const result = apis.retrieval.create(catalog, apis.query).score(
    "carbon capture",
    { semantic: false, evidence: true },
  );

  assert.ok(result.scores[0] > 0);
  assert.deepEqual(
    Array.from(result.evidence[0].groups, group => [group.source, ...group.matchedTerms]),
    [["carbon", "carbon"], ["capture", "capture"]],
  );
  assert.deepEqual(
    Array.from(result.evidence[0].groups, group => [...group.matchedDisplayTerms]),
    [["Carbon"], ["capture"]],
  );
  assert.deepEqual(
    Array.from(result.evidence[0].groups, group => (
      Array.from(group.matchedTermContributions, item => item.term)
    )),
    [["carbon"], ["capture"]],
  );
  assert.equal(result.evidence[0].admission.admitted, true);
  assert.equal(result.evidence[0].admission.reason, "exact_phrase_or_identifier");
  assert.equal(result.evidence[1].admission.admitted, false);
  assert.equal(result.evidence[1].admission.reason, "no_scoring_evidence");
  assert.deepEqual(Array.from(result.evidence[1].groups), []);
});

test("diagnostic scoring configuration can ablate title boosts without changing defaults", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    record("title", "Carbon capture"),
    record("description", "General research", "Carbon capture"),
  ], apis.query);
  const production = apis.retrieval.create(catalog, apis.query)
    .score("carbon capture", { semantic: false, evidence: true });
  const ablated = apis.retrieval.create(catalog, apis.query, {
    exactTitleMatchBoost: 0,
    titlePhraseBoost: 0,
    trigramPhraseBoost: 0,
  }).score("carbon capture", { semantic: false, evidence: true });

  assert.equal(production.diagnostics.scoringConfiguration.exactTitleMatchBoost, 24);
  assert.equal(ablated.diagnostics.scoringConfiguration.exactTitleMatchBoost, 0);
  assert.ok(production.scores[0] > ablated.scores[0]);
  assert.ok(ablated.scores[0] > 0, "the underlying indexed title evidence remains");
  assert.equal(production.scores[1], ablated.scores[1]);
});

test("generic parent-child rollup is deterministic and cardinality-neutral", () => {
  const { retrieval } = loadApis();
  const parent = [{ id: "p", score: 10 }];
  const child = { id: "p:c", parent: "p", score: 20 };
  const options = children => ({
    parentRows: parent,
    childRows: children,
    childParentId: row => row.parent,
  });
  const one = retrieval.rollupRankedRecords(options([child]));
  const hundred = retrieval.rollupRankedRecords(options(
    Array.from({ length: 100 }, (_value, index) => ({
      ...child,
      id: `${child.id}:${index}`,
    })),
  ));

  assert.equal(one.rows[0].relevance, hundred.rows[0].relevance);
  assert.equal(one.cardinalityBonus, 0);
  assert.equal(hundred.cardinalityBonus, 0);
  assert.equal(one.rows[0].bestChild.row.id, "p:c");
  assert.equal(one.rows[0].childDroveMatch, false);
});

test("matched child evidence is marked displayable only when it drives the max", () => {
  const { retrieval } = loadApis();
  const rolled = retrieval.rollupRankedRecords({
    parentRows: [{ id: "p", score: 20 }],
    childRows: [{ id: "p:c", parent: "p", score: 5 }],
    childParentId: row => row.parent,
  });
  assert.equal(rolled.rows[0].bestChild.row.id, "p:c");
  assert.equal(rolled.rows[0].childDroveMatch, false);
});
