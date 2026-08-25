(() => {
  "use strict";

  const SOURCE_NAMES = ["NSF", "NIH", "DOE"];
  const DOE_PAGE_LIMIT = 10;

  function clean(value, maximum = 500) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.slice(0, maximum);
  }

  function year(value) {
    const number = Number(value);
    return Number.isInteger(number) && number >= 1989 && number <= 2100 ? number : null;
  }

  function sourcesForAgency(agency) {
    const value = clean(agency, 10).toUpperCase();
    return SOURCE_NAMES.includes(value) ? [value] : [...SOURCE_NAMES];
  }

  function standaloneCriterion({ mode, agency, query }) {
    const value = clean(query);
    if (!value) return {};
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
        people.set(name, (people.get(name) || 0) + 1);
      }
    }
    return {
      institution: results.find(item => clean(item?.institution?.normalized_name))?.institution?.normalized_name || requested,
      projects: results.length,
      investigators: [...people.entries()]
        .map(([name, projects]) => ({ name, projects }))
        .sort((a, b) => b.projects - a.projects || a.name.localeCompare(b.name)),
    };
  }

  function canPageForward(payload) {
    return (payload?.sources || []).some(source => (
      source.status === "ok"
      && source.has_more === true
    ));
  }

  globalThis.FUNDING_AWARD_PRODUCT = Object.freeze({
    buildRequest,
    canPageForward,
    institutionSummary,
    sourcesForAgency,
    standaloneCriterion,
    validatePayload,
  });
})();
