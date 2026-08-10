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

  globalThis.FUNDING_CHAT_UI = Object.freeze({
    renderRichText,
    knownResultIds,
    focusActionLabel,
  });
})();
