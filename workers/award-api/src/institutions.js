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
  const known = cleanId
    ? identities.find(item => item.id === cleanId)
    : identities.find(item => item.keys.has(identityKey(cleanName)));
  if (known) return known;
  if (!cleanName) return null;
  return {
    id: null,
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
