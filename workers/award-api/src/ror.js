import { cleanText, uniqueStrings } from "./contract.js";
import { AwardSourceError, fetchSourceJson } from "./http.js";

const ROR_API = "https://api.ror.org/v2/organizations";
const ROR_ADAPTER_VERSION = "1.3.0";
const ROR_RESULT_LIMIT = 8;

function identityKey(value) {
  return String(value || "")
    .normalize("NFKD")
    .toLocaleLowerCase("en-US")
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function namesOfType(item, type) {
  return uniqueStrings((Array.isArray(item?.names) ? item.names : [])
    .filter(name => Array.isArray(name?.types) && name.types.includes(type))
    .map(name => name?.value));
}

function safeRorId(value) {
  try {
    const url = new URL(cleanText(value, 100));
    return url.protocol === "https:" && url.hostname === "ror.org" && /^\/0[a-z0-9]{8}$/.test(url.pathname)
      ? url.href.replace(/\/$/, "")
      : null;
  } catch {
    return null;
  }
}

function rorRecordUrl(value) {
  const id = safeRorId(value);
  if (!id) return null;
  return `${ROR_API}/${id.split("/").at(-1)}`;
}

function locationDetails(item) {
  const location = Array.isArray(item?.locations) ? item.locations[0] : null;
  const details = location?.geonames_details || {};
  return {
    city: cleanText(details.name, 160),
    country: cleanText(details.country_name, 160),
    country_code: cleanText(details.country_code, 2),
  };
}

function candidateScore(candidate, query) {
  const queryKey = identityKey(query);
  const canonicalKey = identityKey(candidate.canonical_name);
  const aliasKeys = candidate.aliases.map(identityKey);
  const acronymKeys = candidate.acronyms.map(identityKey);
  const canonicalUniversityKey = `university of ${queryKey}`;
  const canonicalNamedUniversityKey = `${queryKey} university`;
  const commonUniversityShorthand = canonicalKey === canonicalUniversityKey
    || canonicalKey === `the ${canonicalUniversityKey}`
    || canonicalKey === canonicalNamedUniversityKey;
  let score = canonicalKey === queryKey
    ? 120
    : aliasKeys.includes(queryKey)
      ? 100
      : acronymKeys.includes(queryKey)
        ? 90
        : commonUniversityShorthand
          ? 80
          : canonicalKey.startsWith(queryKey)
            ? 65
            : canonicalKey.includes(queryKey)
              ? 45
              : 20;

  // NSF, NIH, DOE, and DoD are U.S. funders. This corpus-specific tie-break keeps
  // ambiguous short acronyms such as MIT, UVA, RIT, and UCLA deterministic
  // without hiding the lower-ranked ROR candidates from the typeahead.
  if (candidate.location.country_code === "US") score += 24;
  if (candidate.types.includes("education")) score += 12;
  if (candidate.status === "active") score += 4;
  return score;
}

export function normalizeRorOrganization(item, query = "") {
  const id = safeRorId(item?.id);
  const displayNames = namesOfType(item, "ror_display");
  const labels = namesOfType(item, "label");
  const canonicalName = cleanText(displayNames[0] || labels[0], 300);
  if (!id || !canonicalName) return null;
  const aliases = namesOfType(item, "alias").filter(name => identityKey(name) !== identityKey(canonicalName));
  const acronyms = namesOfType(item, "acronym").filter(name => identityKey(name) !== identityKey(canonicalName));
  const candidate = {
    id,
    canonical_name: canonicalName,
    aliases,
    acronyms,
    types: uniqueStrings(Array.isArray(item?.types) ? item.types : []).map(value => value.toLocaleLowerCase("en-US")),
    status: cleanText(item?.status, 40) || "active",
    location: locationDetails(item),
    registry: "ROR",
    registry_url: id,
  };
  const queryKey = identityKey(query);
  const exactType = identityKey(candidate.canonical_name) === queryKey
    ? "canonical"
    : candidate.aliases.some(name => identityKey(name) === queryKey)
      ? "alias"
      : candidate.acronyms.some(name => identityKey(name) === queryKey)
        ? "acronym"
        : null;
  return {
    ...candidate,
    match: {
      exact: Boolean(exactType),
      type: exactType || "keyword",
      score: candidateScore(candidate, query),
    },
  };
}

export function rankRorOrganizations(items, query, limit = ROR_RESULT_LIMIT) {
  return (Array.isArray(items) ? items : [])
    .map(item => normalizeRorOrganization(item, query))
    .filter(Boolean)
    .sort((left, right) => (
      right.match.score - left.match.score
      || left.canonical_name.localeCompare(right.canonical_name, "en-US")
      || left.id.localeCompare(right.id)
    ))
    .slice(0, Math.max(1, Math.min(ROR_RESULT_LIMIT, Number(limit) || ROR_RESULT_LIMIT)));
}

export async function searchRor(fetchImpl, query, { limit = ROR_RESULT_LIMIT } = {}) {
  const normalizedQuery = cleanText(query, 120);
  if (!normalizedQuery || normalizedQuery.length < 2) {
    throw new AwardSourceError("invalid_institution_query", "unsupported");
  }
  const url = new URL(ROR_API);
  url.searchParams.set("query", normalizedQuery);
  const payload = await fetchSourceJson(fetchImpl, url.href, {
    headers: { Accept: "application/json" },
  });
  if (!payload || !Array.isArray(payload.items)) {
    throw new AwardSourceError("source_invalid_response");
  }
  return {
    source: "ROR",
    adapter_version: ROR_ADAPTER_VERSION,
    source_url: url.href,
    license: "CC0-1.0",
    query: normalizedQuery,
    institutions: rankRorOrganizations(payload.items, normalizedQuery, limit),
  };
}

export async function resolveRorOrganization(fetchImpl, id) {
  const url = rorRecordUrl(id);
  if (!url) throw new AwardSourceError("invalid_institution_identity", "unsupported");
  const payload = await fetchSourceJson(fetchImpl, url, {
    headers: { Accept: "application/json" },
  });
  const organization = normalizeRorOrganization(payload, "");
  if (!organization || organization.id !== safeRorId(id)) {
    throw new AwardSourceError("source_invalid_response");
  }
  return {
    ...organization,
    source_url: url,
    license: "CC0-1.0",
  };
}

export { ROR_ADAPTER_VERSION, ROR_API, ROR_RESULT_LIMIT, safeRorId };
