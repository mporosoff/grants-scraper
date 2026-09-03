(() => {
  "use strict";

  const SOURCE_NAMES = ["NSF", "NIH", "DOE"];
  const DOE_PAGE_LIMIT = 10;
  const AWARD_YEAR_MIN = 1989;
  const AWARD_YEAR_MAX = 2100;

  function clean(value, maximum = 500) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.slice(0, maximum);
  }

  function displayInvestigatorName(value) {
    const name = clean(value, 300);
    if (!name) return "";
    const casedLetters = [...name].filter(character => (
      character.toLocaleUpperCase("en-US") !== character.toLocaleLowerCase("en-US")
    ));
    const hasUpper = casedLetters.some(character => character === character.toLocaleUpperCase("en-US"));
    const hasLower = casedLetters.some(character => character === character.toLocaleLowerCase("en-US"));
    if (!casedLetters.length || hasUpper && hasLower) return name;
    return name
      .toLocaleLowerCase("en-US")
      .replace(/(^|[\s,.'’\-])(\p{L})/gu, (_match, prefix, letter) => `${prefix}${letter.toLocaleUpperCase("en-US")}`)
      .replace(/\bMc(\p{Ll})/gu, (_match, letter) => `Mc${letter.toLocaleUpperCase("en-US")}`)
      .replace(/([\s,])(?:Ii|Iii|Iv|Vi|Vii|Viii|Ix|X)\.?$/u, match => match.toLocaleUpperCase("en-US"));
  }

  function year(value) {
    const number = Number(value);
    return Number.isInteger(number) && number >= AWARD_YEAR_MIN && number <= AWARD_YEAR_MAX ? number : null;
  }

  function presentFiniteNumber(value) {
    if (typeof value === "number") return Number.isFinite(value) ? value : null;
    if (typeof value !== "string" || !value.trim()) return null;
    const number = Number(value.trim());
    return Number.isFinite(number) ? number : null;
  }

  function awardYear(value) {
    const number = presentFiniteNumber(value);
    return Number.isInteger(number) && number >= AWARD_YEAR_MIN && number <= AWARD_YEAR_MAX
      ? number
      : null;
  }

  function awardYearRange(results) {
    const years = (Array.isArray(results) ? results : [])
      .map(award => awardYear(award?.award_year))
      .filter(value => value !== null)
      .sort((left, right) => left - right);
    if (!years.length) return null;
    return years[0] === years.at(-1) ? String(years[0]) : `${years[0]}–${years.at(-1)}`;
  }

  function boundedErrorCode(value) {
    return clean(value?.error?.code, 80).toLowerCase();
  }

  function sourceIssueText(source) {
    const name = clean(source?.source, 20) || "Selected source";
    if (source?.status === "unsupported") {
      return `${name} does not support this filter combination.`;
    }
    const code = boundedErrorCode(source);
    if (["rate_limited", "source_rate_limited"].includes(code)) {
      return `${name} is rate limited. Wait before retrying.`;
    }
    if (["invalid_response", "source_invalid_response"].includes(code)) {
      return `${name} returned an invalid service response. Retry later.`;
    }
    return `${name} is temporarily unavailable. Retry later.`;
  }

  function serviceIssueText(payload) {
    const code = boundedErrorCode(payload);
    if (code === "invalid_request") {
      return "Check the submitted award filters and try again.";
    }
    if (["rate_limited", "source_rate_limited"].includes(code)) {
      return "Award search is rate limited. Wait before retrying.";
    }
    if (["service_unavailable", "source_unavailable"].includes(code)) {
      return "The award service is unavailable. Retry later.";
    }
    return "";
  }

  function paginationLabel(payload, resultCount = payload?.results?.length || 0) {
    const count = Math.max(0, Number(resultCount) || 0);
    const bounded = (payload?.sources || []).filter(source => source?.safety_bound_reached === true).map(source => clean(source?.source, 20)).filter(Boolean);
    const boundSuffix = bounded.length ? ` · upstream scan bound reached for ${bounded.join(", ")}` : "";
    if (!count) return `No results on this page${boundSuffix}`;
    const offset = Math.max(0, Number(payload?.pagination?.offset) || 0);
    const requestedSources = Array.isArray(payload?.request?.sources)
      ? payload.request.sources
      : (payload?.sources || []).map(source => source?.source);
    const sourceCount = new Set(requestedSources.map(source => clean(source, 20)).filter(Boolean)).size;
    if (sourceCount <= 1) return `Results ${offset + 1}–${offset + count}${boundSuffix}`;
    const noun = count === 1 ? "result" : "results";
    return offset
      ? `${count.toLocaleString()} ${noun} on this page · each source is paged independently after its first ${offset.toLocaleString()} results${boundSuffix}`
      : `${count.toLocaleString()} ${noun} on this source-scoped page${boundSuffix}`;
  }

  function sourcesForAgency(agency) {
    const value = clean(agency, 10).toUpperCase();
    return SOURCE_NAMES.includes(value) ? [value] : [...SOURCE_NAMES];
  }

  function standaloneCriterion({ mode, agency, query }) {
    const value = clean(query);
    if (!value) return {};
    if (mode === "pi") return { pi: value };
    if (mode === "program_officer") return { program_officer: value };
    if (mode !== "program") return { topic: value };
    const source = clean(agency, 10).toUpperCase();
    if (!SOURCE_NAMES.includes(source)) {
      throw new Error("Choose NSF, NIH, or DOE when searching by program identifier or name.");
    }
    if (source === "NSF") {
      const pdCode = globalThis.FUNDING_AWARD_LINKS?.nsfProgramElementCode(value);
      if (pdCode) return { program_codes: [pdCode] };
      return { program: /^[A-Z0-9]{6}$/i.test(value) ? value.toUpperCase() : value };
    }
    if (source === "NIH") {
      return value.includes("-")
        ? { opportunity_number: value.toUpperCase() }
        : { program: value.toUpperCase() };
    }
    return /^DE-FOA-\d+$/i.test(value)
      ? { opportunity_number: value.toUpperCase() }
      : { program: value };
  }

  function buildRequest(state, selectedLookup, limit = 25) {
    const criteria = selectedLookup
      ? { ...selectedLookup.criteria }
      : standaloneCriterion(state);
    const institution = clean(state.institution, 300);
    const pi = clean(state.pi, 160);
    const programOfficer = clean(state.program_officer, 160);
    const yearStart = year(state.year_start);
    const yearEnd = year(state.year_end);
    if (institution) criteria.institution = institution;
    if (pi) criteria.pi = pi;
    if (programOfficer) criteria.program_officer = programOfficer;
    if (yearStart) criteria.year_start = yearStart;
    if (yearEnd) criteria.year_end = yearEnd;
    if (yearStart && yearEnd && yearEnd < yearStart) {
      throw new Error("The ending year must be the same as or later than the starting year.");
    }
    const hasSearch = Object.keys(criteria).some(key => !["year_start", "year_end"].includes(key));
    if (!hasSearch) {
      throw new Error("Enter a topic or program, or add an investigator, program officer, or selected opportunity.");
    }
    const offset = Math.max(0, Math.min(1_000, Number.parseInt(state.offset, 10) || 0));
    const sources = selectedLookup ? [selectedLookup.source] : sourcesForAgency(state.agency);
    const resultLimit = sources.includes("DOE")
      ? Math.max(1, Math.min(DOE_PAGE_LIMIT, Number(limit) || DOE_PAGE_LIMIT))
      : Math.max(1, Math.min(25, Number(limit) || 25));
    return {
      sources,
      criteria,
      limit: resultLimit,
      offset,
    };
  }

  function validatePayload(payload) {
    return Boolean(
      payload
      && payload.schema_version === 1
      && Array.isArray(payload.results)
      && Array.isArray(payload.sources)
      && payload.results.length <= 75
      && payload.results.every(item => item && SOURCE_NAMES.includes(item.source)),
    );
  }

  function institutionSummary(results, institution) {
    const requested = clean(institution, 300);
    if (!requested) return null;
    const people = new Map();
    for (const award of results) {
      for (const person of Array.isArray(award.principal_investigators) ? award.principal_investigators : []) {
        const name = clean(person?.name, 300);
        if (!name) continue;
        const displayName = displayInvestigatorName(name);
        const key = displayName.normalize("NFKC").toLocaleLowerCase("en-US");
        const existing = people.get(key);
        if (existing) existing.projects += 1;
        else people.set(key, { name: displayName, query: name, projects: 1 });
      }
    }
    return {
      institution: results.find(item => clean(item?.institution?.normalized_name))?.institution?.normalized_name || requested,
      projects: results.length,
      investigators: [...people.values()]
        .sort((a, b) => b.projects - a.projects || a.name.localeCompare(b.name)),
    };
  }

  function canPageForward(payload) {
    const limit = Number(payload?.pagination?.limit || 0);
    if (!Number.isFinite(limit) || limit <= 0) return false;
    return (payload?.sources || []).some(source => (
      source.status === "ok"
      && source.has_more === true
    ));
  }

  globalThis.FUNDING_AWARD_PRODUCT = Object.freeze({
    awardYear,
    awardYearRange,
    boundedErrorCode,
    buildRequest,
    canPageForward,
    displayInvestigatorName,
    institutionSummary,
    paginationLabel,
    presentFiniteNumber,
    serviceIssueText,
    sourceIssueText,
    sourcesForAgency,
    standaloneCriterion,
    validatePayload,
  });
})();
