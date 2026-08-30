(() => {
  "use strict";

  const DEFAULT_BROAD_PATTERN = [
    "broad agency announcement", "\\bbaa\\b", "continuation of solicitation",
    "office of science financial assistance", "long[\\s-]?range",
    "research announcement", "\\broses\\b", "omnibus",
    "unsolicited proposal", "open topic", "financial assistance program",
    "annual program statement", "office[ -]wide", "open[ -]scope solicitation",
  ].join("|");
  const COMMON_TOPICS = new Set([
    "Artificial intelligence and machine learning",
    "Biology and biotechnology",
    "Education and workforce",
    "Energy",
    "Environmental science",
    "Manufacturing",
    "Materials science",
    "Technology development",
  ]);
  const OUT_OF_SCOPE_RE = [
    /u\.s\. mission|embassy|consulate|public diplomacy/i,
    /bureau of (?:near eastern|east asian|south and central asian|western hemisphere) affairs/i,
    /mine safety and health administration|brookwood-sago mine safety/i,
  ];
  const STOP_WORDS = new Set([
    "the", "and", "for", "with", "from", "this", "that", "are", "was",
    "into", "over", "out", "per", "via", "research", "program", "programs",
    "grant", "grants", "funding", "award", "awards", "project", "projects",
    "support", "science", "sciences", "engineering", "technology", "technologies",
    "national", "university", "universities", "institute", "department", "studies",
    "study", "development", "applications", "application", "advancing", "advanced",
    "approaches", "approach", "based", "using", "their", "which", "will", "been",
    "more", "also", "may", "can", "under", "new", "toward", "towards", "related",
    "general", "foundation", "opportunity", "opportunities", "proposal", "proposals",
    "faculty", "investigator", "investigators",
  ]);
  const MIN_MEMBER_SCORE = 1.35;
  const STALE_UNDATED_MAX_AGE_DAYS = 5 * 366;
  const NON_FUNDING_TITLE_RE = /^(?:[A-Z0-9-]+\s+)?(?:notice\s+of\s+intent(?:\s+to\s+issue)?\b|request\s+for\s+information\b|RFI\s*[-:])/i;
  const NOT_ACCEPTING_RE = /\b(?:not|isn't|is\s+not)\s+accepting\s+applications?\b|\bno\s+applications?\s+(?:are|will\s+be)\s+accepted\b/i;

  function cleanDate(value) {
    const text = String(value || "");
    return /^\d{4}-\d{2}-\d{2}/.test(text) ? text.slice(0, 10) : "";
  }

  function daysBetween(value, now) {
    const date = cleanDate(value);
    if (!date) return null;
    const timestamp = Date.parse(`${date}T00:00:00Z`);
    if (!Number.isFinite(timestamp)) return null;
    return Math.floor((now.getTime() - timestamp) / 86400000);
  }

  function nonFundingReason(record) {
    if (NON_FUNDING_TITLE_RE.test(String(record.title || "").trim())) return "informational_notice";
    const instruments = new Set((record.funding_instrument_codes || record.funding_instruments || [])
      .map(value => String(value || "").trim().toLowerCase()).filter(Boolean));
    if (instruments.size && [...instruments].every(value => value === "o" || value === "other")
      && NOT_ACCEPTING_RE.test(String(record.description || "").slice(0, 2500))) {
      return "not_accepting_applications";
    }
    return "";
  }

  function recordIsCurrent(record, now = new Date(), catalogRole = "parent") {
    if (catalogRole === "child") {
      return record?.publication_state === "publishable" && record?.child_type === "subject";
    }
    const status = String(record.status || "").trim().toLowerCase();
    if (["archived", "closed", "cancelled", "canceled", "withdrawn", "expired"].includes(status)) {
      return false;
    }
    if (!["posted", "forecasted"].includes(status) || nonFundingReason(record)) return false;
    const archiveAge = daysBetween(record.archive_date, now);
    if (archiveAge !== null && archiveAge >= 0) return false;
    if (record.archive_date && archiveAge === null) return false;
    const closeAge = daysBetween(record.close_date, now);
    if (closeAge !== null && closeAge > 0 && !record.rolling) return false;
    if (record.close_date && closeAge === null) return false;
    if (!record.rolling && !record.close_date && !record.archive_date) {
      const postedAge = daysBetween(record.posted_date, now);
      if (postedAge !== null && postedAge > STALE_UNDATED_MAX_AGE_DAYS) return false;
    }
    return true;
  }

  function recordIsTestOpportunity(record) {
    const agency = String(record.agency || "");
    const text = `${record.title || ""} ${String(record.description || "").slice(0, 500)}`;
    return /\bIV&V Test Agency\b/i.test(agency)
      || /\btest (?:NOFO|funding opportunity)\b[^.]{0,80}\bdo not apply\b/i.test(text);
  }

  function bestUrl(record) {
    const broken = new Set(record.link_health_broken_urls || []);
    const genericAgency = (() => {
      const value = String(record.funding_opportunity_url || "");
      if (!value || !record.detail_page) return false;
      return /^https?:\/\/[^/?#]+\/?(?:#.*)?$/i.test(value);
    })();
    const fields = genericAgency
      ? ["primary_document_url", "detail_page", "funding_opportunity_url", "url"]
      : ["primary_document_url", "funding_opportunity_url", "detail_page", "url"];
    for (const field of fields) {
      const value = String(record[field] || "");
      if (/^https?:\/\//i.test(value) && !broken.has(value)) return value;
    }
    return "";
  }

  function deadlineText(record) {
    const closeDate = cleanDate(record.close_date);
    if (closeDate) return `Closes ${closeDate}`;
    return String(record.deadline_note || record.close_date_note || "");
  }

  function uniq(values) {
    return [...new Set(values.filter(Boolean))];
  }

  function create(catalogData, config = {}, searchApi = null, options = {}) {
    const rawRecords = Array.isArray(catalogData?.opportunities)
      ? catalogData.opportunities
      : [];
    const now = options.now instanceof Date
      ? options.now
      : new Date(options.now || Date.now());
    const catalogRole = options.catalogRole === "child" ? "child" : "parent";
    const lexicon = config.theme_lexicon || {};
    const bridgeDefinitions = config.bridge_themes || [];
    const commonTopics = new Set([...COMMON_TOPICS, ...(config.common_topics || [])]);
    const acronymResolver = searchApi?.createAcronymResolver
      ? searchApi.createAcronymResolver(rawRecords)
      : null;
    let broadPattern;
    try {
      broadPattern = new RegExp(config.broad_pattern || DEFAULT_BROAD_PATTERN, "i");
    } catch (_error) {
      broadPattern = new RegExp(DEFAULT_BROAD_PATTERN, "i");
    }
    const scopes = (config.agency_scope || []).map(scope => {
      let pattern = null;
      try { pattern = new RegExp(scope.pattern, "i"); } catch (_error) { pattern = null; }
      return {
        label: String(scope.label || "Broad sponsor scope"),
        pattern,
        domains: new Set(scope.domains || []),
      };
    });

    const tokenize = value => {
      if (searchApi?.tokenize) return searchApi.tokenize(value).filter(token => !STOP_WORDS.has(token));
      return String(value || "").normalize("NFKC").toLowerCase()
        .match(/[a-z0-9][a-z0-9+.-]{1,}/g)?.filter(token => !STOP_WORDS.has(token)) || [];
    };

    const records = [];
    const wordFrequency = new Map();
    const topicFrequency = new Map();
    const profileVocabularyCache = new WeakMap();
    const groupDefinitionCache = new Map();
    rawRecords.forEach(record => {
      if (!recordIsCurrent(record, now, catalogRole) || recordIsTestOpportunity(record)) return;
      const identityText = `${record.agency || ""} ${record.title || ""}`;
      if (OUT_OF_SCOPE_RE.some(pattern => pattern.test(identityText))) return;
      const sourceText = [
        record.title || "",
        record.description || "",
        String(record.document_search_text || "").slice(0, 16_000),
        ...(record.topic_areas || []),
        ...(record.disciplines || []),
      ].join(" ");
      const sourceLower = sourceText.toLowerCase();
      const tokens = tokenize(sourceText);
      const tokenSet = new Set(tokens);
      const topics = new Set(record.topic_areas || []);
      const broadText = `${record.title || ""} ${(record.description || "").slice(0, 700)}`;
      const postedAge = daysBetween(record.posted_date || record.source_first_seen_date, now);
      // source_last_seen_date changes when a scraper merely observes an
      // unchanged record. It is not a substantive update and must not make the
      // entire catalog look freshly posted after every nightly refresh.
      const updatedAge = daysBetween(record.last_updated, now);
      const freshAge = [postedAge, updatedAge]
        .filter(value => value !== null && value >= 0)
        .reduce((best, value) => best === null ? value : Math.min(best, value), null);
      const closeIn = (() => {
        const age = daysBetween(record.close_date, now);
        return age === null ? null : -age;
      })();
      const prepared = {
        record,
        id: String(record.opportunity_id || record.opportunity_number || record.title || ""),
        sourceLower,
        tokens,
        tokenSet,
        topics,
        agencyLower: String(record.agency || "").toLowerCase(),
        scopeText: identityText.toLowerCase(),
        isBroad: broadPattern.test(broadText),
        isSpecificSubcall: /\broses\s*(?:20)?\d{2}:\s*[a-z]\.\d+/i.test(record.title || ""),
        postedAge,
        updatedAge,
        freshAge,
        closeIn,
      };
      records.push(prepared);
      tokenSet.forEach(token => wordFrequency.set(token, (wordFrequency.get(token) || 0) + 1));
      topics.forEach(topic => topicFrequency.set(topic, (topicFrequency.get(topic) || 0) + 1));
    });

    const documentCount = Math.max(1, records.length);
    function idf(term) {
      const frequency = (wordFrequency.get(term) || 0) / documentCount;
      if (frequency <= .005) return 1;
      if (frequency <= .02) return .82;
      if (frequency <= .05) return .55;
      if (frequency <= .1) return .28;
      return .08;
    }

    function topicWeight(topic) {
      if (commonTopics.has(topic)) return .12;
      const frequency = (topicFrequency.get(topic) || 0) / documentCount;
      if (frequency <= .01) return .72;
      if (frequency <= .03) return .52;
      if (frequency <= .08) return .3;
      return .15;
    }

    function profileContext(profile) {
      return [
        ...(profile.key_terms || []),
        ...(profile.keywords || []),
        profile.research_summary || profile.summary || "",
        String(profile.publication_text || "").slice(0, 12_000),
      ].filter(Boolean).join(". ").slice(0, 24_000);
    }

    function groupDefinitions(value, context = "") {
      let contextCache = groupDefinitionCache.get(context);
      if (!contextCache) {
        contextCache = new Map();
        groupDefinitionCache.set(context, contextCache);
      }
      const valueKey = String(value || "");
      if (contextCache.has(valueKey)) return contextCache.get(valueKey);
      let groups;
      if (searchApi?.expandGroups) {
        groups = searchApi.expandGroups(
          value,
          term => wordFrequency.has(term),
          { acronymResolver, context },
        ).map(group => ({
          source: group.source,
          terms: group.terms || [],
          minimumEvidence: Number(group.minimumEvidence || 0),
          evidenceAlternatives: group.evidenceAlternatives || null,
          requiredUnlessTopic: group.requiredUnlessTopic || "",
          requiredAlways: group.requiredAlways === true,
          expansion: group.expansion || null,
        }));
      } else {
        groups = uniq(tokenize(value)).map(term => ({
          source: term,
          terms: [{ term, weight: 1 }],
        }));
      }
      contextCache.set(valueKey, groups);
      return groups;
    }

    function profileVocabulary(profile) {
      if (profileVocabularyCache.has(profile)) return profileVocabularyCache.get(profile);
      const terms = new Set();
      const context = profileContext(profile);
      for (const phrase of profile.key_terms || profile.keywords || []) {
        groupDefinitions(phrase, context).forEach(group => {
          if (group.source) terms.add(group.source);
          (group.terms || []).forEach(item => {
            if (item.term) terms.add(item.term);
          });
        });
      }
      const values = [...terms];
      profileVocabularyCache.set(profile, values);
      return values;
    }

    function relatedTerm(left, right) {
      if (left === right) return true;
      if (left.length < 6 || right.length < 6) return false;
      return left.slice(0, 6) === right.slice(0, 6);
    }

    function phraseEvidence(phrase, prepared, context = "") {
      const groups = groupDefinitions(phrase, context);
      if (!groups.length) return null;
      const groupTermSets = groups.map(group => new Set(group.terms.map(item => item.term)));
      let matchedGroups = 0;
      let directGroups = 0;
      let specificityTotal = 0;
      let contextualAlias = false;
      groups.forEach((group, groupIndex) => {
        const direct = prepared.tokenSet.has(group.source);
        const aliasHits = group.terms.filter(item =>
          item.term !== group.source && prepared.tokenSet.has(item.term));
        const minimumAliasEvidence = group.minimumEvidence
          || (group.terms.length >= 6 ? 2 : 1);
        const alternativesSatisfied = !group.evidenceAlternatives?.length
          || group.evidenceAlternatives.some(alternative =>
            alternative.every(term => prepared.tokenSet.has(term))
          )
          || (group.requiredUnlessTopic && prepared.topics.has(group.requiredUnlessTopic));
        const contextual = !direct
          && (group.minimumEvidence > 0 || group.terms.length >= 6)
          && aliasHits.length >= minimumAliasEvidence
          && alternativesSatisfied;
        const alias = !direct && minimumAliasEvidence === 1 && !contextual && aliasHits.length > 0;
        if ((!direct && !contextual && !alias) || !alternativesSatisfied) return;
        matchedGroups += 1;
        if (direct) directGroups += 1;
        if (contextual) contextualAlias = true;
        const hitSpecificity = direct
          ? idf(group.source)
          : aliasHits.reduce((sum, item) => sum + idf(item.term) * Number(item.weight || 1), 0)
            / Math.max(1, aliasHits.length);
        specificityTotal += contextual ? Math.max(.7, hitSpecificity) : hitSpecificity;
      });
      if (!matchedGroups) return null;

      const coverage = matchedGroups / groups.length;
      const specificity = specificityTotal / matchedGroups;
      const needed = groups.length <= 3 ? groups.length : Math.max(3, Math.ceil(groups.length * .7));
      let proximity = groups.length === 1;
      const windowSize = groups.length + 6;
      for (let start = 0; !proximity && start < prepared.tokens.length; start += 1) {
        const nearby = new Set();
        prepared.tokens.slice(start, start + windowSize).forEach(token => {
          groupTermSets.forEach((terms, groupIndex) => {
            if (terms.has(token)) nearby.add(groupIndex);
          });
        });
        proximity = nearby.size >= needed;
      }

      let score = 0;
      let strong = false;
      if (matchedGroups >= needed && proximity) {
        score = 1.7 + 1.8 * coverage * Math.max(.35, specificity);
        strong = score >= 2.25;
      } else if (matchedGroups >= 2 && coverage >= .4) {
        score = .45 + 1.25 * coverage * Math.max(.25, specificity);
      } else if (groups.length === 1 && (directGroups || contextualAlias)) {
        score = 1.35 * Math.max(.35, specificity) + (contextualAlias ? .45 : 0);
        strong = score >= 1.2;
      }
      if (score < .18) return null;
      return { score, strong, coverage, label: phrase };
    }

    function vocabularyEvidence(domain, prepared, profileTerms = null) {
      const hits = [];
      let score = 0;
      let linkedScore = 0;
      for (const term of lexicon[domain] || []) {
        if (!prepared.sourceLower.includes(String(term).toLowerCase())) continue;
        const termTokens = tokenize(term);
        const specificity = termTokens.length
          ? termTokens.reduce((sum, token) => sum + idf(token), 0) / termTokens.length
          : .2;
        const contribution = .22 + .42 * specificity;
        score += contribution;
        if (profileTerms && termTokens.some(termToken =>
          profileTerms.some(profileTerm => relatedTerm(termToken, profileTerm)))) {
          linkedScore += contribution;
        }
        hits.push(term);
        if (hits.length >= 4) break;
      }
      return {
        score: Math.min(1.55, score),
        linkedScore: Math.min(1.55, linkedScore),
        hits,
      };
    }

    function scopeEvidence(profile, prepared) {
      if (!prepared.isBroad || prepared.isSpecificSubcall) return null;
      const domains = new Set(profile.domains || []);
      for (const scope of scopes) {
        if (!scope.pattern || !scope.pattern.test(prepared.scopeText)) continue;
        const overlap = [...domains].filter(domain => scope.domains.has(domain));
        if (overlap.length) return { score: 1.08, label: scope.label, domains: overlap };
      }
      return null;
    }

    function scoreProfile(profile, prepared) {
      const reasons = [];
      const matchedDomains = new Set();
      let phraseScore = 0;
      let vocabularyScore = 0;
      let linkedVocabularyScore = 0;
      let tagScore = 0;
      let strong = false;
      let signalCount = 0;
      const context = profileContext(profile);

      for (const phrase of profile.key_terms || profile.keywords || []) {
        const evidence = phraseEvidence(phrase, prepared, context);
        if (!evidence) continue;
        phraseScore += evidence.score;
        strong = strong || evidence.strong;
        signalCount += 1;
        reasons.push({ label: evidence.label, score: evidence.score, type: "interest" });
      }
      phraseScore = Math.min(7.5, phraseScore);

      const profileTerms = profileVocabulary(profile);
      for (const domain of profile.domains || []) {
        const vocabulary = vocabularyEvidence(domain, prepared, profileTerms);
        if (vocabulary.score > 0) {
          vocabularyScore += vocabulary.score;
          linkedVocabularyScore += vocabulary.linkedScore;
          signalCount += vocabulary.hits.length;
          matchedDomains.add(domain);
          reasons.push({ label: domain, score: vocabulary.score, type: "theme" });
        }
        if (prepared.topics.has(domain)) {
          const weight = topicWeight(domain);
          tagScore += weight;
          matchedDomains.add(domain);
          reasons.push({ label: domain, score: weight, type: "topic" });
        }
      }
      vocabularyScore = Math.min(3.4, vocabularyScore);
      linkedVocabularyScore = Math.min(3.4, linkedVocabularyScore);
      tagScore = Math.min(1.25, tagScore);
      const scope = scopeEvidence(profile, prepared);
      const scopeScore = scope?.score || 0;
      if (scope) {
        signalCount += 1;
        scope.domains.forEach(domain => matchedDomains.add(domain));
        reasons.push({ label: scope.label, score: scope.score, type: "scope" });
      }

      const score = phraseScore + vocabularyScore + tagScore + scopeScore;
      // Agency scope is intentionally a modest exception for genuinely broad,
      // otherwise unsearchable solicitations. Ordinary records need a higher
      // accumulation of textual/topic evidence so one generic vocabulary hit
      // cannot establish researcher fit by itself.
      const minimumScore = scopeScore > 0 ? 1.0 : MIN_MEMBER_SCORE;
      const hasResearcherLink = phraseScore >= .18 || linkedVocabularyScore >= .3 || scopeScore > 0;
      if (score < minimumScore || !signalCount || !hasResearcherLink) return null;
      reasons.sort((left, right) => right.score - left.score || left.label.localeCompare(right.label));
      const researchReasons = uniq(reasons
        .filter(reason => reason.type !== "scope")
        .map(reason => reason.label)).slice(0, 4);
      return {
        name: profile.name,
        score,
        strong: strong || phraseScore >= 2.25 || linkedVocabularyScore >= 1.45,
        textEvidence: phraseScore + vocabularyScore,
        phraseScore,
        vocabularyScore,
        linkedVocabularyScore,
        tagScore,
        scopeScore,
        scopeLabel: scope?.label || "",
        matchedDomains: [...matchedDomains],
        researchReasons,
        reasons: uniq(reasons.map(reason => reason.label)).slice(0, 4),
      };
    }

    function buildThemes(profiles) {
      const holders = new Map();
      profiles.forEach(profile => {
        (profile.domains || []).forEach(domain => {
          const members = holders.get(domain) || [];
          members.push(profile.name);
          holders.set(domain, members);
        });
      });
      const themes = [];
      [...holders].sort(([left], [right]) => left.localeCompare(right)).forEach(([domain, members]) => {
        const uniqueMembers = uniq(members);
        if (uniqueMembers.length < 2) return;
        themes.push({
          type: "core",
          label: domain,
          domains: [domain],
          terms: lexicon[domain] || [],
          members: uniqueMembers,
        });
      });
      bridgeDefinitions.forEach(bridge => {
        const leftMembers = holders.get(bridge.domains?.[0]) || [];
        const rightMembers = holders.get(bridge.domains?.[1]) || [];
        const linked = leftMembers.some(left => rightMembers.some(right => left !== right));
        if (!linked) return;
        themes.push({
          type: "bridge",
          label: bridge.label,
          domains: bridge.domains || [],
          terms: bridge.terms || [],
          members: uniq([...leftMembers, ...rightMembers]),
        });
      });
      return themes;
    }

    function domainRecordScore(domain, prepared) {
      const vocabulary = vocabularyEvidence(domain, prepared).score;
      const tag = prepared.topics.has(domain) ? topicWeight(domain) : 0;
      let scope = 0;
      if (prepared.isBroad) {
        for (const item of scopes) {
          if (!prepared.isSpecificSubcall && item.pattern?.test(prepared.scopeText) && item.domains.has(domain)) {
            scope = .45;
            break;
          }
        }
      }
      return vocabulary + tag + scope;
    }

    function themeEvidence(theme, prepared) {
      let direct = 0;
      for (const term of theme.terms || []) {
        if (prepared.sourceLower.includes(String(term).toLowerCase())) direct += .3;
        if (direct >= 1.2) break;
      }
      const domainScores = (theme.domains || []).map(domain => domainRecordScore(domain, prepared));
      let score = direct;
      if (theme.type === "bridge") {
        if (domainScores.length >= 2 && domainScores.every(value => value >= .25)) {
          score += Math.min(1.2, domainScores.reduce((sum, value) => sum + value, 0) * .45);
        }
      } else {
        score += Math.min(.9, domainScores[0] || 0);
      }
      return score >= .35 ? score : 0;
    }

    function recencyBoost(prepared) {
      if (prepared.freshAge !== null && prepared.freshAge <= 14) return 1.65;
      if (prepared.freshAge !== null && prepared.freshAge <= 45) return 1.3;
      return 1;
    }

    function resultRecord(prepared, fits, relevanceScore, themeHits) {
      return {
        id: prepared.id,
        title: prepared.record.title || "Untitled opportunity",
        agency: prepared.record.agency || "",
        url: bestUrl(prepared.record),
        deadline: deadlineText(prepared.record),
        closeIn: prepared.closeIn,
        closingSoon: prepared.closeIn !== null && prepared.closeIn >= 0 && prepared.closeIn <= 21,
        postedDate: cleanDate(prepared.record.posted_date || prepared.record.source_first_seen_date),
        updatedDate: cleanDate(prepared.record.last_updated),
        new: prepared.freshAge !== null && prepared.freshAge <= 14,
        broad: prepared.isBroad,
        relevanceScore,
        recencyBoost: recencyBoost(prepared),
        rankScore: relevanceScore * recencyBoost(prepared),
        fits,
        themeHits,
        record: prepared.record,
      };
    }

    function matchTeam(profiles, activeLabels = null) {
      if (!Array.isArray(profiles) || profiles.length < 2) return { themes: [], results: [] };
      const themes = buildThemes(profiles);
      const active = activeLabels
        ? themes.filter(theme => activeLabels.has(theme.label))
        : themes;
      const themeFilterActive = Boolean(activeLabels) && active.length < themes.length;
      const results = [];
      records.forEach(prepared => {
        const fits = profiles.map(profile => scoreProfile(profile, prepared));
        // A selected team is a true intersection: adding a researcher can
        // never introduce a result that does not also fit that researcher.
        if (fits.some(fit => !fit)) return;
        const themeHits = active.map(theme => ({
          label: theme.label,
          score: themeEvidence(theme, prepared),
        })).filter(hit => hit.score > 0);
        // The full-member intersection is the stable eligibility rule. Themes
        // explain and boost linked areas by default; once a user turns a chip
        // off, the remaining active chips become an explicit narrowing filter.
        if (themeFilterActive && !themeHits.length) return;
        const memberScore = fits.reduce((sum, fit) => sum + fit.score, 0);
        const themeScore = Math.min(3.2, themeHits.reduce((sum, hit) => sum + hit.score, 0));
        results.push(resultRecord(prepared, fits, memberScore + themeScore, themeHits));
      });
      results.sort((left, right) =>
        right.rankScore - left.rankScore
        || right.relevanceScore - left.relevanceScore
        || Number(right.new) - Number(left.new)
        || left.title.localeCompare(right.title));
      return { themes, results };
    }

    function matchDepartment(profiles) {
      const results = [];
      records.forEach(prepared => {
        const fits = profiles.map(profile => scoreProfile(profile, prepared)).filter(Boolean);
        if (fits.length < 2) return;
        const strongCount = fits.filter(fit => fit.strong).length;
        const scopedBroad = prepared.isBroad && fits.some(fit => fit.scopeScore > 0);
        if (strongCount < 2 && !scopedBroad) return;
        const relevance = fits.reduce((sum, fit) => sum + fit.score, 0);
        results.push(resultRecord(prepared, fits, relevance, []));
      });
      results.sort((left, right) =>
        right.rankScore - left.rankScore
        || right.fits.length - left.fits.length
        || left.title.localeCompare(right.title));
      return results;
    }

    function matchProfile(profile) {
      return records.map(prepared => {
        const fit = scoreProfile(profile, prepared);
        return fit ? resultRecord(prepared, [fit], fit.score, []) : null;
      }).filter(Boolean).sort((left, right) => right.rankScore - left.rankScore);
    }

    return Object.freeze({
      records,
      buildThemes,
      scoreProfile,
      matchTeam,
      matchDepartment,
      matchProfile,
    });
  }

  globalThis.FUNDING_TEAM_MATCHER = Object.freeze({ create, recordIsCurrent, nonFundingReason });
})();
