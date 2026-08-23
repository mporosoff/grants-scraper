#!/usr/bin/env node

import { loadHarness, makeVariantHarness, rankQuery } from "./run_search_diagnosis.mjs";

const withoutProgramContracts = process.argv.includes("--without-program-contracts");
const query = process.argv.slice(2).filter(argument => !argument.startsWith("--")).join(" ").trim();
if (!query) throw new Error("Provide a development query to inspect.");
if (/phase4c|iteration3.holdout/i.test(query)) {
  throw new Error("The Iteration-3 probe refuses the sealed Phase-4C population.");
}

const base = await loadHarness();
const searchV2Config = withoutProgramContracts
  ? { ...structuredClone(base.searchV2Config), authoritative_scope_entailments: [] }
  : base.searchV2Config;
const candidate = makeVariantHarness(base, { searchV2: true, searchV2Config });
const ranked = rankQuery(candidate, query, { evidence: true });
const parents = candidate.parentCatalog.opportunities.map((record, index) => ({
  id: String(record.opportunity_id || record.opportunity_number || ""),
  title: record.title,
  description: record.description || "",
  documentSearchText: record.document_search_text || "",
  sourceEvidence: record.document_evidence || record.evidence || record.citations || null,
  documentProgramAreas: record.document_program_areas || [],
  recordKeys: Object.keys(record).sort(),
  officialUrl: record.official_url || record.url || "",
  status: record.status || "",
  closeDate: record.close_date || null,
  archiveDate: record.archive_date || null,
  postedDate: record.posted_date || null,
  actionabilityStatus: record.actionability_status || null,
  score: ranked.parentDirect.scores[index],
  broaderScore: ranked.parentDirect.broaderScores[index],
  discoveryScore: ranked.parentDirect.discoveryScores[index],
  evidence: ranked.parentDirect.evidence[index]?.admission || null,
  directEvidence: ranked.parentDirect.evidence[index] || null,
}));
const children = candidate.childCatalog.opportunities.map((record, index) => ({
  id: String(record.subtopic_id || record.opportunity_id || ""),
  parentId: String(record.parent_id || ""),
  title: record.title,
  description: record.description || record.summary || "",
  childType: record.child_type || "",
  publicationState: record.publication_state || "",
  score: ranked.childDirect.scores[index],
  discoveryScore: ranked.childDirect.discoveryScores[index],
  evidence: ranked.childDirect.evidence[index] || null,
}));
parents.sort((left, right) => (
  right.score - left.score
  || right.broaderScore - left.broaderScore
  || right.discoveryScore - left.discoveryScore
  || left.id.localeCompare(right.id)
));
console.log(JSON.stringify({
  query,
  plan: ranked.queryPlan.map(group => ({
    source: group.source,
    conceptId: group.conceptId,
    role: group.role,
    evidencePolicy: group.evidencePolicy,
    evidenceClass: group.evidenceClass,
  })),
  diagnostics: ranked.parentDirect.diagnostics.searchV2.discovery,
  visible: ranked.rows.slice(0, 20).map(row => ({
    id: row.id,
    title: row.record.title,
    evidenceTier: row.evidenceTier,
    child: row.bestChild?.id || null,
    hierarchicalScope: row.parentDirectEvidence?.hierarchicalScope || null,
  })),
  parents: parents.filter(row => row.score > 0 || row.broaderScore > 0 || row.discoveryScore > 0)
    .slice(0, 30),
  children: children.filter(row => row.score > 0 || row.discoveryScore > 0)
    .sort((left, right) => right.score - left.score || right.discoveryScore - left.discoveryScore)
    .slice(0, 100),
}, null, 2));
