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
    return !cleanId || cleanId === knownByName.id || cleanId === knownByName.ror_id ? knownByName : null;
  }
  if (!cleanName) return null;
  const rorId = /^https:\/\/ror\.org\/0[a-z0-9]{8}$/i.test(cleanId || "") ? cleanId : null;
  if (cleanId && !rorId) return null;
  return {
    id: rorId,
    ror_id: rorId,
    canonical_name: cleanName,
    aliases: [],
    sources: {
      NSF: { search_name: cleanName, uei: [] },
      NIH: { search_names: [cleanName], uei: [], ipf: [] },
      DOE: { search_name: cleanName, uei: [] },
    },
    keys: new Set([identityKey(cleanName)]),
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

export function recordMatchesInstitution(record, identity, source) {
  if (!identity) return true;
  const sourceIdentity = identity.sources?.[source] || {};
  const recordUei = cleanText(record?.institution?.identifiers?.uei, 40);
  const recordIpf = cleanText(record?.institution?.identifiers?.ipf, 40);
  if (recordUei && (sourceIdentity.uei || []).includes(recordUei)) return true;
  if (recordIpf && (sourceIdentity.ipf || []).includes(recordIpf)) return true;
  const names = [identity.canonical_name, ...(identity.aliases || [])].map(identityKey);
  return names.includes(identityKey(record?.institution?.name));
}

export { institutionConfig };
