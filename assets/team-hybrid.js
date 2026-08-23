(() => {
  "use strict";

  const MAX_QUERY_PHRASES = 24;
  const MAX_QUERY_CHARS = 560;

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
    ]);
  }

  function buildTeamQuery(profiles, themes = []) {
    const members = Array.isArray(profiles) ? profiles : [];
    const phrases = unique((themes || []).map(theme => theme?.label || theme));
    const memberTerms = members.map(profileTerms);
    const maximumDepth = Math.max(0, ...memberTerms.map(terms => terms.length));
    for (let depth = 0; depth < maximumDepth && phrases.length < MAX_QUERY_PHRASES; depth += 1) {
      memberTerms.forEach(terms => {
        if (phrases.length < MAX_QUERY_PHRASES && terms[depth]) phrases.push(terms[depth]);
      });
    }
    let query = unique(phrases).join("; ");
    if (query.length > MAX_QUERY_CHARS) query = query.slice(0, MAX_QUERY_CHARS).replace(/[;, ]+$/, "");
    return query;
  }

  function teamSignature(profiles, themes = []) {
    const memberPart = (profiles || []).map(profile => [
      clean(profile?.name).toLowerCase(),
      ...profileTerms(profile).map(term => term.toLowerCase()),
    ].join("|")).join("||");
    const themePart = unique((themes || []).map(theme => theme?.label || theme))
      .map(theme => theme.toLowerCase()).sort().join("|");
    return `${memberPart}::${themePart}`;
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

  function createCoordinator({ client } = {}) {
    const searches = new Map();
    let requestCount = 0;

    function run({ profiles = [], themes = [] } = {}) {
      const signature = teamSignature(profiles, themes);
      if (searches.has(signature)) return searches.get(signature);
      const query = buildTeamQuery(profiles, themes);
      if (!client?.configured || !query) {
        const fallback = Promise.resolve(Object.freeze({
          signature,
          query,
          rankById: new Map(),
          enhanced: false,
          fallback: true,
          diagnostics: {},
        }));
        searches.set(signature, fallback);
        return fallback;
      }
      requestCount += 1;
      const pending = client.search(query, { context: query }).then(outcome => {
        const rankById = new Map((outcome?.parents || []).map((parent, index) => [
          clean(parent.parent_id),
          Number(parent.hybrid_rank || index + 1),
        ]).filter(([id]) => id));
        return Object.freeze({
          signature,
          query,
          rankById,
          enhanced: true,
          fallback: false,
          diagnostics: outcome?.diagnostics || {},
        });
      }).catch(error => Object.freeze({
        signature,
        query,
        rankById: new Map(),
        enhanced: false,
        fallback: true,
        error: error?.code || "hybrid_unavailable",
        diagnostics: {},
      }));
      searches.set(signature, pending);
      return pending;
    }

    return Object.freeze({
      run,
      requestCount: () => requestCount,
      clear: () => searches.clear(),
    });
  }

  globalThis.FUNDING_TEAM_HYBRID = Object.freeze({
    MAX_QUERY_PHRASES,
    MAX_QUERY_CHARS,
    buildTeamQuery,
    teamSignature,
    applyHybridRanking,
    createCoordinator,
  });
})();
