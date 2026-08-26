import institutionConfig from "../../../config/award_institutions.json" with { type: "json" };

import { cleanText } from "./contract.js";

function identityKey(value) {
  return String(value || "")
    .normalize("NFKD")
    .toLocaleLowerCase("en-US")
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function requiresExplicitSelection(value) {
  const text = cleanText(value, 300) || "";
  const words = text.split(/[\s,]+/u).filter(Boolean);
  const compact = identityKey(text).replace(/\s/g, "");
  return Boolean(compact && compact.length <= 12 && (
    words.length === 1
    || words.every(word => identityKey(word).length === 1)
  ));
}

const identities = institutionConfig.institutions.map(item => ({
  ...item,
  keys: new Set([item.canonical_name, ...(item.aliases || [])].map(identityKey)),
}));

export function resolveInstitution({ id, name } = {}) {
  const cleanId = cleanText(id, 100);
  const cleanName = cleanText(name, 300);
  const knownById = cleanId
    ? identities.find(item => item.id === cleanId || item.ror_id === cleanId)
    : null;
  const knownByName = cleanName
    ? identities.find(item => item.keys.has(identityKey(cleanName)))
    : null;
  if (knownById) {
    return !cleanName || knownById.keys.has(identityKey(cleanName)) ? knownById : null;
  }
  if (knownByName) {
    if (!cleanId && requiresExplicitSelection(cleanName) && identityKey(cleanName) !== identityKey(knownByName.canonical_name)) return null;
    return !cleanId || cleanId === knownByName.id || cleanId === knownByName.ror_id ? knownByName : null;
  }
  if (!cleanName || cleanId) return null;
  if (requiresExplicitSelection(cleanName)) return null;
  return {
    id: null,
    ror_id: null,
    canonical_name: cleanName,
    aliases: [],
    acronyms: [],
    match_names: [cleanName],
    identity_source: "submitted_complete_name",
    sources: {
      NSF: { search_name: cleanName, uei: [] },
      NIH: { search_names: [cleanName], uei: [], ipf: [] },
      DOE: { search_name: cleanName, uei: [] },
    },
    keys: new Set([identityKey(cleanName)]),
  };
}

export function institutionFromRor(candidate, submittedName) {
  const canonicalName = cleanText(candidate?.canonical_name, 300);
  const rorId = cleanText(candidate?.id, 100);
  const cleanName = cleanText(submittedName, 300);
  if (!canonicalName || !/^https:\/\/ror\.org\/0[a-z0-9]{8}$/i.test(rorId || "") || !cleanName) return null;
  const aliases = (Array.isArray(candidate?.aliases) ? candidate.aliases : []).map(value => cleanText(value, 300)).filter(Boolean).slice(0, 25);
  const acronyms = (Array.isArray(candidate?.acronyms) ? candidate.acronyms : []).map(value => cleanText(value, 80)).filter(Boolean).slice(0, 25);
  const trustedNames = [canonicalName, ...aliases, ...acronyms];
  if (!trustedNames.some(value => identityKey(value) === identityKey(cleanName))) return null;
  const defensibleAliases = aliases.filter(value => identityKey(value).replace(/\s/g, "").length > 4).slice(0, 8);
  return {
    id: rorId,
    ror_id: rorId,
    canonical_name: canonicalName,
    aliases,
    acronyms,
    match_names: trustedNames,
    identity_source: "ROR",
    registry_url: rorId,
    sources: {
      NSF: { search_name: canonicalName, uei: [] },
      NIH: { search_names: [canonicalName, ...defensibleAliases], uei: [], ipf: [] },
      DOE: { search_name: canonicalName, uei: [] },
    },
  };
}

function identityFromRecord(name, { uei, ipf } = {}) {
  const cleanUei = cleanText(uei, 40);
  const cleanIpf = cleanText(ipf, 40);
  return identities.find(item => (
    (cleanUei && Object.values(item.sources || {}).some(source => (source.uei || []).includes(cleanUei)))
    || (cleanIpf && Object.values(item.sources || {}).some(source => (source.ipf || []).includes(cleanIpf)))
    || item.keys.has(identityKey(name))
  ));
}

export function normalizeInstitution(name, identifiers = {}) {
  const cleanName = cleanText(name, 500);
  const identity = identityFromRecord(cleanName, identifiers);
  return {
    name: cleanName,
    normalized_name: identity?.canonical_name || cleanName,
    identifiers: {
      ror: identity?.ror_id || null,
      uei: cleanText(identifiers.uei, 40),
      ipf: cleanText(identifiers.ipf, 40),
      other: cleanText(identifiers.other, 80),
    },
  };
}

export function attachResolvedInstitution(award, identity) {
  if (!award?.institution || !identity) return award;
  return {
    ...award,
    institution: {
      ...award.institution,
      normalized_name: identity.canonical_name || award.institution.normalized_name,
      identifiers: {
        ...award.institution.identifiers,
        ror: identity.ror_id || award.institution.identifiers?.ror || null,
      },
      identity_source: identity.identity_source || (identity.ror_id ? "curated" : "submitted_complete_name"),
    },
  };
}

export function recordMatchesInstitution(record, identity, source) {
  if (!identity) return true;
  const sourceIdentity = identity.sources?.[source] || {};
  const recordUei = cleanText(record?.institution?.identifiers?.uei, 40);
  const recordIpf = cleanText(record?.institution?.identifiers?.ipf, 40);
  if (recordUei && (sourceIdentity.uei || []).includes(recordUei)) return true;
  if (recordIpf && (sourceIdentity.ipf || []).includes(recordIpf)) return true;
  const names = [
    ...(identity.match_names || []),
    identity.canonical_name,
    ...(identity.aliases || []),
    ...(identity.acronyms || []),
  ].map(identityKey);
  return names.includes(identityKey(record?.institution?.name));
}

export { institutionConfig };
