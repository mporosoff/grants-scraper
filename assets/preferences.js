/*
 * Local, device-only preference model (Workstream B).
 *
 * Learns from the user's own graded relevance labels (Not a fit / Somewhat /
 * Good fit / Strong fit) and gently re-ranks THIS user's future results on
 * their device. It is deterministic, transparent, and reversible: no network,
 * no model call, no data leaves the browser, and the base catalog is unchanged
 * when personalization is off.
 *
 * Design notes:
 * - Signals come from the facet values (topics, disciplines, agency, source,
 *   applicant types) of the opportunities the user has rated.
 * - Positive grades raise those signals; "not a fit" lowers them.
 * - The bonus is bounded (a strong match can at most roughly double a result's
 *   relevance score; a poor-fit pattern can at most halve it) so it nudges the
 *   BM25 ranking rather than replacing it.
 * - `selectExploration` deliberately surfaces a few opportunities the user has
 *   NOT seen that match their positive signals, to counter the filter-bubble
 *   risk where a wrongly-excluded opportunity can never be recovered.
 */
(() => {
  "use strict";

  const STORAGE_KEY = "funding-finder.preference-settings.v1";
  const GRADE_WEIGHTS = {
    strong: 2,
    useful: 1,
    partial: 0.3,
    not_relevant: -1.5,
    needs_verification: 0,
  };
  // Facets the model learns from (arrays or scalars on the record).
  const FACET_FIELDS = ["topic_areas", "disciplines", "agency", "source", "applicant_types"];
  const BONUS_DENOMINATOR = 4; // raw weight of 4 -> full +100% boost
  const MAX_BOOST = 1.0;       // at most double a result's score
  const MAX_PENALTY = -0.5;    // at most halve a result's score
  const MIN_LABELS = 3;        // do not personalize from fewer than this

  function storageOrNull(storage) {
    try {
      return storage || globalThis.localStorage || null;
    } catch {
      return null;
    }
  }

  // `null` means no independent choice has been saved yet, so an older saved
  // profile preference can still be honored during migration.
  function loadEnabled(storage) {
    const target = storageOrNull(storage);
    if (!target) return null;
    try {
      const parsed = JSON.parse(target.getItem(STORAGE_KEY));
      return typeof parsed?.enabled === "boolean" ? parsed.enabled : null;
    } catch {
      return null;
    }
  }

  function saveEnabled(enabled, storage) {
    const target = storageOrNull(storage);
    if (!target) return false;
    try {
      target.setItem(STORAGE_KEY, JSON.stringify({
        schema_version: 1,
        enabled: enabled === true,
      }));
      return true;
    } catch {
      return false;
    }
  }

  function facetValues(record) {
    const values = [];
    for (const field of FACET_FIELDS) {
      const value = record ? record[field] : null;
      if (Array.isArray(value)) {
        for (const item of value) {
          if (item) values.push(`${field}:${item}`);
        }
      } else if (value) {
        values.push(`${field}:${value}`);
      }
    }
    return values;
  }

  // labeled: array of { label, record }
  function buildModel(labeled) {
    const weights = new Map();
    let positives = 0;
    let negatives = 0;
    let used = 0;
    for (const entry of Array.isArray(labeled) ? labeled : []) {
      const weight = GRADE_WEIGHTS[entry && entry.label];
      if (!weight) continue; // undefined or 0 (needs_verification) -> skip
      used += 1;
      if (weight > 0) positives += 1;
      else negatives += 1;
      for (const value of facetValues(entry.record)) {
        weights.set(value, (weights.get(value) || 0) + weight);
      }
    }
    return { weights, positives, negatives, used, ready: used >= MIN_LABELS };
  }

  function rawScore(record, model) {
    if (!model || !model.weights) return 0;
    let raw = 0;
    for (const value of facetValues(record)) {
      raw += model.weights.get(value) || 0;
    }
    return raw;
  }

  // Bounded multiplier applied to a result's relevance score.
  function factor(record, model) {
    if (!model || !model.ready) return 0;
    const scaled = rawScore(record, model) / BONUS_DENOMINATOR;
    return Math.max(MAX_PENALTY, Math.min(MAX_BOOST, scaled));
  }

  // The strongest positive signal explaining a boost, for transparency.
  function explain(record, model) {
    if (!model || !model.ready) return null;
    let best = null;
    for (const value of facetValues(record)) {
      const weight = model.weights.get(value) || 0;
      if (weight > 0 && (!best || weight > best.weight)) {
        const separator = value.indexOf(":");
        best = {
          field: value.slice(0, separator),
          value: value.slice(separator + 1),
          weight,
        };
      }
    }
    return best;
  }

  // Candidates the caller has already filtered to "not currently shown".
  function selectExploration(model, candidates, limit = 3) {
    if (!model || !model.ready) return [];
    const scored = [];
    for (const record of Array.isArray(candidates) ? candidates : []) {
      const raw = rawScore(record, model);
      if (raw > 0) scored.push({ record, raw });
    }
    scored.sort((a, b) => b.raw - a.raw);
    return scored.slice(0, Math.max(0, limit)).map(entry => entry.record);
  }

  globalThis.FUNDING_PREFERENCES = Object.freeze({
    STORAGE_KEY,
    GRADE_WEIGHTS,
    MIN_LABELS,
    loadEnabled,
    saveEnabled,
    facetValues,
    buildModel,
    rawScore,
    factor,
    explain,
    selectExploration,
  });
})();
