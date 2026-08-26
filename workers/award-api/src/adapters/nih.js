import {
  awardRecord,
  cleanEmail,
  cleanSourceText,
  cleanText,
  finiteNumber,
  isoDate,
  makeContact,
  safeOfficialUrl,
  uniqueStrings,
} from "../contract.js";
import { AwardSourceError, fetchSourceJson } from "../http.js";
import { attachResolvedInstitution, normalizeInstitution, recordMatchesInstitution } from "../institutions.js";
import { nihFiscalYears, recordSatisfiesYearFilter, yearFilterDiagnostics } from "../year-filter.js";

export const NIH_ADAPTER_VERSION = "1.4.2";
export const NIH_API = "https://api.reporter.nih.gov/v2/projects/search";
export const NIH_UPSTREAM_PAGE_SIZE = 100;
export const NIH_MAX_UPSTREAM_PAGES = 12;

function parseCoreProjectNumber(value) {
  const match = /^([A-Z0-9]{3})([A-Z]{2})(\d{6})$/.exec(value || "");
  if (!match) throw new AwardSourceError("invalid_core_project_number", "unsupported");
  return { activity_code: match[1], ic_code: match[2], serial_num: match[3] };
}

export function buildNihRequest(criteria, { limit, offset, retrievedDate }) {
  if (criteria.award_id || criteria.program_codes || criteria.program_office) {
    throw new AwardSourceError("unsupported_criteria", "unsupported");
  }
  const apiCriteria = { exclude_subprojects: true };
  if (criteria.core_project_number) {
    apiCriteria.project_num_split = parseCoreProjectNumber(criteria.core_project_number);
  }
  if (criteria.opportunity_number) apiCriteria.opportunity_numbers = [criteria.opportunity_number];
  if (criteria.program) {
    if (!/^(?=.*[A-Z])[A-Z0-9]{3}$/.test(criteria.program)) {
      throw new AwardSourceError("unsupported_program_identifier", "unsupported");
    }
    apiCriteria.activity_codes = [criteria.program];
  }
  if (criteria.topic) {
    apiCriteria.advanced_text_search = {
      operator: "and",
      search_field: "projecttitle,abstracttext",
      search_text: criteria.topic,
    };
  }
  if (criteria.pi) apiCriteria.pi_names = [{ any_name: criteria.pi }];
  if (criteria.program_officer) apiCriteria.po_names = [{ any_name: criteria.program_officer }];
  if (criteria._institution) {
    if (criteria._institution.id) {
      apiCriteria.org_names_exact_match = criteria._institution.sources.NIH.search_names;
    } else {
      apiCriteria.org_names = criteria._institution.sources.NIH.search_names;
    }
  }
  const fiscalYears = nihFiscalYears(criteria, retrievedDate);
  if (fiscalYears) apiCriteria.fiscal_years = fiscalYears;
  const upstreamLimit = Math.min(Math.max(limit * 4, 50), 100);
  const body = {
    criteria: apiCriteria,
    limit: upstreamLimit,
    offset,
    sort_field: "project_start_date",
    sort_order: "desc",
  };
  return {
    url: NIH_API,
    options: {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    body,
  };
}

function latestRecord(records) {
  return [...records].sort((left, right) => {
    const year = (finiteNumber(right.fiscal_year) || 0) - (finiteNumber(left.fiscal_year) || 0);
    if (year) return year;
    return (finiteNumber(right.appl_id) || 0) - (finiteNumber(left.appl_id) || 0);
  })[0];
}

function projectDetailUrl(raw) {
  return safeOfficialUrl(raw?.project_detail_url, ["reporter.nih.gov"]);
}

function nihInvestigators(records, officialUrl, sourceUrl) {
  const contacts = [];
  for (const raw of records) {
    for (const person of Array.isArray(raw.principal_investigators) ? raw.principal_investigators : []) {
      const email = cleanEmail(person.email);
      const contact = makeContact({
        name: person.full_name || [person.first_name, person.middle_name, person.last_name].filter(Boolean).join(" "),
        role: person.is_contact_pi ? "Contact Principal Investigator" : "Principal Investigator",
        email,
        officialContactUrl: officialUrl,
        sourceField: email ? "principal_investigators.email" : "principal_investigators.full_name",
        sourceUrl,
      });
      if (contact) contacts.push({ ...contact, profile_id: finiteNumber(person.profile_id) });
    }
  }
  const byIdentity = new Map();
  for (const contact of contacts) {
    const key = contact.profile_id || contact.name.toLocaleLowerCase("en-US");
    const prior = byIdentity.get(key);
    if (!prior) {
      byIdentity.set(key, contact);
      continue;
    }
    if (contact.role === "Contact Principal Investigator") prior.role = contact.role;
    if (!prior.email && contact.email) {
      prior.email = contact.email;
      prior.source_provenance = contact.source_provenance;
    }
  }
  return [...byIdentity.values()];
}

function nihProgramContacts(records, officialUrl, sourceUrl) {
  const contacts = [];
  for (const raw of records) {
    for (const person of Array.isArray(raw.program_officers) ? raw.program_officers : []) {
      const email = cleanEmail(person.email);
      const contact = makeContact({
        name: person.full_name || [person.first_name, person.middle_name, person.last_name].filter(Boolean).join(" "),
        role: "Program Official",
        email,
        officialContactUrl: officialUrl,
        sourceField: email ? "program_officers.email" : "program_officers.full_name",
        sourceUrl,
      });
      if (contact) contacts.push(contact);
    }
  }
  const seen = new Set();
  return contacts.filter(contact => {
    const key = contact.name.toLocaleLowerCase("en-US");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function minDate(records, field) {
  return records.map(item => isoDate(item[field])).filter(Boolean).sort()[0] || null;
}

function maxDate(records, field) {
  return records.map(item => isoDate(item[field])).filter(Boolean).sort().at(-1) || null;
}

export function normalizeNihProject(records, { retrievedAt, sourceUrl, completeHistory }) {
  const latest = latestRecord(records);
  const core = cleanText(latest.core_project_num || latest.project_num || latest.appl_id, 50);
  if (!core) throw new AwardSourceError("source_invalid_response");
  const officialUrl = projectDetailUrl(latest);
  if (!officialUrl) throw new AwardSourceError("source_invalid_response");
  const annualSupport = [...records]
    .sort((left, right) => (finiteNumber(left.fiscal_year) || 0) - (finiteNumber(right.fiscal_year) || 0))
    .map(raw => ({
      application_id: cleanText(raw.appl_id, 40),
      project_number: cleanText(raw.project_num, 60),
      fiscal_year: finiteNumber(raw.fiscal_year),
      award_amount: finiteNumber(raw.award_amount),
      budget_start: isoDate(raw.budget_start),
      budget_end: isoDate(raw.budget_end),
      official_award_url: projectDetailUrl(raw),
    }));
  const amounts = annualSupport.map(item => item.award_amount).filter(value => value !== null);
  const fiscalYears = annualSupport.map(item => item.fiscal_year).filter(value => value !== null);
  const organization = latest.organization || {};
  const admin = latest.agency_ic_admin || {};
  return awardRecord({
    award_id: core,
    source_record_ids: annualSupport.map(item => item.application_id).filter(Boolean),
    source: "NIH",
    agency: latest.agency_code === "NIH" ? "National Institutes of Health" : cleanText(latest.agency_code, 120),
    subagency: cleanText(admin.name || admin.abbreviation, 500),
    program_name: null,
    program_codes: uniqueStrings([latest.activity_code, admin.code, admin.abbreviation]),
    opportunity_numbers: uniqueStrings(records.map(item => item.opportunity_number)),
    activity_code: cleanText(latest.activity_code, 40),
    funding_mechanism: cleanText(latest.funding_mechanism, 200),
    title: cleanText(latest.project_title),
    abstract: cleanSourceText(latest.abstract_text),
    project_start: minDate(records, "project_start_date"),
    project_end: maxDate(records, "project_end_date"),
    award_year: fiscalYears.length ? Math.min(...fiscalYears) : null,
    total_award: amounts.length ? amounts.reduce((sum, amount) => sum + amount, 0) : null,
    award_amount_basis: amounts.length
      ? completeHistory ? "complete_reporter_history" : "returned_support_years"
      : null,
    institution: normalizeInstitution(organization.org_name, {
      uei: organization.primary_uei || organization.org_ueis?.[0],
      ipf: organization.org_ipf_code,
      other: organization.primary_duns || organization.org_duns?.[0],
    }),
    organization_department: cleanText(organization.dept_type, 500),
    principal_investigators: nihInvestigators(records, officialUrl, sourceUrl),
    program_contacts: nihProgramContacts(records, officialUrl, sourceUrl),
    official_award_url: officialUrl,
    annual_support: annualSupport,
    source_provenance: {
      source_url: sourceUrl,
      retrieved_at: retrievedAt,
      source_record_id: core,
      adapter_version: NIH_ADAPTER_VERSION,
    },
  });
}

function rawRecordKey(raw) {
  return cleanText(raw?.appl_id, 40)
    || [raw?.core_project_num, raw?.project_num, raw?.fiscal_year, raw?.budget_start]
      .map(value => cleanText(value, 80) || "")
      .join("|");
}

function normalizeProjects(groups, { criteria, retrievedAt, completeHistory }) {
  let results = [...groups.values()].map(records => normalizeNihProject(records, {
    retrievedAt,
    sourceUrl: NIH_API,
    completeHistory,
  }));
  if (criteria._institution) {
    results = results
      .filter(award => recordMatchesInstitution(award, criteria._institution, "NIH"))
      .map(award => attachResolvedInstitution(award, criteria._institution));
  }
  results.sort((left, right) => (
    (right.project_start || "").localeCompare(left.project_start || "")
  ));
  return results;
}

export async function searchNih(fetchImpl, criteria, options) {
  const retrievedDate = options.now();
  const retrievedAt = retrievedDate.toISOString();
  const yearFilter = yearFilterDiagnostics(criteria);
  const targetProjectCount = options.offset + options.limit + 1;
  const rawRecords = [];
  const seenRecords = new Set();
  const groups = new Map();
  let upstreamOffset = 0;
  let upstreamTotal = null;
  let upstreamExhausted = false;
  let upstreamPages = 0;
  let results = [];

  for (let page = 0; page < NIH_MAX_UPSTREAM_PAGES; page += 1) {
    const request = buildNihRequest(criteria, { limit: NIH_UPSTREAM_PAGE_SIZE, offset: upstreamOffset, retrievedDate });
    const payload = await fetchSourceJson(fetchImpl, request.url, request.options);
    if (!Array.isArray(payload?.results) || !payload.meta || typeof payload.meta !== "object") {
      throw new AwardSourceError("source_invalid_response");
    }
    const pageRecords = payload.results;
    upstreamPages += 1;
    const reportedTotal = finiteNumber(payload.meta.total);
    if (upstreamTotal === null && reportedTotal !== null) upstreamTotal = reportedTotal;
    for (const raw of pageRecords) {
      const recordKey = rawRecordKey(raw);
      if (!recordKey || seenRecords.has(recordKey)) continue;
      seenRecords.add(recordKey);
      rawRecords.push(raw);
      if (!recordSatisfiesYearFilter(raw.fiscal_year, criteria, yearFilter)) continue;
      const projectKey = cleanText(raw.core_project_num || raw.project_num || raw.appl_id, 60);
      if (!projectKey) continue;
      if (!groups.has(projectKey)) groups.set(projectKey, []);
      groups.get(projectKey).push(raw);
    }
    upstreamOffset += pageRecords.length;
    if (upstreamTotal !== null && upstreamOffset >= upstreamTotal) {
      upstreamExhausted = true;
    } else if (upstreamTotal === null && pageRecords.length < request.body.limit) {
      upstreamExhausted = true;
    }
    results = normalizeProjects(groups, {
      criteria,
      retrievedAt,
      completeHistory: Boolean(criteria.core_project_number && upstreamExhausted),
    });
    if (results.length >= targetProjectCount || upstreamExhausted) break;
    if (!pageRecords.length) break;
  }

  return {
    source: "NIH",
    adapter_version: NIH_ADAPTER_VERSION,
    results: results.slice(options.offset, options.offset + options.limit),
    total_count: upstreamExhausted ? results.length : null,
    raw_record_count: rawRecords.length,
    upstream_total_count: upstreamTotal,
    upstream_pages: upstreamPages,
    safety_bound_reached: !upstreamExhausted && upstreamPages >= NIH_MAX_UPSTREAM_PAGES,
    year_filter: yearFilter,
    has_more: results.length > options.offset + options.limit,
    retrieved_at: retrievedAt,
  };
}
