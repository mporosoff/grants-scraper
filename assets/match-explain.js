(() => {
  "use strict";

  const MATCH_EXPLAIN_CONTRACT_VERSION = 2;
  const PROFILE_LABELS = Object.freeze({
    manual: "research profile",
    cv: "CV",
    orcid: "ORCID publications",
  });
  const FIELD_LABELS = Object.freeze({
    child_title: "publication-eligible subprogram title",
    child_summary: "subprogram summary",
    authoritative_program_area: "named program area",
    parent_title: "opportunity title",
    parent_description: "opportunity description",
    citation_source_evidence: "official-notice evidence",
  });
  const FIELD_PRIORITY = Object.freeze([
    "child_title",
    "child_summary",
    "authoritative_program_area",
    "parent_title",
    "parent_description",
    "citation_source_evidence",
  ]);
  const CONCEPT_LABELS = Object.freeze({
    "rare-earth-elements": "Rare-earth target",
    separations: "Separation-method",
    "ionic-liquid-extraction": "Ionic-liquid method",
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

  function normalized(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function related(left, right) {
    const a = normalized(left);
    const b = normalized(right);
    if (!a || !b) return false;
    const aTerms = a.split(/\s+/);
    const bTerms = b.split(/\s+/);
    const generic = new Set([
      "advanced", "area", "areas", "energy", "program", "programme",
      "research", "science", "sciences",
    ]);
    return aTerms.some(aTerm => (
      !generic.has(aTerm)
      && bTerms.some(bTerm => (
        Math.min(aTerm.length, bTerm.length) >= 5
        && (aTerm.startsWith(bTerm) || bTerm.startsWith(aTerm))
      ))
    ));
  }

  function matchedProgramAreas(evidence, record, maximum = 1) {
    const signals = (evidence?.groups || []).flatMap(group => [
      group.source,
      ...(group.matchedTerms || []),
      ...(group.matchedDisplayTerms || []),
    ]).filter(Boolean);
    return unique((record?.document_program_areas || [])
      .filter(area => signals.some(signal => related(area, signal))))
      .slice(0, maximum);
  }

  function sentenceLabel(value) {
    const text = String(value || "").trim();
    return text ? `${text[0].toUpperCase()}${text.slice(1)}` : "";
  }

  function cleanText(value) {
    return String(value || "")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function bounded(value, maximum = 180) {
    const text = cleanText(value);
    if (text.length <= maximum) return text;
    const clipped = text.slice(0, Math.max(0, maximum - 1));
    const boundary = clipped.lastIndexOf(" ");
    return `${clipped.slice(0, boundary >= maximum * .6 ? boundary : clipped.length).trim()}…`;
  }

  function quoted(value) {
    const text = bounded(value).replace(/[.!?]+$/g, "");
    return text ? `“${text}”` : "";
  }

  function fieldValue(record, field) {
    if (!record) return "";
    if (field === "child_title" || field === "parent_title") return record.title || "";
    if (field === "child_summary") return record.summary || record.description || "";
    if (field === "authoritative_program_area") {
      return (record.program_area_labels || record.document_program_areas || []).join("; ");
    }
    if (field === "parent_description") return record.description || "";
    if (field === "citation_source_evidence") return record.document_search_text || "";
    return "";
  }

  function matchingSentence(value, terms = [], maximum = 180) {
    const text = cleanText(value);
    if (!text) return "";
    const sentences = text.match(/[^.!?]+[.!?]?/g) || [text];
    const usefulTerms = unique(terms.map(normalized).filter(Boolean));
    const scored = sentences.map((sentence, index) => {
      const normalizedSentence = normalized(sentence);
      const sentenceTerms = new Set(normalizedSentence.split(/\s+/).filter(Boolean));
      const score = usefulTerms.reduce((sum, term) => (
        sum + (sentenceTerms.has(term) ? 3 : related(normalizedSentence, term) ? 1 : 0)
      ), 0);
      return { sentence: cleanText(sentence), score, index };
    });
    scored.sort((left, right) => right.score - left.score || left.index - right.index);
    return bounded(scored[0]?.sentence || text, maximum);
  }

  function admissionFields(evidence) {
    return new Set((evidence?.admission?.admittedBy || [])
      .filter(item => item.path === "explicit_evidence")
      .flatMap(item => item.fields || []));
  }

  function causalFieldRows(evidence, record, { exclude = [] } = {}) {
    const admitted = admissionFields(evidence);
    const excluded = new Set(exclude);
    return (evidence?.admission?.fieldContributions || [])
      .filter(item => (
        item.admissionEligible
        && admitted.has(item.field)
        && !excluded.has(item.field)
        && FIELD_LABELS[item.field]
        && fieldValue(record, item.field)
      ))
      .sort((left, right) => (
        FIELD_PRIORITY.indexOf(left.field) - FIELD_PRIORITY.indexOf(right.field)
        || Number(right.aggregateTermContribution || 0) - Number(left.aggregateTermContribution || 0)
        || String(left.term || "").localeCompare(String(right.term || ""))
      ));
  }

  function shortQueryCollision(query, evidence, record) {
    const queryTerms = normalized(query).split(/\s+/).filter(Boolean);
    if (queryTerms.length !== 1 || queryTerms[0].length > 4) return false;
    const queryTerm = queryTerms[0];
    const exactPattern = new RegExp(`\\b${queryTerm.replace(/[^a-z0-9]/g, "")}\\b`, "i");
    const admitted = admissionFields(evidence);
    if (!admitted.size) return true;
    return ![...admitted].some(field => exactPattern.test(cleanText(fieldValue(record, field))));
  }

  function rareEarthQueryForm(query) {
    const text = String(query || "");
    const match = text.match(/\bREEs?\b|\bR\s*\.\s*E\s*\.\s*E(?:\s*\.)?s?/i);
    return match?.[0]?.replace(/\s+/g, "") || "";
  }

  function evidenceHasConcept(evidence, conceptId) {
    return Boolean(
      evidence?.authoritativeScope?.coveredConcepts?.includes(conceptId)
      || (evidence?.groups || []).some(group => group.conceptId === conceptId)
      || (evidence?.admission?.admittedBy || []).some(item => item.conceptId === conceptId),
    );
  }

  function reason(code, text, evidence = {}) {
    return { code, text, evidence };
  }

  function publicChild(bestChild, childDroveMatch, parentAdmitted) {
    const record = bestChild?.record;
    if (!record || record.child_type !== "subject") return null;
    if (
      record.publication_state
      && !["publish", "published", "publishable"].includes(record.publication_state)
    ) {
      return null;
    }
    if (!(childDroveMatch || !parentAdmitted)) return null;
    if (!bestChild?.directEvidence?.admission?.admitted) return null;
    return bestChild;
  }

  function scopeReasons(query, evidence) {
    const scope = evidence?.authoritativeScope;
    if (!scope || scope.path !== "authoritative_scope_entailment") return [];
    const source = scope.authoritativeScope || {};
    const reasons = [reason(
      "authoritative_scope",
      `Authoritative program scope: ${quoted(source.label)}.`,
      {
        path: scope.path,
        kind: source.kind || "authoritative_scope",
        field: source.kind || "authoritative_scope",
        sourceLabel: source.label || "",
      },
    )];
    const relationships = (scope.controlledRelationships || []).filter(item => (
      /ionic/i.test(query) ? true : !/^ionic-liquid/i.test(item)
    )).slice(0, 2);
    if (relationships.length) {
      reasons.push(reason(
        "controlled_relationship",
        `Controlled relationship: ${sentenceLabel(relationships.join("; "))}.`,
        { path: scope.path, relationships },
      ));
    }
    const form = rareEarthQueryForm(query);
    if (form && evidenceHasConcept(evidence, "rare-earth-elements")) {
      reasons.push(reason(
        "query_interpretation",
        `Interpreted ${quoted(form)} as rare-earth elements.`,
        { canonicalConcept: "rare-earth-elements", userForm: form },
      ));
    }
    return reasons.slice(0, 3);
  }

  function contextualFieldReasons(evidence, record, { exclude = [], maximum = 2 } = {}) {
    const rows = causalFieldRows(evidence, record, { exclude });
    const groups = new Map();
    rows.forEach(row => {
      const key = row.conceptId || "generic";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    });
    return [...groups].slice(0, maximum).flatMap(([conceptId, values]) => {
      const item = values[0];
      const terms = unique(values.map(value => value.term));
      const context = matchingSentence(fieldValue(record, item.field), terms);
      if (!context) return [];
      const conceptLabel = CONCEPT_LABELS[conceptId];
      const prefix = conceptLabel
        ? `${conceptLabel} evidence appears in the ${FIELD_LABELS[item.field]}`
        : `The ${FIELD_LABELS[item.field]} provides the matching context`;
      return [reason(
        "field_context",
        `${prefix}: ${quoted(context)}.`,
        {
          path: "explicit_evidence",
          conceptId: conceptId === "generic" ? "" : conceptId,
          field: item.field,
          terms,
          admissionRole: "admission",
        },
      )];
    });
  }

  function profileReason(profileSources) {
    const source = ["manual", "cv", "orcid"].find(name => (
      Number(profileSources?.[name]?.score || 0) > 0
    ));
    if (!source) return null;
    return reason(
      "profile_contribution",
      `Your ${PROFILE_LABELS[source]} increased this result’s ranking after it met the search criteria.`,
      { source, role: "ranking_only", privateTextIncluded: false },
    );
  }

  function buildV2({
    query = "",
    parent,
    bestChild,
    childDroveMatch = false,
    parentAdmitted,
    profileSources = {},
    eligibility = 0,
    broadFallback = null,
  } = {}) {
    const parentEvidence = parent?.directEvidence || null;
    const parentWasAdmitted = parentAdmitted ?? parent?.parentAdmitted
      ?? parentEvidence?.admission?.admitted === true;
    const child = publicChild(bestChild, childDroveMatch, parentWasAdmitted);
    const activeEvidence = child?.directEvidence
      || (parentWasAdmitted ? parentEvidence : null);
    const activeRecord = child?.record || parent?.record || null;
    const admissionPath = activeEvidence?.admission?.reason || "unexplained";
    let tier = "weak_lexical";
    let label = "Limited match evidence";
    let reasons = [];

    if (broadFallback?.status === true) {
      tier = "broader_program";
      label = "Broader program fit";
      reasons = [reason(
        "broader_program",
        `Broader program fit: ${bounded(broadFallback.scope || broadFallback.label)}${broadFallback.targetExplicit === false ? " The published scope is adjacent but does not explicitly name the target." : ""}`,
        { path: "broad_program_fallback", field: "published_program_scope" },
      )];
    } else if (parentEvidence?.authoritativeScope?.path === "authoritative_scope_entailment") {
      tier = "authoritative_scope";
      label = "Primary program-scope match";
      reasons = scopeReasons(query, parentEvidence);
    } else if (child) {
      tier = "direct";
      label = "Subprogram match";
      reasons.push(reason(
        "child_hierarchy",
        `${parent?.broad ? "This umbrella opportunity matched through" : "Matched through"} the publication-eligible subprogram ${quoted(child.record.title)}.`,
        {
          path: child.directEvidence?.admission?.reason || "explicit_evidence",
          field: "child_hierarchy",
          childTitle: child.record.title,
          childId: child.record.subtopic_id || child.id || "",
          publicationState: child.record.publication_state || "published_index",
        },
      ));
      reasons.push(...contextualFieldReasons(
        child.directEvidence,
        child.record,
        { exclude: ["child_title"], maximum: 1 },
      ));
    } else if (activeEvidence?.exactOpportunityNumber) {
      tier = "direct";
      label = "Exact identifier match";
      reasons.push(reason(
        "exact_opportunity_number",
        `Exact opportunity-number match: ${quoted(activeRecord?.opportunity_number || query)}.`,
        { path: "exact_phrase_or_identifier", field: "opportunity_number" },
      ));
    } else if (activeEvidence?.exactTitlePhrase) {
      tier = "direct";
      label = "Exact title match";
      reasons.push(reason(
        "exact_title",
        `Exact opportunity-title match: ${quoted(activeRecord?.title)}.`,
        { path: "exact_phrase_or_identifier", field: "parent_title" },
      ));
    } else if (
      activeEvidence?.admission?.admitted
      && !shortQueryCollision(query, activeEvidence, activeRecord)
    ) {
      const form = rareEarthQueryForm(query);
      if (form && evidenceHasConcept(activeEvidence, "rare-earth-elements")) {
        reasons.push(reason(
          "query_interpretation",
          `Interpreted ${quoted(form)} as rare-earth elements.`,
          { canonicalConcept: "rare-earth-elements", userForm: form },
        ));
      }
      reasons.push(...contextualFieldReasons(activeEvidence, activeRecord, {
        maximum: Math.max(1, 3 - reasons.length),
      }));
      if (reasons.some(item => item.code === "field_context")) {
        tier = form && activeEvidence.groups?.some(group => (
          group.conceptId === "rare-earth-elements"
          && !["ree", "rees", "rare", "earth", "element", "elements"]
            .includes(String(group.matchedTerms?.[0] || "").toLowerCase())
        )) ? "expanded" : "contextual";
        label = tier === "expanded" ? "Expanded scientific match" : "Contextual evidence match";
      } else {
        reasons = [];
      }
    }

    const profile = profileReason(profileSources);
    if (profile && reasons.length && reasons.length < 3) reasons.push(profile);
    if (Number(eligibility) > 0 && reasons.length && reasons.length < 3) {
      reasons.push(reason(
        "eligibility_contribution",
        "Your applicant or career-stage settings improved this result’s ranking.",
        { role: "ranking_only" },
      ));
    }

    reasons = reasons.slice(0, 3);
    if (!reasons.length) {
      tier = "weak_lexical";
      label = "Limited match evidence";
    }
    return {
      contractVersion: MATCH_EXPLAIN_CONTRACT_VERSION,
      tier,
      label,
      primary: tier !== "broader_program" && reasons.length > 0,
      broadFallback: tier === "broader_program",
      admissionPath,
      reasons,
      trace: {
        admittedBy: activeEvidence?.admission?.admittedBy || [],
        rankedBy: activeEvidence?.admission?.rankedBy || [],
        selectedEvidence: reasons.map(item => item.evidence),
        childDroveMatch: Boolean(child),
        exactOpportunityNumber: Boolean(activeEvidence?.exactOpportunityNumber),
        exactTitlePhrase: Boolean(activeEvidence?.exactTitlePhrase),
        profileSources: profile ? [profile.evidence.source] : [],
        eligibilityContributed: Number(eligibility) > 0,
      },
    };
  }

  function build({ parent, bestChild, profileSources = {}, eligibility = 0 } = {}) {
    const reasons = [];
    const childRecord = bestChild?.record;
    const childTerms = displayTerms(bestChild?.directEvidence, childRecord);
    if (childRecord) {
      const suffix = childTerms.length ? ` (${childTerms.join(", ")})` : "";
      const label = parent?.broad ? "Matched sub-program" : "Matched topic";
      reasons.push(`${label}: ${childRecord.title}${suffix}.`);
    }

    if (parent?.directEvidence?.exactOpportunityNumber) {
      reasons.push("Exact opportunity number match.");
    } else if (parent?.directEvidence?.exactTitlePhrase) {
      reasons.push("Your search phrase appears in the opportunity title.");
    } else {
      const parentTerms = displayTerms(parent?.directEvidence, parent?.record);
      const programAreas = parent?.broad
        ? matchedProgramAreas(parent?.directEvidence, parent?.record)
        : [];
      if (programAreas.length) {
        reasons.push(`Matched notice program area: ${programAreas.map(sentenceLabel).join(", ")}.`);
      } else if (parentTerms.length) {
        reasons.push(`Search terms matched: ${parentTerms.join(", ")}.`);
      }
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

  globalThis.FUNDING_MATCH_EXPLAIN = Object.freeze({
    contractVersion: MATCH_EXPLAIN_CONTRACT_VERSION,
    build,
    buildV2,
    contextualFieldReasons,
    matchingSentence,
    displayTerms,
    matchedProgramAreas,
  });
})();
