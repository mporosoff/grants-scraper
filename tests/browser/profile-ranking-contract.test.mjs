import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const sources = await Promise.all([
  "../../assets/search-query.js",
  "../../assets/search-retrieval.js",
  "../../assets/profile-ranking.js",
].map(path => readFile(new URL(path, import.meta.url), "utf8")));

function loadApis() {
  const context = { globalThis: {} };
  sources.forEach(source => vm.runInNewContext(source, context));
  return {
    query: context.globalThis.FUNDING_SEARCH_QUERY,
    retrieval: context.globalThis.FUNDING_RETRIEVAL,
    profile: context.globalThis.FUNDING_PROFILE_RANKING,
  };
}

function catalogFor(records, queryApi) {
  const postings = {};
  const documentLengths = [];
  records.forEach((record, documentId) => {
    const counts = new Map();
    queryApi.tokenize(`${record.title} ${record.description || ""}`).forEach(term => {
      counts.set(term, (counts.get(term) || 0) + 1);
    });
    documentLengths.push(Math.max(1, [...counts.values()].reduce((sum, value) => sum + value, 0)));
    for (const [term, frequency] of counts) {
      (postings[term] ||= []).push(documentId, frequency);
    }
  });
  return {
    record_count: records.length,
    opportunities: records.map(record => ({
      opportunity_number: "",
      agency: "Agency",
      topic_areas: [],
      ...record,
    })),
    search_index: {
      postings,
      document_lengths: documentLengths,
      document_count: records.length,
      average_document_length: (
        documentLengths.reduce((sum, value) => sum + value, 0) / records.length
      ),
    },
  };
}

const profile = {
  research_description: "We do electrochemistry and develop controlled colloids",
  expertise_keywords: "Catalysis, AI, chemical engineering",
  cv_text: "Electrochemical catalyst synthesis and colloidal nanoparticle characterization",
  orcid_text: "",
  applicant_context: "higher_education",
  career_stage: "any",
};

test("extracts concrete profile evidence and removes generic CV language", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    { title: "AI catalyst electrochemistry colloid research" },
    { title: "Chemical catalysis methods" },
  ], apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);
  const built = apis.profile.buildTermQuery(profile, {
    catalog,
    tokenize: apis.query.tokenize,
    expandGroups: (value, options) => engine.expandGroups(value, options),
  });

  assert.ok(built.terms.includes("electrochemistry"));
  assert.ok(built.terms.includes("colloid"));
  assert.ok(built.terms.includes("catalysi"));
  assert.equal(built.terms.includes("do"), false);
  assert.equal(built.terms.includes("develop"), false);
  assert.equal(apis.profile.minimumCoverage(built.terms.length), 3);
  assert.equal(apis.profile.minimumCoverage(4), 3);
});

test("keeps CV and ORCID terms in reranking but out of manual-profile admission", () => {
  const apis = loadApis();
  const catalog = catalogFor([
    { title: "Electrochemistry and catalysis" },
    { title: "Genomics and proteomics platform" },
  ], apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);
  const richProfile = {
    ...profile,
    cv_text: "Genomics proteomics",
    orcid_text: "Genomics methods",
  };
  const options = {
    catalog,
    tokenize: apis.query.tokenize,
    expandGroups: (value, expandOptions) => engine.expandGroups(value, expandOptions),
  };
  const full = apis.profile.buildTermQuery(richProfile, options);
  const admission = apis.profile.buildTermQuery(richProfile, {
    ...options,
    admissionOnly: true,
  });
  const cvTerms = apis.query.tokenize("genomics proteomics");

  assert.equal(cvTerms.some(term => full.terms.includes(term)), true);
  assert.equal(cvTerms.some(term => admission.terms.includes(term)), false);
});

test("profile-only retrieval requires multiple independent concepts", () => {
  const apis = loadApis();
  const records = [
    { id: "focused", title: "AI catalyst design", description: "Electrochemistry and colloids." },
    { id: "ai-only", title: "AI journalism", description: "Artificial intelligence for newsrooms." },
    { id: "cat-only", title: "Catalysis program", description: "Reaction science." },
    { id: "unrelated", title: "Arts education", description: "Museum programming." },
  ];
  const catalog = catalogFor(records, apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);
  const built = apis.profile.buildTermQuery(profile, {
    catalog,
    tokenize: apis.query.tokenize,
    expandGroups: (value, options) => engine.expandGroups(value, options),
    admissionOnly: true,
  });
  const result = engine.score(built.query, {
    semantic: false,
    coverage: false,
    minimumCoverage: apis.profile.minimumCoverage(built.terms.length),
  });

  assert.ok(result.scores[0] > 0);
  assert.equal(result.scores[1], 0);
  assert.equal(result.scores[2], 0);
  assert.equal(result.scores[3], 0);
});

test("profile evidence reranks but does not broaden an explicit query", () => {
  const apis = loadApis();
  const records = [
    {
      id: "focused",
      title: "AI catalyst design for electrochemistry",
      description: "Controlled colloids and chemical reaction engineering.",
    },
    {
      id: "generic",
      title: "AI catalyst design initiative",
      description: "Chemical innovation program.",
    },
    { id: "ai-only", title: "AI journalism", description: "Newsroom training." },
  ];
  const catalog = catalogFor(records, apis.query);
  const engine = apis.retrieval.create(catalog, apis.query);
  const direct = engine.score("catalysts for AI");
  const built = apis.profile.buildTermQuery(profile, {
    catalog,
    tokenize: apis.query.tokenize,
    expandGroups: (value, options) => engine.expandGroups(value, options),
  });
  const profiled = engine.score(built.query, {
    semantic: false,
    coverage: false,
    minimumCoverage: 0,
  });

  assert.ok(direct.scores[0] > 0 && direct.scores[1] > 0);
  assert.equal(direct.scores[2], 0);
  assert.ok(profiled.scores[0] > profiled.scores[1]);
});

test("eligibility and career context contribute bounded ranking evidence", () => {
  const { profile: api } = loadApis();
  const record = {
    applicant_types: ["Institutions of higher education"],
    career_stage_signal: true,
  };
  assert.equal(api.applicantFitBonus(record, "higher_education"), 2.4);
  assert.equal(api.applicantFitBonus(record, "small_business"), -0.8);
  assert.equal(api.careerFitBonus(record, "early_career"), 2.6);
});
