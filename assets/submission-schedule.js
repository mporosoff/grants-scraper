/* Source-owned submission selection. Python parity: scripts/submission_schedule.py. */
(() => {
  "use strict";
  const PRELIMINARY = new Set(["letter_of_intent", "concept_paper", "white_paper", "preapplication", "preproposal", "abstract"]);
  const FULL = new Set(["application", "estimated_application", "full_application", "proposal"]);
  const KINDS = new Set([...PRELIMINARY, ...FULL, "submission", "internal"]);
  const ACCESS_LABELS = Object.freeze({
    open: "", prerequisite_closed: "Required submission step has closed",
    invitation_required: "Invitation required for the full application", verify_prerequisite: "Verify the required submission step",
    verify_stage: "Verify the submission stage", resubmission_only: "Remaining dates are for resubmissions only",
    closed: "No upcoming submission date", rolling: "Rolling / open until superseded", not_listed: "Date not listed",
  });
  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const instant = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(instant.getTime()) && instant.toISOString().slice(0, 10) === value;
  }
  function fiscalCyclePairs(quote) {
    if (typeof quote !== "string" || quote.length > 500) return [];
    const header = /^\s*APPLICATION\s+DEADLINES?\s*:/i.exec(quote);
    if (!header) return [];
    const months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const row = new RegExp(`^\\s*FY\\s*(20\\d{2})\\s+(${months.join("|")})\\s+(\\d{1,2}),?\\s+(20\\d{2})\\b`, "i");
    let tail = quote.slice(header[0].length);
    const pairs = [];
    for (let index = 0; index < 8; index += 1) {
      const match = row.exec(tail);
      if (!match) break;
      const month = months.findIndex(value => value.toLowerCase() === match[2].toLowerCase()) + 1;
      const date = `${match[4]}-${String(month).padStart(2, "0")}-${match[3].padStart(2, "0")}`;
      if (!validDate(date)) return [];
      pairs.push([`FY${match[1]}`, date]);
      tail = tail.slice(match[0].length);
    }
    if (tail.trim() || pairs.length < 2 || new Set(pairs.map(pair => pair[0])).size !== pairs.length
      || pairs.some((pair, index) => index > 0 && (pairs[index - 1][0] >= pair[0] || pairs[index - 1][1] >= pair[1]))) return [];
    return pairs;
  }
  function sameApplicationDocument(requested, served) {
    if (requested === served && typeof requested === "string" && requested) return true;
    if (typeof requested !== "string" || typeof served !== "string") return false;
    const ids = [requested, served].map(value => {
      if (value.slice(0, 8).toLowerCase() !== "https://") return null;
      const route = /^([^/]+)\/grantsws\/rest\/opportunity\/att\/download\/([1-9][0-9]*)$/.exec(value.slice(8));
      if (!route) return null;
      const host = route[1].toLowerCase().replace(/:443$/, "");
      return ["grants.gov", "www.grants.gov", "apply07.grants.gov"].includes(host) ? route[2] : null;
    });
    return Boolean(ids[0] && ids[0] === ids[1]);
  }
  function applicationCycleEnd(record) {
    const evidence = record?.document_evidence || {};
    const document = evidence.document || {};
    const {url, sha256: digest} = document;
    if (record?.document_evidence_status !== "current" || document.source_kind !== "primary_notice"
      || !url || !sameApplicationDocument(record.primary_document_url, url)
      || typeof digest !== "string" || !/^[a-f0-9]{64}$/.test(digest)) return null;
    const deadlines = record.deadlines || [];
    const source = deadlines.filter(event => event?.kind === "application" && !event.evidence_id
      && event.confidence === "official_structured" && event.source_field === "CloseDate" && event.date === record.close_date);
    if (source.length !== 1) return null;
    const owned = citation => citation && citation.document_url === url && citation.sha256 === digest
      && Number.isInteger(citation.page) && citation.page > 0;
    const groups = new Map();
    for (const fact of evidence.facts || []) {
      if (!fact || fact.type !== "deadline" || typeof fact.id !== "string" || !fact.id
        || fact.deadline_kind !== "application" || fact.parser_version !== "fiscal-application-cycles-1"
        || fact.field_authority !== "official_notice_field" || !["new", "unspecified"].includes(fact.application_class) || fact.track
        || fact.estimated || fact.date_qualifier || !owned(fact.citation) || !owned(fact.cycle_citation)) continue;
      const citation = fact.citation;
      const cycleCitation = fact.cycle_citation;
      const reference = citation.structural_reference || {};
      const cycleReference = cycleCitation.structural_reference || {};
      const quote = cycleCitation.quote;
      if (typeof quote !== "string" || quote.length > 500 || citation.page !== cycleCitation.page
        || reference.field_label !== "APPLICATION DEADLINE" || !reference.field_id
        || reference.field_id !== cycleReference.field_id || cycleReference.field_label !== "APPLICATION DEADLINE") continue;
      const key = JSON.stringify([reference.field_id, citation.page, quote]);
      if (!groups.has(key)) groups.set(key, {quote, facts: []});
      groups.get(key).facts.push(fact);
    }
    const proved = new Set();
    for (const {quote, facts} of groups.values()) {
      const pairs = fiscalCyclePairs(quote);
      if (!pairs.length || pairs[0][1] !== record.close_date || facts.length !== pairs.length
        || new Set(facts.map(fact => fact.id)).size !== facts.length
        || !pairs.every(([cycle, date]) => facts.some(fact => fact.cycle === cycle && fact.date === date))) continue;
      const first = facts.find(fact => fact.cycle === pairs[0][0]);
      if (source[0].document_evidence_id !== first.id) continue;
      if (!facts.filter(fact => fact !== first).every(fact => deadlines.some(event => event?.evidence_id === fact.id
        && event.kind === "application" && event.date === fact.date && event.cycle === fact.cycle
        && !event.estimated && !event.date_qualifier))) continue;
      proved.add(JSON.stringify(pairs));
    }
    return proved.size === 1 ? JSON.parse([...proved][0]).at(-1)[1] : null;
  }
  function events(record) {
    const declared = [...(record?.deadlines || []), ...(record?.submission_requirements || [])];
    const result = declared.filter(event => event && KINDS.has(event.kind)
      && event.date_qualifier !== "administrative").map(event => ({...event}));
    if (!result.some(event => FULL.has(event.kind) || event.kind === "submission" || event.date === record?.close_date)
      && !declared.some(event => event?.date_qualifier === "administrative" && event.date === record?.close_date)
      && validDate(record?.close_date)) result.push({
      kind: record.close_date_kind === "submission_window_end" ? "submission" : "application", date: record.close_date,
      time: record.deadline_time ?? null, timezone: record.deadline_timezone ?? null, source: record.source ?? null});
    return result;
  }
  function compatible(left, right) {
    return ["application_class", "cycle", "track"].every(key => !left[key] || !right[key] || left[key] === right[key]
      || left[key] === "unspecified" || right[key] === "unspecified");
  }
  function requiredGate(event) {
    return event.required === true || (event.kind === "internal" && event.required !== false);
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
    const result = {version: 2, as_of: asOf, application_class: applicationClass, date: null, event: null, access: "not_listed", prerequisites: []};
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
    const preliminary = relevant.filter(event => compatible(event, chosen) && event.required !== false
      && ((FULL.has(chosen.kind) && PRELIMINARY.has(event.kind)) || (chosen.kind !== "internal" && event.kind === "internal")));
    if (FULL.has(chosen.kind) || preliminary.length) {
      if (!chosen.cycle && new Set(preliminary.map(event => event.cycle).filter(Boolean)).size > 1) {
        result.access = "verify_prerequisite";
      } else {
        result.prerequisites = preliminary;
        const uncertain = new Set(["recommended", "anticipated"]);
        if (preliminary.some(event => requiredGate(event) && !uncertain.has(event.date_qualifier) && validDate(event.date) && event.date < asOf)) result.access = "prerequisite_closed";
        else if (preliminary.some(event => requiredGate(event) && (uncertain.has(event.date_qualifier) || (!validDate(event.date) && event.rolling !== true)))) result.access = "verify_prerequisite";
        else if (preliminary.some(event => event.required == null && !requiredGate(event))) result.access = "verify_prerequisite";
      }
      if (FULL.has(chosen.kind) && result.access !== "prerequisite_closed" && !allEvents.some(event => PRELIMINARY.has(event.kind)) && record.has_preliminary_stage === true && record.preliminary_required !== false) {
        result.access = "verify_prerequisite";
      }
      if (FULL.has(chosen.kind) && (chosen.invitation_required === true || chosen.prerequisite === "invitation"
        || relevant.some(event => FULL.has(event.kind) && event.date == null && compatible(event, chosen)
          && event.invitation_required === true))) result.access = "invitation_required";
    }
    return result;
  }
  function administrativeSubmissionClosed(record, asOf = new Date().toISOString().slice(0, 10)) {
    if (record?.rolling) return false;
    const declared = [...(record?.deadlines || []), ...(record?.submission_requirements || [])];
    if (!declared.some(event => event?.date_qualifier === "administrative"
      && validDate(event.date) && event.date === record?.close_date)) return false;
    const classes = new Set(["new", ...events(record).map(event => event.application_class)
      .filter(value => typeof value === "string" && value && value !== "unspecified")]);
    return [...classes].every(applicationClass => nextSubmission(record, asOf, applicationClass).access === "closed");
  }
  function recordById(records, id) {
    const direct = records.find(record => String(record.opportunity_id || record.opportunity_number || "") === String(id));
    if (direct) return direct;
    const aliases = records.filter(record => (record.source_aliases || []).some(alias => String(alias.opportunity_id || "") === String(id)));
    return aliases.length === 1 ? aliases[0] : null;
  }
  globalThis.FUNDING_SUBMISSION_SCHEDULE = Object.freeze({version: 2, events, nextSubmission, administrativeSubmissionClosed, applicationCycleEnd, validDate, recordById, ACCESS_LABELS});
})();
