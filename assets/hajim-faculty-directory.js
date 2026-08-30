(() => {
  "use strict";

  const MAX_RESULTS = 12;
  const LOAD_TIMEOUT_MS = 12_000;
  const EXPECTED_COUNTS = Object.freeze({
    source_profiles: 156,
    retained_profiles: 1,
    searchable_profiles: 157,
    controlled_terms: 202,
    primary_mappings: 460,
    supporting_mappings: 94,
    matching_available: 157,
    curated_profiles: 13,
  });
  const SOURCE_SHA256 = "4cc24fad355c5716a462b93e1f60d0c7d55d9368d7cfede330ff41daa36af130";
  let loaded = null;
  let pending = null;

  function normalize(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function pageGenerationId(documentRef = globalThis.document) {
    return String(
      documentRef?.querySelector('meta[name="hajim-faculty-directory-generation"]')?.content || "",
    ).trim();
  }

  function assetUrl(generationId, base = "data/hajim-faculty-directory.js") {
    if (!/^[a-f0-9]{64}$/.test(String(generationId || ""))) {
      throw new Error("The Hajim faculty directory generation is invalid.");
    }
    return `${base}?v=${generationId}`;
  }

  function countMappings(profiles, field) {
    return profiles.reduce((sum, profile) => sum + (Array.isArray(profile?.[field]) ? profile[field].length : 0), 0);
  }

  function validate(payload, expectedGeneration) {
    if (!payload || payload.schema_version !== 1) {
      throw new Error("The Hajim faculty directory format is incompatible.");
    }
    if (payload.generation_identity !== expectedGeneration) {
      throw new Error("The Hajim faculty directory does not match this page generation.");
    }
    if (payload.source_sha256 !== SOURCE_SHA256) {
      throw new Error("The Hajim faculty directory is not from the reviewed workbook.");
    }
    const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
    const terms = Array.isArray(payload.terms) ? payload.terms : [];
    const actualCounts = {
      source_profiles: Number(payload.counts?.source_profiles),
      retained_profiles: Number(payload.counts?.retained_profiles),
      searchable_profiles: profiles.length,
      controlled_terms: terms.length,
      primary_mappings: countMappings(profiles, "primary"),
      supporting_mappings: countMappings(profiles, "context"),
      matching_available: profiles.filter(profile => profile?.matching_available === true).length,
      curated_profiles: profiles.filter(profile => profile?.curated_profile_key).length,
    };
    Object.entries(EXPECTED_COUNTS).forEach(([key, value]) => {
      if (actualCounts[key] !== value || Number(payload.counts?.[key]) !== value) {
        throw new Error(`The Hajim faculty directory count ${key} is inconsistent.`);
      }
    });
    const profileIds = new Set();
    profiles.forEach(profile => {
      if (!profile?.id || !profile?.name || profileIds.has(profile.id)) {
        throw new Error("The Hajim faculty directory contains a duplicate or incomplete identity.");
      }
      profileIds.add(profile.id);
      if (!Array.isArray(profile.primary) || !Array.isArray(profile.context)) {
        throw new Error(`The Hajim faculty directory mappings are incomplete for ${profile.name}.`);
      }
    });
    if (profiles.some(profile => /melodie\s+(?:i\.?\s+)?lawton/i.test(profile.name))) {
      throw new Error("The Hajim faculty directory contains a removed identity.");
    }
    const termIds = new Set(terms.map(term => term?.id));
    if (termIds.size !== terms.length || termIds.has(undefined)) {
      throw new Error("The Hajim faculty directory controlled terms are invalid.");
    }
    profiles.forEach(profile => {
      [...profile.primary, ...profile.context].forEach(mapping => {
        if (!termIds.has(mapping?.term_id) || !mapping?.source_phrase || !mapping?.evidence) {
          throw new Error(`The Hajim faculty directory evidence is incomplete for ${profile.name}.`);
        }
      });
    });
    return payload;
  }

  function buildIndex(payload) {
    const terms = new Map(payload.terms.map(term => [term.id, term]));
    const profiles = payload.profiles.map(profile => {
      const mappingText = [...profile.primary, ...profile.context].flatMap(mapping => {
        const term = terms.get(mapping.term_id) || {};
        return [term.label, term.category, ...(term.aliases || []), mapping.source_phrase, mapping.evidence];
      });
      const searchText = normalize([
        profile.name,
        profile.unit,
        profile.relationship,
        profile.appointments,
        ...(profile.rosters || []),
        profile.summary,
        ...mappingText,
      ].join(" "));
      return Object.freeze({ ...profile, search_text: searchText });
    });
    return Object.freeze({
      ...payload,
      terms,
      profiles: Object.freeze(profiles),
      profilesById: new Map(profiles.map(profile => [profile.id, profile])),
    });
  }

  function load({
    documentRef = globalThis.document,
    generationId = pageGenerationId(documentRef),
    baseUrl = "data/hajim-faculty-directory.js",
    timeoutMs = LOAD_TIMEOUT_MS,
  } = {}) {
    if (loaded) {
      if (loaded.generation_identity !== generationId) {
        return Promise.reject(new Error("A different Hajim faculty directory generation is already loaded."));
      }
      return Promise.resolve(loaded);
    }
    if (pending) return pending;
    pending = new Promise((resolve, reject) => {
      const script = documentRef.createElement("script");
      const url = assetUrl(generationId, baseUrl);
      let settled = false;
      const finish = (error, payload) => {
        if (settled) return;
        settled = true;
        globalThis.clearTimeout(timer);
        script.onload = null;
        script.onerror = null;
        pending = null;
        if (error) {
          script.remove();
          delete globalThis.HAJIM_FACULTY_DIRECTORY;
          reject(error);
          return;
        }
        loaded = buildIndex(payload);
        resolve(loaded);
      };
      const timer = globalThis.setTimeout(() => {
        finish(new Error("The Hajim faculty directory took too long to load."));
      }, Math.max(1, Number(timeoutMs) || LOAD_TIMEOUT_MS));
      script.async = true;
      script.src = url;
      script.dataset.hajimFacultyDirectory = generationId;
      script.onload = () => {
        try {
          finish(null, validate(globalThis.HAJIM_FACULTY_DIRECTORY, generationId));
        } catch (error) {
          finish(error);
        }
      };
      script.onerror = () => finish(new Error("The Hajim faculty directory could not be loaded."));
      documentRef.head.appendChild(script);
    });
    return pending;
  }

  function score(profile, normalizedQuery, tokens) {
    if (!tokens.every(token => profile.search_text.includes(token))) return -1;
    const name = normalize(profile.name);
    const unit = normalize(profile.unit);
    if (name === normalizedQuery) return 120;
    if (name.startsWith(normalizedQuery)) return 100;
    if (name.includes(normalizedQuery)) return 85;
    if (unit.startsWith(normalizedQuery)) return 65;
    if (unit.includes(normalizedQuery)) return 55;
    const phraseBonus = profile.search_text.includes(normalizedQuery) ? 20 : 0;
    return 30 + phraseBonus + tokens.length;
  }

  function search(directory, query, { selectedIds = [], limit = MAX_RESULTS } = {}) {
    const normalizedQuery = normalize(query);
    if (normalizedQuery.length < 2) return [];
    const tokens = normalizedQuery.split(" ").filter(Boolean);
    if (!tokens.length) return [];
    const selected = new Set(selectedIds);
    return directory.profiles
      .filter(profile => !selected.has(profile.id))
      .map(profile => ({ profile, score: score(profile, normalizedQuery, tokens) }))
      .filter(item => item.score >= 0)
      .sort((left, right) => right.score - left.score || left.profile.name.localeCompare(right.profile.name))
      .slice(0, Math.min(MAX_RESULTS, Math.max(0, Number(limit) || MAX_RESULTS)))
      .map(item => item.profile);
  }

  function matchingProfile(directory, profile, curatedFaculty = {}) {
    if (!profile?.matching_available) return null;
    if (profile.curated_profile_key) {
      const curated = curatedFaculty[profile.curated_profile_key];
      if (!curated) throw new Error(`The curated matching profile for ${profile.name} is unavailable.`);
      return {
        name: profile.name,
        key_terms: [...(curated.key_terms || [])],
        research_summary: curated.research_summary || "",
        domains: [...(curated.domains || [])],
        faculty_evidence: {
          authority: "curated_cheme",
          directory_id: profile.id,
          primary: profile.primary,
          context: profile.context,
        },
      };
    }
    const primary = profile.primary.map(mapping => ({
      ...mapping,
      term: directory.terms.get(mapping.term_id)?.label || "",
    })).filter(mapping => mapping.term);
    return {
      name: profile.name,
      key_terms: primary.map(mapping => mapping.term),
      domains: [],
      faculty_evidence: {
        authority: "reviewed_primary_anchors",
        directory_id: profile.id,
        primary,
        context: profile.context.map(mapping => ({
          ...mapping,
          term: directory.terms.get(mapping.term_id)?.label || "",
        })),
      },
    };
  }

  function resetForTests() {
    loaded = null;
    pending = null;
    delete globalThis.HAJIM_FACULTY_DIRECTORY;
  }

  globalThis.FUNDING_HAJIM_FACULTY = Object.freeze({
    MAX_RESULTS,
    SOURCE_SHA256,
    EXPECTED_COUNTS,
    normalize,
    pageGenerationId,
    assetUrl,
    validate,
    buildIndex,
    load,
    search,
    matchingProfile,
    resetForTests,
  });
})();
