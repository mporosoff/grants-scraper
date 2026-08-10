(() => {
  "use strict";

  const MAX_NOFO_FILE_BYTES = 25 * 1024 * 1024;
  const MAX_NOFO_PDF_PAGES = 160;
  const MAX_NOFO_TEXT_CHARS = 160_000;
  const MATCH_TEXT_CHARS = 80_000;

  const TITLE_STOP_WORDS = new Set([
    "about", "agency", "and", "application", "applications", "award",
    "awards", "department", "for", "from", "funding", "grant", "grants",
    "notice", "of", "opportunity", "program", "proposal", "proposals",
    "research", "the", "this", "through", "to", "with",
  ]);

  function normalizeIdentifier(value) {
    return String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  }

  function normalizeText(value) {
    return String(value || "")
      .replace(/\u0000/g, "")
      .replace(/\r\n?/g, "\n")
      .replace(/[ \t]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function extensionOf(name) {
    return String(name || "").toLowerCase().match(/\.([a-z0-9]+)$/)?.[1] || "";
  }

  function isPdfFile(file) {
    return Boolean(
      file
      && (
        extensionOf(file.name) === "pdf"
        || String(file.type || "").toLowerCase() === "application/pdf"
      )
    );
  }

  function titleTokens(value) {
    return [...new Set(
      (String(value || "").toLowerCase().match(/[a-z0-9][a-z0-9+.-]{2,}/g) || [])
        .map(token => token.replace(/^[.-]+|[.-]+$/g, ""))
        .filter(token => token.length > 2 && !TITLE_STOP_WORDS.has(token)),
    )];
  }

  function extractOpportunityNumbers(text, fileName = "") {
    const source = `${String(fileName || "").replace(/\.pdf$/i, "")}\n${String(text || "").slice(0, MATCH_TEXT_CHARS)}`;
    const patterns = [
      /\b[A-Z0-9]{1,12}(?:[-\u2010-\u2014_/][A-Z0-9]{1,20}){1,7}\b/gi,
      /\b(?:NSF|NIH|NASA|DOE|DOD|USDA|EPA|NEH|NEA)\s+\d{2,4}[-\u2010-\u2014]\d{2,8}\b/gi,
    ];
    const seen = new Set();
    const values = [];
    for (const pattern of patterns) {
      for (const match of source.matchAll(pattern)) {
        const value = match[0].replace(/[\u2010-\u2014]/g, "-").trim();
        const normalized = normalizeIdentifier(value);
        if (normalized.length < 5 || seen.has(normalized)) continue;
        seen.add(normalized);
        values.push(value);
        if (values.length >= 40) return values;
      }
    }
    return values;
  }

  function matchCatalog(text, fileName, records) {
    const available = Array.isArray(records) ? records : [];
    const detectedNumbers = extractOpportunityNumbers(text, fileName);
    const numberMap = new Map();
    available.forEach((record, index) => {
      const normalized = normalizeIdentifier(record?.opportunity_number);
      if (normalized) {
        const existing = numberMap.get(normalized) || [];
        existing.push({ record, index });
        numberMap.set(normalized, existing);
      }
    });

    for (const detected of detectedNumbers) {
      const exact = numberMap.get(normalizeIdentifier(detected));
      if (!exact?.length) continue;
      const preferred = exact.find(item => item.record?.status === "posted") || exact[0];
      return {
        ...preferred,
        confidence: "exact",
        reason: `Matched opportunity number ${preferred.record.opportunity_number}.`,
        detectedNumbers,
      };
    }

    const sourceTokens = new Set(titleTokens(
      `${String(fileName || "").replace(/\.pdf$/i, " ")} ${String(text || "").slice(0, MATCH_TEXT_CHARS)}`,
    ));
    let best = null;
    available.forEach((record, index) => {
      const tokens = titleTokens(record?.title);
      if (tokens.length < 3) return;
      const overlap = tokens.filter(token => sourceTokens.has(token)).length;
      const ratio = overlap / tokens.length;
      if (overlap < 3 || (ratio < .58 && overlap < 7)) return;
      const agencyTokens = titleTokens(record?.agency);
      const agencyOverlap = agencyTokens.filter(token => sourceTokens.has(token)).length;
      const score = ratio * 100 + overlap * 4 + Math.min(agencyOverlap, 3) * 3;
      if (!best || score > best.score) {
        best = { record, index, score, ratio, overlap };
      }
    });

    return best
      ? {
          record: best.record,
          index: best.index,
          confidence: best.ratio >= .78 ? "strong_title" : "possible_title",
          reason: `Matched ${best.overlap} distinctive title terms in the uploaded notice.`,
          detectedNumbers,
        }
      : { record: null, index: -1, confidence: "none", reason: "", detectedNumbers };
  }

  function suggestedQuery(extracted, fileName = "") {
    const numbers = extractOpportunityNumbers(extracted?.text, fileName);
    if (numbers.length) return numbers[0];
    const baseName = String(fileName || "")
      .replace(/\.pdf$/i, "")
      .replace(/[_-]+/g, " ")
      .trim();
    if (titleTokens(baseName).length >= 3) return baseName.slice(0, 240);

    const counts = new Map();
    titleTokens(String(extracted?.text || "").slice(0, 12_000)).forEach(token => {
      if (/^\d+$/.test(token)) return;
      counts.set(token, (counts.get(token) || 0) + 1);
    });
    return [...counts]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, 10)
      .map(([token]) => token)
      .join(" ");
  }

  function rejectCatalogMatch(nofo) {
    const current = nofo && typeof nofo === "object" ? nofo : {};
    const rejectedId = String(current.matchedId || "");
    return {
      ...current,
      matchedId: "",
      matchConfidence: "rejected",
      matchReason: rejectedId
        ? "The suggested catalog connection was marked as unrelated by the user."
        : "No catalog connection was confirmed.",
      rejectedIds: [
        ...new Set([...(current.rejectedIds || []).map(String), rejectedId].filter(Boolean)),
      ],
    };
  }

  async function extract(file, dependencies = {}) {
    if (!file) throw new Error("Choose a NOFO or FOA PDF first.");
    if (!isPdfFile(file)) throw new Error("Only PDF notices can be dropped here.");
    if (!Number.isFinite(file.size) || file.size <= 0) {
      throw new Error("The selected PDF is empty.");
    }
    if (file.size > MAX_NOFO_FILE_BYTES) {
      throw new Error("NOFO PDFs must be 25 MB or smaller.");
    }

    const extractPdfText = dependencies.extractPdfText
      || globalThis.FUNDING_PROFILE?.extractPdfText;
    if (typeof extractPdfText !== "function") {
      throw new Error("The local PDF reader did not load. Refresh the page and try again.");
    }
    const parsed = await extractPdfText(
      file,
      dependencies.pdfLoader,
      MAX_NOFO_PDF_PAGES,
    );
    const pages = Array.isArray(parsed.pages) && parsed.pages.length
      ? parsed.pages
      : [parsed.rawText || ""];
    const pageMarkedText = pages
      .map((page, index) => `[Page ${index + 1}]\n${normalizeText(page)}`)
      .filter(page => /\n\S/.test(page))
      .join("\n\n");
    const normalized = normalizeText(pageMarkedText);
    if (normalized.replace(/\[Page \d+\]/g, "").trim().length < 200) {
      throw new Error(
        "Very little selectable text was found. This may be a scanned PDF; use an OCR-enabled copy.",
      );
    }
    const text = normalized.slice(0, MAX_NOFO_TEXT_CHARS);
    return {
      name: String(file.name || "Uploaded notice").slice(0, 260),
      text,
      pageCount: Number(parsed.pageCount) || pages.length,
      pagesRead: pages.length,
      wordCount: text.split(/\s+/).filter(Boolean).length,
      truncated: Boolean(
        parsed.truncated
        || normalized.length > MAX_NOFO_TEXT_CHARS
        || pages.length < Number(parsed.pageCount || pages.length)
      ),
    };
  }

  globalThis.FUNDING_NOFO = Object.freeze({
    MAX_NOFO_FILE_BYTES,
    MAX_NOFO_PDF_PAGES,
    MAX_NOFO_TEXT_CHARS,
    extract,
    extractOpportunityNumbers,
    isPdfFile,
    matchCatalog,
    normalizeIdentifier,
    rejectCatalogMatch,
    suggestedQuery,
    titleTokens,
  });
})();
