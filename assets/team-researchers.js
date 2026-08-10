(() => {
  "use strict";

  const STORAGE_KEY = "funding-finder.external-researchers.v1";
  const MAX_EXTERNAL = 4;
  const MIN_KEYWORDS = 3;
  const MAX_KEYWORDS = 8;
  const BROAD_RE = /broad agency announcement|\bbaa\b|continuation of solicitation|office of science|long[\s-]?range|research announcement|\broses\b|omnibus|unsolicited proposal/i;
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
    "Environmental science": ["environ", "pollut", "emission", "sustainab", "remediation", "air quality"],
    Water: ["desalinat", "wastewater", "water treatment", "drinking water", "water purification", "water resources"],
    "Public health": ["clinical trial", "drug delivery", "therapeutic", "pharmaceutic", "vaccine", "diagnostic"],
    "Climate change": ["climate", "greenhouse gas", "global warming"],
    "Space and aeronautics": ["aerospace", "spacecraft", "aeronautic", "propulsion", "in situ resource"],
  });

  function cleanText(value, maximum) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
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
      if (!keyword || seen.has(key)) continue;
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
      output.push({ id, name, keywords });
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

  function buildMatches(profile, catalogData, searchApi, nicheTopics = []) {
    const records = Array.isArray(catalogData?.opportunities)
      ? catalogData.opportunities
      : [];
    const postings = catalogData?.search_index?.postings || {};
    if (!records.length || !searchApi?.tokenize || !searchApi?.expandTerms) return [];

    const hitsByDocument = new Map();
    for (const keyword of profile.keywords || []) {
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
        const terms = hitsByDocument.get(documentId) || [];
        terms.push(keyword);
        hitsByDocument.set(documentId, terms);
      });
    }

    const domains = new Set(inferDomains(profile.keywords || []));
    const niche = new Set(nicheTopics || []);
    const matches = [];
    records.forEach((record, documentId) => {
      const hitTerms = hitsByDocument.get(documentId) || [];
      const topics = new Set(record.topic_areas || []);
      const sharedDomains = [...domains].filter(domain => topics.has(domain));
      const nicheHits = sharedDomains.filter(domain => niche.has(domain));
      const broad = BROAD_RE.test(`${record.title || ""} ${(record.description || "").slice(0, 400)}`);
      const broadHits = broad ? sharedDomains : [];
      const strong = Boolean(hitTerms.length || nicheHits.length);
      if (!strong && !broadHits.length) return;
      const sharedTopics = strong ? nicheHits : broadHits;
      matches.push({
        id: record.opportunity_id || record.opportunity_number || record.title,
        title: record.title || "Untitled opportunity",
        agency: record.agency || "",
        url: bestUrl(record),
        deadline: deadlineText(record),
        tier: strong ? "strong" : "broad",
        terms: hitTerms,
        shared_topics: sharedTopics,
        score: (strong ? 2 : 0) + hitTerms.length + sharedTopics.length,
      });
    });

    matches.sort((left, right) =>
      (left.tier === "strong" ? 0 : 1) - (right.tier === "strong" ? 0 : 1)
      || right.score - left.score
      || left.title.localeCompare(right.title),
    );
    return matches;
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
  });
})();
