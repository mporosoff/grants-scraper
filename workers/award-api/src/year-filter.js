const MIN_AWARD_YEAR = 1989;
const MAX_AWARD_YEAR = 2100;

function boundedYear(value) {
  const year = Number(value);
  return Number.isInteger(year) && year >= MIN_AWARD_YEAR && year <= MAX_AWARD_YEAR ? year : null;
}

export function federalFiscalYear(asOf = new Date()) {
  const directYear = boundedYear(asOf);
  if (directYear !== null) return directYear;
  const date = asOf instanceof Date ? asOf : new Date(asOf);
  const calendarYear = date.getUTCFullYear();
  if (!Number.isInteger(calendarYear)) return MIN_AWARD_YEAR;
  const fiscalYear = calendarYear + (date.getUTCMonth() >= 9 ? 1 : 0);
  return Math.min(MAX_AWARD_YEAR, Math.max(MIN_AWARD_YEAR, fiscalYear));
}

export function requestedYearRange(criteria = {}) {
  const start = boundedYear(criteria.year_start);
  const end = boundedYear(criteria.year_end);
  return {
    active: start !== null || end !== null,
    start,
    end,
  };
}

export function yearFilterDiagnostics(criteria = {}) {
  const range = requestedYearRange(criteria);
  return {
    active: range.active,
    requested_start: range.start,
    requested_end: range.end,
    rejected_missing_year: 0,
    rejected_out_of_range: 0,
  };
}

export function recordSatisfiesYearFilter(value, criteria, diagnostics = null) {
  const range = requestedYearRange(criteria);
  if (!range.active) return true;
  const year = value === null || value === undefined || value === "" ? Number.NaN : Number(value);
  if (!Number.isInteger(year)) {
    if (diagnostics) diagnostics.rejected_missing_year += 1;
    return false;
  }
  if ((range.start !== null && year < range.start) || (range.end !== null && year > range.end)) {
    if (diagnostics) diagnostics.rejected_out_of_range += 1;
    return false;
  }
  return true;
}

export function nihFiscalYears(criteria = {}, asOf = new Date()) {
  const range = requestedYearRange(criteria);
  if (!range.active) return null;
  const start = range.start ?? MIN_AWARD_YEAR;
  const end = range.end !== null
    ? range.end
    : Math.max(start, federalFiscalYear(asOf));
  return Array.from({ length: Math.max(0, end - start + 1) }, (_value, index) => start + index);
}
