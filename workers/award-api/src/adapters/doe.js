import { load } from "cheerio/slim";

import {
  awardRecord,
  cleanSourceText,
  cleanText,
  finiteNumber,
  isoDate,
  makeContact,
  safeOfficialUrl,
  uniqueStrings,
} from "../contract.js";
import { AwardSourceError, fetchSourceText } from "../http.js";
import { normalizeInstitution, recordMatchesInstitution } from "../institutions.js";

export const DOE_ADAPTER_VERSION = "1.0.0";
export const DOE_SEARCH_URL = "https://pamspublic.science.energy.gov/WebPAMSExternal/Interface/Awards/AwardSearchExternal.aspx";
export const DOE_MAX_RESULTS = 10;
export const DOE_MAX_OFFSET = 100;

const DOE_HOST = "pamspublic.science.energy.gov";
const DOE_REQUEST_TIMEOUT_MS = 15_000;
const DOE_ABSTRACT_CONCURRENCY = 2;
const DOE_ABSTRACT_PAUSE_MS = 125;
const FORM_PREFIX = "ctl00$MainContent$pnlSearch$";
const COUNTRY_CLIENT_STATE = "ctl00_MainContent_pnlSearch_rlbCountry_ClientState";
const SEARCH_EVENT_TARGET = "ctl00$MainContent$pnlSearch";
const SEARCH_EVENT_ARGUMENT = "CustomSortSelected=False SearchPanelExpanded=True Search";
const REQUEST_HEADERS = Object.freeze({
  Accept: "text/html,application/xhtml+xml",
  "Accept-Language": "en-US,en;q=0.8",
  "Cache-Control": "no-cache",
});

function unsupported() {
  throw new AwardSourceError("source_query_unsupported", "unsupported");
}

function sourceInvalid() {
  throw new AwardSourceError("source_invalid_response");
}

function pamsUrl(value) {
  const decoded = cleanText(value, 2_000);
  if (!decoded) return null;
  let candidate = decoded;
  try {
    candidate = decodeURIComponent(candidate);
  } catch {
    // A plain, already-decoded PAMS path remains usable.
  }
  try {
    const url = new URL(candidate, DOE_SEARCH_URL);
    return safeOfficialUrl(url.href, [DOE_HOST]);
  } catch {
    return null;
  }
}

function popupUrl(href) {
  const text = cleanText(href, 4_000);
  if (/ViewPublicAbstract\.aspx/i.test(text || "") && !/^javascript:/i.test(text)) {
    return pamsUrl(text);
  }
  const match = /OpenPopupWithMenuBar\(\s*(["'])(.*?)\1/i.exec(text || "");
  if (!match || !/ViewPublicAbstract\.aspx/i.test(match[2])) return null;
  return pamsUrl(match[2]);
}

function splitPersonName(value) {
  const text = cleanText(value, 160);
  if (!text) return { first: null, last: null };
  if (text.includes(",")) {
    const [last, ...first] = text.split(",");
    return { first: cleanText(first.join(" "), 80), last: cleanText(last, 80) };
  }
  const parts = text.split(" ").filter(Boolean);
  if (parts.length === 1) return { first: null, last: parts[0] };
  return { first: parts.slice(0, -1).join(" "), last: parts.at(-1) };
}

function displayPersonName(value) {
  const { first, last } = splitPersonName(value);
  return cleanText([first, last].filter(Boolean).join(" "), 160);
}

function dateClientState(year, lastDay = false) {
  const date = lastDay ? `12/31/${year}` : `1/1/${year}`;
  const machine = lastDay ? `${year}-12-31-00-00-00` : `${year}-01-01-00-00-00`;
  return JSON.stringify({
    enabled: true,
    emptyMessage: "",
    validationText: machine,
    valueAsString: machine,
    minDateStr: "1980-00-01-00-01-00",
    maxDateStr: "2099-00-31-00-12-00",
    lastSetTextBoxValue: date,
  });
}

function setDate(params, field, year, lastDay = false) {
  if (!year) return;
  const date = lastDay ? `12/31/${year}` : `1/1/${year}`;
  const iso = lastDay ? `${year}-12-31` : `${year}-01-01`;
  params.set(`${FORM_PREFIX}${field}`, iso);
  params.set(`${FORM_PREFIX}${field}$dateInput`, date);
  params.set(`ctl00_MainContent_pnlSearch_${field}_dateInput_ClientState`, dateClientState(year, lastDay));
}

function hiddenForm(html) {
  const $ = load(html);
  const form = $("#aspnetForm");
  if (form.length !== 1) sourceInvalid();
  const params = new URLSearchParams();
  form.find('input[type="hidden"][name]').each((_index, element) => {
    const name = $(element).attr("name");
    if (name) params.set(name, $(element).attr("value") || "");
  });
  if (!params.has("__VIEWSTATE")) sourceInvalid();
  return params;
}

export function buildDoeSearchForm(html, criteria) {
  if (criteria.core_project_number || criteria.program_codes) unsupported();
  if (criteria.award_id && !/^DE-[A-Z0-9-]+$/i.test(criteria.award_id)) unsupported();
  if (criteria.opportunity_number && !/^DE-FOA-\d+$/i.test(criteria.opportunity_number)) unsupported();

  const params = hiddenForm(html);
  params.set("__EVENTTARGET", SEARCH_EVENT_TARGET);
  params.set("__EVENTARGUMENT", SEARCH_EVENT_ARGUMENT);
  params.set(`${FORM_PREFIX}ddAwardStatus`, "0");
  params.set(COUNTRY_CLIENT_STATE, JSON.stringify({
    isEnabled: true,
    logEntries: [],
    selectedIndices: [],
    checkedIndices: [],
    scrollPosition: 0,
  }));

  if (criteria.award_id) params.set(`${FORM_PREFIX}txtAwardNumber`, criteria.award_id.toUpperCase());
  if (criteria.topic) params.set(`${FORM_PREFIX}txtAbstractKeyword`, criteria.topic);
  if (criteria.opportunity_number) params.set(`${FORM_PREFIX}txtSolNum`, criteria.opportunity_number.toUpperCase());
  if (criteria.program) params.set(`${FORM_PREFIX}txtProgramArea`, criteria.program);
  if (criteria._institution) {
    const sourceIdentity = criteria._institution.sources?.DOE || {};
    params.set(`${FORM_PREFIX}txtInstitutionName`, sourceIdentity.search_name || criteria._institution.canonical_name);
  }
  const pi = splitPersonName(criteria.pi);
  if (pi.last) params.set(`${FORM_PREFIX}txtPILastName`, pi.last);
  if (pi.first) params.set(`${FORM_PREFIX}txtPIFirstName`, pi.first);
  const manager = splitPersonName(criteria.program_officer);
  if (manager.last) params.set(`${FORM_PREFIX}txtPMLastName`, manager.last);
  if (manager.first) params.set(`${FORM_PREFIX}txtPMFirstName`, manager.first);
  setDate(params, "dpAwardDateFrom", criteria.year_start, false);
  setDate(params, "dpAwardDateTo", criteria.year_end, true);
  return params;
}

function detailFields($, row) {
  const values = new Map();
  const detail = row.next("tr");
  detail.find("li").each((_index, element) => {
    const text = cleanText($(element).text(), 4_000);
    const separator = text?.indexOf(":") ?? -1;
    if (separator < 1) return;
    values.set(text.slice(0, separator).trim(), text.slice(separator + 1).trim());
  });
  return values;
}

function institutionName(value) {
  const text = cleanText(value, 500);
  const match = /^(.*),\s*[^,]+,\s*[A-Z]{2}$/.exec(text || "");
  return cleanText(match?.[1] || text, 500);
}

function pageTarget($, pageNumber) {
  let target = null;
  $("#ctl00_MainContent_grdAwardsList a").each((_index, element) => {
    if (cleanText($(element).text(), 20) !== String(pageNumber)) return;
    const match = /__doPostBack\('([^']+)'\s*,\s*'[^']*'\)/.exec($(element).attr("href") || "");
    if (match) target = match[1];
  });
  return target;
}

export function parseDoeSearchResults(html) {
  const $ = load(html);
  if (!/Award Search/i.test($("title").text()) || $("#aspnetForm").length !== 1) sourceInvalid();
  const grid = $("#ctl00_MainContent_grdAwardsList");
  if (!grid.length) {
    if (/\b0\s+items?\b|no\s+(?:records|awards)\s+(?:were\s+)?found/i.test($.root().text())) {
      return { records: [], total_count: 0, page_count: 0, page_size: 15, page_targets: {} };
    }
    sourceInvalid();
  }

  const pagerText = cleanText(grid.text(), 100_000) || "";
  const countMatch = /([\d,]+)\s+items?\s+in\s+([\d,]+)\s+page/i.exec(pagerText);
  const pageSizeValue = Number($("input[id*='PageSizeComboBox_Input']").first().attr("value") || 15);
  if (!countMatch || !Number.isInteger(pageSizeValue) || pageSizeValue < 1 || pageSizeValue > 100) sourceInvalid();

  const records = [];
  grid.find('tr[id*="grdAwardsList"][id*="__"]').each((_index, element) => {
    const row = $(element);
    const cells = row.children("td");
    if (cells.length < 7) return;
    const awardId = cleanText(cells.eq(1).text(), 80);
    if (!/^DE-[A-Z0-9-]+$/i.test(awardId || "")) return;
    const details = detailFields($, row);
    let abstractUrl = null;
    row.find("a").each((_linkIndex, link) => {
      if (!abstractUrl && /View Abstract/i.test($(link).text())) abstractUrl = popupUrl($(link).attr("href"));
    });
    const solicitation = details.get("Solicitation") || "";
    const opportunityNumbers = uniqueStrings(solicitation.match(/DE-FOA-\d+/gi) || []).map(value => value.toUpperCase());
    records.push({
      award_id: awardId.toUpperCase(),
      title: cleanText(cells.eq(2).text(), 2_000),
      institution_name: institutionName(cells.eq(3).text()),
      pi_name: cleanText(cells.eq(4).text(), 300),
      action_type: cleanText(cells.eq(5).text(), 120),
      abstract_url: abstractUrl,
      org_code: cleanText(details.get("Org Code"), 80),
      program_office: cleanText(details.get("Program Office"), 300),
      program_manager: cleanText(details.get("PM"), 300),
      status: cleanText(details.get("Status"), 80),
      project_start: isoDate(details.get("Start Date")),
      project_end: isoDate(details.get("End Date")),
      most_recent_award_date: isoDate(details.get("Most Recent Award Date")),
      award_type: cleanText(details.get("Award Type"), 160),
      amount_awarded_to_date: finiteNumber(details.get("Amount Awarded to Date")),
      amount_awarded_this_fy: finiteNumber(details.get("Amount Awarded this FY")),
      institution_type: cleanText(details.get("Institution Type"), 300),
      uei: cleanText(details.get("UEI"), 40),
      program_area: cleanText(details.get("Program Area"), 500),
      register_number: cleanText(details.get("Register Number"), 80),
      duns: cleanText(details.get("DUNS"), 40),
      solicitation: cleanText(solicitation, 4_000),
      opportunity_numbers: opportunityNumbers,
    });
  });

  const pageCount = Number(countMatch[2].replaceAll(",", ""));
  const pageTargets = {};
  for (let page = 1; page <= Math.min(pageCount, 10); page += 1) {
    const target = pageTarget($, page);
    if (target) pageTargets[page] = target;
  }
  return {
    records,
    total_count: Number(countMatch[1].replaceAll(",", "")),
    page_count: pageCount,
    page_size: pageSizeValue,
    page_targets: pageTargets,
  };
}

const SUBSCRIPT = Object.freeze({
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
  "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
  "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎",
});
const SUPERSCRIPT = Object.freeze({
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
  "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
  "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
});

function scientificText(node, script = null) {
  if (node.type === "text") {
    const value = node.data || "";
    if (!script) return value;
    const alphabet = script === "sub" ? SUBSCRIPT : SUPERSCRIPT;
    return [...value].map(character => alphabet[character] || character).join("");
  }
  const name = String(node.name || "").toLowerCase();
  if (name === "br") return "\n";
  const nextScript = ["sub", "sup"].includes(name) ? name : script;
  return (node.children || []).map(child => scientificText(child, nextScript)).join("");
}

export function parseDoeAbstract(html, expectedAwardId = null) {
  const $ = load(html);
  if (!/Public Abstract/i.test($("title").text())) sourceInvalid();
  const heading = cleanText($("h3").first().text(), 2_000);
  if (expectedAwardId && !heading?.toUpperCase().includes(String(expectedAwardId).toUpperCase())) sourceInvalid();
  const cell = $("table.ehb_datatable td").first();
  if (!cell.length) sourceInvalid();
  const paragraphs = [];
  cell.find("p").each((_index, element) => {
    const text = cleanSourceText(scientificText(element), 20_000);
    if (text) paragraphs.push(text);
  });
  const abstract = cleanSourceText(
    paragraphs.length ? paragraphs.join("\n\n") : scientificText(cell.get(0)),
    20_000,
  );
  if (!abstract) sourceInvalid();
  return abstract;
}

export function normalizeDoeAward(raw, { retrievedAt, abstract = null } = {}) {
  const officialUrl = raw.abstract_url || DOE_SEARCH_URL;
  const pi = makeContact({
    name: displayPersonName(raw.pi_name),
    role: "Principal Investigator",
    email: null,
    officialContactUrl: officialUrl,
    sourceField: "PI",
    sourceUrl: officialUrl,
  });
  const manager = makeContact({
    name: displayPersonName(raw.program_manager),
    role: "Program Manager",
    email: null,
    officialContactUrl: officialUrl,
    sourceField: "PM",
    sourceUrl: officialUrl,
  });
  const awardYear = Number(raw.most_recent_award_date?.slice(0, 4)) || null;
  return awardRecord({
    award_id: raw.award_id,
    source_record_ids: uniqueStrings([raw.award_id, raw.register_number]),
    source: "DOE",
    agency: "U.S. Department of Energy Office of Science",
    subagency: raw.program_office,
    program_name: raw.program_area || raw.program_office,
    program_codes: uniqueStrings([raw.org_code]),
    opportunity_numbers: raw.opportunity_numbers,
    activity_code: null,
    funding_mechanism: raw.award_type || raw.action_type,
    title: raw.title,
    abstract: cleanSourceText(abstract, 20_000),
    project_start: raw.project_start,
    project_end: raw.project_end,
    award_year: awardYear,
    total_award: raw.amount_awarded_to_date,
    award_amount_basis: raw.amount_awarded_to_date === null ? null : "amount_awarded_to_date",
    institution: normalizeInstitution(raw.institution_name, { uei: raw.uei, other: raw.duns ? `DUNS:${raw.duns}` : null }),
    organization_department: raw.org_code,
    principal_investigators: pi ? [pi] : [],
    program_contacts: manager ? [manager] : [],
    official_award_url: officialUrl,
    annual_support: [],
    source_provenance: {
      source_url: officialUrl,
      retrieved_at: retrievedAt,
      source_record_id: raw.award_id,
      adapter_version: DOE_ADAPTER_VERSION,
    },
  });
}

async function postPage(fetchImpl, html, target) {
  const params = hiddenForm(html);
  params.set("__EVENTTARGET", target);
  params.set("__EVENTARGUMENT", "");
  const { body } = await fetchSourceText(fetchImpl, DOE_SEARCH_URL, {
    method: "POST",
    headers: { ...REQUEST_HEADERS, "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  }, { timeoutMs: DOE_REQUEST_TIMEOUT_MS });
  return body;
}

async function enrichAbstracts(fetchImpl, records, sleep) {
  const enriched = [];
  let requested = 0;
  let loaded = 0;
  let failed = 0;
  for (let index = 0; index < records.length; index += DOE_ABSTRACT_CONCURRENCY) {
    const batch = records.slice(index, index + DOE_ABSTRACT_CONCURRENCY);
    const values = await Promise.all(batch.map(async raw => {
      if (!raw.abstract_url) return { raw, abstract: null };
      requested += 1;
      try {
        const { body } = await fetchSourceText(fetchImpl, raw.abstract_url, {
          headers: REQUEST_HEADERS,
        }, { timeoutMs: DOE_REQUEST_TIMEOUT_MS });
        const abstract = parseDoeAbstract(body, raw.award_id);
        loaded += 1;
        return { raw, abstract };
      } catch {
        failed += 1;
        return { raw, abstract: null };
      }
    }));
    enriched.push(...values);
    if (index + DOE_ABSTRACT_CONCURRENCY < records.length) await sleep(DOE_ABSTRACT_PAUSE_MS);
  }
  return { enriched, requested, loaded, failed };
}

export async function searchDoe(fetchImpl, criteria, {
  limit,
  offset,
  now = () => new Date(),
  sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)),
} = {}) {
  if (limit > DOE_MAX_RESULTS) unsupported();
  const retrievedAt = now().toISOString();
  if (offset > DOE_MAX_OFFSET) {
    return {
      source: "DOE",
      adapter_version: DOE_ADAPTER_VERSION,
      retrieved_at: retrievedAt,
      total_count: null,
      raw_record_count: 0,
      has_more: false,
      results: [],
      health: { status: "available", abstract_requests: 0, abstracts_loaded: 0, abstracts_failed: 0 },
    };
  }

  const { body: searchForm } = await fetchSourceText(fetchImpl, DOE_SEARCH_URL, {
    headers: REQUEST_HEADERS,
  }, { timeoutMs: DOE_REQUEST_TIMEOUT_MS });
  const form = buildDoeSearchForm(searchForm, criteria);
  const { body: firstPageHtml } = await fetchSourceText(fetchImpl, DOE_SEARCH_URL, {
    method: "POST",
    headers: { ...REQUEST_HEADERS, "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  }, { timeoutMs: DOE_REQUEST_TIMEOUT_MS });
  const firstPage = parseDoeSearchResults(firstPageHtml);
  const firstNeededPage = Math.floor(offset / firstPage.page_size) + 1;
  const lastNeededIndex = Math.min(offset + limit - 1, DOE_MAX_OFFSET + DOE_MAX_RESULTS - 1);
  const lastNeededPage = Math.floor(lastNeededIndex / firstPage.page_size) + 1;
  const pages = new Map([[1, { html: firstPageHtml, parsed: firstPage }]]);
  let currentHtml = firstPageHtml;
  let currentParsed = firstPage;
  for (let page = firstNeededPage; page <= lastNeededPage; page += 1) {
    if (pages.has(page) || page > firstPage.page_count) continue;
    const target = currentParsed.page_targets[page];
    if (!target) sourceInvalid();
    currentHtml = await postPage(fetchImpl, currentHtml, target);
    currentParsed = parseDoeSearchResults(currentHtml);
    pages.set(page, { html: currentHtml, parsed: currentParsed });
  }

  const positioned = new Map();
  let rawRecordCount = 0;
  for (const [page, value] of pages) {
    rawRecordCount += value.parsed.records.length;
    const pageStart = (page - 1) * firstPage.page_size;
    value.parsed.records.forEach((record, index) => positioned.set(pageStart + index, record));
  }
  const selected = [];
  for (let index = offset; index < offset + limit; index += 1) {
    const record = positioned.get(index);
    if (record) selected.push(record);
  }
  const sourceScoped = criteria._institution
    ? selected.filter(raw => recordMatchesInstitution({
      institution: normalizeInstitution(raw.institution_name, { uei: raw.uei }),
    }, criteria._institution, "DOE"))
    : selected;
  const abstracts = await enrichAbstracts(fetchImpl, sourceScoped, sleep);
  const results = abstracts.enriched.map(({ raw, abstract }) => normalizeDoeAward(raw, {
    retrievedAt,
    abstract,
  }));
  const hasMore = offset < DOE_MAX_OFFSET && offset + limit < firstPage.total_count;
  return {
    source: "DOE",
    adapter_version: DOE_ADAPTER_VERSION,
    retrieved_at: retrievedAt,
    total_count: firstPage.total_count,
    raw_record_count: rawRecordCount,
    has_more: hasMore,
    results,
    health: {
      status: abstracts.failed ? "degraded" : "available",
      abstract_requests: abstracts.requested,
      abstracts_loaded: abstracts.loaded,
      abstracts_failed: abstracts.failed,
    },
  };
}
