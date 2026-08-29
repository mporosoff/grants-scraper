const SOURCE_NAMES = Object.freeze(["NSF", "NIH", "DOE"]);
export const AWARD_ORDERING_VERSION = "award-recency-v1";
export const SNAPSHOT_BATCH_SIZE = 25;
export const SNAPSHOT_PAGE_SIZES = Object.freeze([10, 25, 50]);
const EN_COLLATOR = new Intl.Collator("en-US");

function clean(value, maximum = 500) {
  const text = String(value ?? "");
  if (!/[\t\n\f\r\v]| {2,}/u.test(text)) return text.trim().slice(0, maximum);
  return text.replace(/\s+/g, " ").trim().slice(0, maximum);
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

function trustworthyDate(value) {
  const date = clean(value, 40);
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : "";
}

export function awardRecency(award) {
  const awardDate = trustworthyDate(award?.award_date);
  if (awardDate) return { date: awardDate, basis: "award_or_action_date" };
  const projectStart = trustworthyDate(award?.project_start);
  if (projectStart) return { date: projectStart, basis: "project_start" };
  const year = validYear(award?.award_year);
  if (year) return { date: `${year}-01-01`, basis: "award_year" };
  return { date: "", basis: "missing" };
}

export function compareAwardsByRecency(left, right) {
  const leftRecency = awardRecency(left);
  const rightRecency = awardRecency(right);
  if (leftRecency.date !== rightRecency.date) return rightRecency.date.localeCompare(leftRecency.date);
  const source = clean(left?.source, 10).localeCompare(clean(right?.source, 10), "en-US");
  if (source) return source;
  return clean(left?.award_id, 120).localeCompare(clean(right?.award_id, 120), "en-US");
}

function awardKey(award) {
  const source = clean(award?.source, 10).toUpperCase();
  const id = clean(award?.award_id, 120);
  return source && id ? `${source}:${id}` : "";
}

function uniqueAwards(values) {
  const seen = new Set();
  return (Array.isArray(values) ? values : []).filter(award => {
    const key = awardKey(award);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function deduplicateAwards(values) {
  return sortAwards(uniqueAwards(values));
}

function sortAwards(values) {
  return values.map(award => ({
    award,
    recency: awardRecency(award).date,
    source: clean(award?.source, 10),
    id: clean(award?.award_id, 120),
  })).sort((left, right) => (
    (right.recency > left.recency ? 1 : right.recency < left.recency ? -1 : 0)
    || EN_COLLATOR.compare(left.source, right.source)
    || EN_COLLATOR.compare(left.id, right.id)
  )).map(item => item.award);
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

function normalizedInvestigatorName(value, cache = null) {
  const raw = String(value ?? "");
  if (!raw) return null;
  if (cache?.has(raw)) return cache.get(raw);
  let published = clean(raw, 300);
  if (!published) return null;
  published = published
    .replace(/^(?:(?:dr|doctor|prof|professor|mr|mrs|ms|miss|mx)\.?\s+)+/iu, "")
    .replace(/(?:,?\s+|,)(?:jr|sr|ii|iii|iv|ph\.?d\.?|m\.?d\.?|dds|dvm|esq)\.?$/iu, "")
    .trim();
  const commaParts = published.split(",").map(part => clean(part, 160)).filter(Boolean);
  const tokens = commaParts.length >= 2
    ? [...commaParts[1].split(/\s+/), ...commaParts[0].split(/\s+/)].filter(Boolean)
    : published.split(/\s+/).filter(Boolean);
  const keyed = tokens.map(personToken).filter(Boolean);
  if (keyed.length < 2) {
    cache?.set(raw, null);
    return null;
  }
  const middleParts = keyed.slice(1, -1);
  const normalized = {
    published: clean(value, 300),
    published_key: identityKey(value),
    first_display: tokens[0],
    middle_display: tokens.slice(1, -1).join(" "),
    family_display: tokens.at(-1),
    first: keyed[0],
    middle: middleParts.join(" "),
    middle_initial: middleParts[0]?.[0] || "",
    middle_is_initial: Boolean(middleParts.length) && middleParts.every(part => part.length === 1),
    family: keyed.at(-1),
    base_key: `${keyed[0]}|${keyed.at(-1)}`,
    complete_key: `${keyed[0]}|${middleParts.join(" ")}|${keyed.at(-1)}`,
  };
  cache?.set(raw, normalized);
  return normalized;
}

function institutionIdentity(award, cache = null) {
  if (cache?.has(award)) return cache.get(award);
  const identity = clean(award?.institution?.identifiers?.ror, 100)
    || identityKey(award?.institution?.normalized_name || award?.institution?.name);
  if (award && typeof award === "object") cache?.set(award, identity);
  return identity;
}

function contactEvidence(person, nameCache, awardEvidence) {
  const parsed = normalizedInvestigatorName(person?.name, nameCache);
  if (!parsed) return null;
  const identifier = clean(person?.source_person_id ?? person?.profile_id, 120);
  return {
    ...parsed,
    ...awardEvidence,
    identifier: identifier ? `${awardEvidence.source}:${identifier}` : "",
    email: clean(person?.email, 320).toLocaleLowerCase("en-US"),
  };
}

function identifiersConflict(left, right) {
  if (!left.identifier || !right.identifier) return false;
  return left.identifier.split(":", 1)[0] === right.identifier.split(":", 1)[0]
    && left.identifier !== right.identifier;
}

function middleCompatible(left, right) {
  if (!left.middle || !right.middle) return true;
  if (left.middle === right.middle) return true;
  return left.middle_initial === right.middle_initial && left.middle_is_initial !== right.middle_is_initial;
}

function contactsCanGroup(left, right) {
  if (left.identifier && left.identifier === right.identifier) return true;
  if (identifiersConflict(left, right)) return false;
  if (left.email && right.email) return left.email === right.email;
  if (!left.institution_key || left.institution_key !== right.institution_key) return false;
  if (left.first !== right.first || left.family !== right.family) return false;
  return left.complete_key === right.complete_key
    || (middleCompatible(left, right) && (!left.middle || !right.middle || left.middle_is_initial !== right.middle_is_initial));
}

function canonicalInvestigatorLabel(entry) {
  const middle = entry.middle_display
    ? entry.middle_display.split(/\s+/u).map(token => personToken(token).length === 1
      ? `${token.replace(/\.+$/u, "")}.`
      : token).join(" ")
    : "";
  return [entry.first_display, middle, entry.family_display].filter(Boolean).join(" ");
}

function investigatorGroups(awards, factsFor) {
  const entries = [];
  const nameCache = new Map();
  for (const award of awards) {
    const awardEvidence = factsFor(award);
    const seen = new Set();
    for (const person of Array.isArray(award?.principal_investigators) ? award.principal_investigators : []) {
      const entry = contactEvidence(person, nameCache, awardEvidence);
      if (!entry) continue;
      const key = `${entry.award_key}:${entry.identifier || entry.email || entry.complete_key}`;
      if (seen.has(key)) continue;
      seen.add(key);
      entries.push(entry);
    }
  }
  entries.sort((left, right) => (
    (left.base_key < right.base_key ? -1 : left.base_key > right.base_key ? 1 : 0)
    || (left.complete_key < right.complete_key ? -1 : left.complete_key > right.complete_key ? 1 : 0)
    || (left.award_key < right.award_key ? -1 : left.award_key > right.award_key ? 1 : 0)
  ));
  const groups = [];
  const identifierIndex = new Map();
  const emailIndex = new Map();
  const baseIndex = new Map();
  const labelPreference = (candidate, current) => (
    Number(Boolean(candidate.middle)) - Number(Boolean(current.middle))
    || candidate.middle.length - current.middle.length
    || -EN_COLLATOR.compare(candidate.published, current.published)
  );
  const compatibilityKey = entry => [
    entry.identifier,
    entry.email,
    entry.institution_key,
    entry.complete_key,
    entry.middle_is_initial ? "1" : "0",
  ].join("\u0000");
  const groupCompatible = (group, entry) => {
    for (const member of group.compatibility.values()) {
      if (!contactsCanGroup(member, entry)) return false;
    }
    return true;
  };
  const findCompatible = (candidates, entry) => {
    for (const candidate of candidates || []) {
      if (groupCompatible(candidate, entry)) return candidate;
    }
    return null;
  };
  const indexGroup = (index, key, group) => {
    if (!key) return;
    const matches = index.get(key) || [];
    if (!matches.includes(group)) matches.push(group);
    index.set(key, matches);
  };
  const addMember = (group, entry) => {
    group.members.push(entry);
    group.compatibility.set(compatibilityKey(entry), entry);
    group.awardKeys.add(entry.award_key);
    if (labelPreference(entry, group.labelEntry) > 0) group.labelEntry = entry;
    const variantKey = `${entry.source}:${entry.published_key}`;
    if (!group.variantKeys.has(variantKey)) {
      group.variantKeys.add(variantKey);
      group.variants.push({ name: entry.published, source: entry.source, award_id: entry.award_id });
    }
  };
  for (const entry of entries) {
    let group = findCompatible(identifierIndex.get(entry.identifier), entry)
      || findCompatible(emailIndex.get(entry.email), entry)
      || findCompatible(baseIndex.get(entry.base_key), entry);
    if (group) addMember(group, entry);
    else {
      group = {
        members: [],
        compatibility: new Map(),
        awardKeys: new Set(),
        labelEntry: entry,
        variantKeys: new Set(),
        variants: [],
      };
      addMember(group, entry);
      groups.push(group);
    }
    indexGroup(identifierIndex, entry.identifier, group);
    indexGroup(emailIndex, entry.email, group);
    indexGroup(baseIndex, entry.base_key, group);
  }
  const normalized = groups.map(group => {
    const labelEntry = group.labelEntry;
    const awardKeys = [...group.awardKeys].sort();
    return {
      name: canonicalInvestigatorLabel(labelEntry),
      normalized: {
        first: labelEntry.first,
        middle: labelEntry.middle,
        middle_initial: labelEntry.middle_initial,
        family: labelEntry.family,
      },
      projects: awardKeys.length,
      variants: group.variants,
      award_keys: awardKeys,
    };
  }).sort((left, right) => (
    EN_COLLATOR.compare(left.normalized.family, right.normalized.family)
    || EN_COLLATOR.compare(left.normalized.first, right.normalized.first)
    || EN_COLLATOR.compare(left.normalized.middle, right.normalized.middle)
    || EN_COLLATOR.compare(left.name, right.name)
  ));
  const identityOrdinals = new Map();
  normalized.forEach(group => {
    const base = `${group.normalized.first}|${group.normalized.family}:${group.normalized.middle_initial || "none"}`;
    const ordinal = (identityOrdinals.get(base) || 0) + 1;
    identityOrdinals.set(base, ordinal);
    group.identity_key = `investigator:${base}:${ordinal}`;
  });
  return normalized;
}

function programDescriptors(award, cache = null) {
  const cacheKey = cache ? [
    award?.source,
    award?.subagency,
    award?.activity_code,
    award?.program_name,
    ...(Array.isArray(award?.program_codes) ? award.program_codes : []),
  ].join("\u0000") : "";
  if (cache?.has(cacheKey)) return cache.get(cacheKey);
  const source = clean(award?.source, 10).toUpperCase();
  const parent = clean(award?.subagency, 300);
  const sourceCodes = [...new Set((Array.isArray(award?.program_codes) ? award.program_codes : [])
    .map(value => clean(value, 100)).filter(Boolean))];
  const code = sourceCodes[0] || "";
  const sourceLeaf = source === "NIH"
    ? clean(award?.activity_code || award?.program_name || code, 300)
    : clean(award?.program_name || code, 300);
  const leaf = sourceLeaf || parent;
  if (!source || !leaf) {
    cache?.set(cacheKey, []);
    return [];
  }
  const distinctChild = Boolean(parent && identityKey(parent) !== identityKey(leaf));
  const doeOfficeCode = sourceCodes.find(value => /^SC-\d+(?:\.\d+)?$/i.test(value));
  const query = source === "DOE" && !distinctChild
    ? /Basic Energy Sciences/i.test(parent) ? "BES" : doeOfficeCode || leaf
    : leaf;
  const descriptors = [{
    key: `${source}:${identityKey(parent || leaf)}:${identityKey(leaf)}`,
    source,
    parent_label: parent || null,
    leaf_label: leaf,
    leaf_role: distinctChild ? "child_program" : "most_specific_available_program",
    query,
    query_role: distinctChild ? "leaf_program" : "fallback_leaf",
    source_codes: sourceCodes,
    label: `${source} · ${distinctChild ? `${parent} › ${leaf}` : leaf}`,
  }];
  cache?.set(cacheKey, descriptors);
  return descriptors;
}

export function aggregateSnapshotAwards(values, { alreadyNormalized = false } = {}) {
  const awards = alreadyNormalized ? values : deduplicateAwards(values);
  const factsCache = new WeakMap();
  const institutionCache = new WeakMap();
  const factsFor = award => {
    let facts = factsCache.get(award);
    if (facts) return facts;
    const source = clean(award?.source, 10).toUpperCase();
    const awardId = clean(award?.award_id, 120);
    facts = {
      source,
      award_key: source && awardId ? `${source}:${awardId}` : "",
      award_id: awardId,
      institution_key: institutionIdentity(award, institutionCache),
      year: validYear(award?.award_year),
      recency: awardRecency(award),
    };
    factsCache.set(award, facts);
    return facts;
  };
  const investigators = investigatorGroups(awards, factsFor);
  const programs = new Map();
  const programCache = new Map();
  const years = new Map();
  const agencyTotals = new Map(SOURCE_NAMES.map(source => [source, 0]));
  for (const award of awards) {
    const facts = factsFor(award);
    const year = facts.year;
    if (year) years.set(year, (years.get(year) || 0) + 1);
    const source = facts.source;
    if (agencyTotals.has(source)) agencyTotals.set(source, agencyTotals.get(source) + 1);
    for (const descriptor of programDescriptors(award, programCache)) {
      const current = programs.get(descriptor.key) || { ...descriptor, projects: 0, award_keys: [] };
      current.projects += 1;
      current.award_keys.push(awardKey(award));
      programs.set(descriptor.key, current);
    }
  }
  const orderedYears = [...years.entries()].sort(([left], [right]) => left - right);
  return {
    project_count: awards.length,
    investigator_count: investigators.length,
    program_count: programs.size,
    year_start: orderedYears[0]?.[0] || null,
    year_end: orderedYears.at(-1)?.[0] || null,
    represented_years: orderedYears.map(([year, projects]) => ({ year, projects })),
    agency_totals: SOURCE_NAMES.map(source => ({ source, projects: agencyTotals.get(source) || 0 })),
    investigators,
    programs: [...programs.values()].map(program => ({
      ...program,
      award_keys: [...new Set(program.award_keys)].sort(),
    })).sort((left, right) => EN_COLLATOR.compare(left.label, right.label)),
    ordered_refs: awards.map((award, index) => {
      const facts = factsFor(award);
      return {
        position: index + 1,
        evidence_id: facts.award_key,
        source: facts.source,
        award_id: facts.award_id,
        title: clean(award?.title, 500),
        award_year: facts.year,
        recency: facts.recency,
      };
    }),
  };
}

function sourceState(source, payload, normalizedResultCount = null) {
  if (!payload || payload.status) {
    const status = payload?.status === "unsupported"
      ? "unsupported"
      : payload?.status === "rate_limited" || ["rate_limited", "source_rate_limited"].includes(payload?.error?.code)
        ? "rate_limited"
        : "unavailable";
    return { source, status, result_count: 0, total_count: null, error: payload?.error || { code: "source_unavailable" } };
  }
  const resultCount = normalizedResultCount ?? (Array.isArray(payload.results) ? payload.results.length : 0);
  const complete = payload.safety_bound_reached !== true
    && payload.has_more !== true
    && Number.isInteger(payload.total_count)
    && payload.total_count >= 0;
  const status = complete ? "complete" : payload.safety_bound_reached === true ? "safety_bounded" : "partial";
  return {
    source,
    status,
    result_count: resultCount,
    total_count: complete ? resultCount : null,
    at_least: resultCount,
    adapter_version: payload.adapter_version,
    cache: payload.cache,
    upstream_total_count: payload.upstream_total_count ?? null,
    raw_record_count: payload.raw_record_count ?? null,
    upstream_pages: payload.upstream_pages ?? null,
    upstream_queries: payload.upstream_queries ?? null,
    safety_bound_reached: payload.safety_bound_reached === true,
    year_filter: payload.year_filter,
    health: payload.health,
    retrieved_at: payload.retrieved_at,
    recency_order: complete ? "verified_complete_snapshot" : "available_snapshot_only",
  };
}

export function buildAwardSnapshot({ snapshotId, queryId, asOf, request, sourcePayloads }) {
  const sourceResults = {};
  const sources = request.sources.map(source => {
    const payload = sourcePayloads[source];
    sourceResults[source] = payload?.status ? [] : uniqueAwards(payload?.results || []);
    return sourceState(source, payload, sourceResults[source].length);
  });
  const awards = sortAwards(request.sources.flatMap(source => sourceResults[source]));
  const complete = sources.every(source => source.status === "complete");
  const sourceMetadata = Object.fromEntries(request.sources.map(source => {
    const { results: _results, ...metadata } = sourcePayloads[source] || {};
    return [source, metadata];
  }));
  return {
    schema_version: 1,
    snapshot_contract_version: 1,
    snapshot_id: snapshotId,
    query_id: queryId,
    as_of: asOf,
    ordering_version: AWARD_ORDERING_VERSION,
    batch_ceiling_per_agency: SNAPSHOT_BATCH_SIZE,
    request,
    completeness: complete ? "complete" : awards.length ? "partial" : "unavailable",
    exact_total: complete ? awards.length : null,
    at_least: awards.length,
    recency_order: complete ? "verified_most_recent_to_older" : "available_snapshot_recent_to_older",
    sources,
    base_aggregate: aggregateSnapshotAwards(awards, { alreadyNormalized: true }),
    awards,
    source_metadata: sourceMetadata,
  };
}

function facetAwards(snapshot, facet = { type: "all", key: "" }) {
  const type = clean(facet?.type, 20) || "all";
  const key = clean(facet?.key, 300);
  if (type === "all") return { facet: { type: "all", key: "", label: "All awards" }, awards: snapshot.awards };
  const groups = type === "investigator" ? snapshot.base_aggregate.investigators
    : type === "program" ? snapshot.base_aggregate.programs : [];
  const group = groups.find(item => (type === "investigator" ? item.identity_key : item.key) === key);
  if (!group) return null;
  const allowed = new Set(group.award_keys);
  return {
    facet: { type, key, label: type === "investigator" ? group.name : group.label },
    awards: snapshot.awards.filter(award => allowed.has(awardKey(award))),
  };
}

function batchObjects(awards, positions = null) {
  const bySource = new Map(SOURCE_NAMES.map(source => [source, []]));
  awards.forEach((award, index) => bySource.get(clean(award?.source, 10).toUpperCase())?.push({
    award,
    position: positions?.[index] ?? index + 1,
  }));
  const batches = [];
  for (const source of SOURCE_NAMES) {
    const records = bySource.get(source) || [];
    for (let index = 0; index < records.length; index += SNAPSHOT_BATCH_SIZE) {
      const chunk = records.slice(index, index + SNAPSHOT_BATCH_SIZE);
      batches.push({
        source,
        batch_index: Math.floor(index / SNAPSHOT_BATCH_SIZE),
        actual_added: chunk.length,
        results: chunk.map(item => ({ ...item.award, snapshot_position: item.position })),
      });
    }
  }
  return batches;
}

export function snapshotSourceBatch(snapshot, { source, offset = 0, facet = { type: "all", key: "" } } = {}) {
  const normalizedSource = clean(source, 10).toUpperCase();
  const start = Math.max(0, Number(offset) || 0);
  const view = facetAwards(snapshot, facet);
  if (!SOURCE_NAMES.includes(normalizedSource) || !view) return null;
  const sourceAwards = view.awards.filter(award => clean(award?.source, 10).toUpperCase() === normalizedSource);
  const results = sourceAwards.slice(start, start + SNAPSHOT_BATCH_SIZE);
  const state = snapshot.sources.find(item => item.source === normalizedSource);
  const end = start + results.length;
  return {
    schema_version: 1,
    snapshot_id: snapshot.snapshot_id,
    query_id: snapshot.query_id,
    ordering_version: snapshot.ordering_version,
    batch_ceiling: SNAPSHOT_BATCH_SIZE,
    source: normalizedSource,
    offset: start,
    actual_added: results.length,
    loaded_through: end,
    source_total: state?.status === "complete" ? sourceAwards.length : null,
    additional_available: end < sourceAwards.length,
    upstream_may_have_more: state?.status !== "complete",
    source_status: state,
    facet: view.facet,
    results,
  };
}

export function snapshotPage(snapshot, { page = 1, pageSize = 10, facet = { type: "all", key: "" } } = {}) {
  const normalizedPage = Number(page);
  const normalizedPageSize = Number(pageSize);
  if (!Number.isInteger(normalizedPage) || normalizedPage < 1 || !SNAPSHOT_PAGE_SIZES.includes(normalizedPageSize)) return null;
  const view = facetAwards(snapshot, facet);
  if (!view) return null;
  const availablePages = Math.max(1, Math.ceil(view.awards.length / normalizedPageSize));
  if (normalizedPage > availablePages) return null;
  const start = (normalizedPage - 1) * normalizedPageSize;
  const selected = view.awards.slice(start, start + normalizedPageSize);
  const allAwards = view.facet.type === "all";
  const aggregate = allAwards
    ? snapshot.base_aggregate
    : aggregateSnapshotAwards(view.awards, { alreadyNormalized: true });
  return {
    schema_version: 1,
    snapshot_contract_version: 1,
    snapshot_id: snapshot.snapshot_id,
    query_id: snapshot.query_id,
    as_of: snapshot.as_of,
    ordering_version: snapshot.ordering_version,
    batch_ceiling_per_agency: SNAPSHOT_BATCH_SIZE,
    completeness: snapshot.completeness,
    exact_total: snapshot.completeness === "complete" ? view.awards.length : null,
    at_least: view.awards.length,
    recency_order: snapshot.recency_order,
    sources: snapshot.sources,
    ...(allAwards ? {} : { base_aggregate: publicAggregate(snapshot.base_aggregate, { includeOrderedRefs: false }) }),
    aggregate: publicAggregate(aggregate),
    facet: view.facet,
    pagination: {
      page: normalizedPage,
      page_size: normalizedPageSize,
      start: selected.length ? start + 1 : 0,
      end: start + selected.length,
      page_count: snapshot.completeness === "complete" ? availablePages : null,
      available_page_count: availablePages,
      has_previous: normalizedPage > 1,
      has_next: normalizedPage < availablePages,
    },
    batches: batchObjects(selected, selected.map((_award, index) => start + index + 1)),
  };
}

export function publicSnapshot(snapshot) {
  return {
    schema_version: snapshot.schema_version,
    snapshot_contract_version: snapshot.snapshot_contract_version,
    snapshot_id: snapshot.snapshot_id,
    query_id: snapshot.query_id,
    as_of: snapshot.as_of,
    ordering_version: snapshot.ordering_version,
    batch_ceiling_per_agency: snapshot.batch_ceiling_per_agency,
    request: snapshot.request,
    completeness: snapshot.completeness,
    exact_total: snapshot.exact_total,
    at_least: snapshot.at_least,
    recency_order: snapshot.recency_order,
    sources: snapshot.sources,
    initial_batches: snapshot.request.sources.map(source => snapshotSourceBatch(snapshot, { source, offset: 0 })),
  };
}

function publicAggregate(aggregate, { includeOrderedRefs = true } = {}) {
  return {
    ...aggregate,
    investigators: aggregate.investigators.map(({ award_keys: _awardKeys, ...investigator }) => investigator),
    programs: aggregate.programs.map(({ award_keys: _awardKeys, ...program }) => program),
    ...(includeOrderedRefs ? {} : { ordered_refs: [] }),
  };
}

export { SOURCE_NAMES, awardKey, facetAwards, identityKey, programDescriptors };
