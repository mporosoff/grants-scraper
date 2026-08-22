(() => {
  "use strict";

  const K1 = 1.2;
  const B = .75;
  const PREFIX_LIMIT = 12;
  const FUZZY_LIMIT = 6;

  function compareIds(left, right) {
    return String(left).localeCompare(String(right), undefined, {
      numeric: true,
      sensitivity: "base",
    });
  }

  function positiveScale(values) {
    const positive = Array.from(values || [])
      .filter(value => Number(value) > 0)
      .map(Number)
      .sort((left, right) => left - right);
    if (!positive.length) return 1;
    return positive[Math.max(0, Math.ceil(positive.length * .9) - 1)];
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

    childRecords.forEach((record, index) => {
      if (!(Number(childDirect?.scores?.[index]) > 0)) return;
      const parentId = String(record.parent_id || "");
      if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
      childrenByParent.get(parentId).push({
        id: String(record.subtopic_id || record.opportunity_id),
        record,
        raw: childRaw[index],
        normalized: childRaw[index] / childScale,
        directEvidence: childDirect?.evidence?.[index] || null,
        profileEvidence: childProfile?.evidence?.[index] || null,
      });
    });
    childrenByParent.forEach(children => children.sort((left, right) => (
      right.normalized - left.normalized || compareIds(left.id, right.id)
    )));

    const rows = [];
    parentRecords.forEach((record, index) => {
      const id = String(record.opportunity_id || record.opportunity_number || "");
      const matchingChildren = childrenByParent.get(id) || [];
      const parentAdmitted = Number(parentDirect?.scores?.[index]) > 0;
      if (!parentAdmitted && !matchingChildren.length) return;
      const parentNormalized = parentRaw[index] / parentScale;
      const childNormalized = matchingChildren[0]?.normalized || 0;
      const childDroveMatch = childNormalized > parentNormalized;
      const relevance = Math.max(parentNormalized, childNormalized);
      const eligibility = Number(eligibilityBonuses?.[index] || 0) / parentScale;
      rows.push({
        id,
        record,
        score: relevance + eligibility,
        relevance,
        eligibility,
        parentAdmitted,
        parentRaw: parentRaw[index],
        parentNormalized,
        childDroveMatch,
        parentDirectEvidence: parentDirect?.evidence?.[index] || null,
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
    const documentTopics = records.map(record => [
      ...new Set((record.topic_areas || []).filter(Boolean).map(String)),
    ]);
    const documentPhraseTokens = records.map(record => queryApi.tokenize([
      record.title || "",
      record.opportunity_number || "",
      String(record.description || "").slice(0, 5_000),
      String(record.document_search_text || "").slice(0, 16_000),
      ...(record.topic_areas || []),
    ].join(" ")));
    const documentPhraseText = documentPhraseTokens.map(terms => terms.join(" "));
    const topicDocuments = new Map();

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

    function resolveTerm(term) {
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

    function expandedGroups(query, { context = "" } = {}) {
      return queryApi.expandGroups(
        query,
        term => Boolean(postings[term]),
        { acronymResolver, context },
      );
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
      } = {},
    ) {
      const groups = expandedGroups(query, { context });
      const scores = new Float64Array(documentCount);
      const lexicalScores = new Float64Array(documentCount);
      const semanticScores = new Float64Array(documentCount);
      const lexicalCoverage = new Uint16Array(documentCount);
      const semanticCoverage = new Uint16Array(documentCount);
      const requiredGroupCoverage = new Uint8Array(documentCount);
      const alwaysRequiredCoverage = new Uint8Array(documentCount);
      const fuzzyTerms = new Map();
      const inferredTopics = new Map();
      const exactPhraseDocuments = new Set();
      const evidence = collectEvidence
        ? Array.from({ length: documentCount }, () => ({
          groups: [],
          exactPhrase: false,
          exactTitlePhrase: false,
          exactOpportunityNumber: false,
          trigrams: [],
        }))
        : null;

      groups.forEach(group => {
        const groupDocuments = new Set();
        const groupEvidence = new Map();
        const groupLexicalScores = new Map();
        const groupMatchedTerms = collectEvidence ? new Map() : null;
        group.terms.forEach(({ term: queryTerm, weight: queryWeight }) => {
          const queryTermDocuments = new Set();
          resolveTerm(queryTerm).forEach(resolution => {
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
              if (collectEvidence) {
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
          const evidenceChecks = [];
          if (evidenceAlternatives.length) {
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
          lexicalScores[documentId] += groupLexicalScores.get(documentId) || 0;
          lexicalCoverage[documentId] += 1;
          if (group.requiredUnlessTopic) requiredGroupCoverage[documentId] += 1;
          if (group.requiredAlways) alwaysRequiredCoverage[documentId] += 1;
          if (collectEvidence) {
            evidence[documentId].groups.push({
              source: group.source,
              contribution: groupLexicalScores.get(documentId) || 0,
              matchedTermContributions: [...(groupMatchedTerms.get(documentId) || new Map())]
                .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
                .map(([term, contribution]) => ({ term, contribution })),
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
      // result set from a coarse catalog topic. Two-concept searches use AND;
      // longer natural-language searches use a forgiving 60% concept floor.
      const hasExplicitMinimumCoverage = requestedMinimumCoverage !== null
        && requestedMinimumCoverage !== undefined
        && Number.isFinite(Number(requestedMinimumCoverage));
      const explicitMinimumCoverage = hasExplicitMinimumCoverage
        ? Math.max(0, Math.min(groups.length, Math.floor(Number(requestedMinimumCoverage))))
        : null;
      const minimumCoverage = explicitMinimumCoverage ?? (
        !groups.length
          ? 0
          : !coverage
            ? 1
            : groups.length <= 2
              ? groups.length
              : Math.ceil(groups.length * .6)
      );
      const requiredGroups = groups.filter(group => group.requiredUnlessTopic);
      const alwaysRequiredGroups = groups.filter(group => group.requiredAlways);
      for (let documentId = 0; documentId < documentCount; documentId += 1) {
        const combined = lexicalScores[documentId] + semanticScores[documentId];
        const admission = collectEvidence ? {
          admitted: false,
          reason: "no_scoring_evidence",
          lexicalCoverage: lexicalCoverage[documentId],
          semanticCoverage: semanticCoverage[documentId],
          requiredGroupCoverage: requiredGroupCoverage[documentId],
          alwaysRequiredCoverage: alwaysRequiredCoverage[documentId],
          lexicalScore: lexicalScores[documentId],
          semanticScore: semanticScores[documentId],
          finalScore: 0,
        } : null;
        if (collectEvidence) evidence[documentId].admission = admission;
        if (combined <= 0) continue;
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
          admission.reason = exactPhraseDocuments.has(documentId)
            ? "exact_phrase_or_identifier"
            : "lexical_concept_coverage";
          admission.finalScore = scores[documentId];
        }
      }

      return {
        scores,
        lexicalScores,
        semanticScores,
        lexicalCoverage,
        semanticCoverage,
        evidence,
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
    boundedDamerauLevenshtein,
    create,
    createChildCatalog,
    positiveScale,
    rollupRankedRecords,
    rollupScores,
  });
})();
