(() => {
  "use strict";

  const PROFILE_LABELS = Object.freeze({
    manual: "research profile",
    cv: "CV",
    orcid: "ORCID publications",
  });

  function unique(values) {
    return [...new Set(values.filter(Boolean))];
  }

  function displayTerms(evidence, record, maximum = 3) {
    const display = record?.term_display || {};
    return unique((evidence?.groups || [])
      .slice()
      .sort((left, right) => (
        Number(right.contribution || 0) - Number(left.contribution || 0)
        || String(left.source || "").localeCompare(String(right.source || ""))
      ))
      .flatMap(group => (group.matchedTerms || []).map((term, index) => (
        display[term]
        || group.matchedDisplayTerms?.[index]
        || group.source
        || term
      ))))
      .slice(0, maximum);
  }

  function build({ parent, bestChild, profileSources = {}, eligibility = 0 } = {}) {
    const reasons = [];
    const childRecord = bestChild?.record;
    const childTerms = displayTerms(bestChild?.directEvidence, childRecord);
    if (childRecord) {
      const suffix = childTerms.length ? ` (${childTerms.join(", ")})` : "";
      reasons.push(`Matched topic: ${childRecord.title}${suffix}.`);
    }

    if (parent?.directEvidence?.exactOpportunityNumber) {
      reasons.push("Exact opportunity number match.");
    } else if (parent?.directEvidence?.exactTitlePhrase) {
      reasons.push("Your search phrase appears in the opportunity title.");
    } else {
      const parentTerms = displayTerms(parent?.directEvidence, parent?.record);
      if (parentTerms.length) reasons.push(`Search terms matched: ${parentTerms.join(", ")}.`);
    }

    for (const source of ["manual", "cv", "orcid"]) {
      const item = profileSources[source];
      if (!(Number(item?.score) > 0)) continue;
      const terms = displayTerms(item.evidence, item.record || childRecord || parent?.record);
      reasons.push(
        terms.length
          ? `Your ${PROFILE_LABELS[source]} matched: ${terms.join(", ")}.`
          : `Your ${PROFILE_LABELS[source]} contributed to this match.`,
      );
    }

    if (Number(eligibility) > 0) reasons.push("Your applicant or career-stage settings improved this match.");
    return unique(reasons).slice(0, 3);
  }

  globalThis.FUNDING_MATCH_EXPLAIN = Object.freeze({ build, displayTerms });
})();
