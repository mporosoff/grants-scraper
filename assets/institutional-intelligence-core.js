(() => {
  "use strict";

  const SOURCE_NAMES = ["NSF", "NIH", "DOE"];
  const MANAGED_PARAMS = [
    "ii", "ii_institution", "ii_ror", "ii_agency", "ii_program",
    "ii_topic", "ii_pi", "ii_program_officer", "ii_year_start", "ii_year_end", "ii_offset",
  ];
  const LEGACY_SEARCH_PARAMS = [
    "opportunity", "q", "mode", "agency", "institution", "year_start", "year_end", "pi", "program_officer", "offset",
  ];
  const DOE_PROGRAM_OFFICES = new Map([
    ["bes", "SC-32"],
    ["doe bes", "SC-32"],
    ["basic energy sciences", "SC-32"],
    ["office of basic energy sciences", "SC-32"],
    ["sc 32", "SC-32"],
  ]);

  function clean(value, maximum = 500) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function identityKey(value) {
    return clean(value)
      .normalize("NFKD")
      .toLocaleLowerCase("en-US")
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function validYear(value) {
    const year = Number(value);
    return Number.isInteger(year) && year >= 1989 && year <= 2100 ? year : null;
  }

  function sourcesForAgency(agency) {
    const normalized = clean(agency, 10).toUpperCase();
    return SOURCE_NAMES.includes(normalized) ? [normalized] : [...SOURCE_NAMES];
  }

  function programCriterion(agency, program) {
    const source = clean(agency, 10).toUpperCase();
    const value = clean(program, 160);
    if (!value) return {};
    if (!SOURCE_NAMES.includes(source)) {
      throw new Error("Choose NSF, NIH, or DOE before filtering by a program.");
    }
    if (source === "DOE") {
      const office = DOE_PROGRAM_OFFICES.get(identityKey(value));
      if (office) return { program_office: office };
      if (/^SC-\d+(?:\.\d+)?$/i.test(value)) return { program_office: value.toUpperCase() };
    }
    const product = globalThis.FUNDING_AWARD_PRODUCT;
    if (!product?.standaloneCriterion) {
      throw new Error("The shared funded-award request builder did not load.");
    }
    return product.standaloneCriterion({ mode: "program", agency: source, query: value });
  }

  function buildAwardRequest(state, limit = 10) {
    const institution = clean(state?.institution, 300);
    const agency = clean(state?.agency, 10).toUpperCase();
    const sources = sourcesForAgency(agency);
    const criteria = {
      ...programCriterion(agency, state?.program),
    };
    if (institution) criteria.institution = institution;
    const rorId = clean(state?.ror_id, 100);
    if (institution && /^https:\/\/ror\.org\/0[a-z0-9]{8}$/i.test(rorId)) criteria.institution_id = rorId;
    const topic = clean(state?.topic, 500);
    const pi = clean(state?.pi, 160);
    const programOfficer = clean(state?.program_officer, 160);
    const yearStart = validYear(state?.year_start);
    const yearEnd = validYear(state?.year_end);
    if (topic) criteria.topic = topic;
    if (pi) criteria.pi = pi;
    if (programOfficer) criteria.program_officer = programOfficer;
    if (yearStart) criteria.year_start = yearStart;
    if (yearEnd) criteria.year_end = yearEnd;
    if (yearStart && yearEnd && yearEnd < yearStart) {
      throw new Error("The ending year must be the same as or later than the starting year.");
    }
    if (!institution && !topic && !pi && !programOfficer && !clean(state?.program, 160)) {
      throw new Error("Enter an institution, topic, program, investigator, or program officer before searching.");
    }
    return {
      sources,
      criteria,
      limit: sources.includes("DOE") ? Math.min(10, Math.max(1, Number(limit) || 10)) : Math.min(25, Math.max(1, Number(limit) || 10)),
      offset: Math.max(0, Math.min(1_000, Number(state?.offset) || 0)),
    };
  }

  function chooseInstitution(query, institutions) {
    const queryKey = identityKey(query);
    const candidates = (Array.isArray(institutions) ? institutions : [])
      .filter(candidate => candidate && clean(candidate.canonical_name, 300))
      .filter(candidate => {
        const names = [candidate.canonical_name, ...(candidate.aliases || []), ...(candidate.acronyms || [])];
        return candidate.match?.exact === true || names.some(name => identityKey(name) === queryKey);
      })
      .sort((left, right) => (
        Number(right.match?.score || 0) - Number(left.match?.score || 0)
        || clean(left.canonical_name).localeCompare(clean(right.canonical_name), "en-US")
        || clean(left.id).localeCompare(clean(right.id))
      ));
    return candidates[0] || null;
  }

  function programDescriptors(award) {
    const source = clean(award?.source, 10).toUpperCase();
    const output = [];
    const add = (label, query) => {
      const cleanLabel = clean(label, 300);
      const cleanQuery = clean(query, 160);
      if (!cleanLabel || !cleanQuery) return;
      const key = `${source}:${identityKey(cleanQuery)}`;
      if (!output.some(item => item.key === key)) output.push({ key, source, label: cleanLabel, query: cleanQuery });
    };
    if (source === "DOE") {
      if (/Basic Energy Sciences/i.test(clean(award?.subagency))) {
        add("Office of Basic Energy Sciences", "BES");
      }
      add(award?.program_name, award?.program_name);
    } else if (source === "NIH") {
      add(award?.activity_code, award?.activity_code);
    } else if (source === "NSF") {
      add(award?.program_name, award?.program_name || award?.program_codes?.[0]);
    }
    if (!output.length) {
      const code = (Array.isArray(award?.program_codes) ? award.program_codes : []).find(Boolean);
      add(code, code);
    }
    return output;
  }

  function aggregateAwards(results) {
    const awards = [];
    const seenAwards = new Set();
    const investigators = new Map();
    const programs = new Map();
    const years = new Set();
    const agencies = new Set();
    for (const award of Array.isArray(results) ? results : []) {
      const awardKey = `${clean(award?.source, 10)}:${clean(award?.award_id, 100)}`;
      if (!clean(award?.award_id, 100) || seenAwards.has(awardKey)) continue;
      seenAwards.add(awardKey);
      awards.push(award);
      agencies.add(clean(award?.source, 10));
      const year = validYear(award?.award_year);
      if (year) years.add(year);
      const awardPeople = new Set();
      for (const person of Array.isArray(award?.principal_investigators) ? award.principal_investigators : []) {
        const name = clean(person?.name, 300);
        if (!name || awardPeople.has(identityKey(name))) continue;
        awardPeople.add(identityKey(name));
        const entry = investigators.get(identityKey(name)) || { name, projects: 0 };
        entry.projects += 1;
        investigators.set(identityKey(name), entry);
      }
      for (const descriptor of programDescriptors(award)) {
        const entry = programs.get(descriptor.key) || { ...descriptor, projects: 0 };
        entry.projects += 1;
        programs.set(descriptor.key, entry);
      }
    }
    const orderedYears = [...years].sort((a, b) => a - b);
    return {
      awards,
      project_count: awards.length,
      investigator_count: investigators.size,
      program_count: programs.size,
      agency_count: agencies.size,
      year_start: orderedYears[0] || null,
      year_end: orderedYears.at(-1) || null,
      investigators: [...investigators.values()].sort((left, right) => right.projects - left.projects || left.name.localeCompare(right.name)),
      programs: [...programs.values()].sort((left, right) => right.projects - left.projects || left.label.localeCompare(right.label)),
    };
  }

  function stateFromSearch(search) {
    const params = new URLSearchParams(search || "");
    return {
      open: true,
      institution: clean(params.get("ii_institution") || params.get("institution"), 300),
      ror_id: clean(params.get("ii_ror"), 100),
      agency: SOURCE_NAMES.includes(clean(params.get("ii_agency") || params.get("agency"), 10).toUpperCase())
        ? clean(params.get("ii_agency") || params.get("agency"), 10).toUpperCase()
        : "all",
      program: clean(params.get("ii_program") || (params.get("mode") === "program" ? params.get("q") : ""), 160),
      topic: clean(params.get("ii_topic") || (!params.get("mode") || params.get("mode") === "topic" ? params.get("q") : ""), 500),
      pi: clean(params.get("ii_pi") || params.get("pi") || (params.get("mode") === "pi" ? params.get("q") : ""), 160),
      program_officer: clean(params.get("ii_program_officer") || params.get("program_officer") || (params.get("mode") === "program_officer" ? params.get("q") : ""), 160),
      year_start: /^\d{4}$/.test(params.get("ii_year_start") || params.get("year_start") || "") ? (params.get("ii_year_start") || params.get("year_start")) : "",
      year_end: /^\d{4}$/.test(params.get("ii_year_end") || params.get("year_end") || "") ? (params.get("ii_year_end") || params.get("year_end")) : "",
      offset: Math.max(0, Math.min(1_000, Number(params.get("ii_offset") || params.get("offset")) || 0)),
    };
  }

  function urlForState(href, state) {
    const url = new URL(href, "https://funding-finder.invalid/");
    MANAGED_PARAMS.forEach(key => url.searchParams.delete(key));
    LEGACY_SEARCH_PARAMS.forEach(key => url.searchParams.delete(key));
    if (state?.open || clean(state?.institution)) url.searchParams.set("ii", "1");
    if (clean(state?.institution)) url.searchParams.set("ii_institution", clean(state.institution, 300));
    if (clean(state?.ror_id)) url.searchParams.set("ii_ror", clean(state.ror_id, 100));
    if (SOURCE_NAMES.includes(clean(state?.agency, 10).toUpperCase())) url.searchParams.set("ii_agency", clean(state.agency, 10).toUpperCase());
    if (clean(state?.program)) url.searchParams.set("ii_program", clean(state.program, 160));
    if (clean(state?.topic)) url.searchParams.set("ii_topic", clean(state.topic, 500));
    if (clean(state?.pi)) url.searchParams.set("ii_pi", clean(state.pi, 160));
    if (clean(state?.program_officer)) url.searchParams.set("ii_program_officer", clean(state.program_officer, 160));
    if (validYear(state?.year_start)) url.searchParams.set("ii_year_start", String(state.year_start));
    if (validYear(state?.year_end)) url.searchParams.set("ii_year_end", String(state.year_end));
    if (Number(state?.offset) > 0) url.searchParams.set("ii_offset", String(Math.max(0, Math.min(1_000, Number(state.offset)))));
    return url;
  }

  function sanitizeQuestionPlan(plan, currentState) {
    const agency = clean(plan?.agency, 10).toUpperCase();
    return {
      ...currentState,
      agency: SOURCE_NAMES.includes(agency) ? agency : "all",
      program: clean(plan?.program, 160),
      topic: clean(plan?.topic, 500),
      pi: clean(plan?.pi, 160),
      program_officer: clean(plan?.program_officer, 160),
      year_start: validYear(plan?.year_start) || "",
      year_end: validYear(plan?.year_end) || "",
    };
  }

  function explicitInvestigator(question) {
    const value = clean(question, 1_000);
    if (!value) return "";
    const name = "([\\p{Lu}][\\p{L}'’.-]*(?:\\s+[\\p{Lu}][\\p{L}'’.-]*){1,3})";
    const patterns = [
      new RegExp(`\\b(?:investigator|researcher|professor|faculty member|PI)\\s+(?:named\\s+)?${name}(?=\\s*(?:[?.,;:]|$))`, "u"),
      new RegExp(`\\b(?:has|did)\\s+${name}\\s+(?:been\\s+funded|receive|received|win|won|lead|led|secure|secured|get|got|have)\\b`, "u"),
    ];
    for (const pattern of patterns) {
      const match = value.match(pattern);
      if (match?.[1]) {
        const candidate = clean(match[1], 160).replace(/[.,;:]+$/u, "");
        if (/\b(?:DOE|NIH|NSF|BES)\b/.test(candidate)) continue;
        return candidate;
      }
    }
    return "";
  }

  globalThis.FUNDING_INSTITUTIONAL_INTELLIGENCE = Object.freeze({
    MANAGED_PARAMS,
    aggregateAwards,
    buildAwardRequest,
    chooseInstitution,
    explicitInvestigator,
    identityKey,
    programCriterion,
    sanitizeQuestionPlan,
    sourcesForAgency,
    stateFromSearch,
    urlForState,
  });
})();
