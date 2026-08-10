(() => {
  "use strict";

  const PROFILE_SCHEMA_VERSION = 1;
  const FEEDBACK_SCHEMA_VERSION = 1;
  const PROFILE_STORAGE_KEY = "funding-finder.profile.v1";
  const FEEDBACK_STORAGE_KEY = "funding-finder.feedback.v1";
  const MAX_CV_FILE_BYTES = 10 * 1024 * 1024;
  const MAX_CV_TEXT_CHARS = 120_000;
  const MAX_PDF_PAGES = 80;

  const APPLICANT_CONTEXTS = new Set([
    "higher_education",
    "nonprofit",
    "small_business",
    "individual",
    "government",
    "tribal",
    "other",
  ]);
  const CAREER_STAGES = new Set([
    "any",
    "trainee",
    "early_career",
    "established",
  ]);
  const SORT_MODES = new Set([
    "relevance",
    "deadline",
    "posted",
    "award",
    "agency",
    "title",
  ]);
  const FACET_NAMES = [
    "source",
    "source_type",
    "discipline",
    "topic",
    "agency",
    "eligibility",
    "funding_instrument",
  ];

  function cleanString(value, maximum = 20_000) {
    return String(value || "")
      .replace(/\u0000/g, "")
      .replace(/\r\n?/g, "\n")
      .trim()
      .slice(0, maximum);
  }

  function cleanDate(value) {
    const text = cleanString(value, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
  }

  function cleanStringArray(value, maximum = 50) {
    return Array.isArray(value)
      ? [...new Set(
          value
            .map(item => cleanString(item, 200))
            .filter(Boolean),
        )].slice(0, maximum)
      : [];
  }

  function emptyPreferences() {
    return {
      status_posted: true,
      status_forecasted: true,
      deadline_from: "",
      deadline_to: "",
      minimum_award: "",
      evidence: false,
      preliminary: false,
      limited: false,
      early_career: false,
      no_cost_share: false,
      profile_search_active: false,
      personalize: false,
      ai_provider: "openai",
      sort: "deadline",
      facets: Object.fromEntries(FACET_NAMES.map(name => [name, []])),
    };
  }

  function sanitizePreferences(value) {
    const source = value && typeof value === "object" ? value : {};
    const facets = source.facets && typeof source.facets === "object"
      ? source.facets
      : {};
    const minimumAward = Number(source.minimum_award || 0);
    return {
      status_posted: source.status_posted !== false,
      status_forecasted: source.status_forecasted !== false,
      deadline_from: cleanDate(source.deadline_from),
      deadline_to: cleanDate(source.deadline_to),
      minimum_award: Number.isFinite(minimumAward) && minimumAward > 0
        ? String(Math.round(minimumAward))
        : "",
      evidence: source.evidence === true,
      preliminary: source.preliminary === true,
      limited: source.limited === true,
      early_career: source.early_career === true,
      no_cost_share: source.no_cost_share === true,
      profile_search_active: source.profile_search_active === true,
      personalize: source.personalize === true,
      ai_provider: source.ai_provider === "anthropic"
        ? "anthropic"
        : "openai",
      sort: SORT_MODES.has(source.sort) ? source.sort : "deadline",
      facets: Object.fromEntries(
        FACET_NAMES.map(name => [name, cleanStringArray(facets[name])]),
      ),
    };
  }

  function emptyProfile() {
    return {
      schema_version: PROFILE_SCHEMA_VERSION,
      research_description: "",
      expertise_keywords: "",
      applicant_context: "higher_education",
      career_stage: "any",
      cv_name: "",
      cv_type: "",
      cv_text: "",
      cv_word_count: 0,
      cv_page_count: null,
      cv_updated_at: null,
      cv_truncated: false,
      include_cv_in_ai: true,
      remember: false,
      preferences: emptyPreferences(),
      updated_at: null,
    };
  }

  function sanitizeProfile(value) {
    const source = value && typeof value === "object" ? value : {};
    const applicantContext = APPLICANT_CONTEXTS.has(source.applicant_context)
      ? source.applicant_context
      : "higher_education";
    const careerStage = CAREER_STAGES.has(source.career_stage)
      ? source.career_stage
      : "any";
    const normalizedCv = normalizeCvText(source.cv_text || "");
    const cvText = normalizedCv.text;
    return {
      ...emptyProfile(),
      research_description: cleanString(source.research_description, 20_000),
      expertise_keywords: cleanString(source.expertise_keywords, 4_000),
      applicant_context: applicantContext,
      career_stage: careerStage,
      cv_name: cleanString(source.cv_name, 260),
      cv_type: cleanString(source.cv_type, 80),
      cv_text: cvText,
      cv_word_count: cvText ? cvText.split(/\s+/).filter(Boolean).length : 0,
      cv_page_count: Number.isInteger(source.cv_page_count)
        && source.cv_page_count > 0
        ? source.cv_page_count
        : null,
      cv_updated_at: cleanString(source.cv_updated_at, 40) || null,
      cv_truncated: source.cv_truncated === true || normalizedCv.truncated,
      include_cv_in_ai: source.include_cv_in_ai !== false,
      remember: source.remember === true,
      preferences: sanitizePreferences(source.preferences),
      updated_at: cleanString(source.updated_at, 40) || null,
    };
  }

  function storageOrNull(storage) {
    try {
      return storage || globalThis.localStorage || null;
    } catch {
      return null;
    }
  }

  function loadProfile(storage) {
    const target = storageOrNull(storage);
    if (!target) return emptyProfile();
    try {
      const raw = target.getItem(PROFILE_STORAGE_KEY);
      if (!raw) return emptyProfile();
      const parsed = JSON.parse(raw);
      if (parsed?.schema_version !== PROFILE_SCHEMA_VERSION) {
        return emptyProfile();
      }
      return sanitizeProfile(parsed);
    } catch {
      return emptyProfile();
    }
  }

  function saveProfile(value, storage) {
    const target = storageOrNull(storage);
    const profile = sanitizeProfile(value);
    if (!target) {
      return { saved: false, profile, reason: "storage_unavailable" };
    }
    try {
      if (!profile.remember) {
        target.removeItem(PROFILE_STORAGE_KEY);
        return { saved: false, profile, reason: "remember_disabled" };
      }
      profile.updated_at = new Date().toISOString();
      target.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
      return { saved: true, profile, reason: null };
    } catch {
      return { saved: false, profile, reason: "storage_failed" };
    }
  }

  function clearProfile(storage) {
    const target = storageOrNull(storage);
    if (!target) return false;
    try {
      target.removeItem(PROFILE_STORAGE_KEY);
      return true;
    } catch {
      return false;
    }
  }

  function normalizeCvText(value) {
    const lines = String(value || "")
      .replace(/\u0000/g, "")
      .replace(/\r\n?/g, "\n")
      .split("\n")
      .map(line => line.replace(/[ \t]+/g, " ").trim());
    const normalized = lines
      .reduce((output, line) => {
        if (!line && output[output.length - 1] === "") return output;
        output.push(line);
        return output;
      }, [])
      .join("\n")
      .trim();
    const truncated = normalized.length > MAX_CV_TEXT_CHARS;
    return {
      text: normalized.slice(0, MAX_CV_TEXT_CHARS),
      truncated,
    };
  }

  function extensionOf(name) {
    const match = cleanString(name, 260).toLowerCase().match(/\.([a-z0-9]+)$/);
    return match ? match[1] : "";
  }

  async function loadPdfJs() {
    const moduleUrl = new URL(
      "./assets/vendor/pdf.mjs",
      document.baseURI,
    ).href;
    const workerUrl = new URL(
      "./assets/vendor/pdf.worker.mjs",
      document.baseURI,
    ).href;
    const pdfjs = await import(moduleUrl);
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
    return pdfjs;
  }

  async function loadMammoth() {
    if (globalThis.mammoth?.extractRawText) return globalThis.mammoth;
    const source = new URL(
      "./assets/vendor/mammoth.browser.min.js",
      document.baseURI,
    ).href;
    await new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${source}"]`);
      if (existing) {
        existing.addEventListener("load", resolve, { once: true });
        existing.addEventListener("error", reject, { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = source;
      script.async = true;
      script.addEventListener("load", resolve, { once: true });
      script.addEventListener(
        "error",
        () => reject(new Error("The local DOCX parser could not load.")),
        { once: true },
      );
      document.head.appendChild(script);
    });
    if (!globalThis.mammoth?.extractRawText) {
      throw new Error("The local DOCX parser did not initialize.");
    }
    return globalThis.mammoth;
  }

  async function extractPdfText(
    file,
    pdfLoader = loadPdfJs,
    maximumPages = MAX_PDF_PAGES,
  ) {
    const pdfjs = await pdfLoader();
    const bytes = new Uint8Array(await file.arrayBuffer());
    const documentTask = pdfjs.getDocument({ data: bytes });
    const pdf = await documentTask.promise;
    const totalPages = pdf.numPages;
    const requestedPages = Number.isInteger(maximumPages) && maximumPages > 0
      ? maximumPages
      : MAX_PDF_PAGES;
    const pagesToRead = Math.min(totalPages, requestedPages);
    const pages = [];
    try {
      for (let pageNumber = 1; pageNumber <= pagesToRead; pageNumber += 1) {
        const page = await pdf.getPage(pageNumber);
        const content = await page.getTextContent();
        let pageText = "";
        for (const item of content.items || []) {
          const text = String(item.str || "").trim();
          if (text) pageText += `${text}${item.hasEOL ? "\n" : " "}`;
        }
        pages.push(pageText.trim());
        page.cleanup?.();
      }
      return {
        rawText: pages.filter(Boolean).join("\n\n"),
        pages,
        pageCount: totalPages,
        truncated: totalPages > requestedPages,
      };
    } finally {
      await pdf.cleanup?.();
      await pdf.destroy?.();
    }
  }

  async function extractDocxText(file, mammothLoader = loadMammoth) {
    const mammoth = await mammothLoader();
    const result = await mammoth.extractRawText({
      arrayBuffer: await file.arrayBuffer(),
    });
    return {
      rawText: result.value || "",
      pageCount: null,
      truncated: false,
      messages: result.messages || [],
    };
  }

  async function extractCv(file, dependencies = {}) {
    if (!file) throw new Error("Choose a CV file first.");
    if (!Number.isFinite(file.size) || file.size <= 0) {
      throw new Error("The selected CV file is empty.");
    }
    if (file.size > MAX_CV_FILE_BYTES) {
      throw new Error("CV files must be 10 MB or smaller.");
    }

    const extension = extensionOf(file.name);
    const type = String(file.type || "").toLowerCase();
    let extracted;
    let format;
    if (extension === "pdf" || type === "application/pdf") {
      format = "PDF";
      extracted = await extractPdfText(file, dependencies.pdfLoader);
    } else if (
      extension === "docx"
      || type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ) {
      format = "DOCX";
      extracted = await extractDocxText(file, dependencies.mammothLoader);
    } else if (
      ["txt", "md", "text"].includes(extension)
      || type.startsWith("text/")
    ) {
      format = extension === "md" ? "Markdown" : "text";
      extracted = {
        rawText: await file.text(),
        pageCount: null,
        truncated: false,
      };
    } else {
      throw new Error("Use a PDF, DOCX, TXT, or Markdown CV.");
    }

    const normalized = normalizeCvText(extracted.rawText);
    if (normalized.text.length < 80) {
      throw new Error(
        "Very little selectable text was found. For a scanned CV, upload a DOCX/TXT version or paste a research description.",
      );
    }
    const wordCount = normalized.text.split(/\s+/).filter(Boolean).length;
    return {
      name: cleanString(file.name, 260),
      type: format,
      text: normalized.text,
      wordCount,
      pageCount: extracted.pageCount,
      truncated: Boolean(extracted.truncated || normalized.truncated),
      updatedAt: new Date().toISOString(),
    };
  }

  function stableHash(value) {
    let hash = 0x811c9dc5;
    const text = String(value || "");
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }

  function profileFingerprint(profile) {
    const value = sanitizeProfile(profile);
    return stableHash(JSON.stringify({
      research_description: value.research_description,
      expertise_keywords: value.expertise_keywords,
      applicant_context: value.applicant_context,
      career_stage: value.career_stage,
      cv_text: value.cv_text,
      preferences: value.preferences,
    }));
  }

  function aiProfileContext(value, maximumCvCharacters = 12_000) {
    const profile = sanitizeProfile(value);
    const maximum = Number.isInteger(maximumCvCharacters)
      && maximumCvCharacters > 0
      ? Math.min(maximumCvCharacters, MAX_CV_TEXT_CHARS)
      : 12_000;
    const context = {
      research_description: profile.research_description || null,
      expertise_keywords: profile.expertise_keywords || null,
      applicant_context: profile.applicant_context,
      career_stage: profile.career_stage,
    };
    if (profile.include_cv_in_ai && profile.cv_text) {
      context.cv_excerpt = profile.cv_text.slice(0, maximum);
      context.cv_excerpt_note = profile.cv_text.length > maximum
        ? `First ${maximum.toLocaleString()} characters of the locally extracted CV`
        : "Complete locally extracted CV text";
    }
    return context;
  }

  function sanitizeFeedbackEntry(value) {
    const source = value && typeof value === "object" ? value : {};
    const labels = new Set([
      "useful", "not_relevant", "needs_verification", "partial", "strong",
    ]);
    if (!labels.has(source.label)) return null;
    return {
      opportunity_id: cleanString(source.opportunity_id, 120),
      opportunity_number: cleanString(source.opportunity_number, 160),
      title: cleanString(source.title, 500),
      agency: cleanString(source.agency, 300),
      label: source.label,
      reason: cleanString(source.reason, 120),
      note: cleanString(source.note, 1_000),
      query: cleanString(source.query, 1_000),
      profile_active: source.profile_active === true,
      profile_fingerprint: cleanString(source.profile_fingerprint, 40),
      retrieval_rank: Number.isInteger(source.retrieval_rank)
        && source.retrieval_rank > 0
        ? source.retrieval_rank
        : null,
      displayed_rank: Number.isInteger(source.displayed_rank)
        && source.displayed_rank > 0
        ? source.displayed_rank
        : null,
      ai_rank: Number.isInteger(source.ai_rank) && source.ai_rank > 0
        ? source.ai_rank
        : null,
      ai_score: Number.isFinite(Number(source.ai_score))
        ? Number(source.ai_score)
        : null,
      ai_verdict: cleanString(source.ai_verdict, 80),
      provider: cleanString(source.provider, 40),
      model: cleanString(source.model, 120),
      close_date: cleanDate(source.close_date) || null,
      status: cleanString(source.status, 40),
      catalog_generated_at: cleanString(source.catalog_generated_at, 40),
      updated_at: cleanString(source.updated_at, 40)
        || new Date().toISOString(),
    };
  }

  function loadFeedback(storage) {
    const target = storageOrNull(storage);
    if (!target) return {};
    try {
      const parsed = JSON.parse(target.getItem(FEEDBACK_STORAGE_KEY) || "{}");
      if (parsed?.schema_version !== FEEDBACK_SCHEMA_VERSION) return {};
      const entries = parsed.entries && typeof parsed.entries === "object"
        ? parsed.entries
        : {};
      return Object.fromEntries(
        Object.entries(entries)
          .map(([id, entry]) => [cleanString(id, 120), sanitizeFeedbackEntry(entry)])
          .filter(([id, entry]) => id && entry),
      );
    } catch {
      return {};
    }
  }

  function saveFeedback(entries, storage) {
    const target = storageOrNull(storage);
    if (!target) return false;
    try {
      const cleanEntries = Object.fromEntries(
        Object.entries(entries || {})
          .map(([id, entry]) => [cleanString(id, 120), sanitizeFeedbackEntry(entry)])
          .filter(([id, entry]) => id && entry),
      );
      target.setItem(FEEDBACK_STORAGE_KEY, JSON.stringify({
        schema_version: FEEDBACK_SCHEMA_VERSION,
        updated_at: new Date().toISOString(),
        entries: cleanEntries,
      }));
      return true;
    } catch {
      return false;
    }
  }

  function clearFeedback(storage) {
    const target = storageOrNull(storage);
    if (!target) return false;
    try {
      target.removeItem(FEEDBACK_STORAGE_KEY);
      return true;
    } catch {
      return false;
    }
  }

  globalThis.FUNDING_PROFILE = Object.freeze({
    FEEDBACK_SCHEMA_VERSION,
    FEEDBACK_STORAGE_KEY,
    MAX_CV_FILE_BYTES,
    MAX_CV_TEXT_CHARS,
    PROFILE_SCHEMA_VERSION,
    PROFILE_STORAGE_KEY,
    aiProfileContext,
    clearFeedback,
    clearProfile,
    emptyPreferences,
    emptyProfile,
    extractCv,
    extractPdfText,
    loadFeedback,
    loadProfile,
    normalizeCvText,
    profileFingerprint,
    sanitizeFeedbackEntry,
    sanitizePreferences,
    sanitizeProfile,
    saveFeedback,
    saveProfile,
    stableHash,
  });
})();
