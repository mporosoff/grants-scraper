import {
  awardRecord,
  cleanSourceText,
  cleanText,
  finiteNumber,
  isoDate,
  safeOfficialUrl,
  uniqueStrings,
} from "../contract.js";
import { AwardSourceError, fetchSourceJson } from "../http.js";
import { attachResolvedInstitution, normalizeInstitution, recordMatchesInstitution } from "../institutions.js";
import { recordSatisfiesYearFilter, yearFilterDiagnostics } from "../year-filter.js";

export const DOD_ADAPTER_VERSION = "1.0.0";
export const DOD_SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/";
export const DOD_DETAIL_URL = "https://api.usaspending.gov/api/v2/awards";
export const DOD_MAX_RESULTS = 25;
export const DOD_UPSTREAM_PAGE_SIZE = 25;
export const DOD_DETAIL_CONCURRENCY = 3;

const DOD_AGENCY_NAME = "Department of Defense";
const DOD_AWARD_TYPE_CODES = Object.freeze(["04", "05"]);
const DOD_AWARD_TYPE_LABELS = Object.freeze({
  project_grant: /^PROJECT GRANT(?:\s*\([A-Z0-9]+\))?$/i,
  cooperative_agreement: /^COOPERATIVE AGREEMENT(?:\s*\([A-Z0-9]+\))?$/i,
});
const DOD_PROFILE_HOST = "www.usaspending.gov";
const DOD_API_HOST = "api.usaspending.gov";
const ASSISTANCE_LISTING_PATTERN = /^\d{2}\.\d{3}$/;
const OPPORTUNITY_NUMBER_PATTERN = /^[A-Z0-9][A-Z0-9._/-]{2,119}$/;
const UNAVAILABLE_OPPORTUNITY_NUMBERS = new Set([
  "N/A",
  "NA",
  "NONE",
  "NOT APPLICABLE",
  "NOT AVAILABLE",
  "UNKNOWN",
]);
const REQUEST_HEADERS = Object.freeze({
  Accept: "application/json",
  "Content-Type": "application/json",
});

export const DOD_CAPABILITIES = Object.freeze({
  filters: Object.freeze({
    award_id: "supported_exact",
    topic: "supported_description",
    institution: "supported_uei_or_exact_name",
    year_start: "supported_date_signed",
    year_end: "supported_date_signed",
    program: "supported_assistance_listing_code_only",
    opportunity_number: "unavailable",
    core_project_number: "unavailable",
    program_codes: "unavailable",
    program_office: "unavailable",
    pi: "unavailable",
    program_officer: "unavailable",
  }),
  fields: Object.freeze({
    description: "available",
    institution: "available",
    recipient_uei: "available_when_reported",
    assistance_listing: "detail_enrichment",
    award_amount: "total_obligation",
    project_dates: "available",
    abstract: "unavailable_at_source",
    principal_investigators: "unavailable_at_source",
    program_contacts: "unavailable_at_source",
    annual_support: "unavailable_at_source",
    opportunity_number: "detail_enrichment",
    awarding_office: "detail_enrichment",
  }),
  award_scope: "prime_assistance_awards_04_05_only",
});

function unsupported() {
  throw new AwardSourceError("source_query_unsupported", "unsupported");
}

function sourceInvalid() {
  throw new AwardSourceError("source_invalid_response");
}

function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function firstText(...values) {
  for (const value of values) {
    const text = cleanText(value, 2_000);
    if (text) return text;
  }
  return null;
}

function exactAwardId(value) {
  return cleanText(value, 120)?.toUpperCase() || null;
}

function assistanceListing(value) {
  const text = cleanText(value, 40);
  return ASSISTANCE_LISTING_PATTERN.test(text || "") ? text : null;
}

function searchFields() {
  return [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Start Date",
    "End Date",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Description",
    "Base Obligation Date",
    "Award Type",
    "generated_internal_id",
  ];
}

function dateFilter(criteria, now) {
  if (!criteria.year_start && !criteria.year_end) return [];
  const currentYear = now().getUTCFullYear();
  const startYear = Math.max(2007, Number(criteria.year_start || 2007));
  const endYear = Number(criteria.year_end || Math.max(startYear, currentYear));
  if (endYear < 2007) return null;
  return [{
    start_date: startYear === 2007 ? "2007-10-01" : `${startYear}-01-01`,
    end_date: `${endYear}-12-31`,
    date_type: "date_signed",
  }];
}

export function buildDodRequest(criteria, { page = 1, now = () => new Date() } = {}) {
  if (
    criteria.core_project_number
    || criteria.opportunity_number
    || criteria.program_codes
    || criteria.program_office
    || criteria.pi
    || criteria.program_officer
  ) unsupported();
  if (criteria.program && !ASSISTANCE_LISTING_PATTERN.test(criteria.program)) unsupported();

  const timePeriod = dateFilter(criteria, now);
  if (timePeriod === null) return null;
  const filters = {
    award_type_codes: [...DOD_AWARD_TYPE_CODES],
    agencies: [{ type: "awarding", tier: "toptier", name: DOD_AGENCY_NAME }],
    ...(timePeriod.length ? { time_period: timePeriod } : {}),
  };
  if (criteria.award_id) filters.award_ids = [exactAwardId(criteria.award_id)];
  if (criteria.topic) filters.description = criteria.topic;
  if (criteria.program) filters.program_numbers = [criteria.program];
  if (criteria._institution) {
    const identity = criteria._institution.sources?.DOD || {};
    const uei = (identity.uei || []).map(value => cleanText(value, 40)).find(Boolean);
    const name = cleanText(identity.search_name || criteria._institution.canonical_name, 300);
    if (!uei && !name) unsupported();
    filters.recipient_search_text = [uei || name];
  }
  return {
    subawards: false,
    spending_level: "awards",
    filters,
    fields: searchFields(),
    page,
    limit: DOD_UPSTREAM_PAGE_SIZE,
    sort: "Base Obligation Date",
    order: "desc",
  };
}

function searchRecords(payload) {
  if (!payload || typeof payload !== "object") sourceInvalid();
  const records = Array.isArray(payload.results)
    ? payload.results
    : payload.spending_by_award;
  if (!Array.isArray(records)) sourceInvalid();
  const page = object(payload.page_metadata);
  const pageNumber = Number(page.page);
  const parsedTotal = page.total === null || page.total === undefined ? null : Number(page.total);
  const total = Number.isFinite(parsedTotal) && parsedTotal >= 0 ? parsedTotal : null;
  if (!Number.isInteger(pageNumber) || pageNumber < 1) sourceInvalid();
  return {
    records,
    page: pageNumber,
    total,
    hasNext: page.hasNext === true,
  };
}

function searchAwardType(raw) {
  const label = firstText(raw["Award Type"], raw.award_type, raw.type_description);
  if (DOD_AWARD_TYPE_LABELS.project_grant.test(label || "")) return "Project Grant";
  if (DOD_AWARD_TYPE_LABELS.cooperative_agreement.test(label || "")) return "Cooperative Agreement";
  return null;
}

function isDodAgency(raw) {
  const agency = firstText(raw["Awarding Agency"], raw.awarding_agency_name);
  return agency === DOD_AGENCY_NAME || agency === "Department of Defense (DOD)";
}

function baseRawAward(raw) {
  const generatedId = firstText(raw.generated_internal_id, raw.generated_unique_award_id);
  const awardId = exactAwardId(firstText(raw["Award ID"], raw.award_id, raw.fain));
  if (!generatedId || !/^ASST_/i.test(generatedId) || !awardId) return null;
  const awardType = searchAwardType(raw);
  if (!isDodAgency(raw) || !awardType) return null;
  return {
    generated_id: generatedId,
    award_id: awardId,
    recipient_name: firstText(raw["Recipient Name"], raw.recipient_name),
    recipient_uei: firstText(raw["Recipient UEI"], raw.recipient_uei),
    project_start: isoDate(firstText(raw["Start Date"], raw.start_date)),
    project_end: isoDate(firstText(raw["End Date"], raw.end_date)),
    total_obligation: finiteNumber(raw["Award Amount"] ?? raw.award_amount),
    agency: firstText(raw["Awarding Agency"], raw.awarding_agency_name),
    subagency: firstText(raw["Awarding Sub Agency"], raw.awarding_sub_agency_name),
    description: cleanSourceText(firstText(raw.Description, raw.description), 20_000),
    base_obligation_date: isoDate(firstText(raw["Base Obligation Date"], raw.base_obligation_date)),
    award_type: awardType,
  };
}

function detailCacheRequest(generatedId) {
  return new Request(`https://award-cache.internal/v1/dod-detail/${encodeURIComponent(generatedId)}`);
}

async function readDetail(fetchImpl, generatedId, { cache, cacheTtl }) {
  const key = detailCacheRequest(generatedId);
  if (cache) {
    try {
      const cached = await cache.match(key);
      if (cached) {
        const payload = await cached.json();
        if (cleanText(payload?.generated_unique_award_id, 300) === generatedId) return { payload, cache: "hit" };
      }
    } catch {
      // A detail-cache outage must not discard the base USAspending award.
    }
  }
  const encodedId = encodeURIComponent(generatedId);
  const payload = await fetchSourceJson(fetchImpl, `${DOD_DETAIL_URL}/${encodedId}/`, {
    headers: { Accept: "application/json" },
  });
  if (cleanText(payload?.generated_unique_award_id, 300) !== generatedId) sourceInvalid();
  if (cache) {
    try {
      await cache.put(key, new Response(JSON.stringify(payload), {
        headers: {
          "Cache-Control": `public, max-age=${cacheTtl}`,
          "Content-Type": "application/json; charset=utf-8",
        },
      }));
    } catch {
      // Successful live detail data remains usable if cache storage fails.
    }
  }
  return { payload, cache: cache ? "miss" : "bypass" };
}

function detailAgency(detail) {
  const awarding = object(detail.awarding_agency);
  return {
    agency: firstText(awarding.toptier_agency?.name, detail.awarding_agency_name),
    subagency: firstText(awarding.subtier_agency?.name, detail.awarding_sub_agency_name),
    office: firstText(awarding.office_agency_name, detail.awarding_office_name),
  };
}

function detailRecipient(detail) {
  const recipient = object(detail.recipient);
  return {
    name: firstText(recipient.recipient_name, detail.recipient_name),
    uei: firstText(recipient.recipient_uei, detail.recipient_uei),
  };
}

function detailPeriod(detail) {
  const period = object(detail.period_of_performance);
  return {
    start: isoDate(firstText(period.start_date, detail.period_of_performance_start_date)),
    end: isoDate(firstText(period.end_date, detail.period_of_performance_current_end_date)),
  };
}

function detailListing(detail) {
  const listings = Array.isArray(detail.cfda_info) ? detail.cfda_info : [];
  const first = listings.map(object).find(item => assistanceListing(item.cfda_number));
  const code = assistanceListing(firstText(first?.cfda_number, detail.cfda_number));
  return {
    code,
    title: firstText(first?.cfda_title, detail.cfda_title),
  };
}

function detailOpportunity(detail) {
  const opportunity = object(detail.funding_opportunity);
  const value = firstText(opportunity.number, detail.funding_opportunity_number)?.toUpperCase() || "";
  if (!value || UNAVAILABLE_OPPORTUNITY_NUMBERS.has(value) || !OPPORTUNITY_NUMBER_PATTERN.test(value)) return null;
  return value;
}

function uniqueBaseAwards(values) {
  const seen = new Set();
  return values.filter(award => {
    const key = award?.generated_id || award?.award_id;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function normalizeDodAward(raw, { detail = null, retrievedAt } = {}) {
  const sourceDetail = object(detail);
  const agency = detailAgency(sourceDetail);
  const recipient = detailRecipient(sourceDetail);
  const period = detailPeriod(sourceDetail);
  const listing = detailListing(sourceDetail);
  const opportunityNumber = detailOpportunity(sourceDetail);
  const generatedId = firstText(sourceDetail.generated_unique_award_id, raw.generated_id);
  const officialUrl = safeOfficialUrl(
    generatedId ? `https://${DOD_PROFILE_HOST}/award/${encodeURIComponent(generatedId)}/` : null,
    [DOD_PROFILE_HOST],
  );
  const awardDate = isoDate(firstText(sourceDetail.date_signed, raw.base_obligation_date));
  const awardYear = Number(awardDate?.slice(0, 4)) || null;
  const detailType = cleanText(sourceDetail.type, 20);
  const mechanism = DOD_AWARD_TYPE_CODES.includes(detailType)
    ? (detailType === "04" ? "Project Grant" : "Cooperative Agreement")
    : raw.award_type;
  return awardRecord({
    award_id: exactAwardId(firstText(sourceDetail.fain, raw.award_id)),
    source_record_ids: uniqueStrings([raw.award_id, generatedId]),
    source: "DOD",
    agency: agency.agency || raw.agency || DOD_AGENCY_NAME,
    subagency: agency.subagency || raw.subagency,
    program_name: listing.title,
    program_codes: uniqueStrings([listing.code]),
    opportunity_numbers: uniqueStrings([opportunityNumber]),
    activity_code: null,
    funding_mechanism: mechanism,
    title: cleanSourceText(firstText(sourceDetail.description, raw.description), 20_000),
    abstract: null,
    award_date: awardDate,
    project_start: period.start || raw.project_start,
    project_end: period.end || raw.project_end,
    award_year: awardYear,
    total_award: finiteNumber(sourceDetail.total_obligation ?? raw.total_obligation),
    award_amount_basis: finiteNumber(sourceDetail.total_obligation ?? raw.total_obligation) === null
      ? null
      : "total_obligation",
    institution: normalizeInstitution(recipient.name || raw.recipient_name, {
      uei: recipient.uei || raw.recipient_uei,
    }),
    organization_department: agency.office,
    principal_investigators: [],
    program_contacts: [],
    official_award_url: officialUrl,
    annual_support: [],
    source_provenance: {
      source_url: officialUrl || DOD_SEARCH_URL,
      retrieved_at: retrievedAt,
      source_record_id: generatedId || raw.award_id,
      adapter_version: DOD_ADAPTER_VERSION,
    },
  });
}

async function enrichDetails(fetchImpl, rawAwards, options) {
  const output = [];
  let requested = 0;
  let loaded = 0;
  let failed = 0;
  let cacheHits = 0;
  for (let index = 0; index < rawAwards.length; index += DOD_DETAIL_CONCURRENCY) {
    const batch = rawAwards.slice(index, index + DOD_DETAIL_CONCURRENCY);
    const values = await Promise.all(batch.map(async raw => {
      requested += 1;
      try {
        const result = await readDetail(fetchImpl, raw.generated_id, options);
        loaded += 1;
        if (result.cache === "hit") cacheHits += 1;
        return { raw, detail: result.payload };
      } catch {
        failed += 1;
        return { raw, detail: null };
      }
    }));
    output.push(...values);
  }
  return { output, requested, loaded, failed, cacheHits };
}

function emptyPayload(retrievedAt, criteria) {
  return {
    source: "DOD",
    adapter_version: DOD_ADAPTER_VERSION,
    retrieved_at: retrievedAt,
    total_count: 0,
    raw_record_count: 0,
    upstream_total_count: 0,
    upstream_pages: 0,
    safety_bound_reached: false,
    has_more: false,
    capabilities: DOD_CAPABILITIES,
    year_filter: yearFilterDiagnostics(criteria),
    results: [],
    health: { status: "available", detail_requests: 0, details_loaded: 0, details_failed: 0, detail_cache_hits: 0 },
  };
}

export async function searchDod(fetchImpl, criteria, {
  limit = DOD_MAX_RESULTS,
  offset = 0,
  now = () => new Date(),
  scanAll = false,
  cache = null,
  cacheTtl = 3_600,
} = {}) {
  if (limit > DOD_MAX_RESULTS) unsupported();
  const retrievedAt = now().toISOString();
  const firstPage = Math.floor(offset / DOD_UPSTREAM_PAGE_SIZE) + 1;
  const localOffset = offset % DOD_UPSTREAM_PAGE_SIZE;
  const lastPage = Math.floor((offset + limit - 1) / DOD_UPSTREAM_PAGE_SIZE) + 1;
  const firstRequest = buildDodRequest(criteria, { page: firstPage, now });
  if (!firstRequest) return emptyPayload(retrievedAt, criteria);

  const pages = [];
  for (let page = firstPage; page <= lastPage; page += 1) {
    const body = buildDodRequest(criteria, { page, now });
    const payload = await fetchSourceJson(fetchImpl, DOD_SEARCH_URL, {
      method: "POST",
      headers: REQUEST_HEADERS,
      body: JSON.stringify(body),
    });
    const parsed = searchRecords(payload);
    pages.push(parsed);
    if (!parsed.hasNext) break;
  }

  const rawRecords = pages.flatMap(page => page.records);
  const baseAwards = rawRecords.map(baseRawAward).filter(Boolean);
  const selected = uniqueBaseAwards(baseAwards.slice(localOffset, localOffset + limit));
  const enrichment = await enrichDetails(fetchImpl, selected, { cache, cacheTtl });
  const yearFilter = yearFilterDiagnostics(criteria);
  const normalized = enrichment.output.map(({ raw, detail }) => normalizeDodAward(raw, { detail, retrievedAt }))
    .filter(award => !criteria.award_id || award.award_id === exactAwardId(criteria.award_id))
    .filter(award => recordSatisfiesYearFilter(award.award_year, criteria, yearFilter))
    .filter(award => recordMatchesInstitution(award, criteria._institution, "DOD"))
    .map(award => attachResolvedInstitution(award, criteria._institution));
  const last = pages.at(-1);
  const hasMore = Boolean(last?.hasNext || baseAwards.length > localOffset + limit);
  return {
    source: "DOD",
    adapter_version: DOD_ADAPTER_VERSION,
    retrieved_at: retrievedAt,
    total_count: criteria._institution || criteria.year_start || criteria.year_end ? null : last?.total ?? null,
    raw_record_count: rawRecords.length,
    upstream_total_count: last?.total ?? null,
    upstream_pages: pages.length,
    safety_bound_reached: scanAll && hasMore,
    has_more: scanAll ? false : hasMore,
    capabilities: DOD_CAPABILITIES,
    year_filter: yearFilter,
    results: normalized,
    health: {
      status: "available",
      detail_requests: enrichment.requested,
      details_loaded: enrichment.loaded,
      details_failed: enrichment.failed,
      detail_cache_hits: enrichment.cacheHits,
    },
  };
}

export { ASSISTANCE_LISTING_PATTERN, DOD_API_HOST };
