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
