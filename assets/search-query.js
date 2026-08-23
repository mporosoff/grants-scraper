(() => {
  "use strict";

  const QUERY_API_CONTRACT_VERSION = 3;

  // PFAS notices are often written around the problem being addressed instead
  // of naming an individual compound. These terms keep searches useful against
  // catalogs that describe water contamination and remediation but omit PFAS.
  const PFAS_CONCEPT = "persistent contaminant contamination pollution remediation groundwater drinking wastewater water treatment purification";
  // Keep target materials separate from methods. The previous REE expansion
  // included generic words such as "processing" and "critical mineral", which
  // allowed diplomacy, education, and unrelated process notices to satisfy an
  // REE query without mentioning a rare-earth material at all.
  const RARE_EARTH_CONCEPT = "ree rare earth element lanthanide scandium yttrium cerium dysprosium erbium europium gadolinium holmium lanthanum lutetium neodymium praseodymium promethium samarium terbium thulium ytterbium";
  const RARE_EARTH_QUERY_MEMBERS = new Set([
    "ree", "rees", "lanthanide", "scandium", "yttrium", "cerium", "dysprosium",
    "erbium", "europium", "gadolinium", "holmium", "lanthanum", "lutetium",
    "neodymium", "praseodymium", "promethium", "samarium", "terbium", "thulium",
    "ytterbium",
  ]);
  const RARE_EARTH_EVIDENCE = Object.freeze([
    Object.freeze(["ree"]),
    Object.freeze(["rare", "earth"]),
    Object.freeze(["lanthanide"]),
    Object.freeze(["scandium"]),
    Object.freeze(["yttrium"]),
    ...[
      "cerium", "dysprosium", "erbium", "europium", "gadolinium", "holmium",
      "lanthanum", "lutetium", "neodymium", "praseodymium", "promethium",
      "samarium", "terbium", "thulium", "ytterbium",
    ].map(term => Object.freeze([term])),
  ]);
  const IONIC_LIQUID_CONCEPT = "ionic liquid solvent extraction separation membrane hydrometallurgy leaching";
  const IONIC_LIQUID_EVIDENCE = Object.freeze([
    Object.freeze(["ionic", "liquid"]),
    Object.freeze(["solvent", "extraction"]),
    Object.freeze(["solvent", "separation"]),
    Object.freeze(["chemical", "separation"]),
    Object.freeze(["desalination", "purification"]),
    Object.freeze(["hydrometallurgy", "leaching"]),
    Object.freeze(["ion", "exchange"]),
  ]);
  const SEPARATION_METHOD_CONCEPT = "separation separate extraction extract processing recovery recover purification solvent hydrometallurgy leaching ion exchange membrane refining";
  const SEPARATION_QUERY_TERMS = new Set([
    "separation", "extraction", "processing", "recovery", "purification",
    "hydrometallurgy", "leach", "refin", "recycl",
  ]);
  const MATERNAL_HEALTH_CONCEPT = "maternal maternity obstetric mortality morbidity pregnancy childbirth";
  const RURAL_CARE_CONCEPT = "rural community communities area network access delivery care";
  const DROUGHT_RESILIENCE_CONCEPT = "drought tolerant tolerance resilience resilient abiotic stress trait";
  const CROP_GENETICS_CONCEPT = "crop plant genetics genetic genomics genomic breeding cultivar germplasm trait";
  const ENERGY_STORAGE_CONCEPT = "energy storage battery grid-scale grid technology technologies";
  const LONG_DURATION_CONCEPT = "long duration long-duration seasonal extended storage";
  const FOUNDATION_MODEL_CONCEPT = "foundation model models composable modular generative ai";
  const SECURITY_RESILIENCE_CONCEPT = "secure security cybersecurity adversarial robustness robust resilience resilient attack mitigation trustworthy";
  const EARTH_SYSTEM_CONCEPT = "earth system sun-earth geospace coupled";
  const CHEMICAL_PROCESS_CONCEPT = "chemical element elements process processes chemistry cycling";
  const MEMBRANE_TREATMENT_CONCEPT = "membrane treatment purification separation filtration water";
  const RARE_DISEASE_MOLECULAR_CONCEPT = "rare disease molecular genetic genetics genomic genomics diagnosis gene variant";
  const EDUCATION_INNOVATION_CONCEPT = "innovation innovative catalyst change strategy transformation";
  const STUDENT_SUCCESS_CONCEPT = "student success retention graduation pathway education stem";
  const SINGLE_CELL_BIOLOGY_CONCEPT = "single cell single-cell cellular physiology biology";
  const CANCER_IMMUNOLOGY_CONCEPT = "cancer immunology immune oncology tumor";
  const ELECTROCATALYSIS_CONCEPT = "electrocatalysis electrocatalytic electrochemical redox catalysis electrode";
  const AMMONIA_SYNTHESIS_CONCEPT = "ammonia synthesis nitrogen reduction chemical production";
  const HIGH_TEMPERATURE_MATERIALS_CONCEPT = "high temperature thermal composite composites structural materials";
  const HYPERSONIC_ENVIRONMENT_CONCEPT = "hypersonic extreme dynamic thermal environment";
  const MARITIME_CONCEPT = "maritime marine naval navy ocean sea";
  const NAVIGATION_CONCEPT = "navigation pnt";
  const QUANTUM_SENSING_CONCEPT = "quantum sensing";
  const AGENCY_QUALIFIER_TERMS = new Set(["doe", "nsf", "nasa", "nih"]);
  const BROAD_CALL_CONCEPT = "broad agency announcement baa long range office wide open scope";
  const BROAD_CALL_EVIDENCE = Object.freeze([
    Object.freeze(["broad", "agency", "announcement"]),
    Object.freeze(["baa"]),
    Object.freeze(["long", "range"]),
    Object.freeze(["office", "wide"]),
    Object.freeze(["open", "scope"]),
  ]);
  const BASIC_ENERGY_SCIENCES_CONCEPT = "basic energy science bes";
  const BASIC_ENERGY_SCIENCES_EVIDENCE = Object.freeze([
    Object.freeze(["basic", "energy", "science"]),
    Object.freeze(["bes"]),
  ]);
  // "Catalyst" is highly polysemous in funding notices: programs describe
  // themselves as a catalyst for change, and BioData Catalyst is a platform.
  // Treat the scientific word family as one concept, but require chemistry or
  // reaction evidence before a literal "catalyst" occurrence can satisfy it.
  const CATALYSIS_CONCEPT = "catalyst catalysis catalytic electrocatalysis photocatalysis thermocatalysis";
  const CATALYST_DESIGN_CONCEPT = "catalyst catalysis catalytic design discovery optimization screening engineering";
  const CATALYSIS_EVIDENCE = Object.freeze([
    Object.freeze(["catalysi"]),
    Object.freeze(["catalytic"]),
    Object.freeze(["electrocatalysi"]),
    Object.freeze(["photocatalysi"]),
    Object.freeze(["thermocatalysi"]),
  ]);
  const CATALYST_CONTEXT_WINDOWS = Object.freeze([
    "chemical", "reaction", "reactor", "electrochemical", "heterogeneous",
    "homogeneous", "synthesis", "enzyme", "design", "characterization",
  ].map(term => Object.freeze({
    terms: Object.freeze(["catalyst", term]),
    maximumSpan: 6,
  })));
  const AI_CONCEPT = "ai artificial intelligence machine learning";
  const HIGH_PERFORMANCE_COMPUTING_CONCEPT = "high performance computing hpc supercomputing compute computational";
  const AI_EVIDENCE = Object.freeze([
    Object.freeze(["ai"]),
    Object.freeze(["artificial", "intelligence"]),
    Object.freeze(["machine", "learn"]),
  ]);

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
    extraction: "separation recovery processing purification",
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
      || term === "extraction"
    )),
  );
  const PFAS_DESCRIPTOR_TERMS = new Set([
    "acid", "chemical", "compound", "substance", "sulfonate",
  ]);

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
    biology: ["biological", "biochemical", "biotechnology"],
    biological: ["biology"],
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

  function conceptGroup(source, concept, directTermSet, options = {}) {
    const literalTerms = new Set(options.literalTerms || [source]);
    const weightedTerms = new Map();
    tokenize(concept).forEach(term => {
      const direct = literalTerms.has(term) || directTermSet.has(term);
      weightedTerms.set(term, direct ? 1 : .86);
    });
    if (source && !/\s/.test(source) && !weightedTerms.has(source)) weightedTerms.set(source, 1);
    return {
      source,
      terms: [...weightedTerms].map(([term, weight]) => ({ term, weight })),
      minimumEvidence: Number(options.minimumEvidence || 1),
      evidenceAlternatives: options.evidenceAlternatives || null,
      evidencePhrases: options.evidencePhrases || null,
      evidenceWindows: options.evidenceWindows || null,
      evidenceMode: options.evidenceMode || "all",
      requiredUnlessTopic: options.requiredUnlessTopic || "",
      requiredAlways: options.requiredAlways === true,
      conceptId: options.conceptId || "",
      role: options.role || "",
      required: options.required === true,
      evidencePolicy: options.evidencePolicy || "",
      strictEvidence: options.strictEvidence !== false,
      saturateConcept: options.saturateConcept === true,
      expansion: {
        kind: "scientific_concept",
        phrase: options.phrase || concept,
        confidence: 1,
        basis: options.basis || "deterministic scientific phrase",
      },
    };
  }

  function hasIonicLiquidContext(value, directTermSet, context = "") {
    if (/ionic[\s-]+liquids?/i.test(value)) return true;
    if (/ionic[\s-]+liquids?|solvent extraction/i.test(context)) return true;
    if (directTermSet.has("rare") && directTermSet.has("earth")) return true;
    return [
      "ree", "lanthanide", "scandium", "yttrium", "extraction", "separation",
      "recovery", "solvent", "leaching", "hydrometallurgy",
    ].some(term => directTermSet.has(term));
  }

  function expandGroups(value, hasIndexedTerm = () => false, options = {}) {
    const searchV2 = options.searchV2 === true;
    const normalizedValue = normalizeText(value);
    const hasDottedRee = /\bR\s*\.\s*E\s*\.\s*E(?:\s*\.)?s?(?![A-Za-z0-9])/i.test(normalizedValue);
    let directTerms = [...new Set(tokenize(value))];
    if (searchV2 && hasDottedRee) {
      directTerms = [...new Set(directTerms.map(term => (
        /^r\.e\.e(?:s)?$/i.test(term) ? "ree" : term
      )))];
      if (!directTerms.includes("ree")) directTerms.unshift("ree");
    }
    const directTermSet = new Set(directTerms);
    const hasPfasAlias = directTerms.some(term => QUERY_ALIASES[term] === PFAS_CONCEPT);
    const hasCriticalMineralPhrase = searchV2
      && /\bcritical[\s-]+minerals?\b/i.test(normalizedValue);
    const hasQuantumSensingPhrase = searchV2
      && /\bquantum[\s-]+sens(?:e|ing|ors?)\b/i.test(normalizedValue);
    const hasRareEarthPhrase = /\brare[\s-]+earth(?:[\s-]+elements?)?\b/i.test(normalizedValue);
    const hasRareEarthAcronym = searchV2 && (
      hasDottedRee || /\bREEs?\b/i.test(normalizedValue)
    );
    const hasRareEarthQuery = hasRareEarthPhrase
      || hasRareEarthAcronym
      || directTerms.some(term => RARE_EARTH_QUERY_MEMBERS.has(term));
    const hasIonicLiquidPhrase = /\bionic[\s-]+liquids?\b/i.test(normalizedValue);
    const hasSolventExtractionPhrase = searchV2
      && /\bsolvent[\s-]+extractions?\b/i.test(normalizedValue);
    const hasIonExchangePhrase = searchV2
      && /\bion[\s-]+exchange\b/i.test(normalizedValue);
    const hasResourceRecoveryPhrase = searchV2
      && /\bresource[\s-]+recovery\b/i.test(normalizedValue);
    const hasMaternalHealthPhrase = searchV2
      && /\bmaternal[\s-]+(?:mortality|morbidity|health)\b/i.test(normalizedValue);
    const hasRuralContextPhrase = searchV2
      && /\brural\b/i.test(normalizedValue)
      && /\b(?:communities?|areas?|care|maternity|obstetrics?|networks?|access)\b/i.test(normalizedValue);
    const hasDroughtResiliencePhrase = searchV2
      && /\bdrought\b/i.test(normalizedValue)
      && /\b(?:toleran(?:t|ce)|resilien(?:t|ce)|stress|trait)\b/i.test(normalizedValue);
    const hasCropGeneticsPhrase = searchV2
      && /\b(?:crops?|plants?)\b/i.test(normalizedValue)
      && /\b(?:genetics?|genomics?|breeding|traits?)\b/i.test(normalizedValue);
    const hasLongDurationPhrase = searchV2
      && /\blong[\s-]+duration\b/i.test(normalizedValue);
    const hasEnergyStoragePhrase = searchV2
      && /\benergy[\s-]+storage\b/i.test(normalizedValue);
    const hasFoundationModelPhrase = searchV2
      && /\bfoundation[\s-]+models?\b/i.test(normalizedValue);
    const hasModelSecurityContext = searchV2
      && hasFoundationModelPhrase
      && /\b(?:secure|security|cybersecurity|adversarial|robust(?:ness)?|resilien(?:t|ce)|trustworthy)\b/i.test(normalizedValue);
    const hasArtificialIntelligencePhrase = searchV2
      && /\bartificial[\s-]+intelligence\b/i.test(normalizedValue);
    const hasHighPerformanceComputingPhrase = searchV2
      && /\bhigh[\s-]+performance[\s-]+comput(?:e|ing)\b/i.test(normalizedValue);
    const hasEarthSystemPhrase = searchV2
      && /\b(?:sun[\s-]+earth|earth[\s-]+system)\b/i.test(normalizedValue);
    const hasChemicalElementsPhrase = searchV2
      && /\bchemical[\s-]+elements?\b/i.test(normalizedValue);
    const hasMembraneTreatmentPhrase = searchV2
      && /\bmembranes?\b/i.test(normalizedValue)
      && /\b(?:treatment|purification|separation|filtration)\b/i.test(normalizedValue);
    const hasCatalystDesignPhrase = searchV2
      && /\b(?:catalyst|catalysis|catalytic)\b/i.test(normalizedValue)
      && /\b(?:design|discovery|optimization|screening)\b/i.test(normalizedValue);
    const hasRareDiseaseMolecularPhrase = searchV2
      && /\brare[\s-]+diseases?\b/i.test(normalizedValue)
      && /\b(?:molecular|genetics?|genomics?|elements?)\b/i.test(normalizedValue);
    const hasInnovationCatalystPhrase = searchV2
      && /\binnovation[\s-]+catalyst\b/i.test(normalizedValue);
    const hasStudentSuccessPhrase = searchV2
      && /\bstudents?[\s-]+success\b/i.test(normalizedValue);
    const hasSingleCellPhrase = searchV2
      && /\bsingle[\s-]+cell\b/i.test(normalizedValue);
    const hasCancerImmunologyPhrase = searchV2
      && /\bcancer\b/i.test(normalizedValue)
      && /\b(?:immunology|immune|immunotherapy)\b/i.test(normalizedValue);
    const hasElectrocatalyticAmmoniaPhrase = searchV2
      && /\belectrocatal\w*\b/i.test(normalizedValue)
      && /\bammonia\b/i.test(normalizedValue);
    const hasAmmoniaSynthesisPhrase = searchV2
      && /\bammonia\b/i.test(normalizedValue)
      && /\bsynth(?:esis|esize|etic)\b/i.test(normalizedValue);
    const hasHighTemperatureCompositesPhrase = searchV2
      && /\bhigh[\s-]+temperature\b/i.test(normalizedValue)
      && /\bcomposites?\b/i.test(normalizedValue);
    const hasHypersonicEnvironment = searchV2
      && /\bhypersonic\b/i.test(normalizedValue)
      && hasHighTemperatureCompositesPhrase;
    const hasBroadCallPhrase = /\bbroad[\s-]+agency[\s-]+announcements?\b|\bBAAs?\b/i.test(normalizedValue);
    const hasBasicEnergySciences = /\bbasic[\s-]+energy[\s-]+sciences?\b|\bBES\b/i.test(normalizedValue);
    // IL/ILs is far too ambiguous to expand globally. It is interpreted as
    // ionic liquid only when the query or local researcher profile also
    // supplies separations/solvent/rare-earth context.
    const hasIlAbbreviation = /\bILs?\b/i.test(normalizedValue)
      && hasIonicLiquidContext(normalizedValue, directTermSet, options.context || "");
    const uppercaseTerms = new Set(
      (normalizeText(value).match(/\b[A-Z][A-Z0-9]{2,8}s?\b/g) || [])
        .map(normalizeToken),
    );
    let acronymAttempts = 0;
    const emittedConcepts = new Set();
    return directTerms.flatMap(term => {
      if (hasArtificialIntelligencePhrase && ["artificial", "intelligence"].includes(term)) {
        if (emittedConcepts.has("artificial-intelligence")) return [];
        emittedConcepts.add("artificial-intelligence");
        return [conceptGroup("artificial intelligence", AI_CONCEPT, directTermSet, {
          literalTerms: ["artificial", "intelligence"],
          minimumEvidence: 2,
          evidencePhrases: ["artificial intelligence", "machine learning"],
          conceptId: "artificial-intelligence",
          role: "method",
          required: true,
          evidencePolicy: "protected_ai",
          saturateConcept: true,
          phrase: "artificial intelligence and machine learning",
          basis: "controlled technical compound",
        })];
      }
      if (hasHighPerformanceComputingPhrase && ["high", "performance", "comput"].includes(term)) {
        if (emittedConcepts.has("high-performance-computing")) return [];
        emittedConcepts.add("high-performance-computing");
        return [conceptGroup("high performance computing", HIGH_PERFORMANCE_COMPUTING_CONCEPT, directTermSet, {
          literalTerms: ["high", "performance", "comput"],
          minimumEvidence: 2,
          evidencePhrases: ["high performance computing", "high-performance computing", "supercomputing"],
          conceptId: "high-performance-computing",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "high-performance computing",
          basis: "bounded computing technology compound",
        })];
      }
      if (hasQuantumSensingPhrase && ["quantum", "sens"].includes(term)) {
        if (emittedConcepts.has("quantum-sensing")) return [];
        emittedConcepts.add("quantum-sensing");
        return [conceptGroup("quantum sensing", QUANTUM_SENSING_CONCEPT, directTermSet, {
          literalTerms: ["quantum", "sens"],
          minimumEvidence: 2,
          conceptId: "quantum-sensing",
          role: "method",
          required: true,
          phrase: "quantum sensing",
          basis: "controlled technical compound",
        })];
      }
      if (hasCriticalMineralPhrase && ["critical", "mineral"].includes(term)) {
        if (emittedConcepts.has("critical-minerals")) return [];
        emittedConcepts.add("critical-minerals");
        return [conceptGroup("critical mineral", "critical mineral", directTermSet, {
          literalTerms: ["critical", "mineral"],
          minimumEvidence: 2,
          evidencePhrases: ["critical mineral"],
          conceptId: "critical-minerals",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          phrase: "critical minerals",
          basis: "controlled technical compound",
        })];
      }
      if (hasCriticalMineralPhrase && term === "workforce") {
        return [conceptGroup(term, "workforce worker", directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          conceptId: "literal:workforce",
          role: "application_or_context",
          required: true,
          phrase: "workforce or workers",
          basis: "bounded workforce vocabulary",
        })];
      }
      if (hasRareDiseaseMolecularPhrase && ["rare", "disease", "molecular", "genetic", "genomic", "element"].includes(term)) {
        if (emittedConcepts.has("rare-disease-molecular-genomics")) return [];
        emittedConcepts.add("rare-disease-molecular-genomics");
        return [conceptGroup("rare disease molecular genomics", RARE_DISEASE_MOLECULAR_CONCEPT, directTermSet, {
          literalTerms: ["rare", "disease", "molecular", "genetic", "genomic", "element"],
          minimumEvidence: 2,
          evidencePhrases: ["rare disease", "rare genetic disorder"],
          evidenceWindows: [
            { terms: ["rare", "disease", "molecular"], maximumSpan: 30 },
            { terms: ["rare", "disease", "genetic"], maximumSpan: 30 },
            { terms: ["rare", "disease", "genomic"], maximumSpan: 30 },
          ],
          conceptId: "rare-disease-molecular-genomics",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "rare-disease molecular genomics",
          basis: "bounded disease and molecular-method compound",
        })];
      }
      if (hasInnovationCatalystPhrase && ["innovation", "catalyst"].includes(term)) {
        if (emittedConcepts.has("education-innovation")) return [];
        emittedConcepts.add("education-innovation");
        return [conceptGroup("education innovation", EDUCATION_INNOVATION_CONCEPT, directTermSet, {
          literalTerms: ["innovation", "catalyst"],
          minimumEvidence: 1,
          conceptId: "education-innovation",
          role: "application_or_context",
          required: true,
          saturateConcept: true,
          phrase: "education innovation and change",
          basis: "bounded non-chemical catalyst compound",
        })];
      }
      if (hasStudentSuccessPhrase && ["student", "success"].includes(term)) {
        if (emittedConcepts.has("student-success")) return [];
        emittedConcepts.add("student-success");
        return [conceptGroup("student success", STUDENT_SUCCESS_CONCEPT, directTermSet, {
          literalTerms: ["student", "success"],
          minimumEvidence: 2,
          evidencePhrases: ["student success"],
          conceptId: "student-success",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "student success and retention",
          basis: "bounded education outcome compound",
        })];
      }
      if (hasSingleCellPhrase && ["single", "cell", "single-cell"].includes(term)) {
        if (emittedConcepts.has("single-cell-biology")) return [];
        emittedConcepts.add("single-cell-biology");
        return [conceptGroup("single cell biology", SINGLE_CELL_BIOLOGY_CONCEPT, directTermSet, {
          literalTerms: ["single", "cell", "single-cell"],
          minimumEvidence: 1,
          evidencePhrases: ["single cell", "single-cell", "cellular physiology"],
          conceptId: "single-cell-biology",
          role: "method",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "single-cell and cellular biology",
          basis: "bounded cellular-method relationship",
        })];
      }
      if (hasCancerImmunologyPhrase && ["cancer", "immunology", "immune", "immunotherapy"].includes(term)) {
        if (emittedConcepts.has("cancer-immunology")) return [];
        emittedConcepts.add("cancer-immunology");
        return [conceptGroup("cancer immunology", CANCER_IMMUNOLOGY_CONCEPT, directTermSet, {
          literalTerms: ["cancer", "immunology", "immune", "immunotherapy"],
          minimumEvidence: 2,
          evidencePhrases: ["cancer immunology", "cancer immune", "cancer biology"],
          conceptId: "cancer-immunology",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "cancer immunology",
          basis: "bounded disease and mechanism compound",
        })];
      }
      if (hasElectrocatalyticAmmoniaPhrase && ["electrocatalytic", "electrocatalysi"].includes(term)) {
        if (emittedConcepts.has("electrocatalysis")) return [];
        emittedConcepts.add("electrocatalysis");
        return [conceptGroup("electrocatalysis", ELECTROCATALYSIS_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          conceptId: "electrocatalysis",
          role: "method",
          required: true,
          saturateConcept: true,
          phrase: "electrocatalysis and electrochemical redox",
          basis: "bounded electrochemical method family",
        })];
      }
      if (hasAmmoniaSynthesisPhrase && ["ammonia", "synthesi", "synthesize", "synthetic"].includes(term)) {
        if (emittedConcepts.has("ammonia-synthesis")) return [];
        emittedConcepts.add("ammonia-synthesis");
        return [conceptGroup("ammonia synthesis", AMMONIA_SYNTHESIS_CONCEPT, directTermSet, {
          literalTerms: ["ammonia", "synthesi", "synthesize", "synthetic"],
          minimumEvidence: 2,
          evidencePhrases: ["ammonia synthesis"],
          conceptId: "ammonia-synthesis",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "ammonia synthesis",
          basis: "bounded chemical target and operation",
        })];
      }
      if (hasHighTemperatureCompositesPhrase && ["high", "temperature", "composite"].includes(term)) {
        if (emittedConcepts.has("high-temperature-materials")) return [];
        emittedConcepts.add("high-temperature-materials");
        return [conceptGroup("high temperature composites", HIGH_TEMPERATURE_MATERIALS_CONCEPT, directTermSet, {
          literalTerms: ["high", "temperature", "composite"],
          minimumEvidence: 2,
          conceptId: "high-temperature-materials",
          role: "target",
          required: true,
          evidencePolicy: "protected_high_temperature_composites",
          evidencePolicy: "protected_high_temperature_composites",
          saturateConcept: true,
          phrase: "high-temperature composite materials",
          basis: "bounded materials compound",
        })];
      }
      if (hasHypersonicEnvironment && term === "hypersonic") {
        if (emittedConcepts.has("hypersonic-environment")) return [];
        emittedConcepts.add("hypersonic-environment");
        return [conceptGroup("hypersonic environment", HYPERSONIC_ENVIRONMENT_CONCEPT, directTermSet, {
          literalTerms: ["hypersonic"],
          minimumEvidence: 1,
          conceptId: "hypersonic-environment",
          role: "application_or_context",
          required: true,
          evidencePolicy: "protected_hypersonic",
          evidencePolicy: "protected_hypersonic",
          saturateConcept: true,
          phrase: "hypersonic and extreme thermal environments",
          basis: "bounded defense environment relationship",
        })];
      }
      if (hasMaternalHealthPhrase && ["maternal", "mortality", "morbidity", "health"].includes(term)) {
        if (emittedConcepts.has("maternal-health")) return [];
        emittedConcepts.add("maternal-health");
        return [conceptGroup("maternal health", MATERNAL_HEALTH_CONCEPT, directTermSet, {
          literalTerms: ["maternal", "mortality", "morbidity", "health"],
          minimumEvidence: 1,
          evidencePhrases: ["maternal mortality", "maternal morbidity", "maternal health", "maternity"],
          conceptId: "maternal-health",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "maternal health, maternity, and obstetric outcomes",
          basis: "bounded maternal-health relationship",
        })];
      }
      if (hasRuralContextPhrase && ["rural", "community", "area", "care", "network", "access"].includes(term)) {
        if (emittedConcepts.has("rural-care-context")) return [];
        emittedConcepts.add("rural-care-context");
        return [conceptGroup("rural care", RURAL_CARE_CONCEPT, directTermSet, {
          literalTerms: ["rural", "community", "area", "care", "network", "access"],
          minimumEvidence: 1,
          evidencePhrases: ["rural care", "rural area", "rural community", "rural maternity", "rural obstetric", "rural network"],
          conceptId: "rural-care-context",
          role: "application_or_context",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "rural care delivery and access",
          basis: "bounded rural-care context",
        })];
      }
      if (hasDroughtResiliencePhrase && ["drought", "tolerant", "tolerance", "resilient", "resilience", "stress", "trait"].includes(term)) {
        if (emittedConcepts.has("drought-resilience")) return [];
        emittedConcepts.add("drought-resilience");
        return [conceptGroup("drought resilience", DROUGHT_RESILIENCE_CONCEPT, directTermSet, {
          literalTerms: ["drought", "tolerant", "tolerance", "resilient", "resilience", "stress", "trait"],
          minimumEvidence: 1,
          evidencePhrases: ["drought tolerant", "drought tolerance", "drought resilience", "abiotic stress"],
          conceptId: "drought-resilience",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "drought tolerance and abiotic-stress resilience",
          basis: "bounded plant trait relationship",
        })];
      }
      if (hasCropGeneticsPhrase && ["crop", "plant", "genetic", "genomic", "breeding", "trait"].includes(term)) {
        if (emittedConcepts.has("crop-genetics")) return [];
        emittedConcepts.add("crop-genetics");
        return [conceptGroup("crop genetics", CROP_GENETICS_CONCEPT, directTermSet, {
          literalTerms: ["crop", "plant", "genetic", "genomic", "breeding", "trait"],
          minimumEvidence: 1,
          evidencePhrases: ["crop genetics", "crop genomics", "crop breeding", "plant genetics", "plant genomics", "plant breeding"],
          conceptId: "crop-genetics",
          role: "method",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "crop genetics, genomics, and plant breeding",
          basis: "bounded organism and method family",
        })];
      }
      if (hasLongDurationPhrase && ["long", "duration"].includes(term)) {
        if (emittedConcepts.has("long-duration")) return [];
        emittedConcepts.add("long-duration");
        return [conceptGroup("long duration", LONG_DURATION_CONCEPT, directTermSet, {
          literalTerms: ["long", "duration"],
          minimumEvidence: 2,
          evidencePhrases: ["long duration"],
          conceptId: "long-duration",
          role: "application_or_context",
          required: true,
          evidencePolicy: "controlled_compound",
          phrase: "long-duration technology",
          basis: "bounded technology property",
        })];
      }
      if (hasEnergyStoragePhrase && ["energy", "storage"].includes(term)) {
        if (emittedConcepts.has("energy-storage")) return [];
        emittedConcepts.add("energy-storage");
        return [conceptGroup("energy storage", ENERGY_STORAGE_CONCEPT, directTermSet, {
          literalTerms: ["energy", "storage"],
          minimumEvidence: 2,
          evidencePhrases: ["energy storage"],
          conceptId: "energy-storage",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "energy-storage technology",
          basis: "bounded technology family",
        })];
      }
      if (hasModelSecurityContext && ["secure", "security", "cybersecurity", "adversarial", "robustness", "robust", "resilience", "resilient", "trustworthy"].includes(term)) {
        if (emittedConcepts.has("security-resilience")) return [];
        emittedConcepts.add("security-resilience");
        return [conceptGroup("security resilience", SECURITY_RESILIENCE_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          conceptId: "security-resilience",
          role: "application_or_context",
          required: true,
          evidencePolicy: "protected_ai_security",
          evidencePolicy: "protected_ai_security",
          saturateConcept: true,
          phrase: "AI security, robustness, and resilience",
          basis: "bounded AI property family",
        })];
      }
      if (hasFoundationModelPhrase && ["foundation", "model"].includes(term)) {
        if (emittedConcepts.has("foundation-models")) return [];
        emittedConcepts.add("foundation-models");
        return [conceptGroup("foundation models", FOUNDATION_MODEL_CONCEPT, directTermSet, {
          literalTerms: ["foundation", "model"],
          minimumEvidence: 2,
          evidencePhrases: ["foundation model"],
          conceptId: "foundation-models",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "AI foundation models",
          basis: "bounded AI target family",
        })];
      }
      if (hasEarthSystemPhrase && ["earth", "sun-earth", "system"].includes(term)) {
        if (emittedConcepts.has("earth-system")) return [];
        emittedConcepts.add("earth-system");
        return [conceptGroup("earth system", EARTH_SYSTEM_CONCEPT, directTermSet, {
          literalTerms: ["earth", "sun-earth", "system"],
          minimumEvidence: 2,
          evidencePhrases: ["earth system", "sun earth"],
          conceptId: "earth-system",
          role: "target",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "coupled Earth system",
          basis: "bounded scientific system compound",
        })];
      }
      if (hasChemicalElementsPhrase && ["chemical", "element"].includes(term)) {
        if (emittedConcepts.has("chemical-processes")) return [];
        emittedConcepts.add("chemical-processes");
        return [conceptGroup("chemical elements", CHEMICAL_PROCESS_CONCEPT, directTermSet, {
          literalTerms: ["chemical", "element"],
          minimumEvidence: 1,
          evidencePhrases: ["chemical element", "chemical process"],
          conceptId: "chemical-processes",
          role: "method",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "chemical elements and processes",
          basis: "bounded coupled-system process relationship",
        })];
      }
      if (hasMembraneTreatmentPhrase && ["membrane", "treatment", "purification", "separation", "filtration"].includes(term)) {
        if (emittedConcepts.has("membrane-treatment")) return [];
        emittedConcepts.add("membrane-treatment");
        return [conceptGroup("membrane treatment", MEMBRANE_TREATMENT_CONCEPT, directTermSet, {
          literalTerms: ["membrane", "treatment", "purification", "separation", "filtration"],
          minimumEvidence: 2,
          evidencePhrases: ["membrane treatment", "membrane purification", "membrane separation", "membrane filtration"],
          conceptId: "membrane-treatment",
          role: "method",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "membrane treatment and separation",
          basis: "bounded environmental treatment method",
        })];
      }
      // Recognized names such as "perfluorooctanoic acid" and "forever
      // chemicals" are one PFAS concept, not two independent requirements.
      if (hasPfasAlias && PFAS_DESCRIPTOR_TERMS.has(term)) return [];
      if (hasPfasAlias && QUERY_ALIASES[term] === PFAS_CONCEPT) {
        if (emittedConcepts.has("pfas-contamination")) return [];
        emittedConcepts.add("pfas-contamination");
        return [conceptGroup(term, PFAS_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          conceptId: "pfas-contamination",
          role: "target",
          required: true,
          evidencePolicy: "protected_pfas",
          saturateConcept: true,
          phrase: "PFAS contamination",
          basis: "guarded contaminant family",
        })];
      }
      if (hasCatalystDesignPhrase && ["catalyst", "catalysi", "catalytic", "design", "discovery", "optimization", "screening"].includes(term)) {
        if (emittedConcepts.has("catalyst-design")) return [];
        emittedConcepts.add("catalyst-design");
        return [conceptGroup("catalyst design", CATALYST_DESIGN_CONCEPT, directTermSet, {
          literalTerms: ["catalyst", "catalysi", "catalytic", "design", "discovery", "optimization", "screening"],
          minimumEvidence: 2,
          evidencePhrases: ["catalyst design", "catalyst discovery", "catalyst optimization", "catalyst screening", "catalytic design"],
          conceptId: "catalyst-design",
          role: "target_and_method",
          required: true,
          evidencePolicy: "controlled_compound",
          saturateConcept: true,
          phrase: "catalyst design and discovery",
          basis: "bounded scientific target-operation compound",
        })];
      }
      if (["catalyst", "catalysi", "catalytic"].includes(term)) {
        if (emittedConcepts.has("catalysis")) return [];
        emittedConcepts.add("catalysis");
        return [conceptGroup(term, CATALYSIS_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          evidenceAlternatives: CATALYSIS_EVIDENCE,
          evidenceWindows: CATALYST_CONTEXT_WINDOWS,
          evidenceMode: "any",
          conceptId: searchV2 ? "catalysis" : "",
          role: searchV2 ? "method" : "",
          required: searchV2,
          strictEvidence: false,
          phrase: "scientific catalysis",
          basis: "guarded scientific word family",
        })];
      }
      if (term === "ai") {
        if (emittedConcepts.has("artificial-intelligence")) return [];
        emittedConcepts.add("artificial-intelligence");
        return [conceptGroup(term, AI_CONCEPT, directTermSet, {
          literalTerms: ["ai"],
          minimumEvidence: 1,
          evidenceAlternatives: AI_EVIDENCE,
          conceptId: searchV2 ? "artificial-intelligence" : "",
          role: searchV2 ? "method" : "",
          required: searchV2,
          evidencePolicy: searchV2 ? "protected_ai" : "",
          phrase: "artificial intelligence and machine learning",
          basis: "deterministic technical abbreviation",
        })];
      }
      if (
        (hasBasicEnergySciences && ["basic", "energy", "science"].includes(term))
        || (hasBasicEnergySciences && term === "bes")
      ) {
        if (emittedConcepts.has("basic-energy-sciences")) return [];
        emittedConcepts.add("basic-energy-sciences");
        return [conceptGroup(
          term === "bes" ? "bes" : "basic energy sciences",
          BASIC_ENERGY_SCIENCES_CONCEPT,
          directTermSet,
          {
            literalTerms: term === "bes" ? ["bes"] : ["basic", "energy", "science"],
            minimumEvidence: 1,
            evidenceAlternatives: BASIC_ENERGY_SCIENCES_EVIDENCE,
            evidencePhrases: ["basic energy science", "bes"],
            requiredAlways: true,
            conceptId: searchV2 ? "basic-energy-sciences" : "",
            role: searchV2 ? "program_or_agency_qualifier" : "",
            required: searchV2,
            phrase: "basic energy sciences",
          },
        )];
      }
      if (
        (hasBroadCallPhrase && ["broad", "agency", "announcement"].includes(term))
        || (hasBroadCallPhrase && term === "baa")
      ) {
        if (emittedConcepts.has("broad-call")) return [];
        emittedConcepts.add("broad-call");
        return [conceptGroup(
          term === "baa" ? "baa" : "broad agency announcement",
          BROAD_CALL_CONCEPT,
          directTermSet,
          {
            literalTerms: term === "baa" ? ["baa"] : ["broad", "agency", "announcement"],
            minimumEvidence: 1,
            evidenceAlternatives: BROAD_CALL_EVIDENCE,
            requiredAlways: true,
            conceptId: searchV2 ? "broad-call" : "",
            role: searchV2 ? "program_or_agency_qualifier" : "",
            required: searchV2,
            phrase: "broad agency announcement",
          },
        )];
      }
      if (
        (hasRareEarthPhrase && ["rare", "earth", "element", "rare-earth", "rare-earth-element"].includes(term))
        || RARE_EARTH_QUERY_MEMBERS.has(term)
        || (searchV2 && (term === "rees" || (hasRareEarthAcronym && term === "ree")))
      ) {
        if (emittedConcepts.has("rare-earth")) return [];
        emittedConcepts.add("rare-earth");
        return [conceptGroup(
          hasRareEarthPhrase ? "rare earth" : (searchV2 ? "ree" : term),
          RARE_EARTH_CONCEPT,
          directTermSet,
          {
            literalTerms: hasRareEarthPhrase ? ["rare", "earth", "element"] : [searchV2 ? "ree" : term],
            evidenceAlternatives: RARE_EARTH_EVIDENCE,
            requiredUnlessTopic: searchV2 ? "" : "Separations and membranes",
            requiredAlways: searchV2,
            conceptId: searchV2 ? "rare-earth-elements" : "",
            role: searchV2 ? "target" : "",
            required: searchV2,
            evidencePolicy: searchV2 ? "protected_rare_earth" : "",
            saturateConcept: searchV2,
            phrase: "rare earth elements",
          },
        )];
      }
      if (hasIonicLiquidPhrase && ["ionic", "liquid"].includes(term)) {
        if (emittedConcepts.has("ionic-liquid")) return [];
        emittedConcepts.add("ionic-liquid");
        return [conceptGroup("ionic liquid", IONIC_LIQUID_CONCEPT, directTermSet, {
          literalTerms: ["ionic", "liquid"],
          minimumEvidence: 2,
          evidenceAlternatives: IONIC_LIQUID_EVIDENCE,
          requiredAlways: true,
          conceptId: searchV2 ? "ionic-liquid-extraction" : "",
          role: searchV2 ? "method" : "",
          required: searchV2,
          phrase: "ionic liquids",
        })];
      }
      if (hasIlAbbreviation && ["il", "ils"].includes(term)) {
        if (emittedConcepts.has("ionic-liquid")) return [];
        emittedConcepts.add("ionic-liquid");
        return [conceptGroup(term, IONIC_LIQUID_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 2,
          evidenceAlternatives: IONIC_LIQUID_EVIDENCE,
          requiredAlways: true,
          conceptId: searchV2 ? "ionic-liquid-extraction" : "",
          role: searchV2 ? "method" : "",
          required: searchV2,
          phrase: "ionic liquids",
          basis: "contextual scientific abbreviation",
        })];
      }
      if (hasRareEarthQuery && hasSolventExtractionPhrase && ["solvent", "extraction"].includes(term)) {
        if (emittedConcepts.has("separations")) return [];
        emittedConcepts.add("separations");
        return [conceptGroup("solvent extraction", SEPARATION_METHOD_CONCEPT, directTermSet, {
          literalTerms: ["solvent", "extraction"],
          minimumEvidence: 2,
          evidencePhrases: ["solvent extraction"],
          requiredAlways: true,
          conceptId: "separations",
          role: "method",
          required: true,
          evidencePolicy: "technical_separation",
          saturateConcept: true,
          phrase: "solvent extraction and separations",
        })];
      }
      if (hasIonExchangePhrase && ["ion", "exchange"].includes(term)) {
        if (emittedConcepts.has("separations")) return [];
        emittedConcepts.add("separations");
        return [conceptGroup("ion exchange", SEPARATION_METHOD_CONCEPT, directTermSet, {
          literalTerms: ["ion", "exchange"],
          minimumEvidence: 2,
          evidencePhrases: ["ion exchange"],
          requiredAlways: hasRareEarthQuery,
          conceptId: "separations",
          role: "method",
          required: true,
          evidencePolicy: "technical_separation",
          saturateConcept: true,
          phrase: "ion-exchange separation",
          basis: "controlled separation method",
        })];
      }
      if (hasResourceRecoveryPhrase && ["resource", "recovery"].includes(term)) {
        if (emittedConcepts.has("separations")) return [];
        emittedConcepts.add("separations");
        return [conceptGroup("resource recovery", SEPARATION_METHOD_CONCEPT, directTermSet, {
          literalTerms: ["resource", "recovery"],
          minimumEvidence: 1,
          requiredAlways: hasRareEarthQuery,
          conceptId: "separations",
          role: "method",
          required: true,
          evidencePolicy: "technical_separation",
          saturateConcept: true,
          phrase: "resource recovery and separations",
          basis: "controlled recovery operation",
        })];
      }
      if (searchV2 && SEPARATION_QUERY_TERMS.has(term)) {
        if (emittedConcepts.has("separations")) return [];
        emittedConcepts.add("separations");
        return [conceptGroup(term, SEPARATION_METHOD_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          requiredAlways: hasRareEarthQuery,
          conceptId: "separations",
          role: "method",
          required: true,
          evidencePolicy: "technical_separation",
          saturateConcept: true,
          phrase: "separations, extraction, processing, and recovery",
        })];
      }
      if (searchV2 && term === "maritime") {
        return [conceptGroup(term, MARITIME_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          conceptId: "literal:maritime",
          role: "application_or_context",
          required: true,
          phrase: "maritime, marine, naval, or ocean",
          basis: "bounded maritime vocabulary",
        })];
      }
      if (searchV2 && term === "navigation") {
        return [conceptGroup(term, NAVIGATION_CONCEPT, directTermSet, {
          literalTerms: [term],
          minimumEvidence: 1,
          conceptId: "literal:navigation",
          role: "application_or_context",
          required: true,
          phrase: "navigation, positioning, and timing",
          basis: "bounded technical vocabulary",
        })];
      }
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
      const searchMetadata = searchV2 ? {
        conceptId: `literal:${term}`,
        role: AGENCY_QUALIFIER_TERMS.has(term)
          ? "program_or_agency_qualifier"
          : "application_or_context",
        required: true,
        requiredAlways: AGENCY_QUALIFIER_TERMS.has(term),
        exactIndexedAcronym: uppercaseTerms.has(term) && term.length <= 4,
      } : {};
      // Literal matches are preferable to broader long-form expansions. The
      // glossary is a fallback for abbreviations absent from this catalog.
      if (indexed && !ALWAYS_EXPAND_ALIASES.has(term) && !acronymExpansion) {
        return [{
          source: term,
          terms: [...weightedTerms].map(([expanded, weight]) => ({ term: expanded, weight })),
          ...searchMetadata,
        }];
      }
      const expansion = acronymExpansion?.phrase || QUERY_ALIASES[term];
      const expansionWeight = acronymExpansion ? .9 : .86;
      tokenize(expansion || "").forEach(expanded => {
        // A term the user explicitly supplied belongs to its own coverage
        // group; do not let one literal occurrence satisfy two concepts.
        if (expanded !== term && directTermSet.has(expanded)) return;
        if (!weightedTerms.has(expanded)) weightedTerms.set(expanded, expansionWeight);
      });
      return [{
        source: term,
        terms: [...weightedTerms].map(([expanded, weight]) => ({ term: expanded, weight })),
        minimumEvidence: acronymExpansion ? 2 : undefined,
        ...searchMetadata,
        expansion: acronymExpansion ? {
          kind: "contextual_acronym",
          phrase: acronymExpansion.phrase,
          confidence: acronymExpansion.confidence,
          basis: acronymExpansion.basis,
        } : null,
      }];
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
    contractVersion: QUERY_API_CONTRACT_VERSION,
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
