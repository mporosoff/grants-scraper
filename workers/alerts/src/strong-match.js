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
    this.childCatalog = subtopics ? RETRIEVAL_API.createChildCatalog(subtopics) : null;
    this.parent = null;
    this.child = null;
    this.preparedIds = null;
    this.prepared = false;
  }

  prepare(candidateIds = null) {
    const candidates = Array.isArray(candidateIds)
      ? new Set(candidateIds.map(String).filter(Boolean))
      : null;
    if (this.prepared && (
      this.preparedIds === null
      || (candidates && [...candidates].every(id => this.preparedIds.has(id)))
    )) return;
    const parentCandidateIndexes = candidates
      ? this.catalog.opportunities.flatMap((record, index) => (
          candidates.has(recordId(record)) ? [index] : []
        ))
      : null;
    const childCandidateIndexes = candidates && this.childCatalog
      ? this.childCatalog.opportunities.flatMap((record, index) => (
          candidates.has(String(record.parent_id || "")) ? [index] : []
        ))
      : null;
    this.parent = RETRIEVAL_API.create(this.catalog, QUERY_API, {
      searchV2: true, searchV2Config: SEARCH_V2_CONFIG, catalogRole: "parent",
      preparedCandidateIndexes: parentCandidateIndexes,
    });
    this.child = this.childCatalog ? RETRIEVAL_API.create(this.childCatalog, QUERY_API, {
      searchV2: true, searchV2Config: SEARCH_V2_CONFIG, catalogRole: "child",
      preparedCandidateIndexes: childCandidateIndexes,
    }) : null;
    this.preparedIds = candidates;
    this.prepared = true;
  }

  evaluate(definition, asOf, candidateIds = null, collectEvidence = false) {
    const candidates = Array.isArray(candidateIds)
      ? new Set(candidateIds.map(String).filter(Boolean))
      : null;
    this.prepare(candidateIds);
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
  const load = async (url, accept, bodyType) => {
    const controller = new AbortController();
    let timeout;
    const deadline = new Promise((_, reject) => {
      timeout = setTimeout(() => {
        controller.abort();
        reject(Object.assign(new Error("Public alert input was aborted by its timeout."), {
          code: "asset_timeout",
        }));
      }, timeoutMs);
    });
    try {
      return await Promise.race([(async () => {
        const response = await fetchImpl(url, { headers: { Accept: accept }, signal: controller.signal });
        if (!response.ok) throw Object.assign(new Error("Public alert inputs are unavailable."), {
          code: "asset_http_error",
        });
        return bodyType === "json" ? await response.json() : await response.text();
      })(), deadline]);
    } catch (error) {
      if (error?.code) throw error;
      if (error?.name === "AbortError") {
        throw Object.assign(new Error("Public alert input was aborted by its timeout."), {
          code: "asset_timeout",
        });
      }
      throw Object.assign(new Error("Public alert input could not be read."), {
        code: bodyType === "json" ? "asset_parse_error" : "asset_read_error",
      });
    } finally {
      clearTimeout(timeout);
    }
  };
  const [catalogText, subtopicText, changes] = await Promise.all([
    load(env.CATALOG_URL, "application/javascript", "text"),
    load(env.SUBTOPICS_URL, "application/javascript", "text"),
    load(env.CHANGES_URL, "application/json", "json"),
  ]);
  let catalog;
  let subtopics;
  try {
    catalog = parseAssignedJson(catalogText, "GRANT_CATALOG");
    subtopics = parseAssignedJson(subtopicText, "SUBTOPIC_CATALOG");
  } catch {
    throw Object.assign(new Error("Public alert inputs could not be parsed."), {
      code: "asset_parse_error",
    });
  }
  if (Number(catalog.schema_version) !== 3 || Number(subtopics.schema_version) !== 1) {
    throw Object.assign(new Error("Public alert inputs have incompatible schemas."), {
      code: "asset_schema_error",
    });
  }
  if (Number(changes?.schema_version) !== 1 || !Array.isArray(changes.events)) {
    throw Object.assign(new Error("Change feed has an incompatible schema."), {
      code: "asset_schema_error",
    });
  }
  return { catalog, subtopics, changes, matcher: new StrongMatchEngine(catalog, subtopics) };
}
