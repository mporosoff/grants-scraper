/* Source-owned submission selection. Python parity: scripts/submission_schedule.py. */
(() => {
  "use strict";
  const PRELIMINARY = new Set(["letter_of_intent", "concept_paper", "white_paper", "preapplication", "preproposal"]);
  const FULL = new Set(["application", "estimated_application", "full_application", "proposal"]);
  const KINDS = new Set([...PRELIMINARY, ...FULL, "submission", "internal"]);
  const ACCESS_LABELS = Object.freeze({
    open: "", prerequisite_closed: "Required preliminary submission has closed",
    invitation_required: "Invitation required for the full application", verify_prerequisite: "Verify the required preliminary stage",
    verify_stage: "Verify the submission stage", resubmission_only: "Remaining dates are for resubmissions only",
    closed: "No upcoming submission date", rolling: "Rolling / open until superseded", not_listed: "Date not listed",
  });
  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const instant = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(instant.getTime()) && instant.toISOString().slice(0, 10) === value;
  }
  function events(record) {
    const result = [...(record?.deadlines || []), ...(record?.submission_requirements || [])]
      .filter(event => event && KINDS.has(event.kind)).map(event => ({...event}));
    if (!result.some(event => FULL.has(event.kind) || event.kind === "submission" || event.date === record?.close_date) && validDate(record?.close_date)) result.push({
      kind: record.close_date_kind === "submission_window_end" ? "submission" : "application", date: record.close_date,
      time: record.deadline_time ?? null, timezone: record.deadline_timezone ?? null, source: record.source ?? null});
    return result;
  }
  function compatible(left, right) {
    return ["application_class", "cycle", "track"].every(key => !left[key] || !right[key] || left[key] === right[key]
      || left[key] === "unspecified" || right[key] === "unspecified");
  }
  function nextSubmission(record, asOf = new Date().toISOString().slice(0, 10), applicationClass = "new") {
    if (!validDate(asOf)) throw new Error("Submission selection requires an ISO calendar date");
    const allEvents = events(record);
    const relevant = allEvents.filter(event => !event.application_class || ["unspecified", applicationClass].includes(event.application_class));
    const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
    let future = relevant.filter(event => validDate(event.date) && event.date >= asOf)
      .sort((a, b) => compare(a.date, b.date) || compare(a.kind, b.kind) || compare(a.cycle || "", b.cycle || "") || compare(a.track || "", b.track || ""));
    if (!future.length) future = relevant.filter(event => FULL.has(event.kind) && event.rolling === true && event.date == null)
      .sort((a, b) => compare(a.cycle || "", b.cycle || "") || compare(a.track || "", b.track || ""));
    const result = {version: 1, as_of: asOf, application_class: applicationClass, date: null, event: null, access: "not_listed", prerequisites: []};
    if (!future.length) {
      const full = relevant.filter(event => FULL.has(event.kind) && validDate(event.date));
      const latest = full.map(event => event.date).sort().at(-1);
      const recommended = Boolean(latest) && full.filter(event => event.date === latest).every(event => ["recommended", "anticipated"].includes(event.date_qualifier));
      const otherClasses = allEvents.filter(event => validDate(event.date) && event.date >= asOf);
      result.access = otherClasses.length ? (otherClasses.every(event => event.application_class === "resubmission") ? "resubmission_only" : "verify_stage")
        : recommended ? "verify_stage"
        : relevant.some(event => validDate(event.date)) ? "closed" : record?.rolling ? "rolling" : "not_listed";
      return result;
    }
    const chosen = future[0];
    Object.assign(result, {date: chosen.date ?? null, event: chosen, access: chosen.rolling === true && chosen.date == null ? "rolling" : "open"});
    if (chosen.kind === "submission" || chosen.date_qualifier === "anticipated") result.access = "verify_stage";
    if (FULL.has(chosen.kind)) {
      const preliminary = relevant.filter(event => PRELIMINARY.has(event.kind) && compatible(event, chosen) && event.required !== false);
      if (!chosen.cycle && new Set(preliminary.map(event => event.cycle).filter(Boolean)).size > 1) {
        result.access = "verify_prerequisite";
      } else {
        result.prerequisites = preliminary;
        if (preliminary.some(event => event.required === true && validDate(event.date) && event.date < asOf)) result.access = "prerequisite_closed";
        else if (preliminary.some(event => event.required === true && !validDate(event.date) && event.rolling !== true)) result.access = "verify_prerequisite";
        else if (preliminary.some(event => event.required == null)) result.access = "verify_prerequisite";
      }
      if (!allEvents.some(event => PRELIMINARY.has(event.kind)) && record.has_preliminary_stage === true && record.preliminary_required !== false) {
        result.access = "verify_prerequisite";
      }
      if (chosen.invitation_required === true || chosen.prerequisite === "invitation"
        || relevant.some(event => FULL.has(event.kind) && event.date == null && compatible(event, chosen)
          && event.invitation_required === true)) result.access = "invitation_required";
    }
    return result;
  }
  function recordById(records, id) {
    const direct = records.find(record => String(record.opportunity_id || record.opportunity_number || "") === String(id));
    if (direct) return direct;
    const aliases = records.filter(record => (record.source_aliases || []).some(alias => String(alias.opportunity_id || "") === String(id)));
    return aliases.length === 1 ? aliases[0] : null;
  }
  globalThis.FUNDING_SUBMISSION_SCHEDULE = Object.freeze({version: 1, events, nextSubmission, validDate, recordById, ACCESS_LABELS});
})();
