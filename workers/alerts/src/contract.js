export const ALERT_SCHEMA_VERSION = 4;
export const STRONG_CONTRACT_VERSION = "funding-search-v2-strong-1";
export const SUBSCRIPTION_TYPES = Object.freeze(["opportunity", "saved_search", "program"]);
export const CADENCES = Object.freeze(["immediate", "weekly"]);
export const OPPORTUNITY_TRIGGERS = Object.freeze([
  "deadline_changed", "amended", "closing_reminders", "status_changed",
]);
export const PRIVATE_FIELD_PATTERN = /(?:^|_)(?:cv|profile|orcid|publication|upload|document_text|notice_text|chat|messages?|notes?|pursuit)(?:_|$)/i;

const FACET_FIELDS = Object.freeze([
  "source", "source_type", "discipline", "topic", "agency", "eligibility", "funding_instrument",
]);
const FLAG_FIELDS = Object.freeze([
  "evidence", "preliminary", "limited", "early_career", "no_cost_share",
]);

function clean(value, maximum = 500) {
  if (typeof value !== "string") return "";
  return value.replace(/\s+/g, " ").trim().slice(0, maximum);
}

function exactKeys(value, allowed) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...allowed].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

export function containsPrivateFields(value) {
  if (Array.isArray(value)) return value.some(containsPrivateFields);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(([key, item]) => (
    PRIVATE_FIELD_PATTERN.test(key) || containsPrivateFields(item)
  ));
}

export function normalizeEmail(value) {
  const email = clean(value, 320).toLowerCase();
  return email.length <= 320 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ? email : "";
}

function normalizeFilters(value) {
  if (!exactKeys(value, ["status", "facets", "deadline", "minimum_award", "flags", "audience"])) return null;
  if (!exactKeys(value.status, ["posted", "forecasted", "archived"])) return null;
  if (!exactKeys(value.deadline, ["from", "through"])) return null;
  if (!exactKeys(value.flags, FLAG_FIELDS)) return null;
  if (!exactKeys(value.facets, FACET_FIELDS)) return null;
  const date = raw => raw === "" || /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : null;
  const from = date(value.deadline.from);
  const through = date(value.deadline.through);
  if (from === null || through === null || (from && through && from > through)) return null;
  const minimumAward = Number(value.minimum_award);
  if (!Number.isFinite(minimumAward) || minimumAward < 0 || minimumAward > 10_000_000_000) return null;
  const facets = {};
  for (const field of FACET_FIELDS) {
    const selected = value.facets[field];
    if (!Array.isArray(selected) || selected.length > 50) return null;
    const normalized = selected.map(item => clean(item, 300));
    if (normalized.some(item => !item)) return null;
    facets[field] = [...new Set(normalized)].sort();
  }
  if (Object.values(value.status).some(item => typeof item !== "boolean")) return null;
  if (Object.values(value.flags).some(item => typeof item !== "boolean")) return null;
  const audience = clean(value.audience, 40);
  if (!new Set(["all", "faculty", "postdoc", "grad", "undergrad"]).has(audience)) return null;
  return {
    status: { ...value.status }, facets, deadline: { from, through },
    minimum_award: Math.round(minimumAward), flags: { ...value.flags }, audience,
  };
}

export function normalizeSubscription(value, linksApi = globalThis.FUNDING_AWARD_LINKS) {
  if (!exactKeys(value, ["type", "cadence", "definition"])) return null;
  const type = clean(value.type, 40);
  const cadence = clean(value.cadence, 20);
  if (!SUBSCRIPTION_TYPES.includes(type) || !CADENCES.includes(cadence)) return null;
  if (containsPrivateFields(value.definition)) return null;
  let definition = null;
  if (type === "opportunity") {
    if (!exactKeys(value.definition, ["opportunity_id", "triggers"])) return null;
    const opportunityId = clean(value.definition.opportunity_id, 200);
    const triggers = Array.isArray(value.definition.triggers)
      ? [...new Set(value.definition.triggers.map(item => clean(item, 40)))]
      : [];
    if (!opportunityId || !triggers.length || triggers.some(item => !OPPORTUNITY_TRIGGERS.includes(item))) return null;
    definition = { opportunity_id: opportunityId, triggers: triggers.sort() };
  } else if (type === "program") {
    if (!exactKeys(value.definition, ["program_id"])) return null;
    const identity = linksApi?.programIdentityById?.(value.definition.program_id);
    if (!identity) return null;
    definition = { program_id: identity.id };
  } else {
    if (!exactKeys(value.definition, [
      "query", "filters", "currentness", "strong_contract_version", "include_potential",
    ])) return null;
    const query = clean(value.definition.query, 500);
    const filters = normalizeFilters(value.definition.filters);
    if (!query || !filters || value.definition.currentness !== "current_only") return null;
    if (value.definition.strong_contract_version !== STRONG_CONTRACT_VERSION) return null;
    if (value.definition.include_potential !== false) return null;
    definition = {
      query, filters, currentness: "current_only",
      strong_contract_version: STRONG_CONTRACT_VERSION,
      include_potential: false,
    };
  }
  return { type, cadence, definition };
}

export function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function recordId(record) {
  return clean(record?.opportunity_id || record?.opportunity_number, 200);
}

export function recordIsCurrent(record, asOf) {
  const status = clean(record?.status, 40).toLowerCase();
  if (!["posted", "forecasted"].includes(status)) return false;
  if (/^(?:[A-Z0-9_.-]+\s+)?(?:notice of intent\b|request for information\b|rfi\s*[-:])/i.test(clean(record?.title))) return false;
  const instruments = (record?.funding_instruments || []).map(value => clean(value).toLowerCase());
  const note = `${record?.description || ""} ${record?.close_date_note || ""}`;
  if (instruments.length && instruments.every(value => value === "other") && /\bnot accepting applications?\b/i.test(note)) return false;
  const closeDate = clean(record?.close_date, 10);
  return !closeDate || (/^\d{4}-\d{2}-\d{2}$/.test(closeDate) && closeDate >= asOf);
}

function classifyAudience(record) {
  const applicants = (record?.applicant_types || []).join(" | ").toLowerCase();
  if (applicants.includes("early-career faculty")) return "faculty";
  if (applicants.includes("postdoctoral researchers")) return "postdoc";
  if (applicants.includes("graduate students")) return "grad";
  if (applicants.includes("undergraduate students")) return "undergrad";
  const title = clean(record?.title).toLowerCase();
  if (/\breu\b|research experiences for undergraduates|goldwater|\bundergraduate\b/.test(title)) return "undergrad";
  if (/post-?doctoral|\bpostdoc\b/.test(title)) return "postdoc";
  if (/graduate research fellowship|\bgrfp\b|pre-?doctoral|dissertation|doctoral fellowship|graduate fellowship|graduate student research|\bndseg\b|\bscgsr\b/.test(title)) return "grad";
  return "faculty";
}

export function recordPassesSavedSearch(record, definition, asOf) {
  const filters = definition?.filters;
  if (!filters || !recordIsCurrent(record, asOf)) return false;
  const status = clean(record.status).toLowerCase();
  if (status === "posted" && !filters.status.posted) return false;
  if (status === "forecasted" && !filters.status.forecasted) return false;
  if (filters.status.archived) {
    // Saved-search alerts intentionally remain current-only even when an
    // interactive URL also shows archived records.
  }
  const facetFields = {
    source: Object.prototype.hasOwnProperty.call(record, "source_facet") ? "source_facet" : "source",
    source_type: "source_type", discipline: "disciplines", topic: "topic_areas",
    agency: "agency", eligibility: "applicant_types", funding_instrument: "funding_instruments",
  };
  for (const [name, field] of Object.entries(facetFields)) {
    const selected = filters.facets[name];
    if (!selected.length) continue;
    const raw = record[field];
    const values = Array.isArray(raw) ? raw : [raw];
    if (!values.some(value => selected.includes(value))) return false;
  }
  const closeDate = clean(record.close_date, 10);
  if (filters.deadline.from && (!closeDate || closeDate < filters.deadline.from)) return false;
  if (filters.deadline.through && (!closeDate || closeDate > filters.deadline.through)) return false;
  const awardMaximum = Math.max(Number(record.award_ceiling || 0), Number(record.award_floor || 0));
  if (filters.minimum_award && awardMaximum < filters.minimum_award) return false;
  if (filters.flags.evidence && record.document_evidence_status !== "current") return false;
  if (filters.flags.preliminary && !record.has_preliminary_stage) return false;
  if (filters.flags.limited && !record.limited_submission) return false;
  if (filters.flags.early_career && !record.career_stage_signal) return false;
  if (filters.flags.no_cost_share && record.cost_share_required === true) return false;
  return filters.audience === "all" || classifyAudience(record) === filters.audience;
}
