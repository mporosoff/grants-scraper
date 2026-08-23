#!/usr/bin/env node

// Development-only feasibility audit. This never reads the sealed Phase-4C
// frame and does not use configured concept families or program entailments.

import { readFile, writeFile } from "node:fs/promises";
import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const ROOT = new URL("../", import.meta.url);
const FATES = "evaluation/search_v2_iteration3_anchor_fates.json";
const OUTPUT = "evaluation/search_v2_local_field_feasibility.json";
const FIELD_WEIGHTS = Object.freeze({
  parent_title: 8,
  child_title: 9,
  authoritative_program_area: 6,
  child_summary: 4,
  bounded_source_evidence: 3,
  parent_description: 2,
});

function sentences(value) {
  return String(value || "")
    .split(/(?<=[.!?])\s+|…+|[\n\r]+/)
    .map(item => item.trim())
    .filter(Boolean);
}

function sourceFacts(record) {
  return (record?.document_evidence?.facts || [])
    .filter(fact => fact?.type === "review_criteria")
    .flatMap(fact => [fact.value, fact.citation?.quote])
    .filter(Boolean);
}

function parentPassages(record) {
  return [
    { field: "parent_title", text: record.title || "" },
    ...(record.document_program_areas || []).map(text => ({
      field: "authoritative_program_area", text,
    })),
    ...sourceFacts(record).map(text => ({ field: "bounded_source_evidence", text })),
    ...sentences(record.description).map(text => ({ field: "parent_description", text })),
  ];
}

function childPassages(record) {
  return [
    { field: "child_title", text: record.title || "" },
    ...(record.program_area_labels || []).map(text => ({
      field: "authoritative_program_area", text,
    })),
    ...sentences(record.description || record.summary).map(text => ({ field: "child_summary", text })),
  ];
}

function queryGroups(query, queryApi) {
  return queryApi.tokenize(query).map(source => {
    const parts = source.split("-").filter(part => part.length > 1);
    return {
      source,
      alternatives: parts.length > 1 ? [[source], parts] : [[source]],
      exact_short_acronym: new RegExp(`\\b${source}\\b`, "i").test(query)
        && new RegExp(`\\b${source.toUpperCase()}\\b`).test(query)
        && source.length <= 4,
    };
  });
}

function tokenPositions(tokens) {
  const positions = new Map();
  tokens.forEach((term, index) => {
    if (!positions.has(term)) positions.set(term, []);
    positions.get(term).push(index);
  });
  return positions;
}

function matchAlternative(alternative, positions, retrievalApi, exactShort) {
  const selected = [];
  for (const requirement of alternative) {
    const exact = positions.get(requirement) || [];
    if (exact.length) {
      selected.push({ query: requirement, indexed: requirement, position: exact[0], kind: "exact" });
      continue;
    }
    if (exactShort || requirement.length < 7) return null;
    const fuzzy = [...positions.keys()].find(candidate => (
      candidate[0] === requirement[0]
      && retrievalApi.boundedDamerauLevenshtein(requirement, candidate, 1) <= 1
    ));
    if (!fuzzy) return null;
    selected.push({ query: requirement, indexed: fuzzy, position: positions.get(fuzzy)[0], kind: "fuzzy" });
  }
  return selected;
}

function scorePassage(passage, groups, queryApi, retrievalApi) {
  const tokens = queryApi.tokenize(passage.text);
  const positions = tokenPositions(tokens);
  const matches = groups.flatMap((group, groupIndex) => {
    const alternatives = group.alternatives.flatMap(alternative => {
      const match = matchAlternative(
        alternative,
        positions,
        retrievalApi,
        group.exact_short_acronym,
      );
      return match ? [{ match, exact: match.every(item => item.kind === "exact") }] : [];
    });
    if (!alternatives.length) return [];
    alternatives.sort((left, right) => Number(right.exact) - Number(left.exact));
    return [{ group_index: groupIndex, source: group.source, terms: alternatives[0].match }];
  });
  const matchedGroups = new Set(matches.map(item => item.group_index));
  const matchPositions = matches.flatMap(item => item.terms.map(term => term.position));
  const span = matchPositions.length
    ? Math.max(...matchPositions) - Math.min(...matchPositions)
    : null;
  const coverage = groups.length ? matchedGroups.size / groups.length : 0;
  const proximity = span === null ? 0 : 1 / (1 + span);
  return {
    ...passage,
    weight: FIELD_WEIGHTS[passage.field] || 1,
    query_group_count: groups.length,
    matched_group_count: matchedGroups.size,
    coverage: Number(coverage.toFixed(6)),
    span,
    matches,
    score: Number(((FIELD_WEIGHTS[passage.field] || 1)
      * (matchedGroups.size ** 2)
      * (1 + proximity)).toFixed(6)),
  };
}

function feasibility(best, packageCoverage, groupCount) {
  if (best?.matched_group_count === groupCount) return "FULL_SINGLE_PASSAGE_TEXT_SUPPORT";
  if (packageCoverage === groupCount && best?.matched_group_count >= Math.max(1, groupCount - 1)) {
    return "FULL_FIELDED_SUPPORT_BUT_NOT_ONE_PASSAGE";
  }
  if (packageCoverage >= Math.ceil(groupCount * .67)) return "PARTIAL_TEXT_SUPPORT_RELATIONSHIP_STILL_REQUIRED";
  return "INSUFFICIENT_INDEXED_TEXT_FOR_CONVENTIONAL_RANKING";
}

async function main() {
  if (process.argv.some(argument => /phase4c|iteration3.holdout/i.test(argument))) {
    throw new Error("Field feasibility audit refuses the sealed Phase-4C population.");
  }
  const [harness, fateSource] = await Promise.all([
    loadHarness(),
    readFile(new URL(FATES, ROOT), "utf8"),
  ]);
  const fates = JSON.parse(fateSource);
  const candidate = makeVariantHarness(harness, { searchV2: true });
  const rankedByQuery = new Map([...new Set(fates.rows.map(row => row.query))].map(query => [
    query,
    rankQuery(candidate, query, { evidence: true }),
  ]));
  const parentById = new Map(harness.catalog.opportunities.map(record => [
    String(record.opportunity_id || record.opportunity_number || ""), record,
  ]));
  const childrenByParent = new Map();
  harness.childCatalog.opportunities.forEach(record => {
    const parentId = String(record.parent_id || "");
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
    childrenByParent.get(parentId).push(record);
  });
  const rows = fates.rows.map(anchor => {
    const parentId = String(anchor.required_result_id);
    const parent = parentById.get(parentId);
    if (!parent) throw new Error(`Missing required parent ${parentId}.`);
    const groups = queryGroups(anchor.query, harness.queryApi);
    const passages = [
      ...parentPassages(parent).map(passage => ({ ...passage, record_id: parentId, source_kind: "parent" })),
      ...(childrenByParent.get(parentId) || []).flatMap(child => (
        childPassages(child).map(passage => ({
          ...passage,
          record_id: String(child.subtopic_id || child.opportunity_id || ""),
          source_kind: "publication_eligible_child",
        }))
      )),
    ].map(passage => scorePassage(
      passage,
      groups,
      harness.queryApi,
      harness.retrievalApi,
    ));
    passages.sort((left, right) => (
      right.matched_group_count - left.matched_group_count
      || right.score - left.score
      || (left.span ?? Number.MAX_SAFE_INTEGER) - (right.span ?? Number.MAX_SAFE_INTEGER)
    ));
    const matchedAcrossPackage = new Set(passages.flatMap(passage => (
      passage.matches.map(match => match.group_index)
    )));
    const best = passages[0] || null;
    const ranked = rankedByQuery.get(anchor.query);
    const visibleRank = ranked.rows.findIndex(row => row.id === parentId);
    const parentIndex = harness.catalog.opportunities.findIndex(record => (
      String(record.opportunity_id || record.opportunity_number || "") === parentId
    ));
    const childIndexes = harness.childCatalog.opportunities.flatMap((record, index) => (
      String(record.parent_id || "") === parentId ? [index] : []
    ));
    return {
      query_id: anchor.query_id,
      query: anchor.query,
      required_result_id: parentId,
      required_result_title: anchor.required_result_title,
      query_groups: groups.map(group => group.source),
      indexed_fields_checked: Object.keys(FIELD_WEIGHTS),
      package_matched_group_count: matchedAcrossPackage.size,
      package_coverage: groups.length
        ? Number((matchedAcrossPackage.size / groups.length).toFixed(6))
        : 0,
      strongest_passage: best ? {
        record_id: best.record_id,
        source_kind: best.source_kind,
        field: best.field,
        text: best.text,
        matched_group_count: best.matched_group_count,
        coverage: best.coverage,
        span: best.span,
        matches: best.matches,
      } : null,
      conventional_fielded_feasibility: feasibility(best, matchedAcrossPackage.size, groups.length),
      inherited_iteration3_candidate_trace: {
        parent_candidate_discovered: anchor.parent_candidate_discovered,
        relevant_child_candidate_discovered: anchor.relevant_child_candidate_discovered,
        candidate_rank_before_verification: anchor.candidate_rank_before_verification,
      },
      local_fielded_outcome: {
        parent_discovery_score: Number(ranked.parentDirect.discoveryScores[parentIndex] || 0),
        strongest_child_discovery_score: Math.max(
          0,
          ...childIndexes.map(index => Number(ranked.childDirect.discoveryScores[index] || 0)),
        ),
        visible_primary_rank: visibleRank < 0 ? null : visibleRank + 1,
        final_state: visibleRank < 0 ? "not_primary" : "visible_primary",
      },
    };
  });
  const counts = Object.fromEntries([...new Set(rows.map(row => row.conventional_fielded_feasibility))]
    .sort().map(label => [label, rows.filter(row => row.conventional_fielded_feasibility === label).length]));
  const payload = {
    schema_version: 1,
    architecture_reset: "local_fielded_ir",
    generated_at: "2026-08-23",
    status: "pre_implementation_feasibility_and_post_implementation_outcome_complete",
    sealed_phase4c_read_or_executed: false,
    configured_scientific_relationships_used: false,
    program_specific_scope_mappings_used: false,
    method: "Literal/stemmed query groups, conservative edit-distance-one recovery for terms of at least seven characters, compound decomposition, and the strongest authoritative parent/child passage across six distinct fields.",
    field_weights_for_feasibility_only: FIELD_WEIGHTS,
    row_count: rows.length,
    feasibility_counts: counts,
    rows,
  };
  if (process.argv.includes("--write")) {
    await writeFile(new URL(OUTPUT, ROOT), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  console.log(JSON.stringify({ output: process.argv.includes("--write") ? OUTPUT : null, counts }, null, 2));
}

await main();
