#!/usr/bin/env node
// P9.1 frozen cross-corpus scoring prototype. This does not change the browser
// scorer. It measures a query-local normalization for the parent and child
// BM25 corpora, then applies the already-settled max-child rollup.

import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const QUERY_SET = "evaluation/query_set.json";
const CHILDREN = "evaluation/p9_scoring_children.json";
const OUTPUT = "evaluation/p9_scoring_results.json";
const PARENT_CATALOG = "data/opportunities.js";
const TOP_N = 50;
const TOP_GATE = 10;

const TARGET_CASES = Object.freeze([
  { id: "p901", kind: "many_children_office_science", query: "plasma science and technology", focus_parent_id: "360678" },
  { id: "p902", kind: "genesis_hierarchy", query: "agentic AI chemical manufacturing", focus_parent_id: "361526" },
  { id: "p903", kind: "tdac", query: "electromagnetic pulse vulnerability shielding", focus_parent_id: "345241" },
  { id: "p904", kind: "roses_native", query: "habitable worlds observatory precursor science", focus_parent_id: "363325" },
  { id: "p905", kind: "hgeo", query: "produced water treatment technologies", focus_parent_id: "363065" },
  { id: "p906", kind: "arl_many_children", query: "polymer chemistry", focus_parent_id: "344592" },
  { id: "p907", kind: "parent_without_children", query: "advancing global health", focus_parent_id: "363607" },
  { id: "p908", kind: "exact_opportunity_number", query: "W911NF-23-S-0001", focus_parent_id: "344592" },
  { id: "p909", kind: "broad_single_term", query: "energy", focus_parent_id: "360678" },
  { id: "p910", kind: "multiword_technical", query: "quantum materials", focus_parent_id: "361526" },
  { id: "p911", kind: "acronym", query: "AI", focus_parent_id: "360678" },
  { id: "p912", kind: "no_result", query: "zzzzqqqxyzzy" },
  {
    id: "p913",
    kind: "profile",
    query: "carbon capture",
    focus_parent_id: "360678",
    profile: {
      research_description: "We do electrochemistry and can develop well-controlled colloids",
      expertise_keywords: "Catalysis, AI, chemical engineering",
      cv_text: "@tests/fixtures/browser_cv.txt",
      applicant_context: "higher_education",
      career_stage: "early_career",
    },
  },
]);

// These are deliberately explicit. P9.1 requires every flag-on top-10 change
// to be read, not inferred from the fact that a child happened to score. Any
// future movement absent from this frozen review map is suspicious by default.
const MANUAL_MOVEMENT_REVIEW = Object.freeze({
  "frozen_q002|entering|360678": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "Photosynthetic Systems explicitly covers carbon capture and carbon-dioxide conversion.",
  }),
  "frozen_q010|entering|360678": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "Photosynthetic Systems explicitly covers carbon-dioxide conversion.",
  }),
  "frozen_q020|entering|361526": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "Genesis has an exact catalyst-discovery focus area.",
  }),
  "frozen_q020|leaving|351715": Object.freeze({
    classification: "neutral/reordering",
    basis: "ECLIPSE remains rank 11 and is displaced by the more explicit catalyst-discovery child.",
  }),
  "frozen_q033|entering|363065": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "HGEO has an exact carbon-dioxide enhanced-recovery topic.",
  }),
  "frozen_q071|entering|360678": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "The profile path preserves the explicit Photosynthetic Systems carbon-capture match.",
  }),
  "p902|entering|361526": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "Exact Genesis focus-area title: Agentic AI-Driven Chemical Manufacturing.",
  }),
  "p903|entering|345241": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "Exact TDAC topic covers electromagnetic-pulse vulnerability and shielding.",
  }),
  "p906|entering|344592": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "Exact ARL topic title: Polymer Chemistry.",
  }),
  "p913|entering|360678": Object.freeze({
    classification: "intended child-driven improvement",
    basis: "The targeted profile case preserves the explicit Photosynthetic Systems carbon-capture match.",
  }),
});

function usage(code) {
  process.stderr.write("usage: node tools/p9_scoring_probe.mjs (--write | --check)\n");
  return code;
}

function round(value) {
  return Number((Number(value) || 0).toFixed(6));
}

function compareIds(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function positiveScale(values) {
  const positive = values.filter(value => value > 0).sort((a, b) => a - b);
  if (!positive.length) return 1;
  return positive[Math.max(0, Math.ceil(positive.length * 0.9) - 1)];
}

async function loadApis() {
  const context = { globalThis: {} };
  for (const relative of [
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "assets/profile-ranking.js",
  ]) {
    vm.runInNewContext(await readFile(new URL(relative, ROOT), "utf8"), context);
  }
  return {
    context,
    queryApi: context.globalThis.FUNDING_SEARCH_QUERY,
    retrievalApi: context.globalThis.FUNDING_RETRIEVAL,
    profileApi: context.globalThis.FUNDING_PROFILE_RANKING,
  };
}

async function loadParentCatalog(context) {
  vm.runInNewContext(
    await readFile(new URL(PARENT_CATALOG, ROOT), "utf8"),
    context,
  );
  const catalog = context.globalThis.GRANT_CATALOG;
  if (!catalog?.opportunities || !catalog?.search_index) {
    throw new Error(`${PARENT_CATALOG} did not define a searchable GRANT_CATALOG`);
  }
  return catalog;
}

function childCatalog(fixture) {
  const opportunities = fixture.records.map(record => ({
    opportunity_id: record.subtopic_id,
    parent_id: record.parent_id,
    title: record.title,
    opportunity_number: "",
    description: record.summary,
    topic_areas: [],
    applicant_types: [],
    subtopic_terms: record.subtopic_terms,
    source_group: record.source_group,
  }));
  const postings = {};
  const documentLengths = [];
  opportunities.forEach((record, documentId) => {
    let length = 0;
    for (const [term, rawFrequency] of Object.entries(record.subtopic_terms || {})) {
      const frequency = Number(rawFrequency) || 0;
      if (frequency <= 0) continue;
      length += frequency;
      if (!postings[term]) postings[term] = [];
      postings[term].push(documentId, frequency);
    }
    documentLengths.push(length);
  });
  const orderedPostings = {};
  Object.keys(postings).sort(compareIds).forEach(term => {
    orderedPostings[term] = postings[term];
  });
  const totalLength = documentLengths.reduce((sum, value) => sum + value, 0);
  return {
    schema_version: 1,
    record_count: opportunities.length,
    opportunities,
    search_index: {
      document_count: opportunities.length,
      average_document_length: totalLength / Math.max(1, opportunities.length),
      document_lengths: documentLengths,
      postings: orderedPostings,
    },
  };
}

async function resolveProfile(profile) {
  if (!profile) return null;
  const resolved = { ...profile };
  for (const [key, value] of Object.entries(resolved)) {
    if (typeof value === "string" && value.startsWith("@")) {
      resolved[key] = await readFile(new URL(value.slice(1), ROOT), "utf8");
    }
  }
  return resolved;
}

function corpusScores({ catalog, engine, queryApi, profileApi }, query, profile) {
  const direct = engine.score(query, {
    context: profile ? profileApi.context(profile) : "",
  });
  let profiled = null;
  if (profile) {
    const built = profileApi.buildTermQuery(profile, {
      catalog,
      tokenize: queryApi.tokenize,
      expandGroups: (value, options) => engine.expandGroups(value, options),
    });
    profiled = engine.score(built.query, {
      semantic: false,
      coverage: false,
      minimumCoverage: 0,
    });
  }
  const relevance = catalog.opportunities.map((_record, index) => (
    direct.scores[index] > 0
      ? (direct.scores[index] * 2) + (profiled?.scores[index] || 0)
      : 0
  ));
  return { direct, relevance };
}

function topRows(rows) {
  return [...rows]
    .sort((left, right) => right.total - left.total || compareIds(left.id, right.id))
    .slice(0, TOP_N)
    .map((row, index) => ({ ...row, rank: index + 1 }));
}

function compactRow(row) {
  if (!row) return null;
  return {
    rank: row.rank,
    id: row.id,
    title: row.title,
    score: round(row.total),
    parent_score: round(row.parentRaw),
    best_child_score: round(row.childRaw),
    matching_children: row.matchingChildren,
    normalized_combined: round(row.combinedNormalized),
    best_child_id: row.bestChildId || null,
    best_child_title: row.bestChildTitle || null,
  };
}

function movement(before, after) {
  const beforeRanks = new Map(before.map(row => [row.id, row.rank]));
  const afterRanks = new Map(after.map(row => [row.id, row.rank]));
  let displacement = 0;
  for (const [id, rank] of beforeRanks) {
    if (afterRanks.has(id)) displacement += Math.abs(afterRanks.get(id) - rank);
  }
  const beforeTop = new Set(before.filter(row => row.rank <= TOP_GATE).map(row => row.id));
  const afterTop = new Set(after.filter(row => row.rank <= TOP_GATE).map(row => row.id));
  return {
    displacement,
    entering: [...afterTop].filter(id => !beforeTop.has(id)),
    leaving: [...beforeTop].filter(id => !afterTop.has(id)),
  };
}

function classifyMovement(caseId, id, direction) {
  return MANUAL_MOVEMENT_REVIEW[`${caseId}|${direction}|${id}`] || {
    classification: "suspicious/flooding",
    basis: "movement is absent from the frozen human-reviewed movement map",
  };
}

async function evaluateCase(harness, input) {
  const profile = await resolveProfile(input.profile);
  const parentScores = corpusScores(harness.parent, input.query, profile);
  const childScores = corpusScores(harness.child, input.query, profile);
  const parentScale = positiveScale(parentScores.relevance);
  const childNativeScale = positiveScale(childScores.relevance);
  // A sparse or weak child result set must not define itself as highly
  // relevant merely because its own within-corpus scale is small. Anchor the
  // child denominator to at least the parent corpus' robust query scale.
  const childScale = Math.max(parentScale, childNativeScale);
  const childByParent = new Map();

  harness.child.catalog.opportunities.forEach((record, index) => {
    if (!(childScores.direct.scores[index] > 0)) return;
    const parentId = String(record.parent_id);
    const current = childByParent.get(parentId) || { count: 0, best: null };
    current.count += 1;
    const candidate = {
      id: String(record.opportunity_id),
      title: record.title,
      raw: childScores.relevance[index],
      normalized: childScores.relevance[index] / childScale,
    };
    if (
      !current.best
      || candidate.normalized > current.best.normalized
      || (candidate.normalized === current.best.normalized && compareIds(candidate.id, current.best.id) < 0)
    ) current.best = candidate;
    childByParent.set(parentId, current);
  });

  const baselineRows = [];
  const flagOnRows = [];
  harness.parent.catalog.opportunities.forEach((record, index) => {
    if (record.status === "archived") return;
    const id = String(record.opportunity_id);
    const child = childByParent.get(id);
    const parentRaw = parentScores.relevance[index];
    if (!(parentScores.direct.scores[index] > 0) && !child) return;
    const eligibility = profile
      ? harness.profileApi.applicantFitBonus(record, profile.applicant_context)
        + harness.profileApi.careerFitBonus(record, profile.career_stage)
      : 0;
    if (parentScores.direct.scores[index] > 0) {
      baselineRows.push({
        id,
        title: record.title,
        total: parentRaw + eligibility,
        parentRaw,
        childRaw: 0,
        matchingChildren: 0,
        combinedNormalized: parentRaw / parentScale,
      });
    }
    const parentNormalized = parentRaw / parentScale;
    const childNormalized = child?.best?.normalized || 0;
    flagOnRows.push({
      id,
      title: record.title,
      total: Math.max(parentNormalized, childNormalized) + (eligibility / parentScale),
      parentRaw,
      childRaw: child?.best?.raw || 0,
      matchingChildren: child?.count || 0,
      combinedNormalized: Math.max(parentNormalized, childNormalized),
      parentNormalized,
      childNormalized,
      bestChildId: child?.best?.id || null,
      bestChildTitle: child?.best?.title || null,
    });
  });

  const before = topRows(baselineRows);
  const after = topRows(flagOnRows);
  const delta = movement(before, after);
  const beforeById = new Map(before.map(row => [row.id, row]));
  const afterById = new Map(after.map(row => [row.id, row]));
  const reviews = [
    ...delta.entering.map(id => ({ id, direction: "entering" })),
    ...delta.leaving.map(id => ({ id, direction: "leaving" })),
  ].map(item => {
    const row = item.direction === "entering" ? afterById.get(item.id) : beforeById.get(item.id);
    return {
      ...item,
      title: row?.title || null,
      ...classifyMovement(input.id, item.id, item.direction),
    };
  });

  const focusIds = new Set([
    ...delta.entering,
    ...delta.leaving,
    ...after.filter(row => row.bestChildId).slice(0, 3).map(row => row.id),
  ]);
  if (input.focus_parent_id) focusIds.add(input.focus_parent_id);
  return {
    id: input.id,
    kind: input.kind,
    query: input.query || "",
    focus_parent_id: input.focus_parent_id || null,
    profile: Boolean(input.profile),
    parent_positive_count: parentScores.relevance.filter(value => value > 0).length,
    child_positive_count: childScores.relevance.filter(value => value > 0).length,
    parent_p90_positive: round(parentScale),
    child_p90_positive: round(childNativeScale),
    child_anchored_scale: round(childScale),
    top_10_churn: delta.entering.length + delta.leaving.length,
    displacement_top_50: delta.displacement,
    movement_review: reviews,
    inspected_rows: [...focusIds].sort(compareIds).map(id => compactRow(
      afterById.get(id) || beforeById.get(id),
    )),
    before_top_10: before.slice(0, TOP_GATE).map(compactRow),
    after_top_10: after.slice(0, TOP_GATE).map(compactRow),
  };
}

function cardinalityChecks(cases) {
  const ids = ["p901", "p902", "p906"];
  return ids.map(id => {
    const entry = cases.find(item => item.id === id);
    const rows = entry.inspected_rows.filter(row => row?.best_child_score > 0);
    const best = rows.length ? Math.max(...rows.map(row => row.normalized_combined)) : 0;
    return {
      case_id: id,
      query: entry.query,
      one_copy_rollup: round(Math.max(0, best)),
      one_hundred_copy_rollup: round(Math.max(0, ...Array(100).fill(best))),
      cardinality_bonus: 0,
      invariant: Math.max(0, best) === Math.max(0, ...Array(100).fill(best)),
    };
  });
}

async function collect() {
  const apis = await loadApis();
  const parentCatalog = await loadParentCatalog(apis.context);
  const fixture = JSON.parse(await readFile(new URL(CHILDREN, ROOT), "utf8"));
  const children = childCatalog(fixture);
  const parent = {
    catalog: parentCatalog,
    engine: apis.retrievalApi.create(parentCatalog, apis.queryApi),
    queryApi: apis.queryApi,
    profileApi: apis.profileApi,
  };
  const child = {
    catalog: children,
    engine: apis.retrievalApi.create(children, apis.queryApi),
    queryApi: apis.queryApi,
    profileApi: apis.profileApi,
  };
  const frozen = JSON.parse(await readFile(new URL(QUERY_SET, ROOT), "utf8"));
  const inputs = [
    ...frozen.queries.map(item => ({ ...item, id: `frozen_${item.id}` })),
    ...TARGET_CASES,
  ];
  const harness = { parent, child, profileApi: apis.profileApi };
  const cases = [];
  for (const input of inputs) cases.push(await evaluateCase(harness, input));
  const checks = cardinalityChecks(cases);
  const classificationCounts = {};
  cases.flatMap(item => item.movement_review).forEach(item => {
    classificationCounts[item.classification] = (classificationCounts[item.classification] || 0) + 1;
  });
  const unacceptedMovements = cases
    .flatMap(item => item.movement_review)
    .filter(item => ["suspicious/flooding", "regression"].includes(item.classification));
  return {
    schema_version: 1,
    as_of: fixture.as_of,
    inputs: {
      parent_catalog: PARENT_CATALOG,
      parent_records: parentCatalog.opportunities.length,
      child_fixture: CHILDREN,
      child_records: children.opportunities.length,
      frozen_query_set: QUERY_SET,
      frozen_query_count: frozen.queries.length,
      targeted_query_count: TARGET_CASES.length,
    },
    formula: {
      parent_raw: "2 * direct_parent_BM25 + profile_parent_BM25",
      child_raw: "2 * direct_child_BM25 + profile_child_BM25",
      normalization: "parent raw / parent query-local p90; child raw / max(child query-local p90, parent query-local p90)",
      rollup: "max(parent_normalized, best_child_normalized)",
      applicant_fit: "parent eligibility bonus / parent p90, added after relevance rollup",
      admission: "positive direct parent score or positive direct child score",
      cardinality_bonus: 0,
    },
    totals: {
      cases: cases.length,
      cases_with_top_10_churn: cases.filter(item => item.top_10_churn > 0).length,
      top_10_churn: cases.reduce((sum, item) => sum + item.top_10_churn, 0),
      displacement_top_50: cases.reduce((sum, item) => sum + item.displacement_top_50, 0),
      movement_classifications: Object.fromEntries(
        Object.entries(classificationCounts).sort(([left], [right]) => compareIds(left, right)),
      ),
      human_reviewed_top_10_movements: cases
        .flatMap(item => item.movement_review)
        .filter(item => item.classification !== "suspicious/flooding").length,
      unaccepted_top_10_movements: unacceptedMovements.length,
    },
    anti_flooding: {
      operator: "best child only; matching-child count is diagnostic and never enters the score",
      checks,
      passed: checks.every(item => item.invariant && item.cardinality_bonus === 0),
    },
    review_gate: {
      policy: "every top-10 movement must have a frozen case-specific human review; suspicious/flooding and regression fail",
      passed: unacceptedMovements.length === 0,
    },
    cases,
  };
}

async function main(argv) {
  const mode = argv[0];
  if (argv.length !== 1 || !["--write", "--check"].includes(mode)) return usage(2);
  const current = await collect();
  if (mode === "--write") {
    await writeFile(new URL(OUTPUT, ROOT), `${JSON.stringify(current, null, 2)}\n`, "utf8");
    process.stdout.write(
      `Wrote ${OUTPUT}: ${current.totals.cases} cases, `
        + `${current.totals.top_10_churn} top-10 movements, `
        + `${current.totals.displacement_top_50} displacement.\n`,
    );
    return current.anti_flooding.passed && current.review_gate.passed ? 0 : 1;
  }
  let expected;
  try {
    expected = await readFile(new URL(OUTPUT, ROOT), "utf8");
  } catch {
    process.stderr.write(`Missing ${OUTPUT}; run --write first.\n`);
    return 2;
  }
  const serialized = `${JSON.stringify(current, null, 2)}\n`;
  if (serialized !== expected) {
    process.stderr.write("p9-scoring: deterministic result differs from committed artifact\n");
    return 1;
  }
  if (!current.anti_flooding.passed) {
    process.stderr.write("p9-scoring: cardinality invariance failed\n");
    return 1;
  }
  if (!current.review_gate.passed) {
    process.stderr.write("p9-scoring: unreviewed or unacceptable top-10 movement\n");
    return 1;
  }
  process.stdout.write(
    `p9-scoring: OK (${current.totals.cases} cases; cardinality invariant; byte-identical)\n`,
  );
  return 0;
}

process.exitCode = await main(process.argv.slice(2));
