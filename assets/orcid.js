(() => {
  "use strict";

  const CROSSREF_WORKS_URL = "https://api.crossref.org/works";
  const MAX_IMPORTED_WORKS = 50;
  const MAX_PUBLICATION_TEXT = 40_000;
  const KEYWORD_LIMIT = 12;
  const STOP_WORDS = new Set([
    "a", "about", "after", "among", "an", "and", "application", "applications",
    "approach", "approaches", "are", "as", "at", "based", "between", "by",
    "case", "effect", "effects", "for", "from", "in", "into", "is", "method",
    "methods", "new", "of", "on", "or", "our", "study", "the", "their", "through",
    "to", "toward", "towards", "using", "via", "we", "with",
  ]);

  function cleanText(value, maximum = 1_000) {
    return String(value || "")
      .replace(/<[^>]*>/g, " ")
      .replace(/&(?:amp|#38);/gi, "&")
      .replace(/&(?:lt|#60);/gi, "<")
      .replace(/&(?:gt|#62);/gi, ">")
      .replace(/&(?:quot|#34);/gi, '"')
      .replace(/&(?:apos|#39);/gi, "'")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, maximum);
  }

  function formatInput(value) {
    let raw = String(value || "").trim().toUpperCase();
    const urlMatch = raw.match(/ORCID\.ORG\/([^/?#]*)/i);
    if (urlMatch) raw = urlMatch[1];
    const characters = [];
    for (const character of raw) {
      if (/\d/.test(character)) characters.push(character);
      else if (character === "X" && characters.length === 15) characters.push(character);
      if (characters.length >= 16) break;
    }
    return characters.join("").match(/.{1,4}/g)?.join("-") || "";
  }

  function bindInput(input) {
    if (!input || input.dataset.orcidFormatting === "true") return input;
    const applyFormatting = () => {
      const formatted = formatInput(input.value);
      if (input.value !== formatted) input.value = formatted;
    };
    input.dataset.orcidFormatting = "true";
    input.maxLength = 19;
    input.inputMode = "text";
    input.autocomplete = "off";
    input.pattern = "[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]";
    input.addEventListener("paste", event => {
      const pasted = event.clipboardData?.getData("text") || "";
      const formatted = formatInput(pasted);
      if (formatted.length !== 19) return;
      event.preventDefault();
      input.value = formatted;
      if (typeof input.dispatchEvent === "function" && typeof Event === "function") {
        input.dispatchEvent(new Event("input", { bubbles: true }));
      } else {
        applyFormatting();
      }
    });
    input.addEventListener("input", applyFormatting);
    input.value = formatInput(input.value);
    return input;
  }

  function normalizeId(value, { validate = true } = {}) {
    const id = formatInput(value);
    if (!/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/.test(id)) return "";
    if (!validate) return id;
    const compact = id.replace(/-/g, "");
    let total = 0;
    for (const character of compact.slice(0, 15)) {
      total = (total + Number(character)) * 2;
    }
    const result = (12 - (total % 11)) % 11;
    const expected = result === 10 ? "X" : String(result);
    return compact[15] === expected ? id : "";
  }

  function authorOrcid(author) {
    return normalizeId(author?.ORCID || author?.orcid || "");
  }

  function publicationYear(item) {
    for (const field of ["published-print", "published-online", "published", "issued"]) {
      const parts = item?.[field]?.["date-parts"]?.[0];
      if (Number.isInteger(parts?.[0])) return parts[0];
    }
    return null;
  }

  function keywordCandidates(works) {
    const candidates = new Map();
    const add = (phrase, score) => {
      const value = cleanText(phrase, 100).toLowerCase()
        .replace(/^[^a-z0-9]+|[^a-z0-9+.-]+$/g, "");
      if (!value || value.length < 5 || value.length > 80) return;
      const words = value.match(/[a-z0-9][a-z0-9+.-]*/g) || [];
      if (!words.length || STOP_WORDS.has(words[0]) || STOP_WORDS.has(words[words.length - 1])) return;
      if (words.every(word => STOP_WORDS.has(word) || /^\d+$/.test(word))) return;
      candidates.set(value, (candidates.get(value) || 0) + score);
    };

    works.forEach(work => {
      const seen = new Set();
      (work.subjects || []).forEach(subject => {
        const value = cleanText(subject, 100).toLowerCase();
        if (!seen.has(value)) {
          add(value, 7);
          seen.add(value);
        }
      });
      const tokens = work.title.toLowerCase().match(/[a-z0-9][a-z0-9+.-]*/g) || [];
      for (const size of [3, 2]) {
        for (let start = 0; start + size <= tokens.length; start += 1) {
          const window = tokens.slice(start, start + size);
          if (STOP_WORDS.has(window[0]) || STOP_WORDS.has(window[window.length - 1])) continue;
          const phrase = window.join(" ");
          if (seen.has(phrase)) continue;
          add(phrase, size === 3 ? 2.4 : 2);
          seen.add(phrase);
        }
      }
    });

    const ranked = [...candidates]
      .sort((left, right) => right[1] - left[1] || right[0].length - left[0].length || left[0].localeCompare(right[0]));
    const output = [];
    for (const [phrase] of ranked) {
      const nested = output.some(existing => existing.includes(phrase) || phrase.includes(existing));
      if (nested) continue;
      output.push(phrase);
      if (output.length >= KEYWORD_LIMIT) break;
    }
    return output;
  }

  function parseWorks(payload, orcidId) {
    const id = normalizeId(orcidId);
    if (!id) throw new Error("Enter a valid ORCID, including all 16 characters.");
    const items = Array.isArray(payload?.message?.items) ? payload.message.items : [];
    const names = new Map();
    const works = [];
    items.forEach(item => {
      const matchingAuthors = (item.author || []).filter(author => authorOrcid(author) === id);
      if (!matchingAuthors.length) return;
      matchingAuthors.forEach(author => {
        const name = cleanText([author.given, author.family].filter(Boolean).join(" "), 160);
        if (name) names.set(name, (names.get(name) || 0) + 1);
      });
      const title = cleanText(item.title?.[0], 500);
      if (!title) return;
      works.push({
        title,
        year: publicationYear(item),
        doi: cleanText(item.DOI, 200),
        type: cleanText(item.type, 80),
        container: cleanText(item["container-title"]?.[0], 300),
        subjects: (item.subject || []).map(subject => cleanText(subject, 100)).filter(Boolean).slice(0, 12),
      });
    });
    const name = [...names].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))[0]?.[0] || "";
    const keywords = keywordCandidates(works);
    const publicationText = works.map(work => [
      work.title,
      ...work.subjects,
      work.container,
    ].filter(Boolean).join(" | ")).join("\n").slice(0, MAX_PUBLICATION_TEXT);
    return {
      orcidId: id,
      name,
      works,
      importedWorkCount: works.length,
      totalWorkCount: Math.max(works.length, Number(payload?.message?.["total-results"] || 0)),
      keywords,
      publicationText,
      source: "Crossref metadata linked to the supplied ORCID",
      updatedAt: new Date().toISOString(),
    };
  }

  async function fetchProfile(value, options = {}) {
    const id = normalizeId(value);
    if (!id) throw new Error("Enter a valid ORCID, such as 0000-0002-1825-0097.");
    const fetchImpl = options.fetchImpl || globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new Error("ORCID publication lookup is unavailable in this browser.");
    const maximum = Math.max(1, Math.min(Number(options.maxWorks) || MAX_IMPORTED_WORKS, 100));
    const query = [
      `filter=${encodeURIComponent(`orcid:${id}`)}`,
      `rows=${maximum}`,
      "sort=published",
      "order=desc",
    ].join("&");
    let response;
    try {
      response = await fetchImpl(`${CROSSREF_WORKS_URL}?${query}`, {
        headers: { Accept: "application/json" },
      });
    } catch (_error) {
      throw new Error("Could not reach the publication index. Check the connection and try again.");
    }
    if (!response?.ok) {
      throw new Error(`Publication lookup failed (${Number(response?.status || 0) || "network error"}). Try again shortly.`);
    }
    const parsed = parseWorks(await response.json(), id);
    if (!parsed.works.length) {
      throw new Error("No public Crossref publications linked to this ORCID were found. Add keywords or a CV instead.");
    }
    return parsed;
  }

  globalThis.FUNDING_ORCID = Object.freeze({
    CROSSREF_WORKS_URL,
    KEYWORD_LIMIT,
    MAX_IMPORTED_WORKS,
    MAX_PUBLICATION_TEXT,
    fetchProfile,
    formatInput,
    bindInput,
    keywordCandidates,
    normalizeId,
    parseWorks,
  });

  if (typeof document !== "undefined") {
    document.querySelectorAll("[data-orcid-input]").forEach(bindInput);
  }
})();
