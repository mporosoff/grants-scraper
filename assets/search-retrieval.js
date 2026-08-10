(() => {
  "use strict";

  const K1 = 1.2;
  const B = .75;
  const PREFIX_LIMIT = 12;
  const FUZZY_LIMIT = 6;

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

  function create(catalog, queryApi) {
    const index = catalog?.search_index;
    const records = catalog?.opportunities || [];
    if (!index?.postings || !queryApi?.expandGroups) {
      throw new Error("Hybrid search could not initialize because its catalog helpers are missing.");
    }

    const postings = index.postings;
    const indexTerms = Object.keys(postings);
    const documentCount = index.document_count;
    const lengths = index.document_lengths;
    const averageLength = index.average_document_length || 1;
    const termsByLength = new Map();
    const resolutionCache = new Map();
    const documentTopics = records.map(record => [
      ...new Set((record.topic_areas || []).filter(Boolean).map(String)),
    ]);
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

    function score(query, { semantic = true, coverage = true } = {}) {
      const groups = queryApi.expandGroups(query, term => Boolean(postings[term]));
      const scores = new Float64Array(documentCount);
      const lexicalScores = new Float64Array(documentCount);
      const semanticScores = new Float64Array(documentCount);
      const lexicalCoverage = new Uint16Array(documentCount);
      const semanticCoverage = new Uint16Array(documentCount);
      const fuzzyTerms = new Map();
      const inferredTopics = new Map();
      const exactPhraseDocuments = new Set();

      groups.forEach(group => {
        const groupDocuments = new Set();
        const groupEvidence = new Map();
        group.terms.forEach(({ term: queryTerm, weight: queryWeight }) => {
          const queryTermDocuments = new Set();
          resolveTerm(queryTerm).forEach(resolution => {
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
              lexicalScores[documentId] += termWeight * inverseFrequency
                * ((frequency * (K1 + 1)) / denominator);
              queryTermDocuments.add(documentId);
            }
          });
          queryTermDocuments.forEach(documentId => {
            groupEvidence.set(documentId, (groupEvidence.get(documentId) || 0) + 1);
          });
        });
        const requiredEvidence = group.terms.length >= 6 ? 2 : 1;
        groupEvidence.forEach((evidence, documentId) => {
          if (evidence >= requiredEvidence) groupDocuments.add(documentId);
        });
        groupDocuments.forEach(documentId => { lexicalCoverage[documentId] += 1; });

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
            lexicalScores[documentId] += title === phrase ? 24 : 12;
            exactPhraseDocuments.add(documentId);
          }
          if (opportunityNumber === phrase) {
            lexicalScores[documentId] += 50;
            exactPhraseDocuments.add(documentId);
          }
        });
      }

      const minimumCoverage = coverage && groups.length >= 3
        ? Math.max(2, Math.ceil(groups.length * .38))
        : 0;
      for (let documentId = 0; documentId < documentCount; documentId += 1) {
        const combined = lexicalScores[documentId] + semanticScores[documentId];
        if (combined <= 0) continue;
        const effectiveCoverage = lexicalCoverage[documentId] + (.55 * semanticCoverage[documentId]);
        if (
          minimumCoverage
          && lexicalCoverage[documentId] < minimumCoverage
          && !exactPhraseDocuments.has(documentId)
        ) continue;
        const coverageRatio = groups.length
          ? Math.min(1, effectiveCoverage / groups.length)
          : 0;
        scores[documentId] = combined * (.78 + (.5 * coverageRatio));
      }

      return {
        scores,
        lexicalScores,
        semanticScores,
        lexicalCoverage,
        semanticCoverage,
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
        },
      };
    }

    return Object.freeze({ score, resolveTerm });
  }

  globalThis.FUNDING_RETRIEVAL = Object.freeze({
    boundedDamerauLevenshtein,
    create,
  });
})();
