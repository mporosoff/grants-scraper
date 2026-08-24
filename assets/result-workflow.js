(() => {
  "use strict";

  const WORKFLOW_TIERS = new Set(["strong", "potential", "ai_candidate"]);

  function workflowTier(match) {
    const tier = String(match?.workflowTier || "strong").toLowerCase();
    return WORKFLOW_TIERS.has(tier) ? tier : "strong";
  }

  function workflowTierLabel(match) {
    return {
      strong: "Strong",
      potential: "Potential",
      ai_candidate: "AI-candidate",
    }[workflowTier(match)];
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

  function buildCandidateMatchMap({
    candidates,
    baseMatches,
    idForMatch,
    limit = 32,
  }) {
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
      if (!baseMatch) candidate.workflowTier = "ai_candidate";
      candidateMatches.set(id, baseMatch || candidate);
      if (candidateMatches.size >= boundedLimit) break;
    }
    return candidateMatches;
  }

  function resolveCandidateMatches({
    baseMatches,
    candidateMatches,
    ids,
    idForMatch,
  }) {
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
    workflowTier,
    workflowTierLabel,
    potentialEvidence,
    buildCandidateMatchMap,
    resolveCandidateMatches,
    matchMetadata,
    retryDelaySeconds,
  });
})();
