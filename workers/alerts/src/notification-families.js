import { recordId } from "./contract.js";

// Reviewed notification equivalence, not catalog/source or scientific identity.
// FY27's official notices name these three submission routes together (p. 21):
// https://grants.gov/grantsws/rest/opportunity/att/download/355073
// New cycles and other programs require their own source-backed entry.
const FAMILIES = [{
  id: "dod-muri-fy2027",
  title: "Fiscal Year (FY) 2027 Department of War Multidisciplinary Research Program of the University Research Initiative (MURI)",
  notices: [
    ["363899", "NOFOAFRLAFOSR20260002", "DOD-AFOSR", "Air Force Office of Scientific Research"],
    ["363905", "W911NF26S1000", "DOD-AMC", "Dept of the Army -- Materiel Command"],
    ["363906", "N0001426SF002", "DOD-ONR", "Office of Naval Research"],
  ],
}];

function normalized(value) {
  return String(value || "").normalize("NFKC").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function familyFor(record) {
  if (record.parent_opportunity_id || record.record_type === "subtopic"
      || record.source !== "Grants.gov" || record.agency_authority === "source_default") return null;
  return FAMILIES.find(family =>
    normalized(String(record.title || "").replace(/\(DoW\)/gi, "")) === normalized(family.title)
    && family.notices.some(([id, number, code, agency]) => recordId(record) === id
      && record.opportunity_number === number && record.agency_code === code
      && normalized(record.agency) === normalized(agency))) || null;
}

export function savedSearchNotificationIdentity(records, sourceIdentity) {
  const byId = new Map();
  const groups = new Map();
  for (const record of records) {
    const family = familyFor(record);
    if (!family) continue;
    const key = `call:${family.id}`;
    if (!groups.has(key)) groups.set(key, { ...family, records: [], ids: [] });
    const group = groups.get(key);
    group.records.push(record);
    for (const id of sourceIdentity.ids(recordId(record))) {
      byId.set(id, key);
      group.ids.push(id);
    }
  }
  for (const group of groups.values()) {
    group.ids.sort();
    group.records.sort((a, b) => recordId(a).localeCompare(recordId(b)));
  }
  const resolve = id => byId.get(String(id)) || sourceIdentity.resolve(id);
  return {
    resolve,
    ids: id => groups.get(resolve(id))?.ids || sourceIdentity.ids(id),
    record: id => sourceIdentity.record(id),
    family: id => groups.get(resolve(id)),
    // A different service's genuine notice is not merely a duplicate source.
    isSourceAddition: event => sourceIdentity.isSourceAddition(event),
  };
}
