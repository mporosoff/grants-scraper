import { readFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const context = { globalThis: {} };
for (const relative of [
  "assets/search-query.js",
  "assets/search-retrieval.js",
  "assets/profile-ranking.js",
]) {
  vm.runInNewContext(await readFile(new URL(relative, root), "utf8"), context);
}
vm.runInNewContext(
  await readFile(new URL("data/opportunities.js", root), "utf8"),
  context,
);

const queryApi = context.globalThis.FUNDING_SEARCH_QUERY;
const retrievalApi = context.globalThis.FUNDING_RETRIEVAL;
const profileApi = context.globalThis.FUNDING_PROFILE_RANKING;
const catalog = context.globalThis.GRANT_CATALOG;
const engine = retrievalApi.create(catalog, queryApi);

const baseProfile = {
  research_description: (
    "We do electrochemistry and can develop well-controlled colloids"
  ),
  expertise_keywords: "Catalysis, AI, chemical engineering",
  cv_text: "",
  orcid_text: "",
  applicant_context: "higher_education",
  career_stage: "any",
};
const representativeCv = [
  "Electrochemical catalyst synthesis and operando characterization.",
  "Colloidal nanoparticle design for reaction engineering.",
  "Machine learning for catalyst structure property relationships.",
].join(" ");

function build(profile) {
  return profileApi.buildTermQuery(profile, {
    catalog,
    tokenize: queryApi.tokenize,
    expandGroups: (value, options) => engine.expandGroups(value, options),
  });
}

function rank(query, profile = null) {
  const direct = engine.score(query, {
    context: profile ? profileApi.context(profile) : "",
  });
  const built = profile ? build(profile) : { query: "", terms: [] };
  const profiled = profile
    ? engine.score(built.query, {
        semantic: false,
        coverage: false,
        minimumCoverage: 0,
      })
    : { scores: new Float64Array(catalog.record_count) };
  const rows = [];
  catalog.opportunities.forEach((record, index) => {
    if (record.status === "archived" || direct.scores[index] <= 0) return;
    const profileScore = profiled.scores[index] || 0;
    const eligibility = profile
      ? profileApi.applicantFitBonus(record, profile.applicant_context)
      : 0;
    rows.push({
      id: String(record.opportunity_id),
      number: record.opportunity_number,
      title: record.title,
      direct: direct.scores[index],
      profile: profileScore,
      eligibility,
      total: (direct.scores[index] * 2) + profileScore + eligibility,
    });
  });
  rows.sort((left, right) => right.total - left.total || left.title.localeCompare(right.title));
  return { rows, terms: built.terms };
}

function profileOnlyCounts(profile) {
  const built = build(profile);
  const count = minimumCoverage => {
    const result = engine.score(built.query, {
      semantic: false,
      coverage: false,
      minimumCoverage,
    });
    const admitted = catalog.opportunities.filter(
      (record, index) => record.status !== "archived" && result.scores[index] > 0,
    );
    return {
      count: admitted.length,
      audited_anchor_ids: admitted
        .map(record => String(record.opportunity_id))
        .filter(id => anchorIds.has(id)),
    };
  };
  const strictMinimum = profileApi.minimumCoverage(built.terms.length);
  return {
    terms: built.terms,
    former_one_term_admission: count(1).count,
    new_minimum_concepts: strictMinimum,
    new_multi_concept_admission: count(strictMinimum).count,
    coverage_sweep: Array.from(
      { length: Math.min(6, built.terms.length) },
      (_, index) => ({ minimum: index + 1, ...count(index + 1) }),
    ),
  };
}

const query = "catalysts for AI";
const baseline = rank(query);
const screenshotProfile = rank(query, baseProfile);
const cvProfile = rank(query, { ...baseProfile, cv_text: representativeCv });
const anchorIds = new Set(["362061", "360678", "347749", "356605"]);

function summary(label, result) {
  const positions = new Map(result.rows.map((row, index) => [row.id, index + 1]));
  const anchorRanks = [...anchorIds]
    .map(id => positions.get(id))
    .filter(Boolean);
  return {
    label,
    candidate_count: result.rows.length,
    profile_terms: result.terms,
    audited_anchor_mean_rank: Number(
      (anchorRanks.reduce((sum, value) => sum + value, 0) / anchorRanks.length)
        .toFixed(2),
    ),
    top_results: result.rows.slice(0, 12).map((row, index) => ({
      rank: index + 1,
      id: row.id,
      number: row.number,
      title: row.title,
      direct_score: Number(row.direct.toFixed(3)),
      profile_score: Number(row.profile.toFixed(3)),
      eligibility_bonus: row.eligibility,
      total_score: Number(row.total.toFixed(3)),
    })),
  };
}

function benchmark(profile, iterations = 100) {
  for (let index = 0; index < 10; index += 1) rank(query, profile);
  const samples = [];
  for (let index = 0; index < iterations; index += 1) {
    const started = performance.now();
    rank(query, profile);
    samples.push(performance.now() - started);
  }
  samples.sort((left, right) => left - right);
  return {
    median: Number(samples[Math.floor(samples.length * 0.5)].toFixed(3)),
    p95: Number(samples[Math.floor(samples.length * 0.95)].toFixed(3)),
  };
}

console.log(JSON.stringify({
  query,
  audited_anchor_ids: [...anchorIds],
  profile_only: profileOnlyCounts(baseProfile),
  local_ranking_latency_ms: {
    query_only: benchmark(null),
    screenshot_profile: benchmark(baseProfile),
    screenshot_profile_plus_representative_cv: benchmark({
      ...baseProfile,
      cv_text: representativeCv,
    }),
  },
  runs: [
    summary("query_only", baseline),
    summary("screenshot_profile", screenshotProfile),
    summary("screenshot_profile_plus_representative_cv", cvProfile),
  ],
}, null, 2));
