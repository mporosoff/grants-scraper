(() => {
  "use strict";

  const DEFAULT_MAXIMUM_TERMS = 28;
  const GENERIC_PROFILE_TERMS = new Set([
    "approach", "develop", "development", "do", "include", "method",
    "project", "research", "study", "use", "using", "work",
  ]);

  function context(profile) {
    if (!profile) return "";
    return [
      String(profile.research_description || "").slice(0, 6_000),
      String(profile.expertise_keywords || "").slice(0, 4_000),
      String(profile.cv_text || "").slice(0, 10_000),
      String(profile.orcid_text || "").slice(0, 10_000),
    ].filter(Boolean).join(". ").slice(0, 24_000);
  }

  function buildTermQuery(
    profile,
    { catalog, tokenize, expandGroups, maximumTerms = DEFAULT_MAXIMUM_TERMS } = {},
  ) {
    if (!profile || !catalog?.search_index?.postings || !tokenize || !expandGroups) {
      return { query: "", terms: [], acronymExpansions: [] };
    }
    const weights = new Map();
    const acronymExpansions = new Map();
    const acronymContext = context(profile);
    const addSource = (value, sourceWeight) => {
      const counts = new Map();
      tokenize(value).forEach(term => {
        if (!GENERIC_PROFILE_TERMS.has(term)) {
          counts.set(term, (counts.get(term) || 0) + 1);
        }
      });
      expandGroups(value, { context: acronymContext }).forEach(group => {
        if (group.expansion?.kind === "contextual_acronym") {
          acronymExpansions.set(group.source, {
            source: group.source,
            phrase: group.expansion.phrase,
            confidence: group.expansion.confidence,
            basis: group.expansion.basis,
          });
        }
        // Keep one ranked term per source concept. The retrieval engine expands it
        // again at scoring time; putting every synonym into the query would make
        // one idea (for example AI/artificial intelligence) look like several
        // independent profile concepts and weaken profile-only admission.
        if (GENERIC_PROFILE_TERMS.has(group.source)) return;
        const matchingDocuments = new Set();
        group.terms.forEach(item => {
          const postings = catalog.search_index.postings[item.term] || [];
          for (let index = 0; index < postings.length; index += 2) {
            matchingDocuments.add(postings[index]);
          }
        });
        if (!matchingDocuments.size) return;
        const count = counts.get(group.source) || 1;
        const documentFrequency = matchingDocuments.size;
        const inverseFrequency = Math.log(
          1 + (
            (catalog.record_count - documentFrequency + 0.5)
            / (documentFrequency + 0.5)
          ),
        );
        const score = sourceWeight
          * (1 + Math.min(2.2, Math.log1p(count)))
          * inverseFrequency;
        weights.set(group.source, (weights.get(group.source) || 0) + score);
      });
    };

    addSource(profile.research_description, 2.2);
    addSource(profile.expertise_keywords, 5);
    addSource(profile.cv_text, 0.42);
    addSource(profile.orcid_text, 0.72);
    if (profile.career_stage === "early_career") {
      addSource("early career investigator new investigator", 5);
    } else if (profile.career_stage === "trainee") {
      addSource("trainee postdoctoral fellowship training", 5);
    }

    const terms = [...weights]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, Math.max(1, Number(maximumTerms) || DEFAULT_MAXIMUM_TERMS))
      .map(([term]) => term);
    return {
      query: terms.join(" "),
      terms,
      acronymExpansions: [...acronymExpansions.values()],
    };
  }

  function minimumCoverage(termCount) {
    const count = Math.max(0, Number(termCount) || 0);
    if (count <= 2) return count;
    return Math.min(4, Math.max(3, Math.ceil(count * 0.5)));
  }

  function applicantFitBonus(record, applicantContext) {
    const values = (record?.applicant_types || []).join(" ").toLowerCase();
    if (!values) return 0;
    if (values.includes("unrestricted")) return 0.8;
    const patterns = {
      higher_education: /institution(?:s)? of higher education/,
      nonprofit: /nonprofit/,
      small_business: /small business/,
      individual: /individual/,
      government: /government|county|city|township|school district|public housing|special district/,
      tribal: /tribal|native american/,
      other: /other|unrestricted/,
    };
    return patterns[applicantContext]?.test(values) ? 2.4 : -0.8;
  }

  function careerFitBonus(record, stage) {
    if (stage === "early_career") return record?.career_stage_signal ? 2.6 : 0;
    if (stage !== "trainee") return 0;
    const text = `${record?.title || ""} ${record?.description || ""}`.toLowerCase();
    return /\b(?:trainee|postdoc|postdoctoral|fellowship|graduate student)\b/.test(text)
      ? 2.2
      : 0;
  }

  globalThis.FUNDING_PROFILE_RANKING = Object.freeze({
    applicantFitBonus,
    buildTermQuery,
    careerFitBonus,
    context,
    genericTerms: GENERIC_PROFILE_TERMS,
    minimumCoverage,
  });
})();
