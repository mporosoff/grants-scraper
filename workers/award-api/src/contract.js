export const AWARD_SCHEMA_VERSION = 1;

export function cleanText(value, maximum = 20_000) {
  if (value === null || value === undefined) return null;
  const normalized = String(value).replace(/\s+/g, " ").trim();
  return normalized ? normalized.slice(0, maximum) : null;
}

export function cleanSourceText(value, maximum = 20_000) {
  if (value === null || value === undefined) return null;
  const normalized = String(value)
    .replace(/\r\n?/g, "\n")
    .replace(/[^\S\n]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return normalized ? normalized.slice(0, maximum).trimEnd() : null;
}

export function cleanEmail(value) {
  const email = cleanText(value, 320);
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;
  return email;
}

export function isoDate(value) {
  const text = cleanText(value, 40);
  if (!text) return null;
  const usDate = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(text);
  if (usDate) {
    return `${usDate[3]}-${usDate[1].padStart(2, "0")}-${usDate[2].padStart(2, "0")}`;
  }
  const iso = /^(\d{4}-\d{2}-\d{2})/.exec(text);
  return iso ? iso[1] : null;
}

export function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(String(value).replace(/[$,]/g, ""));
  return Number.isFinite(number) ? number : null;
}

export function uniqueStrings(values) {
  const seen = new Set();
  const output = [];
  for (const value of values.flat(Infinity)) {
    const text = cleanText(value, 300);
    if (!text) continue;
    const key = text.toLocaleLowerCase("en-US");
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(text);
  }
  return output;
}

export function safeOfficialUrl(value, allowedHosts) {
  const text = cleanText(value, 2_000);
  if (!text) return null;
  try {
    const url = new URL(text);
    if (url.protocol !== "https:" || !allowedHosts.includes(url.hostname)) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function makeContact({ name, role, email, officialContactUrl, sourceField, sourceUrl }) {
  const normalizedName = cleanText(name, 300);
  if (!normalizedName) return null;
  return {
    name: normalizedName,
    role: cleanText(role, 120),
    email: cleanEmail(email),
    official_contact_url: officialContactUrl,
    source_provenance: {
      source_field: cleanText(sourceField, 120),
      source_url: sourceUrl,
    },
  };
}

const PERSON_NAME_SUFFIXES = new Set(["jr", "sr", "ii", "iii", "iv", "v"]);
const NON_PERSON_CONTACT_TERMS = new Set([
  "administration", "administrator", "agency", "branch", "bureau", "center", "centre",
  "association", "committee", "company", "contact", "corporation", "council", "department", "desk",
  "division", "foundation", "general", "grants", "group", "headquarters", "help", "helpdesk", "hotline",
  "hq", "inc", "institute", "institution", "laboratory", "llc", "office", "program", "programme",
  "service", "staff", "support", "team", "unit", "university",
]);

function contactNameToken(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .toLocaleLowerCase("en-US")
    .replace(/[’]/g, "'")
    .replace(/[‐‑‒–—]/g, "-")
    .replace(/[^\p{L}\p{N}]+/gu, "")
    .trim();
}

function parsedProgramContactName(value) {
  const published = cleanText(value, 300);
  if (!published || /@|https?:|\d{3,}/iu.test(published)) return null;
  const commaParts = published.split(",").map(part => cleanText(part, 160)).filter(Boolean);
  let displayTokens;
  const trailingSuffix = commaParts.length === 2
    && commaParts[1].split(/\s+/u).filter(Boolean).length === 1
    && PERSON_NAME_SUFFIXES.has(contactNameToken(commaParts[1]));
  if (trailingSuffix) {
    displayTokens = [...commaParts[0].split(/\s+/u), ...commaParts[1].split(/\s+/u)];
  } else if (commaParts.length >= 2) {
    const suffix = commaParts.length >= 3 ? commaParts.slice(2) : [];
    displayTokens = [
      ...commaParts[1].split(/\s+/u),
      ...commaParts[0].split(/\s+/u),
      ...suffix.flatMap(part => part.split(/\s+/u)),
    ];
  } else {
    displayTokens = published.split(/\s+/u);
  }
  const tokens = displayTokens.map(contactNameToken).filter(Boolean);
  if (tokens.length < 2 || tokens.length > 7) return null;
  const words = new Set(tokens);
  if ([...words].some(token => NON_PERSON_CONTACT_TERMS.has(token))) return null;
  if (tokens.slice(0, -1).some(token => PERSON_NAME_SUFFIXES.has(token))) return null;
  if (tokens.some(token => token.length > 40)) return null;
  return { published, tokens };
}

export function programContactKey(value) {
  const parsed = parsedProgramContactName(value);
  return parsed ? `program-contact-v1:${parsed.tokens.join("|")}` : null;
}

export function isPersonLikeProgramContactName(value) {
  return Boolean(parsedProgramContactName(value));
}

export function makeProgramContact({ source, sourceDisplayName, ...fields }) {
  const contact = makeContact(fields);
  if (!contact) return null;
  const published = cleanText(sourceDisplayName || fields.name, 300);
  const contactKey = programContactKey(published);
  const normalizedSource = cleanText(source, 10)?.toUpperCase();
  return {
    ...contact,
    source_display_name: published,
    program_contact_key: contactKey,
    program_contact_identity: normalizedSource && contactKey ? `${normalizedSource}:${contactKey}` : null,
    searchable_program_contact: Boolean(normalizedSource && contactKey && published.length <= 160),
  };
}

export function awardMatchesProgramContact(award, source, contactKey) {
  const normalizedSource = cleanText(source, 10)?.toUpperCase();
  const expectedKey = cleanText(contactKey, 300);
  if (!normalizedSource || !expectedKey || cleanText(award?.source, 10)?.toUpperCase() !== normalizedSource) return false;
  return (Array.isArray(award?.program_contacts) ? award.program_contacts : []).some(contact => (
    contact?.searchable_program_contact === true
    && cleanText(contact?.program_contact_key, 300) === expectedKey
    && programContactKey(contact?.source_display_name || contact?.name) === expectedKey
  ));
}

export function awardRecord(fields) {
  return {
    schema_version: AWARD_SCHEMA_VERSION,
    award_id: fields.award_id,
    source_record_ids: fields.source_record_ids || [],
    source: fields.source,
    agency: fields.agency,
    subagency: fields.subagency ?? null,
    program_name: fields.program_name ?? null,
    program_codes: fields.program_codes || [],
    opportunity_numbers: fields.opportunity_numbers || [],
    activity_code: fields.activity_code ?? null,
    funding_mechanism: fields.funding_mechanism ?? null,
    title: fields.title ?? null,
    abstract: fields.abstract ?? null,
    award_date: fields.award_date ?? null,
    project_start: fields.project_start ?? null,
    project_end: fields.project_end ?? null,
    award_year: fields.award_year ?? null,
    total_award: fields.total_award ?? null,
    award_amount_basis: fields.award_amount_basis ?? null,
    institution: fields.institution,
    organization_department: fields.organization_department ?? null,
    principal_investigators: fields.principal_investigators || [],
    program_contacts: fields.program_contacts || [],
    official_award_url: fields.official_award_url,
    annual_support: fields.annual_support || [],
    source_provenance: fields.source_provenance,
  };
}
