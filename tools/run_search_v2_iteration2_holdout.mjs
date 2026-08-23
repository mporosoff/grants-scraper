#!/usr/bin/env node
// Phase 4B one-time Iteration-2 holdout executor. This harness invokes the
// frozen production query/retrieval/explanation modules; it never tunes or
// adjudicates. The immutable raw artifact is written before its hash receipt.

import { createHash } from "node:crypto";
import { access, readFile, writeFile } from "node:fs/promises";
import process from "node:process";

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const PREOPEN_PATH = "evaluation/search_v2_phase4b_preopen.json";
const FRAME_PATH = "evaluation/search_v2_iteration2_holdout_frame.json";
const MANIFEST_PATH = "evaluation/search_v2_iteration2_holdout_manifest.json";
const RAW_PATH = "evaluation/search_v2_iteration2_holdout_results_raw.json";
const RECEIPT_PATH = "evaluation/search_v2_phase4b_execution.json";
const TRUTH_PATH = "evaluation/search_v2_iteration2_holdout_truth.json";
const RESULTS_PATH = "evaluation/search_v2_iteration2_holdout_results.json";
const BROAD_OPPORTUNITY_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science financial assistance|long[\s-]?range|research announcement|research interests of|established program to stimulate competitive research|research collaboration|\broses\b|omnibus|unsolicited proposal|open topic|financial assistance program|annual program statement|office[ -]wide|open[ -]scope solicitation/i;

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function number(value) {
  return Number(Number(value || 0).toFixed(6));
}

async function source(path) {
  return readFile(new URL(path, ROOT), "utf8");
}

async function assertAbsent(path) {
  try {
    await access(new URL(path, ROOT));
    throw new Error(`${path} already exists; the Phase 4B holdout executor is single-use.`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function compactEvidence(evidence) {
  if (!evidence) return null;
  return {
    schema_version: evidence.schemaVersion || null,
    admission: evidence.admission || null,
    authoritative_scope: evidence.authoritativeScope || null,
    exact_phrase: evidence.exactPhrase === true,
    exact_title_phrase: evidence.exactTitlePhrase === true,
    exact_opportunity_number: evidence.exactOpportunityNumber === true,
    trigrams: Array.from(evidence.trigrams || []),
    groups: (evidence.groups || []).map(group => ({
      source: group.source,
      concept_id: group.conceptId || "",
      role: group.role || "",
      evidence_path: group.evidencePath || "",
      contribution: number(group.contribution),
      matched_terms: (group.matchedTermContributions || []).map(item => ({
        term: item.term,
        contribution: number(item.contribution),
        fields: (item.fields || []).map(field => ({
          field: field.field,
          admission_eligible: field.admissionEligible === true,
        })),
      })),
    })),
  };
}

function causalEvidence(row) {
  if (row.childDroveMatch && row.bestChild?.directEvidence) return row.bestChild.directEvidence;
  return row.parentDirectEvidence || row.bestChild?.directEvidence || null;
}

function admissionPath(row) {
  const evidence = causalEvidence(row);
  if (evidence?.admission?.reason === "authoritative_scope_entailment") return "authoritative_scope";
  if (row.childDroveMatch && row.bestChild) return "publication_eligible_child";
  return "explicit_parent_evidence";
}

function compactVisibleRow(harness, row, rank, query, classification) {
  const parentEvidence = row.parentDirectEvidence || null;
  const broad = BROAD_OPPORTUNITY_RE.test(
    `${row.record.title || ""} ${String(row.record.description || "").slice(0, 1_500)}`,
  );
  const explanation = harness.explanationApi.buildV2({
    query,
    parent: {
      record: row.record,
      broad,
      directEvidence: parentEvidence,
      parentAdmitted: row.parentAdmitted,
    },
    bestChild: row.bestChild,
    childDroveMatch: row.childDroveMatch,
    parentAdmitted: row.parentAdmitted,
  });
  return {
    rank,
    classification,
    id: row.id,
    number: row.record.opportunity_number || "",
    title: row.record.title || "",
    agency: row.record.agency || "",
    status: row.record.status || "",
    source_type: row.record.source_type || "",
    official_url: row.record.official_url || row.record.url || "",
    topic_areas: row.record.topic_areas || [],
    description_excerpt: String(row.record.description || "").slice(0, 2_000),
    score: number(row.score),
    evidence_tier: Number(row.evidenceTier || 0),
    admission_path: classification === "broader_program_fit" ? "broader_program_fit" : admissionPath(row),
    parent_admitted: row.parentAdmitted,
    parent_score: number(row.parentRaw),
    child_score: number(row.bestChild?.raw || 0),
    child_drove_match: row.childDroveMatch,
    best_child: row.bestChild ? {
      id: row.bestChild.id,
      title: row.bestChild.record.title || "",
      summary_excerpt: String(row.bestChild.record.summary || row.bestChild.record.description || "").slice(0, 2_000),
      publication_state: row.bestChild.record.publication_state || "",
      program_area_labels: row.bestChild.record.program_area_labels || [],
      evidence: compactEvidence(row.bestChild.directEvidence),
    } : null,
    parent_evidence: compactEvidence(parentEvidence),
    explanation,
  };
}

function alternativeRows(harness, ranked, scoreKey) {
  const parentDirect = { ...ranked.parentDirect, scores: ranked.parentDirect[scoreKey] };
  const childDirect = { ...ranked.childDirect, scores: ranked.childDirect[scoreKey] };
  const rolled = harness.retrievalApi.rollupScores({
    parentCatalog: harness.parentCatalog,
    childCatalog: harness.childCatalog,
    parentDirect,
    parentProfile: { scores: new Float64Array(harness.parentCatalog.opportunities.length) },
    childDirect,
    childProfile: { scores: new Float64Array(harness.childCatalog.opportunities.length) },
    eligibilityBonuses: new Float64Array(harness.parentCatalog.opportunities.length),
  });
  const rows = rolled.rows.filter(row => row.record?.status !== "archived");
  rows.sort((left, right) => (
    Number(left.evidenceTier || 99) - Number(right.evidenceTier || 99)
    || right.score - left.score
    || left.id.localeCompare(right.id)
  ));
  return rows;
}

function rejectedCandidates(harness, ranked) {
  const rows = [];
  function collect(catalog, result, sourceType) {
    catalog.opportunities.forEach((record, index) => {
      const lexicalScore = Number(result.lexicalScores?.[index] || 0);
      const semanticScore = Number(result.semanticScores?.[index] || 0);
      if (!(lexicalScore + semanticScore > 0)) return;
      const admission = result.evidence?.[index]?.admission;
      if (admission?.classification !== "rejected") return;
      rows.push({
        source: sourceType,
        id: String(record.opportunity_id || record.subtopic_id || ""),
        parent_id: String(record.parent_id || record.opportunity_id || ""),
        title: record.title || "",
        publication_state: record.publication_state || "",
        reason: admission.reason,
        evidence_tier: Number(admission.evidenceTier || 5),
        lexical_coverage: Number(admission.lexicalCoverage || 0),
        semantic_coverage: Number(admission.semanticCoverage || 0),
        substantive_coverage: Number(admission.substantiveCoverage || 0),
        lexical_score: number(lexicalScore),
        semantic_score: number(semanticScore),
      });
    });
  }
  collect(harness.parentCatalog, ranked.parentDirect, "parent");
  collect(harness.childCatalog, ranked.childDirect, "publication_eligible_child");
  return rows.sort((left, right) => (
    left.source.localeCompare(right.source)
    || left.id.localeCompare(right.id)
  ));
}

function requiredAnchorChecks(harness, ranked, primaryRows, broaderRows, requiredIds) {
  const parents = new Map(harness.parentCatalog.opportunities.map((record, index) => [
    String(record.opportunity_id), { record, index },
  ]));
  return requiredIds.map(id => {
    const parent = parents.get(String(id));
    const primaryIndex = primaryRows.findIndex(row => row.id === String(id));
    const broaderIndex = broaderRows.findIndex(row => row.id === String(id));
    if (!parent) return { id: String(id), catalog_state: "absent" };
    const children = harness.childCatalog.opportunities.flatMap((child, childIndex) => {
      if (String(child.parent_id) !== String(id)) return [];
      const evidence = ranked.childDirect.evidence?.[childIndex] || null;
      const discovered = Number(ranked.childDirect.lexicalScores?.[childIndex] || 0)
        + Number(ranked.childDirect.semanticScores?.[childIndex] || 0) > 0;
      if (!discovered && !evidence?.admission?.admitted) return [];
      return [{
        id: String(child.subtopic_id || child.opportunity_id || ""),
        title: child.title || "",
        publication_state: child.publication_state || "",
        evidence: compactEvidence(evidence),
      }];
    });
    return {
      id: String(id),
      catalog_state: "present",
      title: parent.record.title || "",
      primary_rank: primaryIndex < 0 ? null : primaryIndex + 1,
      broader_rank: broaderIndex < 0 ? null : broaderIndex + 1,
      parent_evidence: compactEvidence(ranked.parentDirect.evidence?.[parent.index] || null),
      discovered_children: children,
    };
  });
}

async function execute() {
  if (!process.argv.includes("--execute-once")) {
    throw new Error("Phase 4B holdout execution requires the explicit --execute-once flag.");
  }
  await assertAbsent(RAW_PATH);
  await assertAbsent(RECEIPT_PATH);
  await assertAbsent(TRUTH_PATH);
  await assertAbsent(RESULTS_PATH);

  const [preopenSource, frameSource, manifestSource] = await Promise.all([
    source(PREOPEN_PATH),
    source(FRAME_PATH),
    source(MANIFEST_PATH),
  ]);
  const preopen = JSON.parse(preopenSource);
  const frame = JSON.parse(frameSource);
  const manifest = JSON.parse(manifestSource);
  if (preopen.status !== "candidate_frozen_before_phase4b_holdout_open") {
    throw new Error("The Phase 4B pre-open checkpoint is not frozen.");
  }
  if (preopen.holdout.execution_count !== 0 || preopen.protocol.execute_exactly_once !== true) {
    throw new Error("The pre-open checkpoint does not certify a zero-execution single-use holdout.");
  }
  if (sha256(frameSource) !== preopen.holdout.frame_sha256) {
    throw new Error("The sealed holdout frame hash differs from the pre-open checkpoint.");
  }
  if (sha256(manifestSource) !== preopen.holdout.manifest_sha256) {
    throw new Error("The holdout manifest hash differs from the pre-open checkpoint.");
  }
  for (const [path, expected] of Object.entries(preopen.frozen_hashes || {})) {
    if (sha256(await source(path)) !== expected) throw new Error(`Frozen input hash mismatch: ${path}`);
  }
  for (const [path, expected] of Object.entries(preopen.preserved_failed_phase4_hashes || {})) {
    if (sha256(await source(path)) !== expected) throw new Error(`Failed Phase-4 evidence drift: ${path}`);
  }
  if (frame.status !== "sealed_never_executed" || frame.unlock_phase !== "phase-4b") {
    throw new Error("The Iteration-2 holdout is not eligible for Phase 4B execution.");
  }
  if (frame.queries?.length !== 28 || manifest.query_count !== 28) {
    throw new Error("The registered Phase 4B holdout must contain exactly 28 queries.");
  }
  const queryIds = frame.queries.map(item => item.id);
  const queryTexts = frame.queries.map(item => item.query.toLowerCase());
  if (new Set(queryIds).size !== queryIds.length || new Set(queryTexts).size !== queryTexts.length) {
    throw new Error("The registered holdout contains duplicate query IDs or text.");
  }

  const base = await loadHarness();
  for (const [path, expected] of Object.entries(preopen.frozen_hashes || {})) {
    if (base.hashes[path] && base.hashes[path] !== expected) {
      throw new Error(`Loaded harness hash mismatch: ${path}`);
    }
  }
  const candidate = makeVariantHarness(base, { searchV2: true });
  const production = makeVariantHarness(base, { searchV2: false });
  const requiredByQuery = manifest.pre_registered_required_anchors || {};
  const results = [];

  for (const item of frame.queries) {
    const productionRanked = rankQuery(production, item.query, { evidence: true });
    const ranked = rankQuery(candidate, item.query, { evidence: true });
    const primaryRows = ranked.rows;
    const primaryIds = new Set(primaryRows.map(row => row.id));
    const broaderRows = alternativeRows(candidate, ranked, "broaderScores")
      .filter(row => !primaryIds.has(row.id));
    const rejected = rejectedCandidates(candidate, ranked);
    const parentDiscovery = ranked.parentDirect.diagnostics.searchV2.discovery;
    const childDiscovery = ranked.childDirect.diagnostics.searchV2.discovery;
    const requiredIds = Array.from(requiredByQuery[item.id] || [], String);
    results.push({
      id: item.id,
      stratum: item.stratum,
      discipline: item.discipline,
      query: item.query,
      candidate_latency_ms: number(ranked.latencyMs),
      production_latency_ms: number(productionRanked.latencyMs),
      query_plan: ranked.queryPlan.map(group => ({
        source: group.source,
        concept_id: group.conceptId || "",
        role: group.role || "",
        evidence_policy: group.evidencePolicy || "",
        required: group.required === true || group.requiredAlways === true,
      })),
      admission_contract: {
        minimum_coverage: ranked.parentDirect.diagnostics.minimumCoverage,
        short_complete_coverage: ranked.parentDirect.diagnostics.searchV2.shortCompleteCoverage,
        strict_substantive_coverage: ranked.parentDirect.diagnostics.searchV2.strictSubstantiveCoverage,
        authoritative_scope_entailments: ranked.parentDirect.diagnostics.searchV2.authoritativeScopeEntailments,
      },
      discovery: {
        internal_candidate_count: parentDiscovery.internalCandidateCount + childDiscovery.internalCandidateCount,
        parent_internal_candidate_count: parentDiscovery.internalCandidateCount,
        child_internal_candidate_count: childDiscovery.internalCandidateCount,
        internal_admitted_primary_count: parentDiscovery.admittedPrimaryCount + childDiscovery.admittedPrimaryCount,
        internal_admitted_broader_count: parentDiscovery.broaderFitCount + childDiscovery.broaderFitCount,
        rejected_candidate_count: rejected.length,
        rejected_partial_intent_count: parentDiscovery.rejectedPartialIntentCount + childDiscovery.rejectedPartialIntentCount,
        rejection_reason_counts: Object.fromEntries([...new Set(rejected.map(row => row.reason))].sort()
          .map(reason => [reason, rejected.filter(row => row.reason === reason).length])),
      },
      visible_primary_count: primaryRows.length,
      broader_fit_count: broaderRows.length,
      production_visible_result_count: productionRanked.rows.length,
      required_primary_ids: requiredIds,
      required_anchor_checks: requiredAnchorChecks(candidate, ranked, primaryRows, broaderRows, requiredIds),
      visible_primary_results: primaryRows.map((row, index) => (
        compactVisibleRow(candidate, row, index + 1, item.query, "primary")
      )),
      broader_program_fits: broaderRows.map((row, index) => (
        compactVisibleRow(candidate, row, index + 1, item.query, "broader_program_fit")
      )),
      rejected_candidates: rejected,
      production_top_10_ids: productionRanked.rows.slice(0, 10).map(row => row.id),
    });
  }

  const payload = {
    schema_version: 1,
    phase: "4B",
    iteration: "search-v2-iteration-2",
    executed_at: new Date().toISOString(),
    status: "holdout_executed_unadjudicated",
    execution_count: 1,
    post_outcome_tuning_permitted: false,
    candidate_code_sha: preopen.candidate_code_sha,
    candidate_tree_sha: preopen.candidate_tree_sha,
    preopen_checkpoint: PREOPEN_PATH,
    preopen_checkpoint_sha256: sha256(preopenSource),
    holdout_frame: FRAME_PATH,
    holdout_frame_sha256: sha256(frameSource),
    holdout_manifest: MANIFEST_PATH,
    holdout_manifest_sha256: sha256(manifestSource),
    frozen_hashes: preopen.frozen_hashes,
    query_count: results.length,
    production_search_v2_enabled: false,
    results,
  };
  const rawSource = `${JSON.stringify(payload, null, 2)}\n`;
  await writeFile(new URL(RAW_PATH, ROOT), rawSource, "utf8");
  const receipt = {
    schema_version: 1,
    phase: "4B",
    status: "one_time_raw_execution_frozen",
    execution_count: 1,
    raw_results: RAW_PATH,
    raw_results_sha256: sha256(rawSource),
    candidate_code_sha: preopen.candidate_code_sha,
    candidate_tree_sha: preopen.candidate_tree_sha,
    config_sha256: preopen.frozen_hashes["config/search_v2.json"],
    catalog_sha256: preopen.frozen_hashes["data/opportunities.js"],
    sidecar_sha256: preopen.frozen_hashes["data/subtopics.js"],
    holdout_frame_sha256: sha256(frameSource),
    holdout_manifest_sha256: sha256(manifestSource),
    post_outcome_tuning_permitted: false,
  };
  await writeFile(new URL(RECEIPT_PATH, ROOT), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  process.stdout.write(
    `Phase 4B holdout executed once: ${results.length} queries; raw SHA-256 ${receipt.raw_results_sha256}.\n`,
  );
}

await execute();
