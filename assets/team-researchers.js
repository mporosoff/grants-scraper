(() => {
  "use strict";

  const STORAGE_KEY = "funding-finder.external-researchers.v1";
  const MAX_EXTERNAL = 4;
  const MIN_KEYWORDS = 3;
  const MAX_KEYWORDS = 8;
  const MAX_MATCHES_PER_KEYWORD = 16;
  const MAX_SEMANTIC_MATCHES_PER_KEYWORD = 4;
  const MIN_RELATIVE_KEYWORD_SCORE = .28;
  const MIN_RELATIVE_SEMANTIC_SCORE = .6;
  const MIN_SINGLE_SEMANTIC_SCORE = .72;
  const GENERIC_KEYWORDS = new Set([
    "biology", "chemistry", "energy", "engineering", "environment",
    "environmental science", "manufacturing", "material science",
    "materials", "materials science", "science", "sustainability", "technology",
  ]);
  const UMBRELLA_TOPICS = new Set([
    "Artificial intelligence and machine learning",
    "Biology and biotechnology",
    "Energy",
    "Environmental science",
    "Manufacturing",
    "Materials science",
  ]);
  const CONCEPT_STOP_WORDS = new Set([
    "a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to",
    "using", "via", "with",
  ]);
  const DOMAIN_HINTS = Object.freeze({
    "Catalysis and reaction engineering": ["cataly", "electrocataly", "photocataly", "reaction engineering", "kinetic", "hydrogenation"],
    Energy: ["energy", "fuel cell", "biofuel", "battery", "electrochem", "solar", "photovolta", "combustion", "hydrogen", "electroly", "power grid", "renewable"],
    "Carbon management": ["co2", "carbon dioxide", "carbon capture", "carbon utiliz", "decarboniz", "sequestrat", "direct air capture", "syngas"],
    "Materials science": ["material", "polymer", "nanomaterial", "thin film", "crystal", "metal-organic framework", "mof", "composite", "coating", "graphene", "semiconductor", "nanoparticle", "self-assembl"],
    "Separations and membranes": ["membrane", "gas separation", "adsorp", "filtration", "distillation", "chromatograph", "ion exchange"],
    Manufacturing: ["manufactur", "additive manufactur", "3d printing", "fabrication", "roll-to-roll", "process intensification", "scale-up"],
    "Artificial intelligence and machine learning": ["machine learning", "deep learning", "neural network", "artificial intelligence", "data-driven"],
    "Quantum science": ["quantum"],
    "Biology and biotechnology": ["biolog", "biotechnolog", "microb", "protein", "synthetic biology", "enzyme", "antibiotic", "bioreactor", "metabolic", "fermentation"],
    "Environmental science": ["environ", "pollut", "emission", "sustainab", "remediation", "air quality", "pfas", "perfluoro", "polyfluoro"],
    Water: ["desalinat", "wastewater", "water treatment", "drinking water", "water purification", "water resources", "pfas", "perfluoro", "polyfluoro"],
    "Public health": ["clinical trial", "drug delivery", "therapeutic", "pharmaceutic", "vaccine", "diagnostic"],
    "Climate change": ["climate", "greenhouse gas", "global warming"],
    "Space and aeronautics": ["aerospace", "spacecraft", "aeronautic", "propulsion", "in situ resource"],
  });

  function cleanText(value, maximum) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function conceptTokens(value) {
    const raw = String(value || "").normalize("NFKC").toLowerCase()
      .match(/[a-z0-9][a-z0-9+.-]{1,}/g) || [];
    return raw.map(token => {
      let normalized = token.replace(/^[.-]+|[.-]+$/g, "");
      if (normalized.length > 5 && normalized.endsWith("ies")) normalized = `${normalized.slice(0, -3)}y`;
      else if (normalized.length > 5 && normalized.endsWith("ing")) normalized = normalized.slice(0, -3);
      else if (normalized.length > 4 && normalized.endsWith("ed")) normalized = normalized.slice(0, -2);
      else if (normalized.length > 4 && normalized.endsWith("s") && !normalized.endsWith("ss")) normalized = normalized.slice(0, -1);
      return normalized;
    }).filter(token => token.length > 1 && !CONCEPT_STOP_WORDS.has(token));
  }

  function parseKeywords(value, limit = MAX_KEYWORDS) {
    const values = Array.isArray(value)
      ? value
      : String(value || "").split(/[,;\n]+/);
    const seen = new Set();
    const output = [];
    for (const item of values) {
      const keyword = cleanText(item, 64);
      const key = keyword.toLowerCase();
      if (!keyword || GENERIC_KEYWORDS.has(key) || seen.has(key)) continue;
      seen.add(key);
      output.push(keyword);
      if (output.length >= limit) break;
    }
    return output;
  }

  function createId(name, profiles = []) {
    const stem = cleanText(name, 80).toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 32) || "researcher";
    const used = new Set(profiles.map(profile => profile.id));
    let id = `ext-${stem}`;
    let suffix = 2;
    while (used.has(id)) {
      id = `ext-${stem}-${suffix}`;
      suffix += 1;
    }
    return id;
  }

  function normalizeProfiles(value) {
    if (!Array.isArray(value)) return [];
    const output = [];
    const used = new Set();
    for (const raw of value) {
      if (!raw || typeof raw !== "object" || output.length >= MAX_EXTERNAL) break;
      const name = cleanText(raw.name, 80);
      const keywords = parseKeywords(raw.keywords);
      if (!name || !keywords.length) continue;
      let id = /^ext-[a-z0-9][a-z0-9-]{0,47}$/.test(String(raw.id || ""))
        ? String(raw.id)
        : createId(name, output);
      if (used.has(id)) id = createId(name, output);
      used.add(id);
      const orcidId = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/i.test(String(raw.orcid_id || ""))
        ? String(raw.orcid_id).toUpperCase()
        : "";
      output.push({
        id,
        registry_id: /^urh-[0-9]{6}$/.test(String(raw.registry_id || "")) ? String(raw.registry_id) : "",
        name,
        keywords,
        orcid_id: orcidId,
        orcid_name: orcidId ? cleanText(raw.orcid_name, 160) : "",
        orcid_text: orcidId ? cleanText(raw.orcid_text, 40_000) : "",
        orcid_work_count: orcidId ? Math.max(0, Math.min(100, Number(raw.orcid_work_count) || 0)) : 0,
        orcid_total_work_count: orcidId ? Math.max(0, Number(raw.orcid_total_work_count) || 0) : 0,
        orcid_source: orcidId ? cleanText(raw.orcid_source, 200) : "",
        orcid_updated_at: orcidId ? cleanText(raw.orcid_updated_at, 40) : "",
      });
    }
    return output;
  }

  function load(storage) {
    try {
      const raw = storage && storage.getItem(STORAGE_KEY);
      return { profiles: raw ? normalizeProfiles(JSON.parse(raw)) : [], available: Boolean(storage), error: "" };
    } catch (_error) {
      return { profiles: [], available: false, error: "Saved external researchers could not be read in this browser." };
    }
  }

  function save(storage, profiles) {
    const normalized = normalizeProfiles(profiles);
    try {
      if (!storage) throw new Error("Storage unavailable");
      storage.setItem(STORAGE_KEY, JSON.stringify(normalized));
      return { profiles: normalized, saved: true, error: "" };
    } catch (_error) {
      return { profiles: normalized, saved: false, error: "Changes are available in this tab but could not be saved on this device." };
    }
  }

  function inferDomains(keywords) {
    const text = keywords.join(" ").toLowerCase();
    return Object.keys(DOMAIN_HINTS).filter(domain =>
      DOMAIN_HINTS[domain].some(hint => text.includes(hint)),
    );
  }

  function bestUrl(record) {
    for (const field of ["funding_opportunity_url", "primary_document_url", "detail_page", "url"]) {
      const value = String(record[field] || "");
      if (/^https?:\/\//i.test(value)) return value;
    }
    return "";
  }

  function deadlineText(record) {
    const closeDate = String(record.close_date || "");
    if (/^\d{4}-\d{2}-\d{2}$/.test(closeDate)) return `Closes ${closeDate}`;
    return String(record.deadline_note || record.close_date_note || "");
  }

  function listingDate(record) {
    for (const field of ["posted_date", "source_first_seen_date"]) {
      const value = String(record[field] || "");
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    }
    return "";
  }

  function listingDateValue(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))
      ? Number(String(value).replace(/-/g, ""))
      : 0;
  }

  function recordIsCurrent(record, now = new Date()) {
    const shared = globalThis.FUNDING_RETRIEVAL?.recordIsCurrent;
    if (typeof shared !== "function") {
      throw new Error("Researcher matching requires the shared funding currentness contract.");
    }
    return shared(record, now);
  }

  function recencyScore(value, newestValue) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))
      || !/^\d{4}-\d{2}-\d{2}$/.test(String(newestValue || ""))) return 0;
    const current = Date.parse(`${value}T00:00:00Z`);
    const newest = Date.parse(`${newestValue}T00:00:00Z`);
    if (!Number.isFinite(current) || !Number.isFinite(newest)) return 0;
    const ageDays = Math.max(0, (newest - current) / 86400000);
    return 3 * Math.max(0, 1 - ageDays / 365);
  }

  function keywordEvidence(keyword, record, searchApi, retrievalEngine, context = "") {
    // Validate retrieval against source wording, not derived topic facets. The
    // search index intentionally contains broad catalog topics, so trusting its
    // lexical score alone can turn a noisy "Materials science" tag into a
    // researcher match.
    const rawText = [
      record.title || "",
      record.description || "",
      ...(record.disciplines || []),
    ].join(" ");
    const rawTokenList = conceptTokens(rawText);
    const rawTokens = new Set(rawTokenList);
    const groups = typeof retrievalEngine?.expandGroups === "function"
      ? retrievalEngine.expandGroups(keyword, { context })
      : searchApi.expandGroups
        ? searchApi.expandGroups(keyword, term => rawTokens.has(term))
      : searchApi.tokenize(keyword).map(term => ({
        source: term,
        terms: [{ term, weight: 1 }],
      }));
    const groupedSources = new Set(groups.map(group => group.source));
    conceptTokens(keyword).forEach(term => {
      if (groupedSources.has(term)) return;
      groupedSources.add(term);
      groups.push({ source: term, terms: [{ term, weight: 1 }] });
    });
    if (!groups.length) return { matched: false, strength: 0, lexical: false };

    let covered = 0;
    let direct = 0;
    let aliasHits = 0;
    const groupTermSets = groups.map(group => {
      const resolvedTerms = new Set();
      group.terms.forEach(item => {
        resolvedTerms.add(item.term);
        if (typeof retrievalEngine?.resolveTerm === "function") {
          retrievalEngine.resolveTerm(item.term).forEach(resolution => {
            resolvedTerms.add(resolution.term);
          });
        }
      });
      return resolvedTerms;
    });
    groups.forEach((group, groupIndex) => {
      const groupHits = new Set();
      groupTermSets[groupIndex].forEach(term => {
        if (rawTokens.has(term)) groupHits.add(term);
      });
      const minimumEvidence = Number(group.minimumEvidence || 0) || 1;
      if (groupHits.size >= minimumEvidence) covered += 1;
      if (rawTokens.has(group.source)) direct += 1;
      aliasHits += groupHits.size;
    });

    const needed = groups.length === 1
      ? 1
      : groups.length <= 3
        ? groups.length
        : Math.max(3, Math.ceil(groups.length * .75));
    // Long one-token aliases such as PFAS expand to a concept family; require
    // at least two contextual words when the abbreviation itself is absent.
    const aliasEnough = groups.length !== 1
      || direct > 0
      || (groups[0].minimumEvidence
        ? aliasHits >= groups[0].minimumEvidence
        : groups[0].terms.length < 6)
      || aliasHits >= 2;
    const windowSize = groups.length + 4;
    let proximityEnough = groups.length === 1;
    for (let start = 0; !proximityEnough && start < rawTokenList.length; start += 1) {
      const matchedGroups = new Set();
      rawTokenList.slice(start, start + windowSize).forEach(token => {
        groupTermSets.forEach((terms, groupIndex) => {
          if (terms.has(token)) matchedGroups.add(groupIndex);
        });
      });
      proximityEnough = matchedGroups.size >= needed;
    }
    return {
      matched: covered >= needed && aliasEnough && proximityEnough,
      strength: covered / groups.length,
      lexical: direct > 0,
    };
  }

  function buildMatches(
    profile,
    catalogData,
    searchApi,
    nicheTopics = [],
    retrievalEngine = null,
  ) {
    const records = Array.isArray(catalogData?.opportunities)
      ? catalogData.opportunities
      : [];
    const postings = catalogData?.search_index?.postings || {};
    if (!records.length || !searchApi?.tokenize || !searchApi?.expandTerms) return [];

    const focusedKeywords = (profile.keywords || []).filter(keyword =>
      !GENERIC_KEYWORDS.has(cleanText(keyword, 64).toLowerCase()),
    );
    const context = [
      ...focusedKeywords,
      profile.research_summary || profile.summary || "",
      cleanText(profile.publication_text, 12_000),
    ].filter(Boolean).join(". ").slice(0, 24_000);
    const evidenceByDocument = new Map();
    function addEvidence(documentId, keyword, strength, lexical) {
      const evidence = evidenceByDocument.get(documentId) || [];
      const prior = evidence.find(item => item.term === keyword);
      if (prior) {
        prior.strength = Math.max(prior.strength, strength);
        prior.lexical = prior.lexical || lexical;
      } else {
        evidence.push({ term: keyword, strength, lexical });
      }
      evidenceByDocument.set(documentId, evidence);
    }
    if (typeof retrievalEngine?.score === "function") {
      for (const keyword of focusedKeywords) {
        const result = retrievalEngine.score(keyword, { context });
        const candidates = [];
        for (let documentId = 0; documentId < records.length; documentId += 1) {
          const score = Number(result.scores?.[documentId] || 0);
          if (score <= 0) continue;
          candidates.push({
            documentId,
            score,
            lexicalScore: Number(result.lexicalScores?.[documentId] || 0),
          });
        }
        candidates.sort((left, right) =>
          right.score - left.score || left.documentId - right.documentId,
        );
        const topScore = candidates[0]?.score || 0;
        const minimumScore = topScore * MIN_RELATIVE_KEYWORD_SCORE;
        let semanticMatches = 0;
        let acceptedMatches = 0;
        for (const candidate of candidates) {
          if (candidate.score < minimumScore || acceptedMatches >= MAX_MATCHES_PER_KEYWORD) break;
          const semanticOnly = candidate.lexicalScore <= 0;
          const relativeScore = topScore > 0 ? candidate.score / topScore : 0;
          if (semanticOnly && relativeScore < MIN_RELATIVE_SEMANTIC_SCORE) continue;
          if (semanticOnly && semanticMatches >= MAX_SEMANTIC_MATCHES_PER_KEYWORD) continue;
          const evidence = keywordEvidence(
            keyword, records[candidate.documentId], searchApi, retrievalEngine, context,
          );
          if (!evidence.matched) continue;
          addEvidence(
            candidate.documentId,
            keyword,
            Math.max(relativeScore, evidence.strength),
            evidence.lexical,
          );
          acceptedMatches += 1;
          if (semanticOnly) semanticMatches += 1;
        }
      }
    } else {
      // Keep a small compatibility path if the hybrid scorer fails to load.
      for (const keyword of focusedKeywords) {
        const concepts = [...new Set(searchApi.tokenize(keyword))];
        if (!concepts.length) continue;
        const conceptCount = new Map();
        for (const concept of concepts) {
          const documentIds = new Set();
          const alternatives = searchApi.expandTerms(
            concept,
            term => Boolean(postings[term]),
          );
          for (const { term } of alternatives) {
            const values = postings[term] || [];
            for (let cursor = 0; cursor < values.length; cursor += 2) {
              documentIds.add(values[cursor]);
            }
          }
          documentIds.forEach(documentId => {
            conceptCount.set(documentId, (conceptCount.get(documentId) || 0) + 1);
          });
        }
        const needed = concepts.length === 1
          ? 1
          : Math.max(2, Math.ceil(concepts.length * .6));
        conceptCount.forEach((count, documentId) => {
          if (count < needed) return;
          const evidence = keywordEvidence(
            keyword, records[documentId], searchApi, retrievalEngine, context,
          );
          if (!evidence.matched) return;
          addEvidence(
            documentId,
            keyword,
            Math.max(count / concepts.length, evidence.strength),
            evidence.lexical,
          );
        });
      }
    }

    const domains = new Set([
      ...(profile.domains || []).filter(Boolean),
      ...inferDomains(profile.keywords || []),
    ]);
    const newestListing = records.reduce((newest, record) => {
      const value = listingDate(record);
      return listingDateValue(value) > listingDateValue(newest) ? value : newest;
    }, "");
    const matches = [];
    records.forEach((record, documentId) => {
      if (!recordIsCurrent(record)) return;
      const evidence = evidenceByDocument.get(documentId) || [];
      if (!evidence.length) return;
      if (evidence.length === 1 && !evidence[0].lexical
        && evidence[0].strength < MIN_SINGLE_SEMANTIC_SCORE) return;
      const hitTerms = evidence.map(item => item.term);
      const topics = new Set(record.topic_areas || []);
      const sharedDomains = [...domains].filter(domain => topics.has(domain));
      const sharedTopics = sharedDomains.filter(domain => !UMBRELLA_TOPICS.has(domain));
      const relevance = evidence.reduce((total, item) =>
        total + 3 + item.strength + (item.lexical ? 1 : 0), 0)
        + Math.min(1.5, sharedTopics.length * .25);
      const listed = listingDate(record);
      const recent = recencyScore(listed, newestListing);
      matches.push({
        id: record.opportunity_id || record.opportunity_number || record.title,
        title: record.title || "Untitled opportunity",
        agency: record.agency || "",
        url: bestUrl(record),
        deadline: deadlineText(record),
        listing_date: listed,
        tier: "focused",
        terms: hitTerms,
        shared_topics: sharedTopics,
        score: relevance,
        relevance_score: relevance,
        recency_score: recent,
        rank_score: relevance + recent,
      });
    });

    matches.sort((left, right) =>
      right.rank_score - left.rank_score
      || listingDateValue(right.listing_date) - listingDateValue(left.listing_date)
      || right.relevance_score - left.relevance_score
      || left.title.localeCompare(right.title),
    );
    return matches;
  }

  function intersectMemberMatches(members) {
    if (!Array.isArray(members) || members.length < 2) return [];
    const opportunities = new Map();

    members.forEach((member, memberIndex) => {
      const memberKey = String(member?.key || `member-${memberIndex}`);
      const seen = new Set();
      (Array.isArray(member?.matches) ? member.matches : []).forEach(match => {
        const opportunityId = String(match?.id || "");
        if (!opportunityId || seen.has(opportunityId)) return;
        seen.add(opportunityId);
        const entry = opportunities.get(opportunityId) || {
          d: {
            id: opportunityId,
            title: match.title,
            agency: match.agency,
            url: match.url,
            deadline: match.deadline,
            listing_date: match.listing_date || "",
          },
          fits: [],
          memberKeys: new Set(),
        };
        entry.memberKeys.add(memberKey);
        entry.fits.push({
          name: member.name,
          external: Boolean(member.external),
          tier: match.tier,
          terms: match.terms,
          shared_topics: match.shared_topics,
          score: Number(match.score || 0),
          rank_score: Number(match.rank_score || match.score || 0),
        });
        opportunities.set(opportunityId, entry);
      });
    });

    return [...opportunities.values()]
      .filter(entry => entry.memberKeys.size === members.length)
      .map(entry => {
        entry.fits.sort((left, right) => right.score - left.score);
        entry.totalN = entry.fits.length;
        entry.sumScore = entry.fits.reduce((sum, fit) => sum + fit.score, 0);
        entry.sumRankScore = entry.fits.reduce((sum, fit) => sum + fit.rank_score, 0);
        delete entry.memberKeys;
        return entry;
      });
  }

  globalThis.FUNDING_TEAM_RESEARCHERS = Object.freeze({
    STORAGE_KEY,
    MAX_EXTERNAL,
    MIN_KEYWORDS,
    MAX_KEYWORDS,
    parseKeywords,
    createId,
    normalizeProfiles,
    load,
    save,
    inferDomains,
    buildMatches,
    intersectMemberMatches,
  });
})();
