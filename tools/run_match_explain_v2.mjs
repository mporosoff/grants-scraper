#!/usr/bin/env node
// Phase 3 explanation evaluator. The sealed search holdout is deliberately not read.

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";
import vm from "node:vm";

import {
  loadHarness,
  makeVariantHarness,
  rankQuery,
} from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const FRAME_PATH = "evaluation/match_explain_v2_frame.json";
const RESULTS_PATH = "evaluation/match_explain_v2_results.json";
const EXPLAIN_PATH = "assets/match-explain.js";
const BROAD_OPPORTUNITY_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science financial assistance|long[\s-]?range|research announcement|\broses\b|omnibus|unsolicited proposal|open topic|financial assistance program|annual program statement|office[ -]wide|open[ -]scope solicitation/i;

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function explanationText(explanation) {
  return [
    explanation?.label || "",
    ...(explanation?.reasons || []).map(item => item.text || ""),
  ].join(" ");
}

function reasonCodes(explanation) {
  return (explanation?.reasons || []).map(item => item.code);
}

function selectedFields(explanation) {
  return new Set((explanation?.reasons || []).flatMap(item => {
    const value = item?.evidence?.field;
    return Array.isArray(value) ? value : [value];
  }).filter(Boolean));
}

function selectedConcepts(explanation) {
  return new Set([
    ...(explanation?.reasons || []).map(item => item?.evidence?.conceptId),
    ...(explanation?.trace?.admittedBy || []).map(item => item?.conceptId),
  ].filter(Boolean));
}

function causalFailures(explanation) {
  if (!explanation) return [];
  const failures = [];
  const admittedBy = explanation.trace?.admittedBy || [];
  for (const item of explanation.reasons || []) {
    const evidence = item.evidence || {};
    if (item.code === "field_context" && !admittedBy.some(path => (
      ["explicit_evidence", "source_grounded_scope"].includes(path.path)
      && (path.fields || []).includes(evidence.field)
      && (!evidence.conceptId || !path.conceptId || path.conceptId === evidence.conceptId)
    ))) failures.push(`uncausal_field=${evidence.field || "none"}`);
    if (
      item.code === "authoritative_scope"
      && !admittedBy.some(path => path.path === "authoritative_scope_entailment")
    ) failures.push(`uncausal_scope=${item.code}`);
    if (
      item.code === "controlled_relationship"
      && !admittedBy.some(path => (
        path.path === "authoritative_scope_entailment"
        || (path.path === "source_grounded_scope" && path.relationship)
      ))
    ) failures.push(`uncausal_scope=${item.code}`);
    if (item.code === "query_interpretation" && !admittedBy.some(path => (
      path.conceptId === evidence.canonicalConcept
      || (path.coveredConcepts || []).includes(evidence.canonicalConcept)
    ))) failures.push("uncausal_query_interpretation");
    if (item.code === "child_hierarchy" && !explanation.trace?.childDroveMatch) {
      failures.push("uncausal_child_hierarchy");
    }
    if (
      item.code === "exact_opportunity_number"
      && !explanation.trace?.exactOpportunityNumber
    ) failures.push("uncausal_exact_match=exact_opportunity_number");
    if (item.code === "exact_title" && !explanation.trace?.exactTitlePhrase) {
      failures.push("uncausal_exact_match=exact_title");
    }
    if (
      item.code === "profile_contribution"
      && !(explanation.trace?.profileSources || []).includes(evidence.source)
    ) failures.push("uncausal_profile_contribution");
    if (item.code === "eligibility_contribution" && !explanation.trace?.eligibilityContributed) {
      failures.push("uncausal_eligibility_contribution");
    }
    if (
      item.code === "broader_program"
      && (
        evidence.path !== "broad_program_fallback"
        || explanation.admissionPath !== "broad_program_fallback"
      )
    ) {
      failures.push("uncausal_broader_program");
    }
  }
  return failures;
}

function fixtureInput(frame, item) {
  const input = clone(frame.fixtures[item.fixture_id]);
  if (item.override?.query) input.query = item.override.query;
  if (item.override?.exactOpportunityNumber) {
    input.parent.directEvidence.exactOpportunityNumber = true;
    input.parent.directEvidence.admission.reason = "exact_phrase_or_identifier";
  }
  if (item.profile_source) {
    const selected = item.profile_source;
    for (const source of ["manual", "cv", "orcid"]) {
      if (source !== selected) input.profileSources[source] = { score: 0 };
    }
    if (selected === "none") {
      for (const source of ["manual", "cv", "orcid"]) {
        input.profileSources[source] = { score: 0 };
      }
    } else {
      input.eligibility = 0;
    }
  }
  return input;
}

function evaluateAssertions(item, admitted, explanation) {
  const expected = item.expected || {};
  const failures = [];
  const text = explanationText(explanation);
  const codes = reasonCodes(explanation);
  const fields = selectedFields(explanation);
  const concepts = selectedConcepts(explanation);
  const reasons = explanation?.reasons || [];

  if (admitted !== expected.admitted) failures.push(`admitted=${admitted}`);
  if (expected.tier && explanation?.tier !== expected.tier) {
    failures.push(`tier=${explanation?.tier || "none"}`);
  }
  if (Number.isInteger(expected.reason_count) && reasons.length !== expected.reason_count) {
    failures.push(`reason_count=${reasons.length}`);
  }
  if (reasons.length > 3) failures.push(`reason_count_above_limit=${reasons.length}`);
  for (const code of expected.required_codes || []) {
    if (!codes.includes(code)) failures.push(`missing_code=${code}`);
  }
  for (const value of expected.required_text || []) {
    if (!text.includes(value)) failures.push(`missing_text=${value}`);
  }
  for (const value of expected.required_labels || []) {
    if (explanation?.label !== value) failures.push(`missing_label=${value}`);
  }
  for (const value of expected.forbidden_labels || []) {
    if (explanation?.label === value || text.includes(value)) failures.push(`forbidden_label=${value}`);
  }
  for (const value of expected.forbidden_text || []) {
    if (text.includes(value)) failures.push(`forbidden_text=${value}`);
  }
  for (const value of expected.forbidden_complete_reasons || []) {
    if (reasons.some(reason => reason.text === value)) failures.push(`forbidden_reason=${value}`);
  }
  for (const field of expected.required_fields || []) {
    if (!fields.has(field)) failures.push(`missing_field=${field}`);
  }
  for (const concept of expected.required_concepts || []) {
    if (!concepts.has(concept)) failures.push(`missing_concept=${concept}`);
  }
  if (
    expected.forbidden_claims?.includes("generic_title_as_direct_scope")
    && (explanation?.tier === "direct" || fields.has("parent_title"))
  ) failures.push("generic_title_as_direct_scope");
  if (reasons.some(itemReason => (
    /^(?:Search terms matched|Keyword match|This matched because)\b/i.test(itemReason.text || "")
  ))) failures.push("tautological_reason");
  if (reasons.some(itemReason => !itemReason.code || !itemReason.evidence)) {
    failures.push("reason_without_causal_evidence");
  }
  failures.push(...causalFailures(explanation));
  return failures;
}

async function evaluate() {
  if (process.argv.includes("--holdout")) {
    throw new Error("Phase 3 refuses to open the sealed search holdout. Phase 4 owns first execution and adjudication.");
  }
  const [frameSource, explainSource] = await Promise.all([
    readFile(new URL(FRAME_PATH, ROOT), "utf8"),
    readFile(new URL(EXPLAIN_PATH, ROOT), "utf8"),
  ]);
  const frame = JSON.parse(frameSource);
  const context = { globalThis: {} };
  vm.runInNewContext(explainSource, context, { filename: EXPLAIN_PATH });
  const explainApi = context.globalThis.FUNDING_MATCH_EXPLAIN;
  if (Number(explainApi?.contractVersion || 0) !== 2 || !explainApi?.buildV2) {
    throw new Error("Phase 3 explanation contract version 2 is unavailable.");
  }
  const base = await loadHarness();
  const candidate = makeVariantHarness(base, { searchV2: true });
  const searchCache = new Map();

  function ranked(query) {
    if (!searchCache.has(query)) searchCache.set(query, rankQuery(candidate, query));
    return searchCache.get(query);
  }

  const results = frame.cases.map(item => {
    let admitted = true;
    let input;
    let row = null;
    if (item.source === "fixture") {
      input = fixtureInput(frame, item);
    } else {
      const search = ranked(item.query);
      row = search.rows.find(candidateRow => candidateRow.id === item.result_id) || null;
      admitted = Boolean(row);
      input = row ? {
        query: item.query,
        parent: {
          record: row.record,
          broad: BROAD_OPPORTUNITY_RE.test(`${row.record.title || ""} ${row.record.opportunity_number || ""}`),
          parentAdmitted: row.parentAdmitted,
          directEvidence: row.parentDirectEvidence,
          profileEvidence: row.parentProfileEvidence,
        },
        bestChild: row.bestChild,
        childDroveMatch: row.childDroveMatch,
        parentAdmitted: row.parentAdmitted,
        profileSources: {},
        eligibility: 0,
      } : null;
    }
    const explanation = input ? explainApi.buildV2(input) : null;
    const failures = evaluateAssertions(item, admitted, explanation);
    const expectedLabel = item.expected?.human_label || "correct_and_useful";
    const adjudicatedLabel = failures.length
      ? (failures.some(failure => /forbidden|privacy|review/i.test(failure))
          ? "unsupported"
          : "misleading")
      : expectedLabel;
    return {
      id: item.id,
      source: item.source,
      query: item.query || input?.query || "",
      result_id: item.result_id || input?.parent?.record?.opportunity_id || "",
      result_title: row?.record?.title || input?.parent?.record?.title || "",
      admitted,
      expected: item.expected,
      explanation,
      assertion_failures: failures,
      adjudicated_label: adjudicatedLabel,
      review_note: item.expected?.review_note || null,
    };
  });

  const counts = Object.fromEntries(frame.rules.allowed_human_labels.map(label => [
    label,
    results.filter(item => item.adjudicated_label === label).length,
  ]));
  const usefulRate = results.length
    ? counts.correct_and_useful / results.length
    : 0;
  const unsupported = results.filter(item => (
    ["unsupported", "misleading", "overstated_broad_fit", "privacy_problem"]
      .includes(item.adjudicated_label)
  ));
  const shallow = results.filter(item => item.adjudicated_label === "correct_but_too_shallow");
  const gates = {
    case_count_at_least_30: results.length >= 30,
    unsupported_explanations: unsupported.map(item => item.id),
    causal_evidence_violations: results
      .filter(item => item.assertion_failures.some(failure => (
        failure === "reason_without_causal_evidence" || failure.startsWith("uncausal_")
      )))
      .map(item => item.id),
    review_only_child_leakage: results
      .filter(item => item.assertion_failures.some(failure => failure.includes("fixture-review-child")))
      .map(item => item.id),
    private_profile_excerpt_leakage: results
      .filter(item => item.assertion_failures.some(failure => failure.includes("secret zeolite project")))
      .map(item => item.id),
    tautological_explanations: results
      .filter(item => item.assertion_failures.includes("tautological_reason"))
      .map(item => item.id),
    authoritative_scope_mislabeled_broad: results
      .filter(item => item.id.startsWith("scope_") && item.explanation?.tier === "broader_program")
      .map(item => item.id),
    correct_and_useful_rate: Number(usefulRate.toFixed(6)),
    correct_and_useful_rate_at_least_90_percent: usefulRate >= .9,
    individually_reviewed_shallow_cases: shallow.map(item => ({
      id: item.id,
      note: item.review_note,
    })),
    maximum_reason_count: Math.max(0, ...results.map(item => item.explanation?.reasons?.length || 0)),
    collapsed_by_default: true,
    holdout_status: "sealed_not_executed_or_adjudicated",
  };
  const passed = gates.case_count_at_least_30
    && !unsupported.length
    && !gates.causal_evidence_violations.length
    && !gates.review_only_child_leakage.length
    && !gates.private_profile_excerpt_leakage.length
    && !gates.tautological_explanations.length
    && !gates.authoritative_scope_mislabeled_broad.length
    && gates.correct_and_useful_rate_at_least_90_percent
    && gates.maximum_reason_count <= 3;
  const payload = {
    schema_version: 1,
    evaluated_at: "2026-08-22",
    phase: 3,
    status: passed ? "explanation_gates_passed" : "explanation_gates_failed",
    production_enabled: false,
    frame: FRAME_PATH,
    frame_sha256: sha256(frameSource),
    explanation_asset: EXPLAIN_PATH,
    explanation_asset_sha256: sha256(explainSource),
    explanation_contract_version: explainApi.contractVersion,
    holdout_status: "sealed_not_executed_or_adjudicated",
    case_count: results.length,
    label_counts: counts,
    gates,
    results,
  };

  if (process.argv.includes("--write")) {
    await writeFile(new URL(RESULTS_PATH, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    process.stdout.write(
      `Wrote Phase 3 explanation results: ${results.length} pairs; `
      + `${Number(usefulRate * 100).toFixed(1)}% correct and useful; holdout sealed.\n`,
    );
  } else {
    process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
  }
  if (!passed) process.exitCode = 1;
}

await evaluate();
