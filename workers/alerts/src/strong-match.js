import "../../../assets/search-v2-config.js";
import "../../../assets/search-query.js";
import "../../../assets/search-retrieval.js";
import "../../../assets/match-explain.js";

import { recordId, recordPassesSavedSearch } from "./contract.js";

const QUERY_API = globalThis.FUNDING_SEARCH_QUERY;
const RETRIEVAL_API = globalThis.FUNDING_RETRIEVAL;
const SEARCH_V2_CONFIG = globalThis.FUNDING_SEARCH_V2_CONFIG;
const MATCH_EXPLAIN_API = globalThis.FUNDING_MATCH_EXPLAIN;

function emptyScores(length) {
  return { scores: new Float64Array(length), evidence: null };
}

export function parseAssignedJson(text, assignment) {
  const marker = `globalThis.${assignment}=`;
  const start = String(text || "").indexOf(marker);
  if (start < 0) throw new Error(`Missing ${assignment} assignment.`);
  const raw = String(text).slice(start + marker.length).trim().replace(/;\s*$/, "");
  return JSON.parse(raw);
}

export class StrongMatchEngine {
  constructor(catalog, subtopics = null) {
    this.catalog = catalog;
    this.parent = RETRIEVAL_API.create(catalog, QUERY_API, {
      searchV2: true, searchV2Config: SEARCH_V2_CONFIG, catalogRole: "parent",
    });
    this.childCatalog = subtopics ? RETRIEVAL_API.createChildCatalog(subtopics) : null;
    this.child = this.childCatalog ? RETRIEVAL_API.create(this.childCatalog, QUERY_API, {
      searchV2: true, searchV2Config: SEARCH_V2_CONFIG, catalogRole: "child",
    }) : null;
  }

  evaluate(definition, asOf, candidateIds = null, collectEvidence = false) {
    const candidates = Array.isArray(candidateIds)
      ? new Set(candidateIds.map(String).filter(Boolean))
      : null;
    const parentCandidateIndexes = candidates
      ? this.catalog.opportunities.flatMap((record, index) => (
          candidates.has(recordId(record)) ? [index] : []
        ))
      : null;
    const parentDirect = this.parent.score(definition.query, {
      context: "", evidence: collectEvidence, candidateIndexes: parentCandidateIndexes,
    });
    let rows;
    if (this.child) {
      const childCandidateIndexes = candidates
        ? this.childCatalog.opportunities.flatMap((record, index) => (
            candidates.has(String(record.parent_id || "")) ? [index] : []
          ))
        : null;
      const childDirect = this.child.score(definition.query, {
        context: "", evidence: collectEvidence, candidateIndexes: childCandidateIndexes,
      });
      const rolled = RETRIEVAL_API.rollupScores({
        parentCatalog: this.catalog,
        childCatalog: this.childCatalog,
        parentDirect,
        childDirect,
        parentProfile: emptyScores(this.catalog.opportunities.length),
        childProfile: emptyScores(this.childCatalog.opportunities.length),
        eligibilityBonuses: this.catalog.opportunities.map(() => 0),
      });
      rows = rolled.rows;
    } else {
      rows = this.catalog.opportunities.flatMap((record, index) => (
        Number(parentDirect.scores[index]) > 0
          ? [{
              id: recordId(record), record, parentAdmitted: true,
              parentDirectEvidence: parentDirect.evidence?.[index] || null,
              bestChild: null, childDroveMatch: false,
            }]
          : []
      ));
    }
    return rows.filter(row => (
      row.id && (!candidates || candidates.has(row.id))
      && recordPassesSavedSearch(row.record, definition, asOf)
    ));
  }

  matchIds(definition, asOf, candidateIds = null) {
    return new Set(this.evaluate(definition, asOf, candidateIds, false).map(row => row.id));
  }

  matchDetails(definition, asOf, candidateIds = null) {
    return new Map(this.evaluate(definition, asOf, candidateIds, true).map(row => {
      const explanation = MATCH_EXPLAIN_API?.buildV2?.({
        query: definition.query,
        parent: {
          record: row.record,
          broad: false,
          parentAdmitted: row.parentAdmitted,
          directEvidence: row.parentDirectEvidence,
          profileEvidence: null,
        },
        bestChild: row.bestChild,
        childDroveMatch: row.childDroveMatch,
        parentAdmitted: row.parentAdmitted,
        profileSources: {},
        eligibility: 0,
        broadFallback: null,
      });
      return [row.id, {
        reasons: (explanation?.reasons || []).map(reason => String(reason?.text || "").trim()).filter(Boolean),
      }];
    }));
  }
}

export async function loadPublicAssets(env, fetchImpl = fetch) {
  const timeoutMs = Math.max(1, Math.min(30_000, Number(env.ALERT_ASSET_TIMEOUT_MS) || 10_000));
  const load = async (url, accept) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetchImpl(url, { headers: { Accept: accept }, signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }
  };
  const [catalogResponse, subtopicResponse, changesResponse] = await Promise.all([
    load(env.CATALOG_URL, "application/javascript"),
    load(env.SUBTOPICS_URL, "application/javascript"),
    load(env.CHANGES_URL, "application/json"),
  ]);
  if (!catalogResponse.ok || !subtopicResponse.ok || !changesResponse.ok) {
    throw new Error("Public alert inputs are unavailable.");
  }
  const [catalogText, subtopicText, changes] = await Promise.all([
    catalogResponse.text(), subtopicResponse.text(), changesResponse.json(),
  ]);
  const catalog = parseAssignedJson(catalogText, "GRANT_CATALOG");
  const subtopics = parseAssignedJson(subtopicText, "SUBTOPIC_CATALOG");
  if (Number(catalog.schema_version) !== 3 || Number(subtopics.schema_version) !== 1) {
    throw new Error("Public alert inputs have incompatible schemas.");
  }
  if (Number(changes?.schema_version) !== 1 || !Array.isArray(changes.events)) {
    throw new Error("Change feed has an incompatible schema.");
  }
  return { catalog, subtopics, changes, matcher: new StrongMatchEngine(catalog, subtopics) };
}
