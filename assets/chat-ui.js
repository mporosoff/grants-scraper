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

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        flushParagraph();
        closeList();
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

  globalThis.FUNDING_CHAT_UI = Object.freeze({
    renderRichText,
    knownResultIds,
  });
})();
