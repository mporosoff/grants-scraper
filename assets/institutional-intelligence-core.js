(() => {
  "use strict";

  const SOURCE_NAMES = ["NSF", "NIH", "DOE"];
  const MANAGED_PARAMS = [
    "ii", "ii_institution", "ii_ror", "ii_agency", "ii_program",
    "ii_topic", "ii_pi", "ii_pi_identity", "ii_program_officer", "ii_year_start", "ii_year_end", "ii_offset",
    "ii_snapshot", "ii_page", "ii_page_size", "ii_facet", "ii_facet_key",
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
  const KNOWN_PROGRAM_IDENTITIES = new Map([
    ["career", "NSF-CAREER"],
    ["faculty early career development", "NSF-CAREER"],
    ["faculty early career development program", "NSF-CAREER"],
  ]);
  const ANSWER_INTENTS = new Set(["count", "investigators", "programs", "years", "awards", "narrative"]);
  const QUESTION_EVIDENCE_LIMIT = 24;
  const QUESTION_ABSTRACT_LIMIT = 800;
  const QUESTION_PAYLOAD_LIMIT = 18_000;
  const SNAPSHOT_FACET_KEY_MAX_LENGTH = 1_024;

  function clean(value, maximum = 500) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function snapshotFacetKey(value) {
    const key = String(value || "").replace(/\s+/g, " ").trim();
    return key.length <= SNAPSHOT_FACET_KEY_MAX_LENGTH ? key : "";
  }

  function identityKey(value) {
    return clean(value)
      .normalize("NFKD")
      .toLocaleLowerCase("en-US")
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function isProgramIdentity(candidate, program) {
    const candidateKey = identityKey(candidate);
    const programKey = identityKey(program);
    if (!candidateKey || !programKey) return false;
    if (candidateKey === programKey) return true;
    const candidateBase = candidateKey.replace(/\s+(?:program|programme|initiative|award|awards|grant|grants|fellowship|fellowships|mechanism|scheme)$/u, "");
    if (candidateBase === programKey) return true;
    const candidateIdentity = KNOWN_PROGRAM_IDENTITIES.get(candidateKey) || KNOWN_PROGRAM_IDENTITIES.get(candidateBase);
    const programIdentity = KNOWN_PROGRAM_IDENTITIES.get(programKey);
    if (candidateIdentity && candidateIdentity === programIdentity) return true;
    const candidateOffice = DOE_PROGRAM_OFFICES.get(candidateKey);
    const programOffice = DOE_PROGRAM_OFFICES.get(programKey);
    if (candidateOffice && programOffice && candidateOffice === programOffice) return true;
    const initialism = value => identityKey(value).split(" ").filter(Boolean).map(word => word[0]).join("");
    const programCompact = programKey.replace(/\s/g, "");
    return programCompact.length >= 3 && initialism(candidate) === programCompact;
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
    if (yearStart && yearEnd && yearEnd - yearStart + 1 > 50) {
      throw new Error("Choose a year range of 50 years or fewer.");
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
    if (!candidates.length) return null;
    const canonical = candidates.filter(candidate => candidate.match?.type === "canonical");
    if (canonical.length === 1) return canonical[0];
    const aliases = candidates.filter(candidate => candidate.match?.type === "alias");
    const acronyms = candidates.filter(candidate => candidate.match?.type === "acronym");
    if (aliases.length === 1 && acronyms.length === 0) return aliases[0];
    const compactQuery = queryKey.replace(/\s/g, "");
    if (acronyms.length === 1 && aliases.length === 0 && compactQuery.length > 6) return acronyms[0];
    return null;
  }

  function requiresExplicitInstitutionSelection(value) {
    const text = clean(value, 300);
    const words = text.split(/[\s,]+/u).filter(Boolean);
    const compact = identityKey(text).replace(/\s/g, "");
    return Boolean(compact && compact.length <= 12 && (
      words.length === 1
      || words.every(word => personToken(word).length === 1)
    ));
  }

  function personToken(value) {
    return clean(value, 100)
      .normalize("NFKD")
      .toLocaleLowerCase("en-US")
      .replace(/[’]/g, "'")
      .replace(/[‐‑‒–—]/g, "-")
      .replace(/\./g, "")
      .replace(/[^\p{L}\p{N}'-]+/gu, "")
      .trim();
  }

  function normalizedInvestigatorName(value) {
    let published = clean(value, 300);
    if (!published) return null;
    published = published
      .replace(/^(?:(?:dr|doctor|prof|professor|mr|mrs|ms|miss|mx)\.?\s+)+/iu, "")
      .replace(/(?:,?\s+|,)(?:jr|sr|ii|iii|iv|ph\.?d\.?|m\.?d\.?|dds|dvm|esq)\.?$/iu, "")
      .trim();
    const commaParts = published.split(",").map(part => clean(part, 160)).filter(Boolean);
    let tokens;
    if (commaParts.length >= 2) {
      const family = commaParts[0].split(/\s+/).filter(Boolean);
      const given = commaParts[1].split(/\s+/).filter(Boolean);
      tokens = [...given, ...family];
    } else {
      tokens = published.split(/\s+/).filter(Boolean);
    }
    const keyed = tokens.map(personToken).filter(Boolean);
    if (keyed.length < 2) return null;
    const first = keyed[0];
    const family = keyed.at(-1);
    const middleParts = keyed.slice(1, -1);
    const middle = middleParts.join(" ");
    return {
      published: clean(value, 300),
      display: tokens.join(" "),
      first_display: tokens[0],
      middle_display: tokens.slice(1, -1).join(" "),
      family_display: tokens.at(-1),
      first,
      middle,
      middle_initial: middleParts[0]?.[0] || "",
      middle_is_initial: Boolean(middleParts.length) && middleParts.every(part => part.length === 1),
      family,
      base_key: `${first}|${family}`,
      complete_key: `${first}|${middle}|${family}`,
    };
  }

  function contactIdentifier(person, source) {
    const value = clean(person?.source_person_id ?? person?.profile_id, 120);
    return value ? `${clean(source, 10).toUpperCase()}:${value}` : "";
  }

  function institutionIdentity(award) {
    return clean(award?.institution?.identifiers?.ror, 100)
      || identityKey(award?.institution?.normalized_name || award?.institution?.name);
  }

  function middleCompatible(left, right) {
    if (!left.middle || !right.middle) return true;
    if (left.middle === right.middle) return true;
    if (left.middle_initial !== right.middle_initial) return false;
    return left.middle_is_initial !== right.middle_is_initial;
  }

  function contactEvidence(award, person) {
    const parsed = normalizedInvestigatorName(person?.name);
    if (!parsed) return null;
    const source = clean(award?.source, 10).toUpperCase();
    return {
      ...parsed,
      source,
      award_id: clean(award?.award_id, 100),
      award_key: `${source}:${clean(award?.award_id, 100)}`,
      institution_key: institutionIdentity(award),
      identifier: contactIdentifier(person, source),
      email: clean(person?.email, 320).toLocaleLowerCase("en-US"),
      provenance: person?.source_provenance || {},
    };
  }

  function identifiersConflict(left, right) {
    if (!left.identifier || !right.identifier) return false;
    const [leftSource] = left.identifier.split(":", 1);
    const [rightSource] = right.identifier.split(":", 1);
    return leftSource === rightSource && left.identifier !== right.identifier;
  }

  function contactsCanGroup(left, right) {
    if (!left || !right) return false;
    if (left.identifier && left.identifier === right.identifier) return true;
    if (identifiersConflict(left, right)) return false;
    if (left.email && right.email) return left.email === right.email;
    if (left.institution_key !== right.institution_key || !left.institution_key) return false;
    if (left.first !== right.first || left.family !== right.family) return false;
    if (left.complete_key === right.complete_key) return true;
    return middleCompatible(left, right) && (!left.middle || !right.middle || left.middle_is_initial !== right.middle_is_initial);
  }

  function nameCompleteness(entry) {
    const middleScore = entry.middle ? (entry.middle_is_initial ? 20 : 40) + entry.middle.length : 0;
    const decorationPenalty = /^(?:dr|doctor|prof|professor|mr|mrs|ms|mx)\b/iu.test(entry.published) ? 5 : 0;
    return middleScore + entry.display.length - decorationPenalty;
  }

  function canonicalInvestigatorLabel(entry) {
    const middle = entry.middle_display
      ? entry.middle_display.split(/\s+/u).map(token => personToken(token).length === 1
        ? `${token.replace(/\.+$/u, "")}.`
        : token).join(" ")
      : "";
    return [entry.first_display, middle, entry.family_display].filter(Boolean).join(" ");
  }

  function groupInvestigators(awards) {
    const entries = [];
    for (const award of Array.isArray(awards) ? awards : []) {
      const seen = new Set();
      for (const person of Array.isArray(award?.principal_investigators) ? award.principal_investigators : []) {
        const entry = contactEvidence(award, person);
        if (!entry) continue;
        const key = `${entry.award_key}:${entry.identifier || entry.email || entry.complete_key}`;
        if (seen.has(key)) continue;
        seen.add(key);
        entries.push(entry);
      }
    }
    const groups = [];
    for (const entry of entries) {
      const group = groups.find(candidate => candidate.members.every(member => contactsCanGroup(member, entry)));
      if (group) group.members.push(entry);
      else groups.push({ members: [entry] });
    }
    return groups.map((group, index) => {
      const labelEntry = [...group.members].sort((left, right) => (
        nameCompleteness(right) - nameCompleteness(left)
        || left.published.localeCompare(right.published, "en-US")
      ))[0];
      const variants = [];
      const seenVariants = new Set();
      const sourceVariants = {};
      const awardsInGroup = new Set();
      for (const member of group.members) {
        awardsInGroup.add(member.award_key);
        const variantKey = `${member.source}:${identityKey(member.published)}`;
        if (!seenVariants.has(variantKey)) {
          seenVariants.add(variantKey);
          variants.push({
            name: member.published,
            source: member.source,
            award_id: member.award_id,
            identifier: member.identifier || null,
            email: member.email || null,
          });
        }
        sourceVariants[member.source] ||= [];
        if (!sourceVariants[member.source].some(value => identityKey(value) === identityKey(member.published))) {
          sourceVariants[member.source].push(member.published);
        }
      }
      return {
        identity_key: `investigator:${labelEntry.base_key}:${labelEntry.middle_initial || "none"}:${index + 1}`,
        name: canonicalInvestigatorLabel(labelEntry),
        normalized: {
          first: labelEntry.first,
          middle: labelEntry.middle,
          middle_initial: labelEntry.middle_initial,
          family: labelEntry.family,
        },
        projects: awardsInGroup.size,
        variants,
        source_variants: sourceVariants,
        members: group.members,
      };
    }).sort((left, right) => (
      left.normalized.family.localeCompare(right.normalized.family, "en-US")
      || left.normalized.first.localeCompare(right.normalized.first, "en-US")
      || left.normalized.middle.localeCompare(right.normalized.middle, "en-US")
      || left.name.localeCompare(right.name, "en-US")
    ));
  }

  function investigatorQueryVariants(group, source, maximum = 4) {
    const values = [...(group?.source_variants?.[source] || [])];
    const published = normalizedInvestigatorName(group?.name) || {};
    const name = group?.normalized || published;
    const first = published.first_display || name.first;
    const middle = published.middle_display || name.middle;
    const family = published.family_display || name.family;
    if (name.first && name.family) {
      if (name.middle) values.push(`${first} ${middle} ${family}`);
      if (name.middle_initial) values.push(`${first} ${name.middle_initial.toUpperCase()} ${family}`);
      values.push(`${first} ${family}`);
      if (name.middle) values.push(`${family}, ${first} ${middle}`);
    }
    const seen = new Set();
    return values.map(value => clean(value, 160)).filter(value => {
      const key = identityKey(value);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, Math.max(1, Math.min(4, Number(maximum) || 4)));
  }

  function awardMatchesInvestigator(award, group) {
    const members = Array.isArray(group?.members) ? group.members : [];
    const source = clean(award?.source, 10).toUpperCase();
    return (Array.isArray(award?.principal_investigators) ? award.principal_investigators : []).some(person => {
      const returned = contactEvidence(award, person);
      if (!returned) return false;
      if (members.length) return members.every(member => contactsCanGroup(member, returned));
      const expected = normalizedInvestigatorName(group?.name);
      return expected && contactsCanGroup({ ...expected, source, award_id: "", award_key: "", institution_key: institutionIdentity(award), identifier: "", email: "" }, returned);
    });
  }

  function programDescriptors(award) {
    const source = clean(award?.source, 10).toUpperCase();
    const parent = clean(award?.subagency, 300);
    const sourceCodes = [...new Set((Array.isArray(award?.program_codes) ? award.program_codes : []).map(value => clean(value, 100)).filter(Boolean))];
    const code = sourceCodes[0] || "";
    const sourceLeaf = source === "NIH"
      ? clean(award?.activity_code || award?.program_name || code, 300)
      : clean(award?.program_name || code, 300);
    const leaf = sourceLeaf || parent;
    if (!source || !leaf) return [];
    const distinctChild = Boolean(parent && identityKey(parent) !== identityKey(leaf));
    const doeOfficeCode = sourceCodes.find(value => /^SC-\d+(?:\.\d+)?$/i.test(value));
    const query = source === "DOE" && !distinctChild
      ? /Basic Energy Sciences/i.test(parent) ? "BES" : doeOfficeCode || leaf
      : leaf;
    if (!query) return [];
    const label = `${source} · ${distinctChild ? `${parent} › ${leaf}` : leaf}`;
    return [{
      key: `${source}:${identityKey(parent || leaf)}:${identityKey(leaf)}`,
      source,
      parent_label: parent || null,
      leaf_label: leaf,
      leaf_role: distinctChild ? "child_program" : "most_specific_available_program",
      query,
      query_role: distinctChild ? "leaf_program" : "fallback_leaf",
      source_codes: sourceCodes,
      label,
    }];
  }

  function aggregateAwards(results) {
    const awards = [];
    const seenAwards = new Set();
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
      for (const descriptor of programDescriptors(award)) {
        const entry = programs.get(descriptor.key) || { ...descriptor, projects: 0 };
        entry.projects += 1;
        programs.set(descriptor.key, entry);
      }
    }
    const orderedYears = [...years].sort((a, b) => a - b);
    const investigators = groupInvestigators(awards);
    return {
      awards,
      project_count: awards.length,
      investigator_count: investigators.length,
      program_count: programs.size,
      agency_count: agencies.size,
      year_start: orderedYears[0] || null,
      year_end: orderedYears.at(-1) || null,
      investigators,
      programs: [...programs.values()].sort((left, right) => left.label.localeCompare(right.label, "en-US")),
    };
  }

  function sanitizeAnswerIntent(plan, question = "") {
    const requested = clean(plan?.answer_intent, 40).toLocaleLowerCase("en-US");
    if (ANSWER_INTENTS.has(requested)) return requested;
    const text = clean(question, 1_000).toLocaleLowerCase("en-US");
    if (/\bwho\b|investigator|researcher|faculty|\bpi\b/.test(text)) return "investigators";
    if (/program|mechanism|office/.test(text)) return "programs";
    if (/\bwhen\b|\byear/.test(text)) return "years";
    if (/how many|count|number of/.test(text)) return "count";
    if (/which (?:award|project)|list|show/.test(text)) return "awards";
    return plan?.narrative_needed === true ? "narrative" : "awards";
  }

  function evidenceId(award) {
    return `${clean(award?.source, 10).toUpperCase()}:${clean(award?.award_id, 100)}`;
  }

  function questionEvidencePack(results, { recordLimit = QUESTION_EVIDENCE_LIMIT } = {}) {
    const unique = [];
    const uniqueIds = new Set();
    for (const award of Array.isArray(results) ? results : []) {
      const id = evidenceId(award);
      if (!/^(?:NSF|NIH|DOE):.+/.test(id) || uniqueIds.has(id)) continue;
      uniqueIds.add(id);
      unique.push(award);
    }
    const bySource = new Map(SOURCE_NAMES.map(source => [source, []]));
    for (const award of unique) bySource.get(clean(award?.source, 10).toUpperCase())?.push(award);
    const balanced = [];
    for (let index = 0; balanced.length < unique.length; index += 1) {
      let added = false;
      for (const source of SOURCE_NAMES) {
        const award = bySource.get(source)?.[index];
        if (!award) continue;
        balanced.push(award);
        added = true;
      }
      if (!added) break;
    }
    const awards = [];
    let totalBytes = 2;
    let truncated = false;
    const limit = Math.min(QUESTION_EVIDENCE_LIMIT, Math.max(1, Number(recordLimit) || QUESTION_EVIDENCE_LIMIT));
    for (const award of balanced) {
      const id = evidenceId(award);
      const record = {
        evidence_id: id,
        source: clean(award?.source, 10).toUpperCase(),
        award_id: clean(award?.award_id, 100),
        title: clean(award?.title, 500),
        program: clean(award?.program_name || award?.activity_code || award?.program_codes?.[0], 200),
        year: validYear(award?.award_year),
        investigators: (Array.isArray(award?.principal_investigators) ? award.principal_investigators : [])
          .map(person => clean(person?.name, 160)).filter(Boolean).slice(0, 8),
        abstract_excerpt: clean(award?.abstract, QUESTION_ABSTRACT_LIMIT),
      };
      const bytes = JSON.stringify(record).length + (awards.length ? 1 : 0);
      if (awards.length >= limit) {
        truncated = true;
        break;
      }
      if (totalBytes + bytes > QUESTION_PAYLOAD_LIMIT) {
        truncated = true;
        continue;
      }
      awards.push(record);
      totalBytes += bytes;
    }
    if (awards.length < unique.length) truncated = true;
    return {
      awards,
      truncated,
      limits: {
        records: QUESTION_EVIDENCE_LIMIT,
        abstract_characters_per_record: QUESTION_ABSTRACT_LIMIT,
        serialized_characters: QUESTION_PAYLOAD_LIMIT,
      },
      serialized_characters: JSON.stringify(awards).length,
    };
  }

  function deterministicInstitutionAnswer({ question = "", intent = "", aggregate, sources = [] } = {}) {
    const safeAggregate = aggregate || aggregateAwards([]);
    const resolvedIntent = sanitizeAnswerIntent({ answer_intent: intent }, question);
    const evidenceIds = Array.isArray(safeAggregate.ordered_refs)
      ? safeAggregate.ordered_refs.map(item => clean(item?.evidence_id, 120)).filter(Boolean)
      : (safeAggregate.awards || []).map(evidenceId);
    let answer;
    if (resolvedIntent === "investigators") {
      const people = safeAggregate.investigators.map(person => `${person.name} (${person.projects} award${person.projects === 1 ? "" : "s"} in the result snapshot)`);
      answer = people.length ? `Investigators in the result snapshot: ${people.join("; ")}.` : "No investigator names appear in the matching result snapshot.";
    } else if (resolvedIntent === "programs") {
      const programs = safeAggregate.programs.map(program => `${program.label} (${program.projects})`);
      answer = programs.length ? `Programs in the result snapshot: ${programs.join("; ")}.` : "No program labels appear in the matching result snapshot.";
    } else if (resolvedIntent === "years") {
      answer = safeAggregate.year_start
        ? `The matching result snapshot spans ${safeAggregate.year_start}${safeAggregate.year_end !== safeAggregate.year_start ? ` through ${safeAggregate.year_end}` : ""}.`
        : "The matching result snapshot does not contain a usable award year.";
    } else if (resolvedIntent === "count") {
      answer = `${safeAggregate.project_count} normalized matching award${safeAggregate.project_count === 1 ? " is" : "s are"} in the result snapshot.`;
    } else if (resolvedIntent === "awards") {
      const titles = (Array.isArray(safeAggregate.ordered_refs) ? safeAggregate.ordered_refs : safeAggregate.awards || [])
        .slice(0, 8)
        .map(award => clean(award?.title, 180) || clean(award?.evidence_id, 120) || `${award.source} ${award.award_id}`);
      answer = titles.length ? `${safeAggregate.project_count} matching award${safeAggregate.project_count === 1 ? " is" : "s are"} in the result snapshot: ${titles.join("; ")}.` : "No matching awards are in the result snapshot.";
    } else {
      answer = `${safeAggregate.project_count} normalized matching award${safeAggregate.project_count === 1 ? " is" : "s are"} in the result snapshot for evidence-grounded interpretation.`;
    }
    const searched = sources.map(source => clean(source?.source, 10)).filter(Boolean);
    const usableStatuses = new Set(["ok", "complete", "partial", "safety_bounded"]);
    const unavailable = sources.filter(source => !usableStatuses.has(source?.status)).map(source => clean(source?.source, 10)).filter(Boolean);
    const hasMore = sources.filter(source => source?.has_more === true || ["partial", "safety_bounded"].includes(source?.status)).map(source => clean(source?.source, 10));
    return { answer, intent: resolvedIntent, evidence_ids: evidenceIds, searched, unavailable, has_more: hasMore };
  }

  function validateNarrativeAnswer(value, evidence) {
    if (!value || typeof value !== "object" || Array.isArray(value) || !Array.isArray(value.claims)) return null;
    const known = new Set((Array.isArray(evidence) ? evidence : []).map(item => clean(item?.evidence_id, 120)).filter(Boolean));
    const claims = [];
    for (const claim of value.claims.slice(0, 6)) {
      const text = clean(claim?.text, 700);
      const ids = [...new Set((Array.isArray(claim?.evidence_ids) ? claim.evidence_ids : []).map(id => clean(id, 120)).filter(Boolean))].slice(0, 8);
      if (!text || !ids.length || ids.some(id => !known.has(id))) return null;
      claims.push({ text, evidence_ids: ids });
    }
    return claims.length ? { claims } : null;
  }

  function questionProviderPayload({ question, institution, filters, intent, evidencePack }) {
    return {
      question: clean(question, 1_000),
      institution: {
        id: clean(institution?.id, 100),
        canonical_name: clean(institution?.canonical_name, 300),
      },
      visible_filters: {
        agency: clean(filters?.agency, 10),
        program: clean(filters?.program, 160),
        topic: clean(filters?.topic, 500),
        pi: clean(filters?.pi, 160),
        program_officer: clean(filters?.program_officer, 160),
        year_start: validYear(filters?.year_start),
        year_end: validYear(filters?.year_end),
      },
      answer_intent: sanitizeAnswerIntent({ answer_intent: intent }, question),
      public_award_evidence: Array.isArray(evidencePack?.awards) ? evidencePack.awards : [],
      evidence_truncated: evidencePack?.truncated === true,
    };
  }

  function stateFromSearch(search) {
    const params = new URLSearchParams(search || "");
    const state = {
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
      snapshot_id: clean(params.get("ii_snapshot"), 100),
      page: Math.max(1, Number.parseInt(params.get("ii_page") || "1", 10) || 1),
      page_size: [10, 25, 50].includes(Number(params.get("ii_page_size"))) ? Number(params.get("ii_page_size")) : 10,
      facet_type: ["all", "investigator", "program"].includes(params.get("ii_facet")) ? params.get("ii_facet") : "all",
      facet_key: snapshotFacetKey(params.get("ii_facet_key")),
    };
    if (state.pi && params.get("ii_pi_identity") === "1") state.pi_identity = true;
    return state;
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
    if (clean(state?.pi) && state?.pi_identity === true) url.searchParams.set("ii_pi_identity", "1");
    if (clean(state?.program_officer)) url.searchParams.set("ii_program_officer", clean(state.program_officer, 160));
    if (validYear(state?.year_start)) url.searchParams.set("ii_year_start", String(state.year_start));
    if (validYear(state?.year_end)) url.searchParams.set("ii_year_end", String(state.year_end));
    if (Number(state?.offset) > 0) url.searchParams.set("ii_offset", String(Math.max(0, Math.min(1_000, Number(state.offset)))));
    if (clean(state?.snapshot_id, 100)) url.searchParams.set("ii_snapshot", clean(state.snapshot_id, 100));
    if (Number(state?.page) > 1) url.searchParams.set("ii_page", String(Math.max(1, Number(state.page) || 1)));
    if ([10, 25, 50].includes(Number(state?.page_size)) && Number(state.page_size) !== 10) url.searchParams.set("ii_page_size", String(state.page_size));
    const facetKey = snapshotFacetKey(state?.facet_key);
    if (["investigator", "program"].includes(state?.facet_type) && facetKey) {
      url.searchParams.set("ii_facet", state.facet_type);
      url.searchParams.set("ii_facet_key", facetKey);
    }
    return url;
  }

  function compactPageNumbers(page, pageCount) {
    const current = Math.max(1, Number(page) || 1);
    const total = Math.max(1, Number(pageCount) || 1);
    if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
    const values = new Set([1, total, current - 1, current, current + 1]);
    const ordered = [...values].filter(value => value >= 1 && value <= total).sort((left, right) => left - right);
    const compact = [];
    ordered.forEach((value, index) => {
      if (index && value - ordered[index - 1] > 1) compact.push(null);
      compact.push(value);
    });
    return compact;
  }

  function sanitizeQuestionPlan(plan, currentState, question = "") {
    const agency = clean(plan?.agency, 10).toUpperCase();
    const questionText = clean(question, 1_000);
    let yearStart = validYear(plan?.year_start) || "";
    let yearEnd = validYear(plan?.year_end) || "";
    const explicitRange = questionText.match(
      /\b(?:from|between)\s+((?:19|20)\d{2})(?:\s+(?:through|to|until|and)\s+|\s*[-\u2013\u2014]\s*)((?:19|20)\d{2})\b/i,
    );
    const onward = questionText.match(/\b(?:since|from)\s+((?:19|20)\d{2})(?:\s+onward)?\b/i);
    const singleYear = questionText.match(/\b(?:in|during)\s+((?:19|20)\d{2})\b/i);
    if (explicitRange) {
      yearStart = validYear(explicitRange[1]) || "";
      yearEnd = validYear(explicitRange[2]) || "";
    } else if (onward) {
      yearStart = validYear(onward[1]) || "";
      yearEnd = "";
    } else if (singleYear) {
      yearStart = validYear(singleYear[1]) || "";
      yearEnd = yearStart;
    }
    return {
      ...currentState,
      agency: SOURCE_NAMES.includes(agency) ? agency : "all",
      program: clean(plan?.program, 160),
      topic: clean(plan?.topic, 500),
      pi: clean(plan?.pi, 160),
      program_officer: clean(plan?.program_officer, 160),
      year_start: yearStart,
      year_end: yearEnd,
    };
  }

  function explicitInvestigator(question, institution = "", program = "", institutionAliases = [], topic = "") {
    const value = clean(question, 1_000);
    if (!value) return "";
    const name = "([\\p{Lu}][\\p{L}'’.-]*(?:\\s+[\\p{Lu}][\\p{L}'’.-]*){1,3})";
    const patterns = [
      new RegExp(`\\b(?:[Ii]nvestigator|[Rr]esearcher|[Pp]rofessor|[Ff]aculty [Mm]ember|PI)\\s+(?:[Nn]amed\\s+)?${name}(?=\\s*(?:[?.,;:]|$|\\b(?:from|for|at|with|in|under|through|during|between|since|before|after)\\b))`, "u"),
      new RegExp(`\\b(?:[Hh]as|[Dd]id)\\s+${name}\\s+(?:been\\s+funded|receive|received|win|won|lead|led|secure|secured|get|got|have)\\b`, "u"),
    ];
    for (const pattern of patterns) {
      const match = value.match(pattern);
      if (match?.[1]) {
        const candidate = clean(match[1], 160)
          .replace(/[.,;:]+$/u, "")
          .replace(/^(?:Dr|Doctor|Prof|Professor|Mr|Ms|Mrs|Mx)\.?\s+/u, "");
        if (/\b(?:DOE|NIH|NSF|BES)\b/.test(candidate)) continue;
        if (DOE_PROGRAM_OFFICES.has(identityKey(candidate))) continue;
        if (isProgramIdentity(candidate, program)) continue;
        if (identityKey(candidate) === identityKey(topic)) continue;
        if (/\b(?:University|Institute|College|Hospital|Laboratory|Center|Centre|School|Department|Office|Foundation|Corporation|Program|Programme|Initiative|Award|Awards|Fellowship|Fellowships|LLC|Inc)\b/i.test(candidate)) continue;
        const institutionIdentities = [institution, ...(Array.isArray(institutionAliases) ? institutionAliases : [])]
          .map(identityKey)
          .filter(Boolean);
        const candidateKey = identityKey(candidate);
        const institutionKey = identityKey(institution);
        const canonicalSuffix = institutionKey.startsWith(`${candidateKey} `)
          ? institutionKey.slice(candidateKey.length + 1)
          : "";
        if (institutionIdentities.includes(candidateKey)) continue;
        if (/^(?:university|institute|college|hospital|laboratory|center|centre|school|department|office|foundation|corporation)\b/u.test(canonicalSuffix)) continue;
        return candidate;
      }
    }
    return "";
  }

  globalThis.FUNDING_INSTITUTIONAL_INTELLIGENCE = Object.freeze({
    MANAGED_PARAMS,
    aggregateAwards,
    awardMatchesInvestigator,
    buildAwardRequest,
    chooseInstitution,
    compactPageNumbers,
    deterministicInstitutionAnswer,
    evidenceId,
    explicitInvestigator,
    groupInvestigators,
    identityKey,
    investigatorQueryVariants,
    normalizedInvestigatorName,
    programDescriptors,
    programCriterion,
    questionEvidencePack,
    questionProviderPayload,
    requiresExplicitInstitutionSelection,
    sanitizeQuestionPlan,
    sanitizeAnswerIntent,
    sourcesForAgency,
    stateFromSearch,
    urlForState,
    validateNarrativeAnswer,
  });
})();
