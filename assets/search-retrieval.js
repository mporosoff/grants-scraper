(() => {
  "use strict";

  const K1 = 1.2;
  const B = .75;
  const PREFIX_LIMIT = 12;
  const FUZZY_LIMIT = 6;
  const RETRIEVAL_API_CONTRACT_VERSION = 5;
  const STALE_UNDATED_MAX_AGE_DAYS = 5 * 366;
  const PRIMARY_EVIDENCE_TIER = Object.freeze({
    exact_or_child: 1,
    authoritative_scope: 2,
    contextual_parent: 3,
    broader_program: 4,
    weak_discovery: 5,
  });
  const BROAD_OPPORTUNITY_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science financial assistance|long[\s-]?range|research announcement|research interests of|established program to stimulate competitive research|research collaboration|\broses\b|omnibus|unsolicited proposal|open topic|financial assistance program|annual program statement|office[ -]wide|open[ -]scope solicitation/i;
  const PROTECTED_TECHNICAL_SCOPE_RE = /\b(?:research|r&d|scientific|hypothesis|experimental|computational|chemical|materials?|separat(?:e|ion|ions)|extract(?:ion)?|process(?:ing)?|recover(?:y)?|purif(?:y|ication)|hydrometallurgy|refin(?:e|ing)|synthesis)\b/i;
  const PROTECTED_NON_RESEARCH_SCOPE_RE = /\b(?:workshops?|training|advocacy|policy recommendations?|public diplomacy|participants?)\b/i;
  const PROTECTED_STRONG_RESEARCH_RE = /\b(?:research|r&d|fundamental|hypothesis|experimental|computational)\b/i;
  const SEPARATION_INTRINSIC_METHOD_RE = /\b(?:separat(?:e|ed|ing|ion|ions)|purif(?:y|ied|ication)|hydrometallurg(?:y|ical)|leach(?:ed|ing)?|ion exchange|membranes?)\b/i;
  const SEPARATION_CONTEXTUAL_METHOD_RE = /\b(?:extract(?:s|ed|ing|ion|ions)?|process(?:es|ed|ing)?|recover(?:s|ed|ing|y|ies)?|refin(?:e|ed|ing))\b/i;
  const SEPARATION_MATERIAL_CONTEXT_RE = /\b(?:chemical|compounds?|critical[\s-]+minerals?|rare[\s-]+earth|lanthanides?|materials?|metals?|minerals?|ores?|resources?|recycl(?:e|ed|ing)|sorbents?|solvents?)\b/i;
  const SEPARATION_PRIMARY_SCOPE_RE = /\b(?:research|r&d|fundamental|scientific|experimental|engineering|methods?|technolog(?:y|ies|ical)|investigat(?:e|es|ed|ing|ion|ions))\b/i;
  const SEPARATION_NON_RESEARCH_RE = /\b(?:workshops?|training|advocacy|policy recommendations?|public diplomacy|commercial diplomacy|participants?|investment forums?)\b/i;
  const INCIDENTAL_ALIGNMENT_RE = /\b(?:aligns? with|consistent with|administration priorit(?:y|ies)|executive orders?|\bEO\s+\d)/i;

  function compareIds(left, right) {
    return String(left).localeCompare(String(right), undefined, {
      numeric: true,
      sensitivity: "base",
    });
  }

  function staleUndatedOpportunity(record, now = Date.now()) {
    if (!record || record.rolling || record.close_date || record.archive_date) return false;
    const status = String(record.status || "").toLowerCase();
    if (!["posted", "forecasted"].includes(status)) return false;
    const posted = Date.parse(String(record.posted_date || ""));
    return Number.isFinite(posted)
      && Math.floor((now - posted) / 86_400_000) > STALE_UNDATED_MAX_AGE_DAYS;
  }

  function nonFundingReason(record) {
    const title = String(record?.title || "").trim();
    if (/^(?:[A-Z0-9_.-]+\s+)?(?:notice of intent\b|request for information\b|rfi\s*[-:])/i.test(title)) {
      return "informational notice";
    }
    const instruments = (record?.funding_instruments || []).map(value => String(value).toLowerCase());
    const note = `${record?.description || ""} ${record?.close_date_note || ""}`;
    if (
      instruments.length
      && instruments.every(value => value === "other")
      && /\bnot accepting applications?\b/i.test(note)
    ) {
      return "not accepting applications";
    }
    return "";
  }

  function runtimeDate(value = Date.now()) {
    const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
    return Number.isFinite(date.getTime()) ? date : null;
  }

  function runtimeDateIso(value = Date.now()) {
    return runtimeDate(value)?.toISOString().slice(0, 10) || "";
  }

  function recordIsArchived(record, now = Date.now()) {
    const status = String(record?.status || "").trim().toLowerCase();
    if (status === "archived") return true;
    const today = runtimeDateIso(now);
    const archiveDate = String(record?.archive_date || "").trim();
    if (!archiveDate) return false;
    return /^\d{4}-\d{2}-\d{2}$/.test(archiveDate) && Boolean(today) && archiveDate <= today;
  }

  function recordIsCurrent(record, now = Date.now()) {
    if (!record) return false;
    const status = String(record.status || "").trim().toLowerCase();
    if (["archived", "closed", "cancelled", "canceled", "withdrawn", "expired"].includes(status)) {
      return false;
    }
    if (recordIsArchived(record, now)) return false;
    if ((status && !["posted", "forecasted"].includes(status)) || nonFundingReason(record)) return false;
    const today = runtimeDateIso(now);
    if (!today) return false;
    const closeDate = String(record.close_date || "").trim();
    if (closeDate) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(closeDate)) return false;
      if (closeDate < today) return false;
    }
    const instant = runtimeDate(now);
    return !staleUndatedOpportunity(record, instant?.getTime());
  }

  function positiveScale(values) {
    const positive = Array.from(values || [])
      .filter(value => Number(value) > 0)
      .map(Number)
      .sort((left, right) => left - right);
    if (!positive.length) return 1;
    return positive[Math.max(0, Math.ceil(positive.length * .9) - 1)];
  }

  function validateSearchV2Configuration(catalog, queryApi, configuration) {
    const specification = configuration?.searchV2Config;
    const role = configuration?.catalogRole === "child" ? "child" : "parent";
    if (!specification || Number(specification.schema_version) !== 2) {
      throw new Error("Search v2 cannot start without its schema-version 2 concept contract.");
    }
    const compatibility = specification.compatibility || {};
    if (Number(queryApi?.contractVersion) !== Number(compatibility.query_api_contract_version)) {
      throw new Error("Search v2 query code is incompatible with its concept contract.");
    }
    if (RETRIEVAL_API_CONTRACT_VERSION !== Number(compatibility.retrieval_api_contract_version)) {
      throw new Error("Search v2 retrieval code is incompatible with its concept contract.");
    }
    const expectedCatalogSchema = Number(
      role === "child"
        ? compatibility.child_catalog_schema_version
        : compatibility.parent_catalog_schema_version,
    );
    if (Number(catalog?.schema_version) !== expectedCatalogSchema) {
      throw new Error(`Search v2 rejected an incompatible ${role} catalog schema.`);
    }
    const algorithm = catalog?.search_index?.algorithm || "bm25";
    if (algorithm !== compatibility.search_index_algorithm) {
      throw new Error("Search v2 rejected an incompatible search-index algorithm.");
    }
    if (Number(catalog?.search_index?.document_count) !== (catalog?.opportunities || []).length) {
      throw new Error("Search v2 rejected a mixed catalog/search-index asset set.");
    }
    return specification;
  }

  function createChildCatalog(sidecar) {
    const index = sidecar?.search_index;
    const recordIds = index?.record_ids || [];
    const recordsById = new Map();
    Object.values(sidecar?.records || {}).forEach(entry => {
      (entry?.subtopics || []).forEach(record => {
        if (record?.subtopic_id) recordsById.set(String(record.subtopic_id), record);
      });
    });
    if (!index?.postings || Number(index.document_count) !== recordIds.length) {
      throw new Error("The topic sidecar search index is incomplete.");
    }
    const opportunities = recordIds.map(identifier => {
      const record = recordsById.get(String(identifier));
      if (
        !record
        || record.publication_state !== "publishable"
        || record.child_type !== "subject"
      ) {
        throw new Error(`Topic index record ${identifier} is not a publishable subject.`);
      }
      return {
        ...record,
        opportunity_id: String(record.subtopic_id),
        opportunity_number: "",
        description: record.summary || "",
        document_search_text: "",
      };
    });
    return Object.freeze({
      schema_version: sidecar.schema_version,
      opportunities,
      search_index: index,
    });
  }

  function rollupRankedRecords({
    parentRows = [],
    childRows = [],
    parentId = row => row?.id,
    childParentId = row => row?.parent_id,
    childId = row => row?.id,
    score = row => row?.score,
  } = {}) {
    const parentScale = positiveScale(parentRows.map(score));
    const childNativeScale = positiveScale(childRows.map(score));
    const childScale = Math.max(parentScale, childNativeScale);
    const childrenByParent = new Map();
    childRows.forEach(row => {
      const value = Number(score(row) || 0);
      if (!(value > 0)) return;
      const identifier = String(childParentId(row) || "");
      if (!identifier) return;
      if (!childrenByParent.has(identifier)) childrenByParent.set(identifier, []);
      childrenByParent.get(identifier).push({
        row,
        id: String(childId(row) || ""),
        raw: value,
        normalized: value / childScale,
      });
    });
    childrenByParent.forEach(children => children.sort((left, right) => (
      right.normalized - left.normalized || compareIds(left.id, right.id)
    )));

    const parentById = new Map(parentRows.map(row => [String(parentId(row) || ""), row]));
    const ids = [...new Set([
      ...parentRows.map(row => String(parentId(row) || "")),
      ...childrenByParent.keys(),
    ].filter(Boolean))];
    return {
      rows: ids.map(id => {
        const parent = parentById.get(id) || null;
        const parentRaw = Number(score(parent) || 0);
        const children = childrenByParent.get(id) || [];
        const parentNormalized = parentRaw > 0 ? parentRaw / parentScale : 0;
        const childNormalized = children[0]?.normalized || 0;
        const childDroveMatch = childNormalized > parentNormalized;
        return {
          id,
          parent,
          parentRaw,
          parentNormalized,
          bestChild: children[0] || null,
          children,
          childNormalized,
          childDroveMatch,
          relevance: Math.max(parentNormalized, childNormalized),
          matchingChildCount: children.length,
        };
      }),
      scales: { parent: parentScale, childNative: childNativeScale, child: childScale },
      cardinalityBonus: 0,
    };
  }

  function rollupScores({
    parentCatalog,
    childCatalog,
    parentDirect,
    parentProfile,
    childDirect,
    childProfile,
    eligibilityBonuses,
  }) {
    const parentRecords = parentCatalog?.opportunities || [];
    const childRecords = childCatalog?.opportunities || [];
    const parentRaw = parentRecords.map((_record, index) => (
      Number(parentDirect?.scores?.[index]) > 0
        ? (2 * Number(parentDirect.scores[index])) + Number(parentProfile?.scores?.[index] || 0)
        : 0
    ));
    const childRaw = childRecords.map((_record, index) => (
      Number(childDirect?.scores?.[index]) > 0
        ? (2 * Number(childDirect.scores[index])) + Number(childProfile?.scores?.[index] || 0)
        : 0
    ));
    const parentScale = positiveScale(parentRaw);
    const childNativeScale = positiveScale(childRaw);
    const childScale = Math.max(parentScale, childNativeScale);
    const childrenByParent = new Map();
    const partialChildrenByParent = new Map();
    const rejectedParents = new Set(parentDirect?.currentnessRejectedIndexes || []);
    const fieldedRanking = parentDirect?.diagnostics?.searchV2?.rankingArchitecture === "fielded_bm25f"
      || childDirect?.diagnostics?.searchV2?.rankingArchitecture === "fielded_bm25f";

    function verifiedGroups(result, index) {
      return new Set(result?.verificationGroupIndexes?.[index] || []);
    }

    function candidateContribution(result, index) {
      return Number(result?.scores?.[index] || 0)
        || Number(result?.lexicalScores?.[index] || 0)
        + Number(result?.semanticScores?.[index] || 0);
    }

    childRecords.forEach((record, index) => {
      const parentId = String(record.parent_id || "");
      const groups = verifiedGroups(childDirect, index);
      if (groups.size && parentId) {
        if (!partialChildrenByParent.has(parentId)) partialChildrenByParent.set(parentId, []);
        partialChildrenByParent.get(parentId).push({
          id: String(record.subtopic_id || record.opportunity_id),
          record,
          index,
          groups,
          contribution: candidateContribution(childDirect, index),
          directEvidence: childDirect?.evidence?.[index] || null,
          profileEvidence: childProfile?.evidence?.[index] || null,
        });
      }
      if (!(Number(childDirect?.scores?.[index]) > 0)) return;
      if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
      childrenByParent.get(parentId).push({
        id: String(record.subtopic_id || record.opportunity_id),
        record,
        raw: childRaw[index],
        normalized: childRaw[index] / childScale,
        evidenceTier: Number(childDirect?.evidenceTiers?.[index] || PRIMARY_EVIDENCE_TIER.contextual_parent),
        directEvidence: childDirect?.evidence?.[index] || null,
        profileEvidence: childProfile?.evidence?.[index] || null,
      });
    });
    childrenByParent.forEach(children => children.sort((left, right) => (
      left.evidenceTier - right.evidenceTier
      || right.normalized - left.normalized
      || compareIds(left.id, right.id)
    )));

    function aggregateScopeMatch(parentIndex, parentId) {
      const queryGroups = parentDirect?.queryGroups || childDirect?.queryGroups || [];
      if (queryGroups.length < 2 || queryGroups.length > 5) return null;
      const expected = new Set(queryGroups.map(group => Number(group.index)));
      const contributors = [];
      const bridgeStopWords = new Set([
        "ai", "analysis", "and", "application", "applications", "area", "areas", "army", "announcement",
        "baa", "challenge", "competencies", "data", "development", "devcom", "domain",
        "focus", "foundational", "method", "methodologies", "office", "program", "proposal",
        "research", "scale", "science", "scientific", "system", "systems", "tdac", "tdacbaa",
        "technique", "techniques", "technology", "title", "topic", "topics", "tpoc",
      ]);
      function bridgeTokens(item) {
        // A broad parent's description can enumerate many unrelated children.
        // For a parent-child bridge, only the umbrella identity in the parent
        // title may connect those scopes; child-child bridges may use each
        // publication-eligible child's full source description.
        const bridgeText = item.kind === "parent"
          ? item.record?.title || ""
          : `${item.record?.title || ""} ${item.record?.description || item.record?.summary || ""}`;
        return new Set((String(bridgeText)
          .toLowerCase().match(/[a-z0-9]+/g) || []).filter(token => (
          token.length >= 4 && !bridgeStopWords.has(token)
        )));
      }
      function hasSharedScientificBridge(pair) {
        const [left, right] = pair.map(bridgeTokens);
        return [...left].some(token => right.has(token));
      }
      const parentGroups = verifiedGroups(parentDirect, parentIndex);
      if (parentGroups.size) {
        contributors.push({
          kind: "parent",
          id: parentId,
          record: parentRecords[parentIndex],
          groups: parentGroups,
          contribution: candidateContribution(parentDirect, parentIndex),
          directEvidence: parentDirect?.evidence?.[parentIndex] || null,
        });
      }
      (partialChildrenByParent.get(parentId) || []).forEach(child => {
        if (!["publishable", "published_index"].includes(child.record.publication_state || "publishable")) return;
        contributors.push({ ...child, kind: "child" });
      });
      const combinations = [];
      for (let left = 0; left < contributors.length; left += 1) {
        for (let right = left + 1; right < contributors.length; right += 1) {
          const pair = [contributors[left], contributors[right]];
          if (pair.every(item => item.kind === "parent")) continue;
          if (!hasSharedScientificBridge(pair)) continue;
          const covered = new Set(pair.flatMap(item => [...item.groups]));
          if (![...expected].every(groupIndex => covered.has(groupIndex))) continue;
          combinations.push({
            contributors: pair,
            contribution: pair.reduce((sum, item) => sum + item.contribution, 0),
          });
        }
      }
      combinations.sort((left, right) => (
        right.contribution - left.contribution
        || left.contributors.map(item => item.id).join("+")
          .localeCompare(right.contributors.map(item => item.id).join("+"))
      ));
      const selected = combinations[0];
      if (!selected) return null;
      const conceptIds = groupIndexes => [...groupIndexes].map(groupIndex => (
        queryGroups[groupIndex]?.conceptId || queryGroups[groupIndex]?.source || String(groupIndex)
      ));
      const childContributors = selected.contributors.filter(item => item.kind === "child");
      const evidenceGroups = selected.contributors.flatMap(item => item.directEvidence?.groups || []);
      const sourceGroups = selected.contributors.flatMap(item => (
        item.directEvidence?.sourceGroundedScope?.groups || []
      ));
      const contributorRows = selected.contributors.map(item => ({
        kind: item.kind,
        id: item.id,
        title: item.record?.title || "",
        coveredConcepts: conceptIds(item.groups),
        publicationState: item.record?.publication_state || "parent",
      }));
      const directEvidence = {
        schemaVersion: 2,
        groups: evidenceGroups,
        authoritativeScope: null,
        sourceGroundedScope: sourceGroups.length ? {
          path: "source_grounded_scope",
          groups: sourceGroups,
        } : null,
        hierarchicalScope: {
          path: "parent_child_scope_aggregation",
          parentId,
          contributors: contributorRows,
          coveredConcepts: conceptIds(expected),
        },
        exactPhrase: false,
        exactTitlePhrase: false,
        exactOpportunityNumber: false,
        trigrams: [],
        admission: {
          admitted: true,
          classification: "primary",
          evidenceTier: PRIMARY_EVIDENCE_TIER.authoritative_scope,
          reason: "parent_child_scope_aggregation",
          lexicalCoverage: expected.size,
          semanticCoverage: 0,
          substantiveCoverage: expected.size,
          finalScore: selected.contribution,
          admittedBy: [{
            path: "parent_child_scope_aggregation",
            parentId,
            coveredConcepts: conceptIds(expected),
            contributors: contributorRows,
          }],
          rankedBy: [{ type: "parent_child_scope_aggregation" }],
          fieldContributions: evidenceGroups.flatMap(group => (
            (group.matchedTermContributions || []).flatMap(term => (
              (term.fields || []).map(field => ({
                conceptId: group.conceptId,
                term: term.term,
                field: field.field,
                admissionEligible: field.admissionEligible,
                aggregateTermContribution: term.contribution,
              }))
            ))
          )),
        },
      };
      const matchingChildren = childContributors.map(child => ({
        id: child.id,
        record: child.record,
        raw: Math.max(.35, child.contribution * 2),
        normalized: Math.max(.35, child.contribution * 2) / childScale,
        evidenceTier: PRIMARY_EVIDENCE_TIER.authoritative_scope,
        directEvidence: child.directEvidence,
        profileEvidence: child.profileEvidence || null,
      })).sort((left, right) => right.normalized - left.normalized || compareIds(left.id, right.id));
      return {
        raw: Math.max(.35, selected.contribution * 2),
        directEvidence,
        matchingChildren,
      };
    }

    const rows = [];
    parentRecords.forEach((record, index) => {
      if (rejectedParents.has(index)) return;
      const id = String(record.opportunity_id || record.opportunity_number || "");
      let matchingChildren = childrenByParent.get(id) || [];
      let parentAdmitted = Number(parentDirect?.scores?.[index]) > 0;
      let parentDirectEvidence = parentDirect?.evidence?.[index] || null;
      const aggregate = !fieldedRanking && !parentAdmitted && !matchingChildren.length
        ? aggregateScopeMatch(index, id)
        : null;
      if (aggregate) {
        parentAdmitted = true;
        parentRaw[index] = aggregate.raw;
        parentDirectEvidence = aggregate.directEvidence;
        matchingChildren = aggregate.matchingChildren;
      }
      if (!parentAdmitted && !matchingChildren.length) return;
      const parentNormalized = parentRaw[index] / parentScale;
      const childNormalized = matchingChildren[0]?.normalized || 0;
      const parentEvidenceTier = aggregate
        ? PRIMARY_EVIDENCE_TIER.authoritative_scope
        : parentAdmitted
        ? Number(parentDirect?.evidenceTiers?.[index] || PRIMARY_EVIDENCE_TIER.contextual_parent)
        : PRIMARY_EVIDENCE_TIER.weak_discovery;
      const childEvidenceTier = matchingChildren[0]?.evidenceTier || PRIMARY_EVIDENCE_TIER.weak_discovery;
      const evidenceTier = Math.min(parentEvidenceTier, childEvidenceTier);
      const childDroveMatch = childEvidenceTier < parentEvidenceTier
        || (childEvidenceTier === parentEvidenceTier && childNormalized > parentNormalized);
      const relevance = Math.max(parentNormalized, childNormalized);
      const eligibility = Number(eligibilityBonuses?.[index] || 0) / parentScale;
      rows.push({
        id,
        record,
        score: relevance + eligibility,
        relevance,
        eligibility,
        evidenceTier,
        parentEvidenceTier,
        childEvidenceTier,
        parentAdmitted,
        parentRaw: parentRaw[index],
        parentNormalized,
        childDroveMatch,
        parentDirectEvidence,
        parentProfileEvidence: parentProfile?.evidence?.[index] || null,
        bestChild: matchingChildren[0] || null,
        matchingChildren,
        matchingChildCount: matchingChildren.length,
      });
    });
    return {
      rows,
      parentRaw,
      childRaw,
      scales: { parent: parentScale, childNative: childNativeScale, child: childScale },
      cardinalityBonus: 0,
    };
  }

  function boundedDamerauLevenshtein(left, right, maximum) {
    if (left === right) return 0;
    if (Math.abs(left.length - right.length) > maximum) return maximum + 1;
    let previousPrevious = null;
    let previous = Array.from({ length: right.length + 1 }, (_, index) => index);

    for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
      const current = [leftIndex];
      let rowMinimum = current[0];
      for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
        const substitution = previous[rightIndex - 1]
          + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1);
        let distance = Math.min(
          current[rightIndex - 1] + 1,
          previous[rightIndex] + 1,
          substitution,
        );
        if (
          previousPrevious
          && leftIndex > 1
          && rightIndex > 1
          && left[leftIndex - 1] === right[rightIndex - 2]
          && left[leftIndex - 2] === right[rightIndex - 1]
        ) {
          distance = Math.min(distance, previousPrevious[rightIndex - 2] + 1);
        }
        current.push(distance);
        rowMinimum = Math.min(rowMinimum, distance);
      }
      if (rowMinimum > maximum) return maximum + 1;
      previousPrevious = previous;
      previous = current;
    }
    return previous[right.length];
  }

  function create(catalog, queryApi, configuration = {}) {
    const index = catalog?.search_index;
    const records = catalog?.opportunities || [];
    if (!index?.postings || !queryApi?.expandGroups) {
      throw new Error("Hybrid search could not initialize because its catalog helpers are missing.");
    }
    const searchV2 = configuration.searchV2 === true;
    const catalogRole = configuration.catalogRole === "child" ? "child" : "parent";
    const searchV2Config = searchV2
      ? validateSearchV2Configuration(catalog, queryApi, configuration)
      : null;
    const evidenceSchemaVersion = searchV2
      ? Number(searchV2Config.compatibility?.evidence_schema_version || 0)
      : 1;
    const preparedCandidateIndexes = Array.isArray(configuration.preparedCandidateIndexes)
      ? new Set(configuration.preparedCandidateIndexes.filter(documentId => (
          Number.isInteger(documentId) && documentId >= 0 && documentId < records.length
        )))
      : null;
    const shouldPrepareDocument = documentId => (
      !preparedCandidateIndexes || preparedCandidateIndexes.has(documentId)
    );

    // The defaults below are the production scoring contract. Phase-1/CI
    // diagnostics may set an individual value to zero to measure an ablation,
    // without carrying a second copy of the retrieval implementation.
    const exactTitleMatchBoost = Number.isFinite(Number(configuration.exactTitleMatchBoost))
      ? Math.max(0, Number(configuration.exactTitleMatchBoost))
      : 24;
    const titlePhraseBoost = Number.isFinite(Number(configuration.titlePhraseBoost))
      ? Math.max(0, Number(configuration.titlePhraseBoost))
      : 12;
    const opportunityNumberBoost = Number.isFinite(Number(configuration.opportunityNumberBoost))
      ? Math.max(0, Number(configuration.opportunityNumberBoost))
      : 50;
    const trigramPhraseBoost = Number.isFinite(Number(configuration.trigramPhraseBoost))
      ? Math.max(0, Number(configuration.trigramPhraseBoost))
      : 40;

    const postings = index.postings;
    const displayTermCache = new Map();
    function displayTerm(documentId, term) {
      const record = records[documentId] || {};
      const explicit = record.term_display?.[term];
      if (explicit) return explicit;
      if (!displayTermCache.has(documentId)) {
        const values = new Map();
        const text = [
          record.title,
          record.description,
          record.document_search_text,
          ...(record.topic_areas || []),
          ...(record.disciplines || []),
        ].filter(Boolean).join(" ");
        (text.match(/[A-Za-z0-9][A-Za-z0-9+.'-]*/g) || []).forEach(value => {
          queryApi.tokenize(value).forEach(normalized => {
            if (!values.has(normalized)) values.set(normalized, value);
          });
        });
        displayTermCache.set(documentId, values);
      }
      return displayTermCache.get(documentId).get(term) || "";
    }
    const indexTerms = Object.keys(postings);
    const documentCount = index.document_count;
    const lengths = index.document_lengths;
    const averageLength = index.average_document_length || 1;
    const termsByLength = new Map();
    const resolutionCache = new Map();
    const exactDocumentsCache = new Map();
    const acronymResolver = queryApi.createAcronymResolver
      ? queryApi.createAcronymResolver(records)
      : null;
    function authoritativeDocumentScopeFacts(record) {
      const facts = record?.document_evidence?.facts || [];
      return facts.filter(fact => fact?.type === "review_criteria").map(fact => ({
        id: String(fact.id || ""),
        type: String(fact.type || ""),
        value: [
          typeof fact.value === "string" ? fact.value : "",
          fact.citation?.quote || "",
        ].filter(Boolean).join(" "),
        citationUrl: String(fact.citation?.citation_url || fact.citation?.document_url || ""),
        documentName: String(fact.citation?.document_name || ""),
        location: String(fact.citation?.location || ""),
      })).filter(fact => fact.value);
    }
    const authoritativeDocumentScopeByDocument = records.map((record, documentId) => (
      shouldPrepareDocument(documentId) ? authoritativeDocumentScopeFacts(record) : []
    ));
    function fieldsForRecord(record, authoritativeDocumentScope) {
      const child = Boolean(record.subtopic_id);
      const authoritativeDocumentScopeText = authoritativeDocumentScope
        .map(fact => fact.value).join(" ");
      return child
        ? [
            ["child_title", record.title || "", true],
            ["child_summary", record.description || record.summary || "", true],
            ["authoritative_program_area", (
              record.program_area_labels || record.document_program_areas || []
            ).join(" "), true],
            ["child_topic", (record.topic_areas || []).join(" "), false],
          ]
        : [
            ["parent_title", record.title || "", true],
            ["parent_description", record.description || "", true],
            ["authoritative_program_area", (
              record.program_area_labels || record.document_program_areas || []
            ).join(" "), true],
            ["authoritative_document_scope", authoritativeDocumentScopeText, true],
            ["citation_source_evidence", record.document_search_text || "", !searchV2],
            ["topic_area", (record.topic_areas || []).join(" "), false],
            ["discipline", (record.disciplines || []).join(" "), false],
            ["agency", record.agency || "", false],
            ["funding_category", (record.funding_categories || []).join(" "), false],
          ];
    }
    const documentFields = records.map((record, documentId) => (
      shouldPrepareDocument(documentId)
        ? fieldsForRecord(record, authoritativeDocumentScopeByDocument[documentId])
        : []
    ));
    const documentFieldTokens = documentFields.map(fields => new Map(
      fields.map(([name, value]) => [name, new Set(queryApi.tokenize(value))]),
    ));
    function scopeTokens(value) {
      return queryApi.tokenize(value).flatMap(term => (
        term.includes("-")
          ? [term, ...term.split("-").filter(part => part.length > 1)]
          : [term]
      ));
    }
    const documentScopeFields = documentFields.map((fields, documentId) => fields
      .filter(([_name, _value, admissionEligible]) => admissionEligible)
      .map(([field, value]) => {
        const tokens = scopeTokens(value);
        const positions = new Map();
        tokens.forEach((token, index) => {
          if (!positions.has(token)) positions.set(token, []);
          positions.get(token).push(index);
        });
        return {
          field,
          value: String(value || ""),
          tokens,
          positions,
          provenance: field === "authoritative_document_scope"
            ? authoritativeDocumentScopeByDocument[documentId]
            : [],
        };
      }));
    const fieldedConfig = searchV2Config?.fielded_ranking || null;
    const fieldedRankingEnabled = searchV2
      && fieldedConfig?.architecture === "bm25f_passage_coordination";
    const fieldWeights = Object.freeze({
      parent_title: 8,
      child_title: 9,
      child_summary: 4,
      parent_description: 2,
      authoritative_program_area: 6,
      authoritative_document_scope: 3,
      ...(fieldedConfig?.field_weights || {}),
    });
    const fieldLengthNormalization = Object.freeze({
      parent_title: .2,
      child_title: .15,
      child_summary: .6,
      parent_description: .75,
      authoritative_program_area: .2,
      authoritative_document_scope: .5,
      ...(fieldedConfig?.field_length_normalization || {}),
    });
    const fieldedK1 = Number(fieldedConfig?.k1 || 1.2);
    const coordinationPower = Number(fieldedConfig?.coordination_power || 3);
    const proximityWindow = Number(fieldedConfig?.proximity_window || 32);
    const proximityBonus = Number(fieldedConfig?.proximity_bonus || 3);
    const exactPhraseBonus = Number(fieldedConfig?.exact_phrase_bonus || 8);
    const titleExactPhraseBonus = Number(fieldedConfig?.title_exact_phrase_bonus || 12);
    const conservativeFuzzyMinimumLength = Number(
      fieldedConfig?.conservative_fuzzy_minimum_length || 7,
    );
    const fieldedFieldNames = Object.keys(fieldWeights);
    const fieldedTokenCounts = documentScopeFields.map(fields => new Map(fields.map(field => {
      const counts = new Map();
      field.tokens.forEach(term => counts.set(term, (counts.get(term) || 0) + 1));
      return [field.field, { ...field, counts }];
    })));
    let fieldedAverageLengths = Object.fromEntries(fieldedFieldNames.map(fieldName => {
      const lengthsForField = fieldedTokenCounts.flatMap(fields => (
        fields.has(fieldName) ? [fields.get(fieldName).tokens.length] : []
      ));
      return [fieldName, lengthsForField.length
        ? lengthsForField.reduce((sum, value) => sum + value, 0) / lengthsForField.length
        : 1];
    }));
    let fieldedVocabulary = new Set(documentScopeFields.flatMap(fields => (
      fields.flatMap(field => [...field.positions.keys()])
    )));
    let fieldedDocumentFrequency = new Map();
    fieldedTokenCounts.forEach(fields => {
      const terms = new Set([...fields.values()].flatMap(field => [...field.counts.keys()]));
      terms.forEach(term => fieldedDocumentFrequency.set(
        term,
        (fieldedDocumentFrequency.get(term) || 0) + 1,
      ));
    });
    if (preparedCandidateIndexes) {
      const vocabulary = new Set();
      const documentFrequency = new Map();
      const lengthTotals = Object.fromEntries(fieldedFieldNames.map(fieldName => [fieldName, 0]));
      const lengthCounts = Object.fromEntries(fieldedFieldNames.map(fieldName => [fieldName, 0]));
      records.forEach(record => {
        const documentTerms = new Set();
        fieldsForRecord(record, authoritativeDocumentScopeFacts(record))
          .filter(([_name, _value, admissionEligible]) => admissionEligible)
          .forEach(([fieldName, value]) => {
            const tokens = scopeTokens(value);
            if (Object.hasOwn(lengthTotals, fieldName)) {
              lengthTotals[fieldName] += tokens.length;
              lengthCounts[fieldName] += 1;
            }
            tokens.forEach(term => {
              vocabulary.add(term);
              documentTerms.add(term);
            });
          });
        documentTerms.forEach(term => documentFrequency.set(
          term,
          (documentFrequency.get(term) || 0) + 1,
        ));
      });
      fieldedVocabulary = vocabulary;
      fieldedDocumentFrequency = documentFrequency;
      fieldedAverageLengths = Object.fromEntries(fieldedFieldNames.map(fieldName => [
        fieldName,
        lengthCounts[fieldName] ? lengthTotals[fieldName] / lengthCounts[fieldName] : 1,
      ]));
    }
    function boundedPassageWindows(value) {
      let sentenceOffset = 0;
      return String(value || "").split(/[\n\r]+/).flatMap(paragraph => {
        const sentences = paragraph.split(/(?<=[.!?])\s+|…+/)
          .map(part => part.trim()).filter(Boolean);
        const windows = sentences.map((_sentence, index) => {
          const end = Math.min(sentences.length, index + 3);
          return {
            value: sentences.slice(index, end).join(" "),
            unit: `sentences:${sentenceOffset + index + 1}-${sentenceOffset + end}`,
          };
        });
        sentenceOffset += sentences.length;
        return windows;
      });
    }
    function atomicFieldedPassage({
      documentId,
      field,
      value,
      unit,
      fields = [field],
      title = "",
    }) {
      const combined = [String(title || "").trim(), String(value || "").trim()]
        .filter(Boolean).join(". ");
      const record = records[documentId] || {};
      const recordId = String(
        record.subtopic_id || record.opportunity_id || record.opportunity_number || documentId,
      );
      return {
        passageId: `${catalogRole}:${recordId}#${field}:${unit}`,
        field,
        fields,
        value: combined,
        tokens: scopeTokens(combined),
      };
    }
    const fieldedPassages = records.map((record, documentId) => {
      if (!shouldPrepareDocument(documentId)) return [];
      const child = Boolean(record.subtopic_id);
      const titleField = child ? "child_title" : "parent_title";
      const descriptionField = child ? "child_summary" : "parent_description";
      const title = String(record.title || "").trim();
      const passages = [];
      if (title) passages.push(atomicFieldedPassage({
        documentId,
        field: titleField,
        value: title,
        unit: "title",
      }));
      boundedPassageWindows(record.description || record.summary || "").forEach(passage => {
        passages.push(atomicFieldedPassage({
          documentId,
          field: descriptionField,
          value: passage.value,
          unit: passage.unit,
          fields: [titleField, descriptionField],
          title,
        }));
      });
      (record.program_area_labels || record.document_program_areas || []).forEach((value, index) => {
        passages.push(atomicFieldedPassage({
          documentId,
          field: "authoritative_program_area",
          value,
          unit: `entry:${index + 1}`,
          fields: [titleField, "authoritative_program_area"],
          title,
        }));
      });
      if (!child) authoritativeDocumentScopeByDocument[documentId].forEach((fact, factIndex) => {
        boundedPassageWindows(fact.value).forEach(passage => {
          passages.push(atomicFieldedPassage({
            documentId,
            field: "authoritative_document_scope",
            value: passage.value,
            unit: `fact:${factIndex + 1}:${passage.unit}`,
            fields: [titleField, "authoritative_document_scope"],
            title,
          }));
        });
      });
      return passages;
    });
    const sourceScopeVocabulary = [...new Set(documentScopeFields.flatMap(fields => (
      fields.flatMap(field => [...field.positions.keys()])
    )))];
    const sourceScopeRelatedTermCache = new Map();
    const sourceScopeRelationships = new Map();
    (searchV2Config?.source_scope_relationships || []).forEach(relationship => {
      const conceptId = String(relationship.query_concept_id || "");
      if (!conceptId) return;
      if (!sourceScopeRelationships.has(conceptId)) sourceScopeRelationships.set(conceptId, []);
      sourceScopeRelationships.get(conceptId).push(relationship);
    });

    function scopeTermsRelated(queryTerm, sourceTerm) {
      if (queryTerm === sourceTerm) return true;
      if (!queryTerm || !sourceTerm) return false;
      const minimum = Math.min(queryTerm.length, sourceTerm.length);
      return minimum >= 5
        && (queryTerm.startsWith(sourceTerm) || sourceTerm.startsWith(queryTerm));
    }

    function sourceScopeRelatedTerms(requirement) {
      if (!sourceScopeRelatedTermCache.has(requirement)) {
        sourceScopeRelatedTermCache.set(requirement, sourceScopeVocabulary.filter(term => (
          term !== requirement && scopeTermsRelated(requirement, term)
        )));
      }
      return sourceScopeRelatedTermCache.get(requirement);
    }

    function fieldScopeMatch(field, requirements, { exactShort = false } = {}) {
      const matches = requirements.map(requirement => {
        const exact = field.positions.get(requirement) || [];
        if (exact.length || (exactShort && requirement.length <= 4)) {
          return exact.map(position => ({ position, term: requirement }));
        }
        return sourceScopeRelatedTerms(requirement).flatMap(term => (
          (field.positions.get(term) || []).map(position => ({ position, term }))
        ));
      });
      if (matches.some(items => !items.length)) return null;
      if (matches.length === 1) {
        return { field: field.field, matchedTerms: [matches[0][0].term] };
      }
      const maximumSpan = 11;
      for (const anchor of matches[0]) {
        const selected = [anchor];
        for (const items of matches.slice(1)) {
          const item = items.find(candidate => Math.abs(candidate.position - anchor.position) <= maximumSpan);
          if (!item) break;
          selected.push(item);
        }
        if (
          selected.length === matches.length
          && Math.max(...selected.map(item => item.position))
            - Math.min(...selected.map(item => item.position)) <= maximumSpan
        ) {
          return {
            field: field.field,
            matchedTerms: [...new Set(selected.map(item => item.term))],
          };
        }
      }
      return null;
    }

    function sourceGroundedRoleEvidence(documentId, group, { allowAdjacent = false } = {}) {
      const fields = documentScopeFields[documentId] || [];
      const exactShort = group.exactIndexedAcronym === true;
      if (
        exactShort
        && group.expansion?.kind !== "contextual_acronym"
        && !exactShortAcronymEvidence(documentId, group.source)
      ) return null;
      const directRequirements = scopeTokens(group.source || "");
      for (const field of fields) {
        const direct = fieldScopeMatch(field, directRequirements, { exactShort });
        if (direct && directRequirements.length) {
          return {
            ...direct,
            path: "source_grounded_scope",
            relationship: null,
            sourceExcerpt: field.value,
            provenance: field.provenance || [],
          };
        }
      }
      for (const relationship of sourceScopeRelationships.get(group.conceptId) || []) {
        for (const alternative of relationship.source_alternatives || []) {
          const evidenceClassRequirements = relationship.evidence_class_requirements?.[
            group.evidenceClass
          ] || [];
          if (
            evidenceClassRequirements.length
            && !alternative.some(term => evidenceClassRequirements.includes(term))
            && !allowAdjacent
          ) continue;
          const requirements = scopeTokens((alternative || []).join(" "));
          for (const field of fields) {
            const related = fieldScopeMatch(field, requirements);
            if (!related || !requirements.length) continue;
            return {
              ...related,
              path: "source_grounded_scope",
              relationship: {
                id: relationship.canonical_id,
                type: relationship.relationship_type,
                rationale: relationship.source_rationale,
                directionality: relationship.directionality,
              },
              sourceExcerpt: field.value,
              provenance: field.provenance || [],
            };
          }
        }
      }
      return null;
    }
    function exactShortAcronymEvidence(documentId, source) {
      const acronym = String(source || "").toUpperCase();
      if (!/^[A-Z0-9]{2,4}$/.test(acronym)) return false;
      const pattern = new RegExp(`(^|[^A-Za-z0-9])${acronym}(?![A-Za-z0-9]|\\s*\\/\\s*[A-Z])`);
      return documentFields[documentId].some(([_field, value, admissionEligible]) => (
        admissionEligible && pattern.test(String(value || ""))
      ));
    }
    const documentTopics = records.map((record, documentId) => shouldPrepareDocument(documentId) ? [
      ...new Set((record.topic_areas || []).filter(Boolean).map(String)),
    ] : []);
    const documentPhraseTokens = records.map((record, documentId) => shouldPrepareDocument(documentId) ? queryApi.tokenize([
      record.title || "",
      record.opportunity_number || "",
      String(record.description || "").slice(0, 5_000),
      String(record.document_search_text || "").slice(0, 16_000),
      ...(record.topic_areas || []),
    ].join(" ")) : []);
    const documentPhraseText = documentPhraseTokens.map(terms => terms.join(" "));
    const documentNarrativeSentences = records.map((record, documentId) => shouldPrepareDocument(documentId) ? [
      record.title || "",
      record.description || record.summary || "",
      ...(record.program_area_labels || []),
      ...authoritativeDocumentScopeByDocument[documentId].map(fact => fact.value),
    ].join(". ").split(/(?<=[.!?])\s+|…+|[\n\r]+/).map(value => (
      new Set(scopeTokens(value))
    )).filter(tokens => tokens.size) : []);
    const documentNarrativeTokens = records.map((record, documentId) => shouldPrepareDocument(documentId) ? queryApi.tokenize([
      record.title || "",
      record.description || record.summary || "",
      ...(record.program_area_labels || []),
      ...authoritativeDocumentScopeByDocument[documentId].map(fact => fact.value),
    ].join(". ")) : []);
    const topicDocuments = new Map();

    function fieldsForTerms(documentId, terms) {
      const required = [...new Set((terms || []).filter(Boolean))];
      return documentFields[documentId].flatMap(([field, _value, admissionEligible]) => {
        const tokens = documentFieldTokens[documentId].get(field) || new Set();
        const matchedTerms = required.filter(term => tokens.has(term));
        return matchedTerms.length ? [{ field, matchedTerms, admissionEligible }] : [];
      });
    }

    function protectedRareEarthEvidence(documentId) {
      const eligibleFields = documentFields[documentId]
        .filter(([_field, _value, admissionEligible]) => admissionEligible);
      const matchingFields = [];
      eligibleFields.forEach(([field, value]) => {
        const text = String(value || "");
        const namedTarget = /\brare[\s-]+earth(?:[\s-]+elements?)?\b|\blanthanides?\b|\b(?:scandium|yttrium|cerium|dysprosium|erbium|europium|gadolinium|holmium|lanthanum|lutetium|neodymium|praseodymium|promethium|samarium|terbium|thulium|ytterbium)\b/i.test(text);
        const acronym = /\bREEs?\b|\bR\s*\.\s*E\s*\.\s*E(?:\s*\.)?s?(?![A-Za-z0-9])/.test(text);
        const acronymContext = /\bcritical[\s-]+minerals?\b|\bseparat(?:e|ion|ions)\b|\bextract(?:ion)?\b|\brecover(?:y)?\b|\bhydrometallurgy\b|\brefin(?:e|ing)\b/i.test(text);
        if (namedTarget || (acronym && acronymContext)) matchingFields.push(field);
      });
      if (!matchingFields.length) return null;
      const substantiveText = eligibleFields.map(([_field, value]) => String(value || "")).join(" ");
      if (!PROTECTED_TECHNICAL_SCOPE_RE.test(substantiveText)) return null;
      if (
        PROTECTED_NON_RESEARCH_SCOPE_RE.test(substantiveText)
        && !PROTECTED_STRONG_RESEARCH_RE.test(substantiveText)
      ) return null;
      return {
        policy: "protected_rare_earth",
        fields: [...new Set(matchingFields)],
      };
    }

    function protectedAiEvidence(documentId) {
      const matchingFields = documentFields[documentId].flatMap(([field, value, admissionEligible]) => {
        if (!admissionEligible) return [];
        const text = String(value || "");
        const longForm = /\bartificial[\s-]+intelligence\b|\bmachine[\s-]+learning\b/i.test(text);
        const acronym = /\bAI\b(?!\s*\/\s*AN\b)/.test(text);
        const technicalContext = /\b(?:AI[\s-]+(?:enabled|ready|driven|based|science|models?)|algorithms?|comput(?:e|ing|ational)|data|models?)\b/i.test(text);
        return longForm || (acronym && technicalContext) ? [field] : [];
      });
      return matchingFields.length ? {
        policy: "protected_ai",
        fields: [...new Set(matchingFields)],
      } : null;
    }

    function protectedPfasEvidence(documentId) {
      const matchingFields = documentFields[documentId].flatMap(([field, value, admissionEligible]) => {
        if (!admissionEligible) return [];
        const text = String(value || "");
        return /\b(?:PFAS|PFOA|PFOS|PFHxS|PFNA|PFBS|AFFF)\b|\b(?:per|poly)fluoroalkyl\b|\bforever[\s-]+chemicals?\b/i.test(text)
          ? [field]
          : [];
      });
      return matchingFields.length ? {
        policy: "protected_pfas",
        fields: [...new Set(matchingFields)],
      } : null;
    }

    function protectedAiSecurityEvidence(documentId, group) {
      const pattern = group?.evidenceClass === "security"
        ? /\b(?:secure|security|cybersecurity|adversarial|attack|mitigation)\b/i
        : /\b(?:secure|security|cybersecurity|adversarial|robustness|robust|resilience|resilient|attack|mitigation|trustworthy)\b/i;
      const matchingFields = documentFields[documentId].flatMap(([field, value, admissionEligible]) => {
        if (!admissionEligible || !/title|description|summary|program_area/.test(field)) return [];
        return pattern.test(String(value || ""))
          ? [field]
          : [];
      });
      return matchingFields.length ? {
        policy: "protected_ai_security",
        fields: [...new Set(matchingFields)],
      } : null;
    }

    function protectedHighTemperatureCompositeEvidence(documentId) {
      const matchingFields = documentFields[documentId].flatMap(([field, value, admissionEligible]) => {
        if (!admissionEligible || !/title|description|summary|program_area/.test(field)) return [];
        return /\bcomposites?\b/i.test(String(value || "")) ? [field] : [];
      });
      return matchingFields.length ? {
        policy: "protected_high_temperature_composites",
        fields: [...new Set(matchingFields)],
      } : null;
    }

    function protectedHypersonicEvidence(documentId) {
      const matchingFields = documentFields[documentId].flatMap(([field, value, admissionEligible]) => {
        if (!admissionEligible || !/title|description|summary|program_area/.test(field)) return [];
        return /\bhypersonics?\b/i.test(String(value || "")) ? [field] : [];
      });
      return matchingFields.length ? {
        policy: "protected_hypersonic",
        fields: [...new Set(matchingFields)],
      } : null;
    }

    function technicalSeparationEvidence(documentId) {
      const eligibleFields = documentFields[documentId]
        .filter(([_field, _value, admissionEligible]) => admissionEligible);
      const narrativeFields = eligibleFields
        .filter(([field]) => /title|description|summary|program_area/.test(field));
      const matchingFields = eligibleFields.flatMap(([field, value]) => {
        const text = String(value || "");
        const sentences = text.split(/(?<=[.!?])\s+|…+|[\n\r]+/);
        const primarySentence = sentences.some(sentence => {
          const materialContext = SEPARATION_MATERIAL_CONTEXT_RE.test(sentence);
          const intrinsic = SEPARATION_INTRINSIC_METHOD_RE.test(sentence)
            && (materialContext || SEPARATION_PRIMARY_SCOPE_RE.test(sentence));
          const contextual = SEPARATION_CONTEXTUAL_METHOD_RE.test(sentence)
            && materialContext;
          return (intrinsic || contextual) && !INCIDENTAL_ALIGNMENT_RE.test(sentence);
        });
        return primarySentence ? [field] : [];
      });
      const narrativeText = narrativeFields
        .map(([_field, value]) => String(value || ""))
        .join(" ");
      if (!matchingFields.length) {
        const combinedMethod = SEPARATION_INTRINSIC_METHOD_RE.test(narrativeText)
          || SEPARATION_CONTEXTUAL_METHOD_RE.test(narrativeText);
        if (
          combinedMethod
          && SEPARATION_MATERIAL_CONTEXT_RE.test(narrativeText)
          && !INCIDENTAL_ALIGNMENT_RE.test(narrativeText)
        ) matchingFields.push(...narrativeFields.map(([field]) => field));
      }
      if (!matchingFields.length) return null;
      if (!SEPARATION_PRIMARY_SCOPE_RE.test(narrativeText)) return null;
      if (
        SEPARATION_NON_RESEARCH_RE.test(narrativeText)
        && !PROTECTED_STRONG_RESEARCH_RE.test(narrativeText)
      ) return null;
      return {
        policy: "technical_separation",
        fields: [...new Set(matchingFields)],
      };
    }

    function controlledCompoundEvidence(documentId, phrases) {
      const phraseTokens = (phrases || [])
        .map(value => queryApi.tokenize(value).join(" "))
        .filter(Boolean);
      const matchingFields = documentFields[documentId].flatMap(([field, value, admissionEligible]) => {
        if (!admissionEligible || !/title|description|summary|program_area/.test(field)) return [];
        const fieldText = queryApi.tokenize(value).join(" ");
        return phraseTokens.some(phrase => (` ${fieldText} `).includes(` ${phrase} `))
          ? [field]
          : [];
      });
      return matchingFields.length ? {
        policy: "controlled_compound",
        fields: [...new Set(matchingFields)],
      } : null;
    }

    indexTerms.forEach(term => {
      if (!termsByLength.has(term.length)) termsByLength.set(term.length, []);
      termsByLength.get(term.length).push(term);
    });
    documentTopics.forEach((topics, documentId) => {
      topics.forEach(topic => {
        if (!topicDocuments.has(topic)) topicDocuments.set(topic, []);
        topicDocuments.get(topic).push(documentId);
      });
    });

    function resolveTerm(term, { exactOnly = false } = {}) {
      if (exactOnly) {
        return postings[term] ? [{ term, weight: 1, kind: "exact" }] : [];
      }
      if (resolutionCache.has(term)) return resolutionCache.get(term);
      if (postings[term]) {
        const exact = [{ term, weight: 1, kind: "exact" }];
        resolutionCache.set(term, exact);
        return exact;
      }
      if (term.length >= 3) {
        const prefixes = indexTerms
          .filter(candidate => candidate.startsWith(term))
          .slice(0, PREFIX_LIMIT)
          .map(candidate => ({ term: candidate, weight: .72, kind: "prefix" }));
        if (prefixes.length) {
          resolutionCache.set(term, prefixes);
          return prefixes;
        }
      }
      if (term.length < 5) {
        resolutionCache.set(term, []);
        return [];
      }

      const maximum = term.length >= 8 ? 2 : 1;
      const candidates = [];
      for (let length = term.length - maximum; length <= term.length + maximum; length += 1) {
        for (const candidate of termsByLength.get(length) || []) {
          if (candidate[0] !== term[0]) continue;
          const distance = boundedDamerauLevenshtein(term, candidate, maximum);
          if (distance > maximum) continue;
          const similarity = 1 - (distance / Math.max(term.length, candidate.length));
          candidates.push({
            term: candidate,
            distance,
            weight: .62 + (.16 * similarity),
            kind: "fuzzy",
          });
        }
      }
      candidates.sort((left, right) =>
        left.distance - right.distance
        || right.weight - left.weight
        || left.term.localeCompare(right.term)
      );
      const fuzzy = candidates.slice(0, FUZZY_LIMIT);
      resolutionCache.set(term, fuzzy);
      return fuzzy;
    }

    function exactDocuments(term) {
      if (exactDocumentsCache.has(term)) return exactDocumentsCache.get(term);
      const values = postings[term] || [];
      const documents = new Set();
      for (let cursor = 0; cursor < values.length; cursor += 2) {
        documents.add(values[cursor]);
      }
      exactDocumentsCache.set(term, documents);
      return documents;
    }

    function inferTopics(documentIds) {
      if (documentIds.size < 2) return [];
      const counts = new Map();
      documentIds.forEach(documentId => {
        documentTopics[documentId].forEach(topic => {
          counts.set(topic, (counts.get(topic) || 0) + 1);
        });
      });
      const requiredHits = Math.max(2, Math.ceil(documentIds.size * .06));
      return [...counts].flatMap(([topic, hits]) => {
        const topicSize = topicDocuments.get(topic)?.length || 0;
        const hitRate = hits / documentIds.size;
        const baseRate = topicSize / Math.max(1, documentCount);
        const lift = hitRate / Math.max(.015, baseRate);
        if (hits < requiredHits || hitRate < .16 || lift < 1.35) return [];
        return [{
          topic,
          confidence: hitRate * Math.log1p(lift) * (1 - Math.min(.65, baseRate)),
        }];
      }).sort((left, right) =>
        right.confidence - left.confidence || left.topic.localeCompare(right.topic)
      ).slice(0, 3);
    }

    function fieldedQueryGroups(query, { context = "" } = {}) {
      const rawUppercase = new Set(
        (String(query || "").match(/\b[A-Z][A-Z0-9.-]{1,7}s?\b/g) || [])
          .flatMap(value => queryApi.tokenize(value)),
      );
      return queryApi.tokenize(query).map((source, index) => {
        const exactIndexedAcronym = rawUppercase.has(source) && source.length <= 8;
        const alternatives = [[source]];
        const compoundParts = source.split("-").filter(part => part.length > 1);
        if (compoundParts.length > 1) alternatives.push(compoundParts);
        let expansion = null;
        if (exactIndexedAcronym) {
          const registeredPhrase = searchV2Config?.acronym_expansions?.[source];
          expansion = registeredPhrase ? {
            phrase: registeredPhrase,
            confidence: 1,
            basis: "registered unambiguous acronym",
          } : String(context || "").trim()
            ? acronymResolver?.resolve?.(source, { context, uppercase: true })
            : null;
          const expansionTerms = expansion ? queryApi.tokenize(expansion.phrase) : [];
          if (expansionTerms.length >= 2) alternatives.push(expansionTerms);
        }
        const normalizedAlternatives = alternatives.map(terms => [...new Set(terms)]);
        return {
          index,
          source,
          conceptId: `literal:${source}`,
          role: "substantive",
          required: true,
          exactIndexedAcronym,
          alternatives: normalizedAlternatives,
          terms: [...new Set(normalizedAlternatives.flat())].map(term => ({
            term,
            weight: term === source ? 1 : .9,
          })),
          evidencePolicy: "indexed_field_evidence",
          expansion: expansion ? {
            kind: "contextual_acronym",
            phrase: expansion.phrase,
            confidence: expansion.confidence,
            basis: expansion.basis,
          } : null,
        };
      });
    }

    function expandedGroups(query, { context = "" } = {}) {
      if (fieldedRankingEnabled) return fieldedQueryGroups(query, { context });
      return queryApi.expandGroups(
        query,
        term => Boolean(postings[term]),
        { acronymResolver, context, searchV2 },
      );
    }

    function scoreFielded(
      query,
      {
        coverage = true,
        context = "",
        minimumCoverage: requestedMinimumCoverage = null,
        evidence: collectEvidence = false,
        candidateIndexes = null,
      } = {},
    ) {
      const groups = fieldedQueryGroups(query, { context });
      const groupCount = groups.length;
      const shortMinimum = Number(searchV2Config?.primary_admission?.concise_query_minimum_groups || 2);
      const shortMaximum = Number(searchV2Config?.primary_admission?.concise_query_maximum_groups || 5);
      const strictComplete = coverage && groupCount >= shortMinimum && groupCount <= shortMaximum;
      const configuredLongCoverage = Number(
        requestedMinimumCoverage
        ?? fieldedConfig?.long_query_minimum_coordination
        ?? .7,
      );
      const minimumCoordination = strictComplete ? 1 : Math.max(0, Math.min(1, configuredLongCoverage));
      const scores = new Float64Array(documentCount);
      const broaderScores = new Float64Array(documentCount);
      const evidenceTiers = new Uint8Array(documentCount);
      const lexicalScores = new Float64Array(documentCount);
      const discoveryScores = new Float64Array(documentCount);
      const semanticScores = new Float64Array(documentCount);
      const lexicalCoverage = new Uint16Array(documentCount);
      const semanticCoverage = new Uint16Array(documentCount);
      const verificationGroupIndexes = Array.from({ length: documentCount }, () => []);
      const currentnessRejectedIndexes = records.flatMap((record, index) => (
        staleUndatedOpportunity(record) ? [index] : []
      ));
      const currentnessRejected = new Set(currentnessRejectedIndexes);
      const fuzzyTerms = new Map();
      const fieldedResolutionCache = new Map();
      const fieldedTermScoreCache = new Map();
      const resultEvidence = collectEvidence
        ? Array.from({ length: documentCount }, () => ({
          schemaVersion: evidenceSchemaVersion,
          groups: [],
          authoritativeScope: null,
          sourceGroundedScope: null,
          highestContributingPassage: null,
          exactPhrase: false,
          exactTitlePhrase: false,
          exactOpportunityNumber: false,
          trigrams: [],
        }))
        : null;

      function fieldedResolutions(term, exactOnly = false) {
        const cacheKey = `${exactOnly ? "exact" : "normal"}:${term}`;
        if (fieldedResolutionCache.has(cacheKey)) return fieldedResolutionCache.get(cacheKey);
        if (fieldedVocabulary.has(term)) {
          const exact = [{ term, weight: 1, kind: "exact" }];
          fieldedResolutionCache.set(cacheKey, exact);
          return exact;
        }
        if (exactOnly || term.length < conservativeFuzzyMinimumLength) {
          fieldedResolutionCache.set(cacheKey, []);
          return [];
        }
        const candidates = [];
        for (let length = term.length - 1; length <= term.length + 1; length += 1) {
          for (const candidate of termsByLength.get(length) || []) {
            if (!fieldedVocabulary.has(candidate) || candidate[0] !== term[0]) continue;
            const distance = boundedDamerauLevenshtein(term, candidate, 1);
            if (distance !== 1) continue;
            candidates.push({ term: candidate, weight: .72, kind: "fuzzy" });
          }
        }
        const resolved = candidates.sort((left, right) => left.term.localeCompare(right.term)).slice(0, 2);
        fieldedResolutionCache.set(cacheKey, resolved);
        return resolved;
      }

      function termFieldScore(documentId, queryTerm, { exactOnly = false } = {}) {
        const cacheKey = `${documentId}:${exactOnly ? "exact" : "normal"}:${queryTerm}`;
        if (fieldedTermScoreCache.has(cacheKey)) return fieldedTermScoreCache.get(cacheKey);
        let best = null;
        fieldedResolutions(queryTerm, exactOnly).forEach(resolution => {
          const df = Number(fieldedDocumentFrequency.get(resolution.term) || 0);
          if (!df) return;
          const idf = Math.log(1 + ((documentCount - df + .5) / (df + .5)));
          const fields = [];
          let weightedFrequency = 0;
          fieldedTokenCounts[documentId].forEach((field, fieldName) => {
            if (!fieldWeights[fieldName]) return;
            const frequency = Number(field.counts.get(resolution.term) || 0);
            if (!frequency) return;
            const average = Math.max(1, Number(fieldedAverageLengths[fieldName] || 1));
            const normalization = 1 - Number(fieldLengthNormalization[fieldName] || 0)
              + Number(fieldLengthNormalization[fieldName] || 0) * (field.tokens.length / average);
            const normalizedFrequency = Number(fieldWeights[fieldName]) * frequency
              / Math.max(.1, normalization);
            weightedFrequency += normalizedFrequency;
            fields.push({
              field: fieldName,
              matchedTerms: [resolution.term],
              admissionEligible: true,
              contribution: normalizedFrequency,
            });
          });
          if (!(weightedFrequency > 0)) return;
          const contribution = resolution.weight * idf
            * ((weightedFrequency * (fieldedK1 + 1)) / (fieldedK1 + weightedFrequency));
          const candidate = { ...resolution, contribution, idf, fields };
          if (resolution.kind === "fuzzy") {
            if (!fuzzyTerms.has(queryTerm)) fuzzyTerms.set(queryTerm, new Set());
            fuzzyTerms.get(queryTerm).add(resolution.term);
          }
          if (!best || candidate.contribution > best.contribution) best = candidate;
        });
        fieldedTermScoreCache.set(cacheKey, best);
        return best;
      }

      function bestGroupMatch(documentId, group) {
        let best = null;
        group.alternatives.forEach(alternative => {
          if (
            group.exactIndexedAcronym === true
            && alternative.length === 1
            && alternative[0] === group.source
            && !exactShortAcronymEvidence(documentId, group.source)
          ) return;
          const matches = alternative.map(term => termFieldScore(documentId, term, {
            exactOnly: group.exactIndexedAcronym === true && alternative.length === 1,
          }));
          if (matches.some(match => !match)) return;
          const contribution = matches.reduce((sum, match) => sum + match.contribution, 0);
          const candidate = { alternative, matches, contribution };
          if (!best || candidate.contribution > best.contribution) best = candidate;
        });
        return best;
      }

      function passageMatch(documentId, documentGroupMatches) {
        let best = null;
        fieldedPassages[documentId].forEach(passage => {
          const positions = new Map();
          passage.tokens.forEach((term, index) => {
            if (!positions.has(term)) positions.set(term, []);
            positions.get(term).push(index);
          });
          const matchedGroups = [];
          const usedPositions = [];
          documentGroupMatches.forEach((groupMatch, groupIndex) => {
            if (!groupMatch) return;
            let selectedAlternative = null;
            groupMatch.alternative.forEach(term => {
              const resolved = groupMatch.matches.find(match => match.term === term)
                || groupMatch.matches.find(match => match.kind === "fuzzy");
              const concrete = resolved?.term || term;
              const position = positions.get(concrete)?.[0];
              if (!Number.isInteger(position)) return;
              if (!selectedAlternative) selectedAlternative = [];
              selectedAlternative.push({ term: concrete, position });
            });
            if (selectedAlternative?.length === groupMatch.alternative.length) {
              matchedGroups.push(groupIndex);
              usedPositions.push(...selectedAlternative.map(item => item.position));
            }
          });
          const span = usedPositions.length
            ? Math.max(...usedPositions) - Math.min(...usedPositions) + 1
            : Number.POSITIVE_INFINITY;
          const candidate = {
            passageId: passage.passageId,
            field: passage.field,
            fields: passage.fields,
            text: passage.value,
            matchedGroups,
            matchedTerms: [...new Set(usedPositions.map(position => passage.tokens[position]))],
            span,
          };
          if (
            !best
            || candidate.matchedGroups.length > best.matchedGroups.length
            || (
              candidate.matchedGroups.length === best.matchedGroups.length
              && candidate.span < best.span
            )
          ) best = candidate;
        });
        return best;
      }

      const normalizedPhrase = queryApi.tokenize(query).join(" ");
      const candidateDocuments = Array.isArray(candidateIndexes)
        ? [...new Set(candidateIndexes)]
          .filter(documentId => Number.isInteger(documentId) && documentId >= 0 && documentId < documentCount)
          .map(documentId => [records[documentId], documentId])
        : records.map((record, documentId) => [record, documentId]);
      candidateDocuments.forEach(([record, documentId]) => {
        const groupMatches = groups.map(group => bestGroupMatch(documentId, group));
        const matchedIndexes = groupMatches.flatMap((match, index) => match ? [index] : []);
        lexicalCoverage[documentId] = matchedIndexes.length;
        const baseScore = groupMatches.reduce((sum, match) => sum + Number(match?.contribution || 0), 0);
        lexicalScores[documentId] = baseScore;
        discoveryScores[documentId] = baseScore;
        const opportunityNumber = String(record.opportunity_number || "").trim().toLowerCase();
        const exactIdentifier = opportunityNumber && String(query || "").trim().toLowerCase() === opportunityNumber;
        if (!(baseScore > 0) && !exactIdentifier || !groupCount) return;
        if (exactIdentifier) discoveryScores[documentId] = opportunityNumberBoost;
        const coordination = matchedIndexes.length / groupCount;
        const singleAcronymExpansionOnly = groupCount === 1
          && groups[0].exactIndexedAcronym === true
          && groups[0].expansion?.basis !== "researcher context"
          && groupMatches[0]
          && !(
            groupMatches[0].alternative.length === 1
            && groupMatches[0].alternative[0] === groups[0].source
            && exactShortAcronymEvidence(documentId, groups[0].source)
          );
        const bestPassage = passageMatch(documentId, groupMatches);
        const atomicMatchedIndexes = bestPassage?.matchedGroups || [];
        verificationGroupIndexes[documentId] = atomicMatchedIndexes;
        const fieldPhraseMatches = documentScopeFields[documentId].filter(field => (
          normalizedPhrase
          && (` ${field.tokens.join(" ")} `).includes(` ${normalizedPhrase} `)
        ));
        const titlePhrase = fieldPhraseMatches.some(field => /title$/.test(field.field));
        const phraseBonus = fieldPhraseMatches.length
          ? (titlePhrase ? titleExactPhraseBonus : exactPhraseBonus)
          : 0;
        const proximity = bestPassage?.matchedGroups.length === groupCount
          && bestPassage.span <= proximityWindow
          ? proximityBonus * (1 - Math.max(0, bestPassage.span - groupCount) / proximityWindow)
          : 0;
        const finalScore = baseScore * Math.pow(coordination, coordinationPower)
          + phraseBonus + proximity + (exactIdentifier ? opportunityNumberBoost : 0);
        const atomicCoordination = atomicMatchedIndexes.length / groupCount;
        const admitted = exactIdentifier || (
          atomicCoordination >= minimumCoordination && !singleAcronymExpansionOnly
        );
        const broader = !admitted
          && groupCount >= 2
          && atomicCoordination >= Math.max(.5, minimumCoordination - .35);
        if (!currentnessRejected.has(documentId)) {
          if (admitted) scores[documentId] = finalScore;
          else if (broader) broaderScores[documentId] = finalScore;
        }
        const bestField = groupMatches.flatMap((match, groupIndex) => (
          (match?.matches || []).flatMap(termMatch => termMatch.fields.map(field => ({
            ...field,
            groupIndex,
            aggregateTermContribution: termMatch.contribution,
          })))
        )).sort((left, right) => (
          right.aggregateTermContribution - left.aggregateTermContribution
          || left.field.localeCompare(right.field)
        ))[0];
        evidenceTiers[documentId] = admitted
          ? (exactIdentifier ? PRIMARY_EVIDENCE_TIER.exact_or_child
            : /child_/.test(bestField?.field || "") ? PRIMARY_EVIDENCE_TIER.exact_or_child
            : /title$/.test(bestField?.field || "") ? PRIMARY_EVIDENCE_TIER.exact_or_child
              : PRIMARY_EVIDENCE_TIER.contextual_parent)
          : broader ? PRIMARY_EVIDENCE_TIER.broader_program : PRIMARY_EVIDENCE_TIER.weak_discovery;
        if (!collectEvidence) return;
        const item = resultEvidence[documentId];
        item.exactPhrase = fieldPhraseMatches.length > 0;
        item.exactTitlePhrase = titlePhrase;
        item.exactOpportunityNumber = Boolean(exactIdentifier);
        item.highestContributingPassage = bestPassage ? {
          passageId: bestPassage.passageId,
          field: bestPassage.field,
          fields: bestPassage.fields,
          text: bestPassage.text,
          matchedTerms: bestPassage.matchedTerms,
          matchedConcepts: bestPassage.matchedGroups.map(index => groups[index].conceptId),
          span: Number.isFinite(bestPassage.span) ? bestPassage.span : null,
        } : null;
        item.groups = groupMatches.flatMap((match, groupIndex) => {
          if (!match || !atomicMatchedIndexes.includes(groupIndex)) return [];
          const group = groups[groupIndex];
          return [{
            source: group.source,
            conceptId: group.conceptId,
            role: group.role,
            evidencePath: "fielded_bm25f",
            contribution: match.contribution,
            rawContribution: match.contribution,
            saturationApplied: false,
            matchedTerms: match.matches.map(termMatch => termMatch.term),
            matchedDisplayTerms: match.matches.map(termMatch => (
              displayTerm(documentId, termMatch.term) || termMatch.term
            )),
            matchedTermContributions: match.matches.map(termMatch => ({
              term: termMatch.term,
              contribution: termMatch.contribution,
              fields: termMatch.fields.filter(field => (
                bestPassage?.fields?.includes(field.field)
              )),
            })),
          }];
        });
        const classification = admitted ? "primary" : broader ? "broader_program_fit" : "reject";
        const incoherentCrossPassageEvidence = !admitted
          && coordination >= minimumCoordination
          && atomicCoordination < minimumCoordination;
        const reason = admitted
          ? exactIdentifier ? "exact_identifier" : "fielded_complete_intent"
          : broader ? "fielded_adjacent_intent"
            : incoherentCrossPassageEvidence
              ? "incoherent_cross_passage_evidence"
              : "insufficient_query_coordination";
        item.admission = {
          admitted,
          classification,
          reason,
          evidenceTier: evidenceTiers[documentId],
          lexicalCoverage: matchedIndexes.length,
          semanticCoverage: 0,
          substantiveCoverage: atomicMatchedIndexes.length,
          atomicCoverage: atomicMatchedIndexes.length,
          atomicEvidenceCoherent: admitted,
          finalScore,
          admittedBy: admitted ? [{
            path: "fielded_bm25f",
            field: bestPassage?.field || bestField?.field || "",
            fields: bestPassage?.fields
              || [bestPassage?.field || bestField?.field || ""].filter(Boolean),
            passageId: bestPassage?.passageId || null,
            matchedConcepts: atomicMatchedIndexes.map(index => groups[index].conceptId),
          }] : [],
          rankedBy: [
            { type: "bm25f", score: baseScore },
            { type: "query_coordination", ratio: coordination, power: coordinationPower },
            { type: "atomic_evidence_coordination", ratio: atomicCoordination },
            ...(phraseBonus ? [{ type: "exact_phrase", score: phraseBonus }] : []),
            ...(proximity ? [{ type: "proximity", score: proximity, span: bestPassage.span }] : []),
          ],
          fieldContributions: groupMatches.flatMap((match, groupIndex) => (
            atomicMatchedIndexes.includes(groupIndex)
              ?
            (match?.matches || []).flatMap(termMatch => termMatch.fields
              .filter(field => bestPassage?.fields?.includes(field.field))
              .map(field => ({
                conceptId: groups[groupIndex].conceptId,
                term: termMatch.term,
                field: field.field,
                admissionEligible: true,
                aggregateTermContribution: termMatch.contribution,
              })))
              : []
          )),
        };
      });

      const discoveredCandidateCount = Array.from(discoveryScores).filter(value => value > 0).length;
      const admittedPrimaryCount = Array.from(scores).filter(value => value > 0).length;
      const admittedBroaderCount = Array.from(broaderScores).filter(value => value > 0).length;
      return {
        scores,
        broaderScores,
        evidenceTiers,
        lexicalScores,
        discoveryScores,
        semanticScores,
        lexicalCoverage,
        semanticCoverage,
        evidence: resultEvidence,
        queryGroups: groups.map(group => ({
          index: group.index,
          conceptId: group.conceptId,
          role: group.role,
          source: group.source,
        })),
        verificationGroupIndexes,
        currentnessRejectedIndexes,
        hasTerms: groupCount > 0,
        diagnostics: {
          queryGroups: groupCount,
          minimumCoverage: minimumCoordination,
          fuzzyTerms: [...fuzzyTerms].map(([source, matches]) => ({ source, matches: [...matches] })),
          inferredTopics: [],
          acronymExpansions: groups.filter(group => group.expansion).map(group => ({
            source: group.source,
            phrase: group.expansion.phrase,
            confidence: group.expansion.confidence,
            basis: group.expansion.basis,
          })),
          searchV2: {
            enabled: searchV2,
            contractVersion: searchV2Config?.contract_version || null,
            evidenceSchemaVersion,
            catalogRole,
            rankingArchitecture: "fielded_bm25f",
            configuredScientificEntailmentsUsed: false,
            strictCompleteCoverage: strictComplete,
            queryPlan: groups.map(group => ({
              conceptId: group.conceptId,
              role: group.role,
              required: true,
              source: group.source,
              evidencePolicy: "indexed_field_evidence",
            })),
            discovery: {
              internalCandidateCount: discoveredCandidateCount,
              visiblePrimaryCount: admittedPrimaryCount,
              broaderFitCount: admittedBroaderCount,
              rejectedPartialIntentCount: Math.max(
                0,
                discoveredCandidateCount - admittedPrimaryCount - admittedBroaderCount,
              ),
              rejectedCurrentnessCount: currentnessRejectedIndexes.length,
              admissionCounts: {
                exactOrChild: Array.from(evidenceTiers).filter(value => value === PRIMARY_EVIDENCE_TIER.exact_or_child).length,
                authoritativeScope: 0,
                contextualParent: Array.from(evidenceTiers).filter(value => value === PRIMARY_EVIDENCE_TIER.contextual_parent).length,
              },
            },
          },
          scoringConfiguration: {
            architecture: "bm25f_passage_coordination",
            fieldWeights,
            fieldLengthNormalization,
            k1: fieldedK1,
            coordinationPower,
            proximityWindow,
            proximityBonus,
            exactPhraseBonus,
            titleExactPhraseBonus,
            opportunityNumberBoost,
          },
        },
      };
    }

    function authoritativeScopeMatches(groups) {
      if (!searchV2 || catalogRole !== "parent") return new Map();
      const scientificConcepts = [...new Set(groups
        .filter(group => group.required === true && group.conceptId)
        .map(group => group.conceptId))];
      if (!scientificConcepts.length) return new Map();
      const recordById = new Map(records.map((record, documentId) => [
        String(record.opportunity_id || record.opportunity_number || ""),
        documentId,
      ]));
      const matches = new Map();
      (searchV2Config.authoritative_scope_entailments || []).forEach(entry => {
        const supported = new Set(entry.supported_query_concepts || []);
        const required = entry.required_query_concepts || [];
        const signatureSupported = new Set(entry.scope_signature?.supported_concepts || []);
        const exactContractMatch = required.every(conceptId => scientificConcepts.includes(conceptId))
          && !(
            searchV2Config.scope_entailment_requires_complete_scientific_query
            && scientificConcepts.some(conceptId => !supported.has(conceptId))
          );
        const signatureMatch = entry.scope_signature?.bounded === true
          && scientificConcepts.length >= 2
          && scientificConcepts.every(conceptId => signatureSupported.has(conceptId));
        if (!exactContractMatch && !signatureMatch) return;
        const documentId = recordById.get(String(entry.parent_id || ""));
        if (!Number.isInteger(documentId)) return;
        matches.set(documentId, {
          ...entry,
          coveredConcepts: scientificConcepts.filter(conceptId => (
            exactContractMatch ? supported.has(conceptId) : signatureSupported.has(conceptId)
          )),
          matchType: signatureMatch && !exactContractMatch
            ? "source_scope_signature"
            : "controlled_concept_contract",
        });
      });
      return matches;
    }

    function designatedBroaderFitMatches(groups) {
      if (!searchV2 || catalogRole !== "parent") return new Map();
      const scientificConcepts = [...new Set(groups
        .filter(group => group.required === true && group.conceptId)
        .map(group => group.conceptId))];
      if (!scientificConcepts.length) return new Map();
      const recordById = new Map(records.map((record, documentId) => [
        String(record.opportunity_id || record.opportunity_number || ""),
        documentId,
      ]));
      const matches = new Map();
      (searchV2Config.broader_program_fits || []).forEach(entry => {
        const supported = new Set(entry.supported_query_concepts || []);
        const required = entry.required_query_concepts || [];
        if (!required.every(conceptId => scientificConcepts.includes(conceptId))) return;
        if (scientificConcepts.some(conceptId => !supported.has(conceptId))) return;
        const documentId = recordById.get(String(entry.parent_id || ""));
        if (!Number.isInteger(documentId)) return;
        matches.set(documentId, entry);
      });
      return matches;
    }

    function termsWithinWindow(documentId, terms, maximumSpan) {
      const required = [...new Set((terms || []).filter(Boolean))];
      const span = Math.max(required.length, Number(maximumSpan) || required.length);
      if (!required.length) return false;
      const tokens = documentPhraseTokens[documentId];
      for (let start = 0; start < tokens.length; start += 1) {
        if (!required.includes(tokens[start])) continue;
        const present = new Set(tokens.slice(start, start + span));
        if (required.every(term => present.has(term))) return true;
      }
      return false;
    }

    function score(
      query,
      {
        semantic = true,
        coverage = true,
        context = "",
        minimumCoverage: requestedMinimumCoverage = null,
        evidence: collectEvidence = false,
        candidateIndexes = null,
      } = {},
    ) {
      if (fieldedRankingEnabled) {
        return scoreFielded(query, {
          coverage,
          context,
          minimumCoverage: requestedMinimumCoverage,
          evidence: collectEvidence,
          candidateIndexes,
        });
      }
      const groups = expandedGroups(query, { context });
      const scopeMatches = authoritativeScopeMatches(groups);
      const broaderFitMatches = designatedBroaderFitMatches(groups);
      const shortMinimum = Number(searchV2Config?.primary_admission?.concise_query_minimum_groups || 2);
      const shortMaximum = Number(searchV2Config?.primary_admission?.concise_query_maximum_groups || 5);
      const shortCompleteCoverage = searchV2
        && coverage
        && groups.length >= shortMinimum
        && groups.length <= shortMaximum;
      const strictSubstantiveCoverage = shortCompleteCoverage
        && searchV2Config?.primary_admission?.require_complete_substantive_intent !== false;
      const strictBroadGrounding = strictSubstantiveCoverage;
      const strictEvidenceGroupIndexes = groups.flatMap((group, index) => (
        group.strictEvidence === true ? [index] : []
      ));
      const scores = new Float64Array(documentCount);
      const broaderScores = new Float64Array(documentCount);
      const evidenceTiers = new Uint8Array(documentCount);
      const lexicalScores = new Float64Array(documentCount);
      const discoveryScores = new Float64Array(documentCount);
      const semanticScores = new Float64Array(documentCount);
      const lexicalCoverage = new Uint16Array(documentCount);
      const semanticCoverage = new Uint16Array(documentCount);
      const requiredGroupCoverage = new Uint8Array(documentCount);
      const alwaysRequiredCoverage = new Uint8Array(documentCount);
      const sourceGroundedCoverage = new Uint8Array(documentCount);
      const sourceGroundedRelationshipCoverage = new Uint8Array(documentCount);
      const criticalMineralSubsetCoverage = new Uint8Array(documentCount);
      const lexicalGroupMatches = searchV2
        ? Array.from({ length: documentCount }, () => new Set())
        : null;
      const substantiveGroupMatches = strictSubstantiveCoverage
        ? Array.from({ length: documentCount }, () => new Set())
        : null;
      const substantiveTermsByDocument = strictSubstantiveCoverage
        ? Array.from({ length: documentCount }, () => (
            Array.from({ length: groups.length }, () => new Set())
          ))
        : null;
      const adjacentGroupMatches = strictSubstantiveCoverage
        ? Array.from({ length: documentCount }, () => new Set())
        : null;
      const adjacentTermsByDocument = strictSubstantiveCoverage
        ? Array.from({ length: documentCount }, () => (
            Array.from({ length: groups.length }, () => new Set())
          ))
        : null;
      const broadGroundedGroupMatches = strictBroadGrounding && catalogRole === "parent"
        ? Array.from({ length: documentCount }, () => new Set())
        : null;
      const fuzzyTerms = new Map();
      const inferredTopics = new Map();
      const exactPhraseDocuments = new Set();
      const evidence = collectEvidence
        ? Array.from({ length: documentCount }, () => ({
          schemaVersion: evidenceSchemaVersion,
          groups: [],
          authoritativeScope: null,
          sourceGroundedScope: null,
          exactPhrase: false,
          exactTitlePhrase: false,
          exactOpportunityNumber: false,
          trigrams: [],
        }))
        : null;
      const currentnessRejectedIndexes = searchV2
        ? records.flatMap((record, index) => staleUndatedOpportunity(record) ? [index] : [])
        : [];
      const currentnessRejected = new Set(currentnessRejectedIndexes);

      groups.forEach((group, groupIndex) => {
        const groupDocuments = new Set();
        const groupEvidence = new Map();
        const groupLexicalScores = new Map();
        const groupMatchedTerms = (collectEvidence || group.saturateConcept || strictSubstantiveCoverage || searchV2)
          ? new Map()
          : null;
        group.terms.forEach(({ term: queryTerm, weight: queryWeight }) => {
          const queryTermDocuments = new Set();
          resolveTerm(queryTerm, {
            exactOnly: group.exactIndexedAcronym === true && queryTerm === group.source,
          }).forEach(resolution => {
            // Fuzzy recovery is for the text the user entered. Controlled
            // synonyms and scientific variants must match their indexed form
            // instead of drifting through a second, implicit expansion.
            if (queryTerm !== group.source && resolution.kind !== "exact") return;
            const values = postings[resolution.term];
            const documentFrequency = values.length / 2;
            const inverseFrequency = Math.log(
              1 + ((documentCount - documentFrequency + .5) / (documentFrequency + .5)),
            );
            const termWeight = queryWeight * resolution.weight;
            if (resolution.kind === "fuzzy") {
              if (!fuzzyTerms.has(group.source)) fuzzyTerms.set(group.source, new Set());
              fuzzyTerms.get(group.source).add(resolution.term);
            }
            for (let cursor = 0; cursor < values.length; cursor += 2) {
              const documentId = values[cursor];
              const frequency = values[cursor + 1];
              const denominator = frequency
                + K1 * (1 - B + B * (lengths[documentId] / averageLength));
              const contribution = termWeight * inverseFrequency
                * ((frequency * (K1 + 1)) / denominator);
              groupLexicalScores.set(
                documentId,
                (groupLexicalScores.get(documentId) || 0) + contribution,
              );
              if (groupMatchedTerms) {
                if (!groupMatchedTerms.has(documentId)) groupMatchedTerms.set(documentId, new Map());
                const matches = groupMatchedTerms.get(documentId);
                matches.set(
                  resolution.term,
                  (matches.get(resolution.term) || 0) + contribution,
                );
              }
              queryTermDocuments.add(documentId);
            }
          });
          queryTermDocuments.forEach(documentId => {
            groupEvidence.set(documentId, (groupEvidence.get(documentId) || 0) + 1);
          });
        });
        const requiredEvidence = Number(group.minimumEvidence || 0)
          || (group.terms.length >= 6 ? 2 : 1);
        groupLexicalScores.forEach((value, documentId) => {
          discoveryScores[documentId] += value;
          if (!strictSubstantiveCoverage) return;
          const matchedTerms = [...(groupMatchedTerms?.get(documentId) || new Map()).keys()];
          const matchedFields = fieldsForTerms(documentId, matchedTerms)
            .filter(field => field.admissionEligible);
          const eligibleMatchedTerms = new Set(matchedFields.flatMap(field => field.matchedTerms));
          if (
            Number(groupEvidence.get(documentId) || 0) < requiredEvidence
            || eligibleMatchedTerms.size < requiredEvidence
          ) return;
          adjacentGroupMatches[documentId].add(groupIndex);
          matchedFields.forEach(field => field.matchedTerms.forEach(term => (
            adjacentTermsByDocument[documentId][groupIndex].add(term)
          )));
        });
        const evidenceAlternatives = Array.isArray(group.evidenceAlternatives)
          ? group.evidenceAlternatives
          : [];
        const evidencePhrases = Array.isArray(group.evidencePhrases)
          ? group.evidencePhrases.map(value => queryApi.tokenize(value).join(" ")).filter(Boolean)
          : [];
        const evidenceWindows = Array.isArray(group.evidenceWindows)
          ? group.evidenceWindows.filter(item => Array.isArray(item?.terms))
          : [];
        groupEvidence.forEach((evidence, documentId) => {
          if (evidence < requiredEvidence) return;
          if (searchV2 && group.evidencePolicy === "source_grounded_only") return;
          const protectedEvidence = searchV2 && group.evidencePolicy === "protected_rare_earth"
            ? protectedRareEarthEvidence(documentId)
            : null;
          const aiEvidence = searchV2 && group.evidencePolicy === "protected_ai"
            ? protectedAiEvidence(documentId)
            : null;
          const pfasEvidence = searchV2 && group.evidencePolicy === "protected_pfas"
            ? protectedPfasEvidence(documentId)
            : null;
          const aiSecurityEvidence = searchV2 && group.evidencePolicy === "protected_ai_security"
            ? protectedAiSecurityEvidence(documentId, group)
            : null;
          const highTemperatureCompositeEvidence = searchV2 && group.evidencePolicy === "protected_high_temperature_composites"
            ? protectedHighTemperatureCompositeEvidence(documentId)
            : null;
          const hypersonicEvidence = searchV2 && group.evidencePolicy === "protected_hypersonic"
            ? protectedHypersonicEvidence(documentId)
            : null;
          const separationEvidence = searchV2 && group.evidencePolicy === "technical_separation"
            ? technicalSeparationEvidence(documentId)
            : null;
          const compoundEvidence = searchV2 && group.evidencePolicy === "controlled_compound"
            ? controlledCompoundEvidence(documentId, group.evidencePhrases)
            : null;
          if (
            searchV2
            && group.evidencePolicy === "protected_rare_earth"
            && !protectedEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "protected_ai"
            && !aiEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "protected_pfas"
            && !pfasEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "protected_ai_security"
            && !aiSecurityEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "protected_high_temperature_composites"
            && !highTemperatureCompositeEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "protected_hypersonic"
            && !hypersonicEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "technical_separation"
            && !separationEvidence
          ) return;
          if (
            searchV2
            && group.evidencePolicy === "controlled_compound"
            && !compoundEvidence
          ) return;
          if (searchV2) {
            const matchedTerms = [...(groupMatchedTerms?.get(documentId) || new Map()).keys()];
            const hasAdmissionEligibleField = fieldsForTerms(documentId, matchedTerms)
              .some(item => item.admissionEligible);
            if (!hasAdmissionEligibleField) return;
            if (
              group.exactIndexedAcronym === true
              && group.expansion?.kind !== "contextual_acronym"
              && !exactShortAcronymEvidence(documentId, group.source)
            ) return;
          }
          const evidenceChecks = [];
          if (evidenceAlternatives.length && !protectedEvidence && !aiEvidence && !pfasEvidence) {
            evidenceChecks.push(evidenceAlternatives.some(alternative =>
              alternative.every(term => exactDocuments(term).has(documentId))
            ));
          }
          if (evidencePhrases.length) {
            evidenceChecks.push(evidencePhrases.some(value =>
              (` ${documentPhraseText[documentId]} `).includes(` ${value} `)
            ));
          }
          if (evidenceWindows.length) {
            evidenceChecks.push(evidenceWindows.some(item =>
              termsWithinWindow(documentId, item.terms, item.maximumSpan)
            ));
          }
          if (
            evidenceChecks.length
            && (group.evidenceMode === "any"
              ? !evidenceChecks.some(Boolean)
              : !evidenceChecks.every(Boolean))
          ) return;
          groupDocuments.add(documentId);
        });
        groupDocuments.forEach(documentId => {
          if (strictSubstantiveCoverage) {
            const matchedTerms = [...(groupMatchedTerms?.get(documentId) || new Map()).keys()];
            const matchedFields = fieldsForTerms(documentId, matchedTerms);
            if (matchedFields.some(field => field.admissionEligible)) {
              substantiveGroupMatches[documentId].add(groupIndex);
              matchedFields.filter(field => field.admissionEligible).forEach(field => {
                field.matchedTerms.forEach(term => (
                  substantiveTermsByDocument[documentId][groupIndex].add(term)
                ));
              });
            }
            if (
              strictBroadGrounding
              && catalogRole === "parent"
            ) {
              const groundedTerms = new Set(matchedFields.flatMap(field => (
                field.field === "parent_title" || field.field === "parent_description"
                  ? field.matchedTerms
                  : []
              )));
              if (groundedTerms.size >= requiredEvidence) {
                broadGroundedGroupMatches[documentId].add(groupIndex);
              }
            }
          }
          const rawContribution = groupLexicalScores.get(documentId) || 0;
          const termContributions = [...(groupMatchedTerms?.get(documentId) || new Map()).values()]
            .sort((left, right) => right - left);
          const contribution = searchV2 && group.saturateConcept && termContributions.length
            ? termContributions[0] + (.35 * (termContributions[1] || 0))
            : rawContribution;
          lexicalScores[documentId] += contribution;
          lexicalCoverage[documentId] += 1;
          if (lexicalGroupMatches) lexicalGroupMatches[documentId].add(groupIndex);
          if (group.requiredUnlessTopic) requiredGroupCoverage[documentId] += 1;
          if (group.requiredAlways) alwaysRequiredCoverage[documentId] += 1;
          if (collectEvidence) {
            const protectedEvidence = searchV2 && group.evidencePolicy === "protected_rare_earth"
              ? protectedRareEarthEvidence(documentId)
              : null;
            evidence[documentId].groups.push({
              source: group.source,
              conceptId: group.conceptId || "",
              role: group.role || "",
              evidencePath: "explicit_evidence",
              contribution,
              rawContribution,
              saturationApplied: contribution !== rawContribution,
              protectedEvidence,
              matchedTermContributions: [...(groupMatchedTerms.get(documentId) || new Map())]
                .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
                .map(([term, termContribution]) => ({
                  term,
                  contribution: termContribution,
                  fields: fieldsForTerms(documentId, [term]),
                })),
            });
            evidence[documentId].groups.at(-1).matchedTerms = evidence[
              documentId
            ].groups.at(-1).matchedTermContributions.map(item => item.term);
            evidence[documentId].groups.at(-1).matchedDisplayTerms = evidence[
              documentId
            ].groups.at(-1).matchedTerms.map(term => displayTerm(documentId, term));
          }
        });

        if (!semantic) return;
        const topics = inferTopics(groupDocuments);
        topics.forEach(item => {
          inferredTopics.set(
            item.topic,
            Math.max(item.confidence, inferredTopics.get(item.topic) || 0),
          );
        });
        const semanticGroupScores = new Map();
        topics.forEach(({ topic, confidence }) => {
          const topicScore = 2.6 * confidence;
          (topicDocuments.get(topic) || []).forEach(documentId => {
            semanticGroupScores.set(
              documentId,
              Math.max(topicScore, semanticGroupScores.get(documentId) || 0),
            );
          });
        });
        semanticGroupScores.forEach((value, documentId) => {
          semanticScores[documentId] += value;
          if (!groupDocuments.has(documentId)) semanticCoverage[documentId] += 1;
        });
      });

      // Iteration 3 source signatures verify compound and morphological intent
      // only against publication-eligible parent/child fields. They may add a
      // deterministic discovery score, but generic topics, agency fields, and
      // citation text are deliberately absent from this path.
      if (searchV2 && strictSubstantiveCoverage) {
        records.forEach((_record, documentId) => {
          if (
            discoveryScores[documentId] + semanticScores[documentId] <= 0
            && !scopeMatches.has(documentId)
          ) return;
          groups.forEach((group, groupIndex) => {
            if (substantiveGroupMatches[documentId].has(groupIndex)) return;
            const match = sourceGroundedRoleEvidence(documentId, group);
            if (!match) return;
            const contribution = .35;
            if (!lexicalGroupMatches[documentId].has(groupIndex)) {
              lexicalGroupMatches[documentId].add(groupIndex);
              lexicalCoverage[documentId] += 1;
              lexicalScores[documentId] += contribution;
              if (group.requiredUnlessTopic) requiredGroupCoverage[documentId] += 1;
              if (group.requiredAlways) alwaysRequiredCoverage[documentId] += 1;
            }
            substantiveGroupMatches[documentId].add(groupIndex);
            sourceGroundedCoverage[documentId] += 1;
            if (match.relationship) sourceGroundedRelationshipCoverage[documentId] += 1;
            if (match.relationship?.id === "rare-earth-subset-to-critical-mineral-scope") {
              criticalMineralSubsetCoverage[documentId] = 1;
            }
            match.matchedTerms.forEach(term => (
              substantiveTermsByDocument[documentId][groupIndex].add(term)
            ));
            if (
              strictBroadGrounding
              && catalogRole === "parent"
              && ["parent_title", "parent_description", "authoritative_document_scope"].includes(match.field)
            ) broadGroundedGroupMatches[documentId].add(groupIndex);
            if (!collectEvidence) return;
            evidence[documentId].groups.push({
              source: group.source,
              conceptId: group.conceptId || "",
              role: group.role || "",
              evidencePath: "source_grounded_scope",
              contribution,
              rawContribution: contribution,
              saturationApplied: false,
              sourceRelationship: match.relationship,
              matchedTerms: match.matchedTerms,
              matchedDisplayTerms: match.matchedTerms.map(term => displayTerm(documentId, term) || term),
              matchedTermContributions: match.matchedTerms.map(term => ({
                term,
                contribution: contribution / Math.max(1, match.matchedTerms.length),
                fields: [{ field: match.field, matchedTerms: [term], admissionEligible: true }],
              })),
            });
            if (!evidence[documentId].sourceGroundedScope) {
              evidence[documentId].sourceGroundedScope = {
                path: "source_grounded_scope",
                groups: [],
              };
            }
            evidence[documentId].sourceGroundedScope.groups.push({
              conceptId: group.conceptId || "",
              role: group.role || "",
              field: match.field,
              matchedTerms: match.matchedTerms,
              relationship: match.relationship,
              provenance: match.provenance,
            });
          });
        });
      }

      const scopeEntailmentScore = Math.max(
        .01,
        Number(searchV2Config?.scope_entailment_score || 1),
      );
      scopeMatches.forEach((match, documentId) => {
        groups.forEach((group, groupIndex) => {
          if (!match.coveredConcepts.includes(group.conceptId)) return;
          if (!lexicalGroupMatches[documentId].has(groupIndex)) {
            lexicalGroupMatches[documentId].add(groupIndex);
            lexicalCoverage[documentId] += 1;
            if (group.requiredUnlessTopic) requiredGroupCoverage[documentId] += 1;
            if (group.requiredAlways) alwaysRequiredCoverage[documentId] += 1;
          }
          if (strictSubstantiveCoverage) {
            substantiveGroupMatches[documentId].add(groupIndex);
            if (strictBroadGrounding && catalogRole === "parent") {
              broadGroundedGroupMatches[documentId].add(groupIndex);
            }
          }
        });
        lexicalScores[documentId] += scopeEntailmentScore;
        if (collectEvidence) {
          evidence[documentId].authoritativeScope = {
            path: "authoritative_scope_entailment",
            entailmentId: match.id,
            parentId: String(match.parent_id),
            coveredConcepts: match.coveredConcepts,
            authoritativeScope: match.authoritative_scope,
            controlledRelationships: match.controlled_relationships || [],
            contribution: scopeEntailmentScore,
          };
        }
      });

      const phrase = queryApi.normalizeText(query).trim().toLowerCase();
      if (phrase.length >= 4) {
        records.forEach((record, documentId) => {
          const title = String(record.title || "").toLowerCase();
          const opportunityNumber = String(record.opportunity_number || "").toLowerCase();
          if (title.includes(phrase)) {
            lexicalScores[documentId] += title === phrase
              ? exactTitleMatchBoost
              : titlePhraseBoost;
            exactPhraseDocuments.add(documentId);
            if (collectEvidence) {
              evidence[documentId].exactPhrase = true;
              evidence[documentId].exactTitlePhrase = true;
            }
          }
          if (opportunityNumber === phrase) {
            lexicalScores[documentId] += opportunityNumberBoost;
            exactPhraseDocuments.add(documentId);
            if (collectEvidence) {
              evidence[documentId].exactPhrase = true;
              evidence[documentId].exactOpportunityNumber = true;
            }
          }
        });
      }

      const phraseTokens = queryApi.tokenize(query).slice(0, 12);
      const queryTrigrams = [];
      for (let index = 0; index + 3 <= phraseTokens.length; index += 1) {
        const terms = phraseTokens.slice(index, index + 3);
        if (terms.every(term => term.length >= 3)) queryTrigrams.push(terms.join(" "));
      }
      if (queryTrigrams.length) {
        records.forEach((_record, documentId) => {
          queryTrigrams.forEach(trigram => {
            if (documentPhraseText[documentId].includes(trigram)) {
              lexicalScores[documentId] += trigramPhraseBoost;
              if (collectEvidence) evidence[documentId].trigrams.push(trigram);
            }
          });
        });
      }

      // Candidate admission is lexical. Topic inference may rerank a record
      // that already matches the query, but it must never manufacture a large
      // result set from a coarse catalog topic. Concise two- to four-concept
      // searches require complete substantive coverage; longer natural-language
      // searches retain the forgiving 60% concept floor.
      const hasExplicitMinimumCoverage = requestedMinimumCoverage !== null
        && requestedMinimumCoverage !== undefined
        && Number.isFinite(Number(requestedMinimumCoverage));
      const explicitMinimumCoverage = hasExplicitMinimumCoverage
        ? Math.max(0, Math.min(groups.length, Math.floor(Number(requestedMinimumCoverage))))
        : null;
      const protectedCompleteCoverage = searchV2 && groups.some(group => (
        group.evidencePolicy === "protected_rare_earth"
      ));
      const minimumCoverage = explicitMinimumCoverage ?? (
        !groups.length
          ? 0
          : !coverage
            ? 1
            : protectedCompleteCoverage
              ? groups.length
              : shortCompleteCoverage
              ? groups.length
              : Math.ceil(groups.length * .6)
      );
      const requiredGroups = groups.filter(group => group.requiredUnlessTopic);
      const alwaysRequiredGroups = groups.filter(group => group.requiredAlways);
      function hasCoherentNarrativeIntent(documentId, { allowOneMissing = false } = {}) {
        if (!strictSubstantiveCoverage) return true;
        const intentGroups = allowOneMissing
          ? substantiveTermsByDocument[documentId].filter(terms => terms.size > 0)
          : substantiveTermsByDocument[documentId];
        if (allowOneMissing && intentGroups.length < groups.length - 1) return false;
        if (documentNarrativeSentences[documentId].some(sentence => (
          intentGroups.every(terms => (
            terms.size > 0 && [...terms].some(term => sentence.has(term))
          ))
        ))) return true;
        const tokens = documentNarrativeTokens[documentId];
        // Keep concise scientific intent inside one bounded source passage.
        // A wider window admitted unrelated uses from neighboring program
        // examples (for example, a generic verb in one sentence and an
        // application term several sentences later).
        const maximumSpan = 48;
        for (let start = 0; start < tokens.length; start += 1) {
          const window = new Set(tokens.slice(start, start + maximumSpan).flatMap(token => [
            token,
            ...token.split("-").filter(part => part.length > 1),
          ]));
          if (intentGroups.every(terms => (
            terms.size > 0 && [...terms].some(term => window.has(term))
          ))) return true;
        }
        return false;
      }
      function hasCoherentAdjacentIntent(documentId) {
        if (!strictSubstantiveCoverage) return false;
        const termsByGroup = adjacentTermsByDocument[documentId];
        if (documentNarrativeSentences[documentId].some(sentence => (
          termsByGroup.every(terms => (
            terms.size > 0 && [...terms].some(term => sentence.has(term))
          ))
        ))) return true;
        const tokens = documentNarrativeTokens[documentId];
        const maximumSpan = 48;
        for (let start = 0; start < tokens.length; start += 1) {
          const window = new Set(tokens.slice(start, start + maximumSpan).flatMap(token => [
            token,
            ...token.split("-").filter(part => part.length > 1),
          ]));
          if (termsByGroup.every(terms => (
            terms.size > 0 && [...terms].some(term => window.has(term))
          ))) return true;
        }
        return false;
      }
      function hasBoundedCriticalMineralOperationScope(documentId) {
        const values = (documentScopeFields[documentId] || []).map(field => field.value);
        const sourceUnits = [...values, values.join(" ")];
        return sourceUnits.some(value => {
          const tokens = scopeTokens(value);
          for (let index = 0; index + 1 < tokens.length; index += 1) {
            if (tokens[index] !== "critical" || !tokens[index + 1].startsWith("mineral")) continue;
            const start = Math.max(0, index - 50);
            const windowTokens = tokens.slice(start, index + 52);
            const window = windowTokens.join(" ");
            if (!/\b(?:separat|extract|process|recover|recycl|refin|leach|purif|hydrometallurg)/.test(window)) continue;
            if (!/\b(?:research|science|scientific|chemical|engineering|technology|technologies|method|program|support|fund|advance|develop|resource recovery)\b/.test(window)) continue;
            if (/\b(?:align\w* with|executive order|commercial diplomacy|workforce training|trade facilitation|are critical to)\b/.test(window)) continue;
            return true;
          }
          return false;
        });
      }
      for (let documentId = 0; documentId < documentCount; documentId += 1) {
        const combined = lexicalScores[documentId] + semanticScores[documentId];
        const admission = collectEvidence ? {
          admitted: false,
          classification: "rejected",
          evidenceTier: PRIMARY_EVIDENCE_TIER.weak_discovery,
          reason: "no_scoring_evidence",
          lexicalCoverage: lexicalCoverage[documentId],
          semanticCoverage: semanticCoverage[documentId],
          requiredGroupCoverage: requiredGroupCoverage[documentId],
          alwaysRequiredCoverage: alwaysRequiredCoverage[documentId],
          substantiveCoverage: substantiveGroupMatches?.[documentId]?.size || 0,
          broadGroundedCoverage: broadGroundedGroupMatches?.[documentId]?.size || 0,
          lexicalScore: lexicalScores[documentId],
          semanticScore: semanticScores[documentId],
          finalScore: 0,
          admittedBy: [],
          rankedBy: [],
          fieldContributions: [],
        } : null;
        if (collectEvidence) evidence[documentId].admission = admission;
        if (combined <= 0) continue;
        if (currentnessRejected.has(documentId)) {
          if (admission) admission.reason = "stale_undated_opportunity";
          continue;
        }
        if (broaderFitMatches.has(documentId) && !scopeMatches.has(documentId)) {
          const broader = broaderFitMatches.get(documentId);
          broaderScores[documentId] = combined;
          evidenceTiers[documentId] = PRIMARY_EVIDENCE_TIER.broader_program;
          if (admission) {
            admission.classification = "broader_program_fit";
            admission.evidenceTier = PRIMARY_EVIDENCE_TIER.broader_program;
            admission.reason = "explicitly_designated_broader_program_fit";
            admission.finalScore = combined;
            admission.admittedBy = [{
              path: "broader_program_fit",
              fitId: broader.id,
              publishedScope: broader.published_scope,
              rationale: broader.rationale,
            }];
          }
          continue;
        }
        const missingSubstantiveDimensions = strictSubstantiveCoverage
          ? groups.length - substantiveGroupMatches[documentId].size
          : groups.length;
        const missingSubstantiveIndexes = strictSubstantiveCoverage
          ? groups.flatMap((_group, groupIndex) => (
              substantiveGroupMatches[documentId].has(groupIndex) ? [] : [groupIndex]
            ))
          : [];
        const adjacentMissingEvidence = missingSubstantiveIndexes.length === 1
          ? sourceGroundedRoleEvidence(
              documentId,
              groups[missingSubstantiveIndexes[0]],
              { allowAdjacent: true },
            )
          : null;
        const boundedIncompleteBroaderFit = strictSubstantiveCoverage
          && !scopeMatches.has(documentId)
          && groups.length === 3
          && missingSubstantiveDimensions === 1
          && substantiveGroupMatches[documentId].size >= 2
          && groups[missingSubstantiveIndexes[0]]?.role === "program_form_or_intervention"
          && hasCoherentNarrativeIntent(documentId, { allowOneMissing: true });
        const sourceAdjacentBroaderFit = strictSubstantiveCoverage
          && !scopeMatches.has(documentId)
          && groups.length >= 2
          && missingSubstantiveDimensions === 1
          && adjacentGroupMatches[documentId].size === groups.length
          && Boolean(adjacentMissingEvidence)
          && hasCoherentAdjacentIntent(documentId);
        if (sourceAdjacentBroaderFit || boundedIncompleteBroaderFit) {
          broaderScores[documentId] = combined;
          evidenceTiers[documentId] = PRIMARY_EVIDENCE_TIER.broader_program;
          if (admission) {
            const missingConcepts = groups.flatMap((group, groupIndex) => (
              substantiveGroupMatches[documentId].has(groupIndex)
                ? []
                : [group.conceptId || group.source]
            ));
            admission.classification = "broader_program_fit";
            admission.evidenceTier = PRIMARY_EVIDENCE_TIER.broader_program;
            admission.reason = "source_grounded_adjacent_scope";
            admission.finalScore = combined;
            admission.admittedBy = [{
              path: "source_grounded_adjacent_scope",
              establishedConcepts: groups.flatMap((group, groupIndex) => (
                substantiveGroupMatches[documentId].has(groupIndex)
                  ? [group.conceptId || group.source]
                  : []
              )),
              missingConcepts,
              fields: adjacentMissingEvidence ? [adjacentMissingEvidence.field] : [],
              matchedTerms: adjacentMissingEvidence?.matchedTerms || [],
              relationship: adjacentMissingEvidence?.relationship || null,
              statement: "One major query dimension is adjacent but not established by published scope.",
            }];
          }
          continue;
        }
        const effectiveCoverage = lexicalCoverage[documentId] + (.55 * semanticCoverage[documentId]);
        if (
          minimumCoverage
          && lexicalCoverage[documentId] < minimumCoverage
          && !exactPhraseDocuments.has(documentId)
        ) {
          if (admission) admission.reason = "insufficient_lexical_coverage";
          continue;
        }
        if (
          strictSubstantiveCoverage
          && substantiveGroupMatches[documentId].size < groups.length
          && !exactPhraseDocuments.has(documentId)
          && !scopeMatches.has(documentId)
          && !(
            strictBroadGrounding
            && catalogRole === "parent"
            && BROAD_OPPORTUNITY_RE.test(`${records[documentId].title || ""} ${records[documentId].opportunity_number || ""}`)
            && strictEvidenceGroupIndexes.length > 0
            && strictEvidenceGroupIndexes.every(groupIndex => (
              broadGroundedGroupMatches[documentId].has(groupIndex)
            ))
            && lexicalCoverage[documentId] >= groups.length
          )
        ) {
          if (admission) admission.reason = "insufficient_substantive_query_coverage";
          continue;
        }
        if (
          strictSubstantiveCoverage
          && !hasCoherentNarrativeIntent(documentId)
          && !exactPhraseDocuments.has(documentId)
          && !scopeMatches.has(documentId)
          && !(
            strictBroadGrounding
            && catalogRole === "parent"
            && BROAD_OPPORTUNITY_RE.test(`${records[documentId].title || ""} ${records[documentId].opportunity_number || ""}`)
            && strictEvidenceGroupIndexes.length > 0
            && strictEvidenceGroupIndexes.every(groupIndex => (
              broadGroundedGroupMatches[documentId].has(groupIndex)
            ))
            && lexicalCoverage[documentId] >= groups.length
          )
        ) {
          if (admission) admission.reason = "incoherent_substantive_query_evidence";
          continue;
        }
        if (
          (criticalMineralSubsetCoverage[documentId]
            || groups.some(group => group.conceptId === "critical-minerals"))
          && groups.some(group => group.conceptId === "separations")
          && !hasBoundedCriticalMineralOperationScope(documentId)
          && !scopeMatches.has(documentId)
        ) {
          if (admission) admission.reason = "unbounded_critical_mineral_scope";
          continue;
        }
        if (
          strictBroadGrounding
          && catalogRole === "parent"
          && BROAD_OPPORTUNITY_RE.test(`${records[documentId].title || ""} ${records[documentId].opportunity_number || ""}`)
          && strictEvidenceGroupIndexes.some(groupIndex => (
            !broadGroundedGroupMatches[documentId].has(groupIndex)
          ))
          && !exactPhraseDocuments.has(documentId)
          && !scopeMatches.has(documentId)
        ) {
          if (admission) admission.reason = "ungrounded_broad_program_scope";
          continue;
        }
        if (
          requiredGroups.length
          && requiredGroupCoverage[documentId] < requiredGroups.length
          && !requiredGroups.every(group =>
            documentTopics[documentId].includes(group.requiredUnlessTopic)
          )
        ) {
          if (admission) admission.reason = "missing_required_concept_evidence";
          continue;
        }
        if (
          alwaysRequiredGroups.length
          && alwaysRequiredCoverage[documentId] < alwaysRequiredGroups.length
        ) {
          if (admission) admission.reason = "missing_always_required_concept_evidence";
          continue;
        }
        const coverageRatio = groups.length
          ? Math.min(1, effectiveCoverage / groups.length)
          : 0;
        scores[documentId] = combined * (.78 + (.5 * coverageRatio));
        if (admission) {
          admission.admitted = true;
          const scopeEvidence = evidence[documentId].authoritativeScope;
          const sourceScopeEvidence = evidence[documentId].sourceGroundedScope;
          admission.reason = scopeEvidence
            ? "authoritative_scope_entailment"
            : sourceScopeEvidence
              ? "source_grounded_scope_entailment"
            : exactPhraseDocuments.has(documentId)
              ? "exact_phrase_or_identifier"
              : "explicit_evidence";
          admission.finalScore = scores[documentId];
          admission.classification = "primary";
          admission.evidenceTier = scopeEvidence
            ? PRIMARY_EVIDENCE_TIER.authoritative_scope
            : sourceGroundedRelationshipCoverage[documentId] > 0
              ? PRIMARY_EVIDENCE_TIER.authoritative_scope
            : exactPhraseDocuments.has(documentId) || catalogRole === "child"
              ? PRIMARY_EVIDENCE_TIER.exact_or_child
              : PRIMARY_EVIDENCE_TIER.contextual_parent;
          admission.admittedBy = scopeEvidence
            ? [{
                path: "authoritative_scope_entailment",
                entailmentId: scopeEvidence.entailmentId,
                coveredConcepts: scopeEvidence.coveredConcepts,
                authoritativeScope: scopeEvidence.authoritativeScope,
                controlledRelationships: scopeEvidence.controlledRelationships,
              }]
            : sourceScopeEvidence
              ? [
                  ...sourceScopeEvidence.groups.map(group => ({
                    path: "source_grounded_scope",
                    conceptId: group.conceptId,
                    role: group.role,
                    fields: [group.field],
                    matchedTerms: group.matchedTerms,
                    relationship: group.relationship,
                    provenance: group.provenance,
                  })),
                  ...evidence[documentId].groups
                    .filter(group => (
                      group.evidencePath === "explicit_evidence"
                      && !sourceScopeEvidence.groups.some(sourceGroup => (
                        sourceGroup.conceptId === group.conceptId
                      ))
                    ))
                    .map(group => ({
                      path: "explicit_evidence",
                      conceptId: group.conceptId,
                      role: group.role,
                      fields: [...new Set(group.matchedTermContributions.flatMap(term => (
                        term.fields.filter(field => field.admissionEligible).map(field => field.field)
                      )))],
                    })),
                ]
            : evidence[documentId].groups.map(group => ({
                path: group.evidencePath,
                conceptId: group.conceptId,
                role: group.role,
                fields: [...new Set(group.matchedTermContributions.flatMap(term => (
                  term.fields.filter(field => field.admissionEligible).map(field => field.field)
                )))],
              }));
          admission.rankedBy = [
            ...(scopeEvidence ? [{ type: "authoritative_scope", contribution: scopeEvidence.contribution }] : []),
            ...(sourceScopeEvidence ? [{
              type: "source_grounded_scope",
              contribution: .35 * sourceGroundedCoverage[documentId],
            }] : []),
            ...evidence[documentId].groups.map(group => ({
              type: "lexical_concept",
              conceptId: group.conceptId,
              contribution: group.contribution,
            })),
            ...(semanticScores[documentId] > 0
              ? [{ type: "topic_rerank", contribution: semanticScores[documentId] }]
              : []),
            ...(exactPhraseDocuments.has(documentId)
              ? [{ type: "exact_phrase_or_identifier" }]
              : []),
          ];
          admission.fieldContributions = evidence[documentId].groups.flatMap(group => (
            group.matchedTermContributions.flatMap(term => term.fields.map(field => ({
              conceptId: group.conceptId,
              term: term.term,
              field: field.field,
              admissionEligible: field.admissionEligible,
              aggregateTermContribution: term.contribution,
            })))
          ));
        }
        evidenceTiers[documentId] = evidence?.[documentId]?.admission?.evidenceTier || (
          scopeMatches.has(documentId)
            ? PRIMARY_EVIDENCE_TIER.authoritative_scope
            : sourceGroundedRelationshipCoverage[documentId] > 0
              ? PRIMARY_EVIDENCE_TIER.authoritative_scope
            : exactPhraseDocuments.has(documentId) || catalogRole === "child"
              ? PRIMARY_EVIDENCE_TIER.exact_or_child
              : PRIMARY_EVIDENCE_TIER.contextual_parent
        );
      }

      const discoveredCandidateCount = Array.from(discoveryScores, (value, documentId) => (
        value + semanticScores[documentId] > 0 ? 1 : 0
      )).reduce((sum, value) => sum + value, 0);
      const admittedPrimaryCount = Array.from(scores).filter(value => value > 0).length;
      const admittedBroaderCount = Array.from(broaderScores).filter(value => value > 0).length;
      const rejectedPartialIntentCount = collectEvidence
        ? evidence.filter(item => [
            "insufficient_lexical_coverage",
            "insufficient_substantive_query_coverage",
            "incoherent_substantive_query_evidence",
            "missing_required_concept_evidence",
            "missing_always_required_concept_evidence",
            "ungrounded_broad_program_scope",
            "unbounded_critical_mineral_scope",
          ].includes(item?.admission?.reason)).length
        : Math.max(0, discoveredCandidateCount - admittedPrimaryCount);

      return {
        scores,
        broaderScores,
        evidenceTiers,
        lexicalScores,
        discoveryScores,
        semanticScores,
        lexicalCoverage,
        semanticCoverage,
        evidence,
        queryGroups: groups.map((group, index) => ({
          index,
          conceptId: group.conceptId || group.source,
          role: group.role || "",
          source: group.source,
        })),
        verificationGroupIndexes: substantiveGroupMatches
          ? substantiveGroupMatches.map(matches => [...matches].sort((left, right) => left - right))
          : null,
        currentnessRejectedIndexes,
        hasTerms: groups.length > 0,
        diagnostics: {
          queryGroups: groups.length,
          minimumCoverage,
          fuzzyTerms: [...fuzzyTerms].map(([source, terms]) => ({
            source,
            matches: [...terms],
          })),
          inferredTopics: [...inferredTopics]
            .sort((left, right) => right[1] - left[1])
            .slice(0, 5)
            .map(([topic]) => topic),
          acronymExpansions: groups
            .filter(group => group.expansion?.kind === "contextual_acronym")
            .map(group => ({
              source: group.source,
              phrase: group.expansion.phrase,
              confidence: group.expansion.confidence,
              basis: group.expansion.basis,
            })),
          searchV2: {
            enabled: searchV2,
            contractVersion: searchV2Config?.contract_version || null,
            evidenceSchemaVersion,
            catalogRole,
          protectedCompleteCoverage,
          shortCompleteCoverage,
          strictSubstantiveCoverage,
          strictBroadGrounding,
            authoritativeScopeEntailments: [...scopeMatches.values()].map(match => ({
              id: match.id,
              parentId: String(match.parent_id),
              coveredConcepts: match.coveredConcepts,
            })),
            queryPlan: groups.map(group => ({
              conceptId: group.conceptId || "",
              role: group.role || "",
              required: group.required === true || group.requiredAlways === true,
              source: group.source,
              evidencePolicy: group.evidencePolicy || "",
              strictEvidence: group.strictEvidence === true,
            })),
            discovery: {
              internalCandidateCount: discoveredCandidateCount,
              visiblePrimaryCount: admittedPrimaryCount,
              broaderFitCount: admittedBroaderCount,
              rejectedPartialIntentCount,
              rejectedCurrentnessCount: currentnessRejectedIndexes.length,
              admissionCounts: {
                exactOrChild: Array.from(evidenceTiers).filter(value => value === PRIMARY_EVIDENCE_TIER.exact_or_child).length,
                authoritativeScope: Array.from(evidenceTiers).filter(value => value === PRIMARY_EVIDENCE_TIER.authoritative_scope).length,
                contextualParent: Array.from(evidenceTiers).filter(value => value === PRIMARY_EVIDENCE_TIER.contextual_parent).length,
              },
            },
          },
          scoringConfiguration: {
            exactTitleMatchBoost,
            titlePhraseBoost,
            opportunityNumberBoost,
            trigramPhraseBoost,
          },
        },
      };
    }

    return Object.freeze({ score, resolveTerm, expandGroups: expandedGroups });
  }

  globalThis.FUNDING_RETRIEVAL = Object.freeze({
    contractVersion: RETRIEVAL_API_CONTRACT_VERSION,
    boundedDamerauLevenshtein,
    create,
    createChildCatalog,
    nonFundingReason,
    positiveScale,
    recordIsArchived,
    recordIsCurrent,
    rollupRankedRecords,
    rollupScores,
    validateSearchV2Configuration,
  });
})();
