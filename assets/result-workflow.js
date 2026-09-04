(() => {
  "use strict";

  const WORKFLOW_TIERS = new Set(["strong", "potential"]);
  const ASSESSMENT_VERDICTS = new Set(["Strong fit", "Possible fit", "Weak fit"]);
  const GENERIC_STANDALONE_PHRASES = new Set([
    "energy",
    "health",
    "innovation",
    "research",
    "science",
    "technology",
  ]);

  function workflowTier(match) {
    const tier = String(match?.workflowTier || "strong").toLowerCase();
    return WORKFLOW_TIERS.has(tier) ? tier : "strong";
  }

  function workflowTierLabel(match) {
    return workflowTier(match) === "potential" ? "Potential" : "Strong";
  }

  function potentialEvidence(match, maximum = 360) {
    if (workflowTier(match) !== "potential") return null;
    const explanation = match?.hybridExplanation;
    const excerpt = String(explanation?.excerpt || "").replace(/\s+/g, " ").trim();
    if (!excerpt) return null;
    const boundedMaximum = Math.max(80, Math.min(600, Number(maximum) || 360));
    return {
      source_field: String(explanation.source_field || "public_source_passage").slice(0, 80),
      source_label: String(explanation.source_label || "Public source passage").slice(0, 120),
      excerpt: excerpt.length <= boundedMaximum
        ? excerpt
        : `${excerpt.slice(0, boundedMaximum - 1).trim()}…`,
    };
  }

  function cloneValue(value, seen = new Map()) {
    if (!value || typeof value !== "object") return value;
    if (seen.has(value)) return seen.get(value);
    if (Array.isArray(value)) {
      const output = [];
      seen.set(value, output);
      value.forEach(item => output.push(cloneValue(item, seen)));
      return output;
    }
    const output = {};
    seen.set(value, output);
    Object.entries(value).forEach(([key, item]) => {
      output[key] = cloneValue(item, seen);
    });
    return output;
  }

  function deepFreeze(value, seen = new Set()) {
    if (!value || typeof value !== "object" || seen.has(value)) return value;
    seen.add(value);
    Object.values(value).forEach(item => deepFreeze(item, seen));
    return Object.freeze(value);
  }

  function immutableMatches(matches) {
    return deepFreeze(cloneValue(Array.isArray(matches) ? matches : []));
  }

  function captureOrdinaryBaseline({
    matches,
    strongMatches,
    potentialMatches,
    page,
    sort,
    signature,
    idForMatch,
  }) {
    const capturedMatches = immutableMatches(matches);
    const capturedStrong = immutableMatches(strongMatches);
    const capturedPotential = immutableMatches(potentialMatches);
    const ids = capturedMatches.map(match => String(idForMatch(match) || "")).filter(Boolean);
    return deepFreeze({
      signature: String(signature || ""),
      ids,
      matches: capturedMatches,
      strongMatches: capturedStrong,
      potentialMatches: capturedPotential,
      counts: {
        total: capturedMatches.length,
        strong: capturedMatches.filter(match => workflowTier(match) === "strong").length,
        potential: capturedMatches.filter(match => workflowTier(match) === "potential").length,
      },
      page: Math.max(1, Number(page) || 1),
      sort: String(sort || "relevance"),
    });
  }

  function restoreOrdinaryBaseline(baseline) {
    return {
      matches: cloneValue(baseline?.matches || []),
      strongMatches: cloneValue(baseline?.strongMatches || []),
      potentialMatches: cloneValue(baseline?.potentialMatches || []),
      page: Math.max(1, Number(baseline?.page) || 1),
      sort: String(baseline?.sort || "relevance"),
    };
  }

  function sanitizeAlternativePhrases(values, maximum = 16) {
    const limit = Math.max(0, Math.min(16, Number(maximum) || 0));
    if (!limit) return [];
    const retrievalTokenize = globalThis.FUNDING_SEARCH_QUERY?.tokenize;
    if (typeof retrievalTokenize !== "function") return [];
    const phrases = [];
    const seen = new Set();
    for (const value of Array.isArray(values) ? values : []) {
      const phrase = String(value || "")
        .replace(/[\u0000-\u001f\u007f]/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 120);
      const tokens = retrievalTokenize(phrase);
      const key = Array.isArray(tokens) ? tokens.join("\u001f") : "";
      const genericStandalone = tokens?.length === 1
        && GENERIC_STANDALONE_PHRASES.has(tokens[0]);
      if (!key || seen.has(key) || genericStandalone) continue;
      seen.add(key);
      phrases.push(phrase);
      if (phrases.length >= limit) break;
    }
    return phrases;
  }

  function collectAlternativeCandidates({
    phrases,
    retrieve,
    baselineIds = [],
    idForMatch,
    limit = 32,
  }) {
    const boundedLimit = Math.max(0, Math.min(32, Number(limit) || 0));
    if (!boundedLimit || typeof retrieve !== "function") return [];
    const ordinaryIds = new Set((baselineIds || []).map(String));
    const candidates = new Map();
    sanitizeAlternativePhrases(phrases).forEach((phrase, phraseIndex) => {
      const outcome = retrieve(phrase);
      const matches = Array.isArray(outcome) ? outcome : outcome?.matches;
      for (const match of Array.isArray(matches) ? matches : []) {
        if (workflowTier(match) !== "strong") continue;
        const id = String(idForMatch(match) || "");
        if (!id || ordinaryIds.has(id)) continue;
        const existing = candidates.get(id);
        const aiPhrases = [...new Set([...(existing?.aiPhrases || []), phrase])];
        const preferred = !existing || Number(match.score || 0) > Number(existing.score || 0)
          ? cloneValue(match)
          : cloneValue(existing);
        candidates.set(id, {
          ...preferred,
          workflowTier: "strong",
          aiIdentified: true,
          aiPhrases,
          aiPhraseOrder: Math.min(
            phraseIndex,
            Number.isInteger(existing?.aiPhraseOrder) ? existing.aiPhraseOrder : phraseIndex,
          ),
        });
      }
    });
    return [...candidates.entries()]
      .sort(([leftId, left], [rightId, right]) => (
        Number(right.score || 0) - Number(left.score || 0)
        || Number(left.aiPhraseOrder || 0) - Number(right.aiPhraseOrder || 0)
        || leftId.localeCompare(rightId, undefined, { numeric: true })
      ))
      .slice(0, boundedLimit)
      .map(([_id, match]) => match);
  }

  function selectAssessedAdditions({ candidates, assessments, idForMatch, limit = 12 }) {
    const boundedLimit = Math.max(0, Math.min(12, Number(limit) || 0));
    if (!boundedLimit) return { additions: [], assessments: new Map() };
    const candidateById = new Map((candidates || []).flatMap(match => {
      const id = String(idForMatch(match) || "");
      return id ? [[id, match]] : [];
    }));
    const accepted = new Map();
    for (const item of Array.isArray(assessments) ? assessments : []) {
      const id = String(item?.id || "");
      if (!candidateById.has(id) || accepted.has(id)) continue;
      const verdict = String(item?.verdict || "");
      if (!ASSESSMENT_VERDICTS.has(verdict)) continue;
      accepted.set(id, {
        score: Math.max(0, Math.min(100, Math.round(Number(item.score) || 0))),
        verdict,
        reason: String(item.reason || "").slice(0, 900),
        concern: String(item.concern || "").slice(0, 900),
      });
    }
    const additions = [...accepted.keys()]
      .map(id => candidateById.get(id))
      .sort((left, right) => {
        const leftId = String(idForMatch(left) || "");
        const rightId = String(idForMatch(right) || "");
        return Number(accepted.get(rightId)?.score || 0) - Number(accepted.get(leftId)?.score || 0)
          || Number(right.score || 0) - Number(left.score || 0)
          || Number(left.aiPhraseOrder || 0) - Number(right.aiPhraseOrder || 0)
          || leftId.localeCompare(rightId, undefined, { numeric: true });
      })
      .slice(0, boundedLimit)
      .map(match => deepFreeze(cloneValue(match)));
    return {
      additions,
      assessments: new Map(additions.map(match => {
        const id = String(idForMatch(match) || "");
        return [id, accepted.get(id)];
      })),
    };
  }

  function mergeAdditiveResults({ baseline, additions }) {
    const ordinary = Array.isArray(baseline?.matches) ? baseline.matches : [];
    return deepFreeze([
      ...cloneValue(additions || []),
      ...cloneValue(ordinary),
    ]);
  }

  function buildCandidateMatchMap({ candidates, baseMatches, idForMatch, limit = 32 }) {
    const boundedLimit = Math.max(0, Math.min(32, Number(limit) || 0));
    if (!boundedLimit) return new Map();
    const baseById = new Map((baseMatches || []).flatMap(match => {
      const id = String(idForMatch(match) || "");
      return id ? [[id, match]] : [];
    }));
    const candidateMatches = new Map();
    for (const candidate of candidates || []) {
      const id = String(idForMatch(candidate) || "");
      if (!id || candidateMatches.has(id)) continue;
      const baseMatch = baseById.get(id);
      candidateMatches.set(id, baseMatch || {
        ...cloneValue(candidate),
        workflowTier: "strong",
        aiIdentified: true,
      });
      if (candidateMatches.size >= boundedLimit) break;
    }
    return candidateMatches;
  }

  function resolveCandidateMatches({ baseMatches, candidateMatches, ids, idForMatch }) {
    const byId = new Map((baseMatches || []).flatMap(match => {
      const id = String(idForMatch(match) || "");
      return id ? [[id, match]] : [];
    }));
    for (const [id, match] of candidateMatches || []) byId.set(String(id), match);
    return (ids || []).map(id => byId.get(String(id))).filter(Boolean);
  }

  function matchMetadata(match) {
    return {
      workflow_tier: workflowTier(match),
      ai_identified: match?.aiIdentified === true,
      ai_discovery_phrases: match?.aiIdentified === true
        ? sanitizeAlternativePhrases(match.aiPhrases, 16)
        : [],
      potential_evidence: potentialEvidence(match),
    };
  }

  function retryDelaySeconds(retryAvailableAt, now = Date.now()) {
    return Math.max(
      0,
      Math.ceil((Number(retryAvailableAt || 0) - Number(now || 0)) / 1_000),
    );
  }

  globalThis.FUNDING_RESULT_WORKFLOW = Object.freeze({
    buildCandidateMatchMap,
    captureOrdinaryBaseline,
    collectAlternativeCandidates,
    immutableMatches,
    matchMetadata,
    mergeAdditiveResults,
    potentialEvidence,
    resolveCandidateMatches,
    restoreOrdinaryBaseline,
    retryDelaySeconds,
    sanitizeAlternativePhrases,
    selectAssessedAdditions,
    workflowTier,
    workflowTierLabel,
  });
})();
