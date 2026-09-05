(() => {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeUrl(value) {
    try {
      const parsed = new URL(String(value || "").trim());
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch {
      return "";
    }
  }

  function safeEmail(value) {
    const email = String(value || "").trim();
    if (email.length > 254 || !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+$/i.test(email)) {
      return "";
    }
    const [local, ...domainParts] = email.split("@");
    if (
      local.length > 64
      || local.startsWith(".")
      || local.endsWith(".")
      || local.includes("..")
      || domainParts.length !== 1
      || domainParts[0].split(".").some(part => !part || part.startsWith("-") || part.endsWith("-"))
    ) {
      return "";
    }
    return email;
  }

  function renderInline(value) {
    const replacements = [];
    const token = html => {
      const marker = `FUNDINGCHATPLACEHOLDER${replacements.length}TOKEN`;
      replacements.push([marker, html]);
      return marker;
    };
    let prepared = String(value || "")
      .replace(/`([^`\n]+)`/g, (_, code) =>
        token(`<code>${escapeHtml(code)}</code>`))
      .replace(/\[([^\]\n]{1,240})\]\((https?:\/\/[^\s)]+)\)/gi, (_, label, url) => {
        const verified = safeUrl(url);
        if (!verified) return label;
        return token(
          `<a href="${escapeHtml(verified)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`,
        );
      });
    prepared = prepared.replace(
      /(^|[\s([{>])([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+)(?=$|[\s)\]}>.,;:!?])/gi,
      (match, prefix, candidate) => {
        const email = safeEmail(candidate);
        if (!email) return match;
        return `${prefix}${token(`<a href="mailto:${escapeHtml(email)}">${escapeHtml(email)}</a>`)}`;
      },
    );
    prepared = escapeHtml(prepared)
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
    for (const [marker, html] of replacements) {
      prepared = prepared.replace(marker, html);
    }
    return prepared;
  }

  function tableCells(value) {
    let line = String(value || "").trim();
    if (!line.includes("|")) return null;
    if (line.startsWith("|")) line = line.slice(1);
    if (line.endsWith("|")) line = line.slice(0, -1);
    const cells = [];
    let cell = "";
    for (let index = 0; index < line.length; index += 1) {
      const character = line[index];
      if (character === "\\" && line[index + 1] === "|") {
        cell += "|";
        index += 1;
      } else if (character === "|") {
        cells.push(cell.trim());
        cell = "";
      } else {
        cell += character;
      }
    }
    cells.push(cell.trim());
    return cells.length >= 2 ? cells : null;
  }

  function tableAlignments(cells) {
    if (!cells?.length) return null;
    const alignments = [];
    for (const cell of cells) {
      const marker = cell.replace(/\s+/g, "");
      if (!/^:?-{3,}:?$/.test(marker)) return null;
      alignments.push(marker.startsWith(":") && marker.endsWith(":")
        ? "center"
        : marker.endsWith(":")
          ? "right"
          : "left");
    }
    return alignments;
  }

  function renderTable(headers, alignments, rows) {
    const cellClass = alignment => ` class="chat-table-align-${alignment}"`;
    return `<div class="chat-table-wrap" tabindex="0"><table class="chat-table"><thead><tr>${headers
      .map((header, index) => `<th scope="col"${cellClass(alignments[index])}>${renderInline(header)}</th>`)
      .join("")}</tr></thead><tbody>${rows
      .map(row => `<tr>${row
        .map((cell, index) => `<td${cellClass(alignments[index])}>${renderInline(cell)}</td>`)
        .join("")}</tr>`)
      .join("")}</tbody></table></div>`;
  }

  function renderRichText(value) {
    const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
    const output = [];
    let listType = "";
    let paragraph = [];

    const closeList = () => {
      if (!listType) return;
      output.push(`</${listType}>`);
      listType = "";
    };
    const flushParagraph = () => {
      if (!paragraph.length) return;
      output.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
      paragraph = [];
    };
    const openList = type => {
      flushParagraph();
      if (listType === type) return;
      closeList();
      listType = type;
      output.push(`<${type}>`);
    };

    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      const rawLine = lines[lineIndex];
      const line = rawLine.trim();
      if (!line) {
        flushParagraph();
        closeList();
        continue;
      }
      const headers = tableCells(line);
      const dividerCells = tableCells(lines[lineIndex + 1]);
      const alignments = tableAlignments(dividerCells);
      if (headers && alignments && headers.length === alignments.length) {
        flushParagraph();
        closeList();
        const rows = [];
        let rowIndex = lineIndex + 2;
        while (rowIndex < lines.length) {
          const cells = tableCells(lines[rowIndex]);
          if (!cells || cells.length !== headers.length) break;
          rows.push(cells);
          rowIndex += 1;
        }
        output.push(renderTable(headers, alignments, rows));
        lineIndex = rowIndex - 1;
        continue;
      }
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        closeList();
        const level = Math.min(heading[1].length + 2, 5);
        output.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        continue;
      }
      const unordered = line.match(/^[-*]\s+(.+)$/);
      if (unordered) {
        openList("ul");
        output.push(`<li>${renderInline(unordered[1])}</li>`);
        continue;
      }
      const ordered = line.match(/^\d+[.)]\s+(.+)$/);
      if (ordered) {
        openList("ol");
        output.push(`<li>${renderInline(ordered[1])}</li>`);
        continue;
      }
      const quote = line.match(/^>\s?(.+)$/);
      if (quote) {
        flushParagraph();
        closeList();
        output.push(`<blockquote>${renderInline(quote[1])}</blockquote>`);
        continue;
      }
      closeList();
      paragraph.push(line);
    }
    flushParagraph();
    closeList();
    return output.join("");
  }

  function knownResultIds(values, allowedValues, maximum = 8) {
    const allowed = new Set(
      Array.isArray(allowedValues) ? allowedValues.map(String) : [],
    );
    const ids = [];
    for (const value of Array.isArray(values) ? values : []) {
      const id = String(value);
      if (!allowed.has(id) || ids.includes(id)) continue;
      ids.push(id);
      if (ids.length >= maximum) break;
    }
    return ids;
  }

  function focusActionLabel(count) {
    const total = Number.isFinite(Number(count))
      ? Math.max(0, Math.floor(Number(count)))
      : 0;
    if (!total) return "";
    return total === 1
      ? "Narrow results to this opportunity"
      : `Narrow results to these ${total} opportunities`;
  }

  async function copyText(value, { clipboard, documentRef } = {}) {
    const text = String(value || "").trim();
    if (!text) return false;
    const targetClipboard = clipboard || globalThis.navigator?.clipboard;
    if (typeof targetClipboard?.writeText === "function") {
      try {
        await targetClipboard.writeText(text);
        return true;
      } catch {
        // Fall through to the bounded legacy copy path.
      }
    }
    const targetDocument = documentRef || globalThis.document;
    if (!targetDocument?.body || typeof targetDocument.execCommand !== "function") return false;
    const textarea = targetDocument.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    targetDocument.body.append(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = targetDocument.execCommand("copy") === true;
    } catch {
      copied = false;
    } finally {
      textarea.remove();
    }
    return copied;
  }

  // Remove conversational scaffolding, keeping scientific modifiers and identifiers.
  function retrievalQuery(question) {
    const filler = new Set("a an the and or for to of in on with at by from about into is are was were be been being do does did can could would should will may might i we you me my our your it its they their them this that these those what which who when where why how please find search show give list name tell suggest recommend compare explain describe discuss opportunities opportunity funding funded funds fund grants grant calls call programs program options option results result matches match fit fits best good few some any more other available current catalog full together pursue suitable relevant relate related help need want looking look ones instead details detail additional support supports supported".split(" "));
    const facts = new Set("deadline deadlines dates date eligibility eligible requirements requirement amounts amount budget budgets award awards duration durations contact contacts officer officers submission submissions apply applying cited cited source sources evidence verify verification stage stages actually open closed forecasted project projects".split(" "));
    const scopedQuestion = String(question || "")
      .replace(/\bcannot\b|\b[\p{L}]+n['’]t\b/giu, "not")
      .replace(/\b([\p{L}]+)['’](?:s|re|ve|ll|d)\b/giu, "$1")
      .replace(/^\s*(?:please\s+)?(?:(?:new|different|another|unrelated)\s+(?:topic|search)|(?:switch|change)\s+(?:the\s+)?topics?|start\s+over)\s*[:,.;-]?\s*/i, "");
    const tokens = scopedQuestion.match(/[\p{L}\p{N}]+(?:[-/][\p{L}\p{N}]+)*/gu) || [];
    const substantive = tokens.filter(word => /^[A-Z]{2,}$/.test(word) || (!filler.has(word.toLowerCase()) && !facts.has(word.toLowerCase())));
    return substantive.join(" ").slice(0, 500);
  }

  function isResultFollowUp(question) {
    const text = String(question || "").toLowerCase();
    // An explicit change of topic takes precedence over references to the old set.
    if (/\b(?:new|different|another|unrelated)\s+(?:topic|search)\b|\b(?:switch|change)\s+(?:the\s+)?topics?\b|\bstart\s+over\b|\binstead(?:\s+of\s+(?:those|these|them))?[,\s]+(?:find|search|look|show)\b|\b(?:find|search)\b.*\binstead\b/.test(text)) return false;
    if (/\b(?:those|these|them|their)\b|\b(?:this|that|previous|last|same)\s+(?:opportunit(?:y|ies)|calls?|grants?|programs?|awards?|options?|results?|set|comparison|answer)\b|\b(?:mentioned|listed|shown|discussed|compared)\s+(?:above|earlier|previously)\b/.test(text)
      || /\b(?:which|this|that|either|each)\s+one\b(?!-)|\b(?:does|is|can|will|would|could|should)\s+(?:(?:either|each|any)\s+)?one\b(?!-)/.test(text)
      || /\b(?:it|its|It|Its)\b/.test(String(question || ""))) return true;
    const query = retrievalQuery(question);
    if (!query) return true;
    // Date and amount qualifiers do not turn a factual comparison into a new topic.
    const qualifiers = new Set("not must shall ought dare am has have had after before since until through between during over under below above least most than greater less more fewer minimum maximum min max up next last first earliest latest soon sooner later still already remain remaining within due close closes closing start starts starting end ends ending offer offers provide provides exceed exceeds exceeding year years month months week weeks day days annually annual per total dollars usd eur gbp thousand million billion january february march april may june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec".split(" "));
    const numericUnits = new Set("usd eur gbp january february march april may june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec".split(" "));
    return query.split(/\s+/).every(word => {
      // Uppercase topical abbreviations (for example AM or DARE) are not verbs.
      if (/^[A-Z]{2,}$/.test(word) && !(numericUnits.has(word.toLowerCase()) && /\d/.test(query))) return false;
      return qualifiers.has(word.toLowerCase()) || /^\d+(?:[-/]\d+)*(?:k|m|b)?$/i.test(word);
    });
  }

  function evidenceExcerpt(text, query, maximum = 1600) {
    const source = String(text || "");
    if (source.length <= maximum) return source;
    const terms = retrievalQuery(query).toLowerCase().split(/\s+/).filter(term => term.length > 2);
    let best = 0, bestScore = 0;
    for (let start = 0; start < source.length; start += Math.floor(maximum / 2)) {
      const window = source.slice(start, start + maximum).toLowerCase();
      const score = terms.reduce((sum, term) => sum + (window.includes(term) ? 1 : 0), 0);
      if (score > bestScore) { best = start; bestScore = score; }
    }
    return `${best ? "…" : ""}${source.slice(best, best + maximum)}${best + maximum < source.length ? "…" : ""}`;
  }

  function resolveEvidenceLinks(text, citations) {
    const known = new Map((citations || []).map(item => [item.evidence_id, item]));
    return String(text || "").replace(/\[([^\]\n]+)\]\(([^\s)]+)\)/g, (original, label, id) => {
      const citation = known.get(id);
      const url = citation && safeUrl(citation.url);
      return url ? `[Official notice](${url})` : original;
    });
  }

  function resultScopeSummary(count, limit) {
    const first = Math.min(count, limit);
    const comparison = count > limit ? `the first ${first} results in the current order` : `all ${count} results`;
    return `Topic questions search all ${count.toLocaleString()} results and select up to ${limit}. General comparisons start with ${comparison}. Ask about those results to keep the previous answer’s records, or name a new topic to search again.`;
  }

  function resultContextLabel(mode, count, total) {
    if (mode === "initial_comparison") return count < total
      ? `Comparison of the first ${count} of ${total} results in the current order; the other ${total - count} results are outside this comparison`
      : `Comparison of all ${total} current results`;
    if (mode === "connected_follow_up") return `Comparison of ${count} opportunities from the previous answer, within ${total} currently eligible results`;
    if (mode === "focused_opportunity") return "Single connected opportunity";
    return `${count} question-relevant records selected from ${total} eligible results`;
  }

  globalThis.FUNDING_CHAT_UI = Object.freeze({
    retrievalQuery,
    isResultFollowUp,
    evidenceExcerpt,
    resolveEvidenceLinks,
    resultScopeSummary,
    resultContextLabel,
    renderRichText,
    knownResultIds,
    focusActionLabel,
    copyText,
  });
})();
