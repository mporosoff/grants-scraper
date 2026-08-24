import {
  awardRecord,
  cleanEmail,
  cleanText,
  finiteNumber,
  isoDate,
  makeContact,
  uniqueStrings,
} from "../contract.js";
import { AwardSourceError, fetchSourceJson } from "../http.js";
import { normalizeInstitution, recordMatchesInstitution } from "../institutions.js";

export const NSF_ADAPTER_VERSION = "1.0.0";
const NSF_API = "https://api.nsf.gov/services/v1/awards";

function quoted(value) {
  return `"${String(value).replace(/"/g, "").trim()}"`;
}

function allTerms(value) {
  return String(value || "").split(/\s+/).filter(Boolean).join(" AND ");
}

function splitCodes(value) {
  return String(value || "").split(",").map(item => item.trim()).filter(Boolean);
}

function nsfAwardUrl(id) {
  return `https://www.nsf.gov/awardsearch/show-award/?AWD_ID=${encodeURIComponent(id)}`;
}

function parseNamedEmail(value) {
  const text = cleanText(value, 500);
  if (!text) return { name: null, email: null };
  const match = /\s+([^\s@]+@[^\s@]+\.[^\s@]+)$/.exec(text);
  return match
    ? { name: cleanText(text.slice(0, match.index), 300), email: cleanEmail(match[1]) }
    : { name: text, email: null };
}

function nsfInvestigators(raw, officialUrl, sourceUrl) {
  const contacts = [];
  let primaryEmailSource = cleanEmail(raw.piEmail) ? "piEmail" : null;
  const primary = {
    name: cleanText(raw.pdPIName, 300),
    email: cleanEmail(raw.piEmail),
  };
  if (Array.isArray(raw.pi) && raw.pi.length) {
    const listedPrimary = parseNamedEmail(raw.pi[0]);
    primary.name ||= listedPrimary.name;
    primary.email ||= listedPrimary.email;
    if (!primaryEmailSource && listedPrimary.email) primaryEmailSource = "pi";
  }
  const primaryContact = makeContact({
    ...primary,
    role: "Principal Investigator",
    officialContactUrl: officialUrl,
    sourceField: primary.email ? `pdPIName/${primaryEmailSource}` : "pdPIName",
    sourceUrl,
  });
  if (primaryContact) contacts.push(primaryContact);
  const coInvestigators = Array.isArray(raw.coPDPI) ? raw.coPDPI : raw.coPDPI ? [raw.coPDPI] : [];
  for (const value of coInvestigators) {
    const contact = makeContact({
      ...parseNamedEmail(value),
      role: "Co-Principal Investigator",
      officialContactUrl: officialUrl,
      sourceField: "coPDPI",
      sourceUrl,
    });
    if (contact) contacts.push(contact);
  }
  const seen = new Set();
  return contacts.filter(contact => {
    const key = contact.name.toLocaleLowerCase("en-US");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function buildNsfRequest(criteria, { limit, offset }) {
  if (criteria.core_project_number || criteria.opportunity_number) {
    throw new AwardSourceError("unsupported_criteria", "unsupported");
  }
  if (criteria.award_id) {
    const url = `${NSF_API}/${encodeURIComponent(criteria.award_id)}.json`;
    return { url, options: { headers: { Accept: "application/json" } } };
  }
  const params = new URLSearchParams({ rpp: String(limit), offset: String(offset) });
  if (criteria.program) {
    if (/^\d{6}$/.test(criteria.program)) params.set("ProgEleCode", criteria.program);
    else params.set("fundProgramName", quoted(criteria.program));
  }
  if (criteria.topic) params.set("keyword", allTerms(criteria.topic));
  if (criteria.pi) params.set("pdPIName", criteria.pi);
  if (criteria.program_officer) params.set("poName", criteria.program_officer);
  if (criteria._institution) {
    params.set("awardeeName", quoted(criteria._institution.sources.NSF.search_name));
  }
  if (criteria.year_start) params.set("dateStart", `01/01/${criteria.year_start}`);
  if (criteria.year_end) params.set("dateEnd", `12/31/${criteria.year_end}`);
  return {
    url: `${NSF_API}.json?${params.toString()}`,
    options: { headers: { Accept: "application/json" } },
  };
}

export function normalizeNsfAward(raw, { retrievedAt, sourceUrl }) {
  const id = cleanText(raw?.id, 40);
  if (!id) throw new AwardSourceError("source_invalid_response");
  const officialUrl = nsfAwardUrl(id);
  const awardDate = isoDate(raw.date);
  const estimatedAmount = finiteNumber(raw.estimatedTotalAmt);
  const obligatedAmount = finiteNumber(raw.fundsObligatedAmt);
  const totalAward = estimatedAmount ?? obligatedAmount;
  const po = makeContact({
    name: raw.poName,
    role: "Program Officer",
    email: raw.poEmail,
    officialContactUrl: officialUrl,
    sourceField: cleanEmail(raw.poEmail) ? "poName/poEmail" : "poName",
    sourceUrl,
  });
  return awardRecord({
    award_id: id,
    source_record_ids: [id],
    source: "NSF",
    agency: "National Science Foundation",
    subagency: cleanText(raw.orgLongName2 || raw.orgLongName, 500),
    program_name: cleanText(raw.fundProgramName || raw.program, 1_000),
    program_codes: uniqueStrings([splitCodes(raw.progEleCode), splitCodes(raw.progRefCode)]),
    opportunity_numbers: [],
    activity_code: null,
    funding_mechanism: cleanText(raw.transType, 200),
    title: cleanText(raw.title),
    abstract: cleanText(raw.abstractText),
    project_start: isoDate(raw.startDate),
    project_end: isoDate(raw.expDate),
    award_year: awardDate ? Number(awardDate.slice(0, 4)) : null,
    total_award: totalAward,
    award_amount_basis: estimatedAmount !== null
      ? "estimated_total_award"
      : obligatedAmount !== null ? "funds_obligated" : null,
    institution: normalizeInstitution(raw.awardeeName || raw.awardee, { uei: raw.ueiNumber }),
    organization_department: null,
    principal_investigators: nsfInvestigators(raw, officialUrl, sourceUrl),
    program_contacts: po ? [po] : [],
    official_award_url: officialUrl,
    annual_support: [],
    source_provenance: {
      source_url: sourceUrl,
      retrieved_at: retrievedAt,
      source_record_id: id,
      adapter_version: NSF_ADAPTER_VERSION,
    },
  });
}

export async function searchNsf(fetchImpl, criteria, options) {
  const request = buildNsfRequest(criteria, options);
  const payload = await fetchSourceJson(fetchImpl, request.url, request.options);
  const response = payload?.response;
  if (!response || typeof response !== "object") throw new AwardSourceError("source_invalid_response");
  const rawAwards = Array.isArray(response.award) ? response.award : response.award ? [response.award] : [];
  const retrievedAt = options.now().toISOString();
  let awards = rawAwards.map(raw => normalizeNsfAward(raw, { retrievedAt, sourceUrl: request.url }));
  if (criteria._institution) {
    awards = awards.filter(award => recordMatchesInstitution(award, criteria._institution, "NSF"));
  }
  return {
    source: "NSF",
    adapter_version: NSF_ADAPTER_VERSION,
    results: awards.slice(0, options.limit),
    total_count: finiteNumber(response.metadata?.totalCount) ?? rawAwards.length,
    raw_record_count: rawAwards.length,
    retrieved_at: retrievedAt,
  };
}
