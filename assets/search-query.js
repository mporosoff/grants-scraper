(() => {
  "use strict";

  // PFAS notices are often written around the problem being addressed instead
  // of naming an individual compound. These terms keep searches useful against
  // catalogs that describe water contamination and remediation but omit PFAS.
  const PFAS_CONCEPT = "persistent contaminant contamination pollution remediation groundwater drinking wastewater water treatment purification";
  const RARE_EARTH_CONCEPT = "rare earth element lanthanide scandium yttrium critical mineral extraction separation recovery recycling processing";

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
    ree: RARE_EARTH_CONCEPT,
    rees: RARE_EARTH_CONCEPT,
    lanthanide: RARE_EARTH_CONCEPT,
    lanthanides: RARE_EARTH_CONCEPT,
    ionic: "ion electrolyte solvent salt extraction separation",
    extraction: "separation recovery recycling processing",
    pfas: PFAS_CONCEPT,
    pfoa: PFAS_CONCEPT,
    pfos: PFAS_CONCEPT,
    pfhx: PFAS_CONCEPT,
    pfna: PFAS_CONCEPT,
    pfbs: PFAS_CONCEPT,
    pfba: PFAS_CONCEPT,
    pfhxa: PFAS_CONCEPT,
    pfpea: PFAS_CONCEPT,
    pfhpa: PFAS_CONCEPT,
    pfda: PFAS_CONCEPT,
    pfuna: PFAS_CONCEPT,
    pfdoa: PFAS_CONCEPT,
    pfca: PFAS_CONCEPT,
    pfsa: PFAS_CONCEPT,
    fosa: PFAS_CONCEPT,
    "hfpo-da": PFAS_CONCEPT,
    afff: PFAS_CONCEPT,
    perfluoroalkyl: PFAS_CONCEPT,
    polyfluoroalkyl: PFAS_CONCEPT,
    perfluorinat: PFAS_CONCEPT,
    polyfluorinat: PFAS_CONCEPT,
    perfluorooctanoic: PFAS_CONCEPT,
    perfluorooctane: PFAS_CONCEPT,
    fluorochemical: PFAS_CONCEPT,
    fluorosurfactant: PFAS_CONCEPT,
    forever: PFAS_CONCEPT,
  });

  // Always add environmental context for this family. AFFF, for example, can
  // occur literally in an unrelated notice even though it commonly refers to
  // PFAS-containing aqueous film-forming foam.
  const ALWAYS_EXPAND_ALIASES = new Set(
    Object.keys(QUERY_ALIASES).filter(term => (
      QUERY_ALIASES[term] === PFAS_CONCEPT
      || QUERY_ALIASES[term] === RARE_EARTH_CONCEPT
      || ["ionic", "extraction"].includes(term)
    )),
  );

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

  // The catalog index intentionally keeps its compact, deterministic stemmer.
  // These query-side alternatives cover common scientific irregulars without
  // forcing a full catalog rebuild or making every search depend on a glossary.
  const QUERY_VARIANTS = Object.freeze({
    analyse: ["analysi"],
    analysi: ["analyse"],
    bacterium: ["bacteria"],
    bacteria: ["bacterium"],
    child: ["children"],
    children: ["child"],
    criterion: ["criteria"],
    criteria: ["criterion"],
    datum: ["data"],
    fungus: ["fungi"],
    fungi: ["fungus"],
    index: ["indicy", "indice"],
    indicy: ["index"],
    indice: ["index"],
    man: ["men"],
    men: ["man"],
    matrix: ["matrice"],
    matrice: ["matrix"],
    medium: ["media"],
    mouse: ["mice"],
    mice: ["mouse"],
    phenomenon: ["phenomena"],
    phenomena: ["phenomenon"],
    woman: ["women"],
    women: ["woman"],
  });

  const MAX_ACRONYM_LENGTH = 8;
  const MAX_ACRONYM_ATTEMPTS = 12;
  const MAX_ACRONYM_SOURCE_CHARS = 8_000;
  const ACRONYM_WORD_RE = /[a-z][a-z0-9'-]*/gi;

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

  function acronymWords(value) {
    return (normalizeText(value).match(ACRONYM_WORD_RE) || [])
      .map(word => word.toLowerCase().replace(/^[-']+|[-']+$/g, ""))
      .filter(word => word.length > 1 && !STOP_WORDS.has(word));
  }

  function scanAcronymPhrases(value, acronym) {
    const letters = String(acronym || "").toLowerCase().replace(/[^a-z]/g, "");
    if (letters.length < 3 || letters.length > MAX_ACRONYM_LENGTH) return [];
    const phrases = new Map();
    normalizeText(value).slice(0, MAX_ACRONYM_SOURCE_CHARS)
      .split(/[.!?;:\n\r]+/)
      .forEach(sentence => {
        const words = acronymWords(sentence);
        if (words.length < letters.length) return;
        for (let start = 0; start + letters.length <= words.length; start += 1) {
          const window = words.slice(start, start + letters.length);
          if (window.some((word, index) => word[0] !== letters[index])) continue;
          if (window.filter(word => word.length >= 4).length < 2) continue;
          const phrase = window.join(" ");
          const entry = phrases.get(phrase) || { phrase, words: window, occurrences: 0 };
          entry.occurrences += 1;
          phrases.set(phrase, entry);
        }
      });
    return [...phrases.values()];
  }

  function acronymSourceText(record) {
    return [
      record?.title || "",
      String(record?.description || "").slice(0, MAX_ACRONYM_SOURCE_CHARS),
      String(record?.document_search_text || "").slice(0, 2_500),
      ...(record?.topic_areas || []),
      ...(record?.disciplines || []),
    ].join(". ");
  }

  function createAcronymResolver(records = []) {
    const catalog = Array.isArray(records) ? records : [];
    const candidateCache = new Map();

    function catalogCandidates(acronym) {
      if (candidateCache.has(acronym)) return candidateCache.get(acronym);
      const candidates = new Map();
      const upper = acronym.toUpperCase();
      catalog.forEach((record, documentId) => {
        const source = acronymSourceText(record);
        const perDocument = new Set();
        scanAcronymPhrases(source, acronym).forEach(item => {
          const entry = candidates.get(item.phrase) || {
            phrase: item.phrase,
            words: item.words,
            documents: new Set(),
            occurrences: 0,
            defined: false,
          };
          entry.documents.add(documentId);
          entry.occurrences += item.occurrences;
          const escaped = item.phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          entry.defined = entry.defined || new RegExp(
            `(?:${escaped}\\s*\\(\\s*${upper}\\s*\\)|${upper}\\s*\\(\\s*${escaped}\\s*\\))`,
            "i",
          ).test(source);
          candidates.set(item.phrase, entry);
          perDocument.add(item.phrase);
        });
      });
      const values = [...candidates.values()];
      candidateCache.set(acronym, values);
      return values;
    }

    function resolve(acronym, { context = "", uppercase = false } = {}) {
      const normalized = String(acronym || "").toLowerCase().replace(/[^a-z]/g, "");
      if (normalized.length < 3 || normalized.length > MAX_ACRONYM_LENGTH) return null;
      const contextItems = scanAcronymPhrases(context, normalized);
      const contextCandidates = new Set(contextItems.map(item => item.phrase));
      const contextTerms = new Set(acronymWords(context));
      // A research summary, CV, or publication title can define a new acronym
      // before that exact long form appears in the funding catalog. Add those
      // local phrases as candidates; normal result scoring still requires the
      // resulting long-form terms to occur in an opportunity.
      const combinedCandidates = new Map(
        catalogCandidates(normalized).map(candidate => [candidate.phrase, candidate]),
      );
      contextItems.forEach(item => {
        if (combinedCandidates.has(item.phrase)) return;
        combinedCandidates.set(item.phrase, {
          phrase: item.phrase,
          words: item.words,
          documents: new Set(),
          occurrences: item.occurrences,
          defined: false,
        });
      });
      const ranked = [...combinedCandidates.values()].map(candidate => {
        const exactContext = contextCandidates.has(candidate.phrase);
        const overlapCount = candidate.words.filter(word => contextTerms.has(word)).length;
        const overlap = overlapCount / candidate.words.length;
        const documentCount = candidate.documents.size;
        let confidence = 0;
        let basis = "";
        if (exactContext) {
          confidence = .99;
          basis = "researcher context";
        } else if (candidate.defined) {
          confidence = .95;
          basis = "catalog definition";
        } else if (overlapCount >= 2 && overlap >= .5) {
          confidence = Math.min(.94, .82 + (.1 * overlap) + Math.min(.02, documentCount * .01));
          basis = "catalog and researcher context";
        } else if (uppercase && documentCount >= 3) {
          confidence = Math.min(.9, .82 + Math.min(.08, documentCount * .015));
          basis = "repeated catalog phrase";
        }
        return { ...candidate, confidence, basis, exactContext, overlap };
      }).filter(candidate => candidate.confidence >= .84)
        .sort((left, right) =>
          right.confidence - left.confidence
          || Number(right.exactContext) - Number(left.exactContext)
          || right.documents.size - left.documents.size
          || right.occurrences - left.occurrences
          || left.phrase.localeCompare(right.phrase)
        );
      const best = ranked[0];
      if (!best) return null;
      const runnerUp = ranked[1];
      if (
        runnerUp
        && runnerUp.phrase !== best.phrase
        && runnerUp.confidence >= best.confidence - .035
        && runnerUp.exactContext === best.exactContext
      ) return null;
      return {
        acronym: normalized,
        phrase: best.phrase,
        confidence: best.confidence,
        basis: best.basis,
        catalogDocuments: best.documents.size,
      };
    }

    return Object.freeze({ resolve });
  }

  function variants(term) {
    return [term, ...(QUERY_VARIANTS[term] || [])];
  }

  function expandGroups(value, hasIndexedTerm = () => false, options = {}) {
    const directTerms = [...new Set(tokenize(value))];
    const directTermSet = new Set(directTerms);
    const uppercaseTerms = new Set(
      (normalizeText(value).match(/\b[A-Z][A-Z0-9]{2,8}s?\b/g) || [])
        .map(normalizeToken),
    );
    let acronymAttempts = 0;
    return directTerms.map(term => {
      const weightedTerms = new Map([[term, 1]]);
      variants(term).slice(1).forEach(variant => weightedTerms.set(variant, .94));
      const indexed = hasIndexedTerm(term);
      const looksLikeAcronym = /^[a-z]{3,8}$/.test(term)
        && (uppercaseTerms.has(term) || !/[aeiou]/.test(term));
      const acronymExpansion = looksLikeAcronym
        && options.acronymResolver?.resolve
        && acronymAttempts < MAX_ACRONYM_ATTEMPTS
        ? options.acronymResolver.resolve(term, {
            context: options.context || "",
            uppercase: uppercaseTerms.has(term),
          })
        : null;
      if (looksLikeAcronym) acronymAttempts += 1;
      // Literal matches are preferable to broader long-form expansions. The
      // glossary is a fallback for abbreviations absent from this catalog.
      if (indexed && !ALWAYS_EXPAND_ALIASES.has(term) && !acronymExpansion) {
        return {
          source: term,
          terms: [...weightedTerms].map(([expanded, weight]) => ({ term: expanded, weight })),
        };
      }
      const expansion = acronymExpansion?.phrase || QUERY_ALIASES[term];
      const expansionWeight = acronymExpansion ? .9 : .86;
      tokenize(expansion || "").forEach(expanded => {
        // A term the user explicitly supplied belongs to its own coverage
        // group; do not let one literal occurrence satisfy two concepts.
        if (expanded !== term && directTermSet.has(expanded)) return;
        if (!weightedTerms.has(expanded)) weightedTerms.set(expanded, expansionWeight);
      });
      return {
        source: term,
        terms: [...weightedTerms].map(([expanded, weight]) => ({ term: expanded, weight })),
        minimumEvidence: acronymExpansion ? 2 : undefined,
        expansion: acronymExpansion ? {
          kind: "contextual_acronym",
          phrase: acronymExpansion.phrase,
          confidence: acronymExpansion.confidence,
          basis: acronymExpansion.basis,
        } : null,
      };
    });
  }

  function expandTerms(value, hasIndexedTerm = () => false, options = {}) {
    const weightedTerms = new Map();
    expandGroups(value, hasIndexedTerm, options).forEach(group => {
      group.terms.forEach(({ term, weight }) => {
        weightedTerms.set(term, Math.max(weight, weightedTerms.get(term) || 0));
      });
    });

    return [...weightedTerms].map(([term, weight]) => ({ term, weight }));
  }

  globalThis.FUNDING_SEARCH_QUERY = Object.freeze({
    aliases: QUERY_ALIASES,
    normalizeText,
    tokenize,
    variants,
    createAcronymResolver,
    scanAcronymPhrases,
    expandGroups,
    expandTerms,
  });
})();
