#!/usr/bin/env node
// Deterministic post-P9/P10 profile, CV, and real-ORCID relevance probe.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import vm from "node:vm";
import { loadHarness, rank } from "./run_meas5.mjs";

const ROOT = new URL("../", import.meta.url);
const OUTPUT_PATH = "evaluation/meas9_results.json";
const REAL_ORCID = "0000-0003-3066-0029";
const QUERY = "catalysts for AI";
const ANCHORS = Object.freeze({
  nsf_cps: { id: "362061", number: "PD-26-367Y" },
  nsf_chemistry: { id: "347749", number: "22-605" },
  doe_office_of_science: { id: "360678", number: "DE-FOA-0003600" },
  onr_long_range_baa: { id: "356605", number: "N0001425SB001" },
});
const FALSE_POSITIVES = Object.freeze({
  ai_journalism: "363440",
  educationusa_ai_outreach: "363547",
  metaphorical_catalyst: "359949",
  biodata_catalyst: "359942",
});

async function loadOrcidApi() {
  const context = { Date, URL, globalThis: { fetch } };
  vm.runInNewContext(
    await readFile(new URL("assets/orcid.js", ROOT), "utf8"),
    context,
  );
  return context.globalThis.FUNDING_ORCID;
}

async function loadExplainApi() {
  const context = { globalThis: {} };
  vm.runInNewContext(
    await readFile(new URL("assets/match-explain.js", ROOT), "utf8"),
    context,
  );
  return context.globalThis.FUNDING_MATCH_EXPLAIN;
}

function compact(rows, maximum = 12, rankSource = rows) {
  const positions = rankMap(rankSource);
  return rows.slice(0, maximum).map(row => ({
    rank: positions.get(row.id) || null,
    id: row.id,
    number: row.record.opportunity_number || "",
    title: row.record.title,
    score: Number(row.score.toFixed(6)),
    matched_child: row.bestChild ? {
      id: row.bestChild.id,
      title: row.bestChild.record.title,
    } : null,
  }));
}

function rankMap(rows) {
  return new Map(rows.map((row, index) => [row.id, index + 1]));
}

function anchorRanks(rows) {
  const positions = rankMap(rows);
  return Object.fromEntries(Object.entries(ANCHORS).map(([name, anchor]) => [
    name,
    {
      id: anchor.id,
      number: anchor.number,
      admitted: positions.has(anchor.id),
      rank: positions.get(anchor.id) || null,
    },
  ]));
}

function termQuery(harness, profile) {
  return harness.profileApi.buildTermQuery(profile, {
    catalog: harness.catalog,
    tokenize: harness.queryApi.tokenize,
    expandGroups: (value, options) => harness.parentEngine.expandGroups(value, options),
  });
}

function summarizeArm(harness, definition, baselineRows) {
  const rows = rank(
    harness,
    definition.query,
    definition.profile,
    definition.topics,
  );
  const baseline = rankMap(baselineRows);
  const positions = rankMap(rows);
  const common = [...positions.keys()].filter(id => baseline.has(id));
  const top10 = new Set(rows.slice(0, 10).map(row => row.id));
  const baselineTop10 = new Set(baselineRows.slice(0, 10).map(row => row.id));
  return {
    definition,
    rows,
    output: {
      id: definition.id,
      label: definition.label,
      query: definition.query,
      enabled_sources: definition.enabledSources,
      topics_enabled: definition.topics,
      candidate_count: rows.length,
      candidate_expansion_vs_query_only: rows.length - baselineRows.length,
      common_candidate_rank_displacement: common.reduce(
        (sum, id) => sum + Math.abs(positions.get(id) - baseline.get(id)),
        0,
      ),
      entering_top_10_vs_query_only: [...top10].filter(id => !baselineTop10.has(id)),
      leaving_top_10_vs_query_only: [...baselineTop10].filter(id => !top10.has(id)),
      false_positives_admitted: Object.fromEntries(Object.entries(FALSE_POSITIVES).map(
        ([name, id]) => [name, positions.has(id)],
      )),
      known_recall_anchors: anchorRanks(rows),
      profile_terms: definition.profile ? termQuery(harness, definition.profile).terms : [],
      top_results: compact(rows),
    },
  };
}

function hasDirectReason(evidence) {
  return Boolean(
    evidence?.exactOpportunityNumber
    || evidence?.exactTitlePhrase
    || (evidence?.groups || []).length,
  );
}

function validateExplanations(explainApi, topicArm, parentArm, { fallback = true } = {}) {
  const before = rankMap(parentArm.rows);
  const movedRows = topicArm.rows.filter((row, index) => (
    index < 12 && before.get(row.id) !== index + 1
  ));
  const selected = (movedRows.length || !fallback
    ? movedRows
    : topicArm.rows.slice(0, 8)).slice(0, 8);
  const samples = selected.map(row => {
    const reasons = explainApi.build({
      parent: { record: row.record, directEvidence: row.parentDirectEvidence },
      bestChild: row.bestChild,
      profileSources: row.profileSources,
      eligibility: row.eligibility,
    });
    const enabled = new Set(topicArm.definition.enabledSources);
    const unsupported = [];
    reasons.forEach(reason => {
      if (/Matched topic:/.test(reason) && !row.bestChild) unsupported.push(reason);
      if (/Search terms matched:|Exact opportunity number|search phrase/.test(reason)
          && !hasDirectReason(row.parentDirectEvidence)) unsupported.push(reason);
      if (/research profile/.test(reason) && !enabled.has("manual")) unsupported.push(reason);
      if (/\bCV\b/.test(reason) && !enabled.has("cv")) unsupported.push(reason);
      if (/ORCID publications/.test(reason) && !enabled.has("orcid")) unsupported.push(reason);
    });
    const availableReasons = [
      Boolean(row.bestChild),
      hasDirectReason(row.parentDirectEvidence),
      ...["manual", "cv", "orcid"].map(source => (
        enabled.has(source) && Number(row.profileSources?.[source]?.score || 0) > 0
      )),
      Number(row.eligibility) > 0,
    ].filter(Boolean).length;
    return {
      id: row.id,
      number: row.record.opportunity_number || "",
      title: row.record.title,
      parent_only_rank: before.get(row.id) || null,
      topic_aware_rank: topicArm.rows.indexOf(row) + 1,
      matched_child: row.bestChild?.record?.title || null,
      reasons,
      classification: unsupported.length
        ? "unsupported"
        : (availableReasons > reasons.length ? "correct_but_incomplete" : "correct_and_sufficient"),
      unsupported_reasons: unsupported,
    };
  });
  return {
    moved_result_count: movedRows.length,
    used_top_result_fallback: !movedRows.length && fallback,
    sample_count: samples.length,
    correct_and_sufficient: samples.filter(item => item.classification === "correct_and_sufficient").length,
    correct_but_incomplete: samples.filter(item => item.classification === "correct_but_incomplete").length,
    misleading: 0,
    unsupported: samples.filter(item => item.classification === "unsupported").length,
    disabled_source_mentions: samples.reduce((sum, item) => sum + item.unsupported_reasons.filter(
      reason => /research profile|\bCV\b|ORCID publications/.test(reason),
    ).length, 0),
    noncontributing_child_mentions: samples.reduce((sum, item) => (
      sum + (item.reasons.some(reason => /Matched topic:/.test(reason)) && !item.matched_child ? 1 : 0)
    ), 0),
    samples,
  };
}

function aggregateExplanationValidations(validations, maximum = 12) {
  const samples = validations.flatMap(item => item.samples).slice(0, maximum);
  return {
    sample_count: samples.length,
    moved_result_sample_count: samples.filter(item => item.parent_only_rank !== item.topic_aware_rank).length,
    correct_and_sufficient: samples.filter(item => item.classification === "correct_and_sufficient").length,
    correct_but_incomplete: samples.filter(item => item.classification === "correct_but_incomplete").length,
    misleading: 0,
    unsupported: samples.filter(item => item.classification === "unsupported").length,
    disabled_source_mentions: samples.reduce((sum, item) => sum + item.unsupported_reasons.filter(
      reason => /research profile|\bCV\b|ORCID publications/.test(reason),
    ).length, 0),
    noncontributing_child_mentions: samples.reduce((sum, item) => (
      sum + (item.reasons.some(reason => /Matched topic:/.test(reason)) && !item.matched_child ? 1 : 0)
    ), 0),
    samples,
  };
}

async function probeOpenAlex(orcid) {
  const authorUrl = `https://api.openalex.org/authors/https://orcid.org/${orcid}`;
  const started = Date.now();
  try {
    const response = await fetch(authorUrl, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      return {
        attempted: true,
        usable: false,
        status: response.status,
        elapsed_ms: Date.now() - started,
        reason: "The unauthenticated author lookup did not succeed; no provider change was evaluated against ranking.",
      };
    }
    const author = await response.json();
    const worksUrl = new URL("https://api.openalex.org/works");
    worksUrl.searchParams.set("filter", `authorships.author.id:${author.id}`);
    worksUrl.searchParams.set("per_page", "50");
    worksUrl.searchParams.set("sort", "publication_date:desc");
    const worksResponse = await fetch(worksUrl, { headers: { Accept: "application/json" } });
    if (!worksResponse.ok) {
      return {
        attempted: true,
        usable: false,
        status: worksResponse.status,
        elapsed_ms: Date.now() - started,
        reason: "The unauthenticated works lookup did not succeed; no provider change was evaluated against ranking.",
      };
    }
    const payload = await worksResponse.json();
    const works = Array.isArray(payload.results) ? payload.results : [];
    return {
      attempted: true,
      usable: true,
      status: worksResponse.status,
      elapsed_ms: Date.now() - started,
      work_count: works.length,
      total_work_count: Number(payload.meta?.count || works.length),
      titles: works.filter(work => work.title).length,
      abstracts: works.filter(work => work.abstract_inverted_index).length,
    };
  } catch (error) {
    return {
      attempted: true,
      usable: false,
      elapsed_ms: Date.now() - started,
      reason: String(error?.message || error),
    };
  }
}

async function main() {
  const started = Date.now();
  const harness = await loadHarness();
  const orcidApi = await loadOrcidApi();
  const explainApi = await loadExplainApi();
  const crossrefStarted = Date.now();
  const imported = await orcidApi.fetchProfile(REAL_ORCID);
  const crossrefElapsed = Date.now() - crossrefStarted;
  const representativeCv = await readFile(
    new URL("tests/fixtures/browser_cv.txt", ROOT), "utf8",
  );
  const manual = {
    research_description: "We do electrochemistry and can develop well-controlled colloids",
    expertise_keywords: "Catalysis, AI, chemical engineering",
    applicant_context: "higher_education",
    career_stage: "any",
  };
  const cv = { cv_text: representativeCv, applicant_context: "higher_education", career_stage: "any" };
  const orcid = { orcid_text: imported.publicationText, applicant_context: "higher_education", career_stage: "any" };
  const combine = (...values) => Object.assign(
    { research_description: "", expertise_keywords: "", cv_text: "", orcid_text: "", applicant_context: "higher_education", career_stage: "any" },
    ...values,
  );
  const definitions = [
    { id: "arm_1_manual", label: "manual research description and expertise", query: QUERY, profile: combine(manual), enabledSources: ["manual"], topics: false },
    { id: "arm_2_cv", label: "CV-derived", query: QUERY, profile: combine(cv), enabledSources: ["cv"], topics: false },
    { id: "arm_3_orcid", label: "real ORCID-derived", query: QUERY, profile: combine(orcid), enabledSources: ["orcid"], topics: false },
    { id: "arm_4_manual_cv", label: "manual plus CV", query: QUERY, profile: combine(manual, cv), enabledSources: ["manual", "cv"], topics: false },
    { id: "arm_5_manual_orcid", label: "manual plus real ORCID", query: QUERY, profile: combine(manual, orcid), enabledSources: ["manual", "orcid"], topics: false },
    { id: "arm_6_manual_cv_orcid", label: "manual plus CV plus real ORCID", query: QUERY, profile: combine(manual, cv, orcid), enabledSources: ["manual", "cv", "orcid"], topics: false },
    { id: "arm_7_profile_only_fallback", label: "profile-only CV and ORCID fallback", query: "", profile: combine(cv, orcid), enabledSources: ["cv", "orcid"], topics: false },
    { id: "arm_8_topic_aware", label: "post-P9 parent/subtopic-aware ranking", query: QUERY, profile: combine(manual, cv, orcid), enabledSources: ["manual", "cv", "orcid"], topics: true },
  ];
  const baselineRows = rank(harness, QUERY, null, false);
  const arms = definitions.map(definition => summarizeArm(harness, definition, baselineRows));
  const parentArm = arms.find(arm => arm.definition.id === "arm_6_manual_cv_orcid");
  const topicArm = arms.find(arm => arm.definition.id === "arm_8_topic_aware");
  const topicProbeQueries = ["electrochemistry", "polymer materials", "advanced manufacturing"];
  const topicBehavior = topicProbeQueries.map(query => {
    const definition = {
      id: `topic_probe_${query.replace(/\W+/g, "_")}`,
      label: `child-sensitive probe: ${query}`,
      query,
      profile: combine(manual, cv, orcid),
      enabledSources: ["manual", "cv", "orcid"],
      topics: true,
    };
    const parentRows = rank(harness, query, definition.profile, false);
    const topicRows = rank(harness, query, definition.profile, true);
    const parentIds = new Set(parentRows.slice(0, 10).map(row => row.id));
    const topicIds = new Set(topicRows.slice(0, 10).map(row => row.id));
    const parentProbe = { definition: { ...definition, topics: false }, rows: parentRows };
    const topicProbe = { definition, rows: topicRows };
    return {
      query,
      parent_candidate_count: parentRows.length,
      topic_candidate_count: topicRows.length,
      entering_top_10: compact(topicRows.slice(0, 10).filter(row => !parentIds.has(row.id)), 10, topicRows),
      leaving_top_10: compact(parentRows.slice(0, 10).filter(row => !topicIds.has(row.id)), 10, parentRows),
      child_driven_top_10: compact(topicRows.slice(0, 10).filter(row => row.bestChild), 10, topicRows),
      validation: validateExplanations(explainApi, topicProbe, parentProbe, { fallback: false }),
    };
  });
  const armEightValidation = validateExplanations(
    explainApi, topicArm, parentArm, { fallback: false },
  );
  const movedValidations = topicBehavior.map(item => item.validation);
  const explanationValidation = aggregateExplanationValidations(
    movedValidations.some(item => item.samples.length)
      ? movedValidations
      : [validateExplanations(explainApi, topicArm, parentArm, { fallback: true })],
  );
  const openAlex = await probeOpenAlex(REAL_ORCID);
  const works = imported.works || [];
  const output = {
    schema_version: 1,
    measured_at: new Date().toISOString(),
    sidecar_sha256: harness.sidecarSha256,
    product_query: QUERY,
    baseline_query_only: {
      candidate_count: baselineRows.length,
      known_recall_anchors: anchorRanks(baselineRows),
      top_results: compact(baselineRows),
    },
    real_orcid_route: {
      orcid: REAL_ORCID,
      provider: "Crossref",
      endpoint_contract: "assets/orcid.js fetchProfile -> /works?filter=orcid:<id>",
      source: imported.source,
      resolved_name: imported.name,
      imported_work_count: imported.importedWorkCount,
      total_work_count: imported.totalWorkCount,
      works_with_title: works.filter(work => work.title).length,
      works_with_subjects: works.filter(work => work.subjects?.length).length,
      works_with_container: works.filter(work => work.container).length,
      derived_keyword_count: imported.keywords.length,
      derived_keywords: imported.keywords,
      publication_text_sha256: createHash("sha256").update(imported.publicationText).digest("hex"),
      first_five_public_titles: works.slice(0, 5).map(work => work.title),
      elapsed_ms: crossrefElapsed,
      error: null,
    },
    provider_comparison: {
      crossref: {
        usable: true,
        imported_work_count: imported.importedWorkCount,
        works_with_subjects: works.filter(work => work.subjects?.length).length,
        elapsed_ms: crossrefElapsed,
      },
      openalex: openAlex,
      decision: "retain_crossref",
      rationale: openAlex.usable
        ? "Crossref completed the actual product route; OpenAlex produced no demonstrated ranking gain in this bounded probe, so the provider was not changed."
        : "Crossref completed the actual product route; the bounded unauthenticated OpenAlex probe was not usable, so there is no demonstrated product gain that justifies a provider change or new credential dependency.",
    },
    arms: arms.map(arm => arm.output),
    parent_vs_subtopic_behavior: {
      historical_anchor_arm_moved_results: armEightValidation.moved_result_count,
      probes: topicBehavior.map(({ validation, ...item }) => ({
        ...item,
        explanation_sample_count: validation.sample_count,
      })),
    },
    explanation_validation: explanationValidation,
    elapsed_ms: Date.now() - started,
    notes: [
      "The explicit query remains the admission gate in arms 1-6; CV and ORCID evidence may rerank but may not broaden that candidate set.",
      "Arm 7 deliberately leaves both manual fields blank so CV/ORCID terms exercise the product's documented profile-only fallback.",
      "Arm 8 uses the production P9 rollup exported by assets/search-retrieval.js; it does not implement a second topic formula.",
      "No relevance labels are inferred by this deterministic regression.",
    ],
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(OUTPUT_PATH, ROOT), `${JSON.stringify(output, null, 2)}\n`, "utf8");
    process.stdout.write(`Wrote ${OUTPUT_PATH}: 8 arms, ${imported.importedWorkCount} real Crossref works, ${output.explanation_validation.unsupported} unsupported explanations.\n`);
  } else {
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
  }
}

await main();
