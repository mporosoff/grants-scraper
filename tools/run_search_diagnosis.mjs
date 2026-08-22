#!/usr/bin/env node
// Phase 1 v1.2.0 search-quality diagnosis.
//
// This runner deliberately calls the production query, retrieval, rollup, and
// explanation modules. Alternative field indexes are measurement inputs; no
// scoring or admission algorithm is duplicated here. The sealed holdout frame
// is not accepted by this program and is first eligible for execution in Phase 4.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import { performance } from "node:perf_hooks";
import vm from "node:vm";

const ROOT = new URL("../", import.meta.url);
const FRAME_PATH = "evaluation/search_v2_frame.json";
const TRUTH_PATH = "evaluation/search_v2_truth.json";
const BASELINE_PATH = "evaluation/search_v2_baseline.json";
const DIAGNOSIS_PATH = "evaluation/search_v2_diagnosis.json";
const ABLATION_PATH = "evaluation/search_v2_field_ablation.json";
const TOP_N = 50;

const PARENT_DEFAULT_WEIGHTS = Object.freeze({
  parent_title: 7,
  opportunity_number: 7,
  agency: 3,
  topic_area: 5,
  discipline: 4,
  funding_category: 3,
  funding_instrument: 2,
  applicant_type: 1,
  eligibility: 1,
  parent_description: 1,
  citation_source_evidence: 1,
});

const BROAD_OPPORTUNITY_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science financial assistance|long[\s-]?range|research announcement|\broses\b|omnibus|unsolicited proposal|open topic|financial assistance program|annual program statement|office[ -]wide|open[ -]scope solicitation/i;

function assignmentJson(source) {
  return JSON.parse(source.slice(source.indexOf("{"), source.lastIndexOf(";")).trim());
}

function sha256(source) {
  return createHash("sha256").update(source).digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

function quantile(values, fraction) {
  if (!values.length) return 0;
  const ordered = values.slice().sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)];
}

function fieldValues(record, weights = PARENT_DEFAULT_WEIGHTS) {
  return [
    ["parent_title", record.title || "", weights.parent_title],
    ["opportunity_number", record.opportunity_number || "", weights.opportunity_number],
    ["agency", record.agency || "", weights.agency],
    ["topic_area", (record.topic_areas || []).join(" "), weights.topic_area],
    ["discipline", (record.disciplines || []).join(" "), weights.discipline],
    ["funding_category", (record.funding_categories || []).join(" "), weights.funding_category],
    ["funding_instrument", (record.funding_instruments || []).join(" "), weights.funding_instrument],
    ["applicant_type", (record.applicant_types || []).join(" "), weights.applicant_type],
    ["eligibility", record.eligibility_text || "", weights.eligibility],
    ["parent_description", record.description || "", weights.parent_description],
    ["citation_source_evidence", record.document_search_text || "", weights.citation_source_evidence],
  ].filter(([_name, _value, weight]) => Number(weight) > 0);
}

function childFieldValues(record, configuration = {}) {
  const titleWeight = Number(configuration.childTitle ?? 1);
  const summaryWeight = Number(configuration.childSummary ?? 1);
  const topicWeight = Number(configuration.childTopic ?? 0);
  return [
    ["child_title", record.title || "", titleWeight],
    ["child_summary", record.description || record.summary || "", summaryWeight],
    ["child_topic", [
      ...(record.topic_areas || []),
      ...(record.program_area_labels || []),
    ].join(" "), topicWeight],
  ].filter(([_name, _value, weight]) => weight > 0);
}

function buildIndex(records, queryApi, fields, { maximumDocumentFrequency = true } = {}) {
  const postings = new Map();
  const documentLengths = [];
  records.forEach((record, documentId) => {
    const weighted = new Map();
    fields(record).forEach(([_name, value, weight]) => {
      const counts = new Map();
      queryApi.tokenize(value).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
      counts.forEach((count, term) => {
        weighted.set(term, (weighted.get(term) || 0) + (count * Number(weight)));
      });
    });
    documentLengths.push([...weighted.values()].reduce((sum, value) => sum + value, 0) || 1);
    weighted.forEach((frequency, term) => {
      if (!postings.has(term)) postings.set(term, []);
      postings.get(term).push(documentId, frequency);
    });
  });
  const maximum = Math.max(1, Math.floor(records.length * .8));
  const compact = Object.fromEntries([...postings]
    .filter(([_term, values]) => !maximumDocumentFrequency || values.length / 2 <= maximum)
    .sort(([left], [right]) => left.localeCompare(right)));
  return {
    algorithm: "bm25",
    document_count: records.length,
    average_document_length: documentLengths.length
      ? documentLengths.reduce((sum, value) => sum + value, 0) / documentLengths.length
      : 0,
    document_lengths: documentLengths,
    postings: compact,
    ...(records.some(record => record.subtopic_id)
      ? { record_ids: records.map(record => String(record.subtopic_id)) }
      : {}),
  };
}

function catalogWithIndex(catalog, searchIndex) {
  return { ...catalog, search_index: searchIndex };
}

function copyScoreResult(result, gate = null) {
  if (!gate) return result;
  const scores = Float64Array.from(result.scores, (value, index) => (
    gate.scores[index] > 0 ? value : 0
  ));
  return { ...result, scores };
}

function emptyScores(count) {
  return { scores: new Float64Array(count), evidence: null };
}

async function loadHarness() {
  const sources = {};
  for (const relative of [
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "assets/match-explain.js",
    "data/opportunities.js",
    "data/subtopics.js",
  ]) sources[relative] = await readFile(new URL(relative, ROOT), "utf8");

  const context = { globalThis: {} };
  for (const relative of [
    "assets/search-query.js",
    "assets/search-retrieval.js",
    "assets/match-explain.js",
  ]) vm.runInNewContext(sources[relative], context);

  const catalog = assignmentJson(sources["data/opportunities.js"]);
  const sidecar = assignmentJson(sources["data/subtopics.js"]);
  const queryApi = context.globalThis.FUNDING_SEARCH_QUERY;
  const retrievalApi = context.globalThis.FUNDING_RETRIEVAL;
  const explanationApi = context.globalThis.FUNDING_MATCH_EXPLAIN;
  const childCatalog = retrievalApi.createChildCatalog(sidecar);
  return {
    sources,
    catalog,
    childCatalog,
    queryApi,
    retrievalApi,
    explanationApi,
    hashes: Object.fromEntries(Object.entries(sources).map(([path, source]) => [path, sha256(source)])),
  };
}

function makeVariantHarness(base, definition) {
  const parentWeights = { ...PARENT_DEFAULT_WEIGHTS, ...(definition.parentWeights || {}) };
  const parentCatalog = definition.parentWeights
    ? catalogWithIndex(base.catalog, buildIndex(
        base.catalog.opportunities,
        base.queryApi,
        record => fieldValues(record, parentWeights),
      ))
    : base.catalog;
  const childCatalog = definition.childWeights
    ? catalogWithIndex(base.childCatalog, buildIndex(
        base.childCatalog.opportunities,
        base.queryApi,
        record => childFieldValues(record, definition.childWeights),
        { maximumDocumentFrequency: false },
      ))
    : base.childCatalog;
  const parentEngine = base.retrievalApi.create(
    parentCatalog,
    base.queryApi,
    definition.scoringConfiguration || {},
  );
  const childEngine = base.retrievalApi.create(
    childCatalog,
    base.queryApi,
    definition.scoringConfiguration || {},
  );

  let gate = null;
  if (definition.admissionFields === "substantive") {
    const gateParentCatalog = catalogWithIndex(base.catalog, buildIndex(
      base.catalog.opportunities,
      base.queryApi,
      record => fieldValues(record, {
        ...PARENT_DEFAULT_WEIGHTS,
        agency: 0,
        topic_area: 0,
        discipline: 0,
        funding_category: 0,
        funding_instrument: 0,
        applicant_type: 0,
        eligibility: 0,
      }),
    ));
    const gateChildCatalog = catalogWithIndex(base.childCatalog, buildIndex(
      base.childCatalog.opportunities,
      base.queryApi,
      record => childFieldValues(record, { childTitle: 1, childSummary: 1, childTopic: 0 }),
      { maximumDocumentFrequency: false },
    ));
    gate = {
      parent: base.retrievalApi.create(gateParentCatalog, base.queryApi),
      child: base.retrievalApi.create(gateChildCatalog, base.queryApi),
    };
  }
  return { ...base, parentCatalog, childCatalog, parentEngine, childEngine, gate };
}

function rankQuery(harness, query, { evidence = true } = {}) {
  const started = performance.now();
  const options = { evidence };
  let parentDirect = harness.parentEngine.score(query, options);
  let childDirect = harness.childEngine.score(query, options);
  if (harness.gate) {
    parentDirect = copyScoreResult(parentDirect, harness.gate.parent.score(query));
    childDirect = copyScoreResult(childDirect, harness.gate.child.score(query));
  }
  const rolled = harness.retrievalApi.rollupScores({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentDirect,
    parentProfile: emptyScores(harness.parentCatalog.opportunities.length),
    childDirect,
    childProfile: emptyScores(harness.childCatalog.opportunities.length),
    eligibilityBonuses: new Array(harness.parentCatalog.opportunities.length).fill(0),
  });
  const parentById = new Map(harness.parentCatalog.opportunities.map((record, index) => [
    String(record.opportunity_id), { record, index },
  ]));
  const rows = rolled.rows.flatMap(row => {
    const parent = parentById.get(row.id);
    if (!parent || parent.record.status === "archived") return [];
    return [{ ...row, record: parent.record, index: parent.index }];
  });
  rows.sort((left, right) => right.score - left.score || left.id.localeCompare(right.id));
  return {
    query,
    rows,
    parentDirect,
    childDirect,
    queryPlan: harness.parentEngine.expandGroups(query),
    diagnostics: parentDirect.diagnostics,
    scales: rolled.scales,
    latencyMs: performance.now() - started,
  };
}

function postingFrequency(catalog, term, documentId) {
  const values = catalog.search_index.postings[term] || [];
  for (let cursor = 0; cursor < values.length; cursor += 2) {
    if (values[cursor] === documentId) return Number(values[cursor + 1]);
    if (values[cursor] > documentId) break;
  }
  return 0;
}

function traceEvidence({ catalog, queryApi, record, documentId, evidence, child = false }) {
  if (!evidence) return null;
  const fields = child
    ? childFieldValues(record, { childTitle: 1, childSummary: 1, childTopic: 0 })
    : fieldValues(record);
  const tokenCounts = new Map(fields.map(([name, value, weight]) => {
    const counts = new Map();
    queryApi.tokenize(value).forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
    return [name, { counts, weight }];
  }));
  const groups = (evidence.groups || []).map(group => ({
    source: group.source,
    contribution: number(group.contribution),
    matched_terms: (group.matchedTermContributions || []).map(item => {
      const indexedFrequency = postingFrequency(catalog, item.term, documentId);
      const fieldRows = [];
      let attributedFrequency = 0;
      tokenCounts.forEach(({ counts, weight }, field) => {
        const rawFrequency = Number(counts.get(item.term) || 0);
        const weightedFrequency = rawFrequency * Number(weight);
        if (!weightedFrequency) return;
        attributedFrequency += weightedFrequency;
        fieldRows.push({ field, raw_frequency: rawFrequency, weight, weighted_frequency: weightedFrequency });
      });
      if (indexedFrequency > attributedFrequency) {
        fieldRows.push({
          field: child ? "collapsed_child_source_excerpt" : "collapsed_unattributed",
          raw_frequency: null,
          weight: null,
          weighted_frequency: indexedFrequency - attributedFrequency,
        });
      }
      const denominator = fieldRows.reduce((sum, row) => sum + row.weighted_frequency, 0) || 1;
      fieldRows.forEach(row => {
        row.allocated_contribution = number(Number(item.contribution) * row.weighted_frequency / denominator);
      });
      return {
        term: item.term,
        contribution: number(item.contribution),
        indexed_frequency: indexedFrequency,
        fields: fieldRows,
      };
    }),
  }));
  return {
    groups,
    admission: evidence.admission,
    bonuses: {
      exact_title_phrase: evidence.exactTitlePhrase,
      exact_opportunity_number: evidence.exactOpportunityNumber,
      trigrams: Array.from(evidence.trigrams || []),
    },
  };
}

function serializePlan(groups) {
  return groups.map(group => ({
    source: group.source,
    terms: Array.from(group.terms || [], item => ({ term: item.term, weight: item.weight })),
    minimum_evidence: group.minimumEvidence || null,
    evidence_alternatives: group.evidenceAlternatives || null,
    evidence_phrases: group.evidencePhrases || null,
    evidence_windows: group.evidenceWindows || null,
    evidence_mode: group.evidenceMode || "all",
    required_unless_topic: group.requiredUnlessTopic || null,
    required_always: group.requiredAlways === true,
    expansion: group.expansion || null,
  }));
}

function compactRow(harness, ranked, row, rank, truth) {
  const childIndex = row.bestChild
    ? harness.childCatalog.opportunities.indexOf(row.bestChild.record)
    : -1;
  const parentEvidence = ranked.parentDirect.evidence?.[row.index] || null;
  const childEvidence = childIndex >= 0
    ? ranked.childDirect.evidence?.[childIndex] || null
    : null;
  const broad = BROAD_OPPORTUNITY_RE.test(
    `${row.record.title || ""} ${String(row.record.description || "").slice(0, 1_500)}`,
  );
  const reasons = harness.explanationApi.build({
    parent: { record: row.record, broad, directEvidence: parentEvidence },
    bestChild: row.bestChild,
  });
  return {
    rank,
    id: row.id,
    number: row.record.opportunity_number || "",
    title: row.record.title,
    agency: row.record.agency,
    score: number(row.score),
    parent_admitted: row.parentAdmitted,
    parent_score: number(row.parentRaw),
    child_score: number(row.bestChild?.raw || 0),
    child_drove_match: row.childDroveMatch,
    best_child: row.bestChild ? {
      id: row.bestChild.id,
      title: row.bestChild.record.title,
      publication_state: row.bestChild.record.publication_state,
      trace: traceEvidence({
        catalog: harness.childCatalog,
        queryApi: harness.queryApi,
        record: row.bestChild.record,
        documentId: childIndex,
        evidence: childEvidence,
        child: true,
      }),
    } : null,
    truth: truth.adjudications[row.id] || null,
    parent_trace: traceEvidence({
      catalog: harness.parentCatalog,
      queryApi: harness.queryApi,
      record: row.record,
      documentId: row.index,
      evidence: parentEvidence,
    }),
    rendered_explanations: Array.from(reasons),
  };
}

function nearMiss(harness, ranked, id, truth) {
  const index = harness.parentCatalog.opportunities.findIndex(record => (
    String(record.opportunity_id) === id
  ));
  if (index < 0) return { id, catalog_state: "missing" };
  const record = harness.parentCatalog.opportunities[index];
  const parentEvidence = ranked.parentDirect.evidence?.[index] || null;
  const childMatches = harness.childCatalog.opportunities.flatMap((child, childIndex) => (
    String(child.parent_id) === id && ranked.childDirect.scores[childIndex] > 0
      ? [{ id: child.subtopic_id, title: child.title, score: number(ranked.childDirect.scores[childIndex]) }]
      : []
  )).sort((left, right) => right.score - left.score);
  return {
    id,
    title: record.title,
    truth: truth.adjudications[id] || null,
    parent_admission: parentEvidence?.admission || null,
    matching_children: childMatches.slice(0, 10),
  };
}

function queryIsReeFamily(item) {
  return /\b(?:ree|rees|lanthanide)|rare[ .-]?earth/i.test(item.query);
}

async function collectBaseline(base, frame, truth) {
  const harness = makeVariantHarness(base, {});
  const results = [];
  const unlabelled = new Set();
  for (const item of frame.queries) {
    const ranked = rankQuery(harness, item.query);
    const traceLimit = queryIsReeFamily(item) ? TOP_N : 10;
    const top = ranked.rows.slice(0, traceLimit).map((row, index) => (
      compactRow(harness, ranked, row, index + 1, truth)
    ));
    if (queryIsReeFamily(item)) {
      ranked.rows.forEach(row => {
        if (!truth.adjudications[row.id]) unlabelled.add(`${item.id}:${row.id}`);
      });
    }
    results.push({
      id: item.id,
      discipline: item.discipline,
      kind: item.kind,
      query: item.query,
      query_plan: serializePlan(ranked.queryPlan),
      candidate_count: ranked.rows.length,
      latency_ms: number(ranked.latencyMs),
      diagnostics: ranked.diagnostics,
      normalization_scales: ranked.scales,
      top_results: top,
      required_anchor_status: truth.required_anchor_ids.map(id => {
        const rank = ranked.rows.findIndex(row => row.id === id);
        return rank >= 0
          ? { id, admitted: true, rank: rank + 1 }
          : { ...nearMiss(harness, ranked, id, truth), admitted: false };
      }),
    });
  }
  if (unlabelled.size) {
    throw new Error(`REE-family results lack frozen truth labels: ${[...unlabelled].join(", ")}`);
  }
  return {
    schema_version: 1,
    frozen_at: frame.frozen_at,
    frame: FRAME_PATH,
    truth: TRUTH_PATH,
    catalog_sha256: base.hashes["data/opportunities.js"],
    sidecar_sha256: base.hashes["data/subtopics.js"],
    query_count: results.length,
    holdout_status: "sealed_and_unopened",
    results,
  };
}

const VARIANTS = Object.freeze([
  { id: "production", label: "Current production weights and boosts" },
  {
    id: "no_exact_title_bonus",
    label: "Exact-title phrase bonus disabled",
    scoringConfiguration: { exactTitleMatchBoost: 0, titlePhraseBoost: 0 },
  },
  {
    id: "parent_title_flattened",
    label: "Parent title weight reduced from 7 to 3",
    parentWeights: { parent_title: 3 },
  },
  {
    id: "parent_child_titles_separated",
    label: "Parent title weight 3; child title weight 7",
    parentWeights: { parent_title: 3 },
    childWeights: { childTitle: 7, childSummary: 1, childTopic: 0 },
  },
  {
    id: "metadata_rerank_only",
    label: "Agency/topic/discipline/category metadata cannot admit",
    admissionFields: "substantive",
  },
  {
    id: "description_child_summary_strengthened",
    label: "Parent description and child summary strengthened to 3",
    parentWeights: { parent_description: 3 },
    childWeights: { childTitle: 1, childSummary: 3, childTopic: 0 },
  },
  {
    id: "citation_source_strengthened",
    label: "Citation-backed source evidence strengthened to 3",
    parentWeights: { citation_source_evidence: 3 },
  },
  {
    id: "title_removed_diagnostic",
    label: "Parent and child title evidence removed",
    parentWeights: { parent_title: 0 },
    childWeights: { childTitle: 0, childSummary: 1, childTopic: 0 },
    scoringConfiguration: { exactTitleMatchBoost: 0, titlePhraseBoost: 0 },
  },
]);

async function collectAblation(base, frame, truth) {
  const variants = [];
  const admissionsByVariant = new Map();
  for (const definition of VARIANTS) {
    const harness = makeVariantHarness(base, definition);
    const queryResults = [];
    const latencies = [];
    const admissions = new Map();
    for (const item of frame.queries) {
      const ranked = rankQuery(harness, item.query, { evidence: false });
      latencies.push(ranked.latencyMs);
      admissions.set(item.id, new Set(ranked.rows.map(row => row.id)));
      queryResults.push({
        id: item.id,
        query: item.query,
        candidate_count: ranked.rows.length,
        top_10: ranked.rows.slice(0, 10).map((row, index) => ({
          rank: index + 1,
          id: row.id,
          title: row.record.title,
          child_driven: row.childDroveMatch,
        })),
        known_negative_admissions: ranked.rows
          .filter(row => truth.known_negative_ids.includes(row.id))
          .map(row => row.id),
        anchor_ranks: Object.fromEntries(truth.required_anchor_ids.map(id => {
          const rank = ranked.rows.findIndex(row => row.id === id);
          return [id, rank < 0 ? null : rank + 1];
        })),
        child_only_admissions: ranked.rows.filter(row => !row.parentAdmitted).length,
      });
    }
    admissionsByVariant.set(definition.id, admissions);
    variants.push({
      id: definition.id,
      label: definition.label,
      query_count: queryResults.length,
      total_candidate_admissions: queryResults.reduce((sum, row) => sum + row.candidate_count, 0),
      total_known_negative_admissions: queryResults.reduce(
        (sum, row) => sum + row.known_negative_admissions.length,
        0,
      ),
      queries_with_zero_results: queryResults.filter(row => row.candidate_count === 0).length,
      child_only_admissions: queryResults.reduce((sum, row) => sum + row.child_only_admissions, 0),
      latency_ms: {
        median: number(quantile(latencies, .5)),
        p95: number(quantile(latencies, .95)),
        maximum: number(Math.max(...latencies)),
      },
      queries: queryResults,
    });
  }
  const production = admissionsByVariant.get("production");
  const noTitle = admissionsByVariant.get("title_removed_diagnostic");
  const titleOnly = Object.fromEntries(frame.queries.map(item => [
    item.id,
    [...production.get(item.id)].filter(id => !noTitle.get(item.id).has(id)),
  ]));
  return {
    schema_version: 1,
    frozen_at: frame.frozen_at,
    frame: FRAME_PATH,
    interpretation: "Measurement-only ablations. They diagnose field sensitivity and do not select Phase 2 production weights.",
    variants,
    production_title_only_admissions: titleOnly,
  };
}

function buildDiagnosis(frame, truth, baseline, ablation) {
  const result = id => baseline.results.find(item => item.id === id);
  const production = ablation.variants.find(item => item.id === "production");
  const noTitleBonus = ablation.variants.find(item => item.id === "no_exact_title_bonus");
  const titleRemoved = ablation.variants.find(item => item.id === "title_removed_diagnostic");
  return {
    schema_version: 1,
    frozen_at: frame.frozen_at,
    starting_main_sha: frame.starting_main_sha,
    live_asset_reconciliation: "identical_to_local_main",
    holdout_status: "sealed_and_unopened",
    reported_failures: {
      REE: { candidate_count: result("ree_01").candidate_count, ids: result("ree_01").top_results.map(row => row.id) },
      REEs: { candidate_count: result("ree_02").candidate_count, ids: result("ree_02").top_results.map(row => row.id) },
      REE_separations: { candidate_count: result("ree_03").candidate_count, ids: result("ree_03").top_results.map(row => row.id) },
    },
    root_causes: [
      {
        id: "RC-1",
        status: "confirmed",
        mechanism: "The tokenizer leaves the four-character plural REEs as rees. The protected rare-earth branch recognizes ree and lanthanide but not rees, so the generic alias expansion runs without rare-earth evidence guards.",
        evidence_query: "REEs",
        effect: "NASA Earth/element, rare-disease, rare-cancer, and unrelated child-token results are admitted."
      },
      {
        id: "RC-2",
        status: "confirmed",
        mechanism: "Rare-earth evidence alternatives test token co-occurrence, not phrase adjacency/proximity. The YSEALI policy workshop therefore satisfies rare + earth even though it is not technical R&D.",
        evidence_query: "REE",
        effect: "A policy/workshop notice is the sole result for REE, ree, rare earth, rare earth elements, and lanthanide extraction."
      },
      {
        id: "RC-3",
        status: "confirmed",
        mechanism: "requiredUnlessTopic allows the Separations and membranes topic to substitute for the required rare-earth target concept.",
        evidence_query: "ionic liquids for REE extraction",
        effect: "Five method-only or unrelated programs are admitted without rare-earth evidence."
      },
      {
        id: "RC-4",
        status: "confirmed",
        mechanism: "Hyphenated and dotted scientific forms are not normalized into the protected phrase/acronym representation.",
        evidence_query: "R.E.E. / rare-earth elements",
        effect: "Both punctuation variants return zero results."
      },
      {
        id: "RC-5",
        status: "confirmed",
        mechanism: "The current published catalog contains no direct rare-earth technical-R&D parent or publishable child. DOE Office of Science, Genesis, and NSF CPS are adjudicated broad-program homes only.",
        evidence_query: "REE separations",
        effect: "Strict target evidence alone produces a valid no-direct-match state; broad-program recall requires an explicit display policy rather than synonym leakage."
      },
      {
        id: "RC-6",
        status: "confirmed",
        mechanism: "The parent index collapses all weighted fields into one posting frequency and the child index stores collapsed source terms. The explanation layer receives terms and aggregate contributions but not causal fields.",
        evidence_query: "catalysis",
        effect: "Rendered reasons fall back to tautologies such as Search terms matched: catalysis."
      }
    ],
    rejected_hypotheses: [
      "stale live search assets",
      "live/local catalog mismatch",
      "parent-only search caused by a sidecar race",
      "profile, eligibility, freshness, filters, or sort as the reported public-search cause",
      "title boost as the primary REE admission mechanism"
    ],
    field_ablation_summary: {
      production_admissions: production.total_candidate_admissions,
      no_title_bonus_admissions: noTitleBonus.total_candidate_admissions,
      title_removed_admissions: titleRemoved.total_candidate_admissions,
      interpretation: "Title influence changes cross-domain ranking and some admissions, but disabling title bonuses does not repair the REE acronym/phrase failures. The motivating defect is protected-concept admission; field provenance remains a systemic explanation limitation."
    },
    source_coverage: {
      direct_ree_fit_count: truth.current_direct_ree_fit_count,
      broad_program_anchor_ids: truth.required_anchor_ids,
      stop_condition: "No ingestion repair is required to represent the adjudicated broad homes, but the absence of a current direct REE call must remain visible rather than being hidden by false positives."
    },
    recommended_repair_track: "B",
    scope_authorization: "A bounded protected-concept/query-admission correction is sufficient for retrieval. Add causal field/hierarchy provenance for explanations without replacing the full BM25 index architecture.",
    work_eliminated: [
      "No embedding or query-time model layer.",
      "No wholesale BM25F rewrite in Phase 2.",
      "No intuitive global title/description reweighting.",
      "No source-ingestion rebuild solely to fabricate direct REE recall.",
      "No artificial search delay."
    ],
    unresolved_product_policy: "Choose whether adjudicated broad-program homes appear in a separately labeled Broader program fit tier when direct target evidence is absent."
  };
}

async function main() {
  if (process.argv.includes("--holdout")) {
    throw new Error("Phase 1 refuses to open the sealed holdout. Phase 4 must use the release-candidate runner.");
  }
  const write = process.argv.includes("--write");
  const frameSource = await readFile(new URL(FRAME_PATH, ROOT), "utf8");
  const truthSource = await readFile(new URL(TRUTH_PATH, ROOT), "utf8");
  const frame = JSON.parse(frameSource);
  const truth = JSON.parse(truthSource);
  const harness = await loadHarness();
  const baseline = await collectBaseline(harness, frame, truth);
  baseline.frame_sha256 = sha256(frameSource);
  baseline.truth_sha256 = sha256(truthSource);
  const ablation = await collectAblation(harness, frame, truth);
  ablation.frame_sha256 = baseline.frame_sha256;
  const diagnosis = buildDiagnosis(frame, truth, baseline, ablation);
  diagnosis.frame_sha256 = baseline.frame_sha256;
  diagnosis.truth_sha256 = baseline.truth_sha256;

  if (write) {
    for (const [path, payload] of [
      [BASELINE_PATH, baseline],
      [ABLATION_PATH, ablation],
      [DIAGNOSIS_PATH, diagnosis],
    ]) await writeFile(new URL(path, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    process.stdout.write(
      `Wrote ${BASELINE_PATH}, ${ABLATION_PATH}, and ${DIAGNOSIS_PATH}: `
      + `${frame.queries.length} development queries; holdout sealed.\n`,
    );
  } else {
    process.stdout.write(`${JSON.stringify({ baseline, ablation, diagnosis }, null, 2)}\n`);
  }
}

if (String(process.argv[1] || "").replace(/\\/g, "/").endsWith("/tools/run_search_diagnosis.mjs")) {
  await main();
}

export {
  buildIndex,
  collectAblation,
  collectBaseline,
  loadHarness,
  makeVariantHarness,
  rankQuery,
};
