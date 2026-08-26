const MIN_AWARD_YEAR = 1989;
const MAX_AWARD_YEAR = 2100;

function boundedYear(value) {
  const year = Number(value);
  return Number.isInteger(year) && year >= MIN_AWARD_YEAR && year <= MAX_AWARD_YEAR ? year : null;
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

export function nihFiscalYears(criteria = {}, currentYear = new Date().getUTCFullYear()) {
  const range = requestedYearRange(criteria);
  if (!range.active) return null;
  const boundedCurrent = boundedYear(currentYear) || MIN_AWARD_YEAR;
  const start = range.start ?? MIN_AWARD_YEAR;
  const end = range.end !== null
    ? Math.min(range.end, Math.max(MIN_AWARD_YEAR, boundedCurrent))
    : Math.max(start, boundedCurrent);
  return Array.from({ length: Math.max(0, end - start + 1) }, (_value, index) => start + index);
}
