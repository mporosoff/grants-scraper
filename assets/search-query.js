(() => {
  "use strict";

  // Keep this deliberately conservative. Ambiguous shorthand (for example,
  // AD, AM, or AR) creates worse search results than leaving it literal.
  const QUERY_ALIASES = Object.freeze({
    co2: "carbon dioxide",
    ccs: "carbon capture",
    ccus: "carbon capture",
    ghg: "greenhouse",
    h2: "hydrogen",
    ch4: "methane",
    n2o: "nitrous nitrogen",
    nox: "nitrogen",
    sox: "sulfur",
    "pm2.5": "particulate",
    voc: "volatile organic",
    dac: "air capture",
    ldes: "energy storage",
    pv: "photovoltaic",
    ev: "electric vehicle",
    ai: "artificial intelligence",
    ml: "machine learning",
    llm: "generative",
    hpc: "computing",
    iot: "internet",
    gis: "geographic geospatial",
    uav: "aerial drone",
    qis: "quantum",
    crispr: "gene editing",
    mrna: "rna",
    ptsd: "post-traumatic",
    tbi: "traumatic brain injury",
    sud: "substance use disorder",
    oud: "opioid use disorder",
    als: "amyotrophic lateral sclerosis",
    adhd: "attention deficit",
    ckd: "kidney",
    copd: "pulmonary",
  });

  const STOP_WORDS = new Set([
    "a", "about", "after", "all", "also", "an", "and", "any", "application",
    "applications", "are", "as", "at", "award", "awards", "be", "been",
    "being", "by", "can", "for", "from", "funding", "grant", "grants", "has",
    "have", "in", "including", "is", "it", "may", "more", "must", "new", "not",
    "of", "on", "opportunities", "opportunity", "or", "other", "program",
    "project", "projects", "proposal", "proposals", "research", "shall", "should",
    "support", "than", "that", "the", "their", "these", "this", "through", "to",
    "under", "use", "using", "was", "we", "which", "will", "with",
  ]);

  function normalizeText(value) {
    // NFKC turns commonly pasted scientific subscripts into searchable ASCII:
    // CO₂ -> CO2, H₂ -> H2, and PM₂.₅ -> PM2.5.
    return String(value || "").normalize("NFKC");
  }

  function normalizeToken(raw) {
    let token = raw.toLowerCase().replace(/^[.-]+|[.-]+$/g, "");
    if (token.length > 5 && token.endsWith("ies")) token = `${token.slice(0, -3)}y`;
    else if (token.length > 5 && token.endsWith("ing")) token = token.slice(0, -3);
    else if (token.length > 4 && token.endsWith("ed")) token = token.slice(0, -2);
    else if (token.length > 4 && token.endsWith("s") && !token.endsWith("ss")) token = token.slice(0, -1);
    return token;
  }

  function tokenize(value) {
    const raw = normalizeText(value).toLowerCase().match(/[a-z0-9][a-z0-9+.-]{1,}/g) || [];
    return raw
      .map(normalizeToken)
      .filter(token => token.length > 1 && !STOP_WORDS.has(token));
  }

  function expandTerms(value, hasIndexedTerm = () => false) {
    const directTerms = [...new Set(tokenize(value))];
    const weightedTerms = new Map(directTerms.map(term => [term, 1]));

    directTerms.forEach(term => {
      // Literal matches are preferable to broader long-form expansions. The
      // glossary is a fallback for abbreviations absent from this catalog.
      if (hasIndexedTerm(term)) return;
      const expansion = QUERY_ALIASES[term];
      if (!expansion) return;
      tokenize(expansion).forEach(expanded => {
        if (!weightedTerms.has(expanded)) weightedTerms.set(expanded, .86);
      });
    });

    return [...weightedTerms].map(([term, weight]) => ({ term, weight }));
  }

  globalThis.FUNDING_SEARCH_QUERY = Object.freeze({
    aliases: QUERY_ALIASES,
    normalizeText,
    tokenize,
    expandTerms,
  });
})();
