import "../../../assets/search-v2-config.js";
import "../../../assets/search-query.js";
import "../../../assets/search-retrieval.js";

import { recordId, recordPassesSavedSearch } from "./contract.js";

const QUERY_API = globalThis.FUNDING_SEARCH_QUERY;
const RETRIEVAL_API = globalThis.FUNDING_RETRIEVAL;
const SEARCH_V2_CONFIG = globalThis.FUNDING_SEARCH_V2_CONFIG;

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

  matchIds(definition, asOf, candidateIds = null) {
    const candidates = Array.isArray(candidateIds)
      ? new Set(candidateIds.map(String).filter(Boolean))
      : null;
    const parentCandidateIndexes = candidates
      ? this.catalog.opportunities.flatMap((record, index) => (
          candidates.has(recordId(record)) ? [index] : []
        ))
      : null;
    const parentDirect = this.parent.score(definition.query, {
      context: "", evidence: false, candidateIndexes: parentCandidateIndexes,
    });
    let admitted;
    if (this.child) {
      const childCandidateIndexes = candidates
        ? this.childCatalog.opportunities.flatMap((record, index) => (
            candidates.has(String(record.parent_id || "")) ? [index] : []
          ))
        : null;
      const childDirect = this.child.score(definition.query, {
        context: "", evidence: false, candidateIndexes: childCandidateIndexes,
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
      admitted = new Set(rolled.rows.map(row => row.id));
    } else {
      admitted = new Set(this.catalog.opportunities.flatMap((record, index) => (
        Number(parentDirect.scores[index]) > 0 ? [recordId(record)] : []
      )));
    }
    return new Set(this.catalog.opportunities.flatMap(record => {
      const id = recordId(record);
      return id && (!candidates || candidates.has(id))
        && admitted.has(id) && recordPassesSavedSearch(record, definition, asOf)
        ? [id]
        : [];
    }));
  }
}

export async function loadPublicAssets(env, fetchImpl = fetch) {
  const [catalogResponse, subtopicResponse, changesResponse] = await Promise.all([
    fetchImpl(env.CATALOG_URL, { headers: { Accept: "application/javascript" } }),
    fetchImpl(env.SUBTOPICS_URL, { headers: { Accept: "application/javascript" } }),
    fetchImpl(env.CHANGES_URL, { headers: { Accept: "application/json" } }),
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
