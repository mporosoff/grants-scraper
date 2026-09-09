import { recordId } from "./contract.js";

function nsfSolicitation(record) {
  if (record.parent_opportunity_id || record.record_type === "subtopic") return "";
  const agency = String(record.agency || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const code = String(record.agency_code || "").toLowerCase().trim();
  if ((agency && !["nsf", "national science foundation", "u s national science foundation"].includes(agency))
      || (code && code !== "nsf") || (!agency && !code)) return "";
  const number = String(record.opportunity_number || "").normalize("NFKC").toLowerCase()
    .replace(/[^a-z0-9]/g, "").replace(/^nsf(?=\d{5}$)/, "");
  if (!number) return "";
  const grants = record.source === "Grants.gov" && /^\d+$/.test(recordId(record));
  if (!grants || record.agency_authority === "source_default") {
    // Only NSF's own feed namespace plus its exact official solicitation URL
    // establishes this sponsor. An aggregator default or similar title cannot.
    const id = recordId(record);
    try {
      const url = new URL(id.replace(/^nsf-funding:/, ""));
      const suffix = url.pathname.match(/\/(nsf|pd)(\d{2}-[0-9a-z]+)\/?$/i);
      const fromUrl = suffix && `${suffix[1] === "pd" ? "pd" : ""}${suffix[2].replaceAll("-", "")}`;
      if (!id.startsWith("nsf-funding:") || url.protocol !== "https:"
          || url.hostname !== "www.nsf.gov" || url.username || url.password || url.port
          || !url.pathname.startsWith("/funding/opportunities/") || fromUrl !== number
          || record.detail_page !== url.href) return "";
    } catch { return ""; }
  }
  return `nsf:${number}`;
}

export function alertRecordIdentity(records = []) {
  const direct = new Map(records.map(record => [recordId(record), record]));
  const groups = new Map();
  for (const record of records) {
    const key = nsfSolicitation(record) || `id:${recordId(record)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(record);
  }
  const canonical = new Map();
  const members = new Map();
  for (const group of groups.values()) {
    group.sort((a, b) => Number(/^\d+$/.test(recordId(b)) && b.source === "Grants.gov")
      - Number(/^\d+$/.test(recordId(a)) && a.source === "Grants.gov")
      || recordId(a).localeCompare(recordId(b)));
    const id = recordId(group[0]);
    members.set(id, group.map(recordId));
    for (const record of group) canonical.set(recordId(record), id);
  }
  const aliasOwners = new Map();
  for (const record of records) for (const alias of record.source_aliases || []) {
    const id = String(alias.opportunity_id || "");
    if (!id || direct.has(id)) continue;
    if (!aliasOwners.has(id)) aliasOwners.set(id, new Set());
    aliasOwners.get(id).add(canonical.get(recordId(record)));
  }
  for (const [alias, owners] of aliasOwners) if (owners.size === 1) {
    const owner = [...owners][0];
    canonical.set(alias, owner);
    members.get(owner).push(alias);
  }
  const resolve = id => canonical.get(String(id)) || String(id);
  return {
    resolve,
    ids: id => members.get(resolve(id)) || [String(id)],
    record: id => direct.get(resolve(id)),
    isSourceAddition: event => event.type === "new" && resolve(event.opportunity_id) !== String(event.opportunity_id),
  };
}

export function isSavedSearchRestoration(event) {
  return event.type === "status_changed" && event.old_status === "archived" && event.new_status === "posted";
}
