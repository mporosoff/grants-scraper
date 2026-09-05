(() => {
  "use strict";

  const MAX_QUERY_PHRASES = 24;
  const SHARED_MAX_QUERY_CHARS = Math.max(
    1,
    Number(globalThis.FUNDING_HYBRID_SEARCH?.MAX_QUERY_CHARS || 500),
  );
  const CANONICALIZATION_SAFETY_CHARS = 24;
  const MAX_QUERY_CHARS = Math.max(1, SHARED_MAX_QUERY_CHARS - CANONICALIZATION_SAFETY_CHARS);

  function clean(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function unique(values) {
    const seen = new Set();
    return values.flatMap(value => {
      const text = clean(value);
      const key = text.toLowerCase();
      if (!text || seen.has(key)) return [];
      seen.add(key);
      return [text];
    });
  }

  function profileTerms(profile) {
    return unique([
      ...(profile?.key_terms || []),
      ...(profile?.keywords || []),
      ...(profile?.capability_phrases || []),
    ]);
  }

  function buildTeamQuery(profiles, themes = []) {
    const members = Array.isArray(profiles) ? profiles : [];
    const memberTerms = members.map(profileTerms);
    const maximumDepth = Math.max(0, ...memberTerms.map(terms => terms.length));
    const candidates = [];
    const perMemberBudget = Math.floor((MAX_QUERY_CHARS - Math.max(0, members.length - 1) * 2) / Math.max(1, members.length));
    const anchors = memberTerms.map(terms => terms.find(term => term.length <= perMemberBudget));
    if (anchors.some(anchor => !anchor)) return "";
    candidates.push(...anchors);
    candidates.push(...unique((themes || []).map(theme => theme?.label || theme)));
    for (let depth = 0; depth < maximumDepth; depth += 1) {
      memberTerms.forEach(terms => {
        if (terms[depth]) candidates.push(terms[depth]);
      });
    }
    const phrases = [];
    unique(candidates).some(phrase => {
      if (phrases.length >= MAX_QUERY_PHRASES) return true;
      const next = [...phrases, phrase].join("; ");
      if (next.length <= MAX_QUERY_CHARS) phrases.push(phrase);
      return false;
    });
    return phrases.join("; ");
  }

  function teamContext(profiles) {
    // Used only by the local acronym resolver. The shared client sends only
    // the resulting bounded scientific query to the hosted service.
    return (profiles || []).map(profile => [
      ...profileTerms(profile),
      clean(profile?.research_summary || profile?.summary),
      clean(profile?.publication_text).slice(0, 12000),
    ].filter(Boolean).join(". ")).join(". ").slice(0, 24000);
  }

  function teamSignature(profiles, themes = [], eligibleParentIds = null) {
    const memberPart = (profiles || []).map(profile => [
      clean(profile?.researcher_id || profile?.id || profile?.name),
      ...profileTerms(profile),
      clean(profile?.research_summary || profile?.summary),
      clean(profile?.publication_text).slice(0, 12000),
    ].join("|")).join("||");
    const themePart = unique((themes || []).map(theme => theme?.label || theme))
      .map(theme => theme.toLowerCase()).sort().join("|");
    const eligibility = eligibleParentIds == null ? null : [...eligibleParentIds].map(String).sort();
    return JSON.stringify([memberPart, themePart, eligibility]);
  }

  function resultId(result) {
    return clean(result?.d?.id || result?.id);
  }

  function applyHybridRanking(localResults, rankById) {
    const results = Array.isArray(localResults) ? localResults.slice() : [];
    if (!(rankById instanceof Map) || !rankById.size) return results;
    return results.map((result, localIndex) => ({
      result,
      localIndex,
      hybridRank: rankById.get(resultId(result)) || Number.POSITIVE_INFINITY,
    })).sort((left, right) =>
      left.hybridRank - right.hybridRank || left.localIndex - right.localIndex
    ).map(item => item.result);
  }

  function failureCategory(code) {
    if (["rate_limited", "budget_limited"].includes(code)) return "limited";
    if ([
      "manifest_corpus_mismatch",
      "manifest_passage_mismatch",
      "vector_hash_mismatch",
      "vector_shape_mismatch",
    ].includes(code)) return "package_mismatch";
    return "unavailable";
  }

  function createCoordinator({ client } = {}) {
    const searches = new Map();
    let requestCount = 0;
    let lastState = Object.freeze({
      enhanced: false,
      fallback: true,
      reason: "not_started",
      reason_category: "unavailable",
      request_count: 0,
      cached: false,
    });

    function run({ profiles = [], themes = [], eligibleParentIds = null } = {}) {
      const eligible = eligibleParentIds == null ? null : new Set([...eligibleParentIds].map(String));
      const signature = teamSignature(profiles, themes, eligible);
      if (searches.has(signature)) return searches.get(signature).then(outcome => {
        lastState = Object.freeze({ ...outcome, request_count: requestCount, cached: true });
        return lastState;
      });
      const query = buildTeamQuery(profiles, themes);
      if (!client?.configured || !query || eligible?.size === 0) {
        const fallback = Promise.resolve().then(() => {
          lastState = Object.freeze({
          signature,
          query,
          rankById: new Map(),
          enhanced: false,
          fallback: true,
          reason: !client?.configured ? "proxy_unconfigured" : eligible?.size === 0 ? "no_eligible_opportunities" : "empty_query",
          reason_category: "unavailable",
          request_count: requestCount,
          cached: false,
          diagnostics: {},
          });
          return lastState;
        });
        searches.set(signature, fallback);
        return fallback;
      }
      requestCount += 1;
      const pending = Promise.resolve().then(() => client.search(query, {
        context: teamContext(profiles), eligibleParentIds: eligible,
      })).then(outcome => {
        const rankById = new Map((outcome?.parents || []).map((parent, index) => [
          clean(parent.parent_id),
          Number(parent.hybrid_rank || index + 1),
        ]).filter(([id]) => id));
        lastState = Object.freeze({
          signature,
          query,
          rankById,
          enhanced: true,
          fallback: false,
          reason: "",
          reason_category: "",
          request_count: requestCount,
          cached: false,
          diagnostics: outcome?.diagnostics || {},
        });
        return lastState;
      }).catch(error => {
        const reason = error?.code || "hybrid_unavailable";
        lastState = Object.freeze({
          signature,
          query,
          rankById: new Map(),
          enhanced: false,
          fallback: true,
          reason,
          reason_category: failureCategory(reason),
          request_count: requestCount,
          cached: false,
          diagnostics: {},
        });
        return lastState;
      });
      searches.set(signature, pending);
      return pending;
    }

    return Object.freeze({
      run,
      requestCount: () => requestCount,
      state: () => lastState,
      clear: () => searches.clear(),
    });
  }

  globalThis.FUNDING_TEAM_HYBRID = Object.freeze({
    MAX_QUERY_PHRASES,
    SHARED_MAX_QUERY_CHARS,
    CANONICALIZATION_SAFETY_CHARS,
    MAX_QUERY_CHARS,
    buildTeamQuery,
    teamContext,
    teamSignature,
    applyHybridRanking,
    failureCategory,
    createCoordinator,
  });
})();
